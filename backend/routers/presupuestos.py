"""Presupuestos y control de gasto (§4.1, §6.8.5): CRUD por UN o grupo, vista consolidada Tenant → Grupo → UN y detalle de
folios cargados. Incluye las tarifas de mano de obra que alimentan el costo del folio. P09."""
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from core.dependencias import DB, Actor, requiere_rol
from models.base import Rol
from schemas.comun import RESPUESTAS_ERROR
from schemas.costos import (
    ConsolidadoSalida, ConsumoSalida, PresupuestoCambios, PresupuestoEntrada, PresupuestoSalida, TarifaEntrada, TarifaSalida,
)
from services import costos_service, presupuestos_service as svc

router = APIRouter(prefix="/api/presupuestos", tags=["Presupuestos"], responses=RESPUESTAS_ERROR)
TODOS = requiere_rol(*Rol)


@router.get("", response_model=list[PresupuestoSalida], summary="Presupuestos por UN o grupo con consumido, comprometido y disponible")
async def listar(db: DB, actor: Actor = Depends(TODOS), tenant_id: UUID | None = None, un_id: UUID | None = None, grupo_id: UUID | None = None,
                 vigentes: bool = False):
    return await svc.listar(db, actor, tenant_id=tenant_id, un_id=un_id, grupo_id=grupo_id, vigentes=vigentes)


@router.get("/consolidado", response_model=ConsolidadoSalida, summary="Tablero Tenant → Grupo → UN con semáforo por umbral (§6.8.5)")
async def consolidado(db: DB, actor: Actor = Depends(TODOS), tenant_id: UUID | None = None, vigentes: bool = True):
    return await svc.consolidado(db, actor, tenant_id=tenant_id, vigentes=vigentes)


@router.post("", response_model=PresupuestoSalida, status_code=201, summary="Alta de presupuesto (Admin empresa)")
async def crear(datos: PresupuestoEntrada, request: Request, db: DB, actor: Actor = Depends(TODOS)):
    p = await svc.crear(db, actor, datos.model_dump(exclude_none=True), request)
    await db.commit()
    return await svc.resumen(db, p)


@router.get("/tarifas", response_model=list[TarifaSalida], summary="Tarifas de mano de obra vigentes (§6.8.6)")
async def tarifas(db: DB, actor: Actor = Depends(TODOS)):
    return await costos_service.listar_tarifas(db, actor)


@router.post("/tarifas", response_model=TarifaSalida, status_code=201, summary="Alta de tarifa de mano de obra (Admin prestador)")
async def crear_tarifa(datos: TarifaEntrada, request: Request, db: DB, actor: Actor = Depends(TODOS)):
    t = await costos_service.guardar_tarifa(db, actor, datos.model_dump(exclude_none=True), request)
    await db.commit()
    return t


@router.get("/{presupuesto_id}", response_model=PresupuestoSalida, summary="Detalle del presupuesto")
async def detalle(presupuesto_id: UUID, db: DB, actor: Actor = Depends(TODOS)):
    return await svc.resumen(db, await svc.obtener(db, actor, presupuesto_id))


@router.put("/{presupuesto_id}", response_model=PresupuestoSalida, summary="Editar presupuesto (Admin empresa)")
async def editar(presupuesto_id: UUID, datos: PresupuestoCambios, request: Request, db: DB, actor: Actor = Depends(TODOS)):
    p = await svc.obtener(db, actor, presupuesto_id)
    await svc.actualizar(db, actor, p, datos.model_dump(exclude_unset=True), request)
    await db.commit()
    return await svc.resumen(db, p)


@router.get("/{presupuesto_id}/consumos", response_model=list[ConsumoSalida], summary="Folios cargados al presupuesto")
async def consumos(presupuesto_id: UUID, db: DB, actor: Actor = Depends(TODOS)):
    return await svc.consumos(db, actor, await svc.obtener(db, actor, presupuesto_id))
