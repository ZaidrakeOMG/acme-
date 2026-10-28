"""Chat archivado por folio (§6.8.1): mensajes por HTTP, recepción en tiempo real por WebSocket con fallback SSE."""
import asyncio
import json
import uuid
from datetime import datetime
from uuid import UUID

import jwt
from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

from core.db import nueva_sesion
from core.dependencias import DB, Actor, ActorActual, requiere_rol, usuario_actual
from core.errors import ErrorAPI, prohibido
from core.middleware import contexto_desde_claims
from core.security import TIPO_ACCESO, decodificar_jwt
from models.base import Rol
from models.chat import TipoMensaje
from schemas.comun import RESPUESTAS_ERROR, Mensaje
from schemas.sync import ChatSalida, LeidoEntrada, MensajeEntrada, MensajeSalida, ParticipanteEntrada
from services import chat_service
from services import folios_captura_service as folios
from services.almacenamiento import obtener_almacenamiento
from services.ws_manager import gestor

router = APIRouter(tags=["Chat del folio"], responses=RESPUESTAS_ERROR)


@router.get("/api/folios/{folio_id}/chats", response_model=list[ChatSalida], summary="Los tres canales del folio",
            description="Con bandera de participación, permisos de gestión y mensajes no leídos. Solo los participantes leen los mensajes (RLS).")
async def chats_del_folio(folio_id: UUID, db: DB, actor: Actor = Depends(requiere_rol(*Rol))):
    folio = await folios.obtener(db, actor, folio_id)
    return [ChatSalida(**c) for c in await chat_service.chats_para(db, actor, folio)]


@router.get("/api/chats/{chat_id}/mensajes", response_model=list[MensajeSalida], summary="Mensajes del chat (desde un timestamp)")
async def mensajes(chat_id: UUID, db: DB, actor: ActorActual, desde: datetime | None = None, limite: int = Query(default=200, ge=1, le=1000)):
    chat = await chat_service.obtener_chat(db, chat_id)
    return [MensajeSalida(**m) for m in await chat_service.listar_mensajes(db, actor, chat, desde, limite)]


@router.post("/api/chats/{chat_id}/mensajes", response_model=MensajeSalida, status_code=201, summary="Enviar mensaje (JSON)",
             description="`id_cliente` obligatorio (idempotencia de la cola offline). El servidor fija `timestamp_servidor` y conserva "
                         "`timestamp_dispositivo` (doble timestamp §6.8.1). Folio cerrado: solo evidencia posterior (imagen por multipart).")
async def enviar(chat_id: UUID, datos: MensajeEntrada, request: Request, db: DB, actor: ActorActual):
    chat = await chat_service.obtener_chat(db, chat_id)
    m, dup = await chat_service.enviar_mensaje(db, actor, chat, contenido=datos.contenido_texto, tipo=datos.tipo, id_cliente=datos.id_cliente,
                                               timestamp_dispositivo=datos.timestamp_dispositivo, datos=datos.datos, request=request)
    await db.commit()
    salida = await chat_service.publicar_mensaje(db, m, actor.nombre) if not dup else chat_service.serializar(m, None, actor.nombre)
    return MensajeSalida(**salida, duplicado=dup)


@router.post("/api/chats/{chat_id}/mensajes/archivo", response_model=MensajeSalida, status_code=201, summary="Enviar mensaje con adjunto (multipart)")
async def enviar_archivo(chat_id: UUID, request: Request, db: DB, actor: ActorActual, archivo: UploadFile = File(...), id_cliente: UUID = Form(...),
                         tipo: TipoMensaje = Form(default=TipoMensaje.imagen), contenido_texto: str = Form(default=""),
                         timestamp_dispositivo: datetime | None = Form(default=None)):
    chat = await chat_service.obtener_chat(db, chat_id)
    contenido = await archivo.read()
    m, dup = await chat_service.enviar_mensaje(db, actor, chat, contenido=contenido_texto, tipo=tipo, id_cliente=id_cliente,
                                               timestamp_dispositivo=timestamp_dispositivo,
                                               archivo=(contenido, archivo.filename or "adjunto", archivo.content_type or "application/octet-stream"), request=request)
    await db.commit()
    salida = await chat_service.publicar_mensaje(db, m, actor.nombre) if not dup else chat_service.serializar(m, None, actor.nombre)
    return MensajeSalida(**salida, duplicado=dup)


@router.get("/api/chats/{chat_id}/archivos/{archivo_id}", summary="Descargar un adjunto del chat")
async def descargar_archivo(chat_id: UUID, archivo_id: UUID, db: DB, actor: ActorActual):
    from fastapi.responses import Response
    from sqlalchemy import select

    from models.chat import ChatArchivo

    chat = await chat_service.obtener_chat(db, chat_id)
    await chat_service.exigir_participante(db, actor, chat)
    a = (await db.execute(select(ChatArchivo).where(ChatArchivo.id == archivo_id, ChatArchivo.chat_id == chat.id))).scalar_one_or_none()
    if a is None:
        raise ErrorAPI(404, "NO_ENCONTRADO", "Archivo no encontrado")
    return Response(obtener_almacenamiento().leer(a.archivo_key), media_type=a.tipo_mime)


@router.post("/api/chats/{chat_id}/leido", response_model=Mensaje, summary="Marcar mensajes como leídos")
async def leido(chat_id: UUID, datos: LeidoEntrada, db: DB, actor: ActorActual):
    chat = await chat_service.obtener_chat(db, chat_id)
    n = await chat_service.marcar_leido(db, actor, chat, datos.hasta)
    await db.commit()
    return Mensaje(mensaje=f"{n} mensaje(s) marcados como leídos")


@router.post("/api/chats/{chat_id}/participantes", response_model=ChatSalida, status_code=201, summary="Agregar participante (permisos §6.8.1)")
async def agregar_participante(chat_id: UUID, datos: ParticipanteEntrada, request: Request, db: DB, actor: ActorActual):
    chat = await chat_service.obtener_chat(db, chat_id)
    await chat_service.agregar_participante(db, actor, chat, datos.usuario_id, request)
    await db.commit()
    folio = await folios.obtener(db, actor, chat.folio_id)
    return next(ChatSalida(**c) for c in await chat_service.chats_para(db, actor, folio) if c["id"] == chat.id)


@router.delete("/api/chats/{chat_id}/participantes/{usuario_id}", response_model=Mensaje, summary="Quitar participante adicional")
async def quitar_participante(chat_id: UUID, usuario_id: UUID, request: Request, db: DB, actor: ActorActual):
    chat = await chat_service.obtener_chat(db, chat_id)
    await chat_service.quitar_participante(db, actor, chat, usuario_id, request)
    await db.commit()
    return Mensaje(mensaje="Participante retirado")


# ------------------------------------------------------------ tiempo real

async def _actor_desde_token(token: str | None) -> Actor:
    if not token:
        raise prohibido("Token requerido")
    try:
        claims = decodificar_jwt(token, TIPO_ACCESO)
    except (jwt.PyJWTError, ValueError):
        raise prohibido("Token inválido")

    class _Req:  # mínimo que usuario_actual() necesita
        state = type("S", (), {"claims": claims})()

    async with nueva_sesion(contexto_desde_claims(claims)) as db:
        return await usuario_actual(_Req(), db)  # type: ignore[arg-type]


async def _verificar_participante(actor: Actor, chat_id: UUID) -> None:
    from core.rls import ContextoRLS

    async with nueva_sesion(ContextoRLS(usuario_id=actor.id, tenant_id=actor.tenant_id, prestador_id=actor.prestador_id, rol=actor.rol.value)) as db:
        chat = await chat_service.obtener_chat(db, chat_id)
        await chat_service.exigir_participante(db, actor, chat)


@router.websocket("/ws/chats/{chat_id}")
async def ws_chat(websocket: WebSocket, chat_id: UUID, token: str | None = Query(default=None)):
    """Un canal por chat. Autenticación con el JWT en `?token=`. El envío siempre es HTTP POST (§6.8.1)."""
    try:
        actor = await _actor_desde_token(token)
        await _verificar_participante(actor, chat_id)
    except ErrorAPI:
        await websocket.close(code=4403)
        return
    await websocket.accept()
    cola = await gestor.suscribir(str(chat_id))
    await websocket.send_text(json.dumps({"evento": "conectado", "chat_id": str(chat_id), "usuario_id": str(actor.id)}))

    async def _recibir():
        while True:
            texto = await websocket.receive_text()  # latidos del cliente; el envío va por HTTP
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
        await gestor.desuscribir(str(chat_id), cola)


@router.get("/api/chats/{chat_id}/stream", summary="Fallback SSE (recepción); el envío es HTTP POST",
            description="`?token=` porque EventSource no envía cabeceras. Un evento `data:` por mensaje; latidos cada 15 s.")
async def sse_chat(chat_id: UUID, request: Request, token: str | None = Query(default=None)):
    actor = await _actor_desde_token(token or (request.headers.get("authorization", "")[7:] or None))
    await _verificar_participante(actor, chat_id)
    cola = await gestor.suscribir(str(chat_id))

    async def _generar():
        try:
            yield f"event: conectado\ndata: {json.dumps({'chat_id': str(chat_id)})}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    evento = await asyncio.wait_for(cola.get(), timeout=15)
                    yield f"data: {json.dumps(evento, default=str)}\n\n"
                except asyncio.TimeoutError:
                    yield ": latido\n\n"
        finally:
            await gestor.desuscribir(str(chat_id), cola)

    return StreamingResponse(_generar(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


__all__ = ["router", "uuid"]
