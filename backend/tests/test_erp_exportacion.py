"""Capa desacoplada de ERP (§6.6): los cuatro eventos, adaptadores stub que dejan el evento en `omitido`, configuración de
columnas y cuentas, exportación universal por período en XML de pólizas y Excel configurable, y aislamiento."""
import io
from datetime import date, timedelta
from decimal import Decimal

from openpyxl import load_workbook

from tests.folios_utiles import AE, AP, DES, MC, OP, OTRO_AP, TEC
from tests.inventario_utiles import almacen_demo, articulo, cerrar_folio, costos_de, entrada, folio_en_ejecucion, refaccion, tarifa, validar_costo


async def test_configuracion_y_adaptadores_stub(cliente, auth, datos):
    r = await cliente.get("/api/erp/configuracion", headers=await auth(AP))
    assert r.status_code == 200, r.text
    c = r.json()
    assert c["adaptador"] == "ninguno" and c["columnas_excel_json"] and len(c["adaptadores_disponibles"]) == 3
    assert {a["clave"] for a in c["adaptadores_disponibles"]} == {"ninguno", "contpaqi", "microsip"}
    assert [a["fase"] for a in c["adaptadores_disponibles"] if a["clave"] != "ninguno"] == [2, 2]
    assert (await cliente.put("/api/erp/configuracion", headers=await auth(DES), json={"adaptador": "contpaqi"})).status_code == 403
    assert (await cliente.get("/api/erp/configuracion", headers=await auth(AE))).status_code == 403
    r = await cliente.put("/api/erp/configuracion", headers=await auth(AP),
                          json={"columnas_excel_json": ["fecha", "referencia", "concepto", "total"],
                                "cuentas_contables_json": {"registrar_gasto": "5101-001"}, "centros_costos_json": {"registrar_gasto": "MANTENIMIENTO"}})
    assert r.status_code == 200 and r.json()["columnas_excel_json"] == ["fecha", "referencia", "concepto", "total"]
    # Con adaptador configurado, el stub de Fase 2 deja el evento en `omitido` con su motivo.
    await cliente.put("/api/erp/configuracion", headers=await auth(AP), json={"adaptador": "contpaqi"})
    a = await articulo(cliente, auth, costo="400.00")
    oc = (await cliente.post("/api/inventario/ordenes-compra", headers=await auth(DES),
                             json={"proveedor": "Proveedor stub", "partidas": [{"articulo_id": a["id"], "cantidad": "1"}]})).json()
    await cliente.post(f"/api/inventario/ordenes-compra/{oc['id']}/aprobar", headers=await auth(AP))
    eventos = (await cliente.get("/api/erp/eventos", headers=await auth(AP), params={"limite": 200})).json()
    evento = next(e for e in eventos if e["entidad_id"] == oc["id"])
    assert evento["estado"] == "omitido" and evento["adaptador"] == "contpaqi" and "Fase 2" in evento["respuesta_json"]["detalle"]
    assert evento["intentos"] == 1 and evento["procesado_at"]
    await cliente.put("/api/erp/configuracion", headers=await auth(AP), json={"adaptador": "ninguno"})


async def test_las_cuatro_operaciones_generan_evento(cliente, auth, datos):
    """OC aprobada, costo de folio validado, equipo nuevo instalado (P08) y póliza de caja chica."""
    await cliente.put("/api/erp/configuracion", headers=await auth(AP), json={"adaptador": "ninguno"})
    await tarifa(cliente, auth, "300.00")
    f = await folio_en_ejecucion(cliente, auth, datos)
    await refaccion(cliente, auth, f["id"], descripcion="Refacción ERP", cantidad="1", costo="700.00")
    await cerrar_folio(cliente, auth, datos, f)
    await validar_costo(cliente, auth, f["id"], centro_costos="MANTENIMIENTO")
    eventos = (await cliente.get("/api/erp/eventos", headers=await auth(AP), params={"limite": 300})).json()
    gasto = next(e for e in eventos if e["operacion"] == "registrar_gasto" and e["payload_json"].get("numero_folio") == f["numero_folio"])
    assert gasto["estado"] == "pendiente" and Decimal(str(gasto["payload_json"]["total"])) > 0 and gasto["entidad"] == "folio_costo"
    # El seed de P09 dejó las otras tres operaciones.
    operaciones = {e["operacion"] for e in eventos}
    assert {"generar_oc", "registrar_gasto", "crear_activo_fijo", "poliza_caja_chica"} <= operaciones
    # Procesar a mano con el adaptador «ninguno» deja el evento pendiente para la exportación universal.
    r = await cliente.post(f"/api/erp/eventos/{gasto['id']}/procesar", headers=await auth(AP))
    assert r.status_code == 200 and r.json()["estado"] == "pendiente" and "Sin adaptador" in r.json()["respuesta_json"]["detalle"]
    assert (await cliente.post(f"/api/erp/eventos/{gasto['id']}/procesar", headers=await auth(DES))).status_code == 403


async def test_exportacion_universal_xml_y_excel(cliente, auth, datos):
    await cliente.put("/api/erp/configuracion", headers=await auth(AP),
                      json={"adaptador": "ninguno", "columnas_excel_json": ["fecha", "tipo", "referencia", "concepto", "centro_costos",
                                                                             "cuenta_contable", "total", "moneda"],
                            "cuentas_contables_json": {"registrar_gasto": "5101-001", "generar_oc": "2101-001"}})
    hoy = date.today()
    desde, hasta = hoy - timedelta(days=30), hoy
    assert (await cliente.post("/api/erp/exportaciones", headers=await auth(DES), json={"desde": desde.isoformat(), "hasta": hasta.isoformat()})).status_code == 403
    assert (await cliente.post("/api/erp/exportaciones", headers=await auth(AP),
                               json={"desde": hasta.isoformat(), "hasta": desde.isoformat()})).status_code == 422
    pendientes = [e for e in (await cliente.get("/api/erp/eventos", headers=await auth(AP), params={"estado": "pendiente", "limite": 300})).json()
                  if e["exportacion_id"] is None]
    r = await cliente.post("/api/erp/exportaciones", headers=await auth(AP), json={"desde": desde.isoformat(), "hasta": hasta.isoformat()})
    assert r.status_code == 201, r.text
    exp = r.json()
    assert exp["eventos_incluidos"] >= len(pendientes) and exp["archivo_disponible"] and exp["xml_disponible"]
    # Excel con las columnas configuradas.
    x = await cliente.get(f"/api/erp/exportaciones/{exp['id']}/archivo", headers=await auth(AP), params={"formato": "xlsx"})
    assert x.status_code == 200
    ws = load_workbook(io.BytesIO(x.content)).active
    assert [c.value for c in ws[3]] == ["Fecha", "Tipo", "Referencia", "Concepto", "Centro costos", "Cuenta contable", "Total", "Moneda"]
    # XML con estructura de pólizas contables.
    xml = await cliente.get(f"/api/erp/exportaciones/{exp['id']}/archivo", headers=await auth(AP), params={"formato": "xml"})
    assert xml.status_code == 200 and b"<Polizas" in xml.content and b"<Poliza " in xml.content and b"cuenta=" in xml.content
    # Los eventos incluidos quedan procesados y marcados con la exportación.
    eventos = (await cliente.get("/api/erp/eventos", headers=await auth(AP), params={"limite": 300})).json()
    incluidos = [e for e in eventos if e["exportacion_id"] == exp["id"]]
    assert incluidos and all(e["estado"] in ("procesado", "omitido") for e in incluidos)
    # Una segunda exportación del mismo período ya no los incluye.
    r2 = await cliente.post("/api/erp/exportaciones", headers=await auth(AP), json={"desde": desde.isoformat(), "hasta": hasta.isoformat()})
    assert r2.json()["eventos_incluidos"] == 0
    assert any(e["id"] == exp["id"] for e in (await cliente.get("/api/erp/exportaciones", headers=await auth(AP))).json())
    # Aislamiento: otro prestador no ve eventos ni exportaciones de este.
    assert all(e["id"] != exp["id"] for e in (await cliente.get("/api/erp/exportaciones", headers=await auth(OTRO_AP))).json())
    assert (await cliente.get(f"/api/erp/exportaciones/{exp['id']}/archivo", headers=await auth(OTRO_AP))).status_code == 404
