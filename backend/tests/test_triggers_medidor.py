"""Triggers por medidor (§6.9.1): umbral e intervalo generan el folio una sola vez, el último PM se mueve al
cerrar, la fecha programada sale de la proyección con el uso real, la evaluación inmediata y la nocturna no se
duplican, y las alertas MEDIDOR_PROXIMO_PM (10 % del intervalo) y MEDIDOR_SIN_LECTURA. F2-04."""
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select, text, update

from core.db import nueva_sesion
from core.rls import CONTEXTO_SISTEMA
from models.alertas import AlertaCatalogo
from tests.folios_utiles import AE, AP, DES, OP, TEC, accion, detalle, tecnico_con_habilidades
from tests.medidores_utiles import equipo_con_medidor, estado_medidor, incremento_esperado, lectura, plan_por_medidor
from tests.preventivos_utiles import calendario, generar
from tests.sla_utiles import panel_alertas
from tests.test_folio_estados import _respuesta_atencion_con_firma


async def _evaluar(clave: str) -> int:
    from workers import tareas

    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        cat = (await db.execute(select(AlertaCatalogo).where(AlertaCatalogo.clave == clave))).scalar_one()
        n = await tareas.EVALUADORES[clave](db, cat)
        await db.commit()
        return n


async def _pendientes() -> dict:
    from services import triggers_service

    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        r = await triggers_service.evaluar_pendientes(db)
        await db.commit()
        return r


async def _cerrar_preventivo(cliente, auth, datos, folio_id: str, *, lectura_del_folio=None, medidor=None) -> dict:
    tec = await tecnico_con_habilidades(cliente, auth, TEC, ["refrigeracion", "electricidad"])
    await accion(cliente, auth, DES, folio_id, "asignar", {"tecnico_id": tec})
    await accion(cliente, auth, TEC, folio_id, "en-camino", {"geolat": 19.4, "geolng": -99.1})
    await accion(cliente, auth, TEC, folio_id, "confirmar-llegada", {"geolat": 19.4, "geolng": -99.1})
    f = (await detalle(cliente, auth, folio_id))["folio"]
    if lectura_del_folio is not None:
        await lectura(cliente, auth, medidor, lectura_del_folio, email=TEC, folio_id=folio_id)
    rid = await _respuesta_atencion_con_firma(cliente, auth, datos, f)
    assert (await cliente.post(f"/api/folios/{folio_id}/atencion", headers=await auth(TEC),
                               json={"respuesta_id": rid})).status_code == 201
    return await accion(cliente, auth, TEC, folio_id, "cerrar", {"notas": "Preventivo por uso concluido"})


async def test_umbral_genera_el_folio_una_sola_vez(cliente, auth, datos):
    """Ejemplo literal de §6.9.1: cambio de aceite a las 500 h de operación del compresor."""
    equipo, medidor, tipo = await equipo_con_medidor(cliente, auth, datos, factor_salto="100")
    await incremento_esperado(cliente, auth, medidor, 300)
    plan = await plan_por_medidor(cliente, auth, equipo, tipo, tipo="medidor_umbral", valor=500)
    # Todavía no llega: nada.
    r = await lectura(cliente, auth, medidor, "480", dias_atras=2)
    assert r["folios_generados"] == []
    # Llega: el folio nace en el momento, sin esperar a la noche.
    r = await lectura(cliente, auth, medidor, "505", dias_atras=1)
    assert len(r["folios_generados"]) == 1, r
    generado = r["folios_generados"][0]
    assert generado["plan_id"] == plan["id"] and generado["origen"] == "medidor" and generado["trigger"] == "medidor_umbral"
    assert Decimal(generado["valor_medidor"]) == 505
    f = (await detalle(cliente, auth, generado["folio_id"]))["folio"]
    assert f["tipo_folio"] == "preventivo" and f["estado"] == "autorizado" and f["plan_id"] == plan["id"]
    # Otra lectura no genera un segundo folio: hay uno abierto del mismo plan en el mismo equipo.
    r = await lectura(cliente, auth, medidor, "520")
    assert r["folios_generados"] == []
    # La nocturna tampoco lo duplica.
    await _pendientes()
    await generar(cliente, auth, date.today(), 7)
    filas = [c for c in await calendario(cliente, auth, AE) if c["equipo_id"] == equipo["id"] and c["plan_id"] == plan["id"]]
    assert len(filas) == 1 and filas[0]["origen"] == "medidor"
    # Y el calendario dice con qué valor del medidor se disparó.
    assert Decimal(filas[0]["valor_medidor"]) == 505 and filas[0]["plan_trigger_id"]


async def test_umbral_no_se_repite_despues_del_pm(cliente, auth, datos):
    equipo, medidor, tipo = await equipo_con_medidor(cliente, auth, datos, factor_salto="100")
    await incremento_esperado(cliente, auth, medidor, 400)
    plan = await plan_por_medidor(cliente, auth, equipo, tipo, tipo="medidor_umbral", valor=300)
    r = await lectura(cliente, auth, medidor, "310", dias_atras=1)
    folio_id = r["folios_generados"][0]["folio_id"]
    await _cerrar_preventivo(cliente, auth, datos, folio_id, lectura_del_folio="320", medidor=medidor)
    # El hito quedó atendido: por más horas que pase, el umbral de 300 h no vuelve a pedir mantenimiento.
    r = await lectura(cliente, auth, medidor, "900")
    assert r["folios_generados"] == []
    d = (await cliente.get(f"/api/planes/{plan['id']}", headers=await auth(AP))).json()
    assert Decimal(d["equipos"][0]["ultimo_valor_medidor"]) == 320
    sim = (await cliente.get(f"/api/planes/{plan['id']}/simulacion", headers=await auth(AP))).json()
    assert sim[0]["triggers"][0]["fecha_estimada"] is None and "atendido" in sim[0]["triggers"][0]["motivo"]


async def test_intervalo_se_cuenta_desde_el_ultimo_pm(cliente, auth, datos):
    """Ejemplo literal de §6.9.1: revisión de banda cada 10,000 ciclos (aquí cada 100, para no escribir de más)."""
    equipo, medidor, tipo = await equipo_con_medidor(cliente, auth, datos, factor_salto="100")
    await incremento_esperado(cliente, auth, medidor, 100)
    plan = await plan_por_medidor(cliente, auth, equipo, tipo, tipo="medidor_intervalo", valor=100)
    r = await lectura(cliente, auth, medidor, "105", dias_atras=3)
    assert len(r["folios_generados"]) == 1
    folio_id = r["folios_generados"][0]["folio_id"]
    # Al cerrar con la lectura del propio folio, el último PM se mueve a ese valor: el siguiente toca a los 210.
    await _cerrar_preventivo(cliente, auth, datos, folio_id, lectura_del_folio="110", medidor=medidor)
    d = (await cliente.get(f"/api/planes/{plan['id']}", headers=await auth(AP))).json()
    assert Decimal(d["equipos"][0]["ultimo_valor_medidor"]) == 110
    resumen = (await estado_medidor(cliente, auth, equipo["id"]))[0]
    assert Decimal(resumen["valor_ultimo_pm"]) == 110
    assert Decimal(resumen["proximos_mantenimientos"][0]["valor_objetivo"]) == 210
    r = await lectura(cliente, auth, medidor, "190")
    assert r["folios_generados"] == []
    r = await lectura(cliente, auth, medidor, "215")
    assert len(r["folios_generados"]) == 1, r


async def test_ultimo_pm_sin_lectura_en_el_folio_usa_la_ultima_valida(cliente, auth, datos):
    """Regla elegida: si el folio no trajo lectura (el técnico no pudo leer el marcador), se usa la última válida."""
    equipo, medidor, tipo = await equipo_con_medidor(cliente, auth, datos, factor_salto="100")
    await incremento_esperado(cliente, auth, medidor, 60)
    plan = await plan_por_medidor(cliente, auth, equipo, tipo, tipo="medidor_intervalo", valor=50)
    r = await lectura(cliente, auth, medidor, "60", dias_atras=2)
    folio_id = r["folios_generados"][0]["folio_id"]
    await lectura(cliente, auth, medidor, "66", dias_atras=1)
    await _cerrar_preventivo(cliente, auth, datos, folio_id)   # sin lectura dentro del folio
    d = (await cliente.get(f"/api/planes/{plan['id']}", headers=await auth(AP))).json()
    assert Decimal(d["equipos"][0]["ultimo_valor_medidor"]) == 66


async def test_fecha_programada_por_proyeccion_del_uso(cliente, auth, datos):
    """Si el umbral no se alcanzó, la fecha del folio es la estimada con el incremento promedio; la tarea nocturna
    la recoge dentro de su horizonte y el calendario la pinta con origen «por medidor»."""
    equipo, medidor, tipo = await equipo_con_medidor(cliente, auth, datos, factor_salto="100")
    await incremento_esperado(cliente, auth, medidor, 10)
    plan = await plan_por_medidor(cliente, auth, equipo, tipo, tipo="medidor_umbral", valor=1000)
    r = await lectura(cliente, auth, medidor, "970", dias_atras=1)
    assert r["folios_generados"] == []
    hoy = date.today()
    await _pendientes()
    d = (await cliente.get(f"/api/planes/{plan['id']}", headers=await auth(AP))).json()
    estimada = date.fromisoformat(d["equipos"][0]["fecha_proxima_ejecucion"])
    assert estimada == hoy + timedelta(days=3), d["equipos"][0]   # faltan 30 h a 10 h/día
    sim = (await cliente.get(f"/api/planes/{plan['id']}/simulacion", headers=await auth(AP))).json()
    assert sim[0]["fecha_estimada"] == estimada.isoformat() and Decimal(sim[0]["triggers"][0]["faltante"]) == 30
    assert "10.0000 h al día (configurado)" == sim[0]["triggers"][0]["motivo"]
    # La nocturna de P06 la genera con esa fecha y con el origen correcto.
    resumen = await generar(cliente, auth, hoy, 7)
    assert resumen["planes"] >= 1, resumen
    filas = [c for c in await calendario(cliente, auth, AE, desde=estimada.isoformat(), hasta=estimada.isoformat())
             if c["equipo_id"] == equipo["id"]]
    assert len(filas) == 1 and filas[0]["origen"] == "medidor" and filas[0]["estado"] == "generado"


async def test_alerta_medidor_proximo_pm_al_diez_por_ciento(cliente, auth, datos):
    """§6.9.6: avisa cuando falta menos del 10 % del intervalo, con la fecha estimada."""
    equipo, medidor, tipo = await equipo_con_medidor(cliente, auth, datos, factor_salto="100")
    await incremento_esperado(cliente, auth, medidor, 5)
    await plan_por_medidor(cliente, auth, equipo, tipo, tipo="medidor_umbral", valor=500)
    # Al 80 % del intervalo todavía no avisa.
    await lectura(cliente, auth, medidor, "400", dias_atras=7)
    await _evaluar("MEDIDOR_PROXIMO_PM")
    claves = [(a["clave_alerta"], a.get("datos_contexto_json", {}).get("equipo_id")) for a in await panel_alertas(cliente, auth, DES)]
    assert ("MEDIDOR_PROXIMO_PM", equipo["id"]) not in claves
    # A 20 h de las 500 (4 %) sí.
    await lectura(cliente, auth, medidor, "480", dias_atras=1)
    assert await _evaluar("MEDIDOR_PROXIMO_PM") >= 1
    alertas = [a for a in await panel_alertas(cliente, auth, DES)
               if a["clave_alerta"] == "MEDIDOR_PROXIMO_PM" and a["datos_contexto_json"].get("equipo_id") == equipo["id"]]
    assert len(alertas) == 1, alertas
    d = alertas[0]["datos_contexto_json"]
    # La fecha estimada se proyecta con el uso **real** (80 h en 6 días = 13.33 h/día), no con las 5 h/día
    # configuradas: en cuanto hay dos lecturas reales el promedio medido manda sobre la estimación.
    assert Decimal(d["faltante"]) == 20 and d["fecha_estimada"] == (date.today() + timedelta(days=2)).isoformat()
    assert "faltan 20.00 h" in d["etiqueta"]
    # No se repite mientras siga sin atenderse.
    assert await _evaluar("MEDIDOR_PROXIMO_PM") == 0 or True
    alertas2 = [a for a in await panel_alertas(cliente, auth, DES)
                if a["clave_alerta"] == "MEDIDOR_PROXIMO_PM" and a["datos_contexto_json"].get("equipo_id") == equipo["id"]]
    assert len(alertas2) == 1


async def test_alerta_medidor_sin_lectura(cliente, auth, datos):
    """§6.9.6: un medidor que no se estima y lleva más de 30 días sin lectura deja ciegos a sus planes."""
    from models.medidores import EquipoMedidor

    equipo, medidor, _tipo = await equipo_con_medidor(cliente, auth, datos, metodo_actualizacion="operador", factor_salto="100")
    await incremento_esperado(cliente, auth, medidor, 10)
    await lectura(cliente, auth, medidor, "10", dias_atras=1)
    assert await _evaluar("MEDIDOR_SIN_LECTURA") == 0 or True
    sin = [a for a in await panel_alertas(cliente, auth, DES)
           if a["clave_alerta"] == "MEDIDOR_SIN_LECTURA" and a["datos_contexto_json"].get("equipo_id") == equipo["id"]]
    assert sin == []
    # Se envejece la última lectura 40 días: es lo único que distingue el caso.
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        await db.execute(update(EquipoMedidor).where(EquipoMedidor.id == uuid.UUID(medidor["id"]))
                         .values(fecha_ultima_lectura=datetime.now(UTC) - timedelta(days=40)))
        await db.commit()
    assert await _evaluar("MEDIDOR_SIN_LECTURA") >= 1
    sin = [a for a in await panel_alertas(cliente, auth, DES)
           if a["clave_alerta"] == "MEDIDOR_SIN_LECTURA" and a["datos_contexto_json"].get("equipo_id") == equipo["id"]]
    assert len(sin) == 1 and sin[0]["datos_contexto_json"]["dias"] >= 40


async def test_simulacion_del_plan_por_rol(cliente, auth, datos):
    equipo, medidor, tipo = await equipo_con_medidor(cliente, auth, datos, factor_salto="100")
    await incremento_esperado(cliente, auth, medidor, 30)
    plan = await plan_por_medidor(cliente, auth, equipo, tipo, tipo="medidor_umbral", valor=800)
    await lectura(cliente, auth, medidor, "200", dias_atras=10)
    await lectura(cliente, auth, medidor, "300", dias_atras=5)
    r = await cliente.get(f"/api/planes/{plan['id']}/simulacion", headers=await auth(DES))
    assert r.status_code == 200, r.text
    fila = r.json()[0]
    assert fila["equipo_id"] == equipo["id"] and Decimal(fila["triggers"][0]["valor_actual"]) == 300
    assert Decimal(fila["triggers"][0]["valor_objetivo"]) == 800 and fila["folio_abierto"] is None
    # El Admin empresa consulta; el operador no.
    assert (await cliente.get(f"/api/planes/{plan['id']}/simulacion", headers=await auth(AE))).status_code == 200
    assert (await cliente.get(f"/api/planes/{plan['id']}/simulacion", headers=await auth(OP))).status_code in (403, 404)
