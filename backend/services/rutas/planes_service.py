"""Plan de rutas del día: cálculo, revisión, movimiento de paradas y publicación (§6.8.2, §4.1). F2-06.

**El plan es una propuesta hasta que se publica.** El cálculo deja un `borrador` con las paradas y sus horas
estimadas; el despachador lo revisa, mueve lo que quiera y publica. **Publicar** es lo único que toca la operación:
asigna cada folio con `transicionar()` de P04 (así pasa por la tabla de estados de §6.8.6, el historial inmutable y
la auditoría), fija `orden_en_ruta` y avisa a cada técnico su ruta del día.

Los folios que ya tienen técnico asignado a mano **se respetan como fijos**: el optimizador acomoda alrededor de
ellos y publicar no los vuelve a asignar.
"""
import logging
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.dependencias import Actor
from core.errors import ErrorAPI, no_encontrado, prohibido
from core.rls import CONTEXTO_SISTEMA, fijar_contexto
from models.base import Rol
from models.folios import EstadoFolio, Folio
from models.rutas import (
    EstadoPlanRuta, Mercado, RutaParada, RutaPlan, RutaTrazo, RutasConfiguracion,
)
from services import auditoria, folio_estados, notificaciones
from services.rutas import distancias as dist
from services.rutas import motor

log = logging.getLogger("acma.rutas.planes")

# §5.2: la ruta la opera el prestador. El cliente no la ve (son sus folios, pero la logística no es suya).
CALCULAN = {Rol.superadmin, Rol.admin_prestador, Rol.despachador}
CONSULTAN = CALCULAN | {Rol.mesa_control, Rol.direccion_prestador, Rol.supervisor_prestador}
CONFIGURAN = {Rol.superadmin, Rol.admin_prestador}


def _exigir(actor: Actor, roles: set[Rol], que: str) -> None:
    if not actor.es_superadmin and actor.rol not in roles:
        raise prohibido(f"Tu rol no {que}")


def _prestador_de(actor: Actor, prestador_id: UUID | None = None) -> UUID:
    destino = prestador_id if (prestador_id and actor.es_superadmin) else actor.prestador_id
    if destino is None:
        raise ErrorAPI(422, "PRESTADOR_REQUERIDO", "Indica el prestador")
    return destino


# ------------------------------------------------------------------ cálculo

async def calcular(db: AsyncSession, actor: Actor, mercado_id: UUID, fecha: date, *,
                   request: Request | None = None, prestador_id: UUID | None = None) -> RutaPlan:
    """Corre el optimizador y deja un plan en `borrador`. Reemplaza el borrador anterior del mismo día: mientras no
    se publique, el último cálculo es el que vale."""
    _exigir(actor, CALCULAN, "calcula rutas")
    prestador = _prestador_de(actor, prestador_id)
    await motor.mercado_de(db, prestador, mercado_id)
    cfg = await motor.configuracion(db, prestador, mercado_id)

    publicado = (await db.execute(select(RutaPlan).where(
        RutaPlan.mercado_id == mercado_id, RutaPlan.fecha == fecha,
        RutaPlan.estado.in_((EstadoPlanRuta.publicado, EstadoPlanRuta.en_curso))))).scalars().first()
    if publicado is not None:
        raise ErrorAPI(409, "PLAN_YA_PUBLICADO",
                       "Ya hay un plan publicado para ese mercado y esa fecha. Recalcula por técnico con el "
                       "recálculo parcial, o cierra el plan antes de volver a calcular todo.")

    problema = await motor.armar(db, prestador, mercado_id, fecha, cfg=cfg)
    resultado = await motor.resolver(db, problema)

    # El borrador anterior se va: no tiene sentido guardar propuestas que ya nadie va a publicar.
    for viejo in (await db.execute(select(RutaPlan).where(
            RutaPlan.mercado_id == mercado_id, RutaPlan.fecha == fecha,
            RutaPlan.estado == EstadoPlanRuta.borrador))).scalars():
        await db.delete(viejo)
    await db.flush()

    version = int(((await db.execute(select(func.max(RutaPlan.version)).where(
        RutaPlan.mercado_id == mercado_id, RutaPlan.fecha == fecha))).scalar() or 0)) + 1
    plan = RutaPlan(
        prestador_id=prestador, mercado_id=mercado_id, fecha=fecha, estado=EstadoPlanRuta.borrador,
        costo_objetivo=Decimal(str(resultado.get("costo", 0))),
        tiempo_calculo_ms=int(resultado.get("ms", 0)), motor=str(resultado.get("motor", "ortools")),
        calculado_por=actor.id, version=version)
    db.add(plan)
    await db.flush()

    await _guardar_resultado(db, plan, problema, resultado)
    await auditoria.registrar_actor(db, actor, "rutas.calculo", request, prestador_id=prestador,
                                   recurso_tipo="rutas_planes", recurso_id=plan.id,
                                   despues={"mercado_id": str(mercado_id), "fecha": fecha.isoformat(),
                                            "folios_asignados": plan.folios_asignados,
                                            "folios_sin_asignar": plan.folios_sin_asignar,
                                            "motor": plan.motor, "ms": plan.tiempo_calculo_ms,
                                            "transporte": resultado.get("transporte")})
    log.info("plan de rutas %s: %s folios en %s técnicos, %s sin asignar (%sms, %s)", plan.id,
             plan.folios_asignados, len(resultado.get("rutas", [])), plan.folios_sin_asignar,
             plan.tiempo_calculo_ms, resultado.get("transporte"))
    return plan


async def _guardar_resultado(db: AsyncSession, plan: RutaPlan, problema: motor.Problema,
                             resultado: dict[str, Any]) -> None:
    """Pasa las rutas del modelo a `rutas_paradas` y `rutas_trazos`, con sus horas y su holgura de SLA."""
    por_folio = {str(p.folio_id): p for p in problema.paradas}
    por_tecnico = {str(t.usuario_id): t for t in problema.tecnicos}
    inicio = problema.inicio_dia
    total_km = Decimal("0")
    asignados = 0

    for ruta in resultado.get("rutas", []):
        tecnico_id = UUID(str(ruta["tecnico"]))
        trazo_puntos = [por_tecnico[str(ruta["tecnico"])].punto] if str(ruta["tecnico"]) in por_tecnico else []
        for parada in ruta["paradas"]:
            p = por_folio.get(str(parada["folio"]))
            if p is None:
                continue
            llegada = inicio + timedelta(seconds=int(parada["llegada_s"]))
            fin = inicio + timedelta(seconds=int(parada["fin_s"]))
            km = Decimal(str(round(int(parada["metros_desde_anterior"]) / 1000, 2)))
            total_km += km
            holgura = None if p.sla_limite_min is None else p.sla_limite_min - int(parada["llegada_s"]) // 60
            db.add(RutaParada(
                plan_id=plan.id, prestador_id=plan.prestador_id, tecnico_id=tecnico_id, folio_id=p.folio_id,
                orden=int(parada["orden"]), llegada_estimada=llegada, inicio_servicio_estimado=llegada,
                fin_estimado=fin, distancia_desde_anterior_km=km,
                minutos_desde_anterior=int(parada["segundos_desde_anterior"]) // 60,
                minutos_servicio=p.servicio_min,
                ventana_ok=p.ventana[0] <= int(parada["llegada_s"]) // 60 <= p.ventana[1],
                sla_ok=(holgura is None or holgura >= 0), holgura_sla_min=holgura,
                fijo=p.fijo_tecnico is not None))
            trazo_puntos.append(p.punto)
            asignados += 1
        if len(trazo_puntos) >= 2:
            wkt = "LINESTRING(" + ", ".join(f"{pt.lng} {pt.lat}" for pt in trazo_puntos) + ")"
            db.add(RutaTrazo(plan_id=plan.id, prestador_id=plan.prestador_id, tecnico_id=tecnico_id,
                             geometria=func.ST_GeogFromText(wkt), proveedor=problema.proveedor))

    motivos = resultado.get("motivos") or {}
    sin_asignar = []
    for folio_id in resultado.get("sin_asignar", []):
        p = por_folio.get(str(folio_id))
        sin_asignar.append({"folio_id": str(folio_id),
                            "numero_folio": p.numero_folio if p else "",
                            "motivo": motivos.get(str(folio_id), "no entró en ninguna ruta")})
    plan.folios_asignados = asignados
    plan.folios_sin_asignar = len(sin_asignar)
    plan.sin_asignar_json = sin_asignar
    plan.distancia_total_km = total_km
    await db.flush()


# ------------------------------------------------------------------ consulta

async def obtener(db: AsyncSession, actor: Actor, plan_id: UUID) -> RutaPlan:
    plan = await db.get(RutaPlan, plan_id)
    if plan is None:
        raise no_encontrado("Plan de rutas")
    if not actor.es_superadmin and actor.prestador_id != plan.prestador_id:
        raise no_encontrado("Plan de rutas")
    _exigir(actor, CONSULTAN, "consulta las rutas")
    return plan


async def del_dia(db: AsyncSession, actor: Actor, mercado_id: UUID, fecha: date) -> RutaPlan | None:
    """El plan vigente del mercado: el publicado o en curso, y si no hay, el último borrador."""
    _exigir(actor, CONSULTAN, "consulta las rutas")
    filas = list((await db.execute(select(RutaPlan).where(
        RutaPlan.mercado_id == mercado_id, RutaPlan.fecha == fecha)
        .order_by(RutaPlan.version.desc()))).scalars())
    filas = [p for p in filas if actor.es_superadmin or p.prestador_id == actor.prestador_id]
    for estado in (EstadoPlanRuta.en_curso, EstadoPlanRuta.publicado, EstadoPlanRuta.borrador):
        for p in filas:
            if p.estado == estado:
                return p
    return filas[0] if filas else None


async def detalle(db: AsyncSession, actor: Actor, plan: RutaPlan) -> dict[str, Any]:
    """El plan con sus rutas por técnico, listo para la pantalla: paradas con hora, holgura y criticidad."""
    from models.catalogos import Equipo
    from models.criticidad import ActivoCriticidad
    from models.unidades import UnidadNegocio
    from models.usuarios import Usuario

    filas = (await db.execute(
        select(RutaParada, Folio, UnidadNegocio, Usuario)
        .join(Folio, Folio.id == RutaParada.folio_id)
        .join(UnidadNegocio, UnidadNegocio.id == Folio.un_id)
        .join(Usuario, Usuario.id == RutaParada.tecnico_id)
        .where(RutaParada.plan_id == plan.id)
        .order_by(RutaParada.tecnico_id, RutaParada.orden))).all()
    equipo_ids = [f.equipo_id for _, f, _, _ in filas if f.equipo_id] or [UUID(int=0)]
    criticidades = dict((await db.execute(select(ActivoCriticidad.equipo_id, ActivoCriticidad.nivel).where(
        ActivoCriticidad.equipo_id.in_(equipo_ids)))).all())
    # Si el activo no tiene evaluación de F2-05, sirve el campo capturado a mano en su ficha (P04).
    manuales = dict((await db.execute(select(Equipo.id, Equipo.criticidad).where(
        Equipo.id.in_(equipo_ids)))).all())
    rutas: dict[str, dict[str, Any]] = {}
    for parada, folio, un, usuario in filas:
        ruta = rutas.setdefault(str(parada.tecnico_id), {
            "tecnico_id": str(parada.tecnico_id), "tecnico": usuario.nombre, "paradas": [],
            "km": 0.0, "minutos": 0})
        ruta["paradas"].append({
            "parada_id": str(parada.id), "folio_id": str(folio.id), "numero_folio": folio.numero_folio,
            "orden": parada.orden, "un_codigo": un.codigo, "un_nombre": un.nombre,
            "tipo_folio": folio.tipo_folio.value, "estado_folio": folio.estado.value,
            "criticidad": criticidades.get(folio.equipo_id) or manuales.get(folio.equipo_id),
            "llegada_estimada": parada.llegada_estimada, "fin_estimado": parada.fin_estimado,
            "minutos_desde_anterior": parada.minutos_desde_anterior,
            "km_desde_anterior": float(parada.distancia_desde_anterior_km),
            "minutos_servicio": parada.minutos_servicio,
            "ventana_ok": parada.ventana_ok, "sla_ok": parada.sla_ok,
            "holgura_sla_min": parada.holgura_sla_min, "fijo": parada.fijo,
        })
        ruta["km"] = round(ruta["km"] + float(parada.distancia_desde_anterior_km), 2)
        ruta["minutos"] += parada.minutos_desde_anterior + parada.minutos_servicio
    return {
        "plan": {
            "id": str(plan.id), "mercado_id": str(plan.mercado_id), "fecha": plan.fecha,
            "estado": plan.estado.value, "version": plan.version,
            "distancia_total_km": float(plan.distancia_total_km),
            "folios_asignados": plan.folios_asignados, "folios_sin_asignar": plan.folios_sin_asignar,
            "sin_asignar": plan.sin_asignar_json or [], "tiempo_calculo_ms": plan.tiempo_calculo_ms,
            "motor": plan.motor, "costo_objetivo": float(plan.costo_objetivo),
            "publicado_at": plan.publicado_at,
        },
        "rutas": sorted(rutas.values(), key=lambda r: r["tecnico"]),
    }


# ------------------------------------------------------------------ mover una parada a mano

async def mover_parada(db: AsyncSession, actor: Actor, plan: RutaPlan, parada_id: UUID, *,
                       tecnico_destino_id: UUID, orden: int | None = None,
                       request: Request | None = None) -> dict[str, Any]:
    """El despachador mueve una parada de técnico o de posición dentro del borrador.

    **Valida la habilidad certificada igual que la asignación** (§6.8.2: restricción dura no negociable) y vuelve a
    calcular las horas de las dos rutas tocadas. No recalcula el plan completo: es un ajuste a mano, y lo que el
    despachador acaba de decidir no se le discute.
    """
    _exigir(actor, CALCULAN, "mueve paradas de la ruta")
    if plan.estado != EstadoPlanRuta.borrador:
        raise ErrorAPI(409, "PLAN_NO_EDITABLE",
                       "Solo se mueven paradas en un plan en borrador: el publicado se cambia con una reasignación")
    parada = await db.get(RutaParada, parada_id)
    if parada is None or parada.plan_id != plan.id:
        raise no_encontrado("Parada de la ruta")
    if parada.fijo:
        raise ErrorAPI(409, "PARADA_FIJA",
                       "Ese folio está en ejecución: el técnico ya está en la unidad y no se mueve")
    folio = await db.get(Folio, parada.folio_id)
    from services import folios_captura_service as captura

    _, tiene, requerida = await captura.tecnico_con_habilidad(db, tecnico_destino_id, folio)
    if not tiene:
        raise ErrorAPI(409, "TECNICO_SIN_HABILIDAD",
                       f"El técnico destino no tiene la habilidad certificada requerida ({requerida})",
                       [{"habilidad_requerida": requerida}])

    origen_tecnico = parada.tecnico_id
    hermanas = list((await db.execute(select(RutaParada).where(
        RutaParada.plan_id == plan.id, RutaParada.tecnico_id == tecnico_destino_id)
        .order_by(RutaParada.orden))).scalars())
    destino_orden = len(hermanas) if orden is None else max(0, min(orden, len(hermanas)))
    # Se renumera en dos pasos con un hueco negativo para no chocar con el UNIQUE (plan, técnico, orden).
    parada.orden = -1
    parada.tecnico_id = tecnico_destino_id
    await db.flush()
    for i, h in enumerate(hermanas):
        h.orden = i if i < destino_orden else i + 1
    await db.flush()
    parada.orden = destino_orden
    await db.flush()

    await _renumerar(db, plan, origen_tecnico)
    await recalcular_horas(db, plan, [origen_tecnico, tecnico_destino_id])
    await auditoria.registrar_actor(db, actor, "rutas.mover_parada", request, prestador_id=plan.prestador_id,
                                   recurso_tipo="rutas_paradas", recurso_id=parada.id,
                                   antes={"tecnico_id": str(origen_tecnico)},
                                   despues={"tecnico_id": str(tecnico_destino_id), "orden": destino_orden})
    return await detalle(db, actor, plan)


async def _renumerar(db: AsyncSession, plan: RutaPlan, tecnico_id: UUID) -> None:
    paradas = list((await db.execute(select(RutaParada).where(
        RutaParada.plan_id == plan.id, RutaParada.tecnico_id == tecnico_id)
        .order_by(RutaParada.orden))).scalars())
    for i, p in enumerate(paradas):
        if p.orden != i:
            p.orden = i
    await db.flush()


async def recalcular_horas(db: AsyncSession, plan: RutaPlan, tecnicos: list[UUID]) -> None:
    """Vuelve a calcular llegada, fin y holgura de las rutas de esos técnicos con el proveedor de distancias.

    Es la cuenta que sostiene la ETA: no vuelve a optimizar nada, solo recorre la ruta en el orden que quedó.
    """
    from models.unidades import UnidadNegocio

    cfg = await motor.configuracion(db, plan.prestador_id, plan.mercado_id)
    parametros = dist.ParametrosDistancia.desde(cfg)
    inicio_dia = datetime.combine(plan.fecha, cfg.hora_inicio_jornada, tzinfo=UTC)
    centro = await motor._punto_centro(db, await motor.mercado_de(db, plan.prestador_id, plan.mercado_id),
                                       await motor.unidades_del_mercado(db, plan.mercado_id))
    total = Decimal("0")
    for tecnico_id in {t for t in tecnicos if t}:
        paradas = list((await db.execute(select(RutaParada).where(
            RutaParada.plan_id == plan.id, RutaParada.tecnico_id == tecnico_id)
            .order_by(RutaParada.orden))).scalars())
        anterior = centro
        reloj = inicio_dia
        for parada in paradas:
            folio = await db.get(Folio, parada.folio_id)
            un = await db.get(UnidadNegocio, folio.un_id)
            punto = await motor._punto_de_un(db, un) or centro
            tramo = await dist.medir(db, anterior, punto, reloj, proveedor=cfg.proveedor_distancias,
                                     parametros=parametros)
            llegada = reloj + timedelta(seconds=tramo.segundos)
            fin = llegada + timedelta(minutes=parada.minutos_servicio)
            parada.distancia_desde_anterior_km = Decimal(str(round(tramo.metros / 1000, 2)))
            parada.minutos_desde_anterior = tramo.segundos // 60
            parada.llegada_estimada = llegada
            parada.inicio_servicio_estimado = llegada
            parada.fin_estimado = fin
            if parada.holgura_sla_min is not None:
                desfase = int((llegada - inicio_dia).total_seconds() // 60)
                limite = parada.holgura_sla_min + (parada.minutos_desde_anterior or 0)
                parada.holgura_sla_min = limite - desfase if limite else parada.holgura_sla_min
                parada.sla_ok = (parada.holgura_sla_min or 0) >= 0
            total += parada.distancia_desde_anterior_km
            anterior, reloj = punto, fin
    await db.flush()
    suma = (await db.execute(select(func.coalesce(func.sum(RutaParada.distancia_desde_anterior_km), 0))
                             .where(RutaParada.plan_id == plan.id))).scalar()
    plan.distancia_total_km = Decimal(str(suma or 0))
    await db.flush()


# ------------------------------------------------------------------ publicar

async def publicar(db: AsyncSession, actor: Actor, plan: RutaPlan, *,
                   request: Request | None = None) -> dict[str, Any]:
    """Asigna de verdad: cada parada pasa por `transicionar()` de P04 y el folio queda con su técnico y su orden.

    Los folios que ya estaban asignados a ese mismo técnico no se vuelven a transicionar (se respetan como fijos);
    los que están en ejecución tampoco se tocan.
    """
    _exigir(actor, CALCULAN, "publica rutas")
    if plan.estado != EstadoPlanRuta.borrador:
        raise ErrorAPI(409, "PLAN_NO_PUBLICABLE", f"El plan ya está {plan.estado.value}")
    paradas = list((await db.execute(select(RutaParada).where(RutaParada.plan_id == plan.id)
                                     .order_by(RutaParada.tecnico_id, RutaParada.orden))).scalars())
    if not paradas:
        raise ErrorAPI(409, "PLAN_VACIO", "El plan no tiene ninguna parada que publicar")

    asignados, respetados, por_tecnico = 0, 0, {}
    for parada in paradas:
        folio = await db.get(Folio, parada.folio_id)
        por_tecnico.setdefault(parada.tecnico_id, []).append((parada, folio))
        if folio.estado in motor.EN_EJECUCION:
            respetados += 1
            continue
        if folio.tecnico_id == parada.tecnico_id and folio.estado in (EstadoFolio.asignado, EstadoFolio.reasignado,
                                                                      EstadoFolio.en_camino):
            folio.orden_en_ruta = parada.orden
            respetados += 1
            continue
        # La tabla de §6.8.6 manda: a un folio que ya tiene técnico hay que pasarlo primero por `reasignado` y de
        # ahí a `asignado` (es lo que hace la reasignación de P06). Uno que ya está en `reasignado` solo le falta
        # el `asignado`, y uno sin técnico va directo. Sin esto, publicar un plan con folios reasignados fallaba
        # con «no se permite pasar de reasignado a reasignado».
        contexto = {"tecnico_id": str(parada.tecnico_id), "plan_rutas_id": str(plan.id),
                    "orden_en_ruta": parada.orden, "origen": "optimizacion_rutas"}
        notas = f"Ruta del día publicada (orden {parada.orden + 1})"
        if folio.tecnico_id and folio.estado != EstadoFolio.reasignado:
            await folio_estados.transicionar(db, folio, EstadoFolio.reasignado, actor, notas, contexto, request)
        folio.tecnico_id = parada.tecnico_id
        await folio_estados.transicionar(db, folio, EstadoFolio.asignado, actor, notas, contexto, request)
        folio.orden_en_ruta = parada.orden
        folio.ventana_inicio = parada.llegada_estimada
        asignados += 1
    plan.estado = EstadoPlanRuta.publicado
    plan.publicado_por = actor.id
    plan.publicado_at = datetime.now(UTC)
    await db.flush()

    for tecnico_id, lista in por_tecnico.items():
        primera = lista[0][0]
        notificaciones.enviar(
            usuarios=[tecnico_id], prestador_id=plan.prestador_id,
            titulo=f"Tu ruta del {plan.fecha.isoformat()}: {len(lista)} folio(s)",
            cuerpo=(f"Primera parada a las {primera.llegada_estimada.strftime('%H:%M')} "
                    f"({len(lista)} paradas en total)."),
            datos={"plan_rutas_id": str(plan.id), "paradas": len(lista), "url": "/campo"},
            canales=["app", "push"])
    await auditoria.registrar_actor(db, actor, "rutas.publicar", request, prestador_id=plan.prestador_id,
                                   recurso_tipo="rutas_planes", recurso_id=plan.id,
                                   despues={"asignados": asignados, "respetados": respetados,
                                            "tecnicos": len(por_tecnico)})
    log.info("plan %s publicado: %s folios asignados, %s respetados", plan.id, asignados, respetados)
    return {"plan_id": str(plan.id), "estado": plan.estado.value, "asignados": asignados,
            "respetados": respetados, "tecnicos": len(por_tecnico)}


async def cerrar(db: AsyncSession, actor: Actor, plan: RutaPlan, *, request: Request | None = None) -> RutaPlan:
    _exigir(actor, CALCULAN, "cierra rutas")
    plan.estado = EstadoPlanRuta.cerrado
    await db.flush()
    await auditoria.registrar_actor(db, actor, "rutas.cerrar", request, prestador_id=plan.prestador_id,
                                   recurso_tipo="rutas_planes", recurso_id=plan.id,
                                   despues={"estado": plan.estado.value})
    return plan


# ------------------------------------------------------------------ tarea del día

async def calcular_del_dia(db: AsyncSession, fecha: date | None = None) -> dict[str, Any]:
    """Lo que corre la tarea de la madrugada: un plan por mercado activo, en borrador, para que el despachador lo
    encuentre listo. Nunca publica sola: asignar folios es decisión de una persona."""
    from models.usuarios import Usuario

    fecha = fecha or date.today()
    resumen = {"mercados": 0, "planes": 0, "folios": 0, "sin_asignar": 0, "errores": 0}
    mercados = list((await db.execute(select(Mercado).where(Mercado.activo.is_(True)))).scalars())
    for mercado in mercados:
        resumen["mercados"] += 1
        sistema = (await db.execute(select(Usuario).where(Usuario.rol == Rol.superadmin))).scalars().first()
        if sistema is None:
            continue
        actor = Actor(id=sistema.id, email=sistema.email, nombre="sistema", rol=Rol.superadmin,
                      dominio=sistema.dominio, tenant_id=None, prestador_id=mercado.prestador_id,
                      sesion_id=None)
        try:
            punto = await db.begin_nested()
            plan = await calcular(db, actor, mercado.id, fecha, prestador_id=mercado.prestador_id)
            await punto.commit()
        except ErrorAPI as e:
            await punto.rollback()
            if e.codigo != "PLAN_YA_PUBLICADO":
                resumen["errores"] += 1
                log.warning("no se pudo calcular la ruta del mercado %s: %s", mercado.codigo, e.mensaje)
            continue
        except Exception:  # noqa: BLE001 — un mercado mal configurado no detiene a los demás
            await punto.rollback()
            resumen["errores"] += 1
            log.exception("error calculando la ruta del mercado %s", mercado.codigo)
            continue
        resumen["planes"] += 1
        resumen["folios"] += plan.folios_asignados
        resumen["sin_asignar"] += plan.folios_sin_asignar
    return resumen
