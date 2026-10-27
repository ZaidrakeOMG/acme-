"""Motor de estados (§6.8.6): tabla de transiciones por rol, 409 fuera de tabla, historial inmutable, cierre incompleto,
inmutabilidad del folio cerrado/cancelado, asignación con habilidad y SLA prometido."""
import pytest
from sqlalchemy import text

from core.db import nueva_sesion
from core.rls import CONTEXTO_SISTEMA, ContextoRLS
from services import folio_estados
from services.folio_estados import ACTOR_SISTEMA, TRANSICIONES, EstadoFolio as E
from tests.folios_utiles import (
    AE, AP, AUN, DES, MC, OP, SA, SUPO, TEC, TEC2, TEC4, accion, autorizar_sin_flujo, capturar, detalle, nuevo_equipo, tecnico_con_habilidades,
)


def test_tabla_literal_de_6_8_6():
    assert set(TRANSICIONES) == set(E) and len(folio_estados.tabla_transiciones()) == 21
    assert TRANSICIONES[E.cerrado] == {} and TRANSICIONES[E.cancelado] == {}
    assert set(TRANSICIONES[E.en_revision]) == {E.autorizado, E.pendiente_informacion, E.cancelado}
    assert set(TRANSICIONES[E.en_ejecucion]) == {E.cerrado, E.pendiente_refaccion}
    assert set(TRANSICIONES[E.pendiente_refaccion]) == {E.en_ejecucion, E.reasignado, E.cancelado}
    assert "sistema" in {str(getattr(r, "value", r)) for r in TRANSICIONES[E.reasignado][E.asignado]}
    assert folio_estados.puede(ACTOR_SISTEMA, E.capturado, E.en_revision) and not folio_estados.puede(ACTOR_SISTEMA, E.en_revision, E.pendiente_informacion)


async def test_endpoint_transiciones_y_acciones_por_rol(cliente, auth, datos):
    tabla = (await cliente.get("/api/folios/transiciones", headers=await auth(OP))).json()
    assert {(t["origen"], t["destino"]) for t in tabla} >= {("asignado", "en_camino"), ("en_revision", "autorizado")}
    f = await autorizar_sin_flujo(cliente, auth, datos)
    assert f["estado"] == "autorizado"
    assert (await detalle(cliente, auth, f["id"], DES))["acciones"] == ["asignado", "cancelado"]
    assert (await detalle(cliente, auth, f["id"], OP))["acciones"] == []
    assert (await detalle(cliente, auth, f["id"], AE))["acciones"] == ["cancelado"]


async def test_camino_feliz_completo_con_roles_y_fechas(cliente, auth, datos):
    f = await autorizar_sin_flujo(cliente, auth, datos)
    tec = await tecnico_con_habilidades(cliente, auth, TEC, ["refrigeracion", "electricidad"])
    # El operador no asigna (409 con detalle); el despachador sí.
    r = await accion(cliente, auth, OP, f["id"], "asignar", {"tecnico_id": tec}, 409)
    assert r["codigo"] == "TRANSICION_NO_PERMITIDA" and "despachador" in r["detalles"][0]["roles_permitidos"]
    a = await accion(cliente, auth, DES, f["id"], "asignar", {"tecnico_id": tec})
    assert a["estado"] == "asignado" and a["tecnico_id"] == tec and a["tecnico_nombre"] == "Tomás Técnico"
    # Otro técnico no ve el folio (alcance); el asignado avanza.
    assert (await cliente.post(f"/api/folios/{f['id']}/en-camino", headers=await auth(TEC2), json={})).status_code == 404
    assert (await accion(cliente, auth, TEC, f["id"], "en-camino"))["estado"] == "en_camino"
    assert (await accion(cliente, auth, TEC, f["id"], "pendiente-refaccion", {}, 409))["codigo"] == "TRANSICION_NO_PERMITIDA"
    lleg = await accion(cliente, auth, TEC, f["id"], "confirmar-llegada", {"geolat": 19.43, "geolng": -99.13})
    assert lleg["estado"] == "en_ejecucion" and lleg["fecha_inicio_atencion"] is not None
    p = await accion(cliente, auth, TEC, f["id"], "pendiente-refaccion", {"notas": "Falta compresor"})
    assert p["estado"] == "pendiente_refaccion"
    assert (await accion(cliente, auth, TEC, f["id"], "reanudar", {}, 409))["codigo"] == "TRANSICION_NO_PERMITIDA"
    assert (await accion(cliente, auth, AP, f["id"], "reanudar", {"notas": "Llegó la pieza"}))["estado"] == "en_ejecucion"
    # Cierre incompleto: sin atención ni firma.
    r = await accion(cliente, auth, TEC, f["id"], "cerrar", {}, 409)
    assert r["codigo"] == "CIERRE_INCOMPLETO" and set(r["detalles"]) == {"formulario_atencion", "firma"}
    d = await detalle(cliente, auth, f["id"])
    estados = [h["estado_nuevo"] for h in d["historial"] if h["evento"] == "transicion"]
    assert estados == ["capturado", "autorizado", "asignado", "en_camino", "en_ejecucion", "pendiente_refaccion", "en_ejecucion"]
    assert d["sla"]["tiempo_respuesta_prometido_horas"] == 2 and d["sla"]["tiempo_resolucion_prometido_horas"] == 8  # crítica del contrato
    ficha = next(t for t in (await cliente.get("/api/catalogos/tecnicos", headers=await auth(AP))).json() if t["usuario_id"] == tec)
    assert d["asignacion"]["vehiculo"] == ficha["vehiculo_placas"] and d["asignacion"]["asignado_at"] is not None


async def _respuesta_atencion_con_firma(cliente, auth, datos, folio, tecnico=TEC):
    """Formulario de atención enviado con firma, hecho con la API de P03 (el técnico asignado lo responde)."""
    from tests.test_formularios_evidencias import png

    esquema = {"secciones": [{"clave": "s", "titulo": "S", "campos": [
        {"clave": "diag", "tipo": "texto", "etiqueta": "Diagnóstico", "obligatorio": True, "config": {"longitud_min": 2, "longitud_max": 200}},
        {"clave": "firma", "tipo": "firma", "etiqueta": "Firma", "obligatorio": True, "config": {"pantalla_completa": True}},
    ]}]}
    h = await auth(AP)
    fr = await cliente.post("/api/formularios", headers=h, json={"nombre": f"Atención {folio['numero_folio']}", "tipo": "atencion_tecnico",
                                                                 "rol_destino": ["tecnico"], "esquema": esquema})
    assert fr.status_code == 201, fr.text
    await cliente.post(f"/api/formularios/{fr.json()['id']}/publicar", headers=h, json={"notas_version": ""})
    ht = await auth(tecnico)
    r = await cliente.post(f"/api/formularios/{fr.json()['id']}/respuestas", headers=ht,
                           json={"origen": "folio_atencion", "referencia_id": folio["id"],
                                 "contexto": {"tenant_id": str(datos["tenant"]), "un_id": folio["un_id"], "equipo_id": folio["equipo_id"]},
                                 "respuestas": {"diag": "Se cambió el fusible"}})
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    e = await cliente.post(f"/api/formularios/respuestas/{rid}/evidencias", headers=ht, data={"campo_clave": "firma"},
                           files={"archivo": ("firma.png", png(), "image/png")})
    assert e.status_code == 201, e.text
    env = await cliente.post(f"/api/formularios/respuestas/{rid}/enviar", headers=ht)
    assert env.status_code == 200 and env.json()["estado"] == "enviado", env.text
    return rid


async def test_cierre_con_atencion_y_firma_e_inmutabilidad(cliente, auth, datos):
    f = await autorizar_sin_flujo(cliente, auth, datos)
    tec = await tecnico_con_habilidades(cliente, auth, TEC, ["refrigeracion", "electricidad"])
    await accion(cliente, auth, DES, f["id"], "asignar", {"tecnico_id": tec})
    await accion(cliente, auth, TEC, f["id"], "en-camino")
    await accion(cliente, auth, TEC, f["id"], "confirmar-llegada")
    rid = await _respuesta_atencion_con_firma(cliente, auth, datos, f)
    # Otro técnico no puede vincular; el asignado sí, y la firma queda como evidencia del folio.
    assert (await cliente.post(f"/api/folios/{f['id']}/atencion", headers=await auth(TEC2), json={"respuesta_id": rid})).status_code == 404
    v = await cliente.post(f"/api/folios/{f['id']}/atencion", headers=await auth(TEC), json={"respuesta_id": rid})
    assert v.status_code == 201 and v.json()["respuestas_json"]["diag"] == "Se cambió el fusible"
    assert (await cliente.post(f"/api/folios/{f['id']}/atencion", headers=await auth(TEC), json={"respuesta_id": rid})).json()["codigo"] == "ATENCION_YA_VINCULADA"
    d = await detalle(cliente, auth, f["id"])
    assert [e["tipo"] for e in d["evidencias"]] == ["firma"] and d["formulario_atencion"]["respuesta_id"] == rid
    c = await accion(cliente, auth, TEC, f["id"], "cerrar", {"notas": "Listo"})
    assert c["estado"] == "cerrado" and c["fecha_cierre"] is not None
    # Inmutabilidad: ninguna transición, ni cambios directos (ni como sistema), solo comentarios en el historial.
    assert (await accion(cliente, auth, DES, f["id"], "cancelar", {"razon": "Ya no aplica"}, 409))["codigo"] == "TRANSICION_NO_PERMITIDA"
    assert (await cliente.post(f"/api/folios/{f['id']}/refacciones", headers=await auth(TEC), json={"descripcion": "Compresor", "cantidad": 1})).status_code == 409
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        with pytest.raises(Exception, match="inmutable"):
            await db.execute(text("UPDATE folios SET descripcion = 'editado' WHERE id = :i"), {"i": f["id"]})
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        with pytest.raises(Exception, match="append-only|permission denied"):
            await db.execute(text("DELETE FROM folios WHERE id = :i"), {"i": f["id"]})
    com = await accion(cliente, auth, AE, f["id"], "comentario", {"notas": "Revisado para la minuta"})
    assert com["evento"] == "comentario" and com["estado_nuevo"] == "cerrado"
    d = await detalle(cliente, auth, f["id"])
    assert d["historial"][-1]["notas"] == "Revisado para la minuta" and d["folio"]["estado"] == "cerrado"


async def test_historial_y_decisiones_son_append_only_incluso_superadmin(cliente, auth, datos):
    f = await capturar(cliente, auth, datos, OP)
    d = await detalle(cliente, auth, f["id"])
    hid = d["historial"][0]["id"]
    for ctx in (CONTEXTO_SISTEMA, ContextoRLS(rol="superadmin")):
        async with nueva_sesion(ctx) as db:
            with pytest.raises(Exception, match="append-only|permission denied"):
                await db.execute(text("UPDATE folio_estados_historial SET notas = 'x' WHERE id = :i"), {"i": hid})
        async with nueva_sesion(ctx) as db:
            with pytest.raises(Exception, match="append-only|permission denied"):
                await db.execute(text("DELETE FROM folio_estados_historial WHERE id = :i"), {"i": hid})
    # Decisiones de aprobación: idem (se genera una aprobando el folio en Nivel 1).
    await accion(cliente, auth, AUN, f["id"], "aprobacion/aprobar", {"canal": "app"})
    did = (await detalle(cliente, auth, f["id"]))["decisiones"][0]["id"]
    for ctx in (CONTEXTO_SISTEMA, ContextoRLS(rol="superadmin")):
        async with nueva_sesion(ctx) as db:
            with pytest.raises(Exception, match="append-only|permission denied"):
                await db.execute(text("UPDATE aprobacion_decisiones SET notas = 'x' WHERE id = :i"), {"i": did})
        async with nueva_sesion(ctx) as db:
            with pytest.raises(Exception, match="append-only|permission denied"):
                await db.execute(text("DELETE FROM aprobacion_decisiones WHERE id = :i"), {"i": did})
    # Y por la API tampoco hay forma: solo lectura.
    assert (await cliente.delete(f"/api/folios/{f['id']}/historial", headers=await auth(SA))).status_code == 405


async def test_cancelacion_requiere_razon_y_es_inmutable(cliente, auth, datos):
    f = await capturar(cliente, auth, datos, OP)
    assert (await cliente.post(f"/api/folios/{f['id']}/cancelar", headers=await auth(DES), json={"razon": ""})).status_code == 422
    assert (await accion(cliente, auth, OP, f["id"], "cancelar", {"razon": "Ya no aplica"}, 409))["codigo"] == "TRANSICION_NO_PERMITIDA"
    c = await accion(cliente, auth, AE, f["id"], "cancelar", {"razon": "Ya no aplica"})
    assert c["estado"] == "cancelado" and c["razon_cancelacion"] == "Ya no aplica"
    assert (await accion(cliente, auth, DES, f["id"], "autorizar", {}, 409))["codigo"] == "TRANSICION_NO_PERMITIDA"
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        with pytest.raises(Exception, match="inmutable"):
            await db.execute(text("UPDATE folios SET prioridad = 9 WHERE id = :i"), {"i": f["id"]})
    com = await accion(cliente, auth, DES, f["id"], "comentario", {"notas": "Cliente avisó que lo resolvió el proveedor"})
    assert com["estado_anterior"] == "cancelado"


async def test_revision_pendiente_informacion_y_autorizacion_manual(cliente, auth, datos):
    e = await nuevo_equipo(cliente, auth, datos, garantia_vigente_hasta="2030-01-01")
    f = await capturar(cliente, auth, datos, OP, e)  # en revisión por garantía
    assert f["estado"] == "en_revision" and f["flujo"] is None
    assert (await accion(cliente, auth, OP, f["id"], "pedir-informacion", {"notas": "?"}, 409))["codigo"] == "TRANSICION_NO_PERMITIDA"
    assert (await cliente.post(f"/api/folios/{f['id']}/pedir-informacion", headers=await auth(DES), json={"notas": ""})).status_code == 422
    p = await accion(cliente, auth, DES, f["id"], "pedir-informacion", {"notas": "¿Desde cuándo falla?"})
    assert p["estado"] == "pendiente_informacion"
    assert (await accion(cliente, auth, DES, f["id"], "responder-informacion", {"notas": "x"}, 409))["codigo"] == "TRANSICION_NO_PERMITIDA"
    r = await accion(cliente, auth, OP, f["id"], "responder-informacion", {"notas": "Desde ayer"})
    assert r["estado"] == "en_revision"
    # Autorizar en revisión con reglas configuradas y sin flujo previo → inicia el flujo (no autoriza directo).
    a = await accion(cliente, auth, DES, f["id"], "autorizar", {"notas": "Garantía revisada; se atiende"})
    assert a["estado"] == "en_revision" and a["flujo"]["nivel_actual"] == 1 and a["triggers_pendientes"] == 0  # sin criticidad, monto 0 → Nivel 1
    d = await detalle(cliente, auth, f["id"])
    assert any(h["evento"] == "revision.resuelta" for h in d["historial"]) and all(t["resuelto"] for t in d["triggers_revision"])
    assert (await accion(cliente, auth, DES, f["id"], "autorizar", {}, 409))["codigo"] == "FLUJO_ACTIVO"


async def test_asignacion_valida_habilidad_y_permiso_del_despachador(cliente, auth, datos):
    f = await autorizar_sin_flujo(cliente, auth, datos)  # refrigeración
    tec4 = await tecnico_con_habilidades(cliente, auth, TEC4, ["iluminacion", "electricidad", "hvac"])  # sin refrigeración
    r = await accion(cliente, auth, DES, f["id"], "asignar", {"tecnico_id": tec4}, 409)
    assert r["codigo"] == "TECNICO_SIN_HABILIDAD" and r["detalles"][0]["habilidad_requerida"] == "refrigeracion"
    h = await auth(AP)
    desp = (await cliente.get("/api/usuarios", headers=h, params={"rol": "despachador"})).json()[0]
    await cliente.put("/api/configuracion/permisos-despachador", headers=h,
                      json={"valores": {"asignar_tecnico_sin_habilidad": True}, "despachador_id": desp["id"], "tenant_id": str(datos["tenant"])})
    try:
        assert (await accion(cliente, auth, DES, f["id"], "asignar", {"tecnico_id": tec4}, 422))["codigo"] == "RAZON_REQUERIDA"
        a = await accion(cliente, auth, DES, f["id"], "asignar", {"tecnico_id": tec4, "razon": "Único disponible hoy"})
        assert a["estado"] == "asignado" and a["tecnico_id"] == tec4
    finally:
        await cliente.put("/api/configuracion/permisos-despachador", headers=h,
                          json={"valores": {"asignar_tecnico_sin_habilidad": False}, "despachador_id": desp["id"], "tenant_id": str(datos["tenant"])})
    d = await detalle(cliente, auth, f["id"])
    ultimo = [x for x in d["historial"] if x["estado_nuevo"] == "asignado"][-1]
    assert ultimo["datos_contexto_json"]["sin_habilidad"] is True and ultimo["datos_contexto_json"]["razon"] == "Único disponible hoy"
    # Reasignación: asignado → reasignado (despachador) → asignado al nuevo técnico.
    assert (await accion(cliente, auth, DES, f["id"], "reasignar", {"notas": "Cambio de ruta"}))["estado"] == "reasignado"
    tec = await tecnico_con_habilidades(cliente, auth, TEC, ["refrigeracion", "electricidad"])
    a = await accion(cliente, auth, DES, f["id"], "asignar", {"tecnico_id": tec})
    assert a["estado"] == "asignado" and a["tecnico_id"] == tec


async def test_transicion_generica_y_no_permitidas(cliente, auth, datos):
    f = await capturar(cliente, auth, datos, OP)  # en revisión con flujo Nivel 1
    for email, estado in ((OP, "autorizado"), (SUPO, "cancelado"), (TEC, "en_camino"), (DES, "cerrado"), (AE, "asignado"), (MC, "autorizado")):
        r = await cliente.post(f"/api/folios/{f['id']}/transicion", headers=await auth(email), json={"estado": estado})
        assert r.status_code in (404, 409), (email, estado, r.text)
        if r.status_code == 409:
            assert r.json()["codigo"] in ("TRANSICION_NO_PERMITIDA", "FLUJO_ACTIVO")
    r = await cliente.post(f"/api/folios/{f['id']}/transicion", headers=await auth(DES), json={"estado": "cancelado", "notas": "Duplicado real"})
    assert r.status_code == 200 and r.json()["estado"] == "cancelado"
    assert (await cliente.post(f"/api/folios/{f['id']}/transicion", headers=await auth(SA), json={"estado": "capturado"})).status_code == 409
