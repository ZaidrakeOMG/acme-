"""Notificaciones push PWA (web-push, gratuito). Suscripciones por usuario/dispositivo; con claves VAPID configuradas se
envía con pywebpush en un hilo; sin claves solo se registra en el log y en `notificaciones.ENVIADAS`."""
import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import config
from core.dependencias import Actor
from models.base import Rol
from models.chat import SuscripcionPush
from models.folios import EstadoFolio, Folio
from services import folio_estados, notificaciones
from services.folio_estados import ActorFolio

log = logging.getLogger("acma.push")
TEXTO_ESTADO = {
    EstadoFolio.en_revision: "está en revisión", EstadoFolio.autorizado: "fue autorizado", EstadoFolio.asignado: "tiene técnico asignado",
    EstadoFolio.en_camino: "el técnico va en camino", EstadoFolio.en_ejecucion: "el técnico llegó y está atendiendo",
    EstadoFolio.pendiente_refaccion: "está pendiente de refacción", EstadoFolio.cerrado: "fue cerrado: responde la encuesta",
    EstadoFolio.cancelado: "fue cancelado", EstadoFolio.pendiente_informacion: "necesita más información tuya",
}


def habilitado() -> bool:
    return bool(config.vapid_clave_publica and config.vapid_clave_privada)


async def registrar(db: AsyncSession, actor: Actor, endpoint: str, claves: dict[str, Any], dispositivo_id: str | None, user_agent: str | None) -> SuscripcionPush:
    s = (await db.execute(select(SuscripcionPush).where(SuscripcionPush.usuario_id == actor.id, SuscripcionPush.endpoint == endpoint))).scalar_one_or_none()
    if s is None:
        s = SuscripcionPush(usuario_id=actor.id, tenant_id=actor.tenant_id, prestador_id=actor.prestador_id, endpoint=endpoint)
        db.add(s)
    s.claves_json, s.dispositivo_id, s.user_agent, s.activa = claves, dispositivo_id, (user_agent or "")[:300], True
    await db.flush()
    return s


async def eliminar(db: AsyncSession, actor: Actor, endpoint: str) -> bool:
    s = (await db.execute(select(SuscripcionPush).where(SuscripcionPush.usuario_id == actor.id, SuscripcionPush.endpoint == endpoint))).scalar_one_or_none()
    if s is None:
        return False
    s.activa = False
    await db.flush()
    return True


def _enviar_sync(s: SuscripcionPush, carga: dict[str, Any]) -> bool:
    from pywebpush import WebPushException, webpush

    try:
        webpush(subscription_info={"endpoint": s.endpoint, "keys": s.claves_json}, data=json.dumps(carga),
                vapid_private_key=config.vapid_clave_privada, vapid_claims={"sub": config.vapid_contacto}, ttl=3600)
        return True
    except WebPushException as e:
        estado = getattr(getattr(e, "response", None), "status_code", None)
        log.warning("Push rechazado (%s) para %s", estado, s.endpoint[:60])
        return estado not in (404, 410)  # suscripción desaparecida → desactivar


async def enviar_a_usuarios(db: AsyncSession, usuarios: list[UUID], titulo: str, cuerpo: str = "", datos: dict[str, Any] | None = None) -> int:
    """Las suscripciones son de otros usuarios (RLS "propio"), así que el envío y su marca se hacen en una sesión de sistema,
    independiente de la transacción de la petición."""
    from core.db import nueva_sesion
    from core.rls import CONTEXTO_SISTEMA

    usuarios = [u for u in usuarios if u]
    if not usuarios:
        return 0
    notificaciones.enviar(usuarios=usuarios, titulo=titulo, cuerpo=cuerpo, datos=datos or {}, canales=["push"])
    carga = {"titulo": titulo, "cuerpo": cuerpo, "datos": datos or {}}
    enviados = 0
    async with nueva_sesion(CONTEXTO_SISTEMA) as sistema:
        suscripciones = (await sistema.execute(select(SuscripcionPush).where(
            SuscripcionPush.usuario_id.in_(usuarios), SuscripcionPush.activa.is_(True)))).scalars().all()
        for s in suscripciones:
            if not habilitado():
                log.info("Push (sin VAPID, solo log) → %s: %s", s.endpoint[:60], titulo)
                ok = True
            else:
                ok = await asyncio.to_thread(_enviar_sync, s, carga)
            if ok:
                s.ultimo_envio_at = datetime.now(UTC)
                enviados += 1
            else:
                s.activa = False
        await sistema.commit()
    return enviados


@folio_estados.suscribir
async def _push_por_transicion(db: AsyncSession, folio: Folio, anterior: EstadoFolio, nuevo: EstadoFolio, actor: ActorFolio, contexto: dict) -> None:
    """§5.1: el operador recibe notificaciones de cambios de estado; el técnico, de su asignación/cancelación."""
    texto = TEXTO_ESTADO.get(nuevo)
    if not texto:
        return
    destinatarios = [folio.capturado_por]
    if nuevo in (EstadoFolio.asignado, EstadoFolio.cancelado, EstadoFolio.autorizado) and folio.tecnico_id:
        destinatarios.append(folio.tecnico_id)
    if isinstance(actor, Actor) and actor.rol in (Rol.operador, Rol.tecnico):
        destinatarios = [d for d in destinatarios if d != actor.id]  # quien ejecuta la acción no se notifica a sí mismo
    await enviar_a_usuarios(db, destinatarios, f"Folio {folio.numero_folio} {texto}",
                            datos={"folio_id": str(folio.id), "estado": nuevo.value, "url": f"/campo/folio/{folio.id}"})
