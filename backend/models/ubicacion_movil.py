"""Ubicación Android opt-in: únicamente la última señal y permisos del mapa."""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class UbicacionMovil(Base):
    __tablename__ = "ubicaciones_movil"

    usuario_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("usuarios.id", ondelete="CASCADE"), primary_key=True
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    prestador_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("prestadores.id"))
    activa: Mapped[bool] = mapped_column(Boolean, default=False)
    consentimiento_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lat: Mapped[float | None] = mapped_column(Float)
    lng: Mapped[float | None] = mapped_column(Float)
    precision_m: Mapped[float | None] = mapped_column(Float)
    ultima_ubicacion_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actualizado_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UbicacionMovilVisor(Base):
    __tablename__ = "ubicacion_movil_visores"

    usuario_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("usuarios.id", ondelete="CASCADE"), primary_key=True
    )
    habilitado: Mapped[bool] = mapped_column(Boolean, default=False)
    otorgado_por: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("usuarios.id", ondelete="SET NULL")
    )
    actualizado_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
