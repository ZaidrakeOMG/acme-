"""Módulo 3 — Seguimiento interno (§7.7 M3): el cliente gestiona con terceros o garantía; ACMA vigila. `con_proveedor` exige
proveedor y fecha acordada (referencia opcional); resuelto y cancelado exigen justificación escrita."""
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.dependencias import Actor
from core.errors import ErrorAPI
from models.base import Rol
from models.folios import ModuloDestino
from models.seguimiento import EstadoSeguimientoInterno as E, SeguimientoInterno
from services import auditoria, notificaciones_service
from services.folio_estados import ActorFolio
from services.seguimiento import base

MODULO = ModuloDestino.seguimiento_interno
GESTIONAN = {Rol.superadmin, Rol.admin_un, Rol.admin_empresa}
TRANSICIONES: dict[E, dict[E, set[Rol]]] = {
    E.registrado: {E.en_gestion: GESTIONAN, E.con_proveedor: GESTIONAN, E.resuelto: GESTIONAN, E.cancelado: GESTIONAN},
    E.en_gestion: {E.con_proveedor: GESTIONAN, E.resuelto: GESTIONAN, E.cancelado: GESTIONAN},
    E.con_proveedor: {E.en_gestion: GESTIONAN, E.resuelto: GESTIONAN, E.cancelado: GESTIONAN},
    E.resuelto: {},
    E.cancelado: {},
}
FINALES = {E.resuelto, E.cancelado}


async def crear(db: AsyncSession, actor: ActorFolio, *, tenant_id: UUID, prestador_id: UUID, un_id: UUID, equipo_id: UUID | None, descripcion: str,
                hallazgo_id: UUID | None = None, folio_id: UUID | None = None, origen: str = "minuta", responsable_un: UUID | None = None) -> SeguimientoInterno:
    ahora = datetime.now(UTC)
    s = SeguimientoInterno(hallazgo_id=hallazgo_id, folio_id=folio_id, tenant_id=tenant_id, prestador_id=prestador_id, un_id=un_id, equipo_id=equipo_id,
                           descripcion=descripcion, responsable_un=responsable_un or getattr(actor, "id", None), origen=origen, estado_desde=ahora, ultima_actualizacion=ahora)
    db.add(s)
    await db.flush()
    await base.historial(db, MODULO, s, None, s.estado.value, actor, f"Registrado ({origen})")
    await auditoria.registrar(db, "seguimiento_interno.registrado", actor_rol=base.rol_de(actor), actor_id=getattr(actor, "id", None), tenant_id=tenant_id,
                              prestador_id=prestador_id, recurso_tipo="seguimiento_interno", recurso_id=s.id, despues={"origen": origen})
    return s


async def cambiar_estado(db: AsyncSession, actor: Actor, s: SeguimientoInterno, nuevo: E, notas: str, request: Request | None, *, proveedor: str | None = None,
                         fecha_acordada: date | None = None, referencia_tercero: str | None = None, **_: Any) -> SeguimientoInterno:
    permitidos = TRANSICIONES[s.estado]
    if nuevo not in permitidos:
        raise ErrorAPI(409, "TRANSICION_NO_PERMITIDA", f"Un seguimiento {s.estado.value} no pasa a {nuevo.value}", [{"destinos_posibles": [d.value for d in permitidos]}])
    base.exigir_rol(actor, permitidos[nuevo], f"Pasar a {nuevo.value}")
    datos: dict[str, Any] = {}
    if nuevo == E.con_proveedor:
        if not (proveedor or "").strip() or fecha_acordada is None:
            raise ErrorAPI(422, "PROVEEDOR_REQUERIDO", "Con proveedor confirmado requiere nombre del proveedor y fecha acordada (referencia opcional)")
        s.proveedor, s.fecha_acordada, s.referencia_tercero = proveedor.strip(), fecha_acordada, (referencia_tercero or "").strip() or None
        datos = {"proveedor": s.proveedor, "fecha_acordada": fecha_acordada.isoformat(), "referencia_tercero": s.referencia_tercero}
    if nuevo in FINALES:
        notas = base.exigir_justificacion(notas, "Resolver" if nuevo == E.resuelto else "Cancelar")
        s.justificacion_cierre, s.cerrado_por, s.cerrado_at = notas, actor.id, datetime.now(UTC)
    anterior = base.transicionar(s, nuevo)
    s.ultima_actualizacion = datetime.now(UTC)
    await db.flush()
    await base.historial(db, MODULO, s, anterior, nuevo.value, actor, notas, datos)
    await auditoria.registrar_actor(db, actor, f"seguimiento_interno.{nuevo.value}", request, tenant_id=s.tenant_id, prestador_id=s.prestador_id,
                                    recurso_tipo="seguimiento_interno", recurso_id=s.id, despues={"notas": notas, **datos})
    destinatarios = await notificaciones_service.destinatarios_por_rol(db, [Rol.despachador, Rol.admin_prestador], prestador_id=s.prestador_id)
    await notificaciones_service.notificar(db, "seguimiento.cambio_estado", destinatarios, {"modulo": MODULO.value, "registro_id": str(s.id), "estado": nuevo.value},
                                           asunto=f"Seguimiento interno: {nuevo.value}", cuerpo=s.descripcion[:200], url=f"/seguimiento/interno/{s.id}",
                                           tenant_id=s.tenant_id, prestador_id=s.prestador_id, canales=["app"])
    return s


async def actualizar(db: AsyncSession, actor: Actor, s: SeguimientoInterno, notas: str, request: Request | None) -> SeguimientoInterno:
    """Novedad sin cambio de estado: reinicia el contador de inactividad."""
    base.exigir_rol(actor, GESTIONAN | base.PRESTADOR, "Actualizar el seguimiento")
    if s.estado in FINALES:
        raise ErrorAPI(409, "ESTADO_FINAL", "El seguimiento ya está cerrado")
    notas = base.exigir_justificacion(notas, "La actualización")
    s.ultima_actualizacion = datetime.now(UTC)
    await db.flush()
    await base.historial(db, MODULO, s, s.estado.value, s.estado.value, actor, notas)
    return s


async def listar(db: AsyncSession, actor: Actor, filtros: dict[str, Any]) -> list[SeguimientoInterno]:
    from services.seguimiento.cotizaciones import _filtrar

    base.exigir_rol(actor, base.CONSULTAN, "Consultar seguimientos internos")
    consulta = await base.alcance(db, actor, select(SeguimientoInterno).order_by(SeguimientoInterno.created_at.desc()), SeguimientoInterno)
    return list((await db.execute(_filtrar(consulta, SeguimientoInterno, filtros))).scalars())
