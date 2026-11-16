"""Configuración centralizada del search_path para bases PostgreSQL.

ACMA original funciona en public; ACMA migrado en Supabase está en acma.
Los modelos SQLAlchemy usan nombres no cualificados: sin search_path
correcto podrían consultar tablas erróneas o fallar durante el login.
"""
from typing import Any


ESQUEMAS_PERMITIDOS = frozenset({"public", "acma"})


def opciones_conexion(esquema: str) -> dict[str, Any]:
    """Devuelve kwargs para create_async_engine; no ejecuta SQL.

    SQLAlchemy/asyncpg requiere 'server_settings' para definir el search_path
    desde que se establece la conexión, incluida la introspección de ENUMs.
    No se incluye public como fallback en modo Supabase para evitar consultar
    accidentalmente tablas que no pertenecen a ACMA.
    """
    if esquema not in ESQUEMAS_PERMITIDOS:
        raise ValueError("DB_SCHEMA debe ser public o acma")
    if esquema == "public":
        return {}
    return {
        "connect_args": {
            "server_settings": {"search_path": "acma,extensions"}
        }
    }
