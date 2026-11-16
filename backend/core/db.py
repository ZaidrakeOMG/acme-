"""Engine y sesiones async de SQLAlchemy.

Cada sesión lleva su contexto RLS en `session.info["rls"]`; el listener de
`core.rls` lo aplica con `set_config(..., true)` (equivalente a SET LOCAL) al
inicio de cada transacción, de modo que un commit no deja la conexión sin
contexto para la siguiente consulta.
"""
from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from core.config import config
from core.esquema_postgresql import opciones_conexion
from core.rls import ContextoRLS, SesionRLS


def crear_engine(url: str) -> AsyncEngine:
    """Pool configurable. P11a: con 10+10 conexiones, 70 usuarios concurrentes agotaban el pool y la API devolvia
    500 por `QueuePool limit ... connection timed out`. El tamaño se calcula junto con los workers de uvicorn y el
    `max_connections` de PostgreSQL; ver docs/rendimiento/resultados.md."""
    kwargs = opciones_conexion(config.db_schema)
    if config.db_pool_nulo:
        return create_async_engine(url, poolclass=NullPool, **kwargs)
    return create_async_engine(url, pool_size=config.db_pool_size, max_overflow=config.db_pool_overflow,
                               pool_timeout=config.db_pool_timeout, pool_recycle=1800, pool_pre_ping=True, **kwargs)


engine = crear_engine(config.database_url)
# Réplica de lectura: misma URL si DATABASE_READ_URL está vacía (Fase 2: réplicas regionales).
engine_lectura = engine if config.url_lectura == config.database_url else crear_engine(config.url_lectura)

SesionLocal = async_sessionmaker(
    engine, expire_on_commit=False, class_=AsyncSession, sync_session_class=SesionRLS
)


def reconstruir_sin_pool() -> None:
    """Para el worker de Celery (`celeryd_init`): cada tarea abre y cierra su propio event loop, y un pool
    compartido guardaria conexiones de loops ya cerrados; la siguiente tarea las reusaba y el envio fallaba
    con "Event loop is closed". Sin pool, cada sesion abre su conexion y la cierra al terminar."""
    global engine, engine_lectura, SesionLocal

    config.db_pool_nulo = True
    engine = crear_engine(config.database_url)
    engine_lectura = engine if config.url_lectura == config.database_url else crear_engine(config.url_lectura)
    SesionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession, sync_session_class=SesionRLS)


def nueva_sesion(contexto: ContextoRLS | None) -> AsyncSession:
    """Sesión con contexto RLS explícito (scripts, Celery, middleware de auditoría)."""
    sesion = SesionLocal()
    sesion.info["rls"] = contexto or ContextoRLS()
    return sesion


async def obtener_db(request: Request) -> AsyncIterator[AsyncSession]:
    """Dependencia FastAPI: sesión cuyo contexto lo fijó el middleware de contexto."""
    contexto: ContextoRLS = getattr(request.state, "contexto_rls", None) or ContextoRLS()
    sesion = nueva_sesion(contexto)
    try:
        yield sesion
    finally:
        if sesion.in_transaction():
            await sesion.rollback()
        await sesion.close()
