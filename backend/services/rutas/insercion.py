"""Inserción greedy de un folio en una ruta ya calculada (§6.8.2, reasignación forzada). F2-06.

§6.8.2 es explícito: en una reasignación forzada el sistema «extrae el folio de la ruta del técnico origen y lo
inserta en la **posición óptima** de la ruta del técnico destino mediante inserción greedy. **No recalcula la ruta
completa** del destino».

La razón de no recalcular es operativa, no de rendimiento: el técnico destino ya salió con un orden, puede ir en
camino a su siguiente parada, y reordenarle el día entero por un folio que le acaban de pasar es peor que un
desvío de unos minutos. El criterio greedy clásico (inserción más barata) hace justo eso:

    costo_extra(k) = d(anterior, nuevo) + d(nuevo, siguiente) − d(anterior, siguiente)

y se elige la posición con el menor costo extra. Al final de la ruta el término que se resta no existe, así que
pegarlo al final cuesta lo que cuesta llegar hasta ahí.

Lo que la inserción **sí** respeta: la ventana de horario del folio y la jornada del técnico. Si ninguna posición
las cumple, devuelve la mejor por costo e informa qué se incumple, para que el despachador decida con el dato a la
vista en lugar de que el sistema lo esconda.
"""
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from services.rutas import distancias as dist

log = logging.getLogger("acma.rutas.insercion")


@dataclass(frozen=True)
class Candidata:
    posicion: int
    costo_extra_s: int
    llegada: datetime
    ventana_ok: bool
    jornada_ok: bool

    @property
    def viable(self) -> bool:
        return self.ventana_ok and self.jornada_ok


@dataclass(frozen=True)
class ParadaRuta:
    """Una parada de la ruta destino, con lo que la inserción necesita saber de ella."""
    punto: dist.Punto
    minutos_servicio: int
    ventana: tuple[datetime, datetime] | None = None


async def evaluar_posiciones(db: AsyncSession, *, origen: dist.Punto, paradas: list[ParadaRuta],
                             nuevo: dist.Punto, minutos_servicio: int, inicio: datetime,
                             fin_jornada: datetime, ventana: tuple[datetime, datetime] | None = None,
                             proveedor=dist.ProveedorDistancias.estimado,
                             parametros: dist.ParametrosDistancia | None = None) -> list[Candidata]:
    """Costo extra de insertar `nuevo` en cada posición de la ruta, de 0 (primero) a len(paradas) (al final)."""
    puntos = [origen, *[p.punto for p in paradas]]
    candidatas: list[Candidata] = []
    for k in range(len(paradas) + 1):
        anterior = puntos[k]
        hasta_anterior = await _reloj_hasta(db, origen, paradas[:k], inicio, proveedor, parametros)
        ida = await dist.medir(db, anterior, nuevo, hasta_anterior, proveedor=proveedor, parametros=parametros)
        llegada = hasta_anterior + timedelta(seconds=ida.segundos)
        extra = ida.segundos
        if k < len(paradas):
            siguiente = puntos[k + 1]
            vuelta = await dist.medir(db, nuevo, siguiente, llegada + timedelta(minutes=minutos_servicio),
                                      proveedor=proveedor, parametros=parametros)
            directo = await dist.medir(db, anterior, siguiente, hasta_anterior, proveedor=proveedor,
                                       parametros=parametros)
            extra = ida.segundos + vuelta.segundos - directo.segundos
        ventana_ok = ventana is None or (ventana[0] <= llegada <= ventana[1])
        # La jornada se mide con lo que falta por atender después de la inserción, no solo con la llegada.
        cola = sum(p.minutos_servicio for p in paradas[k:]) + minutos_servicio
        jornada_ok = llegada + timedelta(minutes=cola) <= fin_jornada
        candidatas.append(Candidata(posicion=k, costo_extra_s=int(extra), llegada=llegada,
                                    ventana_ok=ventana_ok, jornada_ok=jornada_ok))
    return candidatas


async def _reloj_hasta(db: AsyncSession, origen: dist.Punto, paradas: list[ParadaRuta], inicio: datetime,
                       proveedor, parametros) -> datetime:
    """A qué hora el técnico termina la parada `len(paradas)-1`, recorriendo la ruta desde su posición actual."""
    reloj, anterior = inicio, origen
    for p in paradas:
        tramo = await dist.medir(db, anterior, p.punto, reloj, proveedor=proveedor, parametros=parametros)
        reloj = reloj + timedelta(seconds=tramo.segundos) + timedelta(minutes=p.minutos_servicio)
        anterior = p.punto
    return reloj


def elegir(candidatas: list[Candidata]) -> Candidata:
    """La más barata entre las viables; si ninguna lo es, la más barata a secas (y el llamador avisa por qué)."""
    if not candidatas:
        raise ValueError("no hay posiciones que evaluar")
    viables = [c for c in candidatas if c.viable]
    return min(viables or candidatas, key=lambda c: (c.costo_extra_s, c.posicion))


async def insertar(db: AsyncSession, plan, tecnico_destino_id, folio, *, posicion: int | None = None) -> dict[str, Any]:
    """Inserta el folio en la ruta del técnico destino del plan, en la posición óptima (o la indicada).

    Devuelve qué posición se eligió, cuánto costó y si la posición cumple ventana y jornada. No transiciona el
    folio ni toca `folios`: eso lo hace la reasignación, que es la dueña de esa decisión.
    """
    from sqlalchemy import select

    from models.rutas import RutaParada
    from models.unidades import UnidadNegocio
    from services.rutas import motor, planes_service

    cfg = await motor.configuracion(db, plan.prestador_id, plan.mercado_id)
    parametros = dist.ParametrosDistancia.desde(cfg)
    mercado = await motor.mercado_de(db, plan.prestador_id, plan.mercado_id)
    centro = await motor._punto_centro(db, mercado, await motor.unidades_del_mercado(db, plan.mercado_id))
    inicio_dia = datetime.combine(plan.fecha, cfg.hora_inicio_jornada, tzinfo=UTC)
    fin_jornada = inicio_dia + timedelta(minutes=int(cfg.duracion_jornada_min))

    existentes = list((await db.execute(select(RutaParada).where(
        RutaParada.plan_id == plan.id, RutaParada.tecnico_id == tecnico_destino_id)
        .order_by(RutaParada.orden))).scalars())
    paradas: list[ParadaRuta] = []
    for p in existentes:
        f = await db.get(type(folio), p.folio_id)
        un = await db.get(UnidadNegocio, f.un_id)
        punto = await motor._punto_de_un(db, un) or centro
        paradas.append(ParadaRuta(punto=punto, minutos_servicio=p.minutos_servicio))

    un_nuevo = await db.get(UnidadNegocio, folio.un_id)
    punto_nuevo = await motor._punto_de_un(db, un_nuevo) or centro
    servicio = int(cfg.tiempo_servicio_default_min)
    ventana = None
    if folio.ventana_inicio is not None and folio.ventana_fin is not None:
        ventana = (folio.ventana_inicio, folio.ventana_fin)

    candidatas = await evaluar_posiciones(
        db, origen=centro, paradas=paradas, nuevo=punto_nuevo, minutos_servicio=servicio,
        inicio=inicio_dia, fin_jornada=fin_jornada, ventana=ventana,
        proveedor=cfg.proveedor_distancias, parametros=parametros)
    elegida = candidatas[posicion] if posicion is not None and 0 <= posicion < len(candidatas) else elegir(candidatas)

    # Hueco para no chocar con el UNIQUE (plan, técnico, orden) mientras se renumera.
    for p in existentes[elegida.posicion:]:
        p.orden = p.orden + 1000
    await db.flush()
    nueva = RutaParada(plan_id=plan.id, prestador_id=plan.prestador_id, tecnico_id=tecnico_destino_id,
                       folio_id=folio.id, orden=elegida.posicion, minutos_servicio=servicio,
                       llegada_estimada=elegida.llegada,
                       inicio_servicio_estimado=elegida.llegada,
                       fin_estimado=elegida.llegada + timedelta(minutes=servicio),
                       ventana_ok=elegida.ventana_ok)
    db.add(nueva)
    await db.flush()
    for i, p in enumerate(existentes[elegida.posicion:], start=elegida.posicion + 1):
        p.orden = i
    await db.flush()
    await planes_service.recalcular_horas(db, plan, [tecnico_destino_id])
    log.info("folio %s insertado en la posición %s de la ruta de %s (+%ss)", folio.numero_folio,
             elegida.posicion, tecnico_destino_id, elegida.costo_extra_s)
    return {"posicion": elegida.posicion, "costo_extra_s": elegida.costo_extra_s,
            "llegada_estimada": elegida.llegada, "ventana_ok": elegida.ventana_ok,
            "jornada_ok": elegida.jornada_ok, "parada_id": str(nueva.id),
            "evaluadas": len(candidatas)}


async def quitar(db: AsyncSession, plan, folio_id) -> bool:
    """Saca el folio de la ruta en la que esté y renumera. Devuelve si estaba."""
    from sqlalchemy import select

    from models.rutas import RutaParada
    from services.rutas import planes_service

    parada = (await db.execute(select(RutaParada).where(
        RutaParada.plan_id == plan.id, RutaParada.folio_id == folio_id))).scalar_one_or_none()
    if parada is None:
        return False
    tecnico_id = parada.tecnico_id
    await db.delete(parada)
    await db.flush()
    await planes_service._renumerar(db, plan, tecnico_id)
    await planes_service.recalcular_horas(db, plan, [tecnico_id])
    return True
