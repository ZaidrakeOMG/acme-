"""Contratos y SLAs por nivel de severidad (§6.10.1). La lógica del contador llega en P10."""
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.catalogos import CoberturaContrato
from models.base import (
    Base, ConVersion, EstadoRegistro, ModalidadContrato, NivelSeveridad, TipoPenalizacion, UnidadTiempo, pg_enum,
)


class Contrato(ConVersion, Base):
    __tablename__ = "contratos"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    prestador_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("prestadores.id"))
    nombre: Mapped[str] = mapped_column(String(160))
    modalidad: Mapped[ModalidadContrato] = mapped_column(pg_enum(ModalidadContrato, "modalidad_contrato"))
    fecha_inicio: Mapped[date] = mapped_column(Date)
    fecha_fin: Mapped[date] = mapped_column(Date)
    folios_correctivos_iguala: Mapped[int | None] = mapped_column(Integer)
    preventivos_iguala_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    penalizacion_tope_porcentaje: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    calificacion_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    cobertura: Mapped[CoberturaContrato] = mapped_column(
        pg_enum(CoberturaContrato, "cobertura_contrato"), default=CoberturaContrato.todas_las_un
    )
    estado: Mapped[EstadoRegistro] = mapped_column(pg_enum(EstadoRegistro, "estado_registro"), default=EstadoRegistro.activo)


class ContratoSLA(ConVersion, Base):
    __tablename__ = "contrato_sla"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    prestador_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("prestadores.id"))
    contrato_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("contratos.id"))
    nivel_severidad: Mapped[NivelSeveridad] = mapped_column(pg_enum(NivelSeveridad, "nivel_severidad"))
    nivel_severidad_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("niveles_severidad.id"))
    tiempo_respuesta_horas: Mapped[int] = mapped_column(Integer)
    tiempo_resolucion_horas: Mapped[int] = mapped_column(Integer)
    unidad_expresion: Mapped[UnidadTiempo] = mapped_column(pg_enum(UnidadTiempo, "unidad_tiempo"), default=UnidadTiempo.horas)
    penalizacion_tipo: Mapped[TipoPenalizacion] = mapped_column(
        pg_enum(TipoPenalizacion, "tipo_penalizacion"), default=TipoPenalizacion.porcentaje
    )
    penalizacion_valor: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
