"""Esquemas de folios (P04): captura, transiciones, detalle (archivo §6.8.6), aprobación multinivel y configuración."""
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from models.base import Rol
from models.folios import (
    CanalAprobacion, ComportamientoTimeout, Criticidad, CriterioAprobacion, DecisionAprobacion, EstadoFlujo, EstadoFolio,
    ModuloDestino, OrigenRefaccion, RazonRechazo, SeveridadOrigen, TipoEvidenciaFolio, TipoFolio, TriggerRevision,
)
from schemas.comun import ConVersionSalida, Modelo

DIAS = ("lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo")


# ----------------------------------------------------------------- captura

class FolioEntrada(BaseModel):
    un_id: UUID
    equipo_id: UUID
    tipo_falla_id: UUID
    descripcion: str = Field(min_length=5, max_length=4000)
    tipo_folio: TipoFolio = TipoFolio.correctivo
    prioridad: int = Field(default=0, ge=0, le=9)
    confirmacion_un: bool = False
    confirmacion_un_timestamp: datetime | None = None
    confirmacion_un_geolat: float | None = Field(default=None, ge=-90, le=90)
    confirmacion_un_geolng: float | None = Field(default=None, ge=-180, le=180)
    geolat_captura: float | None = Field(default=None, ge=-90, le=90)
    geolng_captura: float | None = Field(default=None, ge=-180, le=180)
    fecha_falla: datetime | None = None
    respuesta_id: UUID | None = Field(default=None, description="Respuesta enviada del formulario de captura (P03)")
    folio_duplicado_justificacion: str | None = Field(default=None, max_length=1000)
    folio_duplicado_ref_id: UUID | None = None
    monto_estimado: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    tenant_id: UUID | None = Field(default=None, description="Solo superadmin")


class ConfirmacionUNEntrada(BaseModel):
    geolat: float | None = Field(default=None, ge=-90, le=90)
    geolng: float | None = Field(default=None, ge=-180, le=180)


class TarjetaDuplicado(BaseModel):
    """§6.8.6: tarjeta enriquecida del folio abierto existente para el mismo equipo."""
    existe: bool
    bloqueo_total: bool = False
    folio_id: UUID | None = None
    numero_folio: str | None = None
    estado: EstadoFolio | None = None
    descripcion: str | None = None
    capturado_at: datetime | None = None
    tecnico_nombre: str | None = None
    eta: datetime | None = None
    severidad: str | None = None


# ------------------------------------------------------------ transiciones

class TransicionEntrada(BaseModel):
    estado: EstadoFolio
    notas: str = Field(default="", max_length=2000)
    contexto: dict[str, Any] = Field(default_factory=dict)


class NotasEntrada(BaseModel):
    notas: str = Field(default="", max_length=2000)


class RazonEntrada(BaseModel):
    razon: str = Field(min_length=3, max_length=2000)


class AsignarEntrada(BaseModel):
    tecnico_id: UUID
    razon: str | None = Field(default=None, max_length=1000, description="Obligatoria si el técnico no tiene la habilidad")
    notas: str = Field(default="", max_length=2000)


class LlegadaEntrada(BaseModel):
    geolat: float | None = Field(default=None, ge=-90, le=90)
    geolng: float | None = Field(default=None, ge=-180, le=180)
    notas: str = Field(default="", max_length=2000)


class MontoEntrada(BaseModel):
    monto_estimado: Decimal = Field(ge=0, max_digits=14, decimal_places=2)


class SeveridadOverrideEntrada(BaseModel):
    severidad_id: UUID
    razon: str = Field(min_length=3, max_length=1000)


class AtencionEntrada(BaseModel):
    respuesta_id: UUID


class EvidenciaFolioEntrada(BaseModel):
    tipo: TipoEvidenciaFolio
    evidencia_id: UUID | None = Field(default=None, description="Evidencia de formulario (P03) a vincular")
    archivo_key: str | None = Field(default=None, max_length=300)
    geolat: float | None = None
    geolng: float | None = None

    @model_validator(mode="after")
    def _origen(self) -> "EvidenciaFolioEntrada":
        if self.evidencia_id is None and not self.archivo_key:
            raise ValueError("Indica evidencia_id o archivo_key")
        return self


class RefaccionEntrada(BaseModel):
    descripcion: str = Field(min_length=2, max_length=200)
    cantidad: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    origen: OrigenRefaccion = OrigenRefaccion.almacen
    costo_unitario: Decimal = Field(default=Decimal("0"), ge=0, max_digits=14, decimal_places=2)
    articulo_id: UUID | None = None


class TransicionTabla(BaseModel):
    origen: EstadoFolio
    destino: EstadoFolio
    roles: list[str]


# ----------------------------------------------------------------- salidas

class SeveridadResumen(BaseModel):
    id: UUID
    clave: str
    nombre: str
    orden: int
    color_hex: str


class FlujoResumen(BaseModel):
    id: UUID
    nivel_actual: int
    nivel_maximo_requerido: int
    estado: EstadoFlujo
    iniciado_at: datetime
    resuelto_at: datetime | None
    rol_aprobador_actual: Rol | None = None
    vence_at: datetime | None = None


class FolioResumen(ConVersionSalida):
    numero_folio: str
    tenant_id: UUID
    prestador_id: UUID
    un_id: UUID
    un_nombre: str | None = None
    un_codigo: str | None = None
    equipo_id: UUID
    equipo_codigo: str | None = None
    equipo_nombre: str | None = None
    tipo_falla_id: UUID | None
    tipo_falla: str | None = None
    tipo_folio: TipoFolio
    estado: EstadoFolio
    prioridad: int
    descripcion: str
    tecnico_id: UUID | None
    tecnico_nombre: str | None = None
    severidad: SeveridadResumen | None = None
    severidad_origen: SeveridadOrigen
    confirmacion_un: bool
    monto_estimado: Decimal | None
    criticidad: Criticidad | None = None
    capturado_por: UUID
    capturado_por_nombre: str | None = None
    capturado_at: datetime
    fecha_falla: datetime
    fecha_inicio_atencion: datetime | None
    fecha_cierre: datetime | None
    razon_cancelacion: str | None
    flujo: FlujoResumen | None = None
    triggers_pendientes: int = 0
    antiguedad_horas: float = 0


class HistorialSalida(BaseModel):
    id: UUID
    evento: str
    estado_anterior: EstadoFolio | None
    estado_nuevo: EstadoFolio
    actor_id: UUID | None
    actor_rol: str
    actor_nombre: str | None = None
    timestamp: datetime
    notas: str
    datos_contexto_json: dict[str, Any]


class TriggerSalida(Modelo):
    id: UUID
    trigger_tipo: TriggerRevision
    descripcion: str
    timestamp: datetime
    resuelto: bool


class DecisionSalida(BaseModel):
    id: UUID
    flujo_id: UUID
    nivel: int
    actor_id: UUID | None
    actor_nombre: str | None = None
    decision: DecisionAprobacion
    razon_rechazo: RazonRechazo | None
    modulo_destino: ModuloDestino | None
    modulo_destino_id: UUID | None
    canal: CanalAprobacion
    timestamp: datetime
    notas: str


class VinculoFormularioSalida(BaseModel):
    respuesta_id: UUID
    formulario_id: UUID
    formulario_nombre: str | None = None
    version_formulario: int
    timestamp: datetime
    respuestas_json: dict[str, Any] = Field(default_factory=dict)


class EvidenciaFolioSalida(ConVersionSalida):
    evidencia_id: UUID | None
    tipo: TipoEvidenciaFolio
    archivo_key: str
    geolat: float | None
    geolng: float | None
    timestamp_captura: datetime
    subido_por: UUID | None


class RefaccionSalida(ConVersionSalida):
    articulo_id: UUID | None
    descripcion: str
    cantidad: Decimal
    origen: OrigenRefaccion
    costo_unitario: Decimal
    gasto_caja_chica_id: UUID | None


class SLASalida(Modelo):
    nivel_severidad_id: UUID | None
    tiempo_respuesta_prometido_horas: int
    tiempo_resolucion_prometido_horas: int
    tiempo_respuesta_real_min: int | None
    tiempo_resolucion_real_min: int | None
    cumplimiento_respuesta: bool | None
    cumplimiento_resolucion: bool | None


class EncuestaSalida(Modelo):
    operador_id: UUID
    nps_score: int
    respuesta_id: UUID | None
    timestamp: datetime


class CapturaSalida(BaseModel):
    """Datos de captura del archivo del folio (§6.8.6)."""
    capturado_por: UUID
    capturado_por_nombre: str | None
    capturado_at: datetime
    un: dict[str, Any]
    equipo: dict[str, Any]
    tipo_falla: str | None
    descripcion: str
    geolat_captura: float | None
    geolng_captura: float | None
    confirmacion_un: bool
    confirmacion_un_timestamp: datetime | None
    confirmacion_un_geolat: float | None
    confirmacion_un_geolng: float | None
    folio_duplicado_justificacion: str | None
    folio_duplicado_ref_id: UUID | None
    folio_duplicado_ref_numero: str | None = None


class AsignacionSalida(BaseModel):
    tecnico_id: UUID | None
    tecnico_nombre: str | None
    asignado_at: datetime | None
    vehiculo: str | None = None
    orden_en_ruta: int | None
    ventana_inicio: datetime | None
    ventana_fin: datetime | None


class FolioDetalle(BaseModel):
    """Archivo completo del folio. Las secciones aún sin módulo (chat P05, reasignaciones P06, financiero P09)
    se devuelven vacías, no se omiten."""
    folio: FolioResumen
    captura: CapturaSalida
    formulario_captura: VinculoFormularioSalida | None
    asignacion: AsignacionSalida
    historial: list[HistorialSalida]
    reasignaciones: list[dict[str, Any]] = Field(default_factory=list)   # P06
    evidencias: list[EvidenciaFolioSalida]
    formulario_atencion: VinculoFormularioSalida | None
    refacciones: list[RefaccionSalida]
    sla: SLASalida | None
    encuesta: EncuestaSalida | None
    triggers_revision: list[TriggerSalida]
    aprobacion: FlujoResumen | None
    decisiones: list[DecisionSalida]
    chat: list[dict[str, Any]] = Field(default_factory=list)             # P05
    financiero: dict[str, Any] = Field(default_factory=dict)              # P09
    acciones: list[EstadoFolio] = Field(default_factory=list, description="Destinos válidos para el actor según §6.8.6")
    puede_aprobar: bool = False


# --------------------------------------------------------------- aprobación

class AprobarEntrada(BaseModel):
    canal: CanalAprobacion = CanalAprobacion.app
    notas: str = Field(default="", max_length=2000)

    @field_validator("canal")
    @classmethod
    def _humano(cls, v: CanalAprobacion) -> CanalAprobacion:
        if v == CanalAprobacion.sistema:
            raise ValueError("El canal sistema es solo para decisiones automáticas")
        return v


class RechazarEntrada(AprobarEntrada):
    razon_rechazo: RazonRechazo


class PendienteAprobacion(BaseModel):
    folio: FolioResumen
    flujo: FlujoResumen
    vence_at: datetime | None = None


class PoliticasEntrada(BaseModel):
    bloqueo_total_duplicados: bool | None = None
    revision_obligatoria_garantia: bool | None = None
    autorizacion_automatica_criticos: bool | None = None
    aprobacion_secuencial: bool | None = None
    prefijo_folio: str | None = Field(default=None, pattern=r"^[A-Z0-9]{1,10}$")


class PoliticasSalida(BaseModel):
    tenant_id: UUID
    bloqueo_total_duplicados: bool
    revision_obligatoria_garantia: bool
    autorizacion_automatica_criticos: bool
    aprobacion_secuencial: bool
    prefijo_folio: str
    ultimo_numero: int


class ReglaEntrada(BaseModel):
    nivel: int = Field(ge=1, le=3)
    criterio: CriterioAprobacion
    operador: str = Field(pattern=r"^(<|<=|>|>=|entre|igual|en)$")
    valor_json: dict[str, Any] = Field(default_factory=dict)
    activa: bool = True

    @model_validator(mode="after")
    def _coherente(self) -> "ReglaEntrada":
        c, o, v = self.criterio, self.operador, self.valor_json
        if c == CriterioAprobacion.monto:
            if o == "entre" and not ("min" in v and "max" in v):
                raise ValueError("entre requiere valor_json.min y .max")
            if o in ("<", "<=", ">", ">=") and "monto" not in v:
                raise ValueError("Las reglas por monto requieren valor_json.monto")
            if o in ("igual", "en"):
                raise ValueError("Operador no válido para monto")
        elif c == CriterioAprobacion.criticidad:
            if o != "en" or not isinstance(v.get("valores"), list):
                raise ValueError("Las reglas por criticidad usan operador 'en' con valor_json.valores")
            if set(v["valores"]) - {x.value for x in Criticidad}:
                raise ValueError("Criticidades válidas: A, B, C, D")
        else:
            if o == "igual" and "tipo" not in v:
                raise ValueError("igual requiere valor_json.tipo")
            if o == "en" and not isinstance(v.get("valores"), list):
                raise ValueError("en requiere valor_json.valores")
            if o not in ("igual", "en"):
                raise ValueError("Las reglas por tipo de trabajo usan 'igual' o 'en'")
        return self


class ReglaSalida(ReglaEntrada):
    id: UUID


class NivelConfigEntrada(BaseModel):
    nivel: int = Field(ge=1, le=3)
    rol_aprobador: Rol
    tiempo_limite_horas: int = Field(ge=1, le=720)
    comportamiento_timeout: ComportamientoTimeout = ComportamientoTimeout.bloquear_alertar
    notificar_por_json: list[str] = Field(default_factory=lambda: ["push", "app"])

    @model_validator(mode="after")
    def _nivel3(self) -> "NivelConfigEntrada":
        if self.nivel == 3 and self.comportamiento_timeout not in (ComportamientoTimeout.bloquear_alertar,
                                                                    ComportamientoTimeout.depende_criticidad):
            raise ValueError("El Nivel 3 solo admite 'bloquear_alertar' o 'depende_criticidad' (§6.8.7)")
        if self.rol_aprobador not in (Rol.admin_un, Rol.supervisor_operadores, Rol.admin_empresa):
            raise ValueError("El aprobador debe ser admin_un, supervisor_operadores o admin_empresa")
        return self


class NivelConfigSalida(NivelConfigEntrada):
    id: UUID


class ConfiguracionAprobacion(BaseModel):
    politicas: PoliticasSalida
    reglas: list[ReglaSalida]
    niveles: list[NivelConfigSalida]


class KeywordEntrada(BaseModel):
    palabra: str = Field(min_length=2, max_length=80)
    tenant_id: UUID | None = None
    activa: bool = True


class KeywordSalida(KeywordEntrada):
    id: UUID
    prestador_id: UUID


class HorarioServicio(Modelo):
    """Validador del horario de servicio del contrato: {"lunes": [["08:00","18:00"]], ...}."""

    @staticmethod
    def validar(horario: dict[str, Any] | None) -> dict[str, Any] | None:
        if horario is None:
            return None
        if not isinstance(horario, dict) or set(horario) - set(DIAS):
            raise ValueError(f"Días válidos: {', '.join(DIAS)}")
        for dia, rangos in horario.items():
            if not isinstance(rangos, list):
                raise ValueError(f"{dia}: lista de rangos [inicio, fin]")
            for r in rangos:
                if not (isinstance(r, list) and len(r) == 2 and all(isinstance(x, str) and len(x) == 5 and x[2] == ":" for x in r)):
                    raise ValueError(f"{dia}: cada rango es [\"HH:MM\", \"HH:MM\"]")
                if r[0] >= r[1]:
                    raise ValueError(f"{dia}: el inicio debe ser menor que el fin")
        return horario
