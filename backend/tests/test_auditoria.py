"""audit_log append-only (rechaza UPDATE/DELETE/TRUNCATE incluso al dueño), bitácora de accesos y tareas."""
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from core.db import nueva_sesion
from core.rls import CONTEXTO_SISTEMA
from models import AlertaHistorial
from services import alertas_service, auditoria
from workers import tareas


async def _evento_de_prueba() -> str:
    marca = f"prueba.{uuid.uuid4().hex[:8]}"
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        await auditoria.registrar(db, marca, recurso_tipo="prueba")
        await db.commit()
    return marca


@pytest.mark.parametrize("sentencia", [
    "UPDATE audit_log SET evento_tipo = 'alterado' WHERE evento_tipo = :m",
    "DELETE FROM audit_log WHERE evento_tipo = :m",
])
async def test_audit_log_rechaza_update_y_delete_como_api(datos, sentencia):
    marca = await _evento_de_prueba()
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        with pytest.raises(DBAPIError, match="permission denied"):
            await db.execute(text(sentencia), {"m": marca})


@pytest.mark.parametrize("sentencia", [
    "UPDATE audit_log SET evento_tipo = 'alterado' WHERE evento_tipo = :m",
    "DELETE FROM audit_log WHERE evento_tipo = :m",
    "TRUNCATE audit_log",
])
async def test_audit_log_rechaza_modificaciones_incluso_al_duenio(datos, sentencia):
    """El trigger BEFORE UPDATE/DELETE/TRUNCATE bloquea también al rol dueño del esquema."""
    marca = await _evento_de_prueba()
    engine = create_async_engine(os.environ["TEST_DATABASE_MIGRATIONS_URL"], poolclass=NullPool)
    try:
        async with engine.connect() as conexion:
            await conexion.execute(text("SELECT set_config('app.rol', 'sistema', false)"))
            with pytest.raises(DBAPIError, match="solo inserción"):
                await conexion.execute(text(sentencia), {"m": marca} if ":m" in sentencia else {})
    finally:
        await engine.dispose()
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        assert (await db.execute(text("SELECT count(*) FROM audit_log WHERE evento_tipo = :m"), {"m": marca})).scalar() == 1


async def test_audit_log_particionado_por_mes(datos):
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        particiones = (await db.execute(text(
            "SELECT count(*) FROM pg_inherits i JOIN pg_class p ON p.oid = i.inhparent WHERE p.relname = 'audit_log'"))).scalar()
    assert particiones >= 5  # mes actual + 3 adelante + default


async def test_auditoria_registra_login_y_accesos(cliente, auth, datos):
    h = await auth("superadmin@acma.dev")
    eventos = (await cliente.get("/api/auditoria/eventos", headers=h, params={"evento_tipo": "auth.login"})).json()
    assert any(e["evento_tipo"] == "auth.login_exitoso" for e in eventos)
    accesos = (await cliente.get("/api/auditoria/accesos-api", headers=h)).json()
    assert any(a["ruta"] == "/api/auth/login" for a in accesos)


async def test_alta_de_usuario_queda_auditada_sin_datos_sensibles(cliente, auth, datos):
    email = f"auditado.{uuid.uuid4().hex[:6]}@prueba.dev"
    r = await cliente.post("/api/usuarios", headers=await auth("admin.empresa@acma.dev"),
                           json={"email": email, "nombre": "Auditado", "rol": "operador", "contrasena": "Prueba#Segura2026"})
    assert r.status_code == 201
    eventos = (await cliente.get("/api/auditoria/eventos", headers=await auth("superadmin@acma.dev"),
                                 params={"evento_tipo": "usuarios.alta"})).json()
    evento = next(e for e in eventos if e["recurso_id"] == r.json()["id"])
    assert evento["valor_nuevo_json"]["email"] == email
    assert "password_hash" not in evento["valor_nuevo_json"]


async def test_evaluar_alertas_registra_en_historial(datos):
    clave = "PRESUPUESTO_ALERTA_1"

    async def evaluador_falso(db, alerta):
        h = await alertas_service.disparar(db, alerta.clave, tenant_id=datos["tenant"], prestador_id=None,
                                           entidad_tipo="unidad_negocio", entidad_id=datos["unidades"][0], datos={"consumo": 72})
        return 1 if h else 0

    tareas.EVALUADORES[clave] = evaluador_falso
    try:
        resumen = await tareas.evaluar_alertas_async()
    finally:
        tareas.EVALUADORES.pop(clave)
    assert resumen["disparadas"] == 1 and resumen["sin_evaluador"] == 19
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        h = (await db.execute(select(AlertaHistorial).where(AlertaHistorial.clave_alerta == clave))).scalars().all()
    assert any(x.datos_contexto_json == {"consumo": 72} and float(x.umbral_en_momento) == 70 for x in h)


async def test_supresion_evita_disparo(cliente, auth, datos):
    hasta = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
    r = await cliente.post("/api/alertas/supresiones", headers=await auth("admin.empresa@acma.dev"),
                           json={"clave_alerta": "ACTIVO_REEMPLAZO", "razon": "Mantenimiento programado", "hasta": hasta})
    assert r.status_code == 201
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        assert await alertas_service.disparar(db, "ACTIVO_REEMPLAZO", tenant_id=datos["tenant"], prestador_id=None) is None
        assert await alertas_service.disparar(db, "ACTIVO_REEMPLAZO", tenant_id=datos["otro_tenant"], prestador_id=None) is not None
        await db.rollback()


async def test_tarea_particiones_es_idempotente(datos):
    assert await tareas.crear_particiones_async() == 0
