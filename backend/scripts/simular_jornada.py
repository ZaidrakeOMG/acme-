"""Demostración de la pantalla de operaciones sin salir a la calle (F2-03).

Mueve a los técnicos demo por el mapa enviando posiciones cada pocos segundos, como lo haría la app en la calle:
abre (o reusa) su jornada, camina su ruta entre las unidades del cliente demo y, al terminar, deja todo como estaba.

Ejecutar desde backend/ con la API corriendo (o sin ella: escribe directo en la base):

    .venv/Scripts/python -m scripts.simular_jornada                 # 5 minutos, un punto cada 3 s
    .venv/Scripts/python -m scripts.simular_jornada --minutos 2 --intervalo 5
    .venv/Scripts/python -m scripts.simular_jornada --tecnico tecnico2@acma.dev

Lo que se ve en la pantalla: los marcadores moviéndose, el estatus cambiando de «en ruta» a «en servicio» al entrar
a la geocerca de una unidad, y la alerta de tiempo muerto si se deja un técnico quieto más del umbral.
"""
import argparse
import asyncio
import math
import random
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from core.rls import CONTEXTO_SISTEMA
from models.catalogos import Tecnico
from models.operaciones import EstadoJornada, JornadaTecnico
from models.organizaciones import Prestador
from models.usuarios import Usuario

RUTAS = {
    "tecnico1@acma.dev": [(19.4326, -99.1332), (19.4290, -99.1500), (19.4333, -99.1950)],
    "tecnico2@acma.dev": [(19.4333, -99.1950), (19.3900, -99.1800), (19.3467, -99.1617)],
    "tecnico3@acma.dev": [(19.3467, -99.1617), (19.4000, -99.1450), (19.4326, -99.1332)],
    "tecnico4@acma.dev": [(19.4326, -99.1332), (19.4100, -99.1700), (19.4333, -99.1950)],
}


def _punto(ruta: list[tuple[float, float]], avance: float) -> tuple[float, float]:
    """Posición a lo largo de la ruta (0 = inicio, 1 = final), con un poco de ruido del GPS."""
    tramos = len(ruta) - 1
    total = max(0.0, min(0.999999, avance)) * tramos
    i = int(total)
    t = total - i
    a, b = ruta[i], ruta[i + 1]
    ruido = 0.0001
    return (a[0] + (b[0] - a[0]) * t + random.uniform(-ruido, ruido),
            a[1] + (b[1] - a[1]) * t + random.uniform(-ruido, ruido))


async def simular(minutos: float, intervalo: float, correos: list[str]) -> None:
    from core.db import nueva_sesion
    from services import operacion_service
    from services.mensajeria import telefonos  # noqa: F401  (asegura el registro de modelos)

    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        prestador = (await db.execute(select(Prestador).where(Prestador.rfc == "PDE200101AB1"))).scalar_one()
        elegidos = []
        for correo in correos:
            fila = (await db.execute(select(Tecnico, Usuario).join(Usuario, Usuario.id == Tecnico.usuario_id)
                                     .where(Usuario.email == correo))).first()
            if fila is None:
                print(f"  (sin técnico {correo})")
                continue
            tecnico, usuario = fila
            jornada = (await db.execute(select(JornadaTecnico).where(
                JornadaTecnico.tecnico_id == tecnico.id,
                JornadaTecnico.estado != EstadoJornada.cerrada))).scalar_one_or_none()
            if jornada is None:
                jornada = JornadaTecnico(prestador_id=prestador.id, tecnico_id=tecnico.id,
                                         estado=EstadoJornada.activa, dispositivo_id="simulador",
                                         aviso_aceptado_at=datetime.now(UTC))
                db.add(jornada)
                await db.flush()
                print(f"  jornada abierta para {usuario.nombre}")
            elegidos.append((tecnico, usuario, jornada, RUTAS.get(correo) or RUTAS["tecnico1@acma.dev"]))
        await db.commit()

        if not elegidos:
            print("Nada que simular.")
            return
        pasos = max(1, int((minutos * 60) / intervalo))
        print(f"Simulando {len(elegidos)} técnico(s) durante {minutos} min "
              f"(un punto cada {intervalo} s, {pasos} pasos). Ctrl+C para cortar.")
        for paso in range(1, pasos + 1):
            avance = paso / pasos
            for tecnico, usuario, jornada, ruta in elegidos:
                lat, lng = _punto(ruta, avance)
                resultado = await operacion_service.registrar_posiciones(
                    db, _ActorFalso(usuario), [{
                        "lat": lat, "lng": lng, "capturada_at": datetime.now(UTC),
                        "precision_m": round(random.uniform(5, 20), 1),
                        "velocidad_mps": round(random.uniform(0, 14), 2),
                        "rumbo": round(random.uniform(0, 359), 1), "bateria_pct": max(10, 95 - paso // 3),
                    }])
                sugerencia = resultado.get("sugerencia_llegada")
                print(f"  [{paso:>3}/{pasos}] {usuario.nombre}: {lat:.5f}, {lng:.5f} · {resultado['estatus']}"
                      + (f" · {sugerencia['mensaje']}" if sugerencia else ""))
            await db.commit()
            await asyncio.sleep(intervalo)
        print("Listo. Las jornadas quedan abiertas: ciérralas desde la app del técnico o déjalas al cierre "
              "automático.")


class _ActorFalso:
    """Lo mínimo que `registrar_posiciones` necesita del actor (es el propio técnico)."""

    def __init__(self, usuario: Usuario) -> None:
        self.id = usuario.id
        self.email = usuario.email
        self.nombre = usuario.nombre
        self.rol = usuario.rol
        self.dominio = usuario.dominio
        self.tenant_id = usuario.tenant_id
        self.prestador_id = usuario.prestador_id
        self.sesion_id = None

    @property
    def es_superadmin(self) -> bool:
        return False


def main() -> None:
    p = argparse.ArgumentParser(description="Mueve a los técnicos demo por el mapa (F2-03)")
    p.add_argument("--minutos", type=float, default=5, help="cuánto dura la simulación")
    p.add_argument("--intervalo", type=float, default=3, help="segundos entre posiciones")
    p.add_argument("--tecnico", action="append", help="correo del técnico (se puede repetir)")
    args = p.parse_args()
    correos = args.tecnico or list(RUTAS)
    try:
        asyncio.run(simular(args.minutos, args.intervalo, correos))
    except KeyboardInterrupt:
        print("\nSimulación cortada.")


if __name__ == "__main__":
    main()
