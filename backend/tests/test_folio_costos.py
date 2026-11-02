"""Costo del folio (§6.8.6): cálculo al cierre con refacciones y mano de obra, tarifa más específica, horas del formulario,
validación con ajuste y razón, evento ERP `registrar_gasto`, y visibilidad por el permiso `ver_costo_refacciones`."""
from decimal import Decimal

from tests.folios_utiles import AE, AP, AUN, DES, MC, OP, OTRO_AE, TEC, accion, detalle
from tests.inventario_utiles import (
    almacen_demo, articulo, bandeja, cerrar_folio, costos_de, entrada, folio_en_ejecucion, permiso_tecnico, refaccion, tarifa, traspaso, validar_costo,
    vehiculo_de,
)


async def test_costo_al_cerrar_con_refacciones_y_mano_de_obra(cliente, auth, datos):
    await tarifa(cliente, auth, "400.00")
    a = await articulo(cliente, auth, costo="500.00")
    alm, veh = await almacen_demo(cliente, auth), await vehiculo_de(cliente, auth, TEC)
    await entrada(cliente, auth, a["id"], alm["id"], "10", "500.00")
    await traspaso(cliente, auth, a["id"], alm["id"], veh["id"], "4")
    f = await folio_en_ejecucion(cliente, auth, datos)
    await refaccion(cliente, auth, f["id"], articulo_id=a["id"], cantidad="2")
    await refaccion(cliente, auth, f["id"], descripcion="Material misceláneo", cantidad="1", costo="150.00")
    # Antes del cierre no hay costo.
    assert (await costos_de(cliente, auth, f["id"]))["costo"] is None
    await cerrar_folio(cliente, auth, datos, f)
    fin = await costos_de(cliente, auth, f["id"])
    c = fin["costo"]
    assert Decimal(c["costo_refacciones"]) == 1150  # 2×500 + 150
    assert Decimal(c["tarifa_hora"]) == 400 and c["origen_horas"] in ("calculadas", "formulario", "minimo")
    assert Decimal(c["costo_total"]) == Decimal(c["costo_refacciones"]) + Decimal(c["costo_mano_obra"])
    assert c["validado_at"] is None and fin["puede_validar"] is True and len(fin["refacciones"]) == 2
    assert any(n["evento"] == "folio.costo_calculado" and n["datos"]["folio_id"] == f["id"] for n in await bandeja(cliente, auth, MC))
    # El detalle del folio trae la sección financiera.
    d = await detalle(cliente, auth, f["id"], MC)
    assert d["financiero"]["visible"] is True and Decimal(d["financiero"]["costo"]["costo_total"]) == Decimal(c["costo_total"])


async def test_tarifa_mas_especifica_y_horas_del_formulario(cliente, auth, datos):
    await tarifa(cliente, auth, "400.00")
    await tarifa(cliente, auth, "900.00", tenant_id=str(datos["tenant"]), tipo_folio="correctivo")
    f = await folio_en_ejecucion(cliente, auth, datos)
    # Formulario de atención con horas capturadas por el técnico: mandan sobre las calculadas.
    from tests.test_cierre_folio import firmar
    from tests.test_formularios import crear_formulario, publicar

    esquema = {"secciones": [{"clave": "s", "titulo": "S", "campos": [
        {"clave": "diag", "tipo": "texto", "etiqueta": "Diagnóstico", "obligatorio": True, "config": {"longitud_min": 2, "longitud_max": 200}},
        {"clave": "horas_mano_obra", "tipo": "texto", "etiqueta": "Horas de mano de obra", "config": {"longitud_min": 1, "longitud_max": 6, "formato": "numeros"}}]}]}
    form = await crear_formulario(cliente, auth, AP, tipo="atencion_tecnico", rol_destino=["tecnico"], esquema=esquema)
    await publicar(cliente, auth, form["id"])
    r = await cliente.post(f"/api/formularios/{form['id']}/respuestas", headers=await auth(TEC),
                           json={"origen": "folio_atencion", "referencia_id": f["id"],
                                 "contexto": {"tenant_id": str(datos["tenant"]), "un_id": f["un_id"], "equipo_id": f["equipo_id"]},
                                 "respuestas": {"diag": "Cambio de empaque", "horas_mano_obra": "3"}})
    rid = r.json()["id"]
    await cliente.post(f"/api/formularios/respuestas/{rid}/enviar", headers=await auth(TEC))
    await accion(cliente, auth, TEC, f["id"], "atencion", {"respuesta_id": rid}, esperado=201)
    await firmar(cliente, auth, OP, f["id"])
    await accion(cliente, auth, TEC, f["id"], "cerrar")
    c = (await costos_de(cliente, auth, f["id"]))["costo"]
    assert Decimal(c["tarifa_hora"]) == 900 and Decimal(c["horas_mano_obra"]) == 3 and c["origen_horas"] == "formulario"
    assert Decimal(c["costo_mano_obra"]) == 2700


async def test_validacion_con_ajuste_y_evento_erp(cliente, auth, datos):
    await tarifa(cliente, auth, "400.00")
    f = await folio_en_ejecucion(cliente, auth, datos)
    await refaccion(cliente, auth, f["id"], descripcion="Refacción libre", cantidad="1", costo="600.00")
    await cerrar_folio(cliente, auth, datos, f)
    assert (await validar_costo(cliente, auth, f["id"], email=OP, esperado=403))["codigo"] == "PROHIBIDO"
    assert (await validar_costo(cliente, auth, f["id"], esperado=422, ajuste="-100.00"))["codigo"] == "RAZON_REQUERIDA"
    r = await validar_costo(cliente, auth, f["id"], ajuste="-100.00", razon_ajuste="Descuento comercial acordado", costo_otros="50.00",
                            centro_costos="MANTENIMIENTO")
    c = r["costo"]
    assert Decimal(c["ajuste"]) == -100 and Decimal(c["costo_otros"]) == 50 and c["centro_costos"] == "MANTENIMIENTO"
    assert Decimal(c["costo_total"]) == Decimal(c["costo_refacciones"]) + Decimal(c["costo_mano_obra"]) + 50 - 100
    assert c["validado_at"] and c["validado_por_nombre"] and c["documento_erp_ref"] and r["puede_validar"] is False
    assert (await validar_costo(cliente, auth, f["id"], esperado=409))["codigo"] == "COSTO_YA_VALIDADO"
    eventos = (await cliente.get("/api/erp/eventos", headers=await auth(AP), params={"limite": 200})).json()
    evento = next(e for e in eventos if e["operacion"] == "registrar_gasto" and e["payload_json"].get("numero_folio") == f["numero_folio"])
    assert evento["estado"] == "pendiente" and evento["payload_json"]["centro_costos"] == "MANTENIMIENTO"
    d = await detalle(cliente, auth, f["id"], AE)
    assert any(h["evento"] == "folio.costo_validado" for h in d["historial"])
    assert any(n["evento"] == "folio.costo_validado" for n in await bandeja(cliente, auth, AUN))


async def test_visibilidad_del_costo_por_permiso(cliente, auth, datos):
    await tarifa(cliente, auth, "400.00")
    f = await folio_en_ejecucion(cliente, auth, datos)
    await refaccion(cliente, auth, f["id"], descripcion="Refacción", cantidad="1", costo="300.00")
    await cerrar_folio(cliente, auth, datos, f)
    await permiso_tecnico(cliente, auth, TEC, "ver_costo_refacciones", False)
    sin_permiso = (await cliente.get(f"/api/folios/{f['id']}/costos", headers=await auth(TEC))).json()
    assert sin_permiso["visible"] is False and "ver_costo_refacciones" in sin_permiso["motivo"]
    await permiso_tecnico(cliente, auth, TEC, "ver_costo_refacciones", True)
    con_permiso = (await cliente.get(f"/api/folios/{f['id']}/costos", headers=await auth(TEC))).json()
    assert con_permiso["visible"] is True and Decimal(con_permiso["costo"]["costo_refacciones"]) == 300
    # El cliente ve el costo total y el desglose de su folio; otro tenant no ve el folio.
    cliente_ve = (await cliente.get(f"/api/folios/{f['id']}/costos", headers=await auth(AUN))).json()
    assert cliente_ve["visible"] is True and cliente_ve["puede_validar"] is False
    assert (await cliente.get(f"/api/folios/{f['id']}/costos", headers=await auth(OTRO_AE))).status_code == 404
