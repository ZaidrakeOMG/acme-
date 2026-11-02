"""Integración con ERPs externos (§6.6): configuración del adaptador y de las columnas, bandeja de eventos y exportación
universal por período con descarga en Excel y XML. P09."""
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from core.dependencias import DB, Actor, requiere_rol
from core.errors import prohibido
from models.base import Rol
from models.costos import AdaptadorERP, EstadoEventoERP
from models.inventario import FormatoPoliza
from schemas.comun import RESPUESTAS_ERROR
from schemas.costos import ErpConfigEntrada, ErpConfigSalida, EventoERPSalida, ExportacionEntrada, ExportacionSalida
from services import auditoria
from services.erp import base as erp_base, eventos as erp_eventos, exportacion as erp_exportacion

router = APIRouter(prefix="/api/erp", tags=["Integración ERP"], responses=RESPUESTAS_ERROR)
TODOS = requiere_rol(*Rol)
ADAPTADORES = [
    {"clave": AdaptadorERP.ninguno.value, "nombre": "Sin adaptador (exportación universal)", "fase": 1},
    {"clave": AdaptadorERP.contpaqi.value, "nombre": "CONTPAQi (XML de importación / ODBC)", "fase": 2},
    {"clave": AdaptadorERP.microsip.value, "nombre": "Microsip (API REST + CSV)", "fase": 2},
]


def _prestador(actor: Actor, prestador_id: UUID | None) -> UUID:
    if prestador_id and actor.es_superadmin:
        return prestador_id
    if actor.prestador_id is None:
        raise prohibido("Solo los usuarios del prestador configuran la integración ERP")
    return actor.prestador_id


@router.get("/configuracion", response_model=ErpConfigSalida, summary="Adaptador, columnas del Excel, cuentas contables y centros de costos")
async def configuracion(db: DB, actor: Actor = Depends(TODOS), prestador_id: UUID | None = None):
    c = await erp_eventos.configuracion(db, _prestador(actor, prestador_id), crear=True)
    await db.commit()
    return ErpConfigSalida(**{**auditoria.instantanea(c), "id": c.id, "prestador_id": c.prestador_id, "created_at": c.created_at,
                              "updated_at": c.updated_at, "adaptadores_disponibles": ADAPTADORES})


@router.put("/configuracion", response_model=ErpConfigSalida, summary="Guardar configuración (Admin prestador)")
async def guardar(datos: ErpConfigEntrada, request: Request, db: DB, actor: Actor = Depends(TODOS), prestador_id: UUID | None = None):
    if not actor.es_superadmin and actor.rol != Rol.admin_prestador:
        raise prohibido("Solo el Admin prestador configura la integración ERP")
    pid = _prestador(actor, prestador_id)
    c = await erp_eventos.configuracion(db, pid, crear=True)
    antes = auditoria.instantanea(c)
    for k, v in datos.model_dump(exclude_unset=True, exclude_none=True).items():
        setattr(c, k, v)
    await db.flush()
    await auditoria.registrar_actor(db, actor, "erp.configuracion", request, prestador_id=pid, recurso_tipo="erp_configuracion", recurso_id=c.id,
                                    antes=antes, despues=auditoria.instantanea(c))
    await db.commit()
    return ErpConfigSalida(**{**auditoria.instantanea(c), "id": c.id, "prestador_id": c.prestador_id, "created_at": c.created_at,
                              "updated_at": c.updated_at, "adaptadores_disponibles": ADAPTADORES})


@router.get("/eventos", response_model=list[EventoERPSalida], summary="Bandeja de eventos pendientes con su estado")
async def eventos(db: DB, actor: Actor = Depends(TODOS), estado: EstadoEventoERP | None = None, limite: int = 100):
    return await erp_exportacion.listar_eventos(db, actor, estado=estado, limite=limite)


@router.post("/eventos/{evento_id}/procesar", response_model=EventoERPSalida, summary="Procesar con el adaptador configurado (stub: queda omitido en Fase 1)")
async def procesar(evento_id: UUID, db: DB, actor: Actor = Depends(TODOS)):
    from core.errors import no_encontrado
    from models.costos import ErpEventoPendiente

    if not actor.es_superadmin and actor.rol != Rol.admin_prestador:
        raise prohibido("Solo el Admin prestador procesa los eventos del ERP")
    e = await db.get(ErpEventoPendiente, evento_id)
    if e is None or (not actor.es_superadmin and e.prestador_id != actor.prestador_id):
        raise no_encontrado("Evento del ERP")
    cfg = await erp_eventos.configuracion(db, e.prestador_id, crear=True)
    await erp_base.procesar(db, e, cfg.adaptador)
    await db.commit()
    return e


@router.get("/exportaciones", response_model=list[ExportacionSalida], summary="Historial de exportaciones")
async def exportaciones(db: DB, actor: Actor = Depends(TODOS)):
    return [ExportacionSalida(**{**auditoria.instantanea(e), "id": e.id, "prestador_id": e.prestador_id, "generado_por": e.generado_por,
                                 "created_at": e.created_at, "updated_at": e.updated_at, "archivo_disponible": bool(e.archivo_key),
                                 "xml_disponible": bool(e.archivo_xml_key)}) for e in await erp_exportacion.listar_exportaciones(db, actor)]


@router.post("/exportaciones", response_model=ExportacionSalida, status_code=201, summary="Exportación universal del período (XML de pólizas + Excel)")
async def exportar(datos: ExportacionEntrada, request: Request, db: DB, actor: Actor = Depends(TODOS)):
    e = await erp_exportacion.exportar(db, actor, desde=datos.desde, hasta=datos.hasta, formato=FormatoPoliza.excel,
                                       prestador_id=datos.prestador_id, request=request)
    await db.commit()
    return ExportacionSalida(**{**auditoria.instantanea(e), "id": e.id, "prestador_id": e.prestador_id, "generado_por": e.generado_por,
                                "created_at": e.created_at, "updated_at": e.updated_at, "archivo_disponible": bool(e.archivo_key),
                                "xml_disponible": bool(e.archivo_xml_key)})


@router.get("/exportaciones/{exportacion_id}/archivo", summary="Descargar la exportación en Excel o XML")
async def archivo(exportacion_id: UUID, db: DB, actor: Actor = Depends(TODOS), formato: str = "xlsx"):
    datos, mime, nombre = await erp_exportacion.archivo(db, actor, exportacion_id, formato)
    return Response(datos, media_type=mime, headers={"Content-Disposition": f'attachment; filename="{nombre}"'})
