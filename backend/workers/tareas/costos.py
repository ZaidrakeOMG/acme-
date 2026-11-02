"""Tareas de P09: reposición diaria de caja chica al cierre de jornada (§6.5), depreciación y TCO mensuales (§6.9.4) y
exportación automática al ERP por período (§6.6)."""
import asyncio
import logging
from datetime import UTC, date, datetime

from workers.celery_app import celery_app
from workers.tareas import sesion_tarea

log = logging.getLogger("acma.tareas.costos")


async def polizas_caja_chica_async(fecha: date | None = None, url: str | None = None) -> dict:
    from services import caja_chica_service
    from services.folio_estados import ACTOR_SISTEMA

    async with sesion_tarea(url=url) as db:
        resumen = await caja_chica_service.generar_polizas_del_dia(db, ACTOR_SISTEMA, fecha)
        await db.commit()
    return resumen


async def depreciacion_y_tco_async(hasta: date | None = None, url: str | None = None) -> dict:
    from services import activos_service

    async with sesion_tarea(url=url) as db:
        resumen = await activos_service.calcular_mes(db, hasta)
        await db.commit()
    return resumen


async def exportacion_erp_async(url: str | None = None) -> dict:
    """Exportación opcional al cierre de período: solo para los prestadores que la activaron."""
    from sqlalchemy import select

    from core.dependencias import Actor
    from models.base import Dominio, Rol
    from models.costos import ErpConfiguracion
    from services.erp import exportacion

    hoy = date.today()
    if hoy.day != 1:
        return {"omitida": True, "motivo": "la exportación automática corre el primer día del mes"}
    primero_mes_anterior = (hoy.replace(day=1) - __import__("datetime").timedelta(days=1)).replace(day=1)
    fin_mes_anterior = hoy.replace(day=1) - __import__("datetime").timedelta(days=1)
    resumen = {"exportaciones": 0, "eventos": 0}
    async with sesion_tarea(url=url) as db:
        for cfg in (await db.execute(select(ErpConfiguracion).where(ErpConfiguracion.exportacion_automatica.is_(True)))).scalars():
            actor = Actor(id=None, email="sistema@acma", nombre="sistema", rol=Rol.admin_prestador, dominio=Dominio.prestador, tenant_id=None,
                          prestador_id=cfg.prestador_id, sesion_id=None)
            exp = await exportacion.exportar(db, actor, desde=primero_mes_anterior, hasta=fin_mes_anterior, prestador_id=cfg.prestador_id)
            resumen["exportaciones"] += 1
            resumen["eventos"] += exp.eventos_incluidos
        await db.commit()
    return resumen


@celery_app.task(name="acma.generar_polizas_caja_chica")
def generar_polizas_caja_chica() -> dict:
    resumen = asyncio.run(polizas_caja_chica_async())
    log.info("generar_polizas_caja_chica: %s", resumen)
    return resumen


@celery_app.task(name="acma.calcular_depreciacion_tco")
def calcular_depreciacion_tco() -> dict:
    resumen = asyncio.run(depreciacion_y_tco_async())
    log.info("calcular_depreciacion_tco: %s", resumen)
    return resumen


@celery_app.task(name="acma.exportar_erp_periodo")
def exportar_erp_periodo() -> dict:
    resumen = asyncio.run(exportacion_erp_async())
    log.info("exportar_erp_periodo: %s", resumen)
    return resumen
