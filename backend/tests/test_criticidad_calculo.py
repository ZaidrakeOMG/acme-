"""Fórmula de criticidad de §6.9.3: impacto ponderado, índice, nivel y sus fronteras; probabilidad desde el
historial y estimada por tipo de equipo; configuración de pesos; evaluación masiva; aislamiento y RLS forzada
en las tablas nuevas. F2-05."""
from decimal import Decimal

import pytest
from sqlalchemy import text

from models.criticidad import PESOS_DEFAULT, RANGOS_NIVEL_DEFAULT
from services.criticidad_service import impacto_ponderado, indice_de, nivel_de
from tests.criticidad_utiles import (
    configuracion, detalle, equipo_con_historia, evaluar, poner_configuracion, restaurar_configuracion,
)
from tests.folios_utiles import AE, AP, AUN, DES, OP, OTRO_AE, SA, TEC, nuevo_equipo, tipo_equipo

TABLAS = ("criticidad_configuracion", "activo_criticidad", "criticidad_evaluaciones", "activo_modos_falla",
          "activo_riesgo_mitigacion")


def test_impacto_ponderado_con_los_pesos_literales():
    """Σ (dimensión × peso) / 100, con los pesos de §6.9.3: operacional 30, seguridad 35, económico 25, imagen 10."""
    assert impacto_ponderado({"operacional": 5, "seguridad": 5, "economico": 5, "imagen": 5}, PESOS_DEFAULT) == Decimal("5.00")
    assert impacto_ponderado({"operacional": 1, "seguridad": 1, "economico": 1, "imagen": 1}, PESOS_DEFAULT) == Decimal("1.00")
    # 5×30 + 4×35 + 4×25 + 4×10 = 430 → 4.30
    assert impacto_ponderado({"operacional": 5, "seguridad": 4, "economico": 4, "imagen": 4}, PESOS_DEFAULT) == Decimal("4.30")
    # El peso manda: el mismo 5 en seguridad pesa más que en imagen.
    alto_seguridad = impacto_ponderado({"operacional": 1, "seguridad": 5, "economico": 1, "imagen": 1}, PESOS_DEFAULT)
    alto_imagen = impacto_ponderado({"operacional": 1, "seguridad": 1, "economico": 1, "imagen": 5}, PESOS_DEFAULT)
    assert alto_seguridad == Decimal("2.40") and alto_imagen == Decimal("1.40")


def test_indice_es_probabilidad_por_impacto_normalizado_a_100():
    """(probabilidad × impacto) / 25 × 100: el máximo 5 × 5.00 es 100 y el mínimo 1 × 1.00 es 4."""
    assert indice_de(Decimal(5), Decimal("5.00")) == Decimal("100.00")
    assert indice_de(Decimal(1), Decimal("1.00")) == Decimal("4.00")
    assert indice_de(Decimal(4), Decimal("4.30")) == Decimal("68.80")
    assert indice_de(Decimal(3), Decimal("2.30")) == Decimal("27.60")


@pytest.mark.parametrize("valor, esperado", [
    ("100.00", "A"), ("80.00", "A"), ("79.99", "B"),      # frontera 79/80
    ("50.00", "B"), ("49.99", "C"),                       # frontera 49/50
    ("20.00", "C"), ("19.99", "D"),                       # frontera 19/20
    ("4.00", "D"), ("0.00", "D"),
])
def test_nivel_en_cada_banda_y_en_sus_fronteras(valor, esperado):
    """A 80–100, B 50–79, C 20–49, D 0–19 (§6.9.3). Cada banda es cerrada por abajo."""
    assert nivel_de(Decimal(valor), RANGOS_NIVEL_DEFAULT) == esperado


async def test_cada_nivel_sale_del_calculo_de_punta_a_punta(cliente, auth, datos):
    """Un equipo por nivel, con la probabilidad saliendo de su propio historial de fallas."""
    casos = [
        # (fallas 12m, probabilidad, dimensiones, impacto, índice, nivel)
        (12, 5, (5, 4, 4, 4), "4.30", "86.00", "A"),
        (7, 4, (4, 4, 3, 3), "3.65", "58.40", "B"),
        (3, 3, (3, 2, 2, 2), "2.30", "27.60", "C"),
        (0, 1, (2, 2, 1, 2), "1.75", "7.00", "D"),
    ]
    for fallas, prob, dims, impacto, idx, nivel in casos:
        equipo = await equipo_con_historia(cliente, auth, datos, fallas=fallas)
        fila = await evaluar(cliente, auth, equipo["id"], *dims)
        assert Decimal(fila["probabilidad"]) == prob, (fallas, fila)
        assert fila["probabilidad_estimada"] is False and fila["probabilidad_origen"] == "historial_equipo"
        assert Decimal(fila["impacto_ponderado"]) == Decimal(impacto)
        assert Decimal(fila["indice_criticidad"]) == Decimal(idx)
        assert fila["nivel"] == nivel


async def test_escala_de_probabilidad_por_fallas(cliente, auth, datos):
    """Las cinco bandas de la escala literal: 0 / 1-2 / 3-5 / 6-11 / 12 o más fallas en 12 meses."""
    for fallas, esperada in ((0, 1), (1, 2), (2, 2), (3, 3), (5, 3), (6, 4), (11, 4), (12, 5)):
        equipo = await equipo_con_historia(cliente, auth, datos, fallas=fallas)
        fila = await evaluar(cliente, auth, equipo["id"])
        assert Decimal(fila["probabilidad"]) == esperada, (fallas, fila["probabilidad"])
        assert fila["dimensiones_json"]["probabilidad"]["fallas_12m"] == fallas


async def test_probabilidad_estimada_desde_el_tipo_de_equipo(cliente, auth, datos):
    """Sin historia propia suficiente la probabilidad se toma del promedio de los equipos del mismo tipo del
    cliente, y la evaluación queda marcada como estimada: el dato es prestado."""
    tipo = await tipo_equipo(cliente, auth, "Equipos industriales", 0)
    # Dos equipos del mismo tipo con historia propia: probabilidad 3 y 5 → promedio 4.
    for fallas in (4, 13):
        viejo = await equipo_con_historia(cliente, auth, datos, fallas=fallas, familia="Equipos industriales",
                                          tipo_equipo_id=tipo["id"])
        await evaluar(cliente, auth, viejo["id"])
    nuevo = await nuevo_equipo(cliente, auth, datos, familia="Equipos industriales",
                               tipo_equipo_id=tipo["id"])   # sin un solo folio: ACMA no lo ha observado
    fila = await evaluar(cliente, auth, nuevo["id"], 4, 4, 3, 3)
    assert fila["probabilidad_estimada"] is True
    assert fila["probabilidad_origen"] == "tipo_equipo_cliente"
    assert "no tiene historia suficiente" in fila["dimensiones_json"]["probabilidad"]["nota"]
    # El valor es el promedio de los equipos del mismo tipo que sí tienen historia propia.
    registro = (await cliente.get("/api/criticidad", headers=await auth(AE))).json()
    mismos = [f for f in registro if f["tipo_equipo"] == tipo["nombre"] and not f["probabilidad_estimada"]]
    promedio = sum(Decimal(f["probabilidad"]) for f in mismos) / len(mismos)
    assert abs(Decimal(fila["probabilidad"]) - promedio) <= Decimal("0.01"), (fila["probabilidad"], promedio)
    # El índice se calcula igual con la probabilidad prestada: probabilidad × 3.65 / 25 × 100.
    assert Decimal(fila["impacto_ponderado"]) == Decimal("3.65")
    assert Decimal(fila["indice_criticidad"]) == indice_de(Decimal(fila["probabilidad"]), Decimal("3.65"))


async def test_sin_referencia_la_probabilidad_queda_declarada(cliente, auth, datos):
    """Un tipo de equipo sin nadie evaluado: el origen lo dice, nunca un número inventado en silencio."""
    tipo = await tipo_equipo(cliente, auth, "Iluminación", 0)
    nuevo = await nuevo_equipo(cliente, auth, datos, familia="Iluminación", tipo_equipo_id=tipo["id"])
    fila = await evaluar(cliente, auth, nuevo["id"], 1, 1, 1, 1)
    assert fila["probabilidad_estimada"] is True
    assert fila["probabilidad_origen"] in ("sin_referencia", "tipo_equipo_cliente", "tipo_equipo_plataforma")


async def test_pesos_tienen_que_sumar_100(cliente, auth):
    """Si no suman 100 el índice deja de significar lo que dice: 422 y la configuración no se mueve."""
    try:
        r = await cliente.put("/api/criticidad/configuracion", headers=await auth(AE),
                              json={"pesos_json": {"operacional": 40, "seguridad": 35, "economico": 25, "imagen": 10}})
        assert r.status_code == 422 and r.json()["codigo"] == "PESOS_NO_SUMAN_100", r.text
        assert (await configuracion(cliente, auth))["pesos_json"] == PESOS_DEFAULT
        nuevos = {"operacional": 50, "seguridad": 20, "economico": 20, "imagen": 10}
        assert (await poner_configuracion(cliente, auth, {"pesos_json": nuevos}))["pesos_json"] == nuevos
    finally:
        await restaurar_configuracion(cliente, auth)


async def test_los_pesos_cambian_el_indice(cliente, auth, datos):
    equipo = await equipo_con_historia(cliente, auth, datos, fallas=3)
    try:
        con_defaults = await evaluar(cliente, auth, equipo["id"], 5, 1, 1, 1)
        assert Decimal(con_defaults["impacto_ponderado"]) == Decimal("2.20")   # 150+35+25+10
        await poner_configuracion(cliente, auth, {"pesos_json": {"operacional": 70, "seguridad": 10,
                                                                 "economico": 10, "imagen": 10}})
        con_otros = await evaluar(cliente, auth, equipo["id"], 5, 1, 1, 1)
        assert Decimal(con_otros["impacto_ponderado"]) == Decimal("3.80")      # 350+10+10+10
        assert Decimal(con_otros["indice_criticidad"]) > Decimal(con_defaults["indice_criticidad"])
    finally:
        await restaurar_configuracion(cliente, auth)


async def test_solo_el_admin_empresa_configura(cliente, auth, datos):
    """§6.9.3: los pesos son del cliente. El prestador los consulta, no los cambia."""
    # El prestador atiende a varios clientes, asi que pide el de uno en concreto.
    assert (await configuracion(cliente, auth, email=AP, tenant_id=str(datos["tenant"])))["pesos_json"] == PESOS_DEFAULT
    assert (await cliente.get("/api/criticidad/configuracion",
                              headers=await auth(AP))).status_code == 422   # TENANT_REQUERIDO
    for email in (AP, DES, AUN):
        r = await cliente.put("/api/criticidad/configuracion", headers=await auth(email),
                              params={"tenant_id": str(datos["tenant"])}, json={"meses_revision": 6})
        assert r.status_code == 403, (email, r.status_code, r.text)
    for email in (OP, TEC):   # el operador y el técnico no consultan criticidad
        assert (await cliente.get("/api/criticidad/configuracion", headers=await auth(email))).status_code == 403


async def test_quien_evalua_y_quien_solo_mira(cliente, auth, datos):
    equipo = await equipo_con_historia(cliente, auth, datos, fallas=2)
    await evaluar(cliente, auth, equipo["id"], email=AUN)        # el Admin UN evalúa sus unidades
    for email in (AP, DES, OP, TEC):
        await evaluar(cliente, auth, equipo["id"], email=email, esperado=403)
    # El prestador sí consulta: es quien mantiene el activo.
    assert (await detalle(cliente, auth, equipo["id"], email=DES))["nivel"] in ("A", "B", "C", "D")
    assert (await cliente.get(f"/api/criticidad/equipos/{equipo['id']}",
                              headers=await auth(OP))).status_code == 403


async def test_detalle_sin_evaluar_trae_la_guia_y_la_propuesta_economica(cliente, auth, datos):
    equipo = await equipo_con_historia(cliente, auth, datos, fallas=1)
    d = await detalle(cliente, auth, equipo["id"])
    assert d["evaluado"] is False and d["probabilidad"] is None
    assert set(d["guia"]) == {"operacional", "seguridad", "economico", "imagen"}
    assert d["guia"]["seguridad"]["peso_default"] == 35
    assert 1 <= d["economico_propuesto"]["nivel"] <= 5
    assert d["probabilidad_detalle"]["fallas_12m"] == 1
    # La probabilidad que saldria si se evaluara hoy, para que la pantalla pueda estimar el indice.
    assert Decimal(d["probabilidad_si_se_evalua"]) == 2 and d["probabilidad_origen"] == "historial_equipo"


async def test_detalle_explica_como_se_formo_el_indice(cliente, auth, datos):
    """Un auditor ISO 55000 pregunta «¿de dónde salió este 86?»: el desglose lo contesta."""
    equipo = await equipo_con_historia(cliente, auth, datos, fallas=12)
    await evaluar(cliente, auth, equipo["id"], 5, 4, 4, 4)
    d = await detalle(cliente, auth, equipo["id"])
    assert d["evaluado"] is True and d["nivel"] == "A"
    assert Decimal(d["indice_criticidad"]) == Decimal("86.00") and d["etiqueta"] == "Crítico"
    aportes = {x["clave"]: x for x in d["dimensiones"]}
    assert set(aportes) == {"operacional", "seguridad", "economico", "imagen"}
    assert aportes["seguridad"]["peso"] == 35 and Decimal(aportes["seguridad"]["aporte"]) == Decimal("1.40")
    assert aportes["operacional"]["texto"] == "Cierre total" and aportes["operacional"]["pregunta"]
    assert sum(Decimal(x["aporte"]) for x in d["dimensiones"]) == Decimal("4.30")
    assert d["probabilidad_detalle"]["fallas_12m"] == 12
    assert d["implicaciones"].startswith("PM obligatorio")


async def test_evaluacion_masiva_por_tipo_de_equipo(cliente, auth, datos):
    """200 equipos no se evalúan de uno en uno (§6.9.3): las mismas dimensiones a todo un tipo."""
    tipo = await tipo_equipo(cliente, auth, "Climatización", 0)
    nuevos = [await equipo_con_historia(cliente, auth, datos, fallas=f, familia="Climatización",
                                        tipo_equipo_id=tipo["id"]) for f in (0, 3)]
    r = await cliente.post("/api/criticidad/masiva", headers=await auth(AE),
                           json={"tipo_equipo_id": tipo["id"],
                                 "dimensiones": {"operacional": 3, "seguridad": 3, "economico": 2, "imagen": 2}})
    assert r.status_code == 200, r.text
    assert r.json()["evaluados"] >= 2 and sum(r.json()["por_nivel"].values()) == r.json()["evaluados"]
    # Vuelve a correr: por defecto omite los que ya tienen criticidad y no ensucia el historial.
    otra = (await cliente.post("/api/criticidad/masiva", headers=await auth(AE),
                               json={"tipo_equipo_id": tipo["id"],
                                     "dimensiones": {"operacional": 1, "seguridad": 1, "economico": 1,
                                                     "imagen": 1}})).json()
    assert otra["evaluados"] == 0 and otra["omitidos"] >= 2
    particular = await evaluar(cliente, auth, nuevos[0]["id"], 1, 1, 1, 1)   # el caso particular se ajusta después
    assert Decimal(particular["impacto_ponderado"]) == Decimal("1.00")


async def test_registro_resumen_y_matriz(cliente, auth, datos):
    equipo = await equipo_con_historia(cliente, auth, datos, fallas=12)
    await evaluar(cliente, auth, equipo["id"], 5, 5, 5, 5)
    registro = (await cliente.get("/api/criticidad", headers=await auth(AE))).json()
    fila = next(f for f in registro if f["equipo_id"] == equipo["id"])
    assert fila["nivel"] == "A" and Decimal(fila["indice_criticidad"]) == Decimal("100.00")
    assert [Decimal(f["indice_criticidad"]) for f in registro] == sorted(
        (Decimal(f["indice_criticidad"]) for f in registro), reverse=True)
    solo_a = (await cliente.get("/api/criticidad", headers=await auth(AE), params={"nivel": "A"})).json()
    assert {f["nivel"] for f in solo_a} == {"A"} and equipo["id"] in {f["equipo_id"] for f in solo_a}

    resumen = (await cliente.get("/api/criticidad/resumen", headers=await auth(AE))).json()
    assert resumen["total"] == len(registro) and resumen["por_nivel"]["A"] >= 1
    assert sum(resumen["por_nivel"].values()) == resumen["total"]

    matriz = (await cliente.get("/api/criticidad/matriz", headers=await auth(AE))).json()
    assert matriz["total"] == len(registro)
    assert sum(c["total"] for c in matriz["celdas"]) == matriz["total"]
    assert all(1 <= c["probabilidad"] <= 5 and 1 <= c["impacto"] <= 5 for c in matriz["celdas"])
    celda = next(c for c in matriz["celdas"] if c["probabilidad"] == 5 and c["impacto"] == 5)
    assert celda["total"] >= 1 and equipo["id"] in {e["equipo_id"] for e in celda["equipos"]}


async def test_los_cuatro_niveles_del_demo_salen_del_calculo(cliente, auth, datos):
    """El seed deja los doce equipos demo evaluados con los cuatro niveles representados y dos activos A, uno de
    ellos sin plan de mantenimiento: es lo que se revisa en la demo."""
    registro = (await cliente.get("/api/criticidad", headers=await auth(AE))).json()
    demo = [f for f in registro if f["codigo"].startswith("EQ-00")]
    por_nivel: dict[str, list[str]] = {}
    for f in demo:
        por_nivel.setdefault(f["nivel"], []).append(f["codigo"])
    assert len(demo) == 12, [f["codigo"] for f in demo]
    assert set(por_nivel) == {"A", "B", "C", "D"}, por_nivel
    assert sorted(por_nivel["A"]) == ["EQ-0001", "EQ-0002"], por_nivel["A"]
    assert all(f["origen"] == "calculado" and not f["probabilidad_estimada"] for f in demo)
    resumen = (await cliente.get("/api/criticidad/resumen", headers=await auth(AE))).json()
    assert resumen["criticos_sin_plan"] >= 1


async def test_aislamiento_entre_clientes(cliente, auth, datos):
    """El otro cliente no ve ni evalúa los activos del demo, y su configuración es la suya."""
    equipo = await equipo_con_historia(cliente, auth, datos, fallas=3)
    await evaluar(cliente, auth, equipo["id"])
    assert (await cliente.get(f"/api/criticidad/equipos/{equipo['id']}",
                              headers=await auth(OTRO_AE))).status_code == 404
    await evaluar(cliente, auth, equipo["id"], email=OTRO_AE, esperado=404)
    assert (await cliente.get(f"/api/criticidad/equipos/{equipo['id']}/historial",
                              headers=await auth(OTRO_AE))).status_code == 404
    ajeno = (await cliente.get("/api/criticidad", headers=await auth(OTRO_AE))).json()
    assert equipo["id"] not in {f["equipo_id"] for f in ajeno}
    propia = await configuracion(cliente, auth, email=OTRO_AE)
    assert propia["tenant_id"] == str(datos["otro_tenant"]) and propia["pesos_json"] == PESOS_DEFAULT
    # El Superadmin de la plataforma sí puede pedir el registro de un cliente concreto.
    del_demo = (await cliente.get("/api/criticidad", headers=await auth(SA),
                                  params={"tenant_id": str(datos["tenant"])})).json()
    assert equipo["id"] in {f["equipo_id"] for f in del_demo}


async def test_la_probabilidad_de_la_plataforma_no_dice_de_quien_salio(cliente, auth, datos):
    """El promedio del mismo tipo de equipo puede cruzar clientes (es un número anónimo), pero lo que se devuelve
    es solo el origen: nunca el cliente ni el equipo de donde salió."""
    tipo = await tipo_equipo(cliente, auth, "Equipos industriales", 1)
    con_historia = await equipo_con_historia(cliente, auth, datos, fallas=13, familia="Equipos industriales",
                                             tipo_equipo_id=tipo["id"])
    await evaluar(cliente, auth, con_historia["id"])
    r = await cliente.post("/api/catalogos/equipos", headers=await auth(OTRO_AE),
                           json={"un_id": str(datos["un_otro"]), "tipo_equipo_id": tipo["id"],
                                 "codigo": "OTRO-CRIT-1", "nombre": "Equipo del otro cliente"})
    assert r.status_code == 201, r.text
    fila = await evaluar(cliente, auth, r.json()["id"], 3, 3, 3, 3, email=OTRO_AE)
    assert fila["probabilidad_estimada"] is True
    texto = str(fila["dimensiones_json"]["probabilidad"]) + fila["probabilidad_origen"]
    assert str(datos["tenant"]) not in texto
    assert con_historia["id"] not in texto and con_historia["codigo"] not in texto


async def test_rls_forzada_y_evaluaciones_sin_delete(datos):
    """Las cinco tablas nuevas con RLS forzada, y el historial de evaluaciones append-only: `acma_api` no borra."""
    from core.db import nueva_sesion
    from core.rls import CONTEXTO_SISTEMA

    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        for tabla in TABLAS:
            fila = (await db.execute(text(
                "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = :t"), {"t": tabla})).one()
            assert fila.relrowsecurity and fila.relforcerowsecurity, tabla
        privilegios = {p for (p,) in (await db.execute(text(
            "SELECT privilege_type FROM information_schema.role_table_grants "
            "WHERE table_name = 'criticidad_evaluaciones' AND grantee = 'acma_api'"))).all()}
        assert "SELECT" in privilegios and "INSERT" in privilegios
        assert "DELETE" not in privilegios, privilegios
