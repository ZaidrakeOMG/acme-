"""Envío de posiciones desde la app del técnico (§6.8.4): jornada, validaciones del lote, posiciones tardías,
Redis con TTL, evento de tiempo real al prestador correcto y privacidad del recorrido. F2-03."""
import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from tests.folios_utiles import AE, AP, AUN, DES, OP, OTRO_AP, TEC, TEC2
from tests.operacion_utiles import (
    CENTRO, POLANCO, cerrar, enviar, jornada, mi_jornada, punto, tecnico_de,
)


async def test_sin_jornada_no_se_acepta_ninguna_posicion(cliente, auth, datos):
    """§6.8.4: la jornada la abre el técnico, y sin ella no se registra nada (regla de privacidad)."""
    await cerrar(cliente, auth, TEC2)
    try:
        estado = await mi_jornada(cliente, auth, TEC2)
        assert estado["jornada"] is None and estado["estatus"] == "fuera_de_jornada"
        r = await cliente.post("/api/operacion/posiciones", headers=await auth(TEC2),
                               json={"posiciones": [punto(CENTRO)]})
        assert r.status_code == 409 and r.json()["codigo"] == "SIN_JORNADA"
    finally:
        await jornada(cliente, auth, TEC2)


async def test_el_aviso_de_ubicacion_se_acepta_una_vez(cliente, auth, datos):
    """La primera vez hay que aceptar el aviso; después ya no se pregunta."""
    estado = await mi_jornada(cliente, auth, TEC)
    assert estado["aviso_aceptado"] is True  # el seed ya abrió jornada con el aviso aceptado
    assert "cada 30 segundos" in estado["aviso_geolocalizacion"]
    assert estado["frecuencias"] == {"jornada_activa_s": 30, "pausa_s": 300, "bateria_baja_s": 120,
                                     "bateria_baja_pct": 20}
    assert estado["geocerca_radio_m"] == 150 and estado["horas_recorrido"] == 2
    # F2-06: el texto ya explica cómo se mide el desvío en vez de prometerlo para la Fase 2.
    assert "corredor" in estado["desvio_ruta"] and "Fase 2" not in estado["desvio_ruta"]


async def test_una_jornada_a_la_vez_y_pausa_con_motivo(cliente, auth, datos):
    primera = await mi_jornada(cliente, auth, TEC)
    otra = await jornada(cliente, auth, TEC)
    assert otra["jornada"]["id"] == primera["jornada"]["id"], "no se abren dos jornadas del mismo técnico"

    r = await cliente.post("/api/operacion/jornada/pausar", headers=await auth(TEC),
                           json={"motivo": "comida", "nota": "20 minutos"})
    assert r.status_code == 200 and r.json()["jornada"]["estado"] == "pausa"
    assert r.json()["estatus"] == "pausa" and r.json()["jornada"]["pausa_motivo"] == "comida"
    r = await cliente.post("/api/operacion/jornada/pausar", headers=await auth(TEC), json={"motivo": "otro"})
    assert r.status_code == 409 and r.json()["codigo"] == "YA_EN_PAUSA"
    r = await cliente.post("/api/operacion/jornada/reanudar", headers=await auth(TEC))
    assert r.status_code == 200 and r.json()["jornada"]["estado"] == "activa"
    r = await cliente.post("/api/operacion/jornada/reanudar", headers=await auth(TEC))
    assert r.status_code == 409 and r.json()["codigo"] == "SIN_PAUSA"


async def test_el_lote_y_la_precision_se_validan_en_el_servidor(cliente, auth, datos):
    """Las frecuencias no se validan (manda la app), pero el tamaño del lote y la calidad del dato sí."""
    estado = await mi_jornada(cliente, auth, TEC)
    assert estado["max_lote"] == 60 and estado["precision_maxima_m"] == 500
    r = await cliente.post("/api/operacion/posiciones", headers=await auth(TEC),
                           json={"posiciones": [punto(CENTRO, i) for i in range(61)]})
    assert r.status_code == 422, r.text  # el esquema corta en 60

    salida = await enviar(cliente, auth, [
        punto(CENTRO, 10, precision_m=800),                      # peor que 500 m: no sirve
        {"lat": 19.4, "lng": -99.1, "capturada_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat()},
        {"lat": 19.4, "lng": -99.1,
         "capturada_at": (datetime.now(UTC) - timedelta(days=3)).isoformat()},
        punto(CENTRO, 5),
    ], email=TEC)
    assert salida["aceptadas"] == 1
    motivos = " ".join(d["motivo"] for d in salida["descartadas"])
    assert "precisión" in motivos and "futuro" in motivos and "dos días" in motivos


async def test_una_posicion_tardia_no_mueve_el_mapa_hacia_atras(cliente, auth, datos):
    """§6.8.4: lo que se guardó sin señal entra al historial, pero no genera movimientos falsos."""
    await jornada(cliente, auth, TEC)
    await enviar(cliente, auth, [punto(POLANCO, 5, bateria_pct=70)], email=TEC)
    actual = await tecnico_de(TEC)
    assert actual["lat"] == pytest.approx(POLANCO[0], abs=0.0005)

    salida = await enviar(cliente, auth, [punto(CENTRO, 900, tardia=True)], email=TEC)
    assert salida["aceptadas"] == 1
    despues = await tecnico_de(TEC)
    assert despues["lat"] == pytest.approx(POLANCO[0], abs=0.0005), "la última posición no retrocede"
    assert despues["ultima_posicion_at"] == actual["ultima_posicion_at"]

    # Y una posición nueva sí la mueve.
    await enviar(cliente, auth, [punto(CENTRO, 0, bateria_pct=65)], email=TEC)
    final = await tecnico_de(TEC)
    assert final["lat"] == pytest.approx(CENTRO[0], abs=0.0005) and final["bateria_pct"] == 65


async def test_la_posicion_actual_va_a_redis_con_ttl_de_dos_minutos(cliente, auth, datos):
    """§6.8.4: Redis guarda la posición actual con TTL de 2 min; la base guarda el historial.

    En pruebas `TIEMPO_REAL_MODO=local`, así que el caché no se usa y el tablero lee de la base: lo que se verifica
    es que el TTL es el del diseño y que sin Redis nada se rompe.
    """
    from services import operacion_service

    assert operacion_service.TTL_REDIS_S == 120
    tecnico = await tecnico_de(TEC)
    assert operacion_service.clave_redis(tecnico["id"]).startswith("acma:posicion:")
    assert await operacion_service.posicion_en_redis(tecnico["id"]) is None
    await enviar(cliente, auth, [punto(CENTRO, 1)], email=TEC)  # no falla sin Redis


async def test_el_evento_llega_solo_al_tablero_del_prestador_del_tecnico(cliente, auth, datos):
    """§6.9.5: las posiciones de un prestador nunca llegan al tablero de otro."""
    from services.ws_manager import gestor

    tecnico = await tecnico_de(TEC)
    mio = await gestor.suscribir_canal(f"operacion:{tecnico['prestador_id']}")
    ajeno = await gestor.suscribir_canal(f"operacion:{datos['otro_prestador']}")
    try:
        await jornada(cliente, auth, TEC)
        await enviar(cliente, auth, [punto(CENTRO, 0, bateria_pct=61)], email=TEC)
        evento = await asyncio.wait_for(mio.get(), timeout=5)
        assert evento["evento"] in ("posicion", "estatus", "jornada")
        while evento["evento"] != "posicion":
            evento = await asyncio.wait_for(mio.get(), timeout=5)
        assert evento["tecnico_id"] == str(tecnico["id"]) and evento["bateria_pct"] == 61
        assert evento["prestador_id"] == str(tecnico["prestador_id"])
        assert ajeno.empty(), "el otro prestador no recibe nada"
    finally:
        await gestor.desuscribir_canal(f"operacion:{tecnico['prestador_id']}", mio)
        await gestor.desuscribir_canal(f"operacion:{datos['otro_prestador']}", ajeno)


async def test_el_tecnico_ve_su_recorrido_y_el_cliente_no_ve_ninguno(cliente, auth, datos):
    tecnico = await tecnico_de(TEC)
    r = await cliente.get("/api/operacion/mis-posiciones", headers=await auth(TEC), params={"horas": 4})
    assert r.status_code == 200, r.text
    assert r.json()["tecnico_id"] == str(tecnico["id"]) and len(r.json()["puntos"]) >= 1

    # Los roles del cliente no entran al recorrido de nadie (§6.9.5).
    for email in (AE, AUN, OP):
        r = await cliente.get(f"/api/operacion/tecnicos/{tecnico['id']}/recorrido", headers=await auth(email))
        assert r.status_code in (403, 404), f"{email} → {r.status_code}"
    # El otro prestador tampoco.
    r = await cliente.get(f"/api/operacion/tecnicos/{tecnico['id']}/recorrido", headers=await auth(OTRO_AP))
    assert r.status_code == 404
    # El despachador sí, y queda en la bitácora de accesos a datos sensibles.
    r = await cliente.get(f"/api/operacion/tecnicos/{tecnico['id']}/recorrido", headers=await auth(DES),
                          params={"horas": 2})
    assert r.status_code == 200, r.text
    from sqlalchemy import select

    from core.db import nueva_sesion
    from core.rls import CONTEXTO_SISTEMA
    from models.auditoria import AuditLog

    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        filas = (await db.execute(select(AuditLog).where(
            AuditLog.evento_tipo == "acceso.datos_sensibles").order_by(AuditLog.created_at.desc()).limit(10))).scalars().all()
    assert any((f.valor_nuevo_json or {}).get("tabla") == "tecnico_posiciones" for f in filas)


async def test_el_cliente_no_ve_la_tabla_ni_por_rls(cliente, auth, datos):
    """La RLS deja la tabla vacía para un contexto de cliente, no solo el endpoint cerrado."""
    from sqlalchemy import select

    from core.db import nueva_sesion
    from core.rls import ContextoRLS
    from models.operaciones import TecnicoPosicion
    from models.usuarios import Usuario

    async with nueva_sesion(ContextoRLS(rol="sistema")) as sistema:
        admin_un = (await sistema.execute(select(Usuario).where(Usuario.email == AUN))).scalar_one()
        total_sistema = len((await sistema.execute(select(TecnicoPosicion.id).limit(5))).all())
    assert total_sistema > 0
    async with nueva_sesion(ContextoRLS(usuario_id=admin_un.id, tenant_id=admin_un.tenant_id,
                                        rol=admin_un.rol.value)) as db:
        visibles = (await db.execute(select(TecnicoPosicion.id).limit(5))).all()
    assert visibles == [], "el cliente no ve posiciones de técnicos"


async def test_las_posiciones_no_se_pueden_borrar_ni_editar_desde_la_api(cliente, auth, datos):
    """El historial de posiciones es append-only: la API solo inserta y lee (§6.9.5, como la auditoría de P01)."""
    from sqlalchemy import text as sql

    from core.db import nueva_sesion
    from core.rls import CONTEXTO_SISTEMA

    tecnico = await tecnico_de(TEC)
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        # La tabla solo tiene políticas de SELECT y de INSERT: con RLS forzada, un UPDATE o un DELETE no alcanzan
        # ninguna fila aunque el rol tenga el privilegio del esquema.
        politicas = set((await db.execute(sql(
            "SELECT cmd FROM pg_policies WHERE tablename = 'tecnico_posiciones'"))).scalars())
        assert politicas == {"SELECT", "INSERT"}, politicas
        antes = (await db.execute(sql("SELECT count(*) FROM tecnico_posiciones WHERE tecnico_id = :t"),
                                  {"t": str(tecnico["id"])})).scalar_one()
        assert antes > 0, "el técnico tiene historial de posiciones"
        borradas = (await db.execute(sql("DELETE FROM tecnico_posiciones WHERE tecnico_id = :t"),
                                     {"t": str(tecnico["id"])})).rowcount
        editadas = (await db.execute(sql("UPDATE tecnico_posiciones SET tardia = true WHERE tecnico_id = :t"),
                                     {"t": str(tecnico["id"])})).rowcount
        await db.commit()
        despues = (await db.execute(sql("SELECT count(*) FROM tecnico_posiciones WHERE tecnico_id = :t"),
                                    {"t": str(tecnico["id"])})).scalar_one()
    assert borradas == 0 and editadas == 0, "el historial de posiciones es append-only"
    assert despues == antes
    # Ni el dueño del esquema puede borrar filas: la RLS está forzada y no hay política de DELETE. Por eso la
    # retención de 90 días se hace soltando particiones (DETACH + DROP) y no con un DELETE por fecha.
    import os

    from sqlalchemy.ext.asyncio import create_async_engine

    duenio = create_async_engine(os.environ["TEST_DATABASE_MIGRATIONS_URL"].replace(
        "postgresql://", "postgresql+asyncpg://"), isolation_level="AUTOCOMMIT")
    try:
        async with duenio.connect() as con:
            r = await con.execute(sql("DELETE FROM tecnico_posiciones WHERE tecnico_id = :t"),
                                  {"t": str(tecnico["id"])})
            assert r.rowcount == 0
    finally:
        await duenio.dispose()


@pytest.mark.parametrize("tabla", ["jornadas_tecnico", "jornada_pausas", "tecnico_posiciones",
                                   "alertas_operacion_seguimiento"])
async def test_rls_forzada_en_las_tablas_nuevas(tabla):
    from sqlalchemy import text as sql

    from core.db import nueva_sesion
    from core.rls import CONTEXTO_SISTEMA

    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        fila = (await db.execute(sql("SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = :t"),
                                 {"t": tabla})).one()
        assert fila.relrowsecurity and fila.relforcerowsecurity


async def test_las_posiciones_viven_en_particiones_diarias_con_retencion(cliente, auth, datos):
    """§6.9.5: 90 días de recorridos, soltando particiones enteras (DETACH + DROP), como la auditoría de P11a."""
    from sqlalchemy import text as sql

    from core.db import nueva_sesion
    from core.rls import CONTEXTO_SISTEMA
    from workers.tareas.operacion import particiones_posiciones_async, purgar_posiciones_async

    await particiones_posiciones_async()
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        hoy = (await db.execute(sql(
            "SELECT count(*) FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid "
            " JOIN pg_class p ON p.oid = i.inhparent WHERE p.relname = 'tecnico_posiciones' "
            "   AND c.relname = 'tecnico_posiciones_' || to_char(CURRENT_DATE, 'YYYY_MM_DD')"))).scalar_one()
        assert hoy == 1, "la partición del día existe"

    # Las particiones viejas las crea el dueño del esquema (la API no puede crear tablas: así debe ser).
    import os

    from sqlalchemy.ext.asyncio import create_async_engine

    duenio = create_async_engine(os.environ["TEST_DATABASE_MIGRATIONS_URL"].replace(
        "postgresql://", "postgresql+asyncpg://"), isolation_level="AUTOCOMMIT")
    try:
        async with duenio.connect() as con:
            # Dos particiones viejas: una con nombre de fecha (se suelta) y otra con otro nombre (no se toca).
            for nombre in ("tecnico_posiciones_2020_01_01", "tecnico_posiciones_vieja_prueba"):
                await con.execute(sql(f"DROP TABLE IF EXISTS {nombre}"))
            await con.execute(sql("""
                CREATE TABLE tecnico_posiciones_2020_01_01 PARTITION OF tecnico_posiciones
                  FOR VALUES FROM ('2020-01-01') TO ('2020-01-02')"""))
            await con.execute(sql("""
                CREATE TABLE tecnico_posiciones_vieja_prueba PARTITION OF tecnico_posiciones
                  FOR VALUES FROM ('2019-01-01') TO ('2019-01-02')"""))
        resultado = await purgar_posiciones_async(90)
        assert any(r["particion"] == "tecnico_posiciones_2020_01_01" and r["accion"] == "soltada"
                   for r in resultado)
        assert all(not r["particion"].endswith("vieja_prueba") for r in resultado),             "solo se sueltan las particiones cuyo nombre lleva su fecha"
        async with nueva_sesion(CONTEXTO_SISTEMA) as db:
            assert (await db.execute(sql("SELECT to_regclass('tecnico_posiciones_2020_01_01')"))).scalar() is None
    finally:
        async with duenio.connect() as con:
            await con.execute(sql("ALTER TABLE tecnico_posiciones DETACH PARTITION "
                                  "tecnico_posiciones_vieja_prueba"))
            await con.execute(sql("DROP TABLE IF EXISTS tecnico_posiciones_vieja_prueba"))
        await duenio.dispose()


async def test_los_roles_del_cliente_no_mandan_posiciones_ni_abren_jornada(cliente, auth, datos):
    for email in (AE, OP, AP):
        r = await cliente.post("/api/operacion/jornada/iniciar", headers=await auth(email),
                               json={"acepta_aviso": True})
        assert r.status_code == 403, email
        r = await cliente.post("/api/operacion/posiciones", headers=await auth(email),
                               json={"posiciones": [punto(CENTRO)]})
        assert r.status_code == 403, email
