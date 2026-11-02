"""Ficha de activos, depreciación, TCO y análisis reemplazar vs. reparar (§6.9.4). P09."""
from datetime import date
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from core.dependencias import DB, Actor, requiere_rol
from core.errors import no_encontrado, prohibido
from models.activos import ActivoReemplazoAlerta
from models.base import Rol
from schemas.activos import (
    ActivoEntrada, ActivoResumen, AlertaReemplazoSalida, DecisionEntrada, DecisionResultado, DepreciacionEntrada, FichaActivo, UmbralEntrada,
)
from schemas.comun import RESPUESTAS_ERROR
from services import activos_service as svc
from services import auditoria

router = APIRouter(prefix="/api/activos", tags=["Equipos y activos"], responses=RESPUESTAS_ERROR)
TODOS = requiere_rol(*Rol)


@router.get("", response_model=list[ActivoResumen], summary="Listado de activos con TCO y alerta de reemplazo")
async def listar(db: DB, actor: Actor = Depends(TODOS), tenant_id: UUID | None = None, un_id: UUID | None = None, con_alerta: bool = False):
    return await svc.listado(db, actor, tenant_id=tenant_id, un_id=un_id, con_alerta=con_alerta)


@router.get("/alertas-reemplazo", response_model=list[AlertaReemplazoSalida], summary="Alertas de reemplazo recomendado")
async def alertas(db: DB, actor: Actor = Depends(TODOS), pendientes: bool = True):
    return await svc.alertas_reemplazo(db, actor, pendientes=pendientes)


@router.put("/umbral-reemplazo", summary="Umbral de TCO contra valor de reposición que dispara la recomendación (Admin empresa)")
async def umbral(datos: UmbralEntrada, request: Request, db: DB, actor: Actor = Depends(TODOS), tenant_id: UUID | None = None) -> dict:
    t = tenant_id if (tenant_id and actor.es_superadmin) else actor.tenant_id
    if t is None:
        raise prohibido("Indica el cliente del umbral")
    await svc.guardar_umbral(db, actor, t, datos.umbral_reemplazo_pct, request)
    await db.commit()
    return {"umbral_reemplazo_pct": float(datos.umbral_reemplazo_pct)}


@router.get("/{equipo_id}", response_model=FichaActivo, summary="Ficha del equipo: historial, costos, depreciación y TCO (§6.9.4)")
async def ficha(equipo_id: UUID, db: DB, actor: Actor = Depends(TODOS)):
    return await svc.ficha(db, actor, await svc.obtener_equipo(db, actor, equipo_id))


@router.put("/{equipo_id}/datos-economicos", response_model=FichaActivo, summary="Costo de adquisición, valor de reposición y costo/hora de inactividad")
async def datos_economicos(equipo_id: UUID, datos: ActivoEntrada, request: Request, db: DB, actor: Actor = Depends(TODOS)):
    equipo = await svc.obtener_equipo(db, actor, equipo_id)
    if not actor.es_superadmin and actor.rol not in svc.CONFIGURAN:
        raise prohibido("Solo el Admin empresa captura los datos económicos del activo")
    antes = auditoria.instantanea(equipo)
    for k, v in datos.model_dump(exclude_unset=True, exclude_none=True).items():
        setattr(equipo, k, v)
    await db.flush()
    await auditoria.registrar_actor(db, actor, "activos.datos_economicos", request, tenant_id=equipo.tenant_id, recurso_tipo="equipo", recurso_id=equipo.id,
                                    antes=antes, despues=auditoria.instantanea(equipo))
    await db.commit()
    return await svc.ficha(db, actor, equipo)


@router.put("/{equipo_id}/depreciacion", response_model=FichaActivo, summary="Método de depreciación (línea recta, doble saldo, unidades o manual)")
async def depreciacion(equipo_id: UUID, datos: DepreciacionEntrada, request: Request, db: DB, actor: Actor = Depends(TODOS)):
    equipo = await svc.obtener_equipo(db, actor, equipo_id)
    await svc.guardar_depreciacion(db, actor, equipo, datos.model_dump(exclude_unset=True, exclude_none=True), request)
    await db.commit()
    return await svc.ficha(db, actor, equipo)


@router.post("/{equipo_id}/calcular", response_model=FichaActivo, summary="Recalcular depreciación y TCO del período (también corre en la tarea mensual)")
async def calcular(equipo_id: UUID, db: DB, actor: Actor = Depends(TODOS), hasta: date | None = None):
    equipo = await svc.obtener_equipo(db, actor, equipo_id)
    if not actor.es_superadmin and actor.rol not in svc.CONFIGURAN:
        raise prohibido("Solo el Admin empresa recalcula el TCO de su activo (la tarea mensual lo hace con el rol sistema)")
    await svc.calcular_depreciacion(db, equipo, hasta)
    await svc.calcular_tco(db, equipo, hasta, actor)
    await db.commit()
    return await svc.ficha(db, actor, equipo)


@router.post("/alertas-reemplazo/{alerta_id}/decidir", response_model=DecisionResultado, summary="Aceptar (genera el TE de reemplazo) o posponer con razón")
async def decidir(alerta_id: UUID, datos: DecisionEntrada, request: Request, db: DB, actor: Actor = Depends(TODOS)):
    a = await db.get(ActivoReemplazoAlerta, alerta_id)
    if a is None or (not actor.es_superadmin and actor.tenant_id != a.tenant_id):
        raise no_encontrado("Alerta de reemplazo")
    r = await svc.decidir_reemplazo(db, actor, a, datos.decision, datos.razon, request)
    await db.commit()
    te = r["trabajo_especial"]
    salida = next(x for x in await svc.alertas_reemplazo(db, actor, pendientes=False) if x["id"] == a.id)
    return DecisionResultado(alerta=AlertaReemplazoSalida(**salida),
                             trabajo_especial=None if te is None else {"id": te.id, "numero": te.numero, "estado": te.estado.value,
                                                                        "descripcion": te.descripcion})
