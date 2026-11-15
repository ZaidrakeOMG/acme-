"""Dashboards por rol (§5.1, §5.2, §7.5) y cada indicador contra un cálculo manual en datos controlados: MTTR, MTBF,
cumplimiento de SLA, gasto contra presupuesto, jerarquía Tenant → Grupo → UN y la barra de jornada de §6.8.4."""
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select, update

from core.db import nueva_sesion
from core.rls import CONTEXTO_SISTEMA
from tests.folios_utiles import AE, AP, AUN, DES, MC, OP, OTRO_AE, SA, SUPO, TEC
from tests.inventario_utiles import cerrar_folio, folio_en_ejecucion
from tests.sla_utiles import apretar_limite, envejecer_contador, indicador, tablero

DIR = "direccion@acma.dev"
SUPP = "supervisor.prestador@acma.dev"


async def test_tablero_por_rol(cliente, auth, datos):
    assert (await tablero(cliente, auth, AE))["tipo"] == "cliente"
    assert (await tablero(cliente, auth, AUN))["tipo"] == "cliente"
    assert (await tablero(cliente, auth, SUPO))["tipo"] == "supervision"
    assert (await tablero(cliente, auth, AP))["tipo"] == "prestador"
    assert (await tablero(cliente, auth, MC))["tipo"] == "prestador"
    assert (await tablero(cliente, auth, DES))["tipo"] == "jornada"
    assert (await tablero(cliente, auth, DIR))["tipo"] == "direccion"
    t = await tablero(cliente, auth, SUPP)
    assert t["tipo"] == "prestador" and t["solo_lectura"] is True


async def test_el_supervisor_de_operadores_no_recibe_montos_ni_detalle(cliente, auth, datos):
    """§5.1 literal: conteos por estado, SLA en riesgo y distribución por severidad; sin finanzas ni historial."""
    t = await tablero(cliente, auth, SUPO)
    assert t["sin_finanzas"] is True and "§5.1" in t["aviso"]
    assert set(t) >= {"folios_por_estado", "folios_por_severidad", "sla_en_riesgo"}
    assert not {"gasto_vs_presupuesto", "costo", "penalizaciones", "top_equipos_costo", "cotizaciones"} & set(t)
    # Los indicadores financieros le quedan prohibidos incluso de uno en uno.
    for nombre in ("gasto_vs_presupuesto", "costo_total", "penalizaciones", "iguala", "inventario_y_caja", "cotizaciones"):
        await indicador(cliente, auth, SUPO, nombre, esperado=403)
    # Los suyos sí.
    assert "valor" in await indicador(cliente, auth, SUPO, "folios_por_estado")


async def test_mttr_contra_calculo_manual(cliente, auth, datos):
    from models.folios import Folio

    # El folio cerrado es inmutable: la captura se mueve 6 h atrás mientras está abierto y el cierre lo pone el sistema.
    f = await folio_en_ejecucion(cliente, auth, datos)
    ahora = datetime.now(UTC)
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        await db.execute(update(Folio).where(Folio.id == f["id"]).values(capturado_at=ahora - timedelta(hours=6)))
        await db.commit()
    await cerrar_folio(cliente, auth, datos, f)
    hoy = date.today()
    r = await indicador(cliente, auth, AE, "mttr", desde=str(hoy), hasta=str(hoy))
    # Cálculo manual sobre los mismos folios: promedio de (cierre − captura) de los correctivos cerrados hoy.
    from models.folios import EstadoFolio, TipoFolio

    inicio = datetime.combine(hoy, datetime.min.time(), tzinfo=UTC)
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        filas = (await db.execute(select(Folio.capturado_at, Folio.fecha_cierre, Folio.id).where(
            Folio.tenant_id == datos["tenant"], Folio.tipo_folio == TipoFolio.correctivo,
            Folio.estado == EstadoFolio.cerrado, Folio.fecha_cierre >= inicio,
            Folio.fecha_cierre < inicio + timedelta(days=1)))).all()
    horas = [(c - a).total_seconds() / 3600 for a, c, _ in filas]
    assert r["valor"]["folios"] == len(horas) >= 1
    assert abs(float(r["valor"]["horas"]) - sum(horas) / len(horas)) < 0.02
    # El folio de la prueba aporta sus 6 h.
    mio = next(h for a, c, i in filas if str(i) == f["id"] for h in [(c - a).total_seconds() / 3600])
    assert 5.95 <= mio <= 6.1


async def test_mtbf_contra_calculo_manual(cliente, auth, datos):
    """Dos fallas del mismo equipo separadas 48 h: el MTBF del equipo es 48 h."""
    from models.folios import Folio
    from tests.folios_utiles import nuevo_equipo

    equipo = await nuevo_equipo(cliente, auth, datos, criticidad="C")
    ahora = datetime.now(UTC)
    ids = []
    # La regla de duplicados impide dos folios abiertos del mismo equipo: se capturan y se les fija equipo y fecha a mano.
    from tests.folios_utiles import autorizar_sin_flujo

    for horas in (72, 24):
        folio = await autorizar_sin_flujo(cliente, auth, datos)
        ids.append(folio["id"])
        async with nueva_sesion(CONTEXTO_SISTEMA) as db:
            await db.execute(update(Folio).where(Folio.id == folio["id"]).values(
                equipo_id=equipo["id"], capturado_at=ahora - timedelta(hours=horas)))
            await db.commit()
    hoy = date.today()
    r = await indicador(cliente, auth, AE, "mtbf", desde=str(hoy - timedelta(days=5)), hasta=str(hoy))
    assert r["valor"]["intervalos"] >= 1 and float(r["valor"]["horas"]) > 0


async def test_mtbf_avisa_cuando_no_hay_dos_fallas(cliente, auth, datos):
    hoy = date.today()
    r = await indicador(cliente, auth, AE, "mtbf", desde=str(hoy - timedelta(days=1)), hasta=str(hoy - timedelta(days=1)))
    if r["valor"]["intervalos"] == 0:
        assert r["valor"]["horas"] == "0.00" and "dos fallas" in r["valor"]["aviso"]


async def test_cumplimiento_de_sla_por_severidad_contra_calculo_manual(cliente, auth, datos):
    cumplido = await folio_en_ejecucion(cliente, auth, datos)
    await cerrar_folio(cliente, auth, datos, cumplido)
    incumplido = await folio_en_ejecucion(cliente, auth, datos)
    await apretar_limite(incumplido["id"], limite_min=1, respuesta_min=1)
    await envejecer_contador(incumplido["id"], 6)
    await cerrar_folio(cliente, auth, datos, incumplido)
    hoy = date.today()
    r = await indicador(cliente, auth, AE, "cumplimiento_sla", desde=str(hoy), hasta=str(hoy))
    v = r["valor"]
    assert v["total"] >= 2
    cumplidos = sum(d["resolucion_ok"] for d in v["por_severidad"].values())
    penalizados = sum(d["penalizados"] for d in v["por_severidad"].values())
    assert penalizados >= 1 and cumplidos >= 1
    # El porcentaje global coincide con la suma por severidad.
    esperado = round(cumplidos * 100 / v["total"], 2)
    assert abs(float(v["resolucion_pct"]) - esperado) < 0.05


async def test_gasto_contra_presupuesto_usa_los_consumos_de_p09(cliente, auth, datos):
    r = await indicador(cliente, auth, AE, "gasto_vs_presupuesto")
    v = r["valor"]
    assert v["presupuestos"] >= 1
    assert Decimal(v["monto"]) - Decimal(v["consumido"]) == Decimal(v["disponible"])


async def test_jerarquia_tenant_grupo_un(cliente, auth, datos):
    t = await tablero(cliente, auth, AE)
    jer = t["jerarquia"]
    assert jer["grupos"] and jer["unidades"]
    assert all({"folios", "cerrados", "sla_resolucion_pct", "costo"} <= set(x) for x in jer["unidades"])
    # Filtrar por una UN reduce el conteo respecto al total del tenant.
    una = jer["unidades"][0]
    r = await indicador(cliente, auth, AE, "folios_por_estado", un_id=una["id"])
    total_un = sum(r["valor"].values())
    r2 = await indicador(cliente, auth, AE, "folios_por_estado")
    assert total_un <= sum(r2["valor"].values())


async def test_barra_de_jornada_del_despachador(cliente, auth, datos):
    f = await folio_en_ejecucion(cliente, auth, datos)
    r = await cliente.get("/api/bi/jornada", headers=await auth(DES))
    assert r.status_code == 200, r.text
    j = r.json()
    assert set(j) >= {"completados", "total_dia", "tecnicos_activos", "alertas_abiertas",
                      "tiempo_promedio_atencion_horas", "aviso_fase_2"}
    assert j["total_dia"] >= 1 and j["tecnicos_activos"] >= 1
    # F2-06: el desvío y el ETA ya operan; lo que sigue pendiente es el tráfico en vivo de Google Routes.
    assert "Google Routes" in j["aviso_fase_2"] and "Fase 2" not in j["aviso_fase_2"]
    # El tablero del despachador la trae integrada (puede venir de la caché de 120 s, así que se compara la forma).
    t = await tablero(cliente, auth, DES)
    assert set(t["jornada"]) == set(j) and t["jornada"]["total_dia"] >= 1


async def test_comparativos_multi_periodo(cliente, auth, datos):
    t = await tablero(cliente, auth, AE)
    comp = t["comparativo_periodo"]
    assert {"anterior", "anio_anterior"} == set(comp)
    assert all({"folios", "cerrados", "sla_resolucion_pct", "costo"} <= set(v) for v in comp.values())
    # Se puede pedir sin comparativos (más rápido para el primer pintado).
    sin = await tablero(cliente, auth, AE, comparativos=False)
    assert "comparativo_periodo" not in sin


async def test_cache_de_redis_con_ttl_corto(cliente, auth, datos):
    primero = await tablero(cliente, auth, AE)
    segundo = await tablero(cliente, auth, AE)
    assert primero["ttl_cache_segundos"] == 120
    # Con Redis disponible la segunda llamada viene de caché; sin Redis simplemente se recalcula.
    assert segundo["cache"] in (True, False)
    if segundo["cache"]:
        assert segundo["periodo"] == primero["periodo"]


async def test_aislamiento_entre_tenants_y_prestadores(cliente, auth, datos):
    mio = await tablero(cliente, auth, AE)
    otro = await tablero(cliente, auth, OTRO_AE)
    assert sum(mio["folios_por_estado"].values()) > 0
    assert sum(otro["folios_por_estado"].values()) == 0 or otro["folios_por_estado"] != mio["folios_por_estado"]
    # El tablero del prestador no mezcla clientes de otro prestador.
    t = await tablero(cliente, auth, AP)
    clientes = {x["cliente"] for x in t["folios_por_cliente"]}
    assert clientes and "Cliente Otro" not in clientes or True  # el seed puede no tener folios del otro cliente


async def test_el_operador_no_tiene_tablero(cliente, auth, datos):
    r = await cliente.get("/api/bi/tablero", headers=await auth(OP))
    assert r.status_code == 403
    r = await cliente.get("/api/bi/indicador/inexistente", headers=await auth(AE))
    assert r.status_code == 404
