"""Órdenes de compra (§6.4 Tipo B): ciclo completo desde el folio en `pendiente_refaccion` hasta reabrirlo en ejecución,
evento ERP al aprobar, recepción parcial, cancelación con razón, alertas por días y aislamiento."""
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from models.inventario import OrdenCompra
from tests.folios_utiles import AE, AP, AUN, DES, MC, OP, OTRO_AE, OTRO_AP, TEC, accion, detalle, tecnico_con_habilidades
from tests.inventario_utiles import alertas_disparadas, almacen_demo, articulo, bandeja, entrada, existencia, retroceder


async def _folio_pendiente_refaccion(cliente, auth, datos):
    from tests.test_cierre_folio import _en_ejecucion

    f = await _en_ejecucion(cliente, auth, datos)
    await accion(cliente, auth, TEC, f["id"], "pendiente-refaccion", {"notas": "Falta el compresor"})
    return f


async def test_ciclo_completo_de_la_orden_de_compra(cliente, auth, datos):
    a = await articulo(cliente, auth, costo="6800.00", minimo="1")
    alm = await almacen_demo(cliente, auth)
    f = await _folio_pendiente_refaccion(cliente, auth, datos)
    assert (await cliente.post("/api/inventario/ordenes-compra", headers=await auth(OP),
                               json={"proveedor": "Proveedor", "partidas": [{"articulo_id": a["id"], "cantidad": "1"}]})).status_code == 403
    assert (await cliente.post("/api/inventario/ordenes-compra", headers=await auth(DES),
                               json={"proveedor": "Proveedor", "partidas": []})).status_code == 422
    r = await cliente.post("/api/inventario/ordenes-compra", headers=await auth(DES),
                           json={"proveedor": "Refacciones del Norte", "folio_id": f["id"], "notas": "Compresor del folio",
                                 "partidas": [{"articulo_id": a["id"], "cantidad": "2", "costo_unitario": "6500.00"}]})
    assert r.status_code == 201, r.text
    oc = r.json()
    assert oc["numero"].startswith("OC-") and oc["estado"] == "borrador" and Decimal(oc["total"]) == 13000 and oc["numero_folio"] == f["numero_folio"]
    assert len(oc["partidas"]) == 1 and oc["partidas"][0]["codigo"] == a["codigo"]
    assert any(n["evento"] == "oc.creada" and n["datos"]["numero"] == oc["numero"] for n in await bandeja(cliente, auth, AP, solo_no_leidas=True))
    # Aprobación: solo Admin prestador; genera el evento ERP generar_oc.
    assert (await cliente.post(f"/api/inventario/ordenes-compra/{oc['id']}/aprobar", headers=await auth(DES))).status_code == 403
    r = await cliente.post(f"/api/inventario/ordenes-compra/{oc['id']}/aprobar", headers=await auth(AP))
    assert r.status_code == 200 and r.json()["estado"] == "aprobada" and r.json()["aprobada_por"] and r.json()["aprobada_at"]
    eventos = (await cliente.get("/api/erp/eventos", headers=await auth(AP), params={"limite": 200})).json()
    mio = next(e for e in eventos if e["operacion"] == "generar_oc" and e["entidad_id"] == oc["id"])
    assert mio["estado"] == "pendiente" and mio["payload_json"]["numero"] == oc["numero"] and len(mio["payload_json"]["partidas"]) == 1
    assert (await cliente.post(f"/api/inventario/ordenes-compra/{oc['id']}/aprobar", headers=await auth(AP))).status_code == 409
    # Recepción: entra al almacén con el costo de la partida y el folio puede reanudarse.
    r = await cliente.post(f"/api/inventario/ordenes-compra/{oc['id']}/recibir", headers=await auth(DES), json={"recibidas": {}})
    assert r.status_code == 200 and r.json()["estado"] == "recibida" and Decimal(r.json()["partidas"][0]["recibido"]) == 2
    e = await existencia(cliente, auth, alm["id"], a["id"])
    assert Decimal(e["cantidad"]) == 2 and Decimal(e["costo_promedio"]) == 6500
    assert any(n["evento"] == "oc.recibida" and n["datos"]["folio_id"] == f["id"] for n in await bandeja(cliente, auth, DES))
    # El folio vuelve a ejecución y consume la refacción recibida.
    await accion(cliente, auth, DES, f["id"], "reanudar")
    d = await detalle(cliente, auth, f["id"])
    assert d["folio"]["estado"] == "en_ejecucion"
    r = await cliente.post(f"/api/folios/{f['id']}/refacciones", headers=await auth(TEC),
                           json={"descripcion": a["descripcion"], "cantidad": "1", "origen": "oc", "articulo_id": a["id"], "ubicacion_id": alm["id"]})
    assert r.status_code == 201 and Decimal(r.json()["costo_unitario"]) == 6500
    assert Decimal((await existencia(cliente, auth, alm["id"], a["id"]))["cantidad"]) == 1
    # El cliente ve la OC de su folio; otro tenant no.
    assert any(x["id"] == oc["id"] for x in (await cliente.get("/api/inventario/ordenes-compra", headers=await auth(AE))).json())
    assert all(x["id"] != oc["id"] for x in (await cliente.get("/api/inventario/ordenes-compra", headers=await auth(OTRO_AE))).json())
    assert (await cliente.get(f"/api/inventario/ordenes-compra/{oc['id']}", headers=await auth(OTRO_AP))).status_code == 404


async def test_recepcion_parcial_y_cancelacion(cliente, auth, datos):
    a = await articulo(cliente, auth, costo="300.00")
    alm = await almacen_demo(cliente, auth)
    r = await cliente.post("/api/inventario/ordenes-compra", headers=await auth(MC),
                           json={"proveedor": "Proveedor parcial", "partidas": [{"articulo_id": a["id"], "cantidad": "10", "costo_unitario": "300.00"}]})
    oc = r.json()
    await cliente.post(f"/api/inventario/ordenes-compra/{oc['id']}/aprobar", headers=await auth(AP))
    r = await cliente.post(f"/api/inventario/ordenes-compra/{oc['id']}/recibir", headers=await auth(AP), json={"recibidas": {a["id"]: "4"}})
    assert r.status_code == 200 and Decimal(r.json()["partidas"][0]["recibido"]) == 4
    assert Decimal((await existencia(cliente, auth, alm["id"], a["id"]))["cantidad"]) == 4
    assert (await cliente.post(f"/api/inventario/ordenes-compra/{oc['id']}/recibir", headers=await auth(AP), json={"recibidas": {}})).status_code == 409
    # Cancelación con razón obligatoria sobre una orden en borrador.
    r2 = await cliente.post("/api/inventario/ordenes-compra", headers=await auth(DES),
                            json={"proveedor": "Para cancelar", "partidas": [{"articulo_id": a["id"], "cantidad": "1"}]})
    oc2 = r2.json()
    assert (await cliente.post(f"/api/inventario/ordenes-compra/{oc2['id']}/cancelar", headers=await auth(DES), json={"razon": ""})).status_code == 422
    r3 = await cliente.post(f"/api/inventario/ordenes-compra/{oc2['id']}/cancelar", headers=await auth(DES), json={"razon": "El cliente consiguió la pieza"})
    assert r3.status_code == 200 and r3.json()["estado"] == "cancelada" and r3.json()["razon_cancelacion"]
    assert (await cliente.post(f"/api/inventario/ordenes-compra/{oc['id']}/cancelar", headers=await auth(AP), json={"razon": "ya recibida"})).status_code == 409


async def test_alertas_de_ordenes_de_compra(cliente, auth, datos):
    from workers import tareas

    a = await articulo(cliente, auth, costo="500.00")
    borrador = (await cliente.post("/api/inventario/ordenes-compra", headers=await auth(DES),
                                   json={"proveedor": "Sin aprobar", "partidas": [{"articulo_id": a["id"], "cantidad": "1"}]})).json()
    aprobada = (await cliente.post("/api/inventario/ordenes-compra", headers=await auth(DES),
                                   json={"proveedor": "Sin recibir", "partidas": [{"articulo_id": a["id"], "cantidad": "1"}]})).json()
    await cliente.post(f"/api/inventario/ordenes-compra/{aprobada['id']}/aprobar", headers=await auth(AP))
    hace = datetime.now(UTC) - timedelta(days=30)
    await retroceder(OrdenCompra, borrador["id"], estado_desde=hace)
    await retroceder(OrdenCompra, aprobada["id"], estado_desde=hace)
    await tareas.evaluar_alertas_async()
    assert await alertas_disparadas("OC_SIN_APROBAR", borrador["id"])
    assert await alertas_disparadas("OC_SIN_RECIBIR", aprobada["id"])
