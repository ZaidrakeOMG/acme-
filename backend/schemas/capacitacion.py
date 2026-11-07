"""Esquemas de capacitación y biblioteca (§6.10.3, §6.10.4). F2-01."""
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from models.capacitacion import CategoriaManual, EstadoCursoTecnico, TipoCurso
from schemas.comun import ConVersionSalida, Modelo


# ------------------------------------------------------------------ catálogo de cursos
class CursoEntrada(BaseModel):
    nombre: str = Field(min_length=3, max_length=200)
    proveedor: str | None = Field(default=None, max_length=200)
    duracion_horas: Decimal | None = Field(default=None, gt=0, le=9999)
    vigencia_meses: int | None = Field(default=None, ge=1, le=600)
    habilidad_id: UUID | None = None
    tipo: TipoCurso = TipoCurso.curso
    norma_referencia: str | None = Field(default=None, max_length=160)
    descripcion: str = Field(default="", max_length=2000)
    activo: bool = True
    # Solo el Superadmin: deja el curso en el catálogo global (prestador_id nulo).
    global_: bool = Field(default=False, alias="global")

    model_config = {"populate_by_name": True}


class CursoCambios(BaseModel):
    nombre: str | None = Field(default=None, min_length=3, max_length=200)
    proveedor: str | None = Field(default=None, max_length=200)
    duracion_horas: Decimal | None = Field(default=None, gt=0, le=9999)
    vigencia_meses: int | None = Field(default=None, ge=1, le=600)
    habilidad_id: UUID | None = None
    tipo: TipoCurso | None = None
    norma_referencia: str | None = Field(default=None, max_length=160)
    descripcion: str | None = Field(default=None, max_length=2000)
    activo: bool | None = None


class CursoSalida(ConVersionSalida):
    prestador_id: UUID | None
    nombre: str
    proveedor: str | None
    duracion_horas: Decimal | None
    vigencia_meses: int | None
    habilidad_id: UUID | None
    tipo: TipoCurso
    norma_referencia: str | None
    descripcion: str
    activo: bool


# ------------------------------------------------------------------ cursos del técnico
class RegistroCursoEntrada(BaseModel):
    tecnico_id: UUID
    curso_id: UUID
    fecha_fin: date
    fecha_inicio: date | None = None
    calificacion: Decimal | None = Field(default=None, ge=0, le=100)
    aprobado: bool = True
    folio_constancia: str | None = Field(default=None, max_length=80)
    vigente_hasta: date | None = None
    razon_vigencia: str = Field(default="", max_length=1000)
    notas: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def _fechas(self) -> "RegistroCursoEntrada":
        if self.fecha_inicio and self.fecha_inicio > self.fecha_fin:
            raise ValueError("La fecha de inicio es posterior a la de término")
        return self


class CursoDeTecnicoSalida(Modelo):
    id: UUID
    curso_id: UUID
    curso: str
    tipo: str | None
    proveedor: str | None
    norma_referencia: str | None
    fecha_inicio: date | None
    fecha_fin: date
    calificacion: Decimal | None
    aprobado: bool
    folio_constancia: str | None
    vigente_hasta: date | None
    estado: str
    dias_para_vencer: int | None
    tiene_certificado: bool
    notas: str
    habilidad: str | None


class HabilidadDerivadaSalida(Modelo):
    habilidad_id: UUID
    habilidad: str
    clave: str
    certificada: bool
    origen: str
    fecha_certificacion: date | None
    vigencia_hasta: date | None
    estado: str


class ExpedienteSalida(Modelo):
    tecnico_id: UUID
    tecnico_nombre: str
    numero_empleado: str | None
    dias_anticipacion: int
    cursos: list[CursoDeTecnicoSalida]
    habilidades: list[HabilidadDerivadaSalida]


class VencimientoSalida(Modelo):
    tecnico_curso_id: UUID
    tecnico_id: UUID
    tecnico_nombre: str
    curso: str
    tipo: str
    norma_referencia: str | None
    vigente_hasta: date
    dias: int
    estado: str
    habilidad_id: UUID | None


class CertificacionDelClienteSalida(Modelo):
    """Lo único que ve el cliente (§6.10.3): sin calificaciones, sin adjuntos y sin datos internos."""

    nombre: str
    tipo: str
    norma_referencia: str | None
    proveedor: str | None
    vigente_hasta: date | None
    vigencia: str


class TecnicoDelClienteSalida(Modelo):
    tecnico_id: UUID
    nombre: str
    certificaciones: list[CertificacionDelClienteSalida]


class AlertasConfigEntrada(BaseModel):
    dias_anticipacion: int | None = Field(default=None, ge=1, le=180)
    notificar_cliente: bool | None = None
    activa: bool | None = None


class AlertasConfigSalida(Modelo):
    prestador_id: UUID
    dias_anticipacion: int
    notificar_cliente: bool
    activa: bool


# ------------------------------------------------------------------ biblioteca
class ManualSalida(Modelo):
    id: UUID
    tipo_equipo_id: UUID
    tipo_equipo: str
    titulo: str
    categoria: str
    descripcion: str
    version: int
    fecha_subida: datetime
    nombre_original: str
    mime: str
    bytes: int
    hash_sha256: str
    updated_at: datetime | None


class VersionManualSalida(ConVersionSalida):
    manual_id: UUID
    version_anterior: int
    nombre_original_anterior: str | None
    bytes_anterior: int | None
    hash_sha256_anterior: str | None
    reemplazado_en: datetime
    reemplazado_por: UUID | None
    notas_version: str


class PuntoRevision(BaseModel):
    clave: str | None = Field(default=None, max_length=60)
    descripcion: str = Field(min_length=3, max_length=500)
    obligatorio: bool = True


class ContenidoEntrada(BaseModel):
    tipo_equipo_id: UUID
    contrato_id: UUID
    titulo: str = Field(min_length=3, max_length=200)
    puntos_revision: list[PuntoRevision] = Field(default_factory=list, max_length=200)
    periodicidad: str | None = Field(default=None, max_length=80)
    correctivos_iguala: int | None = Field(default=None, ge=0, le=10000)
    preventivos_iguala: dict[str, Any] | None = None


class ContenidoSalida(Modelo):
    id: UUID
    tenant_id: UUID
    tipo_equipo_id: UUID
    tipo_equipo: str
    contrato_id: UUID
    titulo: str
    puntos_revision: list[dict[str, Any]]
    periodicidad: str | None
    correctivos_iguala: int | None
    preventivos_iguala: dict[str, Any]
    version: int
    activo: bool
    tiene_archivo: bool
    updated_at: datetime | None


class ContenidoGuardado(Modelo):
    contenido: ContenidoSalida
    # §6.10.4 + P10: si lo declarado no coincide con la iguala del contrato se avisa, no se bloquea.
    avisos: list[str]


class DescargaOfflineEntrada(BaseModel):
    manual_id: UUID | None = None
    contenido_id: UUID | None = None
    version: int = Field(ge=1)
    dispositivo_id: str | None = Field(default=None, max_length=120)
    en_dispositivo: bool = True

    @model_validator(mode="after")
    def _uno(self) -> "DescargaOfflineEntrada":
        if (self.manual_id is None) == (self.contenido_id is None):
            raise ValueError("Indica un manual o un contenido de servicio, no los dos")
        return self


class DescargaOfflineSalida(Modelo):
    tipo: str
    id: UUID
    titulo: str
    bytes: int | None
    version_descargada: int
    version_vigente: int
    desactualizado: bool
    activo: bool
    fecha_descarga: datetime
    dispositivo_id: str | None


class EnlaceDescargaSalida(Modelo):
    """Enlace firmado de corta duración para el visor del navegador."""

    url: str
    expira_en_segundos: int
    nombre: str
    mime: str


class ContenidoDeFolioSalida(Modelo):
    """Los puntos de revisión tal como los necesita la atención, sin los datos contractuales ni de costo."""
    id: UUID
    titulo: str
    puntos_revision: list[dict[str, Any]]
    periodicidad: str | None
    version: int


class ApoyoDeFolioSalida(Modelo):
    """Apoyo documental de un folio (§6.10.4): puntos de revisión del contrato y manuales del tipo de equipo."""
    folio_id: UUID
    tipo_equipo_id: UUID
    contenido: ContenidoDeFolioSalida | None
    manuales: list[ManualSalida]
