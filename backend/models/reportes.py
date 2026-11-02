"""Reportes ejecutivos generados y programados (ACT-8.4). P10."""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, ConVersion, FormatoReporte, PeriodicidadReporte, pg_enum


class ReporteProgramado(ConVersion, Base):
    __tablename__ = "reportes_programados"

    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    prestador_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("prestadores.id"))
    nombre: Mapped[str] = mapped_column(String(160))
    tipo_reporte: Mapped[str] = mapped_column(String(40))
    filtros_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    formato: Mapped[FormatoReporte] = mapped_column(pg_enum(FormatoReporte, "formato_reporte"), default=FormatoReporte.pdf)
    periodicidad: Mapped[PeriodicidadReporte] = mapped_column(
        pg_enum(PeriodicidadReporte, "periodicidad_reporte"), default=PeriodicidadReporte.mensual
    )
    dia_hora: Mapped[str] = mapped_column(String(16), default="08:00")  # "08:00", "lunes 08:00" o "1 08:00"
    destinatarios_json: Mapped[list] = mapped_column(JSONB, default=list)
    activo: Mapped[bool] = mapped_column(Boolean, default=True)
    ultimo_envio_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("usuarios.id"))


class ReporteGenerado(ConVersion, Base):
    __tablename__ = "reportes_generados"

    programado_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("reportes_programados.id"))
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    prestador_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("prestadores.id"))
    tipo_reporte: Mapped[str] = mapped_column(String(40))
    filtros_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    formato: Mapped[FormatoReporte] = mapped_column(pg_enum(FormatoReporte, "formato_reporte"), default=FormatoReporte.pdf)
    archivo_key: Mapped[str] = mapped_column(String(300))
    filas: Mapped[int] = mapped_column(Integer, default=0)
    ms_generacion: Mapped[int | None] = mapped_column(Integer)
    generado_por: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("usuarios.id"))
    generado_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
