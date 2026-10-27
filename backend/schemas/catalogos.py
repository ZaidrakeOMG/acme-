from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, model_validator

from models.catalogos import EstadoActivo, OrigenHabilidad
from schemas.comun import ConVersionSalida

_COLOR = r"^#[0-9A-Fa-f]{6}$"
_CLAVE = r"^[a-z0-9][a-z0-9_]{1,59}$"

# ---------------------------------------------------------------- habilidades


class HabilidadEntrada(BaseModel):
    clave: str = Field(pattern=_CLAVE, description="Identificador en minúsculas, p. ej. `refrigeracion_comercial`")
    nombre: str = Field(min_length=2, max_length=120)
    descripcion: str = Field(default="", max_length=1000)


class HabilidadCambios(BaseModel):
    nombre: str | None = Field(default=None, min_length=2, max_length=120)
    descripcion: str | None = Field(default=None, max_length=1000)
    activa: bool | None = None


class HabilidadSalida(ConVersionSalida):
    prestador_id: UUID
    clave: str
    nombre: str
    descripcion: str
    activa: bool


# ------------------------------------------------------------------ técnicos


class TecnicoEntrada(BaseModel):
    usuario_id: UUID | None = Field(default=None, description="Vincular un usuario existente con rol técnico")
    email: EmailStr | None = Field(default=None, description="Crear un usuario técnico nuevo")
    nombre: str | None = Field(default=None, min_length=2, max_length=160)
    contrasena: str | None = Field(default=None, min_length=10, max_length=200)
    numero_empleado: str | None = Field(default=None, max_length=40)
    telefono: str | None = Field(default=None, max_length=30)
    vehiculo_placas: str | None = Field(default=None, max_length=20)
    fecha_ingreso: date | None = None

    @model_validator(mode="after")
    def _usuario(self) -> "TecnicoEntrada":
        if self.usuario_id is None and not (self.email and self.nombre and self.contrasena):
            raise ValueError("Indica usuario_id, o bien email, nombre y contrasena para crear el usuario")
        return self


class TecnicoCambios(BaseModel):
    numero_empleado: str | None = Field(default=None, max_length=40)
    telefono: str | None = Field(default=None, max_length=30)
    vehiculo_placas: str | None = Field(default=None, max_length=20)
    fecha_ingreso: date | None = None
    estado: EstadoActivo | None = None


class HabilidadDeTecnico(BaseModel):
    habilidad_id: UUID
    clave: str
    nombre: str
    certificada: bool
    fecha_certificacion: date | None
    vigencia_hasta: date | None
    origen: OrigenHabilidad
    vigente: bool


class TecnicoSalida(ConVersionSalida):
    prestador_id: UUID
    usuario_id: UUID
    nombre: str
    email: str
    numero_empleado: str | None
    telefono: str | None
    vehiculo_placas: str | None
    estado: EstadoActivo
    fecha_ingreso: date | None
    habilidades: list[HabilidadDeTecnico] = Field(default_factory=list)
    tenants_habilitados: list[UUID] = Field(default_factory=list)
    grupo_id: UUID | None = None


class HabilidadAsignada(BaseModel):
    habilidad_id: UUID
    certificada: bool = False
    fecha_certificacion: date | None = None
    vigencia_hasta: date | None = None

    @model_validator(mode="after")
    def _fechas(self) -> "HabilidadAsignada":
        if self.vigencia_hasta and self.fecha_certificacion and self.vigencia_hasta < self.fecha_certificacion:
            raise ValueError("La vigencia no puede ser anterior a la fecha de certificación")
        return self


class HabilidadesEntrada(BaseModel):
    habilidades: list[HabilidadAsignada] = Field(max_length=200)


class TenantsHabilitadosEntrada(BaseModel):
    tenant_ids: list[UUID] = Field(max_length=500)


class GrupoTecnicosEntrada(BaseModel):
    nombre: str = Field(min_length=2, max_length=80)
    descripcion: str = Field(default="", max_length=1000)


class GrupoTecnicosSalida(ConVersionSalida):
    prestador_id: UUID
    nombre: str
    descripcion: str
    permisos: dict[str, bool] = Field(default_factory=dict)


class GrupoDeTecnicoEntrada(BaseModel):
    grupo_id: UUID | None = Field(description="null quita al técnico de su grupo")


class OverrideEntrada(BaseModel):
    permiso_clave: str
    habilitado: bool | None = Field(description="null elimina el override")
    razon: str = Field(default="", max_length=500)


class OverridesEntrada(BaseModel):
    overrides: list[OverrideEntrada] = Field(max_length=50)


class PermisoEfectivoTecnico(BaseModel):
    clave: str
    descripcion: str
    habilitado: bool
    origen: str = Field(description="override, grupo, prestador o catalogo")
    razon: str | None = None


# --------------------------------------------------------------- severidades


class SeveridadCambios(BaseModel):
    nombre: str | None = Field(default=None, min_length=2, max_length=60)
    color_hex: str | None = Field(default=None, pattern=_COLOR)
    tiempo_respuesta_horas: int | None = Field(default=None, ge=1, le=4320)
    tiempo_resolucion_horas: int | None = Field(default=None, ge=1, le=4320)
    activo: bool | None = None


class SeveridadSalida(ConVersionSalida):
    prestador_id: UUID
    clave: str
    nombre: str
    orden: int
    color_hex: str
    tiempo_respuesta_horas: int
    tiempo_resolucion_horas: int
    activo: bool


# ------------------------------------------------------- familias y tipos


class FamiliaEntrada(BaseModel):
    habilidad_clave: str | None = Field(default=None, max_length=60, description="P04: habilidad requerida para asignar técnico")
    nombre: str = Field(min_length=2, max_length=120)
    descripcion: str = Field(default="", max_length=1000)
    global_: bool = Field(default=False, alias="global", description="Solo superadmin: catálogo de plataforma")


class FamiliaCambios(BaseModel):
    habilidad_clave: str | None = Field(default=None, max_length=60)
    nombre: str | None = Field(default=None, min_length=2, max_length=120)
    descripcion: str | None = Field(default=None, max_length=1000)
    activa: bool | None = None


class FamiliaSalida(ConVersionSalida):
    habilidad_clave: str | None = None
    tenant_id: UUID | None
    nombre: str
    descripcion: str
    activa: bool
    es_global: bool


class TipoEquipoEntrada(BaseModel):
    familia_id: UUID
    nombre: str = Field(min_length=2, max_length=120)
    descripcion: str = Field(default="", max_length=1000)
    global_: bool = Field(default=False, alias="global")


class TipoEquipoCambios(BaseModel):
    nombre: str | None = Field(default=None, min_length=2, max_length=120)
    descripcion: str | None = Field(default=None, max_length=1000)
    activa: bool | None = None


class TipoEquipoSalida(ConVersionSalida):
    familia_id: UUID
    tenant_id: UUID | None
    nombre: str
    descripcion: str
    activa: bool
    es_global: bool


# -------------------------------------------------------------------- equipos


class EquipoEntrada(BaseModel):
    un_id: UUID
    tipo_equipo_id: UUID
    codigo: str = Field(min_length=1, max_length=60)
    nombre: str = Field(min_length=2, max_length=160)
    marca: str | None = Field(default=None, max_length=80)
    modelo: str | None = Field(default=None, max_length=80)
    numero_serie: str | None = Field(default=None, max_length=80)
    fecha_instalacion: date | None = None
    valor_reposicion: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    garantia_vigente_hasta: date | None = None
    contrato_id: UUID | None = None
    notas: str = Field(default="", max_length=2000)
    criticidad: Literal["A", "B", "C", "D"] | None = Field(default=None, description="P04: criticidad del activo (manual en Fase 1)")


class EquipoCambios(BaseModel):
    un_id: UUID | None = None
    tipo_equipo_id: UUID | None = None
    codigo: str | None = Field(default=None, min_length=1, max_length=60)
    nombre: str | None = Field(default=None, min_length=2, max_length=160)
    marca: str | None = Field(default=None, max_length=80)
    modelo: str | None = Field(default=None, max_length=80)
    numero_serie: str | None = Field(default=None, max_length=80)
    fecha_instalacion: date | None = None
    valor_reposicion: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    garantia_vigente_hasta: date | None = None
    contrato_id: UUID | None = None
    estado: EstadoActivo | None = None
    notas: str | None = Field(default=None, max_length=2000)
    criticidad: Literal["A", "B", "C", "D"] | None = None


class EquipoSalida(ConVersionSalida):
    tenant_id: UUID
    un_id: UUID
    tipo_equipo_id: UUID
    familia_id: UUID | None = None
    codigo: str
    nombre: str
    marca: str | None
    modelo: str | None
    numero_serie: str | None
    fecha_instalacion: date | None
    valor_reposicion: Decimal | None
    estado: EstadoActivo
    garantia_vigente_hasta: date | None
    contrato_id: UUID | None
    notas: str
    criticidad: Literal["A", "B", "C", "D"] | None = None
    con_contrato_activo: bool = False
    en_garantia: bool = False


# --------------------------------------------------------------- tipos de falla


class TipoFallaEntrada(BaseModel):
    descripcion: str = Field(min_length=2, max_length=200)
    familia_equipo_id: UUID
    requiere_revision_manual: bool | None = Field(default=None, description="Solo superadmin")


class TipoFallaCambios(BaseModel):
    descripcion: str | None = Field(default=None, min_length=2, max_length=200)
    familia_equipo_id: UUID | None = None
    requiere_revision_manual: bool | None = Field(default=None, description="Solo superadmin")
    activa: bool | None = None


class TipoFallaSalida(ConVersionSalida):
    prestador_id: UUID
    descripcion: str
    familia_equipo_id: UUID
    requiere_revision_manual: bool
    activa: bool


# --------------------------------------------------------- matriz de severidad


class CeldaMatriz(BaseModel):
    tipo_falla_id: UUID
    tipo_equipo_id: UUID
    nivel_severidad_id: UUID | None = Field(description="null elimina la configuración de la celda")


class MatrizMasivaEntrada(BaseModel):
    celdas: list[CeldaMatriz] = Field(min_length=1, max_length=5000)


class FilaMatriz(BaseModel):
    id: UUID
    descripcion: str
    familia_equipo_id: UUID
    prestador_id: UUID


class ColumnaMatriz(BaseModel):
    id: UUID
    nombre: str
    familia_id: UUID
    en_uso: bool


class NivelMatriz(BaseModel):
    id: UUID
    prestador_id: UUID
    clave: str
    nombre: str
    orden: int
    color_hex: str


class CeldaSalida(BaseModel):
    tipo_falla_id: UUID
    tipo_equipo_id: UUID
    nivel_severidad_id: UUID


class MatrizSalida(BaseModel):
    tenant_id: UUID
    tipos_falla: list[FilaMatriz]
    tipos_equipo: list[ColumnaMatriz]
    niveles: list[NivelMatriz]
    celdas: list[CeldaSalida]
    faltantes_en_uso: int = Field(description="Combinaciones en uso (misma familia) sin severidad")


class SeveridadResuelta(BaseModel):
    tipo_falla_id: UUID
    tipo_equipo_id: UUID
    nivel: NivelMatriz
    tiempo_respuesta_horas: int
    tiempo_resolucion_horas: int
    requiere_revision_manual: bool


# ------------------------------------------------------------------ importador


class ErrorFila(BaseModel):
    fila: int
    columna: str | None
    motivo: str


class ImportacionSalida(ConVersionSalida):
    tenant_id: UUID | None
    prestador_id: UUID | None
    catalogo: str
    archivo_nombre: str
    total_filas: int
    filas_ok: int
    filas_error: int
    errores_json: list[ErrorFila]
    duplicados_json: list[ErrorFila]
    estado: str
    vista_previa: list[dict] = Field(default_factory=list, description="Primeras 50 filas válidas")
    resultado: dict | None = None
