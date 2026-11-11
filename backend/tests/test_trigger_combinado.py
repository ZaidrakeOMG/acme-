"""Trigger combinado (§6.9.1): OR = «lo que ocurra primero», AND = «cuando se cumplan todas», y el reinicio de
**todos** los triggers del combinado al ejecutarse el plan. F2-04.

El ejemplo literal del documento es «revisión si han pasado 90 días O si el medidor supera 400 horas, lo que ocurra
primero». La identidad de los triggers dentro del plan es su `clave` (`t1`, `t2`, …), que sobrevive a las
ediciones; la API acepta y devuelve además `triggers_ids`, que es con lo que trabaja la interfaz.
"""
from datetime import date, timedelta
from decimal import Decimal

from core.db import nueva_sesion
from core.rls import CONTEXTO_SISTEMA
from tests.folios_utiles import AE, AP, DES, TEC, accion, detalle, tecnico_con_habilidades
from tests.medidores_utiles import equipo_con_medidor, incremento_esperado, lectura
from tests.preventivos_utiles import calendario, nuevo_plan
from tests.test_folio_estados import _respuesta_atencion_con_firma


def _triggers(tipo_medidor_id: str, *, umbral=400, dias=90, logica="OR") -> list[dict]:
    return [
        {"tipo_trigger": "tiempo_fijo", "clave": "t1", "parametros_json": {"cada_dias": dias}},
        {"tipo_trigger": "medidor_umbral", "clave": "t2",
         "parametros_json": {"tipo_medidor_id": tipo_medidor_id, "umbral": umbral}},
        {"tipo_trigger": "combinado", "clave": "t3",
         "parametros_json": {"triggers_claves": ["t1", "t2"], "logica": logica}},
    ]


async def _plan_combinado(cliente, auth, equipo, tipo, **kw) -> dict:
    plan = await nuevo_plan(cliente, auth, triggers=_triggers(tipo["id"], **kw))
    r = await cliente.post(f"/api/planes/{plan['id']}/equipos", headers=await auth(AP), json={"equipo_id": equipo["id"]})
    assert r.status_code == 201, r.text
    return plan


async def _filas(cliente, auth, plan, equipo) -> list[dict]:
    return [c for c in await calendario(cliente, auth, AE) if c["plan_id"] == plan["id"] and c["equipo_id"] == equipo["id"]]


async def test_combinado_or_dispara_con_lo_que_ocurra_primero(cliente, auth, datos):
    """90 días O 400 h: las horas llegan antes, así que el folio nace por el medidor."""
    equipo, medidor, tipo = await equipo_con_medidor(cliente, auth, datos, factor_salto="100")
    await incremento_esperado(cliente, auth, medidor, 100)
    plan = await _plan_combinado(cliente, auth, equipo, tipo, umbral=400, dias=90, logica="OR")
    # El detalle devuelve las claves y los ids resueltos: es lo que necesita el constructor de la interfaz.
    d = (await cliente.get(f"/api/planes/{plan['id']}", headers=await auth(AP))).json()
    comb = next(t for t in d["triggers"] if t["tipo_trigger"] == "combinado")
    ids = {t["clave"]: t["id"] for t in d["triggers"]}
    assert comb["parametros_json"]["logica"] == "OR"
    assert comb["parametros_json"]["triggers_ids"] == [ids["t1"], ids["t2"]]
    assert await _filas(cliente, auth, plan, equipo) == []
    await lectura(cliente, auth, medidor, "380", dias_atras=2)
    assert await _filas(cliente, auth, plan, equipo) == []
    r = await lectura(cliente, auth, medidor, "410", dias_atras=1)
    assert len(r["folios_generados"]) == 1, r
    generado = r["folios_generados"][0]
    assert generado["origen"] == "medidor" and generado["trigger"] in ("combinado", "medidor_umbral")
    filas = await _filas(cliente, auth, plan, equipo)
    assert len(filas) == 1 and filas[0]["origen"] == "medidor"


async def test_combinado_and_exige_las_dos_condiciones(cliente, auth, datos):
    """AND: con las horas cumplidas pero sin los días transcurridos, no pasa nada."""
    equipo, medidor, tipo = await equipo_con_medidor(cliente, auth, datos, factor_salto="100")
    await incremento_esperado(cliente, auth, medidor, 100)
    # Fecha base de hoy: faltan 90 días para que se cumpla el trigger de tiempo.
    plan = await _plan_combinado(cliente, auth, equipo, tipo, umbral=100, dias=90, logica="AND")
    r = await lectura(cliente, auth, medidor, "150", dias_atras=1)
    assert r["folios_generados"] == [], r
    sim = (await cliente.get(f"/api/planes/{plan['id']}/simulacion", headers=await auth(AP))).json()
    comb = next(t for t in sim[0]["triggers"] if t["tipo_trigger"] == "combinado")
    # Con AND la fecha es la de la última condición que falta: la de los 90 días.
    assert comb["fecha_estimada"] == (date.today() + timedelta(days=90)).isoformat()
    assert comb["motivo"] == "cuando se cumplan todas"
    # Y con el plan dado de alta hace 90 días, las dos se cumplen.
    r = await cliente.post(f"/api/planes/{plan['id']}/equipos", headers=await auth(AP),
                           json={"equipo_id": equipo["id"], "fecha_base": (date.today() - timedelta(days=91)).isoformat()})
    assert r.status_code == 201, r.text
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        from services import triggers_service

        await triggers_service.evaluar_pendientes(db)
        await db.commit()
    filas = await _filas(cliente, auth, plan, equipo)
    assert len(filas) == 1, filas


async def test_ejecutar_el_plan_reinicia_todos_los_triggers(cliente, auth, datos):
    """§6.9.1: al ejecutarse el plan, **todos** los triggers del combinado se reinician desde esa ejecución."""
    equipo, medidor, tipo = await equipo_con_medidor(cliente, auth, datos, factor_salto="100")
    await incremento_esperado(cliente, auth, medidor, 100)
    plan = await _plan_combinado(cliente, auth, equipo, tipo, umbral=200, dias=30, logica="OR")
    r = await lectura(cliente, auth, medidor, "210", dias_atras=1)
    folio_id = r["folios_generados"][0]["folio_id"]
    # Se cierra con la lectura del folio: 230 h.
    tec = await tecnico_con_habilidades(cliente, auth, TEC, ["refrigeracion", "electricidad"])
    await accion(cliente, auth, DES, folio_id, "asignar", {"tecnico_id": tec})
    await accion(cliente, auth, TEC, folio_id, "en-camino", {"geolat": 19.4, "geolng": -99.1})
    await accion(cliente, auth, TEC, folio_id, "confirmar-llegada", {"geolat": 19.4, "geolng": -99.1})
    await lectura(cliente, auth, medidor, "230", email=TEC, folio_id=folio_id)
    folio = (await detalle(cliente, auth, folio_id))["folio"]
    rid = await _respuesta_atencion_con_firma(cliente, auth, datos, folio)
    await cliente.post(f"/api/folios/{folio_id}/atencion", headers=await auth(TEC), json={"respuesta_id": rid})
    await accion(cliente, auth, TEC, folio_id, "cerrar", {"notas": "Revisión del combinado concluida"})
    d = (await cliente.get(f"/api/planes/{plan['id']}", headers=await auth(AP))).json()
    ep = d["equipos"][0]
    # Las dos referencias se movieron a la ejecución: la fecha y el valor del medidor.
    assert ep["fecha_ultima_ejecucion"] == date.today().isoformat()
    assert Decimal(ep["ultimo_valor_medidor"]) == 230
    # El trigger de tiempo vuelve a contar 30 días desde hoy; el del medidor es un hito ya atendido.
    sim = (await cliente.get(f"/api/planes/{plan['id']}/simulacion", headers=await auth(AP))).json()
    por_clave = {t["clave"]: t for t in sim[0]["triggers"]}
    assert por_clave["t1"]["fecha_estimada"] == (date.today() + timedelta(days=30)).isoformat()
    assert por_clave["t2"]["fecha_estimada"] is None and "atendido" in por_clave["t2"]["motivo"]
    assert por_clave["t3"]["fecha_estimada"] == por_clave["t1"]["fecha_estimada"]   # OR: lo que ocurra primero
    # Y por más horas que pase, no vuelve a nacer un folio hasta los 30 días.
    r = await lectura(cliente, auth, medidor, "900")
    assert r["folios_generados"] == []


async def test_validacion_del_combinado(cliente, auth, datos):
    _equipo, _medidor, tipo = await equipo_con_medidor(cliente, auth, datos)
    # Apuntar a un trigger que no está en el plan.
    r = await nuevo_plan(cliente, auth, esperado=422, triggers=[
        {"tipo_trigger": "tiempo_fijo", "clave": "t1", "parametros_json": {"cada_dias": 30}},
        {"tipo_trigger": "combinado", "clave": "t2", "parametros_json": {"triggers_claves": ["t1", "t9"], "logica": "OR"}}])
    assert r["codigo"] == "TRIGGER_INVALIDO" and "t9" in r["mensaje"]
    # Una sola condición no es un combinado.
    r = await nuevo_plan(cliente, auth, esperado=422, triggers=[
        {"tipo_trigger": "tiempo_fijo", "clave": "t1", "parametros_json": {"cada_dias": 30}},
        {"tipo_trigger": "combinado", "clave": "t2", "parametros_json": {"triggers_claves": ["t1"], "logica": "OR"}}])
    assert r["codigo"] == "TRIGGER_INVALIDO" and "dos condiciones" in r["mensaje"]
    # Lógica inválida.
    r = await nuevo_plan(cliente, auth, esperado=422, triggers=_triggers(tipo["id"], logica="XOR"))
    assert r["codigo"] == "TRIGGER_INVALIDO" and "OR" in r["mensaje"]


async def test_la_clave_del_trigger_sobrevive_a_la_edicion(cliente, auth, datos):
    """Antes una edición borraba y recreaba los triggers: el combinado se quedaba apuntando a ids inexistentes."""
    equipo, _medidor, tipo = await equipo_con_medidor(cliente, auth, datos)
    plan = await _plan_combinado(cliente, auth, equipo, tipo)
    d = (await cliente.get(f"/api/planes/{plan['id']}", headers=await auth(AP))).json()
    ids_antes = {t["clave"]: t["id"] for t in d["triggers"]}
    r = await cliente.put(f"/api/planes/{plan['id']}", headers=await auth(AP), json={
        "triggers": [{**t, "parametros_json": {**t["parametros_json"], "cada_dias": 120}} if t["clave"] == "t1" else t
                     for t in d["triggers"]]})
    assert r.status_code == 200, r.text
    ids_despues = {t["clave"]: t["id"] for t in r.json()["triggers"]}
    assert ids_antes == ids_despues
    comb = next(t for t in r.json()["triggers"] if t["clave"] == "t3")
    assert comb["parametros_json"]["triggers_ids"] == [ids_antes["t1"], ids_antes["t2"]]
    assert next(t for t in r.json()["triggers"] if t["clave"] == "t1")["parametros_json"] == {"cada_dias": 120}
    # Quitar un trigger lo borra; el combinado que lo nombraba ya no se puede guardar.
    r = await cliente.put(f"/api/planes/{plan['id']}", headers=await auth(AP), json={
        "triggers": [t for t in d["triggers"] if t["clave"] != "t2"]})
    assert r.status_code == 422 and r.json()["codigo"] == "TRIGGER_INVALIDO"
