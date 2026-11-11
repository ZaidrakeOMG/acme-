"""Ayudas compartidas por las pruebas de P06 (planes, calendario, ciclo de preventivos y reasignaciones)."""
import uuid
from datetime import date

from tests.folios_utiles import AP, DES, nuevo_equipo, tipo_equipo


async def habilidad_id(cliente, auth, clave: str) -> str:
    habs = (await cliente.get("/api/catalogos/habilidades", headers=await auth(AP))).json()
    return next(h["id"] for h in habs if h["clave"] == clave)


async def nuevo_plan(cliente, auth, *, familia="Refrigeración", indice=0, trigger=None, triggers=None, tareas=None, materiales=None, email=AP, esperado=201, **extra) -> dict:
    """`triggers` (lista) para un plan con varias condiciones, como el combinado de F2-04; `trigger` para uno solo."""
    tipo = await tipo_equipo(cliente, auth, familia, indice)
    cuerpo = {"nombre": f"Plan {uuid.uuid4().hex[:6]}", "descripcion": "Plan de prueba", "tipo_equipo_id": tipo["id"], "tiempo_ventana_dias": 5,
              "triggers": triggers if triggers is not None else [trigger or {"tipo_trigger": "tiempo_fijo", "parametros_json": {"cada_dias": 30}}],
              "tareas": tareas if tareas is not None else [{"orden": 1, "descripcion": "Revisión general", "tiempo_estimado_min": 20}],
              "materiales": materiales if materiales is not None else [{"descripcion": "Trapo industrial", "cantidad_estandar": "2", "unidad": "pieza"}], **extra}
    r = await cliente.post("/api/planes", headers=await auth(email), json=cuerpo)
    assert r.status_code == esperado, r.text
    return r.json()


async def plan_en_equipo(cliente, auth, datos, plan: dict, *, familia="Refrigeración", indice=0, fecha_base: date | None = None, equipo=None) -> tuple[dict, dict]:
    equipo = equipo or await nuevo_equipo(cliente, auth, datos, familia=familia, indice=indice)
    r = await cliente.post(f"/api/planes/{plan['id']}/equipos", headers=await auth(AP),
                           json={"equipo_id": equipo["id"], "fecha_base": fecha_base.isoformat() if fecha_base else None})
    assert r.status_code == 201, r.text
    return equipo, r.json()


async def generar(cliente, auth, hoy: date, horizonte=7, email=DES) -> dict:
    r = await cliente.post("/api/preventivos/generar", headers=await auth(email), params={"hoy": hoy.isoformat(), "horizonte_dias": horizonte})
    assert r.status_code == 200, r.text
    return r.json()


async def calendario(cliente, auth, email=DES, **params) -> list[dict]:
    r = await cliente.get("/api/preventivos/calendario", headers=await auth(email), params={k: v for k, v in params.items() if v is not None})
    assert r.status_code == 200, r.text
    return r.json()


async def folio_preventivo_generado(cliente, auth, datos, *, fecha: date, familia="Refrigeración", tareas=None) -> tuple[dict, dict, dict]:
    """Plan + equipo nuevo + generación en `fecha`: devuelve (plan, equipo, fila del calendario con folio)."""
    plan = await nuevo_plan(cliente, auth, familia=familia, tareas=tareas)
    equipo, _ = await plan_en_equipo(cliente, auth, datos, plan, familia=familia, fecha_base=fecha)  # cada 30 días desde fecha_base
    hoy = date(fecha.year, fecha.month, fecha.day)
    from services.planes_service import proxima_fecha_trigger
    proxima = proxima_fecha_trigger("tiempo_fijo", {"cada_dias": 30}, fecha, hoy)
    resumen = await generar(cliente, auth, proxima, 0)
    assert resumen["planes"] >= 1, resumen
    filas = [c for c in await calendario(cliente, auth, desde=proxima.isoformat(), hasta=proxima.isoformat()) if c["equipo_id"] == equipo["id"]]
    assert len(filas) == 1 and filas[0]["folio_id"], filas
    return plan, equipo, filas[0]


async def razones(cliente, auth, email=DES) -> list[dict]:
    r = await cliente.get("/api/reasignaciones/razones", headers=await auth(email))
    assert r.status_code == 200, r.text
    return r.json()
