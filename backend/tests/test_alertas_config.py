"""Configuración central de alertas (§6.9.6): conciliación de claves con alias, rango del Superadmin, default sin
configuración propia, alertas de Fase 2 etiquetadas e inactivas, panel del usuario y supresión temporal."""
from datetime import UTC, datetime, timedelta

from tests.folios_utiles import AE, AP, AUN, DES, MC, OP, SA, TEC
from tests.sla_utiles import panel_alertas

FASE_2 = {"TECNICO_TIEMPO_MUERTO", "TECNICO_DESVIO_RUTA", "TECNICO_SIN_SENAL", "MEDIDOR_PROXIMO_PM", "CERTIFICACION_VENCIDA"}


async def _catalogo(cliente, auth, email=AP) -> dict:
    r = await cliente.get("/api/alertas/catalogo", headers=await auth(email))
    assert r.status_code == 200, r.text
    return {c["clave"]: c for c in r.json()}


async def _efectivas(cliente, auth, email=AE) -> dict:
    r = await cliente.get("/api/alertas/configuracion", headers=await auth(email))
    assert r.status_code == 200, r.text
    return {c["clave"]: c for c in r.json()}


async def test_catalogo_conciliado_con_las_claves_literales_del_documento(cliente, auth, datos):
    cat = await _catalogo(cliente, auth)
    # §6.9.6 nombra los tres umbrales de presupuesto; las claves que P09 había creado ya no están en el catálogo.
    assert {"PRESUPUESTO_ALERTA_1", "PRESUPUESTO_ALERTA_2", "PRESUPUESTO_ALERTA_3"} <= set(cat)
    assert "PRESUPUESTO_UMBRAL_ALCANZADO" not in cat and "PRESUPUESTO_EXCEDIDO" not in cat
    assert cat["PRESUPUESTO_ALERTA_1"]["umbral_default"] == "70.00"
    assert cat["PRESUPUESTO_ALERTA_2"]["umbral_default"] == "90.00"
    assert cat["PRESUPUESTO_ALERTA_3"]["umbral_default"] == "100.00"
    # Las de P10 y las de §6.10.1.
    assert {"SLA_INCUMPLIDO", "EXCLUSION_SLA_PENDIENTE", "CONTRATO_POR_VENCER", "IGUALA_LIMITE_ALCANZADO"} <= set(cat)
    # El evaluador acepta la clave vieja como alias.
    from services import alertas_service

    assert alertas_service.canonica("PRESUPUESTO_UMBRAL_ALCANZADO") == "PRESUPUESTO_ALERTA_1"
    assert alertas_service.canonica("PRESUPUESTO_EXCEDIDO") == "PRESUPUESTO_ALERTA_3"
    assert alertas_service.canonica("SEGUIMIENTO_INTERNO_SIN_ACTUALIZAR") == "SEGUIMIENTO_SIN_UPDATE"


async def test_alertas_de_fase_2_visibles_inactivas_y_no_activables(cliente, auth, datos):
    cat = await _catalogo(cliente, auth)
    for clave in FASE_2:
        assert cat[clave]["fase"] == 2 and cat[clave]["activa_por_defecto"] is False
    # Las de Fase 1 siguen en fase 1.
    assert cat["SLA_INCUMPLIDO"]["fase"] == 1
    r = await cliente.put("/api/alertas/configuracion/TECNICO_TIEMPO_MUERTO", headers=await auth(AP),
                          json={"umbral_valor": "20", "parametros": {}, "canales": ["app"],
                                "destinatarios_roles": ["despachador"], "activa": True})
    assert r.status_code == 422 and r.json()["codigo"] == "ALERTA_FASE_2"
    # Configurarla inactiva sí se permite (queda etiquetada en la pantalla).
    r = await cliente.put("/api/alertas/configuracion/TECNICO_TIEMPO_MUERTO", headers=await auth(AP),
                          json={"umbral_valor": "20", "parametros": {}, "canales": ["app"],
                                "destinatarios_roles": ["despachador"], "activa": False})
    assert r.status_code == 200 and r.json()["activa"] is False


async def test_umbral_dentro_del_rango_y_default_sin_configuracion(cliente, auth, datos):
    cat = await _catalogo(cliente, auth)
    minimo, maximo = cat["SLA_RESPUESTA_EN_RIESGO"]["umbral_min"], cat["SLA_RESPUESTA_EN_RIESGO"]["umbral_max"]
    # Sin configuración propia manda el default del catálogo.
    await cliente.delete("/api/alertas/configuracion/SLA_RESPUESTA_EN_RIESGO", headers=await auth(AE))
    ef = await _efectivas(cliente, auth)
    assert ef["SLA_RESPUESTA_EN_RIESGO"]["umbral_valor"] == cat["SLA_RESPUESTA_EN_RIESGO"]["umbral_default"]
    assert ef["SLA_RESPUESTA_EN_RIESGO"]["personalizada"] is False
    # Fuera de rango: 422 con el mínimo y el máximo en los detalles.
    r = await cliente.put("/api/alertas/configuracion/SLA_RESPUESTA_EN_RIESGO", headers=await auth(AE),
                          json={"umbral_valor": str(float(maximo) + 5), "parametros": {}, "canales": ["app"],
                                "destinatarios_roles": ["admin_empresa"], "activa": True})
    assert r.status_code == 422 and r.json()["codigo"] == "UMBRAL_FUERA_DE_RANGO"
    assert r.json()["detalles"][0]["minimo"] == minimo and r.json()["detalles"][0]["maximo"] == maximo
    # Dentro de rango: queda personalizado.
    r = await cliente.put("/api/alertas/configuracion/SLA_RESPUESTA_EN_RIESGO", headers=await auth(AE),
                          json={"umbral_valor": "60", "parametros": {}, "canales": ["app", "email"],
                                "destinatarios_roles": ["admin_empresa", "admin_un"], "activa": True})
    assert r.status_code == 200 and float(r.json()["umbral_valor"]) == 60.0 and r.json()["personalizada"] is True
    assert r.json()["destinatarios_roles"] == ["admin_empresa", "admin_un"]


async def test_solo_el_superadmin_cambia_el_default_y_el_rango(cliente, auth, datos):
    r = await cliente.patch("/api/alertas/catalogo/SLA_INCUMPLIDO", headers=await auth(AP), json={"umbral_default": "1"})
    assert r.status_code == 403
    r = await cliente.patch("/api/alertas/catalogo/CONTRATO_POR_VENCER", headers=await auth(SA),
                            json={"umbral_default": "45", "umbral_min": "5", "umbral_max": "200"})
    assert r.status_code == 200 and r.json()["umbral_default"] == "45.00"
    # El default fuera del rango se rechaza.
    r = await cliente.patch("/api/alertas/catalogo/CONTRATO_POR_VENCER", headers=await auth(SA),
                            json={"umbral_default": "500"})
    assert r.status_code == 422
    await cliente.patch("/api/alertas/catalogo/CONTRATO_POR_VENCER", headers=await auth(SA),
                        json={"umbral_default": "30", "umbral_min": "1", "umbral_max": "180"})


async def test_panel_del_usuario_con_vista_y_atencion(cliente, auth, datos):
    from services import alertas_service
    from core.db import nueva_sesion
    from core.rls import CONTEXTO_SISTEMA

    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        await alertas_service.disparar(db, "CONTRATO_POR_VENCER", tenant_id=datos["tenant"], prestador_id=datos["prestador"],
                                       entidad_tipo="contratos", entidad_id=None, datos={"prueba": "panel"})
        await db.commit()
    mias = await panel_alertas(cliente, auth, AP)
    propia = next((a for a in mias if a["clave_alerta"] == "CONTRATO_POR_VENCER"), None)
    assert propia is not None and propia["descripcion"] and propia["atendida_at"] is None
    r = await cliente.post(f"/api/alertas/historial/{propia['id']}/vista", headers=await auth(AP))
    assert r.status_code == 200 and r.json()["estado"] == "vista"
    r = await cliente.post(f"/api/alertas/historial/{propia['id']}/atender", headers=await auth(AP),
                           json={"nota": "Se renovó el contrato con el cliente"})
    assert r.status_code == 200 and r.json()["atendida_at"] is not None
    assert r.json()["nota_atencion"] == "Se renovó el contrato con el cliente" and r.json()["estado"] == "resuelta"
    # Ya atendida no se atiende de nuevo y sale del feed de pendientes.
    r = await cliente.post(f"/api/alertas/historial/{propia['id']}/atender", headers=await auth(AP), json={"nota": "otra"})
    assert r.status_code == 409
    pendientes = await panel_alertas(cliente, auth, AP, pendientes=True)
    assert all(a["id"] != propia["id"] for a in pendientes)
    assert any(a["id"] == propia["id"] for a in await panel_alertas(cliente, auth, AP, pendientes=False))


async def test_el_tecnico_no_ve_las_alertas_de_otros_roles(cliente, auth, datos):
    from services import alertas_service
    from core.db import nueva_sesion
    from core.rls import CONTEXTO_SISTEMA

    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        await alertas_service.disparar(db, "SLA_INCUMPLIDO", tenant_id=datos["tenant"], prestador_id=datos["prestador"],
                                       entidad_tipo="folio", entidad_id=None, datos={"prueba": "roles"})
        await db.commit()
    assert all(a["clave_alerta"] != "SLA_INCUMPLIDO" for a in await panel_alertas(cliente, auth, TEC))
    assert any(a["clave_alerta"] == "SLA_INCUMPLIDO" for a in await panel_alertas(cliente, auth, AP))


async def test_supresion_temporal_silencia_la_alerta(cliente, auth, datos):
    from services import alertas_service
    from core.db import nueva_sesion
    from core.rls import CONTEXTO_SISTEMA

    hasta = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    r = await cliente.post("/api/alertas/supresiones", headers=await auth(AE),
                           json={"clave_alerta": "PRESUPUESTO_ALERTA_2", "razon": "Cierre de ejercicio: el gasto se revisa en enero", "hasta": hasta})
    assert r.status_code == 201, r.text
    supresion = r.json()
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        h = await alertas_service.disparar(db, "PRESUPUESTO_ALERTA_2", tenant_id=datos["tenant"], prestador_id=None,
                                           entidad_tipo="folio", entidad_id=None, datos={})
        await db.commit()
    assert h is None, "una alerta suprimida no se registra"
    r = await cliente.post(f"/api/alertas/supresiones/{supresion['id']}/desactivar", headers=await auth(AE))
    assert r.status_code == 200 and r.json()["activa"] is False
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        h2 = await alertas_service.disparar(db, "PRESUPUESTO_ALERTA_2", tenant_id=datos["tenant"], prestador_id=None,
                                            entidad_tipo="folio", entidad_id=None, datos={})
        await db.commit()
    assert h2 is not None
    # El técnico no suprime.
    r = await cliente.post("/api/alertas/supresiones", headers=await auth(TEC),
                           json={"clave_alerta": "STOCK_MINIMO", "razon": "porque sí", "hasta": hasta})
    assert r.status_code == 403
