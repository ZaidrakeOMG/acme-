"""Escalación a la Dirección del prestador (§6.9.6): el umbral se mide desde el disparo de la alerta origen, no desde el
hecho original; el mecanismo es genérico (`escalacion_de`) y el Admin prestador puede encadenar otras alertas críticas."""
from datetime import UTC, datetime, timedelta

from sqlalchemy import update

from core.db import nueva_sesion
from core.rls import CONTEXTO_SISTEMA
from tests.folios_utiles import AE, AP, DES, MC, SA, TEC
from tests.sla_utiles import correr_evaluadores, panel_alertas

DIR = "direccion@acma.dev"


async def _disparar(clave, datos_ctx, tenant_id, prestador_id, atras_dias=0):
    from models.alertas import AlertaHistorial
    from services import alertas_service

    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        h = await alertas_service.disparar(db, clave, tenant_id=tenant_id, prestador_id=prestador_id,
                                           entidad_tipo="prueba", entidad_id=None, datos=datos_ctx)
        if h is not None and atras_dias:
            await db.execute(update(AlertaHistorial).where(AlertaHistorial.id == h.id)
                             .values(timestamp_disparo=datetime.now(UTC) - timedelta(days=atras_dias)))
        await db.commit()
        return h.id if h is not None else None


async def test_el_catalogo_declara_la_cadena_de_escalacion(cliente, auth, datos):
    r = await cliente.get("/api/alertas/escalaciones", headers=await auth(AP))
    assert r.status_code == 200, r.text
    cadena = {c["clave"]: c["escalacion_de"] for c in r.json()}
    # §6.9.6: la escalación de cotizaciones se mide desde COTIZACION_SIN_RESPUESTA, no desde el envío.
    assert cadena["COTIZACION_ESCALADA_DIRECCION"] == "COTIZACION_SIN_RESPUESTA"
    assert cadena["SLA_INCUMPLIDO_ESCALADO_DIRECCION"] == "SLA_INCUMPLIDO"
    assert cadena["PRESUPUESTO_ESCALADO_DIRECCION"] == "PRESUPUESTO_ALERTA_3"
    # Su umbral se configura de forma independiente al de la alerta origen (§6.9.6).
    r = await cliente.put("/api/alertas/configuracion/COTIZACION_ESCALADA_DIRECCION", headers=await auth(AP),
                          json={"umbral_valor": "4", "parametros": {}, "canales": ["app", "email"],
                                "destinatarios_roles": ["direccion_prestador"], "activa": True})
    assert r.status_code == 200 and float(r.json()["umbral_valor"]) == 4.0
    ef = {c["clave"]: c for c in (await cliente.get("/api/alertas/configuracion", headers=await auth(AP))).json()}
    assert float(ef["COTIZACION_ESCALADA_DIRECCION"]["umbral_valor"]) == 4.0
    assert float(ef["COTIZACION_SIN_RESPUESTA"]["umbral_valor"]) == float(ef["COTIZACION_SIN_RESPUESTA"]["umbral_default"])


async def test_escala_a_los_dias_del_disparo_de_la_alerta_origen(cliente, auth, datos):
    """La alerta origen con 10 días sin atender escala; una recién disparada, no."""
    vieja = await _disparar("COTIZACION_SIN_RESPUESTA", {"caso": "vieja"}, datos["tenant"], datos["prestador"], atras_dias=10)
    nueva = await _disparar("COTIZACION_SIN_RESPUESTA", {"caso": "nueva"}, datos["tenant"], datos["prestador"])
    assert vieja is not None and nueva is not None
    from services import alertas_service

    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        pendientes = await alertas_service.por_escalar(db, "COTIZACION_ESCALADA_DIRECCION")
        ids = {str(p.id) for p in pendientes}
    assert str(vieja) in ids and str(nueva) not in ids
    await correr_evaluadores()
    escaladas = await panel_alertas(cliente, auth, DIR, clave="COTIZACION_ESCALADA_DIRECCION", pendientes=False)
    mia = next((a for a in escaladas if a["datos_contexto_json"].get("alerta_origen_id") == str(vieja)), None)
    assert mia is not None and mia["datos_contexto_json"]["clave_origen"] == "COTIZACION_SIN_RESPUESTA"
    assert mia["datos_contexto_json"]["disparo_origen"]
    # La origen queda marcada como escalada y no se vuelve a escalar.
    await correr_evaluadores()
    otra_vez = [a for a in await panel_alertas(cliente, auth, DIR, clave="COTIZACION_ESCALADA_DIRECCION", pendientes=False)
                if a["datos_contexto_json"].get("alerta_origen_id") == str(vieja)]
    assert len(otra_vez) == 1


async def test_la_direccion_recibe_la_escalacion_y_no_la_alerta_operativa(cliente, auth, datos):
    await _disparar("SLA_INCUMPLIDO", {"caso": "direccion"}, datos["tenant"], datos["prestador"], atras_dias=9)
    await correr_evaluadores()
    suyas = await panel_alertas(cliente, auth, DIR, pendientes=False)
    claves = {a["clave_alerta"] for a in suyas}
    assert "SLA_INCUMPLIDO_ESCALADO_DIRECCION" in claves
    # §6.9.6: la alerta operativa va al equipo, no a Dirección.
    assert "SLA_INCUMPLIDO" not in claves
    assert "SLA_INCUMPLIDO" in {a["clave_alerta"] for a in await panel_alertas(cliente, auth, AP, pendientes=False)}


async def test_el_admin_prestador_encadena_y_desconecta_escalaciones(cliente, auth, datos):
    r = await cliente.put("/api/alertas/escalaciones", headers=await auth(AP),
                          json={"clave": "PRESUPUESTO_ESCALADO_DIRECCION", "escalacion_de": "PRESUPUESTO_ALERTA_2"})
    assert r.status_code == 200 and r.json()["escalacion_de"] == "PRESUPUESTO_ALERTA_2"
    # La cadena del prestador no cambia el catálogo de la plataforma (§6.9.6).
    cat = {c["clave"]: c for c in (await cliente.get("/api/alertas/catalogo", headers=await auth(SA))).json()}
    assert cat["PRESUPUESTO_ESCALADO_DIRECCION"]["escalacion_de"] == "PRESUPUESTO_ALERTA_3"
    # Circular: no se permite.
    r = await cliente.put("/api/alertas/escalaciones", headers=await auth(AP),
                          json={"clave": "PRESUPUESTO_ESCALADO_DIRECCION", "escalacion_de": "PRESUPUESTO_ESCALADO_DIRECCION"})
    assert r.status_code == 422 and r.json()["codigo"] == "ESCALACION_CIRCULAR"
    # Desconectar deja la alerta sin cadena.
    r = await cliente.put("/api/alertas/escalaciones", headers=await auth(AP),
                          json={"clave": "PRESUPUESTO_ESCALADO_DIRECCION", "escalacion_de": None})
    assert r.status_code == 200 and r.json()["escalacion_de"] is None
    # El técnico no configura escalaciones.
    r = await cliente.put("/api/alertas/escalaciones", headers=await auth(TEC),
                          json={"clave": "PRESUPUESTO_ESCALADO_DIRECCION", "escalacion_de": "PRESUPUESTO_ALERTA_3"})
    assert r.status_code == 403
    await cliente.put("/api/alertas/escalaciones", headers=await auth(AP),
                      json={"clave": "PRESUPUESTO_ESCALADO_DIRECCION", "escalacion_de": "PRESUPUESTO_ALERTA_3"})


async def test_una_alerta_origen_atendida_ya_no_escala(cliente, auth, datos):
    origen = await _disparar("COTIZACION_SIN_RESPUESTA", {"caso": "atendida"}, datos["tenant"], datos["prestador"], atras_dias=15)
    r = await cliente.post(f"/api/alertas/historial/{origen}/atender", headers=await auth(AP),
                           json={"nota": "El cliente respondió por teléfono"})
    assert r.status_code == 200
    from services import alertas_service

    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        pendientes = await alertas_service.por_escalar(db, "COTIZACION_ESCALADA_DIRECCION")
    assert str(origen) not in {str(p.id) for p in pendientes}


async def test_el_tablero_de_direccion_muestra_el_historico_de_escalaciones(cliente, auth, datos):
    await _disparar("SLA_INCUMPLIDO", {"caso": "tablero"}, datos["tenant"], datos["prestador"], atras_dias=8)
    await correr_evaluadores()
    r = await cliente.get("/api/bi/tablero", headers=await auth(DIR))
    assert r.status_code == 200, r.text
    tablero = r.json()
    assert tablero["tipo"] == "direccion" and tablero["solo_lectura"] is True
    claves = {e["clave"] for e in tablero["escalaciones"]}
    assert "SLA_INCUMPLIDO_ESCALADO_DIRECCION" in claves
    assert "penalizaciones" in tablero and "cumplimiento_sla" in tablero
