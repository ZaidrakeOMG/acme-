"""Selección de proveedor por canal y límite de tasa (§6.1). F2-02.

`WHATSAPP_MODO` y `SMS_MODO` funcionan como `SMTP` en P07:

* `stub` (por defecto): nada sale de la máquina.
* `prueba`: cuentas gratuitas de Meta o Twilio, que solo entregan a números verificados en su panel.
* `real`: cuenta de pago, con las credenciales en `.env`.

Si el modo pide un proveedor real y falta su credencial, se usa el stub y queda anotado en el log: el sistema nunca
se queda sin canal por una variable mal escrita, y la bitácora dice con qué proveedor salió cada mensaje.
"""
import logging
import time

from core.config import config
from services.mensajeria.base import ProveedorMensajeria
from services.mensajeria.meta_cloud import ProveedorMetaCloud
from services.mensajeria.stub import ProveedorStub
from services.mensajeria.twilio import ProveedorTwilio

log = logging.getLogger("acma.mensajeria")

MODOS = ("stub", "prueba", "real")
# Cubeta por minuto: {(clave, minuto): enviados}. Por proceso; con varios workers el tope real es n × el configurado,
# que para un límite de cortesía basta (el tope mensual por tenant sí es exacto porque se cuenta en la base).
_CUBETAS: dict[tuple[str, int], int] = {}


def modo_de_canal(canal: str) -> str:
    modo = (config.whatsapp_modo if canal == "whatsapp" else config.sms_modo).strip().lower()
    return modo if modo in MODOS else "stub"


def nombre_proveedor(canal: str) -> str:
    """Qué proveedor le toca al canal según el modo y las credenciales disponibles."""
    modo = modo_de_canal(canal)
    if modo == "stub":
        return "stub"
    preferido = (config.whatsapp_proveedor if canal == "whatsapp" else config.sms_proveedor).strip().lower()
    if preferido == "meta_cloud" and config.whatsapp_token and config.whatsapp_numero_id:
        return "meta_cloud"
    if preferido == "twilio" and config.twilio_account_sid and config.twilio_auth_token:
        return "twilio"
    log.warning("Canal %s en modo %s sin credenciales de %s: se usa el proveedor simulado", canal, modo, preferido)
    return "stub"


def obtener(canal: str) -> ProveedorMensajeria:
    nombre = nombre_proveedor(canal)
    if nombre == "meta_cloud":
        return ProveedorMetaCloud()
    if nombre == "twilio":
        return ProveedorTwilio()
    return ProveedorStub()


def por_nombre(nombre: str) -> ProveedorMensajeria:
    """El proveedor que registró un envío (para validar su webhook o consultar su estado)."""
    return {"meta_cloud": ProveedorMetaCloud, "twilio": ProveedorTwilio}.get(nombre, ProveedorStub)()


def remitente_de(canal: str) -> str:
    if canal == "whatsapp":
        return config.whatsapp_numero_id or config.twilio_remitente_whatsapp or "stub"
    return config.twilio_remitente_sms or "stub"


def permitir(clave: str, maximo: int | None = None) -> bool:
    """Límite de tasa por proveedor y por tenant: `mensajeria_max_por_minuto` mensajes por minuto."""
    tope = config.mensajeria_max_por_minuto if maximo is None else maximo
    if tope <= 0:
        return True
    minuto = int(time.time() // 60)
    for k in [k for k in _CUBETAS if k[1] < minuto - 1]:
        del _CUBETAS[k]
    usado = _CUBETAS.get((clave, minuto), 0)
    if usado >= tope:
        return False
    _CUBETAS[(clave, minuto)] = usado + 1
    return True


def limpiar_cubetas() -> None:
    _CUBETAS.clear()
