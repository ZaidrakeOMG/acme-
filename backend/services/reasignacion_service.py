"""Reasignación forzada por el despachador (§6.8.2): candidatos con habilidad, carga del día y advertencia de refacción;
restricciones literales; transición reasignado → asignado; registro histórico y reporte de causas. La reasignación
automática por algoritmo y el recálculo VRPTW son Fase 2."""
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.dependencias import Actor
from core.errors import ErrorAPI, no_encontrado, prohibido
from models.base import Dominio, EstadoRegistro, Rol
from models.catalogos import EstadoActivo, Tecnico
from models.chat import CanalChat, ChatParticipante
from models.folios import EstadoFolio, Folio
from models.preventivos import RAZONES_REASIGNACION, RazonReasignacion, Reasignacion, ReasignacionValidacion, TipoReasignacion
from models.usuarios import Usuario
from services import auditoria, chat_service, folio_estados, permisos_service, push_service
from services import folios_captura_service as captura
from services.folio_estados import ACTOR_SISTEMA

REASIGNAN = {Rol.superadmin, Rol.despachador, Rol.admin_prestador}
ESTADOS_REASIGNABLES = {EstadoFolio.asignado, EstadoFolio.pendiente_refaccion, EstadoFolio.en_camino}
ACTIVOS = [EstadoFolio.asignado, EstadoFolio.reasignado, EstadoFolio.en_camino, EstadoFolio.en_ejecucion, EstadoFolio.pendiente_refaccion]


async def sembrar_razones(db: AsyncSession, prestador_id: UUID) -> int:
    existentes = {r.descripcion for r in (await db.execute(select(RazonReasignacion).where(RazonReasignacion.prestador_id == prestador_id))).scalars()}
    n = 0
    for i, (desc, detalle) in enumerate(RAZONES_REASIGNACION, start=1):
        if desc not in existentes:
            db.add(RazonReasignacion(prestador_id=prestador_id, descripcion=desc, detalle=detalle, orden_display=i))
            n += 1
    await db.flush()
    return n


async def razones(db: AsyncSession, prestador_id: UUID, solo_activas: bool = True) -> list[RazonReasignacion]:
    consulta = select(RazonReasignacion).where(RazonReasignacion.prestador_id == prestador_id).order_by(RazonReasignacion.orden_display)
    if solo_activas:
        consulta = consulta.where(RazonReasignacion.activa.is_(True))
    return list((await db.execute(consulta)).scalars())


async def candidatos(db: AsyncSession, actor: Actor, folio: Folio) -> list[dict[str, Any]]:
    if actor.rol not in REASIGNAN and actor.rol != Rol.mesa_control:
        raise prohibido("Solo el despachador consulta candidatos de reasignación")
    hoy = date.today()
    filas = (await db.execute(select(Tecnico, Usuario).join(Usuario, Usuario.id == Tecnico.usuario_id).where(
        Tecnico.prestador_id == folio.prestador_id, Tecnico.estado == EstadoActivo.activo, Usuario.estado == EstadoRegistro.activo).order_by(Usuario.nombre))).all()
    cargas = dict((await db.execute(select(Folio.tecnico_id, func.count()).where(Folio.prestador_id == folio.prestador_id, Folio.estado.in_(ACTIVOS),
                                                                                  Folio.tecnico_id.is_not(None)).group_by(Folio.tecnico_id))).all())
    salida = []
    for t, u in filas:
        _, tiene, requerida = await captura.tecnico_con_habilidad(db, u.id, folio)
        advertencias = []
        if not tiene:
            advertencias.append(f"Sin la habilidad requerida ({requerida})")
        advertencias.append("Refacción no verificada: el inventario del vehículo llega en P09")
        salida.append({"usuario_id": u.id, "tecnico_id": t.id, "nombre": u.nombre, "vehiculo_placas": t.vehiculo_placas, "habilidad_ok": tiene,
                       "habilidad_requerida": requerida, "carga_dia": cargas.get(u.id, 0), "refaccion_ok": None, "es_actual": u.id == folio.tecnico_id,
                       "advertencias": advertencias, "fecha": hoy.isoformat()})
    return salida


async def reasignar(db: AsyncSession, actor: Actor, folio: Folio, tecnico_destino_id: UUID, razon_id: UUID, comentario: str, confirmar_advertencias: bool,
                    razon_sin_habilidad: str | None, request: Request | None) -> Reasignacion:
    if actor.rol not in REASIGNAN:
        raise prohibido("Solo el Despachador o el Admin prestador reasignan folios")
    if actor.dominio == Dominio.prestador and folio.prestador_id != actor.prestador_id:
        raise no_encontrado("Folio")
    if folio.estado == EstadoFolio.en_ejecucion:
        raise ErrorAPI(409, "REASIGNACION_NO_PERMITIDA", "No se puede reasignar un folio en ejecución: el técnico ya está en la unidad")
    if folio.estado not in ESTADOS_REASIGNABLES:
        raise ErrorAPI(409, "REASIGNACION_NO_PERMITIDA", f"El folio está en {folio.estado.value}; solo se reasignan folios asignados, en camino o pendientes de refacción")
    if tecnico_destino_id == folio.tecnico_id:
        raise ErrorAPI(422, "MISMO_TECNICO", "El técnico destino es el mismo que el actual")
    razon = await db.get(RazonReasignacion, razon_id)
    if razon is None or razon.prestador_id != folio.prestador_id or not razon.activa:
        raise ErrorAPI(422, "RAZON_INVALIDA", "Elige una razón de reasignación del catálogo del prestador")
    usuario, tiene, requerida = await captura.tecnico_con_habilidad(db, tecnico_destino_id, folio)
    advertencias: list[str] = []
    if not tiene:
        permitido = actor.es_superadmin or actor.rol == Rol.admin_prestador
        if actor.rol == Rol.despachador:
            permisos = await permisos_service.efectivos_despachador(db, actor.prestador_id, actor.id, folio.tenant_id)
            permitido = any(p["clave"] == "asignar_tecnico_sin_habilidad" and p["habilitado"] for p in permisos)
        if not permitido:
            raise ErrorAPI(403, "TECNICO_SIN_HABILIDAD", f"{usuario.nombre} no tiene la habilidad certificada requerida ({requerida}): restricción dura",
                           [{"habilidad_requerida": requerida}])
        if not (razon_sin_habilidad or "").strip():
            raise ErrorAPI(422, "RAZON_REQUERIDA", "Reasignar sin la habilidad requerida exige razón")
        advertencias.append(f"Asignado sin la habilidad {requerida} (permiso del despachador)")
    refaccion_ok = None  # P09: inventario del vehículo
    advertencias.append("Refacción no verificada (inventario del vehículo en P09)")
    if advertencias and not confirmar_advertencias:
        raise ErrorAPI(409, "CONFIRMACION_REQUERIDA", "Hay advertencias; confirma explícitamente la reasignación", advertencias)
    origen_id = folio.tecnico_id
    origen = await db.get(Usuario, origen_id) if origen_id else None
    contexto = {"tecnico_origen_id": str(origen_id) if origen_id else None, "tecnico_destino_id": str(usuario.id), "razon": razon.descripcion, "comentario": comentario}
    if folio.estado == EstadoFolio.en_camino:
        # En camino no tiene transición directa a reasignado en §6.8.6: se regresa a asignado como estado intermedio del sistema.
        raise ErrorAPI(409, "REASIGNACION_NO_PERMITIDA", "Un folio en camino no se reasigna hasta que el técnico regrese a asignado o llegue (en ejecución)")
    await folio_estados.transicionar(db, folio, EstadoFolio.reasignado, actor if actor.rol == Rol.despachador else ACTOR_SISTEMA, f"Reasignación forzada: {razon.descripcion}", contexto, request)
    tecnico = (await db.execute(select(Tecnico).where(Tecnico.usuario_id == usuario.id))).scalar_one_or_none()
    await folio_estados.transicionar(db, folio, EstadoFolio.asignado, actor if actor.rol == Rol.despachador else ACTOR_SISTEMA, f"Asignado a {usuario.nombre}",
                                     {"tecnico_id": str(usuario.id), "tecnico_nombre": usuario.nombre, "sin_habilidad": not tiene, "razon": razon_sin_habilidad,
                                      "vehiculo": tecnico.vehiculo_placas if tecnico else None, "reasignacion": True}, request)
    r = Reasignacion(folio_id=folio.id, prestador_id=folio.prestador_id, tenant_id=folio.tenant_id, tecnico_origen_id=origen_id, tecnico_destino_id=usuario.id,
                     tipo=TipoReasignacion.forzada, razon_id=razon.id, comentario=(comentario or "").strip(), despachador_id=actor.id, timestamp=datetime.now(UTC))
    db.add(r)
    await db.flush()
    db.add(ReasignacionValidacion(reasignacion_id=r.id, prestador_id=folio.prestador_id, tenant_id=folio.tenant_id, habilidad_ok=tiene, refaccion_ok=refaccion_ok,
                                  advertencias_json=advertencias))
    # Chat: el técnico origen sale del canal de campo (el destino entró con la transición a asignado) y queda el evento.
    chats = await chat_service.chats_del_folio(db, folio.id)
    texto = f"Folio reasignado de {origen.nombre if origen else 'sin técnico'} a {usuario.nombre}: {razon.descripcion}"
    if CanalChat.campo in chats and origen_id:
        p = (await db.execute(select(ChatParticipante).where(ChatParticipante.chat_id == chats[CanalChat.campo].id, ChatParticipante.usuario_id == origen_id))).scalar_one_or_none()
        if p is not None:
            p.activo = False
    for canal in (CanalChat.campo, CanalChat.operativo):
        if canal in chats:
            await chat_service.evento_sistema(db, chats[canal], "folio.reasignado", texto, {"reasignacion_id": str(r.id), "tecnico_origen_id": contexto["tecnico_origen_id"],
                                                                                            "tecnico_destino_id": str(usuario.id)})
    await push_service.enviar_a_usuarios(db, [x for x in (origen_id, usuario.id) if x], f"Folio {folio.numero_folio} reasignado", texto, {"url": f"/campo/folio/{folio.id}"})
    await auditoria.registrar_actor(db, actor, "folio.reasignacion_forzada", request, recurso_tipo="folio", recurso_id=folio.id, tenant_id=folio.tenant_id,
                                    prestador_id=folio.prestador_id, antes={"tecnico_id": origen_id}, despues={"tecnico_id": usuario.id, "razon": razon.descripcion, "advertencias": advertencias})
    await db.flush()
    return r


async def historial_folio(db: AsyncSession, folio_id: UUID) -> list[dict[str, Any]]:
    filas = (await db.execute(select(Reasignacion).where(Reasignacion.folio_id == folio_id).order_by(Reasignacion.timestamp))).scalars().all()
    if not filas:
        return []
    ids = {x for r in filas for x in (r.tecnico_origen_id, r.tecnico_destino_id, r.despachador_id) if x}
    nombres = {u.id: u.nombre for u in (await db.execute(select(Usuario).where(Usuario.id.in_(ids)))).scalars()}
    razones_ = {z.id: z.descripcion for z in (await db.execute(select(RazonReasignacion).where(RazonReasignacion.id.in_({r.razon_id for r in filas if r.razon_id})))).scalars()}
    return [{"id": r.id, "tecnico_origen_id": r.tecnico_origen_id, "tecnico_origen_nombre": nombres.get(r.tecnico_origen_id), "tecnico_destino_id": r.tecnico_destino_id,
             "tecnico_destino_nombre": nombres.get(r.tecnico_destino_id), "tipo": r.tipo, "razon": razones_.get(r.razon_id), "comentario": r.comentario,
             "despachador_id": r.despachador_id, "despachador_nombre": nombres.get(r.despachador_id), "timestamp": r.timestamp} for r in filas]


async def reporte(db: AsyncSession, actor: Actor, desde: date | None, hasta: date | None, tenant_id: UUID | None) -> dict[str, Any]:
    consulta = select(Reasignacion)
    if actor.dominio == Dominio.prestador:
        consulta = consulta.where(Reasignacion.prestador_id == actor.prestador_id)
    elif actor.dominio == Dominio.tenant:
        consulta = consulta.where(Reasignacion.tenant_id == actor.tenant_id)
    if tenant_id:
        consulta = consulta.where(Reasignacion.tenant_id == tenant_id)
    if desde:
        consulta = consulta.where(Reasignacion.timestamp >= datetime.combine(desde, datetime.min.time(), tzinfo=UTC))
    if hasta:
        consulta = consulta.where(Reasignacion.timestamp < datetime.combine(hasta, datetime.max.time(), tzinfo=UTC))
    filas = (await db.execute(consulta)).scalars().all()
    total = len(filas)
    razones_ = {z.id: z.descripcion for z in (await db.execute(select(RazonReasignacion).where(RazonReasignacion.id.in_({r.razon_id for r in filas if r.razon_id})))).scalars()} if filas else {}
    ids = {x for r in filas for x in (r.tecnico_origen_id, r.tecnico_destino_id) if x}
    nombres = {u.id: u.nombre for u in (await db.execute(select(Usuario).where(Usuario.id.in_(ids)))).scalars()} if ids else {}

    def agrupar(clave):
        conteo: dict[str, int] = {}
        for r in filas:
            k = clave(r)
            conteo[k] = conteo.get(k, 0) + 1
        return [{"nombre": k, "total": v, "porcentaje": round(v * 100 / total, 1) if total else 0} for k, v in sorted(conteo.items(), key=lambda x: -x[1])]

    return {"desde": desde, "hasta": hasta, "total": total,
            "por_razon": agrupar(lambda r: razones_.get(r.razon_id, "Sin razón")),
            "por_tecnico_origen": agrupar(lambda r: nombres.get(r.tecnico_origen_id, "Sin técnico")),
            "por_tecnico_destino": agrupar(lambda r: nombres.get(r.tecnico_destino_id, "—")),
            "por_tipo": agrupar(lambda r: r.tipo.value)}
