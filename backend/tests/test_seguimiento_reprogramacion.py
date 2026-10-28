"""Módulo 4 — Reprogramación (§7.7 M4): fecha y tercero obligatorios, despachador habilitado, contador de fechas vencidas con
escalado al Admin empresa al llegar a 3, trabajo coordinado A (confirmación del tercero → folio) y B, cierre con justificación y alertas."""
from datetime import UTC, date, datetime, timedelta

from tests.folios_utiles import AE, AP, AUN, DES, OP, detalle
from tests.seguimiento_utiles import alertas_disparadas, bandeja, cambiar_estado, crear_registro, detalle_registro, retroceder


async def test_ciclo_y_fechas_vencidas_con_escalado(cliente, auth, datos):
    from models.seguimiento import Reprogramacion
    from workers import tareas

    r = await crear_registro(cliente, auth, "reprogramacion", datos, AUN, descripcion="Cambio de transformador por CFE", motivo="Requiere corte de energía")
    assert r["estado"] == "pendiente_fecha" and r["motivo"] == "Requiere corte de energía" and r["proxima_alerta"] == "REPROGRAMACION_SIN_FECHA"
    assert (await cambiar_estado(cliente, auth, "reprogramacion", r["id"], "fecha_asignada", AUN, 422))["codigo"] == "FECHA_REQUERIDA"
    await cambiar_estado(cliente, auth, "reprogramacion", r["id"], "fecha_asignada", OP, 403, proveedor="CFE", fecha_acordada=date.today().isoformat())
    # El despachador también registra la fecha (§7.7 M4).
    manana = date.today() + timedelta(days=1)
    r = await cambiar_estado(cliente, auth, "reprogramacion", r["id"], "fecha_asignada", DES, proveedor="CFE", fecha_acordada=manana.isoformat(), referencia_tercero="CFE-77")
    assert r["estado"] == "fecha_asignada" and r["proveedor_tercero"] == "CFE" and r["fechas_vencidas_count"] == 0
    # Fecha próxima sin confirmar → alerta; fecha vencida → contador + alerta inmediata + se exige nueva fecha.
    await tareas.evaluar_alertas_async()
    assert len(await alertas_disparadas("REPROGRAMACION_FECHA_PROXIMA", r["id"])) == 1
    for vencidas in (1, 2, 3):
        await retroceder(Reprogramacion, r["id"], fecha_acordada=date.today() - timedelta(days=1))
        await tareas.evaluar_alertas_async()
        d = await detalle_registro(cliente, auth, "reprogramacion", r["id"], AUN)
        assert d["fechas_vencidas_count"] == vencidas and d["fecha_acordada"] is None and d["estado"] in ("fecha_asignada", "tercero_confirmado")
        assert len(await alertas_disparadas("REPROGRAMACION_FECHA_VENCIDA", r["id"])) == vencidas
        if vencidas < 3:
            assert d["escalada_empresa"] is False
            r2 = await cambiar_estado(cliente, auth, "reprogramacion", r["id"], "tercero_confirmado", AUN, proveedor="CFE", fecha_acordada=(date.today() + timedelta(days=3)).isoformat())
            assert r2["estado"] == "tercero_confirmado"
    assert d["escalada_empresa"] is True and len(await alertas_disparadas("REPROGRAMACION_ESCALADA_EMPRESA", r["id"])) == 1
    assert any(n["evento"] == "seguimiento.escalada" and n["datos"]["registro_id"] == r["id"] for n in await bandeja(cliente, auth, AE))
    assert any("3 de 3" in h["notas"] for h in d["historial"])
    # El Admin empresa asigna nueva fecha (mismas acciones) y se ejecuta y resuelve con justificación.
    r3 = await cambiar_estado(cliente, auth, "reprogramacion", r["id"], "fecha_asignada", AE, proveedor="CFE", fecha_acordada=(date.today() + timedelta(days=2)).isoformat())
    assert r3["estado"] == "fecha_asignada"
    r3 = await cambiar_estado(cliente, auth, "reprogramacion", r["id"], "en_ejecucion", DES)
    assert r3["estado"] == "en_ejecucion" and r3["proxima_alerta"] == "REPROGRAMACION_SIN_CIERRE"
    assert (await cambiar_estado(cliente, auth, "reprogramacion", r["id"], "resuelto", AUN, 422))["codigo"] == "JUSTIFICACION_REQUERIDA"
    r3 = await cambiar_estado(cliente, auth, "reprogramacion", r["id"], "resuelto", DES, notas="CFE cambió el transformador y el técnico reconectó")
    assert r3["estado"] == "resuelto" and r3["fecha_resolucion"] and r3["justificacion_cierre"].startswith("CFE") and r3["destinos"] == []
    assert (await cambiar_estado(cliente, auth, "reprogramacion", r["id"], "cancelado", AE, 409, notas="x"))["codigo"] == "TRANSICION_NO_PERMITIDA"


async def test_alertas_sin_fecha_y_sin_cierre(cliente, auth, datos):
    from models.seguimiento import Reprogramacion
    from workers import tareas

    r = await crear_registro(cliente, auth, "reprogramacion", datos, AUN, descripcion="Sin fecha")
    await retroceder(Reprogramacion, r["id"], estado_desde=datetime.now(UTC) - timedelta(days=8))
    await tareas.evaluar_alertas_async()
    assert len(await alertas_disparadas("REPROGRAMACION_SIN_FECHA", r["id"])) == 1
    s = await crear_registro(cliente, auth, "reprogramacion", datos, AUN, descripcion="En ejecución eterna", fecha_tentativa=date.today().isoformat())
    assert s["estado"] == "fecha_asignada"
    await cambiar_estado(cliente, auth, "reprogramacion", s["id"], "en_ejecucion", AUN)
    await retroceder(Reprogramacion, s["id"], estado_desde=datetime.now(UTC) - timedelta(days=16))
    await tareas.evaluar_alertas_async()
    assert len(await alertas_disparadas("REPROGRAMACION_SIN_CIERRE", s["id"])) == 1
    # Cancelación por el Admin UN con razón; el despachador no cancela.
    assert (await cambiar_estado(cliente, auth, "reprogramacion", s["id"], "cancelado", DES, 403, notas="no"))
    assert (await cambiar_estado(cliente, auth, "reprogramacion", s["id"], "cancelado", AUN, notas="El tercero ya no atenderá la sucursal"))["estado"] == "cancelado"


async def test_trabajo_coordinado_variantes_a_y_b(cliente, auth, datos):
    # Variante A: el tercero habilita y el técnico ejecuta → el técnico no entra hasta que el Admin UN o el Despachador confirman.
    a = await crear_registro(cliente, auth, "reprogramacion", datos, AUN, descripcion="CFE desenergiza y el técnico cambia el tablero", trabajo_coordinado=True, variante="A",
                             proveedor="CFE", fecha_tentativa=(date.today() + timedelta(days=2)).isoformat())
    assert a["trabajo_coordinado"] and a["variante"] == "A" and a["estado"] == "fecha_asignada" and a["tercero_completo"] is False
    r = await cambiar_estado(cliente, auth, "reprogramacion", a["id"], "en_ejecucion", AUN, 409)
    assert r["codigo"] == "TERCERO_PENDIENTE"
    assert (await cliente.post(f"/api/seguimiento/reprogramacion/{a['id']}/confirmar-tercero", headers=await auth(OP), json={"notas": "x"})).status_code == 403
    r = await cliente.post(f"/api/seguimiento/reprogramacion/{a['id']}/confirmar-tercero", headers=await auth(DES), json={"notas": "CFE desenergizó la línea a las 9:00"})
    assert r.status_code == 200, r.text
    assert r.json()["tercero_completo"] is True and r.json()["estado"] == "en_ejecucion" and r.json()["folio"]["estado"] == "autorizado" and r.json()["folio_coordinado_id"]
    f = await detalle(cliente, auth, r.json()["folio"]["id"])
    assert f["folio"]["tipo_folio"] == "correctivo" and "variante A" in f["folio"]["descripcion"] and f["historial"][0]["datos_contexto_json"]["reprogramacion_id"] == a["id"]
    assert (await cliente.post(f"/api/seguimiento/reprogramacion/{a['id']}/confirmar-tercero", headers=await auth(DES), json={})).json()["codigo"] == "TERCERO_YA_CONFIRMADO"
    # Variante B: el técnico ejecuta y el tercero certifica en el acto; no requiere confirmación.
    b = await crear_registro(cliente, auth, "reprogramacion", datos, AUN, descripcion="UVA certifica la instalación", trabajo_coordinado=True, variante="B",
                             proveedor="UVA Norte", fecha_tentativa=date.today().isoformat())
    assert (await cambiar_estado(cliente, auth, "reprogramacion", b["id"], "en_ejecucion", AUN))["estado"] == "en_ejecucion"
    assert (await cliente.post(f"/api/seguimiento/reprogramacion/{b['id']}/confirmar-tercero", headers=await auth(DES), json={})).json()["codigo"] == "NO_APLICA"
    # Coordinado sin variante → 422.
    r = await cliente.post("/api/seguimiento/reprogramacion", headers=await auth(AUN), json={"un_id": str(datos["unidades"][0]), "descripcion": "Sin variante", "trabajo_coordinado": True})
    assert r.status_code == 422 and r.json()["codigo"] == "VARIANTE_REQUERIDA"
    assert (await cliente.get("/api/seguimiento/reprogramacion", headers=await auth(AP), params={"estado": "en_ejecucion"})).status_code == 200
