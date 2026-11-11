"""Esquemas de sincronización offline (§6.2), chat (§6.8.1), cierre en campo y push (P05)."""
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from models.base import Rol
from models.chat import CanalChat, EstadoChat, ReglaConflicto, TipoMensaje
from schemas.comun import Modelo

TipoMutacion = Literal["crear_folio", "transicion", "guardar_respuesta", "enviar_respuesta", "subir_evidencia",
                       "agregar_refaccion", "mensaje_chat", "registrar_lectura"]


class Mutacion(BaseModel):
    id_cliente: UUID = Field(description="UUID generado en el dispositivo; idempotencia")
    tipo: TipoMutacion
    timestamp_dispositivo: datetime | None = Field(default=None, description="Hora real del evento en el dispositivo")
    payload: dict[str, Any] = Field(default_factory=dict)


class LoteMutaciones(BaseModel):
    dispositivo_id: str | None = Field(default=None, max_length=120)
    version_app: str | None = Field(default=None, max_length=40)
    plataforma: str | None = Field(default=None, max_length=60)
    mutaciones: list[Mutacion] = Field(max_length=500)


class ResultadoMutacionSalida(BaseModel):
    id_cliente: UUID
    tipo: str
    resultado: Literal["aplicada", "duplicada", "rechazada"]
    entidad_id: UUID | None = None
    codigo: str | None = None
    mensaje: str = ""


class IniciarEvidenciaEntrada(BaseModel):
    id_cliente: UUID
    respuesta_id: str = Field(description="Id del servidor o id_cliente de la respuesta creada offline")
    campo_clave: str
    nombre: str = Field(default="evidencia", max_length=255)
    mime: str = Field(default="image/jpeg", max_length=120)
    bytes: int = Field(ge=1)
    hash_sha256: str = Field(min_length=64, max_length=64)


class IniciarEvidenciaSalida(BaseModel):
    estado: Literal["pendiente", "existente", "duplicada"]
    evidencia_id: UUID | None = None
    subir_a: str | None = None


class ConflictoSalida(Modelo):
    id: UUID
    usuario_id: UUID
    dispositivo_id: str | None
    entidad: str
    entidad_id: UUID | None
    regla_aplicada: ReglaConflicto
    datos_cliente_json: dict[str, Any]
    datos_servidor_json: dict[str, Any]
    resuelto_at: datetime | None
    created_at: datetime


# ------------------------------------------------------------------- chat

class ParticipanteSalida(BaseModel):
    usuario_id: UUID
    nombre: str
    rol: Rol
    fijo: bool


class ChatSalida(BaseModel):
    id: UUID
    folio_id: UUID
    canal: CanalChat
    estado: EstadoChat
    es_participante: bool
    puede_gestionar: bool
    no_leidos: int
    participantes: list[ParticipanteSalida]


class ArchivoChatSalida(BaseModel):
    id: str
    archivo_key: str
    nombre_original: str
    tipo_mime: str
    tamano_bytes: int


class MensajeSalida(BaseModel):
    id: str
    chat_id: str
    usuario_id: str | None
    usuario_nombre: str | None
    contenido_texto: str
    tipo: TipoMensaje
    timestamp_servidor: str
    timestamp_dispositivo: str | None
    leido_por_json: dict[str, Any]
    datos_json: dict[str, Any]
    id_cliente: str
    archivos: list[ArchivoChatSalida] = Field(default_factory=list)
    duplicado: bool = False


class MensajeEntrada(BaseModel):
    id_cliente: UUID
    contenido_texto: str = Field(default="", max_length=4000)
    tipo: TipoMensaje = TipoMensaje.texto
    timestamp_dispositivo: datetime | None = None
    datos: dict[str, Any] = Field(default_factory=dict)


class LeidoEntrada(BaseModel):
    hasta: datetime | None = None


class ParticipanteEntrada(BaseModel):
    usuario_id: UUID


# ------------------------------------------------------------- cierre y push

class EncuestaEntrada(BaseModel):
    nps_score: int = Field(ge=0, le=10)
    comentario: str = Field(default="", max_length=2000)
    respuestas: dict[str, Any] = Field(default_factory=dict, description="Respuestas del formulario de encuesta resuelto (opcional)")
    timestamp_dispositivo: datetime | None = None


class EncuestaSalida(BaseModel):
    folio_id: UUID
    operador_id: UUID
    nps_score: int
    respuesta_id: UUID | None
    timestamp: datetime


class SuscripcionPushEntrada(BaseModel):
    endpoint: str = Field(min_length=10, max_length=2000)
    keys: dict[str, str] = Field(default_factory=dict, description="p256dh y auth del PushSubscription")
    dispositivo_id: str | None = Field(default=None, max_length=120)


class ClavePublicaSalida(BaseModel):
    clave_publica: str | None
    habilitado: bool
