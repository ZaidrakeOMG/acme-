"""Seguimiento de OC para instalación de activos (§6.10.7): vista de pendientes, registro de número de OC y estatus por folio,
historial del trámite y decisiones ante rechazo. P08."""
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from core.dependencias import DB, Actor, requiere_rol
from models.base import Rol
from schemas.comun import RESPUESTAS_ERROR
from schemas.trabajos_especiales import AutorizacionActivoDetalle, EstatusOCEntrada, PendienteOCSalida
from services import oc_activos_service as svc

router = APIRouter(prefix="/api/oc-activos", tags=["OC de activos"], responses=RESPUESTAS_ERROR)
TODOS = requiere_rol(*Rol)


async def _detalle(db, actor, folio, aut) -> dict[str, Any]:
    from services import folios_captura_service as captura

    d = await svc.detalle_folio(db, folio)
    return AutorizacionActivoDetalle(**{**d, "folio": (await captura.resumen(db, [folio]))[0]}).model_dump()


@router.get("/pendientes", response_model=list[PendienteOCSalida], summary="Folios de activos pendientes de autorización (Admin UN / Admin empresa)")
async def pendientes(db: DB, actor: Actor = Depends(TODOS), tenant_id: UUID | None = None, incluir_resueltos: bool = False):
    return [PendienteOCSalida(**p) for p in await svc.pendientes(db, actor, tenant_id, incluir_resueltos)]


@router.get("/{folio_id}", response_model=AutorizacionActivoDetalle, summary="Trámite de OC del folio con su historial y el equipo dado de alta")
async def detalle(folio_id: UUID, db: DB, actor: Actor = Depends(TODOS)):
    folio, aut = await svc.obtener(db, actor, folio_id)
    return await _detalle(db, actor, folio, aut)


@router.post("/{folio_id}/estatus", response_model=AutorizacionActivoDetalle, summary="Admin empresa registra el estatus del trámite (número de OC, fecha, rechazo con decisión)")
async def estatus(folio_id: UUID, datos: EstatusOCEntrada, request: Request, db: DB, actor: Actor = Depends(TODOS)):
    folio, aut = await svc.obtener(db, actor, folio_id)
    await svc.cambiar_estatus(db, actor, folio, aut, datos.estatus, numero_oc_provisional=datos.numero_oc_provisional, numero_oc_definitivo=datos.numero_oc_definitivo,
                              fecha_autorizacion_erp=datos.fecha_autorizacion_erp, notas=datos.notas, decision_rechazo=datos.decision_rechazo,
                              periodo_destino=datos.periodo_presupuestal_destino, request=request)
    await db.commit()
    return await _detalle(db, actor, folio, aut)
