"""Mensajería por WhatsApp y SMS (§6.1): plantillas, configuración por prestador/tenant, bitácora de envíos y
mensajes entrantes. F2-02.

El número de teléfono vive cifrado en `usuarios.telefono_movil_e164`; aquí solo se guardan su hash y su máscara.
"""
import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, SmallInteger, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, ConVersion, pg_enum
from models.chat import _SinRetorno


class CanalMensajeria(str, enum.Enum):
    whatsapp = "whatsapp"
    sms = "sms"


class CategoriaPlantilla(str, enum.Enum):
    utility = "utility"
    authentication = "authentication"
    marketing = "marketing"


class EstadoAprobacionPlantilla(str, enum.Enum):
    borrador = "borrador"
    enviada = "enviada"
    aprobada = "aprobada"
    rechazada = "rechazada"
    pausada = "pausada"


class ProveedorMensajeria(str, enum.Enum):
    stub = "stub"
    meta_cloud = "meta_cloud"
    twilio = "twilio"


class EstadoEnvioMensajeria(str, enum.Enum):
    en_cola = "en_cola"
    enviado = "enviado"
    entregado = "entregado"
    leido = "leido"
    fallido = "fallido"
    rechazado_por_proveedor = "rechazado_por_proveedor"


def _fk(tabla: str, nulo: bool = False, **kw):
    return mapped_column(UUID(as_uuid=True), ForeignKey(f"{tabla}.id", **kw), nullable=nulo)


class MensajeriaPlantilla(ConVersion, Base):
    """Plantilla por evento y canal. `prestador_id` NULL = plantilla base de la plataforma (§7.5)."""
    __tablename__ = "mensajeria_plantillas"

    prestador_id: Mapped[uuid.UUID | None] = _fk("prestadores", True)
    clave: Mapped[str] = mapped_column(String(60))
    canal: Mapped[CanalMensajeria] = mapped_column(pg_enum(CanalMensajeria, "canal_mensajeria"))
    idioma: Mapped[str] = mapped_column(String(10), default="es_MX")
    nombre_proveedor: Mapped[str] = mapped_column(String(120), default="")
    categoria: Mapped[CategoriaPlantilla] = mapped_column(pg_enum(CategoriaPlantilla, "categoria_plantilla"),
                                                          default=CategoriaPlantilla.utility)
    encabezado: Mapped[str] = mapped_column(String(120), default="")
    cuerpo: Mapped[str] = mapped_column(Text)
    pie: Mapped[str] = mapped_column(String(120), default="")
    botones_json: Mapped[list] = mapped_column(JSONB, default=list)
    variables_json: Mapped[list] = mapped_column(JSONB, default=list)
    ejemplo_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    estado_aprobacion: Mapped[EstadoAprobacionPlantilla] = mapped_column(
        pg_enum(EstadoAprobacionPlantilla, "estado_aprobacion_plantilla"), default=EstadoAprobacionPlantilla.borrador)
    motivo_rechazo: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[int] = mapped_column(SmallInteger, default=1)
    activa: Mapped[bool] = mapped_column(Boolean, default=True)


class MensajeriaConfiguracion(ConVersion, Base):
    """Una fila por prestador (tenant_id NULL) y, opcionalmente, una por tenant que atiende."""
    __tablename__ = "mensajeria_configuracion"

    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    tenant_id: Mapped[uuid.UUID | None] = _fk("tenants", True)
    whatsapp_activo: Mapped[bool] = mapped_column(Boolean, default=False)
    sms_activo: Mapped[bool] = mapped_column(Boolean, default=False)
    eventos_whatsapp_json: Mapped[list] = mapped_column(JSONB, default=list)
    eventos_sms_json: Mapped[list] = mapped_column(JSONB, default=list)
    horario_silencio_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    tope_mensual_mensajes: Mapped[int] = mapped_column(Integer, default=1000)
    alerta_consumo_pct: Mapped[int] = mapped_column(SmallInteger, default=80)
    remitente_whatsapp: Mapped[str] = mapped_column(String(60), default="")
    remitente_sms: Mapped[str] = mapped_column(String(30), default="")
    tarifa_whatsapp: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=Decimal("0.4"))
    tarifa_sms: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=Decimal("0.6"))
    moneda: Mapped[str] = mapped_column(String(3), default="MXN")
    ventana_respuesta_horas: Mapped[int] = mapped_column(SmallInteger, default=24)


class MensajeriaEnvio(_SinRetorno, Base):
    """Bitácora de un mensaje: sin RETURNING, porque lo registra quien genera el evento, no el destinatario."""
    __tablename__ = "mensajeria_envios"

    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    tenant_id: Mapped[uuid.UUID | None] = _fk("tenants", True)
    usuario_id: Mapped[uuid.UUID | None] = _fk("usuarios", True)
    notificacion_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    evento: Mapped[str] = mapped_column(String(80), default="")
    canal: Mapped[CanalMensajeria] = mapped_column(pg_enum(CanalMensajeria, "canal_mensajeria"))
    proveedor: Mapped[ProveedorMensajeria] = mapped_column(pg_enum(ProveedorMensajeria, "proveedor_mensajeria"),
                                                           default=ProveedorMensajeria.stub)
    telefono_destino_hash: Mapped[str] = mapped_column(String(64))
    telefono_mascara: Mapped[str] = mapped_column(String(40), default="")
    plantilla_id: Mapped[uuid.UUID | None] = _fk("mensajeria_plantillas", True)
    plantilla_clave: Mapped[str] = mapped_column(String(60), default="")
    variables_json: Mapped[list] = mapped_column(JSONB, default=list)
    cuerpo_renderizado: Mapped[str] = mapped_column(Text, default="")
    mensaje_id_proveedor: Mapped[str | None] = mapped_column(String(120))
    estado: Mapped[EstadoEnvioMensajeria] = mapped_column(pg_enum(EstadoEnvioMensajeria, "estado_envio_mensajeria"),
                                                          default=EstadoEnvioMensajeria.en_cola)
    codigo_error: Mapped[str] = mapped_column(String(60), default="")
    detalle_error: Mapped[str] = mapped_column(Text, default="")
    costo_estimado: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=Decimal("0"))
    moneda: Mapped[str] = mapped_column(String(3), default="MXN")
    segmentos_sms: Mapped[int] = mapped_column(SmallInteger, default=0)
    intentos: Mapped[int] = mapped_column(SmallInteger, default=0)
    proximo_intento_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    critico: Mapped[bool] = mapped_column(Boolean, default=False)
    codigo_enlace: Mapped[str | None] = mapped_column(String(16))
    enlace_destino: Mapped[str] = mapped_column(String(400), default="")
    abierto_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    vista_previa_key: Mapped[str | None] = mapped_column(String(300))
    enviado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    entregado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    leido_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MensajeriaRespuesta(_SinRetorno, Base):
    """Mensaje entrante del usuario: texto («BAJA», «ALTA») o botón de una respuesta rápida."""
    __tablename__ = "mensajeria_respuestas"

    prestador_id: Mapped[uuid.UUID | None] = _fk("prestadores", True)
    tenant_id: Mapped[uuid.UUID | None] = _fk("tenants", True)
    usuario_id: Mapped[uuid.UUID | None] = _fk("usuarios", True)
    canal: Mapped[CanalMensajeria] = mapped_column(pg_enum(CanalMensajeria, "canal_mensajeria"))
    proveedor: Mapped[ProveedorMensajeria] = mapped_column(pg_enum(ProveedorMensajeria, "proveedor_mensajeria"),
                                                           default=ProveedorMensajeria.stub)
    telefono_hash: Mapped[str] = mapped_column(String(64))
    telefono_mascara: Mapped[str] = mapped_column(String(40), default="")
    texto: Mapped[str] = mapped_column(Text, default="")
    boton: Mapped[str] = mapped_column(String(60), default="")
    envio_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    mensaje_id_proveedor: Mapped[str | None] = mapped_column(String(120))
    accion_ejecutada: Mapped[str] = mapped_column(String(60), default="")
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
