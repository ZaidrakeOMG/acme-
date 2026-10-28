"""Evaluadores de alertas de los catálogos (P02). Cada módulo agrega los suyos con @registrar_evaluador."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.alertas import AlertaCatalogo, AlertaHistorial
from models.base import EstadoAlerta, EstadoRegistro
from models.organizaciones import Tenant
from services import alertas_service, catalogos_service
from workers.tareas import registrar_evaluador


@registrar_evaluador("MATRIZ_SEVERIDAD_INCOMPLETA")
async def matriz_incompleta(db: AsyncSession, alerta: AlertaCatalogo) -> int:
    """Por tenant activo: combinaciones falla × equipo en uso sin severidad. Dispara si superan el umbral (default 0)
    y no hay ya una alerta de este tipo sin atender para el tenant (la tarea corre cada 60 s)."""
    disparadas = 0
    tenants = (await db.execute(select(Tenant).where(Tenant.estado == EstadoRegistro.activo))).scalars().all()
    for tenant in tenants:
        faltantes = await catalogos_service.combinaciones_faltantes(db, tenant.id)
        if not faltantes:
            continue
        conf = await alertas_service.listar_efectivas(db, tenant.id, None)
        umbral = next(c["umbral_valor"] for c in conf if c["clave"] == alerta.clave)
        if len(faltantes) <= umbral:
            continue
        pendiente = (await db.execute(select(AlertaHistorial.id).where(
            AlertaHistorial.clave_alerta == alerta.clave, AlertaHistorial.tenant_id == tenant.id,
            AlertaHistorial.entidad_tipo == "tenant", AlertaHistorial.estado == EstadoAlerta.disparada))).first()
        if pendiente:
            continue
        h = await alertas_service.disparar(
            db, alerta.clave, tenant_id=tenant.id, prestador_id=None, entidad_tipo="tenant", entidad_id=tenant.id,
            datos={"faltantes": len(faltantes), "ejemplos": [f"{f} × {t}" for f, t in faltantes[:10]]},
        )
        disparadas += 1 if h else 0
    return disparadas


@registrar_evaluador("GEOLOCALIZACION_FUERA_DE_UN")
async def geolocalizacion_fuera_de_un(db: AsyncSession, alerta: AlertaCatalogo) -> int:
    """Red de seguridad: el envío de la respuesta ya dispara la alerta; aquí se recogen respuestas enviadas en las últimas
    24 h con geofencing fuera de rango que no tengan alerta registrada (p. ej. si el envío falló al registrarla)."""
    from datetime import UTC, datetime, timedelta

    from models.formularios import EstadoRespuesta, FormularioRespuesta

    desde = datetime.now(UTC) - timedelta(hours=24)
    respuestas = (await db.execute(select(FormularioRespuesta).where(
        FormularioRespuesta.estado == EstadoRespuesta.enviado, FormularioRespuesta.enviado_at >= desde))).scalars().all()
    disparadas = 0
    for r in respuestas:
        geo = (r.contexto_json or {}).get("geofencing") or {}
        fuera = [(clave, d) for clave, d in geo.items() if d.get("fuera")]
        if not fuera:
            continue
        ya = (await db.execute(select(AlertaHistorial.id).where(
            AlertaHistorial.clave_alerta == alerta.clave, AlertaHistorial.entidad_id == r.id))).first()
        if ya:
            continue
        clave, d = fuera[0]
        h = await alertas_service.disparar(db, alerta.clave, tenant_id=r.tenant_id, prestador_id=r.prestador_id,
                                           entidad_tipo="formulario_respuesta", entidad_id=r.id,
                                           datos={"campo": clave, "distancia_m": d.get("distancia_m"), "radio_m": d.get("radio_m"), "un_id": str(r.un_id)})
        disparadas += 1 if h else 0
    return disparadas


@registrar_evaluador("FOLIO_EN_REVISION_SIN_ATENDER")
async def folio_en_revision_sin_atender(db: AsyncSession, alerta: AlertaCatalogo) -> int:
    """Folios en `en_revision` por excepción de captura (sin flujo de aprobación abierto) con más de X horas sin atender."""
    from datetime import UTC, datetime, timedelta

    from models.folios import AprobacionFlujo, EstadoFlujo, EstadoFolio, Folio

    ahora = datetime.now(UTC)
    folios = (await db.execute(select(Folio).where(Folio.estado == EstadoFolio.en_revision))).scalars().all()
    disparadas = 0
    cache: dict = {}
    for f in folios:
        if f.tenant_id not in cache:
            conf = await alertas_service.listar_efectivas(db, f.tenant_id, None)
            cache[f.tenant_id] = next(c["umbral_valor"] for c in conf if c["clave"] == alerta.clave)
        if f.updated_at > ahora - timedelta(hours=float(cache[f.tenant_id])):
            continue
        con_flujo = (await db.execute(select(AprobacionFlujo.id).where(
            AprobacionFlujo.folio_id == f.id, AprobacionFlujo.estado.in_((EstadoFlujo.activo, EstadoFlujo.bloqueado))))).first()
        if con_flujo:
            continue
        ya = (await db.execute(select(AlertaHistorial.id).where(
            AlertaHistorial.clave_alerta == alerta.clave, AlertaHistorial.entidad_id == f.id, AlertaHistorial.estado == EstadoAlerta.disparada))).first()
        if ya:
            continue
        h = await alertas_service.disparar(db, alerta.clave, tenant_id=f.tenant_id, prestador_id=f.prestador_id, entidad_tipo="folio",
                                           entidad_id=f.id, datos={"numero_folio": f.numero_folio, "horas": round((ahora - f.updated_at).total_seconds() / 3600, 1)})
        disparadas += 1 if h else 0
    return disparadas


# ----------------------------------------------------------------- P06

async def _umbral_p06(db, alerta, tenant_id):
    conf = await alertas_service.listar_efectivas(db, tenant_id, None)
    return next(c["umbral_valor"] for c in conf if c["clave"] == alerta.clave)


async def _ya_disparada(db, alerta, entidad_id) -> bool:
    return (await db.execute(select(AlertaHistorial.id).where(AlertaHistorial.clave_alerta == alerta.clave, AlertaHistorial.entidad_id == entidad_id,
                                                              AlertaHistorial.estado == EstadoAlerta.disparada))).first() is not None


@registrar_evaluador("PREVENTIVO_VENCIDO_SIN_EJECUTAR")
async def preventivo_vencido(db: AsyncSession, alerta: AlertaCatalogo) -> int:
    """Preventivos programados/generados cuya fecha + ventana del plan + umbral (días) ya pasó sin cierre."""
    from datetime import date, timedelta

    from models.preventivos import EstadoPreventivo, PlanMantenimiento, PreventivoCalendario

    hoy = date.today()
    filas = (await db.execute(select(PreventivoCalendario).where(PreventivoCalendario.estado.in_((EstadoPreventivo.programado, EstadoPreventivo.generado))))).scalars().all()
    disparadas = 0
    for f in filas:
        ventana = 0
        if f.plan_id:
            plan = await db.get(PlanMantenimiento, f.plan_id)
            ventana = plan.tiempo_ventana_dias if plan else 0
        if hoy <= f.fecha_programada + timedelta(days=ventana + int(await _umbral_p06(db, alerta, f.tenant_id))):
            continue
        if await _ya_disparada(db, alerta, f.id):
            continue
        h = await alertas_service.disparar(db, alerta.clave, tenant_id=f.tenant_id, prestador_id=f.prestador_id, entidad_tipo="preventivo_calendario", entidad_id=f.id,
                                           datos={"fecha_programada": f.fecha_programada.isoformat(), "ventana_dias": ventana, "folio_id": str(f.folio_id) if f.folio_id else None})
        disparadas += 1 if h else 0
    return disparadas


@registrar_evaluador("AUTORIZACION_PREVENTIVO_PENDIENTE")
async def autorizacion_preventivo_pendiente(db: AsyncSession, alerta: AlertaCatalogo) -> int:
    from datetime import UTC, datetime, timedelta

    from models.preventivos import AutorizacionPreventivo, EstadoAutorizacion

    ahora = datetime.now(UTC)
    pendientes = (await db.execute(select(AutorizacionPreventivo).where(AutorizacionPreventivo.estado == EstadoAutorizacion.pendiente))).scalars().all()
    disparadas = 0
    for a in pendientes:
        if a.fecha_solicitud > ahora - timedelta(hours=float(await _umbral_p06(db, alerta, a.tenant_id))):
            continue
        if await _ya_disparada(db, alerta, a.id):
            continue
        h = await alertas_service.disparar(db, alerta.clave, tenant_id=a.tenant_id, prestador_id=a.prestador_id, entidad_tipo="autorizacion_preventivo", entidad_id=a.id,
                                           datos={"folio_id": str(a.folio_id), "tipo": a.tipo.value, "horas": round((ahora - a.fecha_solicitud).total_seconds() / 3600, 1)})
        disparadas += 1 if h else 0
    return disparadas


@registrar_evaluador("CALENDARIO_MES_SIN_PUBLICAR")
async def calendario_mes_sin_publicar(db: AsyncSession, alerta: AlertaCatalogo) -> int:
    """A partir del día umbral del mes, cada vínculo tenant-prestador sin calendario publicado del mes siguiente dispara una vez por mes."""
    from datetime import date

    from models.organizaciones import TenantPrestador
    from models.preventivos import CalendarioPublicacion

    hoy = date.today()
    siguiente = date(hoy.year + (hoy.month == 12), hoy.month % 12 + 1, 1)
    vinculos = (await db.execute(select(TenantPrestador).where(TenantPrestador.estado == EstadoRegistro.activo))).scalars().all()
    disparadas = 0
    for v in vinculos:
        if hoy.day < int(await _umbral_p06(db, alerta, v.tenant_id)):
            continue
        publicado = (await db.execute(select(CalendarioPublicacion.id).where(CalendarioPublicacion.prestador_id == v.prestador_id,
                                                                             CalendarioPublicacion.tenant_id == v.tenant_id, CalendarioPublicacion.mes == siguiente))).first()
        if publicado:
            continue
        reciente = (await db.execute(select(AlertaHistorial.id).where(AlertaHistorial.clave_alerta == alerta.clave, AlertaHistorial.entidad_id == v.id,
                                                                      AlertaHistorial.datos_contexto_json["mes"].astext == siguiente.isoformat()))).first()
        if reciente:
            continue
        h = await alertas_service.disparar(db, alerta.clave, tenant_id=v.tenant_id, prestador_id=v.prestador_id, entidad_tipo="tenant_prestador", entidad_id=v.id,
                                           datos={"mes": siguiente.isoformat()})
        disparadas += 1 if h else 0
    return disparadas
