"""Chat multiusuario archivado en el folio (§6.8.1): tres canales con participantes fijos, permisos para agregar,
mensajes con doble timestamp e idempotencia por `id_cliente`, eventos de sistema por transición e inmutabilidad en
folios cerrados. Se engancha a P04 con `folio_estados.suscribir` y `folio_estados.suscribir_creacion`."""
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.dependencias import Actor
from core.errors import ErrorAPI, no_encontrado, prohibido
from models.base import Dominio, EstadoRegistro, Rol
from models.chat import CanalChat, Chat, ChatArchivo, ChatEventoSistema, ChatMensaje, ChatParticipante, EstadoChat, TipoMensaje
from models.folios import EstadoFolio, Folio, FolioEstadoHistorial
from models.unidades import UsuarioUN
from models.usuarios import Usuario
from services import auditoria, folio_estados
from services.almacenamiento import obtener_almacenamiento
from services.folio_estados import ACTOR_SISTEMA, ActorFolio
from services.formularios.evidencias import extension_de
from services.ws_manager import gestor

ROLES_PRESTADOR = {Rol.admin_prestador, Rol.despachador, Rol.mesa_control, Rol.supervisor_prestador, Rol.direccion_prestador, Rol.tecnico}
ROLES_TENANT = {Rol.admin_empresa, Rol.admin_un, Rol.supervisor_operadores, Rol.operador}
# §6.8.1 "Quién puede agregar" → roles que puede agregar en cada canal.
PUEDE_AGREGAR: dict[CanalChat, dict[Rol, set[Rol]]] = {
    CanalChat.campo: {Rol.admin_prestador: {Rol.tecnico}, Rol.despachador: {Rol.tecnico}, Rol.admin_un: {Rol.operador}},
    CanalChat.operativo: {Rol.admin_prestador: ROLES_PRESTADOR | ROLES_TENANT},
    CanalChat.interno: {Rol.admin_prestador: ROLES_PRESTADOR},
}
TEXTO_EVENTO = {
    EstadoFolio.asignado: "Folio asignado al técnico {tecnico}",
    EstadoFolio.reasignado: "Folio en reasignación",
    EstadoFolio.en_camino: "El técnico va en camino",
    EstadoFolio.en_ejecucion: "El técnico confirmó su llegada; inicia la atención",
    EstadoFolio.pendiente_refaccion: "Pendiente de refacción",
    EstadoFolio.cerrado: "Folio cerrado",
    EstadoFolio.cancelado: "Folio cancelado",
    EstadoFolio.autorizado: "Folio autorizado",
}
CANALES_EVENTO = {
    EstadoFolio.asignado: (CanalChat.campo, CanalChat.operativo), EstadoFolio.reasignado: (CanalChat.campo, CanalChat.operativo),
    EstadoFolio.en_camino: (CanalChat.campo, CanalChat.operativo), EstadoFolio.en_ejecucion: (CanalChat.campo, CanalChat.operativo),
    EstadoFolio.pendiente_refaccion: (CanalChat.campo, CanalChat.operativo), EstadoFolio.autorizado: (CanalChat.operativo, CanalChat.interno),
    EstadoFolio.cerrado: (CanalChat.campo, CanalChat.operativo, CanalChat.interno),
    EstadoFolio.cancelado: (CanalChat.campo, CanalChat.operativo, CanalChat.interno),
}


# ------------------------------------------------------------- creación

async def _agregar(db: AsyncSession, chat: Chat, usuario: Usuario, agregado_por: uuid.UUID | None = None) -> ChatParticipante | None:
    existente = (await db.execute(select(ChatParticipante).where(
        ChatParticipante.chat_id == chat.id, ChatParticipante.usuario_id == usuario.id))).scalar_one_or_none()
    if existente is not None:
        if not existente.activo:
            existente.activo = True
        return existente
    p = ChatParticipante(chat_id=chat.id, tenant_id=chat.tenant_id, prestador_id=chat.prestador_id, usuario_id=usuario.id,
                         rol=usuario.rol, agregado_por=agregado_por)
    db.add(p)
    await db.flush()
    return p


async def chats_del_folio(db: AsyncSession, folio_id: uuid.UUID) -> dict[CanalChat, Chat]:
    return {c.canal: c for c in (await db.execute(select(Chat).where(Chat.folio_id == folio_id))).scalars()}


async def crear_chats(db: AsyncSession, folio: Folio, actor: ActorFolio) -> dict[CanalChat, Chat]:
    """Los tres chats con los participantes fijos de §6.8.1 (el técnico entra al asignarse; el despachador al actuar)."""
    existentes = await chats_del_folio(db, folio.id)
    if existentes:
        return existentes
    chats = {}
    for canal in CanalChat:
        c = Chat(folio_id=folio.id, tenant_id=folio.tenant_id, prestador_id=folio.prestador_id, canal=canal)
        db.add(c)
        chats[canal] = c
    await db.flush()
    capturador = await db.get(Usuario, folio.capturado_por)
    if capturador is not None:
        await _agregar(db, chats[CanalChat.campo], capturador)
    admins_un = (await db.execute(select(Usuario).join(UsuarioUN, UsuarioUN.usuario_id == Usuario.id).where(
        UsuarioUN.unidad_id == folio.un_id, Usuario.rol == Rol.admin_un, Usuario.estado == EstadoRegistro.activo))).scalars().all()
    for u in admins_un:
        await _agregar(db, chats[CanalChat.operativo], u)
    admins_prestador = (await db.execute(select(Usuario).where(
        Usuario.prestador_id == folio.prestador_id, Usuario.rol == Rol.admin_prestador, Usuario.estado == EstadoRegistro.activo))).scalars().all()
    for u in admins_prestador:
        await _agregar(db, chats[CanalChat.interno], u)
    await db.flush()
    return chats


# ------------------------------------------------------- eventos de sistema

async def evento_sistema(db: AsyncSession, chat: Chat, tipo_evento: str, texto: str, datos: dict[str, Any] | None = None) -> ChatMensaje:
    datos = auditoria.a_json(datos or {})
    db.add(ChatEventoSistema(chat_id=chat.id, tenant_id=chat.tenant_id, prestador_id=chat.prestador_id, tipo_evento=tipo_evento, datos_json=datos))
    m = ChatMensaje(chat_id=chat.id, tenant_id=chat.tenant_id, prestador_id=chat.prestador_id, usuario_id=None, contenido_texto=texto,
                    tipo=TipoMensaje.sistema, timestamp_servidor=datetime.now(UTC), datos_json={"tipo_evento": tipo_evento, **datos})
    db.add(m)
    await db.flush()  # sin refresh: quien transiciona puede no ser participante y no podría releer la fila
    await gestor.publicar(str(chat.id), {"evento": "mensaje", "mensaje": serializar(m)})
    return m


@folio_estados.suscribir_creacion
async def _al_crear_folio(db: AsyncSession, folio: Folio, actor: ActorFolio) -> None:
    chats = await crear_chats(db, folio, actor)
    await evento_sistema(db, chats[CanalChat.campo], "folio.capturado", f"Folio {folio.numero_folio} capturado", {"folio_id": str(folio.id)})


@folio_estados.suscribir
async def _al_transicionar(db: AsyncSession, folio: Folio, anterior: EstadoFolio, nuevo: EstadoFolio, actor: ActorFolio, contexto: dict) -> None:
    chats = await chats_del_folio(db, folio.id)
    if not chats:
        return
    # El despachador que autoriza/asigna entra a los canales operativo e interno; el técnico asignado al de campo.
    if isinstance(actor, Actor) and actor.rol == Rol.despachador:
        u = await db.get(Usuario, actor.id)
        if u is not None:
            for canal in (CanalChat.operativo, CanalChat.interno):
                if canal in chats:
                    await _agregar(db, chats[canal], u)
    tecnico = None
    if nuevo == EstadoFolio.asignado and folio.tecnico_id and CanalChat.campo in chats:
        tecnico = await db.get(Usuario, folio.tecnico_id)
        if tecnico is not None:
            await _agregar(db, chats[CanalChat.campo], tecnico)
    if nuevo in CANALES_EVENTO:
        texto = TEXTO_EVENTO[nuevo].format(tecnico=tecnico.nombre if tecnico else (contexto or {}).get("tecnico_nombre", ""))
        if nuevo == EstadoFolio.cancelado and folio.razon_cancelacion:
            texto += f": {folio.razon_cancelacion}"
        datos = {"estado_anterior": anterior.value, "estado_nuevo": nuevo.value, "actor_rol": folio_estados.rol_de(actor),
                 "timestamp_dispositivo": (contexto or {}).get("timestamp_dispositivo")}
        for canal in CANALES_EVENTO[nuevo]:
            if canal in chats and chats[canal].estado == EstadoChat.activo:
                await evento_sistema(db, chats[canal], f"folio.{nuevo.value}", texto, datos)
    if nuevo == EstadoFolio.cancelado:
        # §6.8.1: borrado lógico solo para chats de folios cancelados antes de asignación.
        asignado = (await db.execute(select(FolioEstadoHistorial.id).where(
            FolioEstadoHistorial.folio_id == folio.id, FolioEstadoHistorial.estado_nuevo == EstadoFolio.asignado))).first()
        if asignado is None:
            for c in chats.values():
                c.estado = EstadoChat.archivado
            for m in (await db.execute(select(ChatMensaje).where(ChatMensaje.chat_id.in_([c.id for c in chats.values()])))).scalars():
                m.oculto = True
            await db.flush()


# ------------------------------------------------------------- consultas

def serializar(m: ChatMensaje, archivos: list[ChatArchivo] | None = None, usuario_nombre: str | None = None) -> dict[str, Any]:
    return {
        "id": str(m.id), "chat_id": str(m.chat_id), "usuario_id": str(m.usuario_id) if m.usuario_id else None, "usuario_nombre": usuario_nombre,
        "contenido_texto": m.contenido_texto, "tipo": m.tipo.value, "timestamp_servidor": m.timestamp_servidor.isoformat(),
        "timestamp_dispositivo": m.timestamp_dispositivo.isoformat() if m.timestamp_dispositivo else None,
        "leido_por_json": m.leido_por_json or {}, "datos_json": m.datos_json or {}, "id_cliente": str(m.id_cliente),
        "archivos": [{"id": str(a.id), "archivo_key": a.archivo_key, "nombre_original": a.nombre_original, "tipo_mime": a.tipo_mime,
                      "tamano_bytes": a.tamano_bytes} for a in (archivos or [])],
    }


async def obtener_chat(db: AsyncSession, chat_id: uuid.UUID) -> Chat:
    c = await db.get(Chat, chat_id)
    if c is None:
        raise no_encontrado("Chat")
    return c


async def participante(db: AsyncSession, chat: Chat, usuario_id: uuid.UUID) -> ChatParticipante | None:
    return (await db.execute(select(ChatParticipante).where(
        ChatParticipante.chat_id == chat.id, ChatParticipante.usuario_id == usuario_id, ChatParticipante.activo.is_(True)))).scalar_one_or_none()


def puede_gestionar(actor: Actor, canal: CanalChat) -> bool:
    return actor.es_superadmin or actor.rol in PUEDE_AGREGAR[canal]


async def exigir_participante(db: AsyncSession, actor: Actor, chat: Chat) -> None:
    if actor.es_superadmin:
        return
    if await participante(db, chat, actor.id) is None:
        raise prohibido("No participas en este chat")


async def chats_para(db: AsyncSession, actor: Actor, folio: Folio) -> list[dict[str, Any]]:
    """Chats del folio con bandera de participación, permisos de gestión y no leídos (solo participantes leen mensajes)."""
    chats = await chats_del_folio(db, folio.id)
    salida = []
    for canal in CanalChat:
        c = chats.get(canal)
        if c is None:
            continue
        es_p = actor.es_superadmin or await participante(db, c, actor.id) is not None
        no_leidos = 0
        if es_p:
            no_leidos = (await db.execute(select(func.count()).select_from(ChatMensaje).where(
                ChatMensaje.chat_id == c.id, ChatMensaje.oculto.is_(False),
                ~ChatMensaje.leido_por_json.has_key(str(actor.id)),  # noqa: W601
                (ChatMensaje.usuario_id.is_(None)) | (ChatMensaje.usuario_id != actor.id)))).scalar() or 0
        participantes = (await db.execute(select(ChatParticipante, Usuario.nombre).join(Usuario, Usuario.id == ChatParticipante.usuario_id)
                                          .where(ChatParticipante.chat_id == c.id, ChatParticipante.activo.is_(True)))).all()
        salida.append({"id": c.id, "folio_id": folio.id, "canal": canal, "estado": c.estado, "es_participante": es_p,
                       "puede_gestionar": puede_gestionar(actor, canal), "no_leidos": no_leidos,
                       "participantes": [{"usuario_id": p.usuario_id, "nombre": n, "rol": p.rol, "fijo": p.agregado_por is None} for p, n in participantes]})
    return salida


async def listar_mensajes(db: AsyncSession, actor: Actor, chat: Chat, desde: datetime | None, limite: int = 200) -> list[dict[str, Any]]:
    await exigir_participante(db, actor, chat)
    if chat.estado == EstadoChat.archivado and not actor.es_superadmin:
        return []
    consulta = select(ChatMensaje, Usuario.nombre).outerjoin(Usuario, Usuario.id == ChatMensaje.usuario_id).where(
        ChatMensaje.chat_id == chat.id).order_by(ChatMensaje.timestamp_servidor, ChatMensaje.id).limit(limite)
    if not actor.es_superadmin:
        consulta = consulta.where(ChatMensaje.oculto.is_(False))  # el borrado lógico lo sigue viendo la plataforma (auditoría)
    if desde:
        consulta = consulta.where(ChatMensaje.timestamp_servidor > desde)
    filas = (await db.execute(consulta)).all()
    ids = [m.id for m, _ in filas]
    archivos: dict[uuid.UUID, list[ChatArchivo]] = {}
    if ids:
        for a in (await db.execute(select(ChatArchivo).where(ChatArchivo.mensaje_id.in_(ids)))).scalars():
            archivos.setdefault(a.mensaje_id, []).append(a)
    return [serializar(m, archivos.get(m.id), nombre) for m, nombre in filas]


# ---------------------------------------------------------------- envío

async def enviar_mensaje(db: AsyncSession, actor: Actor, chat: Chat, *, contenido: str, tipo: TipoMensaje, id_cliente: uuid.UUID,
                         timestamp_dispositivo: datetime | None, archivo: tuple[bytes, str, str] | None = None,
                         datos: dict[str, Any] | None = None, request: Request | None = None) -> tuple[ChatMensaje, bool]:
    """Devuelve (mensaje, duplicado). Idempotente por (chat, id_cliente) para la cola offline."""
    await exigir_participante(db, actor, chat)
    existente = (await db.execute(select(ChatMensaje).where(ChatMensaje.chat_id == chat.id, ChatMensaje.id_cliente == id_cliente))).scalar_one_or_none()
    if existente is not None:
        return existente, True
    if chat.estado == EstadoChat.archivado:
        raise ErrorAPI(409, "CHAT_ARCHIVADO", "El chat está archivado (folio cancelado antes de asignarse)")
    folio = await db.get(Folio, chat.folio_id)
    datos = dict(datos or {})
    if folio is not None and folio.estado == EstadoFolio.cerrado:
        # §6.8.3c: el chat es el único canal abierto para evidencia posterior al cierre (solo imágenes).
        if tipo != TipoMensaje.imagen or archivo is None:
            raise ErrorAPI(409, "CHAT_CERRADO", "El folio está cerrado: solo se admite evidencia posterior (imagen)")
        datos["evidencia_posterior"] = True
    if tipo == TipoMensaje.texto and not contenido.strip():
        raise ErrorAPI(422, "MENSAJE_VACIO", "El mensaje no puede ir vacío")
    if tipo in (TipoMensaje.imagen, TipoMensaje.audio) and archivo is None:
        raise ErrorAPI(422, "ARCHIVO_REQUERIDO", "Adjunta el archivo")
    if tipo == TipoMensaje.sistema:
        raise ErrorAPI(422, "TIPO_INVALIDO", "Los mensajes de sistema los genera ACMA")
    m = ChatMensaje(chat_id=chat.id, tenant_id=chat.tenant_id, prestador_id=chat.prestador_id, usuario_id=actor.id, contenido_texto=contenido.strip(),
                    tipo=tipo, timestamp_servidor=datetime.now(UTC), timestamp_dispositivo=timestamp_dispositivo,
                    leido_por_json={str(actor.id): datetime.now(UTC).isoformat()}, datos_json=auditoria.a_json(datos), id_cliente=id_cliente)
    db.add(m)
    await db.flush()
    archivos = []
    if archivo is not None:
        contenido_bin, nombre, mime = archivo
        if not contenido_bin:
            raise ErrorAPI(422, "ARCHIVO_VACIO", "El archivo está vacío")
        clave = f"chats/{chat.id}/{m.id}.{extension_de(mime, nombre)}"
        obtener_almacenamiento().guardar(clave, contenido_bin, mime)
        a = ChatArchivo(mensaje_id=m.id, chat_id=chat.id, tenant_id=chat.tenant_id, prestador_id=chat.prestador_id, archivo_key=clave,
                        nombre_original=nombre[:255], tipo_mime=mime, tamano_bytes=len(contenido_bin))
        db.add(a)
        await db.flush()
        archivos.append(a)
    if datos.get("evidencia_posterior"):
        await auditoria.registrar_actor(db, actor, "chat.evidencia_posterior", request, recurso_tipo="folio", recurso_id=chat.folio_id,
                                        tenant_id=chat.tenant_id, prestador_id=chat.prestador_id, despues={"mensaje_id": m.id})
    return m, False


async def publicar_mensaje(db: AsyncSession, m: ChatMensaje, actor_nombre: str | None) -> dict[str, Any]:
    archivos = (await db.execute(select(ChatArchivo).where(ChatArchivo.mensaje_id == m.id))).scalars().all()
    datos = serializar(m, list(archivos), actor_nombre)
    await gestor.publicar(str(m.chat_id), {"evento": "mensaje", "mensaje": datos})
    return datos


async def marcar_leido(db: AsyncSession, actor: Actor, chat: Chat, hasta: datetime | None = None) -> int:
    await exigir_participante(db, actor, chat)
    consulta = select(ChatMensaje).where(ChatMensaje.chat_id == chat.id, ~ChatMensaje.leido_por_json.has_key(str(actor.id)))  # noqa: W601
    if hasta:
        consulta = consulta.where(ChatMensaje.timestamp_servidor <= hasta)
    ahora = datetime.now(UTC).isoformat()
    n = 0
    for m in (await db.execute(consulta)).scalars():
        m.leido_por_json = {**(m.leido_por_json or {}), str(actor.id): ahora}
        n += 1
    await db.flush()
    if n:
        await gestor.publicar(str(chat.id), {"evento": "leido", "usuario_id": str(actor.id), "hasta": hasta.isoformat() if hasta else ahora})
    return n


# -------------------------------------------------------------- participantes

async def agregar_participante(db: AsyncSession, actor: Actor, chat: Chat, usuario_id: uuid.UUID, request: Request | None) -> ChatParticipante:
    u = await db.get(Usuario, usuario_id)
    if u is None or u.estado != EstadoRegistro.activo:
        raise no_encontrado("Usuario")
    if not actor.es_superadmin:
        permitidos = PUEDE_AGREGAR[chat.canal].get(actor.rol)
        if permitidos is None:
            raise prohibido(f"Tu rol no agrega participantes al canal {chat.canal.value}")
        if u.rol not in permitidos:
            raise prohibido(f"En el canal {chat.canal.value} no puedes agregar usuarios con rol {u.rol.value}")
        if actor.dominio == Dominio.prestador and actor.prestador_id != chat.prestador_id:
            raise prohibido("El folio es de otro prestador")
        if actor.dominio == Dominio.tenant and actor.tenant_id != chat.tenant_id:
            raise prohibido("El folio es de otro cliente")
    if (u.tenant_id and u.tenant_id != chat.tenant_id) or (u.prestador_id and u.prestador_id != chat.prestador_id):
        raise ErrorAPI(422, "USUARIO_AJENO", "El usuario no pertenece al cliente ni al prestador del folio")
    if chat.canal == CanalChat.campo and u.rol == Rol.operador:
        folio = await db.get(Folio, chat.folio_id)
        misma_un = (await db.execute(select(UsuarioUN.id).where(UsuarioUN.usuario_id == u.id, UsuarioUN.unidad_id == folio.un_id))).first()
        if misma_un is None:
            raise ErrorAPI(422, "USUARIO_AJENO", "Solo operadores de la misma UN pueden entrar al canal de campo")
    p = await _agregar(db, chat, u, actor.id)
    await evento_sistema(db, chat, "participante.agregado", f"{u.nombre} se unió al chat", {"usuario_id": str(u.id), "agregado_por": str(actor.id)})
    await auditoria.registrar_actor(db, actor, "chat.participante_agregado", request, recurso_tipo="chat", recurso_id=chat.id,
                                    tenant_id=chat.tenant_id, prestador_id=chat.prestador_id, despues={"usuario_id": u.id, "canal": chat.canal.value})
    return p


async def quitar_participante(db: AsyncSession, actor: Actor, chat: Chat, usuario_id: uuid.UUID, request: Request | None) -> None:
    p = await participante(db, chat, usuario_id)
    if p is None:
        raise no_encontrado("Participante")
    if not actor.es_superadmin and actor.rol not in PUEDE_AGREGAR[chat.canal]:
        raise prohibido("Tu rol no gestiona participantes de este canal")
    if p.agregado_por is None and not actor.es_superadmin:
        raise ErrorAPI(409, "PARTICIPANTE_FIJO", "Los participantes fijos del canal no se pueden quitar")
    p.activo = False
    await db.flush()
    u = await db.get(Usuario, usuario_id)
    await evento_sistema(db, chat, "participante.quitado", f"{u.nombre if u else 'Un participante'} salió del chat", {"usuario_id": str(usuario_id)})
    await auditoria.registrar_actor(db, actor, "chat.participante_quitado", request, recurso_tipo="chat", recurso_id=chat.id,
                                    tenant_id=chat.tenant_id, prestador_id=chat.prestador_id, despues={"usuario_id": usuario_id})
