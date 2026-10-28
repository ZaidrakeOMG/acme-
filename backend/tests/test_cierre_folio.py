"""Cierre desde campo (§6.8.6, §6.9.1): firma solo del operador/Admin UN de la UN, encuesta NPS con el formulario resuelto,
secuencia atención → firma → encuesta → cerrar, bloqueo sin formulario o sin firma, plazo de la encuesta y push."""
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from core.db import nueva_sesion
from core.rls import CONTEXTO_SISTEMA
from services import notificaciones
from tests.folios_utiles import AE, AUN, DES, OP, OTRO_OP, TEC, TEC2, accion, autorizar_sin_flujo, detalle, politicas, tecnico_con_habilidades
from tests.test_formularios_evidencias import png


async def _en_ejecucion(cliente, auth, datos, un_index=0):
    from tests.folios_utiles import capturar, nuevo_equipo, reglas, REGLAS_DEMO

    await reglas(cliente, auth, [])
    try:
        f = await capturar(cliente, auth, datos, AE, await nuevo_equipo(cliente, auth, datos, un_index=un_index))
    finally:
        await reglas(cliente, auth, REGLAS_DEMO)
    tec = await tecnico_con_habilidades(cliente, auth, TEC, ["refrigeracion", "electricidad"])
    await accion(cliente, auth, DES, f["id"], "asignar", {"tecnico_id": tec})
    await accion(cliente, auth, TEC, f["id"], "en-camino")
    await accion(cliente, auth, TEC, f["id"], "confirmar-llegada")
    return f


async def _respuesta_atencion(cliente, auth, datos, folio, tecnico=TEC):
    """Formulario de atención enviado SIN campo de firma: el operador firma desde su propia app (P05)."""
    from tests.test_formularios import crear_formulario, publicar

    esquema = {"secciones": [{"clave": "s", "titulo": "S", "campos": [
        {"clave": "diag", "tipo": "texto", "etiqueta": "Diagnóstico", "obligatorio": True, "config": {"longitud_min": 2, "longitud_max": 200}}]}]}
    form = await crear_formulario(cliente, auth, "admin.prestador@acma.dev", tipo="atencion_tecnico", rol_destino=["tecnico"], esquema=esquema)
    await publicar(cliente, auth, form["id"])
    r = await cliente.post(f"/api/formularios/{form['id']}/respuestas", headers=await auth(tecnico),
                           json={"origen": "folio_atencion", "referencia_id": folio["id"], "contexto": {"tenant_id": str(datos["tenant"]), "un_id": folio["un_id"], "equipo_id": folio["equipo_id"]},
                                 "respuestas": {"diag": "Se cambió el fusible"}})
    assert r.status_code == 201, r.text
    env = await cliente.post(f"/api/formularios/respuestas/{r.json()['id']}/enviar", headers=await auth(tecnico))
    assert env.status_code == 200, env.text
    return r.json()["id"]


async def firmar(cliente, auth, email, folio_id, esperado=201, **campos):
    r = await cliente.post(f"/api/folios/{folio_id}/firma", headers=await auth(email), data={"geolat": "19.4326", "geolng": "-99.1332", **campos},
                           files={"archivo": ("firma.png", png(), "image/png")})
    assert r.status_code == esperado, r.text
    return r.json()


async def test_firma_solo_operador_o_admin_un_de_la_unidad(cliente, auth, datos):
    f = await _en_ejecucion(cliente, auth, datos)
    assert (await firmar(cliente, auth, TEC, f["id"], 403))["codigo"] == "PROHIBIDO"
    assert (await firmar(cliente, auth, DES, f["id"], 403))["codigo"] == "PROHIBIDO"
    assert (await cliente.post(f"/api/folios/{f['id']}/firma", headers=await auth(OTRO_OP), files={"archivo": ("f.png", png(), "image/png")})).status_code == 404
    g = await _en_ejecucion(cliente, auth, datos, un_index=2)  # SUC-003: ni el operador ni el admin UN la tienen asignada
    assert (await cliente.post(f"/api/folios/{g['id']}/firma", headers=await auth(AUN), files={"archivo": ("f.png", png(), "image/png")})).status_code == 404
    e = await firmar(cliente, auth, OP, f["id"], timestamp_dispositivo="2026-10-27T18:30:00Z")
    assert e["tipo"] == "firma" and e["geolat"] == 19.4326 and e["timestamp_captura"].startswith("2026-10-27T18:30")
    assert (await firmar(cliente, auth, OP, f["id"], 409))["codigo"] == "FIRMA_DUPLICADA"
    d = await detalle(cliente, auth, f["id"])
    assert any(h["evento"] == "firma" for h in d["historial"]) and [x["tipo"] for x in d["evidencias"]] == ["firma"]
    assert any(n["titulo"].endswith("gracias por firmar") and str(f["capturado_por"]) in n["usuarios"] for n in notificaciones.ENVIADAS)


async def test_secuencia_atencion_firma_encuesta_cierre(cliente, auth, datos):
    f = await _en_ejecucion(cliente, auth, datos)
    # Sin atención ni firma no se cierra; la encuesta no está disponible antes de la firma.
    assert set((await accion(cliente, auth, TEC, f["id"], "cerrar", {}, 409))["detalles"]) == {"formulario_atencion", "firma"}
    assert (await cliente.get(f"/api/folios/{f['id']}/encuesta/disponible", headers=await auth(OP))).json()["disponible"] is False
    assert (await cliente.post(f"/api/folios/{f['id']}/encuesta", headers=await auth(OP), json={"nps_score": 9})).json()["codigo"] == "ENCUESTA_NO_DISPONIBLE"
    rid = await _respuesta_atencion(cliente, auth, datos, f)
    await cliente.post(f"/api/folios/{f['id']}/atencion", headers=await auth(TEC), json={"respuesta_id": rid})
    await firmar(cliente, auth, OP, f["id"])
    # Encuesta con calificación baja exige comentario; usa el formulario «Encuesta de satisfacción (operador)» del seed.
    assert (await cliente.post(f"/api/folios/{f['id']}/encuesta", headers=await auth(OP), json={"nps_score": 4})).json()["codigo"] == "COMENTARIO_REQUERIDO"
    r = await cliente.post(f"/api/folios/{f['id']}/encuesta", headers=await auth(OP), json={"nps_score": 4, "comentario": "Tardaron mucho en llegar"})
    assert r.status_code == 201 and r.json()["nps_score"] == 4 and r.json()["respuesta_id"]
    resp = (await cliente.get(f"/api/formularios/respuestas/{r.json()['respuesta_id']}", headers=await auth(OP))).json()
    assert resp["estado"] == "enviado" and resp["origen"] == "encuesta" and resp["respuestas_json"]["calificacion"] == 4
    assert (await cliente.post(f"/api/folios/{f['id']}/encuesta", headers=await auth(OP), json={"nps_score": 9})).json()["codigo"] == "ENCUESTA_DUPLICADA"
    c = await accion(cliente, auth, TEC, f["id"], "cerrar")
    assert c["estado"] == "cerrado"
    d = await detalle(cliente, auth, f["id"])
    assert d["encuesta"]["nps_score"] == 4 and d["sla"] is not None
    assert [h["evento"] for h in d["historial"]][-3:] == ["firma", "encuesta", "transicion"]


async def test_encuesta_despues_del_cierre_dentro_del_plazo(cliente, auth, datos):
    f = await _en_ejecucion(cliente, auth, datos)
    rid = await _respuesta_atencion(cliente, auth, datos, f)
    await cliente.post(f"/api/folios/{f['id']}/atencion", headers=await auth(TEC), json={"respuesta_id": rid})
    await firmar(cliente, auth, AUN, f["id"])
    await accion(cliente, auth, TEC, f["id"], "cerrar")
    d = await detalle(cliente, auth, f["id"])
    assert any(h["evento"] == "encuesta.pendiente" for h in d["historial"])
    assert (await cliente.get(f"/api/folios/{f['id']}/encuesta/disponible", headers=await auth(OP))).json()["disponible"] is True
    r = await cliente.post(f"/api/folios/{f['id']}/encuesta", headers=await auth(OP), json={"nps_score": 10, "timestamp_dispositivo": "2026-10-27T20:00:00Z"})
    assert r.status_code == 201 and r.json()["timestamp"].startswith("2026-10-27T20:00")
    # Fuera de plazo (48 h por defecto) → no disponible; el folio sigue inmutable.
    g = await _en_ejecucion(cliente, auth, datos)
    rid = await _respuesta_atencion(cliente, auth, datos, g)
    await cliente.post(f"/api/folios/{g['id']}/atencion", headers=await auth(TEC), json={"respuesta_id": rid})
    await firmar(cliente, auth, OP, g["id"])
    await accion(cliente, auth, TEC, g["id"], "cerrar")
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        # fecha_cierre no se puede tocar (inmutable): se acorta el plazo del tenant a 1 h y se simula con una política.
        await db.execute(text("UPDATE folio_politicas_tenant SET plazo_encuesta_horas = 1 WHERE tenant_id = :t"), {"t": datos["tenant"]})
        await db.commit()
    try:
        assert (await cliente.get(f"/api/folios/{g['id']}/encuesta/disponible", headers=await auth(OP))).json()["disponible"] is True
        async with nueva_sesion(CONTEXTO_SISTEMA) as db:
            await db.execute(text("UPDATE folio_politicas_tenant SET plazo_encuesta_horas = 0 WHERE tenant_id = :t"), {"t": datos["tenant"]})
            await db.commit()
        r = await cliente.get(f"/api/folios/{g['id']}/encuesta/disponible", headers=await auth(OP))
        assert r.json()["disponible"] is False and "venció" in r.json()["motivo"]
        assert (await cliente.post(f"/api/folios/{g['id']}/encuesta", headers=await auth(OP), json={"nps_score": 8})).status_code == 409
    finally:
        async with nueva_sesion(CONTEXTO_SISTEMA) as db:
            await db.execute(text("UPDATE folio_politicas_tenant SET plazo_encuesta_horas = 48 WHERE tenant_id = :t"), {"t": datos["tenant"]})
            await db.commit()


async def test_push_suscripcion_y_envio_por_transicion(cliente, auth, datos):
    h = await auth(OP)
    assert (await cliente.get("/api/push/clave-publica", headers=h)).json() == {"clave_publica": None, "habilitado": False}
    endpoint = "https://push.example.invalid/prueba-op"
    r = await cliente.post("/api/push/suscripcion", headers=h, json={"endpoint": endpoint, "keys": {"p256dh": "x", "auth": "y"}, "dispositivo_id": "prueba"})
    assert r.status_code == 201
    assert (await cliente.post("/api/push/suscripcion", headers=h, json={"endpoint": endpoint, "keys": {"p256dh": "x2", "auth": "y"}})).status_code == 201  # idempotente
    f = await autorizar_sin_flujo(cliente, auth, datos, OP)
    # Se busca por contenido: el deque ENVIADAS tiene maxlen y en la suite completa ya está lleno.
    nuevas = [n for n in notificaciones.ENVIADAS if "push" in n["canales"] and str(f["capturado_por"]) in n["usuarios"] and f["numero_folio"] in n["titulo"]]
    assert nuevas and any("autorizado" in n["titulo"] for n in nuevas)
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        fila = (await db.execute(text("SELECT activa, ultimo_envio_at FROM suscripciones_push WHERE endpoint = :e"), {"e": endpoint})).one()
    assert fila.activa and fila.ultimo_envio_at is not None  # sin VAPID: se registra el envío en log
    assert (await cliente.request("DELETE", "/api/push/suscripcion", headers=h, json={"endpoint": endpoint})).json()["mensaje"] == "Suscripción desactivada"
    assert (await cliente.get("/api/push/suscripcion", headers=h)).status_code == 405
