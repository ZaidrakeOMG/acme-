"""Tareas en background. Cada tarea abre su propio engine (NullPool) y fija el contexto RLS explícitamente;
nunca comparte el engine global de la API entre tareas concurrentes."""
import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from core.config import config
from core.rls import CONTEXTO_SISTEMA, ContextoRLS, SesionRLS
from models.alertas import AlertaCatalogo
from models.usuarios import Sesion
from workers.celery_app import celery_app

log = logging.getLogger("acma.tareas")

# clave de alerta -> evaluador. Cada módulo (P02–P10) registra el suyo; el evaluador revisa su condición
# y llama a services.alertas_service.disparar() por cada entidad que la cumpla. Devuelve cuántas disparó.
Evaluador = Callable[[AsyncSession, AlertaCatalogo], Awaitable[int]]
EVALUADORES: dict[str, Evaluador] = {}


def registrar_evaluador(clave: str):
    def _decorador(funcion: Evaluador) -> Evaluador:
        EVALUADORES[clave] = funcion
        return funcion
    return _decorador


@asynccontextmanager
async def sesion_tarea(contexto: ContextoRLS = CONTEXTO_SISTEMA, url: str | None = None):
    engine = create_async_engine(url or config.database_url, poolclass=NullPool)
    fabrica = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession, sync_session_class=SesionRLS)
    sesion = fabrica()
    sesion.info["rls"] = contexto
    try:
        yield sesion
    finally:
        await sesion.close()
        await engine.dispose()


async def evaluar_alertas_async(url: str | None = None) -> dict:
    resumen = {"evaluadas": 0, "sin_evaluador": 0, "disparadas": 0, "errores": 0}
    async with sesion_tarea(url=url) as db:
        catalogo = (await db.execute(select(AlertaCatalogo).order_by(AlertaCatalogo.clave))).scalars().all()
        for alerta in catalogo:
            evaluador = EVALUADORES.get(alerta.clave)
            if evaluador is None:
                resumen["sin_evaluador"] += 1
                continue
            try:
                async with db.begin_nested():
                    resumen["disparadas"] += await evaluador(db, alerta)
                resumen["evaluadas"] += 1
            except Exception:
                resumen["errores"] += 1
                log.exception("Error evaluando la alerta %s", alerta.clave)
        await db.commit()
    return resumen


async def crear_particiones_async(url: str | None = None) -> int:
    async with sesion_tarea(url=url) as db:
        creadas = (await db.execute(text("SELECT acma_crear_particiones_auditoria(3)"))).scalar_one()
        await db.commit()
        return creadas


async def purgar_sesiones_async(url: str | None = None) -> int:
    limite = datetime.now(UTC) - timedelta(days=30)
    async with sesion_tarea(url=url) as db:
        resultado = await db.execute(delete(Sesion).where(Sesion.expira_at < limite))
        await db.commit()
        return resultado.rowcount or 0


@celery_app.task(name="acma.evaluar_alertas")
def evaluar_alertas() -> dict:
    resumen = asyncio.run(evaluar_alertas_async())
    log.info("evaluar_alertas: %s", resumen)
    return resumen


@celery_app.task(name="acma.crear_particiones_auditoria")
def crear_particiones_auditoria() -> int:
    return asyncio.run(crear_particiones_async())


@celery_app.task(name="acma.purgar_sesiones_expiradas")
def purgar_sesiones_expiradas() -> int:
    return asyncio.run(purgar_sesiones_async())
