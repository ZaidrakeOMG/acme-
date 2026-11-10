"""Webhooks de Meta y de Twilio: verificación, firma, estados de entrega y lectura, y mensajes entrantes (§6.1).
Nada sale a internet: solo se arma el cuerpo que mandaría el proveedor y se firma como él. F2-02."""
import hashlib
import hmac
import json

from core.config import config
from tests.folios_utiles import AP
from tests.mensajeria_utiles import (
    CON_AMBOS, limpiar_stub, notificar_de_prueba, telefono_en_claro, ultimo_envio,
)

SECRETO_META = "secreto-de-la-app-de-prueba"
TOKEN_TWILIO = "token-de-twilio-de-prueba"
URL_TWILIO = "http://prueba/api/mensajeria/webhook/twilio"


def _cuerpo_estado_meta(mensaje_id: str, estado: str, telefono: str) -> bytes:
    return json.dumps({"object": "whatsapp_business_account", "entry": [{"id": "1", "changes": [{"field": "messages",
        "value": {"messaging_product": "whatsapp", "statuses": [
            {"id": mensaje_id, "status": estado, "recipient_id": telefono.lstrip("+"),
             "timestamp": "1762700000"}]}}]}]}).encode()


def _cuerpo_entrante_meta(telefono: str, texto: str = "", boton: str = "") -> bytes:
    mensaje: dict = {"from": telefono.lstrip("+"), "id": "wamid.PRUEBA", "timestamp": "1762700000"}
    if boton:
        mensaje |= {"type": "button", "button": {"text": boton, "payload": boton}}
    else:
        mensaje |= {"type": "text", "text": {"body": texto}}
    return json.dumps({"object": "whatsapp_business_account", "entry": [{"id": "1", "changes": [{"field": "messages",
        "value": {"messaging_product": "whatsapp", "messages": [mensaje]}}]}]}).encode()


def _firma_meta(cuerpo: bytes) -> dict[str, str]:
    return {"X-Hub-Signature-256": "sha256=" + hmac.new(SECRETO_META.encode(), cuerpo, hashlib.sha256).hexdigest()}


# ------------------------------------------------------------------ Meta
async def test_verificacion_del_webhook_de_meta(cliente, monkeypatch):
    monkeypatch.setattr(config, "whatsapp_verify_token", "token-de-verificacion")
    r = await cliente.get("/api/mensajeria/webhook/meta", params={
        "hub.mode": "subscribe", "hub.verify_token": "token-de-verificacion", "hub.challenge": "1234567890"})
    assert r.status_code == 200 and r.text == "1234567890"
    r = await cliente.get("/api/mensajeria/webhook/meta", params={
        "hub.mode": "subscribe", "hub.verify_token": "equivocado", "hub.challenge": "1234567890"})
    assert r.status_code == 403


async def test_el_webhook_de_meta_actualiza_entrega_y_lectura(cliente, auth, monkeypatch):
    monkeypatch.setattr(config, "whatsapp_app_secret", SECRETO_META)
    limpiar_stub()
    await notificar_de_prueba("folio.espera", CON_AMBOS, canales=["whatsapp"])
    envio = await ultimo_envio(CON_AMBOS, "whatsapp")
    assert envio["estado"] == "enviado"
    numero = await telefono_en_claro(CON_AMBOS)

    for estado, esperado in (("delivered", "entregado"), ("read", "leido")):
        cuerpo = _cuerpo_estado_meta(envio["mensaje_id"], estado, numero)
        r = await cliente.post("/api/mensajeria/webhook/meta", content=cuerpo, headers=_firma_meta(cuerpo))
        assert r.status_code == 200, r.text
        assert r.json()["estados"] == 1
        actual = await ultimo_envio(CON_AMBOS, "whatsapp")
        assert actual["estado"] == esperado

    # Un fallo informado por el proveedor también se registra.
    cuerpo = _cuerpo_estado_meta(envio["mensaje_id"], "failed", numero)
    r = await cliente.post("/api/mensajeria/webhook/meta", content=cuerpo, headers=_firma_meta(cuerpo))
    assert r.status_code == 200 and (await ultimo_envio(CON_AMBOS, "whatsapp"))["estado"] == "fallido"


async def test_el_webhook_de_meta_rechaza_una_firma_invalida(cliente, monkeypatch):
    monkeypatch.setattr(config, "whatsapp_app_secret", SECRETO_META)
    cuerpo = _cuerpo_estado_meta("stub-cualquiera", "delivered", "+521555010003")
    r = await cliente.post("/api/mensajeria/webhook/meta", content=cuerpo,
                           headers={"X-Hub-Signature-256": "sha256=" + "0" * 64})
    assert r.status_code == 403 and r.json()["codigo"] == "FIRMA_INVALIDA"
    r = await cliente.post("/api/mensajeria/webhook/meta", content=cuerpo)
    assert r.status_code == 403, "sin firma no se procesa nada"


async def test_un_mensaje_entrante_de_meta_da_de_baja_el_canal(cliente, auth, monkeypatch):
    monkeypatch.setattr(config, "whatsapp_app_secret", SECRETO_META)
    numero = await telefono_en_claro(CON_AMBOS)
    cuerpo = _cuerpo_entrante_meta(numero, texto="BAJA")
    r = await cliente.post("/api/mensajeria/webhook/meta", content=cuerpo, headers=_firma_meta(cuerpo))
    assert r.status_code == 200 and r.json()["entrantes"] == 1
    from tests.mensajeria_utiles import mi_telefono

    assert (await mi_telefono(cliente, auth, CON_AMBOS))["whatsapp"]["activo"] is False
    # Y se reactiva con ALTA.
    cuerpo = _cuerpo_entrante_meta(numero, texto="ALTA")
    r = await cliente.post("/api/mensajeria/webhook/meta", content=cuerpo, headers=_firma_meta(cuerpo))
    assert r.status_code == 200
    assert (await mi_telefono(cliente, auth, CON_AMBOS))["whatsapp"]["activo"] is True


# ------------------------------------------------------------------ Twilio
async def test_el_webhook_de_twilio_actualiza_el_estado_con_firma_valida(cliente, auth, monkeypatch):
    from services.mensajeria.twilio import cuerpo_formulario, firmar_para_pruebas

    monkeypatch.setattr(config, "twilio_auth_token", TOKEN_TWILIO)
    limpiar_stub()
    await notificar_de_prueba("folio.espera", CON_AMBOS, canales=["sms"])
    envio = await ultimo_envio(CON_AMBOS, "sms")
    assert envio["estado"] == "enviado" and envio["segmentos"] == 1

    parametros = {"MessageSid": envio["mensaje_id"], "MessageStatus": "delivered"}
    firma = firmar_para_pruebas(TOKEN_TWILIO, URL_TWILIO, parametros)
    r = await cliente.post("/api/mensajeria/webhook/twilio", content=cuerpo_formulario(parametros),
                           headers={"X-Twilio-Signature": firma,
                                    "Content-Type": "application/x-www-form-urlencoded"})
    assert r.status_code == 200, r.text
    assert r.json()["estados"] == 1
    assert (await ultimo_envio(CON_AMBOS, "sms"))["estado"] == "entregado"

    # Firma inválida: no se toca nada.
    r = await cliente.post("/api/mensajeria/webhook/twilio", content=cuerpo_formulario(parametros),
                           headers={"X-Twilio-Signature": "otra-cosa",
                                    "Content-Type": "application/x-www-form-urlencoded"})
    assert r.status_code == 403 and r.json()["codigo"] == "FIRMA_INVALIDA"


async def test_un_sms_entrante_de_twilio_se_registra(cliente, auth, monkeypatch):
    from services.mensajeria.twilio import cuerpo_formulario, firmar_para_pruebas

    monkeypatch.setattr(config, "twilio_auth_token", TOKEN_TWILIO)
    numero = await telefono_en_claro(CON_AMBOS)
    parametros = {"MessageSid": "SM-entrante", "From": numero, "Body": "BAJA", "To": "+520000000000"}
    firma = firmar_para_pruebas(TOKEN_TWILIO, URL_TWILIO, parametros)
    r = await cliente.post("/api/mensajeria/webhook/twilio", content=cuerpo_formulario(parametros),
                           headers={"X-Twilio-Signature": firma,
                                    "Content-Type": "application/x-www-form-urlencoded"})
    assert r.status_code == 200 and r.json()["entrantes"] == 1
    from tests.mensajeria_utiles import mi_telefono

    assert (await mi_telefono(cliente, auth, CON_AMBOS))["sms"]["activo"] is False
    r = await cliente.put("/api/usuarios/me/consentimiento", headers=await auth(CON_AMBOS),
                          json={"canal": "sms", "acepta": True})
    assert r.status_code == 200 and r.json()["sms"]["activo"] is True


# ------------------------------------------------------------------ simulación local
async def test_la_simulacion_cambia_el_estado_sin_firma(cliente, auth):
    """En local el proveedor no alcanza la máquina de la usuaria: este endpoint hace su papel."""
    limpiar_stub()
    await notificar_de_prueba("folio.espera", CON_AMBOS, canales=["whatsapp"])
    envio = await ultimo_envio(CON_AMBOS, "whatsapp")
    r = await cliente.post("/api/mensajeria/webhook/simular", headers=await auth(AP),
                           json={"mensaje_id": envio["mensaje_id"], "estado": "leido"})
    assert r.status_code == 200, r.text
    assert r.json()["estado"] == "leido"
    assert (await ultimo_envio(CON_AMBOS, "whatsapp"))["estado"] == "leido"


async def test_los_mensajes_del_proveedor_simulado_se_pueden_revisar(cliente, auth):
    limpiar_stub()
    await notificar_de_prueba("folio.espera", CON_AMBOS, canales=["whatsapp"])
    r = await cliente.get("/api/mensajeria/simulados", headers=await auth(AP))
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["modo_whatsapp"] == "stub" and cuerpo["mensajes"]
    assert cuerpo["mensajes"][0]["plantilla"] == "folio_en_espera"
    assert "destino_final" in cuerpo["mensajes"][0] and len(cuerpo["mensajes"][0]["destino_final"]) == 4


async def test_la_prueba_de_envio_la_hace_el_administrador(cliente, auth):
    """En modo stub el mensaje de prueba solo se guarda como vista previa; con una cuenta real exige número propio."""
    limpiar_stub()
    r = await cliente.post("/api/mensajeria/prueba", headers=await auth(AP),
                           json={"canal": "whatsapp", "telefono": "+521555019009",
                                 "clave": "notificacion_generica"})
    assert r.status_code == 200, r.text
    assert r.json()["estado"] == "enviado" and r.json()["modo"] == "stub" and r.json()["cuerpo"]
    # El Admin prestador del demo no tiene teléfono propio: sin número indicado no hay a dónde mandar.
    r = await cliente.post("/api/mensajeria/prueba", headers=await auth(AP), json={"canal": "sms"})
    assert r.status_code == 409 and r.json()["codigo"] == "SIN_TELEFONO"
    # Y un rol que no administra no manda pruebas.
    r = await cliente.post("/api/mensajeria/prueba", headers=await auth("despachador@acma.dev"),
                           json={"canal": "sms", "telefono": "+521555019009"})
    assert r.status_code == 403
