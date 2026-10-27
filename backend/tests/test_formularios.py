"""Motor de formularios: permisos §6.8.3c, versionado, resolver con prioridad, clonado, catálogos y aislamiento."""
import uuid

from sqlalchemy import text

from core.db import nueva_sesion
from core.rls import CONTEXTO_SISTEMA

SA, AP, MC, DES, TEC, AE, AUN, OP = ("superadmin@acma.dev", "admin.prestador@acma.dev", "mesa.control@acma.dev", "despachador@acma.dev",
                                     "tecnico1@acma.dev", "admin.empresa@acma.dev", "admin.un@acma.dev", "operador@acma.dev")
OTRO_AP, OTRO_AE = "admin.otroprestador@acma.dev", "admin.otro@acma.dev"


def esquema_simple(**extra):
    return {"secciones": [{"clave": "s1", "titulo": "Sección", "campos": [
        {"clave": "comentario", "tipo": "texto", "etiqueta": "Comentario", "obligatorio": True, "config": {"longitud_min": 2, "longitud_max": 100}},
        {"clave": "ok", "tipo": "si_no", "etiqueta": "¿Todo bien?", "obligatorio": True},
        *extra.get("campos", []),
    ]}]}


async def crear_formulario(cliente, auth, email=AP, nombre=None, **campos):
    cuerpo = {"nombre": nombre or f"Prueba {uuid.uuid4().hex[:6]}", "tipo": "libre", "rol_destino": ["tecnico", "operador"], "esquema": esquema_simple(), **campos}
    r = await cliente.post("/api/formularios", headers=await auth(email), json=cuerpo)
    assert r.status_code == 201, r.text
    return r.json()


async def publicar(cliente, auth, fid, email=AP, notas="v"):
    r = await cliente.post(f"/api/formularios/{fid}/publicar", headers=await auth(email), json={"notas_version": notas})
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------------------------------ permisos

async def test_permisos_de_diseno(cliente, auth, datos):
    for email in (AE, AUN, OP, TEC, DES):
        r = await cliente.post("/api/formularios", headers=await auth(email), json={"nombre": "Sin permiso", "rol_destino": ["tecnico"], "esquema": esquema_simple()})
        assert r.status_code == 403, email
    f = await crear_formulario(cliente, auth)
    assert f["estado"] == "borrador" and f["version_actual"] == 1 and f["prestador_id"] == str(datos["prestador"]) and f["puede_editar"]
    # Mesa de control no edita sin permiso; admin empresa solo lectura de publicados.
    assert (await cliente.put(f"/api/formularios/{f['id']}", headers=await auth(MC), json={"nombre": "Nuevo"})).status_code == 403
    assert (await cliente.get(f"/api/formularios/{f['id']}", headers=await auth(AE))).status_code == 404  # borrador no visible para uso
    await publicar(cliente, auth, f["id"])
    visto = await cliente.get(f"/api/formularios/{f['id']}", headers=await auth(AE))
    assert visto.status_code == 200 and visto.json()["puede_editar"] is False
    # Plantillas base: solo superadmin.
    assert (await cliente.post("/api/formularios", headers=await auth(AP), json={"nombre": "Plantilla P", "rol_destino": ["tecnico"], "es_plantilla_base": True, "esquema": esquema_simple()})).status_code == 403
    plantilla = await crear_formulario(cliente, auth, SA, es_plantilla_base=True)
    assert plantilla["prestador_id"] is None and plantilla["es_plantilla_base"]
    # Superadmin modifica cualquiera.
    assert (await cliente.put(f"/api/formularios/{f['id']}", headers=await auth(SA), json={"descripcion": "Tocado por superadmin"})).status_code == 200


async def test_mesa_de_control_edita_publicado_con_permiso(cliente, auth, datos):
    h = await auth(AP)
    f = await crear_formulario(cliente, auth)
    await publicar(cliente, auth, f["id"])
    mesa = (await cliente.get("/api/usuarios", headers=h, params={"rol": "mesa_control"})).json()[0]
    assert (await cliente.put(f"/api/formularios/{f['id']}/permisos-mesa", headers=h, json={"permisos": [{"usuario_id": mesa["id"], "puede_editar_publicado": True}]})).status_code == 200
    desp = (await cliente.get("/api/usuarios", headers=h, params={"rol": "despachador"})).json()[0]
    assert (await cliente.put(f"/api/formularios/{f['id']}/permisos-mesa", headers=h, json={"permisos": [{"usuario_id": desp["id"]}]})).status_code == 422
    nuevo = esquema_simple(campos=[{"clave": "extra", "tipo": "texto", "etiqueta": "Extra"}])
    r = await cliente.put(f"/api/formularios/{f['id']}", headers=await auth(MC), json={"esquema": nuevo, "notas_version": "Ajuste de mesa"})
    assert r.status_code == 200, r.text
    assert r.json()["version_actual"] == 2 and r.json()["numero_version_publicada"] == 1 and r.json()["estado"] == "publicado"
    # La mesa no cambia alcance ni rol destino, ni archiva.
    assert (await cliente.put(f"/api/formularios/{f['id']}", headers=await auth(MC), json={"rol_destino": ["operador"]})).status_code == 403
    assert (await cliente.post(f"/api/formularios/{f['id']}/archivar", headers=await auth(MC))).status_code == 403
    pub = await publicar(cliente, auth, f["id"], MC, "Publicado por mesa")
    assert pub["numero_version_publicada"] == 2


# ----------------------------------------------------------------- versionado

async def test_versionado_y_respuestas_conservan_version(cliente, auth, datos):
    h = await auth(AP)
    f = await crear_formulario(cliente, auth)
    # En borrador se edita en sitio.
    r = await cliente.put(f"/api/formularios/{f['id']}", headers=h, json={"esquema": esquema_simple(campos=[{"clave": "a", "tipo": "texto", "etiqueta": "A"}])})
    assert r.json()["version_actual"] == 1
    assert (await cliente.post(f"/api/formularios/{f['id']}/publicar", headers=h, json={"notas_version": ""})).status_code == 200
    assert (await cliente.post(f"/api/formularios/{f['id']}/publicar", headers=h, json={"notas_version": ""})).json()["codigo"] == "SIN_CAMBIOS"
    # Un técnico responde contra la v1.
    resp = await cliente.post(f"/api/formularios/{f['id']}/respuestas", headers=await auth(TEC), json={"respuestas": {"comentario": "hola", "ok": True, "a": "x"}})
    assert resp.status_code == 201, resp.text
    v1_id = resp.json()["version_id"]
    assert resp.json()["numero_version"] == 1
    # Editar el publicado crea v2 en borrador sin tocar la v1.
    r = await cliente.put(f"/api/formularios/{f['id']}", headers=h, json={"esquema": esquema_simple(campos=[{"clave": "b", "tipo": "texto", "etiqueta": "B"}]), "notas_version": "Agrega b"})
    assert r.json()["version_actual"] == 2 and r.json()["numero_version_publicada"] == 1
    versiones = (await cliente.get(f"/api/formularios/{f['id']}/versiones", headers=h)).json()
    assert [v["numero_version"] for v in versiones] == [1, 2] and versiones[0]["publicada_at"] and versiones[1]["publicada_at"] is None
    diff = (await cliente.get(f"/api/formularios/{f['id']}/versiones/diff", headers=h, params={"de": 1, "a": 2})).json()
    assert diff == {"de": 1, "a": 2, "agregados": ["b"], "quitados": ["a"], "modificados": []}
    # Editar de nuevo mientras v2 sigue en borrador no crea v3.
    r = await cliente.put(f"/api/formularios/{f['id']}", headers=h, json={"esquema": esquema_simple(campos=[{"clave": "b", "tipo": "texto", "etiqueta": "B2"}])})
    assert r.json()["version_actual"] == 2
    pub = await publicar(cliente, auth, f["id"], notas="v2")
    assert pub["numero_version_publicada"] == 2
    # La respuesta enviada contra v1 conserva su versión; una nueva usa v2.
    env = await cliente.post(f"/api/formularios/respuestas/{resp.json()['id']}/enviar", headers=await auth(TEC))
    assert env.status_code == 200 and env.json()["version_id"] == v1_id
    nueva = await cliente.post(f"/api/formularios/{f['id']}/respuestas", headers=await auth(TEC), json={})
    assert nueva.json()["numero_version"] == 2
    # Archivado: no se edita ni se responde.
    assert (await cliente.post(f"/api/formularios/{f['id']}/archivar", headers=h)).json()["estado"] == "archivado"
    assert (await cliente.put(f"/api/formularios/{f['id']}", headers=h, json={"nombre": "Nombre nuevo"})).json()["codigo"] == "FORMULARIO_ARCHIVADO"
    assert (await cliente.post(f"/api/formularios/{f['id']}/respuestas", headers=await auth(TEC), json={})).status_code == 404


async def test_esquema_invalido_rechazado(cliente, auth):
    h = await auth(AP)
    malos = [
        esquema_simple(campos=[{"clave": "comentario", "tipo": "texto", "etiqueta": "Repetida"}]),
        esquema_simple(campos=[{"clave": "x", "tipo": "texto", "etiqueta": "X", "condiciones": [{"campo_origen": "nadie", "operador": "vacio"}]}]),
        esquema_simple(campos=[{"clave": "bg", "tipo": "boton_grupo", "etiqueta": "BG", "fuente_opciones": {"origen": "fija", "opciones": [{"valor": "a", "etiqueta": "A"}]}}]),
        esquema_simple(campos=[{"clave": "f", "tipo": "fotografia", "etiqueta": "F", "valor_defecto": "no"}]),
        esquema_simple(campos=[{"clave": "r", "tipo": "radio", "etiqueta": "R"}]),
        esquema_simple(campos=[{"clave": "t", "tipo": "texto", "etiqueta": "T", "config": {"formato": "regex", "regex": "("}}]),
        esquema_simple(campos=[{"clave": "e", "tipo": "encuesta_satisfaccion", "etiqueta": "E", "config": {"modalidad": "estrellas", "escala_max": 10}}]),
    ]
    for e in malos:
        r = await cliente.post("/api/formularios", headers=h, json={"nombre": "Malo", "rol_destino": ["tecnico"], "esquema": e})
        assert r.status_code == 422, e
    tipos = (await cliente.get("/api/formularios/tipos-campo", headers=h)).json()
    assert len(tipos) == 22 and tipos[0]["tipo"] == "si_no" and tipos[-1]["tipo"] == "geolocalizacion"


# ------------------------------------------------------------- resolver / asignar

async def test_resolver_prioridad_especifico_sobre_global(cliente, auth, datos):
    familias = {f["nombre"]: f for f in (await cliente.get("/api/catalogos/familias-equipo", headers=await auth(AE))).json()}
    refri = familias["Refrigeración"]["id"]
    tipos = {t["nombre"]: t for t in (await cliente.get("/api/catalogos/tipos-equipo", headers=await auth(AE), params={"familia_id": refri})).json()}
    # El técnico (prestador) resuelve para el tenant demo: gana el específico del tenant.
    r = await cliente.get("/api/formularios/resolver", headers=await auth(TEC), params={"tipo": "atencion_tecnico", "tenant_id": str(datos["tenant"]), "tipo_equipo_id": tipos["Refrigerador vertical"]["id"]})
    assert r.status_code == 200, r.text
    assert r.json()["nombre"] == "Cierre de correctivo · Cliente Demo" and r.json()["tenant_id"] == str(datos["tenant"])
    # Para el otro tenant (sin específico) no hay formulario: su prestador no tiene asignaciones.
    assert (await cliente.get("/api/formularios/resolver", headers=await auth(OTRO_AE), params={"tipo": "atencion_tecnico", "familia_equipo_id": refri})).status_code == 404
    # Un operador del tenant demo resuelve su captura; familia Iluminación no tiene asignación.
    cap = await cliente.get("/api/formularios/resolver", headers=await auth(OP), params={"tipo": "captura_operador", "familia_equipo_id": refri})
    assert cap.json()["nombre"] == "Captura de folio (operador)"
    assert (await cliente.get("/api/formularios/resolver", headers=await auth(OP), params={"tipo": "captura_operador", "familia_equipo_id": familias["Iluminación"]["id"]})).status_code == 404
    # Se agrega una asignación más específica (tipo de equipo) al global: gana sobre familia dentro del mismo alcance.
    h = await auth(AP)
    globales = (await cliente.get("/api/formularios", headers=h, params={"tipo": "atencion_tecnico", "alcance": "global"})).json()
    global_ = next(f for f in globales if f["nombre"] == "Cierre de correctivo (global)")
    nuevo = await crear_formulario(cliente, auth, nombre="Atención cámara", tipo="atencion_tecnico", rol_destino=["tecnico"])
    await publicar(cliente, auth, nuevo["id"])
    a = await cliente.post(f"/api/formularios/{nuevo['id']}/asignaciones", headers=h, json={"tipo_equipo_id": tipos["Cámara de congelación"]["id"], "tipo_folio": "correctivo"})
    assert a.status_code == 201 and a.json()["prioridad"] == 5
    # Tenant demo sigue ganando el específico (8 puntos > 5); para un tenant sin específico ganaría el de tipo de equipo.
    r = await cliente.get("/api/formularios/resolver", headers=await auth(TEC), params={"tipo": "atencion_tecnico", "tenant_id": str(datos["tenant"]), "tipo_equipo_id": tipos["Cámara de congelación"]["id"]})
    assert r.json()["nombre"] == "Cierre de correctivo · Cliente Demo"
    await cliente.delete(f"/api/formularios/asignaciones/{a.json()['id']}", headers=h)
    assert (await cliente.post(f"/api/formularios/{global_['id']}/asignaciones", headers=h, json={"tenant_id": str(datos["otro_tenant"])})).json()["codigo"] == "TENANT_NO_VINCULADO"
    assert (await cliente.post(f"/api/formularios/{nuevo['id']}/asignaciones", headers=await auth(AE), json={})).status_code == 403


async def test_plantillas_y_clonado(cliente, auth, datos):
    plantillas = (await cliente.get("/api/formularios/plantillas", headers=await auth(AP))).json()
    base = {"Cierre de correctivo", "Inspección preventiva", "Instalación de equipo", "Trabajo especial"}
    assert base <= {p["nombre"] for p in plantillas}  # otras pruebas crean plantillas propias
    sembradas = [p for p in plantillas if p["nombre"] in base]
    assert all(p["es_plantilla_base"] and p["prestador_id"] is None and p["estado"] == "publicado" for p in sembradas)
    tipos = {c["tipo"] for p in sembradas for s in p["esquema_json"]["secciones"] for c in s["campos"]}
    assert len(tipos) == 22
    base = next(p for p in plantillas if p["nombre"] == "Inspección preventiva")
    clon = await cliente.post(f"/api/formularios/{base['id']}/clonar", headers=await auth(AP), json={"nombre": "Preventivo Cliente Demo", "tenant_id": str(datos["tenant"])})
    assert clon.status_code == 201, clon.text
    assert clon.json()["clonado_de_id"] == base["id"] and clon.json()["estado"] == "borrador" and clon.json()["prestador_id"] == str(datos["prestador"])
    assert clon.json()["esquema_json"] == base["esquema_json"]
    # El otro prestador no puede clonar un formulario propio del prestador demo, pero sí una plantilla base.
    propios = (await cliente.get("/api/formularios", headers=await auth(AP), params={"alcance": "global", "tipo": "captura_operador"})).json()
    assert (await cliente.post(f"/api/formularios/{propios[0]['id']}/clonar", headers=await auth(OTRO_AP), json={})).status_code == 404
    assert (await cliente.post(f"/api/formularios/{base['id']}/clonar", headers=await auth(OTRO_AP), json={})).status_code == 201
    assert (await cliente.post(f"/api/formularios/{base['id']}/clonar", headers=await auth(AE), json={})).status_code == 403


async def test_aislamiento_entre_prestadores_y_tenants(cliente, auth, datos):
    del_otro = (await cliente.get("/api/formularios", headers=await auth(OTRO_AP))).json()
    assert all(f["es_plantilla_base"] or f["prestador_id"] == str(datos["otro_prestador"]) for f in del_otro)
    mios = (await cliente.get("/api/formularios", headers=await auth(AP), params={"plantillas": "false"})).json()
    assert mios and all(f["prestador_id"] == str(datos["prestador"]) for f in mios)
    especifico = next(f for f in mios if f["tenant_id"] == str(datos["tenant"]))
    assert (await cliente.get(f"/api/formularios/{especifico['id']}", headers=await auth(OTRO_AE))).status_code == 404
    assert (await cliente.get(f"/api/formularios/{especifico['id']}", headers=await auth(AE))).status_code == 200
    # Mis formularios: el técnico ve los de su rol, el operador los suyos, y ninguno ve plantillas.
    tec = (await cliente.get("/api/formularios/mis-formularios", headers=await auth(TEC))).json()
    assert {m["formulario"]["nombre"] for m in tec} >= {"Cierre de correctivo (global)", "Cierre de correctivo · Cliente Demo"}
    assert all(not m["formulario"]["es_plantilla_base"] for m in tec)
    op = (await cliente.get("/api/formularios/mis-formularios", headers=await auth(OP))).json()
    nombres_op = {m["formulario"]["nombre"] for m in op}
    assert "Captura de folio (operador)" in nombres_op and "Cierre de correctivo (global)" not in nombres_op
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        sin_rls = (await db.execute(text("""
            SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = 'public' AND c.relkind = 'r' AND c.relname LIKE 'formulario%' AND NOT (c.relrowsecurity AND c.relforcerowsecurity)"""))).scalars().all()
    assert sin_rls == []


# ------------------------------------------------------ catálogos personalizados

async def test_catalogo_personalizado_y_opciones(cliente, auth, datos):
    h = await auth(AP)
    lista = (await cliente.get("/api/formularios/catalogos-personalizados", headers=h)).json()
    causa = next(c for c in lista if c["clave"] == "causa_raiz")
    assert len(causa["opciones"]) == 6 and causa["tenant_id"] == str(datos["tenant"])
    nuevo = await cliente.post("/api/formularios/catalogos-personalizados", headers=h, json={"nombre": "Zonas", "clave": "zonas", "opciones": [
        {"valor": "norte", "etiqueta": "Norte"}, {"valor": "norte_a", "etiqueta": "Norte A", "padre_valor": "norte"}, {"valor": "sur", "etiqueta": "Sur"}]})
    assert nuevo.status_code == 201, nuevo.text
    por_valor = {o["valor"]: o for o in nuevo.json()["opciones"]}
    assert por_valor["norte_a"]["padre_opcion_id"] == por_valor["norte"]["id"]
    cascada = (await cliente.get("/api/formularios/opciones", headers=await auth(TEC), params={"catalogo": "catalogo_personalizado", "catalogo_personalizado_id": nuevo.json()["id"], "padre": "norte"})).json()
    assert [o["valor"] for o in cascada["opciones"]] == ["norte_a"]
    assert (await cliente.post("/api/formularios/catalogos-personalizados", headers=await auth(AE), json={"nombre": "x", "clave": "x"})).status_code == 403
    assert (await cliente.get("/api/formularios/catalogos-personalizados", headers=await auth(OTRO_AP))).json() == []
    # Catálogos del sistema con contexto y cascada.
    familias = {f["nombre"]: f for f in (await cliente.get("/api/catalogos/familias-equipo", headers=await auth(OP))).json()}
    fallas = (await cliente.get("/api/formularios/opciones", headers=await auth(OP), params={"catalogo": "tipos_falla", "padre": familias["Refrigeración"]["id"]})).json()
    assert {o["etiqueta"] for o in fallas["opciones"]} == {"No enciende", "No enfría", "Ruido inusual"}
    equipos = (await cliente.get("/api/formularios/opciones", headers=await auth(OP), params={"catalogo": "equipos_tenant", "un_id": str(datos["unidades"][0])})).json()
    assert len([o for o in equipos["opciones"] if o["etiqueta"].startswith("EQ-")]) == 4 and all(o["padre"] == str(datos["unidades"][0]) for o in equipos["opciones"])
    materiales = (await cliente.get("/api/formularios/opciones", headers=await auth(TEC), params={"catalogo": "materiales"})).json()
    assert materiales["opciones"] == [] and "P09" in materiales["aviso"]
    assert (await cliente.get("/api/formularios/opciones", headers=await auth(OTRO_AE), params={"catalogo": "equipos_tenant"})).json()["opciones"] == []
