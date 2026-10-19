"""Dependencias reutilizables: usuario_actual, requiere_rol(*roles), requiere_dominio(*dominios)."""
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.db import obtener_db
from core.errors import ErrorAPI, no_autenticado, prohibido
from models.base import Dominio, EstadoRegistro, Rol
from models.usuarios import Sesion, Usuario

DB = Annotated[AsyncSession, Depends(obtener_db)]


@dataclass(frozen=True)
class Actor:
    id: uuid.UUID
    email: str
    nombre: str
    rol: Rol
    dominio: Dominio
    tenant_id: uuid.UUID | None
    prestador_id: uuid.UUID | None
    sesion_id: uuid.UUID | None

    @property
    def es_superadmin(self) -> bool:
        return self.rol == Rol.superadmin


async def usuario_actual(request: Request, db: DB) -> Actor:
    claims = getattr(request.state, "claims", None)
    if not claims:
        raise no_autenticado()
    usuario = await db.get(Usuario, uuid.UUID(claims["sub"]))
    if usuario is None or usuario.estado != EstadoRegistro.activo:
        raise no_autenticado("Usuario inactivo o inexistente")
    # El rol/tenant del token deben seguir vigentes (un cambio de rol invalida el token).
    if (usuario.rol.value != claims.get("rol")
            or str(usuario.tenant_id or "") != (claims.get("tenant_id") or "")
            or str(usuario.prestador_id or "") != (claims.get("prestador_id") or "")):
        raise no_autenticado("La sesión ya no corresponde al perfil del usuario")
    sesion_id = uuid.UUID(claims["sid"]) if claims.get("sid") else None
    if sesion_id:
        sesion = (await db.execute(select(Sesion).where(Sesion.id == sesion_id))).scalar_one_or_none()
        if sesion is None or sesion.revocada_at is not None or sesion.expira_at <= datetime.now(UTC):
            raise no_autenticado("Sesión revocada o expirada")
    return Actor(
        id=usuario.id, email=usuario.email, nombre=usuario.nombre, rol=usuario.rol, dominio=usuario.dominio,
        tenant_id=usuario.tenant_id, prestador_id=usuario.prestador_id, sesion_id=sesion_id,
    )


ActorActual = Annotated[Actor, Depends(usuario_actual)]


def requiere_rol(*roles: Rol):
    permitidos = set(roles)

    async def _verificar(actor: ActorActual) -> Actor:
        if actor.rol not in permitidos:
            raise prohibido(f"Requiere uno de los roles: {', '.join(sorted(r.value for r in permitidos))}")
        return actor

    return _verificar


def requiere_dominio(*dominios: Dominio):
    permitidos = set(dominios)

    async def _verificar(actor: ActorActual) -> Actor:
        if actor.dominio not in permitidos:
            raise prohibido("Tu dominio de usuario no tiene acceso a este recurso")
        return actor

    return _verificar


def validar_tenant(actor: Actor, tenant_id: uuid.UUID | None) -> None:
    """Regla 2: validación de multitenancy en el servicio, además de la RLS."""
    if actor.es_superadmin:
        return
    if actor.tenant_id is None or tenant_id != actor.tenant_id:
        raise ErrorAPI(404, "NO_ENCONTRADO", "Recurso no encontrado")


def validar_prestador(actor: Actor, prestador_id: uuid.UUID | None) -> None:
    if actor.es_superadmin:
        return
    if actor.prestador_id is None or prestador_id != actor.prestador_id:
        raise ErrorAPI(404, "NO_ENCONTRADO", "Recurso no encontrado")
