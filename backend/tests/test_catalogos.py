"""Catálogos maestros (P02): CRUD por rol, aislamiento, técnicos y permisos, equipos y contrato activo."""
import uuid
from datetime import date

import pytest
from sqlalchemy import select, text

from core.db import nueva_sesion
from core.rls import CONTEXTO_SISTEMA, ContextoRLS
from models import Contrato, Equipo, TipoEquipo, UnidadNegocio
from services import catalogos_service

SA, AP, AE, AUN, OP, DES, MC, TEC = ("superadmin@acma.dev", "admin.prestador@acma.dev", "admin.empresa@acma.dev", "admin.un@acma.dev",
                                     "operador@acma.dev", "despachador@acma.dev", "mesa.control@acma.dev", "tecnico1@acma.dev")
OTRO_AE, OTRO_AP = "admin.otro@acma.dev", "admin.otroprestador@acma.dev"
NUEVA = "Prueba#Segura2026"


# ---------------------------------------------------------------- habilidades

async def test_habilidades_crud_y_aislamiento(cliente, auth, datos):
    h = await auth(AP)
    lista = (await cliente.get("/api/catalogos/habilidades", headers=h)).json()
    assert {x["clave"] for x in lista} >= {"refrigeracion", "electricidad", "hvac", "plomeria", "iluminacion"}
    r = await cliente.post("/api/catalogos/habilidades", headers=h, json={"clave": "soldadura", "nombre": "Soldadura"})
    assert r.status_code == 201
    dup = await cliente.post("/api/catalogos/habilidades", headers=h, json={"clave": "soldadura", "nombre": "Otra"})
    assert dup.status_code == 409
    mod = await cliente.patch(f"/api/catalogos/habilidades/{r.json()['id']}", headers=h, json={"activa": False})
    assert mod.json()["activa"] is False
    assert (await cliente.post("/api/catalogos/habilidades", headers=await auth(AE), json={"clave": "x_y", "nombre": "X"})).status_code == 403
    otro = (await cliente.get("/api/catalogos/habilidades", headers=await auth(OTRO_AP))).json()
    assert otro == []
    assert (await cliente.patch(f"/api/catalogos/habilidades/{r.json()['id']}", headers=await auth(OTRO_AP), json={"nombre": "Otra"})).status_code == 404


# ------------------------------------------------------------------- técnicos

async def test_tecnicos_listado_busqueda_y_filtro_por_habilidad(cliente, auth, datos):
    h = await auth(AP)
    todos = (await cliente.get("/api/catalogos/tecnicos", headers=h)).json()
    assert len(todos) >= 4 and all(t["email"].startswith("tecnico") for t in todos)
    assert all(t["nombre"] and t["numero_empleado"] for t in todos)
    busqueda = (await cliente.get("/api/catalogos/tecnicos", headers=h, params={"q": "tan"})).json()
    assert [t["nombre"] for t in busqueda] == ["Tania Técnica"]
    plomeria = next(x for x in (await cliente.get("/api/catalogos/habilidades", headers=h)).json() if x["clave"] == "plomeria")
    con = (await cliente.get("/api/catalogos/tecnicos", headers=h, params={"habilidad_id": plomeria["id"]})).json()
    assert [t["nombre"] for t in con] == ["Tadeo Técnico"]
    # F2-01: el seed deja a este tecnico con la certificacion de electricidad **vencida**, asi que se mira la
    # habilidad por la que se filtro y no la primera de la lista; la vencida sigue visible, marcada como no vigente.
    fila = next(x for x in con[0]["habilidades"] if x["habilidad_id"] == plomeria["id"])
    assert fila["vigente"] is True
    assert any(x["vigente"] is False for x in con[0]["habilidades"])
    # Lectura para mesa de control y despachador; nada para el tenant ni para otro prestador.
    assert (await cliente.get("/api/catalogos/tecnicos", headers=await auth(MC))).status_code == 200
    assert (await cliente.get("/api/catalogos/tecnicos", headers=await auth(DES))).status_code == 200
    assert (await cliente.get("/api/catalogos/tecnicos", headers=await auth(AE))).status_code == 403
    assert (await cliente.get("/api/catalogos/tecnicos", headers=await auth(OTRO_AP))).json() == []


async def test_crear_tecnico_con_usuario_nuevo_y_vinculado(cliente, auth, datos):
    h = await auth(AP)
    email = f"tec.{uuid.uuid4().hex[:6]}@prueba.dev"
    r = await cliente.post("/api/catalogos/tecnicos", headers=h, json={"email": email, "nombre": "Técnico Nuevo", "contrasena": NUEVA,
                                                                       "numero_empleado": "T-900", "fecha_ingreso": "2026-02-01"})
    assert r.status_code == 201, r.text
    assert r.json()["email"] == email and r.json()["habilidades"] == []
    assert (await cliente.post("/api/catalogos/tecnicos", headers=h, json={"email": email, "nombre": "Dup", "contrasena": NUEVA})).json()["codigo"] == "EMAIL_DUPLICADO"
    assert (await cliente.post("/api/catalogos/tecnicos", headers=h, json={"usuario_id": r.json()["usuario_id"]})).json()["codigo"] == "TECNICO_DUPLICADO"
    # Un usuario técnico creado por el router de usuarios se puede vincular después.
    u = await cliente.post("/api/usuarios", headers=h, json={"email": f"v.{uuid.uuid4().hex[:6]}@prueba.dev", "nombre": "Vinculado",
                                                              "rol": "tecnico", "contrasena": NUEVA})
    v = await cliente.post("/api/catalogos/tecnicos", headers=h, json={"usuario_id": u.json()["id"], "numero_empleado": "T-901"})
    assert v.status_code == 201 and v.json()["nombre"] == "Vinculado"
    # Usuario con otro rol o de otro prestador: 422.
    desp = (await cliente.get("/api/usuarios", headers=h, params={"rol": "despachador"})).json()[0]
    assert (await cliente.post("/api/catalogos/tecnicos", headers=h, json={"usuario_id": desp["id"]})).status_code == 422
    assert (await cliente.post("/api/catalogos/tecnicos", headers=h, json={"email": "x@p.dev", "nombre": "Débil", "contrasena": "corta"})).status_code == 422
    # El técnico nuevo puede iniciar sesión.
    assert (await cliente.post("/api/auth/login", json={"email": email, "contrasena": NUEVA})).status_code == 200


async def test_habilidades_tenants_y_grupo_del_tecnico(cliente, auth, datos):
    h = await auth(AP)
    tec = (await cliente.get("/api/catalogos/tecnicos", headers=h, params={"q": "tomás"})).json()[0]
    habs = {x["clave"]: x["id"] for x in (await cliente.get("/api/catalogos/habilidades", headers=h)).json()}
    r = await cliente.put(f"/api/catalogos/tecnicos/{tec['id']}/habilidades", headers=h, json={"habilidades": [
        {"habilidad_id": habs["plomeria"], "certificada": True, "fecha_certificacion": "2026-01-01", "vigencia_hasta": "2026-06-01"},
        {"habilidad_id": habs["hvac"], "certificada": False}]})
    assert r.status_code == 200, r.text
    por_clave = {x["clave"]: x for x in r.json()["habilidades"]}
    assert set(por_clave) == {"plomeria", "hvac"}
    assert por_clave["plomeria"]["vigente"] is (date.today() <= date(2026, 6, 1)) and por_clave["hvac"]["vigente"] is False
    assert (await cliente.put(f"/api/catalogos/tecnicos/{tec['id']}/habilidades", headers=h,
                              json={"habilidades": [{"habilidad_id": str(uuid.uuid4())}]})).status_code == 422
    assert (await cliente.put(f"/api/catalogos/tecnicos/{tec['id']}/habilidades", headers=h, json={"habilidades": [
        {"habilidad_id": habs["hvac"], "fecha_certificacion": "2026-05-01", "vigencia_hasta": "2026-01-01"}]})).status_code == 422

    # §6.10.8 tenants habilitados: solo vinculados al prestador.
    t = await cliente.put(f"/api/catalogos/tecnicos/{tec['id']}/tenants", headers=h, json={"tenant_ids": [str(datos["tenant"])]})
    assert t.json()["tenants_habilitados"] == [str(datos["tenant"])]
    assert (await cliente.put(f"/api/catalogos/tecnicos/{tec['id']}/tenants", headers=h,
                              json={"tenant_ids": [str(datos["otro_tenant"])]})).json()["codigo"] == "TENANT_NO_VINCULADO"
    assert (await cliente.put(f"/api/catalogos/tecnicos/{tec['id']}/tenants", headers=h, json={"tenant_ids": []})).json()["tenants_habilitados"] == []

    # Otro prestador no ve ni edita la ficha.
    assert (await cliente.get(f"/api/catalogos/tecnicos/{tec['id']}", headers=await auth(OTRO_AP))).status_code == 404
    assert (await cliente.patch(f"/api/catalogos/tecnicos/{tec['id']}", headers=await auth(OTRO_AP), json={"estado": "baja"})).status_code == 404
    baja = await cliente.patch(f"/api/catalogos/tecnicos/{tec['id']}", headers=h, json={"estado": "inactivo", "vehiculo_placas": None})
    assert baja.json()["estado"] == "inactivo" and baja.json()["vehiculo_placas"] is None
    await cliente.patch(f"/api/catalogos/tecnicos/{tec['id']}", headers=h, json={"estado": "activo"})


async def test_permisos_efectivos_grupo_y_override(cliente, auth, datos):
    h = await auth(AP)
    tec = (await cliente.get("/api/catalogos/tecnicos", headers=h, params={"q": "teresa"})).json()[0]
    base = {p["clave"]: p for p in (await cliente.get(f"/api/catalogos/tecnicos/{tec['id']}/permisos-efectivos", headers=h)).json()}
    assert base["ejecutar_trabajos_especiales"]["habilitado"] is False and base["ejecutar_trabajos_especiales"]["origen"] in ("prestador", "catalogo")

    g = await cliente.post("/api/catalogos/grupos-tecnicos", headers=h, json={"nombre": f"Senior {uuid.uuid4().hex[:4]}", "descripcion": "Nivel senior"})
    assert g.status_code == 201
    gp = await cliente.put(f"/api/catalogos/grupos-tecnicos/{g.json()['id']}/permisos", headers=h,
                           json={"valores": {"ejecutar_trabajos_especiales": True, "ver_costo_refacciones": True}})
    assert gp.json()["permisos"] == {"ejecutar_trabajos_especiales": True, "ver_costo_refacciones": True}
    assert (await cliente.put(f"/api/catalogos/grupos-tecnicos/{g.json()['id']}/permisos", headers=h, json={"valores": {"inventado": True}})).status_code == 422

    asig = await cliente.put(f"/api/catalogos/tecnicos/{tec['id']}/grupo", headers=h, json={"grupo_id": g.json()["id"]})
    assert asig.json()["grupo_id"] == g.json()["id"]
    con_grupo = {p["clave"]: p for p in (await cliente.get(f"/api/catalogos/tecnicos/{tec['id']}/permisos-efectivos", headers=h)).json()}
    assert con_grupo["ejecutar_trabajos_especiales"] == {**con_grupo["ejecutar_trabajos_especiales"], "habilitado": True, "origen": "grupo"}

    ov = await cliente.put(f"/api/catalogos/tecnicos/{tec['id']}/permisos", headers=h, json={"overrides": [
        {"permiso_clave": "ejecutar_trabajos_especiales", "habilitado": False, "razon": "Restricción temporal"},
        {"permiso_clave": "crear_folio_en_campo", "habilitado": True, "razon": "Cliente lo pidió"}]})
    assert ov.status_code == 200, ov.text
    efectivos = {p["clave"]: p for p in ov.json()}
    assert efectivos["ejecutar_trabajos_especiales"]["habilitado"] is False and efectivos["ejecutar_trabajos_especiales"]["origen"] == "override"
    assert efectivos["ejecutar_trabajos_especiales"]["razon"] == "Restricción temporal"
    assert efectivos["crear_folio_en_campo"]["habilitado"] is True and efectivos["ver_costo_refacciones"]["origen"] == "grupo"
    # Quitar el override devuelve el valor del grupo.
    quitar = await cliente.put(f"/api/catalogos/tecnicos/{tec['id']}/permisos", headers=h,
                               json={"overrides": [{"permiso_clave": "ejecutar_trabajos_especiales", "habilitado": None}]})
    assert next(p for p in quitar.json() if p["clave"] == "ejecutar_trabajos_especiales")["origen"] == "grupo"
    sin_grupo = await cliente.put(f"/api/catalogos/tecnicos/{tec['id']}/grupo", headers=h, json={"grupo_id": None})
    assert sin_grupo.json()["grupo_id"] is None
    # Despachador lee permisos efectivos; otro prestador no.
    assert (await cliente.get(f"/api/catalogos/tecnicos/{tec['id']}/permisos-efectivos", headers=await auth(DES))).status_code == 200
    assert (await cliente.get(f"/api/catalogos/tecnicos/{tec['id']}/permisos-efectivos", headers=await auth(OTRO_AP))).status_code == 404


# ---------------------------------------------------------------- severidades

async def test_severidades_cinco_niveles_por_prestador(cliente, auth, datos):
    h = await auth(AP)
    niveles = (await cliente.get("/api/catalogos/severidades", headers=h)).json()
    assert [n["clave"] for n in niveles] == ["muy_baja", "baja", "media", "alta", "critica"]
    assert [n["orden"] for n in niveles] == [1, 2, 3, 4, 5]
    # El tenant ve los niveles de su prestador; el otro prestador tiene los suyos propios.
    del_tenant = (await cliente.get("/api/catalogos/severidades", headers=await auth(AE))).json()
    assert {n["id"] for n in del_tenant} == {n["id"] for n in niveles}
    otros = (await cliente.get("/api/catalogos/severidades", headers=await auth(OTRO_AP))).json()
    assert len(otros) == 5 and {n["id"] for n in otros}.isdisjoint({n["id"] for n in niveles})
    critica = niveles[-1]
    mod = await cliente.patch(f"/api/catalogos/severidades/{critica['id']}", headers=h, json={"nombre": "Crítica (24/7)", "color_hex": "#B71C1C"})
    assert mod.json()["nombre"] == "Crítica (24/7)" and mod.json()["color_hex"] == "#B71C1C"
    assert (await cliente.patch(f"/api/catalogos/severidades/{critica['id']}", headers=h, json={"tiempo_resolucion_horas": 1})).json()["codigo"] == "TIEMPOS_INVALIDOS"
    assert (await cliente.patch(f"/api/catalogos/severidades/{critica['id']}", headers=await auth(AE), json={"nombre": "x"})).status_code == 403
    assert (await cliente.patch(f"/api/catalogos/severidades/{critica['id']}", headers=await auth(OTRO_AP), json={"nombre": "Otra"})).status_code == 404
    # contrato_sla quedó enlazado a los niveles en la migración.
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        sin_enlace = (await db.execute(text("SELECT count(*) FROM contrato_sla WHERE nivel_severidad_id IS NULL"))).scalar()
    assert sin_enlace == 0


# --------------------------------------------------- familias y tipos (cascada)

async def test_familias_globales_y_propias(cliente, auth, datos):
    globales = (await cliente.get("/api/catalogos/familias-equipo", headers=await auth(AE))).json()
    # Las tres del seed de P02 más «Equipos industriales», que F2-04 agregó para los equipos con medidor (§6.9.2).
    assert {f["nombre"] for f in globales if f["es_global"]} == {"Refrigeración", "Climatización", "Iluminación",
                                                                 "Equipos industriales"}
    assert (await cliente.post("/api/catalogos/familias-equipo", headers=await auth(AE), json={"nombre": "Global X", "global": True})).status_code == 403
    nombre = f"Cocina {uuid.uuid4().hex[:4]}"
    propia = await cliente.post("/api/catalogos/familias-equipo", headers=await auth(AE), json={"nombre": nombre})
    assert propia.status_code == 201 and propia.json()["es_global"] is False and propia.json()["tenant_id"] == str(datos["tenant"])
    assert (await cliente.post("/api/catalogos/familias-equipo", headers=await auth(AE), json={"nombre": nombre.lower()})).status_code == 409
    # El otro tenant no la ve; el superadmin sí con tenant_id.
    assert nombre not in {f["nombre"] for f in (await cliente.get("/api/catalogos/familias-equipo", headers=await auth(OTRO_AE))).json()}
    assert nombre in {f["nombre"] for f in (await cliente.get("/api/catalogos/familias-equipo", headers=await auth(SA),
                                                              params={"tenant_id": str(datos["tenant"])})).json()}
    refri = next(f for f in globales if f["nombre"] == "Refrigeración")
    assert (await cliente.patch(f"/api/catalogos/familias-equipo/{refri['id']}", headers=await auth(AE), json={"descripcion": "x"})).status_code == 403
    assert (await cliente.patch(f"/api/catalogos/familias-equipo/{refri['id']}", headers=await auth(SA), json={"descripcion": "Frío"})).json()["descripcion"] == "Frío"
    assert (await cliente.patch(f"/api/catalogos/familias-equipo/{propia.json()['id']}", headers=await auth(OTRO_AE), json={"nombre": "Otra"})).status_code == 404
    # Tipo propio dentro de una familia global, y cascada por familia.
    tipo = await cliente.post("/api/catalogos/tipos-equipo", headers=await auth(AE), json={"familia_id": refri["id"], "nombre": f"Vitrina {uuid.uuid4().hex[:4]}"})
    assert tipo.status_code == 201 and tipo.json()["es_global"] is False
    de_refri = (await cliente.get("/api/catalogos/tipos-equipo", headers=await auth(AE), params={"familia_id": refri["id"]})).json()
    assert all(t["familia_id"] == refri["id"] for t in de_refri) and tipo.json()["id"] in {t["id"] for t in de_refri}
    assert tipo.json()["id"] not in {t["id"] for t in (await cliente.get("/api/catalogos/tipos-equipo", headers=await auth(OTRO_AE))).json()}
    assert (await cliente.post("/api/catalogos/tipos-equipo", headers=await auth(AE), json={"familia_id": str(uuid.uuid4()), "nombre": "X"})).status_code == 422
    assert (await cliente.get("/api/catalogos/tipos-equipo", headers=await auth(TEC))).status_code == 200


# -------------------------------------------------------------------- equipos

async def test_equipos_visibilidad_por_rol_y_filtro_de_contrato(cliente, auth, datos):
    def seed(lista):  # solo los 12 del seed (otras pruebas crean equipos EQ-P…/EQ-U…/EQ-I…)
        return [e for e in lista if e["codigo"].startswith("EQ-0")]

    async def listar(email, **params):
        return seed((await cliente.get("/api/catalogos/equipos", headers=await auth(email), params=params)).json())

    todos = await listar(AE)
    assert len(todos) == 12 and all(e["familia_id"] for e in todos)
    sin = {e["codigo"] for e in todos if not e["con_contrato_activo"]}
    assert sin == {"EQ-0002", "EQ-0006"}
    assert {e["codigo"] for e in todos if e["en_garantia"]} == {"EQ-0009"}
    con = await listar(AE, con_contrato="true")
    assert len(con) == 10 and all(e["con_contrato_activo"] for e in con)
    assert len(await listar(AE, un_id=str(datos["unidades"][0]))) == 4
    assert len(await listar(AUN)) == 8  # UNs 1 y 2
    assert len(await listar(OP)) == 4  # UN 1
    assert len(await listar(DES)) == 12  # clientes del prestador
    assert (await cliente.get("/api/catalogos/equipos", headers=await auth(OTRO_AE))).json() == []
    assert (await cliente.get("/api/catalogos/equipos", headers=await auth(OTRO_AP))).json() == []
    busq = (await cliente.get("/api/catalogos/equipos", headers=await auth(AE), params={"q": "sn000003"})).json()
    assert [e["codigo"] for e in busq] == ["EQ-0003"]
    assert (await cliente.get(f"/api/catalogos/equipos/{todos[0]['id']}", headers=await auth(OTRO_AE))).status_code == 404


async def test_equipos_alta_y_validaciones(cliente, auth, datos):
    h = await auth(AE)
    tipos = (await cliente.get("/api/catalogos/tipos-equipo", headers=h)).json()
    minisplit = next(t for t in tipos if t["nombre"] == "Minisplit")
    base = {"un_id": str(datos["unidades"][2]), "tipo_equipo_id": minisplit["id"], "nombre": "Minisplit oficina"}
    codigo = f"EQ-P{uuid.uuid4().hex[:5]}"
    r = await cliente.post("/api/catalogos/equipos", headers=h, json={**base, "codigo": codigo, "garantia_vigente_hasta": "2030-01-01"})
    assert r.status_code == 201, r.text
    assert r.json()["con_contrato_activo"] is True and r.json()["en_garantia"] is True
    assert (await cliente.post("/api/catalogos/equipos", headers=h, json={**base, "codigo": codigo})).status_code == 409
    assert (await cliente.post("/api/catalogos/equipos", headers=h, json={**base, "codigo": "X1", "un_id": str(datos["un_otro"])})).json()["codigo"] == "UNIDAD_INVALIDA"
    assert (await cliente.post("/api/catalogos/equipos", headers=h, json={**base, "codigo": "X2", "tipo_equipo_id": str(uuid.uuid4())})).json()["codigo"] == "TIPO_EQUIPO_INVALIDO"
    # admin_un solo en sus UNs (1 y 2): la UN 3 no la administra.
    assert (await cliente.post("/api/catalogos/equipos", headers=await auth(AUN), json={**base, "codigo": "X3"})).json()["codigo"] == "UNIDAD_INVALIDA"
    ok_un = await cliente.post("/api/catalogos/equipos", headers=await auth(AUN), json={**base, "codigo": f"EQ-U{uuid.uuid4().hex[:5]}", "un_id": str(datos["unidades"][1])})
    assert ok_un.status_code == 201
    assert (await cliente.post("/api/catalogos/equipos", headers=await auth(OP), json={**base, "codigo": "X4"})).status_code == 403
    assert (await cliente.post("/api/catalogos/equipos", headers=await auth(AP), json={**base, "codigo": "X5"})).status_code == 403
    mod = await cliente.patch(f"/api/catalogos/equipos/{r.json()['id']}", headers=h, json={"estado": "baja", "garantia_vigente_hasta": None})
    assert mod.json()["estado"] == "baja" and mod.json()["en_garantia"] is False
    assert r.json()["id"] not in {e["id"] for e in (await cliente.get("/api/catalogos/equipos", headers=h)).json()}  # solo_activos


async def test_funcion_contrato_activo_cuatro_casos(datos):
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        por_codigo = {e.codigo: e for e in (await db.execute(select(Equipo).where(Equipo.tenant_id == datos["tenant"]))).scalars()}
        # 1. contrato_id NULL + contrato vigente del tenant con cobertura de todas las UN.
        assert await catalogos_service.equipo_con_contrato_activo(db, por_codigo["EQ-0001"].id) is True
        # 2. contrato propio vencido.
        assert await catalogos_service.equipo_con_contrato_activo(db, por_codigo["EQ-0002"].id) is False
        # 3. contrato propio vigente.
        vigente = (await db.execute(select(Contrato).where(Contrato.tenant_id == datos["tenant"], Contrato.fecha_fin >= date.today()))).scalars().first()
        por_codigo["EQ-0002"].contrato_id = vigente.id
        await db.flush()
        assert await catalogos_service.equipo_con_contrato_activo(db, por_codigo["EQ-0002"].id) is True
        await db.rollback()
        # 4. tenant sin ningún contrato vigente.
        tipo = (await db.execute(select(TipoEquipo).where(TipoEquipo.tenant_id.is_(None)))).scalars().first()
        un = await db.get(UnidadNegocio, datos["un_otro"])
        e = Equipo(tenant_id=datos["otro_tenant"], un_id=un.id, tipo_equipo_id=tipo.id, codigo="OTRO-1", nombre="Sin contrato")
        db.add(e)
        await db.flush()
        assert await catalogos_service.equipo_con_contrato_activo(db, e.id) is False
        await db.rollback()


# ---------------------------------------------------------------- tipos de falla

async def test_tipos_falla_y_flag_global(cliente, auth, datos):
    h = await auth(AP)
    familias = {f["nombre"]: f for f in (await cliente.get("/api/catalogos/familias-equipo", headers=h)).json()}
    lista = (await cliente.get("/api/catalogos/tipos-falla", headers=h)).json()
    assert len(lista) == 8
    de_refri = (await cliente.get("/api/catalogos/tipos-falla", headers=h, params={"familia_id": familias["Refrigeración"]["id"]})).json()
    assert {t["descripcion"] for t in de_refri} == {"No enciende", "No enfría", "Ruido inusual"}
    r = await cliente.post("/api/catalogos/tipos-falla", headers=h, json={"descripcion": "Fuga de gas", "familia_equipo_id": familias["Refrigeración"]["id"]})
    assert r.status_code == 201 and r.json()["requiere_revision_manual"] is False
    assert (await cliente.post("/api/catalogos/tipos-falla", headers=h, json={"descripcion": "fuga de gas", "familia_equipo_id": familias["Refrigeración"]["id"]})).status_code == 409
    flag = await cliente.post("/api/catalogos/tipos-falla", headers=h, json={"descripcion": "Incendio", "familia_equipo_id": familias["Refrigeración"]["id"],
                                                                             "requiere_revision_manual": True})
    assert flag.status_code == 403
    assert (await cliente.patch(f"/api/catalogos/tipos-falla/{r.json()['id']}", headers=h, json={"requiere_revision_manual": True})).status_code == 403
    sa = await cliente.patch(f"/api/catalogos/tipos-falla/{r.json()['id']}", headers=await auth(SA), json={"requiere_revision_manual": True})
    assert sa.status_code == 200 and sa.json()["requiere_revision_manual"] is True
    # El trigger de BD también bloquea el cambio aunque se salte el servicio.
    async with nueva_sesion(ContextoRLS(prestador_id=datos["prestador"], rol="admin_prestador")) as db:
        with pytest.raises(Exception, match="requiere_revision_manual"):
            await db.execute(text("UPDATE tipos_falla SET requiere_revision_manual = false WHERE id = :i"), {"i": r.json()["id"]})
    # Lectura: tenant ve los de sus prestadores; otro prestador no ve estos.
    assert len((await cliente.get("/api/catalogos/tipos-falla", headers=await auth(OP))).json()) == 9
    assert (await cliente.get("/api/catalogos/tipos-falla", headers=await auth(OTRO_AP))).json() == []
    assert (await cliente.post("/api/catalogos/tipos-falla", headers=await auth(AE), json={"descripcion": "x", "familia_equipo_id": familias["Refrigeración"]["id"]})).status_code == 403
    # Se desactiva para no dejar combinaciones sin severidad en la matriz del tenant demo.
    assert (await cliente.patch(f"/api/catalogos/tipos-falla/{r.json()['id']}", headers=h, json={"activa": False})).json()["activa"] is False
