"""TE de urgencia (§6.10.6): creación por Admin empresa / Admin UN sin monto, salto directo a programado sin validación del cliente,
cancelación por el cliente solo antes de programar, cotización retroactiva opcional que no bloquea el cierre, bandera en listado,
reporte y minuta, y la alerta informativa."""
from datetime import UTC, date, datetime, timedelta

from tests.folios_utiles import AP, DES, MC, OP, SUPO, TEC
from tests.seguimiento_utiles import alertas_disparadas, bandeja, configurar_minuta, generar_minuta, limpiar_minutas_hoy, minuta_detalle, retroceder
from tests.te_utiles import AE, AUN, accion_te, cerrar_te_completo, crear_te, detalle_te, formulario_te, habilitar_te


async def _urgencia(cliente, auth, datos, email=AUN, **extra) -> dict:
    return await crear_te(cliente, auth, datos, email, descripcion="Fuga de agua en la cámara: requiere plomero hoy (urgencia)", urgencia=True, monto="999.00", **extra)


async def test_creacion_de_urgencia_por_el_cliente_y_salto_a_programado(cliente, auth, datos):
    await formulario_te(cliente, auth)
    assert (await crear_te(cliente, auth, datos, OP, urgencia=True, esperado=403))["codigo"] == "PROHIBIDO"
    assert (await crear_te(cliente, auth, datos, SUPO, urgencia=True, esperado=403))["codigo"] == "PROHIBIDO"
    te = await _urgencia(cliente, auth, datos, AUN)
    assert te["urgencia"] is True and te["monto"] is None and te["creado_por_rol"] == "admin_un" and te["estado"] == "creado"
    assert te["destinos"] == ["cancelado"] and sorted((await detalle_te(cliente, auth, te["id"]))["destinos"]) == ["cancelado", "enviado_cliente", "programado"]  # el cliente no programa
    assert any(n["evento"] == "trabajo_especial.urgencia" and n["datos"]["numero"] == te["numero"] for n in await bandeja(cliente, auth, DES, solo_no_leidas=True))
    # Un TE ordinario no salta a programado desde creado; el de urgencia sí (sin validación del cliente).
    ordinario = await crear_te(cliente, auth, datos, DES)
    tid = await habilitar_te(cliente, auth, TEC, True)
    r = await accion_te(cliente, auth, DES, ordinario["id"], "programar", {"fecha_programada": date.today().isoformat(), "tecnico_ids": [tid]}, 409)
    assert r["codigo"] == "TRANSICION_NO_PERMITIDA"
    d = await accion_te(cliente, auth, DES, te["id"], "programar", {"fecha_programada": date.today().isoformat(), "tecnico_ids": [tid], "notas": "Urgencia"})
    assert d["estado"] == "programado" and d["version_enviada"] == 0 and d["folio_id"] and d["estado_folio"] == "asignado"
    assert next(h for h in d["historial"] if h["estado_nuevo"] == "programado")["datos_json"]["sin_validacion_cliente"] is True
    # Bandera visible en el listado y filtro por urgencia.
    lista = (await cliente.get("/api/trabajos-especiales", headers=await auth(AE), params={"urgencia": True})).json()
    assert any(x["id"] == te["id"] for x in lista) and all(x["urgencia"] for x in lista)
    assert all(x["id"] != te["id"] for x in (await cliente.get("/api/trabajos-especiales", headers=await auth(AE), params={"urgencia": False})).json())


async def test_cancelacion_del_cliente_solo_antes_de_programar(cliente, auth, datos):
    await formulario_te(cliente, auth)
    te = await _urgencia(cliente, auth, datos, AE)
    assert (await accion_te(cliente, auth, AUN, te["id"], "cancelar", {"notas": "x"}, 422))["codigo"] == "JUSTIFICACION_REQUERIDA"
    c = await accion_te(cliente, auth, AE, te["id"], "cancelar", {"notas": "Ya lo resolvió el personal de la sucursal"})
    assert c["estado"] == "cancelado"
    te2 = await _urgencia(cliente, auth, datos, AUN)
    tid = await habilitar_te(cliente, auth, TEC, True)
    await accion_te(cliente, auth, DES, te2["id"], "programar", {"fecha_programada": date.today().isoformat(), "tecnico_ids": [tid]})
    assert (await accion_te(cliente, auth, AUN, te2["id"], "cancelar", {"notas": "Ya no hace falta"}, 409))["codigo"] == "TRANSICION_NO_PERMITIDA"
    assert (await accion_te(cliente, auth, AP, te2["id"], "cancelar", {"notas": "Se atendió como correctivo"}))["estado"] == "cancelado"


async def test_cotizacion_retroactiva_opcional_y_cierre(cliente, auth, datos):
    await formulario_te(cliente, auth)
    tid = await habilitar_te(cliente, auth, TEC, True)
    te = await _urgencia(cliente, auth, datos, AUN)
    d = await accion_te(cliente, auth, DES, te["id"], "programar", {"fecha_programada": date.today().isoformat(), "tecnico_ids": [tid]})
    assert (await cliente.post(f"/api/trabajos-especiales/{te['id']}/cotizacion-retroactiva", headers=await auth(AUN), json={"monto": "1500.00"})).status_code == 403
    r = await cliente.post(f"/api/trabajos-especiales/{te['id']}/cotizacion-retroactiva", headers=await auth(MC), json={"monto": "1500.00", "descripcion": "Plomería de urgencia"})
    assert r.status_code == 201, r.text
    cot = r.json()
    assert cot["numero"].startswith("COT-") and cot["trabajo_especial_id"] == te["id"] and cot["estado"] == "en_preparacion" and cot["monto"] == "1500.00" and cot["origen"] == "retroactiva"
    t = await detalle_te(cliente, auth, te["id"], AUN)
    assert t["cotizacion_retroactiva_id"] == cot["id"] and t["cotizacion_retroactiva_numero"] == cot["numero"] and t["monto"] == "1500.00"
    assert (await cliente.post(f"/api/trabajos-especiales/{te['id']}/cotizacion-retroactiva", headers=await auth(MC), json={})).status_code == 409
    # El cierre no depende de la cotización: otro TE de urgencia se cierra sin ella.
    te2 = await _urgencia(cliente, auth, datos, AE)
    d2 = await accion_te(cliente, auth, DES, te2["id"], "programar", {"fecha_programada": date.today().isoformat(), "tecnico_ids": [tid]})
    c = await cerrar_te_completo(cliente, auth, datos, d2, tid)
    assert c["estado"] == "cerrado" and c["cotizacion_retroactiva_id"] is None and c["urgencia"] is True
    _ = d


async def test_minuta_reporte_y_alerta_informativa(cliente, auth, datos):
    from models.trabajos_especiales import TrabajoEspecial
    from workers import tareas

    await formulario_te(cliente, auth)
    tid = await habilitar_te(cliente, auth, TEC, True)
    te = await _urgencia(cliente, auth, datos, AUN)
    d = await accion_te(cliente, auth, DES, te["id"], "programar", {"fecha_programada": date.today().isoformat(), "tecnico_ids": [tid]})
    c = await cerrar_te_completo(cliente, auth, datos, d, tid)
    # Sección «Trabajos especiales» de la minuta (§7.3): nuevo del día y terminado en el día con evidencia y etiqueta de urgencia.
    await configurar_minuta(cliente, auth, datos, modo="automatica")  # el cliente solo lee minutas enviadas
    await limpiar_minutas_hoy(datos["tenant"])
    minutas = await generar_minuta(cliente, auth, datos)
    m = next(x for x in minutas if x["tipo"] == "un" and x["un_id"] == str(datos["unidades"][0]))
    s = (await minuta_detalle(cliente, auth, m["id"], AUN))["secciones"]["trabajos_especiales"]
    nuevo = next(x for x in s["nuevos"] if x["trabajo_especial_id"] == te["id"])
    terminado = next(x for x in s["terminados"] if x["trabajo_especial_id"] == te["id"])
    assert nuevo["urgencia"] is True and terminado["evidencias_cierre"] and terminado["estado"] == "cerrado"
    pdf = await cliente.get(f"/api/minutas/{m['id']}/pdf", headers=await auth(AUN))
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    # Reporte: porcentaje de urgencias y urgencias sin cotización retroactiva.
    r = (await cliente.get("/api/trabajos-especiales/reporte", headers=await auth(AE), params={"desde": date.today().isoformat()})).json()
    assert r["urgencias"] >= 1 and r["porcentaje_urgencias"] > 0 and r["sin_cotizacion_retroactiva"] >= 1
    # Alerta informativa tras X días sin cotización retroactiva.
    await retroceder(TrabajoEspecial, te["id"], fecha_cierre=datetime.now(UTC) - timedelta(days=30), estado_desde=datetime.now(UTC) - timedelta(days=30))
    await tareas.evaluar_alertas_async()
    assert await alertas_disparadas("TE_URGENCIA_SIN_COTIZACION_RETROACTIVA", te["id"])
    _ = c
