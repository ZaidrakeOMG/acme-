"""Simulación «¿qué pasa si…?» de un plan de rutas, sin aplicar nada (F2-06).

El despachador quiere saber, **antes** de mover un folio, qué le cuesta: cuántos kilómetros más, cuántas paradas se
salen de su ventana y cuántas pierden la holgura del SLA. Esto recorre las rutas con el cambio hecho en memoria y
compara contra lo que hay hoy. No escribe en la base ni transiciona folios.

Deliberadamente **no vuelve a optimizar**: responde «si mueves esto así, pasa esto», que es la pregunta del
despachador. Si lo que quiere es la mejor solución con el cambio, eso es el recálculo parcial.
"""
import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.folios import Folio
from models.rutas import RutaParada, RutaPlan
from models.unidades import UnidadNegocio
from services.rutas import distancias as dist
from services.rutas import insercion, motor

log = logging.getLogger("acma.rutas.simulacion")


async def _recorrer(db: AsyncSession, *, origen: dist.Punto, paradas: list[dict[str, Any]], inicio: datetime,
                    proveedor, parametros) -> dict[str, Any]:
    """Recorre una ruta y devuelve km, minutos y qué paradas se salen de ventana o de SLA."""
    reloj, anterior = inicio, origen
    metros_total, fuera_ventana, fuera_sla = 0, 0, 0
    detalle = []
    for p in paradas:
        tramo = await dist.medir(db, anterior, p["punto"], reloj, proveedor=proveedor, parametros=parametros)
        llegada = reloj + timedelta(seconds=tramo.segundos)
        metros_total += tramo.metros
        ventana_ok = True
        if p.get("ventana"):
            ventana_ok = p["ventana"][0] <= llegada <= p["ventana"][1]
        sla_ok = p.get("limite_sla") is None or llegada <= p["limite_sla"]
        fuera_ventana += 0 if ventana_ok else 1
        fuera_sla += 0 if sla_ok else 1
        detalle.append({"folio_id": str(p["folio_id"]), "numero_folio": p["numero_folio"],
                        "llegada_estimada": llegada.isoformat(), "ventana_ok": ventana_ok, "sla_ok": sla_ok})
        reloj = llegada + timedelta(minutes=int(p["minutos_servicio"]))
        anterior = p["punto"]
    return {"km": round(metros_total / 1000, 2), "minutos": int((reloj - inicio).total_seconds() // 60),
            "fuera_ventana": fuera_ventana, "fuera_sla": fuera_sla, "paradas": detalle}


async def simular(db: AsyncSession, plan: RutaPlan, movimientos: list[dict[str, Any]]) -> dict[str, Any]:
    """Compara el plan de ahora contra el plan con los movimientos aplicados en memoria."""
    cfg = await motor.configuracion(db, plan.prestador_id, plan.mercado_id)
    parametros = dist.ParametrosDistancia.desde(cfg)
    mercado = await motor.mercado_de(db, plan.prestador_id, plan.mercado_id)
    centro = await motor._punto_centro(db, mercado, await motor.unidades_del_mercado(db, plan.mercado_id))
    inicio = datetime.combine(plan.fecha, cfg.hora_inicio_jornada, tzinfo=UTC)

    filas = list((await db.execute(select(RutaParada).where(RutaParada.plan_id == plan.id)
                                   .order_by(RutaParada.tecnico_id, RutaParada.orden))).scalars())
    datos: dict[UUID, list[dict[str, Any]]] = {}
    por_folio: dict[UUID, dict[str, Any]] = {}
    for parada in filas:
        folio = await db.get(Folio, parada.folio_id)
        un = await db.get(UnidadNegocio, folio.un_id)
        punto = await motor._punto_de_un(db, un) or centro
        info = {"folio_id": folio.id, "numero_folio": folio.numero_folio, "punto": punto,
                "minutos_servicio": parada.minutos_servicio,
                "ventana": (folio.ventana_inicio, folio.ventana_fin)
                if folio.ventana_inicio and folio.ventana_fin else None,
                "limite_sla": None, "fijo": parada.fijo}
        datos.setdefault(parada.tecnico_id, []).append(info)
        por_folio[folio.id] = info

    antes: dict[str, Any] = {}
    for tecnico_id, paradas in datos.items():
        antes[str(tecnico_id)] = await _recorrer(db, origen=centro, paradas=paradas, inicio=inicio,
                                                 proveedor=cfg.proveedor_distancias, parametros=parametros)

    # ------------------------------------------------- aplicar los movimientos en memoria
    rechazados = []
    nuevos = {t: list(p) for t, p in datos.items()}
    for m in movimientos:
        try:
            folio_id = UUID(str(m["folio_id"]))
            destino = UUID(str(m["tecnico_destino_id"]))
        except (KeyError, ValueError):
            rechazados.append({**m, "motivo": "movimiento mal formado: se espera {folio_id, tecnico_destino_id}"})
            continue
        info = por_folio.get(folio_id)
        if info is None:
            rechazados.append({**m, "motivo": "el folio no está en este plan"})
            continue
        if info["fijo"]:
            rechazados.append({**m, "motivo": "el folio está en ejecución: no se mueve"})
            continue
        for lista in nuevos.values():
            if info in lista:
                lista.remove(info)
        nuevos.setdefault(destino, [])
        # Se coloca por inserción greedy, igual que la reasignación forzada, para comparar peras con peras.
        candidatas = await insercion.evaluar_posiciones(
            db, origen=centro,
            paradas=[insercion.ParadaRuta(punto=x["punto"], minutos_servicio=x["minutos_servicio"])
                     for x in nuevos[destino]],
            nuevo=info["punto"], minutos_servicio=info["minutos_servicio"], inicio=inicio,
            fin_jornada=inicio + timedelta(minutes=int(cfg.duracion_jornada_min)),
            ventana=info["ventana"], proveedor=cfg.proveedor_distancias, parametros=parametros)
        elegida = insercion.elegir(candidatas)
        nuevos[destino].insert(elegida.posicion, info)

    despues: dict[str, Any] = {}
    for tecnico_id, paradas in nuevos.items():
        despues[str(tecnico_id)] = await _recorrer(db, origen=centro, paradas=paradas, inicio=inicio,
                                                   proveedor=cfg.proveedor_distancias, parametros=parametros)

    km_antes = round(sum(x["km"] for x in antes.values()), 2)
    km_despues = round(sum(x["km"] for x in despues.values()), 2)
    return {
        "plan_id": str(plan.id),
        "antes": {"km": km_antes, "fuera_ventana": sum(x["fuera_ventana"] for x in antes.values()),
                  "fuera_sla": sum(x["fuera_sla"] for x in antes.values()), "por_tecnico": antes},
        "despues": {"km": km_despues, "fuera_ventana": sum(x["fuera_ventana"] for x in despues.values()),
                    "fuera_sla": sum(x["fuera_sla"] for x in despues.values()), "por_tecnico": despues},
        "diferencia_km": round(km_despues - km_antes, 2),
        "rechazados": rechazados,
        "nota": "Simulación: no se aplicó ningún cambio. El recálculo parcial sí busca la mejor solución.",
    }
