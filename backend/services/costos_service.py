"""Costo del folio (§6.8.6 «datos financieros»): al cerrar se calcula refacciones + mano de obra + otros; Mesa de control o
Admin prestador lo validan con ajuste y razón, lo que genera el evento ERP `registrar_gasto` y registra los consumos de
presupuesto. La visibilidad del costo para el técnico depende del permiso `ver_costo_refacciones` (§6.8.3). P09."""
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.dependencias import Actor
from core.errors import ErrorAPI, no_encontrado, prohibido
from models.base import Dominio, Rol
from models.costos import FolioCosto, TarifaManoObra
from models.folios import EstadoFolio, Folio, FolioFormularioAtencion, FolioRefaccion, TipoFolio
from models.formularios import FormularioRespuesta
from models.usuarios import Usuario
from services import auditoria, folio_estados, notificaciones_service, permisos_service
from services.folio_estados import ACTOR_SISTEMA, ActorFolio

VALIDAN = {Rol.superadmin, Rol.mesa_control, Rol.admin_prestador}
CONSULTAN = VALIDAN | {Rol.despachador, Rol.direccion_prestador, Rol.supervisor_prestador, Rol.admin_empresa, Rol.admin_un, Rol.supervisor_operadores}
CERO = Decimal("0")
CENTAVO = Decimal("0.01")
# Claves de campo del formulario de atención que, si existen, mandan sobre las horas calculadas por timestamps.
CLAVES_HORAS = ("horas_mano_obra", "horas_trabajadas", "tiempo_horas", "horas")
MINIMO_HORAS = Decimal("0.5")


async def tarifa_vigente(db: AsyncSession, prestador_id: UUID, tenant_id: UUID, tipo_folio: TipoFolio, cuando: date | None = None) -> TarifaManoObra | None:
    """La más específica gana: tenant + tipo > tenant > tipo > general; entre iguales, la de `vigente_desde` más reciente."""
    cuando = cuando or date.today()
    filas = list((await db.execute(select(TarifaManoObra).where(TarifaManoObra.prestador_id == prestador_id, TarifaManoObra.activa.is_(True),
                                                                TarifaManoObra.vigente_desde <= cuando))).scalars())
    aplicables = [t for t in filas if t.tenant_id in (None, tenant_id) and t.tipo_folio in (None, tipo_folio)]
    if not aplicables:
        return None
    return max(aplicables, key=lambda t: ((2 if t.tenant_id else 0) + (1 if t.tipo_folio else 0), t.vigente_desde, t.created_at))


async def _horas(db: AsyncSession, folio: Folio) -> tuple[Decimal, str]:
    """Horas capturadas por el técnico en el formulario de atención si vienen; si no, las calculadas entre inicio y cierre."""
    vinculo = (await db.execute(select(FolioFormularioAtencion).where(FolioFormularioAtencion.folio_id == folio.id))).scalar_one_or_none()
    if vinculo is not None:
        r = await db.get(FormularioRespuesta, vinculo.respuesta_id)
        for clave in CLAVES_HORAS:
            valor = (r.respuestas_json or {}).get(clave) if r else None
            if valor not in (None, ""):
                try:
                    horas = Decimal(str(valor))
                    if horas > CERO:
                        return horas.quantize(CENTAVO), "formulario"
                except Exception:  # noqa: BLE001
                    pass
    if folio.fecha_inicio_atencion and folio.fecha_cierre:
        delta = (folio.fecha_cierre - folio.fecha_inicio_atencion).total_seconds() / 3600
        return max(MINIMO_HORAS, Decimal(str(round(delta, 2)))).quantize(CENTAVO), "calculadas"
    return MINIMO_HORAS, "minimo"


async def costo_de(db: AsyncSession, folio_id: UUID) -> FolioCosto | None:
    return (await db.execute(select(FolioCosto).where(FolioCosto.folio_id == folio_id))).scalar_one_or_none()


async def refacciones_de(db: AsyncSession, folio_id: UUID) -> list[FolioRefaccion]:
    return list((await db.execute(select(FolioRefaccion).where(FolioRefaccion.folio_id == folio_id).order_by(FolioRefaccion.created_at))).scalars())


async def calcular(db: AsyncSession, folio: Folio, actor: ActorFolio = ACTOR_SISTEMA, *, forzar: bool = False) -> FolioCosto:
    """Gancho del cierre (§6.8.6). Idempotente: un costo ya validado no se recalcula salvo `forzar`."""
    c = await costo_de(db, folio.id)
    if c is not None and c.validado_at is not None and not forzar:
        return c
    refacciones = await refacciones_de(db, folio.id)
    costo_refacciones = sum((r.cantidad * r.costo_unitario for r in refacciones), CERO).quantize(CENTAVO)
    horas, origen_horas = await _horas(db, folio)
    tarifa = await tarifa_vigente(db, folio.prestador_id, folio.tenant_id, folio.tipo_folio, (folio.fecha_cierre or datetime.now(UTC)).date())
    tarifa_hora = tarifa.tarifa_hora if tarifa else CERO
    costo_mano_obra = (horas * tarifa_hora).quantize(CENTAVO)
    if c is None:
        c = FolioCosto(folio_id=folio.id, tenant_id=folio.tenant_id, prestador_id=folio.prestador_id, costo_otros=CERO, ajuste=CERO,
                       costo_total=CERO, moneda="MXN", centro_costos="", razon_ajuste="", detalle_json={})
        db.add(c)
    c.costo_refacciones, c.horas_mano_obra, c.tarifa_hora, c.origen_horas = costo_refacciones, horas, tarifa_hora, origen_horas
    c.costo_mano_obra = costo_mano_obra
    c.moneda = tarifa.moneda if tarifa else c.moneda
    c.costo_total = (costo_refacciones + costo_mano_obra + c.costo_otros + c.ajuste).quantize(CENTAVO)
    c.detalle_json = {"refacciones": [{"descripcion": r.descripcion, "cantidad": str(r.cantidad), "costo_unitario": str(r.costo_unitario),
                                       "origen": r.origen.value, "articulo_id": str(r.articulo_id) if r.articulo_id else None} for r in refacciones],
                      "tarifa_id": str(tarifa.id) if tarifa else None}
    await db.flush()
    return c


@folio_estados.suscribir
async def _al_cerrar(db: AsyncSession, folio: Folio, anterior: EstadoFolio, nuevo: EstadoFolio, actor: ActorFolio, contexto: dict) -> None:
    """Al cerrar el folio se calcula su costo y se avisa a quien lo valida (§6.6: el gasto se registra al validarse)."""
    if nuevo != EstadoFolio.cerrado:
        return
    c = await calcular(db, folio, actor)
    contexto["costo_total"] = str(c.costo_total)
    destinatarios = await notificaciones_service.destinatarios_por_rol(db, [Rol.mesa_control, Rol.admin_prestador], prestador_id=folio.prestador_id)
    await notificaciones_service.notificar(db, "folio.costo_calculado", destinatarios,
                                           {"folio_id": str(folio.id), "costo_total": str(c.costo_total), "numero_folio": folio.numero_folio},
                                           asunto=f"Folio {folio.numero_folio} cerrado con costo de ${c.costo_total:,.2f}: valídalo",
                                           cuerpo=f"Refacciones ${c.costo_refacciones:,.2f} · mano de obra ${c.costo_mano_obra:,.2f} ({c.horas_mano_obra} h)",
                                           url=f"/folios/{folio.id}", tenant_id=folio.tenant_id, prestador_id=folio.prestador_id)


async def validar(db: AsyncSession, actor: Actor, folio: Folio, *, ajuste: Decimal | None = None, razon_ajuste: str = "", costo_otros: Decimal | None = None,
                  centro_costos: str | None = None, request: Request | None = None) -> FolioCosto:
    """Mesa de control o Admin prestador validan el costo; el ajuste exige razón. Genera el evento ERP y los consumos de presupuesto."""
    if not actor.es_superadmin and actor.rol not in VALIDAN:
        raise prohibido("Solo Mesa de control o el Admin prestador validan el costo del folio")
    if actor.dominio == Dominio.prestador and folio.prestador_id != actor.prestador_id:
        raise no_encontrado("Folio")
    if folio.estado != EstadoFolio.cerrado:
        raise ErrorAPI(409, "FOLIO_NO_CERRADO", "El costo se valida con el folio cerrado")
    c = await costo_de(db, folio.id) or await calcular(db, folio, actor)
    if c.validado_at is not None:
        raise ErrorAPI(409, "COSTO_YA_VALIDADO", f"El costo del folio ya fue validado el {c.validado_at:%d/%m/%Y}")
    if ajuste not in (None, CERO) and not (razon_ajuste or "").strip():
        raise ErrorAPI(422, "RAZON_REQUERIDA", "El ajuste del costo exige razón")
    antes = auditoria.instantanea(c)
    if ajuste is not None:
        c.ajuste, c.razon_ajuste = ajuste, (razon_ajuste or "").strip()
    if costo_otros is not None:
        c.costo_otros = costo_otros
    if centro_costos is not None:
        c.centro_costos = centro_costos
    c.costo_total = (c.costo_refacciones + c.costo_mano_obra + c.costo_otros + c.ajuste).quantize(CENTAVO)
    c.validado_por, c.validado_at = actor.id, datetime.now(UTC)
    await db.flush()
    from services import presupuestos_service
    from services.erp import eventos as erp_eventos

    evento = await erp_eventos.registrar_gasto(db, folio, c)
    c.documento_erp_ref = c.documento_erp_ref or f"EVT-{str(evento.id)[:8]}"
    consumos = await presupuestos_service.registrar_consumo(db, folio, c, actor)
    await db.flush()
    await auditoria.registrar_actor(db, actor, "folios.costo_validado", request, tenant_id=folio.tenant_id, prestador_id=folio.prestador_id,
                                    recurso_tipo="folio_costo", recurso_id=c.id, antes=antes,
                                    despues={**auditoria.instantanea(c), "presupuestos": len(consumos)})
    await folio_estados.comentar(db, folio, actor, f"Costo validado: ${c.costo_total:,.2f}",
                                 {"costo_total": str(c.costo_total), "ajuste": str(c.ajuste), "presupuestos": len(consumos)}, evento="folio.costo_validado")
    destinatarios = await notificaciones_service.destinatarios_por_rol(db, [Rol.admin_empresa], tenant_id=folio.tenant_id)
    destinatarios += await notificaciones_service.destinatarios_por_rol(db, [Rol.admin_un], tenant_id=folio.tenant_id, un_id=folio.un_id)
    await notificaciones_service.notificar(db, "folio.costo_validado", destinatarios,
                                           {"folio_id": str(folio.id), "costo_total": str(c.costo_total), "numero_folio": folio.numero_folio},
                                           asunto=f"Folio {folio.numero_folio}: costo validado por ${c.costo_total:,.2f}",
                                           cuerpo=f"Se cargó a {len(consumos)} presupuesto(s) del período.", url=f"/folios/{folio.id}",
                                           tenant_id=folio.tenant_id, prestador_id=folio.prestador_id)
    return c


async def puede_ver_costos(db: AsyncSession, actor: Actor, folio: Folio) -> bool:
    """§6.8.3: el técnico solo ve costos con `ver_costo_refacciones`; el cliente ve el total y el desglose de su folio."""
    if actor.es_superadmin or actor.rol in CONSULTAN:
        return True
    if actor.rol == Rol.tecnico:
        permisos = {p["clave"]: p["habilitado"] for p in await permisos_service.efectivos_de_tecnico(db, folio.prestador_id, actor.id)}
        return bool(permisos.get("ver_costo_refacciones", False))
    return False


async def detalle_financiero(db: AsyncSession, actor: Actor, folio: Folio) -> dict[str, Any] | None:
    """Sección «Datos financieros» del archivo del folio (§6.8.6)."""
    if not await puede_ver_costos(db, actor, folio):
        return {"visible": False, "motivo": "Tu rol no tiene habilitada la visibilidad de costos (ver_costo_refacciones)"}
    c = await costo_de(db, folio.id)
    refacciones = await refacciones_de(db, folio.id)
    from services import caja_chica_service

    gastos = await caja_chica_service.listar_gastos(db, actor, folio_id=folio.id) if actor.dominio == Dominio.prestador or actor.es_superadmin else []
    nombre = None
    if c is not None and c.validado_por:
        u = await db.get(Usuario, c.validado_por)
        nombre = u.nombre if u else None
    return {
        "visible": True,
        "costo": None if c is None else {**auditoria.instantanea(c), "id": c.id, "costo_refacciones": c.costo_refacciones, "costo_mano_obra": c.costo_mano_obra,
                                         "costo_otros": c.costo_otros, "costo_total": c.costo_total, "moneda": c.moneda, "horas_mano_obra": c.horas_mano_obra,
                                         "tarifa_hora": c.tarifa_hora, "origen_horas": c.origen_horas, "ajuste": c.ajuste, "razon_ajuste": c.razon_ajuste,
                                         "centro_costos": c.centro_costos, "validado_por": c.validado_por, "validado_por_nombre": nombre,
                                         "validado_at": c.validado_at, "documento_erp_ref": c.documento_erp_ref},
        "refacciones": [{"id": r.id, "descripcion": r.descripcion, "cantidad": r.cantidad, "costo_unitario": r.costo_unitario, "origen": r.origen.value,
                         "articulo_id": r.articulo_id, "importe": (r.cantidad * r.costo_unitario).quantize(CENTAVO)} for r in refacciones],
        "gastos_caja_chica": gastos,
        "puede_validar": (actor.es_superadmin or actor.rol in VALIDAN) and folio.estado == EstadoFolio.cerrado and (c is None or c.validado_at is None),
    }


# ------------------------------------------------------------- tarifas

async def guardar_tarifa(db: AsyncSession, actor: Actor, datos: dict[str, Any], request: Request | None = None) -> TarifaManoObra:
    if not actor.es_superadmin and actor.rol not in {Rol.admin_prestador}:
        raise prohibido("Solo el Admin prestador configura las tarifas de mano de obra")
    prestador_id = datos.pop("prestador_id", None) or actor.prestador_id
    t = TarifaManoObra(prestador_id=prestador_id, **datos)
    db.add(t)
    await db.flush()
    await auditoria.registrar_actor(db, actor, "costos.tarifa_guardada", request, prestador_id=prestador_id, recurso_tipo="tarifa_mano_obra",
                                    recurso_id=t.id, despues={"tarifa_hora": str(t.tarifa_hora), "tipo_folio": t.tipo_folio.value if t.tipo_folio else None})
    return t


async def listar_tarifas(db: AsyncSession, actor: Actor) -> list[TarifaManoObra]:
    if not actor.es_superadmin and actor.rol not in CONSULTAN:
        raise prohibido("Tu rol no consulta las tarifas de mano de obra")
    consulta = select(TarifaManoObra).order_by(TarifaManoObra.vigente_desde.desc())
    if not actor.es_superadmin and actor.dominio == Dominio.prestador:
        consulta = consulta.where(TarifaManoObra.prestador_id == actor.prestador_id)
    return list((await db.execute(consulta)).scalars())
