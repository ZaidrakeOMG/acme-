"""Capa de proveedores de mensajería: catálogo de plantillas, segmentos de SMS, proveedor simulado, firmas de
webhook y límite de tasa (§6.1). Ninguna prueba llama a Meta ni a Twilio de verdad. F2-02."""
import hashlib
import hmac
import json

import pytest

from core.config import config
from services.mensajeria import base as texto
from services.mensajeria import plantillas as catalogo
from services.mensajeria import proveedores
from services.mensajeria.meta_cloud import ProveedorMetaCloud
from services.mensajeria.stub import ENVIADOS, FALLAS, ProveedorStub
from services.mensajeria.twilio import ProveedorTwilio, cuerpo_formulario, firmar_para_pruebas
from tests.folios_utiles import AP, DES, OP
from tests.mensajeria_utiles import limpiar_stub, plantilla, plantillas


# ------------------------------------------------------------------ catálogo
def test_ninguna_plantilla_lleva_datos_financieros_ni_personales():
    """§6.9.5: en el cuerpo solo van folio, sucursal, estado y enlace; ni montos ni datos de terceros."""
    con_datos = {p.clave: catalogo.datos_sensibles(p) for p in catalogo.CATALOGO if catalogo.datos_sensibles(p)}
    assert con_datos == {}, f"plantillas con datos prohibidos: {con_datos}"


def test_cada_evento_del_prompt_tiene_su_plantilla():
    """Los eventos que §6.1 enumera tienen plantilla propia; el resto cae en la genérica, no en el vacío."""
    esperadas = {"folio_creado", "folio_autorizado", "folio_asignado", "folio_en_camino", "folio_cerrado",
                 "folio_rechazado", "aprobacion_pendiente", "aprobacion_bloqueada", "minuta_disponible",
                 "cotizacion_enviada", "cotizacion_por_vencer", "trabajo_especial_por_validar",
                 "preventivo_por_reprogramar", "certificacion_por_vencer", "sla_incumplido", "alerta_generica",
                 "codigo_verificacion", "notificacion_generica"}
    assert esperadas <= set(catalogo.POR_CLAVE)
    # Todas tienen texto en los dos canales y un botón o un enlace para llegar a la pantalla exacta.
    for p in catalogo.CATALOGO:
        assert p.whatsapp and p.sms, p.clave
        if p.clave != "codigo_verificacion":
            assert p.botones or "{enlace}" in p.sms, p.clave
    # El restablecimiento de contraseña sigue siendo solo por correo: no tiene plantilla de mensajería.
    assert not any("contrasena" in p.clave or "restablec" in p.clave for p in catalogo.CATALOGO)


def test_el_evento_resuelve_la_plantilla_por_subtipo():
    assert catalogo.clave_de_evento("folio.estado", {"estado": "asignado"}) == "folio_asignado"
    assert catalogo.clave_de_evento("folio.estado", {"estado": "cerrado"}) == "folio_cerrado"
    # Un estado sin plantilla propia usa la primera del evento sin subtipo; si no hay, la genérica.
    assert catalogo.clave_de_evento("alerta", {"alerta": "SLA_INCUMPLIDO"}) == "sla_incumplido"
    assert catalogo.clave_de_evento("alerta", {"alerta": "STOCK_MINIMO"}) == "alerta_generica"
    assert catalogo.clave_de_evento("evento.que.no.existe") == "notificacion_generica"


def test_los_sms_del_catalogo_caben_en_un_segmento_gsm7():
    """§6.1: un solo segmento cuando sea posible; con acentos el SMS pasaría a UCS-2 y a 70 caracteres."""
    problemas = []
    for p in catalogo.CATALOGO:
        cuerpo = texto.renderizar(p.sms, [str(p.ejemplo.get(v, v)) for v in p.variables],
                                  enlace="http://localhost:5173/l/abc12345")
        segmentos, codificacion = texto.segmentos_sms(cuerpo)
        if codificacion != "GSM-7" or segmentos > 1:
            problemas.append((p.clave, segmentos, codificacion, len(cuerpo)))
    assert problemas == [], f"SMS que no caben en un segmento GSM-7: {problemas}"


# ------------------------------------------------------------------ texto
def test_segmentos_y_codificacion_del_sms():
    assert texto.segmentos_sms("ACMA: folio F-1 asignado.") == (1, "GSM-7")
    assert texto.segmentos_sms("a" * 160) == (1, "GSM-7")
    assert texto.segmentos_sms("a" * 161) == (2, "GSM-7")
    # Un solo acento cambia la codificación y el límite baja a 70.
    segmentos, codificacion = texto.segmentos_sms("Atención: " + "a" * 65)
    assert (segmentos, codificacion) == (2, "UCS-2")
    assert texto.segmentos_sms("Atención") == (1, "UCS-2")
    assert texto.segmentos_sms("") == (0, "GSM-7")
    # Los caracteres de la tabla de extensión ocupan dos posiciones.
    assert texto.longitud_sms("[") == 2


def test_renderizar_sustituye_variables_y_enlace():
    cuerpo = texto.renderizar("Folio {{1}} en {{2}}. Abre {enlace}", ["F-1", "SUC-001"], "http://x/l/abc")
    assert cuerpo == "Folio F-1 en SUC-001. Abre http://x/l/abc"
    # Una variable que no llegó no deja «{{3}}» a la vista.
    assert "{{" not in texto.renderizar("Hola {{1}} {{2}}", ["Ana"])


# ------------------------------------------------------------------ proveedor simulado
async def test_el_stub_guarda_la_vista_previa_y_simula_la_entrega():
    limpiar_stub()
    mensaje = texto.MensajeSaliente(canal="whatsapp", telefono="+521555019999", cuerpo="Hola desde ACMA",
                                    plantilla_clave="notificacion_generica", botones=[{"texto": "Abrir", "ruta": "/"}])
    r = await ProveedorStub().enviar_plantilla(mensaje)
    assert r.estado == "enviado" and r.mensaje_id.startswith("stub-")
    assert ENVIADOS[-1]["cuerpo"] == "Hola desde ACMA"
    assert ENVIADOS[-1]["destino_final"] == "9999", "el stub no guarda el número completo"
    assert await ProveedorStub().estado(r.mensaje_id) == "entregado"


async def test_el_stub_simula_errores_temporales_y_permanentes():
    limpiar_stub()
    FALLAS["+521555019998"] = ("131026", True)
    FALLAS["+521555019997"] = ("RED", False)
    permanente = await ProveedorStub().enviar_plantilla(
        texto.MensajeSaliente(canal="whatsapp", telefono="+521555019998", cuerpo="x"))
    temporal = await ProveedorStub().enviar_plantilla(
        texto.MensajeSaliente(canal="sms", telefono="+521555019997", cuerpo="x"))
    assert (permanente.estado, permanente.permanente) == ("rechazado_por_proveedor", True)
    assert (temporal.estado, temporal.permanente) == ("fallido", False)
    limpiar_stub()


# ------------------------------------------------------------------ firmas de webhook
def test_firma_de_meta_valida_e_invalida(monkeypatch):
    monkeypatch.setattr(config, "whatsapp_app_secret", "secreto-de-la-app")
    cuerpo = json.dumps({"entry": []}).encode()
    firma = hmac.new(b"secreto-de-la-app", cuerpo, hashlib.sha256).hexdigest()
    proveedor = ProveedorMetaCloud()
    assert proveedor.validar_webhook(cuerpo, {"x-hub-signature-256": f"sha256={firma}"})
    assert not proveedor.validar_webhook(cuerpo, {"x-hub-signature-256": "sha256=" + "0" * 64})
    assert not proveedor.validar_webhook(cuerpo, {}), "sin firma no se acepta"
    monkeypatch.setattr(config, "whatsapp_app_secret", "")
    assert not proveedor.validar_webhook(cuerpo, {"x-hub-signature-256": f"sha256={firma}"}), \
        "sin secreto configurado el webhook queda cerrado"


def test_firma_de_twilio_valida_e_invalida(monkeypatch):
    monkeypatch.setattr(config, "twilio_auth_token", "token-de-twilio")
    parametros = {"MessageSid": "SM123", "MessageStatus": "delivered"}
    url = "http://prueba/api/mensajeria/webhook/twilio"
    firma = firmar_para_pruebas("token-de-twilio", url, parametros)
    proveedor = ProveedorTwilio()
    cuerpo = cuerpo_formulario(parametros)
    assert proveedor.validar_webhook(cuerpo, {"x-twilio-signature": firma, "x-acma-url": url})
    assert not proveedor.validar_webhook(cuerpo, {"x-twilio-signature": "otra", "x-acma-url": url})
    assert not proveedor.validar_webhook(cuerpo, {"x-twilio-signature": firma}), "sin la URL no se puede validar"


# ------------------------------------------------------------------ selección y límite de tasa
def test_el_modo_por_defecto_es_stub_y_nada_sale_de_la_maquina():
    assert proveedores.modo_de_canal("whatsapp") == "stub"
    assert proveedores.modo_de_canal("sms") == "stub"
    assert proveedores.nombre_proveedor("whatsapp") == "stub"
    assert isinstance(proveedores.obtener("sms"), ProveedorStub)


def test_sin_credenciales_el_modo_prueba_cae_al_stub(monkeypatch):
    """Una variable mal escrita no puede dejar al sistema sin canal: se usa el simulado y queda en el log."""
    monkeypatch.setattr(config, "whatsapp_modo", "prueba")
    monkeypatch.setattr(config, "whatsapp_token", "")
    assert proveedores.nombre_proveedor("whatsapp") == "stub"
    monkeypatch.setattr(config, "whatsapp_token", "token")
    monkeypatch.setattr(config, "whatsapp_numero_id", "123")
    assert proveedores.nombre_proveedor("whatsapp") == "meta_cloud"


def test_limite_de_tasa_por_proveedor_y_tenant():
    proveedores.limpiar_cubetas()
    assert all(proveedores.permitir("stub:tenant-1", 3) for _ in range(3))
    assert not proveedores.permitir("stub:tenant-1", 3)
    assert proveedores.permitir("stub:tenant-2", 3), "el tope es por tenant, no global"
    proveedores.limpiar_cubetas()


# ------------------------------------------------------------------ plantillas por API
async def test_las_plantillas_se_listan_con_su_estado_y_vista_previa(cliente, auth):
    lista = await plantillas(cliente, auth, AP, canal="whatsapp")
    assert len(lista) >= 15
    minuta = next(p for p in lista if p["clave"] == "minuta_disponible")
    assert minuta["es_global"] and minuta["estado_aprobacion"] == "aprobada"  # en modo stub nacen aprobadas
    assert minuta["evento"] == "minuta.enviada"

    r = await cliente.get(f"/api/mensajeria/plantillas/{minuta['id']}/vista-previa", headers=await auth(AP))
    assert r.status_code == 200, r.text
    previa = r.json()
    assert "Minuta del 08/11/2026" in previa["cuerpo"] and "{{" not in previa["cuerpo"]
    assert previa["botones"][0]["texto"] == "Ver minuta"

    sms = await plantilla(cliente, auth, "folio_asignado", "sms")
    r = await cliente.get(f"/api/mensajeria/plantillas/{sms['id']}/vista-previa", headers=await auth(AP))
    assert r.json()["segmentos"] == 1 and r.json()["codificacion"] == "GSM-7"


async def test_la_exportacion_para_meta_trae_el_formato_de_la_api(cliente, auth):
    p = await plantilla(cliente, auth, "aprobacion_pendiente", "whatsapp")
    r = await cliente.get(f"/api/mensajeria/plantillas/{p['id']}/exportar", headers=await auth(AP))
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["category"] == "UTILITY" and cuerpo["language"] == "es_MX"
    tipos = [c["type"] for c in cuerpo["components"]]
    assert "BODY" in tipos and "BUTTONS" in tipos
    botones = next(c for c in cuerpo["components"] if c["type"] == "BUTTONS")["buttons"]
    assert botones[0]["type"] == "URL" and "{{1}}" in botones[0]["url"]
    assert [b["type"] for b in botones[1:]] == ["QUICK_REPLY", "QUICK_REPLY"]
    # Un SMS no se somete a Meta.
    sms = await plantilla(cliente, auth, "folio_asignado", "sms")
    r = await cliente.get(f"/api/mensajeria/plantillas/{sms['id']}/exportar", headers=await auth(AP))
    assert r.status_code == 403


async def test_el_admin_prestador_edita_una_copia_y_no_la_base(cliente, auth, datos):
    base = await plantilla(cliente, auth, "folio_creado", "whatsapp")
    assert base["es_global"]
    r = await cliente.put(f"/api/mensajeria/plantillas/{base['id']}", headers=await auth(AP),
                          json={"cuerpo": "Se levantó el folio {{1}} en {{2}} ({{3}}). Lo atendemos enseguida."})
    assert r.status_code == 200, r.text
    copia = r.json()
    assert copia["id"] != base["id"] and copia["prestador_id"] == str(datos["prestador"])
    assert copia["estado_aprobacion"] == "borrador", "una plantilla editada vuelve a necesitar aprobación de Meta"
    assert copia["version"] == base["version"] + 1
    # La base de la plataforma quedó intacta.
    sigue = await plantilla(cliente, auth, "folio_creado", "whatsapp")
    assert any(p["id"] == base["id"] and p["cuerpo"] == base["cuerpo"]
               for p in await plantillas(cliente, auth, AP, canal="whatsapp"))
    assert sigue is not None
    # Y los roles que no administran no editan nada.
    r = await cliente.put(f"/api/mensajeria/plantillas/{base['id']}", headers=await auth(DES),
                          json={"cuerpo": "cualquier cosa"})
    assert r.status_code == 403


async def test_la_configuracion_y_la_bitacora_no_las_ve_el_cliente_operador(cliente, auth):
    for ruta in ("/api/mensajeria/configuracion", "/api/mensajeria/envios", "/api/mensajeria/plantillas"):
        r = await cliente.get(ruta, headers=await auth(OP))
        assert r.status_code == 403, f"{ruta} → {r.status_code}"


@pytest.mark.parametrize("tabla", ["mensajeria_plantillas", "mensajeria_configuracion", "mensajeria_envios",
                                   "mensajeria_respuestas"])
async def test_rls_forzada_en_las_tablas_nuevas(tabla):
    from sqlalchemy import text as sql

    from core.db import nueva_sesion
    from core.rls import CONTEXTO_SISTEMA

    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        fila = (await db.execute(sql("SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = :t"),
                                 {"t": tabla})).one()
        assert fila.relrowsecurity and fila.relforcerowsecurity
