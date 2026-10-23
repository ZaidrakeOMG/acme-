"""Matriz de severidad tipo de falla × tipo de equipo (§6.8.6) y alerta MATRIZ_SEVERIDAD_INCOMPLETA."""
from sqlalchemy import select

from core.db import nueva_sesion
from core.rls import CONTEXTO_SISTEMA
from models import AlertaHistorial
from workers import tareas

AE, AP, OP, SA, OTRO_AE = "admin.empresa@acma.dev", "admin.prestador@acma.dev", "operador@acma.dev", "superadmin@acma.dev", "admin.otro@acma.dev"


async def _matriz(cliente, auth):
    r = await cliente.get("/api/catalogos/matriz-severidad", headers=await auth(AE))
    assert r.status_code == 200, r.text
    return r.json()



async def test_matriz_completa_del_seed(cliente, auth, datos):
    m = await _matriz(cliente, auth)
    assert m["tenant_id"] == str(datos["tenant"])
    assert len(m["tipos_falla"]) >= 8 and len(m["tipos_equipo"]) >= 6 and len(m["niveles"]) == 5
    assert len(m["celdas"]) >= 16 and m["faltantes_en_uso"] == 0
    assert all(t["en_uso"] for t in m["tipos_equipo"] if t["nombre"] in ("Refrigerador vertical", "Minisplit"))
    # Otro tenant: sin prestador con contrato → matriz vacía; el prestador necesita indicar tenant.
    vacia = (await cliente.get("/api/catalogos/matriz-severidad", headers=await auth(OTRO_AE))).json()
    assert vacia["celdas"] == [] and vacia["tipos_falla"] == []
    assert (await cliente.get("/api/catalogos/matriz-severidad", headers=await auth(AP))).status_code == 422
    assert (await cliente.get("/api/catalogos/matriz-severidad", headers=await auth(AP), params={"tenant_id": str(datos["tenant"])})).status_code == 200
    assert (await cliente.get("/api/catalogos/matriz-severidad", headers=await auth(OP))).status_code == 403


async def test_resolver_con_y_sin_configuracion(cliente, auth, datos):
    m = await _matriz(cliente, auth)
    refri = next(t for t in m["tipos_equipo"] if t["nombre"] == "Refrigerador vertical")
    no_enciende = next(f for f in m["tipos_falla"] if f["descripcion"] == "No enciende" and f["familia_equipo_id"] == refri["familia_id"])
    params = {"tipo_falla_id": no_enciende["id"], "tipo_equipo_id": refri["id"]}
    r = await cliente.get("/api/catalogos/matriz-severidad/resolver", headers=await auth(OP), params=params)
    assert r.status_code == 200, r.text
    assert r.json()["nivel"]["clave"] == "critica" and r.json()["tiempo_respuesta_horas"] == 2 and r.json()["requiere_revision_manual"] is False
    # Misma falla, otro tipo de equipo de otra familia: no configurada.
    led = next(t for t in m["tipos_equipo"] if t["nombre"] == "Lámpara LED de techo")
    sin = await cliente.get("/api/catalogos/matriz-severidad/resolver", headers=await auth(OP),
                            params={"tipo_falla_id": no_enciende["id"], "tipo_equipo_id": led["id"]})
    assert sin.status_code == 404 and sin.json()["codigo"] == "SEVERIDAD_NO_CONFIGURADA"
    # Otro tenant no tiene configuración aunque los ids existan.
    assert (await cliente.get("/api/catalogos/matriz-severidad/resolver", headers=await auth(OTRO_AE), params=params)).status_code == 404
    # El prestador resuelve indicando tenant_id.
    assert (await cliente.get("/api/catalogos/matriz-severidad/resolver", headers=await auth(AP),
                              params={**params, "tenant_id": str(datos["tenant"])})).status_code == 200


async def test_editar_celda_y_carga_masiva(cliente, auth, datos):
    h = await auth(AE)
    m = await _matriz(cliente, auth)
    niveles = {n["clave"]: n["id"] for n in m["niveles"]}
    refri = next(t for t in m["tipos_equipo"] if t["nombre"] == "Refrigerador vertical")
    ruido = next(f for f in m["tipos_falla"] if f["descripcion"] == "Ruido inusual")
    r = await cliente.put("/api/catalogos/matriz-severidad/celda", headers=h,
                          json={"tipo_falla_id": ruido["id"], "tipo_equipo_id": refri["id"], "nivel_severidad_id": niveles["alta"]})
    assert r.status_code == 200, r.text
    celda = next(c for c in r.json()["celdas"] if c["tipo_falla_id"] == ruido["id"] and c["tipo_equipo_id"] == refri["id"])
    assert celda["nivel_severidad_id"] == niveles["alta"]
    # Familias distintas: 422. Nivel de otro prestador: 422. Prestador no edita: 403.
    led = next(t for t in m["tipos_equipo"] if t["nombre"] == "Lámpara LED de techo")
    assert (await cliente.put("/api/catalogos/matriz-severidad/celda", headers=h,
                              json={"tipo_falla_id": ruido["id"], "tipo_equipo_id": led["id"], "nivel_severidad_id": niveles["alta"]})).json()["codigo"] == "FAMILIA_DISTINTA"
    assert (await cliente.put("/api/catalogos/matriz-severidad/celda", headers=await auth(AP),
                              json={"tipo_falla_id": ruido["id"], "tipo_equipo_id": refri["id"], "nivel_severidad_id": niveles["alta"]})).status_code == 403
    # Quitar la celda la deja sin configurar y sube faltantes_en_uso.
    quitar = await cliente.put("/api/catalogos/matriz-severidad/celda", headers=h,
                               json={"tipo_falla_id": ruido["id"], "tipo_equipo_id": refri["id"], "nivel_severidad_id": None})
    assert quitar.json()["faltantes_en_uso"] == 1
    assert (await cliente.get("/api/catalogos/matriz-severidad/resolver", headers=h,
                              params={"tipo_falla_id": ruido["id"], "tipo_equipo_id": refri["id"]})).status_code == 404
    masiva = await cliente.put("/api/catalogos/matriz-severidad", headers=h, json={"celdas": [
        {"tipo_falla_id": ruido["id"], "tipo_equipo_id": refri["id"], "nivel_severidad_id": niveles["baja"]}]})
    assert masiva.json()["faltantes_en_uso"] == 0
    # Auditoría registró antes/después.
    ev = (await cliente.get("/api/auditoria/eventos", headers=await auth(SA), params={"evento_tipo": "catalogos.matriz_celda"})).json()
    assert ev and ev[0]["valor_nuevo_json"]


async def test_alerta_matriz_incompleta(cliente, auth, datos):
    h = await auth(AP)
    familias = {f["nombre"]: f for f in (await cliente.get("/api/catalogos/familias-equipo", headers=h)).json()}
    nueva = await cliente.post("/api/catalogos/tipos-falla", headers=h, json={"descripcion": "Olor a quemado", "familia_equipo_id": familias["Climatización"]["id"]})
    assert nueva.status_code == 201
    try:
        m = await _matriz(cliente, auth)
        assert m["faltantes_en_uso"] >= 1  # Minisplit está en uso y no tiene severidad para la falla nueva
        resumen = await tareas.evaluar_alertas_async()
        assert resumen["errores"] == 0 and resumen["disparadas"] >= 1
        async with nueva_sesion(CONTEXTO_SISTEMA) as db:
            h_alerta = (await db.execute(select(AlertaHistorial).where(
                AlertaHistorial.clave_alerta == "MATRIZ_SEVERIDAD_INCOMPLETA", AlertaHistorial.tenant_id == datos["tenant"]))).scalars().all()
        assert h_alerta and any("Olor a quemado × Minisplit" in x.datos_contexto_json["ejemplos"] for x in h_alerta)
        # Mientras la alerta siga sin atender no se vuelve a registrar (la tarea corre cada minuto).
        assert (await tareas.evaluar_alertas_async())["disparadas"] == 0
    finally:
        await cliente.patch(f"/api/catalogos/tipos-falla/{nueva.json()['id']}", headers=h, json={"activa": False})
    assert (await _matriz(cliente, auth))["faltantes_en_uso"] == 0
