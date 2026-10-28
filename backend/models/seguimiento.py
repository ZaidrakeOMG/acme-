"""Los cuatro módulos de seguimiento (§7.7–7.9), períodos presupuestales, clasificación de folios no críticos y
calificación del Admin UN (§6.10.5). P07."""
import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, ConVersion, pg_enum
from models.folios import ModuloDestino
from models.minutas import EstadoNotificacion


class EstadoCotizacion(str, enum.Enum):
    solicitada = "solicitada"
    en_preparacion = "en_preparacion"
    enviada = "enviada"
    autorizada = "autorizada"
    rechazada = "rechazada"
    convertida = "convertida"


class EstadoPresupuesto(str, enum.Enum):
    diferido = "diferido"
    reactivado = "reactivado"
    descartado = "descartado"


class EstadoSeguimientoInterno(str, enum.Enum):
    registrado = "registrado"
    en_gestion = "en_gestion"
    con_proveedor = "con_proveedor"
    resuelto = "resuelto"
    cancelado = "cancelado"


class EstadoReprogramacion(str, enum.Enum):
    pendiente_fecha = "pendiente_fecha"
    fecha_asignada = "fecha_asignada"
    tercero_confirmado = "tercero_confirmado"
    en_ejecucion = "en_ejecucion"
    resuelto = "resuelto"
    cancelado = "cancelado"


class VarianteCoordinado(str, enum.Enum):
    A = "A"
    B = "B"


class TipoPeriodoPresupuestal(str, enum.Enum):
    mensual = "mensual"
    trimestral = "trimestral"
    semestral = "semestral"
    anual = "anual"
    fechas = "fechas"


class OpcionClasificacion(str, enum.Enum):
    presupuesto = "presupuesto"
    reprogramacion = "reprogramacion"
    cotizacion = "cotizacion"
    autorizado = "autorizado"
    seguimiento_interno = "seguimiento_interno"


def _fk(tabla: str, nulo: bool = False):
    return mapped_column(UUID(as_uuid=True), ForeignKey(f"{tabla}.id"), nullable=nulo)


class PeriodoPresupuestal(ConVersion, Base):
    __tablename__ = "periodos_presupuestales"

    tenant_id: Mapped[uuid.UUID] = _fk("tenants")
    tipo: Mapped[TipoPeriodoPresupuestal] = mapped_column(pg_enum(TipoPeriodoPresupuestal, "tipo_periodo_presupuestal"), default=TipoPeriodoPresupuestal.trimestral)
    fechas_json: Mapped[list] = mapped_column(JSONB, default=list)
    activo: Mapped[bool] = mapped_column(Boolean, default=True)
    ultimo_recordatorio: Mapped[date | None] = mapped_column(Date)


class Cotizacion(ConVersion, Base):
    __tablename__ = "cotizaciones"

    hallazgo_id: Mapped[uuid.UUID | None] = _fk("hallazgos", True)
    folio_id: Mapped[uuid.UUID | None] = _fk("folios", True)
    tenant_id: Mapped[uuid.UUID] = _fk("tenants")
    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    un_id: Mapped[uuid.UUID] = _fk("unidades_negocio")
    equipo_id: Mapped[uuid.UUID | None] = _fk("equipos", True)
    numero: Mapped[str] = mapped_column(String(20))
    descripcion: Mapped[str] = mapped_column(Text, default="")
    detalle_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    monto: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    moneda: Mapped[str] = mapped_column(String(3), default="MXN")
    estado: Mapped[EstadoCotizacion] = mapped_column(pg_enum(EstadoCotizacion, "estado_cotizacion"), default=EstadoCotizacion.solicitada)
    origen: Mapped[str] = mapped_column(String(30), default="minuta")
    fecha_solicitud: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    fecha_preparacion: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fecha_envio: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fecha_respuesta: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    estado_desde: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    solicitado_por: Mapped[uuid.UUID | None] = _fk("usuarios", True)
    preparado_por: Mapped[uuid.UUID | None] = _fk("usuarios", True)
    respondido_por: Mapped[uuid.UUID | None] = _fk("usuarios", True)
    notas_respuesta: Mapped[str] = mapped_column(Text, default="")
    trabajo_especial_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))  # FK en P08
    pdf_key: Mapped[str | None] = mapped_column(String(300))
    hash_pdf: Mapped[str | None] = mapped_column(String(64))
    pasar_a_presupuesto_si_rechaza: Mapped[bool] = mapped_column(Boolean, default=False)


class CotizacionEnvioExterno(ConVersion, Base):
    __tablename__ = "cotizacion_envios_externos"

    cotizacion_id: Mapped[uuid.UUID] = _fk("cotizaciones")
    tenant_id: Mapped[uuid.UUID] = _fk("tenants")
    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    destinatarios_json: Mapped[list] = mapped_column(JSONB, default=list)
    comentario: Mapped[str] = mapped_column(Text, default="")
    asunto: Mapped[str] = mapped_column(String(300), default="")
    enviado_por: Mapped[uuid.UUID | None] = _fk("usuarios", True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    estado_entrega: Mapped[EstadoNotificacion] = mapped_column(pg_enum(EstadoNotificacion, "estado_notificacion"), default=EstadoNotificacion.pendiente)


class HallazgoPresupuesto(ConVersion, Base):
    __tablename__ = "hallazgos_presupuesto"

    hallazgo_id: Mapped[uuid.UUID | None] = _fk("hallazgos", True)
    folio_id: Mapped[uuid.UUID | None] = _fk("folios", True)
    tenant_id: Mapped[uuid.UUID] = _fk("tenants")
    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    un_id: Mapped[uuid.UUID] = _fk("unidades_negocio")
    equipo_id: Mapped[uuid.UUID | None] = _fk("equipos", True)
    descripcion: Mapped[str] = mapped_column(Text, default="")
    periodo_presupuestal: Mapped[str] = mapped_column(String(40), default="")
    estado: Mapped[EstadoPresupuesto] = mapped_column(pg_enum(EstadoPresupuesto, "estado_presupuesto"), default=EstadoPresupuesto.diferido)
    origen: Mapped[str] = mapped_column(String(30), default="minuta")
    estado_desde: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ultima_revision: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    razon_descarte: Mapped[str | None] = mapped_column(Text)
    decidido_por: Mapped[uuid.UUID | None] = _fk("usuarios", True)
    decidido_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    monto_estimado: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    reactivado_como: Mapped[str | None] = mapped_column(String(20))
    reactivado_registro_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    historial_revisiones_json: Mapped[list] = mapped_column(JSONB, default=list)


class SeguimientoInterno(ConVersion, Base):
    __tablename__ = "seguimientos_internos"

    hallazgo_id: Mapped[uuid.UUID | None] = _fk("hallazgos", True)
    folio_id: Mapped[uuid.UUID | None] = _fk("folios", True)
    tenant_id: Mapped[uuid.UUID] = _fk("tenants")
    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    un_id: Mapped[uuid.UUID] = _fk("unidades_negocio")
    equipo_id: Mapped[uuid.UUID | None] = _fk("equipos", True)
    descripcion: Mapped[str] = mapped_column(Text, default="")
    responsable_un: Mapped[uuid.UUID | None] = _fk("usuarios", True)
    estado: Mapped[EstadoSeguimientoInterno] = mapped_column(pg_enum(EstadoSeguimientoInterno, "estado_seguimiento_interno"),
                                                             default=EstadoSeguimientoInterno.registrado)
    origen: Mapped[str] = mapped_column(String(30), default="minuta")
    estado_desde: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    proveedor: Mapped[str | None] = mapped_column(String(200))
    fecha_acordada: Mapped[date | None] = mapped_column(Date)
    referencia_tercero: Mapped[str | None] = mapped_column(String(120))
    ultima_actualizacion: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    justificacion_cierre: Mapped[str | None] = mapped_column(Text)
    cerrado_por: Mapped[uuid.UUID | None] = _fk("usuarios", True)
    cerrado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Reprogramacion(ConVersion, Base):
    __tablename__ = "reprogramaciones"

    hallazgo_id: Mapped[uuid.UUID | None] = _fk("hallazgos", True)
    folio_id: Mapped[uuid.UUID | None] = _fk("folios", True)
    tenant_id: Mapped[uuid.UUID] = _fk("tenants")
    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    un_id: Mapped[uuid.UUID] = _fk("unidades_negocio")
    equipo_id: Mapped[uuid.UUID | None] = _fk("equipos", True)
    descripcion: Mapped[str] = mapped_column(Text, default="")
    estado: Mapped[EstadoReprogramacion] = mapped_column(pg_enum(EstadoReprogramacion, "estado_reprogramacion"), default=EstadoReprogramacion.pendiente_fecha)
    origen: Mapped[str] = mapped_column(String(30), default="minuta")
    estado_desde: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    motivo: Mapped[str] = mapped_column(Text, default="")
    proveedor_tercero: Mapped[str | None] = mapped_column(String(200))
    fecha_acordada: Mapped[date | None] = mapped_column(Date)
    fecha_tentativa: Mapped[date | None] = mapped_column(Date)
    referencia_tercero: Mapped[str | None] = mapped_column(String(120))
    trabajo_coordinado: Mapped[bool] = mapped_column(Boolean, default=False)
    variante: Mapped[VarianteCoordinado | None] = mapped_column(pg_enum(VarianteCoordinado, "variante_coordinado"), nullable=True)
    tercero_completo: Mapped[bool] = mapped_column(Boolean, default=False)
    folio_coordinado_id: Mapped[uuid.UUID | None] = _fk("folios", True)
    fechas_vencidas_count: Mapped[int] = mapped_column(Integer, default=0)
    escalada_empresa: Mapped[bool] = mapped_column(Boolean, default=False)
    fecha_resolucion: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    justificacion_cierre: Mapped[str | None] = mapped_column(Text)
    cerrado_por: Mapped[uuid.UUID | None] = _fk("usuarios", True)


class ModuloHistorial(Base):
    """Append-only (trigger acma_auditoria_inmutable)."""
    __tablename__ = "modulo_historial"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    modulo: Mapped[ModuloDestino] = mapped_column(pg_enum(ModuloDestino, "modulo_destino"))
    registro_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    tenant_id: Mapped[uuid.UUID] = _fk("tenants")
    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    estado_anterior: Mapped[str | None] = mapped_column(String(40))
    estado_nuevo: Mapped[str] = mapped_column(String(40))
    usuario_id: Mapped[uuid.UUID | None] = _fk("usuarios", True)
    actor_rol: Mapped[str] = mapped_column(String(40), default="sistema")
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    notas: Mapped[str] = mapped_column(Text, default="")
    datos_json: Mapped[dict] = mapped_column(JSONB, default=dict)


class ClasificacionConfiguracion(ConVersion, Base):
    __tablename__ = "clasificacion_configuracion"

    tenant_id: Mapped[uuid.UUID] = _fk("tenants")
    severidades_no_criticas_json: Mapped[list] = mapped_column(JSONB, default=lambda: ["muy_baja", "baja", "media"])
    plazo_horas: Mapped[int] = mapped_column(Integer, default=24)
    umbral_calificacion: Mapped[int] = mapped_column(Integer, default=70)
    admin_empresa_puede_clasificar: Mapped[bool] = mapped_column(Boolean, default=False)
    puntos_json: Mapped[dict] = mapped_column(JSONB, default=lambda: {"base": 100, "clasificacion_tarde_por_hora": 2, "clasificacion_tarde_max": 20,
                                                                      "minuta_sin_respuesta": 10, "minuta_tardia": 5})
    activa: Mapped[bool] = mapped_column(Boolean, default=True)


class FolioClasificacion(ConVersion, Base):
    __tablename__ = "folio_clasificaciones"

    folio_id: Mapped[uuid.UUID] = _fk("folios")
    tenant_id: Mapped[uuid.UUID] = _fk("tenants")
    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    un_id: Mapped[uuid.UUID] = _fk("unidades_negocio")
    admin_un_id: Mapped[uuid.UUID] = _fk("usuarios")
    opcion_clasificacion: Mapped[OpcionClasificacion] = mapped_column(pg_enum(OpcionClasificacion, "opcion_clasificacion"))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    plazo_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dentro_de_plazo: Mapped[bool] = mapped_column(Boolean, default=True)
    horas_retraso: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=Decimal("0"))
    fecha_tentativa: Mapped[date | None] = mapped_column(Date)
    modulo_destino: Mapped[ModuloDestino | None] = mapped_column(pg_enum(ModuloDestino, "modulo_destino"), nullable=True)
    modulo_registro_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    notas: Mapped[str] = mapped_column(Text, default="")


class AdminUNCalificacion(ConVersion, Base):
    __tablename__ = "admin_un_calificacion"

    tenant_id: Mapped[uuid.UUID] = _fk("tenants")
    usuario_id: Mapped[uuid.UUID] = _fk("usuarios")
    un_id: Mapped[uuid.UUID | None] = _fk("unidades_negocio", True)
    periodo: Mapped[str] = mapped_column(String(20))
    puntos_total: Mapped[int] = mapped_column(Integer, default=100)
    folios_clasificados_tiempo: Mapped[int] = mapped_column(Integer, default=0)
    folios_tardios: Mapped[int] = mapped_column(Integer, default=0)
    folios_sin_clasificar: Mapped[int] = mapped_column(Integer, default=0)
    minutas_respondidas: Mapped[int] = mapped_column(Integer, default=0)
    minutas_tardias: Mapped[int] = mapped_column(Integer, default=0)
    calificacion_final: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("100"))
    eventos_json: Mapped[list] = mapped_column(JSONB, default=list)
    calculada_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    cerrada: Mapped[bool] = mapped_column(Boolean, default=False)
