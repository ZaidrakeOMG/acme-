"""Selección de canal en `notificar()`: preferencia, configuración del tenant, consentimiento, teléfono verificado,
horario de silencio, tope mensual, caída al siguiente canal y reintentos (§6.1). F2-02."""
from datetime import UTC, datetime

from tests.folios_utiles import AP, OTRO_AP
from tests.mensajeria_utiles import (
    CON_AMBOS, CON_WHATSAPP, SIN_TELEFONO, SIN_TELEFONO_2, TELEFONO_PRUEBA_2, columna_cifrada, configuracion,
    configurar, envios, limpiar_stub, notificaciones_de, notificar_de_prueba, quitar_telefono, telefono_en_claro,
    ultimo_envio,
)

SIN_SILENCIO = {"inicio": "00:00", "fin": "00:00", "zona": "America/Mexico_City"}


async def _restaurar(cliente, auth, previa: dict) -> None:
    """Devuelve la configuración del prestador a como estaba (los datos del seed los comparte toda la suite)."""
    await configurar(cliente, auth, AP, whatsapp_activo=previa["whatsapp_activo"], sms_activo=previa["sms_activo"],
                     eventos_whatsapp=previa["eventos_whatsapp"], eventos_sms=previa["eventos_sms"],
                     horario_silencio=previa["horario_silencio"],
                     tope_mensual_mensajes=previa["tope_mensual_mensajes"])


# ------------------------------------------------------------------ camino feliz
async def test_el_aviso_sale_por_whatsapp_y_queda_en_la_bitacora(cliente, auth, datos):
    limpiar_stub()
    creadas = await notificar_de_prueba("folio.espera", CON_WHATSAPP, {"folio_id": None})
    assert [n["estado"] for n in creadas] == ["enviada"], creadas

    envio = await ultimo_envio(CON_WHATSAPP, "whatsapp")
    assert envio["estado"] == "enviado" and envio["plantilla"] == "folio_en_espera"
    assert envio["mensaje_id"].startswith("stub-")
    assert envio["codigo_enlace"] and envio["destino"] == "/folios"
    assert envio["costo"] == "0.4000" and envio["mascara"].startswith("+52 ")
    # §6.9.5: en la bitácora solo la máscara y el hash; el número en claro no aparece nunca.
    numero = await telefono_en_claro(CON_WHATSAPP)
    assert numero not in envio["cuerpo"] and numero not in envio["mascara"]
    assert len(envio["hash"]) == 64

    # La misma bitácora se ve en la pantalla de mensajería.
    lista = await envios(cliente, auth, AP, canal="whatsapp", limite=5)
    assert str(envio["id"]) in [e["id"] for e in lista]


async def test_el_telefono_se_guarda_cifrado():
    """El número vive cifrado con el mecanismo de P11a: la columna no se puede leer."""
    guardado = await columna_cifrada(CON_WHATSAPP)
    numero = await telefono_en_claro(CON_WHATSAPP)
    assert guardado and numero and numero not in guardado and len(guardado) > len(numero)


# ------------------------------------------------------------------ reglas que cierran el canal
async def test_sin_telefono_el_aviso_cae_al_siguiente_canal(cliente, auth):
    limpiar_stub()
    creadas = await notificar_de_prueba("folio.espera", SIN_TELEFONO, canales=["whatsapp"])
    estados = {n["canal"]: n for n in creadas}
    assert estados["whatsapp"]["estado"] == "omitida"
    assert "no tiene teléfono" in estados["whatsapp"]["respuesta"]
    # Y se creó el respaldo para que el aviso llegue de todos modos (§6.1).
    assert "push" in estados, f"faltó el canal de respaldo: {creadas}"
    assert estados["push"]["estado"] in ("enviada", "omitida")  # omitida si no hay suscripción push


async def test_telefono_sin_verificar_no_recibe(cliente, auth):
    h = await auth(SIN_TELEFONO_2)
    r = await cliente.put("/api/usuarios/me/telefono", headers=h, json={"telefono": TELEFONO_PRUEBA_2})
    assert r.status_code == 200 and r.json()["verificado"] is False
    try:
        creadas = await notificar_de_prueba("folio.espera", SIN_TELEFONO_2, canales=["whatsapp"])
        motivo = next(n["respuesta"] for n in creadas if n["canal"] == "whatsapp")
        assert motivo == "teléfono sin verificar"
        # Tampoco se puede dar consentimiento sin verificar el número.
        r = await cliente.put("/api/usuarios/me/consentimiento", headers=h,
                              json={"canal": "whatsapp", "acepta": True})
        assert r.status_code == 409 and r.json()["codigo"] == "TELEFONO_SIN_VERIFICAR"
    finally:
        await quitar_telefono(cliente, auth, SIN_TELEFONO_2)


async def test_sin_consentimiento_vigente_no_recibe(cliente, auth):
    """La baja del canal cierra la puerta aunque el teléfono siga verificado."""
    h = await auth(CON_AMBOS)
    r = await cliente.put("/api/usuarios/me/consentimiento", headers=h, json={"canal": "sms", "acepta": False})
    assert r.status_code == 200 and r.json()["sms"]["activo"] is False
    try:
        creadas = await notificar_de_prueba("folio.espera", CON_AMBOS, canales=["sms"])
        motivo = next(n["respuesta"] for n in creadas if n["canal"] == "sms")
        assert motivo == "sin consentimiento vigente para sms"
    finally:
        r = await cliente.put("/api/usuarios/me/consentimiento", headers=h, json={"canal": "sms", "acepta": True})
        assert r.json()["sms"]["activo"] is True


async def test_el_canal_apagado_en_la_configuracion_cierra_el_envio(cliente, auth):
    previa = await configuracion(cliente, auth, AP)
    await configurar(cliente, auth, AP, sms_activo=False)
    try:
        creadas = await notificar_de_prueba("folio.espera", CON_AMBOS, canales=["sms"])
        motivo = next(n["respuesta"] for n in creadas if n["canal"] == "sms")
        assert motivo == "canal sms no activo para el prestador"
    finally:
        await _restaurar(cliente, auth, previa)


async def test_la_lista_blanca_de_eventos_del_tenant(cliente, auth):
    previa = await configuracion(cliente, auth, AP)
    await configurar(cliente, auth, AP, eventos_whatsapp=["folio.estado"])
    try:
        creadas = await notificar_de_prueba("folio.espera", CON_AMBOS, canales=["whatsapp"])
        motivo = next(n["respuesta"] for n in creadas if n["canal"] == "whatsapp")
        assert "no está habilitado en whatsapp" in motivo
        # El evento de la lista sí pasa.
        creadas = await notificar_de_prueba("folio.estado", CON_AMBOS, {"estado": "asignado"}, canales=["whatsapp"])
        assert [n["estado"] for n in creadas] == ["enviada"]
    finally:
        await _restaurar(cliente, auth, previa)


async def test_el_horario_de_silencio_detiene_lo_no_critico_pero_no_lo_critico(cliente, auth):
    """§6.1: fuera del horario solo salen los eventos críticos (aprobación por vencer, SLA, severidad crítica)."""
    previa = await configuracion(cliente, auth, AP)
    await configurar(cliente, auth, AP, horario_silencio={"inicio": "00:00", "fin": "23:59",
                                                          "zona": "America/Mexico_City"})
    try:
        creadas = await notificar_de_prueba("folio.espera", CON_AMBOS, canales=["whatsapp"])
        assert next(n["respuesta"] for n in creadas if n["canal"] == "whatsapp") == "horario de silencio"

        criticas = await notificar_de_prueba("aprobacion.pendiente", CON_AMBOS, canales=["whatsapp"])
        assert [n["estado"] for n in criticas] == ["enviada"], "una aprobación pendiente sí despierta a alguien"
        envio = await ultimo_envio(CON_AMBOS, "whatsapp")
        assert envio["critico"] is True and envio["plantilla"] == "aprobacion_pendiente"

        alerta = await notificar_de_prueba("alerta", CON_AMBOS, {"alerta": "SLA_INCUMPLIDO"}, canales=["whatsapp"])
        assert [n["estado"] for n in alerta] == ["enviada"]
    finally:
        await _restaurar(cliente, auth, previa)


async def test_el_tope_mensual_bloquea_lo_no_critico(cliente, auth):
    previa = await configuracion(cliente, auth, AP)
    await configurar(cliente, auth, AP, tope_mensual_mensajes=1)
    try:
        creadas = await notificar_de_prueba("folio.espera", CON_AMBOS, canales=["whatsapp"])
        assert next(n["respuesta"] for n in creadas if n["canal"] == "whatsapp") == "tope mensual de mensajes alcanzado"
        criticas = await notificar_de_prueba("aprobacion.pendiente", CON_AMBOS, canales=["whatsapp"])
        assert [n["estado"] for n in criticas] == ["enviada"], "lo crítico pasa aunque el tope esté alcanzado"
        # El consumo del mes y su porcentaje se pueden consultar.
        r = await cliente.get("/api/mensajeria/consumo", headers=await auth(AP))
        assert r.status_code == 200 and r.json()["tope"] == 1
        assert r.json()["porcentaje"] >= 100 and r.json()["mes"].endswith("-01")
    finally:
        await _restaurar(cliente, auth, previa)


# ------------------------------------------------------------------ errores del proveedor
async def test_un_error_permanente_cae_al_siguiente_canal_y_no_se_reintenta(cliente, auth):
    from services.mensajeria.stub import FALLAS

    limpiar_stub()
    numero = await telefono_en_claro(CON_AMBOS)
    FALLAS[numero] = ("131026", True)
    try:
        creadas = await notificar_de_prueba("folio.espera", CON_AMBOS, canales=["whatsapp"])
        whatsapp = next(n for n in creadas if n["canal"] == "whatsapp")
        assert whatsapp["estado"] == "omitida" and "131026" in whatsapp["respuesta"]
        # El respaldo nace al fallar el envío, después de que `notificar()` devolvió su lista: se ve en la base.
        posteriores = await notificaciones_de(CON_AMBOS, "folio.espera")
        respaldo = next((n for n in posteriores if n["datos"].get("respaldo_de") == "whatsapp"), None)
        assert respaldo is not None, "debe caer al siguiente canal"
        assert respaldo["canal"] in ("push", "email")
        assert "131026" in respaldo["datos"]["motivo_respaldo"]
        envio = await ultimo_envio(CON_AMBOS, "whatsapp")
        assert envio["estado"] == "rechazado_por_proveedor" and envio["costo"] == "0.0000"
        assert envio["intentos"] == 1, "un error permanente no se reintenta"
    finally:
        limpiar_stub()


async def test_un_error_temporal_se_reintenta_con_espera_exponencial(cliente, auth):
    from services import mensajeria_service
    from services.mensajeria.stub import FALLAS

    limpiar_stub()
    numero = await telefono_en_claro(CON_AMBOS)
    FALLAS[numero] = ("RED", False)
    try:
        creadas = await notificar_de_prueba("folio.espera", CON_AMBOS, canales=["whatsapp"])
        assert next(n["estado"] for n in creadas if n["canal"] == "whatsapp") == "fallida"
        envio = await ultimo_envio(CON_AMBOS, "whatsapp")
        assert envio["estado"] == "fallido" and envio["intentos"] == 1
        # Al reintentar sin la falla programada, el mismo envío sale.
        FALLAS.clear()
        from core.db import nueva_sesion
        from core.rls import CONTEXTO_SISTEMA
        from models.mensajeria import MensajeriaEnvio
        from sqlalchemy import update

        async with nueva_sesion(CONTEXTO_SISTEMA) as db:
            await db.execute(update(MensajeriaEnvio).where(MensajeriaEnvio.id == envio["id"])
                             .values(proximo_intento_at=datetime.now(UTC)))
            resumen = await mensajeria_service.reintentar_pendientes(db)
            await db.commit()
        assert resumen["reintentados"] >= 1 and resumen["enviados"] >= 1
        de_nuevo = await ultimo_envio(CON_AMBOS, "whatsapp")
        assert de_nuevo["id"] == envio["id"] and de_nuevo["estado"] == "enviado" and de_nuevo["intentos"] == 2
    finally:
        limpiar_stub()


# ------------------------------------------------------------------ multitenancy
async def test_el_otro_prestador_no_ve_los_envios_del_demo(cliente, auth):
    await notificar_de_prueba("folio.espera", CON_WHATSAPP)
    propios = await envios(cliente, auth, AP, limite=200)
    ajenos = await envios(cliente, auth, OTRO_AP, limite=200)
    assert propios, "el prestador demo tiene envíos"
    assert not {e["id"] for e in propios} & {e["id"] for e in ajenos}


async def test_el_consumo_del_otro_prestador_empieza_en_cero(cliente, auth):
    r = await cliente.get("/api/mensajeria/consumo", headers=await auth(OTRO_AP))
    assert r.status_code == 200, r.text
    assert r.json()["mensajes"] == 0


async def test_sin_configuracion_el_canal_no_existe(cliente, auth):
    """El otro prestador no configuró mensajería: sus avisos nunca intentan salir por WhatsApp."""
    creadas = await notificar_de_prueba("folio.espera", "admin.otroprestador@acma.dev", canales=["whatsapp"])
    motivo = next(n["respuesta"] for n in creadas if n["canal"] == "whatsapp")
    assert motivo == "el prestador no tiene configurada la mensajería"
