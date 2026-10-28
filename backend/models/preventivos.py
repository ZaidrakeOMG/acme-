"""Planes de mantenimiento con triggers (§6.9.1), calendario de preventivos (§7.6), autorizaciones de reprogramación y
cancelación, y reasignaciones forzadas (§6.8.2). P06."""
import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, ConVersion, pg_enum
from models.folios import CanalAprobacion


class TipoTrigger(str, enum.Enum):
    tiempo_fijo = "tiempo_fijo"
    calendario = "calendario"
    medidor_umbral = "medidor_umbral"
    medidor_intervalo = "medidor_intervalo"
    evento = "evento"
    combinado = "combinado"


TRIGGERS_FASE_1 = {TipoTrigger.tiempo_fijo, TipoTrigger.calendario}


class EstadoPlan(str, enum.Enum):
    activo = "activo"
    inactivo = "inactivo"


class EstadoEjecucionPlan(str, enum.Enum):
    programada = "programada"
    generada = "generada"
    ejecutada = "ejecutada"
    cancelada = "cancelada"


class EstadoPreventivo(str, enum.Enum):
    programado = "programado"
    generado = "generado"
    reprogramado = "reprogramado"
    cancelado = "cancelado"
    ejecutado = "ejecutado"


class OrigenPreventivo(str, enum.Enum):
    manual = "manual"
    plan = "plan"


class TipoAutorizacionPreventivo(str, enum.Enum):
    reprogramacion = "reprogramacion"
    cancelacion = "cancelacion"


class EstadoAutorizacion(str, enum.Enum):
    pendiente = "pendiente"
    autorizada = "autorizada"
    rechazada = "rechazada"


class TipoReasignacion(str, enum.Enum):
    automatica = "automatica"
    forzada = "forzada"


# §6.8.2 catálogo literal de razones (se siembra por prestador).
RAZONES_REASIGNACION = [
    ("Incidencia del técnico", "Accidente, descompostura de vehículo, enfermedad u otra causa que impide al técnico continuar."),
    ("Prioridad de cliente", "El cliente solicita atención inmediata que requiere reubicar recursos."),
    ("Optimización de ruta", "El despachador detecta una oportunidad de mejora que el algoritmo no capturó."),
    ("Falta de habilidad no detectada", "Se descubrió en campo que el folio requiere una habilidad distinta a la registrada."),
    ("Falta de refacción", "El técnico no tiene la refacción y no puede abastecerse a tiempo."),
    ("Solicitud del técnico", "El técnico reporta que no puede atender el folio por razones justificadas."),
    ("Corrección de asignación inicial", "Error en la asignación automática detectado por el despachador."),
]


def _fk(tabla: str, nulo: bool = False):
    return mapped_column(UUID(as_uuid=True), ForeignKey(f"{tabla}.id"), nullable=nulo)


class PlanMantenimiento(ConVersion, Base):
    __tablename__ = "planes_mantenimiento"

    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    tenant_id: Mapped[uuid.UUID | None] = _fk("tenants", True)  # NULL = aplica a todos los clientes del prestador
    tipo_equipo_id: Mapped[uuid.UUID] = _fk("tipos_equipo")
    nombre: Mapped[str] = mapped_column(String(160))
    descripcion: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[int] = mapped_column(Integer, default=1)
    estado: Mapped[EstadoPlan] = mapped_column(pg_enum(EstadoPlan, "estado_plan"), default=EstadoPlan.activo)
    tiempo_ventana_dias: Mapped[int] = mapped_column(Integer, default=7)
    formulario_id: Mapped[uuid.UUID | None] = _fk("formularios", True)
    nivel_severidad_id: Mapped[uuid.UUID | None] = _fk("niveles_severidad", True)
    created_by: Mapped[uuid.UUID | None] = _fk("usuarios", True)


class PlanTrigger(ConVersion, Base):
    __tablename__ = "plan_triggers"

    plan_id: Mapped[uuid.UUID] = _fk("planes_mantenimiento")
    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    tipo_trigger: Mapped[TipoTrigger] = mapped_column(pg_enum(TipoTrigger, "tipo_trigger_plan"))
    parametros_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    logica_combinacion: Mapped[str | None] = mapped_column(String(10))


class PlanTarea(ConVersion, Base):
    __tablename__ = "plan_tareas"

    plan_id: Mapped[uuid.UUID] = _fk("planes_mantenimiento")
    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    orden: Mapped[int] = mapped_column(Integer, default=1)
    descripcion: Mapped[str] = mapped_column(String(300))
    tiempo_estimado_min: Mapped[int] = mapped_column(Integer, default=0)
    habilidad_requerida_id: Mapped[uuid.UUID | None] = _fk("habilidades", True)


class PlanMaterial(ConVersion, Base):
    __tablename__ = "plan_materiales"

    plan_id: Mapped[uuid.UUID] = _fk("planes_mantenimiento")
    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    articulo_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))  # FK a inventario en P09
    descripcion: Mapped[str] = mapped_column(String(200))
    cantidad_estandar: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("1"))
    unidad: Mapped[str] = mapped_column(String(30), default="pieza")


class PlanEjecucion(ConVersion, Base):
    __tablename__ = "plan_ejecuciones"

    plan_id: Mapped[uuid.UUID] = _fk("planes_mantenimiento")
    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    tenant_id: Mapped[uuid.UUID] = _fk("tenants")
    equipo_id: Mapped[uuid.UUID] = _fk("equipos")
    folio_id: Mapped[uuid.UUID | None] = _fk("folios", True)
    calendario_id: Mapped[uuid.UUID | None] = _fk("preventivos_calendario", True)
    formulario_id: Mapped[uuid.UUID | None] = _fk("formularios", True)
    fecha_programada: Mapped[date] = mapped_column(Date)
    fecha_real: Mapped[date | None] = mapped_column(Date)
    desvio_dias: Mapped[int | None] = mapped_column(Integer)
    estado: Mapped[EstadoEjecucionPlan] = mapped_column(pg_enum(EstadoEjecucionPlan, "estado_ejecucion_plan"), default=EstadoEjecucionPlan.programada)


class EquipoPlan(ConVersion, Base):
    __tablename__ = "equipo_planes"

    equipo_id: Mapped[uuid.UUID] = _fk("equipos")
    plan_id: Mapped[uuid.UUID] = _fk("planes_mantenimiento")
    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    tenant_id: Mapped[uuid.UUID] = _fk("tenants")
    activo: Mapped[bool] = mapped_column(Boolean, default=True)
    fecha_proxima_ejecucion: Mapped[date | None] = mapped_column(Date)
    ultimo_valor_medidor: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))  # Fase 2
    fecha_ultima_ejecucion: Mapped[date | None] = mapped_column(Date)
    fecha_alta: Mapped[date] = mapped_column(Date, default=date.today)


class PreventivoCalendario(ConVersion, Base):
    """Unificación de `calendarios_preventivos` (§6.9.1) y `preventivos_calendario` (§7.6)."""
    __tablename__ = "preventivos_calendario"

    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    tenant_id: Mapped[uuid.UUID] = _fk("tenants")
    un_id: Mapped[uuid.UUID] = _fk("unidades_negocio")
    equipo_id: Mapped[uuid.UUID | None] = _fk("equipos", True)
    plan_id: Mapped[uuid.UUID | None] = _fk("planes_mantenimiento", True)
    tecnico_id: Mapped[uuid.UUID | None] = _fk("usuarios", True)
    fecha_programada: Mapped[date] = mapped_column(Date)
    fecha_programada_original: Mapped[date | None] = mapped_column(Date)
    fecha_real: Mapped[date | None] = mapped_column(Date)
    desvio_dias: Mapped[int | None] = mapped_column(Integer)
    estado: Mapped[EstadoPreventivo] = mapped_column(pg_enum(EstadoPreventivo, "estado_preventivo"), default=EstadoPreventivo.programado)
    folio_id: Mapped[uuid.UUID | None] = _fk("folios", True)
    formulario_id: Mapped[uuid.UUID | None] = _fk("formularios", True)
    origen: Mapped[OrigenPreventivo] = mapped_column(pg_enum(OrigenPreventivo, "origen_preventivo"), default=OrigenPreventivo.manual)
    descripcion: Mapped[str] = mapped_column(Text, default="")
    cargado_por: Mapped[uuid.UUID | None] = _fk("usuarios", True)
    reprogramado_desde_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("preventivos_calendario.id"), nullable=True)


class CalendarioPublicacion(ConVersion, Base):
    __tablename__ = "calendario_publicaciones"

    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    tenant_id: Mapped[uuid.UUID] = _fk("tenants")
    mes: Mapped[date] = mapped_column(Date)  # primer día del mes
    publicado_por: Mapped[uuid.UUID | None] = _fk("usuarios", True)
    publicado_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    total_preventivos: Mapped[int] = mapped_column(Integer, default=0)


class AutorizacionPreventivo(ConVersion, Base):
    __tablename__ = "autorizaciones_preventivo"

    folio_id: Mapped[uuid.UUID] = _fk("folios")
    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    tenant_id: Mapped[uuid.UUID] = _fk("tenants")
    calendario_id: Mapped[uuid.UUID | None] = _fk("preventivos_calendario", True)
    tipo: Mapped[TipoAutorizacionPreventivo] = mapped_column(pg_enum(TipoAutorizacionPreventivo, "tipo_autorizacion_preventivo"))
    solicitado_por: Mapped[uuid.UUID] = _fk("usuarios")
    autorizado_por: Mapped[uuid.UUID | None] = _fk("usuarios", True)
    fecha_solicitud: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    fecha_autorizacion: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    razon: Mapped[str] = mapped_column(Text)
    fecha_nueva: Mapped[date | None] = mapped_column(Date)
    estado: Mapped[EstadoAutorizacion] = mapped_column(pg_enum(EstadoAutorizacion, "estado_autorizacion"), default=EstadoAutorizacion.pendiente)
    canal: Mapped[CanalAprobacion] = mapped_column(pg_enum(CanalAprobacion, "canal_aprobacion"), default=CanalAprobacion.app)
    notas_respuesta: Mapped[str] = mapped_column(Text, default="")


class RazonReasignacion(ConVersion, Base):
    __tablename__ = "razones_reasignacion"

    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    descripcion: Mapped[str] = mapped_column(String(160))
    detalle: Mapped[str] = mapped_column(Text, default="")
    activa: Mapped[bool] = mapped_column(Boolean, default=True)
    orden_display: Mapped[int] = mapped_column(Integer, default=0)


class Reasignacion(ConVersion, Base):
    __tablename__ = "reasignaciones"

    folio_id: Mapped[uuid.UUID] = _fk("folios")
    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    tenant_id: Mapped[uuid.UUID] = _fk("tenants")
    tecnico_origen_id: Mapped[uuid.UUID | None] = _fk("usuarios", True)
    tecnico_destino_id: Mapped[uuid.UUID] = _fk("usuarios")
    tipo: Mapped[TipoReasignacion] = mapped_column(pg_enum(TipoReasignacion, "tipo_reasignacion"), default=TipoReasignacion.forzada)
    razon_id: Mapped[uuid.UUID | None] = _fk("razones_reasignacion", True)
    comentario: Mapped[str] = mapped_column(Text, default="")
    despachador_id: Mapped[uuid.UUID | None] = _fk("usuarios", True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ReasignacionValidacion(ConVersion, Base):
    __tablename__ = "reasignacion_validaciones"

    reasignacion_id: Mapped[uuid.UUID] = _fk("reasignaciones")
    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    tenant_id: Mapped[uuid.UUID] = _fk("tenants")
    habilidad_ok: Mapped[bool] = mapped_column(Boolean, default=True)
    refaccion_ok: Mapped[bool | None] = mapped_column(Boolean)
    advertencias_json: Mapped[list] = mapped_column(JSONB, default=list)
