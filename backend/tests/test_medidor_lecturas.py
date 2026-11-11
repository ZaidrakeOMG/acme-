"""Lecturas de medidor (§6.9.2): los cuatro métodos, validación de anomalías (menor, salto, futura, duplicada),
bandeja de revisión con aprobación y rechazo, inmutabilidad de la medición, estimación diaria y su corrección con
una lectura real, y la lectura registrada sin señal por la cola de mutaciones. F2-04."""
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select, text

from core.db import nueva_sesion
from core.rls import CONTEXTO_SISTEMA
from tests.folios_utiles import AE, AP, AUN, DES, MC, OP, TEC
from tests.medidores_utiles import equipo_con_medidor, estado_medidor, lectura
from tests.sla_utiles import panel_alertas


async def _estimacion(cliente, auth, medidor, **cuerpo):
    r = await cliente.put(f"/api/medidores/{medidor['id']}/estimacion", headers=await auth(AP), json=cuerpo)
    assert r.status_code == 200, r.text
    return r.json()


async def test_lectura_valida_mueve_el_medidor(cliente, auth, datos):
    equipo, medidor, _tipo = await equipo_con_medidor(cliente, auth, datos)
    r = await lectura(cliente, auth, medidor, "120.5", email=OP, dias_atras=1)
    assert r["duplicada"] is False and r["anomalia"] == "" and r["lectura"]["estado"] == "valida"
    assert Decimal(r["lectura"]["valor_acumulado"]) == Decimal("120.5")
    resumen = (await estado_medidor(cliente, auth, equipo["id"]))[0]
    assert Decimal(resumen["valor_actual"]) == Decimal("120.5") and resumen["fecha_ultima_lectura"] is not None
    # El método del medidor manda si la lectura no lo dice; también se puede forzar.
    r = await lectura(cliente, auth, medidor, "130", email=TEC, metodo="tecnico", dias_atras=0.5)
    assert r["lectura"]["metodo"] == "tecnico"


async def test_lectura_menor_queda_en_revision_y_alerta(cliente, auth, datos):
    _equipo, medidor, _tipo = await equipo_con_medidor(cliente, auth, datos)
    await lectura(cliente, auth, medidor, "500", dias_atras=3)
    r = await lectura(cliente, auth, medidor, "400", dias_atras=1)
    assert r["lectura"]["estado"] == "en_revision" and "por debajo" in r["anomalia"]
    assert r["folios_generados"] == []
    # El medidor NO se movió: una lectura en revisión no cuenta hasta que alguien la apruebe.
    assert Decimal((await estado_medidor(cliente, auth, _equipo["id"]))[0]["valor_actual"]) == 500
    claves = [a["clave_alerta"] for a in await panel_alertas(cliente, auth, DES)]
    assert "MEDIDOR_LECTURA_ANOMALA" in claves
    # Y aparece en la bandeja con el valor anterior para comparar.
    bandeja = (await cliente.get("/api/medidores/lecturas/por-revisar", headers=await auth(DES))).json()
    fila = next(x for x in bandeja if x["id"] == r["lectura"]["id"])
    assert Decimal(fila["valor"]) == 400 and Decimal(fila["valor_anterior"]) == 500


async def test_salto_mayor_al_esperado_queda_en_revision(cliente, auth, datos):
    _equipo, medidor, _tipo = await equipo_con_medidor(cliente, auth, datos)
    await _estimacion(cliente, auth, medidor, incremento_por_dia="10", activa=False)
    await lectura(cliente, auth, medidor, "100", dias_atras=2)
    # Un día después, +200 h cuando lo esperado son 10 h/día (tolerancia 3×).
    r = await lectura(cliente, auth, medidor, "300", dias_atras=1)
    assert r["lectura"]["estado"] == "en_revision" and "salto" in r["anomalia"].lower()
    # Con el factor del tipo en 30× el mismo salto pasa: el umbral es configurable por tipo de medidor.
    assert (await cliente.put(f"/api/medidores/tipos/{_tipo['id']}", headers=await auth(AP),
                              json={"factor_salto_maximo": "30"})).status_code == 200
    r = await lectura(cliente, auth, medidor, "280", dias_atras=0.5)
    assert r["lectura"]["estado"] == "valida", r


async def test_lectura_futura_se_rechaza(cliente, auth, datos):
    _equipo, medidor, _tipo = await equipo_con_medidor(cliente, auth, datos)
    futuro = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    r = await cliente.post("/api/medidores/lecturas", headers=await auth(AP),
                           json={"equipo_medidor_id": medidor["id"], "valor": "10", "timestamp_dispositivo": futuro})
    assert r.status_code == 422 and r.json()["codigo"] == "LECTURA_FUTURA", r.text
    # Una lectura por encima del tope del marcador también: hay que registrar el reinicio.
    r2 = await cliente.put(f"/api/medidores/{medidor['id']}", headers=await auth(AP), json={"valor_maximo": "1000"})
    assert r2.status_code == 200
    r = await lectura(cliente, auth, medidor, "1500", esperado=422)
    assert r["codigo"] == "VALOR_SOBRE_MAXIMO"


async def test_lectura_duplicada_es_idempotente(cliente, auth, datos):
    """Lo necesitan la cola sin señal y la importación: reenviar lo mismo no duplica."""
    _equipo, medidor, _tipo = await equipo_con_medidor(cliente, auth, datos)
    momento = (datetime.now(UTC) - timedelta(hours=5)).isoformat()
    cuerpo = {"equipo_medidor_id": medidor["id"], "valor": "77", "timestamp_dispositivo": momento}
    primera = (await cliente.post("/api/medidores/lecturas", headers=await auth(AP), json=cuerpo)).json()
    segunda = (await cliente.post("/api/medidores/lecturas", headers=await auth(AP), json=cuerpo)).json()
    assert primera["duplicada"] is False and segunda["duplicada"] is True
    assert segunda["lectura"]["id"] == primera["lectura"]["id"]
    lecturas = (await cliente.get(f"/api/medidores/lecturas?equipo_medidor_id={medidor['id']}",
                                  headers=await auth(AP))).json()
    assert len([x for x in lecturas if Decimal(x["valor"]) == 77]) == 1


async def test_aprobar_lectura_anomala_la_aplica(cliente, auth, datos):
    _equipo, medidor, _tipo = await equipo_con_medidor(cliente, auth, datos, valor_maximo="1000")
    await lectura(cliente, auth, medidor, "900", dias_atras=3)
    anomala = await lectura(cliente, auth, medidor, "20", dias_atras=2)   # el marcador dio la vuelta sin registrarse
    assert anomala["lectura"]["estado"] == "en_revision"
    # Se registra el reinicio que faltaba y se aprueba: el acumulado se recalcula con el estado actual del medidor.
    assert (await cliente.post(f"/api/medidores/{medidor['id']}/cambios", headers=await auth(AP),
                               json={"tipo": "reinicio", "valor_nuevo": "0",
                                     "motivo": "El marcador dio la vuelta el martes"})).status_code == 201
    r = await cliente.post(f"/api/medidores/lecturas/{anomala['lectura']['id']}/revision", headers=await auth(DES),
                           json={"aprobar": True, "razon": "El marcador dio la vuelta; reinicio ya registrado"})
    assert r.status_code == 200, r.text
    assert r.json()["lectura"]["estado"] == "valida" and Decimal(r.json()["lectura"]["valor_acumulado"]) == 920
    assert Decimal((await estado_medidor(cliente, auth, _equipo["id"]))[0]["valor_acumulado"]) == 920
    # Ya resuelta, no se vuelve a resolver.
    r = await cliente.post(f"/api/medidores/lecturas/{anomala['lectura']['id']}/revision", headers=await auth(DES),
                           json={"aprobar": False, "razon": "otra vez"})
    assert r.status_code == 409 and r.json()["codigo"] == "LECTURA_YA_RESUELTA"


async def test_rechazar_lectura_exige_razon_y_no_mueve_el_medidor(cliente, auth, datos):
    _equipo, medidor, _tipo = await equipo_con_medidor(cliente, auth, datos)
    await lectura(cliente, auth, medidor, "300", dias_atras=3)
    anomala = await lectura(cliente, auth, medidor, "10", dias_atras=1)
    r = await cliente.post(f"/api/medidores/lecturas/{anomala['lectura']['id']}/revision", headers=await auth(AP),
                           json={"aprobar": False, "razon": ""})
    assert r.status_code == 422 and r.json()["codigo"] == "RAZON_REQUERIDA"
    r = await cliente.post(f"/api/medidores/lecturas/{anomala['lectura']['id']}/revision", headers=await auth(AP),
                           json={"aprobar": False, "razon": "El operador capturó el número de serie en lugar del horómetro"})
    assert r.status_code == 200 and r.json()["lectura"]["estado"] == "rechazada"
    assert Decimal((await estado_medidor(cliente, auth, _equipo["id"]))[0]["valor_actual"]) == 300
    # Solo el Despachador y el Admin prestador revisan (§6.9.2).
    otra = await lectura(cliente, auth, medidor, "5", dias_atras=0.5)
    for email in (OP, AUN, MC):
        r = await cliente.post(f"/api/medidores/lecturas/{otra['lectura']['id']}/revision", headers=await auth(email),
                               json={"aprobar": True, "razon": "ok"})
        assert r.status_code == 403, (email, r.text)


async def test_la_medicion_es_inmutable(cliente, auth, datos):
    """Append-only con una excepción: la revisión. El valor, el método y la hora no se pueden cambiar nunca."""
    _equipo, medidor, _tipo = await equipo_con_medidor(cliente, auth, datos)
    r = await lectura(cliente, auth, medidor, "42", dias_atras=1)
    lectura_id = r["lectura"]["id"]
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        try:
            await db.execute(text("UPDATE medidor_lecturas SET valor = 999 WHERE id = :i"), {"i": lectura_id})
            await db.flush()
            fallo = False
        except Exception as e:  # noqa: BLE001
            fallo = "inmutab" in str(e).lower() or "no se modifica" in str(e).lower()
            await db.rollback()
        assert fallo, "El trigger debía rechazar el cambio del valor de una lectura"
        try:
            await db.execute(text("DELETE FROM medidor_lecturas WHERE id = :i"), {"i": lectura_id})
            await db.flush()
            fallo_borrado = False
        except Exception:  # noqa: BLE001
            fallo_borrado = True
            await db.rollback()
        assert fallo_borrado, "Las lecturas no se borran"
        # El estado sí se puede mover: es la revisión.
        await db.execute(text("UPDATE medidor_lecturas SET estado = 'rechazada', motivo = 'prueba' WHERE id = :i"),
                         {"i": lectura_id})
        await db.rollback()


async def test_estimacion_diaria_y_correccion_con_lectura_real(cliente, auth, datos):
    """§6.9.2 «Cálculo estimado»: la tarea suma el incremento de los días de operación; una lectura real corrige lo
    estimado y recalcula el incremento real promedio."""
    from models.medidores import EquipoMedidor, EstadoLecturaMedidor, MedidorLectura
    from services import medidores_service

    _equipo, medidor, _tipo = await equipo_con_medidor(cliente, auth, datos, metodo_actualizacion="estimado")
    est = await _estimacion(cliente, auth, medidor, incremento_por_dia="8", activa=True,
                            horario_operacion_json={"dias": ["lunes", "martes", "miercoles", "jueves", "viernes",
                                                             "sabado", "domingo"], "horas_por_dia": 8},
                            desde=(datetime.now(UTC) - timedelta(days=5)).date().isoformat())
    assert Decimal(est["incremento_por_dia"]) == 8 and est["activa"] is True
    await lectura(cliente, auth, medidor, "100", metodo="tecnico", dias_atras=4)

    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        resumen = await medidores_service.estimar_dia(db)
        await db.commit()
        assert resumen["estimadas"] >= 1, resumen
        fila = (await db.execute(select(EquipoMedidor).where(EquipoMedidor.id == uuid.UUID(medidor["id"])))).scalar_one()
        # 4 días de operación × 8 h = 32 h sobre las 100 reales.
        assert Decimal(fila.valor_actual) == Decimal("132.00"), fila.valor_actual
        # Idempotente: si ya estimó hoy, no vuelve a escribir.
        otra = await medidores_service.estimar_dia(db)
        await db.commit()
        assert otra["estimadas"] == 0

    # Lectura real posterior: corrige el estimado (queda rechazado, no borrado) y recalcula el promedio real.
    real = await lectura(cliente, auth, medidor, "150", metodo="tecnico")
    assert real["lectura"]["estado"] == "valida"
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        estimadas = (await db.execute(select(MedidorLectura).where(
            MedidorLectura.equipo_medidor_id == uuid.UUID(medidor["id"]),
            MedidorLectura.metodo == "estimado"))).scalars().all()
        assert estimadas and all(x.estado == EstadoLecturaMedidor.rechazada for x in estimadas)
        assert all("Corregida por la lectura real" in x.motivo for x in estimadas)
    resumen = (await estado_medidor(cliente, auth, _equipo["id"]))[0]
    assert Decimal(resumen["valor_actual"]) == 150
    # 50 h en 4 días de operación = 12.5 h/día reales contra las 8 estimadas: eso es lo que muestra la pantalla.
    assert Decimal(resumen["estimacion"]["incremento_real_promedio"]) == Decimal("12.5000")


async def test_lectura_sin_senal_por_la_cola_de_mutaciones(cliente, auth, datos):
    """§6.2: el técnico y el operador leen el marcador sin red; la cola la aplica con la hora del dispositivo."""
    _equipo, medidor, _tipo = await equipo_con_medidor(cliente, auth, datos)
    momento = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    id_cliente = str(uuid.uuid4())
    cuerpo = {"dispositivo_id": "disp-medidor", "version_app": "0.5", "plataforma": "android", "mutaciones": [
        {"id_cliente": id_cliente, "tipo": "registrar_lectura", "timestamp_dispositivo": momento,
         "payload": {"equipo_medidor_id": medidor["id"], "valor": "88"}}]}
    r = await cliente.post("/api/sync/mutaciones", headers=await auth(TEC), json=cuerpo)
    assert r.status_code == 200, r.text
    assert r.json()[0]["resultado"] == "aplicada", r.json()
    assert Decimal((await estado_medidor(cliente, auth, _equipo["id"]))[0]["valor_actual"]) == 88
    # Reenviar la misma mutación no duplica (bitácora idempotente de P05).
    r = await cliente.post("/api/sync/mutaciones", headers=await auth(TEC), json=cuerpo)
    assert r.json()[0]["resultado"] == "duplicada"
    # Y el paquete de catálogos del operador trae sus medidores para que la pantalla funcione sin red.
    paquete = (await cliente.get("/api/sync/catalogos?dispositivo_id=disp-medidor", headers=await auth(OP))).json()
    assert "medidores" in paquete and any(m["equipo_medidor_id"] == medidor["id"] for m in paquete["medidores"])


async def test_filtros_de_lecturas_y_aislamiento_de_la_bandeja(cliente, auth, datos):
    _equipo, medidor, _tipo = await equipo_con_medidor(cliente, auth, datos)
    await lectura(cliente, auth, medidor, "10", dias_atras=5)
    await lectura(cliente, auth, medidor, "20", dias_atras=3)
    todas = (await cliente.get(f"/api/medidores/lecturas?equipo_id={_equipo['id']}", headers=await auth(AE))).json()
    assert len(todas) == 2 and [Decimal(x["valor"]) for x in todas] == [20, 10]   # más reciente primero
    validas = (await cliente.get(f"/api/medidores/lecturas?equipo_medidor_id={medidor['id']}&estado=valida",
                                 headers=await auth(AP))).json()
    assert len(validas) == 2
    desde = (datetime.now(UTC) - timedelta(days=4)).date().isoformat()
    recientes = (await cliente.get(f"/api/medidores/lecturas?equipo_medidor_id={medidor['id']}&desde={desde}",
                                   headers=await auth(AP))).json()
    assert len(recientes) == 1 and Decimal(recientes[0]["valor"]) == 20
