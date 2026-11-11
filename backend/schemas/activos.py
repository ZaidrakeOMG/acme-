"""Esquemas de la ficha de activos, depreciación, TCO y análisis reemplazar vs. reparar (§6.9.4). P09."""
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from models.activos import DecisionReemplazo, MetodoDepreciacion


class DepreciacionEntrada(BaseModel):
    metodo: MetodoDepreciacion | None = None
    vida_util_anios: int | None = Field(default=None, ge=1, le=100)
    valor_salvamento: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    valor_reposicion: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    unidades_vida_util: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    unidades_acumuladas: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    valor_en_libros_manual: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    fecha_inicio: date | None = None
    # F2-04 (§6.9.4 «unidades de producción»): de qué medidor del equipo salen las unidades y cuántas traía ya.
    equipo_medidor_id: UUID | None = None
    unidades_al_inicio: Decimal | None = Field(default=None, ge=0, max_digits=16, decimal_places=2)


class ActivoEntrada(BaseModel):
    """Datos económicos del equipo que alimentan el TCO (§6.9.4)."""
    costo_adquisicion: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    fecha_adquisicion: date | None = None
    costo_hora_inactividad: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    valor_reposicion: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    numero_activo_fijo_erp: str | None = Field(default=None, max_length=60)


class UmbralEntrada(BaseModel):
    umbral_reemplazo_pct: Decimal = Field(ge=10, le=300, max_digits=7, decimal_places=2)


class DecisionEntrada(BaseModel):
    decision: DecisionReemplazo
    razon: str = Field(default="", max_length=2000)


class ActivoResumen(BaseModel):
    id: UUID
    codigo: str
    nombre: str
    marca: str | None
    modelo: str | None
    numero_serie: str | None
    estado: str
    criticidad: str | None
    un_id: UUID
    un_codigo: str | None
    un_nombre: str | None
    tenant_id: UUID
    costo_adquisicion: Decimal | None
    fecha_adquisicion: date | None
    fecha_instalacion: date | None
    valor_reposicion: Decimal | None
    numero_activo_fijo_erp: str | None
    tco_total: Decimal | None
    porcentaje_vs_reposicion: Decimal | None
    periodo_tco: str | None
    alerta_reemplazo: bool
    alerta_reemplazo_id: UUID | None


class ComponentesTCO(BaseModel):
    periodo: str
    costo_adquisicion: Decimal
    costo_preventivos: Decimal
    costo_correctivos: Decimal
    costo_refacciones: Decimal
    costo_downtime: Decimal
    horas_downtime: Decimal
    valor_residual: Decimal
    tco_total: Decimal
    valor_reposicion: Decimal | None
    porcentaje_vs_reposicion: Decimal
    folios: int
    aviso: str


class AlertaReemplazoSalida(BaseModel):
    id: UUID
    equipo_id: UUID
    tenant_id: UUID
    equipo_codigo: str | None
    equipo_nombre: str | None
    un_codigo: str | None
    fecha_alerta: date
    tco_al_momento: Decimal
    valor_reposicion: Decimal
    porcentaje_umbral: Decimal
    porcentaje_alcanzado: Decimal
    decision: str | None
    razon: str
    decidido_por: UUID | None
    decidido_at: datetime | None
    trabajo_especial_id: UUID | None
    created_at: datetime
    updated_at: datetime


class FichaActivo(BaseModel):
    equipo: dict[str, Any]
    contrato: dict[str, Any] | None
    historial_folios: list[dict[str, Any]] = Field(default_factory=list)
    refacciones: list[dict[str, Any]] = Field(default_factory=list)
    depreciacion: dict[str, Any] | None
    depreciacion_historial: list[dict[str, Any]] = Field(default_factory=list)
    tco: ComponentesTCO
    tco_historial: list[dict[str, Any]] = Field(default_factory=list)
    alerta_reemplazo: dict[str, Any] | None
    umbral_reemplazo_pct: Decimal
    fase_2: list[str] = Field(default_factory=list)


class DecisionResultado(BaseModel):
    alerta: AlertaReemplazoSalida
    trabajo_especial: dict[str, Any] | None = None
