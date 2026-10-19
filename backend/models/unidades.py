"""Unidades de negocio, grupos de UNs (§6.8.5) y asignaciones de usuarios."""
import uuid
from datetime import date

from geoalchemy2 import Geography
from sqlalchemy import Date, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, ConVersion, EstadoRegistro, pg_enum


class GrupoUN(ConVersion, Base):
    __tablename__ = "grupos_un"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    nombre: Mapped[str] = mapped_column(String(120))
    descripcion: Mapped[str] = mapped_column(Text, default="")
    responsable_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("usuarios.id"))
    estado: Mapped[EstadoRegistro] = mapped_column(pg_enum(EstadoRegistro, "estado_registro"), default=EstadoRegistro.activo)


class UnidadNegocio(ConVersion, Base):
    __tablename__ = "unidades_negocio"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    nombre: Mapped[str] = mapped_column(String(160))
    codigo: Mapped[str] = mapped_column(String(40))
    direccion: Mapped[str] = mapped_column(Text, default="")
    ubicacion = mapped_column(Geography(geometry_type="POINT", srid=4326, spatial_index=False), nullable=True)
    zona_horaria: Mapped[str] = mapped_column(String(64), default="America/Mexico_City")
    estado: Mapped[EstadoRegistro] = mapped_column(pg_enum(EstadoRegistro, "estado_registro"), default=EstadoRegistro.activo)
    grupo_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("grupos_un.id"))


class GrupoUNMiembro(ConVersion, Base):
    __tablename__ = "grupo_un_miembros"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    grupo_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("grupos_un.id"))
    unidad_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("unidades_negocio.id"))
    fecha_ingreso: Mapped[date] = mapped_column(Date, default=date.today)


class UsuarioGrupo(ConVersion, Base):
    __tablename__ = "usuario_grupos"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    usuario_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("usuarios.id"))
    grupo_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("grupos_un.id"))
    rol_en_grupo: Mapped[str] = mapped_column(String(40), default="supervisor")


class UsuarioUN(ConVersion, Base):
    __tablename__ = "usuario_un"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    usuario_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("usuarios.id"))
    unidad_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("unidades_negocio.id"))
