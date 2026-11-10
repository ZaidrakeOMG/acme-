"""WhatsApp Cloud API de Meta (modos `prueba` y `real`). F2-02.

La cuenta la crea la usuaria (ver `docs/operacion/mensajeria.md`): ACMA solo lee el token, el id del número y el
secreto de la app de las variables de entorno. En modo `prueba` se usa el número de prueba de Meta, que solo entrega
a destinatarios verificados en su panel (máximo 5).

Ninguna prueba automatizada llega hasta aquí: `proveedores.obtener()` devuelve el stub salvo que el modo sea
`prueba` o `real`, y en ese caso hace falta token.
"""
import hashlib
import hmac
import json
import logging

from core.config import config
from services.mensajeria.base import MensajeSaliente, Resultado

log = logging.getLogger("acma.mensajeria")

# Errores de Meta que no tiene sentido reintentar: el mensaje cae al siguiente canal (§6.1).
PERMANENTES = {131026, 131047, 131051, 132000, 132001, 132005, 132007, 132012, 132015, 133010, 470}


def _mensaje_plantilla(m: MensajeSaliente) -> dict:
    componentes: list[dict] = []
    if m.variables:
        componentes.append({"type": "body",
                            "parameters": [{"type": "text", "text": str(v)} for v in m.variables]})
    for indice, boton in enumerate(b for b in m.botones if b.get("tipo") == "url"):
        # El botón de la plantilla aprobada lleva la URL base; aquí va solo el sufijo dinámico (el código corto).
        componentes.append({"type": "button", "sub_type": "url", "index": str(indice),
                            "parameters": [{"type": "text", "text": boton.get("sufijo", "")}]})
    return {"messaging_product": "whatsapp", "to": m.telefono, "type": "template",
            "template": {"name": m.nombre_proveedor, "language": {"code": m.idioma},
                         "components": componentes}}


class ProveedorMetaCloud:
    nombre = "meta_cloud"

    def __init__(self) -> None:
        self.token = config.whatsapp_token
        self.numero_id = config.whatsapp_numero_id
        self.base = config.whatsapp_api_url.rstrip("/")

    async def enviar_plantilla(self, m: MensajeSaliente) -> Resultado:
        return await self._enviar(_mensaje_plantilla(m))

    async def enviar_texto(self, m: MensajeSaliente) -> Resultado:
        return await self._enviar({"messaging_product": "whatsapp", "to": m.telefono, "type": "text",
                                   "text": {"preview_url": True, "body": m.cuerpo}})

    async def estado(self, mensaje_id: str) -> str | None:
        return None  # Meta informa los estados por webhook, no se consultan

    def validar_webhook(self, cuerpo: bytes, cabeceras: dict[str, str]) -> bool:
        """Firma `X-Hub-Signature-256` = HMAC-SHA256 del cuerpo con el secreto de la app."""
        secreto = config.whatsapp_app_secret
        firma = (cabeceras.get("x-hub-signature-256") or cabeceras.get("X-Hub-Signature-256") or "")
        if not secreto or not firma.startswith("sha256="):
            return False
        esperado = hmac.new(secreto.encode(), cuerpo, hashlib.sha256).hexdigest()
        return hmac.compare_digest(esperado, firma.split("=", 1)[1])

    async def _enviar(self, cuerpo: dict) -> Resultado:
        if not (self.token and self.numero_id):
            return Resultado(estado="fallido", codigo_error="SIN_CREDENCIALES",
                             detalle="Falta WHATSAPP_TOKEN o WHATSAPP_NUMERO_ID", permanente=True)
        import httpx

        url = f"{self.base}/{self.numero_id}/messages"
        try:
            async with httpx.AsyncClient(timeout=20) as cliente:
                r = await cliente.post(url, json=cuerpo,
                                       headers={"Authorization": f"Bearer {self.token}",
                                                "Content-Type": "application/json"})
        except Exception as e:  # noqa: BLE001 — red caída: se reintenta
            log.warning("Meta Cloud no respondió: %s", e)
            return Resultado(estado="fallido", codigo_error="RED", detalle=str(e)[:400])
        if r.status_code < 300:
            datos = r.json()
            ids = datos.get("messages") or [{}]
            return Resultado(estado="enviado", mensaje_id=str(ids[0].get("id", "")), detalle="meta_cloud")
        try:
            error = r.json().get("error", {})
        except json.JSONDecodeError:
            error = {}
        codigo = int(error.get("code") or 0)
        permanente = codigo in PERMANENTES or 400 <= r.status_code < 500 and r.status_code != 429
        return Resultado(estado="rechazado_por_proveedor" if permanente else "fallido",
                         codigo_error=str(codigo or r.status_code),
                         detalle=(error.get("message") or r.text)[:400], permanente=permanente)
