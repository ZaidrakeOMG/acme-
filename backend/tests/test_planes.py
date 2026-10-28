"""Planes de mantenimiento (§6.9.1): CRUD con triggers de Fase 1, 403 para triggers de Fase 2, cálculo de próxima fecha,
asignación a equipos, versión al editar, roles y aislamiento por prestador."""
from datetime import date

import pytest

from services import planes_service
from tests.folios_utiles import AE, AP, AUN, DES, OP, OTRO_AP, TEC, nuevo_equipo
from tests.preventivos_utiles import habilidad_id, nuevo_plan, plan_en_equipo


def test_proxima_fecha_triggers_fase_1():
    p = planes_service.proxima_fecha_trigger
    assert p("tiempo_fijo", {"cada_dias": 30}, date(2026, 1, 1), date(2026, 1, 1)) == date(2026, 1, 31)
    assert p("tiempo_fijo", {"cada": 3, "unidad": "meses"}, date(2026, 1, 31), date(2026, 1, 31)) == date(2026, 4, 30)  # fin de mes recortado
    assert p("tiempo_fijo", {"cada": 2, "unidad": "semanas"}, date(2026, 3, 1), date(2026, 3, 1)) == date(2026, 3, 15)
    assert p("calendario", {"mes": 1, "dia": 15}, date(2026, 1, 15), date(2026, 1, 15)) == date(2027, 1, 15)  # la misma fecha ya pasó
    assert p("calendario", {"mes": 1, "dia": 15}, date(2026, 6, 1), date(2026, 6, 1)) == date(2027, 1, 15)
    assert p("calendario", {"fechas": ["2026-03-01", "2026-09-01"]}, date(2026, 3, 1), date(2026, 3, 1)) == date(2026, 9, 1)
    # Tiempo fijo: última ejecución + intervalo aunque quede en el pasado (vencido → la tarea nocturna lo genera de inmediato).
    assert p("tiempo_fijo", {"cada_dias": 30}, date(2025, 1, 1), date(2026, 6, 1)) == date(2025, 1, 31)


def test_validacion_de_triggers():
    with pytest.raises(Exception) as e:
        planes_service.validar_trigger("tiempo_fijo", {"cada": 0, "unidad": "meses"})
    assert "cada" in str(e.value).lower()
    with pytest.raises(Exception) as e:
        planes_service.validar_trigger("calendario", {"mes": 13, "dia": 1})
    assert "TRIGGER_INVALIDO" in str(e.value)


async def test_crear_plan_completo_y_detalle(cliente, auth, datos):
    hab = await habilidad_id(cliente, auth, "refrigeracion")
    plan = await nuevo_plan(cliente, auth, trigger={"tipo_trigger": "tiempo_fijo", "parametros_json": {"cada": 3, "unidad": "meses"}},
                            tareas=[{"orden": 2, "descripcion": "Medir temperatura", "tiempo_estimado_min": 10},
                                    {"orden": 1, "descripcion": "Limpiar condensador", "tiempo_estimado_min": 30, "habilidad_requerida_id": hab}],
                            materiales=[{"descripcion": "Refrigerante", "cantidad_estandar": "0.5", "unidad": "kg"}])
    assert plan["version"] == 1 and plan["estado"] == "activo" and plan["prestador_id"] == str(datos["prestador"])
    assert [t["orden"] for t in plan["tareas"]] == [1, 2] and plan["tareas"][0]["habilidad_requerida_id"] == hab
    assert plan["triggers"][0]["parametros_json"] == {"cada": 3, "unidad": "meses"} and plan["materiales"][0]["unidad"] == "kg"
    d = (await cliente.get(f"/api/planes/{plan['id']}", headers=await auth(DES))).json()
    assert d["id"] == plan["id"] and d["tipo_equipo_nombre"]
    # Admin empresa y Admin UN consultan los planes de sus prestadores; el operador y el técnico no.
    assert any(p["id"] == plan["id"] for p in (await cliente.get("/api/planes", headers=await auth(AE))).json())
    assert (await cliente.get("/api/planes", headers=await auth(AUN))).status_code == 200
    assert (await cliente.get("/api/planes", headers=await auth(OP))).status_code == 403
    assert (await cliente.post("/api/planes", headers=await auth(TEC), json={})).status_code in (403, 422)


async def test_trigger_fase_2_responde_403(cliente, auth, datos):
    for tipo, params in (("medidor_umbral", {"umbral": 500}), ("medidor_intervalo", {"cada": 1000}), ("evento", {"evento": "alarma"}), ("combinado", {})):
        r = await nuevo_plan(cliente, auth, trigger={"tipo_trigger": tipo, "parametros_json": params}, esperado=403)
        assert r["codigo"] == "TRIGGER_FASE_2", r


async def test_asignar_plan_a_equipo_calcula_proxima(cliente, auth, datos):
    plan = await nuevo_plan(cliente, auth, trigger={"tipo_trigger": "tiempo_fijo", "parametros_json": {"cada_dias": 30}})
    hoy = date.today()
    equipo, ep = await plan_en_equipo(cliente, auth, datos, plan, fecha_base=hoy)
    assert ep["equipo_id"] == equipo["id"] and ep["activo"] and date.fromisoformat(ep["fecha_proxima_ejecucion"]) == planes_service.proxima_fecha_trigger("tiempo_fijo", {"cada_dias": 30}, hoy, hoy)
    # Equipo de otro tipo → 422; repetir el mismo equipo no duplica la fila (la actualiza).
    otro = await nuevo_equipo(cliente, auth, datos, familia="Climatización")
    r = await cliente.post(f"/api/planes/{plan['id']}/equipos", headers=await auth(AP), json={"equipo_id": otro["id"]})
    assert r.status_code == 422 and r.json()["codigo"] == "EQUIPO_INVALIDO"
    r = await cliente.post(f"/api/planes/{plan['id']}/equipos", headers=await auth(AP), json={"equipo_id": equipo["id"], "fecha_base": hoy.isoformat()})
    assert r.status_code == 201 and r.json()["id"] == ep["id"], r.text
    d = (await cliente.get(f"/api/planes/{plan['id']}", headers=await auth(AP))).json()
    assert [e["equipo_id"] for e in d["equipos"]] == [equipo["id"]]
    # Desactivar y volver a asignar reactiva la fila.
    assert (await cliente.delete(f"/api/planes/{plan['id']}/equipos/{equipo['id']}", headers=await auth(DES))).status_code == 200
    d = (await cliente.get(f"/api/planes/{plan['id']}", headers=await auth(AP))).json()
    assert d["equipos"][0]["activo"] is False
    r = await cliente.post(f"/api/planes/{plan['id']}/equipos", headers=await auth(AP), json={"equipo_id": equipo["id"]})
    assert r.status_code == 201 and r.json()["activo"] is True


async def test_editar_plan_sube_version_y_reemplaza_hijos(cliente, auth, datos):
    plan = await nuevo_plan(cliente, auth)
    equipo, ep = await plan_en_equipo(cliente, auth, datos, plan, fecha_base=date(2026, 1, 1))
    r = await cliente.put(f"/api/planes/{plan['id']}", headers=await auth(DES), json={
        "nombre": "Plan editado", "triggers": [{"tipo_trigger": "calendario", "parametros_json": {"mes": 12, "dia": 1}}],
        "tareas": [{"descripcion": "Única tarea", "tiempo_estimado_min": 5}], "materiales": []})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["version"] == 2 and d["nombre"] == "Plan editado" and len(d["tareas"]) == 1 and d["materiales"] == [] and d["triggers"][0]["tipo_trigger"] == "calendario"
    # La próxima fecha del equipo se recalcula con el nuevo trigger.
    assert date.fromisoformat(d["equipos"][0]["fecha_proxima_ejecucion"]).month == 12
    r = await cliente.put(f"/api/planes/{plan['id']}", headers=await auth(AP), json={"triggers": [{"tipo_trigger": "medidor_umbral", "parametros_json": {"umbral": 10}}]})
    assert r.status_code == 403 and r.json()["codigo"] == "TRIGGER_FASE_2"
    r = await cliente.put(f"/api/planes/{plan['id']}", headers=await auth(AP), json={"estado": "inactivo"})
    assert r.status_code == 200 and r.json()["estado"] == "inactivo" and r.json()["version"] == 3


async def test_aislamiento_por_prestador(cliente, auth, datos):
    plan = await nuevo_plan(cliente, auth)
    assert (await cliente.get(f"/api/planes/{plan['id']}", headers=await auth(OTRO_AP))).status_code == 404
    assert all(p["id"] != plan["id"] for p in (await cliente.get("/api/planes", headers=await auth(OTRO_AP))).json())
    r = await cliente.put(f"/api/planes/{plan['id']}", headers=await auth(OTRO_AP), json={"nombre": "Ajeno"})
    assert r.status_code == 404
