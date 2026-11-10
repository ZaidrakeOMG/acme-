"""Reintentos de WhatsApp y SMS con espera exponencial (§6.1). F2-02.

Los envíos que fallaron por algo temporal (red, 429 del proveedor) quedan con `proximo_intento_at`; esta tarea los
retoma cada pocos minutos. Los errores permanentes —número inválido, plantilla rechazada, usuario dado de baja— no
llegan aquí: el servicio ya cayó al siguiente canal en el momento del fallo.
"""
import asyncio
import logging

from services import mensajeria_service
from workers.celery_app import celery_app
from workers.tareas import sesion_tarea

log = logging.getLogger("acma.tareas.mensajeria")


async def reintentar_mensajeria_async(url: str | None = None) -> dict:
    async with sesion_tarea(url=url) as db:
        resumen = await mensajeria_service.reintentar_pendientes(db)
        await db.commit()
    return resumen


@celery_app.task(name="acma.reintentar_mensajeria")
def reintentar_mensajeria() -> dict:
    resumen = asyncio.run(reintentar_mensajeria_async())
    log.info("reintentar_mensajeria: %s", resumen)
    return resumen
