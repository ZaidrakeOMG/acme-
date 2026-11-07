"""Capacitación y certificación de técnicos (§6.10.3) y biblioteca de manuales con contenido de servicio
contractual (§6.10.4). El esquema real lo define la migración 0013. F2-01.
"""
import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, SmallInteger, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, ConVersion, pg_enum


def _fk(tabla: str, nulo: bool = False):
    return mapped_column(UUID(as_uuid=True), ForeignKey(f"{tabla}.id"), nullable=nulo)


class TipoCurso(str, enum.Enum):
    curso = "curso"
    certificacion = "certificacion"


class EstadoCursoTecnico(str, enum.Enum):
    vigente = "vigente"
    por_vencer = "por_vencer"
    vencido = "vencido"
    sin_vigencia = "sin_vigencia"       # el curso no caduca (vigencia_meses nulo)


class CategoriaManual(str, enum.Enum):
    ficha_tecnica = "ficha_tecnica"
    procedimiento = "procedimiento"
    diagrama = "diagrama"
    refacciones = "refacciones"
    otro = "otro"


class CursoCatalogo(ConVersion, Base):
    """Catálogo de cursos y certificaciones. `prestador_id` nulo = catálogo global del Superadmin."""

    __tablename__ = "cursos_catalogo"

    prestador_id: Mapped[uuid.UUID | None] = _fk("prestadores", True)
    nombre: Mapped[str] = mapped_column(String(200))
    proveedor: Mapped[str | None] = mapped_column(String(200))
    duracion_horas: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    vigencia_meses: Mapped[int | None] = mapped_column(SmallInteger)   # nulo = no vence
    habilidad_id: Mapped[uuid.UUID | None] = _fk("habilidades", True)
    tipo: Mapped[TipoCurso] = mapped_column(pg_enum(TipoCurso, "tipo_curso"), default=TipoCurso.curso)
    norma_referencia: Mapped[str | None] = mapped_column(String(160))  # p. ej. «NOM-STPS / DC-3»
    descripcion: Mapped[str] = mapped_column(Text, default="")
    activo: Mapped[bool] = mapped_column(Boolean, default=True)


class TecnicoCurso(ConVersion, Base):
    """Historial de cursos por técnico. `estado` lo recalculan el servicio y la tarea diaria."""

    __tablename__ = "tecnico_cursos"

    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    tecnico_id: Mapped[uuid.UUID] = _fk("tecnicos")
    curso_id: Mapped[uuid.UUID] = _fk("cursos_catalogo")
    fecha_inicio: Mapped[date | None] = mapped_column(Date)
    fecha_fin: Mapped[date] = mapped_column(Date)
    calificacion: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    aprobado: Mapped[bool] = mapped_column(Boolean, default=True)
    certificado_key: Mapped[str | None] = mapped_column(String(300))
    certificado_nombre: Mapped[str | None] = mapped_column(String(255))
    certificado_mime: Mapped[str | None] = mapped_column(String(120))
    folio_constancia: Mapped[str | None] = mapped_column(String(80))
    vigente_hasta: Mapped[date | None] = mapped_column(Date)
    vigencia_editada: Mapped[bool] = mapped_column(Boolean, default=False)
    razon_vigencia: Mapped[str] = mapped_column(Text, default="")
    estado: Mapped[EstadoCursoTecnico] = mapped_column(pg_enum(EstadoCursoTecnico, "estado_curso_tecnico"),
                                                       default=EstadoCursoTecnico.sin_vigencia)
    # Habilidad que este curso respaldó al registrarse (§6.10.3: el sistema las vincula solo).
    habilidad_otorgada_id: Mapped[uuid.UUID | None] = _fk("habilidades", True)
    registrado_por: Mapped[uuid.UUID | None] = _fk("usuarios", True)
    notas: Mapped[str] = mapped_column(Text, default="")


class CapacitacionAlertasConfig(ConVersion, Base):
    __tablename__ = "capacitacion_alertas_config"

    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    dias_anticipacion: Mapped[int] = mapped_column(SmallInteger, default=30)
    notificar_cliente: Mapped[bool] = mapped_column(Boolean, default=False)
    activa: Mapped[bool] = mapped_column(Boolean, default=True)


class BibliotecaManual(ConVersion, Base):
    """Manual técnico por tipo de equipo. Cada nueva versión reemplaza la vigente y deja fila en el historial."""

    __tablename__ = "biblioteca_manuales"

    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    tipo_equipo_id: Mapped[uuid.UUID] = _fk("tipos_equipo")
    titulo: Mapped[str] = mapped_column(String(200))
    categoria: Mapped[CategoriaManual] = mapped_column(pg_enum(CategoriaManual, "categoria_manual"),
                                                       default=CategoriaManual.otro)
    descripcion: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[int] = mapped_column(Integer, default=1)
    fecha_subida: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    archivo_key: Mapped[str] = mapped_column(String(300))
    nombre_original: Mapped[str] = mapped_column(String(255))
    mime: Mapped[str] = mapped_column(String(120))
    bytes: Mapped[int] = mapped_column(Integer)
    hash_sha256: Mapped[str] = mapped_column(String(64))
    activo: Mapped[bool] = mapped_column(Boolean, default=True)
    subido_por: Mapped[uuid.UUID | None] = _fk("usuarios", True)


class BibliotecaVersion(ConVersion, Base):
    """Historial de versiones. **Append-only**: trigger de inmutabilidad en la base."""

    __tablename__ = "biblioteca_versiones"

    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    manual_id: Mapped[uuid.UUID] = _fk("biblioteca_manuales")
    version_anterior: Mapped[int] = mapped_column(Integer)
    archivo_key_anterior: Mapped[str] = mapped_column(String(300))
    nombre_original_anterior: Mapped[str | None] = mapped_column(String(255))
    bytes_anterior: Mapped[int | None] = mapped_column(Integer)
    hash_sha256_anterior: Mapped[str | None] = mapped_column(String(64))
    reemplazado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    reemplazado_por: Mapped[uuid.UUID | None] = _fk("usuarios", True)
    notas_version: Mapped[str] = mapped_column(Text, default="")


class ContenidoServicio(ConVersion, Base):
    """Contenido de servicio contractual del cliente: confidencial de su tenant (§6.10.4)."""

    __tablename__ = "contenido_servicio"

    tenant_id: Mapped[uuid.UUID] = _fk("tenants")
    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    tipo_equipo_id: Mapped[uuid.UUID] = _fk("tipos_equipo")
    contrato_id: Mapped[uuid.UUID] = _fk("contratos")
    titulo: Mapped[str] = mapped_column(String(200))
    # Lista ordenada de {clave, descripcion, obligatorio}.
    puntos_revision_json: Mapped[list] = mapped_column(JSONB, default=list)
    periodicidad: Mapped[str | None] = mapped_column(String(80))
    correctivos_iguala: Mapped[int | None] = mapped_column(Integer)
    preventivos_iguala_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    archivo_key: Mapped[str | None] = mapped_column(String(300))
    nombre_original: Mapped[str | None] = mapped_column(String(255))
    mime: Mapped[str | None] = mapped_column(String(120))
    bytes: Mapped[int | None] = mapped_column(Integer)
    version: Mapped[int] = mapped_column(Integer, default=1)
    activo: Mapped[bool] = mapped_column(Boolean, default=True)
    subido_por: Mapped[uuid.UUID | None] = _fk("usuarios", True)


class TecnicoDescargaOffline(ConVersion, Base):
    __tablename__ = "tecnico_descargas_offline"

    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    tecnico_id: Mapped[uuid.UUID] = _fk("tecnicos")
    manual_id: Mapped[uuid.UUID | None] = _fk("biblioteca_manuales", True)
    contenido_id: Mapped[uuid.UUID | None] = _fk("contenido_servicio", True)
    fecha_descarga: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    version_descargada: Mapped[int] = mapped_column(Integer)
    en_dispositivo: Mapped[bool] = mapped_column(Boolean, default=True)
    dispositivo_id: Mapped[str | None] = mapped_column(String(120))
