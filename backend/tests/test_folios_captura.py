"""Captura de folios (§6.8.6): quién captura, las 8 validaciones automáticas en orden, duplicados, severidad, alcance por rol."""
from datetime import UTC, datetime

import pytest
from sqlalchemy import text

from core.db import nueva_sesion
from core.rls import CONTEXTO_SISTEMA
from services.folios_captura_service import dentro_de_horario
from tests.folios_utiles import (
    AE, AP, AUN, DES, MC, OP, OTRO_AE, OTRO_OP, SA, SUPO, TEC, accion, capturar, detalle, nuevo_equipo, politicas, tipo_falla,
)


def _triggers(d: dict) -> set[str]:
    return {t["trigger_tipo"] for t in d["triggers_revision"]}


# ------------------------------------------------------------ quién captura

async def test_roles_que_capturan_siempre_y_numero_correlativo(cliente, auth, datos):
    numeros = []
    for email in (OP, AUN, AE, SUPO, MC):
        f = await capturar(cliente, auth, datos, email)
        assert f["numero_folio"].startswith("CD-") and f["confirmacion_un"] is True
        numeros.append(int(f["numero_folio"].split("-")[1]))
    assert numeros == sorted(numeros) and len(set(numeros)) == 5
    assert (await capturar(cliente, auth, datos, "direccion@acma.dev", esperado=403))["codigo"] == "PROHIBIDO"


async def test_tecnico_y_despachador_requieren_permiso_configurable(cliente, auth, datos):
    h = await auth(AP)
    # Técnico sin crear_folio_en_campo (default False) → 403; con el permiso → 201.
    assert (await capturar(cliente, auth, datos, TEC, esperado=403))["mensaje"].startswith("Tu prestador no te habilitó")
    assert (await cliente.put("/api/configuracion/permisos-tecnico", headers=h, json={"valores": {"crear_folio_en_campo": True}})).status_code == 200
    f = await capturar(cliente, auth, datos, TEC)
    assert f["capturado_por_nombre"] == "Tomás Técnico"
    await cliente.put("/api/configuracion/permisos-tecnico", headers=h, json={"valores": {"crear_folio_en_campo": False}})
    # Despachador: crear_folios es True por default; al apagarlo para este cliente, 403.
    assert (await capturar(cliente, auth, datos, DES))["estado"] in ("en_revision", "autorizado")
    desp = (await cliente.get("/api/usuarios", headers=h, params={"rol": "despachador"})).json()[0]
    assert (await cliente.put("/api/configuracion/permisos-despachador", headers=h,
                              json={"valores": {"crear_folios": False}, "despachador_id": desp["id"], "tenant_id": str(datos["tenant"])})).status_code == 200
    assert (await capturar(cliente, auth, datos, DES, esperado=403))["codigo"] == "PROHIBIDO"
    await cliente.put("/api/configuracion/permisos-despachador", headers=h,
                      json={"valores": {"crear_folios": True}, "despachador_id": desp["id"], "tenant_id": str(datos["tenant"])})


async def test_operador_solo_captura_en_sus_un_y_el_equipo_debe_ser_de_la_un(cliente, auth, datos):
    ajeno = await nuevo_equipo(cliente, auth, datos, un_index=2)  # SUC-003 no está asignada al operador
    r = await capturar(cliente, auth, datos, OP, ajeno, esperado=422)
    assert r["codigo"] == "UNIDAD_INVALIDA"
    e = await nuevo_equipo(cliente, auth, datos)
    tf = await tipo_falla(cliente, auth)
    cuerpo = {"un_id": str(datos["unidades"][1]), "equipo_id": e["id"], "tipo_falla_id": tf["id"], "descripcion": "Equipo de otra UN", "confirmacion_un": True}
    r = await cliente.post("/api/folios", headers=await auth(AUN), json=cuerpo)
    assert r.status_code == 422 and r.json()["codigo"] == "EQUIPO_INVALIDO"
    # Tipo de falla de otra familia.
    r = await capturar(cliente, auth, datos, OP, e, falla="Gotea agua", familia="Climatización", esperado=422)
    assert r["codigo"] == "TIPO_FALLA_INVALIDO"


# ----------------------------------------------------- validaciones 1 a 8

async def test_1_sin_confirmacion_un_queda_en_captura_y_se_completa_despues(cliente, auth, datos):
    from services import notificaciones

    f = await capturar(cliente, auth, datos, OP, confirmacion=False)
    assert f["estado"] == "capturado" and f["confirmacion_un"] is False
    d = await detalle(cliente, auth, f["id"])
    assert _triggers(d) == {"confirmacion_un_faltante"}
    assert any(n["titulo"].endswith("en espera") and str(f["id"]) in str(n["datos"]) for n in notificaciones.ENVIADAS)
    # Otro usuario que no capturó ni tiene rol de captura no puede confirmar; el operador sí, y el folio sigue su camino.
    assert (await accion(cliente, auth, TEC, f["id"], "confirmar-un", {"geolat": 19.43, "geolng": -99.13}, 404))["codigo"] == "NO_ENCONTRADO"
    r = await accion(cliente, auth, OP, f["id"], "confirmar-un", {"geolat": 19.43, "geolng": -99.13})
    assert r["confirmacion_un"] is True and r["estado"] == "en_revision" and r["flujo"]["nivel_actual"] == 1
    d = await detalle(cliente, auth, f["id"])
    assert all(t["resuelto"] for t in d["triggers_revision"] if t["trigger_tipo"] == "confirmacion_un_faltante")
    assert d["captura"]["confirmacion_un_geolat"] == 19.43


async def test_2_equipo_sin_contrato_pasa_a_revision(cliente, auth, datos):
    contratos = (await cliente.get("/api/contratos", headers=await auth(AE))).json()
    vencido = next(c for c in contratos if "vencido" in c["nombre"])
    e = await nuevo_equipo(cliente, auth, datos, contrato_id=vencido["id"])
    assert e["con_contrato_activo"] is False
    f = await capturar(cliente, auth, datos, OP, e)
    assert f["estado"] == "en_revision"
    d = await detalle(cliente, auth, f["id"])
    assert _triggers(d) == {"sin_contrato"} and "2025" in d["triggers_revision"][0]["descripcion"]
    assert d["aprobacion"] is None  # la excepción se resuelve antes del flujo


async def test_3_duplicado_con_justificacion_y_con_bloqueo_total(cliente, auth, datos):
    e = await nuevo_equipo(cliente, auth, datos)
    primero = await capturar(cliente, auth, datos, OP, e)
    tarjeta = (await cliente.get("/api/folios/verificar-duplicado", headers=await auth(OP), params={"equipo_id": e["id"]})).json()
    assert tarjeta["existe"] and tarjeta["numero_folio"] == primero["numero_folio"] and tarjeta["bloqueo_total"] is False
    # Sin justificación: 422; con justificación (confirmación fuerte): se guarda la referencia.
    r = await capturar(cliente, auth, datos, OP, e, esperado=422)
    assert r["codigo"] == "JUSTIFICACION_REQUERIDA" and r["detalles"][0]["numero_folio"] == primero["numero_folio"]
    segundo = await capturar(cliente, auth, datos, OP, e, folio_duplicado_justificacion="Es otra falla: ahora hace ruido")
    d = await detalle(cliente, auth, segundo["id"])
    assert d["captura"]["folio_duplicado_ref_id"] == primero["id"] and d["captura"]["folio_duplicado_ref_numero"] == primero["numero_folio"]
    # Bloqueo total: 409 y el intento queda en auditoría.
    await politicas(cliente, auth, bloqueo_total_duplicados=True)
    try:
        r = await capturar(cliente, auth, datos, OP, e, folio_duplicado_justificacion="Otra más", esperado=409)
        assert r["codigo"] == "FOLIO_DUPLICADO_BLOQUEADO"
        tarjeta = (await cliente.get("/api/folios/verificar-duplicado", headers=await auth(OP), params={"equipo_id": e["id"]})).json()
        assert tarjeta["bloqueo_total"] is True
        eventos = (await cliente.get("/api/auditoria/eventos", headers=await auth(SA), params={"evento_tipo": "folio.duplicado_bloqueado"})).json()
        assert any(primero["id"] in str(ev) for ev in (eventos if isinstance(eventos, list) else eventos.get("items", [])))
    finally:
        await politicas(cliente, auth, bloqueo_total_duplicados=False)


async def test_4_severidad_automatica_por_matriz_y_no_configurada(cliente, auth, datos):
    # Refrigerador vertical × "No enciende" → crítica (seed de P02).
    f = await capturar(cliente, auth, datos, OP, falla="No enciende")
    assert f["severidad"]["clave"] == "critica" and f["severidad_origen"] == "automatica_matriz"
    # Sin celda en la matriz: tipo de falla nuevo sin configurar.
    h = await auth(AP)
    familias = {x["nombre"]: x for x in (await cliente.get("/api/catalogos/familias-equipo", headers=h)).json()}
    nueva = (await cliente.post("/api/catalogos/tipos-falla", headers=h, json={"descripcion": "Vibra demasiado", "familia_equipo_id": familias["Refrigeración"]["id"]})).json()
    e = await nuevo_equipo(cliente, auth, datos)
    cuerpo = {"un_id": e["un_id"], "equipo_id": e["id"], "tipo_falla_id": nueva["id"], "descripcion": "Vibra y se mueve", "confirmacion_un": True}
    r = await cliente.post("/api/folios", headers=await auth(OP), json=cuerpo)
    assert r.status_code == 201 and r.json()["estado"] == "en_revision" and r.json()["severidad"] is None
    d = await detalle(cliente, auth, r.json()["id"])
    assert _triggers(d) == {"severidad_no_configurada"}
    historial = (await cliente.get("/api/alertas/historial", headers=await auth(AE))).json()
    assert any(a["clave_alerta"] == "MATRIZ_SEVERIDAD_INCOMPLETA" and a["entidad_id"] == r.json()["id"] for a in historial)
    # Override por el despachador con razón: severidad_origen = override_admin y el trigger queda resuelto.
    niveles = (await cliente.get("/api/catalogos/severidades", headers=await auth(DES))).json()
    media = next(n for n in niveles if n["clave"] == "media")
    assert (await cliente.put(f"/api/folios/{r.json()['id']}/severidad", headers=await auth(OP), json={"severidad_id": media["id"], "razon": "No aplica"})).status_code == 403
    o = await cliente.put(f"/api/folios/{r.json()['id']}/severidad", headers=await auth(DES), json={"severidad_id": media["id"], "razon": "Equipo secundario"})
    assert o.status_code == 200 and o.json()["severidad"]["clave"] == "media" and o.json()["severidad_origen"] == "override_admin"
    d = await detalle(cliente, auth, r.json()["id"])
    assert all(t["resuelto"] for t in d["triggers_revision"])
    assert (await cliente.patch(f"/api/catalogos/tipos-falla/{nueva['id']}", headers=h, json={"activa": False})).status_code == 200


async def test_5_garantia_con_revision_obligatoria(cliente, auth, datos):
    e = await nuevo_equipo(cliente, auth, datos, garantia_vigente_hasta="2030-01-01")
    f = await capturar(cliente, auth, datos, OP, e)  # el seed deja revision_obligatoria_garantia = true
    assert f["estado"] == "en_revision" and _triggers(await detalle(cliente, auth, f["id"])) == {"garantia"}
    # Solo el Admin prestador (o Admin empresa) cambian la política; sin ella, un equipo en garantía pasa.
    r = await cliente.put("/api/folios/politicas", headers=await auth(AP), params={"tenant_id": str(datos["tenant"])}, json={"revision_obligatoria_garantia": False})
    assert r.status_code == 200 and r.json()["revision_obligatoria_garantia"] is False
    assert (await cliente.put("/api/folios/politicas", headers=await auth(AP), params={"tenant_id": str(datos["tenant"])}, json={"prefijo_folio": "XX"})).status_code == 403
    try:
        e2 = await nuevo_equipo(cliente, auth, datos, garantia_vigente_hasta="2030-01-01")
        f2 = await capturar(cliente, auth, datos, OP, e2)
        assert f2["estado"] == "en_revision" and f2["flujo"] is not None and _triggers(await detalle(cliente, auth, f2["id"])) == set()
    finally:
        await politicas(cliente, auth, revision_obligatoria_garantia=True)


async def test_6_tipo_de_falla_con_revision_manual(cliente, auth, datos):
    f = await capturar(cliente, auth, datos, OP, familia="Iluminación", falla="Parpadea")  # flag global activado en el seed
    assert f["estado"] == "en_revision" and _triggers(await detalle(cliente, auth, f["id"])) == {"tipo_falla_flag"}


def test_7_funcion_de_horario_de_servicio():
    horario = {"lunes": [["08:00", "18:00"]], "sabado": [["09:00", "14:00"], ["16:00", "18:00"]]}
    lunes_10 = datetime(2026, 10, 26, 16, 0, tzinfo=UTC)       # 10:00 CDMX
    lunes_19 = datetime(2026, 10, 27, 1, 0, tzinfo=UTC)        # 19:00 CDMX del lunes
    sabado_17 = datetime(2026, 10, 24, 23, 0, tzinfo=UTC)      # 17:00 CDMX
    domingo = datetime(2026, 10, 25, 18, 0, tzinfo=UTC)
    assert dentro_de_horario(horario, lunes_10) and not dentro_de_horario(horario, lunes_19)
    assert dentro_de_horario(horario, sabado_17) and not dentro_de_horario(horario, domingo)
    assert dentro_de_horario(None, domingo) and dentro_de_horario({}, domingo)
    assert dentro_de_horario({"domingo": [["00:00", "23:59"]]}, domingo, "Zona/Invalida")


async def test_7_fuera_de_horario_del_contrato_pasa_a_revision(cliente, auth, datos):
    h = await auth(AP)
    contratos = (await cliente.get("/api/contratos", headers=h, params={"tenant_id": str(datos["tenant"])})).json()
    vigente = next(c for c in contratos if "2026" in c["nombre"])
    # conftest deja el contrato abierto los siete dias para que la suite no dependa de la hora del reloj.
    assert vigente["horario_servicio_json"]["lunes"] == [["00:00", "23:59"]]
    assert (await cliente.patch(f"/api/contratos/{vigente['id']}", headers=h, json={"horario_servicio_json": {"lunes": [["18:00", "08:00"]]}})).status_code == 422
    r = await cliente.patch(f"/api/contratos/{vigente['id']}", headers=h, json={"horario_servicio_json": {d: [["00:00", "00:01"]] for d in ("lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo")}})
    assert r.status_code == 200
    try:
        f = await capturar(cliente, auth, datos, OP)
        assert f["estado"] == "en_revision" and _triggers(await detalle(cliente, auth, f["id"])) == {"fuera_horario"}
    finally:
        assert (await cliente.patch(f"/api/contratos/{vigente['id']}", headers=h, json={"horario_servicio_json": vigente["horario_servicio_json"]})).status_code == 200


async def test_8_palabra_clave_de_alerta(cliente, auth, datos):
    f = await capturar(cliente, auth, datos, OP, descripcion="Se escuchan CHISPAS dentro del tablero eléctrico")
    assert f["estado"] == "en_revision"
    d = await detalle(cliente, auth, f["id"])
    assert _triggers(d) == {"keyword_alerta"} and "chispas" in d["triggers_revision"][0]["descripcion"]
    # "Fuga de gas" con acentos/mayúsculas; "humo" dentro de otra palabra no cuenta.
    f2 = await capturar(cliente, auth, datos, OP, descripcion="Posible FÚGA DE GAS en la línea")
    assert _triggers(await detalle(cliente, auth, f2["id"])) == {"keyword_alerta"}
    f3 = await capturar(cliente, auth, datos, OP, descripcion="El ahumador de la cocina no enciende")
    assert f3["estado"] == "en_revision" and f3["flujo"] is not None and _triggers(await detalle(cliente, auth, f3["id"])) == set()
    # Admin prestador administra la lista.
    lista = (await cliente.get("/api/folios/keywords", headers=await auth(AP))).json()
    assert {k["palabra"] for k in lista} >= {"incendio", "humo", "chispas", "fuga de gas"}
    assert (await cliente.put("/api/folios/keywords", headers=await auth(AE), json=[])).status_code == 403


async def test_varios_triggers_se_acumulan(cliente, auth, datos):
    e = await nuevo_equipo(cliente, auth, datos, familia="Iluminación", garantia_vigente_hasta="2030-01-01")
    f = await capturar(cliente, auth, datos, OP, e, familia="Iluminación", falla="Parpadea", descripcion="Parpadea y huele a incendio")
    assert _triggers(await detalle(cliente, auth, f["id"])) == {"garantia", "tipo_falla_flag", "keyword_alerta"}


async def test_todas_las_validaciones_pasan_y_entra_al_flujo(cliente, auth, datos):
    e = await nuevo_equipo(cliente, auth, datos, criticidad="C")
    f = await capturar(cliente, auth, datos, OP, e)
    assert f["estado"] == "en_revision" and f["triggers_pendientes"] == 0
    assert f["flujo"]["nivel_actual"] == 1 and f["flujo"]["estado"] == "activo" and f["flujo"]["rol_aprobador_actual"] == "admin_un"
    d = await detalle(cliente, auth, f["id"])
    assert [h["evento"] for h in d["historial"]] == ["transicion", "transicion", "aprobacion.inicio"]
    assert d["historial"][1]["actor_rol"] == "sistema" and d["chat"] == [] and d["reasignaciones"] == []
    assert d["financiero"]["visible"] is True and d["financiero"]["costo"] is None and d["financiero"]["refacciones"] == []


async def test_monto_estimado_solo_prestador_en_captura_o_revision(cliente, auth, datos):
    f = await capturar(cliente, auth, datos, OP, monto_estimado=9999)
    assert f["monto_estimado"] is None  # el operador no lo fija
    assert (await cliente.put(f"/api/folios/{f['id']}/monto-estimado", headers=await auth(AE), json={"monto_estimado": 100})).status_code == 403
    r = await cliente.put(f"/api/folios/{f['id']}/monto-estimado", headers=await auth(MC), json={"monto_estimado": 7500.5})
    assert r.status_code == 200 and float(r.json()["monto_estimado"]) == 7500.5
    g = await capturar(cliente, auth, datos, MC, monto_estimado=25000)
    assert float(g["monto_estimado"]) == 25000 and g["flujo"]["nivel_actual"] == 3


# ---------------------------------------------------------- alcance por rol

async def test_alcance_del_listado_por_rol(cliente, auth, datos):
    un1, un2, un3 = (str(u) for u in datos["unidades"])
    async def unidades_de(email, **params):
        r = await cliente.get("/api/folios", headers=await auth(email), params={"limite": 2000, **params})
        assert r.status_code == 200, r.text
        return r.json()
    assert {f["un_id"] for f in await unidades_de(OP)} == {un1}
    assert {f["un_id"] for f in await unidades_de(AUN)} <= {un1, un2} and un2 in {f["un_id"] for f in await unidades_de(AUN)}
    assert {f["un_id"] for f in await unidades_de(SUPO)} == {un1, un2, un3}
    todos = await unidades_de(AE)
    assert {f["un_id"] for f in todos} == {un1, un2, un3} and all(f["tenant_id"] == str(datos["tenant"]) for f in todos)
    assert len(await unidades_de(DES)) == len(todos) and len(await unidades_de(MC)) == len(todos)
    tec = await unidades_de(TEC)
    tec_id = next(f["tecnico_id"] for f in tec if f["tecnico_id"])
    assert all(f["tecnico_id"] == tec_id or f["capturado_por"] == tec_id for f in tec)
    assert len(await unidades_de(OTRO_AE)) == 0 and len(await unidades_de(OTRO_OP)) == 0
    # Filtros.
    assert all(f["estado"] == "cerrado" for f in await unidades_de(AE, estado="cerrado")) and len(await unidades_de(AE, estado="cerrado")) >= 1
    assert all(f["un_id"] == un2 for f in await unidades_de(AE, un_id=un2))
    grupos = (await cliente.get("/api/grupos-un", headers=await auth(AE))).json()
    assert len(await unidades_de(AE, grupo_id=grupos[0]["id"])) == len(todos)
    assert all("CD-0000" in f["numero_folio"] for f in await unidades_de(AE, q="cd-0000"))


async def test_aislamiento_entre_tenants(cliente, auth, datos):
    f = await capturar(cliente, auth, datos, OP)
    assert (await cliente.get(f"/api/folios/{f['id']}", headers=await auth(OTRO_AE))).status_code == 404
    assert (await cliente.get(f"/api/folios/{f['id']}/historial", headers=await auth(OTRO_AE))).status_code == 404
    assert (await cliente.post(f"/api/folios/{f['id']}/cancelar", headers=await auth("admin.otroprestador@acma.dev"), json={"razon": "Prueba"})).status_code == 404
    # El otro tenant tampoco ve la configuración ni los folios por RLS directa.
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        n = (await db.execute(text("SELECT count(*) FROM folios WHERE tenant_id = :t"), {"t": datos["otro_tenant"]})).scalar()
    assert n == 0
    assert (await cliente.get("/api/folios/politicas", headers=await auth(OTRO_AE))).json()["prefijo_folio"] == "F"


@pytest.mark.parametrize("tabla", ["folios", "folio_estados_historial", "revision_manual_triggers", "aprobacion_flujos", "aprobacion_decisiones",
                                   "aprobacion_alertas_timeout", "folio_politicas_tenant", "aprobacion_reglas", "aprobacion_niveles_config",
                                   "folio_keywords_alerta", "folio_sla", "folio_evidencias", "folio_formulario_atencion"])
async def test_rls_forzada_en_tablas_nuevas(datos, tabla):
    from core.rls import ContextoRLS
    async with nueva_sesion(ContextoRLS()) as db:
        fila = (await db.execute(text("SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = :t"), {"t": tabla})).one()
        assert fila.relrowsecurity and fila.relforcerowsecurity
        assert (await db.execute(text(f"SELECT count(*) FROM {tabla}"))).scalar() == 0  # sin contexto: nada
