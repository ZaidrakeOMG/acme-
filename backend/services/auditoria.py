"""Escritura en audit_log (append-only). Sin RETURNING: la política SELECT solo la cumple plataforma."""
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from fastapi import Request
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from models.auditoria import AuditLog


def a_json(valor: Any) -> Any:
    """Convierte valores de modelos/esquemas a algo serializable en JSONB."""
    if valor is None or isinstance(valor, (str, int, float, bool)):
        return valor
    if isinstance(valor, (uuid.UUID, Decimal)):
        return str(valor)
    if isinstance(valor, (datetime, date)):
        return valor.isoformat()
    if isinstance(valor, Enum):
        return valor.value
    if isinstance(valor, dict):
        return {k: a_json(v) for k, v in valor.items()}
    if isinstance(valor, (list, tuple, set)):
        return [a_json(v) for v in valor]
    return str(valor)


_CAMPOS_SENSIBLES = {"password_hash", "mfa_secreto_cifrado", "mfa_codigos_recuperacion", "datos_fiscales_cifrados", "ubicacion"}


def instantanea(objeto: Any) -> dict[str, Any]:
    """Columnas de un modelo ORM sin campos sensibles."""
    return {
        c.key: a_json(getattr(objeto, c.key))
        for c in objeto.__table__.columns
        if c.key not in _CAMPOS_SENSIBLES
    }


async def registrar(
    sesion: AsyncSession,
    evento_tipo: str,
    *,
    actor_id: uuid.UUID | None = None,
    actor_rol: str | None = None,
    tenant_id: uuid.UUID | None = None,
    prestador_id: uuid.UUID | None = None,
    recurso_tipo: str | None = None,
    recurso_id: Any = None,
    antes: dict[str, Any] | None = None,
    despues: dict[str, Any] | None = None,
    request: Request | None = None,
) -> None:
    await sesion.execute(
        insert(AuditLog).values(
            id=uuid.uuid4(),
            created_at=datetime.now(UTC),
            evento_tipo=evento_tipo,
            actor_id=actor_id,
            actor_rol=actor_rol,
            tenant_id=tenant_id,
            prestador_id=prestador_id,
            recurso_tipo=recurso_tipo,
            recurso_id=str(recurso_id) if recurso_id is not None else None,
            valor_anterior_json=a_json(antes),
            valor_nuevo_json=a_json(despues),
            ip_origen=(request.client.host if request and request.client else None),
            user_agent=(request.headers.get("user-agent", "")[:500] if request else None),
        )
    )


async def registrar_actor(sesion: AsyncSession, actor, evento_tipo: str, request: Request | None = None, **kw) -> None:
    """Atajo con los datos del actor autenticado (core.dependencias.Actor)."""
    kw.setdefault("tenant_id", actor.tenant_id)
    kw.setdefault("prestador_id", actor.prestador_id)
    await registrar(sesion, evento_tipo, actor_id=actor.id, actor_rol=actor.rol.value, request=request, **kw)
