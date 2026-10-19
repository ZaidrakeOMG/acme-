"""Tenants (empresas cliente), prestadores, su relación N:N y el catálogo de roles."""
import uuid
from datetime import date

from sqlalchemy import Boolean, Date, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, ConVersion, Dominio, EstadoRegistro, Rol, pg_enum


class RolCatalogo(ConVersion, Base):
    __tablename__ = "roles"

    clave: Mapped[Rol] = mapped_column(pg_enum(Rol, "rol_usuario"), unique=True)
    nombre: Mapped[str] = mapped_column(String(80))
    dominio: Mapped[Dominio] = mapped_column(pg_enum(Dominio, "dominio_usuario"))
    mfa_obligatorio: Mapped[bool] = mapped_column(Boolean, default=False)
    descripcion: Mapped[str] = mapped_column(Text, default="")


class Tenant(ConVersion, Base):
    __tablename__ = "tenants"

    razon_social: Mapped[str] = mapped_column(String(200))
    rfc: Mapped[str] = mapped_column(String(20))
    pais: Mapped[str] = mapped_column(String(2), default="MX")
    moneda: Mapped[str] = mapped_column(String(3), default="MXN")
    zona_horaria: Mapped[str] = mapped_column(String(64), default="America/Mexico_City")
    estado: Mapped[EstadoRegistro] = mapped_column(pg_enum(EstadoRegistro, "estado_registro"), default=EstadoRegistro.activo)


class Prestador(ConVersion, Base):
    __tablename__ = "prestadores"

    razon_social: Mapped[str] = mapped_column(String(200))
    rfc: Mapped[str] = mapped_column(String(20))
    pais: Mapped[str] = mapped_column(String(2), default="MX")
    datos_fiscales_cifrados: Mapped[str | None] = mapped_column(Text)
    logo_key: Mapped[str | None] = mapped_column(String(300))
    color_primario: Mapped[str] = mapped_column(String(7), default="#1C3D8F")
    color_acento: Mapped[str] = mapped_column(String(7), default="#A2C62B")
    estado: Mapped[EstadoRegistro] = mapped_column(pg_enum(EstadoRegistro, "estado_registro"), default=EstadoRegistro.activo)


class TenantPrestador(ConVersion, Base):
    __tablename__ = "tenant_prestador"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    prestador_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("prestadores.id"))
    vigencia_inicio: Mapped[date] = mapped_column(Date, default=date.today)
    vigencia_fin: Mapped[date | None] = mapped_column(Date)
    estado: Mapped[EstadoRegistro] = mapped_column(pg_enum(EstadoRegistro, "estado_registro"), default=EstadoRegistro.activo)
