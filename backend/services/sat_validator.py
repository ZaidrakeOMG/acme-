"""Validación del CFDI contra el SAT (§6.4 Tipo C). Fase 1: implementación `stub` que siempre devuelve `no_validado`
y registra la consulta en `validaciones_cfdi`; la interfaz muestra «Validación SAT disponible en Fase 2»."""
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from models.inventario import EstadoCFDI, ValidacionCFDI

MENSAJE_FASE_2 = "Validación SAT disponible en Fase 2"


@dataclass
class Resultado:
    estado: EstadoCFDI = EstadoCFDI.no_validado
    detalle: str = MENSAJE_FASE_2
    rfc_emisor: str | None = None
    total: Decimal | None = None


class ValidadorCFDI(Protocol):
    async def validar(self, uuid_cfdi: str, rfc_emisor: str | None, total: Decimal | None) -> Resultado: ...


class ValidadorStub:
    nombre = "stub"

    async def validar(self, uuid_cfdi: str, rfc_emisor: str | None, total: Decimal | None) -> Resultado:  # noqa: ARG002
        return Resultado(estado=EstadoCFDI.no_validado, detalle=MENSAJE_FASE_2, rfc_emisor=rfc_emisor, total=total)


VALIDADOR: ValidadorCFDI = ValidadorStub()


async def validar(db: AsyncSession, *, prestador_id: UUID, uuid_cfdi: str | None, rfc_emisor: str | None = None, total: Decimal | None = None,
                  gasto_id: UUID | None = None, rfc_receptor: str | None = None) -> Resultado:
    """Registra la consulta aunque el validador sea stub, para que la bitácora fiscal sea completa desde Fase 1."""
    if not (uuid_cfdi or "").strip():
        return Resultado(estado=EstadoCFDI.no_validado, detalle="Sin UUID de CFDI")
    r = await VALIDADOR.validar(uuid_cfdi.strip(), rfc_emisor, total)
    db.add(ValidacionCFDI(prestador_id=prestador_id, gasto_id=gasto_id, uuid_cfdi=uuid_cfdi.strip(), rfc_emisor=r.rfc_emisor, rfc_receptor=rfc_receptor,
                          total=r.total, estado_fiscal=r.estado, detalle=r.detalle))
    await db.flush()
    return r
