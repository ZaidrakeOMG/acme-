"""Bandeja de notificaciones y preferencias por evento (§6.1). P07."""
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select

from core.dependencias import DB, Actor, ActorActual, requiere_rol
from models.base import Rol
from models.usuarios import Usuario
from schemas.comun import RESPUESTAS_ERROR
from schemas.minutas import MarcarLeidasEntrada, NotificacionSalida, PreferenciaEntrada, PreferenciaSalida
from services import auditoria, notificaciones_service

router = APIRouter(prefix="/api/notificaciones", tags=["Notificaciones"], responses=RESPUESTAS_ERROR)


def _salida(n) -> NotificacionSalida:
    return NotificacionSalida(id=n.id, evento=n.evento, canal=n.canal, asunto=n.asunto, cuerpo=n.cuerpo_json.get("cuerpo", ""), datos=n.cuerpo_json.get("datos", {}),
                              estado=n.estado, timestamp=n.timestamp, leida_at=n.leida_at, url=n.url)


@router.get("", response_model=list[NotificacionSalida], summary="Bandeja interna (canal app)")
async def bandeja(db: DB, actor: ActorActual, solo_no_leidas: bool = False, limite: int = Query(default=50, ge=1, le=200)):
    return [_salida(n) for n in await notificaciones_service.bandeja(db, actor.id, solo_no_leidas, limite)]


@router.get("/no-leidas", summary="Conteo de no leídas (campana)")
async def no_leidas(db: DB, actor: ActorActual) -> dict:
    return {"no_leidas": await notificaciones_service.no_leidas(db, actor.id)}


@router.post("/leidas", summary="Marcar como leídas (todas o por ids)")
async def marcar(datos: MarcarLeidasEntrada, db: DB, actor: ActorActual) -> dict:
    n = await notificaciones_service.marcar_leidas(db, actor.id, datos.ids)
    await db.commit()
    return {"marcadas": n}


@router.get("/eventos", summary="Catálogo de eventos notificables y canales disponibles",
            description="Desde F2-02 WhatsApp y SMS son canales normales: `disponible` dice si el prestador o el "
                        "tenant los tiene activos, y `requiere_telefono`, que hace falta verificar el número.")
async def eventos(db: DB, actor: ActorActual) -> dict:
    from services import mensajeria_service
    from services.mensajeria.plantillas import CATALOGO

    cfg = await mensajeria_service.configuracion(db, actor.prestador_id, actor.tenant_id)
    if cfg is None and actor.tenant_id:
        from models.organizaciones import TenantPrestador

        for prestador_id in (await db.execute(select(TenantPrestador.prestador_id).where(
                TenantPrestador.tenant_id == actor.tenant_id))).scalars():
            cfg = await mensajeria_service.configuracion(db, prestador_id, actor.tenant_id)
            if cfg is not None:
                break
    plantillas = {p.evento for p in CATALOGO}
    return {"eventos": [{"clave": k, "nombre": v,
                         "canales_default": notificaciones_service.CANALES_POR_EVENTO.get(k, notificaciones_service.CANALES_POR_DEFECTO),
                         "tiene_plantilla": k in plantillas}
                        for k, v in notificaciones_service.EVENTOS.items()],
            "canales": [{"clave": "app", "nombre": "Bandeja en la app", "disponible": True},
                        {"clave": "push", "nombre": "Push", "disponible": True},
                        {"clave": "email", "nombre": "Correo", "disponible": True},
                        {"clave": "whatsapp", "nombre": "WhatsApp", "requiere_telefono": True,
                         "disponible": bool(cfg and cfg.whatsapp_activo),
                         "modo": mensajeria_service.proveedores.modo_de_canal("whatsapp")},
                        {"clave": "sms", "nombre": "SMS", "requiere_telefono": True,
                         "disponible": bool(cfg and cfg.sms_activo),
                         "modo": mensajeria_service.proveedores.modo_de_canal("sms")}]}


@router.get("/preferencias", response_model=list[PreferenciaSalida], summary="Mis preferencias por evento ('*' = todos)")
async def preferencias(db: DB, actor: ActorActual):
    return [PreferenciaSalida(evento=p.evento, canales=p.canales_json) for p in await notificaciones_service.preferencias(db, actor.id)]


@router.put("/preferencias", response_model=PreferenciaSalida, summary="Guardar preferencia de canales para un evento")
async def guardar_preferencia(datos: PreferenciaEntrada, request: Request, db: DB, actor: ActorActual):
    u = await db.get(Usuario, actor.id)
    p = await notificaciones_service.guardar_preferencia(db, u, datos.evento, [c.value for c in datos.canales])
    await auditoria.registrar_actor(db, actor, "notificaciones.preferencia", request, recurso_tipo="notificacion_preferencia", recurso_id=p.id,
                                    despues={"evento": datos.evento, "canales": p.canales_json})
    await db.commit()
    return PreferenciaSalida(evento=p.evento, canales=p.canales_json)


@router.post("/procesar", summary="Enviar ahora las pendientes (operación / pruebas)")
async def procesar(db: DB, actor: Actor = Depends(requiere_rol(Rol.superadmin, Rol.admin_prestador))) -> dict:
    r = await notificaciones_service.procesar(db)
    await db.commit()
    return r
