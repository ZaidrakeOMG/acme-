"""Diagnóstico de .env de ACMA que NO revela valores ni contraseñas.

El iniciador original omitía el asistente Supabase si existía un .env
heredado del Docker; luego el preflight fallaba con DB_SCHEMA=public.
Aquí nunca se cambia el host, la contraseña, el bucket ni el rol SQL.

Si el archivo tiene ya una configuración Supabase completa y solo falta
DB_SCHEMA=acma, se ofrece arreglar únicamente esa línea con confirmación
explícita, conservando una copia local ignorada por Git.
"""
from __future__ import annotations

from pathlib import Path
import os
import re
import shutil
import sys
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / ".env"


def cargar_valores(contenido: str) -> tuple[dict[str, str], list[str]]:
    valores: dict[str, str] = {}
    repetidos: list[str] = []
    for linea in contenido.splitlines():
        if linea.lstrip().startswith("#"):
            continue
        match = re.match(r"^\s*([A-Za-z_][A-Za-z_0-9]*)\s*=\s*(.*)$", linea)
        if not match:
            continue
        nombre, valor = match.groups()
        nombre = nombre.upper()
        # La lectura solo usa coincidencias exactas y nunca imprime secretos.
        valor = valor.strip()
        if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in {"'", '"'}:
            valor = valor[1:-1]
        if nombre in valores:
            repetidos.append(nombre)
        valores[nombre] = valor
    return valores, repetidos


def es_dsn_supabase(valor: str) -> bool:
    try:
        p = urlsplit(valor)
        return (
            p.scheme == "postgresql+asyncpg"
            and p.hostname is not None
            and (
                re.fullmatch(r"db\.[a-z0-9]{8,32}\.supabase\.co", p.hostname) is not None
                or p.hostname.endswith(".pooler.supabase.com")
            )
        )
    except ValueError:
        return False


def es_url_publica_supabase(valor: str) -> bool:
    try:
        p = urlsplit(valor)
        return (
            p.scheme == "https" and
            re.fullmatch(r"[a-z0-9]{8,32}\.supabase\.co", p.hostname or "") is not None
        )
    except ValueError:
        return False


def respaldo_privado() -> Path:
    indice = 0
    while True:
        ruta = ROOT / (
            ".env.respaldo_antes_db_schema" + (f"_{indice}" if indice else "")
        )
        if not ruta.exists():
            shutil.copy2(ENV, ruta)
            return ruta
        indice += 1


def corregir_solo_esquema(original: str, existen: dict[str, str]) -> None:
    print("\nLa conexión ya apunta a Supabase; únicamente falta DB_SCHEMA=acma.")
    print("No se modificarán DATABASE_URL, contraseñas, JWT ni Storage.")
    respuesta = input("Escribe CORREGIR para respaldar .env y ajustar solo DB_SCHEMA: ").strip()
    if respuesta != "CORREGIR":
        print("Sin cambios. Puedes editar manualmente la línea DB_SCHEMA=acma.")
        raise SystemExit(2)

    copia = respaldo_privado()
    if "DB_SCHEMA" in existen:
        nuevo, veces = re.subn(
            r"(?m)^\s*DB_SCHEMA\s*=.*$",
            "DB_SCHEMA=acma",
            original,
            count=1,
        )
        if veces != 1:
            print("Hay una configuración DB_SCHEMA inusual. Edita el archivo manualmente.")
            raise SystemExit(2)
    else:
        nuevo = original.rstrip("\r\n") + "\nDB_SCHEMA=acma\n"

    # Privacidad: sólo el archivo local, nunca Git. El respaldo queda protegido
    # por .gitignore (.env.*). No mostrar contenido.
    ENV.write_text(nuevo, encoding="utf-8")
    print("DB_SCHEMA=acma configurado; .env anterior respaldado en " + copia.name)


def main() -> int:
    if not ENV.is_file():
        print("No existe .env. El lanzador abrirá el asistente Supabase.")
        return 0

    original = ENV.read_text(encoding="utf-8-sig")
    valores, duplicados = cargar_valores(original)

    # Configuracion(BaseSettings) lee primero ROOT/.env y luego
    # ROOT/backend/.env. El segundo archivo puede sobrescribir las claves
    # incluso después de corregir el archivo de la raíz.
    backend_env = ROOT / "backend" / ".env"
    if backend_env.is_file() and backend_env.resolve() != ENV.resolve():
        heredado, _ = cargar_valores(backend_env.read_text(encoding="utf-8-sig"))
        claves_solapadas = sorted(set(heredado) & {
            "DB_SCHEMA", "DATABASE_URL", "ALMACENAMIENTO_MODO",
            "SUPABASE_URL", "SUPABASE_SECRET_KEY",
        })
        if claves_solapadas:
            print("ERROR: backend/.env contiene variables que sustituyen las de .env.")
            print("Variables duplicadas entre archivos: " + ", ".join(claves_solapadas))
            print("Respalda backend/.env fuera del repositorio y revisa esas variables;")
            print("no puedo decidir cuáles credenciales deben prevalecer.")
            return 2
    # Variables del sistema también tienen precedencia sobre los archivos.
    esquema_sistema = os.environ.get("DB_SCHEMA")
    if esquema_sistema and esquema_sistema != "acma":
        print("ERROR: Windows define DB_SCHEMA con un valor distinto de acma.")
        print("Revisa esa variable de entorno antes de iniciar el proceso.")
        return 2

    print("Diagnóstico seguro de configuración (.env):")
    if duplicados:
        print("ERROR: hay variables repetidas en .env. Revisar nombres: " +
              ", ".join(sorted(set(duplicados))))
        return 2

    postgres = es_dsn_supabase(valores.get("DATABASE_URL", ""))
    storage_url = es_url_publica_supabase(valores.get("SUPABASE_URL", ""))
    almacenamiento = valores.get("ALMACENAMIENTO_MODO", "") == "supabase"
    secret = bool(valores.get("SUPABASE_SECRET_KEY", "").strip())
    esquema = valores.get("DB_SCHEMA", "public")

    print("  PostgreSQL alojado en Supabase: " + ("sí" if postgres else "no / por configurar"))
    print("  Supabase Storage privado configurado: " +
          ("sí" if storage_url and almacenamiento and secret else "no / incompleto"))
    print("  DB_SCHEMA configurado como acma: " + ("sí" if esquema == "acma" else "no"))
    print("  No se muestran URLs completas, usuarios, claves ni contraseñas.")

    if not (postgres and storage_url and almacenamiento and secret):
        print("\nSe encontró un .env antiguo o incompleto para Supabase.")
        print("El sistema conservará el archivo anterior SIN modificar su contenido.")
        print("Se guardará como .env.respaldo_anterior (con sufijo si existe).")
        print("La copia queda IGNORADA por Git, pero contiene secretos: guárdala segura.")
        print("Iniciando respaldo automático del .env anterior (sin borrarlo).")
        print("Después se abrirá el asistente de PostgreSQL y Storage.")
        numero = 0
        while True:
            nombre = ".env.respaldo_anterior" + (f"_{numero}" if numero else "")
            destino = ROOT / nombre
            if not destino.exists():
                break
            numero += 1
        # Rename atómico, no borra secretos y no sustituye respaldos previos.
        ENV.rename(destino)
        print("Respaldo local guardado: " + destino.name)
        print("El asistente puede crear un .env NUEVO para Supabase.")
        return 3

    if esquema != "acma":
        corregir_solo_esquema(original, valores)
    else:
        print("Configuración básica de Supabase presente. Ejecutando preflight real.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, UnicodeError, KeyboardInterrupt) as exc:
        print("ERROR al leer/guardar .env. " + type(exc).__name__ +
              ". Revisa permisos del archivo.", file=sys.stderr)
        raise SystemExit(2) from None
