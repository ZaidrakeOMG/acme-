from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

from models.base import (
    Dominio, EstadoRegistro, ModalidadContrato, NivelSeveridad, Rol, TipoPenalizacion, UnidadTiempo,
)
from schemas.comun import ConVersionSalida, Modelo

_RFC = r"^[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}$"
_COLOR = r"^#[0-9A-Fa-f]{6}$"

# ------------------------------------------------------------------ tenants


class TenantEntrada(BaseModel):
    razon_social: str = Field(min_length=2, max_length=200)
    rfc: str = Field(pattern=_RFC)
    pais: str = Field(default="MX", min_length=2, max_length=2)
    moneda: str = Field(default="MXN", min_length=3, max_length=3)
    zona_horaria: str = Field(default="America/Mexico_City", max_length=64)

    @field_validator("rfc", mode="before")
    @classmethod
    def _mayus(cls, v: str) -> str:
        return v.strip().upper() if isinstance(v, str) else v


class TenantCambios(BaseModel):
    razon_social: str | None = Field(default=None, min_length=2, max_length=200)
    moneda: str | None = Field(default=None, min_length=3, max_length=3)
    zona_horaria: str | None = Field(default=None, max_length=64)
    estado: EstadoRegistro | None = None


class TenantSalida(ConVersionSalida):
    razon_social: str
    rfc: str
    pais: str
    moneda: str
    zona_horaria: str
    estado: EstadoRegistro


class VinculoPrestadorEntrada(BaseModel):
    prestador_id: UUID
    vigencia_inicio: date = Field(default_factory=date.today)
    vigencia_fin: date | None = None


class VinculoSalida(ConVersionSalida):
    tenant_id: UUID
    prestador_id: UUID
    vigencia_inicio: date
    vigencia_fin: date | None
    estado: EstadoRegistro


# --------------------------------------------------------------- prestadores


class DatosFiscales(BaseModel):
    regimen_fiscal: str | None = Field(default=None, max_length=10)
    codigo_postal: str | None = Field(default=None, max_length=10)
    domicilio_fiscal: str | None = Field(default=None, max_length=300)
    correo_facturacion: EmailStr | None = None


class PrestadorEntrada(BaseModel):
    razon_social: str = Field(min_length=2, max_length=200)
    rfc: str = Field(pattern=_RFC)
    pais: str = Field(default="MX", min_length=2, max_length=2)
    datos_fiscales: DatosFiscales | None = None
    color_primario: str = Field(default="#1C3D8F", pattern=_COLOR)
    color_acento: str = Field(default="#A2C62B", pattern=_COLOR)

    @field_validator("rfc", mode="before")
    @classmethod
    def _mayus(cls, v: str) -> str:
        return v.strip().upper() if isinstance(v, str) else v


class PrestadorCambios(BaseModel):
    razon_social: str | None = Field(default=None, min_length=2, max_length=200)
    datos_fiscales: DatosFiscales | None = None
    color_primario: str | None = Field(default=None, pattern=_COLOR)
    color_acento: str | None = Field(default=None, pattern=_COLOR)
    estado: EstadoRegistro | None = None


class PrestadorSalida(ConVersionSalida):
    razon_social: str
    rfc: str
    pais: str
    logo_key: str | None
    color_primario: str
    color_acento: str
    estado: EstadoRegistro
    datos_fiscales: DatosFiscales | None = None


# ------------------------------------------------------------------ usuarios


class UsuarioEntrada(BaseModel):
    email: EmailStr
    nombre: str = Field(min_length=2, max_length=160)
    telefono: str | None = Field(default=None, max_length=30)
    rol: Rol
    contrasena: str = Field(min_length=10, max_length=200)
    tenant_id: UUID | None = Field(default=None, description="Obligatorio para roles del dominio tenant (solo superadmin lo elige)")
    prestador_id: UUID | None = Field(default=None, description="Obligatorio para roles del dominio prestador (solo superadmin lo elige)")
    modulos_habilitados: list[str] | None = Field(default=None, max_length=50)


class UsuarioCambios(BaseModel):
    modulos_habilitados: list[str] | None = Field(default=None, max_length=50)
    nombre: str | None = Field(default=None, min_length=2, max_length=160)
    telefono: str | None = Field(default=None, max_length=30)
    rol: Rol | None = None
    estado: EstadoRegistro | None = None


class UsuarioSalida(ConVersionSalida):
    modulos_habilitados: list[str] | None = None
    email: str
    nombre: str
    telefono: str | None
    rol: Rol
    dominio: Dominio
    tenant_id: UUID | None
    prestador_id: UUID | None
    estado: EstadoRegistro
    mfa_habilitado: bool
    ultimo_acceso_at: datetime | None


# ----------------------------------------------------------- UNs y grupos


class Coordenadas(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


class UnidadEntrada(BaseModel):
    nombre: str = Field(min_length=2, max_length=160)
    codigo: str = Field(min_length=1, max_length=40)
    direccion: str = Field(default="", max_length=500)
    ubicacion: Coordenadas | None = None
    zona_horaria: str = Field(default="America/Mexico_City", max_length=64)
    grupo_id: UUID | None = None
    tenant_id: UUID | None = Field(default=None, description="Solo superadmin; para los demás se toma del usuario")


class UnidadCambios(BaseModel):
    nombre: str | None = Field(default=None, min_length=2, max_length=160)
    codigo: str | None = Field(default=None, min_length=1, max_length=40)
    direccion: str | None = Field(default=None, max_length=500)
    ubicacion: Coordenadas | None = None
    zona_horaria: str | None = Field(default=None, max_length=64)
    grupo_id: UUID | None = None
    estado: EstadoRegistro | None = None


class UnidadSalida(ConVersionSalida):
    tenant_id: UUID
    nombre: str
    codigo: str
    direccion: str
    ubicacion: Coordenadas | None = None
    zona_horaria: str
    estado: EstadoRegistro
    grupo_id: UUID | None


class AsignacionUsuariosEntrada(BaseModel):
    usuario_ids: list[UUID] = Field(max_length=500)


class GrupoEntrada(BaseModel):
    nombre: str = Field(min_length=2, max_length=120)
    descripcion: str = Field(default="", max_length=1000)
    responsable_id: UUID | None = None
    tenant_id: UUID | None = Field(default=None, description="Solo superadmin")


class GrupoCambios(BaseModel):
    nombre: str | None = Field(default=None, min_length=2, max_length=120)
    descripcion: str | None = Field(default=None, max_length=1000)
    responsable_id: UUID | None = None
    estado: EstadoRegistro | None = None


class GrupoSalida(ConVersionSalida):
    tenant_id: UUID
    nombre: str
    descripcion: str
    responsable_id: UUID | None
    estado: EstadoRegistro
    unidad_ids: list[UUID] = Field(default_factory=list)
    supervisor_ids: list[UUID] = Field(default_factory=list)


class MiembrosEntrada(BaseModel):
    unidad_ids: list[UUID] = Field(max_length=2000)


# ------------------------------------------------------------------ contratos


EN_HORAS = {UnidadTiempo.horas: 1, UnidadTiempo.dias: 24, UnidadTiempo.semanas: 168, UnidadTiempo.meses: 720}


class SLAEntrada(BaseModel):
    """§6.10.1: el contrato se firma en horas, días, semanas o meses; ACMA guarda también el equivalente en horas (1 a 4,320).

    P10: si se envía `tiempo_respuesta`/`tiempo_resolucion` manda la unidad; si no, se usan los valores en horas.
    """

    nivel_severidad: NivelSeveridad
    tiempo_respuesta: int | None = Field(default=None, ge=1, description="En la unidad de `unidad_expresion`")
    tiempo_resolucion: int | None = Field(default=None, ge=1, description="En la unidad de `unidad_expresion`")
    tiempo_respuesta_horas: int = Field(default=0, ge=0, le=4320)
    tiempo_resolucion_horas: int = Field(default=0, ge=0, le=4320)
    unidad_expresion: UnidadTiempo = UnidadTiempo.horas
    penalizacion_tipo: TipoPenalizacion = TipoPenalizacion.porcentaje
    penalizacion_valor: Decimal = Field(default=Decimal("0"), ge=0, max_digits=12, decimal_places=2)

    @model_validator(mode="after")
    def _coherencia(self) -> "SLAEntrada":
        factor = EN_HORAS[self.unidad_expresion]
        if self.tiempo_respuesta is not None:
            self.tiempo_respuesta_horas = self.tiempo_respuesta * factor
        elif self.tiempo_respuesta_horas:
            self.tiempo_respuesta = self.tiempo_respuesta_horas // factor or 1
        if self.tiempo_resolucion is not None:
            self.tiempo_resolucion_horas = self.tiempo_resolucion * factor
        elif self.tiempo_resolucion_horas:
            self.tiempo_resolucion = self.tiempo_resolucion_horas // factor or 1
        for etiqueta, horas in (("respuesta", self.tiempo_respuesta_horas), ("resolución", self.tiempo_resolucion_horas)):
            if not 1 <= horas <= 4320:
                raise ValueError(f"El tiempo de {etiqueta} equivale a {horas} horas; el rango de §6.10.1 es de 1 a 4,320")
        if self.tiempo_resolucion_horas < self.tiempo_respuesta_horas:
            raise ValueError("El tiempo de resolución no puede ser menor al de respuesta")
        if self.penalizacion_tipo == TipoPenalizacion.porcentaje and self.penalizacion_valor > 100:
            raise ValueError("La penalización porcentual no puede exceder 100")
        return self


class SLASalida(ConVersionSalida):
    nivel_severidad: NivelSeveridad
    tiempo_respuesta: int
    tiempo_resolucion: int
    tiempo_respuesta_horas: int
    tiempo_resolucion_horas: int
    unidad_expresion: UnidadTiempo
    penalizacion_tipo: TipoPenalizacion
    penalizacion_valor: Decimal


def _validar_slas(slas: list[SLAEntrada]) -> list[SLAEntrada]:
    niveles = [s.nivel_severidad for s in slas]
    if len(niveles) != 5 or set(niveles) != set(NivelSeveridad):
        raise ValueError("Se requieren exactamente los 5 niveles de severidad: " + ", ".join(n.value for n in NivelSeveridad))
    return slas


class ContratoEntrada(BaseModel):
    tenant_id: UUID
    prestador_id: UUID | None = Field(default=None, description="Solo superadmin; admin_prestador usa el suyo")
    nombre: str = Field(min_length=2, max_length=160)
    modalidad: ModalidadContrato = ModalidadContrato.evento
    fecha_inicio: date
    fecha_fin: date
    folios_correctivos_iguala: int | None = Field(default=None, ge=0)
    preventivos_iguala_json: dict[str, Any] = Field(default_factory=dict,
                                                    description='§6.10.1: {"cantidad": 8, "periodicidad": "mensual", "puntos_a_revisar": "..."}')
    tarifa_iguala_mensual: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    moneda: str = Field(default="MXN", min_length=3, max_length=3)
    penalizacion_tope_porcentaje: Decimal | None = Field(default=None, ge=0, le=100)
    calificacion_json: dict[str, Any] = Field(default_factory=dict)
    horario_servicio_json: dict[str, Any] | None = Field(default=None, description='P04: {"lunes": [["08:00","18:00"]], ...}; vacío = 24/7')
    slas: list[SLAEntrada]

    @field_validator("horario_servicio_json")
    @classmethod
    def _horario(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        from schemas.folios import HorarioServicio
        return HorarioServicio.validar(v)

    @field_validator("slas")
    @classmethod
    def _slas(cls, v: list[SLAEntrada]) -> list[SLAEntrada]:
        return _validar_slas(v)

    @model_validator(mode="after")
    def _vigencia(self) -> "ContratoEntrada":
        if self.fecha_fin < self.fecha_inicio:
            raise ValueError("La fecha de fin debe ser posterior a la de inicio")
        if self.modalidad == ModalidadContrato.iguala and self.folios_correctivos_iguala is None:
            raise ValueError("La modalidad iguala requiere folios_correctivos_iguala")
        if self.modalidad == ModalidadContrato.iguala and self.tarifa_iguala_mensual is None:
            raise ValueError("La modalidad iguala requiere tarifa_iguala_mensual")
        return self


class ContratoCambios(BaseModel):
    nombre: str | None = Field(default=None, min_length=2, max_length=160)
    modalidad: ModalidadContrato | None = None
    fecha_inicio: date | None = None
    fecha_fin: date | None = None
    folios_correctivos_iguala: int | None = Field(default=None, ge=0)
    preventivos_iguala_json: dict[str, Any] | None = None
    tarifa_iguala_mensual: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    moneda: str | None = Field(default=None, min_length=3, max_length=3)
    penalizacion_tope_porcentaje: Decimal | None = Field(default=None, ge=0, le=100)
    calificacion_json: dict[str, Any] | None = None
    horario_servicio_json: dict[str, Any] | None = None
    estado: EstadoRegistro | None = None
    slas: list[SLAEntrada] | None = None

    @field_validator("horario_servicio_json")
    @classmethod
    def _horario(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        from schemas.folios import HorarioServicio
        return HorarioServicio.validar(v)

    @field_validator("slas")
    @classmethod
    def _slas(cls, v: list[SLAEntrada] | None) -> list[SLAEntrada] | None:
        return None if v is None else _validar_slas(v)


class ContratoSalida(ConVersionSalida):
    tenant_id: UUID
    prestador_id: UUID
    nombre: str
    modalidad: ModalidadContrato
    fecha_inicio: date
    fecha_fin: date
    folios_correctivos_iguala: int | None
    preventivos_iguala_json: dict[str, Any]
    tarifa_iguala_mensual: Decimal | None = None
    moneda: str = "MXN"
    penalizacion_tope_porcentaje: Decimal | None
    calificacion_json: dict[str, Any]
    horario_servicio_json: dict[str, Any] | None = None
    estado: EstadoRegistro
    slas: list[SLASalida] = Field(default_factory=list)


class Opcion(Modelo):
    id: UUID
    nombre: str
