"""Módulo 2 — Por presupuesto (§7.7 M2): `diferido` nunca cambia solo; el Admin UN o el Admin empresa reactivan (folio directo o
cotización) o descartan con razón obligatoria. Recordatorio en la minuta mensual y al inicio de cada período presupuestal."""
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.dependencias import Actor
from core.errors import ErrorAPI
from models.base import Rol
from models.folios import ModuloDestino
from models.seguimiento import EstadoPresupuesto, HallazgoPresupuesto, PeriodoPresupuestal, TipoPeriodoPresupuestal
from services import auditoria
from services.folio_estados import ActorFolio
from services.seguimiento import base

MODULO = ModuloDestino.por_presupuesto
DECIDEN = {Rol.superadmin, Rol.admin_un, Rol.admin_empresa}


def periodo_actual(tipo: TipoPeriodoPresupuestal | None, fechas: list[str] | None, hoy: date | None = None) -> str:
    hoy = hoy or date.today()
    if tipo == TipoPeriodoPresupuestal.mensual or tipo is None:
        return f"{hoy.year}-{hoy.month:02d}"
    if tipo == TipoPeriodoPresupuestal.trimestral:
        return f"{hoy.year}-T{(hoy.month - 1) // 3 + 1}"
    if tipo == TipoPeriodoPresupuestal.semestral:
        return f"{hoy.year}-S{1 if hoy.month <= 6 else 2}"
    if tipo == TipoPeriodoPresupuestal.anual:
        return str(hoy.year)
    inicios = sorted(date.fromisoformat(f) for f in (fechas or []))
    vigentes = [f for f in inicios if f <= hoy]
    return (vigentes[-1] if vigentes else (inicios[0] if inicios else hoy)).isoformat()


def inicio_de_periodo(tipo: TipoPeriodoPresupuestal, fechas: list[str] | None, dia: date) -> bool:
    """¿`dia` es el primer día de un período presupuestal?"""
    if tipo == TipoPeriodoPresupuestal.mensual:
        return dia.day == 1
    if tipo == TipoPeriodoPresupuestal.trimestral:
        return dia.day == 1 and dia.month in (1, 4, 7, 10)
    if tipo == TipoPeriodoPresupuestal.semestral:
        return dia.day == 1 and dia.month in (1, 7)
    if tipo == TipoPeriodoPresupuestal.anual:
        return dia.day == 1 and dia.month == 1
    return dia.isoformat() in (fechas or [])


async def periodo_tenant(db: AsyncSession, tenant_id: UUID) -> PeriodoPresupuestal | None:
    return (await db.execute(select(PeriodoPresupuestal).where(PeriodoPresupuestal.tenant_id == tenant_id, PeriodoPresupuestal.activo.is_(True))
                             .order_by(PeriodoPresupuestal.updated_at.desc()))).scalars().first()


async def crear(db: AsyncSession, actor: ActorFolio, *, tenant_id: UUID, prestador_id: UUID, un_id: UUID, equipo_id: UUID | None, descripcion: str,
                hallazgo_id: UUID | None = None, folio_id: UUID | None = None, origen: str = "minuta", monto_estimado: Decimal | None = None) -> HallazgoPresupuesto:
    p = await periodo_tenant(db, tenant_id)
    ahora = datetime.now(UTC)
    hp = HallazgoPresupuesto(hallazgo_id=hallazgo_id, folio_id=folio_id, tenant_id=tenant_id, prestador_id=prestador_id, un_id=un_id, equipo_id=equipo_id,
                             descripcion=descripcion, periodo_presupuestal=periodo_actual(p.tipo if p else None, p.fechas_json if p else None), origen=origen,
                             estado_desde=ahora, ultima_revision=ahora, monto_estimado=monto_estimado,
                             historial_revisiones_json=[{"fecha": ahora.isoformat(), "evento": "diferido", "por": str(getattr(actor, "id", "")) or "sistema"}])
    db.add(hp)
    await db.flush()
    await base.historial(db, MODULO, hp, None, hp.estado.value, actor, f"Diferido por presupuesto ({origen})")
    await auditoria.registrar(db, "presupuesto.diferido", actor_rol=base.rol_de(actor), actor_id=getattr(actor, "id", None), tenant_id=tenant_id, prestador_id=prestador_id,
                              recurso_tipo="hallazgo_presupuesto", recurso_id=hp.id, despues={"origen": origen, "periodo": hp.periodo_presupuestal})
    return hp


async def revisar(db: AsyncSession, actor: Actor, hp: HallazgoPresupuesto, notas: str, request: Request | None) -> HallazgoPresupuesto:
    base.exigir_rol(actor, DECIDEN, "Revisar el diferido")
    if hp.estado != EstadoPresupuesto.diferido:
        raise ErrorAPI(409, "ESTADO_FINAL", "Solo los diferidos se revisan")
    hp.ultima_revision = datetime.now(UTC)
    hp.historial_revisiones_json = [*hp.historial_revisiones_json, {"fecha": hp.ultima_revision.isoformat(), "evento": "revisado", "por": str(actor.id), "notas": notas}]
    await db.flush()
    await base.historial(db, MODULO, hp, hp.estado.value, hp.estado.value, actor, notas or "Revisado sin cambios")
    return hp


async def reactivar(db: AsyncSession, actor: Actor, hp: HallazgoPresupuesto, como: str, notas: str, request: Request | None) -> tuple[HallazgoPresupuesto, Any]:
    """`como` = folio (correctivo directo autorizado) | cotizacion."""
    base.exigir_rol(actor, DECIDEN, "Reactivar")
    if hp.estado != EstadoPresupuesto.diferido:
        raise ErrorAPI(409, "ESTADO_FINAL", f"El registro está {hp.estado.value}")
    if como not in ("folio", "cotizacion"):
        raise ErrorAPI(422, "REACTIVACION_INVALIDA", "Reactivar como folio o como cotizacion")
    from services.seguimiento import cotizaciones, entradas

    if como == "folio":
        registro = await entradas.folio_directo(db, actor, tenant_id=hp.tenant_id, prestador_id=hp.prestador_id, un_id=hp.un_id, equipo_id=hp.equipo_id,
                                                descripcion=hp.descripcion, contexto={"hallazgo_presupuesto_id": str(hp.id), "origen": "presupuesto_reactivado"},
                                                folio_origen_id=hp.folio_id, request=request)
    else:
        registro = await cotizaciones.crear(db, actor, tenant_id=hp.tenant_id, prestador_id=hp.prestador_id, un_id=hp.un_id, equipo_id=hp.equipo_id,
                                            descripcion=hp.descripcion, hallazgo_id=hp.hallazgo_id, folio_id=hp.folio_id, origen="presupuesto_reactivado", request=request)
    anterior = base.transicionar(hp, EstadoPresupuesto.reactivado)
    hp.decidido_por, hp.decidido_at, hp.reactivado_como, hp.reactivado_registro_id = actor.id, datetime.now(UTC), como, registro.id
    hp.historial_revisiones_json = [*hp.historial_revisiones_json, {"fecha": hp.decidido_at.isoformat(), "evento": f"reactivado_{como}", "por": str(actor.id), "notas": notas}]
    await db.flush()
    await base.historial(db, MODULO, hp, anterior, hp.estado.value, actor, notas or f"Reactivado como {como}", {"registro_id": str(registro.id), "como": como})
    await auditoria.registrar_actor(db, actor, "presupuesto.reactivado", request, tenant_id=hp.tenant_id, prestador_id=hp.prestador_id, recurso_tipo="hallazgo_presupuesto",
                                    recurso_id=hp.id, despues={"como": como, "registro_id": registro.id})
    return hp, registro


async def descartar(db: AsyncSession, actor: Actor, hp: HallazgoPresupuesto, razon: str, request: Request | None) -> HallazgoPresupuesto:
    base.exigir_rol(actor, DECIDEN, "Descartar definitivamente")
    if hp.estado != EstadoPresupuesto.diferido:
        raise ErrorAPI(409, "ESTADO_FINAL", f"El registro está {hp.estado.value}")
    razon = base.exigir_justificacion(razon, "Descartar definitivamente")
    anterior = base.transicionar(hp, EstadoPresupuesto.descartado)
    hp.razon_descarte, hp.decidido_por, hp.decidido_at = razon, actor.id, datetime.now(UTC)
    hp.historial_revisiones_json = [*hp.historial_revisiones_json, {"fecha": hp.decidido_at.isoformat(), "evento": "descartado", "por": str(actor.id), "razon": razon}]
    await db.flush()
    await base.historial(db, MODULO, hp, anterior, hp.estado.value, actor, razon)
    await auditoria.registrar_actor(db, actor, "presupuesto.descartado", request, tenant_id=hp.tenant_id, prestador_id=hp.prestador_id, recurso_tipo="hallazgo_presupuesto",
                                    recurso_id=hp.id, despues={"razon": razon})
    return hp


async def cambiar_estado(db: AsyncSession, actor: Actor, hp: HallazgoPresupuesto, nuevo: EstadoPresupuesto, notas: str, request: Request | None, **campos: Any):
    if nuevo == EstadoPresupuesto.reactivado:
        return (await reactivar(db, actor, hp, campos.get("como") or "cotizacion", notas, request))[0]
    if nuevo == EstadoPresupuesto.descartado:
        return await descartar(db, actor, hp, notas, request)
    raise ErrorAPI(409, "TRANSICION_NO_PERMITIDA", "Diferido no cambia automáticamente: reactivar o descartar")


async def listar(db: AsyncSession, actor: Actor, filtros: dict[str, Any]) -> list[HallazgoPresupuesto]:
    from services.seguimiento.cotizaciones import _filtrar

    base.exigir_rol(actor, base.CONSULTAN, "Consultar diferidos")
    consulta = await base.alcance(db, actor, select(HallazgoPresupuesto).order_by(HallazgoPresupuesto.created_at.desc()), HallazgoPresupuesto)
    return list((await db.execute(_filtrar(consulta, HallazgoPresupuesto, filtros))).scalars())


async def diferidos_de(db: AsyncSession, tenant_id: UUID, un_id: UUID | None = None) -> list[HallazgoPresupuesto]:
    consulta = select(HallazgoPresupuesto).where(HallazgoPresupuesto.tenant_id == tenant_id, HallazgoPresupuesto.estado == EstadoPresupuesto.diferido).order_by(HallazgoPresupuesto.created_at)
    if un_id:
        consulta = consulta.where(HallazgoPresupuesto.un_id == un_id)
    return list((await db.execute(consulta)).scalars())


async def monto_potencial(db: AsyncSession, actor: Actor, tenant_id: UUID | None) -> list[dict[str, Any]]:
    """Valor estratégico para el prestador: trabajo potencial diferido por UN (monto de cotizaciones asociadas o estimado)."""
    base.exigir_rol(actor, base.PRESTADOR | {Rol.admin_empresa, Rol.direccion_prestador}, "Consultar el monto potencial")
    from models.costos import FolioCosto  # P09: el costo real del folio manda sobre el monto estimado

    consulta = select(HallazgoPresupuesto).where(HallazgoPresupuesto.estado == EstadoPresupuesto.diferido)
    consulta = await base.alcance(db, actor, consulta, HallazgoPresupuesto)
    if tenant_id:
        consulta = consulta.where(HallazgoPresupuesto.tenant_id == tenant_id)
    filas = list((await db.execute(consulta)).scalars())
    costos = {c.folio_id: c.costo_total for c in (await db.execute(select(FolioCosto).where(
        FolioCosto.folio_id.in_({h.folio_id for h in filas if h.folio_id})))).scalars()} if any(h.folio_id for h in filas) else {}
    por_un: dict = {}
    for h in filas:
        monto = costos.get(h.folio_id) if h.folio_id in costos else (h.monto_estimado or Decimal("0"))
        fila = por_un.setdefault(h.un_id, {"un_id": h.un_id, "diferidos": 0, "monto_potencial": Decimal("0")})
        fila["diferidos"] += 1
        fila["monto_potencial"] += monto or Decimal("0")
    return list(por_un.values())
