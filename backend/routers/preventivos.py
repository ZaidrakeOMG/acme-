"""Planes de mantenimiento (§6.9.1), calendario de preventivos (§7.6), generación y ciclo de vida con autorizaciones formales."""
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from core.dependencias import DB, Actor, ActorActual, requiere_rol
from core.errors import ErrorAPI, no_encontrado
from models.base import Rol
from models.preventivos import AutorizacionPreventivo, EstadoAutorizacion, EstadoPreventivo, PreventivoCalendario, TipoAutorizacionPreventivo
from schemas.comun import RESPUESTAS_ERROR, Mensaje
from schemas.preventivos import (
    AsignarEquipoEntrada, AutorizacionSalida, CalendarioCambios, CalendarioEntrada, CalendarioSalida, EquipoPlanSalida, PlanCambios, PlanEntrada,
    PlanSalida, PublicacionSalida, ResolverEntrada, SolicitudEntrada, TareasMaterialesSalida,
)
from services import planes_service, preventivos_service
from services import folios_captura_service as folios

router = APIRouter(tags=["Preventivos y planes"], responses=RESPUESTAS_ERROR)

TODOS = requiere_rol(*Rol)


async def _plan_salida(db, plan) -> PlanSalida:
    return PlanSalida(**await planes_service.detalle(db, plan))


# ------------------------------------------------------------------ planes

@router.get("/api/planes", response_model=list[PlanSalida], summary="Planes de mantenimiento",
            description="Admin prestador y Despachador administran; Admin empresa y Admin UN consultan los planes de sus prestadores.")
async def listar_planes(db: DB, actor: Actor = Depends(TODOS), prestador_id: UUID | None = None, tipo_equipo_id: UUID | None = None, solo_activos: bool = False):
    if actor.rol not in planes_service.CONSULTAN:
        raise ErrorAPI(403, "PROHIBIDO", "Tu rol no consulta planes")
    return [await _plan_salida(db, p) for p in await planes_service.listar(db, actor, prestador_id, tipo_equipo_id, solo_activos)]


@router.post("/api/planes", response_model=PlanSalida, status_code=201, summary="Crear plan con triggers, tareas y materiales",
             description="Los seis triggers de §6.9.1: `tiempo_fijo` ({cada_dias} o {cada, unidad}), `calendario` "
                         "({mes, dia} o {fechas}), `medidor_umbral` ({tipo_medidor_id, umbral}), `medidor_intervalo` "
                         "({tipo_medidor_id, intervalo}), `evento` ({evento, …} del catálogo cerrado) y `combinado` "
                         "({triggers_ids, logica: OR|AND}). Cada trigger lleva una `clave` estable dentro del plan "
                         "(`t1`, `t2`, …) a la que el combinado apunta.")
async def crear_plan(datos: PlanEntrada, request: Request, db: DB, actor: Actor = Depends(TODOS), prestador_id: UUID | None = None):
    plan = await planes_service.crear(db, actor, datos.model_dump(), request, prestador_id)
    await db.commit()
    return await _plan_salida(db, plan)


@router.get("/api/planes/eventos-catalogo", summary="Catálogo cerrado de eventos que disparan planes",
            description="§6.9.1 «Por evento». Cada clave tiene código que la escucha, así que no se inventan desde "
                        "la interfaz; lo configurable son sus parámetros (`parametros_schema_json`).")
async def eventos_catalogo(db: DB, actor: Actor = Depends(TODOS)):
    if actor.rol not in planes_service.CONSULTAN:
        raise ErrorAPI(403, "PROHIBIDO", "Tu rol no consulta planes")
    from models.medidores import EventoTriggerCatalogo
    from sqlalchemy import select

    filas = (await db.execute(select(EventoTriggerCatalogo).where(EventoTriggerCatalogo.activo.is_(True))
                              .order_by(EventoTriggerCatalogo.clave))).scalars().all()
    return [{"clave": e.clave, "descripcion": e.descripcion, "parametros_schema_json": e.parametros_schema_json,
             "activo": e.activo} for e in filas]


@router.get("/api/planes/{plan_id}", response_model=PlanSalida, summary="Detalle del plan")
async def detalle_plan(plan_id: UUID, db: DB, actor: Actor = Depends(TODOS)):
    return await _plan_salida(db, await planes_service.obtener(db, actor, plan_id))


@router.get("/api/planes/{plan_id}/simulacion", summary="¿Cuándo se dispararía este plan?",
            description="Una fila por equipo asignado, con la fecha estimada de cada trigger: por fecha, el "
                        "calendario; por medidor, la proyección con el incremento promedio real; por evento, si ya "
                        "ocurrió. Si el equipo ya trae un preventivo abierto de este plan, lo dice (no nacerá otro).")
async def simulacion_plan(plan_id: UUID, db: DB, actor: Actor = Depends(TODOS), hoy: date | None = None):
    from services import triggers_service

    plan = await planes_service.obtener(db, actor, plan_id)
    if actor.rol not in planes_service.CONSULTAN:
        raise ErrorAPI(403, "PROHIBIDO", "Tu rol no consulta planes")
    return await triggers_service.simular(db, plan, hoy)


@router.put("/api/planes/{plan_id}", response_model=PlanSalida, summary="Editar plan (sube la versión)")
async def editar_plan(plan_id: UUID, datos: PlanCambios, request: Request, db: DB, actor: Actor = Depends(TODOS)):
    plan = await planes_service.obtener(db, actor, plan_id)
    await planes_service.editar(db, actor, plan, datos.model_dump(exclude_unset=True), request)
    await db.commit()
    return await _plan_salida(db, plan)


@router.post("/api/planes/{plan_id}/equipos", response_model=EquipoPlanSalida, status_code=201, summary="Asignar el plan a un equipo",
             description="Calcula `fecha_proxima_ejecucion` según el trigger (tiempo fijo desde la última ejecución o la fecha base; calendario: próxima fecha fija).")
async def asignar_equipo(plan_id: UUID, datos: AsignarEquipoEntrada, request: Request, db: DB, actor: Actor = Depends(TODOS)):
    plan = await planes_service.obtener(db, actor, plan_id)
    ep = await planes_service.asignar_equipo(db, actor, plan, datos.equipo_id, datos.fecha_base, request)
    await db.commit()
    return EquipoPlanSalida.model_validate(ep)


@router.delete("/api/planes/{plan_id}/equipos/{equipo_id}", response_model=Mensaje, summary="Desactivar el plan en un equipo")
async def desactivar_equipo(plan_id: UUID, equipo_id: UUID, request: Request, db: DB, actor: Actor = Depends(TODOS)):
    plan = await planes_service.obtener(db, actor, plan_id)
    await planes_service.desactivar_equipo(db, actor, plan, equipo_id, request)
    await db.commit()
    return Mensaje(mensaje="Plan desactivado en el equipo")


# -------------------------------------------------------------- calendario

@router.get("/api/preventivos/calendario", response_model=list[CalendarioSalida], summary="Calendario de preventivos",
            description="`mes` = AAAA-MM. Despachador/Mesa/Admin prestador ven el de sus clientes; Admin empresa el de su tenant; Admin UN y Supervisor sus UNs.")
async def calendario(db: DB, actor: Actor = Depends(TODOS), mes: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$"), tenant_id: UUID | None = None,
                     un_id: UUID | None = None, estado: EstadoPreventivo | None = None, desde: date | None = None, hasta: date | None = None):
    return [CalendarioSalida(**f) for f in await preventivos_service.listar_calendario(db, actor, mes, tenant_id, un_id, estado, desde, hasta)]


@router.post("/api/preventivos/calendario", response_model=list[CalendarioSalida], status_code=201, summary="Cargar preventivos (una fila o lote)")
async def cargar_calendario(datos: CalendarioEntrada, request: Request, db: DB, actor: Actor = Depends(TODOS)):
    filas = await preventivos_service.crear_calendario(db, actor, [f.model_dump() for f in datos.filas], datos.tenant_id, request)
    await db.commit()
    return [CalendarioSalida(**f) for f in await preventivos_service.enriquecer(db, filas)]


@router.patch("/api/preventivos/calendario/{calendario_id}", response_model=CalendarioSalida, summary="Editar un preventivo del calendario",
              description="Técnico, equipo y descripción; la fecha solo antes de generar el folio (después, reprogramación autorizada).")
async def editar_calendario(calendario_id: UUID, datos: CalendarioCambios, request: Request, db: DB, actor: Actor = Depends(TODOS)):
    fila = await db.get(PreventivoCalendario, calendario_id)
    if fila is None:
        raise no_encontrado("Preventivo")
    await preventivos_service.editar_calendario(db, actor, fila, datos.model_dump(exclude_unset=True), request)
    await db.commit()
    return CalendarioSalida(**(await preventivos_service.enriquecer(db, [fila]))[0])


@router.post("/api/preventivos/calendario/publicar", response_model=PublicacionSalida, summary="Publicar el mes (§7.6)",
             description="Emite `calendario.publicado` a Admin empresa y Admin UN (push + log; correo en P07).")
async def publicar(request: Request, db: DB, actor: Actor = Depends(TODOS), mes: str = Query(pattern=r"^\d{4}-\d{2}$"), tenant_id: UUID | None = None):
    pub = await preventivos_service.publicar_mes(db, actor, mes, tenant_id, request)
    await db.commit()
    return PublicacionSalida.model_validate(pub)


@router.get("/api/preventivos/calendario/publicaciones", response_model=list[PublicacionSalida], summary="Meses publicados")
async def publicaciones(db: DB, actor: Actor = Depends(TODOS), tenant_id: UUID | None = None):
    return [PublicacionSalida.model_validate(p) for p in await preventivos_service.publicaciones(db, actor, tenant_id)]


@router.post("/api/preventivos/generar", summary="Ejecutar ahora la generación nocturna (pruebas/operación)",
             description="Misma lógica que la tarea Celery `acma.generar_preventivos_programados`: planes con fecha próxima dentro del horizonte y calendario manual.")
async def generar(db: DB, actor: Actor = Depends(requiere_rol(Rol.superadmin, Rol.admin_prestador, Rol.despachador)), horizonte_dias: int = Query(default=7, ge=0, le=90),
                  hoy: date | None = None):
    resumen = await preventivos_service.generar_programados(db, hoy, horizonte_dias)
    await db.commit()
    return resumen


# ------------------------------------------------------------- ciclo de vida

@router.post("/api/preventivos/{folio_id}/solicitar-reprogramacion", response_model=AutorizacionSalida, status_code=201, summary="Solicitar reprogramación (Despachador)")
async def solicitar_reprogramacion(folio_id: UUID, datos: SolicitudEntrada, request: Request, db: DB, actor: Actor = Depends(TODOS)):
    folio = await folios.obtener(db, actor, folio_id)
    a = await preventivos_service.solicitar(db, actor, folio, TipoAutorizacionPreventivo.reprogramacion, datos.razon, datos.fecha_nueva, request)
    await db.commit()
    return await _autorizacion(db, actor, a.id)


@router.post("/api/preventivos/{folio_id}/solicitar-cancelacion", response_model=AutorizacionSalida, status_code=201, summary="Solicitar cancelación (Despachador)")
async def solicitar_cancelacion(folio_id: UUID, datos: SolicitudEntrada, request: Request, db: DB, actor: Actor = Depends(TODOS)):
    folio = await folios.obtener(db, actor, folio_id)
    a = await preventivos_service.solicitar(db, actor, folio, TipoAutorizacionPreventivo.cancelacion, datos.razon, None, request)
    await db.commit()
    return await _autorizacion(db, actor, a.id)


async def _autorizacion(db, actor, autorizacion_id: UUID) -> AutorizacionSalida:
    a = await db.get(AutorizacionPreventivo, autorizacion_id)
    if a is None:
        raise no_encontrado("Autorización")
    lista = await preventivos_service.autorizaciones_de(db, actor, a.folio_id, None)
    fila = next((x for x in lista if x["id"] == a.id), None)
    if fila is None:
        raise no_encontrado("Autorización")
    return AutorizacionSalida(**fila)


@router.get("/api/preventivos/autorizaciones", response_model=list[AutorizacionSalida], summary="Bandeja de autorizaciones de preventivos")
async def autorizaciones(db: DB, actor: Actor = Depends(TODOS), folio_id: UUID | None = None, estado: EstadoAutorizacion | None = None):
    return [AutorizacionSalida(**a) for a in await preventivos_service.autorizaciones_de(db, actor, folio_id, estado)]


@router.post("/api/preventivos/autorizaciones/{autorizacion_id}/autorizar", response_model=AutorizacionSalida, summary="Autorizar (Admin UN de la UN o Admin empresa)")
async def autorizar(autorizacion_id: UUID, datos: ResolverEntrada, request: Request, db: DB, actor: Actor = Depends(TODOS)):
    a = await db.get(AutorizacionPreventivo, autorizacion_id)
    if a is None:
        raise no_encontrado("Autorización")
    await preventivos_service.resolver(db, actor, a, True, datos.notas, datos.canal, request)
    await db.commit()
    return await _autorizacion(db, actor, a.id)


@router.post("/api/preventivos/autorizaciones/{autorizacion_id}/rechazar", response_model=AutorizacionSalida, summary="Rechazar la solicitud")
async def rechazar(autorizacion_id: UUID, datos: ResolverEntrada, request: Request, db: DB, actor: Actor = Depends(TODOS)):
    a = await db.get(AutorizacionPreventivo, autorizacion_id)
    if a is None:
        raise no_encontrado("Autorización")
    await preventivos_service.resolver(db, actor, a, False, datos.notas, datos.canal, request)
    await db.commit()
    return await _autorizacion(db, actor, a.id)


@router.get("/api/preventivos/{folio_id}/plan", response_model=TareasMaterialesSalida, summary="Tareas y materiales del plan del folio (app del técnico)")
async def plan_del_folio(folio_id: UUID, db: DB, actor: Actor = Depends(TODOS)):
    folio = await folios.obtener(db, actor, folio_id)
    return TareasMaterialesSalida(**await preventivos_service.tareas_y_materiales(db, folio))


@router.get("/api/preventivos/texto-desvio", summary="Texto literal de §7.6 para un desvío en días")
async def texto_desvio(_: ActorActual, desvio: int | None = None) -> dict:
    return {"desvio_dias": desvio, "texto": preventivos_service.texto_desvio(desvio)}
