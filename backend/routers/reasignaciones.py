"""Reasignación forzada (§6.8.2): candidatos, ejecución con restricciones y razones, historial, reporte y catálogo de razones."""
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from core.dependencias import DB, Actor, requiere_rol
from core.errors import no_encontrado
from models.base import Rol
from models.preventivos import RazonReasignacion
from routers.catalogos_tecnicos import prestador_de
from schemas.comun import RESPUESTAS_ERROR
from schemas.preventivos import CandidatoSalida, RazonEntrada, RazonSalida, ReasignacionSalida, ReasignarEntrada, ReporteReasignaciones
from services import auditoria, reasignacion_service
from services import folios_captura_service as folios

router = APIRouter(tags=["Reasignaciones"], responses=RESPUESTAS_ERROR)
TODOS = requiere_rol(*Rol)
ADMIN_PRESTADOR = requiere_rol(Rol.superadmin, Rol.admin_prestador)


@router.get("/api/folios/{folio_id}/reasignacion/candidatos", response_model=list[CandidatoSalida], summary="Técnicos candidatos",
            description="Con indicador de habilidad requerida (restricción dura), carga del día y advertencia de refacción (gancho P09).")
async def candidatos(folio_id: UUID, db: DB, actor: Actor = Depends(TODOS)):
    folio = await folios.obtener(db, actor, folio_id)
    return [CandidatoSalida(**c) for c in await reasignacion_service.candidatos(db, actor, folio)]


@router.post("/api/folios/{folio_id}/reasignar", response_model=ReasignacionSalida, status_code=201, summary="Reasignación forzada",
             description="No en ejecución; técnico con habilidad certificada (403 salvo permiso `asignar_tecnico_sin_habilidad` con razón); advertencias "
                         "(refacción) exigen `confirmar_advertencias`; razón del catálogo obligatoria. Ejecuta reasignado → asignado y avisa por chat y push.")
async def reasignar(folio_id: UUID, datos: ReasignarEntrada, request: Request, db: DB, actor: Actor = Depends(TODOS)):
    folio = await folios.obtener(db, actor, folio_id)
    r = await reasignacion_service.reasignar(db, actor, folio, datos.tecnico_destino_id, datos.razon_id, datos.comentario, datos.confirmar_advertencias,
                                             datos.razon_sin_habilidad, request)
    await db.commit()
    return next(ReasignacionSalida(**x) for x in await reasignacion_service.historial_folio(db, folio.id) if x["id"] == r.id)


@router.get("/api/folios/{folio_id}/reasignaciones", response_model=list[ReasignacionSalida], summary="Historial de reasignaciones del folio")
async def historial(folio_id: UUID, db: DB, actor: Actor = Depends(TODOS)):
    folio = await folios.obtener(db, actor, folio_id)
    return [ReasignacionSalida(**x) for x in await reasignacion_service.historial_folio(db, folio.id)]


@router.get("/api/reasignaciones/reporte", response_model=ReporteReasignaciones, summary="Principales causas por período (§4.1)")
async def reporte(db: DB, actor: Actor = Depends(requiere_rol(Rol.superadmin, Rol.admin_prestador, Rol.despachador, Rol.mesa_control, Rol.direccion_prestador,
                                                              Rol.supervisor_prestador, Rol.admin_empresa)),
                  desde: date | None = None, hasta: date | None = None, tenant_id: UUID | None = None):
    return ReporteReasignaciones(**await reasignacion_service.reporte(db, actor, desde, hasta, tenant_id))


@router.get("/api/reasignaciones/razones", response_model=list[RazonSalida], summary="Catálogo de razones del prestador")
async def razones(db: DB, actor: Actor = Depends(requiere_rol(Rol.superadmin, Rol.admin_prestador, Rol.despachador, Rol.mesa_control)),
                  prestador_id: UUID | None = None, incluir_inactivas: bool = False):
    return [RazonSalida.model_validate(r) for r in await reasignacion_service.razones(db, prestador_de(actor, prestador_id), not incluir_inactivas)]


@router.post("/api/reasignaciones/razones", response_model=RazonSalida, status_code=201, summary="Crear razón (Admin prestador)")
async def crear_razon(datos: RazonEntrada, request: Request, db: DB, actor: Actor = Depends(ADMIN_PRESTADOR), prestador_id: UUID | None = None):
    p = prestador_de(actor, prestador_id)
    r = RazonReasignacion(prestador_id=p, **datos.model_dump())
    db.add(r)
    await db.flush()
    await auditoria.registrar_actor(db, actor, "reasignaciones.razon_alta", request, prestador_id=p, recurso_tipo="razon_reasignacion", recurso_id=r.id, despues=datos.model_dump())
    await db.commit()
    return RazonSalida.model_validate(r)


@router.patch("/api/reasignaciones/razones/{razon_id}", response_model=RazonSalida, summary="Modificar razón")
async def editar_razon(razon_id: UUID, datos: RazonEntrada, request: Request, db: DB, actor: Actor = Depends(ADMIN_PRESTADOR)):
    r = await db.get(RazonReasignacion, razon_id)
    if r is None or (not actor.es_superadmin and r.prestador_id != actor.prestador_id):
        raise no_encontrado("Razón")
    antes = auditoria.instantanea(r)
    for k, v in datos.model_dump().items():
        setattr(r, k, v)
    await db.flush()
    await auditoria.registrar_actor(db, actor, "reasignaciones.razon_modificacion", request, prestador_id=r.prestador_id, recurso_tipo="razon_reasignacion", recurso_id=r.id,
                                    antes=antes, despues=auditoria.instantanea(r))
    await db.commit()
    return RazonSalida.model_validate(r)
