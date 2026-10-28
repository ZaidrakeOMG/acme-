"""Evaluadores de las alertas de la minuta, los módulos de seguimiento y la clasificación (P07). Cada uno dispara una vez por
entidad mientras la condición siga activa (dedupe por alerta disparada sin atender)."""
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.alertas import AlertaCatalogo
from models.base import EstadoRegistro, Rol
from models.folios import EstadoFolio, Folio, RevisionManualTrigger, TriggerRevision
from models.minutas import EstadoMinuta, Minuta, MinutaConfiguracion
from models.organizaciones import Tenant, TenantPrestador
from models.seguimiento import (
    ClasificacionConfiguracion, Cotizacion, EstadoCotizacion, EstadoPresupuesto, EstadoReprogramacion, EstadoSeguimientoInterno, HallazgoPresupuesto, Reprogramacion,
    SeguimientoInterno,
)
from services import alertas_service, notificaciones_service
from workers.evaluadores import _umbral_p06 as _umbral, _ya_disparada
from workers.tareas import registrar_evaluador


async def _disparar_una_vez(db, alerta, *, tenant_id, prestador_id, entidad_tipo, entidad_id, datos) -> int:
    if await _ya_disparada(db, alerta, entidad_id):
        return 0
    h = await alertas_service.disparar(db, alerta.clave, tenant_id=tenant_id, prestador_id=prestador_id, entidad_tipo=entidad_tipo, entidad_id=entidad_id, datos=datos)
    return 1 if h else 0


async def _por_dias(db: AsyncSession, alerta: AlertaCatalogo, modelo, estados, campo_fecha, entidad_tipo: str) -> int:
    ahora = datetime.now(UTC)
    filas = (await db.execute(select(modelo).where(modelo.estado.in_(estados)))).scalars().all()
    n = 0
    for r in filas:
        desde = getattr(r, campo_fecha, None) or r.estado_desde
        dias = int(await _umbral(db, alerta, r.tenant_id))
        if desde is None or desde > ahora - timedelta(days=dias):
            continue
        n += await _disparar_una_vez(db, alerta, tenant_id=r.tenant_id, prestador_id=r.prestador_id, entidad_tipo=entidad_tipo, entidad_id=r.id,
                                     datos={"estado": r.estado.value, "dias": (ahora - desde).days, "descripcion": (getattr(r, "descripcion", "") or "")[:200]})
    return n


# ------------------------------------------------------------ cotizaciones

@registrar_evaluador("COTIZACION_SIN_PREPARAR")
async def cotizacion_sin_preparar(db: AsyncSession, alerta: AlertaCatalogo) -> int:
    return await _por_dias(db, alerta, Cotizacion, (EstadoCotizacion.solicitada,), "fecha_solicitud", "cotizacion")


@registrar_evaluador("COTIZACION_SIN_ENVIAR")
async def cotizacion_sin_enviar(db: AsyncSession, alerta: AlertaCatalogo) -> int:
    return await _por_dias(db, alerta, Cotizacion, (EstadoCotizacion.en_preparacion,), "fecha_preparacion", "cotizacion")


@registrar_evaluador("COTIZACION_SIN_RESPUESTA")
async def cotizacion_sin_respuesta(db: AsyncSession, alerta: AlertaCatalogo) -> int:
    return await _por_dias(db, alerta, Cotizacion, (EstadoCotizacion.enviada,), "fecha_envio", "cotizacion")


@registrar_evaluador("COTIZACION_AUTORIZADA_SIN_CONVERTIR")
async def cotizacion_sin_convertir(db: AsyncSession, alerta: AlertaCatalogo) -> int:
    return await _por_dias(db, alerta, Cotizacion, (EstadoCotizacion.autorizada,), "fecha_respuesta", "cotizacion")


# ------------------------------------------------------------- presupuesto

@registrar_evaluador("PRESUPUESTO_SIN_REVISION")
async def presupuesto_sin_revision(db: AsyncSession, alerta: AlertaCatalogo) -> int:
    return await _por_dias(db, alerta, HallazgoPresupuesto, (EstadoPresupuesto.diferido,), "ultima_revision", "hallazgo_presupuesto")


# ------------------------------------------------------ seguimiento interno

@registrar_evaluador("SEGUIMIENTO_SIN_UPDATE")
async def seguimiento_sin_actualizar(db: AsyncSession, alerta: AlertaCatalogo) -> int:
    """Registrado / en gestión / con proveedor sin novedad por más del umbral (default 15 días)."""
    return await _por_dias(db, alerta, SeguimientoInterno, (EstadoSeguimientoInterno.registrado, EstadoSeguimientoInterno.en_gestion, EstadoSeguimientoInterno.con_proveedor),
                           "ultima_actualizacion", "seguimiento_interno")


@registrar_evaluador("SEGUIMIENTO_INTERNO_FECHA_VENCIDA")
async def seguimiento_fecha_vencida(db: AsyncSession, alerta: AlertaCatalogo) -> int:
    hoy = date.today()
    n = 0
    for s in (await db.execute(select(SeguimientoInterno).where(SeguimientoInterno.estado == EstadoSeguimientoInterno.con_proveedor, SeguimientoInterno.fecha_acordada.is_not(None)))).scalars():
        if s.fecha_acordada + timedelta(days=int(await _umbral(db, alerta, s.tenant_id))) >= hoy:
            continue
        n += await _disparar_una_vez(db, alerta, tenant_id=s.tenant_id, prestador_id=s.prestador_id, entidad_tipo="seguimiento_interno", entidad_id=s.id,
                                     datos={"fecha_acordada": s.fecha_acordada.isoformat(), "proveedor": s.proveedor})
    return n


# ---------------------------------------------------------- reprogramación

@registrar_evaluador("REPROGRAMACION_SIN_FECHA")
async def reprogramacion_sin_fecha(db: AsyncSession, alerta: AlertaCatalogo) -> int:
    return await _por_dias(db, alerta, Reprogramacion, (EstadoReprogramacion.pendiente_fecha,), "estado_desde", "reprogramacion")


@registrar_evaluador("REPROGRAMACION_SIN_CIERRE")
async def reprogramacion_sin_cierre(db: AsyncSession, alerta: AlertaCatalogo) -> int:
    return await _por_dias(db, alerta, Reprogramacion, (EstadoReprogramacion.en_ejecucion,), "estado_desde", "reprogramacion")


@registrar_evaluador("REPROGRAMACION_FECHA_PROXIMA")
async def reprogramacion_fecha_proxima(db: AsyncSession, alerta: AlertaCatalogo) -> int:
    hoy = date.today()
    n = 0
    for r in (await db.execute(select(Reprogramacion).where(Reprogramacion.estado == EstadoReprogramacion.fecha_asignada, Reprogramacion.fecha_acordada.is_not(None)))).scalars():
        dias = int(await _umbral(db, alerta, r.tenant_id))
        if not (hoy <= r.fecha_acordada <= hoy + timedelta(days=dias)):
            continue
        n += await _disparar_una_vez(db, alerta, tenant_id=r.tenant_id, prestador_id=r.prestador_id, entidad_tipo="reprogramacion", entidad_id=r.id,
                                     datos={"fecha_acordada": r.fecha_acordada.isoformat(), "proveedor": r.proveedor_tercero, "sin_confirmar": True})
    return n


@registrar_evaluador("REPROGRAMACION_FECHA_VENCIDA")
async def reprogramacion_fecha_vencida(db: AsyncSession, alerta: AlertaCatalogo) -> int:
    """Inmediata (X días de tolerancia): suma al contador acumulado y escala al llegar a 3 (REPROGRAMACION_ESCALADA_EMPRESA)."""
    from services.seguimiento import reprogramacion as svc

    hoy = date.today()
    n = 0
    for r in (await db.execute(select(Reprogramacion).where(Reprogramacion.estado.in_((EstadoReprogramacion.fecha_asignada, EstadoReprogramacion.tercero_confirmado)),
                                                            Reprogramacion.fecha_acordada.is_not(None)))).scalars():
        if r.fecha_acordada + timedelta(days=int(await _umbral(db, alerta, r.tenant_id))) >= hoy:
            continue
        if await svc.registrar_fecha_vencida(db, r, hoy):
            n += 1
    return n


@registrar_evaluador("REPROGRAMACION_ESCALADA_EMPRESA")
async def reprogramacion_escalada(db: AsyncSession, alerta: AlertaCatalogo) -> int:
    """La dispara `registrar_fecha_vencida` al llegar a 3; aquí solo se cubre un escalado pendiente de registrar."""
    n = 0
    for r in (await db.execute(select(Reprogramacion).where(Reprogramacion.escalada_empresa.is_(True)))).scalars():
        n += await _disparar_una_vez(db, alerta, tenant_id=r.tenant_id, prestador_id=r.prestador_id, entidad_tipo="reprogramacion", entidad_id=r.id,
                                     datos={"fechas_vencidas_count": r.fechas_vencidas_count})
    return n


# ------------------------------------------------------------------ minuta

@registrar_evaluador("MINUTA_SIN_VALIDAR")
async def minuta_sin_validar(db: AsyncSession, alerta: AlertaCatalogo) -> int:
    ahora = datetime.now(UTC)
    n = 0
    for m in (await db.execute(select(Minuta).where(Minuta.estado == EstadoMinuta.pendiente_validacion))).scalars():
        if m.timestamp_generacion > ahora - timedelta(minutes=float(await _umbral(db, alerta, m.tenant_id))):
            continue
        n += await _disparar_una_vez(db, alerta, tenant_id=m.tenant_id, prestador_id=m.prestador_id, entidad_tipo="minuta", entidad_id=m.id, datos={"fecha": m.fecha.isoformat(), "tipo": m.tipo.value})
    return n


@registrar_evaluador("MINUTA_SIN_RESPUESTA")
async def minuta_sin_respuesta(db: AsyncSession, alerta: AlertaCatalogo) -> int:
    ahora = datetime.now(UTC)
    n = 0
    for m in (await db.execute(select(Minuta).where(Minuta.estado.in_((EstadoMinuta.enviada, EstadoMinuta.vencida)), Minuta.vence_respuesta_at.is_not(None)))).scalars():
        if m.timestamp_envio is None or m.timestamp_envio > ahora - timedelta(hours=float(await _umbral(db, alerta, m.tenant_id))):
            continue
        n += await _disparar_una_vez(db, alerta, tenant_id=m.tenant_id, prestador_id=m.prestador_id, entidad_tipo="minuta", entidad_id=m.id, datos={"fecha": m.fecha.isoformat(), "tipo": m.tipo.value})
    return n


@registrar_evaluador("MINUTA_NO_GENERADA")
async def minuta_no_generada(db: AsyncSession, alerta: AlertaCatalogo) -> int:
    from zoneinfo import ZoneInfo

    from services import minuta_service

    ahora = datetime.now(UTC)
    n = 0
    for v in (await db.execute(select(TenantPrestador).where(TenantPrestador.estado == EstadoRegistro.activo))).scalars():
        tenant = await db.get(Tenant, v.tenant_id)
        cfg = (await db.execute(select(MinutaConfiguracion).where(MinutaConfiguracion.tenant_id == v.tenant_id, MinutaConfiguracion.prestador_id == v.prestador_id))).scalar_one_or_none()
        zona = tenant.zona_horaria if tenant else "America/Mexico_City"
        local = ahora.astimezone(ZoneInfo(zona))
        hora = cfg.hora_envio if cfg else datetime.strptime("19:00", "%H:%M").time()
        limite = datetime.combine(local.date(), hora, tzinfo=ZoneInfo(zona)) + timedelta(hours=float(await _umbral(db, alerta, v.tenant_id)))
        if local < limite:
            continue
        existe = (await db.execute(select(Minuta.id).where(Minuta.tenant_id == v.tenant_id, Minuta.prestador_id == v.prestador_id, Minuta.fecha == local.date()))).first()
        if existe or not await minuta_service.unidades_con_actividad(db, v.tenant_id, v.prestador_id, local.date(), zona):
            continue
        # entidad = vínculo; una por día gracias a la fecha en los datos
        n += await _disparar_una_vez(db, alerta, tenant_id=v.tenant_id, prestador_id=v.prestador_id, entidad_tipo="tenant_prestador", entidad_id=v.id, datos={"fecha": local.date().isoformat()})
    return n


# ---------------------------------------------------------- clasificación

async def _pendientes_vencidos(db: AsyncSession, horas_extra: float):
    ahora = datetime.now(UTC)
    cfgs = {c.tenant_id: c for c in (await db.execute(select(ClasificacionConfiguracion).where(ClasificacionConfiguracion.activa.is_(True)))).scalars()}
    filas = (await db.execute(select(Folio, RevisionManualTrigger).join(RevisionManualTrigger, RevisionManualTrigger.folio_id == Folio.id).where(
        RevisionManualTrigger.trigger_tipo == TriggerRevision.pendiente_clasificacion, RevisionManualTrigger.resuelto.is_(False), Folio.estado == EstadoFolio.en_revision))).all()
    for folio, t in filas:
        c = cfgs.get(folio.tenant_id)
        plazo = c.plazo_horas if c else 24
        if t.timestamp + timedelta(hours=plazo + horas_extra) <= ahora:
            yield folio, t, plazo


@registrar_evaluador("FOLIO_SIN_CLASIFICAR")
async def folio_sin_clasificar(db: AsyncSession, alerta: AlertaCatalogo) -> int:
    """Recordatorio al Admin UN: pendiente más allá del plazo del tenant (el umbral X horas del catálogo se suma como tolerancia)."""
    n = 0
    async for folio, t, plazo in _pendientes_vencidos(db, 0):
        n += await _disparar_una_vez(db, alerta, tenant_id=folio.tenant_id, prestador_id=folio.prestador_id, entidad_tipo="folio", entidad_id=folio.id,
                                     datos={"numero_folio": folio.numero_folio, "plazo_horas": plazo, "pendiente_desde": t.timestamp.isoformat()})
    return n


@registrar_evaluador("ADMIN_UN_INCUMPLIMIENTO_CLASIFICACION")
async def incumplimiento_clasificacion(db: AsyncSession, alerta: AlertaCatalogo) -> int:
    """§6.10.5: cada folio fuera de plazo informa al Admin empresa (una vez)."""
    n = 0
    async for folio, t, plazo in _pendientes_vencidos(db, 0):
        extra = float(await _umbral(db, alerta, folio.tenant_id))
        if t.timestamp + timedelta(hours=plazo + extra) > datetime.now(UTC):
            continue
        d = await _disparar_una_vez(db, alerta, tenant_id=folio.tenant_id, prestador_id=folio.prestador_id, entidad_tipo="folio", entidad_id=folio.id,
                                    datos={"numero_folio": folio.numero_folio, "plazo_horas": plazo, "pendiente_desde": t.timestamp.isoformat()})
        if d:
            destinatarios = await notificaciones_service.destinatarios_por_rol(db, [Rol.admin_empresa], tenant_id=folio.tenant_id)
            await notificaciones_service.notificar(db, "clasificacion.incumplimiento", destinatarios, {"folio_id": str(folio.id)},
                                                   asunto=f"Folio {folio.numero_folio} sin clasificar fuera de plazo", cuerpo="El Admin UN no clasificó el folio no crítico a tiempo; afecta su calificación.",
                                                   url="/clasificacion?vista=calificacion", tenant_id=folio.tenant_id, prestador_id=folio.prestador_id)
        n += d
    return n


@registrar_evaluador("ADMIN_UN_MINUTA_SIN_RESPONDER")
async def admin_un_minuta_sin_responder(db: AsyncSession, alerta: AlertaCatalogo) -> int:
    ahora = datetime.now(UTC)
    n = 0
    for m in (await db.execute(select(Minuta).where(Minuta.estado == EstadoMinuta.vencida))).scalars():
        if m.vence_respuesta_at and m.vence_respuesta_at + timedelta(hours=float(await _umbral(db, alerta, m.tenant_id))) > ahora:
            continue
        n += await _disparar_una_vez(db, alerta, tenant_id=m.tenant_id, prestador_id=None, entidad_tipo="minuta", entidad_id=m.id, datos={"fecha": m.fecha.isoformat(), "un_id": str(m.un_id) if m.un_id else None})
    return n


@registrar_evaluador("ADMIN_UN_BAJO_DESEMPENO")
async def admin_un_bajo_desempeno(db: AsyncSession, alerta: AlertaCatalogo) -> int:
    """La dispara la calificación (clasificacion_service.calificar) al cruzar el umbral; el evaluador periódico no la duplica."""
    return 0
