"""Esquemas de medidores de activos, lecturas y llaves de API (§6.9.2). F2-04."""
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from models.medidores import CategoriaMedidor, EstadoLecturaMedidor, MetodoActualizacionMedidor, TipoCambioMedidor
from schemas.comun import ConVersionSalida, Modelo


# ------------------------------------------------------------------ catálogo de tipos
class TipoMedidorEntrada(BaseModel):
    nombre: str = Field(min_length=2, max_length=120)
    unidad: str = Field(min_length=1, max_length=30, examples=["h", "ciclos", "km", "kWh", "piezas"])
    categoria: CategoriaMedidor = CategoriaMedidor.personalizado
    descripcion: str = Field(default="", max_length=2000)
    permite_estimacion: bool = True
    decimales: int = Field(default=0, ge=0, le=4)
    requiere_foto: bool = Field(default=False, description="Exige foto del marcador en la app del operador")
    factor_salto_maximo: Decimal = Field(default=Decimal("3"), ge=1, le=100,
                                         description="Cuántas veces el incremento diario esperado se tolera antes de mandar la lectura a revisión")
    # Solo el Superadmin: deja el tipo en el catálogo global (sin prestador ni cliente).
    global_: bool = Field(default=False, alias="global")

    model_config = {"populate_by_name": True}


class TipoMedidorCambios(BaseModel):
    nombre: str | None = Field(default=None, min_length=2, max_length=120)
    unidad: str | None = Field(default=None, min_length=1, max_length=30)
    categoria: CategoriaMedidor | None = None
    descripcion: str | None = Field(default=None, max_length=2000)
    permite_estimacion: bool | None = None
    decimales: int | None = Field(default=None, ge=0, le=4)
    requiere_foto: bool | None = None
    factor_salto_maximo: Decimal | None = Field(default=None, ge=1, le=100)
    activo: bool | None = None


class TipoMedidorSalida(ConVersionSalida):
    prestador_id: UUID | None = None
    tenant_id: UUID | None = None
    nombre: str
    unidad: str
    categoria: CategoriaMedidor
    descripcion: str
    permite_estimacion: bool
    decimales: int
    requiere_foto: bool
    factor_salto_maximo: Decimal
    activo: bool


# ------------------------------------------------------------------ medidores del equipo
class MedidorEntrada(BaseModel):
    tipo_medidor_id: UUID
    valor_inicial: Decimal = Field(default=Decimal("0"), ge=0, max_digits=16, decimal_places=2)
    metodo_actualizacion: MetodoActualizacionMedidor = MetodoActualizacionMedidor.tecnico
    valor_maximo: Decimal | None = Field(default=None, gt=0, max_digits=16, decimal_places=2,
                                         description="Valor en el que el marcador se reinicia (p. ej. 99999)")
    numero_serie_medidor: str | None = Field(default=None, max_length=80)
    instalado_en: date | None = None


class MedidorCambios(BaseModel):
    metodo_actualizacion: MetodoActualizacionMedidor | None = None
    valor_maximo: Decimal | None = Field(default=None, gt=0, max_digits=16, decimal_places=2)
    numero_serie_medidor: str | None = Field(default=None, max_length=80)
    instalado_en: date | None = None
    activo: bool | None = None


class MedidorSalida(ConVersionSalida):
    equipo_id: UUID
    tipo_medidor_id: UUID
    tenant_id: UUID
    valor_actual: Decimal
    valor_acumulado: Decimal
    valor_ultimo_pm: Decimal
    fecha_ultima_lectura: datetime | None = None
    metodo_actualizacion: MetodoActualizacionMedidor
    valor_maximo: Decimal | None = None
    numero_serie_medidor: str | None = None
    instalado_en: date | None = None
    activo: bool


class ResumenMedidor(Modelo):
    """Lo que pinta la pestaña «Medidores» de la ficha del equipo."""
    id: UUID
    tipo_medidor_id: UUID
    tipo: str
    unidad: str
    categoria: CategoriaMedidor | None = None
    decimales: int
    requiere_foto: bool
    valor_actual: Decimal
    valor_acumulado: Decimal
    valor_ultimo_pm: Decimal
    fecha_ultima_lectura: datetime | None = None
    metodo_actualizacion: MetodoActualizacionMedidor
    valor_maximo: Decimal | None = None
    numero_serie_medidor: str | None = None
    instalado_en: date | None = None
    activo: bool
    incremento_por_dia: Decimal
    origen_incremento: str
    estimacion: dict[str, Any] | None = None
    proximos_mantenimientos: list[dict[str, Any]] = Field(default_factory=list)


# ------------------------------------------------------------------ lecturas
class LecturaEntrada(BaseModel):
    equipo_medidor_id: UUID
    valor: Decimal = Field(ge=0, max_digits=16, decimal_places=2)
    metodo: MetodoActualizacionMedidor | None = Field(default=None, description="Vacío = el método del medidor")
    timestamp_dispositivo: datetime | None = Field(default=None, description="Hora del dispositivo (modo sin señal)")
    folio_id: UUID | None = None
    evidencia_id: UUID | None = Field(default=None, description="Foto del marcador ya subida como evidencia")


class LecturaSalida(ConVersionSalida):
    equipo_medidor_id: UUID
    equipo_id: UUID
    tipo_medidor_id: UUID
    valor: Decimal
    valor_acumulado: Decimal
    metodo: MetodoActualizacionMedidor
    registrado_por: UUID | None = None
    folio_id: UUID | None = None
    evidencia_id: UUID | None = None
    timestamp_dispositivo: datetime | None = None
    timestamp: datetime
    estado: EstadoLecturaMedidor
    motivo: str
    revisada_por: UUID | None = None
    revisada_at: datetime | None = None


class LecturaResultado(BaseModel):
    lectura: LecturaSalida
    duplicada: bool = False
    anomalia: str = ""
    folios_generados: list[dict[str, Any]] = Field(default_factory=list)


class RevisionEntrada(BaseModel):
    aprobar: bool
    razon: str = Field(default="", max_length=500)


class PendienteRevision(Modelo):
    id: UUID
    equipo_id: UUID
    equipo: str
    equipo_codigo: str
    tenant_id: UUID
    medidor: str
    unidad: str
    valor: Decimal
    valor_acumulado: Decimal
    metodo: MetodoActualizacionMedidor
    motivo: str
    timestamp: datetime
    valor_anterior: Decimal | None = None
    fecha_anterior: datetime | None = None


# ------------------------------------------------------------------ cambios y estimación
class CambioEntrada(BaseModel):
    tipo: TipoCambioMedidor
    valor_nuevo: Decimal = Field(default=Decimal("0"), ge=0, max_digits=16, decimal_places=2)
    motivo: str = Field(min_length=3, max_length=500)
    numero_serie_nuevo: str | None = Field(default=None, max_length=80)


class CambioSalida(ConVersionSalida):
    equipo_medidor_id: UUID
    tipo: TipoCambioMedidor
    valor_anterior: Decimal
    valor_nuevo: Decimal
    acumulado_al_cambio: Decimal
    numero_serie_anterior: str | None = None
    numero_serie_nuevo: str | None = None
    motivo: str
    registrado_por: UUID | None = None
    timestamp: datetime


class EstimacionEntrada(BaseModel):
    incremento_por_dia: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=4)
    horario_operacion_json: dict[str, Any] | None = Field(
        default=None, examples=[{"dias": ["lunes", "martes", "miercoles", "jueves", "viernes"], "horas_por_dia": 8}])
    activa: bool | None = None
    desde: date | None = None


class EstimacionSalida(ConVersionSalida):
    equipo_medidor_id: UUID
    incremento_por_dia: Decimal
    incremento_real_promedio: Decimal | None = None
    horario_operacion_json: dict[str, Any]
    activa: bool
    desde: date
    ultima_estimacion_at: datetime | None = None


# ------------------------------------------------------------------ lote
class LecturaLote(BaseModel):
    equipo_codigo: str = Field(max_length=60)
    tipo_medidor: str = Field(max_length=120)
    valor: Decimal = Field(ge=0, max_digits=16, decimal_places=2)
    timestamp: datetime | None = None


class LoteEntrada(BaseModel):
    tenant_id: UUID | None = Field(default=None, description="Con llave de API se ignora: la llave ya dice de quién es")
    lecturas: list[LecturaLote] = Field(min_length=1, max_length=1000)


class LoteSalida(BaseModel):
    total: int
    aplicadas: int
    duplicadas: int
    en_revision: int
    rechazadas: int
    resultados: list[dict[str, Any]]


# ------------------------------------------------------------------ llaves de API
class LlaveEntrada(BaseModel):
    nombre: str = Field(min_length=3, max_length=120, examples=["SCADA planta Torreón"])
    tenant_id: UUID | None = Field(default=None, description="Solo el Superadmin la indica")


class LlaveSalida(ConVersionSalida):
    tenant_id: UUID
    nombre: str
    prefijo: str
    permisos_json: list[str]
    activa: bool
    creada_por: UUID | None = None
    revocada_at: datetime | None = None
    ultimo_uso_at: datetime | None = None
    usos: int


class LlaveCreada(BaseModel):
    llave: LlaveSalida
    secreto: str = Field(description="La llave completa. Se muestra una sola vez: ACMA solo guarda su hash.")


# ------------------------------------------------------------------ eventos y simulación de planes
class EventoCatalogoSalida(Modelo):
    clave: str
    descripcion: str
    parametros_schema_json: dict[str, Any]
    activo: bool
