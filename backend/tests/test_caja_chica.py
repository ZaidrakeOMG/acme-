"""Caja chica (§6.4 Tipo C y §6.5): permiso `usar_caja_chica`, captura con foto, aprobación que crea los tres registros en una
transacción y descuenta el saldo, saldo insuficiente bloqueado (§6.7), rechazo, reposición diaria en Excel con las 12 columnas
y en XML, reposición del fondo y alertas."""
import base64
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from openpyxl import load_workbook

from models.inventario import FondoCajaChica, GastoCajaChica
from tests.folios_utiles import AE, AP, DES, MC, OP, OTRO_AP, TEC, TEC2, accion, detalle
from tests.inventario_utiles import (
    alertas_disparadas, almacen_demo, articulo, bandeja, entrada, existencia, fondo, fondo_de, gasto, permiso_tecnico, retroceder, tecnico_usuario_id,
)
from tests.test_formularios_evidencias import jpeg


async def _fondo_tec(cliente, auth, email=TEC, monto="5000.00"):
    f = await fondo_de(cliente, auth, email)
    if f is None:
        f = await fondo(cliente, auth, email, monto)
    return f


async def test_permiso_captura_y_aprobacion_crea_los_tres_registros(cliente, auth, datos):
    from tests.test_cierre_folio import _en_ejecucion

    await permiso_tecnico(cliente, auth, TEC, "usar_caja_chica", True)
    f = await _fondo_tec(cliente, auth, TEC)
    saldo_inicial = Decimal(f["saldo_actual"])
    folio = await _en_ejecucion(cliente, auth, datos)
    art = await articulo(cliente, auth, costo="180.00")
    alm = await almacen_demo(cliente, auth)
    await entrada(cliente, auth, art["id"], alm["id"], "5", "180.00")
    # El técnico captura la factura con foto desde la atención del folio.
    g = await gasto(cliente, auth, folio_id=folio["id"], subtotal="180.00", iva="28.80", articulo_id=art["id"],
                    imagen_base64=base64.b64encode(jpeg(640, 480)).decode(), nombre_imagen="factura.jpg", mime="image/jpeg",
                    centro_costos="MANTENIMIENTO", cuenta_contable="5101-001")
    assert g["estado"] == "capturado" and g["estado_cfdi"] == "no_validado" and g["imagen_disponible"] and Decimal(g["monto"]) == Decimal("208.80")
    assert (await cliente.get(f"/api/caja-chica/gastos/{g['id']}/imagen", headers=await auth(AP))).status_code == 200
    assert any(n["evento"] == "caja_chica.por_aprobar" and n["datos"]["gasto_id"] == g["id"] for n in await bandeja(cliente, auth, AP, solo_no_leidas=True))
    # El OCR y la validación SAT son stub de Fase 1.
    r = await cliente.post("/api/caja-chica/ocr", headers=await auth(TEC), json={"imagen_base64": base64.b64encode(b"x").decode()})
    assert r.status_code == 200 and r.json()["disponible"] is False and "Fase 2" in r.json()["detalle"]
    # Aprobación en un toque: refacción + entrada/salida de inventario + gasto que afecta el saldo.
    assert (await cliente.post(f"/api/caja-chica/gastos/{g['id']}/aprobar", headers=await auth(DES))).status_code == 403
    r = await cliente.post(f"/api/caja-chica/gastos/{g['id']}/aprobar", headers=await auth(AP))
    assert r.status_code == 200, r.text
    resultado = r.json()
    assert resultado["gasto"]["estado"] == "aprobado" and resultado["refaccion_id"] and len(resultado["movimientos"]) == 2
    assert Decimal(resultado["saldo_fondo"]) == saldo_inicial - Decimal("208.80")
    movs = (await cliente.get("/api/inventario/movimientos", headers=await auth(AP), params={"folio_id": folio["id"]})).json()
    tipos = [(m["tipo"], m["origen"]) for m in movs if m["origen"] == "caja_chica"]
    assert ("entrada", "caja_chica") in tipos and ("consumo_folio", "caja_chica") in tipos
    # La refacción queda vinculada al folio con el costo sin IVA y el folio se desbloquea para cierre.
    d = await detalle(cliente, auth, folio["id"])
    ref = next(x for x in d["financiero"]["refacciones"] if x["origen"] == "caja_chica")
    assert Decimal(ref["costo_unitario"]) == 180 and d["financiero"]["visible"] is True
    assert any(e["tipo"] == "factura" for e in d["evidencias"])
    assert (await cliente.post(f"/api/caja-chica/gastos/{g['id']}/aprobar", headers=await auth(AP))).status_code == 409
    assert any(n["evento"] == "caja_chica.resuelto" for n in await bandeja(cliente, auth, TEC))


async def test_sin_permiso_saldo_insuficiente_y_rechazo(cliente, auth, datos):
    await permiso_tecnico(cliente, auth, TEC2, "usar_caja_chica", False)
    await _fondo_tec(cliente, auth, TEC2, "300.00")
    r = await gasto(cliente, auth, subtotal="100.00", iva="16.00", email=TEC2, esperado=403)
    assert r["codigo"] == "SIN_PERMISO_CAJA_CHICA"
    await permiso_tecnico(cliente, auth, TEC2, "usar_caja_chica", True)
    # §6.7: el fondo no puede quedar en saldo negativo.
    caro = await gasto(cliente, auth, subtotal="900.00", iva="144.00", email=TEC2)
    r = await cliente.post(f"/api/caja-chica/gastos/{caro['id']}/aprobar", headers=await auth(AP))
    assert r.status_code == 409 and r.json()["codigo"] == "SALDO_INSUFICIENTE"
    f = await fondo_de(cliente, auth, TEC2)
    assert Decimal(f["saldo_actual"]) == 300  # el rechazo por saldo no toca el fondo
    # Rechazo con razón obligatoria: no afecta saldo ni inventario.
    assert (await cliente.post(f"/api/caja-chica/gastos/{caro['id']}/rechazar", headers=await auth(AP), json={"razon": ""})).status_code == 422
    r = await cliente.post(f"/api/caja-chica/gastos/{caro['id']}/rechazar", headers=await auth(AP), json={"razon": "Excede el fondo autorizado"})
    assert r.status_code == 200 and r.json()["estado"] == "rechazado" and r.json()["razon_rechazo"]
    assert Decimal((await fondo_de(cliente, auth, TEC2))["saldo_actual"]) == 300
    # El técnico solo ve sus gastos; otro prestador no ve ninguno.
    mios = (await cliente.get("/api/caja-chica/gastos", headers=await auth(TEC2))).json()
    tid = await tecnico_usuario_id(cliente, auth, TEC2)
    assert mios and all(g["tecnico_id"] == tid for g in mios)
    assert all(g["id"] != caro["id"] for g in (await cliente.get("/api/caja-chica/gastos", headers=await auth(OTRO_AP))).json())


async def test_reposicion_diaria_excel_xml_y_fondo(cliente, auth, datos):
    await permiso_tecnico(cliente, auth, TEC, "usar_caja_chica", True)
    f = await _fondo_tec(cliente, auth, TEC)
    hoy = date.today()
    gastos = []
    for i in range(2):
        g = await gasto(cliente, auth, subtotal=f"{150 + i * 50}.00", iva=f"{24 + i * 8}.00", descripcion=f"Material de campo {i + 1}",
                        centro_costos="MANTENIMIENTO", cuenta_contable="5101-001")
        await cliente.post(f"/api/caja-chica/gastos/{g['id']}/aprobar", headers=await auth(AP))
        gastos.append(g)
    r = await cliente.post("/api/caja-chica/polizas", headers=await auth(AP), params={"fecha": hoy.isoformat(), "fondo_id": f["id"]})
    assert r.status_code == 200, r.text
    p = r.json()
    assert p is not None and p["gastos"] >= 2 and Decimal(p["total"]) > 0 and p["archivo_disponible"] and p["xml_disponible"]
    # Excel con las 12 columnas literales de §6.5.
    x = await cliente.get(f"/api/caja-chica/polizas/{p['id']}/archivo", headers=await auth(AP), params={"formato": "xlsx"})
    assert x.status_code == 200
    import io

    ws = load_workbook(io.BytesIO(x.content)).active
    encabezados = [c.value for c in ws[3]]
    assert encabezados == ["Fecha", "Proveedor", "RFC", "Folio fiscal", "Descripción", "Monto", "IVA", "Total", "Centro de costos", "Cuenta contable",
                          "Técnico", "Folio de servicio"]
    assert ws.cell(row=4, column=9).value == "MANTENIMIENTO"
    # XML de póliza estándar.
    xml = await cliente.get(f"/api/caja-chica/polizas/{p['id']}/archivo", headers=await auth(AP), params={"formato": "xml"})
    assert xml.status_code == 200 and b"<Poliza" in xml.content and b"Movimiento" in xml.content
    # Evento ERP de la póliza.
    eventos = (await cliente.get("/api/erp/eventos", headers=await auth(AP), params={"limite": 200})).json()
    assert any(e["operacion"] == "poliza_caja_chica" and e["entidad_id"] == p["id"] for e in eventos)
    # Los gastos ya consolidados no entran a una segunda póliza del mismo día: no queda nada por consolidar.
    assert (await cliente.post("/api/caja-chica/polizas", headers=await auth(AP), params={"fecha": hoy.isoformat(), "fondo_id": f["id"]})).json() is None
    assert any(x["id"] == p["id"] for x in (await cliente.get("/api/caja-chica/polizas", headers=await auth(AP))).json())
    # Reposición del fondo: restablece el saldo y la fecha.
    r = await cliente.post(f"/api/caja-chica/fondos/{f['id']}/reponer", headers=await auth(AP), json={})
    assert r.status_code == 200 and Decimal(r.json()["saldo_actual"]) == Decimal(r.json()["monto_inicial"]) and r.json()["fecha_ultima_reposicion"] == hoy.isoformat()


async def test_alertas_de_caja_chica(cliente, auth, datos):
    from workers import tareas

    await permiso_tecnico(cliente, auth, TEC, "usar_caja_chica", True)
    f = await _fondo_tec(cliente, auth, TEC)
    pendiente = await gasto(cliente, auth, subtotal="100.00", iva="16.00", descripcion="Gasto sin aprobar")
    await retroceder(GastoCajaChica, pendiente["id"], timestamp=datetime.now(UTC) - timedelta(days=5))
    await retroceder(FondoCajaChica, f["id"], saldo_actual=Decimal("100.00"), monto_inicial=Decimal("5000.00"))
    await tareas.evaluar_alertas_async()
    assert await alertas_disparadas("GASTO_CAJA_CHICA_SIN_APROBAR", pendiente["id"])
    assert await alertas_disparadas("FONDO_CAJA_CHICA_BAJO", f["id"])
    actualizado = await fondo_de(cliente, auth, TEC)
    assert actualizado["bajo_umbral"] is True and Decimal(actualizado["porcentaje_saldo"]) == 2
