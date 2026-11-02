"""Presupuestos y control de gasto (§4.1, §6.8.5): alta por UN y por grupo, consumo al validarse el costo del folio en todos
los presupuestos aplicables, umbrales configurables y excedido, vista consolidada Tenant → Grupo → UN y aislamiento."""
from datetime import date, timedelta
from decimal import Decimal

from tests.folios_utiles import AE, AP, AUN, DES, MC, OP, OTRO_AE, SUPO, TEC
from tests.inventario_utiles import alertas_disparadas, bandeja, cerrar_folio, costos_de, folio_en_ejecucion, presupuesto, refaccion, tarifa, validar_costo


async def _grupo_demo(cliente, auth, datos) -> dict | None:
    grupos = (await cliente.get("/api/grupos-un", headers=await auth(AE))).json()
    return grupos[0] if grupos else None


async def _folio_con_costo(cliente, auth, datos, costo="1000.00") -> tuple[dict, Decimal]:
    await tarifa(cliente, auth, "0.00")  # sin mano de obra para que el total sea el de la refacción
    f = await folio_en_ejecucion(cliente, auth, datos)
    await refaccion(cliente, auth, f["id"], descripcion="Refacción del presupuesto", cantidad="1", costo=costo)
    await cerrar_folio(cliente, auth, datos, f)
    return f, Decimal((await costos_de(cliente, auth, f["id"]))["costo"]["costo_total"])


async def test_alta_por_un_y_por_grupo_con_validaciones(cliente, auth, datos):
    hoy = date.today()
    assert (await presupuesto(cliente, auth, datos, un_id=datos["unidades"][0], email=AUN, esperado=403))["codigo"] == "PROHIBIDO"
    # Exactamente uno de UN o grupo.
    assert (await presupuesto(cliente, auth, datos, esperado=422))["codigo"] == "ALCANCE_INVALIDO"
    grupo = await _grupo_demo(cliente, auth, datos)
    assert (await presupuesto(cliente, auth, datos, un_id=datos["unidades"][0], grupo_id=grupo["id"], esperado=422))["codigo"] == "ALCANCE_INVALIDO"
    # Período inválido.
    assert (await presupuesto(cliente, auth, datos, un_id=datos["unidades"][0], esperado=422,
                              periodo_inicio=hoy.isoformat(), periodo_fin=(hoy - timedelta(days=1)).isoformat()))["codigo"] == "PERIODO_INVALIDO"
    # UN de otro cliente.
    assert (await presupuesto(cliente, auth, datos, un_id=datos["un_otro"], esperado=422))["codigo"] == "UNIDAD_INVALIDA"
    p = await presupuesto(cliente, auth, datos, un_id=datos["unidades"][0], monto="20000.00", nombre="Presupuesto de prueba UN")
    assert p["un_codigo"] and Decimal(p["monto"]) == 20000 and Decimal(p["consumido"]) == 0 and p["semaforo"] == "verde"
    assert p["umbrales_alerta_json"] == [50, 80, 100] and p["tipo_actividad"] == "todos"
    g = await presupuesto(cliente, auth, datos, grupo_id=grupo["id"], monto="50000.00", tipo="correctivo", nombre="Presupuesto del grupo")
    assert g["grupo_nombre"] == grupo["nombre"] and g["un_id"] is None
    # Edición y detalle.
    r = await cliente.put(f"/api/presupuestos/{p['id']}", headers=await auth(AE), json={"monto": "25000.00", "umbrales_alerta_json": [60, 90]})
    assert r.status_code == 200 and Decimal(r.json()["monto"]) == 25000 and r.json()["umbrales_alerta_json"] == [60, 90]
    assert (await cliente.put(f"/api/presupuestos/{p['id']}", headers=await auth(AUN), json={"monto": "1.00"})).status_code == 403
    # Aislamiento entre clientes.
    assert all(x["id"] != p["id"] for x in (await cliente.get("/api/presupuestos", headers=await auth(OTRO_AE))).json())
    assert (await cliente.get(f"/api/presupuestos/{p['id']}", headers=await auth(OTRO_AE))).status_code == 404
    # El Admin UN lee los de sus UNs; el prestador los de los clientes que atiende.
    assert any(x["id"] == p["id"] for x in (await cliente.get("/api/presupuestos", headers=await auth(AUN))).json())
    assert any(x["id"] == p["id"] for x in (await cliente.get("/api/presupuestos", headers=await auth(MC))).json())
    assert (await cliente.get("/api/presupuestos", headers=await auth(OP))).status_code == 403


async def test_consumo_en_un_grupo_y_tipo_de_actividad(cliente, auth, datos):
    grupo = await _grupo_demo(cliente, auth, datos)
    un = datos["unidades"][0]
    p_un = await presupuesto(cliente, auth, datos, un_id=un, monto="30000.00", nombre="UN todos")
    p_grupo = await presupuesto(cliente, auth, datos, grupo_id=grupo["id"], monto="40000.00", tipo="correctivo", nombre="Grupo correctivos")
    p_otro_tipo = await presupuesto(cliente, auth, datos, un_id=un, monto="15000.00", tipo="preventivo", nombre="UN preventivos")
    f, total = await _folio_con_costo(cliente, auth, datos, "1200.00")
    await validar_costo(cliente, auth, f["id"])
    # El folio correctivo carga al de su UN (todos) y al del grupo (correctivo), no al de preventivos.
    detalle_un = (await cliente.get(f"/api/presupuestos/{p_un['id']}", headers=await auth(AE))).json()
    detalle_grupo = (await cliente.get(f"/api/presupuestos/{p_grupo['id']}", headers=await auth(AE))).json()
    detalle_prev = (await cliente.get(f"/api/presupuestos/{p_otro_tipo['id']}", headers=await auth(AE))).json()
    assert Decimal(detalle_un["consumido"]) == total and Decimal(detalle_grupo["consumido"]) == total
    assert Decimal(detalle_prev["consumido"]) == 0
    assert Decimal(detalle_un["disponible"]) == Decimal(detalle_un["monto"]) - total - Decimal(detalle_un["comprometido"])
    # El detalle lista los folios cargados.
    consumos = (await cliente.get(f"/api/presupuestos/{p_un['id']}/consumos", headers=await auth(AE))).json()
    mio = next(c for c in consumos if c["folio_id"] == f["id"])
    assert mio["numero_folio"] == f["numero_folio"] and Decimal(mio["monto"]) == total and mio["tipo"] == "correctivo"
    # Idempotente: revalidar no duplica el consumo (el costo ya está validado).
    assert (await validar_costo(cliente, auth, f["id"], esperado=409))["codigo"] == "COSTO_YA_VALIDADO"
    assert len((await cliente.get(f"/api/presupuestos/{p_un['id']}/consumos", headers=await auth(AE))).json()) == len(consumos)


async def test_umbrales_excedido_y_comprometido(cliente, auth, datos):
    un = datos["unidades"][0]
    f, total = await _folio_con_costo(cliente, auth, datos, "2000.00")
    # Monto que deja el consumo en ~95%: dispara los umbrales 50 y 80, no el de 100.
    p = await presupuesto(cliente, auth, datos, un_id=un, monto=str((total / Decimal("0.95")).quantize(Decimal("0.01"))), nombre="Casi agotado")
    await validar_costo(cliente, auth, f["id"])
    d = (await cliente.get(f"/api/presupuestos/{p['id']}", headers=await auth(AE))).json()
    assert 90 <= Decimal(d["porcentaje"]) < 100 and d["semaforo"] == "amarillo" and Decimal(d["desviacion"]) < 0
    # P10 concilió las claves: §6.9.6 nombra PRESUPUESTO_ALERTA_1/2/3.
    assert await alertas_disparadas("PRESUPUESTO_ALERTA_1", p["id"]) or await alertas_disparadas("PRESUPUESTO_ALERTA_2", p["id"])
    assert any(n["evento"] == "presupuesto.umbral" and n["datos"]["presupuesto_id"] == p["id"] for n in await bandeja(cliente, auth, AE))
    # Un segundo presupuesto chico queda excedido con el mismo folio.
    g, total2 = await _folio_con_costo(cliente, auth, datos, "3000.00")
    chico = await presupuesto(cliente, auth, datos, un_id=un, monto=str((total2 * Decimal("0.5")).quantize(Decimal("0.01"))), nombre="Excedido")
    await validar_costo(cliente, auth, g["id"])
    d2 = (await cliente.get(f"/api/presupuestos/{chico['id']}", headers=await auth(AE))).json()
    assert Decimal(d2["porcentaje"]) > 100 and d2["semaforo"] == "rojo" and Decimal(d2["desviacion"]) > 0
    assert await alertas_disparadas("PRESUPUESTO_ALERTA_3", chico["id"])
    # Comprometido: un folio autorizado sin cerrar con monto estimado.
    from tests.folios_utiles import autorizar_sin_flujo

    abierto = await autorizar_sin_flujo(cliente, auth, datos, MC, monto_estimado="4000.00")  # solo Mesa/Despachador/Admin prestador fijan monto
    nuevo = await presupuesto(cliente, auth, datos, un_id=abierto["un_id"], monto="50000.00", nombre="Con comprometido")
    d3 = (await cliente.get(f"/api/presupuestos/{nuevo['id']}", headers=await auth(AE))).json()
    assert Decimal(d3["comprometido"]) >= 4000 and Decimal(d3["disponible"]) == Decimal(d3["monto"]) - Decimal(d3["consumido"]) - Decimal(d3["comprometido"])


async def test_vista_consolidada(cliente, auth, datos):
    grupo = await _grupo_demo(cliente, auth, datos)
    await presupuesto(cliente, auth, datos, un_id=datos["unidades"][0], monto="10000.00", nombre="Consolidado UN")
    await presupuesto(cliente, auth, datos, grupo_id=grupo["id"], monto="20000.00", nombre="Consolidado grupo")
    r = await cliente.get("/api/presupuestos/consolidado", headers=await auth(AE))
    assert r.status_code == 200, r.text
    c = r.json()
    assert Decimal(c["tenant"]["monto"]) >= 30000 and c["tenant"]["semaforo"] in ("verde", "amarillo", "rojo")
    assert any(g["nombre"] == grupo["nombre"] for g in c["grupos"]) and c["unidades"]
    assert all({"monto", "consumido", "comprometido", "disponible", "porcentaje", "desviacion", "semaforo"} <= set(n) for n in c["grupos"] + c["unidades"])
    assert Decimal(c["tenant"]["disponible"]) == Decimal(c["tenant"]["monto"]) - Decimal(c["tenant"]["consumido"]) - Decimal(c["tenant"]["comprometido"])
    # El Admin UN ve el consolidado de sus UNs; otro cliente no ve nada de este tenant.
    suyo = (await cliente.get("/api/presupuestos/consolidado", headers=await auth(AUN))).json()
    assert all(p["un_id"] in [str(u) for u in datos["unidades"]] or p["grupo_id"] for p in suyo["presupuestos"])
    ajeno = (await cliente.get("/api/presupuestos/consolidado", headers=await auth(OTRO_AE))).json()
    assert all(p["tenant_id"] != str(datos["tenant"]) for p in ajeno["presupuestos"])


async def test_tarifas_de_mano_de_obra(cliente, auth, datos):
    t = await tarifa(cliente, auth, "515.00", tipo_folio="especial")
    assert Decimal(t["tarifa_hora"]) == 515 and t["tipo_folio"] == "especial" and t["activa"] is True
    assert (await cliente.post("/api/presupuestos/tarifas", headers=await auth(DES), json={"tarifa_hora": "100.00"})).status_code == 403
    lista = (await cliente.get("/api/presupuestos/tarifas", headers=await auth(MC))).json()
    assert any(x["id"] == t["id"] for x in lista)
    assert (await cliente.get("/api/presupuestos/tarifas", headers=await auth(TEC))).status_code == 403
