"""Recálculo parcial y reasignación automática (§6.8.2, literal). F2-06.

§6.8.2 dice exactamente qué recalcular: «solo los folios **pendientes** del técnico afectado usando el estado
actual de todos los técnicos activos como punto de partida. No toca los folios ya completados ni los de otros
técnicos **a menos que sea necesario para absorber folios huérfanos**».

Así que el recálculo:

1. toma los folios pendientes del técnico afectado (los que aún no empezó) más los **huérfanos** (sin técnico);
2. deja fuera lo completado, lo que está en ejecución y los folios de los demás técnicos;
3. resuelve ese problema chico partiendo de **dónde está cada técnico ahora** (F2-03);
4. y produce una **propuesta**, que es lo que el despachador acepta o rechaza.

El modo lo decide el prestador: `solo_sugerir` (default) deja la propuesta esperando y **no cambia nada** hasta que
alguien la acepta; `aplicar_y_avisar` la aplica y notifica. En los dos casos cada movimiento queda en
`reasignaciones` con `tipo = automatica`, su razón y la pausa de SLA de §6.10.1, porque pasa por la misma puerta
que la reasignación forzada de P06.
"""
import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.dependencias import Actor
from core.errors import ErrorAPI, no_encontrado
from models.folios import EstadoFolio, Folio
from models.rutas import (
    DisparadorRecalculo, EstadoPlanRuta, EstadoRecalculo, ModoReasignacionAutomatica, RutaParada, RutaPlan,
    RutaRecalculo,
)
from services import auditoria, notificaciones
from services.rutas import distancias as dist
from services.rutas import motor, planes_service

log = logging.getLogger("acma.rutas.recalculo")

# La razón del catálogo de §6.8.2 con la que se registra cada movimiento automático, según qué lo disparó.
RAZON_POR_DISPARADOR = {
    DisparadorRecalculo.desvio: "Optimización de ruta",
    DisparadorRecalculo.tiempo_muerto: "Optimización de ruta",
    DisparadorRecalculo.sla_en_riesgo: "Optimización de ruta",
    DisparadorRecalculo.incidencia_tecnico: "Incidencia del técnico",
    DisparadorRecalculo.folio_nuevo_urgente: "Prioridad de cliente",
    DisparadorRecalculo.reasignacion_forzada: "Corrección de asignación inicial",
    DisparadorRecalculo.manual: "Optimización de ruta",
}
# Folios que todavía se pueden mover: no empezados. En ejecución y cerrados quedan fuera por §6.8.2.
PENDIENTES = (EstadoFolio.autorizado, EstadoFolio.asignado, EstadoFolio.reasignado)


async def _posiciones_actuales(db: AsyncSession, prestador_id: UUID) -> dict[UUID, dist.Punto]:
    """Dónde está cada técnico ahora, de `tecnicos.ultima_posicion` (F2-03)."""
    from geoalchemy2 import Geometry
    from sqlalchemy import func

    from models.catalogos import Tecnico

    filas = (await db.execute(
        select(Tecnico.usuario_id,
               func.ST_Y(Tecnico.ultima_posicion.cast(Geometry())),
               func.ST_X(Tecnico.ultima_posicion.cast(Geometry())))
        .where(Tecnico.prestador_id == prestador_id, Tecnico.ultima_posicion.is_not(None)))).all()
    return {u: dist.Punto(lat=float(lat), lng=float(lng)) for u, lat, lng in filas if lat is not None}


async def recalcular_parcial(db: AsyncSession, plan: RutaPlan, *, disparador: DisparadorRecalculo,
                             tecnico_id: UUID | None = None, folio_id: UUID | None = None,
                             motivo: str = "", actor: Actor | None = None,
                             request: Request | None = None) -> RutaRecalculo:
    """Recalcula lo afectado y deja una propuesta (o la aplica, según el modo del prestador)."""
    cfg = await motor.configuracion(db, plan.prestador_id, plan.mercado_id)
    inicio = datetime.now(UTC)

    # ------------------------------------------------- qué folios entran
    afectados: set[UUID] = set()
    if tecnico_id is not None:
        afectados = {p.folio_id for p in (await db.execute(select(RutaParada).where(
            RutaParada.plan_id == plan.id, RutaParada.tecnico_id == tecnico_id))).scalars()}
    if folio_id is not None:
        afectados.add(folio_id)
    unidades = await motor.unidades_del_mercado(db, plan.mercado_id)
    huerfanos = {f.id for f in (await db.execute(select(Folio).where(
        Folio.prestador_id == plan.prestador_id, Folio.un_id.in_(unidades or [UUID(int=0)]),
        Folio.estado == EstadoFolio.autorizado, Folio.tecnico_id.is_(None)))).scalars()}
    candidatos = afectados | huerfanos
    # Solo los pendientes: lo que ya empezó no se mueve.
    movibles = {f.id for f in (await db.execute(select(Folio).where(
        Folio.id.in_(candidatos or [UUID(int=0)]), Folio.estado.in_(PENDIENTES)))).scalars()}
    if not movibles:
        raise ErrorAPI(409, "NADA_QUE_RECALCULAR",
                       "No hay folios pendientes que mover: lo que falta ya está en ejecución o cerrado")

    # ------------------------------------------------- resolver el problema chico
    posiciones = await _posiciones_actuales(db, plan.prestador_id)
    problema = await motor.armar(db, plan.prestador_id, plan.mercado_id, plan.fecha, cfg=cfg,
                                 solo_folios=sorted(movibles, key=str), posiciones=posiciones)
    resultado = await motor.resolver(db, problema)

    # ------------------------------------------------- qué cambia contra el plan de ahora
    actual = {p.folio_id: p.tecnico_id for p in (await db.execute(select(RutaParada).where(
        RutaParada.plan_id == plan.id))).scalars()}
    movimientos: list[dict[str, Any]] = []
    for ruta in resultado.get("rutas", []):
        destino = UUID(str(ruta["tecnico"]))
        for parada in ruta["paradas"]:
            fid = UUID(str(parada["folio"]))
            origen = actual.get(fid)
            if origen == destino:
                continue
            folio = await db.get(Folio, fid)
            movimientos.append({
                "folio_id": str(fid), "numero_folio": folio.numero_folio if folio else "",
                "de_tecnico_id": str(origen) if origen else None,
                "a_tecnico_id": str(destino), "orden": int(parada["orden"]),
                "llegada_estimada": (problema.inicio_dia + timedelta(
                    seconds=int(parada["llegada_s"]))).isoformat(),
            })
    ms = int((datetime.now(UTC) - inicio).total_seconds() * 1000)

    recalculo = RutaRecalculo(
        plan_id=plan.id, prestador_id=plan.prestador_id, disparador=disparador,
        disparado_por_folio_id=folio_id, disparado_por_tecnico_id=tecnico_id,
        tecnicos_afectados=[str(t) for t in {m["a_tecnico_id"] for m in movimientos} |
                            {m["de_tecnico_id"] for m in movimientos if m["de_tecnico_id"]}],
        folios_movidos_json=movimientos,
        propuesta_json={"rutas": resultado.get("rutas", []), "sin_asignar": resultado.get("sin_asignar", []),
                        "motivos": resultado.get("motivos", {}), "costo": resultado.get("costo"),
                        "motor": resultado.get("motor"), "transporte": resultado.get("transporte")},
        motivo=motivo or f"Recálculo por {disparador.value}",
        estado=EstadoRecalculo.propuesta,
        vence_at=datetime.now(UTC) + timedelta(minutes=int(cfg.minutos_vigencia_propuesta)),
        tiempo_calculo_ms=ms)
    db.add(recalculo)
    await db.flush()

    if not movimientos:
        recalculo.estado = EstadoRecalculo.rechazada
        recalculo.motivo = "El recálculo no encontró ninguna mejora: la ruta de ahora ya es la buena"
        recalculo.decidido_at = datetime.now(UTC)
        await db.flush()
        log.info("recálculo %s sin cambios (%sms)", recalculo.id, ms)
        return recalculo

    if cfg.modo_reasignacion_automatica == ModoReasignacionAutomatica.aplicar_y_avisar:
        await aplicar(db, recalculo, actor=actor, request=request)
    else:
        notificaciones.enviar(
            roles=["despachador", "admin_prestador"], prestador_id=plan.prestador_id,
            titulo=f"Propuesta de reasignación: {len(movimientos)} folio(s)",
            cuerpo=(f"{recalculo.motivo}. Vence en {cfg.minutos_vigencia_propuesta} minutos y no cambia nada "
                    f"hasta que la aceptes."),
            datos={"recalculo_id": str(recalculo.id), "plan_rutas_id": str(plan.id),
                   "movimientos": len(movimientos), "url": "/operaciones"},
            canales=["app", "push"])
    log.info("recálculo %s por %s: %s movimientos, estado %s (%sms)", recalculo.id, disparador.value,
             len(movimientos), recalculo.estado.value, ms)
    return recalculo


async def aplicar(db: AsyncSession, recalculo: RutaRecalculo, *, actor: Actor | None = None,
                  request: Request | None = None) -> dict[str, Any]:
    """Ejecuta los movimientos de la propuesta como reasignaciones **automáticas**.

    Cada uno pasa por `reasignacion_service.reasignar`, así que hereda las restricciones duras de §6.8.2, la pausa
    de SLA de §6.10.1, las validaciones, el chat y los avisos a los dos técnicos.
    """
    from models.preventivos import RazonReasignacion
    from services import reasignacion_service

    plan = await db.get(RutaPlan, recalculo.plan_id)
    aplicados, omitidos = [], []
    for m in recalculo.folios_movidos_json or []:
        folio = await db.get(Folio, UUID(m["folio_id"]))
        if folio is None:
            continue
        if folio.estado not in PENDIENTES:
            omitidos.append({**m, "motivo": f"el folio pasó a {folio.estado.value} mientras la propuesta esperaba"})
            continue
        destino = UUID(m["a_tecnico_id"])
        if folio.tecnico_id == destino:
            omitidos.append({**m, "motivo": "el folio ya está con ese técnico"})
            continue
        descripcion = RAZON_POR_DISPARADOR.get(recalculo.disparador, "Optimización de ruta")
        razon = (await db.execute(select(RazonReasignacion).where(
            RazonReasignacion.prestador_id == recalculo.prestador_id,
            RazonReasignacion.descripcion == descripcion))).scalar_one_or_none()
        if razon is None:
            razon = (await db.execute(select(RazonReasignacion).where(
                RazonReasignacion.prestador_id == recalculo.prestador_id,
                RazonReasignacion.activa.is_(True)))).scalars().first()
        if razon is None:
            omitidos.append({**m, "motivo": "el prestador no tiene razones de reasignación en su catálogo"})
            continue
        quien = actor or _actor_sistema(recalculo.prestador_id)
        try:
            punto = await db.begin_nested()
            if folio.tecnico_id is None:
                # Folio huérfano: no es una reasignación, es la primera asignación. Va por la ruta normal de P04.
                from services import folio_estados

                folio.tecnico_id = destino
                await folio_estados.transicionar(
                    db, folio, EstadoFolio.asignado, quien,
                    f"Asignado por el recálculo de rutas ({recalculo.disparador.value})",
                    {"tecnico_id": str(destino), "recalculo_id": str(recalculo.id),
                     "origen": "reasignacion_automatica"}, request)
                folio.orden_en_ruta = int(m.get("orden") or 0)
            else:
                await reasignacion_service.reasignar(
                    db, quien, folio, destino, razon.id,
                    f"Reasignación automática: {recalculo.motivo}", True, None, request,
                    tipo=_tipo_automatica(), recalculo_id=recalculo.id, exigir_rol=False)
            await punto.commit()
            aplicados.append(m)
        except ErrorAPI as e:
            await punto.rollback()
            omitidos.append({**m, "motivo": f"{e.codigo}: {e.mensaje}"})
        except Exception as e:  # noqa: BLE001 — un folio que no se puede mover no detiene a los demás
            await punto.rollback()
            omitidos.append({**m, "motivo": str(e)[:200]})
            log.exception("no se pudo aplicar el movimiento del folio %s", m.get("folio_id"))

    recalculo.estado = EstadoRecalculo.aplicada
    recalculo.decidido_por = actor.id if actor else None
    recalculo.decidido_at = datetime.now(UTC)
    recalculo.propuesta_json = {**(recalculo.propuesta_json or {}),
                                "aplicados": len(aplicados), "omitidos": omitidos}
    await db.flush()
    if plan is not None and aplicados:
        tecnicos = {UUID(m["a_tecnico_id"]) for m in aplicados}
        tecnicos |= {UUID(m["de_tecnico_id"]) for m in aplicados if m.get("de_tecnico_id")}
        await planes_service.recalcular_horas(db, plan, sorted(tecnicos, key=str))
    notificaciones.enviar(
        roles=["despachador", "admin_prestador"], prestador_id=recalculo.prestador_id,
        titulo=f"Reasignación automática aplicada: {len(aplicados)} folio(s)",
        cuerpo=recalculo.motivo + (f" · {len(omitidos)} no se pudieron mover" if omitidos else ""),
        datos={"recalculo_id": str(recalculo.id), "aplicados": len(aplicados), "url": "/operaciones"},
        canales=["app", "push"])
    if actor is not None:
        await auditoria.registrar_actor(db, actor, "rutas.recalculo_aplicado", request,
                                       prestador_id=recalculo.prestador_id,
                                       recurso_tipo="rutas_recalculos", recurso_id=recalculo.id,
                                       despues={"aplicados": len(aplicados), "omitidos": len(omitidos)})
    return {"recalculo_id": str(recalculo.id), "aplicados": len(aplicados), "omitidos": omitidos}


def _tipo_automatica():
    from models.preventivos import TipoReasignacion

    return TipoReasignacion.automatica


def _actor_sistema(prestador_id: UUID) -> Actor:
    from models.base import Dominio, Rol

    return Actor(id=UUID(int=0), email="sistema@acma", nombre="sistema", rol=Rol.superadmin,
                 dominio=Dominio.plataforma, tenant_id=None, prestador_id=prestador_id, sesion_id=None)


# ------------------------------------------------------------------ decisión del despachador

async def obtener(db: AsyncSession, actor: Actor, recalculo_id: UUID) -> RutaRecalculo:
    r = await db.get(RutaRecalculo, recalculo_id)
    if r is None or (not actor.es_superadmin and actor.prestador_id != r.prestador_id):
        raise no_encontrado("Recálculo de ruta")
    planes_service._exigir(actor, planes_service.CONSULTAN, "consulta las rutas")
    return r


async def pendientes(db: AsyncSession, actor: Actor, prestador_id: UUID | None = None) -> list[dict[str, Any]]:
    """Las propuestas que esperan decisión, para el tablero de operaciones. Las vencidas se marcan al pasar."""
    planes_service._exigir(actor, planes_service.CONSULTAN, "consulta las rutas")
    destino = prestador_id if (prestador_id and actor.es_superadmin) else actor.prestador_id
    await expirar_vencidas(db, destino)
    filas = list((await db.execute(select(RutaRecalculo).where(
        RutaRecalculo.prestador_id == destino, RutaRecalculo.estado == EstadoRecalculo.propuesta)
        .order_by(RutaRecalculo.timestamp.desc()))).scalars())
    return [{
        "id": str(r.id), "plan_id": str(r.plan_id), "disparador": r.disparador.value, "motivo": r.motivo,
        "movimientos": r.folios_movidos_json or [], "tecnicos_afectados": r.tecnicos_afectados or [],
        "vence_at": r.vence_at, "timestamp": r.timestamp, "tiempo_calculo_ms": r.tiempo_calculo_ms,
        "sin_asignar": (r.propuesta_json or {}).get("sin_asignar", []),
    } for r in filas]


async def aceptar(db: AsyncSession, actor: Actor, recalculo: RutaRecalculo, *,
                  request: Request | None = None) -> dict[str, Any]:
    planes_service._exigir(actor, planes_service.CALCULAN, "decide las reasignaciones automáticas")
    _exigir_pendiente(recalculo)
    return await aplicar(db, recalculo, actor=actor, request=request)


async def rechazar(db: AsyncSession, actor: Actor, recalculo: RutaRecalculo, razon: str = "", *,
                   request: Request | None = None) -> RutaRecalculo:
    planes_service._exigir(actor, planes_service.CALCULAN, "decide las reasignaciones automáticas")
    _exigir_pendiente(recalculo)
    recalculo.estado = EstadoRecalculo.rechazada
    recalculo.decidido_por = actor.id
    recalculo.decidido_at = datetime.now(UTC)
    if razon.strip():
        recalculo.motivo = f"{recalculo.motivo} · rechazada: {razon.strip()}"
    await db.flush()
    await auditoria.registrar_actor(db, actor, "rutas.recalculo_rechazado", request,
                                   prestador_id=recalculo.prestador_id,
                                   recurso_tipo="rutas_recalculos", recurso_id=recalculo.id,
                                   despues={"razon": razon})
    return recalculo


def _exigir_pendiente(recalculo: RutaRecalculo) -> None:
    if recalculo.estado != EstadoRecalculo.propuesta:
        raise ErrorAPI(409, "PROPUESTA_NO_PENDIENTE", f"La propuesta ya está {recalculo.estado.value}")
    if recalculo.vence_at is not None and recalculo.vence_at < datetime.now(UTC):
        raise ErrorAPI(409, "PROPUESTA_EXPIRADA",
                       "La propuesta venció: la operación ya se movió, hay que recalcular con los datos de ahora")


async def expirar_vencidas(db: AsyncSession, prestador_id: UUID | None = None) -> int:
    """Una propuesta vieja es peor que ninguna: describe una operación que ya cambió."""
    consulta = select(RutaRecalculo).where(RutaRecalculo.estado == EstadoRecalculo.propuesta,
                                           RutaRecalculo.vence_at < datetime.now(UTC))
    if prestador_id is not None:
        consulta = consulta.where(RutaRecalculo.prestador_id == prestador_id)
    vencidas = list((await db.execute(consulta)).scalars())
    for r in vencidas:
        r.estado = EstadoRecalculo.expirada
    if vencidas:
        await db.flush()
    return len(vencidas)


# ------------------------------------------------------------------ disparadores automáticos

async def plan_vigente(db: AsyncSession, prestador_id: UUID, un_id: UUID | None = None) -> RutaPlan | None:
    """El plan publicado de hoy que cubre esa unidad, que es el que un disparador tiene que recalcular."""
    from datetime import date

    from models.rutas import MercadoUnidad

    consulta = select(RutaPlan).where(
        RutaPlan.prestador_id == prestador_id, RutaPlan.fecha == date.today(),
        RutaPlan.estado.in_((EstadoPlanRuta.publicado, EstadoPlanRuta.en_curso)))
    if un_id is not None:
        consulta = consulta.join(MercadoUnidad, MercadoUnidad.mercado_id == RutaPlan.mercado_id).where(
            MercadoUnidad.un_id == un_id)
    return (await db.execute(consulta.order_by(RutaPlan.version.desc()))).scalars().first()


async def disparar(db: AsyncSession, prestador_id: UUID, disparador: DisparadorRecalculo, *,
                   tecnico_id: UUID | None = None, folio_id: UUID | None = None, un_id: UUID | None = None,
                   motivo: str = "") -> RutaRecalculo | None:
    """Puerta única de los disparadores (desvío, tiempo muerto, SLA en riesgo, incidencia, folio urgente).

    Si no hay plan publicado hoy, no hace nada: sin ruta planeada no hay nada que recalcular. Y nunca tumba a
    quien la llama: un evaluador de alertas no se cae porque el optimizador no esté disponible.
    """
    plan = await plan_vigente(db, prestador_id, un_id)
    if plan is None:
        return None
    try:
        return await recalcular_parcial(db, plan, disparador=disparador, tecnico_id=tecnico_id,
                                        folio_id=folio_id, motivo=motivo)
    except ErrorAPI as e:
        log.info("no se recalculó la ruta por %s: %s", disparador.value, e.codigo)
        return None
    except Exception:  # noqa: BLE001
        log.exception("error recalculando la ruta por %s", disparador.value)
        return None
