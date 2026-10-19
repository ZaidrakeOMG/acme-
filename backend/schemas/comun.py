from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class Modelo(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ConVersionSalida(Modelo):
    id: UUID
    created_at: datetime
    updated_at: datetime
    version_hash: str | None = None


class Error(BaseModel):
    """Formato estándar de error de la API."""

    codigo: str = Field(examples=["NO_ENCONTRADO"])
    mensaje: str = Field(examples=["Recurso no encontrado"])
    detalles: list[Any] = Field(default_factory=list)


class Mensaje(BaseModel):
    mensaje: str


RESPUESTAS_ERROR: dict[int | str, dict[str, Any]] = {
    401: {"model": Error, "description": "No autenticado"},
    403: {"model": Error, "description": "Sin permiso"},
    404: {"model": Error, "description": "No encontrado"},
    422: {"model": Error, "description": "Datos inválidos"},
}
