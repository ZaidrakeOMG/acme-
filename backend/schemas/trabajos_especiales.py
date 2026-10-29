"""Esquemas de trabajos especiales (§6.10.6) y seguimiento de OC de activos (§6.10.7). P08."""
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from models.trabajos_especiales import DecisionOCRechazo, EstadoTrabajoEspecial, EstatusOCActivo, TipoEvidenciaTE
from schemas.folios import FolioResumen


# ------------------------------------------------------ trabajos especiales

class TrabajoEspecialEntrada(BaseModel):
    un_id: UUID
    descripcion: str = Field(min_length=5, max_length=4000)
    equipo_id: UUID | None = None
    detalle: dict[str, Any] = Field(default_factory=dict, description="Materiales, tiempo estimado, accesos, seguridad… (según el formulario del TE)")
    monto: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    formulario_id: UUID | None = Field(default=None, description="Formulario tipo trabajo_especial; si falta se resuelve con P03")
    urgencia: bool = Field(default=False, description="TE de urgencia (Admin empresa / Admin UN): sin monto, sin validación obligatoria")
    tenant_id: UUID | None = Field(default=None, description="Solo superadmin")


class EnviarClienteEntrada(BaseModel):
    descripcion: str | None = Field(default=None, min_length=5, max_length=4000)
    monto: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    detalle: dict[str, Any] | None = None
    notas: str = Field(default="", max_length=1000)


class RespuestaClienteEntrada(BaseModel):
    canal: str = Field(default="app", pattern="^(app|email|push)$")
    comentario: str = Field(default="", max_length=2000)


class ProgramarEntrada(BaseModel):
    fecha_programada: date
    tecnico_ids: list[UUID] = Field(min_length=1)
    tecnico_responsable_id: UUID | None = None
    notas: str = Field(default="", max_length=1000)


class NotasTEEntrada(BaseModel):
    notas: str = Field(default="", max_length=2000)


class CambioEstadoTEEntrada(BaseModel):
    estado: EstadoTrabajoEspecial
    notas: str = Field(default="", max_length=2000)
    fecha_programada: date | None = None
    tecnico_ids: list[UUID] | None = None
    tecnico_responsable_id: UUID | None = None
    descripcion: str | None = None
    monto: Decimal | None = None
    detalle: dict[str, Any] | None = None
    canal: str | None = None


class EvidenciaTEEntrada(BaseModel):
    tipo: TipoEvidenciaTE = TipoEvidenciaTE.avance
    evidencia_id: UUID | None = Field(default=None, description="Evidencia del formulario (P03)")
    contenido_base64: str | None = None
    nombre: str | None = Field(default=None, max_length=120)
    mime: str | None = Field(default=None, max_length=80)
    geolat: float | None = Field(default=None, ge=-90, le=90)
    geolng: float | None = Field(default=None, ge=-180, le=180)


class CotizacionRetroactivaEntrada(BaseModel):
    descripcion: str | None = Field(default=None, max_length=4000)
    monto: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    detalle: dict[str, Any] | None = None


class TecnicoTE(BaseModel):
    id: str
    nombre: str | None = None


class TrabajoEspecialSalida(BaseModel):
    id: UUID
    numero: str
    tenant_id: UUID
    prestador_id: UUID
    un_id: UUID
    un_codigo: str | None = None
    un_nombre: str | None = None
    equipo_id: UUID | None
    equipo_codigo: str | None = None
    equipo_nombre: str | None = None
    cotizacion_id: UUID | None
    cotizacion_numero: str | None = None
    cotizacion_estado: str | None = None
    cotizacion_retroactiva_id: UUID | None
    cotizacion_retroactiva_numero: str | None = None
    hallazgo_id: UUID | None
    descripcion: str
    detalle_json: dict[str, Any]
    estado: EstadoTrabajoEspecial
    estado_desde: datetime
    dias_en_estado: int = 0
    urgencia: bool
    creado_por_id: UUID | None
    creado_por_rol: str
    creado_por_nombre: str | None = None
    formulario_id: UUID | None
    respuesta_formulario_id: UUID | None
    monto: Decimal | None
    moneda: str
    fecha_programada: date | None
    fecha_inicio: datetime | None
    fecha_cierre: datetime | None
    tecnicos: list[TecnicoTE] = Field(default_factory=list)
    tecnico_responsable_id: UUID | None
    tecnico_responsable_nombre: str | None = None
    folio_id: UUID | None
    numero_folio: str | None = None
    estado_folio: str | None = None
    razon_cancelacion: str | None
    version_enviada: int
    enviado_at: datetime | None
    aceptado_at: datetime | None
    programado_at: datetime | None
    alertas_activas: list[str] = Field(default_factory=list)
    destinos: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class TrabajoEspecialDetalle(TrabajoEspecialSalida):
    historial: list[dict[str, Any]] = Field(default_factory=list)
    respuestas_cliente: list[dict[str, Any]] = Field(default_factory=list)
    evidencias: list[dict[str, Any]] = Field(default_factory=list)
    requisitos_cierre_faltantes: list[str] = Field(default_factory=list)
    puede_responder: bool = False


class ReporteTE(BaseModel):
    desde: date | None
    hasta: date | None
    total: int
    por_estado: dict[str, int]
    tiempo_promedio_etapas_dias: dict[str, float | None]
    porcentaje_urgencias: float
    urgencias: int
    monto_total: str
    sin_cotizacion_retroactiva: int


# ------------------------------------------------------------ OC de activos

class EstatusOCEntrada(BaseModel):
    estatus: EstatusOCActivo
    numero_oc_provisional: str | None = Field(default=None, max_length=60)
    numero_oc_definitivo: str | None = Field(default=None, max_length=60)
    fecha_autorizacion_erp: date | None = None
    notas: str = Field(default="", max_length=2000)
    decision_rechazo: DecisionOCRechazo | None = None
    periodo_presupuestal_destino: str | None = Field(default=None, max_length=40)


class AutorizacionActivoSalida(BaseModel):
    id: UUID
    folio_id: UUID
    tenant_id: UUID
    prestador_id: UUID
    un_id: UUID
    estatus_multinivel: EstatusOCActivo
    estatus_nombre: str
    estatus_desde: datetime
    dias_en_estatus: int
    numero_oc_provisional: str | None
    numero_oc_definitivo: str | None
    fecha_autorizacion_erp: date | None
    registrado_por: UUID | None
    notas: str
    decision_rechazo: str | None
    periodo_presupuestal_destino: str | None
    origen: str
    datos_equipo: dict[str, Any]
    hallazgo_presupuesto_id: UUID | None
    destinos: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class PendienteOCSalida(AutorizacionActivoSalida):
    folio: FolioResumen


class AutorizacionActivoDetalle(AutorizacionActivoSalida):
    folio: FolioResumen
    historial: list[dict[str, Any]] = Field(default_factory=list)
    equipo_instalado: dict[str, Any] | None = None
