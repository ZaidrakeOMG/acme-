"""Contador de SLA con pausas y exclusiones, penalizaciones por período y consumo de la iguala (§6.10.1). P10."""
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, ConVersion, CausaExclusionSLA, EstadoPenalizacion, MotivoPausaSLA, pg_enum


def _fk(tabla: str, nulo: bool = False) -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), ForeignKey(f"{tabla}.id"), nullable=nulo)


class FolioSLAPausa(ConVersion, Base):
    """Tiempo que no cuenta para el SLA: reasignación y espera de información del operador (§6.10.1)."""

    __tablename__ = "folio_sla_pausas"

    folio_id: Mapped[uuid.UUID] = _fk("folios")
    tenant_id: Mapped[uuid.UUID] = _fk("tenants")
    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    motivo: Mapped[MotivoPausaSLA] = mapped_column(pg_enum(MotivoPausaSLA, "motivo_pausa_sla"))
    inicio: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    fin: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    minutos: Mapped[int | None] = mapped_column(Integer)
    notas: Mapped[str] = mapped_column(Text, default="")


class FolioSLAExclusion(ConVersion, Base):
    """El prestador registra la causa y el Admin empresa la aprueba o rechaza; solo lo aprobado se descuenta."""

    __tablename__ = "folio_sla_exclusiones"

    folio_id: Mapped[uuid.UUID] = _fk("folios")
    tenant_id: Mapped[uuid.UUID] = _fk("tenants")
    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    causa: Mapped[CausaExclusionSLA] = mapped_column(pg_enum(CausaExclusionSLA, "causa_exclusion_sla"))
    descripcion: Mapped[str] = mapped_column(Text)
    registrado_por: Mapped[uuid.UUID | None] = _fk("usuarios", True)
    timestamp_inicio: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    timestamp_fin: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    minutos: Mapped[int] = mapped_column(Integer)
    aprobado_por: Mapped[uuid.UUID | None] = _fk("usuarios", True)
    aprobada: Mapped[bool | None] = mapped_column(Boolean)  # None = pendiente de decisión
    decidida_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    razon_decision: Mapped[str] = mapped_column(Text, default="")


class PenalizacionPeriodo(ConVersion, Base):
    """Resumen mensual que el Admin prestador revisa antes del cierre; el descuento en el CFDI es Fase 2."""

    __tablename__ = "penalizaciones_periodo"

    contrato_id: Mapped[uuid.UUID] = _fk("contratos")
    tenant_id: Mapped[uuid.UUID] = _fk("tenants")
    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    periodo: Mapped[str] = mapped_column(String(7))  # YYYY-MM
    total_folios: Mapped[int] = mapped_column(Integer, default=0)
    folios_incumplidos: Mapped[int] = mapped_column(Integer, default=0)
    monto_penalizacion: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    moneda: Mapped[str] = mapped_column(String(3), default="MXN")
    estado: Mapped[EstadoPenalizacion] = mapped_column(
        pg_enum(EstadoPenalizacion, "estado_penalizacion"), default=EstadoPenalizacion.borrador
    )
    detalle_json: Mapped[list] = mapped_column(JSONB, default=list)
    revisado_por: Mapped[uuid.UUID | None] = _fk("usuarios", True)
    revisado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cerrado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    incluido_en_factura_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))  # lo llenará el CFDI de Fase 2


class IgualaConsumoPeriodo(ConVersion, Base):
    """Correctivos y preventivos incluidos en la iguala contra los atendidos en el período (§6.10.1)."""

    __tablename__ = "iguala_consumo_periodo"

    contrato_id: Mapped[uuid.UUID] = _fk("contratos")
    tenant_id: Mapped[uuid.UUID] = _fk("tenants")
    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    periodo: Mapped[str] = mapped_column(String(7))
    correctivos_incluidos: Mapped[int] = mapped_column(Integer, default=0)
    correctivos_atendidos: Mapped[int] = mapped_column(Integer, default=0)
    correctivos_adicionales: Mapped[int] = mapped_column(Integer, default=0)
    preventivos_incluidos: Mapped[int] = mapped_column(Integer, default=0)
    preventivos_ejecutados: Mapped[int] = mapped_column(Integer, default=0)
    tarifa_mensual: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    folios_adicionales_json: Mapped[list] = mapped_column(JSONB, default=list)
