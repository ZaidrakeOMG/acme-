"""Hora estimada de llegada (ETA) por parada (§6.8.4, ACT-3.1). F2-06.

La ETA se recalcula con **dónde está el técnico ahora** (F2-03) y el proveedor de distancias, recorriendo lo que le
queda de ruta. No vuelve a optimizar nada: respeta el orden que ya tiene.

Lo que el operador ve es **la hora, no la posición**: en F2-03 se decidió que el cliente no ve el GPS del técnico
(§6.9.5), y eso no cambia aquí. La tarjeta del folio dice «Técnico asignado · llegada estimada 11:40», y cuando la
ETA se mueve más de `MINUTOS_AVISO_ETA` se le avisa por sus canales (F2-02).
"""
import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.folios import EstadoFolio, Folio
from models.rutas import EstadoPlanRuta, RutaParada, RutaPlan
from services.rutas import distancias as dist
from services.rutas import motor

log = logging.getLogger("acma.rutas.eta")

# §3 del prompt: al operador se le avisa cuando la ETA se mueve más de 15 minutos.
MINUTOS_AVISO_ETA = 15
# Estados en los que la ETA tiene sentido: el técnico todavía no llegó.
ANTES_DE_LLEGAR = (EstadoFolio.asignado, EstadoFolio.reasignado, EstadoFolio.en_camino)


async def recalcular_tecnico(db: AsyncSession, plan: RutaPlan, tecnico_id: UUID, *,
                             publicar: bool = True) -> list[dict[str, Any]]:
    """Recalcula la ETA de lo que le queda al técnico, partiendo de su posición actual.

    Devuelve las paradas con su ETA nueva y, si cambió más de 15 minutos, avisa al operador de ese folio.
    """
    from models.catalogos import Tecnico
    from models.unidades import UnidadNegocio

    cfg = await motor.configuracion(db, plan.prestador_id, plan.mercado_id)
    parametros = dist.ParametrosDistancia.desde(cfg)
    mercado = await motor.mercado_de(db, plan.prestador_id, plan.mercado_id)
    centro = await motor._punto_centro(db, mercado, await motor.unidades_del_mercado(db, plan.mercado_id))

    tecnico = (await db.execute(select(Tecnico).where(Tecnico.usuario_id == tecnico_id))).scalar_one_or_none()
    desde = (await motor._punto_tecnico(db, tecnico)) if tecnico is not None else None
    reloj = datetime.now(UTC)
    if desde is None:
        # Sin posición conocida, la ETA se cuenta desde la última parada cerrada o desde el inicio del día.
        desde, reloj = centro, max(reloj, datetime.combine(plan.fecha, cfg.hora_inicio_jornada, tzinfo=UTC))

    paradas = list((await db.execute(select(RutaParada).where(
        RutaParada.plan_id == plan.id, RutaParada.tecnico_id == tecnico_id)
        .order_by(RutaParada.orden))).scalars())
    salida: list[dict[str, Any]] = []
    for parada in paradas:
        folio = await db.get(Folio, parada.folio_id)
        if folio is None or folio.estado not in ANTES_DE_LLEGAR:
            continue   # ya llegó o ya cerró: su ETA dejó de significar algo
        un = await db.get(UnidadNegocio, folio.un_id)
        punto = await motor._punto_de_un(db, un) or centro
        tramo = await dist.medir(db, desde, punto, reloj, proveedor=cfg.proveedor_distancias,
                                 parametros=parametros)
        llegada = reloj + timedelta(seconds=tramo.segundos)
        anterior = parada.llegada_estimada
        cambio_min = None if anterior is None else int((llegada - anterior).total_seconds() // 60)
        parada.llegada_estimada = llegada
        parada.inicio_servicio_estimado = llegada
        parada.fin_estimado = llegada + timedelta(minutes=parada.minutos_servicio)
        parada.minutos_desde_anterior = tramo.segundos // 60
        salida.append({"folio_id": str(folio.id), "numero_folio": folio.numero_folio,
                       "orden": parada.orden, "llegada_estimada": llegada,
                       "cambio_min": cambio_min, "un_codigo": un.codigo if un else None})
        if cambio_min is not None and abs(cambio_min) >= MINUTOS_AVISO_ETA:
            await _avisar_cambio(db, folio, anterior, llegada, cambio_min)
        desde, reloj = punto, llegada + timedelta(minutes=parada.minutos_servicio)
    await db.flush()
    if publicar and salida:
        await _publicar(plan, tecnico_id, salida)
    return salida


async def _publicar(plan: RutaPlan, tecnico_id: UUID, paradas: list[dict[str, Any]]) -> None:
    """Empuja la ETA al tablero de operaciones por el canal que ya existe de F2-03."""
    try:
        from services import operacion_service

        await operacion_service.publicar(None, plan.prestador_id, {
            "tipo": "ruta.eta",
            "tecnico_id": str(tecnico_id),
            "plan_id": str(plan.id),
            "paradas": [{**p, "llegada_estimada": p["llegada_estimada"].isoformat()} for p in paradas],
        })
    except Exception:  # noqa: BLE001 — el tiempo real es una mejora, no un requisito del cálculo
        log.debug("no se pudo publicar la ETA en el canal de operaciones", exc_info=True)


async def _avisar_cambio(db: AsyncSession, folio: Folio, antes: datetime | None, ahora: datetime,
                         cambio_min: int) -> None:
    """Aviso al cliente cuando la hora prometida se mueve de verdad (§3 del prompt: más de 15 minutos)."""
    from services import notificaciones

    sentido = "se retrasó" if cambio_min > 0 else "se adelantó"
    notificaciones.enviar(
        roles=["operador", "admin_un"], tenant_id=folio.tenant_id, prestador_id=folio.prestador_id,
        titulo=f"Folio {folio.numero_folio}: la llegada {sentido} {abs(cambio_min)} minutos",
        cuerpo=(f"La hora estimada de llegada pasó de {antes.strftime('%H:%M') if antes else 'sin estimar'} "
                f"a {ahora.strftime('%H:%M')}."),
        datos={"folio_id": str(folio.id), "numero_folio": folio.numero_folio,
               "llegada_estimada": ahora.isoformat(), "cambio_min": cambio_min,
               "url": f"/campo/folio/{folio.id}"},
        canales=["app", "push", "whatsapp"])


async def del_folio(db: AsyncSession, folio: Folio) -> dict[str, Any]:
    """Lo que la tarjeta del folio muestra al operador: técnico, hora estimada y de dónde sale ese número.

    Sustituye el «Disponible en Fase 2» de las apps. Sin plan publicado o sin técnico, lo dice en lugar de
    inventar una hora.
    """
    from models.usuarios import Usuario

    if folio.tecnico_id is None:
        return {"tiene_eta": False, "motivo": "El folio todavía no tiene técnico asignado"}
    usuario = await db.get(Usuario, folio.tecnico_id)
    parada = (await db.execute(
        select(RutaParada).join(RutaPlan, RutaPlan.id == RutaParada.plan_id).where(
            RutaParada.folio_id == folio.id,
            RutaPlan.estado.in_((EstadoPlanRuta.publicado, EstadoPlanRuta.en_curso)))
        .order_by(RutaPlan.version.desc()))).scalars().first()
    if parada is None or parada.llegada_estimada is None:
        return {"tiene_eta": False, "tecnico": usuario.nombre if usuario else None,
                "motivo": "El folio no está en una ruta publicada: no hay hora estimada todavía"}
    if folio.estado not in ANTES_DE_LLEGAR:
        return {"tiene_eta": False, "tecnico": usuario.nombre if usuario else None,
                "motivo": f"El folio ya está {folio.estado.value}"}
    return {
        "tiene_eta": True,
        "tecnico": usuario.nombre if usuario else None,
        "llegada_estimada": parada.llegada_estimada,
        "orden": parada.orden,
        "en_camino": folio.estado == EstadoFolio.en_camino,
        "minutos_restantes": max(0, int((parada.llegada_estimada - datetime.now(UTC)).total_seconds() // 60)),
    }


async def refrescar_todas(db: AsyncSession) -> dict[str, int]:
    """Tarea periódica: refresca la ETA de cada técnico con ruta publicada hoy."""
    from datetime import date

    resumen = {"planes": 0, "tecnicos": 0, "paradas": 0}
    planes = list((await db.execute(select(RutaPlan).where(
        RutaPlan.fecha == date.today(),
        RutaPlan.estado.in_((EstadoPlanRuta.publicado, EstadoPlanRuta.en_curso))))).scalars())
    for plan in planes:
        resumen["planes"] += 1
        tecnicos = list((await db.execute(select(RutaParada.tecnico_id).where(
            RutaParada.plan_id == plan.id).distinct())).scalars())
        for tecnico_id in tecnicos:
            resumen["tecnicos"] += 1
            resumen["paradas"] += len(await recalcular_tecnico(db, plan, tecnico_id))
    return resumen
