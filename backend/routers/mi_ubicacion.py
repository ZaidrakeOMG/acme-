"""Solo el dueño del dispositivo puede activar su ubicación con consentimiento."""
from fastapi import APIRouter

from core.dependencias import DB, ActorActual
from core.errors import ErrorAPI
from schemas.rastreo_usuario import ConsentimientoUsuario, MiRastreo, PuntoUsuario
from services import rastreo_usuarios_service as svc

router = APIRouter(prefix="/api/mi-ubicacion", tags=["Mi ubicación"])


@router.get("", response_model=MiRastreo)
async def mi_estado(db: DB, actor: ActorActual):
    return await svc.mi_estado(db, actor)


@router.post("/iniciar", response_model=MiRastreo)
async def comenzar(datos: ConsentimientoUsuario, db: DB, actor: ActorActual):
    if not datos.acepto:
        raise ErrorAPI(422, "CONSENTIMIENTO_REQUERIDO",
                       "Debes aceptar voluntariamente compartir tu ubicación")
    r = await svc.iniciar(db, actor, datos.dispositivo)
    await db.commit()
    return r


@router.put("", response_model=MiRastreo)
async def posicion(datos: PuntoUsuario, db: DB, actor: ActorActual):
    r = await svc.actualizar(db, actor, datos.lat, datos.lng, datos.precision_m)
    await db.commit()
    return r


@router.post("/detener", response_model=MiRastreo)
async def detener(db: DB, actor: ActorActual):
    r = await svc.detener(db, actor)
    await db.commit()
    return r
