"""Clasificación de folios no críticos y calificación del Admin UN (§6.10.5). P07."""
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from core.dependencias import DB, Actor, requiere_rol
from models.base import Rol
from routers.catalogos_equipos import tenant_de
from schemas.comun import RESPUESTAS_ERROR
from schemas.minutas import CalificacionSalida, ClasificacionConfigEntrada, ClasificacionConfigSalida, ClasificacionSalida, ClasificarEntrada, PendienteClasificacion
from services import clasificacion_service
from services import folios_captura_service as folios

router = APIRouter(prefix="/api/clasificacion", tags=["Clasificación de folios no críticos"], responses=RESPUESTAS_ERROR)
TODOS = requiere_rol(*Rol)


@router.get("/configuracion", response_model=ClasificacionConfigSalida, summary="Configuración del tenant (severidades no críticas, plazo, puntos)")
async def configuracion(db: DB, actor: Actor = Depends(requiere_rol(Rol.superadmin, Rol.admin_empresa, Rol.admin_un, Rol.admin_prestador, Rol.despachador)), tenant_id: UUID | None = None):
    t = tenant_id if actor.es_superadmin or actor.tenant_id is None else actor.tenant_id
    c = await clasificacion_service.configuracion(db, t, crear=actor.rol in (Rol.superadmin, Rol.admin_empresa))
    if c is None:
        from core.errors import no_encontrado

        raise no_encontrado("Configuración de clasificación")
    await db.commit()
    return ClasificacionConfigSalida.model_validate(c)


@router.put("/configuracion", response_model=ClasificacionConfigSalida, summary="Guardar configuración (Admin empresa)")
async def guardar(datos: ClasificacionConfigEntrada, request: Request, db: DB, actor: Actor = Depends(requiere_rol(Rol.superadmin, Rol.admin_empresa)), tenant_id: UUID | None = None):
    c = await clasificacion_service.guardar_configuracion(db, actor, tenant_de(actor, tenant_id), datos.model_dump(exclude_unset=True), request)
    await db.commit()
    return ClasificacionConfigSalida.model_validate(c)


@router.get("/pendientes", response_model=list[PendienteClasificacion], summary="Folios no críticos pendientes de clasificar (sus UNs) con plazo restante")
async def pendientes(db: DB, actor: Actor = Depends(TODOS)):
    return [PendienteClasificacion(**p) for p in await clasificacion_service.pendientes(db, actor)]


@router.get("/calificaciones", response_model=list[CalificacionSalida], summary="Calificación por período del Admin UN (Admin empresa; el Admin UN ve la suya)")
async def calificaciones(db: DB, actor: Actor = Depends(TODOS), periodo: str | None = None):
    return [CalificacionSalida(**c) for c in await clasificacion_service.calificaciones(db, actor, periodo)]


@router.post("/calificaciones/calcular", response_model=list[CalificacionSalida], summary="Recalcular la calificación del período (manual)")
async def calcular(db: DB, actor: Actor = Depends(requiere_rol(Rol.superadmin, Rol.admin_empresa)), periodo: str | None = None, tenant_id: UUID | None = None):
    from datetime import date

    t = tenant_de(actor, tenant_id)
    await clasificacion_service.calificar(db, t, periodo or clasificacion_service.periodo_de(date.today()))
    await db.commit()
    return [CalificacionSalida(**c) for c in await clasificacion_service.calificaciones(db, actor, periodo)]


@router.post("/{folio_id}", response_model=ClasificacionSalida, status_code=201, summary="Clasificar un folio con una de las cinco opciones",
             description="presupuesto → Por presupuesto; reprogramacion (pide fecha tentativa) → Reprogramación; cotizacion → Cotizaciones y aviso al prestador; "
                         "autorizado → el folio pasa a Autorizado y el SLA corre desde ese momento; seguimiento_interno → Seguimiento interno.")
async def clasificar(folio_id: UUID, datos: ClasificarEntrada, request: Request, db: DB, actor: Actor = Depends(TODOS)):
    folio = await folios.obtener(db, actor, folio_id)
    fc = await clasificacion_service.clasificar(db, actor, folio, datos.opcion, fecha_tentativa=datos.fecha_tentativa, notas=datos.notas, request=request)
    await db.commit()
    return ClasificacionSalida.model_validate(fc)
