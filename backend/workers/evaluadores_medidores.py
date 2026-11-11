"""Evaluadores de las alertas de medidores (§6.9.6). F2-04.

- `MEDIDOR_PROXIMO_PM` — existía desde P01 esperando este bloque. Umbral literal: **10 % del intervalo** restante.
  Se mide contra el intervalo del propio trigger (el umbral completo, para `medidor_umbral`; el intervalo, para
  `medidor_intervalo`), así que «10 %» significa lo mismo en un plan de 500 h que en uno de 10,000 ciclos. Va al
  Despachador con la fecha estimada en que se alcanzará, calculada con el incremento promedio real.
- `MEDIDOR_SIN_LECTURA` — un medidor que no se estima y lleva más de X días sin lectura (default 30): los planes
  por uso de ese equipo están ciegos y nadie se enteraría.

`MEDIDOR_LECTURA_ANOMALA` no se evalúa aquí: la dispara el servicio en el momento en que la lectura entra, que es
el hecho que importa (igual que `CERTIFICACION_VENCIDA_HABILIDAD_RETIRADA` en F2-01).
"""
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.alertas import AlertaCatalogo
from models.catalogos import Equipo
from models.medidores import EquipoMedidor, MedidorEstimacion, MetodoActualizacionMedidor, TipoMedidor
from models.preventivos import TRIGGERS_MEDIDOR, EquipoPlan, EstadoPlan, PlanMantenimiento, PlanTrigger
from workers.evaluadores import _umbral_p06 as _umbral
from workers.evaluadores_seguimiento import _disparar_una_vez
from workers.tareas import registrar_evaluador

CERO = Decimal("0")


@registrar_evaluador("MEDIDOR_PROXIMO_PM")
async def medidor_proximo_pm(db: AsyncSession, alerta: AlertaCatalogo) -> int:
    """Planes por medidor a los que les falta menos del X % del intervalo (default 10 %)."""
    from services import triggers_service

    hoy = date.today()
    disparadas = 0
    asignaciones = (await db.execute(
        select(EquipoPlan, PlanMantenimiento).join(PlanMantenimiento, PlanMantenimiento.id == EquipoPlan.plan_id)
        .where(EquipoPlan.activo.is_(True), PlanMantenimiento.estado == EstadoPlan.activo))).all()
    for ep, plan in asignaciones:
        triggers = (await db.execute(select(PlanTrigger).where(PlanTrigger.plan_id == plan.id))).scalars().all()
        medidores = [t for t in triggers if t.tipo_trigger in TRIGGERS_MEDIDOR]
        if not medidores:
            continue
        equipo = await db.get(Equipo, ep.equipo_id)
        if equipo is None:
            continue
        pct = Decimal(str(await _umbral(db, alerta, ep.tenant_id)))
        for t in medidores:
            p = await triggers_service.proyeccion(db, plan, ep, equipo, t, hoy)
            if p["valor_objetivo"] is None or p["faltante"] is None:
                continue
            parametros = t.parametros_json or {}
            intervalo = Decimal(str(parametros.get("intervalo") or parametros.get("umbral") or 0))
            if intervalo <= CERO:
                continue
            faltante = Decimal(p["faltante"])
            if faltante <= CERO:
                continue   # ya se alcanzó: el folio lo genera el trigger, no hace falta avisar que «va a llegar»
            if faltante > (intervalo * pct / Decimal("100")):
                continue
            tipo_id = (t.parametros_json or {}).get("tipo_medidor_id")
            tipo = await db.get(TipoMedidor, tipo_id) if tipo_id else None
            disparadas += await _disparar_una_vez(
                db, alerta, tenant_id=ep.tenant_id, prestador_id=plan.prestador_id, entidad_tipo="equipo_plan",
                entidad_id=ep.id, datos={
                    "equipo_id": str(equipo.id), "equipo": equipo.nombre, "equipo_codigo": equipo.codigo,
                    "plan_id": str(plan.id), "plan": plan.nombre, "unidad": p["unidad"],
                    "valor_actual": str(p["valor_actual"]), "valor_objetivo": str(p["valor_objetivo"]),
                    "faltante": str(faltante), "porcentaje_umbral": str(pct),
                    "fecha_estimada": p["fecha_estimada"].isoformat() if p["fecha_estimada"] else None,
                    "medidor": tipo.nombre if tipo else "",
                    "etiqueta": (f"{plan.nombre}: faltan {faltante} {p['unidad']}"
                                 + (f", estimado para el {p['fecha_estimada'].isoformat()}" if p["fecha_estimada"] else ""))})
    return disparadas


@registrar_evaluador("MEDIDOR_SIN_LECTURA")
async def medidor_sin_lectura(db: AsyncSession, alerta: AlertaCatalogo) -> int:
    """Medidores que no se estiman y llevan más de X días sin lectura (default 30)."""
    from services import medidores_service

    ahora = datetime.now(UTC)
    estimaciones = {e.equipo_medidor_id for e in (await db.execute(select(MedidorEstimacion).where(
        MedidorEstimacion.activa.is_(True)))).scalars()}
    filas = (await db.execute(select(EquipoMedidor, TipoMedidor, Equipo)
                              .join(TipoMedidor, TipoMedidor.id == EquipoMedidor.tipo_medidor_id)
                              .join(Equipo, Equipo.id == EquipoMedidor.equipo_id)
                              .where(EquipoMedidor.activo.is_(True),
                                     EquipoMedidor.metodo_actualizacion != MetodoActualizacionMedidor.estimado))).all()
    disparadas = 0
    for m, tipo, equipo in filas:
        if m.id in estimaciones:
            continue
        dias_limite = int(await _umbral(db, alerta, m.tenant_id))
        referencia = m.fecha_ultima_lectura or m.created_at
        if referencia is None or referencia > ahora - timedelta(days=dias_limite):
            continue
        dias = (ahora - referencia).days
        # La alerta la lee el Despachador, y su panel solo muestra las de su prestador (§6.9.6).
        disparadas += await _disparar_una_vez(
            db, alerta, tenant_id=m.tenant_id,
            prestador_id=await medidores_service.prestador_responsable(db, m.tenant_id),
            entidad_tipo="equipo_medidor", entidad_id=m.id,
            datos={"equipo_id": str(equipo.id), "equipo": equipo.nombre, "equipo_codigo": equipo.codigo,
                   "medidor": tipo.nombre, "unidad": tipo.unidad, "dias": dias, "umbral_dias": dias_limite,
                   "ultima_lectura": m.fecha_ultima_lectura.isoformat() if m.fecha_ultima_lectura else None,
                   "etiqueta": f"{equipo.nombre}: {tipo.nombre} sin lectura desde hace {dias} días"})
    return disparadas
