"""Genera todos los secretos que pide produccion, listos para pegar en el .env del servidor.

Ejecutar desde backend/:  .venv/Scripts/python -m scripts.generar_secretos
Con --compose imprime tambien las variables que consume docker-compose.prod.yml.

Nada se guarda en disco: la salida va a la terminal para que quede solo en el gestor de secretos del cliente.
"""
import argparse
import base64
import secrets

AVISO = """
Guarda estos valores en el gestor de secretos (no en el repositorio ni en un correo).
Cambiar CLAVE_CIFRADO con datos ya guardados vuelve ilegibles los secretos MFA y los datos fiscales:
esa clave se rota solo con el procedimiento de docs/operacion/recuperacion_desastres.md.
"""


def clave(bytes_: int = 32) -> str:
    """Contrasena apta para URL de conexion: sin ':' ni '@' ni '/' que haya que escapar."""
    return secrets.token_urlsafe(bytes_).replace("-", "x").replace("_", "y")


def main() -> None:
    p = argparse.ArgumentParser(description="Genera los secretos de ACMA")
    p.add_argument("--compose", action="store_true", help="incluye las variables de docker-compose.prod.yml")
    args = p.parse_args()

    print("# --- Secretos de la aplicacion ---")
    print(f"JWT_SECRETO={secrets.token_urlsafe(48)}")
    print(f"CLAVE_CIFRADO={base64.b64encode(secrets.token_bytes(32)).decode()}")
    if args.compose:
        owner, api, super_, minio, redis = (clave() for _ in range(5))
        print("\n# --- PostgreSQL ---")
        print(f"POSTGRES_SUPERPASSWORD={super_}")
        print(f"ACMA_OWNER_PASSWORD={owner}")
        print(f"ACMA_API_PASSWORD={api}")
        print("\n# --- MinIO ---")
        print("MINIO_ROOT_USER=acma_minio_prod")
        print(f"MINIO_ROOT_PASSWORD={minio}")
        print("\n# --- Redis ---")
        print(f"REDIS_PASSWORD={redis}")
        print("\n# --- Cadenas de conexion (ajusta los hosts) ---")
        print(f"DATABASE_URL=postgresql+asyncpg://acma_api:{api}@postgres:5432/acma")
        print(f"DATABASE_MIGRATIONS_URL=postgresql+asyncpg://acma_owner:{owner}@postgres:5432/acma")
        print(f"REDIS_URL=redis://:{redis}@redis:6379/0")
        print(f"CELERY_BROKER_URL=redis://:{redis}@redis:6379/1")
        print(f"CELERY_RESULT_BACKEND=redis://:{redis}@redis:6379/2")
        print("\n# --- Push PWA ---")
        print("# VAPID: .venv/Scripts/python -m scripts.generar_vapid")
    print(AVISO)


if __name__ == "__main__":
    main()
