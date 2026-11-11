"""Los cuatro triggers de plan que faltaban de §6.9.1: `medidor_umbral`, `medidor_intervalo`, `evento` y
`combinado`. F2-04.

Todo se apoya en un solo predicado: **¿este trigger se cumple hoy para este equipo?** Los cuatro tipos saben
contestarlo sin depender de que alguien les avise en el momento exacto, porque todos se pueden leer como «desde la
última ejecución del plan en este equipo pasó X»:

- `medidor_umbral` — el acumulado del medidor llegó al umbral y el plan nunca se ejecutó con ese valor.
- `medidor_intervalo` — el acumulado llegó a `ultimo_valor_medidor + intervalo`.
- `evento` — el hecho ocurrió después de la última ejecución (o en los últimos X días, para `fallas_repetidas`).
- `combinado` — OR: alguno de sus triggers; AND: todos.

Por eso la **evaluación inmediata** (al registrar una lectura válida o al ocurrir un evento) y la **nocturna** dan
el mismo resultado y no se duplican: las dos llaman al mismo predicado y las dos pasan por el mismo candado, que es
«no hay folio abierto de este plan en este equipo».

Y por eso el reinicio del combinado sale gratis: al cerrarse el folio preventivo, P06 ya mueve
`fecha_ultima_ejecucion` y F2-04 mueve `ultimo_valor_medidor`, que son la referencia de **todos** los triggers del
plan. Ejecutar el plan reinicia el combinado completo, como pide §6.9.1.
"""
import logging
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ErrorAPI
from models.catalogos import Equipo, NivelSeveridadCatalogo
from models.folios import EstadoFolio, Folio, FolioRefaccion, TipoFolio
from models.medidores import (
    EVENTO_CAMBIO_MEDIDOR, EVENTO_EQUIPO_INSTALADO, EVENTO_FALLA_GRAVE, EVENTO_FALLAS_REPETIDAS,
    EVENTO_REEMPLAZO_COMPONENTE, EquipoMedidor, MedidorCambio, TipoCambioMedidor, TipoMedidor,
)
from models.preventivos import (
    TRIGGERS_MEDIDOR, TRIGGERS_POR_FECHA, EquipoPlan, EstadoEjecucionPlan, EstadoPlan, EstadoPreventivo,
    OrigenPreventivo, PlanEjecucion, PlanMantenimiento, PlanTrigger, PreventivoCalendario, TipoTrigger,
)

log = logging.getLogger("acma.triggers")
CERO = Decimal("0")
CENTAVO = Decimal("0.01")
ESTADOS_ABIERTOS = [e for e in EstadoFolio if e not in (EstadoFolio.cerrado, EstadoFolio.cancelado)]


# ------------------------------------------------------------------ referencias del plan en un equipo

def _desde_fecha(ep: EquipoPlan) -> date:
    return ep.fecha_ultima_ejecucion or ep.fecha_alta


async def _medidor_del_trigger(db: AsyncSession, trigger: PlanTrigger, equipo_id: UUID) -> EquipoMedidor | None:
    tipo_id = (trigger.parametros_json or {}).get("tipo_medidor_id")
    if not tipo_id:
        return None
    return (await db.execute(select(EquipoMedidor).where(
        EquipoMedidor.equipo_id == equipo_id, EquipoMedidor.tipo_medidor_id == UUID(str(tipo_id)),
        EquipoMedidor.activo.is_(True)))).scalar_one_or_none()


def _objetivo(trigger: PlanTrigger, ep: EquipoPlan, m: EquipoMedidor) -> Decimal:
    """Valor acumulado con el que el trigger se cumple."""
    p = trigger.parametros_json or {}
    if trigger.tipo_trigger == TipoTrigger.medidor_umbral:
        return Decimal(str(p["umbral"]))
    base = ep.ultimo_valor_medidor if ep.ultimo_valor_medidor is not None else m.valor_ultimo_pm
    return (Decimal(base or 0) + Decimal(str(p["intervalo"]))).quantize(CENTAVO)


async def claves_hijas(db: AsyncSession, plan_id: UUID) -> set[str]:
    """Claves de los triggers que son **condición** de un combinado. Por sí solos no disparan nada: el plan se
    ejecuta cuando lo dice el combinado, que es lo que une «90 días O 400 horas» en una sola regla."""
    hijas: set[str] = set()
    for t in (await db.execute(select(PlanTrigger).where(PlanTrigger.plan_id == plan_id,
                                                         PlanTrigger.tipo_trigger == TipoTrigger.combinado))).scalars():
        hijas.update(str(c) for c in (t.parametros_json or {}).get("triggers_claves", []))
    return hijas


async def _hijos_combinado(db: AsyncSession, trigger: PlanTrigger) -> list[PlanTrigger]:
    """Los triggers que el combinado referencia, por `clave` (identidad estable dentro del plan)."""
    claves = [str(c) for c in (trigger.parametros_json or {}).get("triggers_claves", [])]
    if not claves:
        return []
    filas = (await db.execute(select(PlanTrigger).where(PlanTrigger.plan_id == trigger.plan_id,
                                                        PlanTrigger.clave.in_(claves)))).scalars().all()
    por_clave = {t.clave: t for t in filas}
    return [por_clave[c] for c in claves if c in por_clave]


# ------------------------------------------------------------------ eventos del catálogo cerrado

async def _ocurrio_evento(db: AsyncSession, trigger: PlanTrigger, equipo: Equipo, desde: date, hoy: date) -> bool:
    """§6.9.1 «Por evento». Todos se leen como «ocurrió después de la última ejecución del plan»."""
    p = trigger.parametros_json or {}
    clave = p.get("evento")
    limite = datetime.combine(desde, datetime.min.time(), tzinfo=UTC)

    if clave == EVENTO_FALLA_GRAVE:
        severidades = [str(s) for s in (p.get("severidades") or ["alta", "critica"])]
        fila = (await db.execute(
            select(Folio.id).join(NivelSeveridadCatalogo, NivelSeveridadCatalogo.id == Folio.severidad_id).where(
                Folio.equipo_id == equipo.id, Folio.tipo_folio.in_((TipoFolio.correctivo, TipoFolio.especial)),
                Folio.estado == EstadoFolio.cerrado, Folio.fecha_cierre > limite,
                NivelSeveridadCatalogo.clave.in_(severidades)).limit(1))).first()
        return fila is not None

    if clave == EVENTO_FALLAS_REPETIDAS:
        cantidad, dias = int(p.get("cantidad") or 3), int(p.get("dias") or 30)
        ventana = datetime.combine(hoy - timedelta(days=dias), datetime.min.time(), tzinfo=UTC)
        total = (await db.execute(select(func.count(Folio.id)).where(
            Folio.equipo_id == equipo.id, Folio.tipo_folio == TipoFolio.correctivo,
            Folio.estado == EstadoFolio.cerrado, Folio.fecha_cierre > max(ventana, limite)))).scalar() or 0
        return total >= cantidad

    if clave == EVENTO_EQUIPO_INSTALADO:
        if equipo.fecha_instalacion is None:
            return False
        dias = int(p.get("dias_despues") or 0)
        # Una sola vez: si el plan ya se ejecutó en este equipo, la instalación ya quedó atendida.
        return equipo.fecha_instalacion + timedelta(days=dias) <= hoy

    if clave == EVENTO_REEMPLAZO_COMPONENTE:
        categorias = [str(c).lower() for c in (p.get("categorias") or [])]
        from models.inventario import Articulo

        consulta = (select(FolioRefaccion.id).join(Folio, Folio.id == FolioRefaccion.folio_id)
                    .where(Folio.equipo_id == equipo.id, FolioRefaccion.created_at > limite))
        if categorias:
            consulta = consulta.join(Articulo, Articulo.id == FolioRefaccion.articulo_id).where(
                func.lower(Articulo.categoria).in_(categorias))
        return (await db.execute(consulta.limit(1))).first() is not None

    if clave == EVENTO_CAMBIO_MEDIDOR:
        tipo_id = p.get("tipo_medidor_id")
        consulta = (select(MedidorCambio.id).join(EquipoMedidor, EquipoMedidor.id == MedidorCambio.equipo_medidor_id)
                    .where(EquipoMedidor.equipo_id == equipo.id, MedidorCambio.tipo == TipoCambioMedidor.reemplazo_medidor,
                           MedidorCambio.timestamp > limite))
        if tipo_id:
            consulta = consulta.where(EquipoMedidor.tipo_medidor_id == UUID(str(tipo_id)))
        return (await db.execute(consulta.limit(1))).first() is not None

    return False


# ------------------------------------------------------------------ el predicado

async def cumple(db: AsyncSession, plan: PlanMantenimiento, ep: EquipoPlan, equipo: Equipo, trigger: PlanTrigger,
                 hoy: date | None = None) -> tuple[bool, Decimal | None]:
    """¿Este trigger se cumple hoy para este equipo? Devuelve (se cumple, valor del medidor si aplica)."""
    hoy = hoy or date.today()
    from services import planes_service

    if trigger.tipo_trigger in TRIGGERS_POR_FECHA:
        fecha = planes_service.proxima_fecha_trigger(trigger.tipo_trigger, trigger.parametros_json or {}, _desde_fecha(ep), hoy)
        return (fecha is not None and fecha <= hoy), None

    if trigger.tipo_trigger in TRIGGERS_MEDIDOR:
        m = await _medidor_del_trigger(db, trigger, equipo.id)
        if m is None:
            return False, None
        objetivo = _objetivo(trigger, ep, m)
        if (trigger.tipo_trigger == TipoTrigger.medidor_umbral and ep.ultimo_valor_medidor is not None
                and Decimal(ep.ultimo_valor_medidor) >= objetivo):
            # `medidor_umbral` es un hito, no un ciclo: una vez atendido a las 500 h no vuelve a pedirse. El que se
            # repite cada tanto es `medidor_intervalo`.
            return False, Decimal(m.valor_acumulado)
        return (Decimal(m.valor_acumulado) >= objetivo), Decimal(m.valor_acumulado)

    if trigger.tipo_trigger == TipoTrigger.evento:
        return await _ocurrio_evento(db, trigger, equipo, _desde_fecha(ep), hoy), None

    if trigger.tipo_trigger == TipoTrigger.combinado:
        hijos = await _hijos_combinado(db, trigger)
        if not hijos:
            return False, None
        logica = str((trigger.parametros_json or {}).get("logica") or trigger.logica_combinacion or "OR").upper()
        resultados = [await cumple(db, plan, ep, equipo, h, hoy) for h in hijos]
        valores = [v for _ok, v in resultados if v is not None]
        valor = max(valores) if valores else None
        if logica == "AND":
            return all(ok for ok, _v in resultados), valor
        return any(ok for ok, _v in resultados), valor
    return False, None


async def proyeccion(db: AsyncSession, plan: PlanMantenimiento, ep: EquipoPlan, equipo: Equipo, trigger: PlanTrigger,
                     hoy: date | None = None) -> dict[str, Any]:
    """Cuándo se dispararía este trigger. Para los de medidor, con el incremento promedio; para los de evento no hay
    fecha que proyectar (la respuesta es «cuando pase»)."""
    hoy = hoy or date.today()
    from services import medidores_service, planes_service

    base = {"clave": trigger.clave, "tipo_trigger": trigger.tipo_trigger, "parametros_json": trigger.parametros_json,
            "fecha_estimada": None, "valor_objetivo": None, "valor_actual": None, "unidad": None,
            "faltante": None, "motivo": ""}
    if trigger.tipo_trigger in TRIGGERS_POR_FECHA:
        fecha = planes_service.proxima_fecha_trigger(trigger.tipo_trigger, trigger.parametros_json or {}, _desde_fecha(ep), hoy)
        return {**base, "fecha_estimada": fecha, "motivo": "por fecha"}
    if trigger.tipo_trigger in TRIGGERS_MEDIDOR:
        m = await _medidor_del_trigger(db, trigger, equipo.id)
        if m is None:
            return {**base, "motivo": "El equipo no tiene ese medidor"}
        tipo = await db.get(TipoMedidor, m.tipo_medidor_id)
        objetivo = _objetivo(trigger, ep, m)
        actual = Decimal(m.valor_acumulado)
        if (trigger.tipo_trigger == TipoTrigger.medidor_umbral and ep.ultimo_valor_medidor is not None
                and Decimal(ep.ultimo_valor_medidor) >= objetivo):
            return {**base, "valor_objetivo": objetivo, "valor_actual": actual,
                    "unidad": tipo.unidad if tipo else "", "motivo": "Hito ya atendido: el umbral no se repite"}
        faltante = (objetivo - actual).quantize(CENTAVO)
        incremento, origen = await medidores_service.incremento_diario(db, m)
        if faltante <= CERO:
            fecha = hoy
        elif incremento > CERO:
            fecha = hoy + timedelta(days=int((faltante / incremento).to_integral_value(rounding="ROUND_CEILING")))
        else:
            fecha = None
        return {**base, "fecha_estimada": fecha, "valor_objetivo": objetivo, "valor_actual": actual,
                "unidad": tipo.unidad if tipo else "", "faltante": max(CERO, faltante),
                "motivo": f"{incremento} {tipo.unidad if tipo else ''} al día ({origen})" if incremento > CERO
                          else "Sin lecturas suficientes para proyectar"}
    if trigger.tipo_trigger == TipoTrigger.evento:
        ok, _v = await cumple(db, plan, ep, equipo, trigger, hoy)
        return {**base, "fecha_estimada": hoy if ok else None,
                "motivo": "El evento ya ocurrió" if ok else f"Cuando ocurra: {(trigger.parametros_json or {}).get('evento')}"}
    if trigger.tipo_trigger == TipoTrigger.combinado:
        hijos = await _hijos_combinado(db, trigger)
        detalles = [await proyeccion(db, plan, ep, equipo, h, hoy) for h in hijos]
        fechas = [d["fecha_estimada"] for d in detalles if d["fecha_estimada"] is not None]
        logica = str((trigger.parametros_json or {}).get("logica") or trigger.logica_combinacion or "OR").upper()
        if logica == "AND":
            fecha = max(fechas) if len(fechas) == len(detalles) and fechas else None
        else:
            fecha = min(fechas) if fechas else None
        return {**base, "fecha_estimada": fecha, "detalles": detalles,
                "motivo": "lo que ocurra primero" if logica == "OR" else "cuando se cumplan todas"}
    return base


# ------------------------------------------------------------------ generación

async def _folio_abierto(db: AsyncSession, plan_id: UUID, equipo_id: UUID) -> Folio | None:
    """El candado contra duplicados: mientras el preventivo anterior de este plan siga abierto, no nace otro."""
    return (await db.execute(select(Folio).where(Folio.plan_id == plan_id, Folio.equipo_id == equipo_id,
                                                 Folio.estado.in_(ESTADOS_ABIERTOS)).limit(1))).scalar_one_or_none()


async def _generar(db: AsyncSession, plan: PlanMantenimiento, ep: EquipoPlan, equipo: Equipo, trigger: PlanTrigger,
                   fecha: date, valor: Decimal | None, origen: OrigenPreventivo, hoy: date) -> dict[str, Any] | None:
    """El folio preventivo lo crea **el sistema** (§6.9.1), aunque el disparo venga de la lectura del operador o del
    cierre del folio del técnico: ni uno ni otro pueden escribir `folios` del cliente por la RLS de P04. Así que el
    alta va con el contexto de sistema dentro de la misma transacción y luego se restaura el del actor, igual que el
    alta de equipos de P08."""
    from core.rls import CONTEXTO_SISTEMA, fijar_contexto

    previo = db.info.get("rls")
    await fijar_contexto(db, CONTEXTO_SISTEMA)
    try:
        return await _generar_como_sistema(db, plan, ep, equipo, trigger, fecha, valor, origen, hoy)
    finally:
        if previo is not None:
            await fijar_contexto(db, previo)


async def _generar_como_sistema(db: AsyncSession, plan: PlanMantenimiento, ep: EquipoPlan, equipo: Equipo,
                                trigger: PlanTrigger, fecha: date, valor: Decimal | None,
                                origen: OrigenPreventivo, hoy: date) -> dict[str, Any] | None:
    from services import preventivos_service

    abierto = await _folio_abierto(db, plan.id, equipo.id)
    if abierto is not None:
        return None
    # Idempotencia del día: no se genera dos veces la misma ejecución programada. Una que ya se **ejecutó** no
    # bloquea: si el uso vuelve a cruzar el intervalo, eso es un mantenimiento nuevo, no el mismo otra vez.
    ya = (await db.execute(select(PlanEjecucion.id).where(
        PlanEjecucion.plan_id == plan.id, PlanEjecucion.equipo_id == equipo.id,
        PlanEjecucion.fecha_programada == fecha,
        PlanEjecucion.estado != EstadoEjecucionPlan.ejecutada))).first()
    if ya:
        return None
    detalle = {TipoTrigger.medidor_umbral: "umbral del medidor", TipoTrigger.medidor_intervalo: "intervalo del medidor",
               TipoTrigger.evento: f"evento {(trigger.parametros_json or {}).get('evento')}",
               TipoTrigger.combinado: "trigger combinado"}.get(trigger.tipo_trigger, "plan")
    cal = PreventivoCalendario(
        prestador_id=plan.prestador_id, tenant_id=ep.tenant_id, un_id=equipo.un_id, equipo_id=equipo.id,
        plan_id=plan.id, fecha_programada=fecha, fecha_programada_original=fecha, origen=origen,
        descripcion=f"Mantenimiento preventivo: {plan.nombre} ({detalle})", cargado_por=plan.created_by,
        plan_trigger_id=trigger.id, valor_medidor=valor)
    db.add(cal)
    await db.flush()
    folio = await preventivos_service.generar_folio_preventivo(db, cal, plan, hoy)
    db.add(PlanEjecucion(plan_id=plan.id, prestador_id=plan.prestador_id, tenant_id=ep.tenant_id, equipo_id=equipo.id,
                         folio_id=folio.id, calendario_id=cal.id, formulario_id=cal.formulario_id,
                         fecha_programada=fecha, estado=EstadoEjecucionPlan.generada, plan_trigger_id=trigger.id,
                         valor_medidor=valor))
    await db.flush()
    return {"plan_id": plan.id, "plan": plan.nombre, "equipo_id": equipo.id, "folio_id": folio.id,
            "numero_folio": folio.numero_folio, "fecha_programada": fecha, "origen": origen.value,
            "trigger": trigger.tipo_trigger.value, "valor_medidor": valor}


def _origen_de(tipo: TipoTrigger) -> OrigenPreventivo:
    if tipo in TRIGGERS_MEDIDOR:
        return OrigenPreventivo.medidor
    if tipo == TipoTrigger.evento:
        return OrigenPreventivo.evento
    return OrigenPreventivo.plan


async def origen_y_trigger(db: AsyncSession, plan: PlanMantenimiento, ep: EquipoPlan, equipo: Equipo,
                           hoy: date | None = None) -> tuple[OrigenPreventivo, PlanTrigger | None, Decimal | None]:
    """Qué trigger explica la fecha próxima del plan. La tarea nocturna de P06 la usa para pintar el origen del
    folio («por medidor» / «por evento») en el calendario, en lugar de etiquetar todo como «plan»."""
    hoy = hoy or date.today()
    triggers = (await db.execute(select(PlanTrigger).where(PlanTrigger.plan_id == plan.id)
                                 .order_by(PlanTrigger.clave))).scalars().all()
    hijas = await claves_hijas(db, plan.id)
    mejor: tuple[date, PlanTrigger, Decimal | None] | None = None
    for t in triggers:
        if t.clave in hijas:
            continue
        p = await proyeccion(db, plan, ep, equipo, t, hoy)
        if p["fecha_estimada"] is None:
            continue
        if mejor is None or p["fecha_estimada"] < mejor[0]:
            mejor = (p["fecha_estimada"], t, p.get("valor_actual"))
    if mejor is None:
        return OrigenPreventivo.plan, None, None
    _fecha, trigger, valor = mejor
    if trigger.tipo_trigger == TipoTrigger.combinado:
        hijos = await _hijos_combinado(db, trigger)
        if any(h.tipo_trigger in TRIGGERS_MEDIDOR for h in hijos):
            return OrigenPreventivo.medidor, trigger, valor
        if any(h.tipo_trigger == TipoTrigger.evento for h in hijos):
            return OrigenPreventivo.evento, trigger, valor
        return OrigenPreventivo.plan, trigger, valor
    return _origen_de(trigger.tipo_trigger), trigger, valor


async def _asignaciones_del_equipo(db: AsyncSession, equipo_id: UUID) -> list[tuple[EquipoPlan, PlanMantenimiento]]:
    return list((await db.execute(
        select(EquipoPlan, PlanMantenimiento).join(PlanMantenimiento, PlanMantenimiento.id == EquipoPlan.plan_id)
        .where(EquipoPlan.equipo_id == equipo_id, EquipoPlan.activo.is_(True),
               PlanMantenimiento.estado == EstadoPlan.activo))).all())


async def _evaluar_asignacion(db: AsyncSession, plan: PlanMantenimiento, ep: EquipoPlan, equipo: Equipo,
                              tipos: set[TipoTrigger], hoy: date) -> dict[str, Any] | None:
    """Evalúa los triggers del plan de los tipos indicados; el primero que se cumple genera el folio."""
    triggers = (await db.execute(select(PlanTrigger).where(PlanTrigger.plan_id == plan.id)
                                 .order_by(PlanTrigger.clave))).scalars().all()
    hijas = await claves_hijas(db, plan.id)
    for t in triggers:
        if t.tipo_trigger not in tipos or t.clave in hijas:
            continue
        ok, valor = await cumple(db, plan, ep, equipo, t, hoy)
        if not ok:
            continue
        origen = _origen_de(t.tipo_trigger)
        if t.tipo_trigger == TipoTrigger.combinado:
            # El combinado hereda el origen de lo que lo disparó: con medidor involucrado, «por medidor».
            hijos = await _hijos_combinado(db, t)
            origen = (OrigenPreventivo.medidor if any(h.tipo_trigger in TRIGGERS_MEDIDOR for h in hijos)
                      else OrigenPreventivo.evento if any(h.tipo_trigger == TipoTrigger.evento for h in hijos)
                      else OrigenPreventivo.plan)
        else:
            origen = _origen_de(t.tipo_trigger)
        generado = await _generar(db, plan, ep, equipo, t, hoy, valor, origen, hoy)
        if generado is not None:
            return generado
        return None
    return None


async def evaluar_medidor(db: AsyncSession, m: EquipoMedidor, hoy: date | None = None) -> list[dict[str, Any]]:
    """Evaluación inmediata al registrar una lectura válida: planes por uso de ese equipo, aquí y ahora."""
    hoy = hoy or date.today()
    equipo = await db.get(Equipo, m.equipo_id)
    if equipo is None:
        return []
    generados = []
    for ep, plan in await _asignaciones_del_equipo(db, equipo.id):
        try:
            punto = await db.begin_nested()
            g = await _evaluar_asignacion(db, plan, ep, equipo, TRIGGERS_MEDIDOR | {TipoTrigger.combinado}, hoy)
            await punto.commit()
        except Exception:  # noqa: BLE001 — una lectura no debe fallar porque un plan esté mal configurado
            await punto.rollback()
            log.exception("No se pudo evaluar el plan %s con la lectura del medidor %s", plan.id, m.id)
            continue
        if g is not None:
            generados.append(g)
    await _refrescar_proyeccion_medidor(db, m, hoy)
    return generados


async def evaluar_evento(db: AsyncSession, clave: str, *, equipo_id: UUID, datos: dict[str, Any] | None = None,
                         hoy: date | None = None) -> list[dict[str, Any]]:
    """Evaluación inmediata cuando pasa algo del catálogo cerrado (cierre de folio grave, alta de equipo, consumo de
    refacción, cambio de medidor). Los ganchos la llaman; no hay sondeo."""
    hoy = hoy or date.today()
    equipo = await db.get(Equipo, equipo_id)
    if equipo is None:
        return []
    generados = []
    for ep, plan in await _asignaciones_del_equipo(db, equipo.id):
        triggers = (await db.execute(select(PlanTrigger).where(PlanTrigger.plan_id == plan.id))).scalars().all()
        claves = set()
        for t in triggers:
            if t.tipo_trigger == TipoTrigger.evento:
                claves.add((t.parametros_json or {}).get("evento"))
            elif t.tipo_trigger == TipoTrigger.combinado:
                for h in await _hijos_combinado(db, t):
                    if h.tipo_trigger == TipoTrigger.evento:
                        claves.add((h.parametros_json or {}).get("evento"))
        if clave not in claves:
            continue
        try:
            punto = await db.begin_nested()
            g = await _evaluar_asignacion(db, plan, ep, equipo, {TipoTrigger.evento, TipoTrigger.combinado}, hoy)
            await punto.commit()
        except Exception:  # noqa: BLE001
            await punto.rollback()
            log.exception("No se pudo evaluar el plan %s con el evento %s", plan.id, clave)
            continue
        if g is not None:
            generados.append({**g, "evento": clave, "datos": datos or {}})
    return generados


async def evaluar_pendientes(db: AsyncSession, hoy: date | None = None) -> dict[str, int]:
    """Pasada nocturna: lo mismo que la inmediata, para todo el universo. Cubre lo que no tuvo quien le avisara
    (una lectura estimada de ayer, un evento que nació fuera de un gancho) y vuelve a proyectar las fechas de los
    planes por medidor para que la tarea de P06 los recoja dentro de su horizonte."""
    hoy = hoy or date.today()
    resumen = {"generados": 0, "evaluados": 0, "proyecciones": 0}
    asignaciones = (await db.execute(
        select(EquipoPlan, PlanMantenimiento).join(PlanMantenimiento, PlanMantenimiento.id == EquipoPlan.plan_id)
        .where(EquipoPlan.activo.is_(True), PlanMantenimiento.estado == EstadoPlan.activo))).all()
    for ep, plan in asignaciones:
        triggers = (await db.execute(select(PlanTrigger).where(PlanTrigger.plan_id == plan.id))).scalars().all()
        tipos = {t.tipo_trigger for t in triggers}
        if not tipos & (TRIGGERS_MEDIDOR | {TipoTrigger.evento, TipoTrigger.combinado}):
            continue
        equipo = await db.get(Equipo, ep.equipo_id)
        if equipo is None:
            continue
        resumen["evaluados"] += 1
        try:
            punto = await db.begin_nested()
            g = await _evaluar_asignacion(db, plan, ep, equipo, TRIGGERS_MEDIDOR | {TipoTrigger.evento, TipoTrigger.combinado}, hoy)
            await punto.commit()
        except Exception:  # noqa: BLE001
            await punto.rollback()
            log.exception("No se pudo evaluar el plan %s del equipo %s", plan.id, ep.equipo_id)
            continue
        if g is not None:
            resumen["generados"] += 1
            continue
        if await _proyectar_asignacion(db, plan, ep, equipo, triggers, hoy):
            resumen["proyecciones"] += 1
    await db.flush()
    return resumen


async def _proyectar_asignacion(db: AsyncSession, plan: PlanMantenimiento, ep: EquipoPlan, equipo: Equipo,
                                triggers: list[PlanTrigger], hoy: date) -> bool:
    """Escribe en `equipo_planes.fecha_proxima_ejecucion` la primera fecha de todos los triggers, incluida la
    proyección por medidor, para que el calendario y la tarea nocturna de P06 la vean."""
    hijas = await claves_hijas(db, plan.id)
    fechas = []
    for t in triggers:
        if t.clave in hijas:
            continue   # es condición de un combinado, no una regla por sí sola
        p = await proyeccion(db, plan, ep, equipo, t, hoy)
        if p["fecha_estimada"] is not None:
            fechas.append(p["fecha_estimada"])
    nueva = min(fechas) if fechas else None
    if nueva != ep.fecha_proxima_ejecucion:
        ep.fecha_proxima_ejecucion = nueva
        await db.flush()
        return True
    return False


async def _refrescar_proyeccion_medidor(db: AsyncSession, m: EquipoMedidor, hoy: date) -> None:
    equipo = await db.get(Equipo, m.equipo_id)
    if equipo is None:
        return
    for ep, plan in await _asignaciones_del_equipo(db, equipo.id):
        triggers = (await db.execute(select(PlanTrigger).where(PlanTrigger.plan_id == plan.id))).scalars().all()
        if not {t.tipo_trigger for t in triggers} & (TRIGGERS_MEDIDOR | {TipoTrigger.combinado}):
            continue
        await _proyectar_asignacion(db, plan, ep, equipo, triggers, hoy)


# ------------------------------------------------------------------ consultas para la interfaz

async def proximos_de_medidor(db: AsyncSession, m: EquipoMedidor, hoy: date | None = None) -> list[dict[str, Any]]:
    """«Próximo mantenimiento por uso» de la ficha del equipo, por plan."""
    hoy = hoy or date.today()
    salida = []
    for ep, plan in await _asignaciones_del_equipo(db, m.equipo_id):
        equipo = await db.get(Equipo, m.equipo_id)
        triggers = (await db.execute(select(PlanTrigger).where(PlanTrigger.plan_id == plan.id))).scalars().all()
        for t in triggers:
            if t.tipo_trigger not in TRIGGERS_MEDIDOR:
                continue
            if str((t.parametros_json or {}).get("tipo_medidor_id") or "") != str(m.tipo_medidor_id):
                continue
            p = await proyeccion(db, plan, ep, equipo, t, hoy)
            salida.append({"plan_id": plan.id, "plan": plan.nombre, "ventana_dias": plan.tiempo_ventana_dias, **p})
    return salida


async def simular(db: AsyncSession, plan: PlanMantenimiento, hoy: date | None = None) -> list[dict[str, Any]]:
    """«¿Cuándo se dispararía este plan con las lecturas actuales?» — una fila por equipo asignado."""
    hoy = hoy or date.today()
    filas = []
    asignaciones = (await db.execute(select(EquipoPlan, Equipo).join(Equipo, Equipo.id == EquipoPlan.equipo_id)
                                     .where(EquipoPlan.plan_id == plan.id, EquipoPlan.activo.is_(True)))).all()
    triggers = (await db.execute(select(PlanTrigger).where(PlanTrigger.plan_id == plan.id)
                                 .order_by(PlanTrigger.clave))).scalars().all()
    hijas = await claves_hijas(db, plan.id)
    for ep, equipo in asignaciones:
        # Los hijos de un combinado se muestran (la pantalla explica por qué falta), pero la fecha del plan sale
        # solo de las reglas que disparan por sí mismas.
        detalles = [await proyeccion(db, plan, ep, equipo, t, hoy) for t in triggers]
        fechas = [d["fecha_estimada"] for d in detalles
                  if d["fecha_estimada"] is not None and d["clave"] not in hijas]
        abierto = await _folio_abierto(db, plan.id, equipo.id)
        filas.append({
            "equipo_id": equipo.id, "equipo": equipo.nombre, "equipo_codigo": equipo.codigo,
            "fecha_estimada": min(fechas) if fechas else None,
            "ultima_ejecucion": ep.fecha_ultima_ejecucion, "ultimo_valor_medidor": ep.ultimo_valor_medidor,
            "folio_abierto": None if abierto is None else {"id": abierto.id, "numero_folio": abierto.numero_folio,
                                                           "estado": abierto.estado.value},
            "triggers": detalles,
        })
    return filas


# ------------------------------------------------------------------ cierre del preventivo: último PM

async def al_cerrar(db: AsyncSession, folio: Folio) -> None:
    """Al cerrarse un folio preventivo generado por un plan con medidor: `equipo_medidores.valor_ultimo_pm` y
    `equipo_planes.ultimo_valor_medidor` se mueven a la lectura registrada **en ese folio**; si el folio no trajo
    lectura, a la última válida del medidor (lo esperado cuando el técnico no pudo leer el marcador). Si no hay
    ninguna lectura, no se mueve nada: el plan sigue esperando la primera."""
    from models.medidores import EstadoLecturaMedidor, MedidorLectura
    from services import medidores_service

    if folio.plan_id is None or folio.equipo_id is None:
        return
    medidor = await medidores_service.medidor_del_plan(db, folio.plan_id, folio.equipo_id)
    if medidor is None:
        return
    lectura = (await db.execute(select(MedidorLectura).where(
        MedidorLectura.equipo_medidor_id == medidor.id, MedidorLectura.folio_id == folio.id,
        MedidorLectura.estado == EstadoLecturaMedidor.valida).order_by(MedidorLectura.timestamp.desc()).limit(1))).scalar_one_or_none()
    origen = "folio"
    if lectura is None:
        lectura = await medidores_service.ultima_valida(db, medidor.id)
        origen = "ultima_valida"
    if lectura is None:
        return
    valor = Decimal(lectura.valor_acumulado)
    medidor.valor_ultimo_pm = valor
    ep = (await db.execute(select(EquipoPlan).where(EquipoPlan.plan_id == folio.plan_id,
                                                    EquipoPlan.equipo_id == folio.equipo_id))).scalar_one_or_none()
    if ep is not None:
        ep.ultimo_valor_medidor = valor
    for pe in (await db.execute(select(PlanEjecucion).where(PlanEjecucion.folio_id == folio.id))).scalars():
        if pe.valor_medidor is None:
            pe.valor_medidor = valor
    await db.flush()
    log.info("Preventivo %s cerrado: último PM del medidor %s en %s (%s)", folio.numero_folio, medidor.id, valor, origen)


def validar_parametros(tipo: TipoTrigger, parametros: dict[str, Any], claves_validas: set[str],
                       eventos_validos: set[str]) -> dict[str, Any]:
    """Validación de los cuatro tipos nuevos. La llama `planes_service.validar_trigger`."""
    p = dict(parametros or {})
    if tipo in TRIGGERS_MEDIDOR:
        if not p.get("tipo_medidor_id"):
            raise ErrorAPI(422, "TRIGGER_INVALIDO", f"{tipo.value} requiere tipo_medidor_id")
        campo = "umbral" if tipo == TipoTrigger.medidor_umbral else "intervalo"
        try:
            valor = Decimal(str(p[campo]))
        except Exception:  # noqa: BLE001
            raise ErrorAPI(422, "TRIGGER_INVALIDO", f"{tipo.value} requiere {campo} numérico mayor que cero") from None
        if valor <= CERO:
            raise ErrorAPI(422, "TRIGGER_INVALIDO", f"{campo} debe ser mayor que cero")
        return {"tipo_medidor_id": str(p["tipo_medidor_id"]), campo: float(valor)}
    if tipo == TipoTrigger.evento:
        clave = p.get("evento")
        if clave not in eventos_validos:
            raise ErrorAPI(422, "EVENTO_INVALIDO",
                           f"El evento debe ser uno del catálogo: {', '.join(sorted(eventos_validos))}")
        salida: dict[str, Any] = {"evento": clave}
        if clave == EVENTO_FALLA_GRAVE:
            severidades = p.get("severidades") or ["alta", "critica"]
            if not isinstance(severidades, list) or not severidades:
                raise ErrorAPI(422, "TRIGGER_INVALIDO", "severidades debe ser una lista no vacía")
            salida["severidades"] = [str(s) for s in severidades]
        elif clave == EVENTO_FALLAS_REPETIDAS:
            cantidad, dias = p.get("cantidad"), p.get("dias")
            if not isinstance(cantidad, int) or not 2 <= cantidad <= 20:
                raise ErrorAPI(422, "TRIGGER_INVALIDO", "cantidad va de 2 a 20 fallas")
            if not isinstance(dias, int) or not 1 <= dias <= 365:
                raise ErrorAPI(422, "TRIGGER_INVALIDO", "dias va de 1 a 365")
            salida.update({"cantidad": cantidad, "dias": dias})
        elif clave == EVENTO_EQUIPO_INSTALADO:
            dias = p.get("dias_despues", 0)
            if not isinstance(dias, int) or not 0 <= dias <= 365:
                raise ErrorAPI(422, "TRIGGER_INVALIDO", "dias_despues va de 0 a 365")
            salida["dias_despues"] = dias
        elif clave == EVENTO_REEMPLAZO_COMPONENTE:
            categorias = p.get("categorias") or []
            if not isinstance(categorias, list):
                raise ErrorAPI(422, "TRIGGER_INVALIDO", "categorias debe ser una lista (vacía = cualquier refacción)")
            salida["categorias"] = [str(c) for c in categorias]
        elif clave == EVENTO_CAMBIO_MEDIDOR and p.get("tipo_medidor_id"):
            salida["tipo_medidor_id"] = str(p["tipo_medidor_id"])
        return salida
    # combinado: referencia a otros triggers del mismo plan por su clave estable.
    claves = [str(c) for c in (p.get("triggers_claves") or [])]
    if not claves:
        raise ErrorAPI(422, "TRIGGER_INVALIDO", "combinado requiere al menos dos triggers (triggers_ids o triggers_claves)")
    if len(claves) < 2:
        raise ErrorAPI(422, "TRIGGER_INVALIDO", "Un combinado necesita dos condiciones o más")
    faltantes = [c for c in claves if c not in claves_validas]
    if faltantes:
        raise ErrorAPI(422, "TRIGGER_INVALIDO", f"El combinado apunta a triggers que no están en el plan: {', '.join(faltantes)}")
    logica = str(p.get("logica") or "OR").upper()
    if logica not in ("OR", "AND"):
        raise ErrorAPI(422, "TRIGGER_INVALIDO", "logica debe ser OR (lo que ocurra primero) o AND (cuando se cumplan todas)")
    return {"triggers_claves": claves, "logica": logica}
