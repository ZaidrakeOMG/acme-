"""Sesión en cookies (§6.9.5 «Gestión de sesiones»). P11a.

El refresh token deja de vivir en `localStorage` (decisión pendiente n.º 7) y pasa a una cookie `httpOnly` con la ruta
limitada a `/api/auth`, de modo que ningún script de la página puede leerla y solo se envía a los endpoints que la
necesitan. El token de acceso sigue en memoria del navegador.

Contra CSRF se usa doble envío: junto a la cookie `httpOnly` se emite `acma_csrf`, legible por JavaScript, y los
endpoints que consumen la cookie de sesión exigen la misma cadena en la cabecera `X-ACMA-CSRF`. Como la cookie es
`SameSite=Strict`, un sitio externo no puede provocar la petición; el doble envío cubre además el caso de subdominios.
"""
import secrets

from fastapi import Request, Response

from core.config import config
from core.errors import ErrorAPI

COOKIE_REFRESH = "acma_refresh"
COOKIE_CSRF = "acma_csrf"
CABECERA_CSRF = "x-acma-csrf"
RUTA_REFRESH = "/api/auth"


def nuevo_csrf() -> str:
    return secrets.token_urlsafe(24)


def poner_sesion(respuesta: Response, refresh: str, csrf: str, segundos: int) -> None:
    """Emite la cookie de sesión (httpOnly) y la de CSRF (legible), ambas con la vida máxima de la sesión."""
    comun = {"max_age": segundos, "secure": config.es_produccion, "samesite": "strict"}
    respuesta.set_cookie(COOKIE_REFRESH, refresh, httponly=True, path=RUTA_REFRESH, **comun)
    respuesta.set_cookie(COOKIE_CSRF, csrf, httponly=False, path="/", **comun)


def quitar_sesion(respuesta: Response) -> None:
    respuesta.delete_cookie(COOKIE_REFRESH, path=RUTA_REFRESH, samesite="strict")
    respuesta.delete_cookie(COOKIE_CSRF, path="/", samesite="strict")


def refresh_de(request: Request) -> str:
    token = request.cookies.get(COOKIE_REFRESH)
    if not token:
        raise ErrorAPI(401, "SIN_SESION", "No hay una sesión en este navegador; inicia sesión de nuevo")
    return token


def exigir_csrf(request: Request) -> None:
    """Doble envío: la cabecera debe coincidir con la cookie legible emitida al crear la sesión."""
    cookie = request.cookies.get(COOKIE_CSRF)
    cabecera = request.headers.get(CABECERA_CSRF)
    if not cookie or not cabecera or not secrets.compare_digest(cookie, cabecera):
        raise ErrorAPI(403, "CSRF_INVALIDO",
                       "Falta la verificación contra CSRF de esta petición; recarga la página e inténtalo de nuevo")
