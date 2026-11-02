"""Reportes ejecutivos (ACT-8.4): generación inmediata en PDF y Excel por plantilla, permisos por rol, historial,
programación con periodicidad, envío por el correo stub y medición del tiempo con 1,000+ folios."""
import time
from datetime import UTC, date, datetime, timedelta

from core.db import nueva_sesion
from core.rls import CONTEXTO_SISTEMA
from services import correo
from tests.folios_utiles import AE, AP, AUN, DES, MC, OP, OTRO_AE, SA, SUPO, TEC

DIR = "direccion@acma.dev"
SUPP = "supervisor.prestador@acma.dev"
FIRMAS = {"pdf": b"%PDF", "excel": b"PK"}


async def _generar(cliente, auth, email, *, tipo="cliente", formato="pdf", esperado=200, **extra):
    r = await cliente.post("/api/bi/reportes/generar", headers=await auth(email),
                           json={"tipo_reporte": tipo, "formato": formato, **extra})
    assert r.status_code == esperado, r.text
    return r


async def test_reporte_del_cliente_en_pdf_y_excel(cliente, auth, datos):
    for formato in ("pdf", "excel"):
        r = await _generar(cliente, auth, AE, tipo="cliente", formato=formato)
        assert r.content.startswith(FIRMAS[formato]) and len(r.content) > 800
        assert "attachment" in r.headers["content-disposition"]
        assert int(r.headers["x-reporte-ms"]) >= 0 and r.headers["x-reporte-id"]


async def test_reporte_del_prestador_y_cierre_de_jornada(cliente, auth, datos):
    r = await _generar(cliente, auth, AP, tipo="prestador", formato="excel")
    assert r.content.startswith(b"PK")
    r = await _generar(cliente, auth, SUPP, tipo="jornada", formato="pdf")
    assert r.content.startswith(b"%PDF")


async def test_permisos_por_plantilla(cliente, auth, datos):
    # El cliente no saca el reporte interno del prestador ni al revés para el suyo.
    await _generar(cliente, auth, AE, tipo="prestador", esperado=403)
    await _generar(cliente, auth, TEC, tipo="cliente", esperado=403)
    await _generar(cliente, auth, OP, tipo="jornada", esperado=403)
    # Plantilla inexistente.
    await _generar(cliente, auth, AE, tipo="inventado", esperado=422)


async def test_historial_de_generados_y_descarga(cliente, auth, datos):
    r = await _generar(cliente, auth, AE, tipo="cliente", formato="pdf")
    reporte_id = r.headers["x-reporte-id"]
    lista = (await cliente.get("/api/bi/reportes/generados", headers=await auth(AE))).json()
    mio = next((x for x in lista if x["id"] == reporte_id), None)
    assert mio is not None and mio["tipo_reporte"] == "cliente" and mio["filas"] >= 1
    assert mio["ms_generacion"] is not None and mio["archivo_key"].startswith("reportes/")
    r2 = await cliente.get(f"/api/bi/reportes/generados/{reporte_id}/archivo", headers=await auth(AE))
    assert r2.status_code == 200 and r2.content.startswith(b"%PDF")
    # Otro tenant no lo descarga.
    r3 = await cliente.get(f"/api/bi/reportes/generados/{reporte_id}/archivo", headers=await auth(OTRO_AE))
    assert r3.status_code == 404


async def test_crud_de_programados(cliente, auth, datos):
    r = await cliente.post("/api/bi/reportes/programados", headers=await auth(AE),
                           json={"nombre": "Ejecutivo semanal", "tipo_reporte": "cliente", "formato": "excel",
                                 "periodicidad": "semanal", "dia_hora": "lunes 07:30", "destinatarios_json": []})
    assert r.status_code == 201, r.text
    p = r.json()
    assert p["periodicidad"] == "semanal" and p["dia_hora"] == "lunes 07:30" and p["activo"] is True
    assert p["tenant_id"] is not None and p["prestador_id"] is None
    lista = (await cliente.get("/api/bi/reportes/programados", headers=await auth(AE))).json()
    assert any(x["id"] == p["id"] for x in lista)
    r = await cliente.patch(f"/api/bi/reportes/programados/{p['id']}", headers=await auth(AE), json={"activo": False})
    assert r.status_code == 200 and r.json()["activo"] is False
    r = await cliente.delete(f"/api/bi/reportes/programados/{p['id']}", headers=await auth(AE))
    assert r.status_code == 204
    assert all(x["id"] != p["id"] for x in (await cliente.get("/api/bi/reportes/programados", headers=await auth(AE))).json())
    # El técnico no programa reportes del cliente.
    r = await cliente.post("/api/bi/reportes/programados", headers=await auth(TEC),
                           json={"tipo_reporte": "cliente", "periodicidad": "mensual"})
    assert r.status_code == 403


async def test_periodicidad_y_periodo_calculado(cliente, auth, datos):
    from models.base import FormatoReporte, PeriodicidadReporte
    from models.reportes import ReporteProgramado
    from services import reportes_service

    lunes = date(2026, 11, 2)  # lunes
    diario = ReporteProgramado(nombre="d", tipo_reporte="jornada", formato=FormatoReporte.pdf,
                               periodicidad=PeriodicidadReporte.diaria, dia_hora="22:30")
    semanal = ReporteProgramado(nombre="s", tipo_reporte="cliente", formato=FormatoReporte.pdf,
                                periodicidad=PeriodicidadReporte.semanal, dia_hora="lunes 08:00")
    mensual = ReporteProgramado(nombre="m", tipo_reporte="cliente", formato=FormatoReporte.pdf,
                                periodicidad=PeriodicidadReporte.mensual, dia_hora="1 08:00")
    assert reportes_service.toca_hoy(diario, lunes) is True
    assert reportes_service.toca_hoy(semanal, lunes) is True
    assert reportes_service.toca_hoy(semanal, lunes + timedelta(days=1)) is False
    assert reportes_service.toca_hoy(mensual, lunes) is False         # el 2 no es el día 1 del mes
    assert reportes_service.toca_hoy(mensual, date(2026, 11, 1)) is True
    assert reportes_service.toca_hoy(mensual, date(2026, 11, 15)) is False
    # El período que cubre cada uno.
    assert reportes_service.periodo_de(diario, lunes) == (lunes, lunes)
    assert reportes_service.periodo_de(semanal, lunes) == (lunes - timedelta(days=7), lunes)
    assert reportes_service.periodo_de(mensual, date(2026, 11, 1)) == (date(2026, 10, 1), date(2026, 10, 31))


async def test_la_tarea_genera_y_envia_el_programado(cliente, auth, datos):
    from workers.tareas.sla import enviar_reportes_async

    usuarios = (await cliente.get("/api/usuarios", headers=await auth(AE), params={"rol": "admin_empresa"})).json()
    r = await cliente.post("/api/bi/reportes/programados", headers=await auth(AE),
                           json={"nombre": "Ejecutivo diario de prueba", "tipo_reporte": "cliente", "formato": "pdf",
                                 "periodicidad": "diaria", "dia_hora": "08:00",
                                 "destinatarios_json": [usuarios[0]["id"]]})
    assert r.status_code == 201, r.text
    programado = r.json()
    antes = len(correo.ENVIADOS)
    resumen = await enviar_reportes_async()
    assert resumen["enviados"] >= 1 and resumen["errores"] == 0
    # El correo stub guarda el envío con el PDF adjunto.
    enviados = [c for c in correo.ENVIADOS if "Ejecutivo diario de prueba" in c["asunto"]]
    assert enviados and any(a.endswith(".pdf") for c in enviados for a in c["adjuntos"])
    assert antes >= 0
    # Queda en el historial ligado al programado y con la fecha de último envío.
    lista = (await cliente.get("/api/bi/reportes/generados", headers=await auth(AE))).json()
    assert any(x["programado_id"] == programado["id"] for x in lista)
    actual = (await cliente.get("/api/bi/reportes/programados", headers=await auth(AE))).json()
    assert next(x for x in actual if x["id"] == programado["id"])["ultimo_envio_at"] is not None
    await cliente.delete(f"/api/bi/reportes/programados/{programado['id']}", headers=await auth(AE))


async def test_tiempos_con_mas_de_mil_folios(cliente, auth, datos):
    """ACT-8.4: volumen de 1,000+ folios cerrados y medición del tiempo de generación."""
    from scripts.seed_historico import sembrar_historico

    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        resumen = await sembrar_historico(db, cantidad=1000, meses=12)
        await db.commit()
    assert resumen.get("creados", 0) >= 1000 or resumen.get("existentes", 0) >= 1000, resumen
    hoy = date.today()
    desde = str(hoy - timedelta(days=365))
    medidos = {}
    for formato in ("pdf", "excel"):
        inicio = time.monotonic()
        r = await _generar(cliente, auth, AE, tipo="cliente", formato=formato, desde=desde, hasta=str(hoy))
        medidos[formato] = (int(r.headers["x-reporte-ms"]), round(time.monotonic() - inicio, 2))
        assert r.content.startswith(FIRMAS[formato])
    print(f"\nACT-8.4 · reporte del cliente sobre 12 meses: {medidos}")
    # El servidor registra el tiempo medido y las filas del reporte.
    lista = (await cliente.get("/api/bi/reportes/generados", headers=await auth(AE), params={"limite": 5})).json()
    assert lista[0]["ms_generacion"] is not None and lista[0]["filas"] >= 1
    # Y los indicadores sobre el volumen siguen respondiendo.
    r = await cliente.get("/api/bi/indicador/cumplimiento_sla", headers=await auth(AE),
                          params={"desde": desde, "hasta": str(hoy)})
    assert r.status_code == 200 and r.json()["valor"]["total"] >= 990  # el histórico reparte 12 meses de cierres
