"""Asistente de configuración LOCAL para ACMA + Supabase, sin Docker.

Pide datos privados solo en la terminal del equipo del usuario, nunca por chat.
El .env se excluye de git. No borra tablas ni ejecuta las migraciones.
Crea una contraseña para el rol SQL acma_api y después inicializa la cuenta
superadmin con el seed de PRODUCCIÓN original y su password temporal única.
"""
from __future__ import annotations

import asyncio
import base64
import getpass
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
from urllib.parse import quote, urlencode, urlsplit, urlunsplit, parse_qsl

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / ".env"


def referencia_proyecto(url: str) -> str:
    partes = urlsplit(url.rstrip("/"))
    if partes.scheme != "https" or not partes.hostname:
        raise ValueError("La URL pública de Supabase debe usar https.")
    match = re.fullmatch(r"([a-z0-9]{8,32})\.supabase\.co", partes.hostname)
    if not match or partes.path not in {"", "/"}:
        raise ValueError("Copia la URL exacta https://TU-REF.supabase.co.")
    return match.group(1)


def validar_dsn_privilegiado(dsn: str, ref: str) -> tuple[object, bool]:
    """Admite solo conexión directa o Session pooler del proyecto indicado."""
    p = urlsplit(dsn)
    if p.scheme not in {"postgres", "postgresql"} or not p.hostname:
        raise ValueError("Copia la cadena PostgreSQL desde Supabase > Connect.")
    if p.username is None or p.password is None or p.password.startswith("["):
        raise ValueError("La cadena debe incluir la contraseña real de PostgreSQL.")
    if p.port != 5432 or p.path != "/postgres":
        raise ValueError("Se requiere puerto 5432 y base postgres (no Transaction pooler 6543).")
    directo = p.hostname == f"db.{ref}.supabase.co"
    pooler = p.hostname.endswith(".pooler.supabase.com")
    if directo and p.username != "postgres":
        raise ValueError("Para conexión directa el usuario debe ser postgres.")
    if pooler and p.username != f"postgres.{ref}":
        raise ValueError("En Session pooler el usuario debe ser postgres.REF.")
    if not directo and not pooler:
        raise ValueError("El host PostgreSQL no corresponde a Supabase.")
    return p, pooler


def dsn_para_acma(partes, ref: str, pooler: bool, contrasena: str) -> str:
    """Construye DSN para SQLAlchemy/asyncpg con rol de mínimo privilegio."""
    usuario = f"acma_api.{ref}" if pooler else "acma_api"
    host = partes.hostname
    parametros = dict(parse_qsl(partes.query, keep_blank_values=True))
    parametros.pop("sslmode", None)
    parametros["ssl"] = "require"
    return urlunsplit((
        "postgresql+asyncpg",
        f"{usuario}:{quote(contrasena, safe='')}@{host}:5432",
        "/postgres",
        urlencode(parametros),
        "",
    ))


def comprobar_bucket(project_url: str, key: str) -> None:
    import httpx

    with httpx.Client(timeout=20) as client:
        r = client.get(
            project_url.rstrip("/") + "/storage/v1/bucket/acma",
            headers={"apikey": key, "Authorization": f"Bearer {key}"},
        )
        if r.status_code == 404:
            raise RuntimeError(
                "Falta bucket acma: ejecuta docs/01_CREAR_BUCKET_PRIVADO_ACMA.sql en Supabase."
            )
        r.raise_for_status()
        b = r.json()
        if b.get("id", "acma") != "acma" or b.get("public") is not False:
            raise RuntimeError("Storage acma debe existir y ser un bucket PRIVADO.")


async def clave_rol_api(dsn_postgres: str, ref: str) -> tuple[str, bool]:
    import asyncpg

    partes, pooler = validar_dsn_privilegiado(dsn_postgres, ref)
    conexion = await asyncpg.connect(dsn=dsn_postgres, ssl="require", timeout=25)
    try:
        if await conexion.fetchval("SELECT current_user") != "postgres":
            raise RuntimeError("La conexión de administración debe usar el rol postgres.")
        revision = await conexion.fetchval("SELECT version_num FROM acma.alembic_version")
        if revision != "0018":
            raise RuntimeError("ACMA no tiene Alembic 0018. No se tocará ningún rol.")
        tablas = await conexion.fetchval("""
            SELECT count(*) FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'acma' AND c.relkind IN ('r', 'p')
        """)
        if tablas < 181:
            raise RuntimeError("Faltan tablas en ACMA. No se tocará ningún rol.")
        rol = await conexion.fetchrow(
            "SELECT rolcanlogin, rolbypassrls FROM pg_roles WHERE rolname='acma_api'"
        )
        if not rol or not rol["rolcanlogin"] or rol["rolbypassrls"]:
            raise RuntimeError("acma_api no tiene el perfil de acceso seguro esperado.")
        # Generación local y escape SQL realizado por el propio PostgreSQL.
        # Nunca interpolamos texto aportado por el usuario a SQL privilegiado.
        contrasena = secrets.token_urlsafe(36)
        literal = await conexion.fetchval("SELECT quote_literal($1::text)", contrasena)
        await conexion.execute(f"ALTER ROLE acma_api WITH PASSWORD {literal}")
        return contrasena, pooler
    finally:
        await conexion.close()


def escribir_env(dsn: str, project_url: str, secret_key: str) -> None:
    if ENV.exists():
        raise FileExistsError(
            "Ya existe .env. No lo sobrescribo: haz una copia segura si necesitas reconfigurar."
        )
    jwt = secrets.token_urlsafe(48)
    aes = base64.b64encode(os.urandom(32)).decode("ascii")
    variables = [
        "# ACMA: PRUEBA WEB con Supabase (secretos locales, nunca subir a GitHub)",
        "ACMA_ENTORNO=pruebas",
        "DB_SCHEMA=acma",
        f"DATABASE_URL={dsn}",
        "DATABASE_MIGRATIONS_URL=",
        "DATABASE_READ_URL=",
        f"SUPABASE_URL={project_url}",
        f"SUPABASE_SECRET_KEY={secret_key}",
        "SUPABASE_BUCKET=acma",
        "ALMACENAMIENTO_MODO=supabase",
        f"JWT_SECRETO={jwt}",
        f"CLAVE_CIFRADO={aes}",
        "MFA_OBLIGATORIO=true",
        "APP_URL_PUBLICA=http://localhost:8000",
        "CORS_ORIGENES=http://localhost:8000,http://127.0.0.1:8000",
        "DB_POOL_SIZE=3",
        "DB_POOL_OVERFLOW=1",
        "DB_POOL_TIMEOUT=15",
        "# Primera prueba: sin Redis/Celery; no operan tareas periódicas hasta configurar worker/beat.",
        "TIEMPO_REAL_MODO=local",
        "NOTIFICACIONES_ENVIO_INLINE=true",
        "WHATSAPP_MODO=stub",
        "SMS_MODO=stub",
        "RUTAS_MOTOR_TRANSPORTE=en_proceso",
    ]
    # Exclusive create: no pisar otra instalación. UTF-8 sin BOM.
    with ENV.open("x", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(variables) + "\n")


def ejecutar_script(modulo: str, *args: str) -> None:
    resultado = subprocess.run(
        [sys.executable, "-m", modulo, *args], cwd=ROOT / "backend", check=False
    )
    if resultado.returncode:
        raise RuntimeError(
            f"El paso {modulo} falló con código {resultado.returncode}. "
            "Revisa la salida de tu consola; no compartas archivos .env."
        )


def main() -> None:
    print("\nACMA - Configuración segura de WEB + Supabase\n")
    if ENV.exists():
        raise FileExistsError("Ya existe .env. No modificaré sus credenciales.")
    project_url = input("URL pública Supabase (https://...supabase.co): ").strip().rstrip("/")
    ref = referencia_proyecto(project_url)
    print(
        "Antes de continuar, ejecuta docs/01_CREAR_BUCKET_PRIVADO_ACMA.sql\n"
        "La clave 'secret' solo se escribe aquí y queda en tu .env local."
    )
    key = getpass.getpass("Secret API key de Supabase (oculta): ").strip()
    if not key or key.startswith("sb_publishable_"):
        raise ValueError("La clave publicable no tiene permisos de Storage para ACMA.")
    comprobar_bucket(project_url, key)
    print("Bucket acma privado: verificado.")
    print(
        "\nEn Supabase > Connect selecciona 'Session pooler' puerto 5432"
        " si tu PC no usa IPv6. Copia la cadena como usuario postgres"
        " y reemplaza el marcador por la contraseña de PostgreSQL."
    )
    dsn_postgres = getpass.getpass("Cadena PostgreSQL del botón Connect (oculta): ").strip()
    # Supabase copia normalmente una cadena con [YOUR-PASSWORD].
    # Solicitar la clave por separado evita errores si contiene @, #, / o :.
    if "[YOUR-PASSWORD]" in dsn_postgres:
        clave_postgres = getpass.getpass("Contraseña PostgreSQL de Supabase (oculta): ")
        if not clave_postgres:
            raise ValueError("La contraseña de PostgreSQL está vacía")
        dsn_postgres = dsn_postgres.replace(
            "[YOUR-PASSWORD]", quote(clave_postgres, safe="")
        )
    partes, pooler = validar_dsn_privilegiado(dsn_postgres, ref)
    print("Solo cambiaré la contraseña SQL de acma_api y crearé .env local.")
    if input("Escribe CONFIGURAR para continuar: ").strip() != "CONFIGURAR":
        print("Cancelado. No hubo cambios.")
        return
    pwd, pooler = asyncio.run(clave_rol_api(dsn_postgres, ref))
    dsn = dsn_para_acma(partes, ref, pooler, pwd)
    # Guardar de inmediato la clave, antes de probar el acceso, para poder
    # recuperar la instalación incluso si la red falla tras ALTER ROLE.
    escribir_env(dsn, project_url, key)
    print("\n.env local creado. Las credenciales de postgres NO se guardaron.")
    ejecutar_script("scripts.preflight_supabase")
    print("\nCuenta superadmin inicial de ACMA (sin datos de demostración).")
    email = input("Tu correo real para entrar como administrador: ").strip().lower()
    nombre = input("Nombre para el administrador: ").strip()
    if not email or not nombre:
        raise ValueError("Correo y nombre requeridos. Puedes ejecutar seed_produccion después.")
    ejecutar_script("scripts.seed_produccion", "--email", email, "--nombre", nombre)
    print("\nConfiguración web lista para probar. Ejecuta iniciar_acma_web_pruebas.bat.")
    print("Guarda la contraseña temporal que apareció UNA sola vez en consola.")
    input("Pulsa ENTER después de guardar la contraseña temporal en un lugar seguro... ")
    print("Para producción configura Redis, Celery, HTTPS y pruebas móviles.")


if __name__ == "__main__":
    try:
        main()
    except (Exception, KeyboardInterrupt) as error:
        print(f"\nConfiguración detenida: {error}", file=sys.stderr)
        sys.exit(1)
