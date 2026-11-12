"""Revisión periódica, recálculo, ajuste manual, sincronización con `equipos.criticidad` e inmutabilidad del
historial de evaluaciones (ISO 55000, §6.9.3). F2-05."""
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select, text

from tests.criticidad_utiles import (
    configuracion, detalle, equipo_con_historia, evaluar, poner_configuracion, restaurar_configuracion,
    sembrar_fallas,
)
from tests.folios_utiles import AE, AP, AUN, DES, OTRO_AE


async def _equipo_en_db(equipo_id):
    from core.db import nueva_sesion
    from core.rls import CONTEXTO_SISTEMA
    from models.catalogos import Equipo
    import uuid

    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        return await db.get(Equipo, uuid.UUID(str(equipo_id)))


async def _evaluaciones(equipo_id):
    from core.db import nueva_sesion
    from core.rls import CONTEXTO_SISTEMA
    from models.criticidad import CriticidadEvaluacion
    import uuid

    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        return list((await db.execute(
            select(CriticidadEvaluacion).where(CriticidadEvaluacion.equipo_id == uuid.UUID(str(equipo_id)))
            .order_by(CriticidadEvaluacion.timestamp))).scalars())


async def test_cada_evaluacion_queda_en_el_historial(cliente, auth, datos):
    """La trazabilidad que pide una auditoría: quién, cuándo, de qué a qué y por qué."""
    equipo = await equipo_con_historia(cliente, auth, datos, fallas=3)
    await evaluar(cliente, auth, equipo["id"], 3, 3, 3, 3, razon="Evaluación inicial del parque")
    await evaluar(cliente, auth, equipo["id"], 5, 5, 5, 5, razon="Cambió el proceso de la sucursal",
                  motivo="cambio_configuracion")
    h = (await cliente.get(f"/api/criticidad/equipos/{equipo['id']}/historial",
                           headers=await auth(AE))).json()
    assert len(h) == 2
    ultima, primera = h[0], h[1]            # más reciente primero
    assert primera["nivel_anterior"] is None and primera["motivo"] == "evaluacion_inicial"
    assert ultima["nivel_anterior"] == primera["nivel_nuevo"] and ultima["motivo"] == "cambio_configuracion"
    assert ultima["razon"] == "Cambió el proceso de la sucursal"
    assert Decimal(ultima["indice_anterior"]) == Decimal(primera["indice_nuevo"])
    assert ultima["dimensiones_json"]["operacional"] == 5 and ultima["evaluado_por"] is not None


async def test_el_historial_es_append_only(cliente, auth, datos):
    """`criticidad_evaluaciones` no se edita ni se borra. Son tres cercos: la tabla solo tiene políticas de lectura
    e inserción (así que un UPDATE o un DELETE no encuentra ni una fila), `acma_api` no tiene el permiso de DELETE,
    y un trigger lo frena incluso para el dueño de la tabla."""
    from core.db import nueva_sesion
    from core.rls import CONTEXTO_SISTEMA

    equipo = await equipo_con_historia(cliente, auth, datos, fallas=3)
    await evaluar(cliente, auth, equipo["id"], 3, 3, 3, 3, razon="Evaluación original")
    fila = (await _evaluaciones(equipo["id"]))[0]
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        comandos = {p for (p,) in (await db.execute(text(
            "SELECT cmd FROM pg_policies WHERE tablename = 'criticidad_evaluaciones'"))).all()}
        assert comandos <= {"SELECT", "INSERT"}, comandos
        for sql in ("UPDATE criticidad_evaluaciones SET razon = 'editada' WHERE id = :id",
                    "DELETE FROM criticidad_evaluaciones WHERE id = :id"):
            try:
                r = await db.execute(text(sql), {"id": fila.id})
                assert r.rowcount == 0, sql     # la RLS no deja ni ver la fila para modificarla
            except Exception:
                await db.rollback()             # o el trigger la frena antes
        await db.commit()
    quedan = await _evaluaciones(equipo["id"])
    assert len(quedan) == 1 and quedan[0].razon == "Evaluación original"


async def test_el_recalculo_solo_escribe_si_cambia_el_nivel(cliente, auth, datos):
    """Si el índice se mueve de 51.60 a 55.00 no hace falta ensuciar la traza: solo el cambio de nivel se registra."""
    equipo = await equipo_con_historia(cliente, auth, datos, fallas=3)
    await evaluar(cliente, auth, equipo["id"], 5, 4, 4, 4)       # probabilidad 3 × 4.30 → 51.60, nivel B
    assert len(await _evaluaciones(equipo["id"])) == 1

    # Una falla más dentro de la misma banda (3–5): el índice no se mueve y no se escribe nada.
    await sembrar_fallas(equipo["id"], 1, desde_dias=40, hasta_dias=40)
    r = (await cliente.post(f"/api/criticidad/equipos/{equipo['id']}/recalcular",
                            headers=await auth(AE))).json()
    assert r["estado"] == "sin_cambio" and r["nivel"] == "B", r
    assert len(await _evaluaciones(equipo["id"])) == 1

    # Fallas suficientes para subir a la banda 12+: probabilidad 5 × 4.30 → 86.00, nivel A, y eso sí se registra.
    await sembrar_fallas(equipo["id"], 10, desde_dias=200, hasta_dias=30)
    r = (await cliente.post(f"/api/criticidad/equipos/{equipo['id']}/recalcular",
                            headers=await auth(AE))).json()
    assert r["estado"] == "cambio" and r["nivel_anterior"] == "B" and r["nivel"] == "A", r
    evaluaciones = await _evaluaciones(equipo["id"])
    assert len(evaluaciones) == 2
    assert evaluaciones[-1].motivo.value == "revision_periodica"
    assert evaluaciones[-1].nivel_anterior == "B" and evaluaciones[-1].nivel_nuevo == "A"
    # El recálculo no toca las dimensiones: las puso una persona.
    assert evaluaciones[-1].dimensiones_json["operacional"] == 5


async def test_el_cambio_de_nivel_avisa_al_prestador(cliente, auth, datos):
    """Un activo que se vuelve crítico cambia cómo hay que atenderlo: se le avisa a quien lo mantiene."""
    from services import notificaciones

    equipo = await equipo_con_historia(cliente, auth, datos, fallas=3)
    await evaluar(cliente, auth, equipo["id"], 5, 4, 4, 4)
    await sembrar_fallas(equipo["id"], 10, desde_dias=200, hasta_dias=30)
    await cliente.post(f"/api/criticidad/equipos/{equipo['id']}/recalcular", headers=await auth(AE))
    avisos = [n for n in notificaciones.ENVIADAS if n["datos"].get("equipo_id") == equipo["id"]]
    assert avisos, "el cambio de nivel no avisó a nadie"
    ultimo = avisos[-1]
    assert ultimo["datos"]["nivel_anterior"] == "B" and ultimo["datos"]["nivel_nuevo"] == "A"
    assert set(ultimo["roles"]) == {"admin_prestador", "despachador"}
    assert equipo["codigo"] in ultimo["titulo"]
    assert ultimo["datos"]["url"].endswith("vista=criticidad")


async def test_ajuste_manual_con_razon_obligatoria(cliente, auth, datos):
    """§6.9.3 deja ajustar el nivel a mano, pero la razón es lo que lee la auditoría."""
    equipo = await equipo_con_historia(cliente, auth, datos, fallas=3)
    await evaluar(cliente, auth, equipo["id"], 3, 3, 3, 3)
    r = await cliente.post(f"/api/criticidad/equipos/{equipo['id']}/ajuste", headers=await auth(AE),
                           json={"nivel": "A", "razon": "  "})
    assert r.status_code == 422, r.text
    r = await cliente.post(f"/api/criticidad/equipos/{equipo['id']}/ajuste", headers=await auth(AE),
                           json={"nivel": "Z", "razon": "Nivel inexistente"})
    assert r.status_code == 422, r.text
    # Solo el Admin empresa: ni el Admin UN ni el prestador fijan el nivel a mano.
    for email in (AUN, AP, DES):
        r = await cliente.post(f"/api/criticidad/equipos/{equipo['id']}/ajuste", headers=await auth(email),
                               json={"nivel": "A", "razon": "Lo decidió el comité"})
        assert r.status_code in (403, 404), (email, r.status_code)

    r = await cliente.post(f"/api/criticidad/equipos/{equipo['id']}/ajuste", headers=await auth(AE),
                           json={"nivel": "A", "razon": "Lo decidió el comité de mantenimiento de octubre"})
    assert r.status_code == 200, r.text
    fila = r.json()
    assert fila["nivel"] == "A" and fila["origen"] == "manual"
    assert fila["razon_manual"].startswith("Lo decidió el comité")
    # El índice calculado se conserva: el ajuste cambia el nivel, no finge un cálculo.
    assert Decimal(fila["indice_criticidad"]) == Decimal("36.00")
    evaluaciones = await _evaluaciones(equipo["id"])
    assert evaluaciones[-1].motivo.value == "ajuste_manual" and evaluaciones[-1].nivel_nuevo == "A"


async def test_el_recalculo_respeta_el_nivel_manual(cliente, auth, datos):
    """El ajuste se conserva hasta la próxima revisión: la tarea semanal no lo pisa."""
    equipo = await equipo_con_historia(cliente, auth, datos, fallas=3)
    await evaluar(cliente, auth, equipo["id"], 3, 3, 3, 3)
    await cliente.post(f"/api/criticidad/equipos/{equipo['id']}/ajuste", headers=await auth(AE),
                       json={"nivel": "A", "razon": "Decisión del comité"})
    await sembrar_fallas(equipo["id"], 12, desde_dias=200, hasta_dias=30)
    r = (await cliente.post(f"/api/criticidad/equipos/{equipo['id']}/recalcular",
                            headers=await auth(AE))).json()
    assert r["estado"] == "manual_vigente" and r["nivel"] == "A", r
    assert (await detalle(cliente, auth, equipo["id"]))["nivel"] == "A"
    # Volver a evaluar con dimensiones nuevas sí retoma el cálculo: es una decisión explícita de una persona.
    # Con las doce fallas sembradas la probabilidad es 5 y el impacto mínimo 1.00: el índice cae justo en 20.00,
    # la frontera de C.
    fila = await evaluar(cliente, auth, equipo["id"], 1, 1, 1, 1)
    assert fila["origen"] == "calculado" and fila["razon_manual"] == ""
    assert Decimal(fila["indice_criticidad"]) == Decimal("20.00") and fila["nivel"] == "C"


async def test_el_nivel_se_sincroniza_con_la_ficha_del_activo(cliente, auth, datos):
    """`equipos.criticidad` es el campo que lee la aprobación multinivel: la evaluación lo escribe."""
    equipo = await equipo_con_historia(cliente, auth, datos, fallas=12)
    assert (await _equipo_en_db(equipo["id"])).criticidad is None
    await evaluar(cliente, auth, equipo["id"], 5, 4, 4, 4)
    assert (await _equipo_en_db(equipo["id"])).criticidad == "A"
    ficha = (await cliente.get(f"/api/activos/{equipo['id']}", headers=await auth(AE))).json()
    assert ficha["equipo"]["criticidad"] == "A"
    # La ficha ya no etiqueta la criticidad como «Fase 2»: dice de dónde salió.
    assert ficha["equipo"]["criticidad_origen"] == "calculado (ISO 55000 §6.9.3)"
    assert not any("riticidad" in p or "FMEA" in p for p in ficha["fase_2"]), ficha["fase_2"]
    # Un ajuste manual la mueve igual.
    await cliente.post(f"/api/criticidad/equipos/{equipo['id']}/ajuste", headers=await auth(AE),
                       json={"nivel": "C", "razon": "Se reubicó a una bodega sin producto"})
    assert (await _equipo_en_db(equipo["id"])).criticidad == "C"


async def test_el_nivel_entra_a_la_aprobacion_multinivel(cliente, auth, datos):
    """La criticidad evaluada pesa en el nivel de entrada del flujo de aprobación, igual que el monto (P06)."""
    from services.aprobacion_service import nivel_entrada, regla_aplica
    from models.folios import AprobacionRegla, CriterioAprobacion, TipoFolio

    equipo = await equipo_con_historia(cliente, auth, datos, fallas=12)
    await evaluar(cliente, auth, equipo["id"], 5, 4, 4, 4)
    guardado = (await _equipo_en_db(equipo["id"])).criticidad
    regla = AprobacionRegla(nivel=3, criterio=CriterioAprobacion.criticidad,
                            valor_json={"valores": ["A", "B"]})
    assert regla_aplica(regla, monto=None, criticidad=guardado, tipo_folio=TipoFolio.correctivo)
    assert nivel_entrada([regla], monto=None, criticidad=guardado, tipo_folio=TipoFolio.correctivo) == 3
    assert nivel_entrada([regla], monto=None, criticidad="D", tipo_folio=TipoFolio.correctivo) is None


async def test_la_proxima_revision_sale_de_la_configuracion(cliente, auth, datos):
    equipo = await equipo_con_historia(cliente, auth, datos, fallas=3)
    try:
        fila = await evaluar(cliente, auth, equipo["id"])
        meses = (await configuracion(cliente, auth))["meses_revision"]
        assert fila["proxima_revision"] == str(date.today() + timedelta(days=30 * meses))
        await poner_configuracion(cliente, auth, {"meses_revision": 6})
        otra = await evaluar(cliente, auth, equipo["id"])
        assert otra["proxima_revision"] == str(date.today() + timedelta(days=180))
    finally:
        await restaurar_configuracion(cliente, auth)


async def test_revision_vencida_en_el_registro_y_en_el_resumen(cliente, auth, datos):
    """Una evaluación vieja deja de ser evidencia: el registro la marca y el resumen la cuenta."""
    from core.db import nueva_sesion
    from core.rls import CONTEXTO_SISTEMA
    import uuid

    equipo = await equipo_con_historia(cliente, auth, datos, fallas=3)
    await evaluar(cliente, auth, equipo["id"])
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        await db.execute(text("UPDATE activo_criticidad SET proxima_revision = :f WHERE equipo_id = :e"),
                         {"f": date.today() - timedelta(days=5), "e": uuid.UUID(equipo["id"])})
        await db.commit()
    vencidas = (await cliente.get("/api/criticidad", headers=await auth(AE),
                                  params={"solo_revision_vencida": True})).json()
    fila = next(f for f in vencidas if f["equipo_id"] == equipo["id"])
    assert fila["revision_vencida"] is True
    assert (await detalle(cliente, auth, equipo["id"]))["revision_vencida"] is True
    resumen = (await cliente.get("/api/criticidad/resumen", headers=await auth(AE))).json()
    assert resumen["revisiones_vencidas"] >= 1


async def test_alerta_de_revision_pendiente(cliente, auth, datos):
    """CRITICIDAD_REVISION_PENDIENTE: la revisión vencida se avisa una vez por activo."""
    from core.db import nueva_sesion
    from core.rls import CONTEXTO_SISTEMA
    from tests.criticidad_utiles import activar_implicacion
    from tests.operacion_utiles import alertas_de, evaluar as correr_evaluador
    import uuid

    equipo = await equipo_con_historia(cliente, auth, datos, fallas=3)
    await evaluar(cliente, auth, equipo["id"])
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        await db.execute(text("UPDATE activo_criticidad SET proxima_revision = :f WHERE equipo_id = :e"),
                         {"f": date.today() - timedelta(days=40), "e": uuid.UUID(equipo["id"])})
        await db.commit()
    await correr_evaluador("CRITICIDAD_REVISION_PENDIENTE")
    # La alerta se ancla a la fila de criticidad, no al equipo: se filtra por el equipo que trae en sus datos.
    mias = [a for a in await alertas_de("CRITICIDAD_REVISION_PENDIENTE")
            if a["datos"].get("equipo_id") == equipo["id"]]
    assert len(mias) == 1, mias
    assert mias[0]["datos"]["equipo_codigo"] == equipo["codigo"] and mias[0]["datos"]["dias"] >= 40
    # No se repite al día siguiente: una alerta por activo mientras siga pendiente.
    await correr_evaluador("CRITICIDAD_REVISION_PENDIENTE")
    assert len([a for a in await alertas_de("CRITICIDAD_REVISION_PENDIENTE")
                if a["datos"].get("equipo_id") == equipo["id"]]) == 1


async def test_recalculo_de_todo_el_parque(cliente, auth, datos):
    """Lo que corre la tarea semanal: recalcula lo que tiene evaluación y respeta los niveles manuales."""
    from core.db import nueva_sesion
    from core.rls import CONTEXTO_SISTEMA
    from services import criticidad_service

    equipo = await equipo_con_historia(cliente, auth, datos, fallas=3)
    await evaluar(cliente, auth, equipo["id"], 5, 4, 4, 4)
    manual = await equipo_con_historia(cliente, auth, datos, fallas=3)
    await evaluar(cliente, auth, manual["id"], 1, 1, 1, 1)
    await cliente.post(f"/api/criticidad/equipos/{manual['id']}/ajuste", headers=await auth(AE),
                       json={"nivel": "A", "razon": "Decisión del comité"})
    await sembrar_fallas(equipo["id"], 10, desde_dias=200, hasta_dias=30)

    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        r = await criticidad_service.recalcular_todos(db)
        await db.commit()
    assert r["revisados"] >= 2 and r["cambios"] >= 1 and r["manuales"] >= 1
    assert (await detalle(cliente, auth, equipo["id"]))["nivel"] == "A"
    assert (await detalle(cliente, auth, manual["id"]))["origen"] == "manual"


async def test_el_historial_no_se_ve_entre_clientes(cliente, auth, datos):
    equipo = await equipo_con_historia(cliente, auth, datos, fallas=3)
    await evaluar(cliente, auth, equipo["id"])
    assert (await cliente.post(f"/api/criticidad/equipos/{equipo['id']}/recalcular",
                               headers=await auth(OTRO_AE))).status_code == 404
    assert (await cliente.post(f"/api/criticidad/equipos/{equipo['id']}/ajuste", headers=await auth(OTRO_AE),
                               json={"nivel": "A", "razon": "Ajuste ajeno"})).status_code == 404
