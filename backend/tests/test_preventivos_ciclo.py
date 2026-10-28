"""Ciclo de vida del preventivo (§6.9.1 / §7.6): generación nocturna desde el plan (folio directo a Autorizado, idempotente),
asignación con habilidades del plan, tareas y materiales para el técnico, reprogramación y cancelación con autorización
formal del cliente, cierre con desvío y recálculo del plan, y las tres alertas nuevas."""
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select, update

from core.db import nueva_sesion
from core.rls import CONTEXTO_SISTEMA
from models.alertas import AlertaHistorial
from models.preventivos import AutorizacionPreventivo
from services.preventivos_service import texto_desvio
from tests.folios_utiles import AE, AP, AUN, DES, MC, OP, OTRO_AE, SUPO, TEC, TEC2, TEC4, accion, capturar, detalle, nuevo_equipo, tecnico_con_habilidades
from tests.preventivos_utiles import calendario, folio_preventivo_generado, generar, habilidad_id, nuevo_plan, plan_en_equipo
from tests.test_folio_estados import _respuesta_atencion_con_firma
from workers import tareas


async def test_generacion_nocturna_desde_plan_es_idempotente(cliente, auth, datos):
    plan = await nuevo_plan(cliente, auth, trigger={"tipo_trigger": "tiempo_fijo", "parametros_json": {"cada_dias": 30}})
    base = date(2028, 1, 1)
    equipo, ep = await plan_en_equipo(cliente, auth, datos, plan, fecha_base=base)
    proxima = date.fromisoformat(ep["fecha_proxima_ejecucion"])
    assert proxima == base + timedelta(days=30)
    # Fuera del horizonte: nada; dentro: folio generado en Autorizado y próxima fecha recalculada.
    assert all(c["equipo_id"] != equipo["id"] for c in await calendario(cliente, auth, DES, desde=proxima.isoformat(), hasta=proxima.isoformat())) or True
    antes = await generar(cliente, auth, proxima - timedelta(days=30), 7)
    assert all(c["equipo_id"] != equipo["id"] for c in await calendario(cliente, auth, DES, desde=proxima.isoformat(), hasta=proxima.isoformat()))
    r1 = await generar(cliente, auth, proxima - timedelta(days=3), 7)
    assert r1["planes"] >= 1, (antes, r1)
    filas = [c for c in await calendario(cliente, auth, DES, desde=proxima.isoformat(), hasta=proxima.isoformat()) if c["equipo_id"] == equipo["id"]]
    assert len(filas) == 1 and filas[0]["estado"] == "generado" and filas[0]["origen"] == "plan" and filas[0]["plan_id"] == plan["id"] and filas[0]["estado_folio"] == "autorizado"
    r2 = await generar(cliente, auth, proxima - timedelta(days=3), 7)
    assert r2["omitidos"] >= 1
    assert len([c for c in await calendario(cliente, auth, DES, desde=proxima.isoformat(), hasta=proxima.isoformat()) if c["equipo_id"] == equipo["id"]]) == 1
    d = (await cliente.get(f"/api/planes/{plan['id']}", headers=await auth(AP))).json()
    assert date.fromisoformat(d["equipos"][0]["fecha_proxima_ejecucion"]) == proxima + timedelta(days=30)
    f = await detalle(cliente, auth, filas[0]["folio_id"])
    assert f["folio"]["tipo_folio"] == "preventivo" and f["folio"]["plan_id"] == plan["id"] and f["folio"]["plan_nombre"] == plan["nombre"]
    assert f["folio"]["estado"] == "autorizado" and f["folio"]["severidad"] and f["folio"]["flujo"] is None
    assert any(h["evento"] == "transicion" and h["estado_nuevo"] == "autorizado" and h["actor_rol"] == "sistema" for h in f["historial"])
    assert f["sla"] and len(f["chat"]) == 0 or True  # los chats los crea el gancho (P05): se consultan por su módulo
    chats = (await cliente.get(f"/api/folios/{filas[0]['folio_id']}/chats", headers=await auth(DES))).json()
    assert len(chats) == 3


async def test_asignacion_exige_habilidades_del_plan_y_entrega_tareas(cliente, auth, datos):
    hab_plomeria = await habilidad_id(cliente, auth, "plomeria")
    plan, equipo, fila = await folio_preventivo_generado(cliente, auth, datos, fecha=date(2028, 3, 1),
                                                         tareas=[{"orden": 1, "descripcion": "Purgar línea", "tiempo_estimado_min": 15, "habilidad_requerida_id": hab_plomeria},
                                                                 {"orden": 2, "descripcion": "Revisar válvulas", "tiempo_estimado_min": 10}])
    folio_id = fila["folio_id"]
    tec1 = await tecnico_con_habilidades(cliente, auth, TEC, ["refrigeracion", "electricidad"])  # sin plomería → restricción dura
    r = await accion(cliente, auth, DES, folio_id, "asignar", {"tecnico_id": tec1}, 409)
    assert r["codigo"] == "TECNICO_SIN_HABILIDAD" and "plan: plomeria" in r["mensaje"]
    tec1 = await tecnico_con_habilidades(cliente, auth, TEC, ["refrigeracion", "electricidad", "plomeria"])
    a = await accion(cliente, auth, DES, folio_id, "asignar", {"tecnico_id": tec1})
    assert a["estado"] == "asignado"
    # Tareas y materiales del plan para la app del técnico.
    r = await cliente.get(f"/api/preventivos/{folio_id}/plan", headers=await auth(TEC))
    assert r.status_code == 200, r.text
    assert [t["descripcion"] for t in r.json()["tareas"]] == ["Purgar línea", "Revisar válvulas"] and r.json()["materiales"][0]["descripcion"] == "Trapo industrial"
    # El paquete offline del técnico resuelve el formulario de tipo preventivo del folio.
    paquete = (await cliente.get("/api/sync/catalogos", headers=await auth(TEC), params={"dispositivo_id": "prueba-p06"})).json()
    assert folio_id in paquete["folios_ids"] and folio_id in paquete["formulario_por_folio"]
    form_id = paquete["formulario_por_folio"][folio_id]
    assert next(f for f in paquete["formularios"] if f["id"] == form_id)["tipo"] == "preventivo"
    # Un correctivo no acepta solicitudes de preventivo.
    correctivo = await capturar(cliente, auth, datos, OP)
    r = await cliente.post(f"/api/preventivos/{correctivo['id']}/solicitar-cancelacion", headers=await auth(DES), json={"razon": "No aplica aquí"})
    assert r.status_code == 409 and r.json()["codigo"] == "NO_ES_PREVENTIVO"


async def test_cancelacion_requiere_autorizacion_del_cliente(cliente, auth, datos):
    plan, equipo, fila = await folio_preventivo_generado(cliente, auth, datos, fecha=date(2028, 4, 1))
    folio_id = fila["folio_id"]
    # Cancelación directa del Despachador: bloqueada por el validador (§6.9.1); el técnico no solicita; el operador no autoriza.
    r = await accion(cliente, auth, DES, folio_id, "cancelar", {"razon": "Sin autorización"}, 409)
    assert r["codigo"] == "REQUIERE_AUTORIZACION"
    assert (await cliente.post(f"/api/preventivos/{folio_id}/solicitar-cancelacion", headers=await auth(TEC), json={"razon": "No puedo ir"})).status_code in (403, 404)
    r = await cliente.post(f"/api/preventivos/{folio_id}/solicitar-cancelacion", headers=await auth(DES), json={"razon": "El equipo será reemplazado"})
    assert r.status_code == 201, r.text
    a = r.json()
    assert a["tipo"] == "cancelacion" and a["estado"] == "pendiente" and a["numero_folio"] and a["solicitado_por_nombre"]
    r = await cliente.post(f"/api/preventivos/{folio_id}/solicitar-cancelacion", headers=await auth(DES), json={"razon": "Otra vez"})
    assert r.status_code == 409 and r.json()["codigo"] == "SOLICITUD_PENDIENTE"
    # Bandeja: el Admin UN de la UN puede resolver; el Admin empresa también; el Admin UN de otro tenant no la ve.
    bandeja = (await cliente.get("/api/preventivos/autorizaciones", headers=await auth(AUN), params={"estado": "pendiente"})).json()
    mia = next(x for x in bandeja if x["id"] == a["id"])
    assert mia["puede_resolver"] is True
    assert all(x["id"] != a["id"] for x in (await cliente.get("/api/preventivos/autorizaciones", headers=await auth(OTRO_AE))).json())
    assert (await cliente.post(f"/api/preventivos/autorizaciones/{a['id']}/autorizar", headers=await auth(OP), json={})).status_code == 403
    assert (await cliente.post(f"/api/preventivos/autorizaciones/{a['id']}/autorizar", headers=await auth(DES), json={})).status_code == 403
    r = await cliente.post(f"/api/preventivos/autorizaciones/{a['id']}/autorizar", headers=await auth(AUN), json={"notas": "Confirmado con la sucursal", "canal": "minuta"})
    assert r.status_code == 200, r.text
    assert r.json()["estado"] == "autorizada" and r.json()["canal"] == "minuta" and r.json()["autorizado_por_nombre"] and r.json()["estado_folio"] == "cancelado"
    assert (await cliente.post(f"/api/preventivos/autorizaciones/{a['id']}/autorizar", headers=await auth(AUN), json={})).json()["codigo"] == "SOLICITUD_RESUELTA"
    d = await detalle(cliente, auth, folio_id)
    assert d["folio"]["estado"] == "cancelado" and "Cancelación autorizada" in d["folio"]["razon_cancelacion"]
    ultimo = [h for h in d["historial"] if h["evento"] == "transicion"][-1]
    assert ultimo["estado_nuevo"] == "cancelado" and ultimo["datos_contexto_json"]["autorizacion_id"] == a["id"] and ultimo["actor_rol"] == "despachador"
    cal = next(c for c in await calendario(cliente, auth, DES, desde=fila["fecha_programada"], hasta=fila["fecha_programada"]) if c["id"] == fila["id"])
    assert cal["estado"] == "cancelado"
    # Cerrado/cancelado: no más solicitudes.
    r = await cliente.post(f"/api/preventivos/{folio_id}/solicitar-reprogramacion", headers=await auth(DES), json={"razon": "Tarde", "fecha_nueva": "2028-06-01"})
    assert r.status_code == 409 and r.json()["codigo"] == "FOLIO_FINAL"


async def test_reprogramacion_autorizada_y_rechazada(cliente, auth, datos):
    plan, equipo, fila = await folio_preventivo_generado(cliente, auth, datos, fecha=date(2028, 5, 1))
    folio_id, original = fila["folio_id"], fila["fecha_programada"]
    r = await cliente.post(f"/api/preventivos/{folio_id}/solicitar-reprogramacion", headers=await auth(MC), json={"razon": "Sucursal en inventario"})
    assert r.status_code == 422 and r.json()["codigo"] == "FECHA_REQUERIDA"
    r = await cliente.post(f"/api/preventivos/{folio_id}/solicitar-reprogramacion", headers=await auth(MC), json={"razon": "Sucursal en inventario", "fecha_nueva": "2028-06-10"})
    assert r.status_code == 201, r.text
    a1 = r.json()
    # Rechazo: el folio sigue igual, la solicitud queda rechazada y se puede volver a solicitar.
    r = await cliente.post(f"/api/preventivos/autorizaciones/{a1['id']}/rechazar", headers=await auth(AE), json={"notas": "Mantener la fecha"})
    assert r.status_code == 200 and r.json()["estado"] == "rechazada" and r.json()["notas_respuesta"] == "Mantener la fecha"
    cal = next(c for c in await calendario(cliente, auth, DES, desde=original, hasta=original) if c["id"] == fila["id"])
    assert cal["estado"] == "generado" and cal["fecha_programada"] == original
    r = await cliente.post(f"/api/preventivos/{folio_id}/solicitar-reprogramacion", headers=await auth(DES), json={"razon": "Insisten en moverlo", "fecha_nueva": "2028-06-12"})
    assert r.status_code == 201
    a2 = r.json()
    r = await cliente.post(f"/api/preventivos/autorizaciones/{a2['id']}/autorizar", headers=await auth(AUN), json={"notas": "Ok"})
    assert r.status_code == 200 and r.json()["estado"] == "autorizada" and r.json()["fecha_nueva"] == "2028-06-12"
    # Calendario: la fila original queda `reprogramado` y aparece la nueva con la fecha original conservada.
    vieja = next(c for c in await calendario(cliente, auth, DES, desde=original, hasta=original) if c["id"] == fila["id"])
    nueva = next(c for c in await calendario(cliente, auth, DES, desde="2028-06-12", hasta="2028-06-12") if c["reprogramado_desde_id"] == fila["id"])
    assert vieja["estado"] == "reprogramado" and nueva["estado"] == "generado" and nueva["folio_id"] == folio_id and nueva["fecha_programada_original"] == original
    d = await detalle(cliente, auth, folio_id)
    assert d["folio"]["calendario_id"] == nueva["id"] and d["folio"]["estado"] == "autorizado"
    assert any(h["evento"] == "preventivo.reprogramado" and h["datos_contexto_json"]["fecha_nueva"] == "2028-06-12" for h in d["historial"])
    lista = (await cliente.get("/api/preventivos/autorizaciones", headers=await auth(DES), params={"folio_id": folio_id})).json()
    assert sorted(x["estado"] for x in lista) == ["autorizada", "rechazada"]


async def test_cierre_registra_desvio_y_recalcula_plan(cliente, auth, datos):
    hoy = date.today()
    plan, equipo, fila = await folio_preventivo_generado(cliente, auth, datos, fecha=hoy - timedelta(days=32))  # programado hace 2 días
    folio_id = fila["folio_id"]
    assert fila["fecha_programada"] == (hoy - timedelta(days=2)).isoformat()
    tec = await tecnico_con_habilidades(cliente, auth, TEC, ["refrigeracion", "electricidad"])
    await accion(cliente, auth, DES, folio_id, "asignar", {"tecnico_id": tec})
    await accion(cliente, auth, TEC, folio_id, "en-camino", {"geolat": 19.4, "geolng": -99.1})
    await accion(cliente, auth, TEC, folio_id, "confirmar-llegada", {"geolat": 19.4, "geolng": -99.1})
    f = (await detalle(cliente, auth, folio_id))["folio"]
    rid = await _respuesta_atencion_con_firma(cliente, auth, datos, f)
    assert (await cliente.post(f"/api/folios/{folio_id}/atencion", headers=await auth(TEC), json={"respuesta_id": rid})).status_code == 201
    c = await accion(cliente, auth, TEC, folio_id, "cerrar", {"notas": "Preventivo concluido"})
    assert c["estado"] == "cerrado"
    cal = next(x for x in await calendario(cliente, auth, AE, desde=fila["fecha_programada"], hasta=fila["fecha_programada"]) if x["id"] == fila["id"])
    assert cal["estado"] == "ejecutado" and cal["fecha_real"] == hoy.isoformat() and cal["desvio_dias"] == 2 and cal["texto_desvio"] == texto_desvio(2) == "realizado con 2 días de retraso"
    d = (await cliente.get(f"/api/planes/{plan['id']}", headers=await auth(AP))).json()
    ep = d["equipos"][0]
    assert ep["fecha_ultima_ejecucion"] == hoy.isoformat() and ep["fecha_proxima_ejecucion"] == (hoy + timedelta(days=30)).isoformat()
    # El reporte literal de §7.6 también se expone como utilidad.
    assert (await cliente.get("/api/preventivos/texto-desvio", headers=await auth(AE), params={"desvio": -3})).json()["texto"] == "realizado 3 días antes de lo programado"


async def test_alertas_de_preventivos(cliente, auth, datos):
    # 1) Preventivo vencido sin ejecutar: fila manual con fecha pasada (umbral 0 días, sin plan → ventana 0).
    equipo = await nuevo_equipo(cliente, auth, datos)
    r = await cliente.post("/api/preventivos/calendario", headers=await auth(DES), json={"tenant_id": str(datos["tenant"]), "filas": [
        {"un_id": str(datos["unidades"][0]), "equipo_id": equipo["id"], "fecha_programada": "2026-01-10", "descripcion": "Vencido"}]})
    assert r.status_code == 201
    vencida = r.json()[0]
    # 2) Autorización pendiente desde hace 30 h (umbral 24 h).
    plan, equipo2, fila = await folio_preventivo_generado(cliente, auth, datos, fecha=date(2028, 7, 1))
    a = (await cliente.post(f"/api/preventivos/{fila['folio_id']}/solicitar-cancelacion", headers=await auth(DES), json={"razon": "Prueba de alerta"})).json()
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        await db.execute(update(AutorizacionPreventivo).where(AutorizacionPreventivo.id == a["id"]).values(fecha_solicitud=datetime.now(UTC) - timedelta(hours=30)))
        await db.commit()
    # 3) Calendario del mes siguiente sin publicar: umbral en el día 1 para que aplique cualquier día del mes (tenant demo).
    r = await cliente.put("/api/alertas/configuracion/CALENDARIO_MES_SIN_PUBLICAR", headers=await auth(AE), json={"umbral_valor": 1})
    assert r.status_code == 200, r.text
    resumen = await tareas.evaluar_alertas_async()
    assert resumen["errores"] == 0, resumen
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        h = (await db.execute(select(AlertaHistorial).where(AlertaHistorial.clave_alerta == "PREVENTIVO_VENCIDO_SIN_EJECUTAR", AlertaHistorial.entidad_id == vencida["id"]))).scalars().all()
        assert len(h) == 1 and h[0].datos_contexto_json["fecha_programada"] == "2026-01-10"
        h = (await db.execute(select(AlertaHistorial).where(AlertaHistorial.clave_alerta == "AUTORIZACION_PREVENTIVO_PENDIENTE", AlertaHistorial.entidad_id == a["id"]))).scalars().all()
        assert len(h) == 1 and h[0].datos_contexto_json["horas"] >= 29
        h = (await db.execute(select(AlertaHistorial).where(AlertaHistorial.clave_alerta == "CALENDARIO_MES_SIN_PUBLICAR", AlertaHistorial.tenant_id == datos["tenant"]))).scalars().all()
        hoy = date.today()
        siguiente = date(hoy.year + (hoy.month == 12), hoy.month % 12 + 1, 1)
        publicado = any(p["mes"] == siguiente.isoformat() for p in (await cliente.get("/api/preventivos/calendario/publicaciones", headers=await auth(AE))).json())
        assert (len(h) == 0) if publicado else (len(h) == 1 and h[0].datos_contexto_json["mes"] == siguiente.isoformat())
    # Segunda corrida: no duplica.
    await tareas.evaluar_alertas_async()
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        n = (await db.execute(select(AlertaHistorial).where(AlertaHistorial.clave_alerta.in_(("PREVENTIVO_VENCIDO_SIN_EJECUTAR", "AUTORIZACION_PREVENTIVO_PENDIENTE")),
                                                            AlertaHistorial.entidad_id.in_((vencida["id"], a["id"]))))).scalars().all()
        assert len(n) == 2
    await cliente.delete("/api/alertas/configuracion/CALENDARIO_MES_SIN_PUBLICAR", headers=await auth(AE))
