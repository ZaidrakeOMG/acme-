"""Esquemas de inventario, órdenes de compra y caja chica (§6.4, §6.5). P09."""
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from models.inventario import EstadoCFDI, EstadoGastoCajaChica, EstadoOrdenCompra, EstadoPoliza, FormatoPoliza, TipoUbicacionInventario
from schemas.comun import ConVersionSalida


# ----------------------------------------------------------------- artículos

class ArticuloEntrada(BaseModel):
    codigo: str = Field(min_length=1, max_length=60)
    descripcion: str = Field(min_length=2, max_length=200)
    numero_parte: str | None = Field(default=None, max_length=80)
    unidad: str = Field(default="pieza", max_length=30)
    categoria: str = Field(default="", max_length=80)
    costo_unitario_vigente: Decimal = Field(default=Decimal("0"), ge=0, max_digits=14, decimal_places=2)
    stock_minimo_default: Decimal = Field(default=Decimal("0"), ge=0, max_digits=12, decimal_places=2)
    activo: bool = True
    prestador_id: UUID | None = Field(default=None, description="Solo superadmin")


class ArticuloCambios(BaseModel):
    descripcion: str | None = Field(default=None, min_length=2, max_length=200)
    numero_parte: str | None = Field(default=None, max_length=80)
    unidad: str | None = Field(default=None, max_length=30)
    categoria: str | None = Field(default=None, max_length=80)
    costo_unitario_vigente: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    stock_minimo_default: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    activo: bool | None = None


class ArticuloSalida(ConVersionSalida):
    prestador_id: UUID
    codigo: str
    numero_parte: str | None
    descripcion: str
    unidad: str
    categoria: str
    costo_unitario_vigente: Decimal
    stock_minimo_default: Decimal
    activo: bool


# --------------------------------------------------------------- ubicaciones

class UbicacionEntrada(BaseModel):
    nombre: str = Field(min_length=2, max_length=120)
    tipo: TipoUbicacionInventario = TipoUbicacionInventario.almacen
    tecnico_id: UUID | None = None
    placas: str | None = Field(default=None, max_length=20)
    activo: bool = True
    prestador_id: UUID | None = Field(default=None, description="Solo superadmin")


class UbicacionSalida(ConVersionSalida):
    prestador_id: UUID
    tipo: TipoUbicacionInventario
    nombre: str
    tecnico_id: UUID | None
    placas: str | None
    activo: bool


class ExistenciaSalida(BaseModel):
    id: UUID
    ubicacion_id: UUID
    ubicacion: str
    ubicacion_tipo: str
    articulo_id: UUID
    codigo: str
    descripcion: str
    unidad: str
    categoria: str
    cantidad: Decimal
    stock_minimo: Decimal
    costo_promedio: Decimal
    bajo_minimo: bool
    updated_at: datetime


class MovimientoSalida(BaseModel):
    id: UUID
    timestamp: datetime
    tipo: str
    origen: str
    cantidad: Decimal
    costo_unitario: Decimal
    articulo_id: UUID
    codigo: str | None
    descripcion: str | None
    ubicacion_origen: str | None
    ubicacion_destino: str | None
    folio_id: UUID | None
    numero_folio: str | None
    razon: str
    referencia_externa: str | None
    registrado_por: UUID | None


class EntradaInventario(BaseModel):
    articulo_id: UUID
    ubicacion_id: UUID
    cantidad: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    costo_unitario: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    referencia: str | None = Field(default=None, max_length=120)
    razon: str = Field(default="", max_length=500)


class TraspasoEntrada(BaseModel):
    articulo_id: UUID
    origen_id: UUID
    destino_id: UUID
    cantidad: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    razon: str = Field(default="", max_length=500)


class AjusteEntrada(BaseModel):
    articulo_id: UUID
    ubicacion_id: UUID
    cantidad: Decimal = Field(description="Delta: positivo suma, negativo resta", max_digits=14, decimal_places=2)
    razon: str = Field(min_length=5, max_length=500)


# ---------------------------------------------------------- órdenes de compra

class PartidaOCEntrada(BaseModel):
    articulo_id: UUID
    cantidad: Decimal = Field(default=Decimal("1"), gt=0, max_digits=14, decimal_places=2)
    costo_unitario: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)


class OrdenCompraEntrada(BaseModel):
    proveedor: str = Field(min_length=2, max_length=200)
    partidas: list[PartidaOCEntrada] = Field(min_length=1)
    folio_id: UUID | None = None
    ubicacion_destino_id: UUID | None = None
    notas: str = Field(default="", max_length=1000)


class RecibirOCEntrada(BaseModel):
    recibidas: dict[str, Decimal] = Field(default_factory=dict, description="articulo_id → cantidad recibida; vacío recibe todo lo pendiente")


class RazonEntrada(BaseModel):
    razon: str = Field(min_length=3, max_length=1000)


class PartidaOCSalida(BaseModel):
    id: UUID
    articulo_id: UUID
    codigo: str | None = None
    descripcion: str | None = None
    cantidad: Decimal
    costo_unitario: Decimal
    recibido: Decimal


class OrdenCompraSalida(ConVersionSalida):
    prestador_id: UUID
    tenant_id: UUID | None
    numero: str
    folio_id: UUID | None
    numero_folio: str | None = None
    proveedor: str
    estado: EstadoOrdenCompra
    estado_desde: datetime
    total: Decimal
    moneda: str
    ubicacion_destino_id: UUID | None
    notas: str
    aprobada_por: UUID | None
    aprobada_at: datetime | None
    recibida_at: datetime | None
    razon_cancelacion: str | None
    numero_oc_erp: str | None
    created_by: UUID | None
    partidas: list[PartidaOCSalida] = Field(default_factory=list)


# ------------------------------------------------------------------ caja chica

class FondoEntrada(BaseModel):
    tecnico_id: UUID
    monto_inicial: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    umbral_alerta_pct: Decimal | None = Field(default=None, ge=0, le=100, max_digits=5, decimal_places=2)


class ReponerFondoEntrada(BaseModel):
    monto: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2, description="Vacío restablece el monto inicial")


class FondoSalida(BaseModel):
    id: UUID
    prestador_id: UUID
    tecnico_id: UUID
    tecnico_nombre: str | None
    monto_inicial: Decimal
    saldo_actual: Decimal
    moneda: str
    umbral_alerta_pct: Decimal
    porcentaje_saldo: Decimal
    bajo_umbral: bool
    gastos_pendientes: int
    fecha_ultima_reposicion: date | None
    activo: bool
    created_at: datetime
    updated_at: datetime


class GastoEntrada(BaseModel):
    folio_id: UUID | None = None
    proveedor: str = Field(min_length=2, max_length=200)
    rfc_proveedor: str | None = Field(default=None, max_length=20)
    uuid_cfdi: str | None = Field(default=None, max_length=40)
    descripcion: str = Field(min_length=2, max_length=300)
    numero_parte: str | None = Field(default=None, max_length=80)
    articulo_id: UUID | None = None
    cantidad: Decimal = Field(default=Decimal("1"), gt=0, max_digits=12, decimal_places=2)
    subtotal: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    iva: Decimal = Field(default=Decimal("0"), ge=0, max_digits=14, decimal_places=2)
    monto: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    imagen_base64: str | None = Field(default=None, description="Foto de la factura (evidencia tipo factura)")
    nombre_imagen: str | None = Field(default=None, max_length=120)
    mime: str | None = Field(default=None, max_length=80)
    evidencia_id: UUID | None = None
    centro_costos: str = Field(default="", max_length=80)
    cuenta_contable: str = Field(default="", max_length=40)
    timestamp_dispositivo: datetime | None = None


class GastoSalida(BaseModel):
    id: UUID
    prestador_id: UUID
    tenant_id: UUID | None
    fondo_id: UUID
    folio_id: UUID | None
    numero_folio: str | None
    tecnico_id: UUID
    tecnico_nombre: str | None
    proveedor: str
    rfc_proveedor: str | None
    uuid_cfdi: str | None
    descripcion: str
    numero_parte: str | None
    articulo_id: UUID | None
    articulo_codigo: str | None
    cantidad: Decimal
    subtotal: Decimal
    iva: Decimal
    monto: Decimal
    estado: str
    estado_cfdi: str
    imagen_disponible: bool
    aprobado_por: UUID | None
    aprobado_por_nombre: str | None
    aprobado_at: datetime | None
    razon_rechazo: str | None
    centro_costos: str
    cuenta_contable: str
    poliza_id: UUID | None
    timestamp: datetime
    created_at: datetime
    updated_at: datetime


class GastoAprobadoSalida(BaseModel):
    gasto: GastoSalida
    refaccion_id: UUID | None = None
    movimientos: list[UUID] = Field(default_factory=list)
    saldo_fondo: Decimal


class PolizaSalida(ConVersionSalida):
    prestador_id: UUID
    fondo_id: UUID | None
    fecha: date
    total: Decimal
    gastos: int
    formato: FormatoPoliza
    estado: EstadoPoliza
    generado_por: UUID | None
    archivo_disponible: bool = False
    xml_disponible: bool = False


class ValidacionCFDISalida(BaseModel):
    id: UUID
    uuid_cfdi: str
    rfc_emisor: str | None
    estado_fiscal: EstadoCFDI
    detalle: str
    timestamp_validacion: datetime


class ResultadoOCR(BaseModel):
    """Fase 1: `disponible` siempre falso; el técnico captura los campos a mano."""
    disponible: bool
    detalle: str
    proveedor: str | None = None
    rfc_proveedor: str | None = None
    uuid_cfdi: str | None = None
    descripcion: str | None = None
    numero_parte: str | None = None
    subtotal: Decimal | None = None
    iva: Decimal | None = None
    total: Decimal | None = None
    campos_json: dict[str, Any] = Field(default_factory=dict)
