"""Contador de SLA, exclusiones aprobadas, penalizaciones por período y consumo de la iguala (§6.10.1). P10.

Reglas elegidas y anotadas en CONTEXTO.md:
- `tiempo_inicio` = captura del folio; para los no críticos que el Admin UN clasifica (P07) es la autorización.
- Respuesta = de `tiempo_inicio` a `asignado` (el documento dice «folio sin asignar»); resolución = a `cerrado`.
- Pausas: `reasignado` (§6.10.1) y `pendiente_informacion` (espera de datos del operador).
- `tiempo_efectivo_min = total − pausas − exclusiones aprobadas`; la penalización solo mira la resolución.
"""
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.dependencias import Actor
from core.errors import ErrorAPI, no_encontrado, prohibido
from models.base import CausaExclusionSLA, EstadoPenalizacion, EstadoRegistro, ModalidadContrato, MotivoPausaSLA, Rol, TipoPenalizacion, UnidadTiempo
from models.contratos import Contrato, ContratoSLA
from models.costos import FolioCosto
from models.folios import EstadoFolio, Folio, FolioSLA, TipoFolio
from models.sla import FolioSLAExclusion, FolioSLAPausa, IgualaConsumoPeriodo, PenalizacionPeriodo
from models.seguimiento import FolioClasificacion
from services import alertas_service, auditoria, folio_estados, folios_sla, notificaciones_service
from services.folio_estados import ACTOR_SISTEMA, ActorFolio

# §6.10.1: «Admin prestador (registro) — Admin empresa (aprobación)»; mesa de control y despachador comparten el registro.
REGISTRAN_EXCLUSION = {Rol.superadmin, Rol.admin_prestador, Rol.mesa_control, Rol.despachador}
APRUEBAN_EXCLUSION = {Rol.superadmin, Rol.admin_empresa}
REVISAN_PENALIZACION = {Rol.superadmin, Rol.admin_prestador}
CONSULTAN = (REGISTRAN_EXCLUSION | APRUEBAN_EXCLUSION | REVISAN_PENALIZACION |
             {Rol.admin_un, Rol.supervisor_operadores, Rol.direccion_prestador, Rol.supervisor_prestador})
CERO = Decimal("0")
CENTAVO = Decimal("0.01")
HORAS_MAX = 4320  # §6.10.1: de 1 a 4,320 horas equivalentes
EN_HORAS = {UnidadTiempo.horas: 1, UnidadTiempo.dias: 24, UnidadTiempo.semanas: 168, UnidadTiempo.meses: 720}


def a_horas(valor: int, unidad: UnidadTiempo) -> int:
    """Convierte el tiempo firmado en el contrato a su equivalente en horas y valida el rango de §6.10.1."""
    horas = int(valor) * EN_HORAS[unidad]
    if not 1 <= horas <= HORAS_MAX:
        raise ErrorAPI(422, "SLA_FUERA_DE_RANGO", f"{valor} {unidad.value} equivalen a {horas} horas; el rango es de 1 a {HORAS_MAX}",
                       [{"campo": "tiempo", "minimo": 1, "maximo": HORAS_MAX}])
    return horas


def _minutos(desde: datetime, hasta: datetime) -> int:
    return max(0, int((hasta - desde).total_seconds() // 60))


async def fila(db: AsyncSession, folio: Folio) -> FolioSLA | None:
    return (await db.execute(select(FolioSLA).where(FolioSLA.folio_id == folio.id))).scalar_one_or_none()


# ------------------------------------------------------------------ límites
async def fijar_limites(db: AsyncSession, folio: Folio, f: FolioSLA | None = None) -> FolioSLA | None:
    """Al autorizar: límites en minutos desde `contrato_sla` del contrato vigente y la severidad del folio."""
    f = f or await fila(db, folio) or await folios_sla.registrar_prometido(db, folio) or await fila(db, folio)
    if f is None:
        return None
    if f.autorizado_en is None:
        f.autorizado_en = datetime.now(UTC)
    if f.tiempo_inicio is None:
        # El no crítico que el Admin UN clasificó (P07) arranca en su autorización; los demás, en la captura (§6.10.1).
        clasificado = (await db.execute(select(FolioClasificacion.id).where(FolioClasificacion.folio_id == folio.id))).first()
        f.tiempo_inicio = f.autorizado_en if clasificado else folio.capturado_at
    if f.contrato_sla_id is None and folio.severidad_id is not None:
        equipo = await _equipo(db, folio)
        contrato = await folios_sla.contrato_vigente(db, equipo) if equipo is not None else None
        sla = None
        if contrato is not None:
            sla = (await db.execute(select(ContratoSLA).where(
                ContratoSLA.contrato_id == contrato.id, ContratoSLA.nivel_severidad_id == folio.severidad_id))).scalars().first()
        if sla is not None:
            f.contrato_sla_id = sla.id
    f.limite_respuesta_min = (f.limite_respuesta_min or f.tiempo_respuesta_prometido_horas * 60)
    f.limite_sla_min = (f.limite_sla_min or f.tiempo_resolucion_prometido_horas * 60)
    await db.flush()
    return f


async def _equipo(db: AsyncSession, folio: Folio):
    from models.catalogos import Equipo

    return await db.get(Equipo, folio.equipo_id)


# ------------------------------------------------------------------- pausas
async def abrir_pausa(db: AsyncSession, folio: Folio, motivo: MotivoPausaSLA, notas: str = "") -> FolioSLAPausa | None:
    abierta = (await db.execute(select(FolioSLAPausa).where(
        FolioSLAPausa.folio_id == folio.id, FolioSLAPausa.fin.is_(None)))).scalars().first()
    if abierta is not None:
        return abierta
    p = FolioSLAPausa(folio_id=folio.id, tenant_id=folio.tenant_id, prestador_id=folio.prestador_id, motivo=motivo,
                      inicio=datetime.now(UTC), notas=notas)
    db.add(p)
    await db.flush()
    return p


async def cerrar_pausa(db: AsyncSession, folio: Folio) -> FolioSLAPausa | None:
    p = (await db.execute(select(FolioSLAPausa).where(
        FolioSLAPausa.folio_id == folio.id, FolioSLAPausa.fin.is_(None)))).scalars().first()
    if p is None:
        return None
    p.fin = datetime.now(UTC)
    p.minutos = _minutos(p.inicio, p.fin)
    await db.flush()
    return p


async def minutos_pausados(db: AsyncSession, folio_id: UUID, hasta: datetime | None = None) -> int:
    hasta = hasta or datetime.now(UTC)
    total = 0
    for p in (await db.execute(select(FolioSLAPausa).where(FolioSLAPausa.folio_id == folio_id))).scalars():
        total += p.minutos if p.minutos is not None else _minutos(p.inicio, hasta)
    return total


async def minutos_excluidos(db: AsyncSession, folio_id: UUID) -> int:
    """Solo los períodos aprobados se descuentan (§6.10.1)."""
    total = (await db.execute(select(func.coalesce(func.sum(FolioSLAExclusion.minutos), 0)).where(
        FolioSLAExclusion.folio_id == folio_id, FolioSLAExclusion.aprobada.is_(True)))).scalar_one()
    return int(total or 0)


# ------------------------------------------------------- cálculo y cierre
async def _penalizacion(db: AsyncSession, folio: Folio, f: FolioSLA) -> tuple[Decimal, dict]:
    """Monto fijo o porcentaje sobre el costo validado del folio (P09); sin SLA del contrato no hay penalización."""
    if f.contrato_sla_id is None:
        return CERO, {"motivo": "el contrato no tiene SLA para esta severidad"}
    sla = await db.get(ContratoSLA, f.contrato_sla_id)
    if sla is None or sla.penalizacion_valor in (None, CERO):
        return CERO, {"motivo": "sin penalización configurada"}
    if sla.penalizacion_tipo == TipoPenalizacion.monto:
        return Decimal(sla.penalizacion_valor).quantize(CENTAVO), {"tipo": "monto", "valor": str(sla.penalizacion_valor)}
    costo = (await db.execute(select(FolioCosto).where(FolioCosto.folio_id == folio.id))).scalar_one_or_none()
    base = Decimal(costo.costo_total) if costo is not None else CERO
    monto = (base * Decimal(sla.penalizacion_valor) / Decimal("100")).quantize(CENTAVO)
    return monto, {"tipo": "porcentaje", "valor": str(sla.penalizacion_valor), "base": str(base)}


async def recalcular(db: AsyncSession, folio: Folio, f: FolioSLA | None = None, momento: datetime | None = None) -> FolioSLA | None:
    """Rehace tiempos efectivos, cumplimiento y penalización. Se usa al cerrar y al aprobar una exclusión tardía."""
    f = f or await fila(db, folio)
    if f is None or f.tiempo_inicio is None:
        return f
    ahora = momento or datetime.now(UTC)
    fin = f.tiempo_fin or (folio.fecha_cierre if folio.estado == EstadoFolio.cerrado else None) or ahora
    f.tiempo_pausado_min = await minutos_pausados(db, folio.id, fin)
    f.tiempo_exclusion_min = await minutos_excluidos(db, folio.id)
    descuento = f.tiempo_pausado_min + f.tiempo_exclusion_min
    f.tiempo_efectivo_min = max(0, _minutos(f.tiempo_inicio, fin) - descuento)
    if f.tiempo_respuesta_at is not None:
        f.tiempo_respuesta_efectivo_min = max(0, _minutos(f.tiempo_inicio, f.tiempo_respuesta_at) - descuento)
        f.tiempo_respuesta_real_min = f.tiempo_respuesta_efectivo_min
        f.cumplimiento_respuesta = f.limite_respuesta_min is None or f.tiempo_respuesta_efectivo_min <= f.limite_respuesta_min
    if folio.estado == EstadoFolio.cerrado:
        f.tiempo_resolucion_real_min = f.tiempo_efectivo_min
        dentro = f.limite_sla_min is None or f.tiempo_efectivo_min <= f.limite_sla_min
        if f.excluir_sla_por_cliente:  # P07: la clasificación tardía del cliente no se le cobra al prestador
            dentro = True
            f.penalizacion_detalle_json = {"motivo": "excluido por decisión del cliente (P07)"}
            f.penalizacion_calculada = CERO
        f.cumplimiento_resolucion = dentro
        f.cumplimiento = dentro
        if not dentro:
            f.penalizacion_calculada, f.penalizacion_detalle_json = await _penalizacion(db, folio, f)
        elif not f.excluir_sla_por_cliente:
            f.penalizacion_calculada, f.penalizacion_detalle_json = CERO, {}
    await db.flush()
    return f


async def _avisar(db: AsyncSession, folio: Folio, clave: str, datos: dict[str, Any], asunto: str, cuerpo: str) -> None:
    alerta = await alertas_service.disparar(db, clave, tenant_id=folio.tenant_id, prestador_id=folio.prestador_id,
                                            entidad_tipo="folio", entidad_id=folio.id, datos=datos)
    if alerta is None:
        return
    destinos = await alertas_service.destinatarios(db, clave, tenant_id=folio.tenant_id, prestador_id=folio.prestador_id, un_id=folio.un_id)
    if destinos:
        await notificaciones_service.notificar(db, f"alerta.{clave.lower()}", destinos, {"folio_id": str(folio.id), **datos},
                                               asunto=asunto, cuerpo=cuerpo, url=f"/folios/{folio.id}",
                                               tenant_id=folio.tenant_id, prestador_id=folio.prestador_id)


async def en_riesgo(db: AsyncSession, f: FolioSLA, folio: Folio, umbral_pct: Decimal) -> list[str]:
    """Devuelve las claves disparadas: respuesta sin asignar o resolución sin cerrar al X% del tiempo consumido."""
    claves: list[str] = []
    if f.tiempo_inicio is None:
        return claves
    ahora = datetime.now(UTC)
    transcurrido = max(0, _minutos(f.tiempo_inicio, ahora) - f.tiempo_pausado_min - f.tiempo_exclusion_min)
    if (not f.riesgo_respuesta_avisado and f.limite_respuesta_min and f.tiempo_respuesta_at is None
            and transcurrido * 100 >= f.limite_respuesta_min * int(umbral_pct)):
        f.riesgo_respuesta_avisado = True
        claves.append("SLA_RESPUESTA_EN_RIESGO")
    if (not f.riesgo_resolucion_avisado and f.limite_sla_min and folio.estado != EstadoFolio.cerrado
            and transcurrido * 100 >= f.limite_sla_min * int(umbral_pct)):
        f.riesgo_resolucion_avisado = True
        claves.append("SLA_RESOLUCION_EN_RIESGO")
    return claves


# ------------------------------------------------------------ exclusiones
async def registrar_exclusion(db: AsyncSession, actor: Actor, folio: Folio, *, causa: CausaExclusionSLA, descripcion: str,
                              inicio: datetime, fin: datetime, request: Request | None = None) -> FolioSLAExclusion:
    if actor.rol not in REGISTRAN_EXCLUSION:
        raise prohibido("Solo el prestador registra exclusiones de SLA (§6.10.1)")
    if fin <= inicio:
        raise ErrorAPI(422, "PERIODO_INVALIDO", "El fin de la exclusión debe ser posterior a su inicio")
    if len(descripcion.strip()) < 10:
        raise ErrorAPI(422, "DESCRIPCION_REQUERIDA", "Describe la causa de la exclusión con al menos 10 caracteres")
    e = FolioSLAExclusion(folio_id=folio.id, tenant_id=folio.tenant_id, prestador_id=folio.prestador_id, causa=causa,
                          descripcion=descripcion.strip(), registrado_por=actor.id, timestamp_inicio=inicio,
                          timestamp_fin=fin, minutos=_minutos(inicio, fin))
    db.add(e)
    await db.flush()
    await auditoria.registrar_actor(db, actor, "sla.exclusion_registrada", request, tenant_id=folio.tenant_id,
                                    prestador_id=folio.prestador_id, recurso_tipo="folio_sla_exclusiones", recurso_id=e.id,
                                    despues={"folio": str(folio.id), "causa": causa.value, "minutos": e.minutos})
    await _avisar(db, folio, "EXCLUSION_SLA_PENDIENTE", {"exclusion_id": str(e.id), "causa": causa.value, "minutos": e.minutos},
                  f"Exclusión de SLA por aprobar · {folio.numero_folio}",
                  f"El prestador registró una exclusión de {e.minutos} min por «{causa.value}». Apruébala o recházala.")
    return e


async def decidir_exclusion(db: AsyncSession, actor: Actor, exclusion: FolioSLAExclusion, *, aprobada: bool, razon: str = "",
                            request: Request | None = None) -> FolioSLAExclusion:
    if actor.rol not in APRUEBAN_EXCLUSION:
        raise prohibido("Solo el Admin empresa aprueba o rechaza las exclusiones de SLA (§6.10.1)")
    if exclusion.aprobada is not None:
        raise ErrorAPI(409, "EXCLUSION_YA_DECIDIDA", "La exclusión ya fue aprobada o rechazada")
    if not aprobada and len(razon.strip()) < 3:
        raise ErrorAPI(422, "RAZON_REQUERIDA", "Escribe la razón del rechazo")
    exclusion.aprobada = aprobada
    exclusion.aprobado_por = actor.id
    exclusion.decidida_at = datetime.now(UTC)
    exclusion.razon_decision = razon.strip()
    await db.flush()
    folio = await db.get(Folio, exclusion.folio_id)
    # El folio cerrado es inmutable, pero `folio_sla` no es parte del registro principal: se recalcula.
    f = await recalcular(db, folio)
    await auditoria.registrar_actor(db, actor, "sla.exclusion_decidida", request, tenant_id=exclusion.tenant_id,
                                    prestador_id=exclusion.prestador_id, recurso_tipo="folio_sla_exclusiones",
                                    recurso_id=exclusion.id,
                                    despues={"aprobada": aprobada, "minutos": exclusion.minutos,
                                             "cumplimiento": None if f is None else f.cumplimiento})
    return exclusion


async def pendientes_exclusion(db: AsyncSession, actor: Actor) -> list[FolioSLAExclusion]:
    consulta = select(FolioSLAExclusion).where(FolioSLAExclusion.aprobada.is_(None)).order_by(FolioSLAExclusion.created_at)
    return list((await db.execute(consulta)).scalars())


# ------------------------------------------- penalizaciones e iguala mensual
def _rango(periodo: str) -> tuple[datetime, datetime]:
    anio, mes = (int(x) for x in periodo.split("-"))
    inicio = datetime(anio, mes, 1, tzinfo=UTC)
    fin = datetime(anio + (mes == 12), (mes % 12) + 1, 1, tzinfo=UTC)
    return inicio, fin


async def consolidar_penalizaciones(db: AsyncSession, contrato: Contrato, periodo: str) -> PenalizacionPeriodo:
    """Resumen mensual por contrato con el detalle de folios incumplidos; el Admin prestador lo revisa antes del cierre."""
    inicio, fin = _rango(periodo)
    filas = list((await db.execute(
        select(FolioSLA, Folio).join(Folio, Folio.id == FolioSLA.folio_id).where(
            Folio.tenant_id == contrato.tenant_id, Folio.prestador_id == contrato.prestador_id,
            Folio.estado == EstadoFolio.cerrado, Folio.fecha_cierre >= inicio, Folio.fecha_cierre < fin))).all())
    incumplidos = [(f, folio) for f, folio in filas if f.cumplimiento is False]
    registro = (await db.execute(select(PenalizacionPeriodo).where(
        PenalizacionPeriodo.contrato_id == contrato.id, PenalizacionPeriodo.periodo == periodo))).scalar_one_or_none()
    if registro is None:
        registro = PenalizacionPeriodo(contrato_id=contrato.id, tenant_id=contrato.tenant_id,
                                       prestador_id=contrato.prestador_id, periodo=periodo)
        db.add(registro)
    if registro.estado == EstadoPenalizacion.cerrado:
        return registro
    registro.total_folios = len(filas)
    registro.folios_incumplidos = len(incumplidos)
    registro.monto_penalizacion = sum((Decimal(f.penalizacion_calculada or 0) for f, _ in incumplidos), CERO).quantize(CENTAVO)
    registro.moneda = contrato.moneda or "MXN"
    registro.detalle_json = [
        {"folio_id": str(folio.id), "numero_folio": folio.numero_folio, "severidad": str(folio.severidad_id or ""),
         "limite_min": f.limite_sla_min, "efectivo_min": f.tiempo_efectivo_min, "pausado_min": f.tiempo_pausado_min,
         "excluido_min": f.tiempo_exclusion_min, "penalizacion": str(f.penalizacion_calculada),
         "cierre": folio.fecha_cierre.isoformat() if folio.fecha_cierre else None}
        for f, folio in incumplidos
    ]
    await db.flush()
    return registro


async def revisar_penalizacion(db: AsyncSession, actor: Actor, registro: PenalizacionPeriodo, *, estado: EstadoPenalizacion,
                               request: Request | None = None) -> PenalizacionPeriodo:
    if actor.rol not in REVISAN_PENALIZACION:
        raise prohibido("Solo el Admin prestador revisa y cierra las penalizaciones del período")
    orden = [EstadoPenalizacion.borrador, EstadoPenalizacion.revisado, EstadoPenalizacion.cerrado]
    if orden.index(estado) != orden.index(registro.estado) + 1:
        raise ErrorAPI(409, "TRANSICION_INVALIDA", f"De {registro.estado.value} no se puede pasar a {estado.value}")
    registro.estado = estado
    if estado == EstadoPenalizacion.revisado:
        registro.revisado_por, registro.revisado_at = actor.id, datetime.now(UTC)
    else:
        registro.cerrado_at = datetime.now(UTC)
    await db.flush()
    await auditoria.registrar_actor(db, actor, "sla.penalizacion_revisada", request, tenant_id=registro.tenant_id,
                                    prestador_id=registro.prestador_id, recurso_tipo="penalizaciones_periodo",
                                    recurso_id=registro.id,
                                    despues={"periodo": registro.periodo, "estado": estado.value,
                                             "monto": str(registro.monto_penalizacion)})
    return registro


async def consumo_iguala(db: AsyncSession, contrato: Contrato, periodo: str) -> IgualaConsumoPeriodo | None:
    """Correctivos y preventivos incluidos contra los atendidos; los correctivos de más se identifican por cierre."""
    if contrato.modalidad != ModalidadContrato.iguala:
        return None
    inicio, fin = _rango(periodo)
    folios = list((await db.execute(select(Folio).where(
        Folio.tenant_id == contrato.tenant_id, Folio.prestador_id == contrato.prestador_id,
        Folio.estado == EstadoFolio.cerrado, Folio.fecha_cierre >= inicio, Folio.fecha_cierre < fin
    ).order_by(Folio.fecha_cierre))).scalars())
    correctivos = [f for f in folios if f.tipo_folio == TipoFolio.correctivo]
    preventivos = [f for f in folios if f.tipo_folio == TipoFolio.preventivo]
    incluidos = int(contrato.folios_correctivos_iguala or 0)
    prev_incluidos = int((contrato.preventivos_iguala_json or {}).get("cantidad") or 0)
    registro = (await db.execute(select(IgualaConsumoPeriodo).where(
        IgualaConsumoPeriodo.contrato_id == contrato.id, IgualaConsumoPeriodo.periodo == periodo))).scalar_one_or_none()
    if registro is None:
        registro = IgualaConsumoPeriodo(contrato_id=contrato.id, tenant_id=contrato.tenant_id,
                                        prestador_id=contrato.prestador_id, periodo=periodo)
        db.add(registro)
    registro.correctivos_incluidos = incluidos
    registro.correctivos_atendidos = len(correctivos)
    registro.correctivos_adicionales = max(0, len(correctivos) - incluidos)
    registro.preventivos_incluidos = prev_incluidos
    registro.preventivos_ejecutados = len(preventivos)
    registro.tarifa_mensual = Decimal(contrato.tarifa_iguala_mensual or 0)
    registro.folios_adicionales_json = [
        {"folio_id": str(f.id), "numero_folio": f.numero_folio, "cierre": f.fecha_cierre.isoformat() if f.fecha_cierre else None}
        for f in correctivos[incluidos:]
    ]
    await db.flush()
    if incluidos:
        pct = Decimal(len(correctivos) * 100) / Decimal(incluidos)
        cat = await alertas_service.obtener_catalogo(db, "IGUALA_LIMITE_ALCANZADO")
        conf = await alertas_service.configuracion(db, "IGUALA_LIMITE_ALCANZADO", tenant_id=None, prestador_id=contrato.prestador_id)
        umbral = Decimal(alertas_service.efectiva(cat, conf)["umbral_valor"])
        if pct >= umbral:
            await alertas_service.disparar(db, "IGUALA_LIMITE_ALCANZADO", tenant_id=contrato.tenant_id,
                                           prestador_id=contrato.prestador_id, entidad_tipo="contratos", entidad_id=contrato.id,
                                           datos={"periodo": periodo, "atendidos": len(correctivos), "incluidos": incluidos,
                                                  "porcentaje": str(pct.quantize(CENTAVO))})
    return registro


async def contratos_por_vencer(db: AsyncSession, dias: int = 30) -> list[Contrato]:
    limite = date.today() + timedelta(days=dias)
    return list((await db.execute(select(Contrato).where(
        Contrato.estado == EstadoRegistro.activo, Contrato.fecha_fin <= limite, Contrato.fecha_fin >= date.today()))).scalars())


# ----------------------------------------------------- ganchos de transición
@folio_estados.suscribir
async def _al_transicionar(db: AsyncSession, folio: Folio, anterior: EstadoFolio | None, nuevo: EstadoFolio,
                           _actor: ActorFolio, _contexto: dict) -> None:
    f = await fila(db, folio)
    if nuevo == EstadoFolio.autorizado:
        f = await fijar_limites(db, folio, f)
        return
    if f is None:
        return
    if nuevo == EstadoFolio.reasignado:
        await abrir_pausa(db, folio, MotivoPausaSLA.reasignacion,
                          "§6.10.1: en Fase 1 la reasignación forzada es inmediata; no hay aceptación explícita del técnico")
    elif nuevo == EstadoFolio.pendiente_informacion:
        await abrir_pausa(db, folio, MotivoPausaSLA.pendiente_informacion, "Espera de datos del operador")
    elif anterior in (EstadoFolio.reasignado, EstadoFolio.pendiente_informacion):
        await cerrar_pausa(db, folio)
    if nuevo == EstadoFolio.asignado and f.tiempo_respuesta_at is None:
        f.tiempo_respuesta_at = datetime.now(UTC)
        await recalcular(db, folio, f)  # deja el cumplimiento de respuesta ya evaluado
    if nuevo == EstadoFolio.cerrado:
        await cerrar_pausa(db, folio)
        f.tiempo_fin = folio.fecha_cierre or datetime.now(UTC)
        await recalcular(db, folio, f)
        if f.cumplimiento is False:
            await _avisar(db, folio, "SLA_INCUMPLIDO",
                          {"limite_min": f.limite_sla_min, "efectivo_min": f.tiempo_efectivo_min,
                           "penalizacion": str(f.penalizacion_calculada)},
                          f"SLA incumplido · {folio.numero_folio}",
                          f"El folio cerró en {f.tiempo_efectivo_min} min efectivos contra un límite de {f.limite_sla_min} min. "
                          f"Penalización calculada: ${f.penalizacion_calculada}.")
    await db.flush()


# ------------------------------------------------------------- serialización
def serializar(f: FolioSLA | None, pausas: list[FolioSLAPausa], exclusiones: list[FolioSLAExclusion]) -> dict[str, Any]:
    if f is None:
        return {"disponible": False, "motivo": "El folio no tiene SLA registrado (sin severidad o sin contrato vigente)."}
    return {
        "disponible": True,
        "tiempo_inicio": f.tiempo_inicio, "tiempo_respuesta_at": f.tiempo_respuesta_at, "tiempo_fin": f.tiempo_fin,
        "limite_respuesta_min": f.limite_respuesta_min, "limite_sla_min": f.limite_sla_min,
        "tiempo_pausado_min": f.tiempo_pausado_min, "tiempo_exclusion_min": f.tiempo_exclusion_min,
        "tiempo_efectivo_min": f.tiempo_efectivo_min, "tiempo_respuesta_efectivo_min": f.tiempo_respuesta_efectivo_min,
        "cumplimiento_respuesta": f.cumplimiento_respuesta, "cumplimiento_resolucion": f.cumplimiento_resolucion,
        "cumplimiento": f.cumplimiento, "penalizacion_calculada": str(f.penalizacion_calculada),
        "penalizacion_detalle": f.penalizacion_detalle_json, "excluir_sla_por_cliente": f.excluir_sla_por_cliente,
        "tiempo_respuesta_prometido_horas": f.tiempo_respuesta_prometido_horas,
        "tiempo_resolucion_prometido_horas": f.tiempo_resolucion_prometido_horas,
        "pausas": [{"id": str(p.id), "motivo": p.motivo.value, "inicio": p.inicio, "fin": p.fin, "minutos": p.minutos,
                    "notas": p.notas} for p in pausas],
        "exclusiones": [{"id": str(e.id), "causa": e.causa.value, "descripcion": e.descripcion, "minutos": e.minutos,
                         "inicio": e.timestamp_inicio, "fin": e.timestamp_fin, "aprobada": e.aprobada,
                         "razon_decision": e.razon_decision, "decidida_at": e.decidida_at} for e in exclusiones],
    }


async def detalle(db: AsyncSession, folio: Folio) -> dict[str, Any]:
    f = await fila(db, folio)
    pausas = list((await db.execute(select(FolioSLAPausa).where(FolioSLAPausa.folio_id == folio.id)
                                    .order_by(FolioSLAPausa.inicio))).scalars())
    exclusiones = list((await db.execute(select(FolioSLAExclusion).where(FolioSLAExclusion.folio_id == folio.id)
                                          .order_by(FolioSLAExclusion.created_at))).scalars())
    return serializar(f, pausas, exclusiones)
