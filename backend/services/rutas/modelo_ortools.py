"""Modelo VRPTW en OR-Tools (ACT-2.1). F2-06.

**Este módulo es deliberadamente autónomo**: solo depende de `ortools` y de la librería estándar. No importa nada
de ACMA porque el mismo archivo corre en dos lados — dentro de la API (donde OR-Tools carga) y dentro del
contenedor `solver` (donde no) — y en los dos tiene que ser exactamente el mismo modelo. Entra un diccionario,
sale un diccionario.

Cómo se traducen las reglas de §6.8.2 y ACT-2.1 al modelo:

| Regla | Cómo se expresa |
|---|---|
| Habilidad certificada (dura) | `VehicleVar(nodo).SetValues([...])`: el folio solo admite los técnicos que la tienen. |
| Ventana del folio y de la UN (dura) | ventana del nodo en la dimensión de tiempo. |
| Jornada del técnico | cota del tiempo al cerrar la ruta, **blanda**: pasarse cuesta `horas_extra` por hora. |
| Folio en ejecución | nodo fijado a su técnico y con llegada inmediata: no se mueve. |
| SLA (blanda) | cota superior blanda de la llegada en el límite del SLA, con penalización creciente. |
| Criticidad (blanda) | un activo A es más caro de dejar fuera y su llegada se castiga antes. |
| Refacción en el vehículo (blanda) | costo de arco **por vehículo**: llegar a un folio sin traer su refacción cuesta más. |
| Folio sin asignar (blanda) | penalización de la disyunción del nodo, la más alta de todas. |

La función objetivo es la suma de todo lo anterior en **«minutos de costo equivalente»**: la dimensión de tiempo
del modelo trabaja en minutos, así que un peso es «cuántos minutos de ruta vale la pena gastar para evitar esto».
Con `sla = 600`, entregar un folio una hora tarde cuesta 600 × (60/60) = 600, y dejarlo sin asignar cuesta 5,000:
el optimizador prefiere atenderlo tarde antes que no atenderlo, que es lo que quiere la operación.

La unidad importa y costó un defecto: con la dimensión en **segundos**, una hora de retraso costaba 36,000 y
**dejar el folio fuera salía más barato que atenderlo**, así que el plan salía casi vacío. El contrato de entrada
sigue hablando en segundos (es lo que da el proveedor de distancias) y el modelo convierte al entrar.
"""
from __future__ import annotations

import time as _time
from typing import Any

MOTOR = "ortools"

# Peso relativo de cada nivel de criticidad (§6.9.3): un activo A pesa tres veces lo que uno C.
FACTOR_CRITICIDAD = {"A": 3, "B": 2, "C": 1, "D": 0}
PESOS_BASE = {
    "distancia": 1,
    "sla": 600,
    "criticidad": 300,
    "folio_sin_asignar": 5000,
    "horas_extra": 240,
    "sin_refaccion": 400,
}
HORIZONTE_MIN = 24 * 60


def _pesos(problema: dict[str, Any]) -> dict[str, int]:
    return {**PESOS_BASE, **{k: int(v) for k, v in (problema.get("pesos") or {}).items()}}


def ortools_disponible() -> bool:
    """Si el binario nativo de OR-Tools carga en este proceso. En Windows con Control de aplicaciones
    inteligente no carga, y por eso existe el contenedor `solver`."""
    try:
        from ortools.constraint_solver import pywrapcp  # noqa: F401

        return True
    except Exception:  # noqa: BLE001 — ImportError, OSError o el bloqueo de la política de Windows
        return False


def resolver(problema: dict[str, Any]) -> dict[str, Any]:
    """Resuelve el VRPTW. `problema` trae técnicos, paradas, las dos matrices y los pesos; devuelve las rutas.

    Formato de entrada (todos los tiempos en segundos desde el inicio del día del plan):
      tecnicos: [{id, nodo_inicio, inicio_s, fin_s, habilidades: [...], refacciones: [...]}]
      paradas:  [{id, nodo, habilidad, servicio_s, ventana: [desde, hasta], criticidad, sla_limite_s,
                  articulo, fijo_tecnico}]
      segundos / metros: matrices NxN entre todos los nodos
      limite_s: tope de tiempo de cálculo
    """
    from ortools.constraint_solver import pywrapcp, routing_enums_pb2

    inicio_reloj = _time.monotonic()
    tecnicos = list(problema["tecnicos"])
    paradas = list(problema["paradas"])
    segundos = problema["segundos"]
    metros = problema["metros"]
    # Todo el modelo trabaja en minutos (ver el encabezado): se convierte una vez, al entrar.
    minutos = [[int(round(v / 60)) for v in fila] for fila in segundos]
    pesos = _pesos(problema)
    limite_s = int(problema.get("limite_s") or 30)
    n_nodos = len(segundos)

    if not tecnicos or not paradas:
        return {"rutas": [], "sin_asignar": [p["id"] for p in paradas], "costo": 0, "motor": MOTOR,
                "estado": "sin_datos", "ms": 0,
                "motivos": {p["id"]: "no hay técnicos con jornada en el mercado" for p in paradas}}

    inicios = [int(t["nodo_inicio"]) for t in tecnicos]
    manager = pywrapcp.RoutingIndexManager(n_nodos, len(tecnicos), inicios, inicios)
    routing = pywrapcp.RoutingModel(manager)

    por_nodo = {int(p["nodo"]): p for p in paradas}
    nodos_inicio = set(inicios)

    def servicio_min(nodo: int) -> int:
        p = por_nodo.get(nodo)
        return int(round(int(p["servicio_s"]) / 60)) if p else 0

    # ------------------------------------------------------------------ costo por vehículo
    # Volver al punto de partida no cuesta: la jornada termina donde termina el último folio (ruta abierta). Y el
    # costo depende del vehículo porque la refacción que trae cada técnico cambia lo que le conviene atender.
    def hacer_costo(indice_tecnico: int):
        sin_refaccion = pesos["sin_refaccion"]
        lleva = set(tecnicos[indice_tecnico].get("refacciones") or [])

        def costo(i: int, j: int) -> int:
            ni, nj = manager.IndexToNode(i), manager.IndexToNode(j)
            if nj in nodos_inicio:
                return 0
            base = minutos[ni][nj] * pesos["distancia"]
            destino = por_nodo.get(nj)
            if destino is not None:
                articulo = destino.get("articulo")
                if articulo and articulo not in lleva:
                    base += sin_refaccion
            return base

        return costo

    for v in range(len(tecnicos)):
        routing.SetArcCostEvaluatorOfVehicle(routing.RegisterTransitCallback(hacer_costo(v)), v)

    # ------------------------------------------------------------------ dimensión de tiempo
    def transito(i: int, j: int) -> int:
        ni, nj = manager.IndexToNode(i), manager.IndexToNode(j)
        return servicio_min(ni) + (0 if nj in nodos_inicio else minutos[ni][nj])

    routing.AddDimension(routing.RegisterTransitCallback(transito), HORIZONTE_MIN, HORIZONTE_MIN, False, "Tiempo")
    tiempo = routing.GetDimensionOrDie("Tiempo")

    # Jornada: el técnico arranca a su hora y lo que se pase de su jornada cuesta por hora (restricción blanda,
    # porque dejar un folio sin atender suele ser peor que una hora extra).
    for v, t in enumerate(tecnicos):
        inicio = int(round(int(t.get("inicio_s") or 0) / 60))
        fin = int(round(int(t.get("fin_s") or HORIZONTE_MIN * 60) / 60))
        tiempo.CumulVar(routing.Start(v)).SetRange(inicio, max(inicio, fin))
        tiempo.CumulVar(routing.End(v)).SetRange(inicio, HORIZONTE_MIN)
        # `horas_extra` es el costo de **una hora** de más, así que por minuto se divide entre 60.
        tiempo.SetCumulVarSoftUpperBound(routing.End(v), fin, max(1, pesos["horas_extra"] // 60))

    # Tope del castigo por minuto de retraso: el peor retraso posible (una jornada completa) tiene que costar
    # **menos** que dejar el folio sin asignar. Sin este tope, un folio con el SLA ya vencido sale más caro de
    # atender que de abandonar, y el plan se vacía: es el defecto que hacía que de 99 folios se asignaran 4.
    jornada_max = max((int(round(int(t.get("fin_s") or 0) / 60)) for t in tecnicos), default=480) or 480
    tope_sla = max(1, (pesos["folio_sin_asignar"] - 1) // jornada_max)

    for p in paradas:
        indice = manager.NodeToIndex(int(p["nodo"]))
        crudo = p.get("ventana") or (0, HORIZONTE_MIN * 60)
        desde, hasta = (int(round(int(x) / 60)) for x in crudo)
        tiempo.CumulVar(indice).SetRange(max(0, desde), max(desde, hasta))
        # SLA y criticidad: llegar después del límite del SLA cuesta por minuto, y cuesta más en un activo crítico.
        limite = p.get("sla_limite_s")
        factor = FACTOR_CRITICIDAD.get(str(p.get("criticidad") or "C"), 1)
        # OR-Tools admite **una** cota blanda por variable, así que el SLA y la criticidad se combinan en una:
        #   - un activo A o B se castiga desde el inicio de su ventana, así que cada minuto de espera cuesta y
        #     termina al principio de la ruta (es lo que pide §6.9.3: «A antes que D»);
        #   - un C o un D se castiga solo a partir del límite de su SLA.
        # Sin esto, dos folios con el mismo SLA holgado quedaban en cualquier orden: nadie iba tarde, así que la
        # criticidad no tenía por dónde expresarse.
        coeficiente = min(tope_sla, max(1, (pesos["sla"] + pesos["criticidad"] * factor) // 60))
        if factor >= 2:
            cota = max(0, desde)
        elif limite is not None:
            cota = max(0, int(round(int(limite) / 60)))
        else:
            cota = jornada_max
        tiempo.SetCumulVarSoftUpperBound(indice, cota, coeficiente)

    # ------------------------------------------------------------------ habilidad (dura) y folios fijos
    for p in paradas:
        indice = manager.NodeToIndex(int(p["nodo"]))
        habilidad = p.get("habilidad")
        permitidos = [v for v, t in enumerate(tecnicos)
                      if not habilidad or habilidad in set(t.get("habilidades") or [])]
        fijo = p.get("fijo_tecnico")
        if fijo:
            permitidos = [v for v, t in enumerate(tecnicos) if str(t["id"]) == str(fijo)] or permitidos
        if not permitidos:
            # Nadie puede atenderlo: queda fuera por la disyunción, con su motivo en el resultado.
            routing.AddDisjunction([indice], 0)
            continue
        # El `-1` («sin atender») va **siempre** entre los valores posibles, incluso en un folio fijo: sin él el
        # nodo es obligatorio, y un solo nodo obligatorio que no quepa en la jornada vuelve infactible el modelo
        # entero y no sale ninguna ruta. Que un folio en ejecución no se deje fuera se expresa con su penalización
        # altísima, no quitándole la salida.
        routing.VehicleVar(indice).SetValues([-1, *permitidos])
        # Dejarlo fuera cuesta; un activo crítico cuesta más.
        factor = FACTOR_CRITICIDAD.get(str(p.get("criticidad") or "C"), 1)
        penalizacion = pesos["folio_sin_asignar"] + pesos["criticidad"] * factor
        if fijo:
            # Un folio en ejecución no se deja fuera. Se expresa como penalización **altísima**, no como nodo
            # obligatorio (`-1`): obligatorio vuelve **todo** el modelo infactible si ese folio no cabe en la
            # jornada, y entonces no sale ninguna ruta en lugar de salir la ruta con ese folio primero.
            routing.AddDisjunction([indice], int(penalizacion) * 100)
        else:
            routing.AddDisjunction([indice], int(penalizacion))

    # ------------------------------------------------------------------ búsqueda
    # `PARALLEL_CHEAPEST_INSERTION` en lugar de `PATH_CHEAPEST_ARC`: con muchos folios opcionales (los que se
    # pueden dejar sin asignar) y ventanas estrechas, el barrido por arco más barato se queda **sin primera
    # solución** y el solver devuelve None aunque el modelo sea factible. La inserción más barata en paralelo sí
    # las encuentra, porque va colocando visitas en lugar de encadenarlas.
    def _buscar(estrategia, metaheuristica, segundos):
        parametros = pywrapcp.DefaultRoutingSearchParameters()
        parametros.first_solution_strategy = estrategia
        parametros.local_search_metaheuristic = metaheuristica
        parametros.time_limit.FromSeconds(max(1, segundos))
        return routing.SolveWithParameters(parametros)

    solucion = _buscar(routing_enums_pb2.FirstSolutionStrategy.PARALLEL_CHEAPEST_INSERTION,
                       routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH, limite_s)
    if solucion is None:
        # Red de seguridad: una pasada corta con la estrategia automática antes de rendirse.
        solucion = _buscar(routing_enums_pb2.FirstSolutionStrategy.AUTOMATIC,
                           routing_enums_pb2.LocalSearchMetaheuristic.GREEDY_DESCENT,
                           max(1, min(10, limite_s)))
    ms = int((_time.monotonic() - inicio_reloj) * 1000)

    if solucion is None:
        return {"rutas": [], "sin_asignar": [p["id"] for p in paradas], "costo": 0, "motor": MOTOR,
                "estado": "sin_solucion", "ms": ms,
                "motivos": {p["id"]: "el optimizador no encontró ninguna ruta factible" for p in paradas}}

    rutas: list[dict[str, Any]] = []
    atendidos: set[str] = set()
    for v, t in enumerate(tecnicos):
        indice = routing.Start(v)
        orden = 0
        lista: list[dict[str, Any]] = []
        anterior = manager.IndexToNode(indice)
        while not routing.IsEnd(indice):
            nodo = manager.IndexToNode(indice)
            p = por_nodo.get(nodo)
            if p is not None:
                llegada_min = solucion.Min(tiempo.CumulVar(indice))
                lista.append({
                    "folio": p["id"],
                    "orden": orden,
                    # Se devuelve en segundos: el modelo piensa en minutos, el resto del sistema en segundos.
                    "llegada_s": int(llegada_min) * 60,
                    "fin_s": int(llegada_min) * 60 + int(p["servicio_s"]),
                    "servicio_s": int(p["servicio_s"]),
                    "metros_desde_anterior": int(metros[anterior][nodo]),
                    "segundos_desde_anterior": int(segundos[anterior][nodo]),
                    "nodo": nodo,
                })
                atendidos.add(str(p["id"]))
                orden += 1
                anterior = nodo
            indice = solucion.Value(routing.NextVar(indice))
        if lista:
            rutas.append({"tecnico": t["id"], "paradas": lista,
                          "metros": sum(x["metros_desde_anterior"] for x in lista),
                          "fin_s": lista[-1]["fin_s"]})

    sin_asignar = [p["id"] for p in paradas if str(p["id"]) not in atendidos]
    motivos = {}
    for p in paradas:
        if str(p["id"]) in atendidos:
            continue
        habilidad = p.get("habilidad")
        if habilidad and not any(habilidad in set(t.get("habilidades") or []) for t in tecnicos):
            motivos[p["id"]] = f"ningún técnico con jornada tiene la habilidad certificada «{habilidad}»"
        else:
            motivos[p["id"]] = "no alcanzó la jornada ni la ventana de horario de ningún técnico"
    return {"rutas": rutas, "sin_asignar": sin_asignar, "motivos": motivos,
            "costo": int(solucion.ObjectiveValue()), "motor": MOTOR, "estado": "resuelto", "ms": ms}
