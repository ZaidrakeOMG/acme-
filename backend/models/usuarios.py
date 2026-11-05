"""Usuarios, historial de contraseñas, sesiones (refresh tokens) e intentos fallidos."""
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, ConVersion, Dominio, EstadoRegistro, Rol, pg_enum


class Usuario(ConVersion, Base):
    __tablename__ = "usuarios"

    email: Mapped[str] = mapped_column(String(254))
    password_hash: Mapped[str] = mapped_column(String(255))
    nombre: Mapped[str] = mapped_column(String(160))
    telefono: Mapped[str | None] = mapped_column(String(30))
    rol: Mapped[Rol] = mapped_column(pg_enum(Rol, "rol_usuario"))
    dominio: Mapped[Dominio] = mapped_column(pg_enum(Dominio, "dominio_usuario"))
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    prestador_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("prestadores.id"))
    estado: Mapped[EstadoRegistro] = mapped_column(pg_enum(EstadoRegistro, "estado_registro"), default=EstadoRegistro.activo)
    mfa_secreto_cifrado: Mapped[str | None] = mapped_column(Text)
    mfa_habilitado: Mapped[bool] = mapped_column(Boolean, default=False)
    mfa_codigos_recuperacion: Mapped[list[str]] = mapped_column(JSONB, default=list)
    mfa_ultimo_paso: Mapped[int | None] = mapped_column(BigInteger)  # P11a: §6.9.5 sin reutilizar el mismo TOTP
    intentos_fallidos: Mapped[int] = mapped_column(Integer, default=0)
    bloqueado_hasta: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    password_actualizado_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ultimo_acceso_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class HistorialContrasena(Base):
    __tablename__ = "historial_contrasenas"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    usuario_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("usuarios.id"))
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Sesion(Base):
    __tablename__ = "sesiones"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    usuario_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("usuarios.id"))
    familia_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    padre_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("sesiones.id"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    dispositivo: Mapped[str | None] = mapped_column(String(200))
    user_agent: Mapped[str | None] = mapped_column(Text)
    ip_origen: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    ultimo_acceso_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expira_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    rotada_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revocada_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    motivo_revocacion: Mapped[str | None] = mapped_column(String(60))
