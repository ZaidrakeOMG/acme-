"""Tarea semanal de criticidad y riesgo (§6.9.3). F2-05.

Dos cosas que son datos medidos, no capturados, y que por lo tanto se refrescan solas:

1. La **probabilidad de falla** de cada activo evaluado, con el historial de la semana que pasó. Solo deja una
   evaluación en el historial si **cambia el nivel**: si el índice se mueve de 62.1 a 63.4, ensuciar la traza de
   auditoría no ayuda a nadie.
2. La **frecuencia histórica** de los modos de falla con tipo de falla, que alimenta el nivel de riesgo del FMEA.

Un activo con `origen = manual` no se recalcula: el ajuste del Admin empresa se respeta hasta su próxima revisión.
"""
import asyncio
import logging

from sqlalchemy import select

from workers.celery_app import celery_app
from workers.tareas import sesion_tarea

log = logging.getLogger("acma.tareas.criticidad")


async def recalcular_criticidad_async(url: str | None = None) -> dict:
    from models.catalogos import Equipo
    from models.criticidad import ActivoCriticidad
    from services import criticidad_service, riesgo_service

    async with sesion_tarea(url=url) as db:
        resumen = await criticidad_service.recalcular_todos(db)
        frecuencias = 0
        ids = list((await db.execute(select(ActivoCriticidad.equipo_id))).scalars())
        for equipo_id in ids:
            equipo = await db.get(Equipo, equipo_id)
            if equipo is None:
                continue
            try:
                punto = await db.begin_nested()
                frecuencias += await riesgo_service.refrescar_frecuencias(db, equipo)
                await punto.commit()
            except Exception:  # noqa: BLE001 — un equipo con datos raros no detiene al resto
                await punto.rollback()
                log.exception("No se pudieron refrescar las frecuencias del equipo %s", equipo_id)
        await db.commit()
    return {**resumen, "frecuencias_actualizadas": frecuencias}


@celery_app.task(name="acma.recalcular_criticidad")
def recalcular_criticidad() -> dict:
    resumen = asyncio.run(recalcular_criticidad_async())
    log.info("recalcular_criticidad: %s", resumen)
    return resumen
