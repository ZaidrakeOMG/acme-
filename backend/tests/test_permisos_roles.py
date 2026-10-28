"""Permisos por rol en cada router (§5) y reglas de negocio de los módulos de P01."""
import uuid
from datetime import date

import pytest

SA = "superadmin@acma.dev"
AP = "admin.prestador@acma.dev"
DIR = "direccion@acma.dev"
MC = "mesa.control@acma.dev"
DES = "despachador@acma.dev"
SUPP = "supervisor.prestador@acma.dev"
TEC = "tecnico1@acma.dev"
AE = "admin.empresa@acma.dev"
AUN = "admin.un@acma.dev"
SUPO = "supervisor.operadores@acma.dev"
OP = "operador@acma.dev"
TODOS = [SA, AP, DIR, MC, DES, SUPP, TEC, AE, AUN, SUPO, OP]

# (método, ruta, roles con acceso). El resto debe recibir 403.
MATRIZ_LECTURA = [
    ("GET", "/api/usuarios", {SA, AP, AE}),
    ("GET", "/api/tenants", {SA, AP, DIR, MC, DES, SUPP, AE}),
    ("GET", "/api/prestadores", {SA, AP}),
    ("GET", "/api/unidades-negocio", set(TODOS)),
    ("GET", "/api/grupos-un", {SA, AP, DIR, MC, DES, SUPP, AE, SUPO}),
    ("GET", "/api/contratos", {SA, AP, DIR, MC, AE}),
    ("GET", "/api/alertas/catalogo", set(TODOS)),
    ("GET", "/api/alertas/historial", {SA, AP, DIR, MC, DES, AE, AUN}),
    ("GET", "/api/configuracion/tenant", {SA, AE}),
    ("GET", "/api/configuracion/prestador", {SA, AP}),
    ("GET", "/api/configuracion/permisos-tecnico", {SA, AP, DES, MC}),
    ("GET", "/api/auditoria/eventos", {SA}),
    ("GET", "/api/auditoria/accesos-api", {SA}),
]

# Parámetros que superadmin necesita para elegir ámbito.
PARAMS_SUPERADMIN = {
    "/api/configuracion/tenant": "tenant",
    "/api/configuracion/prestador": "prestador",
    "/api/configuracion/permisos-tecnico": "prestador",
}


@pytest.mark.parametrize("metodo,ruta,permitidos", MATRIZ_LECTURA, ids=[m[1] for m in MATRIZ_LECTURA])
async def test_matriz_de_lectura_por_rol(cliente, auth, datos, metodo, ruta, permitidos):
    for email in TODOS:
        params = {}
        if email == SA and ruta in PARAMS_SUPERADMIN:
            clave = PARAMS_SUPERADMIN[ruta]
            params = {f"{clave}_id": str(datos[clave])}
        r = await cliente.request(metodo, ruta, headers=await auth(email), params=params)
        esperado = 200 if email in permitidos else 403
        assert r.status_code == esperado, f"{email} {metodo} {ruta}: {r.status_code} {r.text[:200]}"
        if esperado == 403:
            assert r.json()["codigo"] == "PROHIBIDO"


@pytest.mark.parametrize("email", [AE, AP, DES, OP])
async def test_solo_superadmin_crea_tenants(cliente, auth, email):
    r = await cliente.post("/api/tenants", headers=await auth(email), json={"razon_social": "X", "rfc": "XAX010101000"})
    assert r.status_code == 403


async def test_superadmin_crea_tenant_prestador_y_vinculo(cliente, auth):
    h = await auth(SA)
    sufijo = uuid.uuid4().hex[:3].upper()
    t = await cliente.post("/api/tenants", headers=h, json={"razon_social": "Nuevo Cliente", "rfc": f"NCL010101{sufijo}"})
    assert t.status_code == 201 and t.json()["version_hash"] and len(t.json()["version_hash"]) == 64
    p = await cliente.post("/api/prestadores", headers=h, json={
        "razon_social": "Nuevo Prestador", "rfc": f"NPR010101{sufijo}",
        "datos_fiscales": {"regimen_fiscal": "601", "codigo_postal": "06000"}})
    assert p.status_code == 201 and p.json()["datos_fiscales"]["regimen_fiscal"] == "601"
    v = await cliente.post(f"/api/tenants/{t.json()['id']}/prestadores", headers=h, json={"prestador_id": p.json()["id"]})
    assert v.status_code == 201
    # Permisos del nuevo prestador sembrados con los defaults del diseño.
    permisos = (await cliente.get("/api/configuracion/permisos-despachador", headers=h,
                                  params={"prestador_id": p.json()["id"]})).json()
    assert {x["clave"]: x["habilitado"] for x in permisos} == {
        "crear_folios": True, "forzar_severidad": False, "cancelar_folios_autorizados": False,
        "asignar_tecnico_sin_habilidad": False, "ver_costos_folio": True}


async def test_version_hash_cambia_al_modificar(cliente, auth, datos):
    h = await auth(AE)
    antes = (await cliente.get(f"/api/tenants/{datos['tenant']}", headers=h)).json()
    despues = (await cliente.patch(f"/api/tenants/{datos['tenant']}", headers=h, json={"zona_horaria": "America/Monterrey"})).json()
    assert despues["version_hash"] != antes["version_hash"] and despues["updated_at"] > antes["updated_at"]
    await cliente.patch(f"/api/tenants/{datos['tenant']}", headers=h, json={"zona_horaria": "America/Mexico_City"})


async def test_admin_empresa_no_cambia_razon_social(cliente, auth, datos):
    r = await cliente.patch(f"/api/tenants/{datos['tenant']}", headers=await auth(AE), json={"razon_social": "Otra"})
    assert r.status_code == 403


async def test_datos_fiscales_cifrados_en_reposo(datos):
    from sqlalchemy import text

    from core.db import nueva_sesion
    from core.rls import CONTEXTO_SISTEMA

    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        crudo = (await db.execute(text(
            "SELECT datos_fiscales_cifrados FROM prestadores WHERE datos_fiscales_cifrados IS NOT NULL LIMIT 1"))).scalar()
        secreto = (await db.execute(text("SELECT count(*) FROM usuarios WHERE mfa_secreto_cifrado LIKE 'v1:%'"))).scalar()
    assert crudo.startswith("v1:") and "601" not in crudo
    assert secreto >= 1


# ------------------------------------------------------------------ usuarios

async def test_admin_empresa_solo_crea_roles_de_su_tenant(cliente, auth, datos):
    h = await auth(AE)
    r = await cliente.post("/api/usuarios", headers=h, json={
        "email": f"tec.{uuid.uuid4().hex[:6]}@prueba.dev", "nombre": "Técnico", "rol": "tecnico", "contrasena": "Prueba#Segura2026"})
    assert r.status_code == 403
    r = await cliente.post("/api/usuarios", headers=h, json={
        "email": f"op.{uuid.uuid4().hex[:6]}@prueba.dev", "nombre": "Operador", "rol": "operador", "contrasena": "Prueba#Segura2026",
        "tenant_id": str(datos["otro_tenant"])})
    assert r.status_code == 201 and r.json()["tenant_id"] == str(datos["tenant"])  # ignora el tenant ajeno


async def test_admin_prestador_crea_tecnico_en_su_prestador(cliente, auth, datos):
    r = await cliente.post("/api/usuarios", headers=await auth(AP), json={
        "email": f"tec.{uuid.uuid4().hex[:6]}@prueba.dev", "nombre": "Técnico Nuevo", "rol": "tecnico", "contrasena": "Prueba#Segura2026"})
    assert r.status_code == 201 and r.json()["prestador_id"] == str(datos["prestador"]) and r.json()["dominio"] == "prestador"
    r = await cliente.post("/api/usuarios", headers=await auth(AP), json={
        "email": f"sa.{uuid.uuid4().hex[:6]}@prueba.dev", "nombre": "Escalada", "rol": "superadmin", "contrasena": "Prueba#Segura2026"})
    assert r.status_code == 403


async def test_usuario_correo_duplicado_y_politica(cliente, auth):
    h = await auth(AE)
    dup = await cliente.post("/api/usuarios", headers=h, json={
        "email": "OPERADOR@acma.dev", "nombre": "Dup", "rol": "operador", "contrasena": "Prueba#Segura2026"})
    assert dup.status_code == 409 and dup.json()["codigo"] == "EMAIL_DUPLICADO"
    debil = await cliente.post("/api/usuarios", headers=h, json={
        "email": f"d.{uuid.uuid4().hex[:6]}@prueba.dev", "nombre": "Débil", "rol": "operador", "contrasena": "abcdefghijk"})
    assert debil.status_code == 422 and debil.json()["codigo"] == "POLITICA_CONTRASENA"


async def test_no_puede_cambiar_rol_a_otro_dominio_ni_el_propio(cliente, auth):
    h = await auth(AE)
    lista = (await cliente.get("/api/usuarios", headers=h, params={"rol": "operador"})).json()
    r = await cliente.patch(f"/api/usuarios/{lista[0]['id']}", headers=h, json={"rol": "tecnico"})
    assert r.status_code == 403
    yo = (await cliente.get("/api/auth/yo", headers=h)).json()
    assert (await cliente.patch(f"/api/usuarios/{yo['id']}", headers=h, json={"rol": "operador"})).status_code == 403


# ------------------------------------------------------------ UNs y grupos

async def test_crud_unidad_con_ubicacion_y_asignacion(cliente, auth, datos):
    h = await auth(AE)
    codigo = f"T-{uuid.uuid4().hex[:5]}"
    r = await cliente.post("/api/unidades-negocio", headers=h, json={
        "nombre": "Sucursal Prueba", "codigo": codigo, "ubicacion": {"lat": 20.6736, "lng": -103.344}})
    assert r.status_code == 201, r.text
    un = r.json()
    assert un["ubicacion"] == {"lat": pytest.approx(20.6736), "lng": pytest.approx(-103.344)}
    dup = await cliente.post("/api/unidades-negocio", headers=h, json={"nombre": "Dup", "codigo": codigo})
    assert dup.status_code == 409
    operadores = (await cliente.get("/api/usuarios", headers=h, params={"rol": "operador", "q": "olga"})).json()
    asig = await cliente.put(f"/api/unidades-negocio/{un['id']}/usuarios", headers=h, json={"usuario_ids": [operadores[0]["id"]]})
    assert asig.status_code == 200
    tecnico = await cliente.put(f"/api/unidades-negocio/{un['id']}/usuarios", headers=h,
                                json={"usuario_ids": [str(uuid.uuid4())]})
    assert tecnico.status_code == 422
    assert (await cliente.put(f"/api/unidades-negocio/{un['id']}/usuarios", headers=h, json={"usuario_ids": []})).json() == []
    assert (await cliente.post("/api/unidades-negocio", headers=await auth(DES), json={"nombre": "X", "codigo": "X"})).status_code == 403


async def test_grupos_miembros_y_supervisores(cliente, auth, datos):
    h = await auth(AE)
    g = await cliente.post("/api/grupos-un", headers=h, json={"nombre": f"Grupo {uuid.uuid4().hex[:5]}"})
    assert g.status_code == 201
    gid = g.json()["id"]
    m = await cliente.put(f"/api/grupos-un/{gid}/unidades", headers=h, json={"unidad_ids": [str(u) for u in datos["unidades"][:2]]})
    assert set(m.json()["unidad_ids"]) == {str(u) for u in datos["unidades"][:2]}
    ajena = await cliente.put(f"/api/grupos-un/{gid}/unidades", headers=h, json={"unidad_ids": [str(datos["un_otro"])]})
    assert ajena.status_code == 422
    sup = (await cliente.get("/api/usuarios", headers=h, params={"rol": "supervisor_operadores"})).json()
    s = await cliente.put(f"/api/grupos-un/{gid}/supervisores", headers=h, json={"usuario_ids": [sup[0]["id"]]})
    assert s.json()["supervisor_ids"] == [sup[0]["id"]]
    # El supervisor ve solo sus grupos asignados.
    vistos = {x["id"] for x in (await cliente.get("/api/grupos-un", headers=await auth(SUPO))).json()}
    assert gid in vistos
    assert all(x["tenant_id"] == str(datos["tenant"]) for x in (await cliente.get("/api/grupos-un", headers=h)).json())


# ------------------------------------------------------------------ contratos

def _slas(resp=2, resol=8):
    return [{"nivel_severidad": n, "tiempo_respuesta_horas": resp, "tiempo_resolucion_horas": resol, "penalizacion_valor": 5}
            for n in ("muy_baja", "baja", "media", "alta", "critica")]


async def test_contrato_requiere_cinco_severidades_y_rangos(cliente, auth, datos):
    h = await auth(AP)
    base = {"tenant_id": str(datos["tenant"]), "nombre": "Contrato prueba", "fecha_inicio": "2026-01-01", "fecha_fin": "2026-12-31"}
    assert (await cliente.post("/api/contratos", headers=h, json={**base, "slas": _slas()[:4]})).status_code == 422
    assert (await cliente.post("/api/contratos", headers=h, json={**base, "slas": _slas(resp=0)})).status_code == 422
    assert (await cliente.post("/api/contratos", headers=h, json={**base, "slas": _slas(resol=4321)})).status_code == 422
    ok = await cliente.post("/api/contratos", headers=h, json={**base, "slas": _slas(resp=1, resol=4320)})
    assert ok.status_code == 201 and len(ok.json()["slas"]) == 5
    cid = ok.json()["id"]
    cambio = await cliente.patch(f"/api/contratos/{cid}", headers=h, json={"slas": _slas(resp=3, resol=10)})
    assert {s["tiempo_respuesta_horas"] for s in cambio.json()["slas"]} == {3}
    # El tenant lo ve pero no lo modifica; otro prestador ni lo ve.
    assert (await cliente.get(f"/api/contratos/{cid}", headers=await auth(AE))).status_code == 200
    assert (await cliente.patch(f"/api/contratos/{cid}", headers=await auth(AE), json={"nombre": "x"})).status_code == 403
    assert (await cliente.get(f"/api/contratos/{cid}", headers=await auth("admin.otroprestador@acma.dev"))).status_code == 404


async def test_contrato_con_tenant_no_vinculado(cliente, auth, datos):
    r = await cliente.post("/api/contratos", headers=await auth(AP), json={
        "tenant_id": str(datos["otro_tenant"]), "nombre": "Indebido", "fecha_inicio": str(date(2026, 1, 1)),
        "fecha_fin": str(date(2026, 6, 30)), "slas": _slas()})
    assert r.status_code == 422 and r.json()["codigo"] == "TENANT_NO_VINCULADO"


# -------------------------------------------------------------------- alertas

async def test_catalogo_tiene_los_20_tipos_mas_los_de_cada_modulo(cliente, auth):
    catalogo = (await cliente.get("/api/alertas/catalogo", headers=await auth(OP))).json()
    assert len(catalogo) == 28  # 20 del diseño + MATRIZ_SEVERIDAD_INCOMPLETA (P02) + GEOLOCALIZACION_FUERA_DE_UN (P03) + 3 de P04 + 3 de P06
    assert {"SLA_RESPUESTA_EN_RIESGO", "COTIZACION_ESCALADA_DIRECCION", "TECNICO_SIN_SENAL"} <= {a["clave"] for a in catalogo}


async def test_umbral_por_tenant_dentro_de_rango(cliente, auth, datos):
    h = await auth(AE)
    fuera = await cliente.put("/api/alertas/configuracion/PRESUPUESTO_ALERTA_1", headers=h, json={"umbral_valor": 5})
    assert fuera.status_code == 422 and fuera.json()["codigo"] == "UMBRAL_FUERA_DE_RANGO"
    ok = await cliente.put("/api/alertas/configuracion/PRESUPUESTO_ALERTA_1", headers=h, json={"umbral_valor": 75, "canales": ["email"]})
    assert ok.status_code == 200 and float(ok.json()["umbral_valor"]) == 75 and ok.json()["personalizada"]
    # El otro tenant conserva el default.
    otro = (await cliente.get("/api/alertas/configuracion", headers=await auth("admin.otro@acma.dev"))).json()
    assert float(next(a for a in otro if a["clave"] == "PRESUPUESTO_ALERTA_1")["umbral_valor"]) == 70
    rest = await cliente.delete("/api/alertas/configuracion/PRESUPUESTO_ALERTA_1", headers=h)
    assert float(rest.json()["umbral_valor"]) == 70 and not rest.json()["personalizada"]


async def test_solo_superadmin_modifica_default_del_catalogo(cliente, auth):
    assert (await cliente.patch("/api/alertas/catalogo/STOCK_MINIMO", headers=await auth(AP), json={"umbral_max": 5})).status_code == 403
    malo = await cliente.patch("/api/alertas/catalogo/STOCK_MINIMO", headers=await auth(SA), json={"umbral_min": 10, "umbral_max": 5})
    assert malo.status_code == 422
    ok = await cliente.patch("/api/alertas/catalogo/STOCK_MINIMO", headers=await auth(SA), json={"umbral_max": 500})
    assert float(ok.json()["umbral_max"]) == 500


# -------------------------------------------------------------- configuración

async def test_configuracion_clave_valor_y_permisos(cliente, auth, datos):
    h = await auth(AP)
    r = await cliente.put("/api/configuracion/prestador/minuta.requiere_validacion", headers=h, json={"valor": True})
    assert r.status_code == 200 and r.json()["valor"] is True
    assert (await cliente.put("/api/configuracion/prestador/Clave Invalida", headers=h, json={"valor": 1})).status_code == 422
    permisos = await cliente.put("/api/configuracion/permisos-tecnico", headers=h, json={"valores": {"ver_costo_refacciones": True}})
    assert next(p for p in permisos.json() if p["clave"] == "ver_costo_refacciones")["habilitado"] is True
    malo = await cliente.put("/api/configuracion/permisos-tecnico", headers=h, json={"valores": {"inventado": True}})
    assert malo.status_code == 422
    # Permiso por despachador y cliente (§6.8.3b).
    desp = (await cliente.get("/api/usuarios", headers=h, params={"rol": "despachador", "q": "daniel"})).json()[0]
    especifico = await cliente.put("/api/configuracion/permisos-despachador", headers=h, json={
        "despachador_id": desp["id"], "tenant_id": str(datos["tenant"]), "valores": {"forzar_severidad": True}})
    assert next(p for p in especifico.json() if p["clave"] == "forzar_severidad")["habilitado"] is True
    propios = (await cliente.get("/api/configuracion/permisos-despachador", headers=await auth(DES),
                                 params={"tenant_id": str(datos["tenant"])})).json()
    assert next(p for p in propios if p["clave"] == "forzar_severidad")["habilitado"] is True
    base = (await cliente.get("/api/configuracion/permisos-despachador", headers=h)).json()
    assert next(p for p in base if p["clave"] == "forzar_severidad")["habilitado"] is False


async def test_logo_de_prestador(cliente, auth, datos):
    h = await auth(AP)
    r = await cliente.post(f"/api/prestadores/{datos['prestador']}/logo", headers=h,
                           files={"archivo": ("logo.png", b"\x89PNG\r\n\x1a\nfalso", "image/png")})
    assert r.status_code == 200 and r.json()["logo_key"].startswith(f"prestadores/{datos['prestador']}/logo-")
    malo = await cliente.post(f"/api/prestadores/{datos['prestador']}/logo", headers=h,
                              files={"archivo": ("logo.exe", b"MZ", "application/octet-stream")})
    assert malo.status_code == 422
    ajeno = await cliente.post(f"/api/prestadores/{datos['otro_prestador']}/logo", headers=h,
                               files={"archivo": ("logo.png", b"x", "image/png")})
    assert ajeno.status_code == 404
