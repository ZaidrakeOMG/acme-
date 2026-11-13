"""Medición del motor VRPTW (ACT-2.2). F2-06.

Corre los escenarios que pide el prompt —10, 25 y 50 técnicos contra 50, 150 y 300 folios— y mide el **cálculo
inicial** y el **recálculo parcial**. No toca la base: arma problemas sintéticos con la misma forma que los reales
y los manda por el mismo transporte que usa la aplicación, así que lo que se mide es el motor.

    python -m scripts.medir_rutas              # los nueve escenarios con el límite de cálculo por defecto
    python -m scripts.medir_rutas 10           # límite de 10 s por cálculo

Los problemas se generan sobre una rejilla de 20 × 20 km alrededor del Zócalo con una semilla fija, para que dos
corridas sean comparables.
"""
import asyncio
import math
import random
import statistics
import sys
import time

from services.rutas.distancias import Punto, metros_linea_recta

CENTRO = (19.4326, -99.1332)
ESCENARIOS = [(10, 50), (25, 150), (50, 300)]
HABILIDADES = ["refrigeracion", "electricidad", "hvac", "iluminacion"]
# El recálculo parcial de §6.8.2 solo mira los folios pendientes de un técnico más los huérfanos: una fracción.
FRACCION_RECALCULO = 0.15


def _puntos(cuantos: int, semilla: int) -> list[Punto]:
    rnd = random.Random(semilla)
    salida = []
    for _ in range(cuantos):
        # ±0.09° ≈ ±10 km
        salida.append(Punto(lat=CENTRO[0] + rnd.uniform(-0.09, 0.09),
                            lng=CENTRO[1] + rnd.uniform(-0.09, 0.09)))
    return salida


def _matrices(puntos: list[Punto], factor: float = 1.4, kmh: float = 30) -> tuple[list, list]:
    n = len(puntos)
    met = [[0] * n for _ in range(n)]
    seg = [[0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            m = metros_linea_recta(puntos[i], puntos[j]) * factor
            met[i][j] = int(m)
            seg[i][j] = int(m / 1000 / kmh * 3600)
    return met, seg


def problema(n_tecnicos: int, n_folios: int, *, limite_s: int, semilla: int = 2026) -> dict:
    rnd = random.Random(semilla)
    puntos = _puntos(n_tecnicos + n_folios, semilla)
    met, seg = _matrices(puntos)
    tecnicos = [{
        "id": f"tec-{v}", "nodo_inicio": v, "inicio_s": 0, "fin_s": 8 * 3600,
        # Cada técnico con dos habilidades: así hay folios que solo algunos pueden atender.
        "habilidades": rnd.sample(HABILIDADES, 2), "refacciones": [],
    } for v in range(n_tecnicos)]
    paradas = []
    for k in range(n_folios):
        criticidad = rnd.choices(["A", "B", "C", "D"], weights=[1, 2, 4, 3])[0]
        paradas.append({
            "id": f"f-{k}", "nodo": n_tecnicos + k,
            "habilidad": rnd.choice(HABILIDADES),
            "servicio_s": rnd.choice([1800, 2700, 3600]),
            "ventana": [0, 8 * 3600] if rnd.random() > 0.3 else [rnd.choice([0, 3600, 7200]), 8 * 3600],
            "criticidad": criticidad,
            "sla_limite_s": rnd.choice([None, 2 * 3600, 4 * 3600, 6 * 3600]),
            "articulo": None, "fijo_tecnico": None,
        })
    return {"tecnicos": tecnicos, "paradas": paradas, "segundos": seg, "metros": met,
            "pesos": {}, "limite_s": limite_s}


async def _resolver(p: dict) -> tuple[dict, float]:
    from services.rutas.motor import _por_sidecar, transporte_efectivo

    inicio = time.monotonic()
    if transporte_efectivo() == "en_proceso":
        from services.rutas import modelo_ortools

        r = modelo_ortools.resolver(p)
    else:
        r = await _por_sidecar(p, int(p["limite_s"]))
    return r, (time.monotonic() - inicio) * 1000


async def main() -> None:
    limite = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    from services.rutas.motor import transporte_efectivo

    print(f"Motor VRPTW · límite {limite} s por cálculo · transporte: {transporte_efectivo()}\n")
    print(f"{'escenario':<22} {'nodos':>6} {'inicial ms':>11} {'colocados':>10} {'sin asignar':>12} "
          f"{'recálculo ms':>13}")
    print("-" * 80)
    filas = []
    for n_tec, n_fol in ESCENARIOS:
        p = problema(n_tec, n_fol, limite_s=limite)
        completo, ms_inicial = await _resolver(p)
        colocados = sum(len(x["paradas"]) for x in completo.get("rutas", []))

        # Recálculo parcial: los folios de un técnico más una fracción de huérfanos, como en §6.8.2.
        cuantos = max(2, int(n_fol * FRACCION_RECALCULO))
        parcial = problema(n_tec, cuantos, limite_s=max(2, limite // 3), semilla=777)
        _, ms_parcial = await _resolver(parcial)

        filas.append({"tecnicos": n_tec, "folios": n_fol, "nodos": n_tec + n_fol,
                      "ms_inicial": round(ms_inicial), "colocados": colocados,
                      "sin_asignar": len(completo.get("sin_asignar", [])),
                      "ms_parcial": round(ms_parcial), "folios_parcial": cuantos})
        print(f"{n_tec:>3} técnicos / {n_fol:>3} folios {n_tec + n_fol:>6} {round(ms_inicial):>11} "
              f"{colocados:>10} {len(completo.get('sin_asignar', [])):>12} {round(ms_parcial):>13}")
    print("\nResumen para `docs/rendimiento/resultados.md`:")
    for f in filas:
        print(f"| {f['tecnicos']} | {f['folios']} | {f['nodos']} | {f['ms_inicial']:,} | {f['colocados']} | "
              f"{f['sin_asignar']} | {f['folios_parcial']} | {f['ms_parcial']:,} |")


if __name__ == "__main__":
    asyncio.run(main())
