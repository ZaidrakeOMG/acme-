"""Envío de correos transaccionales por Resend HTTPS.

No requiere SMTP (Railway Free/Trial/Hobby bloquea salida SMTP).
Los errores se resumen sin incluir API key, direcciones, contenido, ni tokens
de restablecimiento en logs públicos.
"""
from __future__ import annotations

import base64

import httpx

URL_RESEND = "https://api.resend.com/emails"


async def enviar_resend(
    *,
    api_key: str,
    remitente: str,
    destinatarios: list[str],
    asunto: str,
    html: str,
    texto: str,
    adjuntos: list[tuple[str, bytes]] | None = None,
) -> tuple[str, str]:
    """Devuelve estado y diagnóstico seguro; enviar no garantiza entrega en bandeja."""
    if not api_key or not remitente:
        return "fallida", "resend:configuracion_incompleta"
    if not destinatarios:
        return "omitida", "sin destinatarios"
    datos: dict = {
        "from": remitente,
        "to": destinatarios,
        "subject": asunto,
        "html": html,
        "text": texto,
    }
    if adjuntos:
        datos["attachments"] = [
            {"filename": nombre, "content": base64.b64encode(contenido).decode("ascii")}
            for nombre, contenido in adjuntos
        ]
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as cliente:
            respuesta = await cliente.post(
                URL_RESEND,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "User-Agent": "ACMA/1.0",
                },
                json=datos,
            )
    except httpx.HTTPError as error:
        # Jamás registrar str(error): puede revelar URLs o datos sensibles.
        return "fallida", f"resend:red_{type(error).__name__}"
    if not 200 <= respuesta.status_code < 300:
        return "fallida", f"resend:http_{respuesta.status_code}"
    try:
        mensaje_id = respuesta.json().get("id", "")
    except (ValueError, AttributeError, TypeError):
        mensaje_id = ""
    if not isinstance(mensaje_id, str) or not mensaje_id:
        return "fallida", "resend:respuesta_sin_id"
    return "enviada", f"resend:{mensaje_id}"
