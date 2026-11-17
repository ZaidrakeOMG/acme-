"""Correo saliente por SMTP genérico (aiosmtplib): sirve para el correo corporativo o el nivel gratuito de SendGrid por SMTP.
Sin credenciales (`SMTP_HOST` vacío) opera en modo `stub`: guarda el `.eml` en el almacenamiento y lo registra en el log.
Plantillas HTML con el logo y los colores del prestador en `backend/plantillas/correo/` (§7.5)."""
import html
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path
from typing import Any

from core.config import config
from services.almacenamiento import obtener_almacenamiento

log = logging.getLogger("acma.correo")
PLANTILLAS = Path(__file__).resolve().parents[1] / "plantillas" / "correo"
ENVIADOS: list[dict[str, Any]] = []  # últimos correos (modo stub y pruebas)


@dataclass
class Adjunto:
    nombre: str
    contenido: bytes
    mime: str = "application/pdf"


@dataclass
class Correo:
    destinatarios: list[str]
    asunto: str
    html: str
    texto: str = ""
    adjuntos: list[Adjunto] = field(default_factory=list)
    remitente: str | None = None


def modo() -> str:
    """Proveedor activo. El modo auto conserva la prioridad histórica."""
    seleccionado = config.correo_proveedor
    if seleccionado != "auto":
        return seleccionado
    if config.resend_api_key:
        return "resend"
    return "smtp" if config.smtp_host else "stub"


def recuperacion_configurada() -> bool:
    """Guardia para todos los usuarios ANTES de consultar si existe su correo."""
    proveedor = modo()
    if proveedor == "mailjet":
        return bool(config.mailjet_api_key and config.mailjet_secret_key and config.mailjet_from)
    if proveedor == "resend":
        return bool(config.resend_api_key and config.resend_from)
    if proveedor == "smtp":
        return bool(config.smtp_host)
    return False


def plantilla(nombre: str, **valores: Any) -> str:
    """Rellena `plantillas/correo/<nombre>.html` dentro de `base.html`. Los valores se escapan salvo los que terminan en `_html`."""
    cuerpo = (PLANTILLAS / f"{nombre}.html").read_text(encoding="utf-8")
    base = (PLANTILLAS / "base.html").read_text(encoding="utf-8")
    seguros = {k: (v if k.endswith("_html") else html.escape(str(v if v is not None else ""))) for k, v in valores.items()}
    seguros.setdefault("color_primario", "#1C3D8F")
    seguros.setdefault("color_acento", "#A2C62B")
    seguros.setdefault("prestador", "ACMA")
    seguros.setdefault("logo_html", "")
    seguros.setdefault("titulo", seguros.get("asunto", "ACMA"))

    class _Dict(dict):
        def __missing__(self, k: str) -> str:
            return ""

    contenido = cuerpo.format_map(_Dict(seguros))
    return base.format_map(_Dict({**seguros, "contenido_html": contenido, "anio": datetime.now(UTC).year}))


def _construir(c: Correo) -> EmailMessage:
    m = EmailMessage()
    m["From"] = c.remitente or config.smtp_from
    m["To"] = ", ".join(c.destinatarios)
    m["Subject"] = c.asunto
    m["Message-ID"] = make_msgid(domain="acma.local")
    m.set_content(c.texto or _texto_plano(c.html))
    m.add_alternative(c.html, subtype="html")
    for a in c.adjuntos:
        tipo, _, subtipo = a.mime.partition("/")
        m.add_attachment(a.contenido, maintype=tipo or "application", subtype=subtipo or "octet-stream", filename=a.nombre)
    return m


def _texto_plano(h: str) -> str:
    import re

    t = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", h, flags=re.S | re.I)
    t = re.sub(r"<br\s*/?>|</p>|</h\d>|</li>|</tr>", "\n", t, flags=re.I)
    t = re.sub(r"<[^>]+>", "", t)
    return html.unescape(re.sub(r"\n{3,}", "\n\n", t)).strip()


async def enviar(c: Correo) -> tuple[str, str]:
    """Devuelve (estado, detalle): estado `enviada` | `fallida`; en modo stub `enviada` con la clave del .eml guardado."""
    if not c.destinatarios:
        return "omitida", "sin destinatarios"
    mensaje = _construir(c)
    registro = {"destinatarios": list(c.destinatarios), "asunto": c.asunto, "adjuntos": [a.nombre for a in c.adjuntos], "timestamp": datetime.now(UTC).isoformat()}
    if modo() == "stub":
        clave = f"correo/{datetime.now(UTC):%Y/%m/%d}/{mensaje['Message-ID'].strip('<>')}.eml"
        try:
            obtener_almacenamiento().guardar(clave, mensaje.as_bytes(), "message/rfc822")
        except Exception as e:  # noqa: BLE001 — sin almacenamiento el correo solo queda en el log
            log.warning("Correo stub sin almacenamiento (%s): %s → %s", e, c.asunto, c.destinatarios)
            clave = ""
        ENVIADOS.append({**registro, "modo": "stub", "clave": clave, "html": c.html})
        del ENVIADOS[:-200]
        log.info("Correo (stub) «%s» a %s%s", c.asunto, ", ".join(c.destinatarios), f" guardado en {clave}" if clave else "")
        return "enviada", f"stub:{clave}"
    if modo() == "mailjet":
        from services.mailjet_api import enviar_mailjet

        estado, detalle = await enviar_mailjet(
            api_key=config.mailjet_api_key,
            secret_key=config.mailjet_secret_key,
            remitente=c.remitente or config.mailjet_from,
            destinatarios=list(c.destinatarios),
            asunto=c.asunto,
            html=c.html,
            texto=c.texto or _texto_plano(c.html),
            adjuntos=[(adj.nombre, adj.contenido) for adj in c.adjuntos],
        )
        # No registrar cuerpos HTML, enlaces/token ni claves de la API en logs.
        ENVIADOS.append({**registro, "modo": "mailjet", "estado": estado, "detalle": detalle})
        del ENVIADOS[:-200]
        if estado != "enviada":
            log.warning("Envío Mailjet no aceptado: %s", detalle)
        return estado, detalle
    if modo() == "resend":
        from services.resend_api import enviar_resend

        estado, detalle = await enviar_resend(
            api_key=config.resend_api_key,
            remitente=c.remitente or config.resend_from,
            destinatarios=list(c.destinatarios),
            asunto=c.asunto,
            html=c.html,
            texto=c.texto or _texto_plano(c.html),
            adjuntos=[(adjunto.nombre, adjunto.contenido) for adjunto in c.adjuntos],
        )
        # No registrar HTML/tokens ni la clave API en logs de Railway.
        ENVIADOS.append({**registro, "modo": "resend", "estado": estado, "detalle": detalle})
        del ENVIADOS[:-200]
        if estado != "enviada":
            log.warning("Envío Resend no aceptado: %s", detalle)
        return estado, detalle
    import aiosmtplib

    try:
        await aiosmtplib.send(mensaje, hostname=config.smtp_host, port=config.smtp_port, username=config.smtp_user or None,
                              password=config.smtp_password or None, use_tls=config.smtp_tls == "ssl", start_tls=config.smtp_tls == "starttls",
                              timeout=20)
    except Exception as e:  # noqa: BLE001
        log.error("Fallo SMTP al enviar «%s»: %s", c.asunto, e)
        ENVIADOS.append({**registro, "modo": "smtp", "error": str(e)})
        return "fallida", str(e)
    ENVIADOS.append({**registro, "modo": "smtp"})
    del ENVIADOS[:-200]
    return "enviada", f"smtp:{config.smtp_host}"
