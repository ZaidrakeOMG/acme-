from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from models.base import AplicaPermiso, EstadoAlerta, TipoUmbral
from schemas.comun import ConVersionSalida, Modelo

CANALES = Literal["push", "email", "whatsapp", "sms"]


class AlertaCatalogoSalida(ConVersionSalida):
    clave: str
    descripcion: str
    umbral_default: Decimal
    umbral_min: Decimal
    umbral_max: Decimal
    tipo_umbral: TipoUmbral
    parametros_default: dict[str, Any]
    modulo_origen: str
    prompt_origen: str
    destinatarios_default: list[str]
    canales_default: list[str]
    activa_por_defecto: bool


class AlertaCatalogoCambios(BaseModel):
    """Solo superadmin: umbral por defecto y rango permitido a tenants y prestadores."""

    umbral_default: Decimal | None = None
    umbral_min: Decimal | None = None
    umbral_max: Decimal | None = None
    activa_por_defecto: bool | None = None
    parametros_default: dict[str, Any] | None = None


class AlertaConfiguracionEntrada(BaseModel):
    umbral_valor: Decimal
    parametros: dict[str, Any] = Field(default_factory=dict)
    canales: list[CANALES] = Field(default_factory=lambda: ["push", "email"], min_length=1)
    destinatarios_roles: list[str] = Field(default_factory=list)
    activa: bool = True


class AlertaEfectiva(BaseModel):
    clave: str
    descripcion: str
    tipo_umbral: TipoUmbral
    umbral_min: Decimal
    umbral_max: Decimal
    umbral_default: Decimal
    umbral_valor: Decimal
    parametros: dict[str, Any]
    canales: list[str]
    destinatarios_roles: list[str]
    activa: bool
    personalizada: bool
    prompt_origen: str
    modulo_origen: str


class AlertaHistorialSalida(Modelo):
    id: UUID
    clave_alerta: str
    tenant_id: UUID | None
    prestador_id: UUID | None
    entidad_tipo: str | None
    entidad_id: UUID | None
    umbral_en_momento: Decimal | None
    datos_contexto_json: dict[str, Any]
    estado: EstadoAlerta
    timestamp_disparo: datetime
    timestamp_vista: datetime | None


class SupresionEntrada(BaseModel):
    clave_alerta: str
    entidad_id: UUID | None = None
    razon: str = Field(min_length=3, max_length=500)
    hasta: datetime

    @model_validator(mode="after")
    def _futuro(self) -> "SupresionEntrada":
        if self.hasta.tzinfo is None:
            raise ValueError("La fecha 'hasta' debe incluir zona horaria")
        return self


class SupresionSalida(ConVersionSalida):
    clave_alerta: str
    tenant_id: UUID | None
    prestador_id: UUID | None
    entidad_id: UUID | None
    suprimida_por: UUID | None
    razon: str
    desde: datetime
    hasta: datetime
    activa: bool


class ValorConfiguracion(BaseModel):
    valor: Any = Field(description="Cualquier valor JSON")


class ConfiguracionSalida(Modelo):
    clave: str
    valor: Any
    updated_at: datetime


class PermisoEfectivo(BaseModel):
    clave: str
    aplica_a: AplicaPermiso
    descripcion: str
    valor_default: bool
    habilitado: bool


class PermisosCambios(BaseModel):
    valores: dict[str, bool] = Field(description="permiso_clave -> habilitado")


class PermisosDespachadorCambios(PermisosCambios):
    despachador_id: UUID | None = Field(default=None, description="Con tenant_id: permiso por despachador y cliente")
    tenant_id: UUID | None = None

    @model_validator(mode="after")
    def _alcance(self) -> "PermisosDespachadorCambios":
        if (self.despachador_id is None) != (self.tenant_id is None):
            raise ValueError("despachador_id y tenant_id van juntos (o ambos vacíos para el valor base)")
        return self
