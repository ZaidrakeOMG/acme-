"""Evaluadores de las alertas de trabajos especiales (§6.10.6) y del seguimiento de OC de activos (§6.10.7). P08.
Cada uno dispara una vez por entidad mientras la condición siga activa."""
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.alertas import AlertaCatalogo
from models.catalogos import Equipo, EstadoActivo
from models.folios import Folio
from models.trabajos_especiales import EstadoTrabajoEspecial, EstatusOCActivo, FolioActivoAutorizacion, TrabajoEspecial
from workers.evaluadores import _umbral_p06 as _umbral
from workers.evaluadores_seguimiento import _disparar_una_vez
from workers.tareas import registrar_evaluador

E = EstadoTrabajoEspecial


async def _te_por_dias(db: AsyncSession, alerta: AlertaCatalogo, estado: E, campo_fecha: str) -> int:
    ahora = datetime.now(UTC)
    n = 0
    for t in (await db.execute(select(TrabajoEspecial).where(TrabajoEspecial.estado == estado))).scalars():
        desde = getattr(t, campo_fecha, None) or t.estado_desde
        if desde > ahora - timedelta(days=int(await _umbral(db, alerta, t.tenant_id))):
            continue
        n += await _disparar_una_vez(db, alerta, tenant_id=t.tenant_id, prestador_id=t.prestador_id, entidad_tipo="trabajo_especial", entidad_id=t.id,
                                     datos={"numero": t.numero, "estado": t.estado.value, "dias": (ahora - desde).days, "urgencia": t.urgencia, "descripcion": t.descripcion[:200]})
    return n


@registrar_evaluador("TE_SIN_RESPUESTA_CLIENTE")
async def te_sin_respuesta(db: AsyncSession, alerta: AlertaCatalogo) -> int:
    return await _te_por_dias(db, alerta, E.enviado_cliente, "enviado_at")


@registrar_evaluador("TE_ACEPTADO_SIN_PROGRAMAR")
async def te_sin_programar(db: AsyncSession, alerta: AlertaCatalogo) -> int:
    return await _te_por_dias(db, alerta, E.aceptado, "aceptado_at")


@registrar_evaluador("TE_PROGRAMADO_VENCIDO")
async def te_programado_vencido(db: AsyncSession, alerta: AlertaCatalogo) -> int:
    hoy = date.today()
    n = 0
    for t in (await db.execute(select(TrabajoEspecial).where(TrabajoEspecial.estado == E.programado, TrabajoEspecial.fecha_programada.is_not(None)))).scalars():
        if t.fecha_programada + timedelta(days=int(await _umbral(db, alerta, t.tenant_id))) >= hoy:
            continue
        n += await _disparar_una_vez(db, alerta, tenant_id=t.tenant_id, prestador_id=t.prestador_id, entidad_tipo="trabajo_especial", entidad_id=t.id,
                                     datos={"numero": t.numero, "fecha_programada": t.fecha_programada.isoformat(), "dias_vencido": (hoy - t.fecha_programada).days, "urgencia": t.urgencia})
    return n


@registrar_evaluador("TE_URGENCIA_SIN_COTIZACION_RETROACTIVA")
async def te_urgencia_sin_cotizacion(db: AsyncSession, alerta: AlertaCatalogo) -> int:
    """Informativa: TE de urgencia cerrado sin cotización retroactiva (opcional por tenant vía umbral/supresión)."""
    ahora = datetime.now(UTC)
    n = 0
    for t in (await db.execute(select(TrabajoEspecial).where(TrabajoEspecial.estado == E.cerrado, TrabajoEspecial.urgencia.is_(True), TrabajoEspecial.cotizacion_retroactiva_id.is_(None)))).scalars():
        desde = t.fecha_cierre or t.estado_desde
        if desde > ahora - timedelta(days=int(await _umbral(db, alerta, t.tenant_id))):
            continue
        n += await _disparar_una_vez(db, alerta, tenant_id=t.tenant_id, prestador_id=t.prestador_id, entidad_tipo="trabajo_especial", entidad_id=t.id,
                                     datos={"numero": t.numero, "dias_desde_cierre": (ahora - desde).days})
    return n


async def _oc_por_dias(db: AsyncSession, alerta: AlertaCatalogo, estatus: EstatusOCActivo) -> int:
    ahora = datetime.now(UTC)
    n = 0
    for a in (await db.execute(select(FolioActivoAutorizacion).where(FolioActivoAutorizacion.estatus_multinivel == estatus))).scalars():
        if a.estatus_desde > ahora - timedelta(days=int(await _umbral(db, alerta, a.tenant_id))):
            continue
        folio = await db.get(Folio, a.folio_id)
        n += await _disparar_una_vez(db, alerta, tenant_id=a.tenant_id, prestador_id=a.prestador_id, entidad_tipo="folio", entidad_id=a.folio_id,
                                     datos={"numero_folio": folio.numero_folio if folio else None, "estatus": estatus.value, "dias": (ahora - a.estatus_desde).days,
                                            "numero_oc_provisional": a.numero_oc_provisional})
    return n


@registrar_evaluador("OC_ACTIVO_SIN_TRAMITE")
async def oc_sin_tramite(db: AsyncSession, alerta: AlertaCatalogo) -> int:
    return await _oc_por_dias(db, alerta, EstatusOCActivo.pendiente_iniciar_tramite)


@registrar_evaluador("OC_ACTIVO_EN_TRAMITE_PROLONGADO")
async def oc_en_tramite_prolongado(db: AsyncSession, alerta: AlertaCatalogo) -> int:
    return await _oc_por_dias(db, alerta, EstatusOCActivo.oc_en_tramite)


@registrar_evaluador("ACTIVO_INSTALADO_INCOMPLETO")
async def activo_incompleto(db: AsyncSession, alerta: AlertaCatalogo) -> int:
    """Equipos dados de alta por un folio de activo que siguen inactivos (ficha incompleta) tras X días; el alta ya disparó la primera vez."""
    ahora = datetime.now(UTC)
    n = 0
    filas = (await db.execute(select(Folio, Equipo).join(Equipo, Equipo.id == Folio.equipo_instalado_id).where(Folio.es_instalacion_activo.is_(True), Equipo.estado == EstadoActivo.inactivo))).all()
    for folio, equipo in filas:
        if equipo.created_at > ahora - timedelta(days=int(await _umbral(db, alerta, folio.tenant_id))):
            continue
        n += await _disparar_una_vez(db, alerta, tenant_id=folio.tenant_id, prestador_id=folio.prestador_id, entidad_tipo="equipo", entidad_id=equipo.id,
                                     datos={"codigo": equipo.codigo, "numero_folio": folio.numero_folio, "faltan": ["tipo_equipo"]})
    return n
