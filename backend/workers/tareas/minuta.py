"""Tareas de la minuta del día (P07): generación a la hora configurada por tenant, vencimiento de la ventana de validación y
del plazo de respuesta; recordatorio de períodos presupuestales y calificación diaria del Admin UN."""
import asyncio
import logging

from workers.celery_app import celery_app
from workers.tareas import sesion_tarea

log = logging.getLogger("acma.tareas.minuta")


async def generar_minutas_async(url: str | None = None) -> dict:
    from services import minuta_service

    async with sesion_tarea(url=url) as db:
        resumen = await minuta_service.generar_pendientes(db)
        await db.commit()
    return resumen


async def calificar_y_recordar_async(url: str | None = None) -> dict:
    from services import clasificacion_service
    from services.seguimiento import presupuesto

    async with sesion_tarea(url=url) as db:
        recordatorios = await presupuesto_recordatorios(db)
        calificaciones = await clasificacion_service.calificar_periodo_actual(db)
        await db.commit()
    return {"recordatorios_periodo": recordatorios, "calificaciones": calificaciones}


async def presupuesto_recordatorios(db) -> int:
    """Inicio de período presupuestal: aviso a Admin UN y Admin empresa con los diferidos (la minuta global del día también lo incluye)."""
    from datetime import date

    from sqlalchemy import select

    from models.base import Rol
    from models.seguimiento import PeriodoPresupuestal
    from services import notificaciones_service
    from services.seguimiento import presupuesto

    hoy = date.today()
    n = 0
    for p in (await db.execute(select(PeriodoPresupuestal).where(PeriodoPresupuestal.activo.is_(True)))).scalars():
        if p.ultimo_recordatorio == hoy or not presupuesto.inicio_de_periodo(p.tipo, p.fechas_json, hoy):
            continue
        diferidos = await presupuesto.diferidos_de(db, p.tenant_id)
        p.ultimo_recordatorio = hoy
        if not diferidos:
            continue
        destinatarios = await notificaciones_service.destinatarios_por_rol(db, [Rol.admin_empresa, Rol.admin_un], tenant_id=p.tenant_id)
        await notificaciones_service.notificar(db, "presupuesto.recordatorio", destinatarios, {"periodo": presupuesto.periodo_actual(p.tipo, p.fechas_json, hoy), "diferidos": len(diferidos)},
                                               asunto=f"Inicio de período presupuestal: {len(diferidos)} hallazgo(s) diferidos por revisar",
                                               cuerpo="Reactiva (folio o cotización) o descarta definitivamente cada registro.", url="/seguimiento/presupuesto", tenant_id=p.tenant_id)
        n += 1
    return n


@celery_app.task(name="acma.generar_minutas")
def generar_minutas() -> dict:
    resumen = asyncio.run(generar_minutas_async())
    log.info("generar_minutas: %s", resumen)
    return resumen


@celery_app.task(name="acma.calificar_admin_un")
def calificar_admin_un() -> dict:
    resumen = asyncio.run(calificar_y_recordar_async())
    log.info("calificar_admin_un: %s", resumen)
    return resumen
