"""Folios (P04): ciclo de vida §6.8.6, validaciones automáticas y flujo de aprobación multinivel §6.8.7."""
import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, SmallInteger, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, ConVersion, Rol, pg_enum


class TipoFolio(str, enum.Enum):
    correctivo = "correctivo"
    preventivo = "preventivo"
    especial = "especial"


class EstadoFolio(str, enum.Enum):
    capturado = "capturado"
    en_revision = "en_revision"
    pendiente_informacion = "pendiente_informacion"
    autorizado = "autorizado"
    asignado = "asignado"
    reasignado = "reasignado"
    en_camino = "en_camino"
    en_ejecucion = "en_ejecucion"
    pendiente_refaccion = "pendiente_refaccion"
    cerrado = "cerrado"
    cancelado = "cancelado"


ESTADOS_FINALES = {EstadoFolio.cerrado, EstadoFolio.cancelado}
# Un folio "abierto" para la regla de duplicados (§6.8.6) es cualquiera que no haya llegado a un estado final.
ESTADOS_ABIERTOS = [e for e in EstadoFolio if e not in ESTADOS_FINALES]


class SeveridadOrigen(str, enum.Enum):
    automatica_matriz = "automatica_matriz"
    override_admin = "override_admin"


class TipoEvidenciaFolio(str, enum.Enum):
    antes = "antes"
    durante = "durante"
    despues = "despues"
    firma = "firma"
    factura = "factura"
    otro = "otro"


class OrigenRefaccion(str, enum.Enum):
    almacen = "almacen"
    oc = "oc"
    caja_chica = "caja_chica"


class TriggerRevision(str, enum.Enum):
    sin_contrato = "sin_contrato"
    garantia = "garantia"
    tipo_falla_flag = "tipo_falla_flag"
    fuera_horario = "fuera_horario"
    keyword_alerta = "keyword_alerta"
    severidad_no_configurada = "severidad_no_configurada"
    confirmacion_un_faltante = "confirmacion_un_faltante"
    pendiente_clasificacion = "pendiente_clasificacion"  # P07 §6.10.5


class CriterioAprobacion(str, enum.Enum):
    monto = "monto"
    criticidad = "criticidad"
    tipo_trabajo = "tipo_trabajo"


class EstadoFlujo(str, enum.Enum):
    activo = "activo"
    aprobado = "aprobado"
    rechazado = "rechazado"
    bloqueado = "bloqueado"


class ComportamientoTimeout(str, enum.Enum):
    escalar = "escalar"
    bloquear_alertar = "bloquear_alertar"
    autorizar_automatico = "autorizar_automatico"
    depende_criticidad = "depende_criticidad"


class DecisionAprobacion(str, enum.Enum):
    aprobado = "aprobado"
    rechazado = "rechazado"
    auto_aprobado = "auto_aprobado"
    escalado = "escalado"
    bloqueado = "bloqueado"


class RazonRechazo(str, enum.Enum):
    por_presupuesto = "por_presupuesto"
    requiere_cotizacion = "requiere_cotizacion"
    seguimiento_interno = "seguimiento_interno"
    reprogramar = "reprogramar"


class ModuloDestino(str, enum.Enum):
    por_presupuesto = "por_presupuesto"
    cotizaciones = "cotizaciones"
    seguimiento_interno = "seguimiento_interno"
    reprogramacion = "reprogramacion"


# §6.8.7: cada razón de rechazo redirige a un módulo de seguimiento (P07).
MODULO_POR_RAZON = {
    RazonRechazo.por_presupuesto: ModuloDestino.por_presupuesto,
    RazonRechazo.requiere_cotizacion: ModuloDestino.cotizaciones,
    RazonRechazo.seguimiento_interno: ModuloDestino.seguimiento_interno,
    RazonRechazo.reprogramar: ModuloDestino.reprogramacion,
}


class CanalAprobacion(str, enum.Enum):
    push = "push"
    app = "app"
    minuta = "minuta"
    sistema = "sistema"


class Criticidad(str, enum.Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


CRITICOS = {Criticidad.A, Criticidad.B}


def _fk(tabla: str, nulo: bool = False):
    return mapped_column(UUID(as_uuid=True), ForeignKey(f"{tabla}.id"), nullable=nulo)


class FolioPoliticasTenant(ConVersion, Base):
    __tablename__ = "folio_politicas_tenant"

    tenant_id: Mapped[uuid.UUID] = _fk("tenants")
    bloqueo_total_duplicados: Mapped[bool] = mapped_column(Boolean, default=False)
    revision_obligatoria_garantia: Mapped[bool] = mapped_column(Boolean, default=False)
    autorizacion_automatica_criticos: Mapped[bool] = mapped_column(Boolean, default=False)
    aprobacion_secuencial: Mapped[bool] = mapped_column(Boolean, default=False)
    prefijo_folio: Mapped[str] = mapped_column(String(10), default="F")
    ultimo_numero: Mapped[int] = mapped_column(Integer, default=0)
    plazo_encuesta_horas: Mapped[int] = mapped_column(Integer, default=48)  # P05: ventana para responder la encuesta tras el cierre


class FolioKeywordAlerta(ConVersion, Base):
    __tablename__ = "folio_keywords_alerta"

    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    tenant_id: Mapped[uuid.UUID | None] = _fk("tenants", True)
    palabra: Mapped[str] = mapped_column(String(80))
    activa: Mapped[bool] = mapped_column(Boolean, default=True)


class AprobacionRegla(ConVersion, Base):
    __tablename__ = "aprobacion_reglas"

    tenant_id: Mapped[uuid.UUID] = _fk("tenants")
    nivel: Mapped[int] = mapped_column(SmallInteger)
    criterio: Mapped[CriterioAprobacion] = mapped_column(pg_enum(CriterioAprobacion, "criterio_aprobacion"))
    operador: Mapped[str] = mapped_column(String(12))
    valor_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    activa: Mapped[bool] = mapped_column(Boolean, default=True)


class AprobacionNivelConfig(ConVersion, Base):
    __tablename__ = "aprobacion_niveles_config"

    tenant_id: Mapped[uuid.UUID] = _fk("tenants")
    nivel: Mapped[int] = mapped_column(SmallInteger)
    rol_aprobador: Mapped[Rol] = mapped_column(pg_enum(Rol, "rol_usuario"))
    tiempo_limite_horas: Mapped[int] = mapped_column(Integer)
    comportamiento_timeout: Mapped[ComportamientoTimeout] = mapped_column(
        pg_enum(ComportamientoTimeout, "comportamiento_timeout"), default=ComportamientoTimeout.bloquear_alertar)
    notificar_por_json: Mapped[list] = mapped_column(JSONB, default=lambda: ["push", "app"])


class Folio(ConVersion, Base):
    __tablename__ = "folios"

    numero_folio: Mapped[str] = mapped_column(String(30))
    tenant_id: Mapped[uuid.UUID] = _fk("tenants")
    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    un_id: Mapped[uuid.UUID] = _fk("unidades_negocio")
    equipo_id: Mapped[uuid.UUID] = _fk("equipos")
    tipo_falla_id: Mapped[uuid.UUID | None] = _fk("tipos_falla", True)
    tipo_folio: Mapped[TipoFolio] = mapped_column(pg_enum(TipoFolio, "tipo_folio"), default=TipoFolio.correctivo)
    estado: Mapped[EstadoFolio] = mapped_column(pg_enum(EstadoFolio, "estado_folio"), default=EstadoFolio.capturado)
    prioridad: Mapped[int] = mapped_column(SmallInteger, default=0)
    descripcion: Mapped[str] = mapped_column(Text, default="")
    tecnico_id: Mapped[uuid.UUID | None] = _fk("usuarios", True)
    orden_en_ruta: Mapped[int | None] = mapped_column(Integer)
    ventana_inicio: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ventana_fin: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    severidad_id: Mapped[uuid.UUID | None] = _fk("niveles_severidad", True)
    severidad_origen: Mapped[SeveridadOrigen] = mapped_column(
        pg_enum(SeveridadOrigen, "severidad_origen"), default=SeveridadOrigen.automatica_matriz)
    confirmacion_un: Mapped[bool] = mapped_column(Boolean, default=False)
    confirmacion_un_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmacion_un_geolat: Mapped[float | None] = mapped_column()
    confirmacion_un_geolng: Mapped[float | None] = mapped_column()
    folio_duplicado_justificacion: Mapped[str | None] = mapped_column(Text)
    folio_duplicado_ref_id: Mapped[uuid.UUID | None] = _fk("folios", True)
    monto_estimado: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    capturado_por: Mapped[uuid.UUID] = _fk("usuarios")
    capturado_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    geolat_captura: Mapped[float | None] = mapped_column()
    geolng_captura: Mapped[float | None] = mapped_column()
    fecha_falla: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    fecha_inicio_atencion: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fecha_cierre: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    razon_cancelacion: Mapped[str | None] = mapped_column(Text)
    cancelado_por: Mapped[uuid.UUID | None] = _fk("usuarios", True)
    # P06: folio preventivo generado por un plan o por el calendario manual.
    plan_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    calendario_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)


class FolioEstadoHistorial(Base):
    """Append-only (triggers como audit_log). `evento`: transicion | comentario | folio.derivado_a_modulo | aprobacion.*"""
    __tablename__ = "folio_estados_historial"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    folio_id: Mapped[uuid.UUID] = _fk("folios")
    tenant_id: Mapped[uuid.UUID] = _fk("tenants")
    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    evento: Mapped[str] = mapped_column(String(60), default="transicion")
    estado_anterior: Mapped[EstadoFolio | None] = mapped_column(pg_enum(EstadoFolio, "estado_folio"), nullable=True)
    estado_nuevo: Mapped[EstadoFolio] = mapped_column(pg_enum(EstadoFolio, "estado_folio"))
    actor_id: Mapped[uuid.UUID | None] = _fk("usuarios", True)
    actor_rol: Mapped[str] = mapped_column(String(40))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    notas: Mapped[str] = mapped_column(Text, default="")
    datos_contexto_json: Mapped[dict] = mapped_column(JSONB, default=dict)


class _VinculoFormulario(ConVersion):
    folio_id: Mapped[uuid.UUID] = _fk("folios")
    tenant_id: Mapped[uuid.UUID] = _fk("tenants")
    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    respuesta_id: Mapped[uuid.UUID] = _fk("formulario_respuestas")
    formulario_id: Mapped[uuid.UUID] = _fk("formularios")
    version_formulario: Mapped[int] = mapped_column(Integer)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FolioFormularioCaptura(_VinculoFormulario, Base):
    __tablename__ = "folio_formulario_captura"


class FolioFormularioAtencion(_VinculoFormulario, Base):
    __tablename__ = "folio_formulario_atencion"


class FolioEvidencia(ConVersion, Base):
    __tablename__ = "folio_evidencias"

    folio_id: Mapped[uuid.UUID] = _fk("folios")
    tenant_id: Mapped[uuid.UUID] = _fk("tenants")
    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    evidencia_id: Mapped[uuid.UUID | None] = _fk("formulario_evidencias", True)
    tipo: Mapped[TipoEvidenciaFolio] = mapped_column(pg_enum(TipoEvidenciaFolio, "tipo_evidencia_folio"))
    archivo_key: Mapped[str] = mapped_column(String(300))
    geolat: Mapped[float | None] = mapped_column()
    geolng: Mapped[float | None] = mapped_column()
    timestamp_captura: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    subido_por: Mapped[uuid.UUID | None] = _fk("usuarios", True)


class FolioRefaccion(ConVersion, Base):
    __tablename__ = "folio_refacciones"

    folio_id: Mapped[uuid.UUID] = _fk("folios")
    tenant_id: Mapped[uuid.UUID] = _fk("tenants")
    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    articulo_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))  # FK a inventario en P09
    descripcion: Mapped[str] = mapped_column(String(200))
    cantidad: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    origen: Mapped[OrigenRefaccion] = mapped_column(pg_enum(OrigenRefaccion, "origen_refaccion"), default=OrigenRefaccion.almacen)
    costo_unitario: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    gasto_caja_chica_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class FolioSLA(ConVersion, Base):
    __tablename__ = "folio_sla"

    folio_id: Mapped[uuid.UUID] = _fk("folios")
    tenant_id: Mapped[uuid.UUID] = _fk("tenants")
    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    nivel_severidad_id: Mapped[uuid.UUID | None] = _fk("niveles_severidad", True)
    tiempo_respuesta_prometido_horas: Mapped[int] = mapped_column(Integer)
    tiempo_resolucion_prometido_horas: Mapped[int] = mapped_column(Integer)
    tiempo_respuesta_real_min: Mapped[int | None] = mapped_column(Integer)
    tiempo_resolucion_real_min: Mapped[int | None] = mapped_column(Integer)
    cumplimiento_respuesta: Mapped[bool | None] = mapped_column(Boolean)
    cumplimiento_resolucion: Mapped[bool | None] = mapped_column(Boolean)
    autorizado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # P07: el SLA corre desde aquí (P10)
    excluir_sla_por_cliente: Mapped[bool] = mapped_column(Boolean, default=False)     # P07: clasificación tardía del Admin UN


class FolioEncuesta(ConVersion, Base):
    __tablename__ = "folio_encuesta"

    folio_id: Mapped[uuid.UUID] = _fk("folios")
    tenant_id: Mapped[uuid.UUID] = _fk("tenants")
    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    operador_id: Mapped[uuid.UUID] = _fk("usuarios")
    nps_score: Mapped[int] = mapped_column(SmallInteger)
    respuesta_id: Mapped[uuid.UUID | None] = _fk("formulario_respuestas", True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RevisionManualTrigger(ConVersion, Base):
    __tablename__ = "revision_manual_triggers"

    folio_id: Mapped[uuid.UUID] = _fk("folios")
    tenant_id: Mapped[uuid.UUID] = _fk("tenants")
    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    trigger_tipo: Mapped[TriggerRevision] = mapped_column(pg_enum(TriggerRevision, "trigger_revision"))
    descripcion: Mapped[str] = mapped_column(Text, default="")
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resuelto: Mapped[bool] = mapped_column(Boolean, default=False)


class AprobacionFlujo(ConVersion, Base):
    __tablename__ = "aprobacion_flujos"

    folio_id: Mapped[uuid.UUID] = _fk("folios")
    tenant_id: Mapped[uuid.UUID] = _fk("tenants")
    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    nivel_actual: Mapped[int] = mapped_column(SmallInteger)
    nivel_maximo_requerido: Mapped[int] = mapped_column(SmallInteger)
    estado: Mapped[EstadoFlujo] = mapped_column(pg_enum(EstadoFlujo, "estado_flujo_aprobacion"), default=EstadoFlujo.activo)
    iniciado_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resuelto_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AprobacionDecision(Base):
    """Append-only: ningún rol la modifica, incluido Superadmin (§6.8.7)."""
    __tablename__ = "aprobacion_decisiones"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    flujo_id: Mapped[uuid.UUID] = _fk("aprobacion_flujos")
    folio_id: Mapped[uuid.UUID] = _fk("folios")
    tenant_id: Mapped[uuid.UUID] = _fk("tenants")
    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    nivel: Mapped[int] = mapped_column(SmallInteger)
    actor_id: Mapped[uuid.UUID | None] = _fk("usuarios", True)
    decision: Mapped[DecisionAprobacion] = mapped_column(pg_enum(DecisionAprobacion, "decision_aprobacion"))
    razon_rechazo: Mapped[RazonRechazo | None] = mapped_column(pg_enum(RazonRechazo, "razon_rechazo"), nullable=True)
    modulo_destino: Mapped[ModuloDestino | None] = mapped_column(pg_enum(ModuloDestino, "modulo_destino"), nullable=True)
    modulo_destino_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    canal: Mapped[CanalAprobacion] = mapped_column(pg_enum(CanalAprobacion, "canal_aprobacion"))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    notas: Mapped[str] = mapped_column(Text, default="")


class AprobacionAlertaTimeout(ConVersion, Base):
    __tablename__ = "aprobacion_alertas_timeout"

    flujo_id: Mapped[uuid.UUID] = _fk("aprobacion_flujos")
    folio_id: Mapped[uuid.UUID] = _fk("folios")
    tenant_id: Mapped[uuid.UUID] = _fk("tenants")
    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    nivel: Mapped[int] = mapped_column(SmallInteger)
    vence_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    procesado: Mapped[bool] = mapped_column(Boolean, default=False)
    accion_ejecutada: Mapped[str | None] = mapped_column(String(40))
    procesado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
