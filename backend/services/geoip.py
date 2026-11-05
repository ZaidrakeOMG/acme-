"""Geolocalización aproximada de una IP para la auditoría de autenticación (§6.9.5). P11a.

El diseño pide registrar la «geolocalización aproximada» del login. Resolverla exige una base de datos de rangos de IP;
la de MaxMind (GeoLite2) es gratuita pero su licencia obliga a registrarse, aceptar sus términos y actualizarla cada
mes, así que ACMA **no la incluye**: esta interfaz queda como `stub` y se activa poniendo `GEOIP_BASE` con la ruta a un
`GeoLite2-City.mmdb` propio y el paquete `geoip2` instalado. Sin base configurada devuelve `None` y la auditoría anota
`geo: null` sin fallar (decisión pendiente anotada en CONTEXTO.md).

Las IP privadas y de loopback nunca se consultan: se marcan como `red_local`.
"""
import ipaddress
import logging
from functools import lru_cache
from typing import Any

from core.config import config

log = logging.getLogger("acma.geoip")


def disponible() -> bool:
    return bool(config.geoip_base) and _lector() is not None


@lru_cache(maxsize=1)
def _lector() -> Any | None:
    if not config.geoip_base:
        return None
    try:
        import geoip2.database  # type: ignore[import-not-found]

        return geoip2.database.Reader(config.geoip_base)
    except Exception as e:  # falta el paquete o el archivo: se sigue sin geolocalización
        log.warning("GeoIP no disponible (%s); la auditoría registrará geo: null", e)
        return None


def _es_local(ip: str) -> bool:
    try:
        dir_ip = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return dir_ip.is_private or dir_ip.is_loopback or dir_ip.is_link_local


def aproximada(ip: str | None) -> str | None:
    """«Ciudad, País» aproximados, `red_local` para direcciones privadas, o None si no hay base configurada."""
    if not ip or ip == "desconocida":
        return None
    if _es_local(ip):
        return "red_local"
    lector = _lector()
    if lector is None:
        return None
    try:
        r = lector.city(ip)
        partes = [p for p in (r.city.name, r.country.name) if p]
        return ", ".join(partes) or r.country.iso_code
    except Exception:
        return None
