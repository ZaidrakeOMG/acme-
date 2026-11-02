"""Catálogos maestros (P02): técnicos, habilidades, severidades, equipos, tipos de falla, matriz e importaciones."""
import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, SmallInteger, String, Text
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, ConVersion, pg_enum


class EstadoActivo(str, enum.Enum):
    activo = "activo"
    inactivo = "inactivo"
    baja = "baja"


class OrigenHabilidad(str, enum.Enum):
    manual = "manual"
    curso = "curso"


class CoberturaContrato(str, enum.Enum):
    todas_las_un = "todas_las_un"
    equipos_especificos = "equipos_especificos"


class EstadoImportacion(str, enum.Enum):
    vista_previa = "vista_previa"
    confirmada = "confirmada"
    cancelada = "cancelada"


def _fk(tabla: str, nulo: bool = False):
    return mapped_column(UUID(as_uuid=True), ForeignKey(f"{tabla}.id"), nullable=nulo)


class Habilidad(ConVersion, Base):
    __tablename__ = "habilidades"

    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    clave: Mapped[str] = mapped_column(String(60))
    nombre: Mapped[str] = mapped_column(String(120))
    descripcion: Mapped[str] = mapped_column(Text, default="")
    activa: Mapped[bool] = mapped_column(Boolean, default=True)


class Tecnico(ConVersion, Base):
    __tablename__ = "tecnicos"

    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    usuario_id: Mapped[uuid.UUID] = _fk("usuarios")
    numero_empleado: Mapped[str | None] = mapped_column(String(40))
    telefono: Mapped[str | None] = mapped_column(String(30))
    vehiculo_placas: Mapped[str | None] = mapped_column(String(20))
    estado: Mapped[EstadoActivo] = mapped_column(pg_enum(EstadoActivo, "estado_activo"), default=EstadoActivo.activo)
    fecha_ingreso: Mapped[date | None] = mapped_column(Date)


class TecnicoHabilidad(ConVersion, Base):
    __tablename__ = "tecnico_habilidades"

    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    tecnico_id: Mapped[uuid.UUID] = _fk("tecnicos")
    habilidad_id: Mapped[uuid.UUID] = _fk("habilidades")
    certificada: Mapped[bool] = mapped_column(Boolean, default=False)
    fecha_certificacion: Mapped[date | None] = mapped_column(Date)
    vigencia_hasta: Mapped[date | None] = mapped_column(Date)
    origen: Mapped[OrigenHabilidad] = mapped_column(pg_enum(OrigenHabilidad, "origen_habilidad"), default=OrigenHabilidad.manual)


class TecnicoTenantHabilitado(ConVersion, Base):
    __tablename__ = "tecnico_tenants_habilitados"

    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    tecnico_id: Mapped[uuid.UUID] = _fk("tecnicos")
    tenant_id: Mapped[uuid.UUID] = _fk("tenants")
    habilitado_por: Mapped[uuid.UUID | None] = _fk("usuarios", True)
    fecha_habilitacion: Mapped[date] = mapped_column(Date, default=date.today)
    activo: Mapped[bool] = mapped_column(Boolean, default=True)


class NivelSeveridadCatalogo(ConVersion, Base):
    __tablename__ = "niveles_severidad"

    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    clave: Mapped[str] = mapped_column(String(40))
    nombre: Mapped[str] = mapped_column(String(60))
    orden: Mapped[int] = mapped_column(SmallInteger)
    color_hex: Mapped[str] = mapped_column(String(7))
    tiempo_respuesta_horas: Mapped[int] = mapped_column(Integer)
    tiempo_resolucion_horas: Mapped[int] = mapped_column(Integer)
    activo: Mapped[bool] = mapped_column(Boolean, default=True)


class FamiliaEquipo(ConVersion, Base):
    __tablename__ = "familias_equipo"

    tenant_id: Mapped[uuid.UUID | None] = _fk("tenants", True)
    nombre: Mapped[str] = mapped_column(String(120))
    descripcion: Mapped[str] = mapped_column(Text, default="")
    activa: Mapped[bool] = mapped_column(Boolean, default=True)
    habilidad_clave: Mapped[str | None] = mapped_column(String(60))  # P04: habilidad requerida al asignar técnico


class TipoEquipo(ConVersion, Base):
    __tablename__ = "tipos_equipo"

    familia_id: Mapped[uuid.UUID] = _fk("familias_equipo")
    tenant_id: Mapped[uuid.UUID | None] = _fk("tenants", True)
    nombre: Mapped[str] = mapped_column(String(120))
    descripcion: Mapped[str] = mapped_column(Text, default="")
    activa: Mapped[bool] = mapped_column(Boolean, default=True)
    # P09 §6.9.4: costo/hora de inactividad por tipo de equipo que configura el tenant (el del equipo manda sobre este).
    costo_hora_inactividad_default: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))


class Equipo(ConVersion, Base):
    __tablename__ = "equipos"

    tenant_id: Mapped[uuid.UUID] = _fk("tenants")
    un_id: Mapped[uuid.UUID] = _fk("unidades_negocio")
    tipo_equipo_id: Mapped[uuid.UUID] = _fk("tipos_equipo")
    codigo: Mapped[str] = mapped_column(String(60))
    nombre: Mapped[str] = mapped_column(String(160))
    marca: Mapped[str | None] = mapped_column(String(80))
    modelo: Mapped[str | None] = mapped_column(String(80))
    numero_serie: Mapped[str | None] = mapped_column(String(80))
    fecha_instalacion: Mapped[date | None] = mapped_column(Date)
    valor_reposicion: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    estado: Mapped[EstadoActivo] = mapped_column(pg_enum(EstadoActivo, "estado_activo"), default=EstadoActivo.activo)
    garantia_vigente_hasta: Mapped[date | None] = mapped_column(Date)
    contrato_id: Mapped[uuid.UUID | None] = _fk("contratos", True)
    notas: Mapped[str] = mapped_column(Text, default="")
    # P04: criticidad A/B/C/D capturada a mano por Admin empresa (cálculo automático §6.9.3 en Fase 2).
    criticidad: Mapped[str | None] = mapped_column(ENUM("A", "B", "C", "D", name="criticidad_activo", create_type=False), nullable=True)
    # P09 §6.9.4: datos económicos del activo para la depreciación y el TCO.
    costo_adquisicion: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    fecha_adquisicion: Mapped[date | None] = mapped_column(Date)
    costo_hora_inactividad: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    numero_activo_fijo_erp: Mapped[str | None] = mapped_column(String(60))


class TipoFalla(ConVersion, Base):
    __tablename__ = "tipos_falla"

    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    descripcion: Mapped[str] = mapped_column(String(200))
    familia_equipo_id: Mapped[uuid.UUID] = _fk("familias_equipo")
    requiere_revision_manual: Mapped[bool] = mapped_column(Boolean, default=False)
    activa: Mapped[bool] = mapped_column(Boolean, default=True)


class TipoFallaSeveridad(ConVersion, Base):
    __tablename__ = "tipo_falla_severidad"

    tenant_id: Mapped[uuid.UUID] = _fk("tenants")
    tipo_falla_id: Mapped[uuid.UUID] = _fk("tipos_falla")
    tipo_equipo_id: Mapped[uuid.UUID] = _fk("tipos_equipo")
    nivel_severidad_id: Mapped[uuid.UUID] = _fk("niveles_severidad")
    configurado_por: Mapped[uuid.UUID | None] = _fk("usuarios", True)
    activa: Mapped[bool] = mapped_column(Boolean, default=True)


class ImportacionCatalogo(ConVersion, Base):
    __tablename__ = "importaciones_catalogo"

    tenant_id: Mapped[uuid.UUID | None] = _fk("tenants", True)
    prestador_id: Mapped[uuid.UUID | None] = _fk("prestadores", True)
    catalogo: Mapped[str] = mapped_column(String(40))
    archivo_nombre: Mapped[str] = mapped_column(String(255))
    archivo_key: Mapped[str] = mapped_column(String(300))
    total_filas: Mapped[int] = mapped_column(Integer, default=0)
    filas_ok: Mapped[int] = mapped_column(Integer, default=0)
    filas_error: Mapped[int] = mapped_column(Integer, default=0)
    errores_json: Mapped[list] = mapped_column(JSONB, default=list)
    duplicados_json: Mapped[list] = mapped_column(JSONB, default=list)
    filas_validas_json: Mapped[list] = mapped_column(JSONB, default=list)
    estado: Mapped[EstadoImportacion] = mapped_column(
        pg_enum(EstadoImportacion, "estado_importacion"), default=EstadoImportacion.vista_previa
    )
    ejecutada_por: Mapped[uuid.UUID | None] = _fk("usuarios", True)
    confirmada_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
