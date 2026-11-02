"""Generación de los cuatro eventos de §6.6: OC aprobada, costo de folio validado, equipo nuevo instalado (P08) y póliza de
reposición de caja chica. En Fase 1 quedan `pendiente` y entran a la exportación universal por período."""
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.costos import ErpConfiguracion, ErpEventoPendiente, EstadoEventoERP, OperacionERP
from services import auditoria


async def configuracion(db: AsyncSession, prestador_id: UUID, crear: bool = False) -> ErpConfiguracion | None:
    c = (await db.execute(select(ErpConfiguracion).where(ErpConfiguracion.prestador_id == prestador_id))).scalar_one_or_none()
    if c is None and crear:
        c = ErpConfiguracion(prestador_id=prestador_id, columnas_excel_json=list(COLUMNAS_DEFECTO))
        db.add(c)
        await db.flush()
    return c


COLUMNAS_DEFECTO = ("fecha", "tipo", "referencia", "concepto", "centro_costos", "cuenta_contable", "subtotal", "iva", "total", "moneda")


async def registrar(db: AsyncSession, *, prestador_id: UUID, tenant_id: UUID | None, operacion: OperacionERP, entidad: str, entidad_id: UUID | None,
                    payload: dict[str, Any]) -> ErpEventoPendiente:
    """Idempotente por (operación, entidad_id): el mismo hecho no genera dos eventos."""
    if entidad_id is not None:
        previo = (await db.execute(select(ErpEventoPendiente).where(ErpEventoPendiente.operacion == operacion,
                                                                     ErpEventoPendiente.entidad_id == entidad_id))).scalars().first()
        if previo is not None:
            previo.payload_json = auditoria.a_json(payload)
            await db.flush()
            return previo
    e = ErpEventoPendiente(prestador_id=prestador_id, tenant_id=tenant_id, operacion=operacion, entidad=entidad, entidad_id=entidad_id,
                           payload_json=auditoria.a_json(payload), estado=EstadoEventoERP.pendiente)
    db.add(e)
    await db.flush()
    # Con adaptador configurado, el stub de Fase 2 lo deja en `omitido` dejando constancia del motivo.
    cfg = await configuracion(db, prestador_id)
    if cfg is not None and cfg.adaptador.value != "ninguno":
        from services.erp import base

        await base.procesar(db, e, cfg.adaptador)
    return e


async def generar_oc(db: AsyncSession, oc, partidas: list) -> ErpEventoPendiente:
    return await registrar(db, prestador_id=oc.prestador_id, tenant_id=oc.tenant_id, operacion=OperacionERP.generar_oc, entidad="orden_compra",
                           entidad_id=oc.id, payload={"numero": oc.numero, "proveedor": oc.proveedor, "total": oc.total, "moneda": oc.moneda,
                                                      "folio_id": oc.folio_id, "partidas": [{"articulo_id": p.articulo_id, "cantidad": p.cantidad,
                                                                                             "costo_unitario": p.costo_unitario} for p in partidas]})


async def registrar_gasto(db: AsyncSession, folio, costo) -> ErpEventoPendiente:
    return await registrar(db, prestador_id=folio.prestador_id, tenant_id=folio.tenant_id, operacion=OperacionERP.registrar_gasto, entidad="folio_costo",
                           entidad_id=costo.id, payload={"numero_folio": folio.numero_folio, "folio_id": folio.id, "tipo_folio": folio.tipo_folio.value,
                                                         "un_id": folio.un_id, "equipo_id": folio.equipo_id, "centro_costos": costo.centro_costos,
                                                         "costo_refacciones": costo.costo_refacciones, "costo_mano_obra": costo.costo_mano_obra,
                                                         "costo_otros": costo.costo_otros, "total": costo.costo_total, "moneda": costo.moneda,
                                                         "fecha_cierre": folio.fecha_cierre})


async def crear_activo_fijo(db: AsyncSession, folio, equipo) -> ErpEventoPendiente:
    return await registrar(db, prestador_id=folio.prestador_id, tenant_id=folio.tenant_id, operacion=OperacionERP.crear_activo_fijo, entidad="equipo",
                           entidad_id=equipo.id, payload={"codigo": equipo.codigo, "nombre": equipo.nombre, "marca": equipo.marca, "modelo": equipo.modelo,
                                                          "numero_serie": equipo.numero_serie, "un_id": equipo.un_id, "folio_id": folio.id,
                                                          "numero_folio": folio.numero_folio, "valor_reposicion": equipo.valor_reposicion,
                                                          "fecha_instalacion": equipo.fecha_instalacion})


async def poliza_caja_chica(db: AsyncSession, poliza, gastos: list) -> ErpEventoPendiente:
    return await registrar(db, prestador_id=poliza.prestador_id, tenant_id=None, operacion=OperacionERP.poliza_caja_chica, entidad="poliza_exportacion",
                           entidad_id=poliza.id, payload={"fecha": poliza.fecha, "total": poliza.total, "gastos": poliza.gastos,
                                                          "detalle": [{"gasto_id": g.id, "proveedor": g.proveedor, "rfc": g.rfc_proveedor,
                                                                       "uuid_cfdi": g.uuid_cfdi, "monto": g.monto, "iva": g.iva,
                                                                       "centro_costos": g.centro_costos, "cuenta_contable": g.cuenta_contable} for g in gastos]})
