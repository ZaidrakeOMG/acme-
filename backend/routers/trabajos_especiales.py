"""Trabajos especiales (§6.10.6): creación, validación del cliente por botón, programación, ejecución, cierre, cancelación,
cotización retroactiva, evidencias y reporte. P08."""
import io
from datetime import date
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response

from core.dependencias import DB, Actor, requiere_rol
from models.base import Rol
from models.trabajos_especiales import EstadoTrabajoEspecial
from schemas.comun import RESPUESTAS_ERROR
from schemas.minutas import CotizacionSalida
from schemas.trabajos_especiales import (
    CambioEstadoTEEntrada, CotizacionRetroactivaEntrada, EnviarClienteEntrada, EvidenciaTEEntrada, NotasTEEntrada, ProgramarEntrada, ReporteTE, RespuestaClienteEntrada,
    TrabajoEspecialDetalle, TrabajoEspecialEntrada, TrabajoEspecialSalida,
)
from services import trabajos_especiales_service as svc

router = APIRouter(prefix="/api/trabajos-especiales", tags=["Trabajos especiales"], responses=RESPUESTAS_ERROR)
TODOS = requiere_rol(*Rol)
E = EstadoTrabajoEspecial


async def _salida(db, actor, te) -> dict[str, Any]:
    return TrabajoEspecialSalida(**(await svc.serializar(db, actor, [te]))[0]).model_dump()


async def _detalle(db, actor, te) -> dict[str, Any]:
    return TrabajoEspecialDetalle(**await svc.detalle(db, actor, te)).model_dump()


@router.get("", response_model=list[TrabajoEspecialSalida], summary="Listado filtrable (tenant, UN, estado, urgencia, período)")
async def listar(db: DB, actor: Actor = Depends(TODOS), tenant_id: UUID | None = None, un_id: UUID | None = None, estado: EstadoTrabajoEspecial | None = None,
                 urgencia: bool | None = None, desde: date | None = None, hasta: date | None = None, por_validar: bool = False):
    tes = await svc.listar(db, actor, {"tenant_id": tenant_id, "un_id": un_id, "estado": estado, "urgencia": urgencia, "desde": desde, "hasta": hasta, "por_validar": por_validar})
    return [TrabajoEspecialSalida(**d) for d in await svc.serializar(db, actor, tes)]


@router.get("/reporte", response_model=ReporteTE, summary="Conteo por estado, tiempo promedio por etapa, % de urgencias y monto total")
async def reporte(db: DB, actor: Actor = Depends(TODOS), desde: date | None = None, hasta: date | None = None, tenant_id: UUID | None = None):
    return ReporteTE(**await svc.reporte(db, actor, desde, hasta, tenant_id))


@router.get("/reporte.xlsx", summary="Reporte de trabajos especiales en Excel")
async def reporte_excel(db: DB, actor: Actor = Depends(TODOS), desde: date | None = None, hasta: date | None = None, tenant_id: UUID | None = None):
    from openpyxl import Workbook

    r = await svc.reporte(db, actor, desde, hasta, tenant_id)
    wb = Workbook()
    ws = wb.active
    ws.title = "Trabajos especiales"
    ws.append(["Reporte de trabajos especiales", f"{desde or ''} – {hasta or ''}"])
    ws.append(["Total", r["total"], "Urgencias", r["urgencias"], "% urgencias", r["porcentaje_urgencias"], "Monto total", float(r["monto_total"])])
    ws.append([])
    ws.append(["Estado", "Registros"])
    for k, v in r["por_estado"].items():
        ws.append([svc.NOMBRES_ESTADO[E(k)], v])
    ws.append([])
    ws.append(["Etapa", "Días promedio"])
    for k, v in r["tiempo_promedio_etapas_dias"].items():
        ws.append([k, v])
    buf = io.BytesIO()
    wb.save(buf)
    return Response(buf.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": 'attachment; filename="trabajos-especiales.xlsx"'})


@router.get("/reporte.pdf", summary="Reporte de trabajos especiales en PDF")
async def reporte_pdf(db: DB, actor: Actor = Depends(TODOS), desde: date | None = None, hasta: date | None = None, tenant_id: UUID | None = None):
    import html as _html

    from services import pdf as pdf_svc

    r = await svc.reporte(db, actor, desde, hasta, tenant_id)
    e = _html.escape
    filas = "".join(f"<tr><td>{e(svc.NOMBRES_ESTADO[E(k)])}</td><td>{v}</td></tr>" for k, v in r["por_estado"].items())
    etapas = "".join(f"<li>{e(k)}: {v if v is not None else '—'} días</li>" for k, v in r["tiempo_promedio_etapas_dias"].items())
    html = f"""<html><body><h1>Reporte de trabajos especiales</h1><p>Período: {desde or '—'} a {hasta or '—'}</p>
    <p>Total {r['total']} · urgencias {r['urgencias']} ({r['porcentaje_urgencias']}%) · monto total ${r['monto_total']}</p>
    <h2>Por estado</h2><table><tr><th>Estado</th><th>Registros</th></tr>{filas}</table>
    <h2>Tiempo promedio por etapa</h2><ul>{etapas}</ul></body></html>"""
    return Response(pdf_svc.html_a_pdf(html), media_type="application/pdf", headers={"Content-Disposition": 'attachment; filename="trabajos-especiales.pdf"'})


@router.post("", response_model=TrabajoEspecialSalida, status_code=201, summary="Crear TE (prestador) o TE de urgencia (Admin empresa / Admin UN)")
async def crear(datos: TrabajoEspecialEntrada, request: Request, db: DB, actor: Actor = Depends(TODOS)):
    te = await svc.crear(db, actor, tenant_id=datos.tenant_id, un_id=datos.un_id, equipo_id=datos.equipo_id, descripcion=datos.descripcion, detalle=datos.detalle, monto=datos.monto,
                         formulario_id=datos.formulario_id, urgencia=datos.urgencia, request=request)
    await db.commit()
    return await _salida(db, actor, te)


@router.get("/{te_id}", response_model=TrabajoEspecialDetalle, summary="Detalle con línea de tiempo, versiones enviadas, respuestas del cliente, evidencias y acciones")
async def detalle(te_id: UUID, db: DB, actor: Actor = Depends(TODOS)):
    return await _detalle(db, actor, await svc.obtener(db, actor, te_id))


@router.post("/{te_id}/enviar", response_model=TrabajoEspecialDetalle, summary="Enviar al cliente para validación (o reenviar tras rechazo: version_enviada + 1)")
async def enviar(te_id: UUID, datos: EnviarClienteEntrada, request: Request, db: DB, actor: Actor = Depends(TODOS)):
    te = await svc.obtener(db, actor, te_id)
    await svc.cambiar_estado_te(db, actor, te, E.enviado_cliente, datos.notas, request, descripcion=datos.descripcion, monto=datos.monto, detalle=datos.detalle)
    await db.commit()
    return await _detalle(db, actor, te)


@router.post("/{te_id}/aceptar", response_model=TrabajoEspecialDetalle, summary="Botón de aceptación del cliente (§6.10.6)")
async def aceptar(te_id: UUID, datos: RespuestaClienteEntrada, request: Request, db: DB, actor: Actor = Depends(TODOS)):
    te = await svc.obtener(db, actor, te_id)
    await svc.cambiar_estado_te(db, actor, te, E.aceptado, datos.comentario, request, canal=datos.canal)
    await db.commit()
    return await _detalle(db, actor, te)


@router.post("/{te_id}/rechazar", response_model=TrabajoEspecialDetalle, summary="Botón de rechazo del cliente con comentario obligatorio")
async def rechazar(te_id: UUID, datos: RespuestaClienteEntrada, request: Request, db: DB, actor: Actor = Depends(TODOS)):
    te = await svc.obtener(db, actor, te_id)
    await svc.cambiar_estado_te(db, actor, te, E.rechazado, datos.comentario, request, canal=datos.canal)
    await db.commit()
    return await _detalle(db, actor, te)


@router.post("/{te_id}/programar", response_model=TrabajoEspecialDetalle, summary="Despachador asigna fecha y técnicos; crea el folio operativo y confirma la fecha al cliente")
async def programar(te_id: UUID, datos: ProgramarEntrada, request: Request, db: DB, actor: Actor = Depends(TODOS)):
    te = await svc.obtener(db, actor, te_id)
    await svc.cambiar_estado_te(db, actor, te, E.programado, datos.notas, request, fecha_programada=datos.fecha_programada, tecnico_ids=datos.tecnico_ids,
                                tecnico_responsable_id=datos.tecnico_responsable_id)
    await db.commit()
    return await _detalle(db, actor, te)


@router.post("/{te_id}/iniciar", response_model=TrabajoEspecialDetalle, summary="Técnico responsable inicia la ejecución (sincroniza el folio operativo)")
async def iniciar(te_id: UUID, datos: NotasTEEntrada, request: Request, db: DB, actor: Actor = Depends(TODOS)):
    te = await svc.obtener(db, actor, te_id)
    await svc.cambiar_estado_te(db, actor, te, E.en_ejecucion, datos.notas, request)
    await db.commit()
    return await _detalle(db, actor, te)


@router.post("/{te_id}/cerrar", response_model=TrabajoEspecialDetalle, summary="Cierre: exige formulario del TE, evidencia fotográfica de cierre y firma del cliente")
async def cerrar(te_id: UUID, datos: NotasTEEntrada, request: Request, db: DB, actor: Actor = Depends(TODOS)):
    te = await svc.obtener(db, actor, te_id)
    await svc.cambiar_estado_te(db, actor, te, E.cerrado, datos.notas, request)
    await db.commit()
    return await _detalle(db, actor, te)


@router.post("/{te_id}/cancelar", response_model=TrabajoEspecialDetalle, summary="Cancelar con razón documentada")
async def cancelar(te_id: UUID, datos: NotasTEEntrada, request: Request, db: DB, actor: Actor = Depends(TODOS)):
    te = await svc.obtener(db, actor, te_id)
    await svc.cambiar_estado_te(db, actor, te, E.cancelado, datos.notas, request)
    await db.commit()
    return await _detalle(db, actor, te)


@router.post("/{te_id}/estado", response_model=TrabajoEspecialDetalle, summary="Cambio de estado genérico (Kanban): valida rol, campos y razón")
async def cambiar_estado(te_id: UUID, datos: CambioEstadoTEEntrada, request: Request, db: DB, actor: Actor = Depends(TODOS)):
    te = await svc.obtener(db, actor, te_id)
    await svc.cambiar_estado_te(db, actor, te, datos.estado, datos.notas, request, fecha_programada=datos.fecha_programada, tecnico_ids=datos.tecnico_ids,
                                tecnico_responsable_id=datos.tecnico_responsable_id, descripcion=datos.descripcion, monto=datos.monto, detalle=datos.detalle, canal=datos.canal)
    await db.commit()
    return await _detalle(db, actor, te)


@router.post("/{te_id}/evidencias", status_code=201, summary="Evidencia de avance, cierre, firma o documento")
async def evidencia(te_id: UUID, datos: EvidenciaTEEntrada, request: Request, db: DB, actor: Actor = Depends(TODOS)) -> dict[str, Any]:
    te = await svc.obtener(db, actor, te_id)
    e = await svc.agregar_evidencia(db, actor, te, tipo=datos.tipo, evidencia_id=datos.evidencia_id, contenido_base64=datos.contenido_base64, nombre=datos.nombre, mime=datos.mime,
                                    geolat=datos.geolat, geolng=datos.geolng, request=request)
    await db.commit()
    return {"id": e.id, "tipo": e.tipo.value, "archivo_key": e.archivo_key, "evidencia_id": e.evidencia_id, "timestamp": e.timestamp}


@router.post("/{te_id}/cotizacion-retroactiva", response_model=CotizacionSalida, status_code=201, summary="Cotización retroactiva del TE de urgencia (vinculada en ambas direcciones)")
async def cotizacion_retroactiva(te_id: UUID, datos: CotizacionRetroactivaEntrada, request: Request, db: DB, actor: Actor = Depends(TODOS)):
    from models.folios import ModuloDestino
    from routers.seguimiento import _serializar

    te = await svc.obtener(db, actor, te_id)
    c = await svc.cotizacion_retroactiva(db, actor, te, descripcion=datos.descripcion, monto=datos.monto, detalle=datos.detalle, request=request)
    await db.commit()
    return CotizacionSalida(**(await _serializar(db, actor, ModuloDestino.cotizaciones, [c]))[0])


__all__ = ["router", "Query"]
