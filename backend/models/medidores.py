"""Medidores de activos (§6.9.2), catálogo cerrado de eventos que disparan planes (§6.9.1) y llaves de API por
cliente para recibir lecturas de un SCADA o un ERP. F2-04.

El acumulado es la cifra que mandan los planes por uso: `valor_actual` es lo que dice el marcador y
`valor_acumulado` es lo que el equipo lleva de verdad, corrigiendo reinicios y cambios de medidor con
`acumulado_offset` y `ciclo_inicio` (ver `medidores_service.acumulado_de`).
"""
import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, SmallInteger, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, ConVersion, pg_enum


class CategoriaMedidor(str, enum.Enum):
    """Los seis tipos literales de la tabla de §6.9.2."""
    horas = "horas"
    ciclos = "ciclos"
    distancia = "distancia"
    energia = "energia"
    unidades = "unidades"
    personalizado = "personalizado"


class MetodoActualizacionMedidor(str, enum.Enum):
    """Los cuatro métodos de actualización literales de §6.9.2."""
    tecnico = "tecnico"
    operador = "operador"
    importacion = "importacion"
    estimado = "estimado"


class EstadoLecturaMedidor(str, enum.Enum):
    valida = "valida"
    rechazada = "rechazada"
    en_revision = "en_revision"


class TipoCambioMedidor(str, enum.Enum):
    reinicio = "reinicio"
    reemplazo_medidor = "reemplazo_medidor"


# Claves del catálogo cerrado de `eventos_trigger_catalogo` (se siembran en la migración 0016).
EVENTO_FALLA_GRAVE = "falla_correctiva_grave"
EVENTO_FALLAS_REPETIDAS = "fallas_repetidas"
EVENTO_EQUIPO_INSTALADO = "equipo_instalado"
EVENTO_REEMPLAZO_COMPONENTE = "reemplazo_componente"
EVENTO_CAMBIO_MEDIDOR = "cambio_medidor"
EVENTOS_TRIGGER = (EVENTO_FALLA_GRAVE, EVENTO_FALLAS_REPETIDAS, EVENTO_EQUIPO_INSTALADO,
                   EVENTO_REEMPLAZO_COMPONENTE, EVENTO_CAMBIO_MEDIDOR)

PERMISO_LECTURAS = "medidores.lecturas"


def _fk(tabla: str, nulo: bool = False):
    return mapped_column(UUID(as_uuid=True), ForeignKey(f"{tabla}.id"), nullable=nulo)


class TipoMedidor(ConVersion, Base):
    """Catálogo. Sin prestador ni tenant = global de la plataforma (Superadmin)."""
    __tablename__ = "tipos_medidor"

    prestador_id: Mapped[uuid.UUID | None] = _fk("prestadores", True)
    tenant_id: Mapped[uuid.UUID | None] = _fk("tenants", True)
    nombre: Mapped[str] = mapped_column(String(120))
    unidad: Mapped[str] = mapped_column(String(30))
    categoria: Mapped[CategoriaMedidor] = mapped_column(pg_enum(CategoriaMedidor, "categoria_medidor"),
                                                        default=CategoriaMedidor.personalizado)
    descripcion: Mapped[str] = mapped_column(Text, default="")
    permite_estimacion: Mapped[bool] = mapped_column(Boolean, default=True)
    decimales: Mapped[int] = mapped_column(SmallInteger, default=0)
    requiere_foto: Mapped[bool] = mapped_column(Boolean, default=False)
    factor_salto_maximo: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=Decimal("3"))
    activo: Mapped[bool] = mapped_column(Boolean, default=True)


class EquipoMedidor(ConVersion, Base):
    __tablename__ = "equipo_medidores"

    equipo_id: Mapped[uuid.UUID] = _fk("equipos")
    tipo_medidor_id: Mapped[uuid.UUID] = _fk("tipos_medidor")
    tenant_id: Mapped[uuid.UUID] = _fk("tenants")
    valor_actual: Mapped[Decimal] = mapped_column(Numeric(16, 2), default=Decimal("0"))
    valor_acumulado: Mapped[Decimal] = mapped_column(Numeric(16, 2), default=Decimal("0"))
    valor_ultimo_pm: Mapped[Decimal] = mapped_column(Numeric(16, 2), default=Decimal("0"))
    acumulado_offset: Mapped[Decimal] = mapped_column(Numeric(16, 2), default=Decimal("0"))
    ciclo_inicio: Mapped[Decimal] = mapped_column(Numeric(16, 2), default=Decimal("0"))
    fecha_ultima_lectura: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metodo_actualizacion: Mapped[MetodoActualizacionMedidor] = mapped_column(
        pg_enum(MetodoActualizacionMedidor, "metodo_actualizacion_medidor"), default=MetodoActualizacionMedidor.tecnico)
    valor_maximo: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    numero_serie_medidor: Mapped[str | None] = mapped_column(String(80))
    instalado_en: Mapped[date | None] = mapped_column(Date)
    activo: Mapped[bool] = mapped_column(Boolean, default=True)


class MedidorLectura(ConVersion, Base):
    """Append-only: la medición no se modifica. El trigger `acma_medidor_lectura_inmutable()` solo deja cambiar
    `estado`, `motivo`, `valor_acumulado`, `revisada_por` y `revisada_at`, que es la revisión de las anómalas."""
    __tablename__ = "medidor_lecturas"

    equipo_medidor_id: Mapped[uuid.UUID] = _fk("equipo_medidores")
    equipo_id: Mapped[uuid.UUID] = _fk("equipos")
    tipo_medidor_id: Mapped[uuid.UUID] = _fk("tipos_medidor")
    tenant_id: Mapped[uuid.UUID] = _fk("tenants")
    prestador_id: Mapped[uuid.UUID | None] = _fk("prestadores", True)
    valor: Mapped[Decimal] = mapped_column(Numeric(16, 2))
    valor_acumulado: Mapped[Decimal] = mapped_column(Numeric(16, 2))
    metodo: Mapped[MetodoActualizacionMedidor] = mapped_column(pg_enum(MetodoActualizacionMedidor, "metodo_actualizacion_medidor"))
    registrado_por: Mapped[uuid.UUID | None] = _fk("usuarios", True)
    folio_id: Mapped[uuid.UUID | None] = _fk("folios", True)
    respuesta_id: Mapped[uuid.UUID | None] = _fk("formulario_respuestas", True)
    evidencia_id: Mapped[uuid.UUID | None] = _fk("formulario_evidencias", True)
    llave_api_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    timestamp_dispositivo: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    estado: Mapped[EstadoLecturaMedidor] = mapped_column(pg_enum(EstadoLecturaMedidor, "estado_lectura_medidor"),
                                                         default=EstadoLecturaMedidor.valida)
    motivo: Mapped[str] = mapped_column(Text, default="")
    revisada_por: Mapped[uuid.UUID | None] = _fk("usuarios", True)
    revisada_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MedidorEstimacion(ConVersion, Base):
    __tablename__ = "medidor_estimaciones"

    equipo_medidor_id: Mapped[uuid.UUID] = _fk("equipo_medidores")
    tenant_id: Mapped[uuid.UUID] = _fk("tenants")
    incremento_por_dia: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=Decimal("0"))
    incremento_real_promedio: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    horario_operacion_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    activa: Mapped[bool] = mapped_column(Boolean, default=True)
    desde: Mapped[date] = mapped_column(Date, default=date.today)
    ultima_estimacion_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MedidorCambio(ConVersion, Base):
    __tablename__ = "medidor_cambios"

    equipo_medidor_id: Mapped[uuid.UUID] = _fk("equipo_medidores")
    tenant_id: Mapped[uuid.UUID] = _fk("tenants")
    tipo: Mapped[TipoCambioMedidor] = mapped_column(pg_enum(TipoCambioMedidor, "tipo_cambio_medidor"))
    valor_anterior: Mapped[Decimal] = mapped_column(Numeric(16, 2), default=Decimal("0"))
    valor_nuevo: Mapped[Decimal] = mapped_column(Numeric(16, 2), default=Decimal("0"))
    acumulado_al_cambio: Mapped[Decimal] = mapped_column(Numeric(16, 2), default=Decimal("0"))
    numero_serie_anterior: Mapped[str | None] = mapped_column(String(80))
    numero_serie_nuevo: Mapped[str | None] = mapped_column(String(80))
    motivo: Mapped[str] = mapped_column(Text)
    registrado_por: Mapped[uuid.UUID | None] = _fk("usuarios", True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EventoTriggerCatalogo(ConVersion, Base):
    """Catálogo cerrado: cada clave tiene un gancho en el código que la escucha (§6.9.1 «Por evento»)."""
    __tablename__ = "eventos_trigger_catalogo"

    clave: Mapped[str] = mapped_column(String(60))
    descripcion: Mapped[str] = mapped_column(Text)
    parametros_schema_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    activo: Mapped[bool] = mapped_column(Boolean, default=True)


class LlaveApiTenant(ConVersion, Base):
    """Llave de API del cliente, solo para registrar lecturas de medidor. Se guarda hasheada."""
    __tablename__ = "llaves_api_tenant"

    tenant_id: Mapped[uuid.UUID] = _fk("tenants")
    nombre: Mapped[str] = mapped_column(String(120))
    prefijo: Mapped[str] = mapped_column(String(16))
    llave_hash: Mapped[str] = mapped_column(String(64))
    permisos_json: Mapped[list] = mapped_column(JSONB, default=lambda: [PERMISO_LECTURAS])
    activa: Mapped[bool] = mapped_column(Boolean, default=True)
    creada_por: Mapped[uuid.UUID | None] = _fk("usuarios", True)
    revocada_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revocada_por: Mapped[uuid.UUID | None] = _fk("usuarios", True)
    ultimo_uso_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    usos: Mapped[int] = mapped_column(Integer, default=0)
