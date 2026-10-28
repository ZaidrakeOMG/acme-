"""Módulo 3 — Seguimiento interno (§7.7 M3): transiciones por rol, proveedor + fecha obligatorios en `con_proveedor`, justificación
obligatoria en resuelto y cancelado, novedades, alertas de inactividad (15 días) y fecha acordada vencida."""
from datetime import UTC, date, datetime, timedelta

from tests.folios_utiles import AE, AP, AUN, DES, OP, OTRO_AE
from tests.seguimiento_utiles import alertas_disparadas, cambiar_estado, crear_registro, detalle_registro, retroceder


async def test_transiciones_campos_y_justificacion(cliente, auth, datos):
    s = await crear_registro(cliente, auth, "interno", datos, AUN, descripcion="Garantía del fabricante del compresor")
    assert s["estado"] == "registrado" and s["responsable_un"] and set(s["destinos"]) == {"en_gestion", "con_proveedor", "resuelto", "cancelado"}
    # El prestador no gestiona el seguimiento del cliente; el operador tampoco.
    await cambiar_estado(cliente, auth, "interno", s["id"], "en_gestion", DES, 403)
    await cambiar_estado(cliente, auth, "interno", s["id"], "en_gestion", OP, 403)
    r = await cambiar_estado(cliente, auth, "interno", s["id"], "en_gestion", AUN, notas="Llamé al fabricante")
    assert r["estado"] == "en_gestion" and r["proxima_alerta"] == "SEGUIMIENTO_SIN_UPDATE"
    # Con proveedor: nombre y fecha obligatorios; referencia opcional.
    r = await cambiar_estado(cliente, auth, "interno", s["id"], "con_proveedor", AUN, 422, notas="x")
    assert r["codigo"] == "PROVEEDOR_REQUERIDO"
    fecha = (date.today() + timedelta(days=7)).isoformat()
    r = await cambiar_estado(cliente, auth, "interno", s["id"], "con_proveedor", AE, proveedor="Servicio Técnico Torrey", fecha_acordada=fecha, referencia_tercero="GAR-5521")
    assert r["estado"] == "con_proveedor" and r["proveedor"] == "Servicio Técnico Torrey" and r["fecha_acordada"] == fecha and r["referencia_tercero"] == "GAR-5521"
    # Novedad sin cambiar de estado.
    r = await cliente.post(f"/api/seguimiento/interno/{s['id']}/actualizar", headers=await auth(AUN), json={"notas": "El técnico del fabricante confirmó la visita"})
    assert r.status_code == 200
    assert (await cliente.post(f"/api/seguimiento/interno/{s['id']}/actualizar", headers=await auth(AUN), json={"notas": "x"})).status_code == 422
    # Resuelto exige justificación escrita; cancelado también; después son finales.
    r = await cambiar_estado(cliente, auth, "interno", s["id"], "resuelto", AUN, 422)
    assert r["codigo"] == "JUSTIFICACION_REQUERIDA"
    r = await cambiar_estado(cliente, auth, "interno", s["id"], "resuelto", AUN, notas="El fabricante cambió el compresor bajo garantía")
    assert r["estado"] == "resuelto" and r["justificacion_cierre"].startswith("El fabricante") and r["cerrado_por"] and r["cerrado_at"] and r["proxima_alerta"] is None and r["destinos"] == []
    assert (await cambiar_estado(cliente, auth, "interno", s["id"], "cancelado", AUN, 409, notas="ya no"))["codigo"] == "TRANSICION_NO_PERMITIDA"
    d = await detalle_registro(cliente, auth, "interno", s["id"], AUN)
    assert [h["estado_nuevo"] for h in d["historial"]] == ["registrado", "en_gestion", "con_proveedor", "con_proveedor", "resuelto"]
    assert d["historial"][2]["datos_json"]["proveedor"] == "Servicio Técnico Torrey" and d["historial"][2]["datos_json"]["referencia_tercero"] == "GAR-5521"
    t = await crear_registro(cliente, auth, "interno", datos, AE, descripcion="Cancelación")
    assert (await cambiar_estado(cliente, auth, "interno", t["id"], "cancelado", AE, 422))["codigo"] == "JUSTIFICACION_REQUERIDA"
    assert (await cambiar_estado(cliente, auth, "interno", t["id"], "cancelado", AE, notas="El equipo se dará de baja"))["estado"] == "cancelado"
    # El prestador consulta (visibilidad) pero no edita; otro tenant no ve.
    assert (await cliente.get(f"/api/seguimiento/interno/{s['id']}", headers=await auth(DES))).status_code == 200
    assert (await cliente.get(f"/api/seguimiento/interno/{s['id']}", headers=await auth(OTRO_AE))).status_code == 404


async def test_alertas_inactividad_y_fecha_vencida(cliente, auth, datos):
    from models.seguimiento import SeguimientoInterno
    from workers import tareas

    s = await crear_registro(cliente, auth, "interno", datos, AUN, descripcion="Sin novedades")
    await retroceder(SeguimientoInterno, s["id"], ultima_actualizacion=datetime.now(UTC) - timedelta(days=16))
    await tareas.evaluar_alertas_async()
    assert len(await alertas_disparadas("SEGUIMIENTO_SIN_UPDATE", s["id"])) == 1
    fila = next(x for x in (await cliente.get("/api/seguimiento/interno", headers=await auth(AP))).json() if x["id"] == s["id"])
    assert "SEGUIMIENTO_SIN_UPDATE" in fila["alertas_activas"]
    t = await crear_registro(cliente, auth, "interno", datos, AUN, descripcion="Proveedor que no llegó")
    await cambiar_estado(cliente, auth, "interno", t["id"], "con_proveedor", AUN, proveedor="Plomería X", fecha_acordada=(date.today() + timedelta(days=1)).isoformat())
    await retroceder(SeguimientoInterno, t["id"], fecha_acordada=date.today() - timedelta(days=2))
    await tareas.evaluar_alertas_async()
    assert len(await alertas_disparadas("SEGUIMIENTO_INTERNO_FECHA_VENCIDA", t["id"])) == 1
    assert len(await alertas_disparadas("SEGUIMIENTO_INTERNO_FECHA_VENCIDA", s["id"])) == 0
