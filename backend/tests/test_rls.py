"""Aislamiento multitenant: RLS fail-closed directamente en PostgreSQL y a través de la API."""
import os

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from core.db import nueva_sesion
from core.rls import ContextoRLS
from models import Contrato, Tenant, UnidadNegocio, Usuario

TABLAS_CON_DUENIO_SQL = """
SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p') AND NOT c.relispartition
   AND EXISTS (SELECT 1 FROM pg_attribute a WHERE a.attrelid = c.oid AND a.attname IN ('tenant_id', 'prestador_id')
               AND NOT a.attisdropped)
"""


async def _contar(contexto: ContextoRLS, modelo) -> int:
    async with nueva_sesion(contexto) as db:
        return len((await db.execute(select(modelo))).scalars().all())


async def test_rol_de_aplicacion_sin_privilegios_especiales(datos):
    async with nueva_sesion(ContextoRLS()) as db:
        fila = (await db.execute(text(
            "SELECT current_user, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"))).one()
        assert fila.current_user == "acma_api" and not fila.rolsuper and not fila.rolbypassrls
        propias = (await db.execute(text(
            "SELECT count(*) FROM pg_tables WHERE schemaname = 'public' AND tableowner = current_user"))).scalar()
        assert propias == 0


async def test_toda_tabla_con_tenant_o_prestador_tiene_rls_forzada(datos):
    async with nueva_sesion(ContextoRLS()) as db:
        filas = (await db.execute(text(TABLAS_CON_DUENIO_SQL))).all()
    assert len(filas) >= 20
    sin_rls = [f.relname for f in filas if not (f.relrowsecurity and f.relforcerowsecurity)]
    assert sin_rls == []


@pytest.mark.parametrize("modelo", [UnidadNegocio, Usuario, Tenant, Contrato])
async def test_contexto_vacio_devuelve_cero_filas(datos, modelo):
    assert await _contar(ContextoRLS(), modelo) == 0


async def test_contexto_con_rol_pero_sin_tenant_devuelve_cero(datos):
    # Un rol de tenant sin tenant_id no debe ver nada (no hay política "por ausencia de contexto").
    assert await _contar(ContextoRLS(rol="admin_empresa"), UnidadNegocio) == 0


async def test_tenant_solo_ve_sus_unidades(datos):
    ctx_a = ContextoRLS(tenant_id=datos["tenant"], rol="admin_empresa")
    ctx_b = ContextoRLS(tenant_id=datos["otro_tenant"], rol="admin_empresa")
    async with nueva_sesion(ctx_a) as db:
        ids_a = {u.id for u in (await db.execute(select(UnidadNegocio))).scalars()}
    async with nueva_sesion(ctx_b) as db:
        ids_b = {u.id for u in (await db.execute(select(UnidadNegocio))).scalars()}
    assert set(datos["unidades"]) <= ids_a and datos["un_otro"] not in ids_a
    assert ids_b == {datos["un_otro"]}


async def test_prestador_solo_ve_tenants_que_atiende(datos):
    ctx = ContextoRLS(prestador_id=datos["prestador"], rol="despachador")
    async with nueva_sesion(ctx) as db:
        tenants = {t.id for t in (await db.execute(select(Tenant))).scalars()}
        unidades = {u.id for u in (await db.execute(select(UnidadNegocio))).scalars()}
    assert datos["tenant"] in tenants and datos["otro_tenant"] not in tenants
    assert datos["un_otro"] not in unidades and set(datos["unidades"]) <= unidades


async def test_superadmin_ve_todos_por_politica_de_rol(datos):
    async with nueva_sesion(ContextoRLS(rol="superadmin")) as db:
        tenants = {t.id for t in (await db.execute(select(Tenant))).scalars()}
    assert {datos["tenant"], datos["otro_tenant"]} <= tenants


async def test_no_puede_escribir_en_otro_tenant(datos):
    ctx = ContextoRLS(tenant_id=datos["tenant"], rol="admin_empresa")
    async with nueva_sesion(ctx) as db:
        db.add(UnidadNegocio(tenant_id=datos["otro_tenant"], codigo="INTRUSA", nombre="Intrusa"))
        with pytest.raises(DBAPIError, match="row-level security"):
            await db.flush()


async def test_prestador_no_escribe_datos_del_tenant(datos):
    ctx = ContextoRLS(prestador_id=datos["prestador"], rol="admin_prestador")
    async with nueva_sesion(ctx) as db:
        db.add(UnidadNegocio(tenant_id=datos["tenant"], codigo="DESDE-PRESTADOR", nombre="No permitida"))
        with pytest.raises(DBAPIError, match="row-level security"):
            await db.flush()


async def test_contexto_se_reaplica_despues_de_commit(datos):
    ctx = ContextoRLS(tenant_id=datos["tenant"], rol="admin_empresa")
    async with nueva_sesion(ctx) as db:
        antes = len((await db.execute(select(UnidadNegocio))).scalars().all())
        await db.commit()
        despues = len((await db.execute(select(UnidadNegocio))).scalars().all())
    assert antes == despues > 0


async def test_conexion_cruda_sin_contexto_no_ve_nada(datos):
    engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
    async with engine.connect() as conexion:
        assert (await conexion.execute(text("SELECT count(*) FROM usuarios"))).scalar() == 0
        assert (await conexion.execute(text("SELECT count(*) FROM unidades_negocio"))).scalar() == 0
    await engine.dispose()


# ------------------------------------------------------------------ vía API

async def test_api_admin_de_otro_tenant_no_ve_unidades_ajenas(cliente, auth, datos):
    r = await cliente.get("/api/unidades-negocio", headers=await auth("admin.otro@acma.dev"))
    assert r.status_code == 200
    assert {u["id"] for u in r.json()} == {str(datos["un_otro"])}
    ajena = await cliente.get(f"/api/unidades-negocio/{datos['unidades'][0]}", headers=await auth("admin.otro@acma.dev"))
    assert ajena.status_code == 404


async def test_api_no_permite_modificar_unidad_ajena(cliente, auth, datos):
    r = await cliente.patch(f"/api/unidades-negocio/{datos['un_otro']}", headers=await auth("admin.empresa@acma.dev"),
                            json={"nombre": "Hackeada"})
    assert r.status_code == 404


async def test_api_otro_prestador_no_ve_clientes_ajenos(cliente, auth, datos):
    h = await auth("admin.otroprestador@acma.dev")
    tenants = {t["id"] for t in (await cliente.get("/api/tenants", headers=h)).json()}
    assert tenants == {str(datos["otro_tenant"])}
    contratos = (await cliente.get("/api/contratos", headers=h)).json()
    assert contratos == []
    usuarios = {u["email"] for u in (await cliente.get("/api/usuarios", headers=h)).json()}
    assert usuarios == {"admin.otroprestador@acma.dev"}


async def test_api_operador_solo_ve_su_un_y_supervisor_las_de_su_grupo(cliente, auth, datos):
    op = (await cliente.get("/api/unidades-negocio", headers=await auth("operador@acma.dev"))).json()
    assert [u["id"] for u in op] == [str(datos["unidades"][0])]
    un = (await cliente.get("/api/unidades-negocio", headers=await auth("admin.un@acma.dev"))).json()
    assert len(un) == 2
    sup = (await cliente.get("/api/unidades-negocio", headers=await auth("supervisor.operadores@acma.dev"))).json()
    assert {u["id"] for u in sup} == {str(i) for i in datos["unidades"]}
