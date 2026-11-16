"""Alta de un segundo superadministrador en ACMA Supabase.

Se ejecuta localmente con backend/.venv y .env ya configurado. Jamás
lleva contraseñas como argumentos, ni guarda contraseñas en el repositorio.
No borra ni modifica usuarios existentes ni los datos de la plataforma.
"""
from __future__ import annotations

import asyncio
import getpass
import sys
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, text

from core.config import config
from core.db import nueva_sesion
from core.rls import CONTEXTO_SISTEMA
from core.security import errores_politica_contrasena, hashear_contrasena_async
from models.base import Dominio, EstadoRegistro, Rol, dominio_de_rol
from models.usuarios import Usuario

CORREO = "zaidfarjat@gmail.com"
NOMBRE = "Zaid Farjat"


def pedir_contrasena() -> str:
    """Aplica exactamente la misma política que el API original de ACMA."""
    print("La contraseña debe tener al menos 10 caracteres, mayúscula,")
    print("minúscula, número y UN SÍMBOLO (!, #, etc.).")
    print("No se mostrará ni se guardará como texto.")
    for intento in range(3):
        primera = getpass.getpass("Contraseña inicial (oculta): ")
        errores = errores_politica_contrasena(primera)
        if errores:
            print("No cumple la política ACMA: " + "; ".join(errores))
            continue
        segunda = getpass.getpass("Repite la contraseña (oculta): ")
        if primera != segunda:
            print("Las contraseñas no coinciden.")
            continue
        return primera
    raise ValueError("No se recibió una contraseña válida en tres intentos.")


async def crear_si_no_existe(contrasena: str) -> bool:
    if config.db_schema != "acma" or config.almacenamiento_modo != "supabase":
        raise RuntimeError("El archivo .env debe apuntar a Supabase y usar DB_SCHEMA=acma.")
    if not config.database_url.startswith("postgresql+asyncpg://"):
        raise RuntimeError("DATABASE_URL no usa PostgreSQL/asyncpg.")
    if any(h in config.database_url.lower() for h in ("localhost", "127.0.0.1")):
        raise RuntimeError("No se permite crear el administrador en una base local Docker.")

    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        # Privilegios de aplicación y contexto RLS, sin conexión postgres
        # superusuario ni SECURITY DEFINER adicional.
        identity = (await db.execute(text("SELECT current_user"))).scalar_one()
        if identity != "acma_api":
            raise RuntimeError("La conexión debe autenticarse como acma_api.")

        anterior = (await db.execute(
            select(Usuario).where(func.lower(Usuario.email) == CORREO)
        )).scalar_one_or_none()
        if anterior is not None:
            if anterior.rol == Rol.superadmin:
                print("Este correo ya existe como superadmin. NO se cambió su contraseña.")
            else:
                print("Este correo ya está registrado con otro rol. No se elevarán permisos.")
            return False

        if input("Escribe CREAR para dar de alta este superadmin: ").strip() != "CREAR":
            print("Cancelado: no se escribió ningún usuario.")
            return False

        # No guardar contraseña ni imprimirla: solo Argon2.
        nuevo = Usuario(
            email=CORREO,
            nombre=NOMBRE,
            rol=Rol.superadmin,
            dominio=dominio_de_rol(Rol.superadmin),
            estado=EstadoRegistro.activo,
            password_hash=await hashear_contrasena_async(contrasena),
            # Contraseña inicial de un solo uso, como seed_produccion original.
            password_actualizado_at=(
                datetime.now(UTC) - timedelta(days=config.contrasena_dias_admin + 1)
            ),
        )
        db.add(nuevo)
        await db.commit()
        print(f"Superadmin creado correctamente: {CORREO}")
        print("Al entrar se solicitará MFA y cambio de contraseña inicial.")
        return True


def main() -> None:
    print("\nACMA - Crear superadmin adicional en la base Supabase\n")
    print(f"Correo: {CORREO}")
    print(f"Nombre: {NOMBRE}")
    print("Rol: superadmin / dominio plataforma")
    print("No se modificará el administrador original.")
    clave = pedir_contrasena()
    asyncio.run(crear_si_no_existe(clave))


if __name__ == "__main__":
    try:
        main()
    except (Exception, KeyboardInterrupt) as exc:
        # Evitar imprimir la cadena DATABASE_URL o credenciales en un traceback.
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
