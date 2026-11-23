"""Pantalla de operaciones en tiempo real y jornada del técnico (§6.8.4, §6.8.6). F2-03."""
import asyncio
import contextlib
import json
import logging
from uuid import UUID

import jwt
from fastapi import APIRouter, Depends, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

from core.db import nueva_sesion
from core.dependencias import DB, Actor, ActorActual, requiere_rol, usuario_actual
from core.errors import ErrorAPI, prohibido
from core.middleware import contexto_desde_claims
from core.security import TIPO_ACCESO, decodificar_jwt
from models.base import Rol
from schemas.rastreo_folio import UsuarioUbicacionFolio
from models.operaciones import CerradaPorJornada
from schemas.comun import RESPUESTAS_ERROR, Mensaje
from schemas.operaciones import (
    AlertaDelTecnico, JornadaEntrada, LotePosiciones, MiJornadaSalida, PausaEntrada, PosicionesSalida,
    RecorridoSalida, RespuestaAlertaEntrada, TableroSalida,

)
from services import operacion_service as svc
from services import rastreo_folios_service as rastreo
from services.ws_manager import gestor

log = logging.getLogger("acma.operacion")

router = APIRouter(prefix="/api/operacion", tags=["Operaciones en tiempo real"], responses=RESPUESTAS_ERROR)
# El WebSocket vive fuera de `/api`, como el del chat de P05: el proxy del servidor de desarrollo solo levanta la
# conexión en `/ws` (`vite.config.ts`), y en producción es la misma regla para los dos canales.
router_ws = APIRouter(tags=["Operaciones en tiempo real"])

TECNICO = requiere_rol(Rol.tecnico)
DESPACHO = requiere_rol(*svc.VEN_TABLERO)


# ------------------------------------------------------------------ jornada del técnico
@router.get("/parametros", summary="Frecuencias, umbrales y aviso de registro de ubicación",
            description="Las frecuencias son las de §6.8.4: 30 s en jornada, 5 min en pausa y 2 min con batería "
                        "baja. El servidor no las impone; la app las usa y aquí quedan en un solo lugar.")
async def parametros(db: DB, actor: ActorActual) -> dict:
    return await svc.parametros(db, actor.prestador_id)


@router.get("/mi-jornada", response_model=MiJornadaSalida, summary="Mi jornada (app del técnico)")
async def mi_jornada(db: DB, actor: Actor = Depends(TECNICO)):
    return await svc.mi_jornada(db, actor)


@router.post("/jornada/iniciar", response_model=MiJornadaSalida, status_code=201, summary="Iniciar mi jornada",
             description="Sin jornada iniciada no se registra ninguna posición (§6.8.4). La primera vez hay que "
                         "aceptar el aviso de qué se registra y para qué.")
async def iniciar(datos: JornadaEntrada, request: Request, db: DB, actor: Actor = Depends(TECNICO)):
    await svc.iniciar_jornada(db, actor, dispositivo_id=datos.dispositivo_id, acepta_aviso=datos.acepta_aviso,
                              request=request)
    await db.commit()
    return await svc.mi_jornada(db, actor)


@router.post("/jornada/cerrar", response_model=MiJornadaSalida, summary="Cerrar mi jornada")
async def cerrar(request: Request, db: DB, actor: Actor = Depends(TECNICO)):
    await svc.cerrar_jornada(db, actor, cerrada_por=CerradaPorJornada.tecnico, request=request)
    await db.commit()
    return await svc.mi_jornada(db, actor)


@router.post("/jornada/pausar", response_model=MiJornadaSalida, summary="Pausar mi jornada (comida, trámite, otro)")
async def pausar(datos: PausaEntrada, db: DB, actor: Actor = Depends(TECNICO)):
    await svc.pausar(db, actor, motivo=datos.motivo.value, nota=datos.nota)
    await db.commit()
    return await svc.mi_jornada(db, actor)


@router.post("/jornada/reanudar", response_model=MiJornadaSalida, summary="Reanudar mi jornada")
async def reanudar(db: DB, actor: Actor = Depends(TECNICO)):
    await svc.reanudar(db, actor)
    await db.commit()
    return await svc.mi_jornada(db, actor)


@router.post("/jornada/{jornada_id}/cerrar", response_model=Mensaje,
             summary="Cerrar la jornada de un técnico (despachador)",
             description="Para el técnico que terminó y olvidó cerrarla. Queda registrado quién la cerró.")
async def cerrar_ajena(jornada_id: UUID, request: Request, db: DB,
                       actor: Actor = Depends(requiere_rol(Rol.superadmin, Rol.admin_prestador, Rol.despachador))):
    from models.operaciones import JornadaTecnico

    jornada = await db.get(JornadaTecnico, jornada_id)
    if jornada is None or (not actor.es_superadmin and jornada.prestador_id != actor.prestador_id):
        raise ErrorAPI(404, "NO_ENCONTRADO", "Jornada no encontrada")
    await svc.cerrar_jornada(db, actor, jornada=jornada, cerrada_por=CerradaPorJornada.despachador, request=request)
    await db.commit()
    return Mensaje(mensaje="Jornada cerrada")


# ------------------------------------------------------------------ posiciones
@router.post("/posiciones", response_model=PosicionesSalida, summary="Enviar un lote de posiciones (app del técnico)",
             description="La app manda lotes pequeños; lo que guardó sin señal llega marcado como `tardia` y no "
                         "mueve la última posición si es más vieja que la que ya está.")
async def posiciones(datos: LotePosiciones, db: DB, actor: Actor = Depends(TECNICO)):
    resultado = await svc.registrar_posiciones(db, actor, [p.model_dump() for p in datos.posiciones])
    await db.commit()
    return resultado


@router.get("/mis-posiciones", response_model=RecorridoSalida, summary="Mi recorrido de hoy (app del técnico)")
async def mis_posiciones(request: Request, db: DB, actor: Actor = Depends(TECNICO),
                         horas: float = Query(default=8, ge=0.25, le=24)):
    tecnico = await svc.tecnico_del_usuario(db, actor.id)
    salida = await svc.recorrido(db, actor, tecnico.id, horas=horas, request=request)
    await db.commit()
    return salida


@router.get("/tecnicos/{tecnico_id}/recorrido", response_model=RecorridoSalida,
            summary="Recorrido de un técnico (últimas horas)",
            description="Consultarlo queda registrado como acceso a datos sensibles (§6.9.5). El cliente no tiene "
                        "acceso a este endpoint ni a la tabla.")
async def recorrido(tecnico_id: UUID, request: Request, db: DB, actor: ActorActual,
                    horas: float = Query(default=svc.HORAS_RECORRIDO, ge=0.25, le=24)):
    salida = await svc.recorrido(db, actor, tecnico_id, horas=horas, request=request)
    await db.commit()
    return salida


# Solo despacho ve ubicaciones expresamente compartidas y vigentes del mismo prestador.
@router.get("/usuarios-compartiendo", response_model=list[UsuarioUbicacionFolio])
async def usuarios_compartiendo(db: DB, actor: Actor = Depends(DESPACHO)):
    return await rastreo.ubicaciones_compartidas(db, actor)


# ------------------------------------------------------------------ tablero
@router.get("/tablero", response_model=TableroSalida, summary="Tablero de operaciones (§6.8.4)",
            description="Técnicos en jornada con su estatus y posición, folios activos con el contador de SLA, "
                        "unidades con folios abiertos, feed de alertas e indicadores globales de jornada.")
async def tablero(db: DB, actor: Actor = Depends(DESPACHO)):
    return await svc.tablero(db, actor)


@router.get("/mis-alertas", response_model=list[AlertaDelTecnico],
            summary="Avisos que esperan mi respuesta (app del técnico)")
async def mis_alertas(db: DB, actor: Actor = Depends(TECNICO)):
    return await svc.mis_alertas(db, actor)


@router.post("/alertas/{seguimiento_id}/responder", summary="«Estoy bien» o «Necesito apoyo»",
             description="«Necesito apoyo» levanta de inmediato una alerta de prioridad alta al despachador.")
async def responder_alerta(seguimiento_id: UUID, datos: RespuestaAlertaEntrada, request: Request, db: DB,
                           actor: Actor = Depends(TECNICO)) -> dict:
    seguimiento = await svc.responder_alerta(db, actor, seguimiento_id, datos.respuesta.value, request)
    await db.commit()
    return {"id": str(seguimiento.id), "respuesta": seguimiento.respuesta_tecnico.value,
            "respondida_at": seguimiento.respondida_at}


# ------------------------------------------------------------------ tiempo real
async def _actor_desde_token(token: str | None) -> Actor:
    if not token:
        raise prohibido("Token requerido")
    try:
        claims = decodificar_jwt(token, TIPO_ACCESO)
    except (jwt.PyJWTError, ValueError):
        raise prohibido("Token inválido")

    class _Req:
        state = type("S", (), {"claims": claims})()
        url = type("U", (), {"path": "/api/operacion/stream"})()

    async with nueva_sesion(contexto_desde_claims(claims)) as db:
        return await usuario_actual(_Req(), db)  # type: ignore[arg-type]


def _canal_de(actor: Actor) -> str:
    """Un canal por prestador: el tablero de un prestador no recibe las posiciones de otro (§6.9.5)."""
    if actor.prestador_id is None:
        raise prohibido("Tu usuario no pertenece a un prestador")
    return f"operacion:{actor.prestador_id}"


@router_ws.websocket("/ws/operacion")
async def ws_operacion(websocket: WebSocket, token: str | None = Query(default=None)):
    """Eventos del tablero: posiciones, estatus, jornadas, alertas y escalaciones."""
    try:
        actor = await _actor_desde_token(token)
        await svc.exigir_tablero(actor)
        canal = _canal_de(actor)
    except (ErrorAPI, Exception):  # noqa: BLE001 — cualquier fallo de autenticación cierra el socket
        with contextlib.suppress(Exception):
            await websocket.close(code=4403)
        return
    await websocket.accept()
    cola = await gestor.suscribir_canal(canal)
    await websocket.send_text(json.dumps({"evento": "conectado", "canal": canal}))

    async def _recibir():
        while True:
            texto = await websocket.receive_text()
            if texto == "ping":
                await websocket.send_text(json.dumps({"evento": "pong"}))

    tarea = asyncio.create_task(_recibir())
    try:
        while True:
            evento = await cola.get()
            await websocket.send_text(json.dumps(evento, default=str))
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        tarea.cancel()
        await gestor.desuscribir_canal(canal, cola)


@router.get("/stream", summary="Respaldo SSE del tablero",
            description="`?token=` porque EventSource no manda cabeceras. Un `data:` por evento; latidos cada 15 s.")
async def stream(request: Request, token: str | None = Query(default=None)):
    actor = await _actor_desde_token(token or (request.headers.get("authorization", "")[7:] or None))
    await svc.exigir_tablero(actor)
    canal = _canal_de(actor)
    cola = await gestor.suscribir_canal(canal)

    async def _generar():
        try:
            yield f"event: conectado\ndata: {json.dumps({'canal': canal})}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    evento = await asyncio.wait_for(cola.get(), timeout=15)
                    yield f"data: {json.dumps(evento, default=str)}\n\n"
                except asyncio.TimeoutError:
                    yield ": latido\n\n"
        finally:
            await gestor.desuscribir_canal(canal, cola)

    return StreamingResponse(_generar(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
