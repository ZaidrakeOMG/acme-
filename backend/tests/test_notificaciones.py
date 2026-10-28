"""Notificaciones multicanal (§6.1, P07): notificar() por preferencia y evento, canales Fase 2 omitidos, bandeja y no leídas,
correo en modo stub (.eml en el almacenamiento) y por SMTP contra un servidor local (aiosmtpd)."""
import asyncio
import threading

import pytest

from core.config import config
from services import correo
from services.almacenamiento import obtener_almacenamiento
from tests.folios_utiles import AE, AP, AUN, DES, MC, OP
from tests.seguimiento_utiles import bandeja, crear_registro


async def test_preferencias_canales_y_bandeja(cliente, auth, datos):
    h = await auth(DES)
    eventos = (await cliente.get("/api/notificaciones/eventos", headers=h)).json()
    assert {e["clave"] for e in eventos["eventos"]} >= {"minuta.enviada", "cotizacion.solicitada", "aprobacion.pendiente"}
    assert [c["clave"] for c in eventos["canales"] if c["fase"] == 2] == ["whatsapp", "sms"]
    r = await cliente.put("/api/notificaciones/preferencias", headers=h, json={"evento": "no.existe", "canales": ["app"]})
    assert r.status_code == 422 and r.json()["codigo"] == "EVENTO_DESCONOCIDO"
    r = await cliente.put("/api/notificaciones/preferencias", headers=h, json={"evento": "cotizacion.solicitada", "canales": ["app", "whatsapp", "sms"]})
    assert r.status_code == 200 and r.json()["canales"] == ["app", "whatsapp", "sms"]
    assert any(p["evento"] == "cotizacion.solicitada" for p in (await cliente.get("/api/notificaciones/preferencias", headers=h)).json())
    antes = (await cliente.get("/api/notificaciones/no-leidas", headers=h)).json()["no_leidas"]
    # El Admin UN solicita una cotización: Mesa de control, Despachador y Admin prestador la reciben; para el despachador whatsapp/sms quedan omitidas.
    c = await crear_registro(cliente, auth, "cotizaciones", datos, AUN, descripcion="Cotizar cambio de compresor")
    for email in (DES, MC, AP):
        nuevas = [n for n in await bandeja(cliente, auth, email, solo_no_leidas=True) if n["datos"].get("cotizacion_id") == c["id"]]
        assert nuevas and nuevas[0]["evento"] == "cotizacion.solicitada" and nuevas[0]["canal"] == "app" and nuevas[0]["url"].endswith(c["id"]), email
    assert (await cliente.get("/api/notificaciones/no-leidas", headers=h)).json()["no_leidas"] == antes + 1
    from sqlalchemy import select

    from core.db import nueva_sesion
    from core.rls import CONTEXTO_SISTEMA
    from models.minutas import Notificacion

    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        filas = (await db.execute(select(Notificacion).where(Notificacion.evento == "cotizacion.solicitada", Notificacion.cuerpo_json["datos"]["cotizacion_id"].astext == c["id"]))).scalars().all()
    por_canal = {(str(n.usuario_id), n.canal.value): (n.estado.value, n.proveedor_respuesta) for n in filas}
    desp = (await cliente.get("/api/usuarios", headers=await auth(AP), params={"rol": "despachador"})).json()[0]["id"]
    assert por_canal[(desp, "app")][0] == "enviada" and por_canal[(desp, "whatsapp")] == ("omitida", "canal Fase 2") and por_canal[(desp, "sms")] == ("omitida", "canal Fase 2")
    assert (desp, "email") not in por_canal  # la preferencia excluyó el correo
    # Marcar leídas: por id y todas.
    ids = [n["id"] for n in await bandeja(cliente, auth, DES, solo_no_leidas=True)][:1]
    assert (await cliente.post("/api/notificaciones/leidas", headers=h, json={"ids": ids})).json()["marcadas"] == 1
    await cliente.post("/api/notificaciones/leidas", headers=h, json={})
    assert (await cliente.get("/api/notificaciones/no-leidas", headers=h)).json()["no_leidas"] == 0
    assert all(n["leida_at"] for n in await bandeja(cliente, auth, DES))
    # Cada quien ve solo su bandeja.
    assert all(n["datos"].get("cotizacion_id") != c["id"] for n in await bandeja(cliente, auth, OP))
    await cliente.put("/api/notificaciones/preferencias", headers=h, json={"evento": "cotizacion.solicitada", "canales": ["app", "push", "email"]})


async def test_correo_stub_guarda_eml_con_adjunto(cliente, auth, datos):
    assert correo.modo() == "stub"
    antes = len(correo.ENVIADOS)
    estado, detalle = await correo.enviar(correo.Correo(destinatarios=["cliente@prueba.mx"], asunto="Prueba stub", html=correo.plantilla("generico", titulo="Prueba", cuerpo="Hola <b>", detalle_html="<p>x</p>", url="http://x", texto_boton="Abrir"),
                                                        adjuntos=[correo.Adjunto(nombre="a.pdf", contenido=b"%PDF-1.4 prueba")]))
    assert estado == "enviada" and detalle.startswith("stub:correo/")
    registro = correo.ENVIADOS[-1]
    assert len(correo.ENVIADOS) == antes + 1 and registro["modo"] == "stub" and registro["adjuntos"] == ["a.pdf"] and "Hola &lt;b&gt;" in registro["html"]
    eml = obtener_almacenamiento().leer(registro["clave"])
    assert b"Subject: Prueba stub" in eml and b"Content-Disposition: attachment; filename=\"a.pdf\"" in eml and b"text/html" in eml
    assert (await correo.enviar(correo.Correo(destinatarios=[], asunto="x", html="<p>x</p>")))[0] == "omitida"


class _Buzon:
    def __init__(self) -> None:
        self.mensajes: list = []

    async def handle_DATA(self, server, session, envelope):
        self.mensajes.append(envelope)
        return "250 OK"


async def test_correo_por_smtp_contra_servidor_local(monkeypatch):
    from aiosmtpd.controller import Controller

    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        puerto = s.getsockname()[1]
    buzon = _Buzon()
    controlador = Controller(buzon, hostname="127.0.0.1", port=puerto)
    controlador.start()
    try:
        monkeypatch.setattr(config, "smtp_host", "127.0.0.1")
        monkeypatch.setattr(config, "smtp_port", controlador.port)
        monkeypatch.setattr(config, "smtp_tls", "none")
        monkeypatch.setattr(config, "smtp_from", "ACMA Pruebas <acma@prueba.local>")
        assert correo.modo() == "smtp"
        estado, detalle = await correo.enviar(correo.Correo(destinatarios=["destino@prueba.local", "otro@prueba.local"], asunto="Minuta de prueba SMTP", html="<p>Cuerpo</p>",
                                                            adjuntos=[correo.Adjunto(nombre="minuta.pdf", contenido=b"%PDF-1.4 x")]))
        assert estado == "enviada" and detalle == "smtp:127.0.0.1"
        for _ in range(50):
            if buzon.mensajes:
                break
            await asyncio.sleep(0.05)
        assert len(buzon.mensajes) == 1
        env = buzon.mensajes[0]
        assert env.mail_from == "acma@prueba.local" and sorted(env.rcpt_tos) == ["destino@prueba.local", "otro@prueba.local"]
        assert b"Subject: Minuta de prueba SMTP" in env.content and b'filename="minuta.pdf"' in env.content
        assert correo.ENVIADOS[-1]["modo"] == "smtp"
        # Servidor caído → fallida, sin excepción.
        monkeypatch.setattr(config, "smtp_port", 1)
        estado, _ = await correo.enviar(correo.Correo(destinatarios=["x@prueba.local"], asunto="falla", html="<p>x</p>"))
        assert estado == "fallida"
    finally:
        controlador.stop()


async def test_notificacion_email_usa_plantilla_del_prestador(cliente, auth, datos):
    """Una notificación con canal email se envía (stub) con el HTML de la plantilla y los colores del prestador."""
    from core.db import nueva_sesion
    from core.rls import CONTEXTO_SISTEMA
    from services import notificaciones_service

    antes = len(correo.ENVIADOS)
    ae = (await cliente.get("/api/usuarios", headers=await auth(AE), params={"rol": "admin_empresa"})).json()[0]
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        creadas = await notificaciones_service.notificar(db, "alerta", [ae["id"]], {"detalle_html": "<p>Detalle <b>html</b></p>"}, asunto="Alerta de prueba", cuerpo="Cuerpo de la alerta",
                                                         url="/alertas", tenant_id=datos["tenant"], prestador_id=datos["prestador"], canales=["email", "app"])
        await db.commit()
    assert {c.canal.value: c.estado.value for c in creadas} == {"email": "enviada", "app": "enviada"}
    ultimo = correo.ENVIADOS[-1]
    assert len(correo.ENVIADOS) == antes + 1 and ultimo["destinatarios"] == [ae["email"]] and "Prestador Demo" in ultimo["html"] and "#1C3D8F" in ultimo["html"]
    assert "Detalle <b>html</b>" in ultimo["html"] and "http://localhost:5173/alertas" in ultimo["html"]
    assert any(n["asunto"] == "Alerta de prueba" for n in await bandeja(cliente, auth, AE))


@pytest.mark.parametrize("ruta", ["/api/notificaciones", "/api/notificaciones/no-leidas", "/api/notificaciones/preferencias"])
async def test_rutas_requieren_sesion(cliente, ruta):
    assert (await cliente.get(ruta)).status_code == 401


def test_hilo_libre():
    assert threading.active_count() >= 1
