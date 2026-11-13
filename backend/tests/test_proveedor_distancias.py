"""Proveedor de distancias: estimado por línea recta y franja horaria, caché en Redis y en base, y
`google_routes` preparado sin llave (ninguna prueba llama a Google). F2-06, ACT-3.1."""
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from models.rutas import DistanciaCache, ProveedorDistancias
from services.rutas import distancias as dist

CENTRO = dist.Punto(19.4326, -99.1332)
POLANCO = dist.Punto(19.4333, -99.1950)
COYOACAN = dist.Punto(19.3467, -99.1617)
MANANA = datetime(2026, 11, 13, 8, 30, tzinfo=UTC)
MEDIODIA = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)


def test_la_franja_horaria_sale_de_la_configuracion():
    assert dist.franja_de(MANANA) == "06:00-09:00"          # hora pico de la mañana
    assert dist.franja_de(MEDIODIA) == "09:00-13:00"
    assert dist.franja_de(datetime(2026, 11, 13, 17, 0, tzinfo=UTC)) == "16:00-20:00"
    assert dist.franja_de(datetime(2026, 11, 13, 3, 0, tzinfo=UTC)) == "00:00-06:00"
    # Una franja que no existe en la configuración cae en la primera, no revienta.
    assert dist.franja_de(MANANA, {"10:00-11:00": 25}) == "10:00-11:00"


def test_la_velocidad_tiene_piso():
    assert dist.velocidad_kmh("06:00-09:00") == 20
    assert dist.velocidad_kmh("09:00-13:00") == 30
    assert dist.velocidad_kmh("x", {"x": 0}) == dist.VELOCIDAD_MINIMA_KMH, "con 0 el tiempo sería infinito"


def test_la_linea_recta_es_haversine():
    km = dist.metros_linea_recta(CENTRO, COYOACAN) / 1000
    assert 9 < km < 11, km                       # el centro y Coyoacán están a unos 10 km
    assert dist.metros_linea_recta(CENTRO, CENTRO) == 0


def test_la_distancia_al_segmento_y_al_trazo():
    """Es la cuenta que mide el desvío: a qué distancia está el técnico de su ruta."""
    a, b = dist.Punto(19.40, -99.13), dist.Punto(19.50, -99.13)
    # Un punto sobre la línea está a cero; uno desplazado en longitud, a su distancia perpendicular.
    assert dist.metros_al_segmento(dist.Punto(19.45, -99.13), a, b) < 1
    desviado = dist.metros_al_segmento(dist.Punto(19.45, -99.16), a, b)
    assert 2800 < desviado < 3400, desviado
    # Fuera del segmento, se mide al extremo más cercano, no a la recta infinita.
    assert dist.metros_al_segmento(dist.Punto(19.60, -99.13), a, b) > 10000
    trazo = [a, dist.Punto(19.45, -99.16), b]
    assert dist.metros_al_trazo(dist.Punto(19.45, -99.16), trazo) < 1
    assert dist.metros_al_trazo(dist.Punto(19.45, -99.13), []) == float("inf")


async def test_el_estimado_usa_sinuosidad_y_franja(cliente, auth, datos):
    """Línea recta × factor de sinuosidad, a la velocidad de la franja de salida."""
    from core.db import nueva_sesion
    from core.rls import CONTEXTO_SISTEMA

    parametros = dist.ParametrosDistancia(factor_sinuosidad=1.4)
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        pico = await dist.medir(db, CENTRO, COYOACAN, MANANA, parametros=parametros, usar_cache=False)
        valle = await dist.medir(db, CENTRO, COYOACAN, MEDIODIA, parametros=parametros, usar_cache=False)
    recta = dist.metros_linea_recta(CENTRO, COYOACAN)
    assert pico.metros == pytest.approx(int(recta * 1.4), rel=0.01)
    assert pico.proveedor_efectivo == ProveedorDistancias.estimado
    # Misma distancia, más tiempo en hora pico: 20 km/h contra 30 km/h.
    assert pico.metros == valle.metros
    assert pico.segundos > valle.segundos
    assert "20 km/h" in pico.nota and "06:00-09:00" in pico.nota


async def test_el_mismo_punto_no_cuesta_nada(cliente, auth, datos):
    from core.db import nueva_sesion
    from core.rls import CONTEXTO_SISTEMA

    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        t = await dist.medir(db, CENTRO, CENTRO, MANANA)
    assert t.metros == 0 and t.segundos == 0 and t.de_cache


async def test_la_distancia_se_guarda_en_cache_y_se_reusa(cliente, auth, datos):
    """Dos niveles: Redis para la jornada y la tabla como memoria larga. Con Google, es lo que no se paga dos veces."""
    from core.db import nueva_sesion
    from core.rls import CONTEXTO_SISTEMA

    # Un par de puntos propio de esta prueba, para no depender de lo que otras hayan medido.
    a, b = dist.Punto(18.1234, -98.1234), dist.Punto(18.2345, -98.2345)
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        primera = await dist.medir(db, a, b, MEDIODIA)
        await db.commit()
    assert not primera.de_cache
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        segunda = await dist.medir(db, a, b, MEDIODIA)
        fila = (await db.execute(select(DistanciaCache).where(
            DistanciaCache.origen_hash == a.hash(), DistanciaCache.destino_hash == b.hash(),
            DistanciaCache.franja == dist.franja_de(MEDIODIA)))).scalar_one_or_none()
    assert segunda.de_cache and segunda.metros == primera.metros
    assert fila is not None and fila.metros == primera.metros
    assert fila.proveedor == ProveedorDistancias.estimado


async def test_la_llave_de_cache_redondea_a_once_metros(cliente, auth, datos):
    """Más precisión parte la caché sin mejorar la ruta."""
    assert dist.Punto(19.432611, -99.133222).llave() == dist.Punto(19.432609, -99.133218).llave()
    assert dist.Punto(19.4326, -99.1332).llave() != dist.Punto(19.4327, -99.1332).llave()


async def test_la_matriz_es_cuadrada_y_con_diagonal_en_cero(cliente, auth, datos):
    from core.db import nueva_sesion
    from core.rls import CONTEXTO_SISTEMA

    puntos = [CENTRO, POLANCO, COYOACAN]
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        metros, segundos = await dist.matriz(db, puntos, MEDIODIA)
        await db.commit()
    assert len(metros) == len(segundos) == 3
    assert all(len(f) == 3 for f in metros)
    assert all(metros[i][i] == 0 and segundos[i][i] == 0 for i in range(3))
    assert metros[0][2] > 0 and segundos[0][2] > 0


async def test_google_routes_sin_llave_devuelve_el_estimado_y_lo_declara(cliente, auth, datos):
    """**Nunca inventa un tiempo «con tráfico» que no consultó**, y ninguna prueba llama a Google."""
    from core.db import nueva_sesion
    from core.rls import CONTEXTO_SISTEMA

    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        t = await dist.medir(db, CENTRO, POLANCO, MEDIODIA,
                             proveedor=ProveedorDistancias.google_routes, usar_cache=False)
    assert t.proveedor_efectivo == ProveedorDistancias.estimado
    assert "no hay llave" in t.nota or "no se consultó el tráfico" in t.nota
    assert t.metros > 0


def test_el_cuerpo_de_la_peticion_a_google_va_como_lo_pide_la_api():
    """Armado y parseo probados sin red: es lo que queda listo para encender con una llave."""
    proveedor = dist.ProveedorGoogleRoutes()
    cuerpo = proveedor.cuerpo(CENTRO, POLANCO, MEDIODIA)
    assert cuerpo["origin"]["location"]["latLng"] == {"latitude": 19.4326, "longitude": -99.1332}
    assert cuerpo["travelMode"] == "DRIVE" and cuerpo["routingPreference"] == "TRAFFIC_AWARE"
    assert cuerpo["trafficModel"] == "BEST_GUESS"
    assert cuerpo["departureTime"].endswith("Z"), "la Routes API espera la hora en UTC con Z"
    assert "routes.distanceMeters" in proveedor.CAMPOS and "routes.duration" in proveedor.CAMPOS


def test_la_respuesta_de_google_se_lee_y_lo_vacio_no_revienta():
    leer = dist.ProveedorGoogleRoutes.leer
    assert leer({"routes": [{"distanceMeters": 12345, "duration": "1800s"}]}) == (12345, 1800)
    assert leer({"routes": []}) is None
    assert leer({}) is None
    assert leer({"routes": [{"distanceMeters": 100}]}) is None
