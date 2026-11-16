"""Crea el primer superadmin REAL de ACMA, sin claves/demo y sin Docker.

No ejecutar hasta validar funciones auth_*, roles, RLS y conectividad a Supabase.
Solo actúa en el esquema privado acma cuando la tabla usuarios está vacía.
No borra ni modifica usuarios existentes; pide contraseña de forma oculta.

Ejemplo desde backend:
  .venv\\Scripts\\python -m scripts.bootstrap_superadmin
"""
import asyncio
import getpass
import re
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool
from core.config import config
from core.esquema_postgresql import opciones_conexion
from core.security import errores_politica_contrasena, hashear_contrasena


def preparar_datos():
    email = input("Correo para el superadmin de ACMA: ").strip().lower()
    nombre = input("Nombre completo: ").strip()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise ValueError("Correo electrónico inválido")
    if not 2 <= len(nombre) <= 160:
        raise ValueError("Nombre requerido de 2 a 160 caracteres")
    contrasena = getpass.getpass("Contraseña nueva (oculta): ")
    errores = errores_politica_contrasena(contrasena)
    if errores:
        raise ValueError("Contraseña insuficiente: " + ", ".join(errores))
    if contrasena != getpass.getpass("Confirmar contraseña: "):
        raise ValueError("Las contraseñas no coinciden")
    return email, nombre, contrasena


async def crear_admin(email: str, nombre: str, contrasena: str) -> str:
    if config.db_schema != "acma":
        raise RuntimeError("Configura DB_SCHEMA=acma antes del bootstrap en Supabase")
    if not config.database_url.startswith("postgresql+asyncpg://"):
        raise ValueError("DATABASE_URL debe ser PostgreSQL con asyncpg")
    if "localhost" in config.database_url.lower() or "127.0.0.1" in config.database_url:
        raise RuntimeError("Se requiere proyecto Supabase remoto exclusivo de ACMA")
    if config.acma_entorno == "produccion" and not config.mfa_obligatorio:
        raise RuntimeError("En producción MFA debe ser obligatorio")

    # Esquema explícito, sin tocar public, auth ni storage de Supabase.
    engine = create_async_engine(
        config.database_url,
        poolclass=NullPool,
        **opciones_conexion(config.db_schema),
    )
    try:
        async with engine.begin() as conn:
            version = (await conn.execute(
                text("SELECT version_num FROM acma.alembic_version")
            )).scalar_one()
            if version != "0018":
                raise RuntimeError("Esquema incompatible; se esperaba Alembic 0018")

            existentes = (await conn.execute(
                text("SELECT count(*) FROM acma.usuarios")
            )).scalar_one()
            if existentes != 0:
                raise RuntimeError(
                    "Ya existen usuarios. No se permite repetir el bootstrap."
                )

            # CONTEXTO_SISTEMA es el mismo usado por el seed original, pero
            # no se usa la contraseña pública Demo#Acma2026.
            await conn.execute(text("SELECT set_config('app.rol', 'sistema', true)"))
            hash_seguro = hashear_contrasena(contrasena)
            identificador = (await conn.execute(
                text("""
                  INSERT INTO acma.usuarios
                    (email, password_hash, nombre, rol, dominio)
                  VALUES
                    (:email, :hash, :nombre,
                     'superadmin'::acma.rol_usuario,
                     'plataforma'::acma.dominio_usuario)
                  RETURNING id
                """),
                {"email": email, "hash": hash_seguro, "nombre": nombre},
            )).scalar_one()
            return str(identificador)
    finally:
        await engine.dispose()


def main():
    print("ACMA: primer superadmin, sin datos de demostración")
    print("Antes de continuar, verifica DATABASE_URL y proyecto Supabase ACMA.")
    email, nombre, contrasena = preparar_datos()
    respuesta = input("Escribe CREAR para confirmar la creación del usuario: ")
    if respuesta != "CREAR":
        print("Operación cancelada. No se escribió nada.")
        return
    ident = asyncio.run(crear_admin(email, nombre, contrasena))
    print(f"Primer superadmin creado. Identificador: {ident}")
    print("Próximo paso: probar login, MFA obligatorio y políticas de acceso.")


if __name__ == "__main__":
    main()
