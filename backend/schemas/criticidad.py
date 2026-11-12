"""Esquemas de criticidad de activos y gestión de riesgo (ISO 55000, §6.9.3). F2-05."""
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from models.criticidad import EstadoMitigacion, MotivoEvaluacion, OrigenCriticidad, OrigenModoFalla, TipoMitigacion
from schemas.comun import ConVersionSalida, Modelo

Nivel = Literal["A", "B", "C", "D"]


# ------------------------------------------------------------------ configuración
class PesosEntrada(BaseModel):
    """Los cuatro pesos de §6.9.3. Tienen que sumar 100 %: lo valida el servicio y lo garantiza un CHECK."""
    operacional: int = Field(ge=0, le=100, examples=[30])
    seguridad: int = Field(ge=0, le=100, examples=[35])
    economico: int = Field(ge=0, le=100, examples=[25])
    imagen: int = Field(ge=0, le=100, examples=[10])


class ConfiguracionCambios(BaseModel):
    pesos_json: PesosEntrada | None = None
    rangos_economico_json: list[dict[str, Any]] | None = None
    escala_probabilidad_json: dict[str, Any] | None = None
    rangos_nivel_json: list[dict[str, Any]] | None = None
    meses_revision: int | None = Field(default=None, ge=1, le=60)
    implicaciones_activas_json: dict[str, Any] | None = None


class ConfiguracionSalida(ConVersionSalida):
    tenant_id: UUID
    pesos_json: dict[str, Any]
    rangos_economico_json: list[dict[str, Any]]
    escala_probabilidad_json: dict[str, Any]
    rangos_nivel_json: list[dict[str, Any]]
    meses_revision: int
    implicaciones_activas_json: dict[str, Any]
    configurado_por: UUID | None = None


# ------------------------------------------------------------------ evaluación
class DimensionesEntrada(BaseModel):
    """Las cuatro dimensiones en escala 1–5 (§6.9.3). La económica se puede traer de la propuesta automática."""
    operacional: int = Field(ge=1, le=5)
    seguridad: int = Field(ge=1, le=5)
    economico: int = Field(ge=1, le=5)
    imagen: int = Field(ge=1, le=5)


class EvaluacionEntrada(BaseModel):
    dimensiones: DimensionesEntrada
    razon: str = Field(default="", max_length=1000)
    motivo: MotivoEvaluacion = MotivoEvaluacion.evaluacion_inicial


class EvaluacionMasivaEntrada(BaseModel):
    tipo_equipo_id: UUID
    dimensiones: DimensionesEntrada
    tenant_id: UUID | None = None
    solo_sin_evaluar: bool = Field(default=True, description="false reevalúa también los que ya tenían criticidad")


class AjusteManualEntrada(BaseModel):
    nivel: Nivel
    razon: str = Field(min_length=3, max_length=1000)


class CriticidadSalida(ConVersionSalida):
    equipo_id: UUID
    tenant_id: UUID
    indice_criticidad: Decimal
    nivel: Nivel
    probabilidad: Decimal
    probabilidad_estimada: bool
    probabilidad_origen: str
    impacto_ponderado: Decimal
    dimensiones_json: dict[str, Any]
    origen: OrigenCriticidad
    razon_manual: str
    evaluado_por: UUID | None = None
    fecha_evaluacion: date
    proxima_revision: date | None = None


class EvaluacionHistorial(Modelo):
    id: UUID
    equipo_id: UUID
    indice_anterior: Decimal | None = None
    indice_nuevo: Decimal
    nivel_anterior: Nivel | None = None
    nivel_nuevo: Nivel
    probabilidad: Decimal
    impacto_ponderado: Decimal
    dimensiones_json: dict[str, Any]
    motivo: MotivoEvaluacion
    razon: str
    evaluado_por: UUID | None = None
    timestamp: datetime


class FilaRegistro(Modelo):
    """Registro de activos con criticidad: la base del reporte de certificación."""
    equipo_id: UUID
    codigo: str
    nombre: str
    tipo_equipo: str
    un_codigo: str
    un_nombre: str
    tenant_id: UUID
    nivel: Nivel
    indice_criticidad: Decimal
    probabilidad: Decimal
    probabilidad_estimada: bool
    impacto_ponderado: Decimal
    origen: str
    fecha_evaluacion: date
    proxima_revision: date | None = None
    revision_vencida: bool


class ResumenCriticidad(BaseModel):
    por_nivel: dict[str, int]
    total: int
    criticos_sin_plan: int
    criticos_sin_plan_ids: list[str]
    mitigaciones_vencidas: int
    revisiones_vencidas: int


# ------------------------------------------------------------------ modos de falla
class ModoFallaEntrada(BaseModel):
    equipo_id: UUID | None = None
    tipo_equipo_id: UUID | None = Field(default=None, description="Para un modo genérico del tipo de equipo")
    tenant_id: UUID | None = None
    descripcion_falla: str = Field(min_length=3, max_length=300)
    tipo_falla_id: UUID | None = None
    causa_probable: str = Field(default="", max_length=2000)
    efecto_operacional: str = Field(default="", max_length=2000)
    severidad: int = Field(default=3, ge=1, le=5)
    frecuencia_historica: int = Field(default=1, ge=1, le=5)
    deteccion: int | None = Field(default=None, ge=1, le=5,
                                 description="Opcional (FMEA clásico): con ella el riesgo es severidad × frecuencia × detección")
    origen: OrigenModoFalla = OrigenModoFalla.manual


class ModoFallaCambios(BaseModel):
    descripcion_falla: str | None = Field(default=None, min_length=3, max_length=300)
    tipo_falla_id: UUID | None = None
    causa_probable: str | None = Field(default=None, max_length=2000)
    efecto_operacional: str | None = Field(default=None, max_length=2000)
    severidad: int | None = Field(default=None, ge=1, le=5)
    frecuencia_historica: int | None = Field(default=None, ge=1, le=5)
    deteccion: int | None = Field(default=None, ge=1, le=5)
    activo: bool | None = None


class ModoFallaSalida(ConVersionSalida):
    tenant_id: UUID
    equipo_id: UUID | None = None
    tipo_equipo_id: UUID | None = None
    descripcion_falla: str
    tipo_falla_id: UUID | None = None
    causa_probable: str
    efecto_operacional: str
    severidad: int
    frecuencia_historica: int
    fallas_12m: int
    deteccion: int | None = None
    nivel_riesgo: int
    origen: OrigenModoFalla
    activo: bool
    registrado_por: UUID | None = None


class SugerenciaModoFalla(BaseModel):
    descripcion_falla: str
    tipo_falla_id: UUID | None = None
    causa_probable: str
    severidad: int
    frecuencia_historica: int
    fallas_12m: int
    nivel_riesgo: int
    categoria: str
    ya_registrado: bool
    nota: str


class AceptarSugerencias(BaseModel):
    equipo_id: UUID
    sugerencias: list[ModoFallaEntrada] = Field(min_length=1, max_length=50)


# ------------------------------------------------------------------ mitigaciones
class MitigacionEntrada(BaseModel):
    modo_falla_id: UUID
    accion_mitigacion: str = Field(min_length=3, max_length=2000)
    tipo: TipoMitigacion = TipoMitigacion.otro
    plan_mantenimiento_id: UUID | None = None
    curso_id: UUID | None = None
    articulo_id: UUID | None = None
    responsable_id: UUID | None = None
    fecha_compromiso: date | None = None


class EstadoMitigacionEntrada(BaseModel):
    estado: EstadoMitigacion
    fecha_implementacion: date | None = None
    razon: str = Field(default="", max_length=1000)


class MitigacionSalida(ConVersionSalida):
    modo_falla_id: UUID
    tenant_id: UUID
    accion_mitigacion: str
    tipo: TipoMitigacion
    plan_mantenimiento_id: UUID | None = None
    curso_id: UUID | None = None
    articulo_id: UUID | None = None
    responsable_id: UUID | None = None
    fecha_compromiso: date | None = None
    fecha_implementacion: date | None = None
    estado: EstadoMitigacion
    efectividad_json: dict[str, Any]
    evidencia_key: str | None = None
    razon_descarte: str


class MitigacionPendiente(Modelo):
    id: UUID
    accion_mitigacion: str
    tipo: TipoMitigacion
    estado: EstadoMitigacion
    fecha_compromiso: date | None = None
    responsable_id: UUID | None = None
    vencida: bool
    dias_vencida: int
    modo_falla_id: UUID
    modo_falla: str
    nivel_riesgo: int
    equipo_id: UUID | None = None
    equipo_codigo: str | None = None
    equipo_nombre: str | None = None
    tenant_id: UUID
