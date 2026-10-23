"""Motor de formularios (P03): formularios versionados, asignaciones, catálogos personalizados, respuestas y evidencias."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, ConVersion, pg_enum


class TipoFormulario(str, enum.Enum):
    captura_operador = "captura_operador"
    atencion_tecnico = "atencion_tecnico"
    preventivo = "preventivo"
    trabajo_especial = "trabajo_especial"
    encuesta = "encuesta"
    libre = "libre"


class EstadoFormulario(str, enum.Enum):
    borrador = "borrador"
    publicado = "publicado"
    archivado = "archivado"


class OrigenRespuesta(str, enum.Enum):
    folio_captura = "folio_captura"
    folio_atencion = "folio_atencion"
    preventivo = "preventivo"
    trabajo_especial = "trabajo_especial"
    encuesta = "encuesta"
    independiente = "independiente"


class EstadoRespuesta(str, enum.Enum):
    en_progreso = "en_progreso"
    enviado = "enviado"


class TipoEvidencia(str, enum.Enum):
    foto = "foto"
    firma = "firma"
    dibujo = "dibujo"
    archivo = "archivo"
    audio = "audio"


def _fk(tabla: str, nulo: bool = False, **kw):
    return mapped_column(UUID(as_uuid=True), ForeignKey(f"{tabla}.id", **kw), nullable=nulo)


class Formulario(ConVersion, Base):
    __tablename__ = "formularios"

    prestador_id: Mapped[uuid.UUID | None] = _fk("prestadores", True)
    tenant_id: Mapped[uuid.UUID | None] = _fk("tenants", True)
    nombre: Mapped[str] = mapped_column(String(160))
    descripcion: Mapped[str] = mapped_column(Text, default="")
    tipo: Mapped[TipoFormulario] = mapped_column(pg_enum(TipoFormulario, "tipo_formulario"), default=TipoFormulario.libre)
    rol_destino: Mapped[list] = mapped_column(JSONB, default=list)
    estado: Mapped[EstadoFormulario] = mapped_column(pg_enum(EstadoFormulario, "estado_formulario"), default=EstadoFormulario.borrador)
    version_publicada_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    es_plantilla_base: Mapped[bool] = mapped_column(Boolean, default=False)
    clonado_de_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class FormularioVersion(ConVersion, Base):
    __tablename__ = "formulario_versiones"

    formulario_id: Mapped[uuid.UUID] = _fk("formularios", ondelete="CASCADE")
    prestador_id: Mapped[uuid.UUID | None] = _fk("prestadores", True)
    tenant_id: Mapped[uuid.UUID | None] = _fk("tenants", True)
    numero_version: Mapped[int] = mapped_column(Integer)
    esquema_json: Mapped[dict] = mapped_column(JSONB)
    publicada_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    publicada_por: Mapped[uuid.UUID | None] = _fk("usuarios", True)
    notas_version: Mapped[str] = mapped_column(Text, default="")


class FormularioAsignacion(ConVersion, Base):
    __tablename__ = "formulario_asignaciones"

    formulario_id: Mapped[uuid.UUID] = _fk("formularios", ondelete="CASCADE")
    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    tenant_id: Mapped[uuid.UUID | None] = _fk("tenants", True)
    tipo_folio: Mapped[str | None] = mapped_column(String(40))
    tipo_equipo_id: Mapped[uuid.UUID | None] = _fk("tipos_equipo", True)
    familia_equipo_id: Mapped[uuid.UUID | None] = _fk("familias_equipo", True)
    # FK diferida: planes_mantenimiento llega en P06; sin constraint hasta entonces.
    plan_mantenimiento_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    prioridad: Mapped[int] = mapped_column(Integer, default=0)
    activa: Mapped[bool] = mapped_column(Boolean, default=True)


class FormularioPermisoMesa(ConVersion, Base):
    __tablename__ = "formulario_permisos_mesa"

    formulario_id: Mapped[uuid.UUID] = _fk("formularios", ondelete="CASCADE")
    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    usuario_id: Mapped[uuid.UUID] = _fk("usuarios")
    puede_editar_publicado: Mapped[bool] = mapped_column(Boolean, default=True)


class CatalogoPersonalizado(ConVersion, Base):
    __tablename__ = "catalogos_personalizados"

    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    tenant_id: Mapped[uuid.UUID | None] = _fk("tenants", True)
    nombre: Mapped[str] = mapped_column(String(120))
    clave: Mapped[str] = mapped_column(String(60))
    activo: Mapped[bool] = mapped_column(Boolean, default=True)


class CatalogoPersonalizadoOpcion(ConVersion, Base):
    __tablename__ = "catalogo_personalizado_opciones"

    catalogo_id: Mapped[uuid.UUID] = _fk("catalogos_personalizados", ondelete="CASCADE")
    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    tenant_id: Mapped[uuid.UUID | None] = _fk("tenants", True)
    valor: Mapped[str] = mapped_column(String(120))
    etiqueta: Mapped[str] = mapped_column(String(200))
    orden: Mapped[int] = mapped_column(Integer, default=0)
    activa: Mapped[bool] = mapped_column(Boolean, default=True)
    padre_opcion_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("catalogo_personalizado_opciones.id"))


class FormularioRespuesta(ConVersion, Base):
    __tablename__ = "formulario_respuestas"

    formulario_id: Mapped[uuid.UUID] = _fk("formularios")
    version_id: Mapped[uuid.UUID] = _fk("formulario_versiones")
    tenant_id: Mapped[uuid.UUID | None] = _fk("tenants", True)
    prestador_id: Mapped[uuid.UUID | None] = _fk("prestadores", True)
    un_id: Mapped[uuid.UUID | None] = _fk("unidades_negocio", True)
    equipo_id: Mapped[uuid.UUID | None] = _fk("equipos", True)
    origen: Mapped[OrigenRespuesta] = mapped_column(pg_enum(OrigenRespuesta, "origen_respuesta"), default=OrigenRespuesta.independiente)
    referencia_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    respuestas_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    contexto_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    respondido_por: Mapped[uuid.UUID] = _fk("usuarios")
    iniciado_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    enviado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    estado: Mapped[EstadoRespuesta] = mapped_column(pg_enum(EstadoRespuesta, "estado_respuesta"), default=EstadoRespuesta.en_progreso)
    dispositivo_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    inmutable: Mapped[bool] = mapped_column(Boolean, default=False)


class FormularioEvidencia(ConVersion, Base):
    __tablename__ = "formulario_evidencias"

    respuesta_id: Mapped[uuid.UUID] = _fk("formulario_respuestas", ondelete="CASCADE")
    tenant_id: Mapped[uuid.UUID | None] = _fk("tenants", True)
    prestador_id: Mapped[uuid.UUID | None] = _fk("prestadores", True)
    campo_clave: Mapped[str] = mapped_column(String(60))
    tipo: Mapped[TipoEvidencia] = mapped_column(pg_enum(TipoEvidencia, "tipo_evidencia"))
    archivo_key: Mapped[str] = mapped_column(String(300))
    archivo_anotado_key: Mapped[str | None] = mapped_column(String(300))
    nombre_original: Mapped[str] = mapped_column(String(255))
    mime: Mapped[str] = mapped_column(String(120))
    bytes: Mapped[int] = mapped_column(Integer)
    ancho_px: Mapped[int | None] = mapped_column(Integer)
    alto_px: Mapped[int | None] = mapped_column(Integer)
    geolat: Mapped[float | None] = mapped_column()
    geolng: Mapped[float | None] = mapped_column()
    exif_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    anotaciones_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    orden: Mapped[int] = mapped_column(Integer, default=0)
    etiqueta: Mapped[str | None] = mapped_column(String(80))
    hash_sha256: Mapped[str] = mapped_column(String(64))
    inmutable: Mapped[bool] = mapped_column(Boolean, default=False)


class CalidadFotoDefault(ConVersion, Base):
    __tablename__ = "calidad_foto_defaults"

    clave: Mapped[str] = mapped_column(String(20), default="global", server_default=text("'global'"))
    tamano_minimo_kb: Mapped[int] = mapped_column(Integer, default=150)
    resolucion_minima_ancho: Mapped[int] = mapped_column(Integer, default=800)
    resolucion_minima_alto: Mapped[int] = mapped_column(Integer, default=600)
    compresion_maxima_pct: Mapped[int] = mapped_column(Integer, default=70)
