"""Envío en background de las notificaciones encoladas por `services/notificaciones_service.notificar()` (P07)."""
import asyncio
import logging
from uuid import UUID

from services import notificaciones_service
from workers.celery_app import celery_app
from workers.tareas import sesion_tarea

log = logging.getLogger("acma.tareas.notificaciones")


async def enviar_notificaciones_async(ids: list[str] | None = None, url: str | None = None) -> dict:
    async with sesion_tarea(url=url) as db:
        resumen = await notificaciones_service.procesar(db, [UUID(i) for i in ids] if ids else None)
        await db.commit()
    return resumen


@celery_app.task(name="acma.enviar_notificaciones")
def enviar_notificaciones(ids: list[str] | None = None) -> dict:
    resumen = asyncio.run(enviar_notificaciones_async(ids))
    log.info("enviar_notificaciones: %s", resumen)
    return resumen


@celery_app.task(name="acma.enviar_notificaciones_pendientes")
def enviar_notificaciones_pendientes() -> dict:
    """Barrido periódico: lo que quedó pendiente sin broker o tras un fallo transitorio."""
    return asyncio.run(enviar_notificaciones_async(None))
