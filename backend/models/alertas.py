"""Configuración central de alertas y umbrales (§6.9.6)."""
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, SmallInteger, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, ConVersion, EstadoAlerta, TipoUmbral, pg_enum


class AlertaCatalogo(ConVersion, Base):
    __tablename__ = "alertas_catalogo"

    clave: Mapped[str] = mapped_column(String(60), unique=True)
    descripcion: Mapped[str] = mapped_column(Text)
    umbral_default: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    umbral_min: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    umbral_max: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    tipo_umbral: Mapped[TipoUmbral] = mapped_column(pg_enum(TipoUmbral, "tipo_umbral"))
    parametros_default: Mapped[dict] = mapped_column(JSONB, default=dict)
    modulo_origen: Mapped[str] = mapped_column(String(40))
    prompt_origen: Mapped[str] = mapped_column(String(10))
    destinatarios_default: Mapped[list] = mapped_column(JSONB, default=list)
    canales_default: Mapped[list] = mapped_column(JSONB, default=lambda: ["push", "email"])
    activa_por_defecto: Mapped[bool] = mapped_column(Boolean, default=True)
    fase: Mapped[int] = mapped_column(SmallInteger, default=1)  # P10: 2 = la fuente de datos llega en Fase 2
    escalacion_de: Mapped[str | None] = mapped_column(String(60), ForeignKey("alertas_catalogo.clave"))


class AlertaConfiguracion(ConVersion, Base):
    __tablename__ = "alertas_configuracion"

    clave_alerta: Mapped[str] = mapped_column(String(60), ForeignKey("alertas_catalogo.clave"))
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    prestador_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("prestadores.id"))
    umbral_valor: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    parametros: Mapped[dict] = mapped_column(JSONB, default=dict)
    canales_json: Mapped[list] = mapped_column(JSONB, default=lambda: ["push", "email"])
    destinatarios_roles_json: Mapped[list] = mapped_column(JSONB, default=list)
    activa: Mapped[bool] = mapped_column(Boolean, default=True)


class AlertaHistorial(Base):
    __tablename__ = "alertas_historial"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    clave_alerta: Mapped[str] = mapped_column(String(60), ForeignKey("alertas_catalogo.clave"))
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    prestador_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    entidad_tipo: Mapped[str | None] = mapped_column(String(60))
    entidad_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    umbral_en_momento: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    datos_contexto_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    estado: Mapped[EstadoAlerta] = mapped_column(pg_enum(EstadoAlerta, "estado_alerta"), default=EstadoAlerta.disparada)
    timestamp_disparo: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    timestamp_vista: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    vista_por: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("usuarios.id"))
    atendida_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    atendida_por: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("usuarios.id"))
    nota_atencion: Mapped[str] = mapped_column(Text, default="")
    escalada: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class AlertaSupresion(ConVersion, Base):
    __tablename__ = "alertas_supresiones"

    clave_alerta: Mapped[str] = mapped_column(String(60), ForeignKey("alertas_catalogo.clave"))
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    prestador_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("prestadores.id"))
    entidad_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    suprimida_por: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("usuarios.id"))
    razon: Mapped[str] = mapped_column(Text)
    desde: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    hasta: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    activa: Mapped[bool] = mapped_column(Boolean, default=True)
