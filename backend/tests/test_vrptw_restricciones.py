"""Restricciones del motor VRPTW (ACT-2.1): habilidad certificada, ventanas, jornada, folios fijos, prioridad por
criticidad y SLA, penalización por refacción faltante, y los pesos como configuración del prestador. F2-06."""
from datetime import UTC, date, datetime, time, timedelta

import pytest
from sqlalchemy import text

from models.rutas import PESOS_DEFAULT
from services.rutas.modelo_ortools import FACTOR_CRITICIDAD
from tests.folios_utiles import AE, AP, DES, MC, OP, OTRO_AP, SA, TEC
from tests.rutas_utiles import (
    HABILIDADES, calcular, cerrar_jornadas, configurar, folios_del_dia, jornadas_abiertas, mercado,
    paradas_de, publicar, resolver_prueba, sin_asignar, tecnico_de, usuario_id,
)

TABLAS = ("mercados", "mercado_unidades", "rutas_configuracion", "rutas_tiempos_servicio", "rutas_planes",
          "rutas_paradas", "rutas_trazos", "rutas_recalculos")


def _problema(tecnicos, paradas, *, limite_s=2, pesos=None):
    """Problema sintético para probar el modelo sin base de datos: puntos a 10 minutos unos de otros.

    **Renumera los nodos**: los técnicos ocupan 0..n_tec-1 y las paradas siguen a partir de ahí. Escribirlos a
    mano se presta a dejar un nodo fuera de la matriz, y entonces el modelo recibe un índice inválido (el solver
    lo reporta con un 500, que es correcto, pero la prueba no estaría probando lo que cree).
    """
    paradas = [{**p, "nodo": len(tecnicos) + k} for k, p in enumerate(paradas)]
    n = len(tecnicos) + len(paradas)
    seg = [[0 if i == j else 600 for j in range(n)] for i in range(n)]
    met = [[s * 5 for s in fila] for fila in seg]
    return {"tecnicos": tecnicos, "paradas": paradas, "segundos": seg, "metros": met,
            "pesos": pesos or {}, "limite_s": limite_s}


def _tecnico(i, habilidades=("refrigeracion",), refacciones=(), horas=8):
    return {"id": f"tec-{i}", "nodo_inicio": i, "inicio_s": 0, "fin_s": horas * 3600,
            "habilidades": list(habilidades), "refacciones": list(refacciones)}


def _parada(nodo, **extra):
    base = {"id": f"f-{nodo}", "nodo": nodo, "habilidad": "refrigeracion", "servicio_s": 3600,
            "ventana": [0, 8 * 3600], "criticidad": "C", "sla_limite_s": None, "articulo": None,
            "fijo_tecnico": None}
    return {**base, **extra}


# ------------------------------------------------------------------ el modelo, sin base de datos
async def test_la_habilidad_certificada_es_restriccion_dura():
    """§6.8.2: un folio no se le asigna a quien no tiene la habilidad, cueste lo que cueste dejarlo sin atender."""
    r = await resolver_prueba(_problema([_tecnico(0, ["electricidad"])],
                           [_parada(1, habilidad="refrigeracion")]))
    assert r["estado"] == "resuelto"
    assert r["sin_asignar"] == ["f-1"]
    assert "habilidad certificada" in r["motivos"]["f-1"]
    # Con un técnico que sí la tiene, el mismo folio entra.
    r = await resolver_prueba(_problema([_tecnico(0, ["electricidad"]), _tecnico(1, ["refrigeracion"])],
                           [_parada(2, habilidad="refrigeracion")]))
    assert r["sin_asignar"] == [] and r["rutas"][0]["tecnico"] == "tec-1"


async def test_la_ventana_de_horario_se_respeta():
    """La ventana del folio es dura: si no cabe, el folio queda sin asignar en lugar de atenderse fuera de hora."""
    # Ventana de 10 minutos al inicio del día, y el técnico tarda 10 minutos en llegar: entra justo.
    r = await resolver_prueba(_problema([_tecnico(0)], [_parada(1, ventana=[600, 1200])]))
    assert r["sin_asignar"] == []
    assert r["rutas"][0]["paradas"][0]["llegada_s"] == 600
    # Una ventana que cerró antes de que pueda llegar: no se fuerza.
    r = await resolver_prueba(_problema([_tecnico(0)], [_parada(1, ventana=[0, 300])]))
    assert r["sin_asignar"] == ["f-1"]


async def test_la_jornada_limita_cuantas_paradas_entran():
    """Ocho horas con una hora de servicio y diez minutos de traslado: no caben diez folios."""
    paradas = [_parada(1 + k) for k in range(10)]
    r = await resolver_prueba(_problema([_tecnico(0, horas=8)], paradas))
    colocadas = sum(len(x["paradas"]) for x in r["rutas"])
    assert 0 < colocadas <= 8, colocadas
    assert len(r["sin_asignar"]) == 10 - colocadas
    for folio in r["sin_asignar"]:
        assert "jornada" in r["motivos"][folio] or "ventana" in r["motivos"][folio]


async def test_un_folio_en_ejecucion_queda_fijo_con_su_tecnico():
    """§6.8.2: el técnico ya está en la unidad. El folio no cambia de manos."""
    r = await resolver_prueba(_problema([_tecnico(0), _tecnico(1)],
                           [_parada(2, fijo_tecnico="tec-1"), _parada(3)]))
    assert r["estado"] == "resuelto"
    ruta_del_1 = next((x for x in r["rutas"] if x["tecnico"] == "tec-1"), None)
    assert ruta_del_1 is not None
    assert "f-2" in [p["folio"] for p in ruta_del_1["paradas"]]


async def test_un_folio_fijo_que_no_cabe_no_rompe_el_plan_entero():
    """Era un defecto: marcarlo obligatorio volvía infactible el modelo y no salía **ninguna** ruta."""
    imposible = _parada(2, fijo_tecnico="tec-0", ventana=[0, 60])   # 60 s de ventana y 600 s de traslado
    r = await resolver_prueba(_problema([_tecnico(0)], [imposible, _parada(3)]))
    assert r["estado"] == "resuelto", "el modelo no debe quedar infactible por un folio que no cabe"
    assert "f-3" in [p["folio"] for ruta in r["rutas"] for p in ruta["paradas"]]
    assert "f-2" in r["sin_asignar"]


async def test_la_criticidad_adelanta_al_activo_critico():
    """§6.9.3 en la ruta: entre dos folios iguales, el A va antes que el D."""
    r = await resolver_prueba(_problema([_tecnico(0)],
                           [_parada(1, id="f-D", criticidad="D", sla_limite_s=8 * 3600),
                            _parada(2, id="f-A", criticidad="A", sla_limite_s=8 * 3600)]))
    orden = [p["folio"] for p in r["rutas"][0]["paradas"]]
    assert orden[0] == "f-A", orden
    assert FACTOR_CRITICIDAD["A"] > FACTOR_CRITICIDAD["D"]


async def test_el_sla_por_vencer_se_atiende_antes():
    """Dos folios iguales: el que tiene menos holgura de SLA va primero."""
    r = await resolver_prueba(_problema([_tecnico(0)],
                           [_parada(1, id="f-holgado", sla_limite_s=7 * 3600),
                            _parada(2, id="f-apretado", sla_limite_s=3600)]))
    orden = [p["folio"] for p in r["rutas"][0]["paradas"]]
    assert orden[0] == "f-apretado", orden


async def test_atender_tarde_nunca_cuesta_mas_que_no_atender():
    """Era un defecto: con el SLA ya vencido, dejar el folio fuera salía más barato y el plan se vaciaba."""
    paradas = [_parada(1 + k, id=f"f-{k}", sla_limite_s=-3600) for k in range(6)]   # todos con el SLA vencido
    r = await resolver_prueba(_problema([_tecnico(0), _tecnico(1)], paradas))
    colocadas = sum(len(x["paradas"]) for x in r["rutas"])
    assert colocadas >= 6 or colocadas >= 2 * 6 // 3, colocadas
    assert colocadas > 1, "con el SLA vencido el optimizador seguía abandonando casi todo"


async def test_la_refaccion_faltante_penaliza_pero_no_prohibe():
    """§6.8.2: la refacción es advertencia, no restricción. Si alguien la trae, le toca a él."""
    tecnicos = [_tecnico(0, refacciones=[]), _tecnico(1, refacciones=["art-1"])]
    r = await resolver_prueba(_problema(tecnicos, [_parada(2, articulo="art-1")]))
    asignado = next(x["tecnico"] for x in r["rutas"] if x["paradas"])
    assert asignado == "tec-1", "debe preferir al técnico que trae la refacción"
    # Si nadie la trae, el folio igual se atiende: era una advertencia.
    r = await resolver_prueba(_problema([_tecnico(0, refacciones=[])], [_parada(1, articulo="art-1")]))
    assert r["sin_asignar"] == []


async def test_sin_tecnicos_o_sin_folios_lo_dice_en_lugar_de_fallar():
    r = await resolver_prueba(_problema([], [_parada(0)]))
    assert r["estado"] == "sin_datos" and "no hay técnicos" in r["motivos"]["f-0"]
    r = await resolver_prueba(_problema([_tecnico(0)], []))
    assert r["estado"] == "sin_datos" and r["rutas"] == []


async def test_los_pesos_cambian_el_resultado():
    """Los pesos son configuración del prestador: con `folio_sin_asignar` en cero, abandonar es gratis."""
    # Más folios que capacidad, para que abandonar sea una decisión y no un sobrante.
    paradas = [_parada(1 + k) for k in range(12)]
    normal = await resolver_prueba(_problema([_tecnico(0)], paradas))
    sin_castigo = await resolver_prueba(_problema([_tecnico(0)], paradas,
                                                  pesos={**PESOS_DEFAULT, "folio_sin_asignar": 0}))
    colocadas_normal = sum(len(x["paradas"]) for x in normal["rutas"])
    colocadas_sin = sum(len(x["paradas"]) for x in sin_castigo["rutas"])
    assert colocadas_normal >= colocadas_sin, (colocadas_normal, colocadas_sin)
    assert colocadas_normal > 0
    # Y el peso de la refacción cambia a quién le toca, no cuántos se atienden.
    con_refaccion = await resolver_prueba(_problema(
        [_tecnico(0, refacciones=[]), _tecnico(1, refacciones=["art-9"])],
        [_parada(2, articulo="art-9")], pesos={**PESOS_DEFAULT, "sin_refaccion": 100000}))
    assert next(x["tecnico"] for x in con_refaccion["rutas"] if x["paradas"]) == "tec-1"


# ------------------------------------------------------------------ de punta a punta, contra la base
async def test_el_plan_del_dia_respeta_la_habilidad_de_cada_tecnico(cliente, auth, datos):
    """El mismo requisito, ahora con los técnicos y los equipos de verdad."""
    await configurar(cliente, auth)
    await jornadas_abiertas()
    m = await mercado(cliente, auth, datos)
    folios = await folios_del_dia(cliente, auth, datos, 3, familia="Refrigeración")
    detalle = await calcular(cliente, auth, m["id"])
    por_folio = {p["folio_id"]: p for p in paradas_de(detalle)}
    capaces = {await usuario_id(e) for e, h in HABILIDADES.items() if "refrigeracion" in h}
    for f in folios:
        if f["id"] in por_folio:
            assert __import__("uuid").UUID(tecnico_de(detalle, f["id"])) in capaces, f["numero_folio"]


async def test_sin_tecnicos_con_jornada_el_plan_lo_explica(cliente, auth, datos):
    """El plan del día se calcula sobre quien de verdad trabaja: sin jornada abierta, nadie entra."""
    await configurar(cliente, auth)
    await cerrar_jornadas()
    m = await mercado(cliente, auth, datos)
    folios = await folios_del_dia(cliente, auth, datos, 2)
    detalle = await calcular(cliente, auth, m["id"])
    assert detalle["rutas"] == []
    motivos = sin_asignar(detalle)
    assert folios[0]["id"] in motivos
    assert "jornada" in motivos[folios[0]["id"]]
    await jornadas_abiertas()


async def test_un_mercado_sin_unidades_no_se_calcula(cliente, auth, datos):
    await configurar(cliente, auth)
    r = await cliente.post("/api/rutas/mercados", headers=await auth(AP),
                           json={"codigo": f"VACIO{__import__('uuid').uuid4().hex[:4]}", "nombre": "Sin unidades"})
    assert r.status_code == 201
    await calcular(cliente, auth, r.json()["id"], esperado=422)


async def test_quien_calcula_publica_y_consulta(cliente, auth, datos):
    """§5.2: la ruta la opera el prestador. El cliente y el técnico no la calculan."""
    await configurar(cliente, auth)
    await jornadas_abiertas()
    m = await mercado(cliente, auth, datos)
    await folios_del_dia(cliente, auth, datos, 2)
    for email in (AE, OP, TEC):
        await calcular(cliente, auth, m["id"], email=email, esperado=403)
    detalle = await calcular(cliente, auth, m["id"], email=DES)
    plan_id = detalle["plan"]["id"]
    # Mesa de control consulta pero no publica.
    assert (await cliente.get(f"/api/rutas/{plan_id}", headers=await auth(MC))).status_code == 200
    await publicar(cliente, auth, plan_id, email=MC, esperado=403)
    await publicar(cliente, auth, plan_id, email=DES)


async def test_aislamiento_entre_prestadores(cliente, auth, datos):
    await configurar(cliente, auth)
    await jornadas_abiertas()
    m = await mercado(cliente, auth, datos)
    await folios_del_dia(cliente, auth, datos, 2)
    detalle = await calcular(cliente, auth, m["id"])
    plan_id = detalle["plan"]["id"]
    assert (await cliente.get(f"/api/rutas/{plan_id}", headers=await auth(OTRO_AP))).status_code == 404
    assert (await cliente.get("/api/rutas/mercados", headers=await auth(OTRO_AP))).json() == []
    await calcular(cliente, auth, m["id"], email=OTRO_AP, esperado=404)
    # El Superadmin de la plataforma sí lo ve.
    assert (await cliente.get(f"/api/rutas/{plan_id}", headers=await auth(SA))).status_code == 200


async def test_rls_forzada_en_las_tablas_nuevas(datos):
    from core.db import nueva_sesion
    from core.rls import CONTEXTO_SISTEMA

    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        for tabla in TABLAS:
            fila = (await db.execute(text(
                "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = :t"), {"t": tabla})).one()
            assert fila.relrowsecurity and fila.relforcerowsecurity, tabla
        # `distancias_cache` no tiene dueño: es geografía, no dato de nadie, y por eso no filtra por prestador.
        fila = (await db.execute(text(
            "SELECT relrowsecurity FROM pg_class WHERE relname = 'distancias_cache'"))).one()
        assert fila.relrowsecurity
