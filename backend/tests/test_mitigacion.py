"""Acciones de mitigación del riesgo (§6.9.3): alta con su vínculo según el tipo, estados, efectividad medida
antes contra después, bandeja de pendientes y vencidas, y aislamiento entre clientes. F2-05."""
from datetime import date, timedelta

from tests.criticidad_utiles import equipo_con_historia, mitigacion, modo_falla, sembrar_fallas
from tests.folios_utiles import AE, AP, DES, OP, OTRO_AE, TEC, tipo_equipo
from tests.preventivos_utiles import nuevo_plan


async def test_alta_de_una_accion_y_su_vinculo_segun_el_tipo(cliente, auth, datos):
    """Una acción de tipo «plan preventivo» sin plan es una intención, no una acción: se rechaza."""
    equipo = await equipo_con_historia(cliente, auth, datos, fallas=2)
    modo = await modo_falla(cliente, auth, equipo["id"])
    m = await mitigacion(cliente, auth, modo["id"],
                         accion_mitigacion="Cambiar el empaque de la puerta cada seis meses",
                         fecha_compromiso=str(date.today() + timedelta(days=30)))
    assert m["estado"] == "propuesta" and m["tipo"] == "otro" and m["tenant_id"] == str(datos["tenant"])
    assert m["efectividad_json"] == {} and m["fecha_implementacion"] is None

    await mitigacion(cliente, auth, modo["id"], tipo="plan_preventivo", esperado=422)
    await mitigacion(cliente, auth, modo["id"], tipo="capacitacion", esperado=422)
    await mitigacion(cliente, auth, modo["id"], tipo="refaccion_en_inventario", esperado=422)
    # Con su vínculo sí pasa: la acción queda atada al plan que la cumple.
    plan = await nuevo_plan(cliente, auth)
    con_plan = await mitigacion(cliente, auth, modo["id"], tipo="plan_preventivo",
                                plan_mantenimiento_id=plan["id"])
    assert con_plan["plan_mantenimiento_id"] == plan["id"] and con_plan["tipo"] == "plan_preventivo"


async def test_los_estados_de_una_accion(cliente, auth, datos):
    equipo = await equipo_con_historia(cliente, auth, datos, fallas=2)
    modo = await modo_falla(cliente, auth, equipo["id"])
    m = await mitigacion(cliente, auth, modo["id"])
    r = await cliente.post(f"/api/mitigaciones/{m['id']}/estado", headers=await auth(AP),
                           json={"estado": "en_proceso"})
    assert r.status_code == 200 and r.json()["estado"] == "en_proceso"
    # Implementada sin fecha toma la de hoy.
    r = await cliente.post(f"/api/mitigaciones/{m['id']}/estado", headers=await auth(AP),
                           json={"estado": "implementada"})
    assert r.status_code == 200 and r.json()["fecha_implementacion"] == str(date.today())
    # Una fecha futura no: todavía no pasó.
    otra = await mitigacion(cliente, auth, modo["id"])
    r = await cliente.post(f"/api/mitigaciones/{otra['id']}/estado", headers=await auth(AP),
                           json={"estado": "implementada",
                                 "fecha_implementacion": str(date.today() + timedelta(days=3))})
    assert r.status_code == 422 and r.json()["codigo"] == "FECHA_FUTURA", r.text
    # Descartar exige razón: es lo que queda en la traza.
    r = await cliente.post(f"/api/mitigaciones/{otra['id']}/estado", headers=await auth(AP),
                           json={"estado": "descartada"})
    assert r.status_code == 422 and r.json()["codigo"] == "RAZON_REQUERIDA", r.text
    r = await cliente.post(f"/api/mitigaciones/{otra['id']}/estado", headers=await auth(AP),
                           json={"estado": "descartada", "razon": "El activo se va a reemplazar este año"})
    assert r.status_code == 200 and r.json()["razon_descarte"].startswith("El activo se va a reemplazar")


async def test_efectividad_sin_implementar_y_antes_de_los_90_dias(cliente, auth, datos):
    """Antes de 90 días la diferencia es ruido, no medición: ACMA lo dice en lugar de inventar un veredicto."""
    equipo = await equipo_con_historia(cliente, auth, datos, fallas=4)
    modo = await modo_falla(cliente, auth, equipo["id"])
    m = await mitigacion(cliente, auth, modo["id"])
    e = (await cliente.get(f"/api/mitigaciones/{m['id']}/efectividad", headers=await auth(AP))).json()
    assert e["estado"] == "sin_implementar"
    await cliente.post(f"/api/mitigaciones/{m['id']}/estado", headers=await auth(AP),
                       json={"estado": "implementada", "fecha_implementacion": str(date.today() - timedelta(days=30))})
    e = (await cliente.get(f"/api/mitigaciones/{m['id']}/efectividad", headers=await auth(AP))).json()
    assert e["estado"] == "sin_datos_suficientes" and e["dias_desde_implementacion"] == 30
    assert "60 días" in e["nota"]


async def test_efectividad_medida_antes_contra_despues(cliente, auth, datos):
    """§6.9.3 pide medir si la acción sirvió: las fallas y el MTBF de los 6 meses previos contra los posteriores."""
    equipo = await equipo_con_historia(cliente, auth, datos, fallas=0)
    await sembrar_fallas(equipo["id"], 6, desde_dias=320, hasta_dias=170)   # antes de implementar
    await sembrar_fallas(equipo["id"], 1, desde_dias=90, hasta_dias=90)     # después
    modo = await modo_falla(cliente, auth, equipo["id"])
    m = await mitigacion(cliente, auth, modo["id"], tipo="rediseno",
                         accion_mitigacion="Reubicar el condensador para que ventile")
    implementada = str(date.today() - timedelta(days=150))
    r = await cliente.post(f"/api/mitigaciones/{m['id']}/estado", headers=await auth(AP),
                           json={"estado": "implementada", "fecha_implementacion": implementada})
    assert r.status_code == 200, r.text
    # La efectividad se calcula al marcarla implementada y queda guardada en la fila.
    guardada = r.json()["efectividad_json"]
    assert guardada["estado"] == "medida" and guardada["ventana_meses"] == 6

    e = (await cliente.get(f"/api/mitigaciones/{m['id']}/efectividad", headers=await auth(AP))).json()
    assert e["estado"] == "medida" and e["dias_desde_implementacion"] == 150
    assert e["antes"]["fallas"] == 6 and e["despues"]["fallas"] == 1
    assert e["delta_fallas"] == 5 and e["veredicto"] == "mejoro"
    assert "6 falla(s)" in e["nota"] and "1 después" in e["nota"]
    assert e["antes"]["mtbf_horas"] is not None and e["despues"]["mtbf_horas"] is None   # una sola falla, sin intervalo


async def test_efectividad_que_empeoro_y_la_que_no_se_mueve(cliente, auth, datos):
    """El veredicto es honesto en los dos sentidos: también dice cuándo la acción no sirvió."""
    peor = await equipo_con_historia(cliente, auth, datos, fallas=0)
    await sembrar_fallas(peor["id"], 1, desde_dias=300, hasta_dias=300)
    await sembrar_fallas(peor["id"], 5, desde_dias=140, hasta_dias=20)
    modo = await modo_falla(cliente, auth, peor["id"])
    m = await mitigacion(cliente, auth, modo["id"])
    r = await cliente.post(f"/api/mitigaciones/{m['id']}/estado", headers=await auth(AP),
                           json={"estado": "implementada",
                                 "fecha_implementacion": str(date.today() - timedelta(days=150))})
    assert r.status_code == 200, r.text
    e = (await cliente.get(f"/api/mitigaciones/{m['id']}/efectividad", headers=await auth(AP))).json()
    assert e["estado"] == "medida" and e["veredicto"] == "empeoro" and e["delta_fallas"] < 0


async def test_la_efectividad_de_un_modo_generico_no_se_mide_por_equipo(cliente, auth, datos):
    """Un modo genérico del tipo de equipo no tiene un activo del que medir el antes y el después."""
    tipo = await tipo_equipo(cliente, auth, "Iluminación", 1)
    modo = await modo_falla(cliente, auth, tipo_equipo_id=tipo["id"], tenant_id=str(datos["tenant"]))
    m = await mitigacion(cliente, auth, modo["id"])
    await cliente.post(f"/api/mitigaciones/{m['id']}/estado", headers=await auth(AP),
                       json={"estado": "implementada",
                             "fecha_implementacion": str(date.today() - timedelta(days=200))})
    e = (await cliente.get(f"/api/mitigaciones/{m['id']}/efectividad", headers=await auth(AP))).json()
    assert e["estado"] == "no_aplicable" and "genérico" in e["nota"]


async def test_bandeja_de_pendientes_con_lo_vencido_primero(cliente, auth, datos):
    equipo = await equipo_con_historia(cliente, auth, datos, fallas=2)
    modo = await modo_falla(cliente, auth, equipo["id"], severidad=5, frecuencia_historica=4)
    vencida = await mitigacion(cliente, auth, modo["id"], accion_mitigacion="Acción con compromiso vencido",
                               fecha_compromiso=str(date.today() - timedelta(days=12)))
    futura = await mitigacion(cliente, auth, modo["id"], accion_mitigacion="Acción con compromiso al mes",
                              fecha_compromiso=str(date.today() + timedelta(days=30)))
    cerrada = await mitigacion(cliente, auth, modo["id"], accion_mitigacion="Acción ya implementada")
    await cliente.post(f"/api/mitigaciones/{cerrada['id']}/estado", headers=await auth(AP),
                       json={"estado": "implementada"})

    bandeja = (await cliente.get("/api/mitigaciones/pendientes", headers=await auth(AP))).json()
    ids = [x["id"] for x in bandeja]
    assert vencida["id"] in ids and futura["id"] in ids
    assert cerrada["id"] not in ids           # lo implementado ya no es pendiente
    fila = next(x for x in bandeja if x["id"] == vencida["id"])
    assert fila["vencida"] is True and fila["dias_vencida"] == 12
    assert fila["equipo_codigo"] == equipo["codigo"] and fila["nivel_riesgo"] == 20
    assert fila["modo_falla"] == modo["descripcion_falla"]
    assert ids.index(vencida["id"]) < ids.index(futura["id"])   # lo vencido primero

    solo = (await cliente.get("/api/mitigaciones/pendientes", headers=await auth(AP),
                              params={"solo_vencidas": True})).json()
    assert vencida["id"] in {x["id"] for x in solo} and futura["id"] not in {x["id"] for x in solo}
    resumen = (await cliente.get("/api/criticidad/resumen", headers=await auth(AE))).json()
    assert resumen["mitigaciones_vencidas"] >= 1


async def test_alerta_de_mitigacion_vencida(cliente, auth, datos):
    """MITIGACION_VENCIDA: una acción comprometida que no se implementó no se queda callada."""
    from tests.operacion_utiles import alertas_de, evaluar as correr_evaluador

    equipo = await equipo_con_historia(cliente, auth, datos, fallas=2)
    modo = await modo_falla(cliente, auth, equipo["id"])
    m = await mitigacion(cliente, auth, modo["id"], accion_mitigacion="Acción vencida para la alerta",
                         fecha_compromiso=str(date.today() - timedelta(days=45)))
    await correr_evaluador("MITIGACION_VENCIDA")
    mias = [a for a in await alertas_de("MITIGACION_VENCIDA") if a["datos"].get("mitigacion_id") == m["id"]]
    assert len(mias) == 1, mias
    assert mias[0]["datos"]["dias"] >= 45
    await correr_evaluador("MITIGACION_VENCIDA")        # una vez por acción, no una por día
    assert len([a for a in await alertas_de("MITIGACION_VENCIDA")
                if a["datos"].get("mitigacion_id") == m["id"]]) == 1


async def test_quien_registra_y_quien_consulta_mitigaciones(cliente, auth, datos):
    equipo = await equipo_con_historia(cliente, auth, datos, fallas=1)
    modo = await modo_falla(cliente, auth, equipo["id"])
    for email in (AE, AP, DES):
        await mitigacion(cliente, auth, modo["id"], email=email)
    for email in (OP, TEC):
        await mitigacion(cliente, auth, modo["id"], email=email, esperado=403)
        assert (await cliente.get("/api/mitigaciones", headers=await auth(email),
                                  params={"modo_falla_id": modo["id"]})).status_code == 403


async def test_aislamiento_de_las_mitigaciones(cliente, auth, datos):
    equipo = await equipo_con_historia(cliente, auth, datos, fallas=1)
    modo = await modo_falla(cliente, auth, equipo["id"])
    m = await mitigacion(cliente, auth, modo["id"])
    assert (await cliente.get("/api/mitigaciones", headers=await auth(OTRO_AE),
                              params={"modo_falla_id": modo["id"]})).status_code == 404
    assert (await cliente.get(f"/api/mitigaciones/{m['id']}/efectividad",
                              headers=await auth(OTRO_AE))).status_code == 404
    assert (await cliente.post(f"/api/mitigaciones/{m['id']}/estado", headers=await auth(OTRO_AE),
                               json={"estado": "implementada"})).status_code == 404
    await mitigacion(cliente, auth, modo["id"], email=OTRO_AE, esperado=404)
    ajena = (await cliente.get("/api/mitigaciones/pendientes", headers=await auth(OTRO_AE))).json()
    assert m["id"] not in {x["id"] for x in ajena}
