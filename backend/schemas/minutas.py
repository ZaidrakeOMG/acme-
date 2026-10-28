"""Esquemas de hallazgos, minuta, notificaciones, módulos de seguimiento y clasificación (P07)."""
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from models.folios import EstadoFolio, ModuloDestino
from models.minutas import (
    CanalNotificacion, EstadoMinuta, EstadoNotificacion, EstadoRespuestaHallazgo, ModoMinuta, NivelUrgencia, OpcionRespuesta, OrigenHallazgo, OrigenPeticion, TipoHallazgo,
    TipoMinuta,
)
from models.seguimiento import (
    EstadoCotizacion, EstadoPresupuesto, EstadoReprogramacion, EstadoSeguimientoInterno, OpcionClasificacion, TipoPeriodoPresupuestal, VarianteCoordinado,
)
from schemas.comun import ConVersionSalida, Modelo
from schemas.folios import FolioResumen


# ------------------------------------------------------------- hallazgos

class HallazgoEntrada(BaseModel):
    un_id: UUID | None = None
    folio_id: UUID | None = None
    equipo_id: UUID | None = None
    descripcion: str = Field(min_length=5, max_length=4000)
    nivel_urgencia: NivelUrgencia = NivelUrgencia.media
    tipo: TipoHallazgo | None = None


class MarcarMensajeEntrada(BaseModel):
    como: str = Field(pattern="^(hallazgo|peticion)$")
    nivel_urgencia: NivelUrgencia | None = None


class HallazgoSalida(BaseModel):
    id: UUID
    folio_id: UUID | None
    tenant_id: UUID
    prestador_id: UUID
    un_id: UUID
    equipo_id: UUID | None
    descripcion: str
    nivel_urgencia: NivelUrgencia
    foto_evidencia_id: UUID | None
    foto_url: str | None = None
    tipo: TipoHallazgo
    origen: OrigenHallazgo
    respuesta_id: UUID | None
    mensaje_id: UUID | None
    capturado_por: UUID | None
    capturado_por_nombre: str | None = None
    timestamp: datetime
    estado_respuesta: EstadoRespuestaHallazgo
    opcion_respuesta: OpcionRespuesta | None
    respondido_por: UUID | None
    respondido_por_nombre: str | None = None
    respondido_at: datetime | None
    modulo_destino: ModuloDestino | None
    modulo_registro_id: UUID | None
    equipo_codigo: str | None = None
    equipo_nombre: str | None = None
    un_codigo: str | None = None
    un_nombre: str | None = None
    numero_folio: str | None = None


class PeticionSalida(ConVersionSalida):
    folio_id: UUID | None
    tenant_id: UUID
    un_id: UUID
    texto: str
    origen: OrigenPeticion
    mensaje_id: UUID | None
    capturado_por: UUID | None
    timestamp: datetime


# ---------------------------------------------------------------- minuta

class MinutaConfiguracionEntrada(BaseModel):
    modo: ModoMinuta | None = None
    hora_envio: time | None = None
    ventana_validacion_min: int | None = Field(default=None, ge=5, le=240)
    plazo_respuesta_horas: int | None = Field(default=None, ge=1, le=168)
    dias_sin_respuesta_alerta: int | None = Field(default=None, ge=1, le=30)
    dias_cotizacion_sin_respuesta: int | None = Field(default=None, ge=1, le=90)
    dias_presupuesto_sin_revision: int | None = Field(default=None, ge=1, le=365)
    dias_interno_sin_actualizar: int | None = Field(default=None, ge=1, le=90)


class MinutaConfiguracionSalida(ConVersionSalida):
    prestador_id: UUID
    tenant_id: UUID
    modo: ModoMinuta
    hora_envio: time
    ventana_validacion_min: int
    plazo_respuesta_horas: int
    dias_sin_respuesta_alerta: int
    dias_cotizacion_sin_respuesta: int
    dias_presupuesto_sin_revision: int
    dias_interno_sin_actualizar: int


class MinutaResumen(BaseModel):
    id: UUID
    tenant_id: UUID
    tenant_nombre: str | None
    prestador_id: UUID
    un_id: UUID | None
    un_codigo: str | None
    un_nombre: str | None
    fecha: date
    tipo: TipoMinuta
    estado: EstadoMinuta
    modo: ModoMinuta
    timestamp_generacion: datetime
    timestamp_envio: datetime | None
    validada_por: UUID | None
    validada_por_nombre: str | None
    notas_despachador: str
    enviada_sin_validacion: bool
    vence_respuesta_at: datetime | None
    respondida_at: datetime | None
    hash_pdf: str | None
    urgente: bool
    hallazgos: int
    hallazgos_pendientes: int
    colores: dict[str, str | None]
    created_at: datetime
    updated_at: datetime


class RespuestaMinutaSalida(BaseModel):
    id: UUID
    hallazgo_id: UUID
    opcion_elegida: OpcionRespuesta
    usuario_id: UUID | None
    usuario_nombre: str | None
    timestamp: datetime
    notas: str
    canal: CanalNotificacion
    modulo_destino: ModuloDestino | None
    modulo_registro_id: UUID | None
    folio_generado_id: UUID | None


class DestinatarioSalida(BaseModel):
    usuario_id: UUID
    nombre: str | None
    canal: CanalNotificacion
    estado_entrega: EstadoNotificacion
    timestamp: datetime


class MinutaDetalle(MinutaResumen):
    secciones: dict[str, Any]
    hallazgos_detalle: list[HallazgoSalida]
    respuestas: list[RespuestaMinutaSalida]
    destinatarios: list[DestinatarioSalida]
    puede_validar: bool
    puede_responder: bool
    opciones: list[dict[str, str]]
    pdf_disponible: bool


class ValidarEntrada(BaseModel):
    notas: str = Field(default="", max_length=4000)


class ResponderHallazgoEntrada(BaseModel):
    opcion: OpcionRespuesta
    notas: str = Field(default="", max_length=2000)
    canal: CanalNotificacion = CanalNotificacion.app
    fecha_tentativa: date | None = None
    proveedor: str | None = Field(default=None, max_length=200)
    trabajo_coordinado: bool = False
    variante: VarianteCoordinado | None = None

    @field_validator("canal")
    @classmethod
    def _humano(cls, v: CanalNotificacion) -> CanalNotificacion:
        if v not in (CanalNotificacion.app, CanalNotificacion.email, CanalNotificacion.push):
            raise ValueError("La respuesta llega por app, email o push")
        return v


# --------------------------------------------------------- notificaciones

class NotificacionSalida(BaseModel):
    id: UUID
    evento: str
    canal: CanalNotificacion
    asunto: str
    cuerpo: str = ""
    datos: dict[str, Any] = Field(default_factory=dict)
    estado: EstadoNotificacion
    timestamp: datetime
    leida_at: datetime | None
    url: str | None


class PreferenciaEntrada(BaseModel):
    evento: str = Field(min_length=1, max_length=80)
    canales: list[CanalNotificacion]


class PreferenciaSalida(BaseModel):
    evento: str
    canales: list[str]


class MarcarLeidasEntrada(BaseModel):
    ids: list[UUID] | None = None


# --------------------------------------------------------- seguimiento

class CambioEstadoEntrada(BaseModel):
    estado: str
    notas: str = Field(default="", max_length=4000)
    proveedor: str | None = Field(default=None, max_length=200)
    fecha_acordada: date | None = None
    referencia_tercero: str | None = Field(default=None, max_length=120)
    descripcion: str | None = Field(default=None, max_length=4000)
    monto: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    detalle: dict[str, Any] | None = None
    pasar_a_presupuesto: bool | None = None
    como: str | None = Field(default=None, pattern="^(folio|cotizacion)$")


class PrepararCotizacionEntrada(BaseModel):
    descripcion: str | None = Field(default=None, max_length=4000)
    monto: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    detalle: dict[str, Any] | None = None


class ResponderCotizacionEntrada(BaseModel):
    autorizar: bool
    notas: str = Field(default="", max_length=2000)
    pasar_a_presupuesto_si_rechaza: bool | None = None


class EnvioExternoEntrada(BaseModel):
    destinatarios: list[str] = Field(min_length=1, max_length=20)
    comentario: str = Field(default="", max_length=2000)

    @field_validator("destinatarios")
    @classmethod
    def _correos(cls, v: list[str]) -> list[str]:
        limpios = [x.strip() for x in v if x and x.strip()]
        if any("@" not in x or "." not in x.split("@")[-1] for x in limpios):
            raise ValueError("Cada destinatario debe ser un correo válido")
        return limpios


class NotasEntrada(BaseModel):
    notas: str = Field(default="", max_length=4000)


class ReactivarEntrada(BaseModel):
    como: str = Field(pattern="^(folio|cotizacion)$")
    notas: str = Field(default="", max_length=2000)


class CrearRegistroEntrada(BaseModel):
    """Alta directa en un módulo (hallazgo opcional)."""
    un_id: UUID
    equipo_id: UUID | None = None
    descripcion: str = Field(min_length=5, max_length=4000)
    hallazgo_id: UUID | None = None
    folio_id: UUID | None = None
    tenant_id: UUID | None = None
    motivo: str = Field(default="", max_length=2000)
    fecha_tentativa: date | None = None
    trabajo_coordinado: bool = False
    variante: VarianteCoordinado | None = None
    proveedor: str | None = Field(default=None, max_length=200)


class HistorialModuloSalida(BaseModel):
    id: UUID
    modulo: ModuloDestino
    registro_id: UUID
    estado_anterior: str | None
    estado_nuevo: str
    usuario_id: UUID | None
    usuario_nombre: str | None = None
    actor_rol: str
    timestamp: datetime
    notas: str
    datos_json: dict[str, Any]


class RegistroBase(BaseModel):
    id: UUID
    hallazgo_id: UUID | None
    folio_id: UUID | None
    numero_folio: str | None = None
    tenant_id: UUID
    prestador_id: UUID
    un_id: UUID
    un_codigo: str | None = None
    un_nombre: str | None = None
    equipo_id: UUID | None
    equipo_codigo: str | None = None
    descripcion: str
    origen: str
    estado_desde: datetime
    dias_en_estado: int
    alertas_activas: list[str] = Field(default_factory=list)
    proxima_alerta: str | None = None
    urgencia_hallazgo: NivelUrgencia | None = None
    created_at: datetime
    updated_at: datetime


class CotizacionSalida(RegistroBase):
    numero: str
    detalle_json: dict[str, Any]
    monto: Decimal | None
    moneda: str
    estado: EstadoCotizacion
    fecha_solicitud: datetime
    fecha_preparacion: datetime | None
    fecha_envio: datetime | None
    fecha_respuesta: datetime | None
    solicitado_por: UUID | None
    preparado_por: UUID | None
    respondido_por: UUID | None
    notas_respuesta: str
    trabajo_especial_id: UUID | None
    estado_trabajo_especial: str | None = None
    pdf_disponible: bool = False
    hash_pdf: str | None
    pasar_a_presupuesto_si_rechaza: bool
    envios_externos: list[dict[str, Any]] = Field(default_factory=list)
    destinos: list[str] = Field(default_factory=list)


class PresupuestoSalida(RegistroBase):
    periodo_presupuestal: str
    estado: EstadoPresupuesto
    ultima_revision: datetime
    razon_descarte: str | None
    decidido_por: UUID | None
    decidido_at: datetime | None
    monto_estimado: Decimal | None
    reactivado_como: str | None
    reactivado_registro_id: UUID | None
    historial_revisiones_json: list[dict[str, Any]]
    destinos: list[str] = Field(default_factory=list)


class SeguimientoInternoSalida(RegistroBase):
    responsable_un: UUID | None
    estado: EstadoSeguimientoInterno
    proveedor: str | None
    fecha_acordada: date | None
    referencia_tercero: str | None
    ultima_actualizacion: datetime
    justificacion_cierre: str | None
    cerrado_por: UUID | None
    cerrado_at: datetime | None
    destinos: list[str] = Field(default_factory=list)


class ReprogramacionSalida(RegistroBase):
    estado: EstadoReprogramacion
    motivo: str
    proveedor_tercero: str | None
    fecha_acordada: date | None
    fecha_tentativa: date | None
    referencia_tercero: str | None
    trabajo_coordinado: bool
    variante: VarianteCoordinado | None
    tercero_completo: bool
    folio_coordinado_id: UUID | None
    fechas_vencidas_count: int
    escalada_empresa: bool
    fecha_resolucion: datetime | None
    justificacion_cierre: str | None
    cerrado_por: UUID | None
    destinos: list[str] = Field(default_factory=list)


class PorUNSalida(BaseModel):
    un_id: UUID
    cotizaciones: list[CotizacionSalida]
    por_presupuesto: list[PresupuestoSalida]
    seguimiento_interno: list[SeguimientoInternoSalida]
    reprogramacion: list[ReprogramacionSalida]


class ReporteEjecutivo(BaseModel):
    desde: date | None
    hasta: date | None
    tiempo_promedio_resolucion_dias: dict[str, float | None]
    totales: dict[str, int]
    tasa_conversion_cotizaciones: float
    cotizaciones: dict[str, int]
    hallazgos_recurrentes: list[dict[str, Any]]
    monto_potencial: list[dict[str, Any]]


class PeriodoEntrada(BaseModel):
    tipo: TipoPeriodoPresupuestal
    fechas: list[date] = Field(default_factory=list)


class PeriodoSalida(ConVersionSalida):
    tenant_id: UUID
    tipo: TipoPeriodoPresupuestal
    fechas_json: list[Any]
    activo: bool
    periodo_actual: str


# --------------------------------------------------------- clasificación

class ClasificacionConfigEntrada(BaseModel):
    severidades_no_criticas_json: list[str] | None = None
    plazo_horas: int | None = Field(default=None, ge=1, le=720)
    umbral_calificacion: int | None = Field(default=None, ge=0, le=100)
    admin_empresa_puede_clasificar: bool | None = None
    puntos_json: dict[str, Any] | None = None
    activa: bool | None = None


class ClasificacionConfigSalida(ConVersionSalida):
    tenant_id: UUID
    severidades_no_criticas_json: list[str]
    plazo_horas: int
    umbral_calificacion: int
    admin_empresa_puede_clasificar: bool
    puntos_json: dict[str, Any]
    activa: bool


class PendienteClasificacion(BaseModel):
    folio: FolioResumen
    pendiente_desde: datetime
    plazo_at: datetime
    horas_restantes: float
    vencido: bool
    opciones: list[dict[str, str]]


class ClasificarEntrada(BaseModel):
    opcion: OpcionClasificacion
    fecha_tentativa: date | None = None
    notas: str = Field(default="", max_length=2000)


class ClasificacionSalida(ConVersionSalida):
    folio_id: UUID
    tenant_id: UUID
    un_id: UUID
    admin_un_id: UUID
    opcion_clasificacion: OpcionClasificacion
    timestamp: datetime
    plazo_at: datetime | None
    dentro_de_plazo: bool
    horas_retraso: Decimal
    fecha_tentativa: date | None
    modulo_destino: ModuloDestino | None
    modulo_registro_id: UUID | None
    notas: str


class CalificacionSalida(BaseModel):
    id: UUID
    tenant_id: UUID
    usuario_id: UUID
    usuario_nombre: str | None
    un_id: UUID | None
    un_codigo: str | None
    periodo: str
    puntos_total: int
    folios_clasificados_tiempo: int
    folios_tardios: int
    folios_sin_clasificar: int
    minutas_respondidas: int
    minutas_tardias: int
    calificacion_final: Decimal
    eventos_json: list[dict[str, Any]]
    calculada_at: datetime
    cerrada: bool


EstadoFolio_ = EstadoFolio  # reexport para los routers
