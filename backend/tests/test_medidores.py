"""Medidores de activos (§6.9.2): catálogo de tipos (global y propio), alta de medidores por equipo, edición,
reinicio y reemplazo, aislamiento entre clientes y prestadores, y RLS forzada en las tablas nuevas. F2-04."""
from decimal import Decimal

import pytest
from sqlalchemy import text

from tests.folios_utiles import AE, AP, AUN, DES, OP, OTRO_AE, OTRO_AP, SA, TEC, nuevo_equipo
from tests.medidores_utiles import alta_medidor, equipo_con_medidor, estado_medidor, lectura, nuevo_tipo_medidor, tipo_global

TABLAS = ("tipos_medidor", "equipo_medidores", "medidor_lecturas", "medidor_estimaciones", "medidor_cambios",
          "llaves_api_tenant")


async def test_catalogo_global_y_propio(cliente, auth, datos):
    """Los seis tipos de §6.9.2 están sembrados como catálogo global; cada prestador puede tener los suyos."""
    globales = (await cliente.get("/api/medidores/tipos", headers=await auth(AP))).json()
    por_nombre = {t["nombre"]: t for t in globales}
    assert {"Horas de operación", "Ciclos", "Kilómetros", "Energía consumida", "Unidades producidas",
            "Litros tratados"} <= set(por_nombre)
    assert {por_nombre[n]["categoria"] for n in ("Horas de operación", "Ciclos", "Kilómetros")} == {"horas", "ciclos", "distancia"}
    assert por_nombre["Horas de operación"]["prestador_id"] is None and por_nombre["Horas de operación"]["tenant_id"] is None

    propio = await nuevo_tipo_medidor(cliente, auth, nombre="Horas del compresor demo", unidad="h")
    assert propio["prestador_id"] == str(datos["prestador"]) and propio["tenant_id"] is None
    # El Admin empresa crea los suyos, atados a su cliente.
    del_cliente = await nuevo_tipo_medidor(cliente, auth, email=AE, nombre="Litros del cliente demo", unidad="L",
                                           categoria="personalizado")
    assert del_cliente["tenant_id"] == str(datos["tenant"]) and del_cliente["prestador_id"] is None
    # El catálogo global solo lo mantiene el Superadmin.
    r = await cliente.post("/api/medidores/tipos", headers=await auth(AP),
                           json={"nombre": "Global ajeno", "unidad": "x", "global": True})
    assert r.status_code == 403
    r = await cliente.post("/api/medidores/tipos", headers=await auth(SA),
                           json={"nombre": "Pulsos de prueba", "unidad": "p", "global": True, "categoria": "personalizado"})
    assert r.status_code == 201 and r.json()["prestador_id"] is None and r.json()["tenant_id"] is None
    # El operador no mantiene catálogos.
    assert (await cliente.post("/api/medidores/tipos", headers=await auth(OP),
                               json={"nombre": "Medidor del operador", "unidad": "u"})).status_code == 403


async def test_editar_tipo_y_no_tocar_el_global(cliente, auth, datos):
    propio = await nuevo_tipo_medidor(cliente, auth)
    r = await cliente.put(f"/api/medidores/tipos/{propio['id']}", headers=await auth(AP),
                          json={"requiere_foto": True, "factor_salto_maximo": "5", "descripcion": "Con foto del marcador"})
    assert r.status_code == 200 and r.json()["requiere_foto"] is True and Decimal(r.json()["factor_salto_maximo"]) == 5
    global_ = await tipo_global(cliente, auth)
    r = await cliente.put(f"/api/medidores/tipos/{global_['id']}", headers=await auth(AP), json={"activo": False})
    assert r.status_code == 403
    assert (await cliente.put(f"/api/medidores/tipos/{global_['id']}", headers=await auth(SA),
                              json={"descripcion": global_["descripcion"]})).status_code == 200
    # El prestador ajeno ni lo ve.
    assert (await cliente.put(f"/api/medidores/tipos/{propio['id']}", headers=await auth(OTRO_AP),
                              json={"activo": False})).status_code == 404


async def test_alta_de_medidor_por_equipo(cliente, auth, datos):
    equipo, medidor, tipo = await equipo_con_medidor(cliente, auth, datos, valor_inicial="1200.5",
                                                     numero_serie_medidor="HM-1", valor_maximo="99999")
    assert Decimal(medidor["valor_actual"]) == Decimal("1200.5") and Decimal(medidor["valor_acumulado"]) == Decimal("1200.5")
    assert medidor["metodo_actualizacion"] == "operador" and medidor["activo"] is True
    # Un segundo medidor del mismo tipo en el mismo equipo no tiene sentido.
    r = await alta_medidor(cliente, auth, equipo, tipo, esperado=409)
    assert r["codigo"] == "MEDIDOR_DUPLICADO"
    # Otro tipo sí: un equipo puede tener varios medidores (§6.9.2).
    ciclos = await nuevo_tipo_medidor(cliente, auth, nombre=f"Ciclos {equipo['codigo']}", unidad="ciclos", categoria="ciclos")
    segundo = await alta_medidor(cliente, auth, equipo, ciclos)
    assert segundo["tipo_medidor_id"] == ciclos["id"]
    resumen = await estado_medidor(cliente, auth, equipo["id"])
    assert len(resumen) == 2 and {x["unidad"] for x in resumen} == {"h", "ciclos"}
    # Un tipo que no admite estimación no acepta el método `estimado`.
    sin_est = await nuevo_tipo_medidor(cliente, auth, nombre=f"Sin estimar {equipo['codigo']}", permite_estimacion=False)
    otro = await nuevo_equipo(cliente, auth, datos)
    r = await alta_medidor(cliente, auth, otro, sin_est, metodo_actualizacion="estimado", esperado=422)
    assert r["codigo"] == "ESTIMACION_NO_PERMITIDA"


async def test_editar_medidor_no_cambia_el_valor(cliente, auth, datos):
    _equipo, medidor, _tipo = await equipo_con_medidor(cliente, auth, datos, valor_inicial="100")
    r = await cliente.put(f"/api/medidores/{medidor['id']}", headers=await auth(DES),
                          json={"numero_serie_medidor": "HM-9", "valor_maximo": "5000", "metodo_actualizacion": "tecnico"})
    assert r.status_code == 200, r.text
    assert r.json()["numero_serie_medidor"] == "HM-9" and Decimal(r.json()["valor_actual"]) == 100
    # El operador no edita la configuración del medidor.
    assert (await cliente.put(f"/api/medidores/{medidor['id']}", headers=await auth(OP),
                              json={"numero_serie_medidor": "X"})).status_code == 403


async def test_reinicio_del_marcador_no_hace_retroceder_el_acumulado(cliente, auth, datos):
    """§6.9.2: un marcador que da la vuelta (99,999 → 0) no puede borrar las horas que el equipo ya trabajó."""
    _equipo, medidor, _tipo = await equipo_con_medidor(cliente, auth, datos, valor_maximo="1000")
    await lectura(cliente, auth, medidor, "950", dias_atras=2)
    r = await cliente.post(f"/api/medidores/{medidor['id']}/cambios", headers=await auth(AP),
                           json={"tipo": "reinicio", "valor_nuevo": "0", "motivo": "El marcador llegó a 1000 y volvió a cero"})
    assert r.status_code == 201, r.text
    assert Decimal(r.json()["valor_anterior"]) == 950 and Decimal(r.json()["acumulado_al_cambio"]) == 950
    res = await lectura(cliente, auth, medidor, "30", dias_atras=1)
    assert Decimal(res["lectura"]["valor"]) == 30 and Decimal(res["lectura"]["valor_acumulado"]) == 980
    assert res["anomalia"] == "", res
    historial = (await cliente.get(f"/api/medidores/{medidor['id']}/cambios", headers=await auth(AP))).json()
    assert len(historial) == 1 and historial[0]["tipo"] == "reinicio"
    # Un cambio sin motivo no se registra: el motivo es lo que explica el salto del historial.
    r = await cliente.post(f"/api/medidores/{medidor['id']}/cambios", headers=await auth(AP),
                           json={"tipo": "reinicio", "valor_nuevo": "0", "motivo": " "})
    assert r.status_code == 422


async def test_reemplazo_de_medidor_conserva_el_acumulado(cliente, auth, datos):
    _equipo, medidor, _tipo = await equipo_con_medidor(cliente, auth, datos, numero_serie_medidor="HM-VIEJO")
    await lectura(cliente, auth, medidor, "4000", dias_atras=3)
    r = await cliente.post(f"/api/medidores/{medidor['id']}/cambios", headers=await auth(AP),
                           json={"tipo": "reemplazo_medidor", "valor_nuevo": "0", "motivo": "Horómetro dañado",
                                 "numero_serie_nuevo": "HM-NUEVO"})
    assert r.status_code == 201 and r.json()["numero_serie_anterior"] == "HM-VIEJO"
    res = await lectura(cliente, auth, medidor, "120", dias_atras=1)
    assert Decimal(res["lectura"]["valor_acumulado"]) == 4120
    actual = (await estado_medidor(cliente, auth, _equipo["id"]))[0]
    assert actual["numero_serie_medidor"] == "HM-NUEVO" and Decimal(actual["valor_actual"]) == 120


async def test_aislamiento_entre_clientes_y_prestadores(cliente, auth, datos):
    equipo, medidor, _tipo = await equipo_con_medidor(cliente, auth, datos)
    for email in (OTRO_AE, OTRO_AP):
        assert (await cliente.get(f"/api/medidores/equipos/{equipo['id']}", headers=await auth(email))).status_code == 404
        assert (await cliente.put(f"/api/medidores/{medidor['id']}", headers=await auth(email),
                                  json={"numero_serie_medidor": "X"})).status_code == 404
        r = await cliente.post("/api/medidores/lecturas", headers=await auth(email),
                               json={"equipo_medidor_id": medidor["id"], "valor": "10"})
        assert r.status_code == 404, r.text
    # El cliente y el prestador que sí lo atienden lo ven.
    for email in (AE, AUN, AP, DES):
        assert (await cliente.get(f"/api/medidores/equipos/{equipo['id']}", headers=await auth(email))).status_code == 200


async def test_rls_forzada_y_lecturas_sin_borrado(cliente, auth, datos):
    """La RLS forzada general la verifica `test_rls.py`; aquí se comprueba que `acma_api` no puede borrar lecturas."""
    from core.db import nueva_sesion
    from core.rls import CONTEXTO_SISTEMA

    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        for tabla in TABLAS:
            fila = (await db.execute(text(
                "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = :t"), {"t": tabla})).one()
            assert fila.relrowsecurity and fila.relforcerowsecurity, tabla
        privilegios = {p for (p,) in (await db.execute(text(
            "SELECT privilege_type FROM information_schema.role_table_grants "
            "WHERE table_name = 'medidor_lecturas' AND grantee = 'acma_api'"))).all()}
        assert "SELECT" in privilegios and "INSERT" in privilegios and "UPDATE" in privilegios
        assert "DELETE" not in privilegios, privilegios


async def test_tecnico_consulta_pero_no_administra(cliente, auth, datos):
    equipo, medidor, tipo = await equipo_con_medidor(cliente, auth, datos)
    # El técnico registra lecturas (es lo que hace en campo) pero no da de alta medidores.
    r = await lectura(cliente, auth, medidor, "15", email=TEC, dias_atras=1)
    assert r["lectura"]["metodo"] == "operador"   # el método del medidor manda si la lectura no lo dice
    r = await alta_medidor(cliente, auth, equipo, tipo, email=TEC, esperado=403)
    assert r["codigo"] == "PROHIBIDO"


@pytest.mark.parametrize("email", [AP, DES, AE, AUN])
async def test_equipos_del_operador_solo_medidores_de_operador(cliente, auth, datos, email):
    equipo, medidor, tipo = await equipo_con_medidor(cliente, auth, datos, metodo_actualizacion="operador")
    r = await cliente.get("/api/medidores/operador/equipos", headers=await auth(email))
    assert r.status_code == 200, r.text
    assert any(x["equipo_medidor_id"] == medidor["id"] for x in r.json())
    # Uno de importación no aparece en la pantalla del operador.
    otro = await nuevo_equipo(cliente, auth, datos)
    scada = await alta_medidor(cliente, auth, otro, tipo, metodo_actualizacion="importacion")
    r = await cliente.get("/api/medidores/operador/equipos", headers=await auth(email))
    assert all(x["equipo_medidor_id"] != scada["id"] for x in r.json())
