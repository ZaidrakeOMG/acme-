"""Evaluadores de las implicaciones de criticidad (§6.9.3, §6.9.6). F2-05.

§6.9.3 no dice «avisa»: dice que un activo A **tiene** plan obligatorio, respuesta máxima de 4 h, técnico
especialista y refacciones en inventario. ACMA las aplica como **alertas** por defecto y como **restricción** solo
si el cliente lo decide (`criticidad_configuracion.implicaciones_activas_json`), porque un cálculo nuevo no debería
bloquear la operación el primer día. La restricción de la asignación la aplica P06 al asignar; las cuatro de aquí
son las que avisan sin que nadie pregunte.

`RESPUESTA_CRITICIDAD_EN_RIESGO` **no toca el SLA ni la penalización** de P10: es un aviso paralelo, porque el
contrato puede prometer 24 h en un equipo que por su criticidad debería atenderse en 4.
"""
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.alertas import AlertaCatalogo
from models.catalogos import Equipo
from models.criticidad import ActivoCriticidad, ActivoModoFalla, ActivoRiesgoMitigacion, EstadoMitigacion
from models.folios import EstadoFolio, Folio, TipoFolio
from models.inventario import Articulo, Existencia
from models.preventivos import EquipoPlan, EstadoPlan, PlanMantenimiento, PlanMaterial
from models.unidades import UnidadNegocio
from workers.evaluadores import _umbral_p06 as _umbral
from workers.evaluadores_seguimiento import _disparar_una_vez
from workers.tareas import registrar_evaluador

HORAS_POR_NIVEL = {"A": 4, "B": 8}
ESTADOS_ABIERTOS_CORRECTIVO = (EstadoFolio.capturado, EstadoFolio.en_revision, EstadoFolio.pendiente_informacion,
                               EstadoFolio.autorizado, EstadoFolio.asignado, EstadoFolio.reasignado,
                               EstadoFolio.en_camino, EstadoFolio.en_ejecucion, EstadoFolio.pendiente_refaccion)


async def _implicacion_activa(db: AsyncSession, tenant_id, clave: str, campo: str = "alerta") -> bool:
    from services import criticidad_service

    cfg = await criticidad_service.configuracion(db, tenant_id)
    return bool(((cfg.implicaciones_activas_json or {}).get(clave) or {}).get(campo, False))


async def _prestador_de(db: AsyncSession, tenant_id):
    from services import medidores_service

    return await medidores_service.prestador_responsable(db, tenant_id)


@registrar_evaluador("CRITICIDAD_REVISION_PENDIENTE")
async def criticidad_revision_pendiente(db: AsyncSession, alerta: AlertaCatalogo) -> int:
    """ISO 55000 pide revisar la clasificación periódicamente: `meses_revision` por cliente marca la fecha y esto
    avisa cuando se pasó."""
    hoy = date.today()
    filas = (await db.execute(select(ActivoCriticidad, Equipo).join(Equipo, Equipo.id == ActivoCriticidad.equipo_id)
                              .where(ActivoCriticidad.proxima_revision.is_not(None)))).all()
    disparadas = 0
    for fila, equipo in filas:
        dias_gracia = int(await _umbral(db, alerta, fila.tenant_id))
        if fila.proxima_revision > hoy - timedelta(days=dias_gracia):
            continue
        vencida = (hoy - fila.proxima_revision).days
        disparadas += await _disparar_una_vez(
            db, alerta, tenant_id=fila.tenant_id, prestador_id=None, entidad_tipo="activo_criticidad",
            entidad_id=fila.id,
            datos={"equipo_id": str(equipo.id), "equipo": equipo.nombre, "equipo_codigo": equipo.codigo,
                   "nivel": fila.nivel, "proxima_revision": fila.proxima_revision.isoformat(), "dias": vencida,
                   "etiqueta": f"{equipo.codigo}: su criticidad {fila.nivel} debía revisarse hace {vencida} día(s)"})
    return disparadas


@registrar_evaluador("ACTIVO_CRITICO_SIN_PLAN")
async def activo_critico_sin_plan(db: AsyncSession, alerta: AlertaCatalogo) -> int:
    """§6.9.3 nivel A: «PM obligatorio con plan definido»."""
    filas = (await db.execute(select(ActivoCriticidad, Equipo).join(Equipo, Equipo.id == ActivoCriticidad.equipo_id)
                              .where(ActivoCriticidad.nivel == "A"))).all()
    if not filas:
        return 0
    con_plan = set((await db.execute(
        select(EquipoPlan.equipo_id).join(PlanMantenimiento, PlanMantenimiento.id == EquipoPlan.plan_id)
        .where(EquipoPlan.activo.is_(True), PlanMantenimiento.estado == EstadoPlan.activo))).scalars())
    disparadas = 0
    for fila, equipo in filas:
        if equipo.id in con_plan:
            continue
        if not await _implicacion_activa(db, fila.tenant_id, "pm_obligatorio"):
            continue
        disparadas += await _disparar_una_vez(
            db, alerta, tenant_id=fila.tenant_id, prestador_id=await _prestador_de(db, fila.tenant_id),
            entidad_tipo="equipo", entidad_id=equipo.id,
            datos={"equipo_id": str(equipo.id), "equipo": equipo.nombre, "equipo_codigo": equipo.codigo,
                   "nivel": "A", "indice": str(fila.indice_criticidad),
                   "etiqueta": f"{equipo.codigo} es activo crítico (A) y no tiene plan de mantenimiento activo"})
    return disparadas


@registrar_evaluador("RESPUESTA_CRITICIDAD_EN_RIESGO")
async def respuesta_criticidad_en_riesgo(db: AsyncSession, alerta: AlertaCatalogo) -> int:
    """§6.9.3: respuesta máxima de 4 h en activos A y 8 h en B, aunque el SLA del contrato sea más largo. El umbral
    de la alerta es el porcentaje consumido de ese tiempo (default 80 %)."""
    ahora = datetime.now(UTC)
    filas = (await db.execute(
        select(Folio, ActivoCriticidad, Equipo)
        .join(ActivoCriticidad, ActivoCriticidad.equipo_id == Folio.equipo_id)
        .join(Equipo, Equipo.id == Folio.equipo_id)
        .where(Folio.tipo_folio == TipoFolio.correctivo, Folio.estado.in_(ESTADOS_ABIERTOS_CORRECTIVO),
               Folio.fecha_inicio_atencion.is_(None), ActivoCriticidad.nivel.in_(("A", "B"))))).all()
    disparadas = 0
    for folio, fila, equipo in filas:
        horas_limite = HORAS_POR_NIVEL.get(fila.nivel)
        if horas_limite is None:
            continue
        if not await _implicacion_activa(db, fila.tenant_id, "respuesta_maxima"):
            continue
        pct = Decimal(str(await _umbral(db, alerta, fila.tenant_id)))
        transcurridas = Decimal(str((ahora - folio.capturado_at).total_seconds() / 3600))
        if transcurridas < Decimal(horas_limite) * pct / Decimal("100"):
            continue
        disparadas += await _disparar_una_vez(
            db, alerta, tenant_id=folio.tenant_id, prestador_id=folio.prestador_id, entidad_tipo="folio",
            entidad_id=folio.id,
            datos={"folio_id": str(folio.id), "numero_folio": folio.numero_folio, "equipo_codigo": equipo.codigo,
                   "equipo": equipo.nombre, "nivel": fila.nivel, "horas_limite": horas_limite,
                   "horas_transcurridas": str(transcurridas.quantize(Decimal("0.1"))),
                   "etiqueta": f"{folio.numero_folio} lleva {transcurridas.quantize(Decimal('0.1'))} h sin atender y "
                               f"su activo {fila.nivel} exige respuesta en {horas_limite} h"})
    return disparadas


@registrar_evaluador("REFACCION_CRITICA_SIN_STOCK")
async def refaccion_critica_sin_stock(db: AsyncSession, alerta: AlertaCatalogo) -> int:
    """§6.9.3 nivel A: «refacciones siempre en inventario». Se miran los materiales de los planes de los activos A
    contra sus existencias en los almacenes del prestador."""
    criticos = (await db.execute(select(ActivoCriticidad.equipo_id, ActivoCriticidad.tenant_id)
                                 .where(ActivoCriticidad.nivel == "A"))).all()
    if not criticos:
        return 0
    tenant_por_equipo = {e: t for e, t in criticos}
    planes = (await db.execute(
        select(EquipoPlan.equipo_id, PlanMaterial.articulo_id, PlanMaterial.descripcion, PlanMantenimiento.nombre)
        .join(PlanMantenimiento, PlanMantenimiento.id == EquipoPlan.plan_id)
        .join(PlanMaterial, PlanMaterial.plan_id == PlanMantenimiento.id)
        .where(EquipoPlan.equipo_id.in_(list(tenant_por_equipo)), EquipoPlan.activo.is_(True),
               PlanMantenimiento.estado == EstadoPlan.activo, PlanMaterial.articulo_id.is_not(None)))).all()
    disparadas = 0
    vistos: set = set()
    for equipo_id, articulo_id, descripcion, plan in planes:
        if (equipo_id, articulo_id) in vistos:
            continue
        vistos.add((equipo_id, articulo_id))
        tenant_id = tenant_por_equipo[equipo_id]
        if not await _implicacion_activa(db, tenant_id, "refaccion_en_inventario"):
            continue
        articulo = await db.get(Articulo, articulo_id)
        if articulo is None or not articulo.activo:
            continue
        total = Decimal(str((await db.execute(select(func.coalesce(func.sum(Existencia.cantidad), 0)).where(
            Existencia.articulo_id == articulo_id))).scalar() or 0))
        minimo = Decimal(str((await db.execute(select(func.coalesce(func.max(Existencia.stock_minimo), 0)).where(
            Existencia.articulo_id == articulo_id))).scalar() or 0)) or Decimal(str(articulo.stock_minimo_default or 0))
        if minimo <= 0 or total > minimo:
            continue
        equipo = await db.get(Equipo, equipo_id)
        disparadas += await _disparar_una_vez(
            db, alerta, tenant_id=tenant_id, prestador_id=articulo.prestador_id, entidad_tipo="articulo",
            entidad_id=articulo_id,
            datos={"articulo_id": str(articulo_id), "articulo": articulo.descripcion, "codigo": articulo.codigo,
                   "existencia": str(total), "stock_minimo": str(minimo), "plan": plan,
                   "equipo_id": str(equipo_id), "equipo_codigo": equipo.codigo if equipo else "",
                   "etiqueta": f"{articulo.codigo} ({descripcion}) está en {total} con mínimo {minimo} y es "
                               f"refacción de un plan de activos críticos"})
    return disparadas


@registrar_evaluador("MITIGACION_VENCIDA")
async def mitigacion_vencida(db: AsyncSession, alerta: AlertaCatalogo) -> int:
    """Una acción de mitigación con fecha compromiso pasada y sin implementar es riesgo que sigue abierto."""
    hoy = date.today()
    filas = (await db.execute(
        select(ActivoRiesgoMitigacion, ActivoModoFalla, Equipo)
        .join(ActivoModoFalla, ActivoModoFalla.id == ActivoRiesgoMitigacion.modo_falla_id)
        .outerjoin(Equipo, Equipo.id == ActivoModoFalla.equipo_id)
        .where(ActivoRiesgoMitigacion.estado.in_((EstadoMitigacion.propuesta, EstadoMitigacion.en_proceso)),
               ActivoRiesgoMitigacion.fecha_compromiso.is_not(None)))).all()
    disparadas = 0
    for m, modo, equipo in filas:
        dias_gracia = int(await _umbral(db, alerta, m.tenant_id))
        if m.fecha_compromiso > hoy - timedelta(days=dias_gracia):
            continue
        vencida = (hoy - m.fecha_compromiso).days
        disparadas += await _disparar_una_vez(
            db, alerta, tenant_id=m.tenant_id, prestador_id=await _prestador_de(db, m.tenant_id),
            entidad_tipo="activo_riesgo_mitigacion", entidad_id=m.id,
            datos={"mitigacion_id": str(m.id), "accion": m.accion_mitigacion[:200],
                   "modo_falla": modo.descripcion_falla, "nivel_riesgo": modo.nivel_riesgo,
                   "equipo_codigo": equipo.codigo if equipo else "", "dias": vencida,
                   "fecha_compromiso": m.fecha_compromiso.isoformat(),
                   "etiqueta": f"«{m.accion_mitigacion[:80]}» venció hace {vencida} día(s) sin implementarse"})
    return disparadas


async def unidades_del_tenant(db: AsyncSession, tenant_id) -> list:
    """Utilidad para los reportes: las UNs del cliente (se usa al agrupar por unidad)."""
    return list((await db.execute(select(UnidadNegocio).where(UnidadNegocio.tenant_id == tenant_id)
                                  .order_by(UnidadNegocio.codigo))).scalars())
