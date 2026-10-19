"""Consulta de auditoría (solo lectura, superadmin). La tabla es append-only a nivel de base de datos."""
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select

from core.dependencias import DB, Actor, requiere_rol
from models.auditoria import AuditAccesoAPI, AuditLog
from models.base import Rol
from schemas.comun import RESPUESTAS_ERROR, Modelo
from services import auditoria

router = APIRouter(prefix="/api/auditoria", tags=["Auditoría"], responses=RESPUESTAS_ERROR)

SUPERADMIN = requiere_rol(Rol.superadmin)


class EventoSalida(Modelo):
    id: UUID
    created_at: datetime
    evento_tipo: str
    actor_id: UUID | None
    actor_rol: str | None
    tenant_id: UUID | None
    prestador_id: UUID | None
    recurso_tipo: str | None
    recurso_id: str | None
    valor_anterior_json: dict | None
    valor_nuevo_json: dict | None
    ip_origen: str | None


class AccesoSalida(Modelo):
    id: UUID
    created_at: datetime
    metodo: str
    ruta: str
    codigo_respuesta: int
    duracion_ms: int
    usuario_id: UUID | None
    tenant_id: UUID | None
    ip_origen: str | None


@router.get("/eventos", response_model=list[EventoSalida], summary="Eventos de auditoría",
            description="Filtros por tipo de evento, actor, tenant y rango de fechas. Ordenado del más reciente al más antiguo.")
async def eventos(request: Request, db: DB, actor: Actor = Depends(SUPERADMIN),
                  evento_tipo: str | None = None, actor_id: UUID | None = None, tenant_id: UUID | None = None,
                  desde: datetime | None = None, hasta: datetime | None = None,
                  limite: int = Query(default=200, ge=1, le=2000)):
    consulta = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limite)
    if evento_tipo:
        consulta = consulta.where(AuditLog.evento_tipo.like(f"{evento_tipo}%"))
    if actor_id:
        consulta = consulta.where(AuditLog.actor_id == actor_id)
    if tenant_id:
        consulta = consulta.where(AuditLog.tenant_id == tenant_id)
    if desde:
        consulta = consulta.where(AuditLog.created_at >= desde)
    if hasta:
        consulta = consulta.where(AuditLog.created_at < hasta)
    filas = (await db.execute(consulta)).scalars().all()
    await auditoria.registrar_actor(db, actor, "datos_sensibles.consulta", request, recurso_tipo="audit_log",
                                    despues={"registros": len(filas)})
    await db.commit()
    return filas


@router.get("/accesos-api", response_model=list[AccesoSalida], summary="Accesos a la API",
            description="Cada llamada REST con método, ruta, código de respuesta y duración.")
async def accesos(db: DB, _: Actor = Depends(SUPERADMIN), usuario_id: UUID | None = None, codigo_minimo: int | None = None,
                  desde: datetime | None = None, limite: int = Query(default=200, ge=1, le=2000)):
    consulta = select(AuditAccesoAPI).order_by(AuditAccesoAPI.created_at.desc()).limit(limite)
    if usuario_id:
        consulta = consulta.where(AuditAccesoAPI.usuario_id == usuario_id)
    if codigo_minimo:
        consulta = consulta.where(AuditAccesoAPI.codigo_respuesta >= codigo_minimo)
    if desde:
        consulta = consulta.where(AuditAccesoAPI.created_at >= desde)
    return (await db.execute(consulta)).scalars().all()
