"""Motor de estados del folio (§6.8.6). Única puerta de cambio de `folios.estado`: `transicionar()`.

La tabla TRANSICIONES es literal de §6.8.6: estado origen → {estado destino: roles que pueden ejecutarla}. El actor
`sistema` (validaciones automáticas, flujo de aprobación, Celery) aparece como rol "sistema". P05, P06 y P10 deben
llamar a `transicionar()`; ninguna escritura directa al campo `estado`.
"""
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.dependencias import Actor
from core.errors import ErrorAPI
from models.base import Rol
from models.folios import (
    EstadoFolio, Folio, FolioEstadoHistorial, FolioEvidencia, FolioFormularioAtencion, TipoEvidenciaFolio,
)
from services import auditoria

SISTEMA = "sistema"
E = EstadoFolio
R = Rol

# Roles que cancelan en cualquier estado no final (§6.8.6 "Cancelado: Despachador, Admin prestador, Admin empresa").
CANCELAN = {R.despachador, R.admin_prestador, R.admin_empresa}
# Quienes pueden capturar y, por tanto, responder a "Pendiente de información" (el documento dice "Operador (responde)").
RESPONDEN = {R.operador, R.admin_un, R.supervisor_operadores, R.admin_empresa, R.mesa_control}

TRANSICIONES: dict[EstadoFolio, dict[EstadoFolio, set[str]]] = {
    E.capturado: {
        E.en_revision: {SISTEMA},                      # validación automática no resoluble o flujo multinivel
        E.autorizado: {SISTEMA},                       # validaciones OK sin flujo de aprobación / auto-aprobación
        E.cancelado: CANCELAN | {SISTEMA},
    },
    E.en_revision: {
        E.autorizado: {R.despachador, R.admin_prestador, SISTEMA},
        E.pendiente_informacion: {R.despachador, R.admin_prestador},
        E.cancelado: CANCELAN | {SISTEMA},             # sistema: rechazo del flujo de aprobación
    },
    E.pendiente_informacion: {
        E.en_revision: RESPONDEN,
        E.cancelado: CANCELAN,
    },
    E.autorizado: {
        E.asignado: {R.despachador, SISTEMA},          # sistema: asignación automática (P06)
        E.cancelado: CANCELAN,
    },
    E.asignado: {
        E.en_camino: {SISTEMA, R.tecnico},             # sistema al avanzar jornada; el técnico inicia desde la app (P05)
        E.reasignado: {R.despachador, SISTEMA},
        E.cancelado: CANCELAN,
    },
    E.reasignado: {
        E.asignado: {SISTEMA, R.despachador},
    },
    E.en_camino: {
        E.en_ejecucion: {SISTEMA, R.tecnico},          # sistema por GPS; técnico confirma llegada
        E.cancelado: CANCELAN,
    },
    E.en_ejecucion: {
        E.cerrado: {R.tecnico, SISTEMA},
        E.pendiente_refaccion: {R.tecnico},
    },
    E.pendiente_refaccion: {
        E.en_ejecucion: {R.admin_prestador, R.despachador},
        E.reasignado: {R.despachador, R.admin_prestador},
        E.cancelado: CANCELAN,
    },
    E.cerrado: {},
    E.cancelado: {},
}


def _nombre(rol: Any) -> str:
    return rol.value if isinstance(rol, Rol) else str(rol)


def tabla_transiciones() -> list[dict[str, Any]]:
    """Representación serializable (la consume GET /api/folios/transiciones y el frontend)."""
    return [
        {"origen": origen.value, "destino": destino.value, "roles": sorted(_nombre(r) for r in roles)}
        for origen, destinos in TRANSICIONES.items() for destino, roles in destinos.items()
    ]


@dataclass(frozen=True)
class ActorSistema:
    """Actor técnico para transiciones automáticas (validaciones, flujo, Celery)."""
    id: UUID | None = None
    rol: str = SISTEMA
    tenant_id: UUID | None = None
    prestador_id: UUID | None = None
    nombre: str = "sistema"
    es_superadmin: bool = False


ACTOR_SISTEMA = ActorSistema()
ActorFolio = Actor | ActorSistema


def rol_de(actor: ActorFolio) -> str:
    return _nombre(actor.rol)


def puede(actor: ActorFolio, origen: EstadoFolio, destino: EstadoFolio) -> bool:
    roles = TRANSICIONES.get(origen, {}).get(destino)
    if roles is None:
        return False
    if isinstance(actor, Actor) and actor.es_superadmin:
        return True  # plataforma: puede ejecutar cualquier transición existente en la tabla
    return rol_de(actor) in {_nombre(r) for r in roles}


def exigir(actor: ActorFolio, origen: EstadoFolio, destino: EstadoFolio) -> None:
    """409 TRANSICION_NO_PERMITIDA con el detalle de la tabla si el actor no puede ejecutar origen → destino."""
    if puede(actor, origen, destino):
        return
    permitidos = TRANSICIONES.get(origen, {})
    raise ErrorAPI(409, "TRANSICION_NO_PERMITIDA",
                   f"No se permite pasar de {origen.value} a {destino.value} con el rol {rol_de(actor)}",
                   [{"estado_actual": origen.value, "destino": destino.value,
                     "roles_permitidos": sorted(_nombre(r) for r in permitidos.get(destino, set())),
                     "destinos_posibles": [d.value for d in permitidos]}])


def destinos_de(actor: ActorFolio, origen: EstadoFolio) -> list[EstadoFolio]:
    return [d for d in TRANSICIONES.get(origen, {}) if puede(actor, origen, d)]


async def requisitos_cierre(db: AsyncSession, folio: Folio) -> list[str]:
    """§6.8.6: cerrado requiere formulario de atención enviado y evidencia de tipo firma."""
    faltan = []
    atencion = (await db.execute(select(FolioFormularioAtencion.id).where(FolioFormularioAtencion.folio_id == folio.id))).first()
    if atencion is None:
        faltan.append("formulario_atencion")
    firma = (await db.execute(select(FolioEvidencia.id).where(
        FolioEvidencia.folio_id == folio.id, FolioEvidencia.tipo == TipoEvidenciaFolio.firma))).first()
    if firma is None:
        faltan.append("firma")
    return faltan


async def registrar_historial(db: AsyncSession, folio: Folio, actor: ActorFolio, *, evento: str = "transicion",
                              estado_anterior: EstadoFolio | None, estado_nuevo: EstadoFolio, notas: str = "",
                              contexto: dict[str, Any] | None = None) -> FolioEstadoHistorial:
    h = FolioEstadoHistorial(
        folio_id=folio.id, tenant_id=folio.tenant_id, prestador_id=folio.prestador_id, evento=evento,
        estado_anterior=estado_anterior, estado_nuevo=estado_nuevo, actor_id=actor.id, actor_rol=rol_de(actor),
        notas=notas or "", datos_contexto_json=auditoria.a_json(contexto or {}),
        timestamp=datetime.now(UTC),  # explícito: now() de PostgreSQL es el inicio de la transacción y empataría el orden
    )
    db.add(h)
    await db.flush()
    return h


async def comentar(db: AsyncSession, folio: Folio, actor: ActorFolio, notas: str, contexto: dict | None = None,
                   evento: str = "comentario") -> FolioEstadoHistorial:
    """Comentario administrativo: lo único que admite un folio cerrado o cancelado (§6.8.6)."""
    return await registrar_historial(db, folio, actor, evento=evento, estado_anterior=folio.estado, estado_nuevo=folio.estado,
                                     notas=notas, contexto=contexto)


async def _auditar(db: AsyncSession, folio: Folio, actor: ActorFolio, evento: str, request: Request | None,
                   antes: dict, despues: dict) -> None:
    await auditoria.registrar(
        db, evento, actor_id=actor.id, actor_rol=rol_de(actor), tenant_id=folio.tenant_id, prestador_id=folio.prestador_id,
        recurso_tipo="folio", recurso_id=folio.id, antes=antes, despues=despues, request=request,
    )


async def transicionar(db: AsyncSession, folio: Folio, nuevo_estado: EstadoFolio, actor: ActorFolio, notas: str = "",
                       contexto: dict[str, Any] | None = None, request: Request | None = None, momento: datetime | None = None) -> Folio:
    """Valida la transición con la tabla de §6.8.6, actualiza el folio, escribe el historial inmutable y la auditoría,
    fija `fecha_inicio_atencion` al entrar a `en_ejecucion` y `fecha_cierre` al entrar a `cerrado`, y notifica a los
    suscriptores (eventos para P05/P06/P07/P10)."""
    contexto = dict(contexto or {})
    origen = folio.estado
    exigir(actor, origen, nuevo_estado)
    for validador in VALIDADORES:  # P06: p. ej. cancelar un preventivo exige autorización formal
        await validador(db, folio, nuevo_estado, actor, contexto)
    if nuevo_estado == E.cerrado:
        faltan = await requisitos_cierre(db, folio)
        if faltan:
            raise ErrorAPI(409, "CIERRE_INCOMPLETO", "Para cerrar el folio faltan el formulario de atención enviado y/o la firma del operador",
                           faltan)
    if nuevo_estado == E.cancelado and not (contexto.get("razon_cancelacion") or notas):
        raise ErrorAPI(422, "RAZON_REQUERIDA", "Cancelar un folio requiere razón")

    # `momento`: hora real del evento cuando viene de la cola offline (§6.2 client-wins: "hora real de cierre").
    ahora = momento or datetime.now(UTC)
    if momento is not None:
        contexto.setdefault("timestamp_dispositivo", momento.isoformat())
    antes = {"estado": origen.value}
    folio.estado = nuevo_estado
    if nuevo_estado == E.en_ejecucion and folio.fecha_inicio_atencion is None:
        folio.fecha_inicio_atencion = ahora
    if nuevo_estado == E.cerrado:
        folio.fecha_cierre = ahora
    if nuevo_estado == E.cancelado:
        folio.razon_cancelacion = contexto.get("razon_cancelacion") or notas
        folio.cancelado_por = actor.id
    if nuevo_estado == E.asignado and contexto.get("tecnico_id"):
        folio.tecnico_id = UUID(str(contexto["tecnico_id"]))
    if nuevo_estado == E.reasignado:
        contexto.setdefault("tecnico_anterior_id", str(folio.tecnico_id) if folio.tecnico_id else None)
    await db.flush()
    await registrar_historial(db, folio, actor, estado_anterior=origen, estado_nuevo=nuevo_estado, notas=notas, contexto=contexto)
    await _auditar(db, folio, actor, f"folio.transicion.{nuevo_estado.value}", request, antes,
                   {"estado": nuevo_estado.value, "notas": notas, **auditoria.a_json(contexto)})
    for suscriptor in SUSCRIPTORES:
        await suscriptor(db, folio, origen, nuevo_estado, actor, contexto)
    return folio


# Suscriptores en proceso (P05 chat/offline, P06 reasignación/rutas, P07 seguimiento, P10 SLA) — firma:
#   async def fn(db, folio, estado_anterior, estado_nuevo, actor, contexto) -> None
SUSCRIPTORES: list = []
# Evento `folio.creado` (P05 crea los chats) — firma: async def fn(db, folio, actor) -> None
SUSCRIPTORES_CREACION: list = []
# Validadores previos (pueden lanzar ErrorAPI) — firma: async def fn(db, folio, nuevo_estado, actor, contexto) -> None
VALIDADORES: list = []


def suscribir_validacion(fn):
    VALIDADORES.append(fn)
    return fn


def suscribir(fn):
    SUSCRIPTORES.append(fn)
    return fn


def suscribir_creacion(fn):
    SUSCRIPTORES_CREACION.append(fn)
    return fn


async def notificar_creacion(db: AsyncSession, folio: Folio, actor: ActorFolio) -> None:
    for suscriptor in SUSCRIPTORES_CREACION:
        await suscriptor(db, folio, actor)
