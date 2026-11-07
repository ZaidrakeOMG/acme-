"""Esquemas de planes de mantenimiento, calendario de preventivos, autorizaciones y reasignaciones (P06)."""
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from models.folios import CanalAprobacion, EstadoFolio
from models.preventivos import (
    EstadoAutorizacion, EstadoPlan, EstadoPreventivo, OrigenPreventivo, TipoAutorizacionPreventivo, TipoReasignacion, TipoTrigger,
)
from schemas.comun import ConVersionSalida, Modelo


class TriggerEntrada(BaseModel):
    tipo_trigger: TipoTrigger
    parametros_json: dict[str, Any] = Field(default_factory=dict)
    logica_combinacion: str | None = Field(default=None, max_length=10)


class TareaEntrada(BaseModel):
    orden: int | None = Field(default=None, ge=1)
    descripcion: str = Field(min_length=2, max_length=300)
    tiempo_estimado_min: int = Field(default=0, ge=0)
    habilidad_requerida_id: UUID | None = None


class MaterialEntrada(BaseModel):
    descripcion: str = Field(min_length=2, max_length=200)
    cantidad_estandar: Decimal = Field(default=Decimal("1"), gt=0, max_digits=12, decimal_places=2)
    unidad: str = Field(default="pieza", max_length=30)
    articulo_id: UUID | None = None


class PlanEntrada(BaseModel):
    nombre: str = Field(min_length=2, max_length=160)
    descripcion: str = Field(default="", max_length=4000)
    tipo_equipo_id: UUID
    tenant_id: UUID | None = None
    estado: EstadoPlan = EstadoPlan.activo
    tiempo_ventana_dias: int = Field(default=7, ge=0, le=365)
    formulario_id: UUID | None = None
    nivel_severidad_id: UUID | None = None
    triggers: list[TriggerEntrada] = Field(default_factory=list)
    tareas: list[TareaEntrada] = Field(default_factory=list)
    materiales: list[MaterialEntrada] = Field(default_factory=list)


class PlanCambios(BaseModel):
    nombre: str | None = Field(default=None, min_length=2, max_length=160)
    descripcion: str | None = Field(default=None, max_length=4000)
    tipo_equipo_id: UUID | None = None
    tenant_id: UUID | None = None
    estado: EstadoPlan | None = None
    tiempo_ventana_dias: int | None = Field(default=None, ge=0, le=365)
    formulario_id: UUID | None = None
    nivel_severidad_id: UUID | None = None
    triggers: list[TriggerEntrada] | None = None
    tareas: list[TareaEntrada] | None = None
    materiales: list[MaterialEntrada] | None = None


class TriggerSalida(Modelo):
    id: UUID
    tipo_trigger: TipoTrigger
    parametros_json: dict[str, Any]
    logica_combinacion: str | None


class TareaSalida(Modelo):
    id: UUID
    orden: int
    descripcion: str
    tiempo_estimado_min: int
    habilidad_requerida_id: UUID | None


class MaterialSalida(Modelo):
    id: UUID
    articulo_id: UUID | None
    descripcion: str
    cantidad_estandar: Decimal
    unidad: str


class EquipoPlanSalida(Modelo):
    id: UUID
    equipo_id: UUID
    tenant_id: UUID
    activo: bool
    fecha_proxima_ejecucion: date | None
    fecha_ultima_ejecucion: date | None
    fecha_alta: date


class PlanSalida(ConVersionSalida):
    prestador_id: UUID
    tenant_id: UUID | None
    tipo_equipo_id: UUID
    tipo_equipo_nombre: str | None = None
    nombre: str
    descripcion: str
    version: int
    estado: EstadoPlan
    tiempo_ventana_dias: int
    formulario_id: UUID | None
    formulario_nombre: str | None = None
    nivel_severidad_id: UUID | None
    created_by: UUID | None
    triggers: list[TriggerSalida] = Field(default_factory=list)
    tareas: list[TareaSalida] = Field(default_factory=list)
    materiales: list[MaterialSalida] = Field(default_factory=list)
    equipos: list[EquipoPlanSalida] = Field(default_factory=list)


class AsignarEquipoEntrada(BaseModel):
    equipo_id: UUID
    fecha_base: date | None = Field(default=None, description="Fecha de alta/última ejecución desde la que se calcula la próxima; hoy por defecto")


# ------------------------------------------------------------ calendario

class CalendarioFilaEntrada(BaseModel):
    un_id: UUID
    equipo_id: UUID | None = None
    plan_id: UUID | None = None
    tecnico_id: UUID | None = None
    fecha_programada: date
    descripcion: str = Field(default="", max_length=1000)


class CalendarioEntrada(BaseModel):
    tenant_id: UUID | None = Field(default=None, description="Cliente al que pertenece el calendario (el prestador lo indica)")
    filas: list[CalendarioFilaEntrada] = Field(min_length=1, max_length=500)


class CalendarioCambios(BaseModel):
    tecnico_id: UUID | None = None
    equipo_id: UUID | None = None
    descripcion: str | None = Field(default=None, max_length=1000)
    fecha_programada: date | None = None


class CalendarioSalida(ConVersionSalida):
    prestador_id: UUID
    tenant_id: UUID
    un_id: UUID
    un_codigo: str | None
    un_nombre: str | None
    equipo_id: UUID | None
    equipo_codigo: str | None
    equipo_nombre: str | None
    plan_id: UUID | None
    plan_nombre: str | None
    tecnico_id: UUID | None
    tecnico_nombre: str | None
    fecha_programada: date
    fecha_programada_original: date | None
    fecha_real: date | None
    desvio_dias: int | None
    texto_desvio: str
    estado: EstadoPreventivo
    folio_id: UUID | None
    numero_folio: str | None
    estado_folio: EstadoFolio | None
    formulario_id: UUID | None
    origen: OrigenPreventivo
    descripcion: str
    cargado_por: UUID | None
    reprogramado_desde_id: UUID | None


class PublicacionSalida(Modelo):
    id: UUID
    prestador_id: UUID
    tenant_id: UUID
    mes: date
    publicado_por: UUID | None
    publicado_at: datetime
    total_preventivos: int


# --------------------------------------------------------- autorizaciones

class SolicitudEntrada(BaseModel):
    razon: str = Field(min_length=5, max_length=2000)
    fecha_nueva: date | None = None


class ResolverEntrada(BaseModel):
    notas: str = Field(default="", max_length=2000)
    canal: CanalAprobacion = CanalAprobacion.app

    @field_validator("canal")
    @classmethod
    def _humano(cls, v: CanalAprobacion) -> CanalAprobacion:
        if v == CanalAprobacion.sistema:
            raise ValueError("El canal sistema es solo para decisiones automáticas")
        return v


class AutorizacionSalida(BaseModel):
    id: UUID
    folio_id: UUID
    tenant_id: UUID
    prestador_id: UUID
    calendario_id: UUID | None
    tipo: TipoAutorizacionPreventivo
    solicitado_por: UUID
    solicitado_por_nombre: str | None
    autorizado_por: UUID | None
    autorizado_por_nombre: str | None
    fecha_solicitud: datetime
    fecha_autorizacion: datetime | None
    razon: str
    fecha_nueva: date | None
    estado: EstadoAutorizacion
    canal: CanalAprobacion
    notas_respuesta: str
    numero_folio: str | None
    estado_folio: EstadoFolio | None
    fecha_programada: date | None
    puede_resolver: bool = False


class TareasMaterialesSalida(BaseModel):
    tareas: list[TareaSalida]
    materiales: list[MaterialSalida]


# ---------------------------------------------------------- reasignación

class CandidatoSalida(BaseModel):
    usuario_id: UUID
    tecnico_id: UUID
    nombre: str
    vehiculo_placas: str | None
    habilidad_ok: bool
    habilidad_requerida: str | None
    carga_dia: int
    refaccion_ok: bool | None
    es_actual: bool
    advertencias: list[str]
    # F2-01: «vigente», «vencida», «sin_habilidad» o «sin_requisito» para la habilidad que el folio exige.
    certificacion: str = "sin_requisito"
    certificacion_vence: date | None = None


class ReasignarEntrada(BaseModel):
    tecnico_destino_id: UUID
    razon_id: UUID
    comentario: str = Field(default="", max_length=2000)
    confirmar_advertencias: bool = False
    razon_sin_habilidad: str | None = Field(default=None, max_length=1000)


class ReasignacionSalida(BaseModel):
    id: UUID
    tecnico_origen_id: UUID | None
    tecnico_origen_nombre: str | None
    tecnico_destino_id: UUID
    tecnico_destino_nombre: str | None
    tipo: TipoReasignacion
    razon: str | None
    comentario: str
    despachador_id: UUID | None
    despachador_nombre: str | None
    timestamp: datetime


class RazonEntrada(BaseModel):
    descripcion: str = Field(min_length=3, max_length=160)
    detalle: str = Field(default="", max_length=1000)
    activa: bool = True
    orden_display: int = Field(default=0, ge=0)


class RazonSalida(ConVersionSalida):
    prestador_id: UUID
    descripcion: str
    detalle: str
    activa: bool
    orden_display: int


class ConteoSalida(BaseModel):
    nombre: str
    total: int
    porcentaje: float


class ReporteReasignaciones(BaseModel):
    desde: date | None
    hasta: date | None
    total: int
    por_razon: list[ConteoSalida]
    por_tecnico_origen: list[ConteoSalida]
    por_tecnico_destino: list[ConteoSalida]
    por_tipo: list[ConteoSalida]
