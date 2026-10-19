"""Permisos configurables del técnico (§6.8.3) y del despachador (§6.8.3b)."""
import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import AplicaPermiso, Base, ConVersion, pg_enum


class PermisoCatalogo(ConVersion, Base):
    __tablename__ = "permisos_catalogo"

    clave: Mapped[str] = mapped_column(String(60), unique=True)
    aplica_a: Mapped[AplicaPermiso] = mapped_column(pg_enum(AplicaPermiso, "aplica_permiso"))
    valor_default: Mapped[bool] = mapped_column(Boolean)
    descripcion: Mapped[str] = mapped_column(Text)


class PermisoTecnico(ConVersion, Base):
    """Valor base del prestador para cada permiso del técnico."""

    __tablename__ = "permisos_tecnico"

    prestador_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("prestadores.id"))
    permiso_clave: Mapped[str] = mapped_column(String(60), ForeignKey("permisos_catalogo.clave"))
    habilitado: Mapped[bool] = mapped_column(Boolean)


class GrupoTecnicos(ConVersion, Base):
    __tablename__ = "grupos_tecnicos"

    prestador_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("prestadores.id"))
    nombre: Mapped[str] = mapped_column(String(80))
    descripcion: Mapped[str] = mapped_column(Text, default="")


class GrupoTecnicoPermiso(ConVersion, Base):
    __tablename__ = "grupo_tecnico_permisos"

    prestador_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("prestadores.id"))
    grupo_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("grupos_tecnicos.id"))
    permiso_clave: Mapped[str] = mapped_column(String(60), ForeignKey("permisos_catalogo.clave"))
    habilitado: Mapped[bool] = mapped_column(Boolean)


class TecnicoGrupo(ConVersion, Base):
    __tablename__ = "tecnico_grupo"

    prestador_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("prestadores.id"))
    tecnico_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("usuarios.id"))
    grupo_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("grupos_tecnicos.id"))
    fecha_asignacion: Mapped[date] = mapped_column(Date, default=date.today)


class TecnicoPermisoOverride(ConVersion, Base):
    __tablename__ = "tecnico_permisos_override"

    prestador_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("prestadores.id"))
    tecnico_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("usuarios.id"))
    permiso_clave: Mapped[str] = mapped_column(String(60), ForeignKey("permisos_catalogo.clave"))
    habilitado: Mapped[bool] = mapped_column(Boolean)
    razon: Mapped[str] = mapped_column(Text, default="")
    modificado_por: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("usuarios.id"))


class PermisoDespachador(ConVersion, Base):
    """Fila con despachador_id y tenant_id nulos = valor base del prestador."""

    __tablename__ = "permisos_despachador"

    prestador_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("prestadores.id"))
    despachador_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("usuarios.id"))
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    permiso_clave: Mapped[str] = mapped_column(String(60), ForeignKey("permisos_catalogo.clave"))
    habilitado: Mapped[bool] = mapped_column(Boolean)
    configurado_por: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("usuarios.id"))


class PermisoDespachadorLog(Base):
    __tablename__ = "permisos_despachador_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    prestador_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("prestadores.id"))
    despachador_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    permiso_clave: Mapped[str] = mapped_column(String(60))
    valor_anterior: Mapped[bool | None] = mapped_column(Boolean)
    valor_nuevo: Mapped[bool] = mapped_column(Boolean)
    modificado_por: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
