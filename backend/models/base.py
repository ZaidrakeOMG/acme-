"""Base declarativa y columnas comunes (§6.2 capa 1: id, created_at, updated_at, version_hash).

El esquema real lo define la migración Alembic 0001 (SQL explícito: RLS, triggers,
particiones). Estos modelos lo reflejan para el ORM; `updated_at` y `version_hash`
los calcula el trigger `acma_version()`.
"""
import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, FetchedValue, String, func, text
from sqlalchemy.dialects.postgresql import ENUM, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ConVersion:
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=FetchedValue(), server_onupdate=FetchedValue()
    )
    version_hash: Mapped[str | None] = mapped_column(
        String(64), server_default=FetchedValue(), server_onupdate=FetchedValue()
    )

    __mapper_args__ = {"eager_defaults": True}


class Rol(str, enum.Enum):
    superadmin = "superadmin"
    admin_prestador = "admin_prestador"
    direccion_prestador = "direccion_prestador"
    mesa_control = "mesa_control"
    despachador = "despachador"
    supervisor_prestador = "supervisor_prestador"
    tecnico = "tecnico"
    admin_empresa = "admin_empresa"
    admin_un = "admin_un"
    supervisor_operadores = "supervisor_operadores"
    operador = "operador"


class Dominio(str, enum.Enum):
    tenant = "tenant"
    prestador = "prestador"
    plataforma = "plataforma"


class EstadoRegistro(str, enum.Enum):
    activo = "activo"
    inactivo = "inactivo"
    suspendido = "suspendido"


class NivelSeveridad(str, enum.Enum):
    muy_baja = "muy_baja"
    baja = "baja"
    media = "media"
    alta = "alta"
    critica = "critica"


class ModalidadContrato(str, enum.Enum):
    evento = "evento"
    iguala = "iguala"


class UnidadTiempo(str, enum.Enum):
    horas = "horas"
    dias = "dias"
    semanas = "semanas"
    meses = "meses"


class TipoPenalizacion(str, enum.Enum):
    monto = "monto"
    porcentaje = "porcentaje"


class TipoUmbral(str, enum.Enum):
    porcentaje = "porcentaje"
    minutos = "minutos"
    horas = "horas"
    dias = "dias"
    metros = "metros"
    cantidad = "cantidad"


class AplicaPermiso(str, enum.Enum):
    tecnico = "tecnico"
    despachador = "despachador"


class EstadoAlerta(str, enum.Enum):
    disparada = "disparada"
    vista = "vista"
    resuelta = "resuelta"


def pg_enum(tipo: type[enum.Enum], nombre: str) -> ENUM:
    return ENUM(tipo, name=nombre, create_type=False, values_callable=lambda e: [m.value for m in e])


ROLES_TENANT = {Rol.admin_empresa, Rol.admin_un, Rol.supervisor_operadores, Rol.operador}
ROLES_PRESTADOR = {
    Rol.admin_prestador, Rol.direccion_prestador, Rol.mesa_control,
    Rol.despachador, Rol.supervisor_prestador, Rol.tecnico,
}
ROLES_MFA_OBLIGATORIO = {Rol.superadmin, Rol.admin_prestador, Rol.admin_empresa, Rol.direccion_prestador}


def dominio_de_rol(rol: Rol) -> Dominio:
    if rol == Rol.superadmin:
        return Dominio.plataforma
    return Dominio.tenant if rol in ROLES_TENANT else Dominio.prestador
