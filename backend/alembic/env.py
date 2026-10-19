"""Alembic async. Migra con el rol dueño del esquema (DATABASE_MIGRATIONS_URL), nunca con acma_api.

La URL puede sobrescribirse con `-x url=...` (lo usan las pruebas para la base acma_test).
"""
import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from core.config import config as configuracion
from models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _url() -> str:
    x = context.get_x_argument(as_dictionary=True)
    url = x.get("url") or config.attributes.get("url") or configuracion.database_migrations_url
    if not url:
        raise RuntimeError("Define DATABASE_MIGRATIONS_URL (rol acma_owner) para migrar")
    return url


def _migrar(conexion) -> None:
    context.configure(connection=conexion, target_metadata=target_metadata, transaction_per_migration=True)
    with context.begin_transaction():
        context.run_migrations()


async def _correr() -> None:
    engine = create_async_engine(_url(), poolclass=NullPool)
    async with engine.connect() as conexion:
        await conexion.run_sync(_migrar)
        await conexion.commit()
    await engine.dispose()


if context.is_offline_mode():
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(_correr())
