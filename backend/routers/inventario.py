"""Inventario (§6.4): catálogo de artículos, almacenes y vehículos, existencias, movimientos y órdenes de compra. P09."""
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from core.dependencias import DB, Actor, requiere_rol
from models.base import Rol
from models.inventario import EstadoOrdenCompra, TipoUbicacionInventario
from schemas.comun import RESPUESTAS_ERROR
from schemas.inventario import (
    AjusteEntrada, ArticuloCambios, ArticuloEntrada, ArticuloSalida, EntradaInventario, ExistenciaSalida, MovimientoSalida, OrdenCompraEntrada,
    OrdenCompraSalida, PartidaOCSalida, RazonEntrada, RecibirOCEntrada, TraspasoEntrada, UbicacionEntrada, UbicacionSalida,
)
from services import inventario_service as svc

router = APIRouter(prefix="/api/inventario", tags=["Inventario"], responses=RESPUESTAS_ERROR)
TODOS = requiere_rol(*Rol)


# ----------------------------------------------------------------- artículos

@router.get("/articulos", response_model=list[ArticuloSalida], summary="Catálogo de artículos del prestador")
async def articulos(db: DB, actor: Actor = Depends(TODOS), q: str | None = None, categoria: str | None = None, activo: bool | None = None):
    return await svc.listar_articulos(db, actor, q=q, categoria=categoria, activo=activo)


@router.post("/articulos", response_model=ArticuloSalida, status_code=201, summary="Alta de artículo (Admin prestador)")
async def crear_articulo(datos: ArticuloEntrada, request: Request, db: DB, actor: Actor = Depends(TODOS)):
    a = await svc.crear_articulo(db, actor, datos.model_dump(exclude_none=True), request)
    await db.commit()
    return a


@router.put("/articulos/{articulo_id}", response_model=ArticuloSalida, summary="Editar artículo")
async def editar_articulo(articulo_id: UUID, datos: ArticuloCambios, request: Request, db: DB, actor: Actor = Depends(TODOS)):
    a = await svc.obtener_articulo(db, actor, articulo_id)
    await svc.actualizar_articulo(db, actor, a, datos.model_dump(exclude_unset=True), request)
    await db.commit()
    return a


# --------------------------------------------------------------- ubicaciones

@router.get("/ubicaciones", response_model=list[UbicacionSalida], summary="Almacenes y vehículos (el técnico ve solo el suyo)")
async def ubicaciones(db: DB, actor: Actor = Depends(TODOS), tipo: TipoUbicacionInventario | None = None):
    return await svc.listar_ubicaciones(db, actor, tipo=tipo)


@router.post("/ubicaciones", response_model=UbicacionSalida, status_code=201, summary="Alta de almacén o vehículo (Admin prestador)")
async def crear_ubicacion(datos: UbicacionEntrada, request: Request, db: DB, actor: Actor = Depends(TODOS)):
    u = await svc.crear_ubicacion(db, actor, datos.model_dump(exclude_none=True), request)
    await db.commit()
    return u


# --------------------------------------------------------------- existencias

@router.get("/existencias", response_model=list[ExistenciaSalida], summary="Existencias por almacén y vehículo con indicador de stock mínimo")
async def existencias(db: DB, actor: Actor = Depends(TODOS), ubicacion_id: UUID | None = None, articulo_id: UUID | None = None,
                      solo_bajo_minimo: bool = False):
    return await svc.listar_existencias(db, actor, ubicacion_id=ubicacion_id, articulo_id=articulo_id, solo_bajo_minimo=solo_bajo_minimo)


@router.get("/movimientos", response_model=list[MovimientoSalida], summary="Movimientos de inventario (append-only)")
async def movimientos(db: DB, actor: Actor = Depends(TODOS), articulo_id: UUID | None = None, ubicacion_id: UUID | None = None,
                      folio_id: UUID | None = None, limite: int = 200):
    return await svc.listar_movimientos(db, actor, articulo_id=articulo_id, ubicacion_id=ubicacion_id, folio_id=folio_id, limite=limite)


@router.post("/movimientos/entrada", response_model=MovimientoSalida, status_code=201, summary="Entrada a almacén (manual; la masiva va por el importador CSV)")
async def entrada(datos: EntradaInventario, request: Request, db: DB, actor: Actor = Depends(TODOS)):
    m = await svc.entrada(db, actor, articulo_id=datos.articulo_id, ubicacion_id=datos.ubicacion_id, cantidad=datos.cantidad,
                          costo_unitario=datos.costo_unitario, referencia=datos.referencia, razon=datos.razon, request=request)
    await db.commit()
    return (await svc.listar_movimientos(db, actor, articulo_id=datos.articulo_id, limite=1))[0]


@router.post("/movimientos/traspaso", response_model=MovimientoSalida, status_code=201, summary="Traspaso almacén → vehículo (carga de la unidad)")
async def traspaso(datos: TraspasoEntrada, request: Request, db: DB, actor: Actor = Depends(TODOS)):
    await svc.traspaso(db, actor, articulo_id=datos.articulo_id, origen_id=datos.origen_id, destino_id=datos.destino_id, cantidad=datos.cantidad,
                       razon=datos.razon, request=request)
    await db.commit()
    return (await svc.listar_movimientos(db, actor, articulo_id=datos.articulo_id, limite=1))[0]


@router.post("/movimientos/ajuste", response_model=MovimientoSalida, status_code=201, summary="Ajuste con razón obligatoria (Admin prestador)")
async def ajuste(datos: AjusteEntrada, request: Request, db: DB, actor: Actor = Depends(TODOS)):
    await svc.ajuste(db, actor, articulo_id=datos.articulo_id, ubicacion_id=datos.ubicacion_id, cantidad=datos.cantidad, razon=datos.razon, request=request)
    await db.commit()
    return (await svc.listar_movimientos(db, actor, articulo_id=datos.articulo_id, limite=1))[0]


# ---------------------------------------------------------- órdenes de compra

async def _oc_salida(db, oc) -> dict[str, Any]:
    from models.folios import Folio
    from models.inventario import Articulo
    from services import auditoria

    partidas = []
    for p in await svc.partidas_de(db, oc.id):
        a = await db.get(Articulo, p.articulo_id)
        partidas.append(PartidaOCSalida(id=p.id, articulo_id=p.articulo_id, codigo=a.codigo if a else None, descripcion=a.descripcion if a else None,
                                        cantidad=p.cantidad, costo_unitario=p.costo_unitario, recibido=p.recibido))
    folio = await db.get(Folio, oc.folio_id) if oc.folio_id else None
    return {**auditoria.instantanea(oc), "id": oc.id, "prestador_id": oc.prestador_id, "tenant_id": oc.tenant_id, "folio_id": oc.folio_id,
            "numero_folio": folio.numero_folio if folio else None, "ubicacion_destino_id": oc.ubicacion_destino_id, "aprobada_por": oc.aprobada_por,
            "created_by": oc.created_by, "created_at": oc.created_at, "updated_at": oc.updated_at, "estado_desde": oc.estado_desde,
            "aprobada_at": oc.aprobada_at, "recibida_at": oc.recibida_at, "partidas": partidas}


@router.get("/ordenes-compra", response_model=list[OrdenCompraSalida], summary="Órdenes de compra (§6.4 Tipo B)")
async def ordenes(db: DB, actor: Actor = Depends(TODOS), estado: EstadoOrdenCompra | None = None, folio_id: UUID | None = None):
    return [OrdenCompraSalida(**await _oc_salida(db, oc)) for oc in await svc.listar_ocs(db, actor, estado=estado, folio_id=folio_id)]


@router.post("/ordenes-compra", response_model=OrdenCompraSalida, status_code=201, summary="Crear OC desde el folio en pendiente_refaccion")
async def crear_oc(datos: OrdenCompraEntrada, request: Request, db: DB, actor: Actor = Depends(TODOS)):
    oc = await svc.crear_oc(db, actor, folio_id=datos.folio_id, proveedor=datos.proveedor, notas=datos.notas,
                            ubicacion_destino_id=datos.ubicacion_destino_id,
                            partidas=[p.model_dump(exclude_none=True) for p in datos.partidas], request=request)
    await db.commit()
    return OrdenCompraSalida(**await _oc_salida(db, oc))


@router.get("/ordenes-compra/{oc_id}", response_model=OrdenCompraSalida, summary="Detalle de la orden de compra con sus partidas")
async def detalle_oc(oc_id: UUID, db: DB, actor: Actor = Depends(TODOS)):
    return OrdenCompraSalida(**await _oc_salida(db, await svc.obtener_oc(db, actor, oc_id)))


@router.post("/ordenes-compra/{oc_id}/aprobar", response_model=OrdenCompraSalida, summary="Aprobar (Admin prestador): genera el evento ERP generar_oc")
async def aprobar_oc(oc_id: UUID, request: Request, db: DB, actor: Actor = Depends(TODOS)):
    oc = await svc.obtener_oc(db, actor, oc_id)
    await svc.aprobar_oc(db, actor, oc, request)
    await db.commit()
    return OrdenCompraSalida(**await _oc_salida(db, oc))


@router.post("/ordenes-compra/{oc_id}/recibir", response_model=OrdenCompraSalida, summary="Recibir: entra al almacén y el folio puede reanudarse")
async def recibir_oc(oc_id: UUID, datos: RecibirOCEntrada, request: Request, db: DB, actor: Actor = Depends(TODOS)):
    oc = await svc.obtener_oc(db, actor, oc_id)
    await svc.recibir_oc(db, actor, oc, {k: Decimal(str(v)) for k, v in (datos.recibidas or {}).items()} or None, request)
    await db.commit()
    return OrdenCompraSalida(**await _oc_salida(db, oc))


@router.post("/ordenes-compra/{oc_id}/cancelar", response_model=OrdenCompraSalida, summary="Cancelar con razón")
async def cancelar_oc(oc_id: UUID, datos: RazonEntrada, request: Request, db: DB, actor: Actor = Depends(TODOS)):
    oc = await svc.obtener_oc(db, actor, oc_id)
    await svc.cancelar_oc(db, actor, oc, datos.razon, request)
    await db.commit()
    return OrdenCompraSalida(**await _oc_salida(db, oc))
