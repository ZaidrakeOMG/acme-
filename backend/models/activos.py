"""Ficha de activos: depreciación, costo total de propiedad y análisis reemplazar vs. reparar (§6.9.4). P09."""
import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, ConVersion, pg_enum


class MetodoDepreciacion(str, enum.Enum):
    linea_recta = "linea_recta"
    doble_saldo_decreciente = "doble_saldo_decreciente"
    unidades_produccion = "unidades_produccion"
    manual = "manual"


class DecisionReemplazo(str, enum.Enum):
    aceptado = "aceptado"
    pospuesto = "pospuesto"


def _fk(tabla: str, nullable: bool = False):
    return mapped_column(UUID(as_uuid=True), ForeignKey(f"{tabla}.id"), nullable=nullable)


class ActivoDepreciacion(ConVersion, Base):
    __tablename__ = "activo_depreciacion"

    equipo_id: Mapped[uuid.UUID] = _fk("equipos")
    tenant_id: Mapped[uuid.UUID] = _fk("tenants")
    metodo: Mapped[MetodoDepreciacion] = mapped_column(pg_enum(MetodoDepreciacion, "metodo_depreciacion"), default=MetodoDepreciacion.linea_recta)
    vida_util_anios: Mapped[int] = mapped_column(Integer, default=10)
    valor_salvamento: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    valor_reposicion: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    unidades_vida_util: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    unidades_acumuladas: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    valor_en_libros_manual: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    fecha_inicio: Mapped[date] = mapped_column(Date, default=date.today)
    configurado_por: Mapped[uuid.UUID | None] = _fk("usuarios", True)
    # F2-04 (§6.9.4 «unidades de producción»): de qué medidor salen las unidades y cuántas traía el activo cuando
    # empezó a depreciarse (un equipo usado no empieza en cero).
    equipo_medidor_id: Mapped[uuid.UUID | None] = _fk("equipo_medidores", True)
    unidades_al_inicio: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))


class ActivoDepreciacionHistorial(Base):
    """Append-only: valor en libros por período (tarea mensual)."""
    __tablename__ = "activo_depreciacion_historial"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    equipo_id: Mapped[uuid.UUID] = _fk("equipos")
    tenant_id: Mapped[uuid.UUID] = _fk("tenants")
    periodo: Mapped[str] = mapped_column(String(10))
    valor_en_libros: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    depreciacion_periodo: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    depreciacion_acumulada: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    metodo_aplicado: Mapped[MetodoDepreciacion] = mapped_column(pg_enum(MetodoDepreciacion, "metodo_depreciacion"), default=MetodoDepreciacion.linea_recta)
    calculado_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    unidades_periodo: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))      # F2-04
    unidades_acumuladas: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))   # F2-04


class ActivoTCOSnapshot(ConVersion, Base):
    __tablename__ = "activo_tco_snapshot"

    equipo_id: Mapped[uuid.UUID] = _fk("equipos")
    tenant_id: Mapped[uuid.UUID] = _fk("tenants")
    un_id: Mapped[uuid.UUID | None] = _fk("unidades_negocio", True)
    periodo: Mapped[str] = mapped_column(String(10))
    costo_adquisicion: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    costo_preventivos: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    costo_correctivos: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    costo_refacciones: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    costo_downtime: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    horas_downtime: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    valor_residual: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    tco_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    valor_reposicion: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    porcentaje_vs_reposicion: Mapped[Decimal] = mapped_column(Numeric(7, 2), default=Decimal("0"))


class ActivoReemplazoAlerta(ConVersion, Base):
    __tablename__ = "activo_reemplazo_alertas"

    equipo_id: Mapped[uuid.UUID] = _fk("equipos")
    tenant_id: Mapped[uuid.UUID] = _fk("tenants")
    fecha_alerta: Mapped[date] = mapped_column(Date, default=date.today)
    tco_al_momento: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    valor_reposicion: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    porcentaje_umbral: Mapped[Decimal] = mapped_column(Numeric(7, 2), default=Decimal("0"))
    porcentaje_alcanzado: Mapped[Decimal] = mapped_column(Numeric(7, 2), default=Decimal("0"))
    decision: Mapped[DecisionReemplazo | None] = mapped_column(pg_enum(DecisionReemplazo, "decision_reemplazo"), nullable=True)
    razon: Mapped[str] = mapped_column(Text, default="")
    decidido_por: Mapped[uuid.UUID | None] = _fk("usuarios", True)
    decidido_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    trabajo_especial_id: Mapped[uuid.UUID | None] = _fk("trabajos_especiales", True)


__all__ = ["ActivoDepreciacion", "ActivoDepreciacionHistorial", "ActivoReemplazoAlerta", "ActivoTCOSnapshot", "DecisionReemplazo", "MetodoDepreciacion"]
