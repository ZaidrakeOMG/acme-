"""Penalizaciones por período (§6.10.1): consolidado mensual por contrato, revisión borrador → revisado → cerrado,
resumen exportable en PDF y Excel, y consumo de la iguala con su alerta."""
from datetime import date
from decimal import Decimal

from tests.folios_utiles import AE, AP, AUN, DES, MC, OP
from tests.inventario_utiles import cerrar_folio, folio_en_ejecucion
from tests.sla_utiles import apretar_limite, contrato_demo, envejecer_contador, poner_sla_contrato, sla_de

PERIODO = date.today().strftime("%Y-%m")


async def _incumplir(cliente, auth, datos) -> dict:
    f = await folio_en_ejecucion(cliente, auth, datos)
    await apretar_limite(f["id"], limite_min=1, respuesta_min=1)
    await envejecer_contador(f["id"], 7)
    await cerrar_folio(cliente, auth, datos, f)
    return f


async def _calcular(cliente, auth, contrato_id, email=AP, periodo=PERIODO, esperado=200) -> dict:
    r = await cliente.post(f"/api/sla/contratos/{contrato_id}/penalizaciones/calcular",
                           headers=await auth(email), params={"periodo": periodo})
    assert r.status_code == esperado, r.text
    return r.json()


async def test_consolidado_mensual_con_detalle_de_folios(cliente, auth, datos):
    c = await contrato_demo(cliente, auth)
    await poner_sla_contrato(cliente, auth, c["id"], tipo="monto", valor="800.00")
    f = await _incumplir(cliente, auth, datos)
    assert (await sla_de(cliente, auth, f["id"]))["cumplimiento"] is False
    registro = await _calcular(cliente, auth, c["id"])
    assert registro["periodo"] == PERIODO and registro["estado"] == "borrador"
    assert registro["folios_incumplidos"] >= 1 and registro["total_folios"] >= 1
    assert Decimal(registro["monto_penalizacion"]) >= 800
    mio = next((d for d in registro["detalle_json"] if d["numero_folio"] == f["numero_folio"]), None)
    assert mio is not None and mio["limite_min"] is not None and mio["efectivo_min"] > mio["limite_min"]
    assert registro["incluido_en_factura_id"] is None  # el CFDI es Fase 2
    await poner_sla_contrato(cliente, auth, c["id"], tipo="porcentaje", valor="10")


async def test_revision_borrador_revisado_cerrado(cliente, auth, datos):
    c = await contrato_demo(cliente, auth)
    await _incumplir(cliente, auth, datos)
    registro = await _calcular(cliente, auth, c["id"])
    # No se puede saltar un paso.
    r = await cliente.post(f"/api/sla/penalizaciones/{registro['id']}/estado", headers=await auth(AP),
                           json={"estado": "cerrado"})
    assert r.status_code == 409
    r = await cliente.post(f"/api/sla/penalizaciones/{registro['id']}/estado", headers=await auth(AP),
                           json={"estado": "revisado"})
    assert r.status_code == 200 and r.json()["estado"] == "revisado" and r.json()["revisado_at"] is not None
    r = await cliente.post(f"/api/sla/penalizaciones/{registro['id']}/estado", headers=await auth(AP),
                           json={"estado": "cerrado"})
    assert r.status_code == 200 and r.json()["estado"] == "cerrado" and r.json()["cerrado_at"] is not None
    # Un período cerrado ya no se recalcula.
    monto = r.json()["monto_penalizacion"]
    await _incumplir(cliente, auth, datos)
    assert (await _calcular(cliente, auth, c["id"]))["monto_penalizacion"] == monto


async def test_solo_el_prestador_revisa_y_el_cliente_consulta(cliente, auth, datos):
    c = await contrato_demo(cliente, auth)
    await _incumplir(cliente, auth, datos)
    await _calcular(cliente, auth, c["id"], email=AE, esperado=403)
    registro = await _calcular(cliente, auth, c["id"])
    r = await cliente.post(f"/api/sla/penalizaciones/{registro['id']}/estado", headers=await auth(AE),
                           json={"estado": "revisado"})
    assert r.status_code == 403
    # El cliente sí consulta el histórico y el cumplimiento del contrato.
    r = await cliente.get(f"/api/sla/contratos/{c['id']}/penalizaciones", headers=await auth(AE))
    assert r.status_code == 200 and any(x["periodo"] == PERIODO for x in r.json())
    r = await cliente.get(f"/api/sla/contratos/{c['id']}/cumplimiento", headers=await auth(AE))
    assert r.status_code == 200 and r.json()["folios_cerrados"] >= 1 and "por_severidad" in r.json()


async def test_resumen_exportable_en_pdf_y_excel(cliente, auth, datos):
    c = await contrato_demo(cliente, auth)
    await _incumplir(cliente, auth, datos)
    registro = await _calcular(cliente, auth, c["id"])
    for formato, firma in (("pdf", b"%PDF"), ("xlsx", b"PK")):
        r = await cliente.get(f"/api/sla/penalizaciones/{registro['id']}/archivo", headers=await auth(AP),
                              params={"formato": formato})
        assert r.status_code == 200, r.text
        assert r.content.startswith(firma) and len(r.content) > 500
        assert "attachment" in r.headers["content-disposition"]


async def test_consumo_de_iguala_y_correctivos_adicionales(cliente, auth, datos):
    """§6.10.1: la iguala incluye un número pactado de correctivos; los de más se identifican por separado.

    La relación tenant–prestador tiene un solo contrato, así que la prueba ajusta el que ya existe en lugar de crear
    un segundo contrato activo (que dejaría indefinido qué SLA y qué horario de servicio aplican).
    """
    c = await contrato_demo(cliente, auth)
    r = await cliente.patch(f"/api/contratos/{c['id']}", headers=await auth(AP),
                            json={"modalidad": "iguala", "folios_correctivos_iguala": 1,
                                  "tarifa_iguala_mensual": "30000.00",
                                  "preventivos_iguala_json": {"cantidad": 2, "periodicidad": "mensual"}})
    assert r.status_code == 200, r.text
    iguala = r.json()
    assert iguala["modalidad"] == "iguala" and iguala["tarifa_iguala_mensual"] == "30000.00" and iguala["moneda"] == "MXN"
    # Dos correctivos cerrados: uno entra en la iguala y el otro es adicional.
    for _ in range(2):
        f = await folio_en_ejecucion(cliente, auth, datos)
        await cerrar_folio(cliente, auth, datos, f)
    r = await cliente.post(f"/api/sla/contratos/{iguala['id']}/iguala/calcular", headers=await auth(AP),
                           params={"periodo": PERIODO})
    assert r.status_code == 200, r.text
    consumo = r.json()
    assert consumo["correctivos_incluidos"] == 1 and consumo["correctivos_atendidos"] >= 2
    assert consumo["correctivos_adicionales"] >= 1 and len(consumo["folios_adicionales_json"]) >= 1
    assert consumo["preventivos_incluidos"] == 2
    # El histórico queda consultable.
    r = await cliente.get(f"/api/sla/contratos/{iguala['id']}/iguala", headers=await auth(MC))
    assert r.status_code == 200 and r.json()[0]["periodo"] == PERIODO


async def test_un_contrato_por_evento_no_tiene_iguala(cliente, auth, datos):
    c = await contrato_demo(cliente, auth)
    previa = c["modalidad"]
    r = await cliente.patch(f"/api/contratos/{c['id']}", headers=await auth(AP), json={"modalidad": "evento"})
    assert r.status_code == 200 and r.json()["modalidad"] == "evento"
    r = await cliente.post(f"/api/sla/contratos/{c['id']}/iguala/calcular", headers=await auth(AP),
                           params={"periodo": PERIODO})
    assert r.status_code == 409 and r.json()["codigo"] == "CONTRATO_POR_EVENTO"
    if previa == "iguala":
        await cliente.patch(f"/api/contratos/{c['id']}", headers=await auth(AP),
                            json={"modalidad": "iguala", "folios_correctivos_iguala": 20,
                                  "tarifa_iguala_mensual": "48000.00"})


async def test_la_iguala_exige_tarifa_y_folios_incluidos(cliente, auth, datos):
    """La validación es del esquema del contrato: se prueba con un alta nueva (el tenant de prueba la rechaza igual)."""
    base = {"tenant_id": str(datos["tenant"]), "nombre": "Iguala incompleta", "modalidad": "iguala",
            "fecha_inicio": "2026-01-01", "fecha_fin": "2026-12-31",
            "slas": [{"nivel_severidad": n, "tiempo_respuesta_horas": 4, "tiempo_resolucion_horas": 24}
                     for n in ("muy_baja", "baja", "media", "alta", "critica")]}
    r = await cliente.post("/api/contratos", headers=await auth(AP), json=base)
    assert r.status_code == 422
    r = await cliente.post("/api/contratos", headers=await auth(AP), json={**base, "folios_correctivos_iguala": 10})
    assert r.status_code == 422 and "tarifa" in r.text
