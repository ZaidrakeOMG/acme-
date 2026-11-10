"""Interfaz de proveedor de mensajería y utilidades de texto (§6.1). F2-02.

Un proveedor recibe un `MensajeSaliente` ya renderizado y devuelve un `Resultado`. No conoce la base de datos: el
servicio es el que registra la bitácora, el costo y los reintentos, así que agregar un proveedor nuevo (o cambiar de
Twilio a Meta) no toca nada más.
"""
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Protocol

# Alfabeto GSM-7 (3GPP 23.038): lo que cabe en un SMS de 160 caracteres. Fuera de aquí el mensaje pasa a UCS-2 y
# se queda en 70 caracteres por segmento, así que las plantillas de SMS se escriben sin acentos.
GSM7 = set(
    "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?"
    "¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà"
)
# Caracteres que en GSM-7 ocupan dos posiciones (tabla de extensión).
GSM7_DOBLES = set("^{}\\[~]|€")
LIMITE_GSM7, LIMITE_GSM7_MULTI = 160, 153
LIMITE_UCS2, LIMITE_UCS2_MULTI = 70, 67


@dataclass
class MensajeSaliente:
    canal: str  # "whatsapp" | "sms"
    telefono: str  # E.164 en claro: solo existe en memoria durante el envío
    cuerpo: str  # ya renderizado (lo que el stub guarda y lo que viaja en un SMS)
    plantilla_clave: str = ""
    nombre_proveedor: str = ""  # nombre de la plantilla en Meta
    idioma: str = "es_MX"
    variables: list[str] = field(default_factory=list)
    botones: list[dict[str, Any]] = field(default_factory=list)
    remitente: str = ""
    enlace: str = ""  # enlace corto de ACMA (botón de WhatsApp o texto del SMS)


@dataclass
class Resultado:
    estado: str  # "enviado" | "fallido" | "rechazado_por_proveedor"
    mensaje_id: str = ""
    codigo_error: str = ""
    detalle: str = ""
    permanente: bool = False  # True: no se reintenta y se cae al siguiente canal


class ProveedorMensajeria(Protocol):
    """Lo que debe saber hacer un proveedor. `nombre` es el valor del ENUM `proveedor_mensajeria`."""

    nombre: str

    async def enviar_plantilla(self, m: MensajeSaliente) -> Resultado: ...

    async def enviar_texto(self, m: MensajeSaliente) -> Resultado:
        """Texto libre: en WhatsApp solo es válido dentro de la ventana de 24 h posterior a un mensaje del usuario."""
        ...

    async def estado(self, mensaje_id: str) -> str | None:
        """Estado del mensaje según el proveedor, o None si no lo sabe (los estados llegan por webhook)."""
        ...

    def validar_webhook(self, cuerpo: bytes, cabeceras: dict[str, str]) -> bool: ...


# ----------------------------------------------------------------- texto

def sin_acentos(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")


def renderizar(cuerpo: str, variables: list[str], enlace: str = "") -> str:
    """Sustituye `{{1}}`… por las variables en orden y `{enlace}` por el enlace corto."""
    texto = cuerpo
    for i, valor in enumerate(variables, start=1):
        texto = texto.replace("{{%d}}" % i, str(valor))
    texto = re.sub(r"\{\{\d+\}\}", "", texto)  # una variable que no llegó no deja el hueco a la vista
    return texto.replace("{enlace}", enlace).strip()


def codificacion_sms(texto: str) -> str:
    return "GSM-7" if all(c in GSM7 or c in GSM7_DOBLES for c in texto) else "UCS-2"


def longitud_sms(texto: str) -> int:
    if codificacion_sms(texto) == "UCS-2":
        return len(texto)
    return sum(2 if c in GSM7_DOBLES else 1 for c in texto)


def segmentos_sms(texto: str) -> tuple[int, str]:
    """(segmentos, codificación). Con acentos el mensaje pasa a UCS-2 y se queda en 70 caracteres por segmento."""
    codificacion = codificacion_sms(texto)
    largo = longitud_sms(texto)
    simple, multi = ((LIMITE_GSM7, LIMITE_GSM7_MULTI) if codificacion == "GSM-7"
                     else (LIMITE_UCS2, LIMITE_UCS2_MULTI))
    if largo == 0:
        return 0, codificacion
    if largo <= simple:
        return 1, codificacion
    return (largo + multi - 1) // multi, codificacion
