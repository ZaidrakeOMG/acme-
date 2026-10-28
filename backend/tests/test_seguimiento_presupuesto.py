"""Módulo 2 — Por presupuesto (§7.7 M2): diferido nunca cambia solo; reactivar (folio directo o cotización) o descartar con razón;
revisión, recordatorio por período, alerta de 30 días, monto potencial para el prestador y derivación desde el rechazo §6.8.7."""
from datetime import UTC, datetime, timedelta

from tests.folios_utiles import AE, AP, AUN, DES, OP, OTRO_AE, SUPO, capturar, detalle
from tests.seguimiento_utiles import alertas_disparadas, cambiar_estado, crear_registro, detalle_registro, retroceder


async def test_reactivar_descartar_y_revisar(cliente, auth, datos):
    a = await crear_registro(cliente, auth, "presupuesto", datos, AUN, descripcion="Cambio de piso del cuarto frío")
    assert a["estado"] == "diferido" and a["periodo_presupuestal"] and a["proxima_alerta"] == "PRESUPUESTO_SIN_REVISION" and set(a["destinos"]) == {"reactivado", "descartado"}
    # Descartar sin razón → 422; el despachador no decide.
    r = await cliente.post(f"/api/seguimiento/presupuesto/{a['id']}/descartar", headers=await auth(AUN), json={"notas": ""})
    assert r.status_code == 422 and r.json()["codigo"] == "JUSTIFICACION_REQUERIDA"
    assert (await cliente.post(f"/api/seguimiento/presupuesto/{a['id']}/descartar", headers=await auth(DES), json={"notas": "No procede"})).status_code == 403
    r = await cliente.post(f"/api/seguimiento/presupuesto/{a['id']}/revisar", headers=await auth(AUN), json={"notas": "Se revisó; sigue sin presupuesto"})
    assert r.status_code == 200 and r.json()["estado"] == "diferido" and len(r.json()["historial_revisiones_json"]) == 2
    # Reactivar como folio directo: correctivo autorizado.
    r = await cliente.post(f"/api/seguimiento/presupuesto/{a['id']}/reactivar", headers=await auth(AE), json={"como": "folio", "notas": "Hay presupuesto"})
    assert r.status_code == 200 and r.json()["estado"] == "reactivado" and r.json()["reactivado_como"] == "folio" and r.json()["registro"]["numero"].startswith("CD-")
    f = await detalle(cliente, auth, r.json()["registro"]["id"])
    assert f["folio"]["estado"] == "autorizado" and f["folio"]["descripcion"].startswith("Cambio de piso")
    assert (await cliente.post(f"/api/seguimiento/presupuesto/{a['id']}/descartar", headers=await auth(AUN), json={"notas": "ya reactivado"})).json()["codigo"] == "ESTADO_FINAL"
    # Reactivar como cotización.
    b = await crear_registro(cliente, auth, "presupuesto", datos, AUN, descripcion="Pintura de la fachada")
    r = await cliente.post(f"/api/seguimiento/presupuesto/{b['id']}/reactivar", headers=await auth(AUN), json={"como": "cotizacion"})
    assert r.status_code == 200 and r.json()["registro"]["numero"].startswith("COT-")
    cot = await detalle_registro(cliente, auth, "cotizaciones", r.json()["registro"]["id"], DES)
    assert cot["estado"] == "solicitada" and cot["origen"] == "presupuesto_reactivado"
    # Descartar definitivamente con razón: historial de solo lectura.
    c = await crear_registro(cliente, auth, "presupuesto", datos, AUN, descripcion="Cambio de mobiliario")
    r = await cliente.post(f"/api/seguimiento/presupuesto/{c['id']}/descartar", headers=await auth(AE), json={"notas": "La sucursal cierra el próximo año"})
    assert r.status_code == 200 and r.json()["estado"] == "descartado" and r.json()["razon_descarte"].startswith("La sucursal") and r.json()["decidido_por"]
    d = await detalle_registro(cliente, auth, "presupuesto", c["id"], AUN)
    assert [h["estado_nuevo"] for h in d["historial"]] == ["diferido", "descartado"] and d["historial"][-1]["notas"].startswith("La sucursal")
    # Kanban: diferido no admite otros destinos.
    assert (await cambiar_estado(cliente, auth, "presupuesto", b["id"], "diferido", AUN, 409))["codigo"] == "TRANSICION_NO_PERMITIDA"


async def test_alerta_sin_revision_y_monto_potencial(cliente, auth, datos):
    from models.seguimiento import HallazgoPresupuesto
    from workers import tareas

    a = await crear_registro(cliente, auth, "presupuesto", datos, AUN, descripcion="Equipo de respaldo")
    await retroceder(HallazgoPresupuesto, a["id"], ultima_revision=datetime.now(UTC) - timedelta(days=31), monto_estimado=4500)
    await tareas.evaluar_alertas_async()
    assert len(await alertas_disparadas("PRESUPUESTO_SIN_REVISION", a["id"])) == 1
    monto = (await cliente.get("/api/seguimiento/presupuesto/monto-potencial", headers=await auth(AP))).json()
    fila = next(x for x in monto if x["un_id"] == str(datos["unidades"][0]))
    assert fila["diferidos"] >= 1 and float(fila["monto_potencial"]) >= 4500 and fila["un_codigo"]
    assert (await cliente.get("/api/seguimiento/presupuesto/monto-potencial", headers=await auth(AUN))).status_code == 403
    assert all(x["id"] != a["id"] for x in (await cliente.get("/api/seguimiento/presupuesto", headers=await auth(OTRO_AE))).json())


async def test_periodo_presupuestal(cliente, auth, datos):
    from services.seguimiento import presupuesto
    from datetime import date

    assert presupuesto.periodo_actual(presupuesto.TipoPeriodoPresupuestal.mensual, None, date(2026, 3, 15)) == "2026-03"
    assert presupuesto.periodo_actual(presupuesto.TipoPeriodoPresupuestal.semestral, None, date(2026, 8, 1)) == "2026-S2"
    assert presupuesto.periodo_actual(presupuesto.TipoPeriodoPresupuestal.anual, None, date(2026, 8, 1)) == "2026"
    assert presupuesto.periodo_actual(presupuesto.TipoPeriodoPresupuestal.fechas, ["2026-02-01", "2026-09-15"], date(2026, 10, 1)) == "2026-09-15"
    assert presupuesto.inicio_de_periodo(presupuesto.TipoPeriodoPresupuestal.semestral, None, date(2026, 7, 1)) and not presupuesto.inicio_de_periodo(presupuesto.TipoPeriodoPresupuestal.anual, None, date(2026, 7, 1))
    r = await cliente.put("/api/seguimiento/periodos-presupuestales", headers=await auth(AE), json={"tipo": "semestral"})
    assert r.status_code == 200 and r.json()["tipo"] == "semestral" and r.json()["periodo_actual"].endswith(("S1", "S2"))
    assert (await cliente.put("/api/seguimiento/periodos-presupuestales", headers=await auth(AUN), json={"tipo": "anual"})).status_code == 403
    assert (await cliente.get("/api/seguimiento/periodos-presupuestales", headers=await auth(DES), params={"tenant_id": str(datos["tenant"])})).json()["tipo"] == "semestral"
    await cliente.put("/api/seguimiento/periodos-presupuestales", headers=await auth(AE), json={"tipo": "trimestral"})


async def test_rechazo_multinivel_deriva_al_modulo(cliente, auth, datos):
    """§6.8.7: rechazar «por presupuesto» crea el diferido y completa aprobacion_decisiones.modulo_destino_id."""
    f = await capturar(cliente, auth, datos, OP)  # en revisión con flujo Nivel 1
    r = await cliente.post(f"/api/folios/{f['id']}/aprobacion/rechazar", headers=await auth(AUN), json={"canal": "app", "razon_rechazo": "por_presupuesto", "notas": "Sin presupuesto"})
    assert r.status_code == 200, r.text
    d = await detalle(cliente, auth, f["id"])
    assert d["folio"]["estado"] == "cancelado" and d["decisiones"][-1]["modulo_destino"] == "por_presupuesto" and d["decisiones"][-1]["modulo_destino_id"]
    assert d["derivaciones"] and d["derivaciones"][0]["modulo"] == "por_presupuesto" and d["derivaciones"][0]["origen"] == "aprobacion_rechazada"
    assert any(h["evento"] == "folio.derivado_a_modulo" and h["datos_contexto_json"].get("procesado_por_p07") for h in d["historial"])
    hp = await detalle_registro(cliente, auth, "presupuesto", d["decisiones"][-1]["modulo_destino_id"], AUN)
    assert hp["estado"] == "diferido" and hp["folio_id"] == f["id"] and hp["numero_folio"] == f["numero_folio"]
    # Las demás razones: cotización, seguimiento interno y reprogramación.
    for razon, modulo, ruta in (("requiere_cotizacion", "cotizaciones", "cotizaciones"), ("seguimiento_interno", "seguimiento_interno", "interno"), ("reprogramar", "reprogramacion", "reprogramacion")):
        g = await capturar(cliente, auth, datos, OP)
        assert (await cliente.post(f"/api/folios/{g['id']}/aprobacion/rechazar", headers=await auth(AUN), json={"canal": "app", "razon_rechazo": razon})).status_code == 200
        dg = await detalle(cliente, auth, g["id"])
        assert dg["derivaciones"][0]["modulo"] == modulo and dg["decisiones"][-1]["modulo_destino_id"] == str(dg["derivaciones"][0]["registro_id"])
        assert (await cliente.get(f"/api/seguimiento/{ruta}/{dg['derivaciones'][0]['registro_id']}", headers=await auth(AUN))).status_code == 200
    assert (await cliente.get("/api/seguimiento/presupuesto", headers=await auth(SUPO))).status_code == 200
