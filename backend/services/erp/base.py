"""Capa de integración desacoplada con ERPs externos (§6.6): ACMA genera el evento en su formato interno y el adaptador
lo traduce. En Fase 1 no hay adaptador activo: los eventos quedan `pendiente` y los stubs de CONTPAQi y Microsip los dejan
`omitido` con motivo «adaptador Fase 2». La exportación universal (XML de pólizas + Excel configurable) sí es de Fase 1."""
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from models.costos import AdaptadorERP, ErpEventoPendiente, EstadoEventoERP

MOTIVO_FASE_2 = "adaptador Fase 2"


@dataclass
class Respuesta:
    estado: EstadoEventoERP
    detalle: str = ""
    datos: dict | None = None


class Adaptador(Protocol):
    clave: AdaptadorERP
    nombre: str

    async def procesar(self, evento: ErpEventoPendiente) -> Respuesta: ...


class _Stub:
    """Deja el evento en `omitido`: el modelo de datos ya existe y Fase 2 solo agrega el worker que lo procesa."""

    def __init__(self, clave: AdaptadorERP, nombre: str) -> None:
        self.clave, self.nombre = clave, nombre

    async def procesar(self, evento: ErpEventoPendiente) -> Respuesta:
        return Respuesta(EstadoEventoERP.omitido, f"{self.nombre}: {MOTIVO_FASE_2}", {"operacion": evento.operacion.value, "adaptador": self.clave.value})


class SinAdaptador:
    clave, nombre = AdaptadorERP.ninguno, "Sin adaptador"

    async def procesar(self, evento: ErpEventoPendiente) -> Respuesta:  # noqa: ARG002
        return Respuesta(EstadoEventoERP.pendiente, "Sin adaptador configurado: el evento espera la exportación universal")


ADAPTADORES: dict[AdaptadorERP, Adaptador] = {
    AdaptadorERP.ninguno: SinAdaptador(),
    AdaptadorERP.contpaqi: _Stub(AdaptadorERP.contpaqi, "CONTPAQi"),
    AdaptadorERP.microsip: _Stub(AdaptadorERP.microsip, "Microsip"),
}


def adaptador(clave: AdaptadorERP | None) -> Adaptador:
    return ADAPTADORES.get(clave or AdaptadorERP.ninguno, ADAPTADORES[AdaptadorERP.ninguno])


async def procesar(db: AsyncSession, evento: ErpEventoPendiente, clave: AdaptadorERP | None) -> Respuesta:
    a = adaptador(clave)
    r = await a.procesar(evento)
    evento.intentos += 1
    evento.adaptador = a.clave if a.clave != AdaptadorERP.ninguno else None
    evento.respuesta_json = {"detalle": r.detalle, **(r.datos or {})}
    if r.estado != EstadoEventoERP.pendiente:
        evento.estado, evento.procesado_at = r.estado, datetime.now(UTC)
    if r.estado == EstadoEventoERP.error:
        evento.ultimo_error = r.detalle
    await db.flush()
    return r
