"""Análisis de criticidad y gestión de riesgo por activo (ISO 55000, §6.9.3). F2-05.

El nivel usa el mismo ENUM `criticidad_activo` que `equipos.criticidad` (P04), porque son el mismo dato: el campo
del equipo es el que leen la aprobación multinivel y el resto del sistema, y `criticidad_service` lo sincroniza
desde aquí.
"""
import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Numeric, SmallInteger, String, Text, func, text
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, ConVersion, pg_enum


class OrigenCriticidad(str, enum.Enum):
    calculado = "calculado"
    manual = "manual"


class MotivoEvaluacion(str, enum.Enum):
    evaluacion_inicial = "evaluacion_inicial"
    revision_periodica = "revision_periodica"
    recalculo_por_historial = "recalculo_por_historial"
    ajuste_manual = "ajuste_manual"
    cambio_configuracion = "cambio_configuracion"


class OrigenModoFalla(str, enum.Enum):
    sugerido = "sugerido"
    manual = "manual"


class TipoMitigacion(str, enum.Enum):
    plan_preventivo = "plan_preventivo"
    capacitacion = "capacitacion"
    refaccion_en_inventario = "refaccion_en_inventario"
    rediseno = "rediseno"
    otro = "otro"


class EstadoMitigacion(str, enum.Enum):
    propuesta = "propuesta"
    en_proceso = "en_proceso"
    implementada = "implementada"
    descartada = "descartada"


# Las cuatro dimensiones de impacto de §6.9.3, en el orden de la tabla del diseño.
DIMENSIONES = ("operacional", "seguridad", "economico", "imagen")

# Valores literales de §6.9.3 con los que nace la configuración de un cliente. La migración 0017 tiene su propia
# copia como DEFAULT de las columnas (una migración es una foto congelada y no debe importar modelos); esta es la
# que usa la aplicación al crear la fila, y es la que leen las pruebas de la fórmula.
PESOS_DEFAULT = {"operacional": 30, "seguridad": 35, "economico": 25, "imagen": 10}
RANGOS_ECONOMICO_DEFAULT = [
    {"nivel": 1, "hasta": 5000, "texto": "Menor a $5,000"},
    {"nivel": 2, "hasta": 25000, "texto": "De $5,000 a $25,000"},
    {"nivel": 3, "hasta": 100000, "texto": "De $25,000 a $100,000"},
    {"nivel": 4, "hasta": 500000, "texto": "De $100,000 a $500,000"},
    {"nivel": 5, "hasta": None, "texto": "Mayor a $500,000"},
]
ESCALA_PROBABILIDAD_DEFAULT = {
    "meses": 12,
    "minimo_meses_historia": 6,
    "por_fallas": [
        {"nivel": 1, "hasta": 0, "texto": "Sin fallas en 12 meses"},
        {"nivel": 2, "hasta": 2, "texto": "1 o 2 fallas en 12 meses"},
        {"nivel": 3, "hasta": 5, "texto": "De 3 a 5 fallas en 12 meses"},
        {"nivel": 4, "hasta": 11, "texto": "De 6 a 11 fallas en 12 meses"},
        {"nivel": 5, "hasta": None, "texto": "12 fallas o más en 12 meses"},
    ],
    "por_mtbf": [],
    "minimo_fallas_para_mtbf": 3,
}
RANGOS_NIVEL_DEFAULT = [
    {"nivel": "A", "desde": 80, "hasta": 100, "etiqueta": "Crítico"},
    {"nivel": "B", "desde": 50, "hasta": 79, "etiqueta": "Importante"},
    {"nivel": "C", "desde": 20, "hasta": 49, "etiqueta": "Estándar"},
    {"nivel": "D", "desde": 0, "hasta": 19, "etiqueta": "No crítico"},
]
IMPLICACIONES_DEFAULT = {
    "pm_obligatorio": {"alerta": True, "restriccion": False},
    "respuesta_maxima": {"alerta": True, "restriccion": False, "horas_a": 4, "horas_b": 8, "aviso_pct": 80},
    "tecnico_certificado": {"alerta": True, "restriccion": False},
    "refaccion_en_inventario": {"alerta": True, "restriccion": False},
}
MESES_REVISION_DEFAULT = 12

# Niveles de criticidad con sus implicaciones literales, para la interfaz y los reportes.
IMPLICACIONES_POR_NIVEL = {
    "A": "PM obligatorio con plan definido. Respuesta a correctivos máximo 4 horas. Técnico especialista requerido. "
         "Refacciones siempre en inventario.",
    "B": "PM programado. Respuesta máximo 8 horas. Técnico certificado requerido.",
    "C": "PM recomendado. Tiempo de respuesta estándar del SLA.",
    "D": "Mantenimiento correctivo reactivo suficiente. Sin prioridad de inventario.",
}
ETIQUETA_NIVEL = {"A": "Crítico", "B": "Importante", "C": "Estándar", "D": "No crítico"}


def _nivel():
    """Mismo ENUM que `equipos.criticidad`: es el mismo dato."""
    return mapped_column(ENUM("A", "B", "C", "D", name="criticidad_activo", create_type=False))


def _fk(tabla: str, nulo: bool = False):
    return mapped_column(UUID(as_uuid=True), ForeignKey(f"{tabla}.id"), nullable=nulo)


class CriticidadConfiguracion(ConVersion, Base):
    """Pesos, escalas y rangos por cliente. Un CHECK exige que los pesos sumen 100."""
    __tablename__ = "criticidad_configuracion"

    tenant_id: Mapped[uuid.UUID] = _fk("tenants")
    pesos_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    rangos_economico_json: Mapped[list] = mapped_column(JSONB, default=list)
    escala_probabilidad_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    rangos_nivel_json: Mapped[list] = mapped_column(JSONB, default=list)
    meses_revision: Mapped[int] = mapped_column(SmallInteger, default=12)
    implicaciones_activas_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    configurado_por: Mapped[uuid.UUID | None] = _fk("usuarios", True)


class ActivoCriticidad(ConVersion, Base):
    __tablename__ = "activo_criticidad"

    equipo_id: Mapped[uuid.UUID] = _fk("equipos")
    tenant_id: Mapped[uuid.UUID] = _fk("tenants")
    indice_criticidad: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=Decimal("0"))
    nivel: Mapped[str] = _nivel()
    probabilidad: Mapped[Decimal] = mapped_column(Numeric(4, 2), default=Decimal("1"))
    probabilidad_estimada: Mapped[bool] = mapped_column(Boolean, default=False)
    probabilidad_origen: Mapped[str] = mapped_column(String(40), default="historial_equipo")
    impacto_ponderado: Mapped[Decimal] = mapped_column(Numeric(4, 2), default=Decimal("1"))
    dimensiones_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    origen: Mapped[OrigenCriticidad] = mapped_column(pg_enum(OrigenCriticidad, "origen_criticidad"),
                                                     default=OrigenCriticidad.calculado)
    razon_manual: Mapped[str] = mapped_column(Text, default="")
    evaluado_por: Mapped[uuid.UUID | None] = _fk("usuarios", True)
    fecha_evaluacion: Mapped[date] = mapped_column(Date, default=date.today)
    proxima_revision: Mapped[date | None] = mapped_column(Date)


class CriticidadEvaluacion(ConVersion, Base):
    """Append-only: la traza que lee una auditoría ISO 55000."""
    __tablename__ = "criticidad_evaluaciones"

    equipo_id: Mapped[uuid.UUID] = _fk("equipos")
    tenant_id: Mapped[uuid.UUID] = _fk("tenants")
    indice_anterior: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    indice_nuevo: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    nivel_anterior: Mapped[str | None] = mapped_column(ENUM("A", "B", "C", "D", name="criticidad_activo", create_type=False), nullable=True)
    nivel_nuevo: Mapped[str] = _nivel()
    dimensiones_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    probabilidad: Mapped[Decimal] = mapped_column(Numeric(4, 2), default=Decimal("1"))
    impacto_ponderado: Mapped[Decimal] = mapped_column(Numeric(4, 2), default=Decimal("1"))
    motivo: Mapped[MotivoEvaluacion] = mapped_column(pg_enum(MotivoEvaluacion, "motivo_evaluacion_criticidad"))
    razon: Mapped[str] = mapped_column(Text, default="")
    evaluado_por: Mapped[uuid.UUID | None] = _fk("usuarios", True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ActivoModoFalla(ConVersion, Base):
    """FMEA simplificado: de un equipo **o** genérico de un tipo de equipo (CHECK excluyente)."""
    __tablename__ = "activo_modos_falla"

    tenant_id: Mapped[uuid.UUID] = _fk("tenants")
    equipo_id: Mapped[uuid.UUID | None] = _fk("equipos", True)
    tipo_equipo_id: Mapped[uuid.UUID | None] = _fk("tipos_equipo", True)
    descripcion_falla: Mapped[str] = mapped_column(String(300))
    tipo_falla_id: Mapped[uuid.UUID | None] = _fk("tipos_falla", True)
    causa_probable: Mapped[str] = mapped_column(Text, default="")
    efecto_operacional: Mapped[str] = mapped_column(Text, default="")
    severidad: Mapped[int] = mapped_column(SmallInteger, default=3)
    frecuencia_historica: Mapped[int] = mapped_column(SmallInteger, default=1)
    fallas_12m: Mapped[int] = mapped_column(SmallInteger, default=0)
    deteccion: Mapped[int | None] = mapped_column(SmallInteger)
    nivel_riesgo: Mapped[int] = mapped_column(SmallInteger, default=3)
    origen: Mapped[OrigenModoFalla] = mapped_column(pg_enum(OrigenModoFalla, "origen_modo_falla"),
                                                    default=OrigenModoFalla.manual)
    activo: Mapped[bool] = mapped_column(Boolean, default=True)
    registrado_por: Mapped[uuid.UUID | None] = _fk("usuarios", True)


class ActivoRiesgoMitigacion(ConVersion, Base):
    __tablename__ = "activo_riesgo_mitigacion"

    modo_falla_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("activo_modos_falla.id", ondelete="CASCADE"))
    tenant_id: Mapped[uuid.UUID] = _fk("tenants")
    accion_mitigacion: Mapped[str] = mapped_column(Text)
    tipo: Mapped[TipoMitigacion] = mapped_column(pg_enum(TipoMitigacion, "tipo_mitigacion"), default=TipoMitigacion.otro)
    plan_mantenimiento_id: Mapped[uuid.UUID | None] = _fk("planes_mantenimiento", True)
    curso_id: Mapped[uuid.UUID | None] = _fk("cursos_catalogo", True)
    articulo_id: Mapped[uuid.UUID | None] = _fk("articulos", True)
    responsable_id: Mapped[uuid.UUID | None] = _fk("usuarios", True)
    fecha_compromiso: Mapped[date | None] = mapped_column(Date)
    fecha_implementacion: Mapped[date | None] = mapped_column(Date)
    estado: Mapped[EstadoMitigacion] = mapped_column(pg_enum(EstadoMitigacion, "estado_mitigacion"),
                                                     default=EstadoMitigacion.propuesta)
    efectividad_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    evidencia_key: Mapped[str | None] = mapped_column(String(400))
    razon_descarte: Mapped[str] = mapped_column(Text, default="")
    registrado_por: Mapped[uuid.UUID | None] = _fk("usuarios", True)
