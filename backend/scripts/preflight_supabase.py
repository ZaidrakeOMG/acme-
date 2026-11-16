"""Comprobación no destructiva de la conexión ACMA→Supabase con el rol de la API.

Uso (desde backend): python -m scripts.preflight_supabase
No se conecta a storage, no crea usuarios, no modifica tablas ni muestra claves.
Este test NO sustituye la auditoría SQL de columnas, RLS y estructuras.
"""
import asyncio
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from core.config import config
from core.esquema_postgresql import opciones_conexion


async def comprobar_bd() -> None:
    if config.db_schema != "acma":
        raise RuntimeError("DB_SCHEMA debe ser 'acma' para conectar Supabase")
    if not config.database_url.startswith("postgresql+asyncpg://"):
        raise RuntimeError("DATABASE_URL debe usar el driver postgresql+asyncpg")
    engine = create_async_engine(
        config.database_url,
        poolclass=NullPool,
        **opciones_conexion(config.db_schema),
    )
    try:
        async with engine.connect() as conn:
            async with conn.begin():
                fila = (await conn.execute(text("""
                    SELECT current_user,
                           current_schema(),
                           current_setting('search_path') AS ruta,
                           (SELECT rolbypassrls
                              FROM pg_roles
                             WHERE rolname = current_user) AS omite_rls,
                           to_regclass('acma.usuarios') IS NOT NULL AS usuarios,
                           to_regclass('acma.rutas_planes') IS NOT NULL AS rutas,
                           has_schema_privilege(current_user,'acma','USAGE') AS esquema,
                           has_function_privilege(
                              current_user, 'acma.auth_identidad_por_email(text)','EXECUTE'
                           ) AS autenticacion
                """))).one()
                usuario, esquema, ruta, bypass, tabla_usuarios, tabla_rutas, acceso, login = fila
                # Por diseño acma_api NO tiene SELECT en alembic_version:
                # la revisión 0018 se valida desde SQL Editor, no desde la aplicación.
                if usuario != "acma_api":
                    raise RuntimeError("El backend debe conectarse como acma_api, no " + usuario)
                if esquema != "acma" or not ruta.startswith("acma,"):
                    raise RuntimeError("El search_path no está fijado al esquema privado acma")
                if bypass or not all((tabla_usuarios, tabla_rutas, acceso, login)):
                    raise RuntimeError("Faltan tablas/permisos o se está omitiendo RLS")
    finally:
        await engine.dispose()

    if config.almacenamiento_modo != "supabase":
        raise RuntimeError("Configura ALMACENAMIENTO_MODO=supabase para conservar evidencias en Storage")
    from services.almacenamiento_supabase import AlmacenamientoSupabase
    almacenamiento = AlmacenamientoSupabase(
        url=config.supabase_url,
        key=config.supabase_secret_key,
        bucket=config.supabase_bucket,
    )
    await asyncio.to_thread(almacenamiento.comprobar)
    print("ACMA: DB PostgreSQL con rol acma_api y bucket PRIVADO acma: verificados.")
    print("El modo de prueba web no incluye Redis/Celery ni tareas periódicas.")


def main() -> None:
    try:
        asyncio.run(comprobar_bd())
    except Exception as error:
        print("ERROR ACMA Supabase: " + str(error), file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
