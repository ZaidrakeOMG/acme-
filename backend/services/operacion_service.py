"""Operaciones en tiempo real (§6.8.4, §6.8.6, §6.9.6). F2-03.

Lo que vive aquí: la jornada del técnico (con sus pausas), la recepción de posiciones del GPS, el cálculo del
`estatus_operativo`, la sugerencia de llegada por geocerca, el tablero del despachador y el recorrido del técnico.

Reglas de privacidad que el código impone (§6.9.5):

* **Sin jornada activa no se guarda ninguna posición.** El técnico decide cuándo empieza y cuándo termina, y la
  primera vez acepta un aviso de qué se registra y para qué.
* Las posiciones son del **prestador del técnico**: el cliente no las ve ni por API ni por RLS. El técnico ve las
  suyas, y consultar el recorrido de alguien queda registrado como acceso a datos sensibles (P11a).
* Las posiciones viven 90 días (particiones diarias que se sueltan); la hora de llegada y la de cierre de cada
  folio quedan en el historial del folio, que es permanente.

Lo que **no** hace este bloque, por decisión de Dirección: la alerta de desvío de ruta y el ETA por tráfico, que
necesitan la ruta planeada del bloque de optimización de rutas. `TECNICO_DESVIO_RUTA` sigue en Fase 2.
"""
import logging
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import Request
from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import config
from core.dependencias import Actor
from core.errors import ErrorAPI, no_encontrado, prohibido
from models.auditoria import ConfiguracionPrestador
from models.base import Rol
from models.catalogos import EstadoActivo, Tecnico
from models.folios import ESTADOS_ABIERTOS, EstadoFolio, Folio
from models.operaciones import (
    AlertaOperacionSeguimiento, CerradaPorJornada, EstadoJornada, EstatusOperativo, JornadaPausa, JornadaTecnico,
    MotivoPausaJornada, RespuestaAlertaTecnico, TecnicoPosicion,
)
from models.unidades import UnidadNegocio
from models.usuarios import Usuario
from services import auditoria, push_service
from services.ws_manager import gestor

log = logging.getLogger("acma.operacion")

# §6.8.4 «Arquitectura de actualización GPS»: las frecuencias son literales del diseño. El servidor no las impone
# (quien manda es la app), pero las publica para que la app y la pantalla hablen del mismo número.
FRECUENCIAS = {"jornada_activa_s": 30, "pausa_s": 300, "bateria_baja_s": 120, "bateria_baja_pct": 20}
MAX_LOTE = 60  # posiciones por petición: media hora de jornada a 30 s
PRECISION_MAXIMA_M = 500  # una lectura peor que esto no sirve para nada operativo y se descarta
TTL_REDIS_S = 120  # §6.8.4: la posición actual vive 2 minutos en Redis
RADIO_GEOCERCA_M = 150  # sugerencia de llegada (configurable por prestador)
HORAS_CIERRE_AUTOMATICO = 2  # jornada sin actividad que el sistema cierra
MINUTOS_SIN_SENAL = 15  # default del catálogo de alertas (TECNICO_SIN_SENAL)
MINUTOS_TIEMPO_MUERTO = 20
RADIO_TIEMPO_MUERTO_M = 50
MINUTOS_ESCALACION = 10
HORAS_RECORRIDO = 2  # lo que la pantalla dibuja del rastro de un técnico

# Quiénes ven el tablero: los cuatro roles que nombra §6.8.4 y nada más. La Mesa de control entra como lectura.
VEN_TABLERO = (Rol.superadmin, Rol.admin_prestador, Rol.despachador, Rol.mesa_control)
SOLO_LECTURA = (Rol.mesa_control,)
ESTADOS_ACTIVOS = (EstadoFolio.autorizado, EstadoFolio.asignado, EstadoFolio.en_camino, EstadoFolio.en_ejecucion,
                   EstadoFolio.pendiente_refaccion)

AVISO_GEOLOCALIZACION = (
    "Mientras tu jornada esté iniciada, ACMA registra la ubicación de tu teléfono cada 30 segundos (cada 5 minutos "
    "en pausa) para que el despachador sepa dónde estás, pueda apoyarte si te detienes y pueda decirle al cliente a "
    "qué hora llegas. No se registra nada cuando cierras la jornada, ni cuando la app está cerrada o el teléfono "
    "bloqueado. El recorrido se guarda 90 días y solo lo ve el personal de tu prestador: el cliente nunca ve tu "
    "ubicación. Consultar tu recorrido queda registrado en la bitácora de accesos."
)


# ----------------------------------------------------------------- configuración por prestador

async def ajuste(db: AsyncSession, prestador_id: UUID | None, clave: str, default: Any) -> Any:
    """Valor de `configuracion_prestador` (clave/valor JSONB) con su default de código."""
    if prestador_id is None:
        return default
    valor = (await db.execute(select(ConfiguracionPrestador.valor).where(
        ConfiguracionPrestador.prestador_id == prestador_id,
        ConfiguracionPrestador.clave == clave))).scalar()
    return default if valor is None else valor


async def parametros(db: AsyncSession, prestador_id: UUID | None) -> dict[str, Any]:
    """Lo que la app del técnico y el tablero necesitan saber del prestador."""
    return {
        "frecuencias": FRECUENCIAS,
        "geocerca_radio_m": int(await ajuste(db, prestador_id, "operacion.geocerca_radio_m", RADIO_GEOCERCA_M)),
        "jornada_cierre_horas": float(await ajuste(db, prestador_id, "operacion.jornada_cierre_horas",
                                                   HORAS_CIERRE_AUTOMATICO)),
        "sin_senal_min": int(await umbral_alerta(db, prestador_id, "TECNICO_SIN_SENAL", MINUTOS_SIN_SENAL)),
        "tiempo_muerto_min": int(await umbral_alerta(db, prestador_id, "TECNICO_TIEMPO_MUERTO",
                                                     MINUTOS_TIEMPO_MUERTO)),
        "aviso_geolocalizacion": AVISO_GEOLOCALIZACION,
        "max_lote": MAX_LOTE,
        "precision_maxima_m": PRECISION_MAXIMA_M,
        "horas_recorrido": HORAS_RECORRIDO,
        # F2-06: la regla de desvío ya opera; el texto explica cómo se mide para que el tablero lo diga igual.
        "desvio_ruta": ("El desvío se marca cuando el técnico se sale del corredor de su ruta más de los "
                        "metros y los minutos configurados en Rutas del día"),
    }


async def umbral_alerta(db: AsyncSession, prestador_id: UUID | None, clave: str, default: float) -> float:
    from services import alertas_service

    try:
        return float(await alertas_service.umbral(db, clave, prestador_id=prestador_id))
    except Exception:  # noqa: BLE001 — sin catálogo (pruebas aisladas) se usa el default del diseño
        return default


# ----------------------------------------------------------------- técnico y jornada

async def tecnico_del_usuario(db: AsyncSession, usuario_id: UUID) -> Tecnico:
    t = (await db.execute(select(Tecnico).where(Tecnico.usuario_id == usuario_id))).scalar_one_or_none()
    if t is None:
        raise prohibido("Tu usuario no tiene ficha de técnico")
    return t


async def jornada_abierta(db: AsyncSession, tecnico_id: UUID) -> JornadaTecnico | None:
    return (await db.execute(select(JornadaTecnico).where(
        JornadaTecnico.tecnico_id == tecnico_id,
        JornadaTecnico.estado != EstadoJornada.cerrada))).scalar_one_or_none()


async def pausa_abierta(db: AsyncSession, jornada_id: UUID) -> JornadaPausa | None:
    return (await db.execute(select(JornadaPausa).where(
        JornadaPausa.jornada_id == jornada_id, JornadaPausa.fin.is_(None)))).scalar_one_or_none()


async def iniciar_jornada(db: AsyncSession, actor: Actor, *, dispositivo_id: str = "",
                          acepta_aviso: bool = False, request: Request | None = None) -> JornadaTecnico:
    """§6.8.4: sin jornada no se envía ninguna posición. La primera vez hay que aceptar el aviso de privacidad."""
    tecnico = await tecnico_del_usuario(db, actor.id)
    abierta = await jornada_abierta(db, tecnico.id)
    if abierta is not None:
        return abierta
    ya_acepto = (await db.execute(select(func.count()).select_from(JornadaTecnico).where(
        JornadaTecnico.tecnico_id == tecnico.id, JornadaTecnico.aviso_aceptado_at.is_not(None)))).scalar() or 0
    if not ya_acepto and not acepta_aviso:
        raise ErrorAPI(409, "AVISO_NO_ACEPTADO",
                       "Antes de iniciar tu jornada tienes que aceptar el aviso de registro de ubicación",
                       [{"aviso": AVISO_GEOLOCALIZACION}])
    ahora = datetime.now(UTC)
    jornada = JornadaTecnico(prestador_id=tecnico.prestador_id, tecnico_id=tecnico.id, inicio=ahora,
                             estado=EstadoJornada.activa, dispositivo_id=(dispositivo_id or "")[:80],
                             aviso_aceptado_at=ahora if (acepta_aviso or not ya_acepto) else None)
    db.add(jornada)
    await db.flush()
    await _fijar_estatus(db, tecnico, EstatusOperativo.en_ruta)
    await auditoria.registrar_actor(db, actor, "operacion.jornada_iniciada", request,
                                    prestador_id=tecnico.prestador_id, recurso_tipo="jornada_tecnico",
                                    recurso_id=jornada.id,
                                    despues={"dispositivo": jornada.dispositivo_id,
                                             "aviso_aceptado": jornada.aviso_aceptado_at is not None})
    await publicar(db, tecnico.prestador_id, {"evento": "jornada", "tecnico_id": str(tecnico.id),
                                              "estado": "activa"})
    return jornada


async def cerrar_jornada(db: AsyncSession, actor: Actor, *, jornada: JornadaTecnico | None = None,
                         cerrada_por: CerradaPorJornada = CerradaPorJornada.tecnico,
                         request: Request | None = None) -> JornadaTecnico:
    if jornada is None:
        tecnico = await tecnico_del_usuario(db, actor.id)
        jornada = await jornada_abierta(db, tecnico.id)
        if jornada is None:
            raise ErrorAPI(409, "SIN_JORNADA", "No tienes una jornada abierta")
    tecnico = await db.get(Tecnico, jornada.tecnico_id)
    pausa = await pausa_abierta(db, jornada.id)
    ahora = datetime.now(UTC)
    if pausa is not None:
        pausa.fin = ahora
    jornada.estado, jornada.fin, jornada.cerrada_por = EstadoJornada.cerrada, ahora, cerrada_por
    await db.flush()
    if tecnico is not None:
        await _fijar_estatus(db, tecnico, EstatusOperativo.fuera_de_jornada)
        await publicar(db, tecnico.prestador_id, {"evento": "jornada", "tecnico_id": str(tecnico.id),
                                                  "estado": "cerrada", "cerrada_por": cerrada_por.value})
    await auditoria.registrar(db, "operacion.jornada_cerrada",
                              actor_id=actor.id if actor else None,
                              actor_rol=actor.rol.value if actor else "sistema",
                              prestador_id=jornada.prestador_id, request=request,
                              recurso_tipo="jornada_tecnico", recurso_id=jornada.id,
                              despues={"cerrada_por": cerrada_por.value, "posiciones": jornada.posiciones})
    return jornada


async def pausar(db: AsyncSession, actor: Actor, *, motivo: str = "otro", nota: str = "") -> JornadaPausa:
    tecnico = await tecnico_del_usuario(db, actor.id)
    jornada = await jornada_abierta(db, tecnico.id)
    if jornada is None:
        raise ErrorAPI(409, "SIN_JORNADA", "Inicia tu jornada antes de pausarla")
    if await pausa_abierta(db, jornada.id) is not None:
        raise ErrorAPI(409, "YA_EN_PAUSA", "Tu jornada ya está en pausa")
    pausa = JornadaPausa(prestador_id=jornada.prestador_id, jornada_id=jornada.id,
                         motivo=MotivoPausaJornada(motivo), nota=nota[:200])
    db.add(pausa)
    jornada.estado = EstadoJornada.pausa
    await db.flush()
    await _fijar_estatus(db, tecnico, EstatusOperativo.pausa)
    await publicar(db, jornada.prestador_id, {"evento": "jornada", "tecnico_id": str(tecnico.id),
                                              "estado": "pausa", "motivo": pausa.motivo.value})
    return pausa


async def reanudar(db: AsyncSession, actor: Actor) -> JornadaTecnico:
    tecnico = await tecnico_del_usuario(db, actor.id)
    jornada = await jornada_abierta(db, tecnico.id)
    if jornada is None:
        raise ErrorAPI(409, "SIN_JORNADA", "No tienes una jornada abierta")
    pausa = await pausa_abierta(db, jornada.id)
    if pausa is None:
        raise ErrorAPI(409, "SIN_PAUSA", "Tu jornada no está en pausa")
    pausa.fin = datetime.now(UTC)
    jornada.estado = EstadoJornada.activa
    await db.flush()
    await recalcular_estatus(db, tecnico)
    await publicar(db, jornada.prestador_id, {"evento": "jornada", "tecnico_id": str(tecnico.id),
                                              "estado": "activa"})
    return jornada


async def mi_jornada(db: AsyncSession, actor: Actor) -> dict[str, Any]:
    tecnico = await tecnico_del_usuario(db, actor.id)
    jornada = await jornada_abierta(db, tecnico.id)
    pausa = await pausa_abierta(db, jornada.id) if jornada else None
    cuantas = 0
    if jornada is not None:
        cuantas = (await db.execute(select(func.count()).select_from(TecnicoPosicion).where(
            TecnicoPosicion.jornada_id == jornada.id))).scalar() or 0
    return {
        "tecnico_id": tecnico.id, "estatus": tecnico.estatus_operativo.value,
        "jornada": None if jornada is None else {
            "id": jornada.id, "inicio": jornada.inicio, "estado": jornada.estado.value,
            "dispositivo_id": jornada.dispositivo_id, "posiciones": cuantas,
            "pausa_desde": pausa.inicio if pausa else None,
            "pausa_motivo": pausa.motivo.value if pausa else None},
        "aviso_aceptado": (await db.execute(select(func.count()).select_from(JornadaTecnico).where(
            JornadaTecnico.tecnico_id == tecnico.id, JornadaTecnico.aviso_aceptado_at.is_not(None)))).scalar() > 0,
        **await parametros(db, tecnico.prestador_id),
    }


# ----------------------------------------------------------------- posiciones

async def registrar_posiciones(db: AsyncSession, actor: Actor, lote: list[dict[str, Any]]) -> dict[str, Any]:
    """Guarda un lote de posiciones de la app del técnico. Sin jornada activa no se acepta ninguna (§6.8.4).

    Las que llegan tarde (se guardaron sin señal) entran marcadas como `tardia` y **no mueven** la última posición
    si son más viejas que la que ya está: el mapa no debe dar saltos falsos al reconectar.
    """
    tecnico = await tecnico_del_usuario(db, actor.id)
    jornada = await jornada_abierta(db, tecnico.id)
    if jornada is None:
        raise ErrorAPI(409, "SIN_JORNADA", "Sin jornada iniciada no se registran posiciones")
    if len(lote) > MAX_LOTE:
        raise ErrorAPI(422, "LOTE_DEMASIADO_GRANDE", f"Manda como máximo {MAX_LOTE} posiciones por envío")
    ahora = datetime.now(UTC)
    aceptadas, descartadas = 0, []
    ultima: dict[str, Any] | None = None
    for cruda in lote:
        try:
            punto = _validar_posicion(cruda)
        except ValueError as e:
            descartadas.append({"capturada_at": str(cruda.get("capturada_at")), "motivo": str(e)})
            continue
        tardia = bool(cruda.get("tardia")) or (ahora - punto["capturada_at"]) > timedelta(minutes=2)
        db.add(TecnicoPosicion(
            prestador_id=tecnico.prestador_id, tecnico_id=tecnico.id, jornada_id=jornada.id,
            posicion=_wkt(punto["lat"], punto["lng"]), precision_m=punto["precision_m"],
            velocidad_mps=punto["velocidad_mps"], rumbo=punto["rumbo"], bateria_pct=punto["bateria_pct"],
            capturada_at=punto["capturada_at"], recibida_at=ahora, tardia=tardia))
        aceptadas += 1
        if ultima is None or punto["capturada_at"] > ultima["capturada_at"]:
            ultima = punto
    jornada.posiciones = (jornada.posiciones or 0) + aceptadas
    await db.flush()

    sugerencia = None
    if ultima is not None and (tecnico.ultima_posicion_at is None or ultima["capturada_at"] > tecnico.ultima_posicion_at):
        tecnico.ultima_posicion = _wkt(ultima["lat"], ultima["lng"])
        tecnico.ultima_posicion_at = ultima["capturada_at"]
        tecnico.ultima_precision_m = ultima["precision_m"]
        if ultima["bateria_pct"] is not None:
            tecnico.ultima_bateria_pct = ultima["bateria_pct"]
        await db.flush()
        await _guardar_en_redis(tecnico, ultima)
        await recalcular_estatus(db, tecnico)
        sugerencia = await sugerir_llegada(db, tecnico, ultima["lat"], ultima["lng"])
        await publicar(db, tecnico.prestador_id, {
            "evento": "posicion", "tecnico_id": str(tecnico.id), "lat": ultima["lat"], "lng": ultima["lng"],
            "precision_m": float(ultima["precision_m"]) if ultima["precision_m"] is not None else None,
            "bateria_pct": ultima["bateria_pct"], "capturada_at": ultima["capturada_at"].isoformat(),
            "estatus": tecnico.estatus_operativo.value})
    return {"aceptadas": aceptadas, "descartadas": descartadas, "jornada_id": jornada.id,
            "estatus": tecnico.estatus_operativo.value, "sugerencia_llegada": sugerencia}


def _validar_posicion(cruda: dict[str, Any]) -> dict[str, Any]:
    try:
        lat, lng = float(cruda["lat"]), float(cruda["lng"])
    except (KeyError, TypeError, ValueError):
        raise ValueError("faltan lat y lng")
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        raise ValueError("coordenadas fuera de rango")
    capturada = cruda.get("capturada_at")
    if isinstance(capturada, str):
        capturada = datetime.fromisoformat(capturada.replace("Z", "+00:00"))
    if not isinstance(capturada, datetime):
        raise ValueError("falta la hora de captura del dispositivo")
    if capturada.tzinfo is None:
        capturada = capturada.replace(tzinfo=UTC)
    ahora = datetime.now(UTC)
    if capturada > ahora + timedelta(minutes=5):
        raise ValueError("la hora del dispositivo está en el futuro")
    if capturada < ahora - timedelta(days=2):
        raise ValueError("la posición es de hace más de dos días")
    precision = cruda.get("precision_m")
    precision = None if precision is None else Decimal(str(round(float(precision), 1)))
    if precision is not None and float(precision) > PRECISION_MAXIMA_M:
        raise ValueError(f"precisión de {precision} m: peor que {PRECISION_MAXIMA_M} m no sirve")
    bateria = cruda.get("bateria_pct")
    bateria = None if bateria is None else max(0, min(100, int(bateria)))
    return {"lat": lat, "lng": lng, "capturada_at": capturada, "precision_m": precision,
            "velocidad_mps": None if cruda.get("velocidad_mps") is None else Decimal(str(round(float(cruda["velocidad_mps"]), 2))),
            "rumbo": None if cruda.get("rumbo") is None else Decimal(str(round(float(cruda["rumbo"]) % 360, 1))),
            "bateria_pct": bateria}


def _wkt(lat: float, lng: float):
    from geoalchemy2 import WKTElement

    return WKTElement(f"POINT({lng} {lat})", srid=4326)


_redis = None


async def _cliente_redis():
    """Un solo cliente (con su pool) para todo el proceso: a 8 posiciones por segundo, abrir uno por lote sobra."""
    global _redis
    if config.tiempo_real_modo != "redis":
        return None
    if _redis is None:
        import redis.asyncio as redis_async

        _redis = redis_async.from_url(config.redis_url, decode_responses=True)
    return _redis


async def _guardar_en_redis(tecnico: Tecnico, punto: dict[str, Any]) -> None:
    """§6.8.4: la posición actual vive en Redis con TTL de 2 minutos; la base guarda el historial."""
    try:
        cliente = await _cliente_redis()
        if cliente is None:
            return
        import json

        await cliente.set(clave_redis(tecnico.id), json.dumps({
            "lat": punto["lat"], "lng": punto["lng"], "capturada_at": punto["capturada_at"].isoformat(),
            "prestador_id": str(tecnico.prestador_id)}), ex=TTL_REDIS_S)
    except Exception as e:  # noqa: BLE001 — sin Redis el tablero lee de la base; no se pierde nada
        log.debug("Posición no cacheada en Redis: %s", e)


def clave_redis(tecnico_id: UUID) -> str:
    return f"acma:posicion:{tecnico_id}"


async def posicion_en_redis(tecnico_id: UUID) -> dict[str, Any] | None:
    try:
        cliente = await _cliente_redis()
        if cliente is None:
            return None
        import json

        crudo = await cliente.get(clave_redis(tecnico_id))
        return json.loads(crudo) if crudo else None
    except Exception:  # noqa: BLE001
        return None


# ----------------------------------------------------------------- estatus y geocerca

async def _fijar_estatus(db: AsyncSession, tecnico: Tecnico, estatus: EstatusOperativo) -> None:
    """Guarda el estatus y **desde cuándo** lo tiene: el tablero ordena por ese tiempo (§6.8.4)."""
    if tecnico.estatus_operativo != estatus or tecnico.estatus_operativo_desde is None:
        tecnico.estatus_operativo = estatus
        tecnico.estatus_operativo_desde = datetime.now(UTC)
        await db.flush()


ZONA_OPERACION = "America/Mexico_City"


def hora_local(momento: datetime, zona: str | None = None) -> str:
    """HH:MM en la zona donde trabaja la gente. Las etiquetas de las alertas las lee el despachador en el piso:
    en UTC leía seis horas adelantadas («sin señal desde las 15:07» cuando eran las 9:07 de la mañana)."""
    return momento.astimezone(ZoneInfo(zona or ZONA_OPERACION)).strftime("%H:%M")


async def recalcular_estatus(db: AsyncSession, tecnico: Tecnico, *, ahora: datetime | None = None,
                             publicar_cambio: bool = True) -> EstatusOperativo:
    """§6.8.4: en_servicio, en_ruta, pausa, sin_senal o fuera_de_jornada, en ese orden de precedencia."""
    ahora = ahora or datetime.now(UTC)
    jornada = await jornada_abierta(db, tecnico.id)
    anterior = tecnico.estatus_operativo
    if jornada is None:
        nuevo = EstatusOperativo.fuera_de_jornada
    elif jornada.estado == EstadoJornada.pausa:
        nuevo = EstatusOperativo.pausa
    else:
        minutos = await umbral_alerta(db, tecnico.prestador_id, "TECNICO_SIN_SENAL", MINUTOS_SIN_SENAL)
        sin_senal = (tecnico.ultima_posicion_at is None
                     or tecnico.ultima_posicion_at < ahora - timedelta(minutes=minutos))
        if sin_senal:
            nuevo = EstatusOperativo.sin_senal
        else:
            estados = set((await db.execute(select(Folio.estado).where(
                Folio.tecnico_id == tecnico.usuario_id,
                Folio.estado.in_(ESTADOS_ACTIVOS)))).scalars())
            if EstadoFolio.en_ejecucion in estados:
                nuevo = EstatusOperativo.en_servicio
            else:
                nuevo = EstatusOperativo.en_ruta
    await _fijar_estatus(db, tecnico, nuevo)
    if publicar_cambio and nuevo != anterior:
        await publicar(db, tecnico.prestador_id, {"evento": "estatus", "tecnico_id": str(tecnico.id),
                                                  "estatus": nuevo.value})
    return nuevo


async def sugerir_llegada(db: AsyncSession, tecnico: Tecnico, lat: float, lng: float) -> dict[str, Any] | None:
    """Geocerca (§6.8.6): dentro del radio de la UN del folio en camino se **propone** confirmar la llegada.

    No se transiciona sola: la confirmación sigue siendo del técnico. La entrada a la geocerca se guarda en el
    historial del folio como dato informativo del SLA de respuesta (no cambia la regla de P10).
    """
    folio = (await db.execute(select(Folio).where(
        Folio.tecnico_id == tecnico.usuario_id, Folio.estado == EstadoFolio.en_camino
    ).order_by(Folio.orden_en_ruta.nulls_last(), Folio.capturado_at).limit(1))).scalar_one_or_none()
    if folio is None:
        return None
    radio = int(await ajuste(db, tecnico.prestador_id, "operacion.geocerca_radio_m", RADIO_GEOCERCA_M))
    distancia = (await db.execute(text(
        "SELECT ST_Distance(ubicacion, ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography) "
        "FROM unidades_negocio WHERE id = :un"), {"lng": lng, "lat": lat, "un": folio.un_id})).scalar()
    if distancia is None:
        return None
    if float(distancia) > radio:
        return None
    await _marcar_entrada_geocerca(db, folio, round(float(distancia), 1), radio)
    un = await db.get(UnidadNegocio, folio.un_id)
    return {"folio_id": folio.id, "numero_folio": folio.numero_folio, "distancia_m": round(float(distancia), 1),
            "radio_m": radio, "sucursal": f"{un.codigo} {un.nombre}" if un else "",
            "mensaje": "Parece que ya llegaste: confirma tu llegada para empezar la atención"}


async def _marcar_entrada_geocerca(db: AsyncSession, folio: Folio, distancia: float, radio: int) -> None:
    from models.folios import FolioEstadoHistorial

    ya = (await db.execute(select(func.count()).select_from(FolioEstadoHistorial).where(
        FolioEstadoHistorial.folio_id == folio.id,
        FolioEstadoHistorial.evento == "entrada_geocerca"))).scalar() or 0
    if ya:
        return
    db.add(FolioEstadoHistorial(
        folio_id=folio.id, tenant_id=folio.tenant_id, prestador_id=folio.prestador_id,
        estado_anterior=folio.estado, estado_nuevo=folio.estado, evento="entrada_geocerca", actor_rol="sistema",
        notas=f"El técnico entró al radio de {radio} m de la unidad ({distancia} m). Dato informativo del SLA de "
              f"respuesta; la llegada la confirma el técnico.",
        datos_contexto_json={"distancia_m": distancia, "radio_m": radio}))
    await db.flush()


# ----------------------------------------------------------------- tiempo real

async def publicar(db: AsyncSession, prestador_id: UUID | None, evento: dict[str, Any]) -> None:
    """Un canal por prestador: las posiciones de un prestador no llegan al tablero de otro (§6.9.5)."""
    if prestador_id is None:
        return
    await gestor.publicar_canal(f"operacion:{prestador_id}", {**evento, "prestador_id": str(prestador_id)})


# ----------------------------------------------------------------- tablero del despachador

def _alcance_tecnicos(actor: Actor):
    if actor.es_superadmin:
        return Tecnico.id.is_not(None)
    return Tecnico.prestador_id == actor.prestador_id


async def exigir_tablero(actor: Actor) -> None:
    if actor.rol not in VEN_TABLERO:
        raise prohibido("Tu rol no ve la pantalla de operaciones (§6.8.4)")


async def tablero(db: AsyncSession, actor: Actor) -> dict[str, Any]:
    """Todo lo que la pantalla dibuja de un golpe: técnicos, folios del día, alertas e indicadores (§6.8.4)."""
    await exigir_tablero(actor)
    ahora = datetime.now(UTC)
    return {
        "generado_at": ahora,
        "tecnicos": await panel_tecnicos(db, actor, ahora=ahora),
        "folios": await panel_folios(db, actor),
        "unidades": await panel_unidades(db, actor),
        "alertas": await panel_alertas(db, actor),
        "indicadores": await indicadores(db, actor),
        "parametros": await parametros(db, actor.prestador_id),
        "solo_lectura": actor.rol in SOLO_LECTURA,
    }


async def panel_tecnicos(db: AsyncSession, actor: Actor, *, ahora: datetime | None = None) -> list[dict[str, Any]]:
    ahora = ahora or datetime.now(UTC)
    filas = list((await db.execute(select(Tecnico).where(
        _alcance_tecnicos(actor), Tecnico.estado == EstadoActivo.activo))).scalars())
    if not filas:
        return []
    usuarios = {u.id: u for u in (await db.execute(select(Usuario).where(
        Usuario.id.in_({t.usuario_id for t in filas})))).scalars()}
    jornadas = {j.tecnico_id: j for j in (await db.execute(select(JornadaTecnico).where(
        JornadaTecnico.tecnico_id.in_({t.id for t in filas}),
        JornadaTecnico.estado != EstadoJornada.cerrada))).scalars()}
    pendientes = dict((await db.execute(select(Folio.tecnico_id, func.count()).where(
        Folio.tecnico_id.in_({t.usuario_id for t in filas}),
        Folio.estado.in_(ESTADOS_ACTIVOS)).group_by(Folio.tecnico_id))).all())
    # La última posición se lee con SQL porque la columna es GEOGRAPHY: se devuelve ya separada en lat y lng.
    puntos = {f[0]: (f[1], f[2]) for f in (await db.execute(text(
        "SELECT id::text, ST_Y(ultima_posicion::geometry) AS lat, ST_X(ultima_posicion::geometry) AS lng "
        "  FROM tecnicos WHERE ultima_posicion IS NOT NULL AND id = ANY(:ids)"),
        {"ids": [str(t.id) for t in filas]})).all()}
    seguimientos = {s.tecnico_id: s for s in (await db.execute(select(AlertaOperacionSeguimiento).where(
        AlertaOperacionSeguimiento.tecnico_id.in_({t.id for t in filas}),
        AlertaOperacionSeguimiento.created_at >= ahora - timedelta(hours=8)
    ).order_by(AlertaOperacionSeguimiento.created_at))).scalars()}
    salida = []
    for t in filas:
        jornada = jornadas.get(t.id)
        usuario = usuarios.get(t.usuario_id)
        seguimiento = seguimientos.get(t.id)
        coord = puntos.get(str(t.id))
        # «Tiempo en el estatus actual»: desde el último cambio de estatus; si nunca cambió, desde que abrió
        # la jornada (los técnicos que ya estaban en jornada antes de F2-03 no tienen esa marca).
        desde = t.estatus_operativo_desde or (jornada.inicio if jornada else t.ultima_posicion_at)
        salida.append({
            "tecnico_id": t.id, "usuario_id": t.usuario_id,
            "nombre": usuario.nombre if usuario else "", "numero_empleado": t.numero_empleado,
            "estatus": t.estatus_operativo.value, "estatus_texto": NOMBRE_ESTATUS[t.estatus_operativo],
            "en_jornada": jornada is not None, "jornada_desde": jornada.inicio if jornada else None,
            "minutos_en_estatus": int((ahora - desde).total_seconds() // 60) if desde else None,
            "folios_pendientes": int(pendientes.get(t.usuario_id, 0)),
            "lat": coord[0] if coord else None, "lng": coord[1] if coord else None,
            "ultima_posicion_at": t.ultima_posicion_at, "precision_m": t.ultima_precision_m,
            "bateria_pct": t.ultima_bateria_pct, "vehiculo_placas": t.vehiculo_placas,
            "telefono": t.telefono,
            "alerta": None if seguimiento is None or seguimiento.respondida_at is not None else {
                "tipo": seguimiento.tipo, "desde": seguimiento.created_at,
                "escalada": seguimiento.escalada_at is not None},
            "respuesta_tecnico": seguimiento.respuesta_tecnico.value
            if seguimiento and seguimiento.respuesta_tecnico else None,
        })
    salida.sort(key=lambda x: (ORDEN_ESTATUS.get(x["estatus"], 9), -x["folios_pendientes"], x["nombre"]))
    return salida


NOMBRE_ESTATUS = {
    EstatusOperativo.en_servicio: "En servicio",
    EstatusOperativo.en_ruta: "En ruta",
    EstatusOperativo.pausa: "En pausa",
    EstatusOperativo.sin_senal: "Sin señal",
    EstatusOperativo.fuera_de_jornada: "Fuera de jornada",
}
ORDEN_ESTATUS = {"sin_senal": 0, "en_servicio": 1, "en_ruta": 2, "pausa": 3, "fuera_de_jornada": 4}


async def panel_folios(db: AsyncSession, actor: Actor, *, ahora: datetime | None = None) -> list[dict[str, Any]]:
    """Folios abiertos y capturados hoy con contador regresivo del SLA de P10 y su técnico.

    El contador se arma con los datos de `folios_sla` en una sola consulta: la pantalla se refresca cada pocos
    segundos y recalcular folio por folio (como hace el detalle) costaría tres consultas por folio.
    """
    from models.folios import FolioSLA
    from services import folios_captura_service

    ahora = ahora or datetime.now(UTC)
    hoy = datetime.combine(date.today(), time.min, tzinfo=UTC)
    # Mostrar también los folios abiertos en espera de revisión/asignación, aunque se
    # hayan capturado ayer: antes el tablero ocultaba F-000001 y otros pendientes.
    # La lista de unidades con servicio operativo sigue contando solo ESTADOS_ACTIVOS.
    consulta = select(Folio).where(or_(Folio.estado.in_(ESTADOS_ABIERTOS), Folio.capturado_at >= hoy))
    filtro = folios_captura_service.filtro_alcance(actor)
    if filtro is not None:
        consulta = consulta.where(filtro)
    folios = list((await db.execute(consulta.order_by(Folio.capturado_at.desc()).limit(300))).scalars())
    if not folios:
        return []
    unidades = {u.id: u for u in (await db.execute(select(UnidadNegocio).where(
        UnidadNegocio.id.in_({f.un_id for f in folios})))).scalars()}
    nombres = {u.id: u.nombre for u in (await db.execute(select(Usuario).where(
        Usuario.id.in_({f.tecnico_id for f in folios if f.tecnico_id})))).scalars()}
    slas = {s.folio_id: s for s in (await db.execute(select(FolioSLA).where(
        FolioSLA.folio_id.in_({f.id for f in folios})))).scalars()}
    umbral_pct = int(await umbral_alerta(db, actor.prestador_id, "SLA_RESOLUCION_EN_RIESGO", 80))
    salida = []
    for f in folios:
        un = unidades.get(f.un_id)
        salida.append({
            "folio_id": f.id, "numero_folio": f.numero_folio, "estado": f.estado.value,
            "tecnico_id": f.tecnico_id, "tecnico": nombres.get(f.tecnico_id),
            "un_id": f.un_id, "sucursal": f"{un.codigo} {un.nombre}" if un else "",
            "capturado_at": f.capturado_at,
            **_contador_sla(slas.get(f.id), f, ahora, umbral_pct),
        })
    salida.sort(key=lambda x: (not x["incumplido"], not x["en_riesgo"],
                               x["minutos_restantes"] if x["minutos_restantes"] is not None else 10 ** 6,
                               x["capturado_at"]))
    return salida


def _contador_sla(sla, folio: Folio, ahora: datetime, umbral_pct: int) -> dict[str, Any]:
    """Minutos que faltan para vencer el SLA de resolución, con las pausas y exclusiones ya descontadas (P10)."""
    if sla is None or sla.tiempo_inicio is None or not sla.limite_sla_min:
        return {"sla_disponible": False, "minutos_restantes": None, "limite_sla_min": None,
                "en_riesgo": False, "incumplido": False, "cumplimiento": None}
    descontado = (sla.tiempo_pausado_min or 0) + (sla.tiempo_exclusion_min or 0)
    if folio.estado == EstadoFolio.cerrado and sla.tiempo_fin:
        transcurrido = max(0, int((sla.tiempo_fin - sla.tiempo_inicio).total_seconds() // 60) - descontado)
    else:
        transcurrido = max(0, int((ahora - sla.tiempo_inicio).total_seconds() // 60) - descontado)
    restantes = sla.limite_sla_min - transcurrido
    incumplido = sla.cumplimiento is False or restantes < 0
    en_riesgo = not incumplido and transcurrido * 100 >= sla.limite_sla_min * umbral_pct
    return {"sla_disponible": True, "minutos_restantes": restantes, "limite_sla_min": sla.limite_sla_min,
            "limite_respuesta_min": sla.limite_respuesta_min, "minutos_transcurridos": transcurrido,
            "respondido_at": sla.tiempo_respuesta_at, "umbral_riesgo_pct": umbral_pct,
            "en_riesgo": en_riesgo, "incumplido": incumplido, "cumplimiento": sla.cumplimiento}


async def panel_unidades(db: AsyncSession, actor: Actor) -> list[dict[str, Any]]:
    """Ubicaciones de UN con folios visibles; contador separado de folios activos.

    Incluye pendientes de asignación para mostrar la sucursal registrada,
    nunca como si fuera una posición GPS del técnico.
    """
    folios = await panel_folios(db, actor)
    ids_visibles = {f["un_id"] for f in folios}
    activos: dict[UUID, int] = {}
    for f in folios:
        if f["estado"] in {e.value for e in ESTADOS_ACTIVOS}:
            activos[f["un_id"]] = activos.get(f["un_id"], 0) + 1
    if not ids_visibles:
        return []
    filas = (await db.execute(text(
        "SELECT id::text, codigo, nombre, ST_Y(ubicacion::geometry), ST_X(ubicacion::geometry) "
        "FROM unidades_negocio WHERE id = ANY(:ids) AND ubicacion IS NOT NULL"),
        {"ids": [str(i) for i in ids_visibles]})).all()
    return [{"un_id": f[0], "codigo": f[1], "nombre": f[2], "lat": f[3], "lng": f[4],
             "folios_activos": activos.get(UUID(f[0]), 0)} for f in filas]


async def panel_alertas(db: AsyncSession, actor: Actor, limite: int = 40) -> list[dict[str, Any]]:
    """Feed cronológico: tiempo muerto, sin señal, SLA en riesgo, reasignaciones y folios autorizados sin técnico."""
    from models.alertas import AlertaHistorial
    from models.base import EstadoAlerta

    # Folios autorizados sin técnico asignado: §6.8.4 los pide en el feed aunque no sean una alerta del catálogo.
    # Se calculan primero y se les reserva su lugar: son lo más accionable del feed y no deben caerse de la página
    # porque haya muchas alertas viejas sin atender.
    sin_tecnico = [f for f in await panel_folios(db, actor)
                   if f["estado"] == EstadoFolio.autorizado.value and f["tecnico_id"] is None][:10]
    cupo = max(5, limite - len(sin_tecnico))
    consulta = select(AlertaHistorial).where(AlertaHistorial.atendida_at.is_(None))
    if not actor.es_superadmin:
        consulta = consulta.where(or_(AlertaHistorial.prestador_id == actor.prestador_id,
                                      AlertaHistorial.tenant_id == actor.tenant_id))
    filas = list((await db.execute(consulta.order_by(
        AlertaHistorial.timestamp_disparo.desc()).limit(cupo))).scalars())
    # El feed enseña el nombre del catálogo, no la clave: el despachador no tiene que traducir
    # `SLA_INCUMPLIDO_ESCALADO_DIRECCION` mentalmente.
    nombres: dict[str, str] = {}
    if filas:
        from models.alertas import AlertaCatalogo

        nombres = {c.clave: _nombre_de_alerta(c)
                   for c in (await db.execute(select(AlertaCatalogo).where(
                       AlertaCatalogo.clave.in_({a.clave_alerta for a in filas})))).scalars()}
    salida = [{"id": a.id, "clave": a.clave_alerta, "nombre": nombres.get(a.clave_alerta, a.clave_alerta),
               "entidad_tipo": a.entidad_tipo, "entidad_id": a.entidad_id,
               "timestamp": a.timestamp_disparo, "estado": a.estado.value, "escalada": a.escalada,
               "datos": a.datos_contexto_json, "vista": a.timestamp_vista is not None} for a in filas]
    for f in sin_tecnico:
        salida.append({"id": None, "clave": "FOLIO_AUTORIZADO_SIN_TECNICO",
                       "nombre": "Folio autorizado sin técnico asignado", "entidad_tipo": "folio",
                       "entidad_id": f["folio_id"], "timestamp": f["capturado_at"], "estado": EstadoAlerta.disparada.value,
                       "escalada": False, "vista": False,
                       "datos": {"numero_folio": f["numero_folio"], "sucursal": f["sucursal"]}})
    salida.sort(key=lambda x: x["timestamp"], reverse=True)
    return salida


def _nombre_de_alerta(catalogo) -> str:
    """Primera frase de la descripción del catálogo; si no hay, la clave en palabras."""
    descripcion = (catalogo.descripcion or "").strip()
    if descripcion:
        corta = descripcion.split(".")[0].strip()
        if 3 <= len(corta) <= 90:
            return corta
    return catalogo.clave.replace("_", " ").capitalize()


async def indicadores(db: AsyncSession, actor: Actor) -> dict[str, Any]:
    """La barra de «Indicadores globales de jornada» de P10, en vivo."""
    from services import bi_service

    hoy = date.today()
    filtro = bi_service.Filtro(hoy, hoy, actor.tenant_id, actor.prestador_id)
    return await bi_service.jornada(db, filtro)


# ----------------------------------------------------------------- recorrido

async def recorrido(db: AsyncSession, actor: Actor, tecnico_id: UUID, *, horas: float = HORAS_RECORRIDO,
                    request: Request | None = None) -> dict[str, Any]:
    """Rastro de las últimas horas de un técnico. Consultarlo es acceso a datos sensibles (P11a, §6.9.5)."""
    tecnico = (await db.execute(select(Tecnico).where(
        Tecnico.id == tecnico_id, _alcance_tecnicos(actor)))).scalar_one_or_none()
    if tecnico is None:
        raise no_encontrado("Técnico")
    propio = tecnico.usuario_id == actor.id
    if not propio:
        await exigir_tablero(actor)
    desde = datetime.now(UTC) - timedelta(hours=min(24.0, max(0.25, horas)))
    filas = (await db.execute(text(
        "SELECT ST_Y(posicion::geometry) AS lat, ST_X(posicion::geometry) AS lng, capturada_at, precision_m, "
        "       velocidad_mps, bateria_pct, tardia "
        "  FROM tecnico_posiciones WHERE tecnico_id = :t AND capturada_at >= :d ORDER BY capturada_at"),
        {"t": str(tecnico_id), "d": desde})).all()
    await auditoria.registrar_acceso_datos(db, actor, request, tabla="tecnico_posiciones", registros=len(filas),
                                           recurso_id=tecnico_id,
                                           detalle={"horas": horas, "propio": propio})
    usuario = await db.get(Usuario, tecnico.usuario_id)
    return {"tecnico_id": tecnico_id, "nombre": usuario.nombre if usuario else "", "desde": desde,
            "estatus": tecnico.estatus_operativo.value,
            "puntos": [{"lat": f.lat, "lng": f.lng, "capturada_at": f.capturada_at,
                        "precision_m": f.precision_m, "velocidad_mps": f.velocidad_mps,
                        "bateria_pct": f.bateria_pct, "tardia": f.tardia} for f in filas]}


# ----------------------------------------------------------------- alertas de operación (§6.8.4)

async def responder_alerta(db: AsyncSession, actor: Actor, seguimiento_id: UUID, respuesta: str,
                           request: Request | None = None) -> AlertaOperacionSeguimiento:
    """«Estoy bien» o «Necesito apoyo». La segunda levanta una alerta de prioridad alta al despachador."""
    seguimiento = await db.get(AlertaOperacionSeguimiento, seguimiento_id)
    if seguimiento is None:
        raise no_encontrado("Alerta")
    tecnico = await tecnico_del_usuario(db, actor.id)
    if seguimiento.tecnico_id != tecnico.id:
        raise prohibido("Solo el técnico de la alerta puede responderla")
    if seguimiento.respondida_at is not None:
        raise ErrorAPI(409, "YA_RESPONDIDA", "Ya respondiste esta alerta")
    seguimiento.respuesta_tecnico = RespuestaAlertaTecnico(respuesta)
    seguimiento.respondida_at = datetime.now(UTC)
    await db.flush()
    await publicar(db, seguimiento.prestador_id, {
        "evento": "respuesta_alerta", "tecnico_id": str(tecnico.id), "tipo": seguimiento.tipo,
        "respuesta": seguimiento.respuesta_tecnico.value})
    if seguimiento.respuesta_tecnico == RespuestaAlertaTecnico.necesito_apoyo:
        await _avisar_apoyo(db, seguimiento, tecnico)
    await auditoria.registrar_actor(db, actor, "operacion.respuesta_alerta", request,
                                    prestador_id=seguimiento.prestador_id,
                                    recurso_tipo="alertas_operacion_seguimiento", recurso_id=seguimiento.id,
                                    despues={"respuesta": seguimiento.respuesta_tecnico.value})
    return seguimiento


async def _avisar_apoyo(db: AsyncSession, seguimiento: AlertaOperacionSeguimiento, tecnico: Tecnico) -> None:
    from services import alertas_service, notificaciones_service

    usuario = await db.get(Usuario, tecnico.usuario_id)
    nombre = usuario.nombre if usuario else "El técnico"
    historial = await alertas_service.disparar(
        db, seguimiento.tipo, tenant_id=None, prestador_id=seguimiento.prestador_id, entidad_tipo="tecnico",
        entidad_id=tecnico.id, datos={"prioridad": "alta", "respuesta": "necesito_apoyo", "tecnico": nombre})
    destinatarios = await notificaciones_service.destinatarios_por_rol(
        db, [Rol.despachador, Rol.mesa_control, Rol.admin_prestador], prestador_id=seguimiento.prestador_id)
    await notificaciones_service.notificar(
        db, "alerta", destinatarios,
        {"alerta": seguimiento.tipo, "tecnico": nombre, "tecnico_id": str(tecnico.id), "severidad": "critica",
         "seguimiento_id": str(seguimiento.id), "alerta_id": str(historial.id) if historial else None},
        asunto=f"{nombre} pidió apoyo", cuerpo="Respondió «Necesito apoyo» al aviso de tiempo muerto.",
        url="/operaciones", prestador_id=seguimiento.prestador_id)


async def mis_alertas(db: AsyncSession, actor: Actor) -> list[dict[str, Any]]:
    """Lo que la app del técnico tiene que preguntarle: avisos sin responder."""
    tecnico = await tecnico_del_usuario(db, actor.id)
    filas = list((await db.execute(select(AlertaOperacionSeguimiento).where(
        AlertaOperacionSeguimiento.tecnico_id == tecnico.id, AlertaOperacionSeguimiento.respondida_at.is_(None)
    ).order_by(AlertaOperacionSeguimiento.created_at.desc()).limit(5))).scalars())
    return [{"id": s.id, "tipo": s.tipo, "desde": s.created_at, "folio_id": s.folio_id,
             "pregunta": "¿Todo bien? Si necesitas apoyo, dinos y avisamos al despachador.",
             "datos": s.datos_json} for s in filas]
