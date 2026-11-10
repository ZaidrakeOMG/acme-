"""Detección automática de §6.8.4: tiempo muerto con push al técnico y escalación, sin señal sin emergencia, y el
desvío de ruta que sigue en Fase 2. F2-03."""
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text

from core.db import nueva_sesion
from core.rls import CONTEXTO_SISTEMA
from tests.folios_utiles import AP, DES, TEC, TEC2, TEC4
from tests.operacion_utiles import (
    AVENIDA, CENTRO, alertas_de, cerrar, evaluar, jornada, limpiar_posiciones, mover, sembrar_quieto,
    seguimientos, tecnico_de,
)
from tests.seguimiento_utiles import bandeja


async def _sin_seguimientos(email: str, tipo: str) -> None:
    """Deja al técnico sin seguimientos abiertos de ese tipo, para que el evaluador pueda volver a disparar."""
    ficha = await tecnico_de(email)
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        await db.execute(text("DELETE FROM alertas_operacion_seguimiento WHERE tecnico_id = :t AND tipo = :tipo"),
                         {"t": str(ficha["id"]), "tipo": tipo})
        await db.commit()


async def test_el_tiempo_muerto_dispara_con_push_al_tecnico_y_aviso_al_despachador(cliente, auth, datos):
    """§6.8.4: alerta en el panel del despachador y push al técnico con dos respuestas."""
    await jornada(cliente, auth, TEC4)
    await _sin_seguimientos(TEC4, "TECNICO_TIEMPO_MUERTO")
    await limpiar_posiciones(TEC4)
    # 30 minutos quieto a media avenida, lejos de cualquier unidad.
    await sembrar_quieto(TEC4, AVENIDA, minutos=30, radio_m=10)

    disparadas = await evaluar("TECNICO_TIEMPO_MUERTO")
    assert disparadas >= 1  # el seed deja a otro técnico detenido a propósito: el total puede ser mayor

    ficha = await tecnico_de(TEC4)
    historial = await alertas_de("TECNICO_TIEMPO_MUERTO", ficha["id"])
    assert historial and historial[0]["datos"]["radio_m"] == 50
    seguimiento = (await seguimientos(TEC4, "TECNICO_TIEMPO_MUERTO"))[0]
    assert seguimiento["push_at"] is not None and seguimiento["respuesta"] is None
    # El despachador recibió el aviso en su bandeja.
    avisos = [n for n in await bandeja(cliente, auth, DES) if n["datos"].get("alerta") == "TECNICO_TIEMPO_MUERTO"]
    assert avisos, "el despachador tiene que ver la alerta"
    # La app del técnico tiene la pregunta pendiente.
    r = await cliente.get("/api/operacion/mis-alertas", headers=await auth(TEC4))
    assert r.status_code == 200 and any(a["id"] == str(seguimiento["id"]) for a in r.json())
    assert "apoyo" in r.json()[0]["pregunta"]

    # No se repite mientras el técnico no conteste.
    assert await evaluar("TECNICO_TIEMPO_MUERTO") == 0


async def test_no_hay_tiempo_muerto_en_pausa_ni_dentro_de_la_unidad(cliente, auth, datos):
    await jornada(cliente, auth, TEC4)
    await _sin_seguimientos(TEC4, "TECNICO_TIEMPO_MUERTO")
    await limpiar_posiciones(TEC4)

    # Dentro de la geocerca de la Sucursal Centro: ahí no es tiempo muerto, es el trabajo.
    await sembrar_quieto(TEC4, CENTRO, minutos=30, radio_m=10)
    from tests.folios_utiles import accion, autorizar_sin_flujo, tecnico_con_habilidades

    folio = await autorizar_sin_flujo(cliente, auth, datos, un_index=0)
    # Desde F2-01 la habilidad certificada es requisito duro para asignar.
    usuario_id = await tecnico_con_habilidades(cliente, auth, TEC4, ["refrigeracion"])
    await accion(cliente, auth, DES, folio["id"], "asignar", {"tecnico_id": usuario_id})
    await accion(cliente, auth, TEC4, folio["id"], "en-camino")
    await evaluar("TECNICO_TIEMPO_MUERTO")
    assert not await seguimientos(TEC4, "TECNICO_TIEMPO_MUERTO"), "dentro de la unidad destino no se dispara"

    # En pausa tampoco, aunque esté quieto a media calle.
    await limpiar_posiciones(TEC4)
    await sembrar_quieto(TEC4, AVENIDA, minutos=30, radio_m=10)
    r = await cliente.post("/api/operacion/jornada/pausar", headers=await auth(TEC4), json={"motivo": "comida"})
    assert r.status_code == 200, r.text
    try:
        assert not await seguimientos(TEC4, "TECNICO_TIEMPO_MUERTO"), "en pausa no se dispara"
    finally:
        r = await cliente.post("/api/operacion/jornada/reanudar", headers=await auth(TEC4))
        assert r.status_code == 200, r.text
        assert r.json()["jornada"]["estado"] == "activa"


async def test_la_respuesta_estoy_bien_cierra_el_aviso(cliente, auth, datos):
    await jornada(cliente, auth, TEC4)
    await _sin_seguimientos(TEC4, "TECNICO_TIEMPO_MUERTO")
    await limpiar_posiciones(TEC4)
    await sembrar_quieto(TEC4, AVENIDA, minutos=30, radio_m=10)
    await evaluar("TECNICO_TIEMPO_MUERTO")
    abiertos = await seguimientos(TEC4, "TECNICO_TIEMPO_MUERTO")
    assert abiertos, "el técnico quieto fuera de su destino tiene que disparar"
    seguimiento = abiertos[0]

    r = await cliente.post(f"/api/operacion/alertas/{seguimiento['id']}/responder", headers=await auth(TEC4),
                           json={"respuesta": "estoy_bien"})
    assert r.status_code == 200 and r.json()["respuesta"] == "estoy_bien"
    # Solo el técnico de la alerta la contesta.
    r = await cliente.post(f"/api/operacion/alertas/{seguimiento['id']}/responder", headers=await auth(TEC2),
                           json={"respuesta": "estoy_bien"})
    assert r.status_code in (403, 409)
    assert (await seguimientos(TEC4, "TECNICO_TIEMPO_MUERTO"))[0]["respuesta"].value == "estoy_bien"


async def test_necesito_apoyo_levanta_una_alerta_de_prioridad_alta(cliente, auth, datos):
    await jornada(cliente, auth, TEC4)
    await _sin_seguimientos(TEC4, "TECNICO_TIEMPO_MUERTO")
    await limpiar_posiciones(TEC4)
    await sembrar_quieto(TEC4, AVENIDA, minutos=30, radio_m=10)
    await evaluar("TECNICO_TIEMPO_MUERTO")
    abiertos = await seguimientos(TEC4, "TECNICO_TIEMPO_MUERTO")
    assert abiertos, "el técnico quieto fuera de su destino tiene que disparar"
    seguimiento = abiertos[0]

    r = await cliente.post(f"/api/operacion/alertas/{seguimiento['id']}/responder", headers=await auth(TEC4),
                           json={"respuesta": "necesito_apoyo"})
    assert r.status_code == 200, r.text
    ficha = await tecnico_de(TEC4)
    altas = [a for a in await alertas_de("TECNICO_TIEMPO_MUERTO", ficha["id"])
             if a["datos"].get("respuesta") == "necesito_apoyo"]
    assert altas and altas[0]["datos"]["prioridad"] == "alta"
    avisos = [n for n in await bandeja(cliente, auth, DES) if "apoyo" in n["asunto"]]
    assert avisos, "el despachador recibe el pedido de apoyo de inmediato"


async def test_la_falta_de_respuesta_escala_al_admin_prestador(cliente, auth, datos):
    """§6.8.4: 10 minutos sin contestar y la alerta sube al Admin prestador."""
    from workers.evaluadores_operacion import escalar_sin_respuesta

    await jornada(cliente, auth, TEC4)
    await _sin_seguimientos(TEC4, "TECNICO_TIEMPO_MUERTO")
    await limpiar_posiciones(TEC4)
    await sembrar_quieto(TEC4, AVENIDA, minutos=30, radio_m=10)
    await evaluar("TECNICO_TIEMPO_MUERTO")
    abiertos = await seguimientos(TEC4, "TECNICO_TIEMPO_MUERTO")
    assert abiertos, "el técnico quieto fuera de su destino tiene que disparar"
    seguimiento = abiertos[0]

    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        assert await escalar_sin_respuesta(db) == 0, "antes de los 10 minutos no escala"
        await db.execute(text("UPDATE alertas_operacion_seguimiento SET push_al_tecnico_at = :t WHERE id = :id"),
                         {"t": datetime.now(UTC) - timedelta(minutes=12), "id": str(seguimiento["id"])})
        await db.commit()
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        assert await escalar_sin_respuesta(db) >= 1
        await db.commit()

    actualizado = (await seguimientos(TEC4, "TECNICO_TIEMPO_MUERTO"))[0]
    assert actualizado["escalada_at"] is not None
    ficha = await tecnico_de(TEC4)
    historial = await alertas_de("TECNICO_TIEMPO_MUERTO", ficha["id"])
    assert any(a["escalada"] for a in historial)
    avisos = [n for n in await bandeja(cliente, auth, AP) if "Sin respuesta" in n["asunto"]]
    assert avisos, "el Admin prestador recibe la escalación"
    # No escala dos veces.
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        assert await escalar_sin_respuesta(db) == 0
        await db.commit()


async def test_sin_senal_avisa_pero_no_genera_emergencia(cliente, auth, datos):
    """§6.8.4: marcador gris con «Sin señal desde HH:MM» y alerta; el despachador decide, el sistema no."""
    await jornada(cliente, auth, TEC2)
    await _sin_seguimientos(TEC2, "TECNICO_SIN_SENAL")
    await mover(TEC2, CENTRO, minutos_atras=40)

    disparadas = await evaluar("TECNICO_SIN_SENAL")
    assert disparadas >= 1
    ficha = await tecnico_de(TEC2)
    assert ficha["estatus"] == "sin_senal"
    historial = await alertas_de("TECNICO_SIN_SENAL", ficha["id"])
    assert historial and historial[0]["datos"]["etiqueta"].startswith("Sin señal desde ")
    seguimiento = (await seguimientos(TEC2, "TECNICO_SIN_SENAL"))[0]
    assert seguimiento["push_at"] is None, "no se le manda push: puede estar sin red, no en peligro"
    avisos = [n for n in await bandeja(cliente, auth, DES) if n["datos"].get("alerta") == "TECNICO_SIN_SENAL"]
    assert avisos and "no genera ninguna emergencia" in avisos[0]["cuerpo"]
    # No hay ninguna alerta de emergencia en el catálogo disparada por esto.
    assert not await alertas_de("TECNICO_DESVIO_RUTA", ficha["id"])
    assert await evaluar("TECNICO_SIN_SENAL") == 0  # no se repite


async def test_el_desvio_de_ruta_sigue_en_fase_2(cliente, auth, datos):
    """Decisión de Dirección: el desvío necesita la ruta planeada del bloque de rutas."""
    from workers.tareas import EVALUADORES

    assert "TECNICO_DESVIO_RUTA" not in EVALUADORES, "no debe tener evaluador todavía"
    r = await cliente.get("/api/alertas/catalogo", headers=await auth(AP))
    catalogo = {c["clave"]: c for c in r.json()}
    assert catalogo["TECNICO_DESVIO_RUTA"]["fase"] == 2
    assert catalogo["TECNICO_DESVIO_RUTA"]["activa_por_defecto"] is False
    assert "optimización de rutas" in catalogo["TECNICO_DESVIO_RUTA"]["descripcion"]
    # Y las dos que sí se activaron dejaron de ser de Fase 2.
    for clave in ("TECNICO_TIEMPO_MUERTO", "TECNICO_SIN_SENAL"):
        assert catalogo[clave]["fase"] == 1 and catalogo[clave]["activa_por_defecto"] is True
    assert catalogo["TECNICO_TIEMPO_MUERTO"]["parametros_default"]["radio_m"] == 50
    assert catalogo["TECNICO_TIEMPO_MUERTO"]["parametros_default"]["escalacion_min"] == 10


async def test_el_umbral_del_tiempo_muerto_se_puede_configurar(cliente, auth, datos):
    """El umbral sale de la configuración central de alertas (P10), no del código."""
    r = await cliente.put("/api/alertas/configuracion/TECNICO_TIEMPO_MUERTO", headers=await auth(AP),
                          json={"umbral_valor": "45", "parametros": {"radio_m": 80, "escalacion_min": 10},
                                "canales": ["app", "push"], "destinatarios_roles": ["despachador"],
                                "activa": True})
    assert r.status_code == 200, r.text
    assert float(r.json()["umbral_valor"]) == 45 and r.json()["parametros"]["radio_m"] == 80
    try:
        await jornada(cliente, auth, TEC4)
        await _sin_seguimientos(TEC4, "TECNICO_TIEMPO_MUERTO")
        await limpiar_posiciones(TEC4)
        await sembrar_quieto(TEC4, AVENIDA, minutos=30, radio_m=10)
        await evaluar("TECNICO_TIEMPO_MUERTO")
        assert not await seguimientos(TEC4, "TECNICO_TIEMPO_MUERTO"),             "con umbral de 45 min, 30 quieto no alcanzan"
    finally:
        r = await cliente.delete("/api/alertas/configuracion/TECNICO_TIEMPO_MUERTO", headers=await auth(AP))
        assert r.status_code == 200, r.text


async def test_el_tecnico_del_otro_prestador_no_sale_en_las_alertas_del_demo(cliente, auth, datos):
    """Aislamiento: el evaluador recorre jornadas de todos los prestadores, pero cada alerta queda en el suyo."""
    ficha = await tecnico_de(TEC4)
    historial = await alertas_de("TECNICO_TIEMPO_MUERTO")
    assert all(a is not None for a in historial)
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        from models.alertas import AlertaHistorial

        filas = (await db.execute(select(AlertaHistorial).where(
            AlertaHistorial.clave_alerta == "TECNICO_TIEMPO_MUERTO"))).scalars().all()
    assert filas and all(f.prestador_id == ficha["prestador_id"] for f in filas)
    assert all(f.tenant_id is None for f in filas), "una alerta de operación es del prestador, no del cliente"
