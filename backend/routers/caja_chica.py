"""Caja chica (§6.4 Tipo C y §6.5): fondos por técnico, captura del gasto con foto, aprobación en un toque y pólizas de
reposición en Excel y XML. El OCR y la validación CFDI son `stub` de Fase 1. P09."""
import base64
from datetime import date
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from core.dependencias import DB, Actor, requiere_rol
from models.base import Rol
from models.inventario import EstadoGastoCajaChica
from schemas.comun import RESPUESTAS_ERROR
from schemas.inventario import (
    FondoEntrada, FondoSalida, GastoAprobadoSalida, GastoEntrada, GastoSalida, PolizaSalida, RazonEntrada, ReponerFondoEntrada, ResultadoOCR,
)
from services import caja_chica_service as svc
from services import ocr

router = APIRouter(prefix="/api/caja-chica", tags=["Caja chica"], responses=RESPUESTAS_ERROR)
TODOS = requiere_rol(*Rol)


@router.get("/fondos", response_model=list[FondoSalida], summary="Fondos por técnico con saldo y gastos pendientes")
async def fondos(db: DB, actor: Actor = Depends(TODOS)):
    return await svc.listar_fondos(db, actor)


@router.post("/fondos", response_model=FondoSalida, status_code=201, summary="Autorizar fondo fijo a un técnico (Admin prestador)")
async def crear_fondo(datos: FondoEntrada, request: Request, db: DB, actor: Actor = Depends(TODOS)):
    f = await svc.crear_fondo(db, actor, tecnico_id=datos.tecnico_id, monto_inicial=datos.monto_inicial,
                              umbral_alerta_pct=datos.umbral_alerta_pct, request=request)
    await db.commit()
    return next(x for x in await svc.listar_fondos(db, actor) if x["id"] == f.id)


@router.post("/fondos/{fondo_id}/reponer", response_model=FondoSalida, summary="Reponer el fondo tras entregar la póliza (§6.5)")
async def reponer(fondo_id: UUID, datos: ReponerFondoEntrada, request: Request, db: DB, actor: Actor = Depends(TODOS)):
    from models.inventario import FondoCajaChica

    f = await db.get(FondoCajaChica, fondo_id)
    if f is None or (not actor.es_superadmin and f.prestador_id != actor.prestador_id):
        from core.errors import no_encontrado

        raise no_encontrado("Fondo de caja chica")
    await svc.reponer_fondo(db, actor, f, datos.monto, request)
    await db.commit()
    return next(x for x in await svc.listar_fondos(db, actor) if x["id"] == fondo_id)


@router.post("/ocr", response_model=ResultadoOCR, summary="Extracción OCR de la factura (stub de Fase 1)")
async def extraer(datos: dict[str, Any], db: DB, actor: Actor = Depends(TODOS)):  # noqa: ARG001
    contenido = base64.b64decode(datos.get("imagen_base64") or "") if datos.get("imagen_base64") else b""
    f = await ocr.extraer(contenido, datos.get("mime") or "image/jpeg")
    return ResultadoOCR(disponible=f.disponible, detalle=f.detalle, proveedor=f.proveedor, rfc_proveedor=f.rfc_proveedor, uuid_cfdi=f.uuid_cfdi,
                        descripcion=f.descripcion, numero_parte=f.numero_parte, subtotal=f.subtotal, iva=f.iva, total=f.total, campos_json=f.campos_json)


@router.get("/gastos", response_model=list[GastoSalida], summary="Gastos de caja chica (el técnico ve los suyos)")
async def gastos(db: DB, actor: Actor = Depends(TODOS), estado: EstadoGastoCajaChica | None = None, fondo_id: UUID | None = None,
                 folio_id: UUID | None = None, desde: date | None = None, hasta: date | None = None):
    return await svc.listar_gastos(db, actor, estado=estado, fondo_id=fondo_id, folio_id=folio_id, desde=desde, hasta=hasta)


@router.post("/gastos", response_model=GastoSalida, status_code=201, summary="Capturar el gasto con la foto de la factura (técnico, operable offline)")
async def capturar(datos: GastoEntrada, request: Request, db: DB, actor: Actor = Depends(TODOS)):
    g = await svc.capturar_gasto(db, actor, folio_id=datos.folio_id, proveedor=datos.proveedor, rfc_proveedor=datos.rfc_proveedor,
                                 uuid_cfdi=datos.uuid_cfdi, descripcion=datos.descripcion, numero_parte=datos.numero_parte, subtotal=datos.subtotal,
                                 iva=datos.iva, monto=datos.monto, articulo_id=datos.articulo_id, cantidad=datos.cantidad,
                                 imagen_base64=datos.imagen_base64, nombre_imagen=datos.nombre_imagen, mime=datos.mime, evidencia_id=datos.evidencia_id,
                                 centro_costos=datos.centro_costos, cuenta_contable=datos.cuenta_contable, momento=datos.timestamp_dispositivo,
                                 request=request)
    await db.commit()
    return (await svc.serializar(db, [g]))[0]


@router.get("/gastos/{gasto_id}/imagen", summary="Foto de la factura")
async def imagen(gasto_id: UUID, db: DB, actor: Actor = Depends(TODOS)):
    g = await svc.obtener_gasto(db, actor, gasto_id)
    datos, mime = await svc.imagen_de(db, actor, g)
    return Response(datos, media_type=mime)


@router.post("/gastos/{gasto_id}/aprobar", response_model=GastoAprobadoSalida, summary="Aprobar en un toque: refacción + inventario + gasto en una transacción")
async def aprobar(gasto_id: UUID, request: Request, db: DB, actor: Actor = Depends(TODOS)):
    g = await svc.obtener_gasto(db, actor, gasto_id)
    r = await svc.aprobar_gasto(db, actor, g, request)
    await db.commit()
    return GastoAprobadoSalida(gasto=(await svc.serializar(db, [g]))[0], refaccion_id=r["refaccion"].id if r["refaccion"] else None,
                               movimientos=r["movimientos"], saldo_fondo=r["saldo_fondo"])


@router.post("/gastos/{gasto_id}/rechazar", response_model=GastoSalida, summary="Rechazar con razón")
async def rechazar(gasto_id: UUID, datos: RazonEntrada, request: Request, db: DB, actor: Actor = Depends(TODOS)):
    g = await svc.obtener_gasto(db, actor, gasto_id)
    await svc.rechazar_gasto(db, actor, g, datos.razon, request)
    await db.commit()
    return (await svc.serializar(db, [g]))[0]


@router.get("/polizas", response_model=list[PolizaSalida], summary="Pólizas de reposición generadas al cierre de jornada")
async def polizas(db: DB, actor: Actor = Depends(TODOS)):
    from services import auditoria

    return [PolizaSalida(**{**auditoria.instantanea(p), "id": p.id, "prestador_id": p.prestador_id, "fondo_id": p.fondo_id, "generado_por": p.generado_por,
                            "created_at": p.created_at, "updated_at": p.updated_at, "archivo_disponible": bool(p.archivo_key),
                            "xml_disponible": bool(p.archivo_xml_key)}) for p in await svc.listar_polizas(db, actor)]


@router.post("/polizas", response_model=PolizaSalida | None, summary="Generar la póliza del día (también corre en la tarea de cierre de jornada)")
async def generar(request: Request, db: DB, actor: Actor = Depends(TODOS), fecha: date | None = None, fondo_id: UUID | None = None):
    from core.errors import prohibido
    from services import auditoria

    if not actor.es_superadmin and actor.rol not in svc.ADMINISTRAN:
        raise prohibido("Solo el Admin prestador genera la póliza de reposición")
    p = await svc.generar_poliza(db, actor, prestador_id=actor.prestador_id, fondo_id=fondo_id, fecha=fecha, request=request)
    await db.commit()
    if p is None:
        return None
    return PolizaSalida(**{**auditoria.instantanea(p), "id": p.id, "prestador_id": p.prestador_id, "fondo_id": p.fondo_id, "generado_por": p.generado_por,
                           "created_at": p.created_at, "updated_at": p.updated_at, "archivo_disponible": bool(p.archivo_key),
                           "xml_disponible": bool(p.archivo_xml_key)})


@router.get("/polizas/{poliza_id}/archivo", summary="Descargar la póliza en Excel (12 columnas de §6.5) o XML")
async def archivo(poliza_id: UUID, db: DB, actor: Actor = Depends(TODOS), formato: str = "xlsx"):
    datos, mime, nombre = await svc.archivo_poliza(db, actor, poliza_id, formato)
    return Response(datos, media_type=mime, headers={"Content-Disposition": f'attachment; filename="{nombre}"'})
