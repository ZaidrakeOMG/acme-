"""FMEA simplificado de §6.9.3: modos de falla por activo y genéricos del tipo de equipo, nivel y categoría de
riesgo, propuestas desde el historial de correctivos, matriz 5×5 y aislamiento entre clientes. F2-05."""
import pytest

from services.riesgo_service import categoria_riesgo, frecuencia_desde_fallas, nivel_riesgo
from tests.criticidad_utiles import equipo_con_historia, modo_falla
from tests.folios_utiles import AE, AP, AUN, DES, OP, OTRO_AE, OTRO_AP, TEC, tipo_equipo


def test_nivel_de_riesgo_y_su_categoria():
    """§6.9.3: severidad × frecuencia, y × detección cuando se captura (el RPN clásico del FMEA)."""
    assert nivel_riesgo(5, 4) == 20 and nivel_riesgo(5, 4, 3) == 60
    assert nivel_riesgo(1, 1) == 1 and nivel_riesgo(5, 5) == 25
    # La categoría siempre es severidad × frecuencia, para que sea comparable entre clientes.
    assert categoria_riesgo(5, 4) == "critico" and categoria_riesgo(4, 4) == "critico"   # 20 y 16
    assert categoria_riesgo(5, 3) == "alto" and categoria_riesgo(5, 2) == "alto"         # 15 y 10
    assert categoria_riesgo(3, 3) == "medio" and categoria_riesgo(5, 1) == "medio"       # 9 y 5
    assert categoria_riesgo(2, 2) == "bajo" and categoria_riesgo(1, 1) == "bajo"         # 4 y 1
    # Fronteras de las cuatro categorías: 4/5, 9/10 y 15/16.
    assert categoria_riesgo(4, 1) == "bajo" and categoria_riesgo(1, 5) == "medio"
    assert categoria_riesgo(3, 3) == "medio" and categoria_riesgo(2, 5) == "alto"
    assert categoria_riesgo(3, 5) == "alto" and categoria_riesgo(4, 4) == "critico"


def test_frecuencia_desde_el_historial():
    """La misma escala que la probabilidad de la criticidad, para que las dos lecturas digan lo mismo."""
    assert [frecuencia_desde_fallas(n) for n in (0, 1, 2, 3, 5, 6, 11, 12, 30)] == [1, 2, 2, 3, 3, 4, 4, 5, 5]


async def test_registrar_un_modo_de_falla_del_activo(cliente, auth, datos):
    equipo = await equipo_con_historia(cliente, auth, datos, fallas=2)
    modo = await modo_falla(cliente, auth, equipo["id"], descripcion_falla="Fuga de refrigerante en el serpentín",
                            causa_probable="Corrosión por condensados", severidad=5, frecuencia_historica=3)
    assert modo["equipo_id"] == equipo["id"] and modo["tipo_equipo_id"] is None
    assert modo["nivel_riesgo"] == 15 and modo["origen"] == "manual" and modo["activo"] is True
    assert modo["tenant_id"] == str(datos["tenant"]) and modo["registrado_por"] is not None
    # Con detección el riesgo es el RPN de tres factores.
    con_deteccion = await modo_falla(cliente, auth, equipo["id"], severidad=5, frecuencia_historica=3, deteccion=4)
    assert con_deteccion["nivel_riesgo"] == 60 and con_deteccion["deteccion"] == 4


async def test_un_modo_es_del_activo_o_del_tipo_pero_no_de_los_dos(cliente, auth, datos):
    """El genérico del tipo de equipo evita repetir el análisis en cada minisplit igual."""
    equipo = await equipo_con_historia(cliente, auth, datos, fallas=1)
    tipo = await tipo_equipo(cliente, auth, "Climatización", 1)
    generico = await modo_falla(cliente, auth, descripcion_falla="Drenaje tapado por biopelícula",
                                tipo_equipo_id=tipo["id"], tenant_id=str(datos["tenant"]),
                                severidad=3, frecuencia_historica=3)
    assert generico["tipo_equipo_id"] == tipo["id"] and generico["equipo_id"] is None
    # Los dos a la vez, o ninguno, se rechazan.
    await modo_falla(cliente, auth, equipo["id"], tipo_equipo_id=tipo["id"], esperado=422)
    await modo_falla(cliente, auth, esperado=422)


async def test_el_equipo_ve_sus_modos_y_los_genericos_de_su_tipo(cliente, auth, datos):
    tipo = await tipo_equipo(cliente, auth, "Climatización", 1)
    equipo = await equipo_con_historia(cliente, auth, datos, fallas=1, familia="Climatización",
                                       tipo_equipo_id=tipo["id"])
    propio = await modo_falla(cliente, auth, equipo["id"], descripcion_falla="Compresor con arranque duro")
    generico = await modo_falla(cliente, auth, descripcion_falla="Filtro saturado del tipo de equipo",
                                tipo_equipo_id=tipo["id"], tenant_id=str(datos["tenant"]))
    con = (await cliente.get("/api/modos-falla", headers=await auth(AP),
                             params={"equipo_id": equipo["id"]})).json()
    assert {propio["id"], generico["id"]} <= {m["id"] for m in con}
    sin = (await cliente.get("/api/modos-falla", headers=await auth(AP),
                             params={"equipo_id": equipo["id"], "incluir_genericos": False})).json()
    assert propio["id"] in {m["id"] for m in sin} and generico["id"] not in {m["id"] for m in sin}


async def test_editar_y_desactivar_un_modo(cliente, auth, datos):
    equipo = await equipo_con_historia(cliente, auth, datos, fallas=1)
    modo = await modo_falla(cliente, auth, equipo["id"], severidad=3, frecuencia_historica=2)
    assert modo["nivel_riesgo"] == 6
    r = await cliente.put(f"/api/modos-falla/{modo['id']}", headers=await auth(AP),
                          json={"severidad": 5, "frecuencia_historica": 4,
                                "efecto_operacional": "Detiene la línea completa"})
    assert r.status_code == 200, r.text
    assert r.json()["nivel_riesgo"] == 20 and r.json()["efecto_operacional"] == "Detiene la línea completa"
    # Desactivarlo lo saca del listado y de la matriz, sin borrar el análisis.
    assert (await cliente.put(f"/api/modos-falla/{modo['id']}", headers=await auth(AP),
                              json={"activo": False})).status_code == 200
    vigentes = (await cliente.get("/api/modos-falla", headers=await auth(AP),
                                  params={"equipo_id": equipo["id"]})).json()
    assert modo["id"] not in {m["id"] for m in vigentes}
    todos = (await cliente.get("/api/modos-falla", headers=await auth(AP),
                               params={"equipo_id": equipo["id"], "solo_activos": False})).json()
    assert modo["id"] in {m["id"] for m in todos}


async def test_sugerencias_desde_el_historial_de_correctivos(cliente, auth, datos):
    """El FMEA no se escribe en blanco: ACMA propone los tipos de falla que el activo ya repitió."""
    from tests.criticidad_utiles import sembrar_fallas

    equipo = await equipo_con_historia(cliente, auth, datos, fallas=7)
    s = (await cliente.get("/api/modos-falla/sugerencias", headers=await auth(AP),
                           params={"equipo_id": equipo["id"]})).json()
    assert s, "con siete correctivos cerrados debería proponer algo"
    primera = s[0]
    assert primera["fallas_12m"] >= 1 and primera["descripcion_falla"]
    assert primera["frecuencia_historica"] == frecuencia_desde_fallas(primera["fallas_12m"])
    assert primera["nivel_riesgo"] == nivel_riesgo(primera["severidad"], primera["frecuencia_historica"])
    assert primera["categoria"] in ("bajo", "medio", "alto", "critico")
    assert primera["ya_registrado"] is False and str(primera["fallas_12m"]) in primera["nota"]
    # Van de la más frecuente a la menos frecuente: es el orden en que conviene atacarlas.
    assert [x["fallas_12m"] for x in s] == sorted((x["fallas_12m"] for x in s), reverse=True)

    # Aceptarlas en lote las deja marcadas como `sugerido`, para distinguirlas de lo que escribió una persona.
    r = await cliente.post("/api/modos-falla/aceptar-sugerencias", headers=await auth(AP),
                           json={"equipo_id": equipo["id"],
                                 "sugerencias": [{"descripcion_falla": primera["descripcion_falla"],
                                                  "tipo_falla_id": primera["tipo_falla_id"],
                                                  "causa_probable": primera["causa_probable"],
                                                  "severidad": primera["severidad"],
                                                  "frecuencia_historica": primera["frecuencia_historica"]}]})
    assert r.status_code == 201, r.text
    creado = r.json()[0]
    assert creado["origen"] == "sugerido" and creado["equipo_id"] == equipo["id"]
    # Ya registrada, la propuesta lo dice para no duplicar el análisis.
    de_nuevo = (await cliente.get("/api/modos-falla/sugerencias", headers=await auth(AP),
                                  params={"equipo_id": equipo["id"]})).json()
    repetida = next(x for x in de_nuevo if x["descripcion_falla"] == primera["descripcion_falla"])
    assert repetida["ya_registrado"] is True


async def test_sin_historial_no_hay_sugerencias(cliente, auth, datos):
    equipo = await equipo_con_historia(cliente, auth, datos, fallas=0)
    s = (await cliente.get("/api/modos-falla/sugerencias", headers=await auth(AP),
                           params={"equipo_id": equipo["id"]})).json()
    assert s == [] or all(x["fallas_12m"] == 0 for x in s)


async def test_refrescar_frecuencias_con_el_historial_de_hoy(cliente, auth, datos):
    """La frecuencia de un modo envejece: la tarea la vuelve a leer del historial."""
    from core.db import nueva_sesion
    from core.rls import CONTEXTO_SISTEMA
    from services import riesgo_service
    from tests.criticidad_utiles import sembrar_fallas
    import uuid

    equipo = await equipo_con_historia(cliente, auth, datos, fallas=2)
    s = (await cliente.get("/api/modos-falla/sugerencias", headers=await auth(AP),
                           params={"equipo_id": equipo["id"]})).json()
    modo = (await cliente.post("/api/modos-falla/aceptar-sugerencias", headers=await auth(AP),
                               json={"equipo_id": equipo["id"],
                                     "sugerencias": [{"descripcion_falla": s[0]["descripcion_falla"],
                                                      "tipo_falla_id": s[0]["tipo_falla_id"],
                                                      "severidad": s[0]["severidad"],
                                                      "frecuencia_historica": s[0]["frecuencia_historica"]}]})).json()[0]
    assert modo["frecuencia_historica"] == 2
    await sembrar_fallas(equipo["id"], 10, desde_dias=200, hasta_dias=30)
    from models.catalogos import Equipo

    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        e = await db.get(Equipo, uuid.UUID(equipo["id"]))
        cambiados = await riesgo_service.refrescar_frecuencias(db, e)
        await db.commit()
    assert cambiados >= 1
    al_dia = (await cliente.get("/api/modos-falla", headers=await auth(AP),
                                params={"equipo_id": equipo["id"]})).json()
    actualizado = next(m for m in al_dia if m["id"] == modo["id"])
    assert actualizado["frecuencia_historica"] == 5 and actualizado["fallas_12m"] >= 12
    assert actualizado["nivel_riesgo"] == nivel_riesgo(actualizado["severidad"], 5, actualizado["deteccion"])


async def test_matriz_de_riesgo_de_los_modos(cliente, auth, datos):
    equipo = await equipo_con_historia(cliente, auth, datos, fallas=1)
    modo = await modo_falla(cliente, auth, equipo["id"], severidad=5, frecuencia_historica=4)
    m = (await cliente.get("/api/modos-falla/matriz", headers=await auth(AP))).json()
    celda = next(c for c in m["celdas"] if c["severidad"] == 5 and c["frecuencia"] == 4)
    assert celda["categoria"] == "critico" and modo["id"] in {x["id"] for x in celda["modos"]}
    assert sum(c["total"] for c in m["celdas"]) == m["total"]
    assert sum(m["por_categoria"].values()) == m["total"]
    assert set(m["por_categoria"]) == {"bajo", "medio", "alto", "critico"}


async def test_quien_registra_riesgo(cliente, auth, datos):
    """El FMEA lo arma quien conoce el equipo: el prestador que lo mantiene y el cliente que lo opera."""
    equipo = await equipo_con_historia(cliente, auth, datos, fallas=1)
    for email in (AE, AUN, AP, DES):
        await modo_falla(cliente, auth, equipo["id"], email=email)
    for email in (OP, TEC):
        await modo_falla(cliente, auth, equipo["id"], email=email, esperado=403)
        assert (await cliente.get("/api/modos-falla", headers=await auth(email),
                                  params={"equipo_id": equipo["id"]})).status_code == 403


async def test_aislamiento_de_los_modos_de_falla(cliente, auth, datos):
    equipo = await equipo_con_historia(cliente, auth, datos, fallas=2)
    modo = await modo_falla(cliente, auth, equipo["id"])
    assert (await cliente.get("/api/modos-falla", headers=await auth(OTRO_AE),
                              params={"equipo_id": equipo["id"]})).status_code == 404
    assert (await cliente.get("/api/modos-falla/sugerencias", headers=await auth(OTRO_AP),
                              params={"equipo_id": equipo["id"]})).status_code == 404
    assert (await cliente.put(f"/api/modos-falla/{modo['id']}", headers=await auth(OTRO_AE),
                              json={"severidad": 1})).status_code == 404
    ajena = (await cliente.get("/api/modos-falla/matriz", headers=await auth(OTRO_AE))).json()
    assert modo["id"] not in {x["id"] for c in ajena["celdas"] for x in c["modos"]}
