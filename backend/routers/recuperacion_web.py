"""Formulario HTML sin JavaScript para restablecer contraseña desde Safari/iPhone.

Conserva la misma validación, vigencia de 30 minutos, política de contraseñas
y revocación de sesiones que la API. No utiliza React ni service workers.
"""
from __future__ import annotations

import html
import re
from string import Template
from urllib.parse import parse_qs

from fastapi import APIRouter, Request
from starlette.responses import HTMLResponse

from core.dependencias import DB
from core.errors import ErrorAPI
from services import auth_service

router = APIRouter(tags=["Recuperación web"])

_TOKEN = re.compile(r"^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$")
_HTML = Template("""<!doctype html>
<html lang="es-MX">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <meta name="referrer" content="no-referrer">
  <meta name="robots" content="noindex, nofollow, noarchive">
  <title>$titulo · ACMA</title>
  <style>
    *{box-sizing:border-box}
    html{color-scheme:light;-webkit-text-size-adjust:100%}
    body{margin:0;min-height:100vh;min-height:100dvh;display:grid;place-items:center;
      padding:32px 16px max(32px,env(safe-area-inset-bottom));background:#f8f6f8;
      font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif;color:#29252a}
    .card{width:100%;max-width:440px;padding:28px 24px;background:#fff;
      border:1px solid #eadde2;border-radius:22px;box-shadow:0 12px 45px #30121b12}
    .brand{display:flex;align-items:center;gap:14px;border-bottom:1px solid #f1e7ec;
      padding-bottom:18px;margin-bottom:22px}
    .brand img{width:54px;height:54px;object-fit:contain;border:1px solid #f0e3e7;border-radius:14px}
    .brand strong{display:block;font-size:21px;letter-spacing:.1em;color:#26232a}
    .brand small{font-size:12px;color:#826f78}
    h1{font-size:23px;line-height:1.2;margin:0 0 10px;letter-spacing:-.025em}
    p{font-size:14px;color:#615760;margin:0 0 16px}
    label{display:block;font-size:14px;font-weight:650;margin:16px 0 7px}
    input{display:block;width:100%;border-radius:12px;border:1px solid #d8cbd1;
      min-height:50px;padding:12px;font-size:16px;background:#fff;color:#222}
    input:focus{outline:3px solid #a70d2d25;border-color:#a70d2d}
    button{width:100%;min-height:50px;margin-top:22px;color:white;background:#97213e;
      font-size:16px;font-weight:700;border:0;border-radius:12px;cursor:pointer}
    .error{background:#fff1f2;border:1px solid #fecdd3;color:#9f1239;
      border-radius:10px;padding:12px;margin-bottom:16px;font-size:14px}
    .ok{background:#f0fdf4;border:1px solid #bbf7d0;color:#166534;
      border-radius:10px;padding:12px;margin-bottom:16px;font-size:14px}
    .ayuda{font-size:12px;line-height:1.6;color:#7a6e77;margin:16px 0}
    .volver{display:block;text-align:center;margin-top:22px;color:#97213e;font-size:14px;font-weight:650}
  </style>
</head>
<body>
  <main class="card">
    <div class="brand"><img src="/icono.svg" alt=""><span><strong>ACMA</strong>
      <small>Acceso seguro</small></span></div>
    <h1>$titulo</h1>
    $contenido
    <a class="volver" href="/">Volver al inicio de sesión</a>
  </main>
</body>
</html>""")

_CABECERAS = {
    "Cache-Control": "no-store, max-age=0",
    "Pragma": "no-cache",
    "Referrer-Policy": "no-referrer",
    "X-Robots-Tag": "noindex, nofollow, noarchive",
}


def _pagina(titulo: str, contenido: str, estado: int = 200) -> HTMLResponse:
    return HTMLResponse(
        _HTML.substitute(titulo=html.escape(titulo), contenido=contenido),
        status_code=estado, headers=_CABECERAS,
    )


def _formulario(token: str, error: str | None = None) -> HTMLResponse:
    aviso = f'<div role="alert" class="error">{html.escape(error)}</div>' if error else ""
    seguro = html.escape(token, quote=True)
    return _pagina("Cambia tu contraseña", f"""
    <p>Introduce una contraseña nueva. El enlace del correo es de un solo uso
      y vence a los 30 minutos.</p>
    {aviso}
    <form method="post" action="/restablecer/seguro" accept-charset="UTF-8">
      <input type="hidden" name="token" value="{seguro}">
      <label for="nueva">Contraseña nueva</label>
      <input id="nueva" name="nueva" type="password" required minlength="10" maxlength="128"
        autocomplete="new-password">
      <label for="confirmacion">Confirma la contraseña</label>
      <input id="confirmacion" name="confirmacion" type="password" required minlength="10" maxlength="128"
        autocomplete="new-password">
      <p class="ayuda">Mínimo 10 caracteres con mayúscula, minúscula, número y símbolo.
        No reutilices una de tus últimas 10 contraseñas.</p>
      <button type="submit">Guardar contraseña nueva</button>
    </form>""")


@router.get("/restablecer/seguro", response_class=HTMLResponse, include_in_schema=False)
async def restablecer_pagina(token: str = "") -> HTMLResponse:
    if len(token) > 4096 or not _TOKEN.fullmatch(token):
        return _pagina("Enlace incompleto",
                       '<div role="alert" class="error">El enlace no es válido. Solicita otro correo desde ACMA.</div>',
                       400)
    return _formulario(token)


@router.post("/restablecer/seguro", response_class=HTMLResponse, include_in_schema=False)
async def restablecer_guardar(request: Request, db: DB) -> HTMLResponse:
    if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/x-www-form-urlencoded":
        return _pagina("Solicitud no válida", '<div class="error">Formato de solicitud no admitido.</div>', 415)
    # Protección frente a cuerpos enormes y campos duplicados.
    cuerpo = await request.body()
    if len(cuerpo) > 12000:
        return _pagina("Solicitud no válida", '<div class="error">Solicitud demasiado grande.</div>', 413)
    try:
        campos = parse_qs(cuerpo.decode("utf-8"), keep_blank_values=True, max_num_fields=5)
        if any(len(campos.get(k, [])) != 1 for k in ("token", "nueva", "confirmacion")):
            raise ValueError("Campos faltantes o duplicados")
        token, nueva, confirmacion = (campos[k][0] for k in ("token", "nueva", "confirmacion"))
    except (ValueError, UnicodeDecodeError):
        return _pagina("Solicitud no válida", '<div class="error">Campos incorrectos.</div>', 400)
    if not _TOKEN.fullmatch(token) or len(token) > 4096:
        return _pagina("Enlace no válido", '<div class="error">Solicita otro enlace de recuperación.</div>', 400)
    if len(nueva) > 128 or len(nueva) < 10 or nueva != confirmacion:
        return _formulario(token, "Comprueba que las dos contraseñas coincidan y tengan al menos 10 caracteres.")
    try:
        await auth_service.confirmar_restablecimiento(db, request, token, nueva)
    except ErrorAPI as exc:
        await db.rollback()
        return _formulario(token, exc.mensaje)
    return _pagina("Contraseña actualizada",
                   '<div role="status" class="ok">Ya puedes iniciar sesión con tu nueva contraseña. '
                   'Por seguridad, tus sesiones anteriores se cerraron.</div>')
