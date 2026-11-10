"""Teléfono, verificación por código, consentimiento por canal, «BAJA» y «ALTA», y la regla de seguridad de que
ninguna acción crítica se ejecuta desde un mensaje (§6.9.5, §6.1). F2-02."""
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from core.db import nueva_sesion
from core.rls import CONTEXTO_SISTEMA
from models.usuarios import Usuario
from tests.folios_utiles import AP, DES, OP
from tests.mensajeria_utiles import (
    CON_AMBOS, SIN_TELEFONO, TELEFONO_PRUEBA, alta_y_verificacion, codigo_del_stub, limpiar_stub, mi_telefono,
    quitar_telefono, telefono_en_claro,
)


async def test_alta_verificacion_y_consentimiento_del_propio_usuario(cliente, auth):
    limpiar_stub()
    try:
        estado = await alta_y_verificacion(cliente, auth, SIN_TELEFONO, TELEFONO_PRUEBA, canal="sms",
                                           consentir=("whatsapp", "sms"))
        assert estado["verificado"] is True
        assert estado["whatsapp"]["activo"] and estado["sms"]["activo"]
        # §6.9.5: la API nunca devuelve el número completo.
        assert estado["telefono_mascara"] == "+52 155 ••• ••01"
        assert TELEFONO_PRUEBA not in str(estado)
        assert "BAJA" in estado["aviso_privacidad"] and "cifrado" in estado["aviso_privacidad"]

        # Cambiar el número vuelve a dejarlo sin verificar.
        r = await cliente.put("/api/usuarios/me/telefono", headers=await auth(SIN_TELEFONO),
                              json={"telefono": "+521555019003"})
        assert r.status_code == 200 and r.json()["verificado"] is False
    finally:
        await quitar_telefono(cliente, auth, SIN_TELEFONO)
        assert (await mi_telefono(cliente, auth, SIN_TELEFONO))["tiene_telefono"] is False


async def test_un_numero_mal_escrito_se_explica(cliente, auth):
    r = await cliente.put("/api/usuarios/me/telefono", headers=await auth(SIN_TELEFONO),
                          json={"telefono": "871123456"})
    assert r.status_code == 422 and r.json()["codigo"] == "TELEFONO_INVALIDO"
    # Un celular mexicano de 10 dígitos se completa con la lada del país.
    r = await cliente.put("/api/usuarios/me/telefono", headers=await auth(SIN_TELEFONO),
                          json={"telefono": "871 123 4567"})
    assert r.status_code == 200 and r.json()["telefono_mascara"].startswith("+52")
    await quitar_telefono(cliente, auth, SIN_TELEFONO)


async def test_el_codigo_equivocado_no_verifica_y_se_agota(cliente, auth):
    limpiar_stub()
    h = await auth(SIN_TELEFONO)
    try:
        assert (await cliente.put("/api/usuarios/me/telefono", headers=h,
                                  json={"telefono": TELEFONO_PRUEBA})).status_code == 200
        assert (await cliente.post("/api/usuarios/me/telefono/codigo?canal=sms", headers=h)).status_code == 200
        bueno = codigo_del_stub()
        malo = "000000" if bueno != "000000" else "111111"
        for _ in range(5):
            r = await cliente.post("/api/usuarios/me/telefono/verificar", headers=h, json={"codigo": malo})
            assert r.status_code == 422 and r.json()["codigo"] == "CODIGO_INCORRECTO"
        # Al sexto intento el código ya no sirve ni siendo el correcto.
        r = await cliente.post("/api/usuarios/me/telefono/verificar", headers=h, json={"codigo": bueno})
        assert r.status_code == 429 and r.json()["codigo"] == "DEMASIADOS_INTENTOS"
    finally:
        await quitar_telefono(cliente, auth, SIN_TELEFONO)


async def test_un_codigo_vencido_no_sirve(cliente, auth):
    limpiar_stub()
    h = await auth(SIN_TELEFONO)
    try:
        assert (await cliente.put("/api/usuarios/me/telefono", headers=h,
                                  json={"telefono": TELEFONO_PRUEBA})).status_code == 200
        assert (await cliente.post("/api/usuarios/me/telefono/codigo?canal=whatsapp", headers=h)).status_code == 200
        codigo = codigo_del_stub()
        async with nueva_sesion(CONTEXTO_SISTEMA) as db:
            await db.execute(update(Usuario).where(Usuario.email == SIN_TELEFONO)
                             .values(telefono_codigo_expira_at=datetime.now(UTC) - timedelta(minutes=1)))
            await db.commit()
        r = await cliente.post("/api/usuarios/me/telefono/verificar", headers=h, json={"codigo": codigo})
        assert r.status_code == 409 and r.json()["codigo"] == "CODIGO_VENCIDO"
        # Sin código pedido tampoco se puede verificar.
        assert (await cliente.post("/api/usuarios/me/telefono/codigo?canal=sms", headers=h)).status_code == 200
    finally:
        await quitar_telefono(cliente, auth, SIN_TELEFONO)


async def test_baja_y_alta_por_mensaje_del_usuario(cliente, auth):
    """La palabra «BAJA» da de baja el canal de inmediato; «ALTA» lo reactiva (§6.9.5)."""
    limpiar_stub()
    try:
        await alta_y_verificacion(cliente, auth, SIN_TELEFONO, TELEFONO_PRUEBA, canal="sms", consentir=("sms",))
        r = await cliente.post("/api/mensajeria/webhook/simular", headers=await auth(AP),
                               json={"canal": "sms", "telefono": TELEFONO_PRUEBA, "texto": "BAJA"})
        assert r.status_code == 200, r.text
        assert r.json()["accion"] == "baja_sms" and r.json()["usuario_resuelto"] is True
        estado = await mi_telefono(cliente, auth, SIN_TELEFONO)
        assert estado["sms"]["activo"] is False and estado["sms"]["baja_at"]
        # El acuse sale por el mismo canal (la ventana de 24 h está abierta: el usuario acaba de escribir).
        from services.mensajeria.stub import ENVIADOS

        assert "ya no recibiras avisos" in ENVIADOS[-1]["cuerpo"]

        # Minúsculas y acentos no importan: se normaliza.
        r = await cliente.post("/api/mensajeria/webhook/simular", headers=await auth(AP),
                               json={"canal": "sms", "telefono": TELEFONO_PRUEBA, "texto": "alta"})
        assert r.json()["accion"] == "alta_sms"
        estado = await mi_telefono(cliente, auth, SIN_TELEFONO)
        assert estado["sms"]["activo"] is True
        assert "volveras a recibir" in ENVIADOS[-1]["cuerpo"]
    finally:
        await quitar_telefono(cliente, auth, SIN_TELEFONO)


async def test_el_boton_de_aprobar_no_ejecuta_la_accion(cliente, auth):
    """Decisión de seguridad: un mensaje nunca autoriza; contesta con el enlace a la pantalla de aprobación."""
    from models.mensajeria import MensajeriaRespuesta

    limpiar_stub()
    from tests.mensajeria_utiles import notificar_de_prueba

    await notificar_de_prueba("aprobacion.pendiente", CON_AMBOS, canales=["whatsapp"])
    numero = await telefono_en_claro(CON_AMBOS)
    r = await cliente.post("/api/mensajeria/webhook/simular", headers=await auth(AP),
                           json={"canal": "whatsapp", "telefono": numero, "boton": "Aprobar"})
    assert r.status_code == 200, r.text
    assert r.json()["accion"] == "enlace_enviado"

    from services.mensajeria.stub import ENVIADOS

    ultimo = ENVIADOS[-1]
    assert "la decision no se toma por mensaje" in ultimo["cuerpo"]
    assert "/l/" in ultimo["cuerpo"], "el acuse lleva el enlace a la pantalla de aprobación"

    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        fila = (await db.execute(select(MensajeriaRespuesta).order_by(
            MensajeriaRespuesta.timestamp.desc()).limit(1))).scalar_one()
        assert fila.boton == "Aprobar" and fila.accion_ejecutada == "enlace_enviado"
        # En la bitácora de respuestas tampoco está el número completo.
        assert fila.telefono_mascara.count("•") >= 5 and len(fila.telefono_hash) == 64


async def test_un_numero_desconocido_se_registra_sin_usuario(cliente, auth):
    r = await cliente.post("/api/mensajeria/webhook/simular", headers=await auth(AP),
                           json={"canal": "whatsapp", "telefono": "+521555099999", "texto": "BAJA"})
    assert r.status_code == 200, r.text
    assert r.json()["usuario_resuelto"] is False and r.json()["accion"] == "registrada"


async def test_la_simulacion_de_webhook_es_solo_para_administradores(cliente, auth):
    for email in (DES, OP):
        r = await cliente.post("/api/mensajeria/webhook/simular", headers=await auth(email),
                               json={"canal": "sms", "telefono": TELEFONO_PRUEBA, "texto": "BAJA"})
        assert r.status_code == 403, email


async def test_el_aviso_de_privacidad_esta_disponible_para_cualquier_usuario(cliente, auth):
    r = await cliente.get("/api/mensajeria/aviso-privacidad", headers=await auth(OP))
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["palabra_baja"] == "BAJA" and cuerpo["palabra_alta"] == "ALTA"
    assert "notificaciones operativas" in cuerpo["texto"] or "avisos operativos" in cuerpo["texto"]
