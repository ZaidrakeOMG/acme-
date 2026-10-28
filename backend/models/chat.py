"""Chat archivado por folio (§6.8.1), sincronización offline (§6.2) y suscripciones push (P05)."""
import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, ConVersion, Rol, pg_enum


class CanalChat(str, enum.Enum):
    campo = "campo"
    operativo = "operativo"
    interno = "interno"


class EstadoChat(str, enum.Enum):
    activo = "activo"
    archivado = "archivado"


class TipoMensaje(str, enum.Enum):
    texto = "texto"
    imagen = "imagen"
    audio = "audio"
    sistema = "sistema"


class ReglaConflicto(str, enum.Enum):
    server_wins = "server_wins"
    client_wins = "client_wins"
    merge_alerta = "merge_alerta"


class ResultadoMutacion(str, enum.Enum):
    aplicada = "aplicada"
    duplicada = "duplicada"
    rechazada = "rechazada"


def _fk(tabla: str, nulo: bool = False):
    return mapped_column(UUID(as_uuid=True), ForeignKey(f"{tabla}.id"), nullable=nulo)


class Chat(ConVersion, Base):
    __tablename__ = "chats"

    folio_id: Mapped[uuid.UUID] = _fk("folios")
    tenant_id: Mapped[uuid.UUID] = _fk("tenants")
    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    canal: Mapped[CanalChat] = mapped_column(pg_enum(CanalChat, "canal_chat"))
    estado: Mapped[EstadoChat] = mapped_column(pg_enum(EstadoChat, "estado_chat"), default=EstadoChat.activo)


class ChatParticipante(ConVersion, Base):
    __tablename__ = "chat_participantes"

    chat_id: Mapped[uuid.UUID] = _fk("chats")
    tenant_id: Mapped[uuid.UUID] = _fk("tenants")
    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    usuario_id: Mapped[uuid.UUID] = _fk("usuarios")
    rol: Mapped[Rol] = mapped_column(pg_enum(Rol, "rol_usuario"))
    agregado_por: Mapped[uuid.UUID | None] = _fk("usuarios", True)
    fecha_ingreso: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    activo: Mapped[bool] = mapped_column(Boolean, default=True)


class _SinRetorno:
    """INSERT sin RETURNING: la política SELECT (solo participantes) también se evalúa sobre las filas devueltas y un
    mensaje de sistema lo inserta quien ejecuta la transición aunque no participe en el chat."""
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    version_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    __mapper_args__ = {"eager_defaults": False}


class ChatMensaje(_SinRetorno, Base):
    __tablename__ = "chat_mensajes"

    chat_id: Mapped[uuid.UUID] = _fk("chats")
    tenant_id: Mapped[uuid.UUID] = _fk("tenants")
    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    usuario_id: Mapped[uuid.UUID | None] = _fk("usuarios", True)
    contenido_texto: Mapped[str] = mapped_column(Text, default="")
    tipo: Mapped[TipoMensaje] = mapped_column(pg_enum(TipoMensaje, "tipo_mensaje_chat"), default=TipoMensaje.texto)
    timestamp_servidor: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    timestamp_dispositivo: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    leido_por_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    datos_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    id_cliente: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), default=uuid.uuid4)
    oculto: Mapped[bool] = mapped_column(Boolean, default=False)


class ChatArchivo(ConVersion, Base):
    __tablename__ = "chat_archivos"

    mensaje_id: Mapped[uuid.UUID] = _fk("chat_mensajes")
    chat_id: Mapped[uuid.UUID] = _fk("chats")
    tenant_id: Mapped[uuid.UUID] = _fk("tenants")
    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    archivo_key: Mapped[str] = mapped_column(String(300))
    nombre_original: Mapped[str] = mapped_column(String(255), default="")
    tipo_mime: Mapped[str] = mapped_column(String(120))
    tamano_bytes: Mapped[int] = mapped_column(Integer)
    thumbnail_key: Mapped[str | None] = mapped_column(String(300))


class ChatEventoSistema(_SinRetorno, Base):
    __tablename__ = "chat_eventos_sistema"

    chat_id: Mapped[uuid.UUID] = _fk("chats")
    tenant_id: Mapped[uuid.UUID] = _fk("tenants")
    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    tipo_evento: Mapped[str] = mapped_column(String(60))
    datos_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class SincronizacionDispositivo(ConVersion, Base):
    __tablename__ = "sincronizacion_dispositivos"

    usuario_id: Mapped[uuid.UUID] = _fk("usuarios")
    tenant_id: Mapped[uuid.UUID | None] = _fk("tenants", True)
    prestador_id: Mapped[uuid.UUID | None] = _fk("prestadores", True)
    dispositivo_id: Mapped[str] = mapped_column(String(120))
    ultimo_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version_app: Mapped[str | None] = mapped_column(String(40))
    plataforma: Mapped[str | None] = mapped_column(String(60))


class SincronizacionConflicto(ConVersion, Base):
    __tablename__ = "sincronizacion_conflictos"

    usuario_id: Mapped[uuid.UUID] = _fk("usuarios")
    tenant_id: Mapped[uuid.UUID | None] = _fk("tenants", True)
    prestador_id: Mapped[uuid.UUID | None] = _fk("prestadores", True)
    dispositivo_id: Mapped[str | None] = mapped_column(String(120))
    entidad: Mapped[str] = mapped_column(String(60))
    entidad_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    regla_aplicada: Mapped[ReglaConflicto] = mapped_column(pg_enum(ReglaConflicto, "regla_conflicto"))
    datos_cliente_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    datos_servidor_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    resuelto_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SincronizacionMutacion(ConVersion, Base):
    """Bitácora idempotente de la cola offline: una fila por (usuario, id_cliente)."""
    __tablename__ = "sincronizacion_mutaciones"

    usuario_id: Mapped[uuid.UUID] = _fk("usuarios")
    tenant_id: Mapped[uuid.UUID | None] = _fk("tenants", True)
    prestador_id: Mapped[uuid.UUID | None] = _fk("prestadores", True)
    dispositivo_id: Mapped[str | None] = mapped_column(String(120))
    id_cliente: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    tipo: Mapped[str] = mapped_column(String(40))
    resultado: Mapped[ResultadoMutacion] = mapped_column(pg_enum(ResultadoMutacion, "resultado_mutacion"))
    entidad_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    codigo: Mapped[str | None] = mapped_column(String(60))
    mensaje: Mapped[str] = mapped_column(Text, default="")
    timestamp_dispositivo: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SuscripcionPush(ConVersion, Base):
    __tablename__ = "suscripciones_push"

    usuario_id: Mapped[uuid.UUID] = _fk("usuarios")
    tenant_id: Mapped[uuid.UUID | None] = _fk("tenants", True)
    prestador_id: Mapped[uuid.UUID | None] = _fk("prestadores", True)
    dispositivo_id: Mapped[str | None] = mapped_column(String(120))
    endpoint: Mapped[str] = mapped_column(Text)
    claves_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    user_agent: Mapped[str | None] = mapped_column(String(300))
    activa: Mapped[bool] = mapped_column(Boolean, default=True)
    ultimo_envio_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
