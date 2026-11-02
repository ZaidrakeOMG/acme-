"""Extracción OCR de facturas de caja chica (§6.4 Tipo C). Fase 1: implementación `stub` que no extrae nada y deja la
captura manual al técnico. Fase 2 sustituye `TRANSCRIPTOR` por Google Cloud Vision o AWS Textract."""
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol


@dataclass
class Factura:
    """Campos que el OCR de Fase 2 extraerá de la foto; en Fase 1 llegan vacíos y los captura el técnico."""
    proveedor: str | None = None
    rfc_proveedor: str | None = None
    uuid_cfdi: str | None = None
    descripcion: str | None = None
    numero_parte: str | None = None
    subtotal: Decimal | None = None
    iva: Decimal | None = None
    total: Decimal | None = None
    confianza: float = 0.0
    disponible: bool = False
    detalle: str = ""
    campos_json: dict[str, Any] = field(default_factory=dict)


class OCR(Protocol):
    async def extraer(self, contenido: bytes, mime: str) -> Factura: ...


class OCRStub:
    """Fase 1: la interfaz muestra «Extracción automática disponible en Fase 2» y el técnico captura los datos."""

    nombre = "stub"

    async def extraer(self, contenido: bytes, mime: str) -> Factura:  # noqa: ARG002
        return Factura(disponible=False, detalle="Extracción automática (OCR) disponible en Fase 2: captura los datos de la factura")


MOTOR: OCR = OCRStub()


async def extraer(contenido: bytes, mime: str = "image/jpeg") -> Factura:
    return await MOTOR.extraer(contenido, mime)
