"""Datos demo de F2-03: jornadas de los cuatro técnicos con recorridos simulados de la última hora entre las tres
unidades del cliente demo, uno por cada caso que la pantalla tiene que saber contar (§6.8.4):

* **Tomás** en servicio: dentro de la geocerca de la Sucursal Centro, con su folio en ejecución.
* **Teresa** en ruta: moviéndose de Polanco hacia Coyoacán, con posiciones cada 30 segundos.
* **Tadeo** detenido 25 minutos a media avenida, lejos de cualquier unidad: es el caso de tiempo muerto.
* **Tania** sin señal: su última posición es de hace 20 minutos.

Idempotente: si ya hay una jornada abierta del prestador demo, no hace nada.

Ejecutar desde backend/:  .venv/Scripts/python -m scripts.seed_operacion
"""
import asyncio
import math
import random
from datetime import UTC, datetime, timedelta

from geoalchemy2 import WKTElement
from sqlalchemy import select, text

from core.rls import CONTEXTO_SISTEMA
from models.catalogos import Tecnico
from models.folios import EstadoFolio, Folio
from models.operaciones import (
    EstadoJornada, EstatusOperativo, JornadaPausa, JornadaTecnico, MotivoPausaJornada, TecnicoPosicion,
)
from models.organizaciones import Prestador
from models.unidades import UnidadNegocio
from models.usuarios import Usuario

# Coordenadas de las tres unidades del demo (las mismas de seed_dev).
CENTRO = (19.4326, -99.1332)
POLANCO = (19.4333, -99.1950)
COYOACAN = (19.3467, -99.1617)
# Un punto a media avenida, lejos de las tres: el técnico detenido fuera de destino.
AVENIDA = (19.4005, -99.1700)


def _interpolar(a: tuple[float, float], b: tuple[float, float], t: float) -> tuple[float, float]:
    """Punto intermedio con un poco de ruido, para que el rastro no sea una línea recta de laboratorio."""
    ruido = 0.00015
    return (a[0] + (b[0] - a[0]) * t + random.uniform(-ruido, ruido),
            a[1] + (b[1] - a[1]) * t + random.uniform(-ruido, ruido))


def _alrededor(centro: tuple[float, float], metros: float) -> tuple[float, float]:
    angulo = random.uniform(0, 2 * math.pi)
    radio = random.uniform(0, metros) / 111_320
    return (centro[0] + radio * math.cos(angulo), centro[1] + radio * math.sin(angulo) / math.cos(math.radians(centro[0])))


async def sembrar_operacion(db) -> bool:
    prestador = (await db.execute(select(Prestador).where(Prestador.rfc == "PDE200101AB1"))).scalar_one_or_none()
    if prestador is None:
        print("Sin prestador demo: corre primero scripts.seed_dev")
        return False
    if (await db.execute(select(JornadaTecnico).where(
            JornadaTecnico.prestador_id == prestador.id,
            JornadaTecnico.estado != EstadoJornada.cerrada))).first():
        return False

    tecnicos: dict[str, Tecnico] = {}
    for correo in ("tecnico1@acma.dev", "tecnico2@acma.dev", "tecnico3@acma.dev", "tecnico4@acma.dev"):
        fila = (await db.execute(select(Tecnico).join(Usuario, Usuario.id == Tecnico.usuario_id)
                                 .where(Usuario.email == correo))).scalar_one_or_none()
        if fila is not None:
            tecnicos[correo] = fila
    if not tecnicos:
        print("Sin técnicos demo")
        return False

    ahora = datetime.now(UTC)
    unidades = {u.codigo: u for u in (await db.execute(select(UnidadNegocio).where(
        UnidadNegocio.codigo.in_(("SUC-001", "SUC-002", "SUC-003"))))).scalars()}

    # (correo, estatus, puntos del recorrido, minutos de la última posición, en pausa)
    guiones = [
        ("tecnico1@acma.dev", EstatusOperativo.en_servicio, "centro", 1, False),
        ("tecnico2@acma.dev", EstatusOperativo.en_ruta, "ruta", 0, False),
        ("tecnico3@acma.dev", EstatusOperativo.en_ruta, "detenido", 1, False),
        ("tecnico4@acma.dev", EstatusOperativo.sin_senal, "sin_senal", 20, False),
    ]
    creadas = 0
    for correo, estatus, guion, minutos_ultima, en_pausa in guiones:
        tecnico = tecnicos.get(correo)
        if tecnico is None:
            continue
        inicio = ahora - timedelta(hours=1, minutes=random.randint(5, 40))
        jornada = JornadaTecnico(prestador_id=prestador.id, tecnico_id=tecnico.id, inicio=inicio,
                                 estado=EstadoJornada.pausa if en_pausa else EstadoJornada.activa,
                                 dispositivo_id=f"demo-{correo.split('@')[0]}",
                                 aviso_aceptado_at=inicio)
        db.add(jornada)
        await db.flush()
        if en_pausa:
            db.add(JornadaPausa(prestador_id=prestador.id, jornada_id=jornada.id,
                                inicio=ahora - timedelta(minutes=18), motivo=MotivoPausaJornada.comida))

        puntos: list[tuple[tuple[float, float], datetime]] = []
        if guion == "centro":
            # Llegó al Centro hace 25 minutos y ahí sigue (está trabajando dentro de la geocerca).
            for i in range(50):
                t = min(1.0, i / 25)
                momento = ahora - timedelta(minutes=50 - i)
                puntos.append((_interpolar(POLANCO, CENTRO, t) if t < 1 else _alrededor(CENTRO, 40), momento))
        elif guion == "ruta":
            for i in range(60):
                momento = ahora - timedelta(seconds=30 * (60 - i))
                puntos.append((_interpolar(POLANCO, COYOACAN, i / 60), momento))
        elif guion == "detenido":
            for i in range(30):  # llegó a la avenida y lleva 25 minutos ahí, a 20 m a la redonda
                momento = ahora - timedelta(minutes=55 - i)
                puntos.append((_interpolar(CENTRO, AVENIDA, min(1.0, i / 5)) if i < 5
                               else _alrededor(AVENIDA, 20), momento))
        else:  # sin_senal: dejó de reportar hace 20 minutos
            for i in range(20):
                momento = ahora - timedelta(minutes=40 - i)
                puntos.append((_interpolar(CENTRO, COYOACAN, i / 40), momento))

        ultima = None
        for (lat, lng), momento in puntos:
            if momento > ahora - timedelta(minutes=minutos_ultima):
                continue
            db.add(TecnicoPosicion(
                prestador_id=prestador.id, tecnico_id=tecnico.id, jornada_id=jornada.id,
                posicion=WKTElement(f"POINT({lng} {lat})", srid=4326),
                precision_m=round(random.uniform(5, 25), 1), velocidad_mps=round(random.uniform(0, 12), 2),
                rumbo=round(random.uniform(0, 359), 1), bateria_pct=random.randint(35, 95),
                capturada_at=momento, recibida_at=momento, tardia=False))
            ultima = (lat, lng, momento)
        if ultima is not None:
            lat, lng, momento = ultima
            await db.execute(text(
                "UPDATE tecnicos SET ultima_posicion = ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography, "
                "ultima_posicion_at = :at, ultima_precision_m = 12.0, ultima_bateria_pct = :bat, "
                "estatus_operativo = :estatus WHERE id = :id"),
                {"lng": lng, "lat": lat, "at": momento, "bat": random.randint(35, 95),
                 "estatus": estatus.value, "id": str(tecnico.id)})
            jornada.posiciones = len(puntos)
        creadas += 1

    # Que el técnico «en servicio» tenga de verdad un folio en ejecución, para que el estatus cuadre con los datos.
    tecnico1 = tecnicos.get("tecnico1@acma.dev")
    if tecnico1 is not None and unidades.get("SUC-001"):
        folio = (await db.execute(select(Folio).where(
            Folio.tecnico_id == tecnico1.usuario_id, Folio.estado == EstadoFolio.en_ejecucion).limit(1))).scalar_one_or_none()
        if folio is None:
            folio = (await db.execute(select(Folio).where(
                Folio.tecnico_id == tecnico1.usuario_id,
                Folio.estado.in_((EstadoFolio.asignado, EstadoFolio.en_camino))).limit(1))).scalar_one_or_none()
            if folio is not None:
                folio.estado = EstadoFolio.en_ejecucion
    await db.flush()
    print(f"Jornadas demo creadas: {creadas}")
    return True


async def main() -> None:
    from core.db import nueva_sesion

    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        if await sembrar_operacion(db):
            await db.commit()
            print("Listo: jornadas y recorridos demo sembrados")
        else:
            print("La operación demo ya estaba sembrada")


if __name__ == "__main__":
    asyncio.run(main())
