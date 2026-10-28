"""Módulo 1 — Cotizaciones (§7.7 M1): ciclo por rol, PDF con hash, envío externo sin cambio de estado, rechazo → Por presupuesto,
conversión 501 (P08), alertas por días, historial inmutable, listados y reporte ejecutivo."""
from datetime import UTC, datetime, timedelta

from tests.folios_utiles import AE, AP, AUN, DES, MC, OP, OTRO_AE, OTRO_AP
from tests.seguimiento_utiles import alertas_disparadas, bandeja, cambiar_estado, crear_registro, detalle_registro, retroceder
from services import correo


async def test_ciclo_completo_por_rol(cliente, auth, datos):
    c = await crear_registro(cliente, auth, "cotizaciones", datos, AUN, descripcion="Cotizar compresor nuevo")
    assert c["estado"] == "solicitada" and c["numero"].startswith("COT-") and c["proxima_alerta"] == "COTIZACION_SIN_PREPARAR" and c["dias_en_estado"] == 0
    assert c["destinos"] == []  # el Admin UN no prepara
    # El cliente no prepara; el prestador sí (en preparación), con descripción y monto.
    assert (await cliente.post(f"/api/seguimiento/cotizaciones/{c['id']}/preparar", headers=await auth(AUN), json={"monto": "100"})).status_code == 403
    r = await cliente.post(f"/api/seguimiento/cotizaciones/{c['id']}/preparar", headers=await auth(DES), json={"descripcion": "Compresor 1/2 HP + instalación", "monto": "7800.00",
                                                                                                             "detalle": {"partidas": [{"descripcion": "Compresor", "cantidad": 1, "importe": "6500"}]}})
    assert r.status_code == 200 and r.json()["estado"] == "en_preparacion" and r.json()["monto"] == "7800.00" and r.json()["proxima_alerta"] == "COTIZACION_SIN_ENVIAR"
    # Enviar: PDF generado, correo al Admin UN y Admin empresa con adjunto, notificación.
    antes = len(correo.ENVIADOS)
    assert (await cliente.post(f"/api/seguimiento/cotizaciones/{c['id']}/responder", headers=await auth(AUN), json={"autorizar": True})).status_code == 409  # aún no enviada
    r = await cliente.post(f"/api/seguimiento/cotizaciones/{c['id']}/enviar", headers=await auth(MC))
    assert r.status_code == 200 and r.json()["estado"] == "enviada" and r.json()["pdf_disponible"] and len(r.json()["hash_pdf"]) == 64 and r.json()["fecha_envio"]
    assert any(c["id"] in (n["datos"].get("cotizacion_id") or "") and n["evento"] == "cotizacion.enviada" for n in await bandeja(cliente, auth, AUN))
    assert any("COT-" in x["asunto"] and x["adjuntos"] for x in correo.ENVIADOS[antes:])
    pdf = await cliente.get(f"/api/seguimiento/cotizaciones/{c['id']}/pdf", headers=await auth(AUN))
    assert pdf.status_code == 200 and pdf.content[:5] == b"%PDF-" and pdf.headers["x-hash-sha256"] == r.json()["hash_pdf"]
    assert (await cliente.get(f"/api/seguimiento/cotizaciones/{c['id']}/pdf", headers=await auth(OTRO_AE))).status_code == 404
    # El prestador no autoriza; el Admin UN sí.
    assert (await cliente.post(f"/api/seguimiento/cotizaciones/{c['id']}/responder", headers=await auth(DES), json={"autorizar": True})).status_code == 403
    r = await cliente.post(f"/api/seguimiento/cotizaciones/{c['id']}/responder", headers=await auth(AUN), json={"autorizar": True, "notas": "Adelante"})
    assert r.status_code == 200 and r.json()["estado"] == "autorizada" and r.json()["notas_respuesta"] == "Adelante" and r.json()["proxima_alerta"] == "COTIZACION_AUTORIZADA_SIN_CONVERTIR"
    assert any(n["evento"] == "cotizacion.respondida" for n in await bandeja(cliente, auth, DES))
    r = await cliente.post(f"/api/seguimiento/cotizaciones/{c['id']}/convertir", headers=await auth(DES))
    assert r.status_code == 501 and r.json()["codigo"] == "DISPONIBLE_EN_P08"
    d = await detalle_registro(cliente, auth, "cotizaciones", c["id"], DES)
    assert [h["estado_nuevo"] for h in d["historial"]] == ["solicitada", "en_preparacion", "enviada", "autorizada"] and d["historial"][1]["usuario_nombre"]
    assert d["estado_trabajo_especial"] is None and d["destinos"] == ["convertida"]


async def test_rechazo_pasa_a_presupuesto_y_envio_externo(cliente, auth, datos):
    c = await crear_registro(cliente, auth, "cotizaciones", datos, AE, descripcion="Cotizar cambio de puerta")
    await cliente.post(f"/api/seguimiento/cotizaciones/{c['id']}/preparar", headers=await auth(AP), json={"descripcion": "Puerta nueva", "monto": "12000"})
    assert (await cliente.post(f"/api/seguimiento/cotizaciones/{c['id']}/enviar-externo", headers=await auth(AE), json={"destinatarios": ["compras@x.mx"]})).status_code == 409
    await cliente.post(f"/api/seguimiento/cotizaciones/{c['id']}/enviar", headers=await auth(AP))
    # Envío externo (licitación): correo con PDF, registro en el historial, el estado no cambia.
    antes = len(correo.ENVIADOS)
    r = await cliente.post(f"/api/seguimiento/cotizaciones/{c['id']}/enviar-externo", headers=await auth(AE), json={"destinatarios": ["compras@clientedemo.mx", "finanzas@clientedemo.mx"], "comentario": "Para licitación interna"})
    assert r.status_code == 200 and r.json()["estado_cotizacion"] == "enviada" and r.json()["estado_entrega"] == "enviada"
    ultimo = correo.ENVIADOS[-1]
    assert len(correo.ENVIADOS) == antes + 1 and ultimo["destinatarios"] == ["compras@clientedemo.mx", "finanzas@clientedemo.mx"] and ultimo["adjuntos"] == [f"{c['numero']}.pdf"]
    assert "Para licitación interna" in ultimo["html"] and c["numero"] in ultimo["asunto"] and "12,000.00" in ultimo["asunto"]
    r = await cliente.post(f"/api/seguimiento/cotizaciones/{c['id']}/enviar-externo", headers=await auth(AE), json={"destinatarios": ["sin-arroba"]})
    assert r.status_code == 422
    d = await detalle_registro(cliente, auth, "cotizaciones", c["id"], AE)
    assert d["estado"] == "enviada" and len(d["envios_externos"]) == 1 and d["envios_externos"][0]["destinatarios"] == ["compras@clientedemo.mx", "finanzas@clientedemo.mx"]
    assert any("compras@clientedemo.mx" in h["notas"] for h in d["historial"])
    # Rechazo con pasar_a_presupuesto → diferido.
    r = await cliente.post(f"/api/seguimiento/cotizaciones/{c['id']}/responder", headers=await auth(AE), json={"autorizar": False, "notas": "No hay presupuesto este trimestre", "pasar_a_presupuesto_si_rechaza": True})
    assert r.status_code == 200 and r.json()["estado"] == "rechazada" and r.json()["pasar_a_presupuesto_si_rechaza"] is True and r.json()["destinos"] == []
    hp_id = r.json()["detalle_json"]["hallazgo_presupuesto_id"]
    hp = await detalle_registro(cliente, auth, "presupuesto", hp_id, AE)
    assert hp["estado"] == "diferido" and hp["origen"] == "cotizacion_rechazada" and hp["monto_estimado"] == "12000.00"
    assert (await cliente.post(f"/api/seguimiento/cotizaciones/{c['id']}/responder", headers=await auth(AE), json={"autorizar": True})).json()["codigo"] == "TRANSICION_NO_PERMITIDA"


async def test_kanban_cambio_estado_y_restricciones(cliente, auth, datos):
    c = await crear_registro(cliente, auth, "cotizaciones", datos, AUN, descripcion="Kanban")
    # Arrastrar a enviada sin monto → 422; con monto en el mismo movimiento → enviada.
    r = await cambiar_estado(cliente, auth, "cotizaciones", c["id"], "enviada", DES, 422)
    assert r["codigo"] == "COTIZACION_INCOMPLETA"
    r = await cambiar_estado(cliente, auth, "cotizaciones", c["id"], "enviada", DES, monto="500", descripcion="Ajuste menor")
    assert r["estado"] == "enviada"
    assert (await cambiar_estado(cliente, auth, "cotizaciones", c["id"], "solicitada", DES, 409))["codigo"] == "TRANSICION_NO_PERMITIDA"
    assert (await cambiar_estado(cliente, auth, "cotizaciones", c["id"], "autorizada", DES, 403))
    assert (await cambiar_estado(cliente, auth, "cotizaciones", c["id"], "inexistente", DES, 422))["codigo"] == "ESTADO_INVALIDO"
    r = await cambiar_estado(cliente, auth, "cotizaciones", c["id"], "rechazada", AE, notas="Muy caro")
    assert r["estado"] == "rechazada"
    # Otro prestador / otro tenant no lo ven; el operador no consulta el módulo.
    assert (await cliente.get(f"/api/seguimiento/cotizaciones/{c['id']}", headers=await auth(OTRO_AP))).status_code == 404
    assert all(x["id"] != c["id"] for x in (await cliente.get("/api/seguimiento/cotizaciones", headers=await auth(OTRO_AE))).json())
    assert (await cliente.get("/api/seguimiento/cotizaciones", headers=await auth(OP))).status_code == 403
    assert (await cliente.get("/api/seguimiento/otro", headers=await auth(DES))).status_code == 404


async def test_historial_inmutable(cliente, auth, datos):
    from sqlalchemy import delete, select, update

    from core.db import nueva_sesion
    from core.rls import CONTEXTO_SISTEMA
    from models.seguimiento import ModuloHistorial

    c = await crear_registro(cliente, auth, "cotizaciones", datos, AUN, descripcion="Historial")
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        h = (await db.execute(select(ModuloHistorial).where(ModuloHistorial.registro_id == c["id"]))).scalars().first()
        assert h is not None and h.estado_nuevo == "solicitada"
        for sentencia in (update(ModuloHistorial).where(ModuloHistorial.id == h.id).values(notas="x"), delete(ModuloHistorial).where(ModuloHistorial.id == h.id)):
            try:
                await db.execute(sentencia)
                raise AssertionError("modulo_historial debe ser append-only")
            except Exception as e:  # noqa: BLE001
                assert "append-only" in str(e) or "solo inserción" in str(e), str(e)
                await db.rollback()


async def test_alertas_por_dias_y_listado(cliente, auth, datos):
    from models.seguimiento import Cotizacion
    from workers import tareas

    c = await crear_registro(cliente, auth, "cotizaciones", datos, AUN, descripcion="Alertas")
    await retroceder(Cotizacion, c["id"], fecha_solicitud=datetime.now(UTC) - timedelta(days=5), estado_desde=datetime.now(UTC) - timedelta(days=5))
    await tareas.evaluar_alertas_async()
    assert len(await alertas_disparadas("COTIZACION_SIN_PREPARAR", c["id"])) == 1
    await tareas.evaluar_alertas_async()
    assert len(await alertas_disparadas("COTIZACION_SIN_PREPARAR", c["id"])) == 1  # no duplica
    lista = (await cliente.get("/api/seguimiento/cotizaciones", headers=await auth(DES), params={"estado": "solicitada"})).json()
    fila = next(x for x in lista if x["id"] == c["id"])
    assert fila["dias_en_estado"] == 5 and "COTIZACION_SIN_PREPARAR" in fila["alertas_activas"] and fila["un_codigo"]
    await cliente.post(f"/api/seguimiento/cotizaciones/{c['id']}/preparar", headers=await auth(DES), json={"descripcion": "x", "monto": "900"})
    await cliente.post(f"/api/seguimiento/cotizaciones/{c['id']}/enviar", headers=await auth(DES))
    await retroceder(Cotizacion, c["id"], fecha_envio=datetime.now(UTC) - timedelta(days=9))
    await tareas.evaluar_alertas_async()
    assert len(await alertas_disparadas("COTIZACION_SIN_RESPUESTA", c["id"])) == 1
    await cliente.post(f"/api/seguimiento/cotizaciones/{c['id']}/responder", headers=await auth(AUN), json={"autorizar": True})
    await retroceder(Cotizacion, c["id"], fecha_respuesta=datetime.now(UTC) - timedelta(days=4))
    await tareas.evaluar_alertas_async()
    assert len(await alertas_disparadas("COTIZACION_AUTORIZADA_SIN_CONVERTIR", c["id"])) == 1


async def test_reporte_ejecutivo_json_excel_pdf(cliente, auth, datos):
    for email, esperado in ((AE, 200), (AP, 200), (DES, 403), (AUN, 403)):
        assert (await cliente.get("/api/seguimiento/reporte/ejecutivo", headers=await auth(email))).status_code == esperado, email
    r = (await cliente.get("/api/seguimiento/reporte/ejecutivo", headers=await auth(AE))).json()
    assert set(r["totales"]) == {"cotizaciones", "por_presupuesto", "seguimiento_interno", "reprogramacion"} and "autorizada" in r["cotizaciones"] and 0 <= r["tasa_conversion_cotizaciones"] <= 100
    assert isinstance(r["hallazgos_recurrentes"], list) and isinstance(r["monto_potencial"], list)
    x = await cliente.get("/api/seguimiento/reporte/ejecutivo.xlsx", headers=await auth(AP))
    assert x.status_code == 200 and x.content[:2] == b"PK" and "spreadsheetml" in x.headers["content-type"]
    p = await cliente.get("/api/seguimiento/reporte/ejecutivo.pdf", headers=await auth(AE))
    assert p.status_code == 200 and p.content[:5] == b"%PDF-"
    por_un = (await cliente.get(f"/api/seguimiento/por-un/{datos['unidades'][0]}", headers=await auth(AUN))).json()
    assert set(por_un) == {"un_id", "cotizaciones", "por_presupuesto", "seguimiento_interno", "reprogramacion"}
