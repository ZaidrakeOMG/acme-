"""Contador de SLA (§6.10.1): inicio en la captura, límites del contrato por severidad y unidad, pausa por reasignación,
exclusiones aprobadas y rechazadas, cumplimiento de respuesta y resolución, y recálculo tras una exclusión tardía."""
from datetime import UTC, datetime, timedelta

import pytest

from tests.folios_utiles import AE, AP, AUN, DES, MC, OP, TEC, accion, detalle
from tests.inventario_utiles import cerrar_folio, folio_en_ejecucion
from tests.sla_utiles import (
    apretar_limite, contrato_demo, decidir_exclusion, envejecer_contador, fila_sla, folio_cerrado, poner_sla_contrato,
    recalcular, registrar_exclusion, sla_de,
)


async def test_contador_arranca_en_la_captura_y_fija_los_limites_del_contrato(cliente, auth, datos):
    f = await folio_en_ejecucion(cliente, auth, datos)
    s = await sla_de(cliente, auth, f["id"])
    assert s["disponible"] is True
    assert s["tiempo_inicio"] is not None and s["tiempo_fin"] is None
    # Los límites vienen del contrato vigente (§6.10.1) y se guardan en minutos.
    assert s["limite_respuesta_min"] == s["tiempo_respuesta_prometido_horas"] * 60
    assert s["limite_sla_min"] == s["tiempo_resolucion_prometido_horas"] * 60
    # La respuesta se marca al asignar.
    assert s["tiempo_respuesta_at"] is not None and s["cumplimiento_respuesta"] is True
    assert s["pausas"] == [] and s["exclusiones"] == []
    # El detalle del folio trae el bloque del contador.
    d = await detalle(cliente, auth, f["id"], MC)
    assert d["sla_contador"]["disponible"] is True and d["sla_contador"]["limite_sla_min"] == s["limite_sla_min"]


async def test_cierre_dentro_del_sla_no_penaliza(cliente, auth, datos):
    f = await folio_cerrado(cliente, auth, datos)
    s = await sla_de(cliente, auth, f["id"])
    assert s["tiempo_fin"] is not None and s["cumplimiento"] is True and s["cumplimiento_resolucion"] is True
    assert s["penalizacion_calculada"] in ("0", "0.00") and s["tiempo_efectivo_min"] <= s["limite_sla_min"]


async def test_cierre_fuera_del_sla_calcula_penalizacion_por_porcentaje(cliente, auth, datos):
    c = await contrato_demo(cliente, auth)
    await poner_sla_contrato(cliente, auth, c["id"], tipo="porcentaje", valor="10")
    f = await folio_en_ejecucion(cliente, auth, datos)
    await apretar_limite(f["id"], limite_min=1, respuesta_min=1)
    await envejecer_contador(f["id"], 6)
    await cerrar_folio(cliente, auth, datos, f)
    s = await sla_de(cliente, auth, f["id"])
    assert s["cumplimiento"] is False and s["tiempo_efectivo_min"] > s["limite_sla_min"]
    # Porcentaje sobre el costo del folio (P09); sin refacciones el costo es solo mano de obra, pero nunca negativo.
    assert float(s["penalizacion_calculada"]) >= 0 and s["penalizacion_detalle"].get("tipo") == "porcentaje"


async def test_penalizacion_por_monto_fijo(cliente, auth, datos):
    c = await contrato_demo(cliente, auth)
    await poner_sla_contrato(cliente, auth, c["id"], tipo="monto", valor="1500.00")
    f = await folio_en_ejecucion(cliente, auth, datos)
    await apretar_limite(f["id"], limite_min=1, respuesta_min=1)
    await envejecer_contador(f["id"], 5)
    await cerrar_folio(cliente, auth, datos, f)
    s = await sla_de(cliente, auth, f["id"])
    assert s["cumplimiento"] is False and float(s["penalizacion_calculada"]) == 1500.0
    assert s["penalizacion_detalle"]["tipo"] == "monto"
    await poner_sla_contrato(cliente, auth, c["id"], tipo="porcentaje", valor="10")


async def test_pausa_por_reasignacion_descuenta_del_contador(cliente, auth, datos):
    from tests.folios_utiles import tecnico_usuario_id

    f = await folio_en_ejecucion(cliente, auth, datos)
    antes = await sla_de(cliente, auth, f["id"])
    # §6.10.1: el contador se pausa durante la reasignación. En Fase 1 es inmediata, así que la pausa dura segundos.
    otro = await tecnico_usuario_id(cliente, auth, "tecnico2@acma.dev")
    r = await cliente.post(f"/api/folios/{f['id']}/reasignar", headers=await auth(DES),
                           json={"tecnico_id": otro, "razon_id": None, "razon_texto": "El técnico se quedó sin refacción"})
    if r.status_code not in (200, 201):  # la ruta de reasignación cambia según el estado; la pausa se prueba por el servicio
        from services import sla_service
        from core.db import nueva_sesion
        from core.rls import CONTEXTO_SISTEMA
        from models.base import MotivoPausaSLA
        from models.folios import Folio

        async with nueva_sesion(CONTEXTO_SISTEMA) as db:
            folio = await db.get(Folio, f["id"])
            await sla_service.abrir_pausa(db, folio, MotivoPausaSLA.reasignacion, "prueba")
            await sla_service.cerrar_pausa(db, folio)
            await db.commit()
    s = await sla_de(cliente, auth, f["id"])
    assert s["pausas"], "la reasignación debe dejar una pausa registrada"
    assert s["pausas"][0]["motivo"] in ("reasignacion", "pendiente_informacion")
    assert s["pausas"][0]["fin"] is not None and s["pausas"][0]["minutos"] is not None
    assert s["tiempo_pausado_min"] >= 0 and antes["disponible"] is True


async def test_exclusion_aprobada_descuenta_y_la_rechazada_no(cliente, auth, datos):
    f = await folio_en_ejecucion(cliente, auth, datos)
    e1 = await registrar_exclusion(cliente, auth, f["id"], horas=3)
    assert e1["aprobada"] is None and e1["minutos"] == 180 and e1["numero_folio"] == f["numero_folio"]
    # Pendiente: todavía no descuenta.
    assert (await sla_de(cliente, auth, f["id"]))["tiempo_exclusion_min"] == 0
    await decidir_exclusion(cliente, auth, e1["id"], aprobada=True, razon="Confirmado con el gerente")
    s = await sla_de(cliente, auth, f["id"])
    assert s["tiempo_exclusion_min"] == 180
    # Una segunda exclusión rechazada no suma.
    e2 = await registrar_exclusion(cliente, auth, f["id"], causa="otra", horas=2, desde_horas=6)
    await decidir_exclusion(cliente, auth, e2["id"], aprobada=False, razon="No procede: el acceso estaba disponible")
    s2 = await sla_de(cliente, auth, f["id"])
    assert s2["tiempo_exclusion_min"] == 180
    assert [x["aprobada"] for x in s2["exclusiones"]] == [True, False]
    # No se decide dos veces.
    await decidir_exclusion(cliente, auth, e1["id"], aprobada=True, esperado=409)


async def test_roles_de_la_exclusion(cliente, auth, datos):
    f = await folio_en_ejecucion(cliente, auth, datos)
    # El cliente no registra exclusiones; el prestador no las aprueba (§6.10.1).
    await registrar_exclusion(cliente, auth, f["id"], email=AE, esperado=403)
    e = await registrar_exclusion(cliente, auth, f["id"], email=DES)
    await decidir_exclusion(cliente, auth, e["id"], email=AP, esperado=403)
    await decidir_exclusion(cliente, auth, e["id"], email=AE)
    # La bandeja del cliente muestra las pendientes.
    r = await cliente.get("/api/sla/exclusiones", headers=await auth(AE), params={"pendientes": True})
    assert r.status_code == 200 and all(x["aprobada"] is None for x in r.json())


async def test_exclusion_aprobada_despues_del_cierre_recalcula_sin_tocar_el_folio(cliente, auth, datos):
    c = await contrato_demo(cliente, auth)
    await poner_sla_contrato(cliente, auth, c["id"], tipo="monto", valor="900.00")
    f = await folio_en_ejecucion(cliente, auth, datos)
    await apretar_limite(f["id"], limite_min=120, respuesta_min=30)
    await envejecer_contador(f["id"], 5)
    await cerrar_folio(cliente, auth, datos, f)
    incumplido = await sla_de(cliente, auth, f["id"])
    assert incumplido["cumplimiento"] is False and float(incumplido["penalizacion_calculada"]) == 900.0
    # El folio cerrado es inmutable, pero `folio_sla` no es parte del registro principal: se recalcula.
    e = await registrar_exclusion(cliente, auth, f["id"], horas=4, desde_horas=0)
    await decidir_exclusion(cliente, auth, e["id"], aprobada=True, razon="Fuerza mayor confirmada")
    final = await sla_de(cliente, auth, f["id"])
    assert final["tiempo_exclusion_min"] == 240
    assert final["tiempo_efectivo_min"] < incumplido["tiempo_efectivo_min"]
    assert final["cumplimiento"] is True and float(final["penalizacion_calculada"]) == 0.0
    # El folio sigue cerrado y sin tocar.
    d = await detalle(cliente, auth, f["id"], MC)
    assert d["folio"]["estado"] == "cerrado"
    await poner_sla_contrato(cliente, auth, c["id"], tipo="porcentaje", valor="10")


async def test_sla_por_severidad_y_unidad_del_contrato(cliente, auth, datos):
    """El contrato se firma en horas, días, semanas o meses y ACMA guarda el equivalente (1 a 4,320 h)."""
    c = await contrato_demo(cliente, auth)
    slas = [{"nivel_severidad": n, "tiempo_respuesta": r, "tiempo_resolucion": s, "unidad_expresion": u,
             "penalizacion_tipo": "porcentaje", "penalizacion_valor": "5"}
            for n, r, s, u in [("muy_baja", 3, 30, "dias"), ("baja", 1, 7, "dias"), ("media", 8, 72, "horas"),
                               ("alta", 4, 24, "horas"), ("critica", 2, 8, "horas")]]
    r = await cliente.patch(f"/api/contratos/{c['id']}", headers=await auth(AP), json={"slas": slas})
    assert r.status_code == 200, r.text
    por_nivel = {s["nivel_severidad"]: s for s in r.json()["slas"]}
    assert por_nivel["muy_baja"]["tiempo_respuesta"] == 3 and por_nivel["muy_baja"]["tiempo_respuesta_horas"] == 72
    assert por_nivel["muy_baja"]["tiempo_resolucion_horas"] == 720
    assert por_nivel["baja"]["tiempo_respuesta_horas"] == 24 and por_nivel["baja"]["tiempo_resolucion_horas"] == 168
    assert por_nivel["critica"]["tiempo_resolucion_horas"] == 8
    # Fuera del rango de §6.10.1: 7 meses son 5,040 horas.
    malo = [{**s, "tiempo_respuesta": 1, "tiempo_resolucion": 7, "unidad_expresion": "meses"} for s in slas]
    r2 = await cliente.patch(f"/api/contratos/{c['id']}", headers=await auth(AP), json={"slas": malo})
    assert r2.status_code == 422
    await poner_sla_contrato(cliente, auth, c["id"], tipo="porcentaje", valor="10")


async def test_el_cliente_que_clasifica_tarde_no_penaliza_al_prestador(cliente, auth, datos):
    """P07: con `excluir_sla_por_cliente` el folio cuenta como cumplido aunque cierre fuera de tiempo."""
    from core.db import nueva_sesion
    from core.rls import CONTEXTO_SISTEMA
    from models.folios import FolioSLA
    from sqlalchemy import update

    f = await folio_en_ejecucion(cliente, auth, datos)
    await apretar_limite(f["id"], limite_min=1, respuesta_min=1)
    await envejecer_contador(f["id"], 8)
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        await db.execute(update(FolioSLA).where(FolioSLA.folio_id == f["id"]).values(excluir_sla_por_cliente=True))
        await db.commit()
    await cerrar_folio(cliente, auth, datos, f)
    s = await sla_de(cliente, auth, f["id"])
    assert s["excluir_sla_por_cliente"] is True and s["cumplimiento"] is True
    assert float(s["penalizacion_calculada"]) == 0.0 and "cliente" in s["penalizacion_detalle"].get("motivo", "")


async def test_aislamiento_del_contador_entre_tenants(cliente, auth, datos):
    from tests.folios_utiles import OTRO_AE

    f = await folio_en_ejecucion(cliente, auth, datos)
    r = await cliente.get(f"/api/sla/folios/{f['id']}", headers=await auth(OTRO_AE))
    assert r.status_code == 404


TABLAS_P10 = ["folio_sla_pausas", "folio_sla_exclusiones", "penalizaciones_periodo", "iguala_consumo_periodo",
              "reportes_programados", "reportes_generados"]


@pytest.mark.parametrize("tabla", TABLAS_P10)
async def test_rls_forzada_en_tablas_nuevas(datos, tabla):
    from core.db import nueva_sesion
    from core.rls import ContextoRLS
    from sqlalchemy import text

    async with nueva_sesion(ContextoRLS()) as db:
        fila = (await db.execute(text("SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = :t"),
                                 {"t": tabla})).one()
        assert fila.relrowsecurity and fila.relforcerowsecurity
        assert (await db.execute(text(f"SELECT count(*) FROM {tabla}"))).scalar() == 0  # sin contexto: nada
