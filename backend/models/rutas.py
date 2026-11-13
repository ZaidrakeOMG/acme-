"""Optimización de rutas (VRPTW), reasignación automática, ETA y desvío de ruta (§6.8.2, §6.8.4, §4.1). F2-06.

**El mercado** es el área de operación del prestador. El diseño lo usa (velocidad promedio por mercado, plan de
rutas por mercado y fecha) pero no define la entidad, así que ACMA la modela como un catálogo del prestador que
agrupa las UNs de sus clientes que se atienden juntas: una UN pertenece a un mercado **por prestador**, porque dos
prestadores pueden agrupar la misma sucursal de distinta forma.

**El plan del día** (`rutas_planes`) nace en `borrador` del cálculo del optimizador; el despachador lo revisa, mueve
paradas si quiere y lo **publica**. Publicar es lo que asigna los folios de verdad (con `transicionar()` de P04) y
fija `orden_en_ruta`: hasta entonces el plan es una propuesta y no toca la operación.
"""
import enum
import uuid
from datetime import date, datetime, time
from decimal import Decimal

from geoalchemy2 import Geography
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, Time, func, text
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, ConVersion, pg_enum
from models.folios import TipoFolio


class ModoReasignacionAutomatica(str, enum.Enum):
    """Qué hace el recálculo con lo que encuentra: proponerlo al despachador o aplicarlo y avisar."""
    solo_sugerir = "solo_sugerir"
    aplicar_y_avisar = "aplicar_y_avisar"


class ProveedorDistancias(str, enum.Enum):
    estimado = "estimado"
    google_routes = "google_routes"


class EstadoPlanRuta(str, enum.Enum):
    borrador = "borrador"
    publicado = "publicado"
    en_curso = "en_curso"
    cerrado = "cerrado"


class DisparadorRecalculo(str, enum.Enum):
    desvio = "desvio"
    tiempo_muerto = "tiempo_muerto"
    sla_en_riesgo = "sla_en_riesgo"
    incidencia_tecnico = "incidencia_tecnico"
    folio_nuevo_urgente = "folio_nuevo_urgente"
    reasignacion_forzada = "reasignacion_forzada"
    manual = "manual"


class EstadoRecalculo(str, enum.Enum):
    propuesta = "propuesta"
    aplicada = "aplicada"
    rechazada = "rechazada"
    expirada = "expirada"


# ------------------------------------------------------------------ valores literales (copia de la migración 0018)
# La migración es una foto congelada y no importa modelos; esta es la copia que usa la aplicación al crear la fila,
# y la que leen las pruebas. Es el mismo patrón que `models/criticidad.py` de F2-05.
PESOS_DEFAULT = {
    "distancia": 1,
    "sla": 600,
    "criticidad": 300,
    "folio_sin_asignar": 5000,
    "horas_extra": 240,
    "sin_refaccion": 400,
}
VELOCIDADES_DEFAULT = {
    "00:00-06:00": 45,
    "06:00-09:00": 20,
    "09:00-13:00": 30,
    "13:00-16:00": 28,
    "16:00-20:00": 20,
    "20:00-24:00": 38,
}
FACTOR_SINUOSIDAD_DEFAULT = Decimal("1.40")
DURACION_JORNADA_DEFAULT = 480
TIEMPO_SERVICIO_DEFAULT = 60
UMBRAL_DESVIO_M_DEFAULT = 500
UMBRAL_DESVIO_MIN_DEFAULT = 5
CORREDOR_DESVIO_M_DEFAULT = 2000
SEGUNDOS_LIMITE_DEFAULT = 30
MINUTOS_VIGENCIA_PROPUESTA_DEFAULT = 20

# Peso relativo de cada nivel de criticidad en la función objetivo: un activo A pesa tres veces lo que uno C.
FACTOR_CRITICIDAD = {"A": 3, "B": 2, "C": 1, "D": 0}

# Qué explica cada peso, en lenguaje claro, para la pantalla de configuración.
EXPLICACION_PESOS = {
    "distancia": "Cuánto importa recorrer menos kilómetros. Es el costo base contra el que compiten los demás.",
    "sla": "Cuánto se castiga entregar un folio cuando su SLA ya venció. Súbelo si el cumplimiento es lo primero.",
    "criticidad": "Cuánto se adelantan los activos críticos. Un activo A pesa tres veces lo que uno C.",
    "folio_sin_asignar": "Cuánto se castiga dejar un folio fuera de la ruta. Es el más alto a propósito: ACMA "
                         "prefiere una ruta larga a un folio sin atender.",
    "horas_extra": "Cuánto se castiga que la ruta pase de la jornada del técnico, por cada hora de más.",
    "sin_refaccion": "Cuánto se castiga asignar un folio a quien no trae la refacción en su vehículo.",
}


class Mercado(ConVersion, Base):
    __tablename__ = "mercados"

    prestador_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("prestadores.id"))
    codigo: Mapped[str] = mapped_column(String(40))
    nombre: Mapped[str] = mapped_column(String(160))
    zona_horaria: Mapped[str] = mapped_column(String(64), default="America/Mexico_City")
    centro = mapped_column(Geography(geometry_type="POINT", srid=4326, spatial_index=False), nullable=True)
    activo: Mapped[bool] = mapped_column(Boolean, default=True)


class MercadoUnidad(ConVersion, Base):
    __tablename__ = "mercado_unidades"

    mercado_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("mercados.id"))
    prestador_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("prestadores.id"))
    un_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("unidades_negocio.id"))


class RutasConfiguracion(ConVersion, Base):
    __tablename__ = "rutas_configuracion"

    prestador_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("prestadores.id"))
    mercado_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("mercados.id"))
    pesos_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    hora_inicio_jornada: Mapped[time] = mapped_column(Time, default=time(8, 0))
    duracion_jornada_min: Mapped[int] = mapped_column(Integer, default=DURACION_JORNADA_DEFAULT)
    tiempo_servicio_default_min: Mapped[int] = mapped_column(Integer, default=TIEMPO_SERVICIO_DEFAULT)
    factor_sinuosidad: Mapped[Decimal] = mapped_column(Numeric(4, 2), default=FACTOR_SINUOSIDAD_DEFAULT)
    velocidades_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    modo_reasignacion_automatica: Mapped[ModoReasignacionAutomatica] = mapped_column(
        pg_enum(ModoReasignacionAutomatica, "modo_reasignacion_automatica"),
        default=ModoReasignacionAutomatica.solo_sugerir)
    minutos_vigencia_propuesta: Mapped[int] = mapped_column(Integer, default=MINUTOS_VIGENCIA_PROPUESTA_DEFAULT)
    umbral_desvio_m: Mapped[int] = mapped_column(Integer, default=UMBRAL_DESVIO_M_DEFAULT)
    umbral_desvio_min: Mapped[int] = mapped_column(Integer, default=UMBRAL_DESVIO_MIN_DEFAULT)
    corredor_desvio_m: Mapped[int] = mapped_column(Integer, default=CORREDOR_DESVIO_M_DEFAULT)
    proveedor_distancias: Mapped[ProveedorDistancias] = mapped_column(
        pg_enum(ProveedorDistancias, "proveedor_distancias"), default=ProveedorDistancias.estimado)
    segundos_limite_calculo: Mapped[int] = mapped_column(Integer, default=SEGUNDOS_LIMITE_DEFAULT)
    hora_calculo_automatico: Mapped[time] = mapped_column(Time, default=time(6, 30))
    configurado_por: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("usuarios.id"))


class RutaTiempoServicio(ConVersion, Base):
    __tablename__ = "rutas_tiempos_servicio"

    prestador_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("prestadores.id"))
    tipo_folio: Mapped[TipoFolio] = mapped_column(pg_enum(TipoFolio, "tipo_folio"))
    tipo_equipo_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("tipos_equipo.id"))
    minutos_estimados: Mapped[int] = mapped_column(Integer)
    origen: Mapped[str] = mapped_column(String(30), default="configurado")
    muestras: Mapped[int] = mapped_column(Integer, default=0)


class RutaPlan(ConVersion, Base):
    __tablename__ = "rutas_planes"

    prestador_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("prestadores.id"))
    mercado_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("mercados.id"))
    fecha: Mapped[date] = mapped_column(Date)
    estado: Mapped[EstadoPlanRuta] = mapped_column(pg_enum(EstadoPlanRuta, "estado_plan_ruta"),
                                                   default=EstadoPlanRuta.borrador)
    costo_objetivo: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    distancia_total_km: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0"))
    folios_asignados: Mapped[int] = mapped_column(Integer, default=0)
    folios_sin_asignar: Mapped[int] = mapped_column(Integer, default=0)
    sin_asignar_json: Mapped[list] = mapped_column(JSONB, default=list)
    tiempo_calculo_ms: Mapped[int] = mapped_column(Integer, default=0)
    motor: Mapped[str] = mapped_column(String(40), default="ortools")
    calculado_por: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("usuarios.id"))
    publicado_por: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("usuarios.id"))
    publicado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1)


class RutaParada(ConVersion, Base):
    __tablename__ = "rutas_paradas"

    plan_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("rutas_planes.id"))
    prestador_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("prestadores.id"))
    tecnico_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("usuarios.id"))
    folio_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("folios.id"))
    orden: Mapped[int] = mapped_column(Integer)
    llegada_estimada: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    inicio_servicio_estimado: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fin_estimado: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    distancia_desde_anterior_km: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0"))
    minutos_desde_anterior: Mapped[int] = mapped_column(Integer, default=0)
    minutos_servicio: Mapped[int] = mapped_column(Integer, default=0)
    ventana_ok: Mapped[bool] = mapped_column(Boolean, default=True)
    sla_ok: Mapped[bool] = mapped_column(Boolean, default=True)
    holgura_sla_min: Mapped[int | None] = mapped_column(Integer)
    fijo: Mapped[bool] = mapped_column(Boolean, default=False)


class RutaTrazo(ConVersion, Base):
    __tablename__ = "rutas_trazos"

    plan_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("rutas_planes.id"))
    prestador_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("prestadores.id"))
    tecnico_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("usuarios.id"))
    geometria = mapped_column(Geography(geometry_type="LINESTRING", srid=4326, spatial_index=False))
    proveedor: Mapped[ProveedorDistancias] = mapped_column(pg_enum(ProveedorDistancias, "proveedor_distancias"),
                                                           default=ProveedorDistancias.estimado)
    version: Mapped[int] = mapped_column(Integer, default=1)


class RutaRecalculo(ConVersion, Base):
    __tablename__ = "rutas_recalculos"

    plan_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("rutas_planes.id"))
    prestador_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("prestadores.id"))
    disparador: Mapped[DisparadorRecalculo] = mapped_column(pg_enum(DisparadorRecalculo, "disparador_recalculo"))
    disparado_por_folio_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("folios.id"))
    disparado_por_tecnico_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("usuarios.id"))
    tecnicos_afectados: Mapped[list] = mapped_column(JSONB, default=list)
    folios_movidos_json: Mapped[list] = mapped_column(JSONB, default=list)
    propuesta_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    motivo: Mapped[str] = mapped_column(Text, default="")
    estado: Mapped[EstadoRecalculo] = mapped_column(pg_enum(EstadoRecalculo, "estado_recalculo"),
                                                    default=EstadoRecalculo.propuesta)
    vence_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decidido_por: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("usuarios.id"))
    decidido_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    tiempo_calculo_ms: Mapped[int] = mapped_column(Integer, default=0)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DistanciaCache(Base):
    """Caché persistente de distancias. No tiene dueño: es geografía, no dato de nadie."""
    __tablename__ = "distancias_cache"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True,
                                          server_default=text("gen_random_uuid()"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    version_hash: Mapped[str | None] = mapped_column(String(64))
    origen_hash: Mapped[str] = mapped_column(String(64))
    destino_hash: Mapped[str] = mapped_column(String(64))
    franja: Mapped[str] = mapped_column(String(20))
    proveedor: Mapped[ProveedorDistancias] = mapped_column(pg_enum(ProveedorDistancias, "proveedor_distancias"))
    metros: Mapped[int] = mapped_column(Integer)
    segundos: Mapped[int] = mapped_column(Integer)
    calculado_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
