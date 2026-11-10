"""Operaciones en tiempo real (§6.8.4): jornada del técnico, pausas, posiciones GPS y seguimiento de alertas. F2-03.

`tecnico_posiciones` es un flujo de solo inserción particionado por día: no lleva las columnas de versión de §6.2
capa 1 ni su trigger, por la misma razón que la auditoría de P01 (100 posiciones por minuto con 50 técnicos).
"""
import enum
import uuid
from datetime import datetime
from decimal import Decimal

from geoalchemy2 import Geography
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, SmallInteger, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, ConVersion, pg_enum


class EstatusOperativo(str, enum.Enum):
    fuera_de_jornada = "fuera_de_jornada"
    en_ruta = "en_ruta"
    en_servicio = "en_servicio"
    pausa = "pausa"
    sin_senal = "sin_senal"


class EstadoJornada(str, enum.Enum):
    activa = "activa"
    pausa = "pausa"
    cerrada = "cerrada"


class CerradaPorJornada(str, enum.Enum):
    tecnico = "tecnico"
    sistema = "sistema"
    despachador = "despachador"


class MotivoPausaJornada(str, enum.Enum):
    comida = "comida"
    tramite = "tramite"
    otro = "otro"


class RespuestaAlertaTecnico(str, enum.Enum):
    estoy_bien = "estoy_bien"
    necesito_apoyo = "necesito_apoyo"


def _fk(tabla: str, nulo: bool = False, **kw):
    return mapped_column(UUID(as_uuid=True), ForeignKey(f"{tabla}.id", **kw), nullable=nulo)


class JornadaTecnico(ConVersion, Base):
    __tablename__ = "jornadas_tecnico"

    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    tecnico_id: Mapped[uuid.UUID] = _fk("tecnicos")
    inicio: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    fin: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    estado: Mapped[EstadoJornada] = mapped_column(pg_enum(EstadoJornada, "estado_jornada"),
                                                  default=EstadoJornada.activa)
    dispositivo_id: Mapped[str] = mapped_column(String(80), default="")
    cerrada_por: Mapped[CerradaPorJornada | None] = mapped_column(
        pg_enum(CerradaPorJornada, "cerrada_por_jornada"), nullable=True)
    # §6.8.4: la primera vez que inicia jornada, el técnico acepta el aviso de qué se registra y para qué.
    aviso_aceptado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    posiciones: Mapped[int] = mapped_column(Integer, default=0)


class JornadaPausa(ConVersion, Base):
    __tablename__ = "jornada_pausas"

    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    jornada_id: Mapped[uuid.UUID] = _fk("jornadas_tecnico", ondelete="CASCADE")
    inicio: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    fin: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    motivo: Mapped[MotivoPausaJornada] = mapped_column(pg_enum(MotivoPausaJornada, "motivo_pausa_jornada"),
                                                       default=MotivoPausaJornada.otro)
    nota: Mapped[str] = mapped_column(String(200), default="")


class TecnicoPosicion(Base):
    """Una posición del GPS del teléfono del técnico. Particionada por día; sin UPDATE ni DELETE desde la API."""
    __tablename__ = "tecnico_posiciones"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    prestador_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    tecnico_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    jornada_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    posicion = mapped_column(Geography(geometry_type="POINT", srid=4326, spatial_index=False), nullable=False)
    precision_m: Mapped[Decimal | None] = mapped_column(Numeric(7, 1))
    velocidad_mps: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    rumbo: Mapped[Decimal | None] = mapped_column(Numeric(5, 1))
    bateria_pct: Mapped[int | None] = mapped_column(SmallInteger)
    capturada_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    recibida_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    tardia: Mapped[bool] = mapped_column(Boolean, default=False)


class AlertaOperacionSeguimiento(ConVersion, Base):
    """Lo que §6.8.4 pide para el tiempo muerto: push al técnico, su respuesta y la escalación al Admin prestador."""
    __tablename__ = "alertas_operacion_seguimiento"

    prestador_id: Mapped[uuid.UUID] = _fk("prestadores")
    alerta_historial_id: Mapped[uuid.UUID | None] = _fk("alertas_historial", True, ondelete="SET NULL")
    tipo: Mapped[str] = mapped_column(String(60))
    tecnico_id: Mapped[uuid.UUID] = _fk("tecnicos")
    folio_id: Mapped[uuid.UUID | None] = _fk("folios", True)
    jornada_id: Mapped[uuid.UUID | None] = _fk("jornadas_tecnico", True, ondelete="SET NULL")
    push_al_tecnico_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    respuesta_tecnico: Mapped[RespuestaAlertaTecnico | None] = mapped_column(
        pg_enum(RespuestaAlertaTecnico, "respuesta_alerta_tecnico"), nullable=True)
    respondida_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    escalada_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    datos_json: Mapped[dict] = mapped_column(JSONB, default=dict)
