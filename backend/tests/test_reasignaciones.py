"""Reasignación forzada (§6.8.2): candidatos con validaciones, restricción dura de habilidad (y excepción con permiso + razón),
advertencia de refacción con confirmación explícita, razón del catálogo obligatoria, no reasignar en ejecución, historial,
chat y reporte de causas; catálogo de razones por prestador."""
from tests.folios_utiles import AE, AP, AUN, DES, MC, OP, OTRO_AP, TEC, TEC2, TEC4, accion, autorizar_sin_flujo, detalle, tecnico_con_habilidades
from tests.preventivos_utiles import razones

RAZONES_6_8_2 = ["Incidencia del técnico", "Prioridad de cliente", "Optimización de ruta", "Falta de habilidad no detectada", "Falta de refacción",
                 "Solicitud del técnico", "Corrección de asignación inicial"]


async def _folio_asignado(cliente, auth, datos, tecnico_email=TEC, claves=("refrigeracion", "electricidad")):
    f = await autorizar_sin_flujo(cliente, auth, datos, OP)
    tec = await tecnico_con_habilidades(cliente, auth, tecnico_email, list(claves))
    a = await accion(cliente, auth, DES, f["id"], "asignar", {"tecnico_id": tec})
    assert a["estado"] == "asignado"
    return f, tec


async def test_catalogo_de_razones_literal_y_administrable(cliente, auth, datos):
    lista = await razones(cliente, auth)
    assert [r["descripcion"] for r in lista] == RAZONES_6_8_2 and all(r["detalle"] for r in lista)
    assert (await cliente.get("/api/reasignaciones/razones", headers=await auth(OP))).status_code == 403
    r = await cliente.post("/api/reasignaciones/razones", headers=await auth(AP), json={"descripcion": "Cliente cerrado", "detalle": "La sucursal no abrió", "orden_display": 8})
    assert r.status_code == 201 and r.json()["activa"] is True
    nueva = r.json()
    assert (await cliente.post("/api/reasignaciones/razones", headers=await auth(DES), json={"descripcion": "No puedo", "detalle": ""})).status_code == 403
    r = await cliente.patch(f"/api/reasignaciones/razones/{nueva['id']}", headers=await auth(AP), json={"descripcion": "Cliente cerrado", "detalle": "x", "activa": False, "orden_display": 8})
    assert r.status_code == 200 and r.json()["activa"] is False
    assert all(x["id"] != nueva["id"] for x in await razones(cliente, auth))
    assert any(x["id"] == nueva["id"] for x in (await cliente.get("/api/reasignaciones/razones", headers=await auth(AP), params={"incluir_inactivas": True})).json())
    assert (await cliente.patch(f"/api/reasignaciones/razones/{nueva['id']}", headers=await auth(OTRO_AP), json={"descripcion": "Ajena", "detalle": ""})).status_code == 404
    # Un prestador nuevo recibe el catálogo al crearse.
    r = await cliente.post("/api/prestadores", headers=await auth("superadmin@acma.dev"), json={"razon_social": "Prestador Razones", "rfc": "PRZ260101AA1"})
    assert r.status_code == 201, r.text
    r = await cliente.get("/api/reasignaciones/razones", headers=await auth("superadmin@acma.dev"), params={"prestador_id": r.json()["id"]})
    assert [x["descripcion"] for x in r.json()] == RAZONES_6_8_2


async def test_candidatos_y_reasignacion_con_restricciones(cliente, auth, datos):
    f, tec1 = await _folio_asignado(cliente, auth, datos)
    tec2 = await tecnico_con_habilidades(cliente, auth, TEC2, ["hvac", "electricidad"])  # sin refrigeración
    tec4 = await tecnico_con_habilidades(cliente, auth, TEC4, ["iluminacion", "electricidad", "hvac", "refrigeracion"])
    cands = {c["usuario_id"]: c for c in (await cliente.get(f"/api/folios/{f['id']}/reasignacion/candidatos", headers=await auth(DES))).json()}
    assert cands[tec1]["es_actual"] and cands[tec1]["habilidad_ok"] and cands[tec1]["carga_dia"] >= 1
    assert cands[tec2]["habilidad_ok"] is False and cands[tec2]["habilidad_requerida"] == "refrigeracion" and any("habilidad" in a.lower() for a in cands[tec2]["advertencias"])
    assert cands[tec4]["habilidad_ok"] and cands[tec4]["refaccion_ok"] is None and any("refacci" in a.lower() for a in cands[tec4]["advertencias"])
    assert (await cliente.get(f"/api/folios/{f['id']}/reasignacion/candidatos", headers=await auth(OP))).status_code in (403, 404)
    razon = (await razones(cliente, auth))[2]  # Optimización de ruta
    # Validaciones: razón obligatoria/inválida, mismo técnico, habilidad (restricción dura), advertencias sin confirmar.
    r = await cliente.post(f"/api/folios/{f['id']}/reasignar", headers=await auth(DES), json={"tecnico_destino_id": tec4})
    assert r.status_code == 422
    r = await accion(cliente, auth, DES, f["id"], "reasignar", {"tecnico_destino_id": tec4, "razon_id": f["id"]}, 422)
    assert r["codigo"] == "RAZON_INVALIDA"
    r = await accion(cliente, auth, DES, f["id"], "reasignar", {"tecnico_destino_id": tec1, "razon_id": razon["id"]}, 422)
    assert r["codigo"] == "MISMO_TECNICO"
    r = await accion(cliente, auth, DES, f["id"], "reasignar", {"tecnico_destino_id": tec2, "razon_id": razon["id"], "confirmar_advertencias": True}, 403)
    assert r["codigo"] == "TECNICO_SIN_HABILIDAD" and r["detalles"][0]["habilidad_requerida"] == "refrigeracion"
    r = await accion(cliente, auth, DES, f["id"], "reasignar", {"tecnico_destino_id": tec4, "razon_id": razon["id"]}, 409)
    assert r["codigo"] == "CONFIRMACION_REQUERIDA" and any("refacci" in a.lower() for a in r["detalles"])
    assert (await detalle(cliente, auth, f["id"]))["folio"]["tecnico_id"] == tec1  # nada cambió
    # Reasignación válida: reasignado → asignado, validaciones guardadas, chat de campo actualizado, historial del folio.
    r = await accion(cliente, auth, DES, f["id"], "reasignar", {"tecnico_destino_id": tec4, "razon_id": razon["id"], "comentario": "Tania pasa por ahí", "confirmar_advertencias": True}, 201)
    assert r["tecnico_origen_id"] == tec1 and r["tecnico_destino_id"] == tec4 and r["razon"] == "Optimización de ruta" and r["tipo"] == "forzada" and r["despachador_nombre"]
    d = await detalle(cliente, auth, f["id"])
    assert d["folio"]["estado"] == "asignado" and d["folio"]["tecnico_id"] == tec4 and d["folio"]["tecnico_nombre"]
    assert [h["estado_nuevo"] for h in d["historial"] if h["evento"] == "transicion"][-2:] == ["reasignado", "asignado"]
    assert len(d["reasignaciones"]) == 1 and d["reasignaciones"][0]["comentario"] == "Tania pasa por ahí"
    hist = (await cliente.get(f"/api/folios/{f['id']}/reasignaciones", headers=await auth(AE))).json()
    assert len(hist) == 1 and hist[0]["id"] == r["id"]
    chats = {c["canal"]: c for c in (await cliente.get(f"/api/folios/{f['id']}/chats", headers=await auth(TEC4))).json()}
    campo = (await cliente.get(f"/api/chats/{chats['campo']['id']}/mensajes", headers=await auth(TEC4))).json()
    assert any(m["datos_json"].get("tipo_evento") == "folio.reasignado" for m in campo), campo
    operativo = (await cliente.get(f"/api/chats/{chats['operativo']['id']}/mensajes", headers=await auth(DES))).json()
    assert any(m["datos_json"].get("tipo_evento") == "folio.reasignado" for m in operativo)
    # El técnico anterior ya no participa en el chat de campo; el nuevo sí.
    activos = {p["usuario_id"] for p in chats["campo"]["participantes"]}
    assert tec4 in activos and tec1 not in activos
    assert (await cliente.get(f"/api/folios/{f['id']}", headers=await auth(TEC4))).status_code == 200
    assert (await cliente.get(f"/api/folios/{f['id']}", headers=await auth(TEC))).status_code == 404


async def test_sin_habilidad_con_permiso_y_razon(cliente, auth, datos):
    f, tec1 = await _folio_asignado(cliente, auth, datos)
    tec2 = await tecnico_con_habilidades(cliente, auth, TEC2, ["hvac"])
    razon = (await razones(cliente, auth))[3]  # Falta de habilidad no detectada
    h = await auth(AP)
    desp = (await cliente.get("/api/usuarios", headers=h, params={"rol": "despachador"})).json()[0]
    # Admin prestador puede, pero exige razón; el Despachador necesita el permiso.
    r = await accion(cliente, auth, AP, f["id"], "reasignar", {"tecnico_destino_id": tec2, "razon_id": razon["id"], "confirmar_advertencias": True}, 422)
    assert r["codigo"] == "RAZON_REQUERIDA"
    r = await accion(cliente, auth, DES, f["id"], "reasignar", {"tecnico_destino_id": tec2, "razon_id": razon["id"], "confirmar_advertencias": True,
                                                                "razon_sin_habilidad": "Único disponible"}, 403)
    assert r["codigo"] == "TECNICO_SIN_HABILIDAD"
    await cliente.put("/api/configuracion/permisos-despachador", headers=h,
                      json={"valores": {"asignar_tecnico_sin_habilidad": True}, "despachador_id": desp["id"], "tenant_id": str(datos["tenant"])})
    try:
        r = await accion(cliente, auth, DES, f["id"], "reasignar", {"tecnico_destino_id": tec2, "razon_id": razon["id"], "confirmar_advertencias": True,
                                                                    "razon_sin_habilidad": "Único disponible"}, 201)
        assert r["tecnico_destino_id"] == tec2
    finally:
        await cliente.put("/api/configuracion/permisos-despachador", headers=h,
                          json={"valores": {"asignar_tecnico_sin_habilidad": False}, "despachador_id": desp["id"], "tenant_id": str(datos["tenant"])})
    d = await detalle(cliente, auth, f["id"])
    ultimo = [x for x in d["historial"] if x["estado_nuevo"] == "asignado"][-1]
    assert ultimo["datos_contexto_json"]["sin_habilidad"] is True and ultimo["datos_contexto_json"]["razon"] == "Único disponible"


async def test_no_reasignar_en_ejecucion_ni_otros_estados(cliente, auth, datos):
    f, tec1 = await _folio_asignado(cliente, auth, datos)
    tec4 = await tecnico_con_habilidades(cliente, auth, TEC4, ["refrigeracion", "iluminacion"])
    razon = (await razones(cliente, auth))[0]
    await accion(cliente, auth, TEC, f["id"], "en-camino", {"geolat": 19.4, "geolng": -99.1})
    # En camino sí se permite (decisión pendiente: el técnico aún no está en la unidad).
    cands = (await cliente.get(f"/api/folios/{f['id']}/reasignacion/candidatos", headers=await auth(DES))).json()
    assert any(c["usuario_id"] == tec4 for c in cands)
    await accion(cliente, auth, TEC, f["id"], "confirmar-llegada", {"geolat": 19.4, "geolng": -99.1})
    r = await accion(cliente, auth, DES, f["id"], "reasignar", {"tecnico_destino_id": tec4, "razon_id": razon["id"], "confirmar_advertencias": True}, 409)
    assert r["codigo"] == "REASIGNACION_NO_PERMITIDA" and "ejecución" in r["mensaje"]
    # Pendiente de refacción vuelve a permitirlo; cancelado no.
    await accion(cliente, auth, TEC, f["id"], "pendiente-refaccion", {"notas": "Falta compresor"})
    r = await accion(cliente, auth, DES, f["id"], "reasignar", {"tecnico_destino_id": tec4, "razon_id": razon["id"], "confirmar_advertencias": True}, 201)
    assert r["tecnico_destino_id"] == tec4
    assert (await detalle(cliente, auth, f["id"]))["folio"]["estado"] == "asignado"
    await accion(cliente, auth, DES, f["id"], "cancelar", {"razon": "Se cancela para la prueba"})
    r = await accion(cliente, auth, DES, f["id"], "reasignar", {"tecnico_destino_id": tec1, "razon_id": razon["id"], "confirmar_advertencias": True}, 409)
    assert r["codigo"] == "REASIGNACION_NO_PERMITIDA"
    # Solo Despachador / Admin prestador reasignan.
    g, _ = await _folio_asignado(cliente, auth, datos)
    for email in (MC, AE, AUN, OP, TEC):
        r = await cliente.post(f"/api/folios/{g['id']}/reasignar", headers=await auth(email), json={"tecnico_destino_id": tec4, "razon_id": razon["id"], "confirmar_advertencias": True})
        assert r.status_code in (403, 404), (email, r.text)


async def test_reporte_de_causas(cliente, auth, datos):
    f, tec1 = await _folio_asignado(cliente, auth, datos)
    tec4 = await tecnico_con_habilidades(cliente, auth, TEC4, ["refrigeracion", "iluminacion"])
    lista = await razones(cliente, auth)
    await accion(cliente, auth, DES, f["id"], "reasignar", {"tecnico_destino_id": tec4, "razon_id": lista[1]["id"], "confirmar_advertencias": True}, 201)
    await accion(cliente, auth, DES, f["id"], "reasignar", {"tecnico_destino_id": tec1, "razon_id": lista[1]["id"], "confirmar_advertencias": True}, 201)
    assert len((await detalle(cliente, auth, f["id"]))["reasignaciones"]) == 2
    rep = (await cliente.get("/api/reasignaciones/reporte", headers=await auth(DES))).json()
    assert rep["total"] >= 2 and rep["por_razon"][0]["total"] >= 1 and abs(sum(x["porcentaje"] for x in rep["por_razon"]) - 100) < 1
    prioridad = next(x for x in rep["por_razon"] if x["nombre"] == "Prioridad de cliente")
    assert prioridad["total"] >= 2 and any(x["nombre"] == "forzada" for x in rep["por_tipo"])
    assert {x["nombre"] for x in rep["por_tecnico_destino"]} >= {"Tomás Técnico", "Tania Técnica"}
    # Por período: una ventana futura queda vacía; el Admin empresa ve el reporte de su tenant; el operador no.
    vacio = (await cliente.get("/api/reasignaciones/reporte", headers=await auth(DES), params={"desde": "2030-01-01", "hasta": "2030-01-31"})).json()
    assert vacio["total"] == 0 and vacio["por_razon"] == []
    assert (await cliente.get("/api/reasignaciones/reporte", headers=await auth(AE))).json()["total"] >= 2
    assert (await cliente.get("/api/reasignaciones/reporte", headers=await auth(OTRO_AP))).json()["total"] == 0
    assert (await cliente.get("/api/reasignaciones/reporte", headers=await auth(OP))).status_code == 403
