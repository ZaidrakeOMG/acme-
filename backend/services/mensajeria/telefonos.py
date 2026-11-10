"""Teléfono móvil del usuario: formato E.164, cifrado, hash y máscara (§6.9.5). F2-02.

El número en claro solo existe en memoria durante el envío. En la base vive cifrado (envelope AES-256-GCM de P11a),
y lo que se guarda en bitácoras y se muestra en pantalla es la máscara `+52 871 ••• ••34` o el hash.
"""
import hashlib
import re
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from core.config import config
from core.errors import ErrorAPI
from core.security import cifrar, descifrar

E164 = re.compile(r"^\+[1-9]\d{7,14}$")
MINUTOS_CODIGO = 10
MAX_INTENTOS_CODIGO = 5
# Rangos reservados para pruebas en México (NANP 555 y los números de documentación): el seed los usa para que
# nadie reciba un mensaje real si algún día se activa un proveedor de verdad con los datos demo.
PREFIJOS_DE_PRUEBA = ("+52155501", "+1555")

# Texto que la pantalla de perfil muestra junto al teléfono. Marcado para revisión del área legal en
# docs/decisiones_para_validar.md (uso de datos personales para notificaciones operativas, §6.9.5).
AVISO_PRIVACIDAD = (
    "Tu número de celular se usa solo para enviarte avisos operativos de ACMA: folios, aprobaciones, minutas y "
    "alertas del servicio. No se usa para publicidad ni se comparte con nadie más que el proveedor de mensajería "
    "que entrega el mensaje (Meta para WhatsApp, Twilio para SMS). El número se guarda cifrado y en las bitácoras "
    "solo aparece enmascarado. Puedes darte de baja cuando quieras: escribe BAJA por WhatsApp o SMS, o quita el "
    "consentimiento en esta pantalla; para volver, escribe ALTA."
)


def normalizar(texto: str) -> str:
    """Deja el número en E.164 (`+528711234567`) o explica el error. Un 10 dígitos mexicano se asume de México."""
    limpio = re.sub(r"[\s().-]", "", (texto or "").strip())
    if limpio.startswith("00"):
        limpio = "+" + limpio[2:]
    if not limpio.startswith("+"):
        if len(limpio) == 10 and limpio.isdigit():
            limpio = "+52" + limpio
        elif len(limpio) == 12 and limpio.startswith("52"):
            limpio = "+" + limpio
    if not E164.match(limpio):
        raise ErrorAPI(422, "TELEFONO_INVALIDO",
                       "Escribe el celular en formato internacional, por ejemplo +52 871 123 4567",
                       [{"campo": "telefono", "formato": "E.164"}])
    return limpio


def hash_telefono(e164: str) -> str:
    """Hash con el secreto de la instalación: sirve para reconocer al remitente de un mensaje entrante sin descifrar."""
    return hashlib.sha256(f"{config.jwt_secreto}|{e164}".encode()).hexdigest()


def mascara(e164: str) -> str:
    """`+52 871 ••• ••34` (§6.9.5: el número nunca se muestra completo)."""
    if not e164 or len(e164) < 6:
        return "•••"
    pais, resto = e164[:3], e164[3:]
    return f"{pais} {resto[:3]} ••• ••{e164[-2:]}"


def es_de_prueba(e164: str) -> bool:
    return any(e164.startswith(p) for p in PREFIJOS_DE_PRUEBA)


def guardar(usuario, e164: str) -> None:
    """Deja el teléfono cifrado y sin verificar: cambiar el número obliga a verificarlo otra vez."""
    usuario.telefono_movil_e164 = cifrar(e164)
    usuario.telefono_movil_hash = hash_telefono(e164)
    usuario.telefono_movil_mascara = mascara(e164)
    usuario.telefono_verificado_at = None
    usuario.telefono_codigo_hash = None
    usuario.telefono_codigo_expira_at = None
    usuario.telefono_codigo_intentos = 0


def borrar(usuario) -> None:
    """Quita el teléfono y con él los consentimientos: sin número no hay canal."""
    for campo in ("telefono_movil_e164", "telefono_movil_hash", "telefono_movil_mascara", "telefono_verificado_at",
                  "telefono_codigo_hash", "telefono_codigo_expira_at", "whatsapp_consentimiento_at",
                  "sms_consentimiento_at"):
        setattr(usuario, campo, None)
    usuario.telefono_codigo_intentos = 0


def en_claro(usuario) -> str | None:
    if not usuario.telefono_movil_e164:
        return None
    try:
        return descifrar(usuario.telefono_movil_e164)
    except Exception:  # noqa: BLE001 — un valor ilegible (clave rotada) se trata como «sin teléfono»
        return None


def nuevo_codigo(usuario) -> str:
    codigo = f"{secrets.randbelow(1000000):06d}"
    usuario.telefono_codigo_hash = hashlib.sha256(f"{config.jwt_secreto}|{codigo}".encode()).hexdigest()
    usuario.telefono_codigo_expira_at = datetime.now(UTC) + timedelta(minutes=MINUTOS_CODIGO)
    usuario.telefono_codigo_intentos = 0
    return codigo


def verificar_codigo(usuario, codigo: str) -> None:
    """Marca el teléfono como verificado o explica por qué no. Cinco intentos y el código se invalida."""
    if not usuario.telefono_codigo_hash or not usuario.telefono_codigo_expira_at:
        raise ErrorAPI(409, "SIN_CODIGO", "Pide un código nuevo para verificar tu teléfono")
    if usuario.telefono_codigo_expira_at <= datetime.now(UTC):
        raise ErrorAPI(409, "CODIGO_VENCIDO", "El código venció; pide uno nuevo")
    if usuario.telefono_codigo_intentos >= MAX_INTENTOS_CODIGO:
        raise ErrorAPI(429, "DEMASIADOS_INTENTOS", "Demasiados intentos; pide un código nuevo")
    esperado = hashlib.sha256(f"{config.jwt_secreto}|{(codigo or '').strip()}".encode()).hexdigest()
    if not secrets.compare_digest(esperado, usuario.telefono_codigo_hash):
        usuario.telefono_codigo_intentos += 1
        raise ErrorAPI(422, "CODIGO_INCORRECTO", "El código no coincide")
    usuario.telefono_verificado_at = datetime.now(UTC)
    usuario.telefono_codigo_hash = None
    usuario.telefono_codigo_expira_at = None
    usuario.telefono_codigo_intentos = 0


def estado_de_canales(usuario) -> dict[str, Any]:
    """Lo que la pantalla de perfil necesita saber, sin el número en claro."""
    return {
        "telefono_mascara": usuario.telefono_movil_mascara,
        "tiene_telefono": bool(usuario.telefono_movil_e164),
        "verificado": usuario.telefono_verificado_at is not None,
        "verificado_at": usuario.telefono_verificado_at,
        "whatsapp": {"consentimiento_at": usuario.whatsapp_consentimiento_at, "baja_at": usuario.whatsapp_baja_at,
                     "activo": consentido(usuario, "whatsapp")},
        "sms": {"consentimiento_at": usuario.sms_consentimiento_at, "baja_at": usuario.sms_baja_at,
                "activo": consentido(usuario, "sms")},
    }


def consentido(usuario, canal: str) -> bool:
    """Consentimiento vigente: dio de alta el canal y no se dio de baja después (§6.9.5)."""
    alta = getattr(usuario, f"{canal}_consentimiento_at", None)
    baja = getattr(usuario, f"{canal}_baja_at", None)
    if alta is None:
        return False
    return baja is None or baja < alta


def fijar_consentimiento(usuario, canal: str, acepta: bool) -> None:
    ahora = datetime.now(UTC)
    if acepta:
        setattr(usuario, f"{canal}_consentimiento_at", ahora)
        setattr(usuario, f"{canal}_baja_at", None)
    else:
        setattr(usuario, f"{canal}_baja_at", ahora)
