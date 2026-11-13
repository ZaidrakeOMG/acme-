"""Distancias y tiempos de traslado entre dos puntos (F2-06, ACT-3.1).

Dos implementaciones detrás de la misma interfaz, como pide el prompt:

- **`estimado`** (default, y lo único que corre sin contratar nada): distancia en línea recta por el **factor de
  sinuosidad** del prestador (1.4 por default: las calles no van en línea recta), a la **velocidad promedio de la
  franja horaria** de la salida. No conoce calles ni tráfico, así que se equivoca; pero se equivoca igual para
  todos los candidatos, que es lo que el optimizador necesita para comparar.
- **`google_routes`**: Google Maps Routes API con `departureTime` y `traffic_model`, lista para encenderse con una
  llave. **Sin llave devuelve el estimado y lo declara** en el resultado (`proveedor_efectivo`), nunca inventa un
  tiempo «con tráfico» que no consultó.

Dos niveles de caché, porque la matriz de distancias es lo que más se pide y, con Google, lo que se paga:
**Redis** con TTL corto para la jornada en curso y la tabla **`distancias_cache`** como memoria larga. La llave es
el par de puntos redondeados a ~11 m, la franja horaria y el proveedor.
"""
import hashlib
import json
import logging
import math
from dataclasses import dataclass
from datetime import datetime, time

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import config
from models.rutas import DistanciaCache, ProveedorDistancias, RutasConfiguracion, VELOCIDADES_DEFAULT

log = logging.getLogger("acma.rutas.distancias")

TTL_REDIS_S = 3600          # una hora: dentro de la misma jornada la geografía no cambia
DECIMALES_LLAVE = 4         # ~11 m: más precisión solo parte la caché sin mejorar la ruta
RADIO_TIERRA_M = 6_371_000
VELOCIDAD_MINIMA_KMH = 5    # piso de cordura: con 0 el tiempo sería infinito


@dataclass(frozen=True)
class Punto:
    lat: float
    lng: float

    def llave(self) -> str:
        return f"{round(self.lat, DECIMALES_LLAVE)},{round(self.lng, DECIMALES_LLAVE)}"

    def hash(self) -> str:
        return hashlib.sha256(self.llave().encode()).hexdigest()[:32]


@dataclass(frozen=True)
class Tramo:
    metros: int
    segundos: int
    proveedor_efectivo: ProveedorDistancias
    de_cache: bool = False
    nota: str = ""


def metros_linea_recta(a: Punto, b: Punto) -> float:
    """Haversine. Es la distancia real sobre la Tierra, no la euclidiana del plano."""
    lat1, lat2 = math.radians(a.lat), math.radians(b.lat)
    dlat = lat2 - lat1
    dlng = math.radians(b.lng - a.lng)
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 2 * RADIO_TIERRA_M * math.asin(min(1.0, math.sqrt(h)))


def franja_de(momento: datetime | time, velocidades: dict[str, float] | None = None) -> str:
    """Franja horaria de `velocidades_json` a la que pertenece la hora de salida."""
    hora = momento.time() if isinstance(momento, datetime) else momento
    minutos = hora.hour * 60 + hora.minute
    for clave in sorted((velocidades or VELOCIDADES_DEFAULT).keys()):
        inicio, fin = clave.split("-")
        hi, mi = (int(x) for x in inicio.split(":"))
        hf, mf = (int(x) for x in fin.split(":"))
        desde, hasta = hi * 60 + mi, hf * 60 + mf
        if desde <= minutos < hasta:
            return clave
    return sorted((velocidades or VELOCIDADES_DEFAULT).keys())[0]


def velocidad_kmh(franja: str, velocidades: dict[str, float] | None = None) -> float:
    v = float((velocidades or VELOCIDADES_DEFAULT).get(franja, 30))
    return max(VELOCIDAD_MINIMA_KMH, v)


class Proveedor:
    """Interfaz. `tramo()` no pregunta por la caché: eso lo hace `medir()`, que es por donde entra todo."""

    clave: ProveedorDistancias

    async def tramo(self, a: Punto, b: Punto, salida: datetime, cfg: "ParametrosDistancia") -> Tramo:
        raise NotImplementedError


@dataclass(frozen=True)
class ParametrosDistancia:
    """Lo que el proveedor necesita de la configuración del prestador, sin arrastrar la fila entera."""
    factor_sinuosidad: float = 1.4
    velocidades: dict[str, float] | None = None

    @classmethod
    def desde(cls, cfg: RutasConfiguracion | None) -> "ParametrosDistancia":
        if cfg is None:
            return cls()
        return cls(factor_sinuosidad=float(cfg.factor_sinuosidad or 1.4),
                   velocidades=dict(cfg.velocidades_json or VELOCIDADES_DEFAULT))


class ProveedorEstimado(Proveedor):
    clave = ProveedorDistancias.estimado

    async def tramo(self, a: Punto, b: Punto, salida: datetime, cfg: ParametrosDistancia) -> Tramo:
        franja = franja_de(salida, cfg.velocidades)
        metros = metros_linea_recta(a, b) * cfg.factor_sinuosidad
        kmh = velocidad_kmh(franja, cfg.velocidades)
        segundos = (metros / 1000) / kmh * 3600
        return Tramo(metros=int(round(metros)), segundos=int(round(segundos)),
                     proveedor_efectivo=ProveedorDistancias.estimado,
                     nota=f"línea recta × {cfg.factor_sinuosidad} a {kmh:g} km/h ({franja})")


class ProveedorGoogleRoutes(Proveedor):
    """Google Maps Routes API con tráfico. **Sin llave no llama a nadie**: devuelve el estimado y lo dice.

    Lo que falta para encenderlo en producción está en `CONTEXTO.md`: una llave en `GOOGLE_ROUTES_API_KEY` con la
    Routes API habilitada y facturación activa. El cuerpo de la petición ya va armado como lo pide la API
    (`departureTime` en UTC y `trafficModel`), y el parseo espera `routes[0].distanceMeters` y `routes[0].duration`.
    """
    clave = ProveedorDistancias.google_routes
    URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
    CAMPOS = "routes.distanceMeters,routes.duration"

    def __init__(self) -> None:
        self._estimado = ProveedorEstimado()

    def cuerpo(self, a: Punto, b: Punto, salida: datetime) -> dict:
        """El cuerpo de la petición, expuesto para poder probarlo sin llamar a Google."""
        return {
            "origin": {"location": {"latLng": {"latitude": a.lat, "longitude": a.lng}}},
            "destination": {"location": {"latLng": {"latitude": b.lat, "longitude": b.lng}}},
            "travelMode": "DRIVE",
            "routingPreference": "TRAFFIC_AWARE",
            "departureTime": salida.isoformat().replace("+00:00", "Z"),
            "trafficModel": "BEST_GUESS",
        }

    @staticmethod
    def leer(respuesta: dict) -> tuple[int, int] | None:
        """`routes[0]` → (metros, segundos). Devuelve None si la respuesta no trae ruta."""
        rutas = respuesta.get("routes") or []
        if not rutas:
            return None
        metros = rutas[0].get("distanceMeters")
        duracion = str(rutas[0].get("duration") or "").rstrip("s")
        if metros is None or not duracion:
            return None
        return int(metros), int(float(duracion))

    async def tramo(self, a: Punto, b: Punto, salida: datetime, cfg: ParametrosDistancia) -> Tramo:
        llave = getattr(config, "google_routes_api_key", "") or ""
        if not llave:
            base = await self._estimado.tramo(a, b, salida, cfg)
            return Tramo(metros=base.metros, segundos=base.segundos,
                         proveedor_efectivo=ProveedorDistancias.estimado,
                         nota="Google Routes está configurado pero no hay llave: se usó el estimado y no se "
                              "consultó el tráfico")
        import httpx

        cabeceras = {"X-Goog-Api-Key": llave, "X-Goog-FieldMask": self.CAMPOS}
        async with httpx.AsyncClient(timeout=10) as cliente:
            r = await cliente.post(self.URL, json=self.cuerpo(a, b, salida), headers=cabeceras)
            r.raise_for_status()
            leido = self.leer(r.json())
        if leido is None:
            base = await self._estimado.tramo(a, b, salida, cfg)
            return Tramo(metros=base.metros, segundos=base.segundos,
                         proveedor_efectivo=ProveedorDistancias.estimado,
                         nota="Google Routes no devolvió ruta entre esos puntos: se usó el estimado")
        metros, segundos = leido
        return Tramo(metros=metros, segundos=segundos, proveedor_efectivo=ProveedorDistancias.google_routes,
                     nota="Google Routes con tráfico")


PROVEEDORES: dict[ProveedorDistancias, Proveedor] = {
    ProveedorDistancias.estimado: ProveedorEstimado(),
    ProveedorDistancias.google_routes: ProveedorGoogleRoutes(),
}

_redis = None


async def _cliente_redis():
    global _redis
    if config.tiempo_real_modo != "redis":
        return None
    if _redis is None:
        import redis.asyncio as redis_async

        _redis = redis_async.from_url(config.redis_url, decode_responses=True)
    return _redis


def _llave_redis(a: Punto, b: Punto, franja: str, proveedor: ProveedorDistancias) -> str:
    return f"dist:{proveedor.value}:{franja}:{a.llave()}:{b.llave()}"


async def medir(db: AsyncSession, a: Punto, b: Punto, salida: datetime, *,
                proveedor: ProveedorDistancias = ProveedorDistancias.estimado,
                parametros: ParametrosDistancia | None = None, usar_cache: bool = True) -> Tramo:
    """La única puerta de entrada: caché de Redis → caché en base → proveedor, y guarda en las dos."""
    cfg = parametros or ParametrosDistancia()
    franja = franja_de(salida, cfg.velocidades)
    if a.llave() == b.llave():
        return Tramo(metros=0, segundos=0, proveedor_efectivo=proveedor, de_cache=True, nota="mismo punto")

    if usar_cache:
        cliente = await _cliente_redis()
        if cliente is not None:
            try:
                crudo = await cliente.get(_llave_redis(a, b, franja, proveedor))
                if crudo:
                    d = json.loads(crudo)
                    return Tramo(metros=int(d["m"]), segundos=int(d["s"]),
                                 proveedor_efectivo=ProveedorDistancias(d["p"]), de_cache=True, nota="caché Redis")
            except Exception:  # noqa: BLE001 — la caché nunca debe tumbar un cálculo
                log.debug("no se pudo leer la caché de distancias en Redis", exc_info=True)
        fila = (await db.execute(select(DistanciaCache).where(
            DistanciaCache.origen_hash == a.hash(), DistanciaCache.destino_hash == b.hash(),
            DistanciaCache.franja == franja, DistanciaCache.proveedor == proveedor))).scalar_one_or_none()
        if fila is not None:
            return Tramo(metros=fila.metros, segundos=fila.segundos, proveedor_efectivo=fila.proveedor,
                         de_cache=True, nota="caché en base")

    tramo = await PROVEEDORES[proveedor].tramo(a, b, salida, cfg)
    if usar_cache:
        await _guardar(db, a, b, franja, proveedor, tramo)
    return tramo


async def _guardar(db: AsyncSession, a: Punto, b: Punto, franja: str, proveedor: ProveedorDistancias,
                   tramo: Tramo) -> None:
    cliente = await _cliente_redis()
    if cliente is not None:
        try:
            await cliente.set(_llave_redis(a, b, franja, proveedor),
                              json.dumps({"m": tramo.metros, "s": tramo.segundos,
                                          "p": tramo.proveedor_efectivo.value}), ex=TTL_REDIS_S)
        except Exception:  # noqa: BLE001
            log.debug("no se pudo escribir la caché de distancias en Redis", exc_info=True)
    try:
        await db.execute(pg_insert(DistanciaCache).values(
            origen_hash=a.hash(), destino_hash=b.hash(), franja=franja, proveedor=proveedor,
            metros=tramo.metros, segundos=tramo.segundos,
        ).on_conflict_do_nothing(constraint="uq_distancias_cache"))
        await db.flush()
    except Exception:  # noqa: BLE001
        log.debug("no se pudo escribir la caché de distancias en la base", exc_info=True)


async def matriz(db: AsyncSession, puntos: list[Punto], salida: datetime, *,
                 proveedor: ProveedorDistancias = ProveedorDistancias.estimado,
                 parametros: ParametrosDistancia | None = None) -> tuple[list[list[int]], list[list[int]]]:
    """Matrices de metros y de segundos entre todos los puntos, que es lo que come el optimizador.

    Con el proveedor estimado no hace falta pedir nada: se calcula. Con Google, cada par pasa por la caché, así que
    el segundo cálculo del día sobre los mismos puntos no cuesta llamadas.
    """
    cfg = parametros or ParametrosDistancia()
    n = len(puntos)
    metros = [[0] * n for _ in range(n)]
    segundos = [[0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            t = await medir(db, puntos[i], puntos[j], salida, proveedor=proveedor, parametros=cfg)
            metros[i][j], segundos[i][j] = t.metros, t.segundos
    return metros, segundos


def metros_al_segmento(p: Punto, a: Punto, b: Punto) -> float:
    """Distancia del punto `p` al segmento `a`→`b`, en metros. Es lo que mide el desvío contra el trazo.

    Proyecta en un plano local (equirectangular alrededor de `p`): a las distancias de una ciudad el error es
    despreciable y evita arrastrar una dependencia de geometría para tres restas.
    """
    lat0 = math.radians(p.lat)
    mx = 111_320 * math.cos(lat0)   # metros por grado de longitud a esta latitud
    my = 110_540                    # metros por grado de latitud
    px, py = p.lng * mx, p.lat * my
    ax, ay = a.lng * mx, a.lat * my
    bx, by = b.lng * mx, b.lat * my
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def metros_al_trazo(p: Punto, trazo: list[Punto]) -> float:
    """Distancia al trazo completo: la menor a cualquiera de sus segmentos."""
    if not trazo:
        return float("inf")
    if len(trazo) == 1:
        return metros_linea_recta(p, trazo[0])
    return min(metros_al_segmento(p, trazo[i], trazo[i + 1]) for i in range(len(trazo) - 1))
