"""Esquemas de mensajería por WhatsApp y SMS (§6.1, §7.5). F2-02."""
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from models.mensajeria import CanalMensajeria, CategoriaPlantilla, EstadoAprobacionPlantilla, EstadoEnvioMensajeria
from schemas.comun import Modelo


# ------------------------------------------------------------------ configuración
class HorarioSilencio(BaseModel):
    inicio: str = Field(default="22:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    fin: str = Field(default="07:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    zona: str = Field(default="America/Mexico_City", max_length=60)


class ConfiguracionEntrada(BaseModel):
    tenant_id: UUID | None = None
    whatsapp_activo: bool | None = None
    sms_activo: bool | None = None
    eventos_whatsapp: list[str] | None = None
    eventos_sms: list[str] | None = None
    horario_silencio: HorarioSilencio | None = None
    tope_mensual_mensajes: int | None = Field(default=None, ge=0, le=1_000_000)
    alerta_consumo_pct: int | None = Field(default=None, ge=50, le=100)
    remitente_whatsapp: str | None = Field(default=None, max_length=60)
    remitente_sms: str | None = Field(default=None, max_length=30)
    tarifa_whatsapp: Decimal | None = Field(default=None, ge=0, le=100)
    tarifa_sms: Decimal | None = Field(default=None, ge=0, le=100)
    moneda: str | None = Field(default=None, min_length=3, max_length=3)
    ventana_respuesta_horas: int | None = Field(default=None, ge=1, le=24)


class ConfiguracionSalida(Modelo):
    id: UUID
    prestador_id: UUID
    tenant_id: UUID | None
    whatsapp_activo: bool
    sms_activo: bool
    eventos_whatsapp_json: list[str] = Field(serialization_alias="eventos_whatsapp")
    eventos_sms_json: list[str] = Field(serialization_alias="eventos_sms")
    horario_silencio_json: dict[str, Any] = Field(serialization_alias="horario_silencio")
    tope_mensual_mensajes: int
    alerta_consumo_pct: int
    remitente_whatsapp: str
    remitente_sms: str
    tarifa_whatsapp: Decimal
    tarifa_sms: Decimal
    moneda: str
    ventana_respuesta_horas: int

    model_config = {"from_attributes": True, "populate_by_name": True, "serialize_by_alias": True}


class ConsumoSalida(BaseModel):
    mes: str
    mensajes: int
    tope: int
    porcentaje: float
    costo_estimado: Decimal
    moneda: str
    alerta_pct: int
    por_canal: dict[str, dict[str, Any]]


# ------------------------------------------------------------------ plantillas
class PlantillaSalida(BaseModel):
    id: UUID
    clave: str
    nombre: str = ""
    evento: str = ""
    canal: CanalMensajeria
    idioma: str
    nombre_proveedor: str
    categoria: CategoriaPlantilla
    cuerpo: str
    encabezado: str = ""
    pie: str = ""
    botones: list[dict[str, Any]] = Field(default_factory=list)
    variables: list[str] = Field(default_factory=list)
    estado_aprobacion: EstadoAprobacionPlantilla
    motivo_rechazo: str = ""
    version: int
    activa: bool
    prestador_id: UUID | None = None
    es_global: bool = False


class PlantillaCambios(BaseModel):
    cuerpo: str | None = Field(default=None, min_length=5, max_length=1024)
    encabezado: str | None = Field(default=None, max_length=120)
    pie: str | None = Field(default=None, max_length=120)
    nombre_proveedor: str | None = Field(default=None, max_length=120)
    estado_aprobacion: EstadoAprobacionPlantilla | None = None
    motivo_rechazo: str | None = Field(default=None, max_length=1000)
    botones: list[dict[str, Any]] | None = None
    activa: bool | None = None


class VistaPreviaSalida(BaseModel):
    clave: str
    canal: str
    cuerpo: str
    botones: list[dict[str, Any]]
    segmentos: int
    codificacion: str
    caracteres: int
    critica: bool
    aviso: str


# ------------------------------------------------------------------ envíos
class EnvioSalida(BaseModel):
    id: UUID
    canal: CanalMensajeria
    estado: EstadoEnvioMensajeria
    evento: str
    plantilla: str
    proveedor: str
    telefono: str
    cuerpo: str
    costo_estimado: str
    moneda: str
    segmentos_sms: int
    intentos: int
    codigo_error: str
    detalle_error: str
    created_at: datetime
    enviado_at: datetime | None
    entregado_at: datetime | None
    leido_at: datetime | None
    abierto_at: datetime | None
    usuario_id: UUID | None
    critico: bool
    enlace_destino: str
    mensaje_id_proveedor: str | None = None


class PruebaEntrada(BaseModel):
    canal: CanalMensajeria = CanalMensajeria.whatsapp
    telefono: str | None = Field(default=None, max_length=25)
    clave: str = Field(default="notificacion_generica", max_length=60)


class WebhookSimuladoEntrada(BaseModel):
    """Simulación de webhook para desarrollo: en local el proveedor no alcanza a la máquina de la usuaria."""

    mensaje_id: str | None = Field(default=None, max_length=120)
    estado: str | None = Field(default=None, pattern="^(entregado|leido|fallido)$")
    canal: CanalMensajeria = CanalMensajeria.whatsapp
    telefono: str | None = Field(default=None, max_length=25)
    texto: str = Field(default="", max_length=1000)
    boton: str = Field(default="", max_length=60)


# ------------------------------------------------------------------ teléfono del usuario
class TelefonoEntrada(BaseModel):
    telefono: str = Field(min_length=8, max_length=25, examples=["+52 871 123 4567"])


class CodigoEntrada(BaseModel):
    codigo: str = Field(min_length=4, max_length=10)


class ConsentimientoEntrada(BaseModel):
    canal: CanalMensajeria
    acepta: bool


class CanalConsentimiento(BaseModel):
    consentimiento_at: datetime | None = None
    baja_at: datetime | None = None
    activo: bool = False


class TelefonoSalida(BaseModel):
    telefono_mascara: str | None = None
    tiene_telefono: bool = False
    verificado: bool = False
    verificado_at: datetime | None = None
    whatsapp: CanalConsentimiento
    sms: CanalConsentimiento
    aviso_privacidad: str = ""
