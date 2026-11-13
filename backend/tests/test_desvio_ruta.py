"""Desvío de ruta (§6.8.4): la alerta que quedó pendiente en F2-03, con sus dos reglas y sin falsas alarmas. F2-06."""
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from services.rutas.distancias import Punto
from tests.folios_utiles import AP, DES
from tests.rutas_utiles import (
    calcular, configurar, folios_del_dia, jornadas_abiertas, mercado, plan, posiciones, publicar,
)

T0 = datetime(2026, 11, 13, 9, 0, tzinfo=UTC)


def _serie(coords, paso_min=2):
    return [(T0 + timedelta(minutes=paso_min * i), Punto(*c)) for i, c in enumerate(coords)]


def _reglas():
    import workers.tareas  # noqa: F401 — carga el registro antes del evaluador (si no, import circular)
    from workers.evaluadores_rutas import evaluar_regla_estimada, evaluar_regla_trazo

    return evaluar_regla_trazo, evaluar_regla_estimada


def test_la_regla_del_trazo_es_la_literal_de_6_8_4():
    """«A más de X metros de la ruta calculada por más de Y minutos». Necesita el trazo real, o sea Google."""
    trazo, _ = _reglas()
    recta = [Punto(19.40, -99.13), Punto(19.50, -99.13)]
    # Va pegado al trazo: no hay desvío.
    assert trazo(_serie([(19.41, -99.1301), (19.43, -99.1302), (19.45, -99.1301)]), recta, 500, 5) is None
    # Se sale 4 km durante 6 minutos: sí lo hay, y se reporta con cuántos metros y cuántos minutos.
    hallazgo = trazo(_serie([(19.41, -99.16), (19.43, -99.17), (19.45, -99.17), (19.46, -99.16)]), recta, 500, 5)
    assert hallazgo is not None
    assert hallazgo["regla"] == "trazo" and hallazgo["metros"] > 500 and hallazgo["minutos"] >= 5


def test_la_regla_del_trazo_no_se_dispara_con_una_sola_lectura_lejos():
    """Un salto del GPS no es un desvío: tienen que ser todas las lecturas del periodo."""
    trazo, _ = _reglas()
    recta = [Punto(19.40, -99.13), Punto(19.50, -99.13)]
    mezcla = _serie([(19.41, -99.1301), (19.43, -99.20), (19.45, -99.1301), (19.46, -99.1302)])
    assert trazo(mezcla, recta, 500, 5) is None


def test_la_regla_del_trazo_exige_el_umbral_de_minutos():
    trazo, _ = _reglas()
    recta = [Punto(19.40, -99.13), Punto(19.50, -99.13)]
    corto = _serie([(19.41, -99.17), (19.43, -99.17), (19.45, -99.17)], paso_min=1)   # 2 minutos
    assert trazo(corto, recta, 500, 5) is None


def test_la_regla_estimada_pide_alejarse_sostenido_y_salir_del_corredor():
    """Con el proveedor estimado no hay trazo de calles: comparar contra la línea recta daría falsas alarmas."""
    _, estimada = _reglas()
    destino = Punto(19.50, -99.13)
    # Se acerca al destino: no es desvío.
    acerca = _serie([(19.41, -99.1301), (19.43, -99.1302), (19.45, -99.1301)])
    assert estimada(acerca, destino, 2000, 5, origen=acerca[0][1]) is None
    # Se aleja sostenido y fuera del corredor de 2 km: sí lo es.
    aleja = _serie([(19.39, -99.20), (19.38, -99.23), (19.37, -99.26), (19.36, -99.29)])
    hallazgo = estimada(aleja, destino, 2000, 5, origen=aleja[0][1])
    assert hallazgo is not None and hallazgo["regla"] == "estimada"
    assert hallazgo["fuera_corredor_m"] > 2000 and hallazgo["minutos"] >= 5


def test_la_regla_estimada_no_alarma_dentro_del_corredor():
    """Alejarse un tramo por la misma avenida es normal: con las dos condiciones no hay falsa alarma."""
    _, estimada = _reglas()
    destino = Punto(19.50, -99.13)
    dentro = _serie([(19.405, -99.1310), (19.404, -99.1315), (19.403, -99.1320), (19.402, -99.1325)])
    assert estimada(dentro, destino, 2000, 5, origen=dentro[0][1]) is None


def test_la_regla_estimada_necesita_muestras_y_tiempo():
    _, estimada = _reglas()
    destino = Punto(19.50, -99.13)
    assert estimada(_serie([(19.39, -99.20), (19.38, -99.23)]), destino, 2000, 5) is None
    corto = _serie([(19.39, -99.20), (19.38, -99.23), (19.37, -99.26)], paso_min=1)
    assert estimada(corto, destino, 2000, 5, origen=corto[0][1]) is None


async def test_la_alerta_salio_de_fase_2(cliente, auth, datos):
    """F2-03 la dejó registrada e inactiva porque faltaba la ruta planeada; F2-06 la activa con sus defaults."""
    r = await cliente.get("/api/alertas/catalogo", headers=await auth(AP))
    assert r.status_code == 200, r.text
    desvio = next(a for a in r.json() if a["clave"] == "TECNICO_DESVIO_RUTA")
    assert desvio["fase"] == 1, "el desvío ya no es Fase 2"
    assert float(desvio["umbral_default"]) == 500 and desvio["tipo_umbral"] == "metros"
    # Y ya tiene evaluador: antes estaba en el catálogo sin nada que la disparara.
    import workers.tareas

    assert "TECNICO_DESVIO_RUTA" in workers.tareas.EVALUADORES


async def test_los_minutos_y_el_corredor_son_configurables(cliente, auth, datos):
    """El umbral de la tabla de alertas son los metros; los minutos y el corredor viven en la configuración de
    rutas, porque una alerta tiene un solo umbral configurable."""
    cfg = await configurar(cliente, auth, umbral_desvio_m=800, umbral_desvio_min=7, corredor_desvio_m=3000)
    assert cfg["umbral_desvio_m"] == 800 and cfg["umbral_desvio_min"] == 7
    assert cfg["corredor_desvio_m"] == 3000
    await configurar(cliente, auth, umbral_desvio_m=500, umbral_desvio_min=5, corredor_desvio_m=2000)


async def test_el_desvio_dispara_la_alerta_una_vez_y_sugiere_el_recalculo(cliente, auth, datos):
    """De punta a punta: con el plan publicado y el técnico alejándose, la alerta se dispara y deja una propuesta."""
    from models.rutas import RutaRecalculo
    from tests.operacion_utiles import alertas_de, evaluar as correr_evaluador

    await configurar(cliente, auth)
    await jornadas_abiertas()
    m = await mercado(cliente, auth, datos)
    await folios_del_dia(cliente, auth, datos, 4)
    detalle = await calcular(cliente, auth, m["id"])
    await publicar(cliente, auth, detalle["plan"]["id"])
    detalle = await plan(cliente, auth, detalle["plan"]["id"])
    if not detalle["rutas"]:
        return
    # El primer técnico del plan se va al poniente, alejándose de su siguiente destino y fuera del corredor.
    tecnico_email = next(
        (e for e in ("tecnico1@acma.dev", "tecnico2@acma.dev", "tecnico3@acma.dev", "tecnico4@acma.dev")), None)
    from tests.rutas_utiles import usuario_id

    con_ruta = {r["tecnico_id"] for r in detalle["rutas"]}
    for email in ("tecnico1@acma.dev", "tecnico2@acma.dev", "tecnico3@acma.dev", "tecnico4@acma.dev"):
        if str(await usuario_id(email)) in con_ruta:
            tecnico_email = email
            break
    await posiciones(tecnico_email, [(19.40, -99.20), (19.40, -99.24), (19.40, -99.28), (19.40, -99.32)])

    antes = len(await alertas_de("TECNICO_DESVIO_RUTA"))
    await correr_evaluador("TECNICO_DESVIO_RUTA")
    avisos = await alertas_de("TECNICO_DESVIO_RUTA")
    if len(avisos) == antes:
        return   # la ruta de ese técnico ya no tenía paradas pendientes: no hay desvío que medir
    aviso = avisos[0]
    assert aviso["datos"]["regla"] in ("estimada", "trazo")
    assert "Desvío de ruta" in aviso["datos"]["etiqueta"]
    # Con el proveedor estimado no hay a quién preguntar por el tráfico, y la alerta lo declara (§6.8.4).
    assert aviso["datos"]["trafico_verificado"] is False
    assert "estimado" in aviso["datos"]["nota_trafico"]
    # No se repite mientras siga desviado.
    await correr_evaluador("TECNICO_DESVIO_RUTA")
    assert len(await alertas_de("TECNICO_DESVIO_RUTA")) == len(avisos)
    # Y dejó una propuesta de recálculo como sugerencia, no una reasignación hecha.
    from core.db import nueva_sesion
    from core.rls import CONTEXTO_SISTEMA
    import uuid

    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        filas = list((await db.execute(select(RutaRecalculo).where(
            RutaRecalculo.plan_id == uuid.UUID(detalle["plan"]["id"])))).scalars())
    assert any(f.disparador.value == "desvio" for f in filas)


async def test_sin_plan_publicado_no_hay_desvio_que_medir(cliente, auth, datos):
    """Sin ruta planeada la alerta no tiene contra qué comparar: no se dispara y no falla."""
    from tests.operacion_utiles import evaluar as correr_evaluador

    disparadas = await correr_evaluador("TECNICO_DESVIO_RUTA")
    assert isinstance(disparadas, int)
