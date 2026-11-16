"""Arranque de ACMA para Railway o VPS: URL publica HTTPS y secretos solo en backend.

Railway define RAILWAY_PUBLIC_DOMAIN cuando se crea un dominio público.
La web React integrada y el APK Flutter deben apuntar al mismo origen HTTPS.
No crea ni migra ninguna tabla de Supabase.
"""
from __future__ import annotations

import os
import re
import sys


DOMINIO_SEGURO = re.compile(
    r"^(?=.{4,253}$)[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)+$"
)
REQUERIDOS = ("DATABASE_URL", "SUPABASE_URL", "SUPABASE_SECRET_KEY", "JWT_SECRETO", "CLAVE_CIFRADO")


def preparar_entorno(environ: dict[str, str]) -> None:
    """Prepara valores de seguridad sin imprimir ni alterar credenciales.

    En un VPS con APP_URL_PUBLICA y CORS_ORIGENES ya configurados, respeta
    estos valores. En Railway usa su dominio generado, si está disponible.
    """
    dominio = environ.get("RAILWAY_PUBLIC_DOMAIN", "").strip()
    if dominio and not DOMINIO_SEGURO.fullmatch(dominio):
        raise ValueError("RAILWAY_PUBLIC_DOMAIN debe ser un hostname válido, sin https:// ni ruta")

    if dominio:
        origen = "https://" + dominio
        environ.setdefault("APP_URL_PUBLICA", origen)
        environ.setdefault("CORS_ORIGENES", origen)

    # El contenedor está previsto para clientes externos, NO para desarrollo sin MFA.
    environ.setdefault("ACMA_ENTORNO", "produccion")
    environ.setdefault("DB_SCHEMA", "acma")
    environ.setdefault("ALMACENAMIENTO_MODO", "supabase")
    environ.setdefault("SUPABASE_BUCKET", "acma")
    environ.setdefault("MFA_OBLIGATORIO", "true")
    environ.setdefault("UVICORN_WORKERS", "1")
    environ.setdefault("DB_POOL_SIZE", "3")
    environ.setdefault("DB_POOL_OVERFLOW", "2")
    environ.setdefault("LOG_JSON", "true")
    # Un solo proceso sin Redis es apto para probar login/WebView, no para
    # chat distribuido ni trabajos programados de Celery.
    environ.setdefault("TIEMPO_REAL_MODO", "local")
    environ.setdefault("NOTIFICACIONES_ENVIO_INLINE", "false")

    faltan = [clave for clave in REQUERIDOS if not environ.get(clave, "").strip()]
    if faltan:
        raise ValueError(
            "Faltan variables PRIVADAS de ACMA en Railway (Variables): " + ", ".join(faltan)
        )
    if not environ.get("APP_URL_PUBLICA", "").startswith("https://"):
        raise ValueError(
            "Genera un dominio en Settings > Networking > Generate Domain "
            "o configura APP_URL_PUBLICA=https://tu-dominio"
        )
    if not environ.get("CORS_ORIGENES", "").strip():
        raise ValueError(
            "Genera un dominio de Railway o configura CORS_ORIGENES=https://tu-dominio"
        )
    if environ.get("MFA_OBLIGATORIO", "").lower() not in ("true", "1", "yes", "on"):
        raise ValueError("El despliegue web de ACMA exige MFA_OBLIGATORIO=true")
    if environ.get("ACMA_ENTORNO") != "produccion":
        raise ValueError("El despliegue web de ACMA exige ACMA_ENTORNO=produccion")


def main() -> int:
    try:
        preparar_entorno(os.environ)
        puerto = int(os.environ.get("PORT", "8000"))
        workers = int(os.environ.get("UVICORN_WORKERS", "1"))
        if not (1 <= puerto <= 65535) or not (1 <= workers <= 4):
            raise ValueError("PORT o UVICORN_WORKERS fuera del rango permitido")
    except ValueError as error:
        print("[ACMA CONFIG] " + str(error), file=sys.stderr)
        return 1

    print("[ACMA] Arrancando FastAPI + React (HTTPS en Railway / proxy externo).", flush=True)
    os.execvp(
        "uvicorn",
        [
            "uvicorn", "main:app", "--host", "0.0.0.0", "--port", str(puerto),
            "--workers", str(workers),
        ],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
