"""Tareas de optimización de rutas (ACT-2.2). F2-06.

Tres trabajos, con cadencias distintas porque atienden cosas distintas:

1. **`acma.calcular_rutas_del_dia`** (madrugada): un plan en **borrador** por mercado activo, para que el
   despachador llegue y lo encuentre listo. Nunca publica sola: asignar folios es decisión de una persona.
2. **`acma.refrescar_eta`** (cada 5 minutos): recalcula la hora estimada de llegada con la posición de cada
   técnico y avisa al operador si se movió más de 15 minutos.
3. **`acma.expirar_propuestas_ruta`** (cada 5 minutos): marca vencidas las propuestas de reasignación que nadie
   decidió. Una propuesta vieja describe una operación que ya cambió, y es peor que ninguna.
"""
import asyncio
import logging

from workers.celery_app import celery_app
from workers.tareas import sesion_tarea

log = logging.getLogger("acma.tareas.rutas")


async def calcular_rutas_del_dia_async(url: str | None = None) -> dict:
    from services.rutas import planes_service

    async with sesion_tarea(url=url) as db:
        resumen = await planes_service.calcular_del_dia(db)
        await db.commit()
    return resumen


@celery_app.task(name="acma.calcular_rutas_del_dia")
def calcular_rutas_del_dia() -> dict:
    resumen = asyncio.run(calcular_rutas_del_dia_async())
    log.info("calcular_rutas_del_dia: %s", resumen)
    return resumen


async def refrescar_eta_async(url: str | None = None) -> dict:
    from services.rutas import eta

    async with sesion_tarea(url=url) as db:
        resumen = await eta.refrescar_todas(db)
        await db.commit()
    return resumen


@celery_app.task(name="acma.refrescar_eta")
def refrescar_eta() -> dict:
    resumen = asyncio.run(refrescar_eta_async())
    log.info("refrescar_eta: %s", resumen)
    return resumen


async def expirar_propuestas_async(url: str | None = None) -> dict:
    from services.rutas import recalculo_service

    async with sesion_tarea(url=url) as db:
        vencidas = await recalculo_service.expirar_vencidas(db)
        await db.commit()
    return {"expiradas": vencidas}


@celery_app.task(name="acma.expirar_propuestas_ruta")
def expirar_propuestas_ruta() -> dict:
    resumen = asyncio.run(expirar_propuestas_async())
    if resumen["expiradas"]:
        log.info("expirar_propuestas_ruta: %s", resumen)
    return resumen
