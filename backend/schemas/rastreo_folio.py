"""Contratos de geolocalizacion voluntaria para un folio."""
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ConsentimientoUbicacion(BaseModel):
    acepto: bool = False


class PuntoUbicacionUsuario(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    precision_m: float | None = Field(default=None, ge=0, le=10000)


class MiRastreoFolio(BaseModel):
    compartiendo: bool
    ultima_at: datetime | None = None


class UsuarioUbicacionFolio(BaseModel):
    folio_id: UUID
    usuario_id: UUID
    usuario_nombre: str
    lat: float
    lng: float
    precision_m: float | None
    ultima_at: datetime
