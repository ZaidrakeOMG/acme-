"""Trabajos especiales con validación del cliente (§6.10.6, §7.9) y seguimiento de OC para instalación de activos (§6.10.7). P08."""
import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, ConVersion, pg_enum


class EstadoTrabajoEspecial(str, enum.Enum):
    creado = "creado"
    enviado_cliente = "enviado_cliente"
    aceptado = "aceptado"
    rechazado = "rechazado"
    programado = "programado"
    en_ejecucion = "en_ejecucion"
    cerrado = "cerrado"
    cancelado = "cancelado"


class DecisionTECliente(str, enum.Enum):
    aceptado = "aceptado"
    rechazado = "rechazado"


class TipoEvidenciaTE(str, enum.Enum):
    avance = "avance"
    cierre = "cierre"
    firma = "firma"
    documento = "documento"


class EstatusOCActivo(str, enum.Enum):
    pendiente_iniciar_tramite = "pendiente_iniciar_tramite"
    oc_en_tramite = "oc_en_tramite"
    oc_autorizada = "oc_autorizada"
    listo_para_asignar = "listo_para_asignar"
    oc_rechazada = "oc_rechazada"


class DecisionOCRechazo(str, enum.Enum):
    cancelar = "cancelar"
    reprogramar_periodo = "reprogramar_periodo"


def _fk(tabla: str, nullable: bool = False):
    return mapped_column(UUID(as_uuid=True), ForeignKey(f"{tabla}.id"), nullable=nullable)


class TrabajoEspecial(ConVersion, Base):
    __tablename__ = "trabajos_especiales"

    numero: Mapped[str] = mapped_column(String(20))
    tenant_id: Mapped[uuid.UUID] = _fk("tenants")
    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    un_id: Mapped[uuid.UUID] = _fk("unidades_negocio")
    equipo_id: Mapped[uuid.UUID | None] = _fk("equipos", True)
    cotizacion_id: Mapped[uuid.UUID | None] = _fk("cotizaciones", True)
    hallazgo_id: Mapped[uuid.UUID | None] = _fk("hallazgos", True)
    descripcion: Mapped[str] = mapped_column(Text, default="")
    detalle_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    estado: Mapped[EstadoTrabajoEspecial] = mapped_column(pg_enum(EstadoTrabajoEspecial, "estado_trabajo_especial"), default=EstadoTrabajoEspecial.creado)
    estado_desde: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    urgencia: Mapped[bool] = mapped_column(Boolean, default=False)
    creado_por_id: Mapped[uuid.UUID | None] = _fk("usuarios", True)
    creado_por_rol: Mapped[str] = mapped_column(String(40), default="sistema")
    formulario_id: Mapped[uuid.UUID | None] = _fk("formularios", True)
    respuesta_formulario_id: Mapped[uuid.UUID | None] = _fk("formulario_respuestas", True)
    monto: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    moneda: Mapped[str] = mapped_column(String(3), default="MXN")
    cotizacion_retroactiva_id: Mapped[uuid.UUID | None] = _fk("cotizaciones", True)
    fecha_programada: Mapped[date | None] = mapped_column(Date)
    fecha_inicio: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fecha_cierre: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    tecnico_ids_json: Mapped[list] = mapped_column(JSONB, default=list)
    tecnico_responsable_id: Mapped[uuid.UUID | None] = _fk("usuarios", True)
    folio_id: Mapped[uuid.UUID | None] = _fk("folios", True)
    razon_cancelacion: Mapped[str | None] = mapped_column(Text)
    version_enviada: Mapped[int] = mapped_column(Integer, default=0)
    enviado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    aceptado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    programado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TERespuestaCliente(Base):
    """Append-only: cada aceptación o rechazo del cliente por versión enviada (§6.10.6)."""
    __tablename__ = "te_respuesta_cliente"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    trabajo_especial_id: Mapped[uuid.UUID] = _fk("trabajos_especiales")
    tenant_id: Mapped[uuid.UUID] = _fk("tenants")
    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    version_enviada: Mapped[int] = mapped_column(Integer, default=1)
    respondido_por: Mapped[uuid.UUID | None] = _fk("usuarios", True)
    decision: Mapped[DecisionTECliente] = mapped_column(pg_enum(DecisionTECliente, "decision_te_cliente"))
    comentario: Mapped[str] = mapped_column(Text, default="")
    canal: Mapped[str] = mapped_column(String(20), default="app")
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TEEvidencia(ConVersion, Base):
    __tablename__ = "te_evidencias"

    trabajo_especial_id: Mapped[uuid.UUID] = _fk("trabajos_especiales")
    tenant_id: Mapped[uuid.UUID] = _fk("tenants")
    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    tipo: Mapped[TipoEvidenciaTE] = mapped_column(pg_enum(TipoEvidenciaTE, "tipo_evidencia_te"), default=TipoEvidenciaTE.avance)
    evidencia_id: Mapped[uuid.UUID | None] = _fk("formulario_evidencias", True)
    archivo_key: Mapped[str] = mapped_column(String(300), default="")
    geolat: Mapped[float | None] = mapped_column()
    geolng: Mapped[float | None] = mapped_column()
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    subido_por: Mapped[uuid.UUID | None] = _fk("usuarios", True)


class TEHistorial(Base):
    """Append-only (trigger acma_auditoria_inmutable): tabla propia del TE, separada de `modulo_historial` de P07."""
    __tablename__ = "te_historial"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    trabajo_especial_id: Mapped[uuid.UUID] = _fk("trabajos_especiales")
    tenant_id: Mapped[uuid.UUID] = _fk("tenants")
    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    estado_anterior: Mapped[str | None] = mapped_column(String(40))
    estado_nuevo: Mapped[str] = mapped_column(String(40))
    actor_id: Mapped[uuid.UUID | None] = _fk("usuarios", True)
    actor_rol: Mapped[str] = mapped_column(String(40), default="sistema")
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    notas: Mapped[str] = mapped_column(Text, default="")
    datos_json: Mapped[dict] = mapped_column(JSONB, default=dict)


class FolioActivoAutorizacion(ConVersion, Base):
    """§6.10.7: trámite de OC en el ERP del cliente por folio de instalación de activo (uno por folio)."""
    __tablename__ = "folio_activo_autorizacion"

    folio_id: Mapped[uuid.UUID] = _fk("folios")
    tenant_id: Mapped[uuid.UUID] = _fk("tenants")
    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    un_id: Mapped[uuid.UUID] = _fk("unidades_negocio")
    estatus_multinivel: Mapped[EstatusOCActivo] = mapped_column(pg_enum(EstatusOCActivo, "estatus_oc_activo"), default=EstatusOCActivo.pendiente_iniciar_tramite)
    estatus_desde: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    numero_oc_provisional: Mapped[str | None] = mapped_column(String(60))
    numero_oc_definitivo: Mapped[str | None] = mapped_column(String(60))
    fecha_autorizacion_erp: Mapped[date | None] = mapped_column(Date)
    registrado_por: Mapped[uuid.UUID | None] = _fk("usuarios", True)
    notas: Mapped[str] = mapped_column(Text, default="")
    decision_rechazo: Mapped[DecisionOCRechazo | None] = mapped_column(pg_enum(DecisionOCRechazo, "decision_oc_rechazo"), nullable=True)
    periodo_presupuestal_destino: Mapped[str | None] = mapped_column(String(40))
    origen: Mapped[str] = mapped_column(String(30), default="captura")
    respuesta_id: Mapped[uuid.UUID | None] = _fk("formulario_respuestas", True)
    datos_equipo_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    hallazgo_presupuesto_id: Mapped[uuid.UUID | None] = _fk("hallazgos_presupuesto", True)


class FolioActivoHistorial(Base):
    __tablename__ = "folio_activo_historial"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    folio_id: Mapped[uuid.UUID] = _fk("folios")
    tenant_id: Mapped[uuid.UUID] = _fk("tenants")
    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    estatus_anterior: Mapped[str | None] = mapped_column(String(40))
    estatus_nuevo: Mapped[str] = mapped_column(String(40))
    actor_id: Mapped[uuid.UUID | None] = _fk("usuarios", True)
    actor_rol: Mapped[str] = mapped_column(String(40), default="sistema")
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    notas: Mapped[str] = mapped_column(Text, default="")
