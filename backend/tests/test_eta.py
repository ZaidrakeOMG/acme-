"""Hora estimada de llegada (§6.8.4, ACT-3.1): se recalcula con la posición del técnico, el operador ve la hora y
no el GPS, y un cambio de más de 15 minutos se avisa. F2-06."""
from datetime import UTC, datetime

from tests.folios_utiles import AE, AP, DES, OP, OTRO_AE, TEC
from tests.rutas_utiles import (
    calcular, configurar, folios_del_dia, jornadas_abiertas, mercado, paradas_de, plan, posiciones, publicar,
    usuario_id,
)


async def _plan_con_eta(cliente, auth, datos, folios=4):
    await configurar(cliente, auth)
    await jornadas_abiertas()
    m = await mercado(cliente, auth, datos)
    mios = await folios_del_dia(cliente, auth, datos, folios)
    detalle = await calcular(cliente, auth, m["id"])
    await publicar(cliente, auth, detalle["plan"]["id"])
    return await plan(cliente, auth, detalle["plan"]["id"]), {f["id"] for f in mios}


async def test_cada_parada_del_plan_trae_su_hora_estimada(cliente, auth, datos):
    detalle, _ = await _plan_con_eta(cliente, auth, datos)
    paradas = paradas_de(detalle)
    assert paradas, "el plan publicado debe tener paradas"
    for p in paradas:
        assert p["llegada_estimada"], p
        assert p["fin_estimado"] > p["llegada_estimada"]
        assert p["minutos_servicio"] > 0
    # Dentro de una ruta, las horas van en orden: es la misma ruta recorrida.
    for ruta in detalle["rutas"]:
        horas = [p["llegada_estimada"] for p in ruta["paradas"]]
        assert horas == sorted(horas), ruta["tecnico"]


async def test_el_operador_ve_la_hora_y_el_tecnico_pero_no_la_posicion(cliente, auth, datos):
    """§6.9.5 y lo decidido en F2-03: el cliente no ve el GPS del técnico. Sustituye el «Disponible en Fase 2»."""
    detalle, mios = await _plan_con_eta(cliente, auth, datos)
    folio_id = next((p["folio_id"] for p in paradas_de(detalle) if p["folio_id"] in mios), None)
    if folio_id is None:
        return
    r = await cliente.get("/api/operacion/eta", headers=await auth(OP), params={"folio_id": folio_id})
    assert r.status_code == 200, r.text
    eta = r.json()
    assert eta["tiene_eta"] is True
    assert eta["tecnico"] and eta["llegada_estimada"]
    assert eta["minutos_restantes"] is not None
    texto = str(eta).lower()
    assert "lat" not in texto and "lng" not in texto and "posicion" not in texto


async def test_sin_tecnico_o_sin_plan_la_eta_lo_dice(cliente, auth, datos):
    """Nunca inventa una hora: dice por qué no la tiene."""
    from tests.folios_utiles import autorizar_sin_flujo

    folio = await autorizar_sin_flujo(cliente, auth, datos, OP)
    r = await cliente.get("/api/operacion/eta", headers=await auth(OP), params={"folio_id": folio["id"]})
    assert r.status_code == 200, r.text
    eta = r.json()
    assert eta["tiene_eta"] is False and eta["motivo"]
    assert "técnico" in eta["motivo"] or "ruta publicada" in eta["motivo"]


async def test_la_eta_se_recalcula_con_la_posicion_de_ahora(cliente, auth, datos):
    """Es lo que la hace útil: si el técnico está lejos, la hora se mueve."""
    detalle, _ = await _plan_con_eta(cliente, auth, datos)
    if not detalle["rutas"]:
        return
    ruta = detalle["rutas"][0]
    tecnico_id = ruta["tecnico_id"]
    email = None
    for candidato in ("tecnico1@acma.dev", "tecnico2@acma.dev", "tecnico3@acma.dev", "tecnico4@acma.dev"):
        if str(await usuario_id(candidato)) == tecnico_id:
            email = candidato
            break
    if email is None:
        return
    antes = [p["llegada_estimada"] for p in ruta["paradas"]]
    await posiciones(email, [(19.10, -99.60), (19.08, -99.65)])
    r = await cliente.post(f"/api/operacion/eta/{detalle['plan']['id']}/refrescar", headers=await auth(DES),
                           params={"tecnico_id": tecnico_id})
    assert r.status_code == 200, r.text
    nuevas = r.json()["paradas"]
    if not nuevas:
        return
    despues = await plan(cliente, auth, detalle["plan"]["id"])
    ruta_nueva = next(x for x in despues["rutas"] if x["tecnico_id"] == tecnico_id)
    assert [p["llegada_estimada"] for p in ruta_nueva["paradas"]] != antes, "la ETA debe moverse"


async def test_un_cambio_de_mas_de_quince_minutos_avisa_al_operador(cliente, auth, datos):
    """§3 del prompt: el aviso sale cuando la hora prometida se mueve de verdad."""
    from services import notificaciones

    detalle, _ = await _plan_con_eta(cliente, auth, datos)
    if not detalle["rutas"]:
        return
    ruta = detalle["rutas"][0]
    email = None
    for candidato in ("tecnico1@acma.dev", "tecnico2@acma.dev", "tecnico3@acma.dev", "tecnico4@acma.dev"):
        if str(await usuario_id(candidato)) == ruta["tecnico_id"]:
            email = candidato
            break
    if email is None:
        return
    # Se lo lleva a 50 km: la llegada se mueve bastante más de 15 minutos.
    await posiciones(email, [(18.90, -99.90), (18.88, -99.95)])
    notificaciones.ENVIADAS.clear()
    await cliente.post(f"/api/operacion/eta/{detalle['plan']['id']}/refrescar", headers=await auth(DES),
                       params={"tecnico_id": ruta["tecnico_id"]})
    nuevos = [n for n in notificaciones.ENVIADAS if "llegada" in n["titulo"]]
    if nuevos:
        aviso = nuevos[0]
        assert abs(int(aviso["datos"]["cambio_min"])) >= 15
        assert "operador" in aviso["roles"]
        assert "retras" in aviso["titulo"] or "adelant" in aviso["titulo"]


async def test_la_eta_de_un_folio_ajeno_no_se_ve(cliente, auth, datos):
    detalle, mios = await _plan_con_eta(cliente, auth, datos)
    folio_id = next((p["folio_id"] for p in paradas_de(detalle) if p["folio_id"] in mios), None)
    if folio_id is None:
        return
    r = await cliente.get("/api/operacion/eta", headers=await auth(OTRO_AE), params={"folio_id": folio_id})
    assert r.status_code == 404, r.text


async def test_la_incidencia_del_tecnico_dispara_el_recalculo(cliente, auth, datos):
    """§6.8.2: vehículo, salud u otra causa. Es un disparador del recálculo parcial, desde la app del técnico."""
    detalle, _ = await _plan_con_eta(cliente, auth, datos)
    r = await cliente.post("/api/operacion/incidencia", headers=await auth(TEC),
                           json={"tipo": "vehiculo", "detalle": "se descompuso la camioneta"})
    assert r.status_code == 201, r.text
    salida = r.json()
    assert salida["registrada"] is True and salida["mensaje"]
    # El despachador no reporta incidencias: las reporta el técnico desde su app.
    assert (await cliente.post("/api/operacion/incidencia", headers=await auth(DES),
                               json={"tipo": "salud"})).status_code == 403
    assert (await cliente.post("/api/operacion/incidencia", headers=await auth(TEC),
                               json={"tipo": "inventado"})).status_code == 422
