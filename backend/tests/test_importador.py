"""Importador CSV/Excel (§6.3): plantillas, vista previa con errores y duplicados, confirmar y cancelar."""
import io
import uuid

from openpyxl import Workbook, load_workbook

AE, AP, SA, OTRO_AE = "admin.empresa@acma.dev", "admin.prestador@acma.dev", "superadmin@acma.dev", "admin.otro@acma.dev"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _csv(nombre: str, texto: str) -> dict:
    return {"archivo": (nombre, texto.encode("utf-8"), "text/csv")}


def _xlsx(nombre: str, filas: list[list]) -> dict:
    libro = Workbook()
    hoja = libro.active
    for f in filas:
        hoja.append(f)
    salida = io.BytesIO()
    libro.save(salida)
    return {"archivo": (nombre, salida.getvalue(), XLSX)}


async def test_catalogos_y_plantillas(cliente, auth):
    lista = (await cliente.get("/api/catalogos/importar/catalogos", headers=await auth(AE))).json()
    assert {c["clave"] for c in lista} == {"tecnicos", "unidades_negocio", "severidades", "familias_equipo", "tipos_equipo",
                                           "tipos_falla", "equipos", "matriz_severidad"}
    for cat in lista:
        r = await cliente.get(f"/api/catalogos/importar/{cat['clave']}/plantilla", headers=await auth(AE))
        assert r.status_code == 200 and r.headers["content-type"].startswith(XLSX)
        assert f"plantilla_{cat['clave']}.xlsx" in r.headers["content-disposition"]
        libro = load_workbook(io.BytesIO(r.content))
        encabezados = [c.value for c in libro.worksheets[0][1]]
        assert encabezados == [c["nombre"] for c in cat["columnas"]]
        assert len(list(libro.worksheets[0].iter_rows())) == 2  # encabezado + ejemplo
        assert "Instrucciones" in libro.sheetnames
    assert (await cliente.get("/api/catalogos/importar/inexistente/plantilla", headers=await auth(AE))).status_code == 404
    assert (await cliente.get("/api/catalogos/importar/equipos/plantilla", headers=await auth("operador@acma.dev"))).status_code == 403


async def test_importar_equipos_csv_valida_errores_duplicados_y_confirma(cliente, auth, datos):
    h = await auth(AE)
    nuevo = f"EQ-I{uuid.uuid4().hex[:5]}"
    csv = (
        "codigo,nombre,un_codigo,familia,tipo_equipo,marca,fecha_instalacion,valor_reposicion,garantia_vigente_hasta\n"
        f"{nuevo},Vitrina importada,SUC-001,Refrigeración,Refrigerador vertical,Torrey,2025-01-10,32000,2027-01-10\n"
        "EQ-X1,Sin unidad,SUC-999,Refrigeración,Refrigerador vertical,,,,\n"
        "EQ-X2,Tipo malo,SUC-001,Refrigeración,Inexistente,,,,\n"
        "EQ-X3,Fecha mala,SUC-001,Climatización,Minisplit,,ayer,,\n"
        "EQ-0001,Ya existe,SUC-001,Refrigeración,Refrigerador vertical,,,,\n"
        f"{nuevo},Repetido en archivo,SUC-001,Refrigeración,Refrigerador vertical,,,,\n"
    )
    r = await cliente.post("/api/catalogos/importar/equipos", headers=h, files=_csv("equipos.csv", csv))
    assert r.status_code == 201, r.text
    cuerpo = r.json()
    assert cuerpo["estado"] == "vista_previa" and cuerpo["total_filas"] == 6
    assert cuerpo["filas_ok"] == 1 and cuerpo["filas_error"] == 4 and len(cuerpo["duplicados_json"]) == 1
    errores = {(e["fila"], e["columna"]) for e in cuerpo["errores_json"]}
    assert errores == {(3, "un_codigo"), (4, "tipo_equipo"), (5, "fecha_instalacion"), (7, "codigo")}
    assert cuerpo["duplicados_json"][0]["fila"] == 6
    assert cuerpo["vista_previa"][0]["codigo"] == nuevo and cuerpo["vista_previa"][0]["fila"] == 2

    detalle = await cliente.get(f"/api/catalogos/importar/{cuerpo['id']}", headers=h)
    assert detalle.status_code == 200
    assert (await cliente.get(f"/api/catalogos/importar/{cuerpo['id']}", headers=await auth(OTRO_AE))).status_code == 404

    conf = await cliente.post(f"/api/catalogos/importar/{cuerpo['id']}/confirmar", headers=h)
    assert conf.status_code == 200, conf.text
    assert conf.json()["estado"] == "confirmada" and conf.json()["resultado"] == {"creados": 1, "actualizados": 0}
    equipo = (await cliente.get("/api/catalogos/equipos", headers=h, params={"q": nuevo})).json()[0]
    assert equipo["marca"] == "Torrey" and equipo["en_garantia"] is True and equipo["con_contrato_activo"] is True
    assert (await cliente.post(f"/api/catalogos/importar/{cuerpo['id']}/confirmar", headers=h)).json()["codigo"] == "IMPORTACION_CERRADA"


async def test_importar_tecnicos_xlsx_y_cancelar(cliente, auth, datos):
    h = await auth(AP)
    correo = f"imp.{uuid.uuid4().hex[:6]}@prestador.dev"
    filas = [
        ["email", "nombre", "contrasena", "numero_empleado", "habilidades"],
        [correo, "Importado Uno", "Inicial#Acma2026", "T-800", "refrigeracion;hvac"],
        ["malo@prestador.dev", "Contraseña débil", "corta", "T-801", ""],
        ["otro@prestador.dev", "Habilidad rara", "Inicial#Acma2026", "T-802", "soldadura_laser"],
        ["tecnico1@acma.dev", "Ya existe", "Inicial#Acma2026", "T-803", ""],
    ]
    r = await cliente.post("/api/catalogos/importar/tecnicos", headers=h, files=_xlsx("tecnicos.xlsx", filas))
    assert r.status_code == 201, r.text
    c = r.json()
    assert c["filas_ok"] == 1 and c["filas_error"] == 2 and len(c["duplicados_json"]) == 1
    assert {e["columna"] for e in c["errores_json"]} == {"contrasena", "habilidades"}
    assert "contrasena" not in c["vista_previa"][0]  # ya está pero no debe viajar: la vista previa la omite
    conf = await cliente.post(f"/api/catalogos/importar/{c['id']}/confirmar", headers=h)
    assert conf.status_code == 200 and conf.json()["resultado"]["creados"] == 1
    tec = (await cliente.get("/api/catalogos/tecnicos", headers=h, params={"q": correo})).json()[0]
    assert {x["clave"] for x in tec["habilidades"]} == {"refrigeracion", "hvac"} and tec["numero_empleado"] == "T-800"
    assert (await cliente.post("/api/auth/login", json={"email": correo, "contrasena": "Inicial#Acma2026"})).status_code == 200

    # Cancelar deja todo igual.
    r2 = await cliente.post("/api/catalogos/importar/tecnicos", headers=h, files=_xlsx("t2.xlsx", filas[:2]))
    assert r2.json()["filas_ok"] == 0 and len(r2.json()["duplicados_json"]) == 1  # el correo ya existe
    canc = await cliente.post(f"/api/catalogos/importar/{r2.json()['id']}/cancelar", headers=h)
    assert canc.json()["estado"] == "cancelada"
    assert (await cliente.post(f"/api/catalogos/importar/{r2.json()['id']}/confirmar", headers=h)).status_code == 409


async def test_importar_roles_columnas_y_formatos(cliente, auth, datos):
    assert (await cliente.post("/api/catalogos/importar/tecnicos", headers=await auth(AE), files=_csv("t.csv", "email\n"))).status_code == 403
    assert (await cliente.post("/api/catalogos/importar/equipos", headers=await auth(AP), files=_csv("e.csv", "codigo\n"))).status_code == 403
    faltan = await cliente.post("/api/catalogos/importar/equipos", headers=await auth(AE), files=_csv("e.csv", "codigo,nombre\nA,B\n"))
    assert faltan.status_code == 422 and faltan.json()["codigo"] == "COLUMNAS_FALTANTES" and "un_codigo" in faltan.json()["detalles"]
    assert (await cliente.post("/api/catalogos/importar/equipos", headers=await auth(AE), files={"archivo": ("e.txt", b"x", "text/plain")})).json()["codigo"] == "FORMATO_NO_SOPORTADO"
    assert (await cliente.post("/api/catalogos/importar/equipos", headers=await auth(AE), files=_csv("e.csv", ""))).json()["codigo"] == "ARCHIVO_VACIO"
    # Separador ; y encabezados con acentos/mayúsculas se normalizan.
    r = await cliente.post("/api/catalogos/importar/familias_equipo", headers=await auth(AE),
                           files=_csv("f.csv", f"Nombre;Descripción\nFamilia {uuid.uuid4().hex[:4]};Propia del tenant\nRefrigeración;ya existe global\n"))
    assert r.status_code == 201 and r.json()["filas_ok"] == 1 and len(r.json()["duplicados_json"]) == 1
    conf = await cliente.post(f"/api/catalogos/importar/{r.json()['id']}/confirmar", headers=await auth(AE))
    assert conf.json()["resultado"]["creados"] == 1


async def test_importar_matriz_y_severidades(cliente, auth, datos):
    # Matriz (tenant): actualiza una celda existente y crea una nueva combinación válida.
    h = await auth(AE)
    m = (await cliente.get("/api/catalogos/matriz-severidad", headers=h)).json()
    csv = ("tipo_falla,tipo_equipo,severidad\n"
           "No enciende,Refrigerador vertical,alta\n"
           "No enciende,Lámpara LED de techo,critica\n"  # válida: hay 'No enciende' de Iluminación
           "Ruido inusual,Minisplit,media\n"  # familias distintas
           "Inexistente,Minisplit,media\n"
           "No enfría,Minisplit,urgente\n")
    r = await cliente.post("/api/catalogos/importar/matriz_severidad", headers=h, files=_csv("m.csv", csv))
    assert r.status_code == 201, r.text
    assert r.json()["filas_ok"] == 2 and {e["columna"] for e in r.json()["errores_json"]} == {"tipo_equipo", "tipo_falla", "severidad"}
    conf = await cliente.post(f"/api/catalogos/importar/{r.json()['id']}/confirmar", headers=h)
    assert conf.json()["resultado"] == {"creados": 0, "actualizados": 2}
    refri = next(t for t in m["tipos_equipo"] if t["nombre"] == "Refrigerador vertical")
    ne = next(f for f in m["tipos_falla"] if f["descripcion"] == "No enciende" and f["familia_equipo_id"] == refri["familia_id"])
    res = (await cliente.get("/api/catalogos/matriz-severidad/resolver", headers=h, params={"tipo_falla_id": ne["id"], "tipo_equipo_id": refri["id"]})).json()
    assert res["nivel"]["clave"] == "alta"
    # Restaurar a crítica para las demás pruebas.
    niveles = {n["clave"]: n["id"] for n in m["niveles"]}
    await cliente.put("/api/catalogos/matriz-severidad/celda", headers=h, json={"tipo_falla_id": ne["id"], "tipo_equipo_id": refri["id"], "nivel_severidad_id": niveles["critica"]})

    # Severidades (prestador): actualiza por clave; clave inválida es error.
    hp = await auth(AP)
    r = await cliente.post("/api/catalogos/importar/severidades", headers=hp,
                           files=_csv("s.csv", "clave,nombre,tiempo_respuesta_horas,tiempo_resolucion_horas\nalta,Alta prioridad,3,20\nurgente,X,1,2\nmedia,,9000,1\n"))
    assert r.json()["filas_ok"] == 1 and r.json()["filas_error"] == 2
    await cliente.post(f"/api/catalogos/importar/{r.json()['id']}/confirmar", headers=hp)
    alta = next(n for n in (await cliente.get("/api/catalogos/severidades", headers=hp)).json() if n["clave"] == "alta")
    assert alta["nombre"] == "Alta prioridad" and alta["tiempo_respuesta_horas"] == 3 and alta["tiempo_resolucion_horas"] == 20
