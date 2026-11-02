"""Inventario con los tres orígenes de refacciones (§6.4) y fondo fijo de caja chica (§6.5). P09."""
import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, ConVersion, pg_enum
from models.folios import OrigenRefaccion


class TipoUbicacionInventario(str, enum.Enum):
    almacen = "almacen"
    vehiculo = "vehiculo"


class TipoMovimientoInventario(str, enum.Enum):
    entrada = "entrada"
    salida = "salida"
    traspaso = "traspaso"
    ajuste = "ajuste"
    consumo_folio = "consumo_folio"


class EstadoOrdenCompra(str, enum.Enum):
    borrador = "borrador"
    aprobada = "aprobada"
    enviada_erp = "enviada_erp"
    recibida = "recibida"
    cancelada = "cancelada"


class EstadoGastoCajaChica(str, enum.Enum):
    capturado = "capturado"
    aprobado = "aprobado"
    rechazado = "rechazado"


class EstadoCFDI(str, enum.Enum):
    no_validado = "no_validado"
    vigente = "vigente"
    cancelado = "cancelado"
    no_encontrado = "no_encontrado"


class FormatoPoliza(str, enum.Enum):
    excel = "excel"
    xml = "xml"
    api = "api"


class EstadoPoliza(str, enum.Enum):
    pendiente = "pendiente"
    enviado = "enviado"
    contabilizado = "contabilizado"


def _fk(tabla: str, nullable: bool = False):
    return mapped_column(UUID(as_uuid=True), ForeignKey(f"{tabla}.id"), nullable=nullable)


class Articulo(ConVersion, Base):
    __tablename__ = "articulos"

    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    codigo: Mapped[str] = mapped_column(String(60))
    numero_parte: Mapped[str | None] = mapped_column(String(80))
    descripcion: Mapped[str] = mapped_column(String(200))
    unidad: Mapped[str] = mapped_column(String(30), default="pieza")
    categoria: Mapped[str] = mapped_column(String(80), default="")
    costo_unitario_vigente: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    stock_minimo_default: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    activo: Mapped[bool] = mapped_column(Boolean, default=True)


class UbicacionInventario(ConVersion, Base):
    __tablename__ = "ubicaciones_inventario"

    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    tipo: Mapped[TipoUbicacionInventario] = mapped_column(pg_enum(TipoUbicacionInventario, "tipo_ubicacion_inventario"), default=TipoUbicacionInventario.almacen)
    nombre: Mapped[str] = mapped_column(String(120))
    tecnico_id: Mapped[uuid.UUID | None] = _fk("usuarios", True)
    placas: Mapped[str | None] = mapped_column(String(20))
    activo: Mapped[bool] = mapped_column(Boolean, default=True)


class Existencia(ConVersion, Base):
    __tablename__ = "existencias"

    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    ubicacion_id: Mapped[uuid.UUID] = _fk("ubicaciones_inventario")
    articulo_id: Mapped[uuid.UUID] = _fk("articulos")
    cantidad: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    stock_minimo: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    costo_promedio: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))


class MovimientoInventario(Base):
    """Append-only (trigger `acma_auditoria_inmutable`): cada movimiento recalcula `existencias` en la misma transacción."""
    __tablename__ = "movimientos_inventario"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    tenant_id: Mapped[uuid.UUID | None] = _fk("tenants", True)
    articulo_id: Mapped[uuid.UUID] = _fk("articulos")
    ubicacion_origen_id: Mapped[uuid.UUID | None] = _fk("ubicaciones_inventario", True)
    ubicacion_destino_id: Mapped[uuid.UUID | None] = _fk("ubicaciones_inventario", True)
    tipo: Mapped[TipoMovimientoInventario] = mapped_column(pg_enum(TipoMovimientoInventario, "tipo_movimiento_inventario"))
    cantidad: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    costo_unitario: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    origen: Mapped[OrigenRefaccion] = mapped_column(pg_enum(OrigenRefaccion, "origen_refaccion"), default=OrigenRefaccion.almacen)
    folio_id: Mapped[uuid.UUID | None] = _fk("folios", True)
    oc_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    gasto_caja_chica_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    refaccion_id: Mapped[uuid.UUID | None] = _fk("folio_refacciones", True)
    referencia_externa: Mapped[str | None] = mapped_column(String(120))
    razon: Mapped[str] = mapped_column(Text, default="")
    registrado_por: Mapped[uuid.UUID | None] = _fk("usuarios", True)
    timestamp_dispositivo: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OrdenCompra(ConVersion, Base):
    __tablename__ = "ordenes_compra"

    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    tenant_id: Mapped[uuid.UUID | None] = _fk("tenants", True)
    numero: Mapped[str] = mapped_column(String(20))
    folio_id: Mapped[uuid.UUID | None] = _fk("folios", True)
    proveedor: Mapped[str] = mapped_column(String(200), default="")
    estado: Mapped[EstadoOrdenCompra] = mapped_column(pg_enum(EstadoOrdenCompra, "estado_orden_compra"), default=EstadoOrdenCompra.borrador)
    estado_desde: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    moneda: Mapped[str] = mapped_column(String(3), default="MXN")
    ubicacion_destino_id: Mapped[uuid.UUID | None] = _fk("ubicaciones_inventario", True)
    notas: Mapped[str] = mapped_column(Text, default="")
    aprobada_por: Mapped[uuid.UUID | None] = _fk("usuarios", True)
    aprobada_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recibida_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    razon_cancelacion: Mapped[str | None] = mapped_column(Text)
    numero_oc_erp: Mapped[str | None] = mapped_column(String(60))
    created_by: Mapped[uuid.UUID | None] = _fk("usuarios", True)


class OrdenCompraPartida(ConVersion, Base):
    __tablename__ = "orden_compra_partidas"

    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    oc_id: Mapped[uuid.UUID] = _fk("ordenes_compra")
    articulo_id: Mapped[uuid.UUID] = _fk("articulos")
    cantidad: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("1"))
    costo_unitario: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    recibido: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))


class FondoCajaChica(ConVersion, Base):
    __tablename__ = "fondos_caja_chica"

    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    tecnico_id: Mapped[uuid.UUID] = _fk("usuarios")
    monto_inicial: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    saldo_actual: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    moneda: Mapped[str] = mapped_column(String(3), default="MXN")
    umbral_alerta_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("20"))
    fecha_ultima_reposicion: Mapped[date | None] = mapped_column(Date)
    activo: Mapped[bool] = mapped_column(Boolean, default=True)


class GastoCajaChica(ConVersion, Base):
    __tablename__ = "gastos_caja_chica"

    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    tenant_id: Mapped[uuid.UUID | None] = _fk("tenants", True)
    fondo_id: Mapped[uuid.UUID] = _fk("fondos_caja_chica")
    folio_id: Mapped[uuid.UUID | None] = _fk("folios", True)
    tecnico_id: Mapped[uuid.UUID] = _fk("usuarios")
    proveedor: Mapped[str] = mapped_column(String(200), default="")
    rfc_proveedor: Mapped[str | None] = mapped_column(String(20))
    uuid_cfdi: Mapped[str | None] = mapped_column(String(40))
    descripcion: Mapped[str] = mapped_column(String(300), default="")
    numero_parte: Mapped[str | None] = mapped_column(String(80))
    articulo_id: Mapped[uuid.UUID | None] = _fk("articulos", True)
    cantidad: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("1"))
    subtotal: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    iva: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    monto: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    estado: Mapped[EstadoGastoCajaChica] = mapped_column(pg_enum(EstadoGastoCajaChica, "estado_gasto_caja_chica"), default=EstadoGastoCajaChica.capturado)
    estado_cfdi: Mapped[EstadoCFDI] = mapped_column(pg_enum(EstadoCFDI, "estado_cfdi"), default=EstadoCFDI.no_validado)
    imagen_key: Mapped[str | None] = mapped_column(String(300))
    evidencia_id: Mapped[uuid.UUID | None] = _fk("formulario_evidencias", True)
    aprobado_por: Mapped[uuid.UUID | None] = _fk("usuarios", True)
    aprobado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    razon_rechazo: Mapped[str | None] = mapped_column(Text)
    centro_costos: Mapped[str] = mapped_column(String(80), default="")
    cuenta_contable: Mapped[str] = mapped_column(String(40), default="")
    poliza_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    timestamp_dispositivo: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PolizaExportacion(ConVersion, Base):
    __tablename__ = "polizas_exportacion"

    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    fondo_id: Mapped[uuid.UUID | None] = _fk("fondos_caja_chica", True)
    fecha: Mapped[date] = mapped_column(Date)
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    gastos: Mapped[int] = mapped_column(Integer, default=0)
    formato: Mapped[FormatoPoliza] = mapped_column(pg_enum(FormatoPoliza, "formato_poliza"), default=FormatoPoliza.excel)
    archivo_key: Mapped[str | None] = mapped_column(String(300))
    archivo_xml_key: Mapped[str | None] = mapped_column(String(300))
    estado: Mapped[EstadoPoliza] = mapped_column(pg_enum(EstadoPoliza, "estado_poliza"), default=EstadoPoliza.pendiente)
    generado_por: Mapped[uuid.UUID | None] = _fk("usuarios", True)


class ValidacionCFDI(ConVersion, Base):
    """Fase 1: la llena el stub de `services/sat_validator.py` con `no_validado`; Fase 2 la llena el SAT."""
    __tablename__ = "validaciones_cfdi"

    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    gasto_id: Mapped[uuid.UUID | None] = _fk("gastos_caja_chica", True)
    uuid_cfdi: Mapped[str] = mapped_column(String(40))
    rfc_emisor: Mapped[str | None] = mapped_column(String(20))
    rfc_receptor: Mapped[str | None] = mapped_column(String(20))
    total: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    estado_fiscal: Mapped[EstadoCFDI] = mapped_column(pg_enum(EstadoCFDI, "estado_cfdi"), default=EstadoCFDI.no_validado)
    detalle: Mapped[str] = mapped_column(Text, default="")
    timestamp_validacion: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


__all__ = [
    "Articulo", "EstadoCFDI", "EstadoGastoCajaChica", "EstadoOrdenCompra", "EstadoPoliza", "Existencia", "FondoCajaChica", "FormatoPoliza",
    "GastoCajaChica", "MovimientoInventario", "OrdenCompra", "OrdenCompraPartida", "PolizaExportacion", "TipoMovimientoInventario",
    "TipoUbicacionInventario", "UbicacionInventario", "ValidacionCFDI", "JSONB",
]
