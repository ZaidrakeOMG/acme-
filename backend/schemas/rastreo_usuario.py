"""GPS voluntario del usuario autenticado, no requiere ningún folio."""
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ConsentimientoUsuario(BaseModel):
    acepto: bool = False
    dispositivo: str = Field(default="navegador", max_length=24, pattern="^(pc|android|iphone|navegador)$")


class PuntoUsuario(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    precision_m: float | None = Field(default=None, ge=0, le=1000000)


class MiRastreo(BaseModel):
    compartiendo: bool
    ultima_at: datetime | None = None


class UsuarioEnMapa(BaseModel):
    usuario_id: UUID
    usuario_nombre: str
    dispositivo: str
    lat: float
    lng: float
    precision_m: float | None
    ultima_at: datetime


class UsuarioRastreable(BaseModel):
    """Usuario con cuenta activa; su GPS solo aparece con consentimiento vigente."""
    usuario_id: UUID
    usuario_nombre: str
    rol: str
    correo: str
    dispositivo: str | None = None
    gps_activo: bool
    lat: float | None = None
    lng: float | None = None
    precision_m: float | None = None
    ultima_at: datetime | None = None
    ultimo_acceso_at: datetime | None = None
