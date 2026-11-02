"""Costo del folio, tarifas de mano de obra, presupuestos por UN y grupo (§6.8.5) y capa desacoplada de ERP (§6.6). P09."""
import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, ConVersion, pg_enum
from models.folios import TipoFolio
from models.inventario import FormatoPoliza


class TipoActividadPresupuesto(str, enum.Enum):
    correctivo = "correctivo"
    preventivo = "preventivo"
    especial = "especial"
    todos = "todos"


class OperacionERP(str, enum.Enum):
    generar_oc = "generar_oc"
    registrar_gasto = "registrar_gasto"
    crear_activo_fijo = "crear_activo_fijo"
    poliza_caja_chica = "poliza_caja_chica"


class EstadoEventoERP(str, enum.Enum):
    pendiente = "pendiente"
    procesado = "procesado"
    error = "error"
    omitido = "omitido"


class AdaptadorERP(str, enum.Enum):
    ninguno = "ninguno"
    contpaqi = "contpaqi"
    microsip = "microsip"


def _fk(tabla: str, nullable: bool = False):
    return mapped_column(UUID(as_uuid=True), ForeignKey(f"{tabla}.id"), nullable=nullable)


class FolioCosto(ConVersion, Base):
    __tablename__ = "folio_costos"

    folio_id: Mapped[uuid.UUID] = _fk("folios")
    tenant_id: Mapped[uuid.UUID] = _fk("tenants")
    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    costo_refacciones: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    costo_mano_obra: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    costo_otros: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    costo_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    moneda: Mapped[str] = mapped_column(String(3), default="MXN")
    centro_costos: Mapped[str] = mapped_column(String(80), default="")
    horas_mano_obra: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=Decimal("0"))
    tarifa_hora: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    origen_horas: Mapped[str] = mapped_column(String(30), default="calculadas")
    ajuste: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    razon_ajuste: Mapped[str] = mapped_column(Text, default="")
    validado_por: Mapped[uuid.UUID | None] = _fk("usuarios", True)
    validado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    documento_erp_ref: Mapped[str | None] = mapped_column(String(80))
    detalle_json: Mapped[dict] = mapped_column(JSONB, default=dict)


class TarifaManoObra(ConVersion, Base):
    __tablename__ = "tarifas_mano_obra"

    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    tenant_id: Mapped[uuid.UUID | None] = _fk("tenants", True)
    tipo_folio: Mapped[TipoFolio | None] = mapped_column(pg_enum(TipoFolio, "tipo_folio"), nullable=True)
    tarifa_hora: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    moneda: Mapped[str] = mapped_column(String(3), default="MXN")
    vigente_desde: Mapped[date] = mapped_column(Date, default=date.today)
    activa: Mapped[bool] = mapped_column(Boolean, default=True)


class Presupuesto(ConVersion, Base):
    """§6.8.5: unifica `presupuestos` por UN y `presupuestos_grupo` en una sola tabla con `un_id` XOR `grupo_id`."""
    __tablename__ = "presupuestos"

    tenant_id: Mapped[uuid.UUID] = _fk("tenants")
    un_id: Mapped[uuid.UUID | None] = _fk("unidades_negocio", True)
    grupo_id: Mapped[uuid.UUID | None] = _fk("grupos_un", True)
    nombre: Mapped[str] = mapped_column(String(160), default="")
    tipo_actividad: Mapped[TipoActividadPresupuesto] = mapped_column(pg_enum(TipoActividadPresupuesto, "tipo_actividad_presupuesto"), default=TipoActividadPresupuesto.todos)
    periodo_inicio: Mapped[date] = mapped_column(Date)
    periodo_fin: Mapped[date] = mapped_column(Date)
    monto: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    moneda: Mapped[str] = mapped_column(String(3), default="MXN")
    umbrales_alerta_json: Mapped[list] = mapped_column(JSONB, default=lambda: [50, 80, 100])
    activo: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[uuid.UUID | None] = _fk("usuarios", True)


class PresupuestoConsumo(Base):
    """Append-only: una fila por folio validado y presupuesto aplicable."""
    __tablename__ = "presupuesto_consumos"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    presupuesto_id: Mapped[uuid.UUID] = _fk("presupuestos")
    tenant_id: Mapped[uuid.UUID] = _fk("tenants")
    folio_id: Mapped[uuid.UUID | None] = _fk("folios", True)
    un_id: Mapped[uuid.UUID | None] = _fk("unidades_negocio", True)
    monto: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    fecha: Mapped[date] = mapped_column(Date, default=date.today)
    tipo: Mapped[TipoActividadPresupuesto] = mapped_column(pg_enum(TipoActividadPresupuesto, "tipo_actividad_presupuesto"), default=TipoActividadPresupuesto.todos)
    notas: Mapped[str] = mapped_column(Text, default="")
    registrado_por: Mapped[uuid.UUID | None] = _fk("usuarios", True)


class ErpEventoPendiente(ConVersion, Base):
    """§6.6: ACMA genera el evento en su formato interno; el adaptador lo traduce (Fase 2)."""
    __tablename__ = "erp_eventos_pendientes"

    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    tenant_id: Mapped[uuid.UUID | None] = _fk("tenants", True)
    operacion: Mapped[OperacionERP] = mapped_column(pg_enum(OperacionERP, "operacion_erp"))
    entidad: Mapped[str] = mapped_column(String(60))
    entidad_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    payload_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    estado: Mapped[EstadoEventoERP] = mapped_column(pg_enum(EstadoEventoERP, "estado_evento_erp"), default=EstadoEventoERP.pendiente)
    intentos: Mapped[int] = mapped_column(Integer, default=0)
    ultimo_error: Mapped[str | None] = mapped_column(Text)
    adaptador: Mapped[AdaptadorERP | None] = mapped_column(pg_enum(AdaptadorERP, "adaptador_erp"), nullable=True)
    respuesta_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    exportacion_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    procesado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ErpConfiguracion(ConVersion, Base):
    __tablename__ = "erp_configuracion"

    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    adaptador: Mapped[AdaptadorERP] = mapped_column(pg_enum(AdaptadorERP, "adaptador_erp"), default=AdaptadorERP.ninguno)
    columnas_excel_json: Mapped[list] = mapped_column(JSONB, default=list)
    cuentas_contables_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    centros_costos_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    exportacion_automatica: Mapped[bool] = mapped_column(Boolean, default=False)


class ErpExportacion(ConVersion, Base):
    __tablename__ = "erp_exportaciones"

    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    periodo_inicio: Mapped[date] = mapped_column(Date)
    periodo_fin: Mapped[date] = mapped_column(Date)
    formato: Mapped[FormatoPoliza] = mapped_column(pg_enum(FormatoPoliza, "formato_poliza"), default=FormatoPoliza.excel)
    archivo_key: Mapped[str | None] = mapped_column(String(300))
    archivo_xml_key: Mapped[str | None] = mapped_column(String(300))
    eventos_incluidos: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    generado_por: Mapped[uuid.UUID | None] = _fk("usuarios", True)


__all__ = [
    "AdaptadorERP", "ErpConfiguracion", "ErpEventoPendiente", "ErpExportacion", "EstadoEventoERP", "FolioCosto", "OperacionERP",
    "Presupuesto", "PresupuestoConsumo", "TarifaManoObra", "TipoActividadPresupuesto",
]
