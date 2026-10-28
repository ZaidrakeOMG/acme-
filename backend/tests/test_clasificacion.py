"""Clasificación de folios no críticos y calificación del Admin UN (§6.10.5): configuración del tenant, folio no crítico en
espera de clasificación, pantalla de pendientes con plazo, las cinco opciones y su efecto, clasificación tardía (puntos y
bandera de SLA), alertas al Admin empresa y calificación del período."""
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from core.db import nueva_sesion
from core.rls import CONTEXTO_SISTEMA
from models.folios import FolioSLA, RevisionManualTrigger, TriggerRevision
from tests.folios_utiles import AE, AP, AUN, DES, OP, OTRO_AE, SUPO, capturar, detalle
from tests.seguimiento_utiles import alertas_disparadas, bandeja, detalle_registro


async def _config(cliente, auth, **cambios):
    r = await cliente.put("/api/clasificacion/configuracion", headers=await auth(AE), json=cambios)
    assert r.status_code == 200, r.text
    return r.json()


async def _no_critico(cliente, auth, datos, descripcion="Minisplit gotea un poco"):
    """Climatización «Gotea agua» → severidad baja/media (no crítica según la configuración del seed)."""
    return await capturar(cliente, auth, datos, OP, familia="Climatización", falla="Gotea agua", descripcion=descripcion)


async def test_configuracion_y_folio_pendiente_de_clasificar(cliente, auth, datos):
    c = await _config(cliente, auth, severidades_no_criticas_json=["muy_baja", "baja", "media"], plazo_horas=24, admin_empresa_puede_clasificar=True)
    assert c["plazo_horas"] == 24 and c["umbral_calificacion"] == 70 and c["puntos_json"]["base"] == 100
    assert (await cliente.put("/api/clasificacion/configuracion", headers=await auth(AUN), json={"plazo_horas": 1})).status_code == 403
    f = await _no_critico(cliente, auth, datos)
    d = await detalle(cliente, auth, f["id"])
    assert d["folio"]["estado"] == "en_revision" and d["aprobacion"] is None and d["folio"]["severidad"]["clave"] in ("muy_baja", "baja", "media")
    assert [t["trigger_tipo"] for t in d["triggers_revision"]] == ["pendiente_clasificacion"] and d["clasificacion"] is None
    assert any(n["evento"] == "clasificacion.pendiente" and n["datos"]["folio_id"] == f["id"] for n in await bandeja(cliente, auth, AUN, solo_no_leidas=True))
    pend = (await cliente.get("/api/clasificacion/pendientes", headers=await auth(AUN))).json()
    mio = next(p for p in pend if p["folio"]["id"] == f["id"])
    assert 0 < mio["horas_restantes"] <= 24 and mio["vencido"] is False and len(mio["opciones"]) == 5 and mio["folio"]["numero_folio"] == f["numero_folio"]
    assert any(p["folio"]["id"] == f["id"] for p in (await cliente.get("/api/clasificacion/pendientes", headers=await auth(AE))).json())  # habilitado
    assert (await cliente.get("/api/clasificacion/pendientes", headers=await auth(OP))).status_code == 403
    assert all(p["folio"]["id"] != f["id"] for p in (await cliente.get("/api/clasificacion/pendientes", headers=await auth(OTRO_AE))).json())
    # Un folio crítico sigue yendo al flujo multinivel.
    g = await capturar(cliente, auth, datos, OP)
    assert (await detalle(cliente, auth, g["id"]))["aprobacion"] is not None


async def test_cinco_opciones_y_su_efecto(cliente, auth, datos):
    await _config(cliente, auth, severidades_no_criticas_json=["muy_baja", "baja", "media"], plazo_horas=24, admin_empresa_puede_clasificar=False)
    # 4. Autorizado: el folio pasa a Autorizado y el SLA corre desde ese momento.
    f = await _no_critico(cliente, auth, datos, "Para autorizar")
    assert (await cliente.post(f"/api/clasificacion/{f['id']}", headers=await auth(DES), json={"opcion": "autorizado"})).status_code == 403
    assert (await cliente.post(f"/api/clasificacion/{f['id']}", headers=await auth(AE), json={"opcion": "autorizado"})).status_code == 403  # sin permiso del tenant
    r = await cliente.post(f"/api/clasificacion/{f['id']}", headers=await auth(AUN), json={"opcion": "autorizado", "notas": "Que lo atiendan"})
    assert r.status_code == 201 and r.json()["dentro_de_plazo"] is True and r.json()["horas_retraso"] == "0" and r.json()["modulo_destino"] is None
    d = await detalle(cliente, auth, f["id"])
    assert d["folio"]["estado"] == "autorizado" and d["clasificacion"]["opcion"] == "autorizado" and d["triggers_revision"][0]["resuelto"] is True
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        sla = (await db.execute(select(FolioSLA).where(FolioSLA.folio_id == f["id"]))).scalar_one()
        assert sla.autorizado_en is not None and sla.excluir_sla_por_cliente is False
    assert (await cliente.post(f"/api/clasificacion/{f['id']}", headers=await auth(AUN), json={"opcion": "autorizado"})).json()["codigo"] == "FOLIO_NO_PENDIENTE"
    assert any(n["evento"] == "folio.estado" and n["datos"]["folio_id"] == f["id"] for n in await bandeja(cliente, auth, DES))
    # 3. Cotización: módulo + aviso simultáneo a Mesa, Despachador y Admin prestador; el folio sale del ciclo.
    f = await _no_critico(cliente, auth, datos, "Para cotizar")
    r = await cliente.post(f"/api/clasificacion/{f['id']}", headers=await auth(AUN), json={"opcion": "cotizacion"})
    assert r.status_code == 201 and r.json()["modulo_destino"] == "cotizaciones"
    cot = await detalle_registro(cliente, auth, "cotizaciones", r.json()["modulo_registro_id"], DES)
    assert cot["estado"] == "solicitada" and cot["origen"] == "clasificacion" and cot["folio_id"] == f["id"]
    d = await detalle(cliente, auth, f["id"])
    assert d["folio"]["estado"] == "cancelado" and "cotización" in d["folio"]["razon_cancelacion"].lower() and d["derivaciones"][0]["modulo"] == "cotizaciones"
    for email in (DES, AP):
        assert any(n["datos"].get("cotizacion_id") == cot["id"] for n in await bandeja(cliente, auth, email)), email
    # 2. Reprogramación: pide fecha tentativa.
    f = await _no_critico(cliente, auth, datos, "Para reprogramar")
    r = await cliente.post(f"/api/clasificacion/{f['id']}", headers=await auth(AUN), json={"opcion": "reprogramacion"})
    assert r.status_code == 422 and r.json()["codigo"] == "FECHA_TENTATIVA_REQUERIDA"
    fecha = (datetime.now(UTC) + timedelta(days=12)).date().isoformat()
    r = await cliente.post(f"/api/clasificacion/{f['id']}", headers=await auth(AUN), json={"opcion": "reprogramacion", "fecha_tentativa": fecha, "notas": "Lo ve el plomero"})
    assert r.status_code == 201 and r.json()["fecha_tentativa"] == fecha
    rep = await detalle_registro(cliente, auth, "reprogramacion", r.json()["modulo_registro_id"], AUN)
    assert rep["estado"] == "fecha_asignada" and rep["fecha_acordada"] == fecha and rep["motivo"] == "Lo ve el plomero"
    # 1. Presupuesto y 5. Seguimiento interno.
    f = await _no_critico(cliente, auth, datos, "Para presupuesto")
    r = await cliente.post(f"/api/clasificacion/{f['id']}", headers=await auth(AUN), json={"opcion": "presupuesto"})
    assert r.status_code == 201 and (await detalle_registro(cliente, auth, "presupuesto", r.json()["modulo_registro_id"], AUN))["estado"] == "diferido"
    f = await _no_critico(cliente, auth, datos, "Para seguimiento")
    r = await cliente.post(f"/api/clasificacion/{f['id']}", headers=await auth(AUN), json={"opcion": "seguimiento_interno"})
    assert r.status_code == 201 and (await detalle_registro(cliente, auth, "interno", r.json()["modulo_registro_id"], AUN))["estado"] == "registrado"


async def test_clasificacion_tardia_puntos_y_alertas(cliente, auth, datos):
    from workers import tareas

    await _config(cliente, auth, severidades_no_criticas_json=["muy_baja", "baja", "media"], plazo_horas=24, umbral_calificacion=70)
    f = await _no_critico(cliente, auth, datos, "Tardío")
    g = await _no_critico(cliente, auth, datos, "Sigue pendiente")
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        for folio_id in (f["id"], g["id"]):
            t = (await db.execute(select(RevisionManualTrigger).where(RevisionManualTrigger.folio_id == folio_id, RevisionManualTrigger.trigger_tipo == TriggerRevision.pendiente_clasificacion))).scalar_one()
            t.timestamp = datetime.now(UTC) - timedelta(hours=30)
        await db.commit()
    pend = (await cliente.get("/api/clasificacion/pendientes", headers=await auth(AUN))).json()
    assert next(p for p in pend if p["folio"]["id"] == f["id"])["vencido"] is True
    # Alertas: recordatorio al Admin UN e incumplimiento al Admin empresa (una vez por folio).
    await tareas.evaluar_alertas_async()
    assert len(await alertas_disparadas("FOLIO_SIN_CLASIFICAR", f["id"])) == 1 and len(await alertas_disparadas("ADMIN_UN_INCUMPLIMIENTO_CLASIFICACION", f["id"])) == 1
    assert any(n["evento"] == "clasificacion.incumplimiento" and n["datos"]["folio_id"] == f["id"] for n in await bandeja(cliente, auth, AE))
    await tareas.evaluar_alertas_async()
    assert len(await alertas_disparadas("ADMIN_UN_INCUMPLIMIENTO_CLASIFICACION", f["id"])) == 1
    # Clasificación tardía: fuera de plazo, horas de retraso y bandera de SLA (no cuenta contra el prestador).
    r = await cliente.post(f"/api/clasificacion/{f['id']}", headers=await auth(AUN), json={"opcion": "autorizado"})
    assert r.status_code == 201 and r.json()["dentro_de_plazo"] is False and float(r.json()["horas_retraso"]) >= 5.9
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        sla = (await db.execute(select(FolioSLA).where(FolioSLA.folio_id == f["id"]))).scalar_one()
        assert sla.excluir_sla_por_cliente is True and sla.autorizado_en is not None
    # Calificación del período: descuento proporcional por el tardío y por el pendiente vencido; el Admin UN ve la suya.
    r = await cliente.post("/api/clasificacion/calificaciones/calcular", headers=await auth(AE))
    assert r.status_code == 200, r.text
    cal = next(c for c in r.json() if c["usuario_nombre"] == "Úrsula Unidad")
    assert cal["folios_tardios"] >= 1 and cal["folios_sin_clasificar"] >= 1 and float(cal["calificacion_final"]) < 100 and cal["puntos_total"] == 100
    assert any(e["tipo"] == "clasificacion_tardia" and e["folio_id"] == f["id"] for e in cal["eventos_json"])
    mias = (await cliente.get("/api/clasificacion/calificaciones", headers=await auth(AUN))).json()
    assert mias and all(m["usuario_nombre"] == "Úrsula Unidad" for m in mias)
    assert (await cliente.get("/api/clasificacion/calificaciones", headers=await auth(SUPO))).status_code == 403
    # Bajo desempeño: umbral alto → alerta y aviso al Admin empresa.
    await _config(cliente, auth, umbral_calificacion=100)
    await cliente.post("/api/clasificacion/calificaciones/calcular", headers=await auth(AE))
    assert await alertas_disparadas("ADMIN_UN_BAJO_DESEMPENO")
    assert any(n["evento"] == "calificacion.bajo_desempeno" for n in await bandeja(cliente, auth, AE))
    await _config(cliente, auth, umbral_calificacion=70)
    await cliente.post(f"/api/clasificacion/{g['id']}", headers=await auth(AUN), json={"opcion": "autorizado"})
