"""Hallazgos y peticiones del cliente, minuta del día (§7.1–7.5) y notificaciones multicanal (§6.1). P07."""
import enum
import uuid
from datetime import date, datetime, time

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, Time, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, ConVersion, pg_enum
from models.chat import _SinRetorno
from models.folios import ModuloDestino


class NivelUrgencia(str, enum.Enum):
    baja = "baja"
    media = "media"
    alta = "alta"
    critica = "critica"


class TipoHallazgo(str, enum.Enum):
    preventivo = "preventivo"
    correctivo = "correctivo"


class OrigenHallazgo(str, enum.Enum):
    formulario_atencion = "formulario_atencion"
    chat = "chat"
    manual = "manual"


class EstadoRespuestaHallazgo(str, enum.Enum):
    pendiente = "pendiente"
    respondido = "respondido"


class OpcionRespuesta(str, enum.Enum):
    """§7.4: las seis opciones del Admin UN."""
    enterado = "enterado"
    cotizacion = "cotizacion"
    autorizar_reparar = "autorizar_reparar"
    por_presupuesto = "por_presupuesto"
    seguimiento_interno = "seguimiento_interno"
    reprogramacion = "reprogramacion"


class OrigenPeticion(str, enum.Enum):
    chat = "chat"
    formulario = "formulario"


class TipoMinuta(str, enum.Enum):
    un = "un"
    global_ = "global"


class EstadoMinuta(str, enum.Enum):
    borrador = "borrador"
    pendiente_validacion = "pendiente_validacion"
    enviada = "enviada"
    respondida = "respondida"
    vencida = "vencida"


class ModoMinuta(str, enum.Enum):
    automatica = "automatica"
    con_validacion = "con_validacion"


class CanalNotificacion(str, enum.Enum):
    push = "push"
    email = "email"
    whatsapp = "whatsapp"
    sms = "sms"
    app = "app"


class EstadoNotificacion(str, enum.Enum):
    pendiente = "pendiente"
    enviada = "enviada"
    fallida = "fallida"
    omitida = "omitida"


def _fk(tabla: str, nulo: bool = False, **kw):
    return mapped_column(UUID(as_uuid=True), ForeignKey(f"{tabla}.id", **kw), nullable=nulo)


class Hallazgo(ConVersion, Base):
    __tablename__ = "hallazgos"

    folio_id: Mapped[uuid.UUID | None] = _fk("folios", True)
    tenant_id: Mapped[uuid.UUID] = _fk("tenants")
    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    un_id: Mapped[uuid.UUID] = _fk("unidades_negocio")
    equipo_id: Mapped[uuid.UUID | None] = _fk("equipos", True)
    descripcion: Mapped[str] = mapped_column(Text)
    nivel_urgencia: Mapped[NivelUrgencia] = mapped_column(pg_enum(NivelUrgencia, "nivel_urgencia"), default=NivelUrgencia.media)
    foto_evidencia_id: Mapped[uuid.UUID | None] = _fk("formulario_evidencias", True, ondelete="SET NULL")
    tipo: Mapped[TipoHallazgo] = mapped_column(pg_enum(TipoHallazgo, "tipo_hallazgo"), default=TipoHallazgo.correctivo)
    origen: Mapped[OrigenHallazgo] = mapped_column(pg_enum(OrigenHallazgo, "origen_hallazgo"), default=OrigenHallazgo.manual)
    respuesta_id: Mapped[uuid.UUID | None] = _fk("formulario_respuestas", True, ondelete="SET NULL")
    mensaje_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    capturado_por: Mapped[uuid.UUID | None] = _fk("usuarios", True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    estado_respuesta: Mapped[EstadoRespuestaHallazgo] = mapped_column(pg_enum(EstadoRespuestaHallazgo, "estado_respuesta_hallazgo"),
                                                                      default=EstadoRespuestaHallazgo.pendiente)
    opcion_respuesta: Mapped[OpcionRespuesta | None] = mapped_column(pg_enum(OpcionRespuesta, "opcion_respuesta_minuta"), nullable=True)
    respondido_por: Mapped[uuid.UUID | None] = _fk("usuarios", True)
    respondido_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    modulo_destino: Mapped[ModuloDestino | None] = mapped_column(pg_enum(ModuloDestino, "modulo_destino"), nullable=True)
    modulo_registro_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class PeticionCliente(ConVersion, Base):
    __tablename__ = "peticiones_cliente"

    folio_id: Mapped[uuid.UUID | None] = _fk("folios", True)
    tenant_id: Mapped[uuid.UUID] = _fk("tenants")
    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    un_id: Mapped[uuid.UUID] = _fk("unidades_negocio")
    texto: Mapped[str] = mapped_column(Text)
    origen: Mapped[OrigenPeticion] = mapped_column(pg_enum(OrigenPeticion, "origen_peticion"), default=OrigenPeticion.chat)
    mensaje_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    capturado_por: Mapped[uuid.UUID | None] = _fk("usuarios", True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MinutaConfiguracion(ConVersion, Base):
    __tablename__ = "minuta_configuracion"

    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    tenant_id: Mapped[uuid.UUID] = _fk("tenants")
    modo: Mapped[ModoMinuta] = mapped_column(pg_enum(ModoMinuta, "modo_minuta"), default=ModoMinuta.automatica)
    hora_envio: Mapped[time] = mapped_column(Time, default=time(19, 0))
    ventana_validacion_min: Mapped[int] = mapped_column(Integer, default=30)
    plazo_respuesta_horas: Mapped[int] = mapped_column(Integer, default=24)
    dias_sin_respuesta_alerta: Mapped[int] = mapped_column(Integer, default=2)
    dias_cotizacion_sin_respuesta: Mapped[int] = mapped_column(Integer, default=7)
    dias_presupuesto_sin_revision: Mapped[int] = mapped_column(Integer, default=30)
    dias_interno_sin_actualizar: Mapped[int] = mapped_column(Integer, default=15)


class Minuta(ConVersion, Base):
    __tablename__ = "minutas"

    tenant_id: Mapped[uuid.UUID] = _fk("tenants")
    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    un_id: Mapped[uuid.UUID | None] = _fk("unidades_negocio", True)
    fecha: Mapped[date] = mapped_column(Date)
    tipo: Mapped[TipoMinuta] = mapped_column(pg_enum(TipoMinuta, "tipo_minuta"))
    estado: Mapped[EstadoMinuta] = mapped_column(pg_enum(EstadoMinuta, "estado_minuta"), default=EstadoMinuta.borrador)
    modo: Mapped[ModoMinuta] = mapped_column(pg_enum(ModoMinuta, "modo_minuta"), default=ModoMinuta.automatica)
    timestamp_generacion: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    timestamp_envio: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    validada_por: Mapped[uuid.UUID | None] = _fk("usuarios", True)
    notas_despachador: Mapped[str] = mapped_column(Text, default="")
    enviada_sin_validacion: Mapped[bool] = mapped_column(Boolean, default=False)
    vence_respuesta_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    respondida_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pdf_key: Mapped[str | None] = mapped_column(String(300))
    hash_pdf: Mapped[str | None] = mapped_column(String(64))
    urgente: Mapped[bool] = mapped_column(Boolean, default=False)


class MinutaSeccion(ConVersion, Base):
    __tablename__ = "minutas_secciones"

    minuta_id: Mapped[uuid.UUID] = _fk("minutas", ondelete="CASCADE")
    tenant_id: Mapped[uuid.UUID] = _fk("tenants")
    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    seccion: Mapped[str] = mapped_column(String(40))
    orden: Mapped[int] = mapped_column(Integer, default=0)
    contenido_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    editado_por: Mapped[uuid.UUID | None] = _fk("usuarios", True)


class MinutaRespuesta(ConVersion, Base):
    __tablename__ = "minutas_respuestas"

    minuta_id: Mapped[uuid.UUID] = _fk("minutas")
    tenant_id: Mapped[uuid.UUID] = _fk("tenants")
    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    hallazgo_id: Mapped[uuid.UUID] = _fk("hallazgos")
    opcion_elegida: Mapped[OpcionRespuesta] = mapped_column(pg_enum(OpcionRespuesta, "opcion_respuesta_minuta"))
    usuario_id: Mapped[uuid.UUID | None] = _fk("usuarios", True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    notas: Mapped[str] = mapped_column(Text, default="")
    canal: Mapped[CanalNotificacion] = mapped_column(pg_enum(CanalNotificacion, "canal_notificacion"), default=CanalNotificacion.app)
    modulo_destino: Mapped[ModuloDestino | None] = mapped_column(pg_enum(ModuloDestino, "modulo_destino"), nullable=True)
    modulo_registro_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    folio_generado_id: Mapped[uuid.UUID | None] = _fk("folios", True)


class MinutaDestinatario(ConVersion, Base):
    __tablename__ = "minutas_destinatarios"

    minuta_id: Mapped[uuid.UUID] = _fk("minutas", ondelete="CASCADE")
    tenant_id: Mapped[uuid.UUID] = _fk("tenants")
    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    usuario_id: Mapped[uuid.UUID] = _fk("usuarios")
    canal: Mapped[CanalNotificacion] = mapped_column(pg_enum(CanalNotificacion, "canal_notificacion"))
    estado_entrega: Mapped[EstadoNotificacion] = mapped_column(pg_enum(EstadoNotificacion, "estado_notificacion"), default=EstadoNotificacion.pendiente)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    notificacion_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class Notificacion(_SinRetorno, Base):
    """Bandeja y bitácora de envío. Sin RETURNING: quien la crea (sistema o un actor del evento) no es el destinatario."""
    __tablename__ = "notificaciones"

    usuario_id: Mapped[uuid.UUID] = _fk("usuarios")
    tenant_id: Mapped[uuid.UUID | None] = _fk("tenants", True)
    prestador_id: Mapped[uuid.UUID | None] = _fk("prestadores", True)
    evento: Mapped[str] = mapped_column(String(80))
    canal: Mapped[CanalNotificacion] = mapped_column(pg_enum(CanalNotificacion, "canal_notificacion"))
    asunto: Mapped[str] = mapped_column(String(300))
    cuerpo_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    estado: Mapped[EstadoNotificacion] = mapped_column(pg_enum(EstadoNotificacion, "estado_notificacion"), default=EstadoNotificacion.pendiente)
    proveedor_respuesta: Mapped[str] = mapped_column(Text, default="")
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(__import__("datetime").UTC))
    enviada_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    leida_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    url: Mapped[str | None] = mapped_column(String(300))


class NotificacionPreferencia(ConVersion, Base):
    __tablename__ = "notificacion_preferencias"

    usuario_id: Mapped[uuid.UUID] = _fk("usuarios")
    tenant_id: Mapped[uuid.UUID | None] = _fk("tenants", True)
    prestador_id: Mapped[uuid.UUID | None] = _fk("prestadores", True)
    evento: Mapped[str] = mapped_column(String(80))
    canales_json: Mapped[list] = mapped_column(JSONB, default=lambda: ["app", "push", "email"])
