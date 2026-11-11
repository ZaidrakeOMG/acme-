"""Trigger por evento (§6.9.1): el catálogo cerrado de `eventos_trigger_catalogo` y que cada clave dispare su plan
con el gancho que le corresponde, sin sondeo. F2-04.

Las cinco claves y lo que las dispara:
- `falla_correctiva_grave` — cierre de un correctivo del equipo con severidad de la lista configurada.
- `fallas_repetidas` — N correctivos cerrados del equipo en X días.
- `equipo_instalado` — alta del equipo por instalación de activo (P08), con sus días de gracia.
- `reemplazo_componente` — refacción consumida en un folio del equipo (de una categoría, si se configura).
- `cambio_medidor` — reemplazo del medidor físico (no un reinicio del marcador).
"""
from datetime import date
from decimal import Decimal

from tests.folios_utiles import AE, AP, DES, nuevo_equipo
from tests.medidores_utiles import correctivo_cerrado, equipo_con_medidor, lectura
from tests.preventivos_utiles import calendario, nuevo_plan


async def _plan_evento(cliente, auth, equipo, parametros, *, familia="Refrigeración") -> dict:
    plan = await nuevo_plan(cliente, auth, familia=familia,
                            trigger={"tipo_trigger": "evento", "parametros_json": parametros})
    r = await cliente.post(f"/api/planes/{plan['id']}/equipos", headers=await auth(AP),
                           json={"equipo_id": equipo["id"]})
    assert r.status_code == 201, r.text
    return plan


async def _folios_del_plan(cliente, auth, plan, equipo) -> list[dict]:
    return [c for c in await calendario(cliente, auth, AE)
            if c["plan_id"] == plan["id"] and c["equipo_id"] == equipo["id"]]


async def test_falla_correctiva_grave_dispara_la_inspeccion(cliente, auth, datos):
    """Ejemplo literal de §6.9.1: inspección después de cualquier falla correctiva grave."""
    equipo = await nuevo_equipo(cliente, auth, datos)
    plan = await _plan_evento(cliente, auth, equipo,
                              {"evento": "falla_correctiva_grave", "severidades": ["alta", "critica"]})
    assert await _folios_del_plan(cliente, auth, plan, equipo) == []
    await correctivo_cerrado(cliente, auth, datos, equipo)
    filas = await _folios_del_plan(cliente, auth, plan, equipo)
    assert len(filas) == 1, filas
    assert filas[0]["origen"] == "evento" and filas[0]["fecha_programada"] == date.today().isoformat()
    assert filas[0]["estado"] == "generado" and filas[0]["estado_folio"] == "autorizado"
    assert "evento falla_correctiva_grave" in filas[0]["descripcion"]


async def test_falla_grave_no_dispara_si_la_severidad_no_esta_en_la_lista(cliente, auth, datos):
    equipo = await nuevo_equipo(cliente, auth, datos)
    plan = await _plan_evento(cliente, auth, equipo, {"evento": "falla_correctiva_grave", "severidades": ["muy_baja"]})
    await correctivo_cerrado(cliente, auth, datos, equipo)   # la falla demo es crítica, no muy baja
    assert await _folios_del_plan(cliente, auth, plan, equipo) == []


async def test_fallas_repetidas_cuenta_en_la_ventana(cliente, auth, datos):
    equipo = await nuevo_equipo(cliente, auth, datos)
    plan = await _plan_evento(cliente, auth, equipo, {"evento": "fallas_repetidas", "cantidad": 2, "dias": 30})
    await correctivo_cerrado(cliente, auth, datos, equipo)
    # Con una sola falla no alcanza... salvo que el plan del equipo ya tenga un folio abierto por otra razón.
    assert await _folios_del_plan(cliente, auth, plan, equipo) == []
    await correctivo_cerrado(cliente, auth, datos, equipo, falla="No enfría")
    filas = await _folios_del_plan(cliente, auth, plan, equipo)
    assert len(filas) == 1 and filas[0]["origen"] == "evento"
    # El preventivo que nació deja el equipo con un folio abierto, así que ni la nocturna abre otro.
    from core.db import nueva_sesion
    from core.rls import CONTEXTO_SISTEMA
    from services import triggers_service

    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        await triggers_service.evaluar_pendientes(db)
        await db.commit()
    assert len(await _folios_del_plan(cliente, auth, plan, equipo)) == 1


async def test_reemplazo_componente_por_categoria_de_refaccion(cliente, auth, datos):
    """La refacción consumida en un folio del equipo dispara el plan; con categorías configuradas, solo esa."""
    equipo = await nuevo_equipo(cliente, auth, datos)
    plan = await _plan_evento(cliente, auth, equipo, {"evento": "reemplazo_componente", "categorias": []})
    assert await _folios_del_plan(cliente, auth, plan, equipo) == []
    from tests.folios_utiles import TEC, accion, autorizar_sin_flujo, detalle, tecnico_con_habilidades
    from tests.test_folio_estados import _respuesta_atencion_con_firma

    f = await autorizar_sin_flujo(cliente, auth, datos, equipo=equipo)
    tec = await tecnico_con_habilidades(cliente, auth, TEC, ["refrigeracion", "electricidad"])
    await accion(cliente, auth, DES, f["id"], "asignar", {"tecnico_id": tec})
    await accion(cliente, auth, TEC, f["id"], "en-camino", {"geolat": 19.43, "geolng": -99.13})
    await accion(cliente, auth, TEC, f["id"], "confirmar-llegada", {"geolat": 19.43, "geolng": -99.13})
    r = await cliente.post(f"/api/folios/{f['id']}/refacciones", headers=await auth(TEC),
                           json={"descripcion": "Empaque de puerta", "cantidad": "1", "origen": "almacen",
                                 "costo_unitario": "320.00"})
    assert r.status_code == 201, r.text
    folio = (await detalle(cliente, auth, f["id"]))["folio"]
    rid = await _respuesta_atencion_con_firma(cliente, auth, datos, folio)
    await cliente.post(f"/api/folios/{f['id']}/atencion", headers=await auth(TEC), json={"respuesta_id": rid})
    await accion(cliente, auth, TEC, f["id"], "cerrar", {"notas": "Refacción cambiada"})
    filas = await _folios_del_plan(cliente, auth, plan, equipo)
    assert len(filas) == 1 and filas[0]["origen"] == "evento"


async def test_cambio_de_medidor_dispara_el_plan_y_el_reinicio_no(cliente, auth, datos):
    """`cambio_medidor` escucha el reemplazo del medidor físico. Un reinicio del marcador no es un cambio."""
    equipo, medidor, tipo = await equipo_con_medidor(cliente, auth, datos, valor_maximo="1000", factor_salto="100")
    plan = await _plan_evento(cliente, auth, equipo, {"evento": "cambio_medidor", "tipo_medidor_id": tipo["id"]})
    await lectura(cliente, auth, medidor, "900", dias_atras=2)
    r = await cliente.post(f"/api/medidores/{medidor['id']}/cambios", headers=await auth(AP),
                           json={"tipo": "reinicio", "valor_nuevo": "0", "motivo": "El marcador dio la vuelta"})
    assert r.status_code == 201
    assert await _folios_del_plan(cliente, auth, plan, equipo) == []
    r = await cliente.post(f"/api/medidores/{medidor['id']}/cambios", headers=await auth(AP),
                           json={"tipo": "reemplazo_medidor", "valor_nuevo": "0", "motivo": "Horómetro reemplazado",
                                 "numero_serie_nuevo": "HM-NUEVO"})
    assert r.status_code == 201
    filas = await _folios_del_plan(cliente, auth, plan, equipo)
    assert len(filas) == 1 and filas[0]["origen"] == "evento"


async def test_equipo_instalado_con_dias_de_gracia(cliente, auth, datos):
    """`equipo_instalado` (P08 §6.10.7): el plan arranca a los X días de la instalación del activo."""
    from datetime import timedelta

    hace_un_mes = (date.today() - timedelta(days=40)).isoformat()
    equipo = await nuevo_equipo(cliente, auth, datos, fecha_instalacion=hace_un_mes)
    # Con 90 días de gracia todavía no toca; con 30, sí.
    plan_lejano = await _plan_evento(cliente, auth, equipo, {"evento": "equipo_instalado", "dias_despues": 90})
    plan_cercano = await _plan_evento(cliente, auth, equipo, {"evento": "equipo_instalado", "dias_despues": 30})
    from services import triggers_service

    from core.db import nueva_sesion
    from core.rls import CONTEXTO_SISTEMA

    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        await triggers_service.evaluar_pendientes(db)
        await db.commit()
    assert await _folios_del_plan(cliente, auth, plan_lejano, equipo) == []
    filas = await _folios_del_plan(cliente, auth, plan_cercano, equipo)
    assert len(filas) == 1 and filas[0]["origen"] == "evento"


async def test_evento_fuera_del_catalogo_se_rechaza(cliente, auth, datos):
    r = await nuevo_plan(cliente, auth, trigger={"tipo_trigger": "evento", "parametros_json": {"evento": "lo_que_sea"}},
                         esperado=422)
    assert r["codigo"] == "EVENTO_INVALIDO" and "falla_correctiva_grave" in r["mensaje"]
    # Los parámetros también se validan contra el esquema del catálogo.
    r = await nuevo_plan(cliente, auth, esperado=422, trigger={
        "tipo_trigger": "evento", "parametros_json": {"evento": "fallas_repetidas", "cantidad": 1, "dias": 30}})
    assert r["codigo"] == "TRIGGER_INVALIDO" and "2 a 20" in r["mensaje"]
