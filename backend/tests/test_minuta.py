"""Minuta del día (§7.1–7.5): generación por UN y global con las secciones literales de §7.3 y los contadores de Bloque 1,
modo automático y con validación (ventana vencida → envío automático), PDF con hash, entrega por correo/push/bandeja,
las seis respuestas de §7.4 con su efecto, vencimiento del plazo, recordatorio por período presupuestal y alcance por rol."""
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select

from core.db import nueva_sesion
from core.rls import CONTEXTO_SISTEMA
from models.minutas import Minuta
from services import correo
from tests.folios_utiles import AE, AP, AUN, DES, MC, OP, OTRO_AE, SUPO, TEC, detalle
from tests.seguimiento_utiles import (
    alertas_disparadas, bandeja, configurar_minuta, folio_con_hallazgo, generar_minuta, hallazgo, limpiar_minutas_hoy, minuta_detalle, responder, retroceder,
)


async def _preparar(cliente, auth, datos, modo="automatica", **cfg):
    await limpiar_minutas_hoy(datos["tenant"])
    await configurar_minuta(cliente, auth, datos, modo=modo, **cfg)


async def test_configuracion_por_cliente(cliente, auth, datos):
    c = await configurar_minuta(cliente, auth, datos, modo="con_validacion", hora_envio="19:30:00", ventana_validacion_min=45, plazo_respuesta_horas=36)
    assert c["modo"] == "con_validacion" and c["hora_envio"] == "19:30:00" and c["ventana_validacion_min"] == 45 and c["plazo_respuesta_horas"] == 36
    r = await cliente.get("/api/minutas/configuracion", headers=await auth(DES), params={"tenant_id": str(datos["tenant"])})
    assert r.status_code == 200 and r.json()["ventana_validacion_min"] == 45
    assert (await cliente.put("/api/minutas/configuracion", headers=await auth(DES), params={"tenant_id": str(datos["tenant"])}, json={"modo": "automatica"})).status_code == 403
    assert (await cliente.put("/api/minutas/configuracion", headers=await auth(AP), params={"tenant_id": str(datos["otro_tenant"])}, json={"modo": "automatica"})).status_code == 404
    await configurar_minuta(cliente, auth, datos, modo="automatica", hora_envio="19:00:00", ventana_validacion_min=30, plazo_respuesta_horas=24)


async def test_generacion_un_y_global_con_secciones_y_entrega(cliente, auth, datos):
    await _preparar(cliente, auth, datos)
    f, h = await folio_con_hallazgo(cliente, auth, datos, "Cable de alimentación pelado detrás del refrigerador", "critica")
    antes_correos = len(correo.ENVIADOS)
    minutas = await generar_minuta(cliente, auth, datos)
    tipos = {m["tipo"]: m for m in minutas}
    assert "global" in tipos and any(m["tipo"] == "un" and m["un_id"] == f["un_id"] for m in minutas)
    m_un = next(m for m in minutas if m["tipo"] == "un" and m["un_id"] == f["un_id"])
    assert m_un["estado"] == "enviada" and m_un["modo"] == "automatica" and m_un["hash_pdf"] and len(m_un["hash_pdf"]) == 64 and m_un["urgente"] is True
    assert m_un["hallazgos"] >= 1 and m_un["hallazgos_pendientes"] >= 1 and set(m_un["colores"]) == {"cotizaciones", "por_presupuesto", "seguimiento_interno", "reprogramacion"}
    d = await minuta_detalle(cliente, auth, m_un["id"], AUN)
    s = d["secciones"]
    assert set(s) >= {"contadores", "preventivos", "hallazgos", "cotizaciones", "trabajos_especiales", "peticiones", "pendientes_autorizacion"}
    assert all(k in s["contadores"][m] for m in ("cotizaciones", "por_presupuesto", "seguimiento_interno", "reprogramacion") for k in ("total", "color", "umbral"))
    mio = next(x for x in s["hallazgos"] if x["hallazgo_id"] == h["id"])
    assert mio["urgencia"] == "critica" and mio["estado_respuesta"] == "pendiente" and mio["equipo"].startswith("EQT-")
    assert "P08" in s["trabajos_especiales"]["nota"] and isinstance(s["cotizaciones"]["pendientes_enviar"], list)
    assert d["puede_responder"] is True and len(d["opciones"]) == 6 and d["pdf_disponible"]
    # Entrega §7.5: Admin UN por app, push y correo (PDF adjunto); la global al Admin empresa.
    canales = {(x["nombre"], x["canal"]) for x in d["destinatarios"]}
    assert {("Úrsula Unidad", "app"), ("Úrsula Unidad", "email")} <= canales or any(x["canal"] == "email" for x in d["destinatarios"])
    correos = [c for c in correo.ENVIADOS[antes_correos:] if "Minuta del" in c["asunto"]]
    assert correos and any(a.startswith("minuta-") and a.endswith(".pdf") for c in correos for a in c["adjuntos"])
    assert any("[URGENTE]" in c["asunto"] for c in correos)
    assert any(n["evento"] == "minuta.enviada" and n["datos"]["minuta_id"] == m_un["id"] for n in await bandeja(cliente, auth, AUN))
    assert any(n["evento"] == "minuta.enviada" and n["datos"]["tipo"] == "global" for n in await bandeja(cliente, auth, AE))
    # PDF descargable con el mismo hash.
    r = await cliente.get(f"/api/minutas/{m_un['id']}/pdf", headers=await auth(AUN))
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/pdf") and r.content[:5] == b"%PDF-" and r.headers["x-hash-sha256"] == m_un["hash_pdf"]
    # Idempotente: volver a generar no duplica.
    assert await generar_minuta(cliente, auth, datos) == []
    # Alcance: el Admin UN solo ve las de sus UNs; otro tenant no ve nada; el operador no responde.
    assert all(x["tipo"] == "un" for x in (await cliente.get("/api/minutas", headers=await auth(AUN), params={"desde": date.today().isoformat()})).json())
    assert (await cliente.get(f"/api/minutas/{m_un['id']}", headers=await auth(OTRO_AE))).status_code == 404
    assert (await cliente.get("/api/minutas", headers=await auth(OTRO_AE))).json() == []
    assert (await cliente.get(f"/api/minutas/{m_un['id']}", headers=await auth(TEC))).status_code in (403, 404)


async def test_modo_con_validacion_y_ventana_vencida(cliente, auth, datos):
    await _preparar(cliente, auth, datos, modo="con_validacion", ventana_validacion_min=5)
    await folio_con_hallazgo(cliente, auth, datos, "Hallazgo con validación")
    minutas = await generar_minuta(cliente, auth, datos)
    assert minutas and all(m["estado"] == "pendiente_validacion" for m in minutas)
    assert any(n["evento"] == "minuta.pendiente_validacion" for n in await bandeja(cliente, auth, DES, solo_no_leidas=True))
    m = minutas[0]
    assert (await cliente.post(f"/api/minutas/{m['id']}/validar", headers=await auth(AUN), json={"notas": "x"})).status_code in (403, 404)
    r = await cliente.post(f"/api/minutas/{m['id']}/validar", headers=await auth(DES), json={"notas": "Revisada: el hallazgo crítico ya se programó"})
    assert r.status_code == 200 and r.json()["estado"] == "enviada" and r.json()["notas_despachador"].startswith("Revisada") and r.json()["validada_por_nombre"]
    assert (await cliente.post(f"/api/minutas/{m['id']}/validar", headers=await auth(DES), json={})).json()["codigo"] == "MINUTA_NO_PENDIENTE"
    # Otra pendiente cuya ventana ya venció: la tarea la envía «sin validación».
    otra = next(x for x in minutas if x["id"] != m["id"])
    await retroceder(Minuta, otra["id"], timestamp_generacion=datetime.now(UTC) - timedelta(minutes=10))
    r = await cliente.post("/api/minutas/procesar-pendientes", headers=await auth(AP))
    assert r.status_code == 200 and r.json()["validaciones_vencidas"] >= 1
    d = await minuta_detalle(cliente, auth, otra["id"])
    assert d["estado"] == "enviada" and d["enviada_sin_validacion"] is True and d["validada_por"] is None
    await configurar_minuta(cliente, auth, datos, modo="automatica", ventana_validacion_min=30)


async def test_seis_respuestas_con_efecto_literal(cliente, auth, datos):
    await _preparar(cliente, auth, datos)
    pares = [(op, (await folio_con_hallazgo(cliente, auth, datos, f"Hallazgo para {op}"))) for op in
             ("enterado", "cotizacion", "autorizar_reparar", "por_presupuesto", "seguimiento_interno", "reprogramacion")]
    minutas = await generar_minuta(cliente, auth, datos)
    m = next(x for x in minutas if x["tipo"] == "un" and x["un_id"] == pares[0][1][0]["un_id"])
    assert (await minuta_detalle(cliente, auth, m["id"]))["estado"] == "enviada"
    # El operador no responde; el Admin UN de otra UN no la ve.
    await responder(cliente, auth, m["id"], pares[0][1][1]["id"], "enterado", email=OP, esperado=403)
    await responder(cliente, auth, m["id"], pares[0][1][1]["id"], "enterado", email=OTRO_AE, esperado=404)
    r = await responder(cliente, auth, m["id"], pares[0][1][1]["id"], "enterado", notas="Sin observaciones")
    assert r["modulo_destino"] is None and r["folio_generado_id"] is None and r["canal"] == "app"
    await responder(cliente, auth, m["id"], pares[0][1][1]["id"], "enterado", esperado=409)  # ya respondido
    r = await responder(cliente, auth, m["id"], pares[1][1][1]["id"], "cotizacion", canal="email")
    assert r["modulo_destino"] == "cotizaciones" and r["modulo_registro_id"] and r["canal"] == "email"
    cot = (await cliente.get(f"/api/seguimiento/cotizaciones/{r['modulo_registro_id']}", headers=await auth(DES))).json()
    assert cot["estado"] == "solicitada" and cot["hallazgo_id"] == pares[1][1][1]["id"] and cot["numero"].startswith("COT-")
    for e in (MC, DES, AP):
        assert any(n["datos"].get("cotizacion_id") == cot["id"] for n in await bandeja(cliente, auth, e)), e
    r = await responder(cliente, auth, m["id"], pares[2][1][1]["id"], "autorizar_reparar", canal="push", email=AE)
    assert r["folio_generado_id"] and r["modulo_destino"] is None
    nuevo = await detalle(cliente, auth, r["folio_generado_id"])
    assert nuevo["folio"]["estado"] == "autorizado" and nuevo["folio"]["tipo_folio"] == "correctivo" and nuevo["aprobacion"] is None
    assert [x["estado_nuevo"] for x in nuevo["historial"] if x["evento"] == "transicion"] == ["capturado", "autorizado"]
    assert nuevo["historial"][0]["datos_contexto_json"]["hallazgo_id"] == pares[2][1][1]["id"]
    r = await responder(cliente, auth, m["id"], pares[3][1][1]["id"], "por_presupuesto")
    assert (await cliente.get(f"/api/seguimiento/presupuesto/{r['modulo_registro_id']}", headers=await auth(AUN))).json()["estado"] == "diferido"
    r = await responder(cliente, auth, m["id"], pares[4][1][1]["id"], "seguimiento_interno")
    assert (await cliente.get(f"/api/seguimiento/interno/{r['modulo_registro_id']}", headers=await auth(AUN))).json()["estado"] == "registrado"
    r = await responder(cliente, auth, m["id"], pares[5][1][1]["id"], "reprogramacion", fecha_tentativa=(date.today() + timedelta(days=10)).isoformat(),
                        proveedor="Refrigeración Industrial SA", notas="El fabricante lo atiende")
    rep = (await cliente.get(f"/api/seguimiento/reprogramacion/{r['modulo_registro_id']}", headers=await auth(AUN))).json()
    assert rep["estado"] == "fecha_asignada" and rep["fecha_acordada"] == (date.today() + timedelta(days=10)).isoformat() and rep["proveedor_tercero"] == "Refrigeración Industrial SA"
    d = await minuta_detalle(cliente, auth, m["id"], AUN)
    mios = {p[1][1]["id"] for p in pares}
    for x in d["secciones"]["hallazgos"]:  # pendientes de otras pruebas del mismo día
        if x["estado_respuesta"] == "pendiente" and x["hallazgo_id"] not in mios:
            await responder(cliente, auth, m["id"], x["hallazgo_id"], "enterado")
    d = await minuta_detalle(cliente, auth, m["id"], AUN)
    assert d["estado"] == "respondida" and d["respondida_at"] and len([r for r in d["respuestas"] if r["hallazgo_id"] in mios]) == 6 and d["hallazgos_pendientes"] == 0
    assert {x["opcion_respuesta"] for x in d["secciones"]["hallazgos"] if x["hallazgo_id"] in mios} == {p[0] for p in pares}
    assert all(x["estado_respuesta"] == "respondido" for x in d["hallazgos_detalle"])
    assert any(n["evento"] == "minuta.respondida" for n in await bandeja(cliente, auth, DES))
    # El detalle del folio original muestra el hallazgo y su respuesta.
    f_det = await detalle(cliente, auth, pares[1][1][0]["id"])
    assert f_det["hallazgos"][0]["opcion_respuesta"] == "cotizacion" and f_det["derivaciones"][0]["modulo"] == "cotizaciones"


async def test_minuta_vence_sin_respuesta_y_alerta(cliente, auth, datos):
    await _preparar(cliente, auth, datos, plazo_respuesta_horas=1)
    f, h = await folio_con_hallazgo(cliente, auth, datos, "Hallazgo que nadie responde")
    minutas = await generar_minuta(cliente, auth, datos)
    m = next(x for x in minutas if x["tipo"] == "un" and x["un_id"] == f["un_id"])
    assert m["vence_respuesta_at"]
    await retroceder(Minuta, m["id"], vence_respuesta_at=datetime.now(UTC) - timedelta(minutes=1))
    r = await cliente.post("/api/minutas/procesar-pendientes", headers=await auth(AP))
    assert r.json()["respuestas_vencidas"] >= 1
    d = await minuta_detalle(cliente, auth, m["id"])
    assert d["estado"] == "vencida"
    assert any(str(a.entidad_id) == m["id"] for a in await alertas_disparadas("MINUTA_SIN_RESPUESTA"))
    assert any(n["evento"] == "minuta.vencida" for n in await bandeja(cliente, auth, AE))
    # Aún se puede responder tarde (cuenta en la calificación); al responder todos los pendientes la minuta pasa a respondida.
    for x in d["secciones"]["hallazgos"]:
        if x["estado_respuesta"] == "pendiente":
            await responder(cliente, auth, m["id"], x["hallazgo_id"], "enterado")
    assert (await minuta_detalle(cliente, auth, m["id"]))["estado"] == "respondida"
    await configurar_minuta(cliente, auth, datos, plazo_respuesta_horas=24)


async def test_recordatorio_de_diferidos_al_inicio_de_periodo(cliente, auth, datos):
    await _preparar(cliente, auth, datos)
    r = await cliente.put("/api/seguimiento/periodos-presupuestales", headers=await auth(AE), json={"tipo": "fechas", "fechas": [date.today().isoformat()]})
    assert r.status_code == 200 and r.json()["periodo_actual"] == date.today().isoformat()
    f, h = await folio_con_hallazgo(cliente, auth, datos, "Hallazgo diferido para el recordatorio")
    minutas = await generar_minuta(cliente, auth, datos)
    m = next(x for x in minutas if x["tipo"] == "un" and x["un_id"] == f["un_id"])
    await responder(cliente, auth, m["id"], h["id"], "por_presupuesto")
    await limpiar_minutas_hoy(datos["tenant"])
    minutas = await generar_minuta(cliente, auth, datos)
    g = await minuta_detalle(cliente, auth, next(x for x in minutas if x["tipo"] == "global")["id"], AE)
    rec = g["secciones"].get("recordatorio_presupuesto")
    assert rec is not None and any("recordatorio" in x["descripcion"] for x in rec) and rec[0]["motivo"] == "inicio de período presupuestal"
    # La tarea diaria también avisa al inicio del período.
    from workers.tareas.minuta import presupuesto_recordatorios

    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        n = await presupuesto_recordatorios(db)
        await db.commit()
    assert n >= 1 and any(n["evento"] == "presupuesto.recordatorio" for n in await bandeja(cliente, auth, AE))
    await cliente.put("/api/seguimiento/periodos-presupuestales", headers=await auth(AE), json={"tipo": "trimestral", "fechas": []})


async def test_hallazgos_desde_formulario_y_chat(cliente, auth, datos):
    """Campo con genera_hallazgo en un formulario de atención y mensaje de chat marcado como hallazgo / petición."""
    import uuid

    from tests.folios_utiles import accion, autorizar_sin_flujo, tecnico_con_habilidades

    f = await autorizar_sin_flujo(cliente, auth, datos, OP)
    tec = await tecnico_con_habilidades(cliente, auth, TEC, ["refrigeracion", "electricidad"])
    await accion(cliente, auth, DES, f["id"], "asignar", {"tecnico_id": tec})
    await accion(cliente, auth, TEC, f["id"], "en-camino", {"geolat": 19.4, "geolng": -99.1})
    await accion(cliente, auth, TEC, f["id"], "confirmar-llegada", {"geolat": 19.4, "geolng": -99.1})
    h = await auth(AP)
    esquema = {"secciones": [{"clave": "s", "titulo": "S", "campos": [
        {"clave": "requiere", "tipo": "si_no", "etiqueta": "¿Requiere correctivo?", "obligatorio": True, "config": {"etiqueta_si": "Sí", "etiqueta_no": "No", "modo_defecto": "sin_defecto"}},
        {"clave": "urgencia", "tipo": "texto", "etiqueta": "Urgencia", "config": {"longitud_min": 1, "longitud_max": 20}},
        {"clave": "detalle", "tipo": "texto_amplio", "etiqueta": "Hallazgo", "obligatorio": True, "config": {"lineas_visibles": 3, "longitud_min": 5, "longitud_max": 500},
         "genera_hallazgo": {"condicion_campo": "requiere", "condicion_valor": True, "campo_urgencia": "urgencia"}},
    ]}]}
    r = await cliente.post("/api/formularios", headers=h, json={"nombre": f"Atención con hallazgo {uuid.uuid4().hex[:4]}", "tipo": "atencion_tecnico", "rol_destino": ["tecnico"], "esquema": esquema})
    assert r.status_code == 201, r.text
    assert (await cliente.post(f"/api/formularios/{r.json()['id']}/publicar", headers=h, json={"notas_version": ""})).status_code == 200
    ht = await auth(TEC)
    resp = await cliente.post(f"/api/formularios/{r.json()['id']}/respuestas", headers=ht, json={"origen": "folio_atencion", "referencia_id": f["id"],
                                                                                                 "contexto": {"tenant_id": f["tenant_id"], "un_id": f["un_id"], "equipo_id": f["equipo_id"]},
                                                                                                 "respuestas": {"requiere": True, "urgencia": "alta", "detalle": "Ventilador del condensador con aspa rota"}})
    assert resp.status_code == 201, resp.text
    rid = resp.json()["id"]
    env = await cliente.post(f"/api/formularios/respuestas/{rid}/enviar", headers=ht)
    assert env.status_code == 200, env.text
    lista = (await cliente.get("/api/hallazgos", headers=await auth(DES), params={"folio_id": f["id"]})).json()
    assert len(lista) == 1 and lista[0]["origen"] == "formulario_atencion" and lista[0]["nivel_urgencia"] == "alta" and lista[0]["descripcion"].startswith("Ventilador")
    # Chat: el técnico marca un mensaje como petición y el Admin UN otro como hallazgo.
    chats = {c["canal"]: c for c in (await cliente.get(f"/api/folios/{f['id']}/chats", headers=ht)).json()}
    m1 = (await cliente.post(f"/api/chats/{chats['campo']['id']}/mensajes", headers=ht, json={"id_cliente": str(uuid.uuid4()), "contenido_texto": "El gerente pide revisar también el congelador chico"})).json()
    r = await cliente.post(f"/api/chats/{chats['campo']['id']}/mensajes/{m1['id']}/marcar", headers=ht, json={"como": "peticion"})
    assert r.status_code == 200 and r.json()["tipo"] == "peticion" and r.json()["registro"]["origen"] == "chat"
    assert (await cliente.post(f"/api/chats/{chats['campo']['id']}/mensajes/{m1['id']}/marcar", headers=ht, json={"como": "hallazgo"})).json()["codigo"] == "MENSAJE_YA_MARCADO"
    m2 = (await cliente.post(f"/api/chats/{chats['campo']['id']}/mensajes", headers=ht, json={"id_cliente": str(uuid.uuid4()), "contenido_texto": "Puerta trasera con bisagra rota"})).json()
    hun = await auth(OP)
    r = await cliente.post(f"/api/chats/{chats['campo']['id']}/mensajes/{m2['id']}/marcar", headers=hun, json={"como": "hallazgo", "nivel_urgencia": "baja"})
    assert r.status_code == 200 and r.json()["registro"]["origen"] == "chat" and r.json()["registro"]["nivel_urgencia"] == "baja"
    assert (await cliente.post(f"/api/chats/{chats['campo']['id']}/mensajes/{m2['id']}/marcar", headers=await auth(SUPO), json={"como": "hallazgo"})).status_code in (403, 404)
    assert len((await cliente.get("/api/hallazgos", headers=await auth(DES), params={"folio_id": f["id"]})).json()) == 2
    assert len((await cliente.get("/api/peticiones", headers=await auth(DES), params={"folio_id": f["id"]})).json()) == 1
