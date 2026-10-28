"""Tarea nocturna de preventivos (§6.9.1): evalúa los triggers de Fase 1 y el calendario manual con el contexto
CONTEXTO_SISTEMA en una sesión propia, y genera los folios preventivos en Autorizado."""
import asyncio
import logging

from services import preventivos_service
from workers.celery_app import celery_app
from workers.tareas import sesion_tarea

log = logging.getLogger("acma.tareas.preventivos")


async def generar_preventivos_async(url: str | None = None, horizonte_dias: int = preventivos_service.HORIZONTE_DIAS) -> dict:
    async with sesion_tarea(url=url) as db:
        resumen = await preventivos_service.generar_programados(db, horizonte_dias=horizonte_dias)
        await db.commit()
    return resumen


@celery_app.task(name="acma.generar_preventivos_programados")
def generar_preventivos_programados() -> dict:
    resumen = asyncio.run(generar_preventivos_async())
    log.info("generar_preventivos_programados: %s", resumen)
    return resumen
