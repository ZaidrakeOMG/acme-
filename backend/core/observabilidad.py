"""Observabilidad mínima sin servicios de pago (P11a): logs en JSON y comprobación de dependencias.

- Logs en JSON cuando `LOG_JSON=true` (producción): una línea por evento, con el nivel, el logger y el mensaje, para
  que `docker logs`, `jq` o cualquier recolector los lean sin parsear texto libre. La rotación la hace Docker
  (`max-size` y `max-file` en el compose), no la aplicación.
- `/api/salud` queda ligera a propósito (la usa el healthcheck del contenedor): si Redis se cae, no hay que
  reiniciar la API. El estado de las dependencias vive en `/api/salud/detalle`, que es lo que vigila el monitoreo.
"""
import asyncio
import json
import logging
import time
from typing import Any

from core.config import config

# Campos que el logger ya trae y no hay que repetir dentro de `extra`.
_PROPIOS = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"asctime", "message", "taskName"}


class FormatoJSON(logging.Formatter):
    def format(self, registro: logging.LogRecord) -> str:
        salida: dict[str, Any] = {
            "hora": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(registro.created)) + f".{int(registro.msecs):03d}Z",
            "nivel": registro.levelname,
            "logger": registro.name,
            "mensaje": registro.getMessage(),
        }
        if registro.exc_info:
            salida["excepcion"] = self.formatException(registro.exc_info)
        # Lo que el código pase en `extra=` viaja como campo propio, no embutido en el texto.
        for clave, valor in registro.__dict__.items():
            if clave not in _PROPIOS and not clave.startswith("_"):
                salida[clave] = valor if isinstance(valor, (str, int, float, bool, type(None))) else str(valor)
        return json.dumps(salida, ensure_ascii=False)


def configurar_logs() -> None:
    """Deja los logs en JSON si LOG_JSON=true; si no, los deja como están (legibles en desarrollo)."""
    if not config.log_json:
        return
    manejador = logging.StreamHandler()
    manejador.setFormatter(FormatoJSON())
    raiz = logging.getLogger()
    raiz.handlers = [manejador]
    raiz.setLevel(logging.INFO)
    # uvicorn y gunicorn traen sus propios manejadores: se les quitan para que no dupliquen la línea.
    for nombre in ("uvicorn", "uvicorn.access", "uvicorn.error", "gunicorn.access", "gunicorn.error"):
        log = logging.getLogger(nombre)
        log.handlers = []
        log.propagate = True



# ------------------------------------------------------------ estado de dependencias

async def _con_limite(corrutina, segundos: float = 8.0) -> tuple[bool, str]:
    """Una dependencia caída no debe colgar la comprobación: cada una tiene su propio límite de tiempo."""
    try:
        await asyncio.wait_for(corrutina, timeout=segundos)
        return True, "ok"
    except TimeoutError:
        return False, f"sin respuesta en {segundos:.0f}s"
    except Exception as e:  # noqa: BLE001 - el detalle del fallo es justo lo que hay que reportar
        return False, f"{type(e).__name__}: {e}"[:200]


async def _probar_base() -> None:
    from sqlalchemy import text

    from core.db import engine

    async with engine.connect() as conexion:
        await conexion.execute(text("SELECT 1"))


async def _probar_redis() -> None:
    import redis.asyncio as redis

    cliente = redis.from_url(config.redis_url)
    try:
        await cliente.ping()
    finally:
        await cliente.aclose()


def _comprobar_minio_sincrono() -> None:
    from services.almacenamiento import AlmacenamientoCifrado, obtener_almacenamiento

    # `obtener_almacenamiento()` tambien va en el hilo: la primera llamada crea el cliente de MinIO y comprueba el
    # bucket con E/S de red sincrona. Hacerlo en el event loop lo bloquea varios segundos y, en la comprobacion de
    # salud, tumbaba las otras tres pruebas por tiempo de espera.
    almacen = obtener_almacenamiento()
    backend = almacen.backend if isinstance(almacen, AlmacenamientoCifrado) else almacen
    if hasattr(backend, "comprobar"):
        backend.comprobar()  # Supabase Storage, bucket privado y token servidor
        return
    if not hasattr(backend, "cliente"):
        return  # modo memoria (pruebas): no hay nada que comprobar
    backend.cliente.bucket_exists(backend.bucket)


async def _probar_minio() -> None:
    await asyncio.to_thread(_comprobar_minio_sincrono)


async def _probar_celery() -> None:
    """Pregunta a los workers si contestan. Sin workers vivos devuelve lista vacía y se reporta como caído."""
    from workers.celery_app import celery_app

    respuestas = await asyncio.to_thread(lambda: celery_app.control.ping(timeout=2.0))
    if not respuestas:
        raise RuntimeError("ningún worker de Celery respondió")


async def estado_dependencias() -> dict[str, Any]:
    """Estado de base de datos, Redis, MinIO y Celery, cada uno con su propio límite de tiempo."""
    pruebas = {
        "base_datos": _probar_base(),
        "redis": _probar_redis(),
        "almacenamiento": _probar_minio(),
        "celery": _probar_celery(),
    }
    resultados = await asyncio.gather(*(_con_limite(c) for c in pruebas.values()))
    detalle = {nombre: {"ok": ok, "mensaje": mensaje} for nombre, (ok, mensaje) in zip(pruebas, resultados)}
    return {"estado": "ok" if all(d["ok"] for d in detalle.values()) else "degradado", "dependencias": detalle}
