"""Inserción greedy de §6.8.2: el folio reasignado entra en la **posición óptima** de la ruta del técnico destino
sin recalcular su ruta completa, y las dos ETA se actualizan. F2-06."""
from datetime import UTC, datetime, timedelta

import pytest

from services.rutas.distancias import Punto
from services.rutas.insercion import Candidata, ParadaRuta, elegir, evaluar_posiciones
from tests.folios_utiles import AP, DES
from tests.rutas_utiles import (
    calcular, configurar, folios_del_dia, jornadas_abiertas, mercado, paradas_de, plan, publicar, tecnico_de,
)

HORA = datetime(2026, 11, 13, 8, 0, tzinfo=UTC)


def test_elegir_prefiere_la_mas_barata_entre_las_viables():
    c = [Candidata(0, 100, HORA, ventana_ok=False, jornada_ok=True),
         Candidata(1, 300, HORA, ventana_ok=True, jornada_ok=True),
         Candidata(2, 500, HORA, ventana_ok=True, jornada_ok=True)]
    assert elegir(c).posicion == 1, "la más barata de todas no sirve si se sale de la ventana"


def test_sin_posiciones_viables_elige_la_mas_barata_y_lo_declara():
    """El despachador decide con el dato a la vista: la posición se devuelve con `ventana_ok` en falso."""
    c = [Candidata(0, 900, HORA, ventana_ok=False, jornada_ok=True),
         Candidata(1, 200, HORA, ventana_ok=True, jornada_ok=False)]
    elegida = elegir(c)
    assert elegida.posicion == 1 and not elegida.viable


def test_elegir_sin_candidatas_falla_claro():
    with pytest.raises(ValueError):
        elegir([])


async def test_el_costo_extra_es_el_de_la_insercion_mas_barata(cliente, auth, datos):
    """`d(anterior, nuevo) + d(nuevo, siguiente) − d(anterior, siguiente)`: pegarlo al final cuesta solo la ida."""
    from core.db import nueva_sesion
    from core.rls import CONTEXTO_SISTEMA

    # Una ruta en línea recta hacia el norte; el folio nuevo queda justo entre la primera y la segunda parada.
    origen = Punto(19.40, -99.13)
    paradas = [ParadaRuta(punto=Punto(19.42, -99.13), minutos_servicio=30),
               ParadaRuta(punto=Punto(19.46, -99.13), minutos_servicio=30)]
    intermedio = Punto(19.44, -99.13)
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        candidatas = await evaluar_posiciones(
            db, origen=origen, paradas=paradas, nuevo=intermedio, minutos_servicio=30,
            inicio=HORA, fin_jornada=HORA + timedelta(hours=8))
    assert len(candidatas) == 3, "tres posiciones: antes de la primera, en medio y al final"
    elegida = elegir(candidatas)
    assert elegida.posicion == 1, [(c.posicion, c.costo_extra_s) for c in candidatas]
    # Meterlo en medio de dos paradas alineadas no agrega distancia: el desvío es casi cero.
    assert candidatas[1].costo_extra_s <= candidatas[0].costo_extra_s
    assert candidatas[1].costo_extra_s <= candidatas[2].costo_extra_s


async def test_la_ventana_descarta_posiciones(cliente, auth, datos):
    from core.db import nueva_sesion
    from core.rls import CONTEXTO_SISTEMA

    origen = Punto(19.40, -99.13)
    paradas = [ParadaRuta(punto=Punto(19.42, -99.13), minutos_servicio=60),
               ParadaRuta(punto=Punto(19.44, -99.13), minutos_servicio=60)]
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        candidatas = await evaluar_posiciones(
            db, origen=origen, paradas=paradas, nuevo=Punto(19.46, -99.13), minutos_servicio=30,
            inicio=HORA, fin_jornada=HORA + timedelta(hours=8),
            ventana=(HORA, HORA + timedelta(minutes=40)))
    # A las 08:00 la franja es la hora pico (20 km/h), así que llegar cuesta ~28 min: la primera posición entra en
    # la ventana de 40 minutos y las de después, que van detrás de dos visitas de una hora, ya no.
    assert candidatas[0].ventana_ok
    assert not candidatas[-1].ventana_ok


async def test_la_jornada_descarta_posiciones(cliente, auth, datos):
    from core.db import nueva_sesion
    from core.rls import CONTEXTO_SISTEMA

    paradas = [ParadaRuta(punto=Punto(19.42, -99.13), minutos_servicio=180),
               ParadaRuta(punto=Punto(19.44, -99.13), minutos_servicio=180)]
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        candidatas = await evaluar_posiciones(
            db, origen=Punto(19.40, -99.13), paradas=paradas, nuevo=Punto(19.46, -99.13),
            minutos_servicio=180, inicio=HORA, fin_jornada=HORA + timedelta(hours=8))
    assert not all(c.jornada_ok for c in candidatas), "tres visitas de 3 h no caben en una jornada de 8 h"


async def test_la_reasignacion_forzada_mueve_la_parada_en_la_ruta(cliente, auth, datos):
    """§6.8.2 de punta a punta: el folio sale de la ruta del origen y entra en la del destino, con su ETA nueva."""
    from models.preventivos import RazonReasignacion
    from sqlalchemy import select

    from core.db import nueva_sesion
    from core.rls import CONTEXTO_SISTEMA

    from tests.rutas_utiles import usuario_id

    await configurar(cliente, auth)
    await jornadas_abiertas()
    m = await mercado(cliente, auth, datos)
    mios = {f["id"] for f in await folios_del_dia(cliente, auth, datos, 5, familia="Refrigeración")}
    detalle = await calcular(cliente, auth, m["id"])
    await publicar(cliente, auth, detalle["plan"]["id"])
    detalle = await plan(cliente, auth, detalle["plan"]["id"])

    # Un folio **de los que esta prueba creó** (de refrigeración) y un destino que tenga esa habilidad
    # certificada: si no, lo que actúa es la restricción dura de §6.8.2 y no se prueba la inserción.
    folio_id = next((p["folio_id"] for p in paradas_de(detalle) if p["folio_id"] in mios), None)
    if folio_id is None:
        pytest.skip("ninguno de los folios de la prueba entró en el plan")
    origen = tecnico_de(detalle, folio_id)
    con_refrigeracion = {str(await usuario_id(e)) for e in ("tecnico1@acma.dev",)}
    destino = next((r["tecnico_id"] for r in detalle["rutas"]
                    if r["tecnico_id"] != origen and r["tecnico_id"] in con_refrigeracion), None)
    if destino is None:
        pytest.skip("el técnico con refrigeración ya tiene el folio o no está en el plan")
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        razon = (await db.execute(select(RazonReasignacion).where(
            RazonReasignacion.descripcion == "Optimización de ruta"))).scalars().first()

    r = await cliente.post(f"/api/folios/{folio_id}/reasignar", headers=await auth(DES),
                           json={"tecnico_destino_id": destino, "razon_id": str(razon.id),
                                 "comentario": "prueba de inserción greedy", "confirmar_advertencias": True})
    if r.status_code == 409 and r.json().get("codigo") == "TECNICO_SIN_HABILIDAD":
        pytest.skip("el técnico destino no tiene la habilidad: la restricción dura actuó primero")
    assert r.status_code in (200, 201), r.text

    despues = await plan(cliente, auth, detalle["plan"]["id"])
    assert tecnico_de(despues, folio_id) == destino, "la parada debe haberse movido de ruta"
    # Y las paradas del destino quedan numeradas sin huecos ni repetidos.
    ruta_destino = next(x for x in despues["rutas"] if x["tecnico_id"] == destino)
    ordenes = [p["orden"] for p in ruta_destino["paradas"]]
    assert ordenes == sorted(ordenes) and len(set(ordenes)) == len(ordenes), ordenes
    assert all(p["llegada_estimada"] for p in ruta_destino["paradas"]), "las ETA del destino se recalculan"
