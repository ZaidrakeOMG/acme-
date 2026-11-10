"""Tareas de operaciones en tiempo real (§6.8.4). F2-03.

Cada minuto: escalación del tiempo muerto sin respuesta y refresco del estatus de los técnicos (para que el mapa no
muestre «en ruta» a quien lleva media hora sin señal). Cada 15 minutos: cierre de jornadas que el técnico olvidó.
Diario: particiones de `tecnico_posiciones` y purga de las que pasan la retención de 90 días.
"""
import asyncio
import logging

from sqlalchemy import text

from workers.celery_app import celery_app
from workers.tareas import sesion_tarea

log = logging.getLogger("acma.tareas.operacion")


async def seguimiento_operacion_async(url: str | None = None) -> dict:
    from workers import evaluadores_operacion

    async with sesion_tarea(url=url) as db:
        resumen = {"escaladas": await evaluadores_operacion.escalar_sin_respuesta(db),
                   "estatus_actualizados": await evaluadores_operacion.marcar_sin_senal(db)}
        await db.commit()
    return resumen


async def cerrar_jornadas_async(url: str | None = None) -> dict:
    from workers import evaluadores_operacion

    async with sesion_tarea(url=url) as db:
        cerradas = await evaluadores_operacion.cerrar_jornadas_inactivas(db)
        await db.commit()
    return {"jornadas_cerradas": cerradas}


async def particiones_posiciones_async(dias_adelante: int = 7, retencion_dias: int = 90,
                                        url: str | None = None) -> dict:
    async with sesion_tarea(url=url) as db:
        creadas = (await db.execute(text("SELECT acma_crear_particiones_posiciones(:d)"),
                                    {"d": dias_adelante})).scalar_one()
        await db.commit()
    return {"particiones_creadas": int(creadas), "retencion_dias": retencion_dias}


async def purgar_posiciones_async(dias: int = 90, url: str | None = None) -> list[dict]:
    """§6.9.5: 90 días de recorridos. Se sueltan particiones enteras (DETACH + DROP), como en P11a."""
    async with sesion_tarea(url=url) as db:
        filas = (await db.execute(text("SELECT particion, accion, filas FROM acma_purgar_posiciones(:n)"),
                                  {"n": dias})).all()
        await db.commit()
        return [{"particion": f.particion, "accion": f.accion, "filas": int(f.filas)} for f in filas]


@celery_app.task(name="acma.seguimiento_operacion")
def seguimiento_operacion() -> dict:
    resumen = asyncio.run(seguimiento_operacion_async())
    if resumen["escaladas"]:
        log.info("seguimiento_operacion: %s", resumen)
    return resumen


@celery_app.task(name="acma.cerrar_jornadas_inactivas")
def cerrar_jornadas_inactivas() -> dict:
    resumen = asyncio.run(cerrar_jornadas_async())
    log.info("cerrar_jornadas_inactivas: %s", resumen)
    return resumen


@celery_app.task(name="acma.crear_particiones_posiciones")
def crear_particiones_posiciones() -> dict:
    return asyncio.run(particiones_posiciones_async())


@celery_app.task(name="acma.purgar_posiciones")
def purgar_posiciones() -> list[dict]:
    return asyncio.run(purgar_posiciones_async())
