"""Evaluadores de las alertas de inventario, órdenes de compra, caja chica, presupuestos y activos (P09)."""
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.activos import ActivoReemplazoAlerta, ActivoTCOSnapshot
from models.alertas import AlertaCatalogo
from models.catalogos import Equipo
from models.costos import Presupuesto
from models.inventario import (
    Articulo, EstadoGastoCajaChica, EstadoOrdenCompra, Existencia, FondoCajaChica, GastoCajaChica, OrdenCompra, UbicacionInventario,
)
from workers.evaluadores import _umbral_p06 as _umbral
from workers.evaluadores_seguimiento import _disparar_una_vez
from workers.tareas import registrar_evaluador

CERO = Decimal("0")


@registrar_evaluador("STOCK_MINIMO")
async def stock_minimo(db: AsyncSession, alerta: AlertaCatalogo) -> int:
    """Por ubicación y artículo: existencia igual o menor al mínimo (el del artículo si la existencia no lo define)."""
    n = 0
    filas = (await db.execute(select(Existencia, Articulo, UbicacionInventario).join(Articulo, Articulo.id == Existencia.articulo_id)
                              .join(UbicacionInventario, UbicacionInventario.id == Existencia.ubicacion_id)
                              .where(UbicacionInventario.activo.is_(True), Articulo.activo.is_(True)))).all()
    for e, a, u in filas:
        minimo = e.stock_minimo if e.stock_minimo is not None else a.stock_minimo_default
        if minimo <= CERO or e.cantidad > minimo:
            continue
        n += await _disparar_una_vez(db, alerta, tenant_id=None, prestador_id=a.prestador_id, entidad_tipo="existencia", entidad_id=e.id,
                                     datos={"articulo": a.codigo, "descripcion": a.descripcion, "ubicacion": u.nombre, "cantidad": str(e.cantidad),
                                            "minimo": str(minimo)})
    return n


@registrar_evaluador("STOCK_NEGATIVO")
async def stock_negativo(db: AsyncSession, alerta: AlertaCatalogo) -> int:
    n = 0
    filas = (await db.execute(select(Existencia, Articulo, UbicacionInventario).join(Articulo, Articulo.id == Existencia.articulo_id)
                              .join(UbicacionInventario, UbicacionInventario.id == Existencia.ubicacion_id)
                              .where(Existencia.cantidad < 0))).all()
    for e, a, u in filas:
        n += await _disparar_una_vez(db, alerta, tenant_id=None, prestador_id=a.prestador_id, entidad_tipo="existencia", entidad_id=e.id,
                                     datos={"articulo": a.codigo, "ubicacion": u.nombre, "cantidad": str(e.cantidad)})
    return n


async def _oc_por_dias(db: AsyncSession, alerta: AlertaCatalogo, estados: tuple[EstadoOrdenCompra, ...]) -> int:
    ahora = datetime.now(UTC)
    n = 0
    for oc in (await db.execute(select(OrdenCompra).where(OrdenCompra.estado.in_(estados)))).scalars():
        dias = int(await _umbral(db, alerta, oc.tenant_id))
        if oc.estado_desde > ahora - timedelta(days=dias):
            continue
        n += await _disparar_una_vez(db, alerta, tenant_id=oc.tenant_id, prestador_id=oc.prestador_id, entidad_tipo="orden_compra", entidad_id=oc.id,
                                     datos={"numero": oc.numero, "proveedor": oc.proveedor, "total": str(oc.total), "estado": oc.estado.value,
                                            "dias": (ahora - oc.estado_desde).days, "folio_id": str(oc.folio_id) if oc.folio_id else None})
    return n


@registrar_evaluador("OC_SIN_APROBAR")
async def oc_sin_aprobar(db: AsyncSession, alerta: AlertaCatalogo) -> int:
    return await _oc_por_dias(db, alerta, (EstadoOrdenCompra.borrador,))


@registrar_evaluador("OC_SIN_RECIBIR")
async def oc_sin_recibir(db: AsyncSession, alerta: AlertaCatalogo) -> int:
    return await _oc_por_dias(db, alerta, (EstadoOrdenCompra.aprobada, EstadoOrdenCompra.enviada_erp))


@registrar_evaluador("GASTO_CAJA_CHICA_SIN_APROBAR")
async def gasto_sin_aprobar(db: AsyncSession, alerta: AlertaCatalogo) -> int:
    ahora = datetime.now(UTC)
    n = 0
    for g in (await db.execute(select(GastoCajaChica).where(GastoCajaChica.estado == EstadoGastoCajaChica.capturado))).scalars():
        horas = int(await _umbral(db, alerta, g.tenant_id))
        if g.timestamp > ahora - timedelta(hours=horas):
            continue
        n += await _disparar_una_vez(db, alerta, tenant_id=g.tenant_id, prestador_id=g.prestador_id, entidad_tipo="gasto_caja_chica", entidad_id=g.id,
                                     datos={"proveedor": g.proveedor, "monto": str(g.monto), "horas": round((ahora - g.timestamp).total_seconds() / 3600, 1),
                                            "folio_id": str(g.folio_id) if g.folio_id else None})
    return n


@registrar_evaluador("FONDO_CAJA_CHICA_BAJO")
async def fondo_bajo(db: AsyncSession, alerta: AlertaCatalogo) -> int:
    n = 0
    for f in (await db.execute(select(FondoCajaChica).where(FondoCajaChica.activo.is_(True), FondoCajaChica.monto_inicial > 0))).scalars():
        umbral = Decimal(str(await _umbral(db, alerta, None)))
        umbral = f.umbral_alerta_pct if f.umbral_alerta_pct else umbral
        pct = f.saldo_actual / f.monto_inicial * 100
        if pct > umbral:
            continue
        n += await _disparar_una_vez(db, alerta, tenant_id=None, prestador_id=f.prestador_id, entidad_tipo="fondo_caja_chica", entidad_id=f.id,
                                     datos={"saldo": str(f.saldo_actual), "monto_inicial": str(f.monto_inicial), "porcentaje": str(pct.quantize(Decimal('0.01')))})
    return n


async def _presupuestos(db: AsyncSession, alerta: AlertaCatalogo, excedidos: bool) -> int:
    from services import presupuestos_service

    hoy = date.today()
    n = 0
    for p in (await db.execute(select(Presupuesto).where(Presupuesto.activo.is_(True), Presupuesto.periodo_inicio <= hoy,
                                                          Presupuesto.periodo_fin >= hoy, Presupuesto.monto > 0))).scalars():
        total = await presupuestos_service.consumido(db, p.id)
        pct = total / p.monto * 100
        umbrales = sorted(Decimal(str(u)) for u in (p.umbrales_alerta_json or [])) or [Decimal(str(await _umbral(db, alerta, p.tenant_id)))]
        alcanzados = [u for u in umbrales if pct >= u]
        if excedidos:
            if pct < 100:
                continue
        elif not alcanzados or max(alcanzados) >= 100:
            continue
        n += await _disparar_una_vez(db, alerta, tenant_id=p.tenant_id, prestador_id=None, entidad_tipo="presupuesto", entidad_id=p.id,
                                     datos={"nombre": p.nombre, "monto": str(p.monto), "consumido": str(total), "porcentaje": str(pct.quantize(Decimal('0.01'))),
                                            "umbral": str(max(alcanzados) if alcanzados else 100)})
    return n


@registrar_evaluador("PRESUPUESTO_UMBRAL_ALCANZADO")
async def presupuesto_umbral(db: AsyncSession, alerta: AlertaCatalogo) -> int:
    return await _presupuestos(db, alerta, excedidos=False)


@registrar_evaluador("PRESUPUESTO_EXCEDIDO")
async def presupuesto_excedido(db: AsyncSession, alerta: AlertaCatalogo) -> int:
    return await _presupuestos(db, alerta, excedidos=True)


@registrar_evaluador("ACTIVO_REEMPLAZO")
async def activo_reemplazo(db: AsyncSession, alerta: AlertaCatalogo) -> int:
    """Dispara por el último snapshot de TCO cuando supera el umbral del tenant y la alerta sigue sin decisión."""
    from services import activos_service

    n = 0
    pendientes = {a.equipo_id for a in (await db.execute(select(ActivoReemplazoAlerta).where(ActivoReemplazoAlerta.decision.is_(None)))).scalars()}
    ultimos: dict = {}
    for s in (await db.execute(select(ActivoTCOSnapshot).order_by(ActivoTCOSnapshot.periodo))).scalars():
        ultimos[s.equipo_id] = s
    for equipo_id, s in ultimos.items():
        if not s.valor_reposicion or s.valor_reposicion <= CERO:
            continue
        umbral = await activos_service.umbral_reemplazo(db, s.tenant_id)
        if s.porcentaje_vs_reposicion < umbral or equipo_id not in pendientes:
            continue
        e = await db.get(Equipo, equipo_id)
        n += await _disparar_una_vez(db, alerta, tenant_id=s.tenant_id, prestador_id=None, entidad_tipo="equipo", entidad_id=equipo_id,
                                     datos={"codigo": e.codigo if e else None, "tco": str(s.tco_total), "valor_reposicion": str(s.valor_reposicion),
                                            "porcentaje": str(s.porcentaje_vs_reposicion), "umbral": str(umbral)})
    return n
