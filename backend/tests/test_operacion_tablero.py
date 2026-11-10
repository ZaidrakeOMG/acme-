"""Tablero de operaciones (§6.8.4): paneles de técnicos, folios con contador de SLA, unidades, feed de alertas,
indicadores de jornada, alcance por rol y aislamiento entre prestadores. F2-03."""
from tests.folios_utiles import AE, AP, AUN, DES, MC, OP, OTRO_AP, SA, TEC
from tests.operacion_utiles import CENTRO, enviar, jornada, punto, tablero, tecnico_de


async def test_el_tablero_trae_los_cinco_paneles_de_la_pantalla(cliente, auth, datos):
    await jornada(cliente, auth, TEC)
    await enviar(cliente, auth, [punto(CENTRO, 0, bateria_pct=77)], email=TEC)
    t = await tablero(cliente, auth, DES)

    assert set(t) >= {"tecnicos", "folios", "unidades", "alertas", "indicadores", "parametros", "solo_lectura"}
    mio = next(x for x in t["tecnicos"] if x["nombre"].startswith("Tomás"))
    assert mio["en_jornada"] is True and mio["lat"] is not None and mio["bateria_pct"] == 77
    # El estatus viaja con su texto: la pantalla no depende del color (§6.8.4).
    assert mio["estatus_texto"] in ("En servicio", "En ruta", "En pausa", "Sin señal", "Fuera de jornada")
    assert mio["minutos_en_estatus"] is not None and mio["folios_pendientes"] >= 0

    # Folios del día con el contador regresivo del SLA de P10.
    assert t["folios"], "el seed tiene folios del día"
    conteos = [f for f in t["folios"] if f["sla_disponible"]]
    assert conteos and all("minutos_restantes" in f for f in conteos)
    assert all(f["umbral_riesgo_pct"] == 80 for f in conteos)

    # Indicadores globales de jornada (los de P10, en vivo).
    assert {"completados", "total_dia", "tecnicos_activos", "alertas_abiertas"} <= set(t["indicadores"])
    # Y el aviso de lo que falta ya no habla del mapa, que ya existe.
    assert "rutas" in t["indicadores"]["aviso_fase_2"] and "mapa" not in t["indicadores"]["aviso_fase_2"].lower()
    assert t["parametros"]["frecuencias"]["jornada_activa_s"] == 30
    assert t["solo_lectura"] is False


async def test_las_unidades_del_mapa_son_las_que_tienen_folios_activos(cliente, auth, datos):
    t = await tablero(cliente, auth, DES)
    for u in t["unidades"]:
        assert u["lat"] and u["lng"] and u["folios_activos"] >= 1
        assert u["codigo"].startswith("SUC-")


async def test_el_feed_de_alertas_incluye_los_folios_autorizados_sin_tecnico(cliente, auth, datos):
    """§6.8.4 lo pide en el feed aunque no sea una alerta del catálogo.

    El feed reserva hasta diez lugares para estos avisos y los llena con los folios más urgentes (los que ya
    incumplieron primero), así que lo que se afirma es que están y que cada uno corresponde de verdad a un folio
    autorizado sin técnico, no que el último folio capturado aparezca: en una base con decenas de folios
    autorizados viejos, el recién hecho es el menos urgente de todos.
    """
    from tests.folios_utiles import autorizar_sin_flujo

    folio = await autorizar_sin_flujo(cliente, auth, datos)
    t = await tablero(cliente, auth, DES)
    sin_tecnico = [a for a in t["alertas"] if a["clave"] == "FOLIO_AUTORIZADO_SIN_TECNICO"]
    assert sin_tecnico, "el feed tiene que traer los folios autorizados sin técnico"
    assert len(sin_tecnico) <= 10
    assert all(a["datos"].get("numero_folio") and a["nombre"] for a in sin_tecnico)
    assert all(a["id"] is None and a["entidad_tipo"] == "folio" for a in sin_tecnico)
    # Cada aviso corresponde a un folio del panel que está autorizado y sin técnico.
    autorizados = {f["folio_id"] for f in t["folios"]
                   if f["estado"] == "autorizado" and f["tecnico_id"] is None}
    assert {a["entidad_id"] for a in sin_tecnico} <= autorizados
    # Y el folio que acaba de autorizarse está en el panel de folios, esperando técnico.
    mio = next(f for f in t["folios"] if f["folio_id"] == folio["id"])
    assert mio["estado"] == "autorizado" and mio["tecnico_id"] is None


async def test_quien_ve_el_tablero_y_quien_no(cliente, auth, datos):
    for email in (DES, AP, MC, SA):
        r = await cliente.get("/api/operacion/tablero", headers=await auth(email))
        assert r.status_code == 200, f"{email} debería ver el tablero"
    # El cliente y el técnico no: el cliente nunca ve posiciones (§6.9.5).
    for email in (AE, AUN, OP, TEC):
        r = await cliente.get("/api/operacion/tablero", headers=await auth(email))
        assert r.status_code == 403, f"{email} no debería ver el tablero"


async def test_la_mesa_de_control_lo_ve_en_lectura(cliente, auth, datos):
    t = await tablero(cliente, auth, MC)
    assert t["solo_lectura"] is True


async def test_el_otro_prestador_no_ve_a_los_tecnicos_del_demo(cliente, auth, datos):
    propio = await tablero(cliente, auth, DES)
    ajeno = await tablero(cliente, auth, OTRO_AP)
    nombres_propios = {x["nombre"] for x in propio["tecnicos"]}
    nombres_ajenos = {x["nombre"] for x in ajeno["tecnicos"]}
    assert nombres_propios and not (nombres_propios & nombres_ajenos)
    assert ajeno["folios"] == [] or all(f["folio_id"] not in {g["folio_id"] for g in propio["folios"]}
                                        for f in ajeno["folios"])


async def test_el_recorrido_del_tecnico_sale_ordenado_y_con_su_rastro(cliente, auth, datos):
    await jornada(cliente, auth, TEC)
    await enviar(cliente, auth, [punto(CENTRO, 120), punto(CENTRO, 60), punto(CENTRO, 0)], email=TEC)
    ficha = await tecnico_de(TEC)
    r = await cliente.get(f"/api/operacion/tecnicos/{ficha['id']}/recorrido", headers=await auth(DES),
                          params={"horas": 2})
    assert r.status_code == 200, r.text
    puntos = r.json()["puntos"]
    assert len(puntos) >= 3
    horas = [p["capturada_at"] for p in puntos]
    assert horas == sorted(horas), "el rastro va en orden para poder dibujar la línea"
    assert r.json()["nombre"].startswith("Tomás")
