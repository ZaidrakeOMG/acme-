"""Esquemas de optimización de rutas, reasignación automática y ETA (§6.8.2, §6.8.4). F2-06."""
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from models.rutas import DisparadorRecalculo, EstadoPlanRuta, ModoReasignacionAutomatica, ProveedorDistancias
from schemas.comun import ConVersionSalida, Modelo


# ------------------------------------------------------------------ mercados
class MercadoEntrada(BaseModel):
    codigo: str = Field(min_length=2, max_length=40)
    nombre: str = Field(min_length=2, max_length=160)
    zona_horaria: str = Field(default="America/Mexico_City", max_length=64)
    centro_lat: float | None = Field(default=None, ge=-90, le=90)
    centro_lng: float | None = Field(default=None, ge=-180, le=180)


class MercadoCambios(BaseModel):
    nombre: str | None = Field(default=None, min_length=2, max_length=160)
    zona_horaria: str | None = Field(default=None, max_length=64)
    centro_lat: float | None = Field(default=None, ge=-90, le=90)
    centro_lng: float | None = Field(default=None, ge=-180, le=180)
    activo: bool | None = None


class MercadoSalida(ConVersionSalida):
    prestador_id: UUID
    codigo: str
    nombre: str
    zona_horaria: str
    activo: bool
    unidades: int = 0


class UnidadesDelMercado(BaseModel):
    un_ids: list[UUID] = Field(min_length=1, max_length=500)


# ------------------------------------------------------------------ configuración
class PesosRutas(BaseModel):
    """Los pesos de la función objetivo (ACT-2.1). Todos en «segundos de costo equivalente»."""
    distancia: int = Field(ge=0, le=100000, examples=[1])
    sla: int = Field(ge=0, le=100000, examples=[600])
    criticidad: int = Field(ge=0, le=100000, examples=[300])
    folio_sin_asignar: int = Field(ge=0, le=1000000, examples=[5000])
    horas_extra: int = Field(ge=0, le=100000, examples=[240])
    sin_refaccion: int = Field(ge=0, le=100000, examples=[400])


class ConfiguracionRutasCambios(BaseModel):
    pesos_json: PesosRutas | None = None
    hora_inicio_jornada: time | None = None
    duracion_jornada_min: int | None = Field(default=None, ge=60, le=1440)
    tiempo_servicio_default_min: int | None = Field(default=None, ge=1, le=1440)
    factor_sinuosidad: Decimal | None = Field(default=None, ge=1, le=3)
    velocidades_json: dict[str, float] | None = None
    modo_reasignacion_automatica: ModoReasignacionAutomatica | None = None
    minutos_vigencia_propuesta: int | None = Field(default=None, ge=1, le=240)
    umbral_desvio_m: int | None = Field(default=None, ge=100, le=10000)
    umbral_desvio_min: int | None = Field(default=None, ge=1, le=120)
    corredor_desvio_m: int | None = Field(default=None, ge=100, le=50000)
    proveedor_distancias: ProveedorDistancias | None = None
    segundos_limite_calculo: int | None = Field(default=None, ge=1, le=600)
    hora_calculo_automatico: time | None = None


class ConfiguracionRutasSalida(ConVersionSalida):
    prestador_id: UUID
    mercado_id: UUID | None = None
    pesos_json: dict[str, Any]
    hora_inicio_jornada: time
    duracion_jornada_min: int
    tiempo_servicio_default_min: int
    factor_sinuosidad: Decimal
    velocidades_json: dict[str, Any]
    modo_reasignacion_automatica: ModoReasignacionAutomatica
    minutos_vigencia_propuesta: int
    umbral_desvio_m: int
    umbral_desvio_min: int
    corredor_desvio_m: int
    proveedor_distancias: ProveedorDistancias
    segundos_limite_calculo: int
    hora_calculo_automatico: time
    configurado_por: UUID | None = None


class TiempoServicioEntrada(BaseModel):
    tipo_folio: str = Field(pattern="^(correctivo|preventivo)$")
    tipo_equipo_id: UUID | None = None
    minutos_estimados: int = Field(ge=1, le=1440)


class TiempoServicioSalida(ConVersionSalida):
    prestador_id: UUID
    tipo_folio: str
    tipo_equipo_id: UUID | None = None
    tipo_equipo: str | None = None
    minutos_estimados: int
    origen: str
    muestras: int


# ------------------------------------------------------------------ plan
class CalcularEntrada(BaseModel):
    mercado_id: UUID
    fecha: date | None = None
    prestador_id: UUID | None = None


class MoverParadaEntrada(BaseModel):
    tecnico_destino_id: UUID
    orden: int | None = Field(default=None, ge=0, le=500)


class RecalcularEntrada(BaseModel):
    disparador: DisparadorRecalculo = DisparadorRecalculo.manual
    tecnico_id: UUID | None = None
    folio_id: UUID | None = None
    motivo: str = Field(default="", max_length=500)


class RechazarPropuestaEntrada(BaseModel):
    razon: str = Field(default="", max_length=500)


class SimulacionEntrada(BaseModel):
    """«¿Qué pasa si…?» sin aplicar nada: mueve folios en memoria y devuelve el costo comparado."""
    movimientos: list[dict[str, Any]] = Field(min_length=1, max_length=100,
                                              description="[{folio_id, tecnico_destino_id}]")


class ParadaSalida(Modelo):
    parada_id: str
    folio_id: str
    numero_folio: str
    orden: int
    un_codigo: str
    un_nombre: str
    tipo_folio: str
    estado_folio: str
    criticidad: str | None = None
    llegada_estimada: datetime | None = None
    fin_estimado: datetime | None = None
    minutos_desde_anterior: int
    km_desde_anterior: float
    minutos_servicio: int
    ventana_ok: bool
    sla_ok: bool
    holgura_sla_min: int | None = None
    fijo: bool


class RutaSalida(Modelo):
    tecnico_id: str
    tecnico: str
    paradas: list[ParadaSalida]
    km: float
    minutos: int


class PlanResumen(Modelo):
    id: str
    mercado_id: str
    fecha: date
    estado: str
    version: int
    distancia_total_km: float
    folios_asignados: int
    folios_sin_asignar: int
    sin_asignar: list[dict[str, Any]]
    tiempo_calculo_ms: int
    motor: str
    costo_objetivo: float
    publicado_at: datetime | None = None


class PlanDetalle(BaseModel):
    plan: PlanResumen
    rutas: list[RutaSalida]


class PropuestaSalida(Modelo):
    id: str
    plan_id: str
    disparador: str
    motivo: str
    movimientos: list[dict[str, Any]]
    tecnicos_afectados: list[str]
    vence_at: datetime | None = None
    timestamp: datetime
    tiempo_calculo_ms: int
    sin_asignar: list[Any] = Field(default_factory=list)


class TrazoSalida(BaseModel):
    tecnico_id: str
    tecnico: str
    proveedor: str
    puntos: list[list[float]] = Field(description="[[lat, lng], ...] para dibujar la ruta en el mapa")


# ------------------------------------------------------------------ ETA e incidencias
class EtaSalida(BaseModel):
    tiene_eta: bool
    tecnico: str | None = None
    llegada_estimada: datetime | None = None
    orden: int | None = None
    en_camino: bool | None = None
    minutos_restantes: int | None = None
    motivo: str | None = None


class IncidenciaEntrada(BaseModel):
    """Lo que el técnico reporta desde su app cuando no puede seguir (§6.8.2, disparador de recálculo)."""
    tipo: str = Field(pattern="^(vehiculo|salud|otro)$")
    detalle: str = Field(default="", max_length=1000)
    folio_id: UUID | None = None


class IncidenciaSalida(BaseModel):
    registrada: bool
    recalculo_id: str | None = None
    movimientos: int = 0
    mensaje: str
