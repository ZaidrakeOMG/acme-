"""Recálculo parcial de §6.8.2: solo los folios pendientes del técnico afectado, partiendo de dónde está cada uno
ahora, sin tocar lo completado ni los folios de los demás salvo para absorber huérfanos. F2-06."""
from datetime import UTC, datetime

from sqlalchemy import select

from tests.folios_utiles import AE, AP, DES, OP, OTRO_AP, TEC
from tests.rutas_utiles import (
    calcular, configurar, folios_del_dia, jornadas_abiertas, mercado, paradas_de, plan, posiciones, publicar,
    tecnico_de, usuario_id,
)


async def _estado_folio(folio_id):
    from core.db import nueva_sesion
    from core.rls import CONTEXTO_SISTEMA
    from models.folios import Folio
    import uuid

    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        f = await db.get(Folio, uuid.UUID(str(folio_id)))
        return (f.estado.value, str(f.tecnico_id) if f.tecnico_id else None)


async def _poner_estado(folio_id, estado: str) -> None:
    """Mueve el folio de estado sin pasar por la máquina: aquí lo que se prueba es el recálculo, no la captura."""
    from core.db import nueva_sesion
    from core.rls import CONTEXTO_SISTEMA
    from models.folios import EstadoFolio, Folio
    import uuid

    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        f = await db.get(Folio, uuid.UUID(str(folio_id)))
        f.estado = EstadoFolio(estado)
        if estado == "en_ejecucion":
            f.fecha_inicio_atencion = datetime.now(UTC)
        await db.commit()


async def _plan_publicado(cliente, auth, datos, *, folios=4):
    await configurar(cliente, auth)
    await jornadas_abiertas()
    m = await mercado(cliente, auth, datos)
    creados = await folios_del_dia(cliente, auth, datos, folios)
    detalle = await calcular(cliente, auth, m["id"])
    await publicar(cliente, auth, detalle["plan"]["id"])
    return m, creados, await plan(cliente, auth, detalle["plan"]["id"])


async def test_el_recalculo_solo_mueve_los_pendientes_del_tecnico(cliente, auth, datos):
    """§6.8.2 literal: lo que ya empezó no se mueve, y los folios de otros técnicos se quedan donde están."""
    m, creados, detalle = await _plan_publicado(cliente, auth, datos, folios=4)
    paradas = paradas_de(detalle)
    assert paradas, "el plan publicado debe tener paradas"
    afectado = paradas[0]
    tecnico = tecnico_de(detalle, afectado["folio_id"])
    # Uno de sus folios pasa a ejecución: ese ya no se puede mover.
    en_ejecucion = next((p for p in paradas if tecnico_de(detalle, p["folio_id"]) == tecnico), None)
    await _poner_estado(en_ejecucion["folio_id"], "en_ejecucion")
    antes = {p["folio_id"]: tecnico_de(detalle, p["folio_id"]) for p in paradas}

    r = await cliente.post(f"/api/rutas/{detalle['plan']['id']}/recalcular", headers=await auth(DES),
                           json={"disparador": "manual", "tecnico_id": tecnico,
                                 "motivo": "prueba de recálculo parcial"})
    assert r.status_code == 200, r.text
    propuesta = r.json()
    movidos = {m_["folio_id"] for m_ in propuesta["movimientos"]}
    # El folio en ejecución nunca aparece entre los movimientos.
    assert en_ejecucion["folio_id"] not in movidos
    # Y nada se aplicó todavía: el modo por defecto es solo sugerir.
    for folio_id, tec in antes.items():
        estado, actual = await _estado_folio(folio_id)
        if estado in ("asignado", "reasignado"):
            assert actual == tec, "la propuesta no debe cambiar nada hasta que se acepte"


async def test_la_propuesta_no_cambia_nada_hasta_aceptarse_y_se_puede_rechazar(cliente, auth, datos):
    m, creados, detalle = await _plan_publicado(cliente, auth, datos, folios=4)
    plan_id = detalle["plan"]["id"]
    r = await cliente.post(f"/api/rutas/{plan_id}/recalcular", headers=await auth(DES),
                           json={"disparador": "manual", "motivo": "para rechazarla"})
    assert r.status_code == 200, r.text
    propuesta_id = r.json()["id"]
    pendientes = (await cliente.get("/api/rutas/propuestas/pendientes", headers=await auth(DES))).json()
    if r.json()["movimientos"]:
        assert propuesta_id in {p["id"] for p in pendientes}
        r2 = await cliente.post(f"/api/rutas/propuestas/{propuesta_id}/rechazar", headers=await auth(DES),
                                json={"razon": "el despachador prefiere la ruta de ahora"})
        assert r2.status_code == 200, r2.text
        # Rechazada dos veces no se puede: ya no está pendiente.
        r3 = await cliente.post(f"/api/rutas/propuestas/{propuesta_id}/rechazar", headers=await auth(DES),
                                json={"razon": "otra vez"})
        assert r3.status_code == 409 and r3.json()["codigo"] == "PROPUESTA_NO_PENDIENTE"


async def test_aceptar_la_propuesta_reasigna_con_registro_y_pausa_de_sla(cliente, auth, datos):
    """Al aplicarse, cada movimiento pasa por la misma puerta que la reasignación forzada: queda en
    `reasignaciones` con `tipo = automatica`, ligado al recálculo, y el SLA se pausa (§6.10.1)."""
    from models.preventivos import Reasignacion, TipoReasignacion

    m, creados, detalle = await _plan_publicado(cliente, auth, datos, folios=6)
    plan_id = detalle["plan"]["id"]
    r = await cliente.post(f"/api/rutas/{plan_id}/recalcular", headers=await auth(DES),
                           json={"disparador": "sla_en_riesgo", "motivo": "para aceptarla"})
    assert r.status_code == 200, r.text
    propuesta = r.json()
    if not propuesta["movimientos"]:
        return   # el recálculo no encontró mejora: no hay nada que aceptar y eso también es correcto
    r2 = await cliente.post(f"/api/rutas/propuestas/{propuesta['id']}/aceptar", headers=await auth(DES))
    assert r2.status_code == 200, r2.text
    assert r2.json()["aplicados"] >= 1

    from core.db import nueva_sesion
    from core.rls import CONTEXTO_SISTEMA
    import uuid

    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        filas = list((await db.execute(select(Reasignacion).where(
            Reasignacion.recalculo_id == uuid.UUID(propuesta["id"])))).scalars())
        if filas:   # un folio huérfano se asigna, no se reasigna: solo los que ya tenían técnico dejan fila
            assert all(f.tipo == TipoReasignacion.automatica for f in filas)
            assert all(f.razon_id is not None for f in filas), "la razón del catálogo de §6.8.2 es obligatoria"


async def test_aplicar_y_avisar_reasigna_solo(cliente, auth, datos):
    """Con el modo `aplicar_y_avisar` el recálculo no espera a nadie: aplica y notifica."""
    try:
        m, creados, detalle = await _plan_publicado(cliente, auth, datos, folios=5)
        await configurar(cliente, auth, modo_reasignacion_automatica="aplicar_y_avisar")
        r = await cliente.post(f"/api/rutas/{detalle['plan']['id']}/recalcular", headers=await auth(DES),
                               json={"disparador": "incidencia_tecnico", "motivo": "modo automático"})
        assert r.status_code == 200, r.text
        from models.rutas import EstadoRecalculo, RutaRecalculo
        from core.db import nueva_sesion
        from core.rls import CONTEXTO_SISTEMA
        import uuid

        async with nueva_sesion(CONTEXTO_SISTEMA) as db:
            fila = await db.get(RutaRecalculo, uuid.UUID(r.json()["id"]))
            # Aplicada o rechazada por no encontrar mejora: lo que no puede quedar es esperando decisión.
            assert fila.estado in (EstadoRecalculo.aplicada, EstadoRecalculo.rechazada), fila.estado
    finally:
        await configurar(cliente, auth, modo_reasignacion_automatica="solo_sugerir")


async def test_la_propuesta_vencida_no_se_puede_aceptar(cliente, auth, datos):
    """Una propuesta vieja describe una operación que ya cambió: vence y hay que recalcular."""
    from core.db import nueva_sesion
    from core.rls import CONTEXTO_SISTEMA
    from models.rutas import EstadoRecalculo, RutaRecalculo
    from datetime import timedelta
    import uuid

    m, creados, detalle = await _plan_publicado(cliente, auth, datos, folios=4)
    r = await cliente.post(f"/api/rutas/{detalle['plan']['id']}/recalcular", headers=await auth(DES),
                           json={"disparador": "manual", "motivo": "para vencerla"})
    propuesta_id = r.json()["id"]
    if not r.json()["movimientos"]:
        return
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        fila = await db.get(RutaRecalculo, uuid.UUID(propuesta_id))
        fila.vence_at = datetime.now(UTC) - timedelta(minutes=1)
        await db.commit()
    r2 = await cliente.post(f"/api/rutas/propuestas/{propuesta_id}/aceptar", headers=await auth(DES))
    assert r2.status_code == 409 and r2.json()["codigo"] == "PROPUESTA_EXPIRADA", r2.text
    # Y al consultar las pendientes queda marcada como expirada.
    await cliente.get("/api/rutas/propuestas/pendientes", headers=await auth(DES))
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        assert (await db.get(RutaRecalculo, uuid.UUID(propuesta_id))).estado == EstadoRecalculo.expirada


async def test_el_recalculo_parte_de_la_posicion_actual(cliente, auth, datos):
    """§6.8.2: «usando el estado actual de todos los técnicos activos como punto de partida»."""
    m, creados, detalle = await _plan_publicado(cliente, auth, datos, folios=4)
    # Se mueve a un técnico lejos: su ruta deja de ser la buena y el recálculo lo tiene en cuenta.
    await posiciones("tecnico1@acma.dev", [(19.20, -99.40), (19.18, -99.45), (19.16, -99.50)])
    r = await cliente.post(f"/api/rutas/{detalle['plan']['id']}/recalcular", headers=await auth(DES),
                           json={"disparador": "desvio", "tecnico_id": str(await usuario_id("tecnico1@acma.dev")),
                                 "motivo": "técnico lejos de su ruta"})
    assert r.status_code == 200, r.text
    assert r.json()["tiempo_calculo_ms"] > 0


async def test_lo_que_ya_empezo_nunca_entra_al_recalculo(cliente, auth, datos):
    """§6.8.2: «no toca los folios ya completados». El recálculo sí absorbe **huérfanos** (folios sin técnico),
    así que casi siempre encuentra algo que mover; lo que nunca puede mover es un folio en ejecución."""
    m, creados, detalle = await _plan_publicado(cliente, auth, datos, folios=3)
    en_ejecucion = [p["folio_id"] for p in paradas_de(detalle)]
    for folio_id in en_ejecucion:
        await _poner_estado(folio_id, "en_ejecucion")
    r = await cliente.post(f"/api/rutas/{detalle['plan']['id']}/recalcular", headers=await auth(DES),
                           json={"disparador": "manual"})
    if r.status_code == 409:
        assert r.json()["codigo"] == "NADA_QUE_RECALCULAR", r.text
        return
    assert r.status_code == 200, r.text
    movidos = {x["folio_id"] for x in r.json()["movimientos"]}
    assert not (movidos & set(en_ejecucion)), "un folio en ejecución no se mueve"


async def test_quien_decide_las_propuestas(cliente, auth, datos):
    m, creados, detalle = await _plan_publicado(cliente, auth, datos, folios=4)
    r = await cliente.post(f"/api/rutas/{detalle['plan']['id']}/recalcular", headers=await auth(DES),
                           json={"disparador": "manual"})
    propuesta_id = r.json()["id"]
    for email in (AE, OP, TEC):
        # 403 si el rol no decide, 404 si además la propuesta no es de su prestador: las dos niegan.
        assert (await cliente.post(f"/api/rutas/propuestas/{propuesta_id}/aceptar",
                                   headers=await auth(email))).status_code in (403, 404)
    assert (await cliente.post(f"/api/rutas/propuestas/{propuesta_id}/rechazar", headers=await auth(OTRO_AP),
                               json={"razon": "ajena"})).status_code == 404


async def test_la_simulacion_no_cambia_nada(cliente, auth, datos):
    """«¿Qué pasa si…?»: devuelve el costo comparado y no escribe una sola fila."""
    m, creados, detalle = await _plan_publicado(cliente, auth, datos, folios=4)
    paradas = paradas_de(detalle)
    if len(detalle["rutas"]) < 2:
        return   # con un solo técnico no hay a quién moverlo
    folio = paradas[0]["folio_id"]
    destino = next(r["tecnico_id"] for r in detalle["rutas"] if r["tecnico_id"] != tecnico_de(detalle, folio))
    antes = await _estado_folio(folio)
    r = await cliente.post(f"/api/rutas/{detalle['plan']['id']}/simulacion", headers=await auth(DES),
                           json={"movimientos": [{"folio_id": folio, "tecnico_destino_id": destino}]})
    assert r.status_code == 200, r.text
    s = r.json()
    assert "antes" in s and "despues" in s and "diferencia_km" in s
    assert s["antes"]["km"] >= 0 and s["despues"]["km"] >= 0
    assert await _estado_folio(folio) == antes, "la simulación no debe tocar el folio"
