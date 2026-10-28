"""Infraestructura común de los cuatro módulos de seguimiento (§7.7–7.9): alcance por rol, historial append-only,
justificación obligatoria, días en el estado y alertas activas."""
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.dependencias import Actor
from core.errors import ErrorAPI, no_encontrado, prohibido
from models.alertas import AlertaHistorial
from models.base import Dominio, EstadoAlerta, Rol
from models.folios import ModuloDestino
from models.seguimiento import Cotizacion, HallazgoPresupuesto, ModuloHistorial, Reprogramacion, SeguimientoInterno
from services.folio_estados import ACTOR_SISTEMA, ActorFolio
from services.preventivos_service import _unidades_visibles

MODELOS = {
    ModuloDestino.cotizaciones: Cotizacion,
    ModuloDestino.por_presupuesto: HallazgoPresupuesto,
    ModuloDestino.seguimiento_interno: SeguimientoInterno,
    ModuloDestino.reprogramacion: Reprogramacion,
}
NOMBRES = {
    ModuloDestino.cotizaciones: "Cotizaciones", ModuloDestino.por_presupuesto: "Por presupuesto",
    ModuloDestino.seguimiento_interno: "Seguimiento interno", ModuloDestino.reprogramacion: "Reprogramación",
}
CLIENTE = {Rol.superadmin, Rol.admin_un, Rol.admin_empresa}
PRESTADOR = {Rol.superadmin, Rol.admin_prestador, Rol.despachador, Rol.mesa_control}
CONSULTAN = CLIENTE | PRESTADOR | {Rol.supervisor_operadores, Rol.direccion_prestador, Rol.supervisor_prestador}


def rol_de(actor: ActorFolio) -> str:
    return actor.rol.value if isinstance(actor.rol, Rol) else str(actor.rol)


def exigir_rol(actor: ActorFolio, roles: set[Rol], accion: str) -> None:
    if actor is ACTOR_SISTEMA or getattr(actor, "es_superadmin", False):
        return
    if actor.rol not in roles:
        raise prohibido(f"{accion}: solo {', '.join(sorted(r.value for r in roles if r != Rol.superadmin))}")


def exigir_justificacion(texto: str | None, que: str) -> str:
    if not (texto or "").strip() or len(texto.strip()) < 5:
        raise ErrorAPI(422, "JUSTIFICACION_REQUERIDA", f"{que} requiere justificación escrita (mínimo 5 caracteres)")
    return texto.strip()


async def alcance(db: AsyncSession, actor: Actor, consulta, modelo):
    """Tenant: su tenant (Admin UN / supervisor: sus UNs). Prestador: sus registros. Superadmin: todo."""
    if actor.es_superadmin:
        return consulta
    if actor.dominio == Dominio.tenant:
        consulta = consulta.where(modelo.tenant_id == actor.tenant_id)
        unidades = await _unidades_visibles(db, actor)
        if unidades is not None:
            consulta = consulta.where(modelo.un_id.in_(unidades))
        return consulta
    return consulta.where(modelo.prestador_id == actor.prestador_id)


async def obtener(db: AsyncSession, actor: Actor, modelo, registro_id: UUID):
    r = (await db.execute(await alcance(db, actor, select(modelo).where(modelo.id == registro_id), modelo))).scalar_one_or_none()
    if r is None:
        raise no_encontrado(NOMBRES.get(modulo_de(modelo), "Registro"))
    return r


def modulo_de(modelo) -> ModuloDestino:
    return next(m for m, cls in MODELOS.items() if cls is modelo or isinstance(modelo, cls))


async def historial(db: AsyncSession, modulo: ModuloDestino, registro, estado_anterior: str | None, estado_nuevo: str, actor: ActorFolio,
                    notas: str = "", datos: dict[str, Any] | None = None) -> ModuloHistorial:
    h = ModuloHistorial(modulo=modulo, registro_id=registro.id, tenant_id=registro.tenant_id, prestador_id=registro.prestador_id,
                        estado_anterior=estado_anterior, estado_nuevo=estado_nuevo, usuario_id=getattr(actor, "id", None), actor_rol=rol_de(actor),
                        timestamp=datetime.now(UTC), notas=notas or "", datos_json=datos or {})
    db.add(h)
    await db.flush()
    return h


async def historial_de(db: AsyncSession, modulo: ModuloDestino, registro_id: UUID) -> list[ModuloHistorial]:
    return list((await db.execute(select(ModuloHistorial).where(ModuloHistorial.modulo == modulo, ModuloHistorial.registro_id == registro_id)
                                  .order_by(ModuloHistorial.timestamp, ModuloHistorial.id))).scalars())


def dias_en_estado(registro, ahora: datetime | None = None) -> int:
    ahora = ahora or datetime.now(UTC)
    desde = getattr(registro, "estado_desde", None) or registro.created_at
    return max(0, (ahora - desde).days)


async def alertas_activas(db: AsyncSession, ids: list[UUID]) -> dict[UUID, list[str]]:
    if not ids:
        return {}
    filas = (await db.execute(select(AlertaHistorial.entidad_id, AlertaHistorial.clave_alerta).where(
        AlertaHistorial.entidad_id.in_(ids), AlertaHistorial.estado == EstadoAlerta.disparada))).all()
    salida: dict[UUID, list[str]] = {}
    for entidad_id, clave in filas:
        salida.setdefault(entidad_id, []).append(clave)
    return salida


def transicionar(registro, nuevo_estado) -> str | None:
    """Aplica el cambio de estado y actualiza `estado_desde`; devuelve el estado anterior."""
    anterior = registro.estado.value if registro.estado else None
    registro.estado = nuevo_estado
    registro.estado_desde = datetime.now(UTC)
    return anterior
