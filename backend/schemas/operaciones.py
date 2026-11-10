"""Esquemas de operaciones en tiempo real (§6.8.4). F2-03."""
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from models.operaciones import EstatusOperativo, MotivoPausaJornada, RespuestaAlertaTecnico


# ------------------------------------------------------------------ jornada
class JornadaEntrada(BaseModel):
    dispositivo_id: str = Field(default="", max_length=80)
    # La primera vez hay que aceptar el aviso de registro de ubicación (§6.8.4, §6.9.5).
    acepta_aviso: bool = False


class PausaEntrada(BaseModel):
    motivo: MotivoPausaJornada = MotivoPausaJornada.otro
    nota: str = Field(default="", max_length=200)


class JornadaSalida(BaseModel):
    id: UUID
    inicio: datetime
    estado: str
    dispositivo_id: str
    posiciones: int
    pausa_desde: datetime | None = None
    pausa_motivo: str | None = None


class MiJornadaSalida(BaseModel):
    tecnico_id: UUID
    estatus: EstatusOperativo
    jornada: JornadaSalida | None
    aviso_aceptado: bool
    frecuencias: dict[str, int]
    geocerca_radio_m: int
    jornada_cierre_horas: float
    sin_senal_min: int
    tiempo_muerto_min: int
    aviso_geolocalizacion: str
    max_lote: int
    precision_maxima_m: int
    horas_recorrido: float
    desvio_ruta: str


# ------------------------------------------------------------------ posiciones
class PosicionEntrada(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    capturada_at: datetime
    precision_m: Decimal | None = Field(default=None, ge=0, le=100000)
    velocidad_mps: Decimal | None = Field(default=None, ge=0, le=500)
    rumbo: Decimal | None = Field(default=None, ge=0, le=360)
    bateria_pct: int | None = Field(default=None, ge=0, le=100)
    # La app marca así lo que guardó sin señal y manda al reconectar (§6.8.4).
    tardia: bool = False


class LotePosiciones(BaseModel):
    posiciones: list[PosicionEntrada] = Field(min_length=1, max_length=60)


class SugerenciaLlegada(BaseModel):
    folio_id: UUID
    numero_folio: str
    distancia_m: float
    radio_m: int
    sucursal: str
    mensaje: str


class PosicionesSalida(BaseModel):
    aceptadas: int
    descartadas: list[dict[str, Any]]
    jornada_id: UUID
    estatus: EstatusOperativo
    sugerencia_llegada: SugerenciaLlegada | None = None


class PuntoRecorrido(BaseModel):
    lat: float
    lng: float
    capturada_at: datetime
    precision_m: Decimal | None = None
    velocidad_mps: Decimal | None = None
    bateria_pct: int | None = None
    tardia: bool = False


class RecorridoSalida(BaseModel):
    tecnico_id: UUID
    nombre: str
    desde: datetime
    estatus: EstatusOperativo
    puntos: list[PuntoRecorrido]


# ------------------------------------------------------------------ tablero
class TecnicoEnTablero(BaseModel):
    # `minutos_en_estatus` es el tiempo en el estatus actual (§6.8.4), no el de la jornada.
    tecnico_id: UUID
    usuario_id: UUID
    nombre: str
    numero_empleado: str | None = None
    estatus: EstatusOperativo
    estatus_texto: str
    en_jornada: bool
    jornada_desde: datetime | None = None
    minutos_en_estatus: int | None = None
    folios_pendientes: int
    lat: float | None = None
    lng: float | None = None
    ultima_posicion_at: datetime | None = None
    precision_m: Decimal | None = None
    bateria_pct: int | None = None
    vehiculo_placas: str | None = None
    telefono: str | None = None
    alerta: dict[str, Any] | None = None
    respuesta_tecnico: str | None = None


class FolioEnTablero(BaseModel):
    folio_id: UUID
    numero_folio: str
    estado: str
    tecnico_id: UUID | None = None
    tecnico: str | None = None
    un_id: UUID
    sucursal: str
    capturado_at: datetime
    sla_disponible: bool
    minutos_restantes: int | None = None
    limite_sla_min: int | None = None
    limite_respuesta_min: int | None = None
    minutos_transcurridos: int | None = None
    respondido_at: datetime | None = None
    umbral_riesgo_pct: int | None = None
    en_riesgo: bool
    incumplido: bool
    cumplimiento: bool | None = None


class UnidadEnTablero(BaseModel):
    un_id: str
    codigo: str
    nombre: str
    lat: float
    lng: float
    folios_activos: int


class AlertaEnTablero(BaseModel):
    id: UUID | None = None
    clave: str
    nombre: str = ""
    entidad_tipo: str | None = None
    entidad_id: UUID | None = None
    timestamp: datetime
    estado: str
    escalada: bool
    vista: bool
    datos: dict[str, Any] = Field(default_factory=dict)


class TableroSalida(BaseModel):
    generado_at: datetime
    tecnicos: list[TecnicoEnTablero]
    folios: list[FolioEnTablero]
    unidades: list[UnidadEnTablero]
    alertas: list[AlertaEnTablero]
    indicadores: dict[str, Any]
    parametros: dict[str, Any]
    solo_lectura: bool


# ------------------------------------------------------------------ alertas del técnico
class RespuestaAlertaEntrada(BaseModel):
    respuesta: RespuestaAlertaTecnico


class AlertaDelTecnico(BaseModel):
    id: UUID
    tipo: str
    desde: datetime
    folio_id: UUID | None = None
    pregunta: str
    datos: dict[str, Any] = Field(default_factory=dict)
