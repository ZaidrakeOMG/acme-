"""Seguimiento de OC para instalación de activos (§6.10.7): clasificación en el formulario de captura y de atención, folio retenido
en revisión con `pendiente_oc_cliente`, los cinco estatus y su actor, `listo_para_asignar` automático, rechazo con cancelación y con
reprogramación a período, alta automática del equipo (completa e incompleta), vista de pendientes, aislamiento y alertas."""
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select

from core.db import nueva_sesion
from core.rls import CONTEXTO_SISTEMA
from tests.folios_utiles import AE, AP, AUN, DES, MC, OP, OTRO_AE, TEC, accion, capturar, detalle, nuevo_equipo, tecnico_con_habilidades
from tests.seguimiento_utiles import alertas_disparadas, bandeja, retroceder

_cache: dict = {}
CAMPOS_ACTIVO = [
    {"clave": "es_activo", "tipo": "si_no", "etiqueta": "¿Instalación de activo nuevo?", "config": {},
     "clasifica_instalacion_activo": {"valor_afirmativo": "si", "campo_tipo_equipo": "tipo_eq", "campo_marca": "marca", "campo_modelo": "modelo", "campo_serie": "serie",
                                      "campo_valor_reposicion": "valor"}},
    {"clave": "tipo_eq", "tipo": "texto", "etiqueta": "Tipo de equipo", "config": {"longitud_min": 0, "longitud_max": 120}},
    {"clave": "marca", "tipo": "texto", "etiqueta": "Marca", "config": {"longitud_min": 0, "longitud_max": 80}},
    {"clave": "modelo", "tipo": "texto", "etiqueta": "Modelo", "config": {"longitud_min": 0, "longitud_max": 80}},
    {"clave": "serie", "tipo": "texto", "etiqueta": "Serie", "config": {"longitud_min": 0, "longitud_max": 80}},
    {"clave": "valor", "tipo": "texto", "etiqueta": "Valor de reposición", "config": {"longitud_min": 0, "longitud_max": 20, "formato": "numeros"}},
]


async def _formulario(cliente, auth, tipo="captura_operador"):
    from tests.test_formularios import crear_formulario, publicar

    if tipo not in _cache:
        roles = ["operador", "admin_un", "admin_empresa"] if tipo == "captura_operador" else ["tecnico"]
        f = await crear_formulario(cliente, auth, AP, tipo=tipo, rol_destino=roles, esquema={"secciones": [{"clave": "a", "titulo": "Activo", "campos": CAMPOS_ACTIVO}]})
        await publicar(cliente, auth, f["id"])
        _cache[tipo] = f
    return _cache[tipo]


async def _respuesta(cliente, auth, datos, email, origen, equipo, referencia=None, **valores) -> str:
    f = await _formulario(cliente, auth, "captura_operador" if origen == "folio_captura" else "atencion_tecnico")
    cuerpo = {"origen": origen, "contexto": {"tenant_id": str(datos["tenant"]), "un_id": equipo["un_id"], "equipo_id": equipo["id"]},
              "respuestas": {"es_activo": True, "tipo_eq": "Refrigerador vertical", "marca": "Imbera", "modelo": "VR-12", "serie": "IMB-0451", "valor": "28500", **valores}}
    if referencia:
        cuerpo["referencia_id"] = referencia
    r = await cliente.post(f"/api/formularios/{f['id']}/respuestas", headers=await auth(email), json=cuerpo)
    assert r.status_code == 201, r.text
    env = await cliente.post(f"/api/formularios/respuestas/{r.json()['id']}/enviar", headers=await auth(email))
    assert env.status_code == 200, env.text
    return r.json()["id"]


async def folio_activo(cliente, auth, datos, email=OP, **valores) -> dict:
    """Folio capturado con el formulario de captura que lo clasifica como instalación de activo."""
    equipo = await nuevo_equipo(cliente, auth, datos, criticidad="A")
    rid = await _respuesta(cliente, auth, datos, email, "folio_captura", equipo, **valores)
    return await capturar(cliente, auth, datos, email, equipo, descripcion="Instalación de refrigerador nuevo para bebidas", respuesta_id=rid)


async def estatus(cliente, auth, folio_id, nuevo, email=AE, esperado=200, **campos) -> dict:
    r = await cliente.post(f"/api/oc-activos/{folio_id}/estatus", headers=await auth(email), json={"estatus": nuevo, **campos})
    assert r.status_code == esperado, f"{nuevo}: {r.status_code} {r.text}"
    return r.json()


async def test_esquema_valida_las_referencias_del_mapeo(cliente, auth):
    campos = [{**CAMPOS_ACTIVO[0], "clasifica_instalacion_activo": {"campo_marca": "inexistente"}}, *CAMPOS_ACTIVO[1:]]
    r = await cliente.post("/api/formularios", headers=await auth(AP), json={"nombre": "Mal mapeo", "tipo": "captura_operador", "rol_destino": ["operador"],
                                                                             "esquema": {"secciones": [{"clave": "a", "titulo": "A", "campos": campos}]}})
    assert r.status_code == 422
    texto = [{**CAMPOS_ACTIVO[1], "clasifica_instalacion_activo": {}}, *CAMPOS_ACTIVO[2:]]
    r = await cliente.post("/api/formularios", headers=await auth(AP), json={"nombre": "Tipo no permitido", "tipo": "captura_operador", "rol_destino": ["operador"],
                                                                             "esquema": {"secciones": [{"clave": "a", "titulo": "A", "campos": texto}]}})
    assert r.status_code == 422


async def test_folio_clasificado_espera_la_oc_y_el_cliente_lo_ve_pendiente(cliente, auth, datos):
    f = await folio_activo(cliente, auth, datos)
    assert f["estado"] == "en_revision" and f["es_instalacion_activo"] is True and f["flujo"] is None  # sin flujo multinivel mientras espera OC
    d = await detalle(cliente, auth, f["id"])
    assert [t["trigger_tipo"] for t in d["triggers_revision"]] == ["pendiente_oc_cliente"] and d["triggers_revision"][0]["resuelto"] is False
    assert d["oc_activo"]["estatus_multinivel"] == "pendiente_iniciar_tramite" and d["oc_activo"]["origen"] == "captura" and d["oc_activo"]["datos_equipo"]["marca"] == "Imbera"
    assert d["oc_activo"]["destinos"] == ["oc_en_tramite", "oc_autorizada", "oc_rechazada"] and d["oc_activo"]["historial"][0]["estatus_nuevo"] == "pendiente_iniciar_tramite"
    assert any(h["evento"] == "activo.clasificado" for h in d["historial"])
    assert any(n["evento"] == "oc_activo.pendiente" and n["datos"]["folio_id"] == f["id"] for n in await bandeja(cliente, auth, AUN, solo_no_leidas=True))
    assert any(n["evento"] == "oc_activo.pendiente" and n["datos"]["folio_id"] == f["id"] for n in await bandeja(cliente, auth, AE, solo_no_leidas=True))
    # Vista de pendientes: Admin UN (su UN), Admin empresa y Mesa de control; no el operador ni otro tenant.
    for email in (AUN, AE, MC):
        pend = (await cliente.get("/api/oc-activos/pendientes", headers=await auth(email))).json()
        mio = next(p for p in pend if p["folio_id"] == f["id"])
        assert mio["folio"]["numero_folio"] == f["numero_folio"] and mio["dias_en_estatus"] == 0
    assert (await cliente.get("/api/oc-activos/pendientes", headers=await auth(OP))).status_code == 403
    assert all(p["folio_id"] != f["id"] for p in (await cliente.get("/api/oc-activos/pendientes", headers=await auth(OTRO_AE))).json())
    assert (await cliente.get(f"/api/oc-activos/{f['id']}", headers=await auth(OTRO_AE))).status_code == 404
    # Un folio sin la bandera afirmativa no se clasifica.
    g = await folio_activo(cliente, auth, datos, es_activo=False)
    assert g["es_instalacion_activo"] is False and (await detalle(cliente, auth, g["id"]))["oc_activo"] is None


async def test_estatus_literales_y_listo_para_asignar_automatico(cliente, auth, datos):
    f = await folio_activo(cliente, auth, datos)
    assert (await estatus(cliente, auth, f["id"], "oc_en_tramite", AUN, 403))["codigo"] == "PROHIBIDO"
    assert (await estatus(cliente, auth, f["id"], "oc_en_tramite", DES, 403))["codigo"] == "PROHIBIDO"
    assert (await estatus(cliente, auth, f["id"], "listo_para_asignar", AE, 409))["codigo"] == "TRANSICION_NO_PERMITIDA"  # lo fija el sistema
    a = await estatus(cliente, auth, f["id"], "oc_en_tramite", numero_oc_provisional="OC-PROV-7", notas="Solicitud creada en SAP")
    assert a["estatus_multinivel"] == "oc_en_tramite" and a["numero_oc_provisional"] == "OC-PROV-7" and a["registrado_por"] and a["destinos"] == ["oc_autorizada", "oc_rechazada"]
    assert (await estatus(cliente, auth, f["id"], "oc_autorizada", esperado=422))["codigo"] == "OC_DEFINITIVA_REQUERIDA"
    a = await estatus(cliente, auth, f["id"], "oc_autorizada", numero_oc_definitivo="4500123987", fecha_autorizacion_erp=date.today().isoformat())
    assert a["estatus_multinivel"] == "listo_para_asignar" and a["numero_oc_definitivo"] == "4500123987" and a["destinos"] == []
    assert [h["estatus_nuevo"] for h in a["historial"]] == ["pendiente_iniciar_tramite", "oc_en_tramite", "oc_autorizada", "listo_para_asignar"]
    assert a["historial"][-1]["actor_rol"] == "sistema" and a["folio"]["estado"] == "autorizado"
    d = await detalle(cliente, auth, f["id"])
    assert d["triggers_revision"][0]["resuelto"] is True and d["sla"] is not None and any(h["evento"] == "activo.oc" for h in d["historial"])
    assert any(n["evento"] == "oc_activo.autorizada" for n in await bandeja(cliente, auth, DES))
    assert (await estatus(cliente, auth, f["id"], "oc_rechazada", esperado=409, decision_rechazo="cancelar"))["codigo"] == "TRANSICION_NO_PERMITIDA"


async def test_rechazo_con_cancelacion_y_con_reprogramacion_a_periodo(cliente, auth, datos):
    f = await folio_activo(cliente, auth, datos)
    assert (await estatus(cliente, auth, f["id"], "oc_rechazada", esperado=422))["codigo"] == "DECISION_REQUERIDA"
    a = await estatus(cliente, auth, f["id"], "oc_rechazada", decision_rechazo="cancelar", notas="Compras no autorizó la inversión")
    assert a["estatus_multinivel"] == "oc_rechazada" and a["decision_rechazo"] == "cancelar" and a["folio"]["estado"] == "cancelado"
    assert "OC rechazada" in a["folio"]["razon_cancelacion"] and "Compras no autorizó" in a["folio"]["razon_cancelacion"]
    g = await folio_activo(cliente, auth, datos, email=AUN)
    await estatus(cliente, auth, g["id"], "oc_en_tramite")
    assert (await estatus(cliente, auth, g["id"], "oc_rechazada", esperado=422, decision_rechazo="reprogramar_periodo"))["codigo"] == "PERIODO_REQUERIDO"
    a = await estatus(cliente, auth, g["id"], "oc_rechazada", decision_rechazo="reprogramar_periodo", periodo_presupuestal_destino="2027-T1", notas="Sin presupuesto este año")
    assert a["periodo_presupuestal_destino"] == "2027-T1" and a["hallazgo_presupuesto_id"] and a["folio"]["estado"] == "cancelado"
    d = await detalle(cliente, auth, g["id"])
    deriv = next(x for x in d["derivaciones"] if x["modulo"] == "por_presupuesto")
    assert deriv["registro_id"] == a["hallazgo_presupuesto_id"] and deriv["origen"] == "oc_rechazada"
    r = await cliente.get(f"/api/seguimiento/presupuesto/{deriv['registro_id']}", headers=await auth(AE))
    assert r.status_code == 200 and r.json()["periodo_presupuestal"] == "2027-T1" and r.json()["estado"] == "diferido"
    # Los resueltos salen de la vista de pendientes salvo que se pidan.
    assert all(p["folio_id"] not in (f["id"], g["id"]) for p in (await cliente.get("/api/oc-activos/pendientes", headers=await auth(AE))).json())
    assert any(p["folio_id"] == g["id"] for p in (await cliente.get("/api/oc-activos/pendientes", headers=await auth(AE), params={"incluir_resueltos": True})).json())


async def _cerrar(cliente, auth, datos, f) -> dict:
    from tests.test_cierre_folio import _respuesta_atencion, firmar

    tec = await tecnico_con_habilidades(cliente, auth, TEC, ["refrigeracion", "electricidad"])
    await accion(cliente, auth, DES, f["id"], "asignar", {"tecnico_id": tec})
    await accion(cliente, auth, TEC, f["id"], "en-camino")
    await accion(cliente, auth, TEC, f["id"], "confirmar-llegada")
    rid = await _respuesta_atencion(cliente, auth, datos, f)
    await accion(cliente, auth, TEC, f["id"], "atencion", {"respuesta_id": rid}, esperado=201)
    await firmar(cliente, auth, OP, f["id"])
    return await accion(cliente, auth, TEC, f["id"], "cerrar")


async def test_alta_automatica_del_equipo_al_cerrar(cliente, auth, datos):
    from models.catalogos import Equipo

    f = await folio_activo(cliente, auth, datos)
    await estatus(cliente, auth, f["id"], "oc_autorizada", numero_oc_definitivo="4500999", fecha_autorizacion_erp=date.today().isoformat())
    c = await _cerrar(cliente, auth, datos, f)
    assert c["estado"] == "cerrado" and c["equipo_instalado_id"]
    d = await detalle(cliente, auth, f["id"])
    assert d["oc_activo"]["equipo_instalado"]["codigo"] == f"ACT-{f['numero_folio']}" and d["oc_activo"]["equipo_instalado"]["estado"] == "activo"
    assert any(h["evento"] == "transicion" and h["estado_nuevo"] == "cerrado" and h["datos_contexto_json"].get("equipo_instalado_codigo") for h in d["historial"])
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        e = (await db.execute(select(Equipo).where(Equipo.id == c["equipo_instalado_id"]))).scalar_one()
        assert e.marca == "Imbera" and e.modelo == "VR-12" and e.numero_serie == "IMB-0451" and str(e.valor_reposicion) == "28500.00" and str(e.un_id) == f["un_id"]
        assert e.fecha_instalacion == date.today() and e.contrato_id is not None and e.tipo_equipo_id is not None and e.estado.value == "activo"
    # Ficha incompleta (sin tipo de equipo): queda inactivo con la alerta y aviso al Admin empresa.
    g = await folio_activo(cliente, auth, datos, tipo_eq="")
    await estatus(cliente, auth, g["id"], "oc_autorizada", numero_oc_definitivo="4500998", fecha_autorizacion_erp=date.today().isoformat())
    c2 = await _cerrar(cliente, auth, datos, g)
    d2 = await detalle(cliente, auth, g["id"])
    assert d2["oc_activo"]["equipo_instalado"]["estado"] == "inactivo"
    assert await alertas_disparadas("ACTIVO_INSTALADO_INCOMPLETO", c2["equipo_instalado_id"])
    assert any(n["evento"] == "oc_activo.equipo_incompleto" and n["datos"]["equipo_id"] == c2["equipo_instalado_id"] for n in await bandeja(cliente, auth, AE))


async def test_clasificacion_desde_el_formulario_de_atencion(cliente, auth, datos):
    from tests.test_cierre_folio import _en_ejecucion

    f = await _en_ejecucion(cliente, auth, datos)
    equipo = {"id": f["equipo_id"], "un_id": f["un_id"]}
    await _respuesta(cliente, auth, datos, TEC, "folio_atencion", equipo, referencia=f["id"], marca="Carrier")
    d = await detalle(cliente, auth, f["id"])
    assert d["folio"]["es_instalacion_activo"] is True and d["folio"]["estado"] == "en_ejecucion"  # el folio en atención continúa; la OC se sigue en paralelo
    assert d["oc_activo"]["origen"] == "atencion" and d["oc_activo"]["datos_equipo"]["marca"] == "Carrier" and d["oc_activo"]["estatus_multinivel"] == "pendiente_iniciar_tramite"
    assert any(p["folio_id"] == f["id"] for p in (await cliente.get("/api/oc-activos/pendientes", headers=await auth(AE))).json())


async def test_alertas_de_oc(cliente, auth, datos):
    from models.trabajos_especiales import FolioActivoAutorizacion
    from workers import tareas

    f = await folio_activo(cliente, auth, datos)
    g = await folio_activo(cliente, auth, datos)
    await estatus(cliente, auth, g["id"], "oc_en_tramite", numero_oc_provisional="P-1")
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        ids = {str(a.folio_id): a.id for a in (await db.execute(select(FolioActivoAutorizacion).where(FolioActivoAutorizacion.folio_id.in_([f["id"], g["id"]])))).scalars()}
    hace = datetime.now(UTC) - timedelta(days=40)
    await retroceder(FolioActivoAutorizacion, ids[f["id"]], estatus_desde=hace)
    await retroceder(FolioActivoAutorizacion, ids[g["id"]], estatus_desde=hace)
    await tareas.evaluar_alertas_async()
    assert await alertas_disparadas("OC_ACTIVO_SIN_TRAMITE", f["id"])
    assert await alertas_disparadas("OC_ACTIVO_EN_TRAMITE_PROLONGADO", g["id"])
    pend = next(p for p in (await cliente.get("/api/oc-activos/pendientes", headers=await auth(AE))).json() if p["folio_id"] == f["id"])
    assert pend["dias_en_estatus"] >= 40
