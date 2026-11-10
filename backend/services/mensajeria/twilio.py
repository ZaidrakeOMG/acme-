"""Twilio: SMS y, si la usuaria lo prefiere, también WhatsApp (modos `prueba` y `real`). F2-02.

La cuenta de prueba de Twilio envía solo a números verificados en su panel y antepone un aviso al texto. Las
credenciales las carga la usuaria en `.env` (ver `docs/operacion/mensajeria.md`); ACMA nunca las pide por chat.
"""
import base64
import hashlib
import hmac
import logging
from urllib.parse import urlencode

from core.config import config
from services.mensajeria.base import MensajeSaliente, Resultado

log = logging.getLogger("acma.mensajeria")

# Errores de Twilio que no se reintentan (número inválido, destinatario no verificado, bloqueo del operador).
PERMANENTES = {21211, 21212, 21214, 21266, 21408, 21606, 21610, 21612, 21614, 63016, 63024}
ESTADOS = {"queued": "enviado", "sending": "enviado", "sent": "enviado", "delivered": "entregado",
           "read": "leido", "undelivered": "fallido", "failed": "fallido"}


class ProveedorTwilio:
    nombre = "twilio"

    def __init__(self) -> None:
        self.sid = config.twilio_account_sid
        self.token = config.twilio_auth_token
        self.base = config.twilio_api_url.rstrip("/")

    def _remitente(self, m: MensajeSaliente) -> str:
        if m.remitente:
            return m.remitente
        return (config.twilio_remitente_whatsapp if m.canal == "whatsapp" else config.twilio_remitente_sms)

    async def enviar_plantilla(self, m: MensajeSaliente) -> Resultado:
        # Twilio envía el cuerpo ya renderizado; la plantilla aprobada se identifica por su `nombre_proveedor`
        # cuando se usa Content API, que es opcional. Con el cuerpo basta para SMS y para WhatsApp de prueba.
        return await self.enviar_texto(m)

    async def enviar_texto(self, m: MensajeSaliente) -> Resultado:
        if not (self.sid and self.token):
            return Resultado(estado="fallido", codigo_error="SIN_CREDENCIALES",
                             detalle="Falta TWILIO_ACCOUNT_SID o TWILIO_AUTH_TOKEN", permanente=True)
        destino = f"whatsapp:{m.telefono}" if m.canal == "whatsapp" else m.telefono
        datos = {"To": destino, "Body": m.cuerpo}
        remitente = self._remitente(m)
        datos["MessagingServiceSid" if remitente.startswith("MG") else "From"] = remitente
        import httpx

        try:
            async with httpx.AsyncClient(timeout=20) as cliente:
                r = await cliente.post(f"{self.base}/Accounts/{self.sid}/Messages.json", data=datos,
                                       auth=(self.sid, self.token))
        except Exception as e:  # noqa: BLE001
            log.warning("Twilio no respondió: %s", e)
            return Resultado(estado="fallido", codigo_error="RED", detalle=str(e)[:400])
        cuerpo = r.json() if r.content else {}
        if r.status_code < 300:
            return Resultado(estado="enviado", mensaje_id=str(cuerpo.get("sid", "")), detalle="twilio")
        codigo = int(cuerpo.get("code") or 0)
        permanente = codigo in PERMANENTES or (400 <= r.status_code < 500 and r.status_code != 429)
        return Resultado(estado="rechazado_por_proveedor" if permanente else "fallido",
                         codigo_error=str(codigo or r.status_code),
                         detalle=str(cuerpo.get("message") or r.text)[:400], permanente=permanente)

    async def estado(self, mensaje_id: str) -> str | None:
        if not (self.sid and self.token and mensaje_id):
            return None
        import httpx

        try:
            async with httpx.AsyncClient(timeout=15) as cliente:
                r = await cliente.get(f"{self.base}/Accounts/{self.sid}/Messages/{mensaje_id}.json",
                                      auth=(self.sid, self.token))
            return ESTADOS.get(str(r.json().get("status", ""))) if r.status_code < 300 else None
        except Exception:  # noqa: BLE001
            return None

    def validar_webhook(self, cuerpo: bytes, cabeceras: dict[str, str]) -> bool:
        """Firma de Twilio: HMAC-SHA1 (base64) de la URL + los parámetros ordenados, con el auth token.

        `cuerpo` llega como el formulario codificado y la URL completa viene en la cabecera `x-acma-url` que el
        router pone con la URL real de la petición (Twilio firma la URL que configuró la usuaria).
        """
        firma = cabeceras.get("x-twilio-signature") or cabeceras.get("X-Twilio-Signature") or ""
        url = cabeceras.get("x-acma-url", "")
        if not (self.token and firma and url):
            return False
        from urllib.parse import parse_qsl

        parametros = sorted(parse_qsl(cuerpo.decode("utf-8", "ignore"), keep_blank_values=True))
        cadena = url + "".join(f"{k}{v}" for k, v in parametros)
        esperado = base64.b64encode(hmac.new(self.token.encode(), cadena.encode(), hashlib.sha1).digest()).decode()
        return hmac.compare_digest(esperado, firma)


def firmar_para_pruebas(token: str, url: str, parametros: dict[str, str]) -> str:
    """Firma de Twilio para las pruebas del webhook (no se usa en producción)."""
    cadena = url + "".join(f"{k}{v}" for k, v in sorted(parametros.items()))
    return base64.b64encode(hmac.new(token.encode(), cadena.encode(), hashlib.sha1).digest()).decode()


def cuerpo_formulario(parametros: dict[str, str]) -> bytes:
    return urlencode(parametros).encode()
