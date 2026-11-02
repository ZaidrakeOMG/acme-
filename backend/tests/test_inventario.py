"""Inventario (§6.4): existencias y costo promedio ponderado por tipo de movimiento, inmutabilidad de `movimientos_inventario`,
consumo desde vehículo y desde almacén, técnico compartido entre tenants, merge offline con stock negativo y alerta,
`refaccion_ok` en la reasignación, alertas de stock y aislamiento entre prestadores."""
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text

from core.db import nueva_sesion
from core.rls import CONTEXTO_SISTEMA
from tests.folios_utiles import AE, AP, DES, MC, OP, OTRO_AP, TEC, TEC2, accion, nuevo_equipo, tecnico_con_habilidades, tecnico_usuario_id
from tests.inventario_utiles import alertas_disparadas, almacen_demo, articulo, bandeja, entrada, existencia, refaccion, traspaso, ubicacion, vehiculo_de


async def test_entrada_traspaso_ajuste_y_costo_promedio(cliente, auth, datos):
    a = await articulo(cliente, auth, costo="100.00", minimo="2")
    assert a["codigo"].startswith("ART-") and a["activo"] is True
    assert (await articulo(cliente, auth, codigo=a["codigo"], esperado=409))["codigo"] == "ARTICULO_DUPLICADO"
    assert (await articulo(cliente, auth, email=DES, esperado=403))["codigo"] == "PROHIBIDO"
    alm = await almacen_demo(cliente, auth)
    # Entrada: 10 a $100 → promedio 100.
    await entrada(cliente, auth, a["id"], alm["id"], "10", "100.00")
    e = await existencia(cliente, auth, alm["id"], a["id"])
    assert Decimal(e["cantidad"]) == 10 and Decimal(e["costo_promedio"]) == 100
    # Segunda entrada: 10 a $200 → promedio ponderado 150.
    await entrada(cliente, auth, a["id"], alm["id"], "10", "200.00")
    e = await existencia(cliente, auth, alm["id"], a["id"])
    assert Decimal(e["cantidad"]) == 20 and Decimal(e["costo_promedio"]) == 150
    # El costo vigente del artículo sigue a la última entrada.
    assert Decimal((await cliente.get("/api/inventario/articulos", headers=await auth(AP), params={"q": a["codigo"]})).json()[0]["costo_unitario_vigente"]) == 200
    # Traspaso al vehículo: la salida no cambia el promedio del origen y el destino lo hereda.
    veh = await vehiculo_de(cliente, auth, TEC)
    await traspaso(cliente, auth, a["id"], alm["id"], veh["id"], "4")
    origen = await existencia(cliente, auth, alm["id"], a["id"])
    destino = await existencia(cliente, auth, veh["id"], a["id"])
    assert Decimal(origen["cantidad"]) == 16 and Decimal(origen["costo_promedio"]) == 150
    assert Decimal(destino["cantidad"]) == 4 and Decimal(destino["costo_promedio"]) == 150
    assert (await traspaso(cliente, auth, a["id"], alm["id"], alm["id"], "1", esperado=422))["codigo"] == "UBICACIONES_IGUALES"
    # Sin stock suficiente: 409 (en línea no se permite negativo).
    r = await cliente.post("/api/inventario/movimientos/traspaso", headers=await auth(AP),
                           json={"articulo_id": a["id"], "origen_id": veh["id"], "destino_id": alm["id"], "cantidad": "99"})
    assert r.status_code == 409 and r.json()["codigo"] == "STOCK_INSUFICIENTE" and r.json()["detalles"][0]["disponible"] == "4.00"
    # Ajuste: exige razón y admite negativo (merma).
    r = await cliente.post("/api/inventario/movimientos/ajuste", headers=await auth(AP),
                           json={"articulo_id": a["id"], "ubicacion_id": alm["id"], "cantidad": "-2", "razon": "x"})
    assert r.status_code == 422
    r = await cliente.post("/api/inventario/movimientos/ajuste", headers=await auth(DES),
                           json={"articulo_id": a["id"], "ubicacion_id": alm["id"], "cantidad": "-2", "razon": "Merma por daño en almacén"})
    assert r.status_code == 403  # el ajuste es del Admin prestador
    await cliente.post("/api/inventario/movimientos/ajuste", headers=await auth(AP),
                       json={"articulo_id": a["id"], "ubicacion_id": alm["id"], "cantidad": "-2", "razon": "Merma por daño en almacén"})
    assert Decimal((await existencia(cliente, auth, alm["id"], a["id"]))["cantidad"]) == 14
    # Historial de movimientos del artículo con sus cinco tipos aplicados.
    movs = (await cliente.get("/api/inventario/movimientos", headers=await auth(AP), params={"articulo_id": a["id"]})).json()
    assert {m["tipo"] for m in movs} == {"entrada", "traspaso", "ajuste"} and len(movs) == 4


async def test_movimientos_son_append_only(cliente, auth, datos):
    a = await articulo(cliente, auth)
    alm = await almacen_demo(cliente, auth)
    m = await entrada(cliente, auth, a["id"], alm["id"], "5", "50.00")
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        with pytest.raises(Exception) as e1:
            await db.execute(text("UPDATE movimientos_inventario SET cantidad = 99 WHERE id = :i"), {"i": m["id"]})
        assert "append-only" in str(e1.value) or "insufficient_privilege" in str(e1.value)
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        with pytest.raises(Exception) as e2:
            await db.execute(text("DELETE FROM movimientos_inventario WHERE id = :i"), {"i": m["id"]})
        assert "append-only" in str(e2.value) or "insufficient_privilege" in str(e2.value)


async def test_consumo_en_folio_desde_vehiculo_y_desde_almacen(cliente, auth, datos):
    from tests.test_cierre_folio import _en_ejecucion

    a = await articulo(cliente, auth, costo="250.00")
    alm, veh = await almacen_demo(cliente, auth), await vehiculo_de(cliente, auth, TEC)
    await entrada(cliente, auth, a["id"], alm["id"], "20", "250.00")
    await traspaso(cliente, auth, a["id"], alm["id"], veh["id"], "5")
    f = await _en_ejecucion(cliente, auth, datos)
    # Sin ubicación: descuenta del vehículo del técnico asignado y hereda el costo promedio.
    r = await refaccion(cliente, auth, f["id"], articulo_id=a["id"], cantidad="2")
    assert Decimal(r["costo_unitario"]) == 250 and r["articulo_id"] == a["id"]
    assert Decimal((await existencia(cliente, auth, veh["id"], a["id"]))["cantidad"]) == 3
    # Con ubicación explícita: descuenta del almacén.
    await refaccion(cliente, auth, f["id"], articulo_id=a["id"], cantidad="1", ubicacion_id=alm["id"])
    assert Decimal((await existencia(cliente, auth, alm["id"], a["id"]))["cantidad"]) == 14
    # Sin artículo: descripción libre, sin movimiento de inventario.
    antes = len((await cliente.get("/api/inventario/movimientos", headers=await auth(AP), params={"folio_id": f["id"]})).json())
    await refaccion(cliente, auth, f["id"], descripcion="Tornillería variada (compra fuera de catálogo)", costo="75.00")
    movs = (await cliente.get("/api/inventario/movimientos", headers=await auth(AP), params={"folio_id": f["id"]})).json()
    assert len(movs) == antes and all(m["tipo"] == "consumo_folio" for m in movs)
    assert movs[0]["numero_folio"] == f["numero_folio"]
    # El consumo imputa el tenant del folio (técnico compartido entre tenants, §6.10.8).
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        filas = (await db.execute(text("SELECT tenant_id, prestador_id FROM movimientos_inventario WHERE folio_id = :f"), {"f": f["id"]})).all()
    assert filas and all(str(t) == str(datos["tenant"]) and str(p) == str(datos["prestador"]) for t, p in filas)


async def test_merge_offline_deja_stock_negativo_con_alerta(cliente, auth, datos):
    """§6.2 merge con alerta: ambos consumos offline se aplican aunque la existencia quede negativa."""
    from tests.test_cierre_folio import _en_ejecucion

    a = await articulo(cliente, auth, costo="90.00")
    alm, veh = await almacen_demo(cliente, auth), await vehiculo_de(cliente, auth, TEC)
    await entrada(cliente, auth, a["id"], alm["id"], "10", "90.00")
    await traspaso(cliente, auth, a["id"], alm["id"], veh["id"], "1")
    f = await _en_ejecucion(cliente, auth, datos)
    lote = {"dispositivo_id": "disp-p09", "version_app": "1.0.0", "plataforma": "android", "mutaciones": [
        {"id_cliente": str(uuid.uuid4()), "tipo": "agregar_refaccion", "timestamp_dispositivo": "2026-10-30T15:00:00Z",
         "payload": {"folio_id": f["id"], "descripcion": "Consumo offline 1", "cantidad": 1, "articulo_id": a["id"], "origen": "almacen"}},
        {"id_cliente": str(uuid.uuid4()), "tipo": "agregar_refaccion", "timestamp_dispositivo": "2026-10-30T15:05:00Z",
         "payload": {"folio_id": f["id"], "descripcion": "Consumo offline 2", "cantidad": 1, "articulo_id": a["id"], "origen": "almacen"}}]}
    r = await cliente.post("/api/sync/mutaciones", headers=await auth(TEC), json=lote)
    assert r.status_code == 200 and [m["resultado"] for m in r.json()] == ["aplicada", "aplicada"]
    e = await existencia(cliente, auth, veh["id"], a["id"])
    assert Decimal(e["cantidad"]) == -1
    conflictos = (await cliente.get("/api/sync/conflictos", headers=await auth(TEC))).json()
    mio = next(c for c in conflictos if c["entidad"] == "existencias" and c["datos_servidor_json"].get("ubicacion_id") == veh["id"])
    assert mio["regla_aplicada"] == "merge_alerta" and mio["datos_servidor_json"]["cantidad_despues"] == "-1.00"
    assert await alertas_disparadas("STOCK_NEGATIVO", e["id"])
    assert any(n["evento"] == "inventario.stock_negativo" for n in await bandeja(cliente, auth, DES))


async def test_refaccion_ok_en_la_reasignacion(cliente, auth, datos):
    """P06: la validación compara las refacciones previstas del folio contra el vehículo del técnico candidato."""
    from models.preventivos import ReasignacionValidacion

    art = await articulo(cliente, auth, costo="300.00")
    alm, veh1 = await almacen_demo(cliente, auth), await vehiculo_de(cliente, auth, TEC)
    await entrada(cliente, auth, art["id"], alm["id"], "20", "300.00")
    await traspaso(cliente, auth, art["id"], alm["id"], veh1["id"], "5")
    tec1 = await tecnico_con_habilidades(cliente, auth, TEC, ["refrigeracion", "electricidad"])
    f = await nuevo_equipo(cliente, auth, datos)
    from tests.folios_utiles import REGLAS_DEMO, capturar, reglas

    await reglas(cliente, auth, [])
    try:
        folio = await capturar(cliente, auth, datos, OP, f)
    finally:
        await reglas(cliente, auth, REGLAS_DEMO)
    await accion(cliente, auth, DES, folio["id"], "asignar", {"tecnico_id": tec1})
    await refaccion(cliente, auth, folio["id"], articulo_id=art["id"], cantidad="2")
    tec2 = await tecnico_con_habilidades(cliente, auth, TEC2, ["refrigeracion", "electricidad"])
    cands = {c["usuario_id"]: c for c in (await cliente.get(f"/api/folios/{folio['id']}/reasignacion/candidatos", headers=await auth(DES))).json()}
    assert cands[tec1]["refaccion_ok"] is True  # el técnico actual sí las trae en su vehículo
    assert cands[tec2]["refaccion_ok"] is False and any("Sin las refacciones previstas" in a for a in cands[tec2]["advertencias"])
    # Al reasignar con advertencias confirmadas, la validación queda registrada.
    razones = (await cliente.get("/api/reasignaciones/razones", headers=await auth(DES))).json()
    r = await cliente.post(f"/api/folios/{folio['id']}/reasignar", headers=await auth(DES),
                           json={"tecnico_destino_id": tec2, "razon_id": razones[0]["id"], "comentario": "Prueba de refacción",
                                 "confirmar_advertencias": True})
    assert r.status_code == 201, r.text
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        from sqlalchemy import select

        v = (await db.execute(select(ReasignacionValidacion).where(ReasignacionValidacion.reasignacion_id == r.json()["id"]))).scalar_one()
        assert v.refaccion_ok is False and any("no tiene las refacciones" in x for x in v.advertencias_json)


async def test_alertas_de_stock_y_aislamiento(cliente, auth, datos):
    from workers import tareas

    a = await articulo(cliente, auth, costo="60.00", minimo="5")
    alm = await almacen_demo(cliente, auth)
    await entrada(cliente, auth, a["id"], alm["id"], "3", "60.00")
    await tareas.evaluar_alertas_async()
    e = await existencia(cliente, auth, alm["id"], a["id"])
    assert e["bajo_minimo"] is True and await alertas_disparadas("STOCK_MINIMO", e["id"])
    assert any(x["id"] == e["id"] for x in (await cliente.get("/api/inventario/existencias", headers=await auth(AP), params={"solo_bajo_minimo": True})).json())
    # Aislamiento: otro prestador no ve el artículo ni sus existencias.
    assert all(x["id"] != a["id"] for x in (await cliente.get("/api/inventario/articulos", headers=await auth(OTRO_AP))).json())
    assert all(x["articulo_id"] != a["id"] for x in (await cliente.get("/api/inventario/existencias", headers=await auth(OTRO_AP))).json())
    assert (await cliente.get("/api/inventario/articulos", headers=await auth(AE))).status_code == 403  # el cliente no ve el inventario del prestador
    # El técnico solo ve su vehículo.
    ubicaciones = (await cliente.get("/api/inventario/ubicaciones", headers=await auth(TEC))).json()
    assert ubicaciones and all(u["tipo"] == "vehiculo" for u in ubicaciones)
    tid = await tecnico_usuario_id(cliente, auth, TEC)
    assert all(u["tecnico_id"] == tid for u in ubicaciones)
    existencias_tecnico = (await cliente.get("/api/inventario/existencias", headers=await auth(TEC))).json()
    assert all(x["ubicacion_tipo"] == "vehiculo" for x in existencias_tecnico)
