"""Tareas de medidores y planes por uso (§6.9.1, §6.9.2). F2-04.

Una sola tarea nocturna, en este orden:

1. **Estimación del día** (§6.9.2 «Cálculo estimado»): por cada medidor con estimación activa escribe una lectura
   `estimado` con el incremento de los días de operación transcurridos. Como cada lectura válida evalúa los planes
   del equipo, un plan por horas de un equipo sin lecturas reales también avanza.
2. **Evaluación de los triggers pendientes**: lo que ya se cumple genera su folio hoy; lo que se proyecta deja su
   fecha estimada en `equipo_planes.fecha_proxima_ejecucion`.
3. **Generación programada de P06** (`generar_preventivos_programados`, que corre aparte a las 02:00): recoge esas
   fechas dentro de su horizonte y pinta el origen «por medidor» o «por evento».

Los pasos 1 y 2 van juntos y antes del 3 a propósito: si se evaluaran después, un umbral alcanzado hoy esperaría a
la noche siguiente.
"""
import asyncio
import logging

from workers.celery_app import celery_app
from workers.tareas import sesion_tarea

log = logging.getLogger("acma.tareas.medidores")


async def estimar_lecturas_async(url: str | None = None) -> dict:
    from services import medidores_service

    async with sesion_tarea(url=url) as db:
        resumen = await medidores_service.estimar_dia(db)
        await db.commit()
    return resumen


async def evaluar_triggers_async(url: str | None = None) -> dict:
    from services import triggers_service

    async with sesion_tarea(url=url) as db:
        resumen = await triggers_service.evaluar_pendientes(db)
        await db.commit()
    return resumen


async def ciclo_medidores_async(url: str | None = None) -> dict:
    estimacion = await estimar_lecturas_async(url)
    triggers = await evaluar_triggers_async(url)
    return {"estimacion": estimacion, "triggers": triggers}


@celery_app.task(name="acma.estimar_lecturas_medidor")
def estimar_lecturas_medidor() -> dict:
    resumen = asyncio.run(estimar_lecturas_async())
    log.info("estimar_lecturas_medidor: %s", resumen)
    return resumen


@celery_app.task(name="acma.evaluar_triggers_medidor")
def evaluar_triggers_medidor() -> dict:
    resumen = asyncio.run(evaluar_triggers_async())
    log.info("evaluar_triggers_medidor: %s", resumen)
    return resumen


@celery_app.task(name="acma.ciclo_medidores")
def ciclo_medidores() -> dict:
    """Las dos de arriba en el orden correcto: es la que programa el beat."""
    resumen = asyncio.run(ciclo_medidores_async())
    log.info("ciclo_medidores: %s", resumen)
    return resumen
