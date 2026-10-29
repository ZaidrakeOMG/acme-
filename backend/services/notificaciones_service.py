"""Notificaciones multicanal (§6.1, P07): un único punto de entrada `notificar()` que resuelve el canal por evento y por
preferencia del usuario, encola cada envío en `notificaciones` y lo despacha en Celery (o en línea en pruebas).

Canales de Fase 1: `app` (bandeja interna), `push` (web-push de P05) y `email` (SMTP de `services/correo.py`).
`whatsapp` y `sms` quedan registrados como `omitida` con motivo «canal Fase 2». La bitácora `services/notificaciones.ENVIADAS`
de P04–P06 se conserva por compatibilidad."""
import logging
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import config
from models.base import EstadoRegistro, Rol
from models.minutas import CanalNotificacion, EstadoNotificacion, Notificacion, NotificacionPreferencia
from models.organizaciones import Prestador
from models.unidades import UsuarioUN
from models.usuarios import Usuario
from services import correo, notificaciones, push_service

log = logging.getLogger("acma.notificaciones")

FASE_2 = {CanalNotificacion.whatsapp, CanalNotificacion.sms}
CANALES_POR_DEFECTO: list[str] = ["app", "push", "email"]
# Canales por evento cuando el usuario no tiene preferencia (los demás eventos usan los tres de Fase 1).
CANALES_POR_EVENTO: dict[str, list[str]] = {
    "folio.estado": ["app", "push"],
    "chat.mensaje": ["app", "push"],
    "minuta.enviada": ["app", "push", "email"],
    "minuta.pendiente_validacion": ["app", "push"],
    "calendario.publicado": ["app", "push", "email"],
    "trabajo_especial.enviado": ["app", "push", "email"],
    "trabajo_especial.programado": ["app", "push", "email"],
    "oc_activo.pendiente": ["app", "push", "email"],
}
EVENTOS: dict[str, str] = {
    "minuta.enviada": "Minuta del día enviada",
    "minuta.pendiente_validacion": "Minuta pendiente de validación",
    "minuta.respondida": "Minuta respondida por el Admin UN",
    "minuta.vencida": "Minuta vencida sin respuesta",
    "hallazgo.respuesta": "Respuesta a un hallazgo",
    "cotizacion.solicitada": "Cotización solicitada",
    "cotizacion.enviada": "Cotización enviada al cliente",
    "cotizacion.respondida": "Cotización autorizada o rechazada",
    "seguimiento.cambio_estado": "Cambio de estado en un módulo de seguimiento",
    "seguimiento.escalada": "Reprogramación escalada al Admin empresa",
    "presupuesto.recordatorio": "Recordatorio de hallazgos diferidos por presupuesto",
    "clasificacion.pendiente": "Folio no crítico por clasificar",
    "clasificacion.incumplimiento": "Incumplimiento de clasificación del Admin UN",
    "calificacion.bajo_desempeno": "Calificación del Admin UN bajo el umbral",
    "aprobacion.pendiente": "Folio pendiente de tu autorización",
    "aprobacion.bloqueada": "Aprobación bloqueada por tiempo límite",
    "folio.estado": "Cambio de estado del folio",
    "folio.espera": "Folio en espera de confirmación",
    "folio.revision": "Folio en revisión manual",
    "calendario.publicado": "Calendario de preventivos publicado",
    "autorizacion.solicitada": "Autorización de preventivo solicitada",
    "autorizacion.resuelta": "Autorización de preventivo resuelta",
    "trabajo_especial.urgencia": "Trabajo especial de urgencia creado por el cliente",
    "trabajo_especial.enviado": "Trabajo especial enviado para tu validación",
    "trabajo_especial.aceptado": "Trabajo especial aceptado por el cliente",
    "trabajo_especial.rechazado": "Trabajo especial rechazado por el cliente",
    "trabajo_especial.programado": "Trabajo especial programado (fecha confirmada)",
    "trabajo_especial.cerrado": "Trabajo especial terminado",
    "trabajo_especial.cancelado": "Trabajo especial cancelado",
    "oc_activo.pendiente": "Folio de instalación de activo pendiente de OC",
    "oc_activo.autorizada": "OC de activo autorizada: folio listo para asignar",
    "oc_activo.rechazada": "OC de activo rechazada",
    "oc_activo.equipo_incompleto": "Equipo instalado con ficha incompleta",
    "alerta": "Alerta del sistema",
}


async def destinatarios_por_rol(db: AsyncSession, roles: Iterable[str | Rol], *, tenant_id: UUID | None = None, prestador_id: UUID | None = None,
                                un_id: UUID | None = None) -> list[UUID]:
    """Usuarios activos de esos roles en el tenant/prestador; para admin_un, los de la UN si se indica."""
    claves = {Rol(r) if isinstance(r, str) else r for r in roles}
    if not claves:
        return []
    consulta = select(Usuario.id, Usuario.rol).where(Usuario.rol.in_(claves), Usuario.estado == EstadoRegistro.activo)
    condiciones = []
    if tenant_id:
        condiciones.append(Usuario.tenant_id == tenant_id)
    if prestador_id:
        condiciones.append(Usuario.prestador_id == prestador_id)
    if condiciones:
        from sqlalchemy import or_

        consulta = consulta.where(or_(*condiciones))
    filas = (await db.execute(consulta)).all()
    if un_id and Rol.admin_un in claves:
        en_un = set((await db.execute(select(UsuarioUN.usuario_id).where(UsuarioUN.unidad_id == un_id))).scalars())
        filas = [f for f in filas if f.rol != Rol.admin_un or f.id in en_un]
    return [f.id for f in filas]


async def canales_de(db: AsyncSession, usuario_id: UUID, evento: str) -> list[str]:
    pref = (await db.execute(select(NotificacionPreferencia.canales_json).where(NotificacionPreferencia.usuario_id == usuario_id,
                                                                                 NotificacionPreferencia.evento == evento))).scalar()
    if pref is None:
        pref = (await db.execute(select(NotificacionPreferencia.canales_json).where(NotificacionPreferencia.usuario_id == usuario_id,
                                                                                     NotificacionPreferencia.evento == "*"))).scalar()
    if pref is not None:
        return [c for c in pref if c in CanalNotificacion.__members__]
    return list(CANALES_POR_EVENTO.get(evento, CANALES_POR_DEFECTO))


async def notificar(db: AsyncSession, evento: str, destinatarios: Iterable[UUID], datos: dict[str, Any] | None = None, *, asunto: str,
                    cuerpo: str = "", url: str | None = None, tenant_id: UUID | None = None, prestador_id: UUID | None = None,
                    canales: Iterable[str] | None = None, adjuntos: list[dict[str, Any]] | None = None, plantilla: str | None = None,
                    enviar_ahora: bool | None = None) -> list[Notificacion]:
    """Encola una notificación por destinatario y canal. `canales` fuerza los canales (p. ej. la minuta siempre va por email);
    si no, se usan las preferencias del usuario. `adjuntos`: [{nombre, clave_almacenamiento | contenido_base64, mime}] solo para email."""
    datos = dict(datos or {})
    ids = list(dict.fromkeys(destinatarios))
    creadas: list[Notificacion] = []
    ahora = datetime.now(UTC)
    for uid in ids:
        lista = [str(c) for c in canales] if canales is not None else await canales_de(db, uid, evento)
        for canal_txt in lista:
            canal = CanalNotificacion(canal_txt)
            n = Notificacion(id=uuid.uuid4(), usuario_id=uid, tenant_id=tenant_id, prestador_id=prestador_id, evento=evento, canal=canal, asunto=asunto[:300],
                             cuerpo_json={"cuerpo": cuerpo, "datos": datos, "adjuntos": adjuntos or [], "plantilla": plantilla}, url=url, timestamp=ahora)
            if canal in FASE_2:
                n.estado, n.proveedor_respuesta = EstadoNotificacion.omitida, "canal Fase 2"
            elif canal == CanalNotificacion.app:
                n.estado, n.enviada_at = EstadoNotificacion.enviada, ahora  # la bandeja interna es inmediata
            db.add(n)
            creadas.append(n)
    await db.flush()
    # Compatibilidad con P04–P06 (pruebas y log).
    notificaciones.enviar(usuarios=ids, tenant_id=tenant_id, prestador_id=prestador_id, titulo=asunto, cuerpo=cuerpo, datos={"evento": evento, **datos},
                          canales=sorted({c.canal.value for c in creadas}) or ["app"])
    pendientes = [n for n in creadas if n.estado == EstadoNotificacion.pendiente]
    if pendientes:
        inline = config.notificaciones_envio_inline if enviar_ahora is None else enviar_ahora
        if inline:
            await procesar(db, [n.id for n in pendientes])
        else:
            _encolar_celery([str(n.id) for n in pendientes])
    return creadas


def _encolar_celery(ids: list[str]) -> None:
    try:
        from workers.tareas.notificaciones import enviar_notificaciones

        enviar_notificaciones.delay(ids)
    except Exception as e:  # noqa: BLE001 — sin broker (desarrollo) queda pendiente para la tarea periódica
        log.info("Notificaciones encoladas para la tarea periódica (sin broker: %s)", e)


# ----------------------------------------------------------------- envío

async def procesar(db: AsyncSession, ids: list[UUID] | None = None, limite: int = 200) -> dict[str, int]:
    """Envía las notificaciones pendientes (push y email). Idempotente: solo toma las que siguen `pendiente`."""
    consulta = select(Notificacion).where(Notificacion.estado == EstadoNotificacion.pendiente).order_by(Notificacion.timestamp).limit(limite)
    if ids:
        consulta = consulta.where(Notificacion.id.in_(ids))
    filas = (await db.execute(consulta)).scalars().all()
    resumen = {"enviadas": 0, "fallidas": 0, "omitidas": 0}
    por_usuario: dict[UUID, Usuario | None] = {}
    for n in filas:
        if n.usuario_id not in por_usuario:
            por_usuario[n.usuario_id] = await db.get(Usuario, n.usuario_id)
        u = por_usuario[n.usuario_id]
        if u is None or u.estado != EstadoRegistro.activo:
            await _marcar(db, n, EstadoNotificacion.omitida, "usuario inactivo")
            resumen["omitidas"] += 1
            continue
        try:
            if n.canal == CanalNotificacion.email:
                estado, detalle = await _enviar_email(db, n, u)
            elif n.canal == CanalNotificacion.push:
                enviados = await push_service.enviar_a_usuarios(db, [u.id], n.asunto, n.cuerpo_json.get("cuerpo", ""), {"url": n.url or "/", **n.cuerpo_json.get("datos", {})})
                estado, detalle = ("enviada", f"push:{enviados}") if enviados else ("omitida", "sin suscripción push")
            else:
                estado, detalle = "enviada", ""
        except Exception as e:  # noqa: BLE001
            log.exception("Fallo al enviar la notificación %s", n.id)
            estado, detalle = "fallida", str(e)[:500]
        await _marcar(db, n, EstadoNotificacion(estado), detalle)
        resumen["enviadas" if estado == "enviada" else "fallidas" if estado == "fallida" else "omitidas"] += 1
    await db.flush()
    return resumen


async def _marcar(db: AsyncSession, n: Notificacion, estado: EstadoNotificacion, detalle: str) -> None:
    await db.execute(update(Notificacion).where(Notificacion.id == n.id).values(estado=estado, proveedor_respuesta=detalle[:2000],
                                                                                 enviada_at=datetime.now(UTC) if estado == EstadoNotificacion.enviada else None))
    n.estado, n.proveedor_respuesta = estado, detalle[:2000]


async def _enviar_email(db: AsyncSession, n: Notificacion, u: Usuario) -> tuple[str, str]:
    prestador = await db.get(Prestador, n.prestador_id) if n.prestador_id else None
    marca = {"prestador": prestador.razon_social if prestador else "ACMA", "color_primario": prestador.color_primario if prestador else "#1C3D8F",
             "color_acento": prestador.color_acento if prestador else "#A2C62B"}
    cuerpo = n.cuerpo_json
    base_url = config.app_url_publica.rstrip("/")
    url = f"{base_url}{n.url}" if n.url and n.url.startswith("/") else (n.url or base_url)
    if cuerpo.get("plantilla") and cuerpo.get("datos", {}).get("html_valores"):
        html = correo.plantilla(cuerpo["plantilla"], **{"titulo": n.asunto, "url": url, **marca, **cuerpo["datos"]["html_valores"]})
    else:
        detalle = cuerpo.get("datos", {}).get("detalle_html", "")
        html = correo.plantilla("generico", titulo=n.asunto, cuerpo=cuerpo.get("cuerpo", ""), detalle_html=detalle, url=url,
                                texto_boton=cuerpo.get("datos", {}).get("texto_boton", "Abrir en ACMA"), **marca)
    adjuntos = []
    for a in cuerpo.get("adjuntos", []):
        try:
            from services.almacenamiento import obtener_almacenamiento

            contenido = obtener_almacenamiento().leer(a["clave"]) if a.get("clave") else b""
            if contenido:
                adjuntos.append(correo.Adjunto(nombre=a.get("nombre", "adjunto.pdf"), contenido=contenido, mime=a.get("mime", "application/pdf")))
        except Exception as e:  # noqa: BLE001
            log.warning("Adjunto %s no disponible: %s", a, e)
    return await correo.enviar(correo.Correo(destinatarios=[u.email], asunto=n.asunto, html=html, adjuntos=adjuntos))


# ---------------------------------------------------------------- bandeja

async def bandeja(db: AsyncSession, usuario_id: UUID, solo_no_leidas: bool, limite: int) -> list[Notificacion]:
    consulta = select(Notificacion).where(Notificacion.usuario_id == usuario_id, Notificacion.canal == CanalNotificacion.app).order_by(Notificacion.timestamp.desc()).limit(limite)
    if solo_no_leidas:
        consulta = consulta.where(Notificacion.leida_at.is_(None))
    return list((await db.execute(consulta)).scalars())


async def no_leidas(db: AsyncSession, usuario_id: UUID) -> int:
    from sqlalchemy import func

    return (await db.execute(select(func.count()).select_from(Notificacion).where(Notificacion.usuario_id == usuario_id, Notificacion.canal == CanalNotificacion.app,
                                                                                   Notificacion.leida_at.is_(None)))).scalar() or 0


async def marcar_leidas(db: AsyncSession, usuario_id: UUID, ids: list[UUID] | None) -> int:
    consulta = update(Notificacion).where(Notificacion.usuario_id == usuario_id, Notificacion.canal == CanalNotificacion.app, Notificacion.leida_at.is_(None))
    if ids:
        consulta = consulta.where(Notificacion.id.in_(ids))
    r = await db.execute(consulta.values(leida_at=datetime.now(UTC)))
    return r.rowcount or 0


async def preferencias(db: AsyncSession, usuario_id: UUID) -> list[NotificacionPreferencia]:
    return list((await db.execute(select(NotificacionPreferencia).where(NotificacionPreferencia.usuario_id == usuario_id).order_by(NotificacionPreferencia.evento))).scalars())


async def guardar_preferencia(db: AsyncSession, usuario: Usuario, evento: str, canales: list[str]) -> NotificacionPreferencia:
    if evento != "*" and evento not in EVENTOS:
        from core.errors import ErrorAPI

        raise ErrorAPI(422, "EVENTO_DESCONOCIDO", f"Evento {evento} no existe; usa uno del catálogo o '*'")
    validos = [c for c in canales if c in CanalNotificacion.__members__]
    p = (await db.execute(select(NotificacionPreferencia).where(NotificacionPreferencia.usuario_id == usuario.id, NotificacionPreferencia.evento == evento))).scalar_one_or_none()
    if p is None:
        p = NotificacionPreferencia(usuario_id=usuario.id, tenant_id=usuario.tenant_id, prestador_id=usuario.prestador_id, evento=evento, canales_json=validos)
        db.add(p)
    else:
        p.canales_json = validos
    await db.flush()
    return p
