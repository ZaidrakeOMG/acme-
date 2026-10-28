"""Suscripciones push PWA (web-push). La clave pública VAPID la usa el navegador al suscribirse."""
from fastapi import APIRouter, Request

from core.config import config
from core.dependencias import DB, ActorActual
from schemas.comun import RESPUESTAS_ERROR, Mensaje
from schemas.sync import ClavePublicaSalida, SuscripcionPushEntrada
from services import push_service

router = APIRouter(prefix="/api/push", tags=["Notificaciones push"], responses=RESPUESTAS_ERROR)


@router.get("/clave-publica", response_model=ClavePublicaSalida, summary="Clave pública VAPID (null si el push no está configurado)")
async def clave_publica(_: ActorActual):
    return ClavePublicaSalida(clave_publica=config.vapid_clave_publica or None, habilitado=push_service.habilitado())


@router.post("/suscripcion", response_model=Mensaje, status_code=201, summary="Registrar la suscripción del dispositivo")
async def suscribir(datos: SuscripcionPushEntrada, request: Request, db: DB, actor: ActorActual):
    await push_service.registrar(db, actor, datos.endpoint, datos.keys, datos.dispositivo_id, request.headers.get("user-agent"))
    await db.commit()
    return Mensaje(mensaje="Suscripción registrada")


@router.delete("/suscripcion", response_model=Mensaje, summary="Dar de baja la suscripción")
async def desuscribir(datos: SuscripcionPushEntrada, db: DB, actor: ActorActual):
    ok = await push_service.eliminar(db, actor, datos.endpoint)
    await db.commit()
    return Mensaje(mensaje="Suscripción desactivada" if ok else "No había suscripción")
