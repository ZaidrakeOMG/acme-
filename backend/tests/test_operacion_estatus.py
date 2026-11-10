"""Estatus operativo del técnico y geocerca de llegada (§6.8.4, §6.8.6). F2-03."""
from tests.folios_utiles import (
    AE, DES, OP, TEC, TEC2, accion, autorizar_sin_flujo, detalle, tecnico_con_habilidades,
)
from tests.operacion_utiles import (
    AVENIDA, CENTRO, cerrar, enviar, jornada, mi_jornada, mover, punto, tecnico_de,
)


async def _folio_asignado_a(cliente, auth, datos, email, un_index=0):
    """Folio autorizado y asignado al técnico, listo para ponerlo «en camino» (helpers de P04).

    Desde F2-01 la habilidad certificada es requisito duro para asignar, así que al técnico de la prueba se le
    deja la de refrigeración (que es la familia del equipo que usa `capturar`).
    """
    folio = await autorizar_sin_flujo(cliente, auth, datos, un_index=un_index)
    usuario_id = await tecnico_con_habilidades(cliente, auth, email, ["refrigeracion"])
    await accion(cliente, auth, DES, folio["id"], "asignar", {"tecnico_id": usuario_id})
    return folio


async def test_el_estatus_sale_de_la_jornada_y_de_los_folios(cliente, auth, datos):
    """§6.8.4: en_servicio con folio en ejecución, en_ruta si se mueve, pausa, sin_senal y fuera_de_jornada."""
    await jornada(cliente, auth, TEC2)
    estado = await enviar(cliente, auth, [punto(CENTRO, 0)], email=TEC2)
    assert estado["estatus"] in ("en_ruta", "en_servicio")

    r = await cliente.post("/api/operacion/jornada/pausar", headers=await auth(TEC2), json={"motivo": "comida"})
    assert r.status_code == 200 and r.json()["estatus"] == "pausa"
    await cliente.post("/api/operacion/jornada/reanudar", headers=await auth(TEC2))

    # Sin posiciones recientes: sin señal (el umbral del catálogo son 15 minutos).
    await mover(TEC2, CENTRO, minutos_atras=40)
    from services import operacion_service
    from core.db import nueva_sesion
    from core.rls import CONTEXTO_SISTEMA
    from models.catalogos import Tecnico

    ficha = await tecnico_de(TEC2)
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        tecnico = await db.get(Tecnico, ficha["id"])
        assert (await operacion_service.recalcular_estatus(db, tecnico)).value == "sin_senal"
        await db.commit()

    # Y al cerrar la jornada, fuera de jornada.
    final = await cerrar(cliente, auth, TEC2)
    assert final["estatus"] == "fuera_de_jornada"
    await jornada(cliente, auth, TEC2)


async def test_un_folio_en_ejecucion_pone_al_tecnico_en_servicio(cliente, auth, datos):
    folio = await _folio_asignado_a(cliente, auth, datos, TEC2)
    await jornada(cliente, auth, TEC2)
    assert (await accion(cliente, auth, TEC2, folio["id"], "en-camino"))["estado"] == "en_camino"
    # La regla mira **todos** sus folios: si el técnico ya traía otro en ejecución, ya está «en servicio».
    salida = await enviar(cliente, auth, [punto(AVENIDA, 0)], email=TEC2)
    assert salida["estatus"] in ("en_ruta", "en_servicio")

    llegada = await accion(cliente, auth, TEC2, folio["id"], "confirmar-llegada",
                           {"geolat": CENTRO[0], "geolng": CENTRO[1]})
    assert llegada["estado"] == "en_ejecucion"
    salida = await enviar(cliente, auth, [punto(CENTRO, 0)], email=TEC2)
    assert salida["estatus"] == "en_servicio", "con un folio en ejecución el estatus es «en servicio»"


async def test_la_geocerca_propone_la_llegada_sin_transicionar_sola(cliente, auth, datos):
    """§6.8.6: el sistema sugiere; la llegada la confirma el técnico. Y la entrada queda en el historial."""
    folio = await _folio_asignado_a(cliente, auth, datos, TEC)
    await jornada(cliente, auth, TEC)
    assert (await accion(cliente, auth, TEC, folio["id"], "en-camino"))["estado"] == "en_camino"

    # Lejos de la unidad: nada que sugerir.
    lejos = await enviar(cliente, auth, [punto(AVENIDA, 0)], email=TEC)
    assert lejos["sugerencia_llegada"] is None

    # Dentro del radio de 150 m de la unidad del folio: se propone confirmar.
    cerca = await enviar(cliente, auth, [punto(CENTRO, 0)], email=TEC)
    sugerencia = cerca["sugerencia_llegada"]
    assert sugerencia is not None and sugerencia["folio_id"] == folio["id"]
    assert sugerencia["distancia_m"] <= 150 and sugerencia["radio_m"] == 150
    assert "Confirma" in sugerencia["mensaje"] or "confirma" in sugerencia["mensaje"]

    # El folio sigue «en camino»: el sistema no transicionó solo.
    d = await detalle(cliente, auth, folio["id"], DES)
    assert d["folio"]["estado"] == "en_camino", "la llegada la confirma el técnico, no la geocerca"
    # Y la entrada a la geocerca quedó como dato informativo del SLA de respuesta.
    eventos = [h for h in d["historial"] if h["evento"] == "entrada_geocerca"]
    assert len(eventos) == 1 and "informativo" in eventos[0]["notas"]
    assert eventos[0]["actor_rol"] == "sistema"

    # Una segunda posición dentro del radio no duplica el registro.
    await enviar(cliente, auth, [punto(CENTRO, 0)], email=TEC)
    d = await detalle(cliente, auth, folio["id"], DES)
    assert len([h for h in d["historial"] if h["evento"] == "entrada_geocerca"]) == 1


async def test_el_radio_de_la_geocerca_es_configurable(cliente, auth, datos):
    r = await cliente.put("/api/configuracion/prestador/operacion.geocerca_radio_m",
                          headers=await auth("admin.prestador@acma.dev"), json={"valor": 300})
    assert r.status_code in (200, 201), r.text
    try:
        estado = await mi_jornada(cliente, auth, TEC)
        assert estado["geocerca_radio_m"] == 300
    finally:
        await cliente.put("/api/configuracion/prestador/operacion.geocerca_radio_m",
                          headers=await auth("admin.prestador@acma.dev"), json={"valor": 150})


async def test_los_parametros_los_ve_cualquier_usuario_autenticado(cliente, auth, datos):
    for email in (TEC, DES, AE, OP):
        r = await cliente.get("/api/operacion/parametros", headers=await auth(email))
        assert r.status_code == 200, email
        assert r.json()["frecuencias"]["jornada_activa_s"] == 30


async def test_el_cierre_automatico_cierra_la_jornada_olvidada(cliente, auth, datos):
    """§6.8.4: sin posiciones ni folios abiertos en X horas, la jornada la cierra el sistema."""
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import select, text

    from core.db import nueva_sesion
    from core.rls import CONTEXTO_SISTEMA
    from models.operaciones import CerradaPorJornada, EstadoJornada, JornadaTecnico
    from workers.evaluadores_operacion import cerrar_jornadas_inactivas

    await jornada(cliente, auth, TEC2)
    ficha = await tecnico_de(TEC2)
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        abierta = (await db.execute(select(JornadaTecnico).where(
            JornadaTecnico.tecnico_id == ficha["id"], JornadaTecnico.estado != EstadoJornada.cerrada))).scalar_one()
        viejo = datetime.now(UTC) - timedelta(hours=5)
        await db.execute(text("UPDATE jornadas_tecnico SET inicio = :i WHERE id = :id"),
                         {"i": viejo, "id": str(abierta.id)})
        await db.execute(text("UPDATE tecnicos SET ultima_posicion_at = :i WHERE id = :id"),
                         {"i": viejo, "id": str(ficha["id"])})
        # Sus folios en curso se cierran para que no haya actividad que la mantenga abierta.
        await db.execute(text("UPDATE folios SET estado = 'cerrado' WHERE tecnico_id = :u "
                              "AND estado IN ('en_camino','en_ejecucion')"), {"u": str(ficha["usuario_id"])})
        await db.commit()

    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        cerradas = await cerrar_jornadas_inactivas(db)
        await db.commit()
    assert cerradas >= 1
    estado = await mi_jornada(cliente, auth, TEC2)
    assert estado["jornada"] is None and estado["estatus"] == "fuera_de_jornada"
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        cerrada = await db.get(JornadaTecnico, abierta.id)
        assert cerrada.estado == EstadoJornada.cerrada
        assert cerrada.cerrada_por == CerradaPorJornada.sistema
    await jornada(cliente, auth, TEC2)


async def test_el_despachador_puede_cerrar_la_jornada_de_un_tecnico(cliente, auth, datos):
    estado = await jornada(cliente, auth, TEC2)
    jornada_id = estado["jornada"]["id"]
    r = await cliente.post(f"/api/operacion/jornada/{jornada_id}/cerrar", headers=await auth(OP))
    assert r.status_code == 403
    r = await cliente.post(f"/api/operacion/jornada/{jornada_id}/cerrar", headers=await auth(DES))
    assert r.status_code == 200, r.text
    assert (await mi_jornada(cliente, auth, TEC2))["jornada"] is None
    await jornada(cliente, auth, TEC2)
