"""Evaluadores de las alertas de SLA, contratos, iguala y escalaciones a Dirección del prestador (§6.10.1, §6.9.6). P10."""
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.alertas import AlertaCatalogo, AlertaHistorial
from models.base import EstadoRegistro, ModalidadContrato
from models.contratos import Contrato
from models.folios import EstadoFolio, Folio, FolioSLA
from models.sla import FolioSLAExclusion
from services import alertas_service, sla_service
from workers.evaluadores import _umbral_p06 as _umbral
from workers.evaluadores_seguimiento import _disparar_una_vez
from workers.tareas import registrar_evaluador


@registrar_evaluador("SLA_RESPUESTA_EN_RIESGO")
async def sla_respuesta_en_riesgo(db: AsyncSession, alerta: AlertaCatalogo) -> int:
    """Folio sin asignar con el X% del tiempo de respuesta ya consumido (§6.9.6, default 80%)."""
    return await _riesgo(db, alerta, "respuesta")


@registrar_evaluador("SLA_RESOLUCION_EN_RIESGO")
async def sla_resolucion_en_riesgo(db: AsyncSession, alerta: AlertaCatalogo) -> int:
    return await _riesgo(db, alerta, "resolucion")


async def _riesgo(db: AsyncSession, alerta: AlertaCatalogo, cual: str) -> int:
    n = 0
    filas = (await db.execute(select(FolioSLA, Folio).join(Folio, Folio.id == FolioSLA.folio_id).where(
        Folio.estado.notin_([EstadoFolio.cerrado, EstadoFolio.cancelado]), FolioSLA.tiempo_inicio.is_not(None),
        FolioSLA.riesgo_respuesta_avisado.is_(False) if cual == "respuesta" else FolioSLA.riesgo_resolucion_avisado.is_(False)))).all()
    for f, folio in filas:
        if f.excluir_sla_por_cliente:
            continue
        pct = Decimal(await _umbral(db, alerta, folio.tenant_id))
        claves = await sla_service.en_riesgo(db, f, folio, pct)
        if alerta.clave not in claves:
            continue
        datos = {"numero_folio": folio.numero_folio, "limite_min": f.limite_respuesta_min if cual == "respuesta" else f.limite_sla_min,
                 "porcentaje": str(pct), "estado": folio.estado.value}
        n += await _disparar_una_vez(db, alerta, tenant_id=folio.tenant_id, prestador_id=folio.prestador_id,
                                     entidad_tipo="folio", entidad_id=folio.id, datos=datos)
    return n


@registrar_evaluador("EXCLUSION_SLA_PENDIENTE")
async def exclusion_pendiente(db: AsyncSession, alerta: AlertaCatalogo) -> int:
    """Exclusión registrada por el prestador sin decisión del Admin empresa (§6.10.1)."""
    ahora = datetime.now(UTC)
    n = 0
    for e in (await db.execute(select(FolioSLAExclusion).where(FolioSLAExclusion.aprobada.is_(None)))).scalars():
        dias = int(await _umbral(db, alerta, e.tenant_id))
        if e.created_at > ahora - timedelta(days=dias):
            continue
        n += await _disparar_una_vez(db, alerta, tenant_id=e.tenant_id, prestador_id=e.prestador_id,
                                     entidad_tipo="folio_sla_exclusiones", entidad_id=e.id,
                                     datos={"causa": e.causa.value, "minutos": e.minutos, "dias": (ahora - e.created_at).days})
    return n


@registrar_evaluador("CONTRATO_POR_VENCER")
async def contrato_por_vencer(db: AsyncSession, alerta: AlertaCatalogo) -> int:
    """ACMA alerta X días antes del vencimiento del contrato (§6.10.1, default 30)."""
    hoy = date.today()
    n = 0
    for c in (await db.execute(select(Contrato).where(Contrato.estado == EstadoRegistro.activo))).scalars():
        dias = int(await _umbral(db, alerta, c.tenant_id))
        if c.fecha_fin < hoy or c.fecha_fin > hoy + timedelta(days=dias):
            continue
        n += await _disparar_una_vez(db, alerta, tenant_id=c.tenant_id, prestador_id=c.prestador_id, entidad_tipo="contratos",
                                     entidad_id=c.id, datos={"nombre": c.nombre, "fecha_fin": c.fecha_fin.isoformat(),
                                                             "dias_restantes": (c.fecha_fin - hoy).days})
    return n


@registrar_evaluador("IGUALA_LIMITE_ALCANZADO")
async def iguala_limite(db: AsyncSession, alerta: AlertaCatalogo) -> int:
    """Correctivos del período contra los incluidos en la iguala; `consumo_iguala` dispara la alerta al recalcular."""
    periodo = date.today().strftime("%Y-%m")
    antes = (await db.execute(select(AlertaHistorial.id).where(AlertaHistorial.clave_alerta == alerta.clave))).all()
    for c in (await db.execute(select(Contrato).where(Contrato.estado == EstadoRegistro.activo,
                                                      Contrato.modalidad == ModalidadContrato.iguala))).scalars():
        await sla_service.consumo_iguala(db, c, periodo)
    despues = (await db.execute(select(AlertaHistorial.id).where(AlertaHistorial.clave_alerta == alerta.clave))).all()
    return len(despues) - len(antes)


@registrar_evaluador("SLA_INCUMPLIDO")
async def sla_incumplido(db: AsyncSession, alerta: AlertaCatalogo) -> int:
    """Red de seguridad: el gancho de cierre ya la dispara; aquí se recogen los folios incumplidos sin alerta."""
    n = 0
    filas = (await db.execute(select(FolioSLA, Folio).join(Folio, Folio.id == FolioSLA.folio_id).where(
        FolioSLA.cumplimiento.is_(False)))).all()
    for f, folio in filas:
        n += await _disparar_una_vez(db, alerta, tenant_id=folio.tenant_id, prestador_id=folio.prestador_id, entidad_tipo="folio",
                                     entidad_id=folio.id, datos={"numero_folio": folio.numero_folio, "limite_min": f.limite_sla_min,
                                                                 "efectivo_min": f.tiempo_efectivo_min,
                                                                 "penalizacion": str(f.penalizacion_calculada)})
    return n


async def _escalar(db: AsyncSession, alerta: AlertaCatalogo) -> int:
    """Escalación genérica (§6.9.6): el umbral se mide desde el disparo de la alerta origen, no desde el hecho."""
    from services import notificaciones_service

    n = 0
    for origen in await alertas_service.por_escalar(db, alerta.clave):
        h = await alertas_service.disparar(db, alerta.clave, tenant_id=origen.tenant_id, prestador_id=origen.prestador_id,
                                           entidad_tipo=origen.entidad_tipo, entidad_id=origen.entidad_id,
                                           datos={**origen.datos_contexto_json, "alerta_origen_id": str(origen.id),
                                                  "clave_origen": origen.clave_alerta,
                                                  "disparo_origen": origen.timestamp_disparo.isoformat()})
        if h is None:
            continue
        origen.escalada = True
        n += 1
        destinos = await alertas_service.destinatarios(db, alerta.clave, tenant_id=origen.tenant_id, prestador_id=origen.prestador_id)
        if destinos:
            await notificaciones_service.notificar(
                db, f"alerta.{alerta.clave.lower()}", destinos, {"clave_origen": origen.clave_alerta},
                asunto=f"Escalación a Dirección: {origen.clave_alerta}",
                cuerpo=f"La alerta {origen.clave_alerta} sigue sin atenderse desde {origen.timestamp_disparo:%d/%m/%Y}.",
                tenant_id=origen.tenant_id, prestador_id=origen.prestador_id)
    await db.flush()
    return n


@registrar_evaluador("SLA_INCUMPLIDO_ESCALADO_DIRECCION")
async def sla_escalado(db: AsyncSession, alerta: AlertaCatalogo) -> int:
    return await _escalar(db, alerta)


@registrar_evaluador("PRESUPUESTO_ESCALADO_DIRECCION")
async def presupuesto_escalado(db: AsyncSession, alerta: AlertaCatalogo) -> int:
    return await _escalar(db, alerta)


@registrar_evaluador("COTIZACION_ESCALADA_DIRECCION")
async def cotizacion_escalada(db: AsyncSession, alerta: AlertaCatalogo) -> int:
    """§6.9.6: el umbral corre desde el disparo de COTIZACION_SIN_RESPUESTA, no desde el envío al cliente."""
    return await _escalar(db, alerta)
