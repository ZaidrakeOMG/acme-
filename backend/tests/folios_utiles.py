"""Ayudas compartidas por las pruebas de folios (P04)."""
import uuid

SA, AP, MC, DES, TEC, TEC2, TEC4 = ("superadmin@acma.dev", "admin.prestador@acma.dev", "mesa.control@acma.dev", "despachador@acma.dev",
                                   "tecnico1@acma.dev", "tecnico2@acma.dev", "tecnico4@acma.dev")
AE, AUN, SUPO, OP = "admin.empresa@acma.dev", "admin.un@acma.dev", "supervisor.operadores@acma.dev", "operador@acma.dev"
OTRO_AE, OTRO_OP, OTRO_AP = "admin.otro@acma.dev", "operador.otro@acma.dev", "admin.otroprestador@acma.dev"

_cache: dict = {}


async def catalogo(cliente, auth):
    """Familias, tipos de equipo y tipos de falla del tenant demo (cacheados por sesión de pruebas)."""
    if "familias" not in _cache:
        h = await auth(AE)
        _cache["familias"] = {f["nombre"]: f for f in (await cliente.get("/api/catalogos/familias-equipo", headers=h)).json()}
        _cache["tipos"] = (await cliente.get("/api/catalogos/tipos-equipo", headers=h)).json()
        _cache["fallas"] = (await cliente.get("/api/catalogos/tipos-falla", headers=h)).json()
    return _cache


async def tipo_equipo(cliente, auth, familia="Refrigeración", indice=0):
    c = await catalogo(cliente, auth)
    familia_id = c["familias"][familia]["id"]
    return sorted([t for t in c["tipos"] if t["familia_id"] == familia_id], key=lambda t: t["nombre"])[indice]


async def tipo_falla(cliente, auth, familia="Refrigeración", descripcion="No enciende"):
    c = await catalogo(cliente, auth)
    familia_id = c["familias"][familia]["id"]
    return next(f for f in c["fallas"] if f["familia_equipo_id"] == familia_id and f["descripcion"] == descripcion)


async def nuevo_equipo(cliente, auth, datos, *, familia="Refrigeración", indice=0, un_index=0, criticidad=None, **extra) -> dict:
    """Equipo nuevo del tenant demo (sin folios abiertos) para no chocar con los 15 folios del seed."""
    tipo = await tipo_equipo(cliente, auth, familia, indice)
    codigo = f"EQT-{uuid.uuid4().hex[:6].upper()}"
    cuerpo = {"un_id": str(datos["unidades"][un_index]), "tipo_equipo_id": tipo["id"], "codigo": codigo, "nombre": f"Equipo {codigo}",
              "criticidad": criticidad, **extra}
    r = await cliente.post("/api/catalogos/equipos", headers=await auth(AE), json=cuerpo)
    assert r.status_code == 201, r.text
    return r.json()


async def capturar(cliente, auth, datos, email=OP, equipo=None, *, familia="Refrigeración", falla="No enciende", descripcion=None,
                   confirmacion=True, esperado=201, **extra):
    equipo = equipo or await nuevo_equipo(cliente, auth, datos, familia=familia)
    tf = await tipo_falla(cliente, auth, familia, falla)
    cuerpo = {"un_id": equipo["un_id"], "equipo_id": equipo["id"], "tipo_falla_id": tf["id"],
              "descripcion": descripcion or f"Falla de prueba {uuid.uuid4().hex[:8]}", "confirmacion_un": confirmacion,
              "confirmacion_un_geolat": 19.4326, "confirmacion_un_geolng": -99.1332, "geolat_captura": 19.4326, "geolng_captura": -99.1332, **extra}
    r = await cliente.post("/api/folios", headers=await auth(email), json=cuerpo)
    assert r.status_code == esperado, r.text
    return r.json()


async def detalle(cliente, auth, folio_id, email=AE):
    r = await cliente.get(f"/api/folios/{folio_id}", headers=await auth(email))
    assert r.status_code == 200, r.text
    return r.json()


async def politicas(cliente, auth, **cambios):
    r = await cliente.put("/api/folios/politicas", headers=await auth(AE), json=cambios)
    assert r.status_code == 200, r.text
    return r.json()


async def reglas(cliente, auth, lista):
    r = await cliente.put("/api/folios/aprobacion/reglas", headers=await auth(AE), json=lista)
    assert r.status_code == 200, r.text
    return r.json()


REGLAS_DEMO = [
    {"nivel": 1, "criterio": "monto", "operador": "<", "valor_json": {"monto": 5000}},
    {"nivel": 2, "criterio": "monto", "operador": "entre", "valor_json": {"min": 5000, "max": 20000}},
    {"nivel": 3, "criterio": "monto", "operador": ">=", "valor_json": {"monto": 20000}},
    {"nivel": 2, "criterio": "criticidad", "operador": "en", "valor_json": {"valores": ["A", "B"]}},
    {"nivel": 1, "criterio": "tipo_trabajo", "operador": "igual", "valor_json": {"tipo": "preventivo"}},
    {"nivel": 2, "criterio": "tipo_trabajo", "operador": "igual", "valor_json": {"tipo": "especial"}},
]
NIVELES_DEMO = [
    {"nivel": 1, "rol_aprobador": "admin_un", "tiempo_limite_horas": 4, "comportamiento_timeout": "escalar"},
    {"nivel": 2, "rol_aprobador": "supervisor_operadores", "tiempo_limite_horas": 12, "comportamiento_timeout": "depende_criticidad"},
    {"nivel": 3, "rol_aprobador": "admin_empresa", "tiempo_limite_horas": 24, "comportamiento_timeout": "bloquear_alertar"},
]


async def niveles(cliente, auth, lista=None, esperado=200):
    r = await cliente.put("/api/folios/aprobacion/niveles", headers=await auth(AE), json=lista or NIVELES_DEMO)
    assert r.status_code == esperado, r.text
    return r.json()


async def autorizar_sin_flujo(cliente, auth, datos, email=OP, **kw):
    """Folio que llega directo a `autorizado`: sin reglas de aprobación en el tenant durante la captura."""
    await reglas(cliente, auth, [])
    try:
        return await capturar(cliente, auth, datos, email, **kw)
    finally:
        await reglas(cliente, auth, REGLAS_DEMO)


async def accion(cliente, auth, email, folio_id, ruta, cuerpo=None, esperado=200):
    r = await cliente.post(f"/api/folios/{folio_id}/{ruta}", headers=await auth(email), json=cuerpo or {})
    assert r.status_code == esperado, f"{ruta}: {r.status_code} {r.text}"
    return r.json()


async def tecnico_usuario_id(cliente, auth, email):
    lista = (await cliente.get("/api/catalogos/tecnicos", headers=await auth(AP))).json()
    return next(t["usuario_id"] for t in lista if t["email"] == email)


async def tecnico_con_habilidades(cliente, auth, email, claves) -> str:
    """Deja al técnico exactamente con esas habilidades (las pruebas de catálogos las cambian) y devuelve su usuario_id."""
    h = await auth(AP)
    lista = (await cliente.get("/api/catalogos/tecnicos", headers=h)).json()
    t = next(x for x in lista if x["email"] == email)
    habs = {x["clave"]: x["id"] for x in (await cliente.get("/api/catalogos/habilidades", headers=h)).json()}
    r = await cliente.put(f"/api/catalogos/tecnicos/{t['id']}/habilidades", headers=h,
                          json={"habilidades": [{"habilidad_id": habs[c], "certificada": True} for c in claves]})
    assert r.status_code == 200, r.text
    return t["usuario_id"]
