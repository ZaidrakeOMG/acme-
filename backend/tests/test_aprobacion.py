"""Flujo de aprobación multinivel (§6.8.7): nivel de entrada por criterio y regla más restrictiva, aprobación en cadena,
rechazo con cada razón y su módulo destino, autorización automática de críticos, timeouts y restricción del Nivel 3."""
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text

from core.db import nueva_sesion
from core.rls import CONTEXTO_SISTEMA
from models.folios import AprobacionAlertaTimeout, AprobacionFlujo, AprobacionRegla, CriterioAprobacion, TipoFolio
from services import aprobacion_service
from tests.folios_utiles import (
    AE, AP, AUN, DES, MC, OP, SA, SUPO, TEC, NIVELES_DEMO, REGLAS_DEMO, accion, capturar, detalle, niveles, nuevo_equipo, politicas, reglas,
)


def _regla(nivel, criterio, operador, **valor):
    return AprobacionRegla(nivel=nivel, criterio=CriterioAprobacion(criterio), operador=operador, valor_json=valor, activa=True)


def test_nivel_de_entrada_por_cada_criterio_y_regla_mas_restrictiva():
    r = [_regla(1, "monto", "<", monto=5000), _regla(2, "monto", "entre", min=5000, max=20000), _regla(3, "monto", ">=", monto=20000),
         _regla(2, "criticidad", "en", valores=["A", "B"]), _regla(1, "tipo_trabajo", "igual", tipo="preventivo"),
         _regla(2, "tipo_trabajo", "igual", tipo="especial")]
    n = aprobacion_service.nivel_entrada
    assert n(r, monto=None, criticidad="C", tipo_folio=TipoFolio.correctivo) == 1          # monto ausente = 0 → Nivel 1
    assert n(r, monto=4999, criticidad="D", tipo_folio=TipoFolio.correctivo) == 1
    assert n(r, monto=5000, criticidad="D", tipo_folio=TipoFolio.correctivo) == 2
    assert n(r, monto=20000, criticidad="D", tipo_folio=TipoFolio.correctivo) == 3
    assert n(r, monto=100, criticidad="A", tipo_folio=TipoFolio.correctivo) == 2            # compresor A → mínimo Nivel 2
    assert n(r, monto=3000, criticidad="C", tipo_folio=TipoFolio.especial) == 2             # especial de $3,000 → Nivel 2
    assert n(r, monto=100, criticidad="C", tipo_folio=TipoFolio.preventivo) == 1
    assert n(r, monto=25000, criticidad="A", tipo_folio=TipoFolio.preventivo) == 3          # la más restrictiva gana
    assert n([], monto=1, criticidad="A", tipo_folio=TipoFolio.correctivo) is None          # sin reglas → sin flujo
    assert n([_regla(2, "criticidad", "en", valores=["A"])], monto=1, criticidad="C", tipo_folio=TipoFolio.correctivo) is None


async def test_sin_reglas_pasa_directo_a_autorizado(cliente, auth, datos):
    await reglas(cliente, auth, [])
    try:
        f = await capturar(cliente, auth, datos, OP)
        assert f["estado"] == "autorizado" and f["flujo"] is None
        d = await detalle(cliente, auth, f["id"])
        assert d["decisiones"] == [] and d["sla"] is not None
    finally:
        await reglas(cliente, auth, REGLAS_DEMO)


async def test_nivel_de_entrada_via_api_y_bandeja_del_aprobador(cliente, auth, datos):
    e_a = await nuevo_equipo(cliente, auth, datos, criticidad="A")
    f2 = await capturar(cliente, auth, datos, OP, e_a)
    assert f2["flujo"]["nivel_actual"] == 2 and f2["flujo"]["rol_aprobador_actual"] == "supervisor_operadores" and f2["flujo"]["vence_at"]
    f1 = await capturar(cliente, auth, datos, OP, await nuevo_equipo(cliente, auth, datos, criticidad="D"))
    assert f1["flujo"]["nivel_actual"] == 1
    f3 = await capturar(cliente, auth, datos, MC, await nuevo_equipo(cliente, auth, datos, criticidad="D"), monto_estimado=50000)
    assert f3["flujo"]["nivel_actual"] == 3 and f3["flujo"]["rol_aprobador_actual"] == "admin_empresa"
    fe = await capturar(cliente, auth, datos, OP, await nuevo_equipo(cliente, auth, datos, criticidad="D"), tipo_folio="especial")
    assert fe["flujo"]["nivel_actual"] == 2
    # Bandejas: Admin UN ve Nivel 1 de sus UNs; Supervisor Nivel 2; Admin empresa Nivel 3; el operador no tiene bandeja.
    async def bandeja(email):
        r = await cliente.get("/api/folios/pendientes-aprobacion", headers=await auth(email))
        assert r.status_code == 200, r.text
        return {p["folio"]["id"]: p for p in r.json()}
    b1, b2, b3 = await bandeja(AUN), await bandeja(SUPO), await bandeja(AE)
    assert f1["id"] in b1 and f2["id"] not in b1 and f3["id"] not in b1
    assert f2["id"] in b2 and fe["id"] in b2 and f1["id"] not in b2
    assert f3["id"] in b3 and f1["id"] not in b3 and b3[f3["id"]]["flujo"]["nivel_actual"] == 3
    assert (await cliente.get("/api/folios/pendientes-aprobacion", headers=await auth(OP))).status_code == 403
    assert (await detalle(cliente, auth, f1["id"], AUN))["puede_aprobar"] is True
    assert (await detalle(cliente, auth, f1["id"], AE))["puede_aprobar"] is False


async def test_solo_el_aprobador_del_nivel_decide(cliente, auth, datos):
    f = await capturar(cliente, auth, datos, OP, await nuevo_equipo(cliente, auth, datos, criticidad="A"))  # Nivel 2
    assert (await accion(cliente, auth, AUN, f["id"], "aprobacion/aprobar", {"canal": "app"}, 403))["codigo"] == "PROHIBIDO"
    assert (await accion(cliente, auth, AE, f["id"], "aprobacion/aprobar", {"canal": "app"}, 403))["codigo"] == "PROHIBIDO"
    assert (await cliente.post(f"/api/folios/{f['id']}/aprobacion/aprobar", headers=await auth(SUPO), json={"canal": "sistema"})).status_code == 422
    # Admin UN de la UN 3 (SUC-003 no es suya) tampoco en Nivel 1.
    g = await capturar(cliente, auth, datos, AE, await nuevo_equipo(cliente, auth, datos, criticidad="D", un_index=2))
    assert g["flujo"]["nivel_actual"] == 1
    assert (await accion(cliente, auth, AUN, g["id"], "aprobacion/aprobar", {"canal": "app"}, 404))["codigo"] == "NO_ENCONTRADO"  # fuera de su alcance
    a = await accion(cliente, auth, SUPO, f["id"], "aprobacion/aprobar", {"canal": "push"})
    assert a["estado"] == "autorizado" and a["flujo"]["estado"] == "aprobado" and a["flujo"]["resuelto_at"]
    d = await detalle(cliente, auth, f["id"])
    assert [(x["decision"], x["nivel"], x["canal"]) for x in d["decisiones"]] == [("aprobado", 2, "push")]
    assert d["decisiones"][0]["actor_nombre"] == "Óscar Supervisor" and d["sla"]["nivel_severidad_id"] == f["severidad"]["id"]
    assert (await accion(cliente, auth, SUPO, f["id"], "aprobacion/aprobar", {"canal": "app"}, 409))["codigo"] == "SIN_FLUJO_ACTIVO"


async def test_aprobacion_en_cadena_con_flujo_secuencial(cliente, auth, datos):
    await politicas(cliente, auth, aprobacion_secuencial=True)
    try:
        f = await capturar(cliente, auth, datos, MC, await nuevo_equipo(cliente, auth, datos, criticidad="D"), monto_estimado=30000)
        assert f["flujo"]["nivel_actual"] == 1 and f["flujo"]["nivel_maximo_requerido"] == 3
        a1 = await accion(cliente, auth, AUN, f["id"], "aprobacion/aprobar", {"canal": "minuta"})
        assert a1["estado"] == "en_revision" and a1["flujo"]["nivel_actual"] == 2
        assert (await accion(cliente, auth, AUN, f["id"], "aprobacion/aprobar", {"canal": "app"}, 403))["codigo"] == "PROHIBIDO"
        a2 = await accion(cliente, auth, SUPO, f["id"], "aprobacion/aprobar", {"canal": "app"})
        assert a2["estado"] == "en_revision" and a2["flujo"]["nivel_actual"] == 3
        a3 = await accion(cliente, auth, AE, f["id"], "aprobacion/aprobar", {"canal": "app", "notas": "Procede"})
        assert a3["estado"] == "autorizado"
        d = await detalle(cliente, auth, f["id"])
        assert [x["nivel"] for x in d["decisiones"]] == [1, 2, 3] and all(x["decision"] == "aprobado" for x in d["decisiones"])
        async with nueva_sesion(CONTEXTO_SISTEMA) as db:
            t = (await db.execute(select(AprobacionAlertaTimeout).where(AprobacionAlertaTimeout.folio_id == f["id"]))).scalars().all()
        assert sorted(x.nivel for x in t) == [1, 2, 3] and all(x.procesado and x.accion_ejecutada == "aprobado" for x in t)
    finally:
        await politicas(cliente, auth, aprobacion_secuencial=False)


@pytest.mark.parametrize("razon,modulo", [("por_presupuesto", "por_presupuesto"), ("requiere_cotizacion", "cotizaciones"),
                                          ("seguimiento_interno", "seguimiento_interno"), ("reprogramar", "reprogramacion")])
async def test_rechazo_con_cada_razon_deriva_al_modulo(cliente, auth, datos, razon, modulo):
    f = await capturar(cliente, auth, datos, OP, await nuevo_equipo(cliente, auth, datos, criticidad="D"))
    assert (await cliente.post(f"/api/folios/{f['id']}/aprobacion/rechazar", headers=await auth(AUN), json={"canal": "app"})).status_code == 422
    r = await accion(cliente, auth, AUN, f["id"], "aprobacion/rechazar", {"canal": "app", "razon_rechazo": razon, "notas": "No procede"})
    assert r["estado"] == "cancelado" and razon in r["razon_cancelacion"] and r["flujo"]["estado"] == "rechazado"
    d = await detalle(cliente, auth, f["id"])
    dec = d["decisiones"][0]
    assert dec["decision"] == "rechazado" and dec["razon_rechazo"] == razon and dec["modulo_destino"] == modulo and dec["modulo_destino_id"] is None
    evento = next(h for h in d["historial"] if h["evento"] == "folio.derivado_a_modulo")
    assert evento["datos_contexto_json"]["modulo_destino"] == modulo and evento["datos_contexto_json"]["procesado_por_p07"] is False
    assert d["folio"]["estado"] == "cancelado" and d["acciones"] == []


async def test_autorizacion_automatica_de_criticos(cliente, auth, datos):
    await politicas(cliente, auth, autorizacion_automatica_criticos=True)
    try:
        f = await capturar(cliente, auth, datos, OP, await nuevo_equipo(cliente, auth, datos, criticidad="B"))
        assert f["estado"] == "autorizado" and f["flujo"]["estado"] == "aprobado"
        d = await detalle(cliente, auth, f["id"])
        assert [(x["decision"], x["canal"], x["actor_id"]) for x in d["decisiones"]] == [("auto_aprobado", "sistema", None)]
        g = await capturar(cliente, auth, datos, OP, await nuevo_equipo(cliente, auth, datos, criticidad="C"))
        assert g["estado"] == "en_revision" and g["flujo"]["estado"] == "activo"
    finally:
        await politicas(cliente, auth, autorizacion_automatica_criticos=False)


# ----------------------------------------------------------------- timeouts

async def _vencer(folio_id, nivel):
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        t = (await db.execute(select(AprobacionAlertaTimeout).where(
            AprobacionAlertaTimeout.folio_id == folio_id, AprobacionAlertaTimeout.nivel == nivel, AprobacionAlertaTimeout.procesado.is_(False)))).scalar_one()
        t.vence_at = datetime.now(UTC) - timedelta(minutes=1)
        await db.commit()


async def _evaluar():
    from workers.tareas import evaluar_timeouts_aprobacion_async
    return await evaluar_timeouts_aprobacion_async()


async def test_timeout_escalar_y_bloquear_alertar(cliente, auth, datos):
    f = await capturar(cliente, auth, datos, OP, await nuevo_equipo(cliente, auth, datos, criticidad="D"))  # Nivel 1: escalar
    await _vencer(f["id"], 1)
    resumen = await _evaluar()
    assert resumen["escalar"] >= 1
    d = await detalle(cliente, auth, f["id"])
    assert d["aprobacion"]["nivel_actual"] == 2 and d["aprobacion"]["estado"] == "activo" and d["aprobacion"]["vence_at"]
    assert [x["decision"] for x in d["decisiones"]] == ["escalado"] and d["decisiones"][0]["canal"] == "sistema"
    historial = (await cliente.get("/api/alertas/historial", headers=await auth(AE))).json()
    assert any(a["clave_alerta"] == "APROBACION_PENDIENTE_VENCIDA" and a["entidad_id"] == f["id"] for a in historial)
    # Nivel 2 con depende_criticidad y activo D → bloquear y alertar; el aprobador aún puede decidir.
    await _vencer(f["id"], 2)
    resumen = await _evaluar()
    assert resumen["depende_criticidad"] >= 1
    d = await detalle(cliente, auth, f["id"])
    assert d["aprobacion"]["estado"] == "bloqueado" and d["folio"]["estado"] == "en_revision"
    assert [x["decision"] for x in d["decisiones"]] == ["escalado", "bloqueado"]
    historial = (await cliente.get("/api/alertas/historial", headers=await auth(AE))).json()
    assert any(a["clave_alerta"] == "APROBACION_BLOQUEADA" and a["entidad_id"] == f["id"] for a in historial)
    assert f["id"] in {p["folio"]["id"] for p in (await cliente.get("/api/folios/pendientes-aprobacion", headers=await auth(SUPO))).json()}
    a = await accion(cliente, auth, SUPO, f["id"], "aprobacion/aprobar", {"canal": "app"})
    assert a["estado"] == "autorizado"


async def test_timeout_autorizar_automatico_y_depende_criticidad_critico(cliente, auth, datos):
    await niveles(cliente, auth, [{**NIVELES_DEMO[0], "comportamiento_timeout": "autorizar_automatico"}, NIVELES_DEMO[1], NIVELES_DEMO[2]])
    try:
        f = await capturar(cliente, auth, datos, OP, await nuevo_equipo(cliente, auth, datos, criticidad="D"))
        await _vencer(f["id"], 1)
        assert (await _evaluar())["autorizar_automatico"] >= 1
        d = await detalle(cliente, auth, f["id"])
        assert d["folio"]["estado"] == "autorizado" and [x["decision"] for x in d["decisiones"]] == ["auto_aprobado"]
        # Nivel 2 depende_criticidad con activo A → autoriza automáticamente.
        g = await capturar(cliente, auth, datos, OP, await nuevo_equipo(cliente, auth, datos, criticidad="A"))
        await _vencer(g["id"], 2)
        assert (await _evaluar())["depende_criticidad"] >= 1
        d = await detalle(cliente, auth, g["id"])
        assert d["folio"]["estado"] == "autorizado" and d["decisiones"][0]["decision"] == "auto_aprobado"
    finally:
        await niveles(cliente, auth, NIVELES_DEMO)


async def test_timeout_nivel_3_bloquea_y_restriccion_de_configuracion(cliente, auth, datos):
    # El Nivel 3 no admite escalar ni autorizar_automatico (422 del esquema) ni por servicio/BD.
    for comportamiento in ("escalar", "autorizar_automatico"):
        await niveles(cliente, auth, [NIVELES_DEMO[0], NIVELES_DEMO[1], {**NIVELES_DEMO[2], "comportamiento_timeout": comportamiento}], 422)
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        with pytest.raises(Exception, match="ck_aprobacion_nivel3"):
            await db.execute(text("UPDATE aprobacion_niveles_config SET comportamiento_timeout = 'escalar' WHERE nivel = 3 AND tenant_id = :t"),
                             {"t": datos["tenant"]})
    assert (await cliente.put("/api/folios/aprobacion/niveles", headers=await auth(AUN), json=NIVELES_DEMO)).status_code == 403
    assert (await cliente.put("/api/folios/aprobacion/niveles", headers=await auth(AE), json=[NIVELES_DEMO[0], NIVELES_DEMO[0]])).status_code == 422
    f = await capturar(cliente, auth, datos, MC, await nuevo_equipo(cliente, auth, datos, criticidad="D"), monto_estimado=99000)  # Nivel 3
    await _vencer(f["id"], 3)
    assert (await _evaluar())["bloquear_alertar"] >= 1
    d = await detalle(cliente, auth, f["id"])
    assert d["aprobacion"]["estado"] == "bloqueado" and d["aprobacion"]["nivel_actual"] == 3
    r = await accion(cliente, auth, AE, f["id"], "aprobacion/rechazar", {"canal": "app", "razon_rechazo": "por_presupuesto"})
    assert r["estado"] == "cancelado"


async def test_timeouts_vencidos_de_flujos_ya_resueltos_se_omiten(cliente, auth, datos):
    f = await capturar(cliente, auth, datos, OP, await nuevo_equipo(cliente, auth, datos, criticidad="D"))
    await accion(cliente, auth, DES, f["id"], "cancelar", {"razon": "Se canceló antes de aprobar"})
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        t = (await db.execute(select(AprobacionAlertaTimeout).where(AprobacionAlertaTimeout.folio_id == f["id"]))).scalars().all()
        for x in t:
            x.procesado, x.vence_at = False, datetime.now(UTC) - timedelta(minutes=1)
        await db.commit()
    resumen = await _evaluar()
    assert resumen["omitidos"] >= 1
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        fl = (await db.execute(select(AprobacionFlujo).where(AprobacionFlujo.folio_id == f["id"]))).scalar_one()
    assert fl.estado.value == "activo" and (await detalle(cliente, auth, f["id"]))["folio"]["estado"] == "cancelado"


async def test_configuracion_de_reglas_valida_y_se_lee(cliente, auth, datos):
    assert (await cliente.put("/api/folios/aprobacion/reglas", headers=await auth(AE), json=[{"nivel": 1, "criterio": "monto", "operador": "en", "valor_json": {}}])).status_code == 422
    assert (await cliente.put("/api/folios/aprobacion/reglas", headers=await auth(AE), json=[{"nivel": 2, "criterio": "criticidad", "operador": "en", "valor_json": {"valores": ["Z"]}}])).status_code == 422
    cfg = (await cliente.get("/api/folios/aprobacion/configuracion", headers=await auth(AE))).json()
    assert len(cfg["reglas"]) == 6 and [n["nivel"] for n in cfg["niveles"]] == [1, 2, 3] and cfg["politicas"]["prefijo_folio"] == "CD"
    assert (await cliente.get("/api/folios/aprobacion/configuracion", headers=await auth(DES), params={"tenant_id": str(datos["tenant"])})).status_code == 200
    assert (await cliente.get("/api/folios/aprobacion/configuracion", headers=await auth(OP))).status_code == 403
    assert (await cliente.put("/api/folios/politicas", headers=await auth(AE), json={"prefijo_folio": "cd-1"})).status_code == 422
