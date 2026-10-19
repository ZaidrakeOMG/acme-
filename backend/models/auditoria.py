"""Auditoría append-only (§6.9.5) y configuración clave-valor por tenant/prestador."""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, SmallInteger, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, ConVersion


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True, server_default=func.now())
    evento_tipo: Mapped[str] = mapped_column(String(80))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    actor_rol: Mapped[str | None] = mapped_column(String(40))
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    prestador_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    recurso_tipo: Mapped[str | None] = mapped_column(String(80))
    recurso_id: Mapped[str | None] = mapped_column(String(80))
    valor_anterior_json: Mapped[dict | None] = mapped_column(JSONB)
    valor_nuevo_json: Mapped[dict | None] = mapped_column(JSONB)
    ip_origen: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(Text)


class AuditAccesoAPI(Base):
    __tablename__ = "audit_accesos_api"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True, server_default=func.now())
    metodo: Mapped[str] = mapped_column(String(10))
    ruta: Mapped[str] = mapped_column(String(300))
    codigo_respuesta: Mapped[int] = mapped_column(SmallInteger)
    duracion_ms: Mapped[int] = mapped_column(Integer)
    usuario_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    prestador_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    ip_origen: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(Text)


class ConfiguracionTenant(ConVersion, Base):
    __tablename__ = "configuracion_tenant"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    clave: Mapped[str] = mapped_column(String(80))
    valor: Mapped[dict | list | str | int | float | bool] = mapped_column(JSONB)


class ConfiguracionPrestador(ConVersion, Base):
    __tablename__ = "configuracion_prestador"

    prestador_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("prestadores.id"))
    clave: Mapped[str] = mapped_column(String(80))
    valor: Mapped[dict | list | str | int | float | bool] = mapped_column(JSONB)
