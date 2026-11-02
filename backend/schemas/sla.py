"""Esquemas de SLA, penalizaciones, iguala, alertas del usuario, BI y reportes (§6.10.1, §6.9.6, ACT-8.1/8.4). P10."""
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from models.base import CausaExclusionSLA, EstadoPenalizacion, FormatoReporte, MotivoPausaSLA, PeriodicidadReporte
from schemas.comun import ConVersionSalida, Modelo


# ---------------------------------------------------------------- SLA
class PausaSalida(Modelo):
    id: UUID
    motivo: MotivoPausaSLA
    inicio: datetime
    fin: datetime | None
    minutos: int | None
    notas: str


class ExclusionEntrada(BaseModel):
    causa: CausaExclusionSLA
    descripcion: str = Field(min_length=10, max_length=2000)
    timestamp_inicio: datetime
    timestamp_fin: datetime

    @model_validator(mode="after")
    def _rango(self) -> "ExclusionEntrada":
        if self.timestamp_fin <= self.timestamp_inicio:
            raise ValueError("El fin de la exclusión debe ser posterior a su inicio")
        return self


class ExclusionDecision(BaseModel):
    aprobada: bool
    razon: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def _razon(self) -> "ExclusionDecision":
        if not self.aprobada and len(self.razon.strip()) < 3:
            raise ValueError("El rechazo exige razón")
        return self


class ExclusionSalida(ConVersionSalida):
    folio_id: UUID
    tenant_id: UUID
    prestador_id: UUID
    causa: CausaExclusionSLA
    descripcion: str
    registrado_por: UUID | None
    timestamp_inicio: datetime
    timestamp_fin: datetime
    minutos: int
    aprobada: bool | None
    aprobado_por: UUID | None
    decidida_at: datetime | None
    razon_decision: str
    numero_folio: str | None = None


class SLAFolioSalida(Modelo):
    disponible: bool
    motivo: str | None = None
    tiempo_inicio: datetime | None = None
    tiempo_respuesta_at: datetime | None = None
    tiempo_fin: datetime | None = None
    limite_respuesta_min: int | None = None
    limite_sla_min: int | None = None
    tiempo_pausado_min: int = 0
    tiempo_exclusion_min: int = 0
    tiempo_efectivo_min: int | None = None
    tiempo_respuesta_efectivo_min: int | None = None
    cumplimiento_respuesta: bool | None = None
    cumplimiento_resolucion: bool | None = None
    cumplimiento: bool | None = None
    penalizacion_calculada: str = "0"
    penalizacion_detalle: dict[str, Any] = Field(default_factory=dict)
    excluir_sla_por_cliente: bool = False
    tiempo_respuesta_prometido_horas: int | None = None
    tiempo_resolucion_prometido_horas: int | None = None
    pausas: list[dict[str, Any]] = Field(default_factory=list)
    exclusiones: list[dict[str, Any]] = Field(default_factory=list)


# ------------------------------------------------- penalizaciones e iguala
class PenalizacionSalida(ConVersionSalida):
    contrato_id: UUID
    tenant_id: UUID
    prestador_id: UUID
    periodo: str
    total_folios: int
    folios_incumplidos: int
    monto_penalizacion: Decimal
    moneda: str
    estado: EstadoPenalizacion
    detalle_json: list[dict[str, Any]]
    revisado_por: UUID | None
    revisado_at: datetime | None
    cerrado_at: datetime | None
    incluido_en_factura_id: UUID | None


class PenalizacionCambio(BaseModel):
    estado: EstadoPenalizacion


class IgualaSalida(ConVersionSalida):
    contrato_id: UUID
    periodo: str
    correctivos_incluidos: int
    correctivos_atendidos: int
    correctivos_adicionales: int
    preventivos_incluidos: int
    preventivos_ejecutados: int
    tarifa_mensual: Decimal
    folios_adicionales_json: list[dict[str, Any]]


class CumplimientoContrato(Modelo):
    contrato_id: UUID
    periodo: str
    folios_cerrados: int
    cumplimiento_respuesta_pct: str
    cumplimiento_resolucion_pct: str
    folios_incumplidos: int
    penalizacion: str
    por_severidad: dict[str, Any]
    exclusiones_pendientes: int


# ------------------------------------------------------------- alertas
class AlertaPanelSalida(Modelo):
    id: UUID
    clave_alerta: str
    descripcion: str | None = None
    tenant_id: UUID | None
    prestador_id: UUID | None
    entidad_tipo: str | None
    entidad_id: UUID | None
    umbral_en_momento: Decimal | None
    datos_contexto_json: dict[str, Any]
    estado: str
    timestamp_disparo: datetime
    timestamp_vista: datetime | None
    atendida_at: datetime | None
    nota_atencion: str
    escalada: bool


class AtenderEntrada(BaseModel):
    nota: str = Field(default="", max_length=2000)


class SupresionEntrada(BaseModel):
    clave: str = Field(min_length=3, max_length=60)
    razon: str = Field(min_length=3, max_length=2000)
    hasta: datetime
    entidad_id: UUID | None = None


class EscalacionEntrada(BaseModel):
    clave: str = Field(min_length=3, max_length=60)
    escalacion_de: str | None = Field(default=None, max_length=60)


# ----------------------------------------------------------------- BI
class TableroSalida(Modelo):
    tipo: str
    rol: str
    periodo: dict[str, str]
    cache: bool = False
    ttl_cache_segundos: int = 0
    datos: dict[str, Any] = Field(default_factory=dict)


# ------------------------------------------------------------- reportes
class ReporteEntrada(BaseModel):
    tipo_reporte: str = Field(min_length=3, max_length=40)
    formato: FormatoReporte = FormatoReporte.pdf
    desde: date | None = None
    hasta: date | None = None
    grupo_id: UUID | None = None
    un_id: UUID | None = None


class ProgramadoEntrada(BaseModel):
    nombre: str = Field(default="", max_length=160)
    tipo_reporte: str = Field(min_length=3, max_length=40)
    formato: FormatoReporte = FormatoReporte.pdf
    periodicidad: PeriodicidadReporte = PeriodicidadReporte.mensual
    dia_hora: str = Field(default="08:00", max_length=16)
    filtros_json: dict[str, Any] = Field(default_factory=dict)
    destinatarios_json: list[UUID] = Field(default_factory=list)
    activo: bool = True


class ProgramadoCambios(BaseModel):
    nombre: str | None = Field(default=None, max_length=160)
    formato: FormatoReporte | None = None
    periodicidad: PeriodicidadReporte | None = None
    dia_hora: str | None = Field(default=None, max_length=16)
    filtros_json: dict[str, Any] | None = None
    destinatarios_json: list[UUID] | None = None
    activo: bool | None = None


class ProgramadoSalida(ConVersionSalida):
    tenant_id: UUID | None
    prestador_id: UUID | None
    nombre: str
    tipo_reporte: str
    formato: FormatoReporte
    periodicidad: PeriodicidadReporte
    dia_hora: str
    filtros_json: dict[str, Any]
    destinatarios_json: list[UUID]
    activo: bool
    ultimo_envio_at: datetime | None


class GeneradoSalida(ConVersionSalida):
    programado_id: UUID | None
    tipo_reporte: str
    formato: FormatoReporte
    archivo_key: str
    filas: int
    ms_generacion: int | None
    generado_at: datetime
