"""Ficha de activos, depreciación y TCO (§6.9.4): los cuatro métodos con casos numéricos, unidades de producción como Fase 2,
los seis componentes del TCO, alerta de reemplazo y sus dos decisiones, y permisos de la ficha."""
from datetime import date, timedelta
from decimal import Decimal

from tests.folios_utiles import AE, AP, AUN, DES, MC, OP, OTRO_AE, TEC, nuevo_equipo
from tests.inventario_utiles import (
    alertas_disparadas, bandeja, cerrar_folio, equipo_con_activo, folio_en_ejecucion, permiso_tecnico, refaccion, tarifa, validar_costo,
)


async def _ficha(cliente, auth, equipo_id, email=AE) -> dict:
    r = await cliente.get(f"/api/activos/{equipo_id}", headers=await auth(email))
    assert r.status_code == 200, r.text
    return r.json()


async def test_datos_economicos_y_depreciacion_linea_recta(cliente, auth, datos):
    e = await equipo_con_activo(cliente, auth, datos, costo="120000.00", reposicion="150000.00")
    f = await _ficha(cliente, auth, e["id"])
    assert Decimal(f["equipo"]["costo_adquisicion"]) == 120000 and Decimal(f["equipo"]["costo_hora_inactividad"]) == 400
    # F2-05: la criticidad y el FMEA ya no son Fase 2. Un equipo recien creado no tiene evaluacion, y la ficha lo
    # dice en lugar de etiquetarlos como pendientes.
    assert f["equipo"]["criticidad_origen"] == "manual"   # el campo capturado a mano, sin evaluacion de F2-05
    assert not any("riticidad" in x or "FMEA" in x for x in f["fase_2"]), f["fase_2"]
    assert (await cliente.put(f"/api/activos/{e['id']}/datos-economicos", headers=await auth(DES), json={"costo_adquisicion": "1.00"})).status_code == 403
    # Línea recta: 10 años, salvamento 20000 → (120000-20000)/120 = 833.33 al mes; a 4 años (48 meses) quedan 80000.
    inicio = date.today() - timedelta(days=365 * 4)
    r = await cliente.put(f"/api/activos/{e['id']}/depreciacion", headers=await auth(AE),
                          json={"metodo": "linea_recta", "vida_util_anios": 10, "valor_salvamento": "20000.00", "fecha_inicio": inicio.isoformat(),
                                "valor_reposicion": "150000.00"})
    assert r.status_code == 200, r.text
    f = r.json()
    assert f["depreciacion"]["metodo"] == "linea_recta" and f["depreciacion"]["aviso"] == ""
    residual = Decimal(f["tco"]["valor_residual"])
    assert Decimal("79000") <= residual <= Decimal("81000"), residual
    # El historial mensual se escribe con el método aplicado.
    r = await cliente.post(f"/api/activos/{e['id']}/calcular", headers=await auth(AE))
    assert r.status_code == 200
    h = r.json()["depreciacion_historial"][-1]
    assert h["metodo_aplicado"] == "linea_recta" and Decimal(h["depreciacion_periodo"]) > 0
    assert Decimal(h["depreciacion_acumulada"]) == 120000 - Decimal(h["valor_en_libros"])


async def test_doble_saldo_decreciente_manual_y_unidades(cliente, auth, datos):
    # Doble saldo: tasa 2/vida sobre el valor en libros; en 12 meses con vida 5 años pierde más que línea recta.
    e = await equipo_con_activo(cliente, auth, datos, costo="100000.00", reposicion="110000.00")
    inicio = date.today() - timedelta(days=365)
    r = await cliente.put(f"/api/activos/{e['id']}/depreciacion", headers=await auth(AE),
                          json={"metodo": "doble_saldo_decreciente", "vida_util_anios": 5, "valor_salvamento": "10000.00",
                                "fecha_inicio": inicio.isoformat(), "valor_reposicion": "110000.00"})
    residual_dsd = Decimal(r.json()["tco"]["valor_residual"])
    assert Decimal("60000") < residual_dsd < Decimal("70000"), residual_dsd  # ~100000×(1-2/60)^12
    # Nunca baja del valor de salvamento.
    await cliente.put(f"/api/activos/{e['id']}/depreciacion", headers=await auth(AE),
                      json={"fecha_inicio": (date.today() - timedelta(days=365 * 20)).isoformat()})
    assert Decimal((await _ficha(cliente, auth, e["id"]))["tco"]["valor_residual"]) == 10000
    # Manual: el admin fija el valor en libros.
    e2 = await equipo_con_activo(cliente, auth, datos, costo="50000.00", reposicion="60000.00")
    r = await cliente.put(f"/api/activos/{e2['id']}/depreciacion", headers=await auth(AE),
                          json={"metodo": "manual", "valor_en_libros_manual": "31500.00", "valor_reposicion": "60000.00"})
    assert Decimal(r.json()["tco"]["valor_residual"]) == 31500
    # Unidades de producción: F2-04 lo calcula de verdad. Sin medidor elegido usa el campo manual de unidades y
    # avisa MEDIDOR_NO_CONFIGURADO: 50,000 × (5,000 ÷ 20,000) = 12,500 de depreciación acumulada.
    r = await cliente.put(f"/api/activos/{e2['id']}/depreciacion", headers=await auth(AE),
                          json={"metodo": "unidades_produccion", "unidades_vida_util": "20000", "unidades_acumuladas": "5000"})
    assert r.json()["depreciacion"]["aviso"] == "MEDIDOR_NO_CONFIGURADO"
    assert Decimal(r.json()["tco"]["valor_residual"]) == 37500
    # Los medidores ya no son Fase 2; lo que queda ahí es la criticidad automática, el FMEA y el MTBF/MTTR.
    assert not any("Medidores" in x for x in r.json()["fase_2"])


async def test_tco_con_sus_componentes(cliente, auth, datos):
    """Adquisición, preventivos, correctivos, refacciones, downtime y valor residual."""
    await tarifa(cliente, auth, "500.00")
    e = await equipo_con_activo(cliente, auth, datos, costo="80000.00", reposicion="100000.00")
    await cliente.put(f"/api/activos/{e['id']}/depreciacion", headers=await auth(AE),
                      json={"metodo": "manual", "valor_en_libros_manual": "40000.00", "valor_reposicion": "100000.00"})
    # Un correctivo cerrado y validado sobre ese equipo.
    from tests.folios_utiles import REGLAS_DEMO, capturar, reglas, tecnico_con_habilidades

    from datetime import UTC, datetime

    await reglas(cliente, auth, [])
    try:
        # La falla ocurrió 5 h antes del cierre: así el downtime del TCO es medible.
        folio = await capturar(cliente, auth, datos, OP, e, fecha_falla=(datetime.now(UTC) - timedelta(hours=5)).isoformat())
    finally:
        await reglas(cliente, auth, REGLAS_DEMO)
    tec = await tecnico_con_habilidades(cliente, auth, TEC, ["refrigeracion", "electricidad"])
    from tests.inventario_utiles import accion

    await accion(cliente, auth, DES, folio["id"], "asignar", {"tecnico_id": tec})
    await accion(cliente, auth, TEC, folio["id"], "en-camino")
    await accion(cliente, auth, TEC, folio["id"], "confirmar-llegada")
    await refaccion(cliente, auth, folio["id"], descripcion="Refacción del activo", cantidad="1", costo="2500.00")
    await cerrar_folio(cliente, auth, datos, folio)
    await validar_costo(cliente, auth, folio["id"])
    f = await _ficha(cliente, auth, e["id"])
    t = f["tco"]
    assert Decimal(t["costo_adquisicion"]) == 80000 and Decimal(t["costo_correctivos"]) > 0 and Decimal(t["costo_refacciones"]) == 2500
    assert Decimal(t["horas_downtime"]) > 0 and Decimal(t["costo_downtime"]) == (Decimal(t["horas_downtime"]) * 400).quantize(Decimal("0.01"))
    assert Decimal(t["valor_residual"]) == 40000 and t["folios"] == 1
    esperado = Decimal(t["costo_adquisicion"]) + Decimal(t["costo_preventivos"]) + Decimal(t["costo_correctivos"]) + Decimal(t["costo_downtime"]) - Decimal(t["valor_residual"])
    assert Decimal(t["tco_total"]) == esperado.quantize(Decimal("0.01"))
    assert Decimal(t["porcentaje_vs_reposicion"]) == (Decimal(t["tco_total"]) / 100000 * 100).quantize(Decimal("0.01"))
    # El historial del folio aparece en la ficha con su costo.
    fila = next(x for x in f["historial_folios"] if x["numero_folio"] == folio["numero_folio"])
    assert fila["costo_validado"] is True and Decimal(fila["costo_total"]) > 0 and fila["tipo_folio"] == "correctivo"
    assert any(r["descripcion"] == "Refacción del activo" for r in f["refacciones"])
    # El listado trae el TCO y el porcentaje del último snapshot.
    await cliente.post(f"/api/activos/{e['id']}/calcular", headers=await auth(AE))
    item = next(x for x in (await cliente.get("/api/activos", headers=await auth(AE))).json() if x["id"] == e["id"])
    assert Decimal(item["tco_total"]) == Decimal(t["tco_total"]) and item["periodo_tco"]


async def test_alerta_de_reemplazo_y_sus_dos_decisiones(cliente, auth, datos):
    # Umbral bajo para que el TCO lo supere con la sola adquisición menos el residual.
    r = await cliente.put("/api/activos/umbral-reemplazo", headers=await auth(AE), json={"umbral_reemplazo_pct": "50"})
    assert r.status_code == 200 and r.json()["umbral_reemplazo_pct"] == 50.0
    assert (await cliente.put("/api/activos/umbral-reemplazo", headers=await auth(AUN), json={"umbral_reemplazo_pct": "90"})).status_code == 403
    e = await equipo_con_activo(cliente, auth, datos, costo="90000.00", reposicion="100000.00")
    await cliente.put(f"/api/activos/{e['id']}/depreciacion", headers=await auth(AE),
                      json={"metodo": "manual", "valor_en_libros_manual": "10000.00", "valor_reposicion": "100000.00"})
    await cliente.post(f"/api/activos/{e['id']}/calcular", headers=await auth(AE))
    f = await _ficha(cliente, auth, e["id"])
    assert Decimal(f["tco"]["porcentaje_vs_reposicion"]) >= 50 and f["alerta_reemplazo"] is not None
    alerta = f["alerta_reemplazo"]
    assert alerta["decision"] is None and Decimal(alerta["porcentaje_umbral"]) == 50
    assert await alertas_disparadas("ACTIVO_REEMPLAZO", e["id"])
    assert any(n["evento"] == "activo.reemplazo" and n["datos"]["equipo_id"] == e["id"] for n in await bandeja(cliente, auth, AE))
    assert any(x["id"] == e["id"] and x["alerta_reemplazo"] for x in (await cliente.get("/api/activos", headers=await auth(AE), params={"con_alerta": True})).json())
    # Posponer exige razón documentada.
    assert (await cliente.post(f"/api/activos/alertas-reemplazo/{alerta['id']}/decidir", headers=await auth(AE),
                               json={"decision": "pospuesto", "razon": ""})).status_code == 422
    assert (await cliente.post(f"/api/activos/alertas-reemplazo/{alerta['id']}/decidir", headers=await auth(AUN),
                               json={"decision": "pospuesto", "razon": "No hay presupuesto"})).status_code == 403
    r = await cliente.post(f"/api/activos/alertas-reemplazo/{alerta['id']}/decidir", headers=await auth(AE),
                           json={"decision": "pospuesto", "razon": "Sin presupuesto hasta el próximo trimestre"})
    assert r.status_code == 200 and r.json()["alerta"]["decision"] == "pospuesto" and r.json()["trabajo_especial"] is None
    assert (await cliente.post(f"/api/activos/alertas-reemplazo/{alerta['id']}/decidir", headers=await auth(AE),
                               json={"decision": "aceptado"})).status_code == 409
    # Aceptar en otro activo genera el trabajo especial de reemplazo en estado `creado`.
    e2 = await equipo_con_activo(cliente, auth, datos, costo="70000.00", reposicion="80000.00")
    await cliente.put(f"/api/activos/{e2['id']}/depreciacion", headers=await auth(AE),
                      json={"metodo": "manual", "valor_en_libros_manual": "5000.00", "valor_reposicion": "80000.00"})
    await cliente.post(f"/api/activos/{e2['id']}/calcular", headers=await auth(AE))
    alerta2 = (await _ficha(cliente, auth, e2["id"]))["alerta_reemplazo"]
    r = await cliente.post(f"/api/activos/alertas-reemplazo/{alerta2['id']}/decidir", headers=await auth(AE), json={"decision": "aceptado"})
    assert r.status_code == 200, r.text
    te = r.json()["trabajo_especial"]
    assert te and te["estado"] == "creado" and te["numero"].startswith("TE-") and "Reemplazo recomendado" in te["descripcion"]
    assert r.json()["alerta"]["trabajo_especial_id"] == te["id"]
    d = (await cliente.get(f"/api/trabajos-especiales/{te['id']}", headers=await auth(DES))).json()
    assert d["equipo_id"] == e2["id"] and d["creado_por_rol"] == "admin_prestador" and d["detalle_json"]["origen"] == "reemplazo_tco"
    assert any("recomendación de reemplazo" in h["notas"] for h in d["historial"])
    await cliente.put("/api/activos/umbral-reemplazo", headers=await auth(AE), json={"umbral_reemplazo_pct": "70"})


async def test_permisos_de_la_ficha(cliente, auth, datos):
    e = await equipo_con_activo(cliente, auth, datos)
    assert (await cliente.get(f"/api/activos/{e['id']}", headers=await auth(OTRO_AE))).status_code == 404
    assert (await cliente.get(f"/api/activos/{e['id']}", headers=await auth(MC))).status_code == 200  # el prestador que atiende
    assert (await cliente.get("/api/activos", headers=await auth(OP))).status_code == 403
    # El técnico necesita ver_historial_equipo y solo ve costos con ver_costo_refacciones.
    await permiso_tecnico(cliente, auth, TEC, "ver_historial_equipo", False)
    assert (await cliente.get(f"/api/activos/{e['id']}", headers=await auth(TEC))).status_code == 403
    await permiso_tecnico(cliente, auth, TEC, "ver_historial_equipo", True)
    await permiso_tecnico(cliente, auth, TEC, "ver_costo_refacciones", False)
    f = (await cliente.get(f"/api/activos/{e['id']}", headers=await auth(TEC))).json()
    assert all(x["costo_total"] is None for x in f["historial_folios"]) and all(r["costo_unitario"] is None for r in f["refacciones"])
    await permiso_tecnico(cliente, auth, TEC, "ver_costo_refacciones", True)
