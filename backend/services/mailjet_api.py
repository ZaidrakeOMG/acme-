"""Canal transaccional Mailjet Send API v3.1 por HTTPS (apto para Railway).

Nunca escribe credenciales, destinatarios, contenido o enlaces de recuperación
en los diagnósticos devueltos ni en los logs de la aplicación.
"""
from __future__ import annotations

import base64
import mimetypes
from email.utils import parseaddr

import httpx

URL_MAILJET = "https://api.mailjet.com/v3.1/send"


def _remitente_valido(valor: str) -> dict[str, str] | None:
    if not valor or any(c in valor for c in "\r\n"):
        return None
    nombre, direccion = parseaddr(valor)
    if direccion.count("@") != 1 or any(c.isspace() for c in direccion):
        return None
    local, dominio = direccion.rsplit("@", 1)
    if not local or "." not in dominio or dominio.startswith(".") or dominio.endswith("."):
        return None
    return {"Email": direccion, "Name": nombre or "ACMA"}


async def enviar_mailjet(
    *,
    api_key: str,
    secret_key: str,
    remitente: str,
    destinatarios: list[str],
    asunto: str,
    html: str,
    texto: str,
    adjuntos: list[tuple[str, bytes]] | None = None,
) -> tuple[str, str]:
    """Devuelve (estado, diagnóstico seguro). Aceptación no implica entrega."""
    origen = _remitente_valido(remitente)
    if not api_key or not secret_key or origen is None:
        return "fallida", "mailjet:configuracion_incompleta"
    if not destinatarios:
        return "omitida", "sin destinatarios"
    # Una entrada Messages por destinatario: nadie ve correos de otros usuarios.
    if len(destinatarios) > 50:
        return "fallida", "mailjet:demasiados_destinatarios"
    if any(_remitente_valido(d) is None or parseaddr(d)[1] != d for d in destinatarios):
        return "fallida", "mailjet:destinatario_invalido"

    archivos = []
    for nombre, contenido in adjuntos or []:
        if not nombre or not isinstance(contenido, bytes):
            return "fallida", "mailjet:adjunto_invalido"
        archivos.append({
            "ContentType": mimetypes.guess_type(nombre)[0] or "application/octet-stream",
            "Filename": nombre,
            "Base64Content": base64.b64encode(contenido).decode("ascii"),
        })

    mensajes = []
    for destinatario in destinatarios:
        mensaje: dict = {
            "From": origen,
            "To": [{"Email": destinatario}],
            "Subject": asunto,
            "HTMLPart": html,
            # Correo transaccional: no reescribir los enlaces con tracking (mjt.lu).
            # Importante en enlaces temporales de recuperación y lectores móviles.
            "TrackClicks": "disabled",
            "TrackOpens": "disabled",
            "TextPart": texto,
        }
        if archivos:
            mensaje["Attachments"] = archivos
        mensajes.append(mensaje)

    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as cliente:
            respuesta = await cliente.post(
                URL_MAILJET,
                auth=httpx.BasicAuth(api_key, secret_key),
                headers={"Content-Type": "application/json", "User-Agent": "ACMA/1.0"},
                json={"Messages": mensajes},
            )
    except httpx.HTTPError as error:
        # El texto de la excepción podría contener datos sensibles.
        return "fallida", f"mailjet:red_{type(error).__name__}"

    if not 200 <= respuesta.status_code < 300:
        return "fallida", f"mailjet:http_{respuesta.status_code}"
    try:
        datos = respuesta.json()
    except (ValueError, TypeError):
        return "fallida", "mailjet:respuesta_invalida"
    resultados = datos.get("Messages") if isinstance(datos, dict) else None
    if not isinstance(resultados, list) or len(resultados) != len(mensajes):
        return "fallida", "mailjet:respuesta_invalida"
    if any(not isinstance(item, dict) or item.get("Status") != "success" for item in resultados):
        return "fallida", "mailjet:mensaje_rechazado"
    return "enviada", "mailjet:aceptada"
