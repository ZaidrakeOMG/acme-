"""Esquemas de costo del folio, presupuestos y exportación ERP (§6.6, §6.8.5, §6.8.6). P09."""
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from models.costos import AdaptadorERP, EstadoEventoERP, OperacionERP, TipoActividadPresupuesto
from models.folios import TipoFolio
from schemas.comun import ConVersionSalida


# ----------------------------------------------------------- costo del folio

class ValidarCostoEntrada(BaseModel):
    ajuste: Decimal | None = Field(default=None, max_digits=14, decimal_places=2, description="Suma o resta al costo calculado")
    razon_ajuste: str = Field(default="", max_length=1000)
    costo_otros: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    centro_costos: str | None = Field(default=None, max_length=80)


class CostoSalida(BaseModel):
    id: UUID
    costo_refacciones: Decimal
    costo_mano_obra: Decimal
    costo_otros: Decimal
    costo_total: Decimal
    moneda: str
    horas_mano_obra: Decimal
    tarifa_hora: Decimal
    origen_horas: str
    ajuste: Decimal
    razon_ajuste: str
    centro_costos: str
    validado_por: UUID | None
    validado_por_nombre: str | None = None
    validado_at: datetime | None
    documento_erp_ref: str | None


class RefaccionCosto(BaseModel):
    id: UUID
    descripcion: str
    cantidad: Decimal
    costo_unitario: Decimal
    origen: str
    articulo_id: UUID | None
    importe: Decimal


class FinancieroSalida(BaseModel):
    """Sección «Datos financieros» del archivo del folio (§6.8.6)."""
    visible: bool
    motivo: str | None = None
    costo: CostoSalida | None = None
    refacciones: list[RefaccionCosto] = Field(default_factory=list)
    gastos_caja_chica: list[dict[str, Any]] = Field(default_factory=list)
    puede_validar: bool = False


class TarifaEntrada(BaseModel):
    tarifa_hora: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    tenant_id: UUID | None = None
    tipo_folio: TipoFolio | None = None
    moneda: str = Field(default="MXN", max_length=3)
    vigente_desde: date | None = None
    activa: bool = True


class TarifaSalida(ConVersionSalida):
    prestador_id: UUID
    tenant_id: UUID | None
    tipo_folio: TipoFolio | None
    tarifa_hora: Decimal
    moneda: str
    vigente_desde: date
    activa: bool


# -------------------------------------------------------------- presupuestos

class PresupuestoEntrada(BaseModel):
    nombre: str = Field(default="", max_length=160)
    un_id: UUID | None = None
    grupo_id: UUID | None = None
    tipo_actividad: TipoActividadPresupuesto = TipoActividadPresupuesto.todos
    periodo_inicio: date
    periodo_fin: date
    monto: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    moneda: str = Field(default="MXN", max_length=3)
    umbrales_alerta_json: list[int] = Field(default_factory=lambda: [50, 80, 100])
    tenant_id: UUID | None = Field(default=None, description="Solo superadmin")


class PresupuestoCambios(BaseModel):
    nombre: str | None = Field(default=None, max_length=160)
    monto: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=2)
    periodo_inicio: date | None = None
    periodo_fin: date | None = None
    umbrales_alerta_json: list[int] | None = None
    activo: bool | None = None


class PresupuestoSalida(BaseModel):
    id: UUID
    tenant_id: UUID
    un_id: UUID | None
    grupo_id: UUID | None
    nombre: str
    un_codigo: str | None
    un_nombre: str | None
    grupo_nombre: str | None
    tipo_actividad: str
    periodo_inicio: date
    periodo_fin: date
    monto: Decimal
    moneda: str
    umbrales_alerta_json: list[Any]
    activo: bool
    consumido: Decimal
    comprometido: Decimal
    disponible: Decimal
    porcentaje: Decimal
    desviacion: Decimal
    semaforo: str
    created_at: datetime
    updated_at: datetime


class ConsumoSalida(BaseModel):
    id: UUID
    folio_id: UUID | None
    numero_folio: str | None
    descripcion: str | None
    un_id: UUID | None
    un_codigo: str | None
    monto: Decimal
    fecha: date
    tipo: str
    created_at: datetime


class NivelConsolidado(BaseModel):
    id: str | None = None
    nombre: str | None = None
    monto: Decimal
    consumido: Decimal
    comprometido: Decimal
    disponible: Decimal
    porcentaje: Decimal
    desviacion: Decimal
    semaforo: str
    presupuestos: list[PresupuestoSalida] = Field(default_factory=list)


class ConsolidadoSalida(BaseModel):
    """Jerarquía Tenant → Grupo → UN de §6.8.5."""
    tenant: NivelConsolidado
    grupos: list[NivelConsolidado] = Field(default_factory=list)
    unidades: list[NivelConsolidado] = Field(default_factory=list)
    presupuestos: list[PresupuestoSalida] = Field(default_factory=list)


# ------------------------------------------------------------------- ERP

class ErpConfigEntrada(BaseModel):
    adaptador: AdaptadorERP | None = None
    columnas_excel_json: list[str] | None = None
    cuentas_contables_json: dict[str, Any] | None = None
    centros_costos_json: dict[str, Any] | None = None
    exportacion_automatica: bool | None = None


class ErpConfigSalida(ConVersionSalida):
    prestador_id: UUID
    adaptador: AdaptadorERP
    columnas_excel_json: list[Any]
    cuentas_contables_json: dict[str, Any]
    centros_costos_json: dict[str, Any]
    exportacion_automatica: bool
    adaptadores_disponibles: list[dict[str, Any]] = Field(default_factory=list)


class EventoERPSalida(BaseModel):
    id: UUID
    prestador_id: UUID
    tenant_id: UUID | None
    operacion: OperacionERP
    entidad: str
    entidad_id: UUID | None
    payload_json: dict[str, Any]
    estado: EstadoEventoERP
    intentos: int
    ultimo_error: str | None
    adaptador: AdaptadorERP | None
    respuesta_json: dict[str, Any]
    exportacion_id: UUID | None
    procesado_at: datetime | None
    created_at: datetime


class ExportacionEntrada(BaseModel):
    desde: date
    hasta: date
    prestador_id: UUID | None = Field(default=None, description="Solo superadmin")


class ExportacionSalida(ConVersionSalida):
    prestador_id: UUID
    periodo_inicio: date
    periodo_fin: date
    eventos_incluidos: int
    total: Decimal
    generado_por: UUID | None
    archivo_disponible: bool = False
    xml_disponible: bool = False
