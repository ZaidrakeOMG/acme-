"""Presupuestos y control de gasto (§4.1, §6.8.5): presupuesto por UN o por grupo de UNs, por tipo de actividad y período;
consumo al validarse el costo del folio; vista consolidada Tenant → Grupo → UN con comprometido y desviación; alertas por los
umbrales configurables de cada presupuesto. P09."""
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.dependencias import Actor
from core.errors import ErrorAPI, no_encontrado, prohibido
from models.base import Dominio, Rol
from models.costos import FolioCosto, Presupuesto, PresupuestoConsumo, TipoActividadPresupuesto
from models.folios import EstadoFolio, Folio, TipoFolio
from models.unidades import GrupoUN, GrupoUNMiembro, UnidadNegocio
from services import alertas_service, auditoria, notificaciones_service
from services.folio_estados import ActorFolio
from services.preventivos_service import _unidades_visibles

ESCRIBEN = {Rol.superadmin, Rol.admin_empresa}
CONSULTAN = ESCRIBEN | {Rol.admin_un, Rol.supervisor_operadores, Rol.admin_prestador, Rol.mesa_control, Rol.direccion_prestador}
CERO = Decimal("0")
CENTAVO = Decimal("0.01")
TIPO_POR_FOLIO = {TipoFolio.correctivo: TipoActividadPresupuesto.correctivo, TipoFolio.preventivo: TipoActividadPresupuesto.preventivo,
                  TipoFolio.especial: TipoActividadPresupuesto.especial}


async def _grupos_de_un(db: AsyncSession, un_id: UUID) -> list[UUID]:
    return list((await db.execute(select(GrupoUNMiembro.grupo_id).where(GrupoUNMiembro.unidad_id == un_id))).scalars())


async def _unidades_del_grupo(db: AsyncSession, grupo_id: UUID) -> list[UUID]:
    return list((await db.execute(select(GrupoUNMiembro.unidad_id).where(GrupoUNMiembro.grupo_id == grupo_id))).scalars())


async def aplicables(db: AsyncSession, *, tenant_id: UUID, un_id: UUID, tipo_folio: TipoFolio, fecha: date) -> list[Presupuesto]:
    """Todos los presupuestos que cubren el folio: el de su UN, el de cada grupo al que pertenece, por tipo y `todos`."""
    tipo = TIPO_POR_FOLIO.get(tipo_folio, TipoActividadPresupuesto.todos)
    grupos = await _grupos_de_un(db, un_id)
    consulta = select(Presupuesto).where(Presupuesto.tenant_id == tenant_id, Presupuesto.activo.is_(True), Presupuesto.periodo_inicio <= fecha,
                                         Presupuesto.periodo_fin >= fecha,
                                         Presupuesto.tipo_actividad.in_((tipo, TipoActividadPresupuesto.todos)))
    filas = list((await db.execute(consulta)).scalars())
    return [p for p in filas if (p.un_id == un_id) or (p.grupo_id is not None and p.grupo_id in grupos)]


async def registrar_consumo(db: AsyncSession, folio: Folio, costo: FolioCosto, actor: ActorFolio) -> list[PresupuestoConsumo]:
    """Append-only e idempotente por (presupuesto, folio): se llama al validarse el costo del folio."""
    fecha = (folio.fecha_cierre or datetime.now(UTC)).date()
    tipo = TIPO_POR_FOLIO.get(folio.tipo_folio, TipoActividadPresupuesto.todos)
    creados: list[PresupuestoConsumo] = []
    for p in await aplicables(db, tenant_id=folio.tenant_id, un_id=folio.un_id, tipo_folio=folio.tipo_folio, fecha=fecha):
        existente = (await db.execute(select(PresupuestoConsumo).where(PresupuestoConsumo.presupuesto_id == p.id,
                                                                        PresupuestoConsumo.folio_id == folio.id))).scalar_one_or_none()
        if existente is not None:
            continue
        c = PresupuestoConsumo(presupuesto_id=p.id, tenant_id=folio.tenant_id, folio_id=folio.id, un_id=folio.un_id, monto=costo.costo_total,
                               fecha=fecha, tipo=tipo, notas=f"Folio {folio.numero_folio}", registrado_por=getattr(actor, "id", None))
        db.add(c)
        creados.append(c)
    await db.flush()
    for c in creados:
        await _revisar_umbrales(db, await db.get(Presupuesto, c.presupuesto_id), folio)
    return creados


async def consumido(db: AsyncSession, presupuesto_id: UUID) -> Decimal:
    total = (await db.execute(select(func.coalesce(func.sum(PresupuestoConsumo.monto), 0)).where(
        PresupuestoConsumo.presupuesto_id == presupuesto_id))).scalar() or CERO
    return Decimal(str(total)).quantize(CENTAVO)


async def comprometido(db: AsyncSession, p: Presupuesto) -> Decimal:
    """Regla elegida: folios autorizados y aún sin cerrar, con `monto_estimado`, cuya fecha de captura cae en el período."""
    abiertos = (EstadoFolio.autorizado, EstadoFolio.asignado, EstadoFolio.reasignado, EstadoFolio.en_camino, EstadoFolio.en_ejecucion,
                EstadoFolio.pendiente_refaccion)
    unidades = [p.un_id] if p.un_id else await _unidades_del_grupo(db, p.grupo_id)
    if not unidades:
        return CERO
    consulta = select(func.coalesce(func.sum(Folio.monto_estimado), 0)).where(
        Folio.tenant_id == p.tenant_id, Folio.un_id.in_(unidades), Folio.estado.in_(abiertos), Folio.monto_estimado.is_not(None),
        func.date(Folio.capturado_at) >= p.periodo_inicio, func.date(Folio.capturado_at) <= p.periodo_fin)
    if p.tipo_actividad != TipoActividadPresupuesto.todos:
        consulta = consulta.where(Folio.tipo_folio == TipoFolio(p.tipo_actividad.value))
    return Decimal(str((await db.execute(consulta)).scalar() or 0)).quantize(CENTAVO)


async def _revisar_umbrales(db: AsyncSession, p: Presupuesto | None, folio: Folio | None = None) -> None:
    if p is None or p.monto <= CERO:
        return
    from models.alertas import AlertaHistorial
    from models.base import EstadoAlerta

    total = await consumido(db, p.id)
    pct = (total / p.monto * 100).quantize(CENTAVO)
    # Dedupe por el historial de alertas (no por una columna del presupuesto): quien valida el costo es el prestador y no
    # escribe el presupuesto del cliente.
    previas = (await db.execute(select(AlertaHistorial.datos_contexto_json).where(
        AlertaHistorial.entidad_id == p.id, AlertaHistorial.clave_alerta.in_(("PRESUPUESTO_UMBRAL_ALCANZADO", "PRESUPUESTO_EXCEDIDO")),
        AlertaHistorial.estado == EstadoAlerta.disparada))).scalars().all()
    disparados = [Decimal(str(d.get("umbral"))) for d in previas if isinstance(d, dict) and d.get("umbral") not in (None, "")]
    for umbral in sorted(Decimal(str(u)) for u in (p.umbrales_alerta_json or [])):
        if pct < umbral or umbral in disparados:
            continue
        excedido = umbral >= 100
        clave = "PRESUPUESTO_EXCEDIDO" if excedido else "PRESUPUESTO_UMBRAL_ALCANZADO"
        datos = {"presupuesto_id": str(p.id), "nombre": p.nombre, "umbral": str(umbral), "consumido": str(total), "monto": str(p.monto),
                 "porcentaje": str(pct), "un_id": str(p.un_id) if p.un_id else None, "grupo_id": str(p.grupo_id) if p.grupo_id else None}
        # El prestador que atiende al cliente es quien valida el costo: la alerta lleva ambos dueños para pasar la RLS de `alertas_historial`.
        await alertas_service.disparar(db, clave, tenant_id=p.tenant_id, prestador_id=folio.prestador_id if folio else None,
                                       entidad_tipo="presupuesto", entidad_id=p.id, datos=datos)
        destinatarios = await notificaciones_service.destinatarios_por_rol(db, [Rol.admin_empresa], tenant_id=p.tenant_id)
        if p.un_id:
            destinatarios += await notificaciones_service.destinatarios_por_rol(db, [Rol.admin_un], tenant_id=p.tenant_id, un_id=p.un_id)
        else:
            grupo = await db.get(GrupoUN, p.grupo_id)
            if grupo is not None and grupo.responsable_id:
                destinatarios.append(grupo.responsable_id)
        etiqueta = p.nombre or (f"UN {p.un_id}" if p.un_id else f"grupo {p.grupo_id}")
        await notificaciones_service.notificar(db, "presupuesto.umbral", destinatarios, datos,
                                               asunto=("Presupuesto excedido" if excedido else f"Presupuesto al {umbral}%") + f": {etiqueta}",
                                               cuerpo=f"Consumido ${total:,.2f} de ${p.monto:,.2f} ({pct}%)" + (f" · último folio {folio.numero_folio}" if folio else ""),
                                               url="/presupuestos", tenant_id=p.tenant_id, prestador_id=folio.prestador_id if folio else None)
        disparados.append(umbral)


# -------------------------------------------------------------------- CRUD

async def crear(db: AsyncSession, actor: Actor, datos: dict[str, Any], request: Request | None = None) -> Presupuesto:
    if not actor.es_superadmin and actor.rol not in ESCRIBEN:
        raise prohibido("Solo el Admin empresa define presupuestos")
    tenant_id = datos.pop("tenant_id", None) if actor.es_superadmin else actor.tenant_id
    if tenant_id is None:
        raise ErrorAPI(422, "TENANT_REQUERIDO", "Indica el cliente del presupuesto")
    un_id, grupo_id = datos.get("un_id"), datos.get("grupo_id")
    if bool(un_id) == bool(grupo_id):
        raise ErrorAPI(422, "ALCANCE_INVALIDO", "El presupuesto se asigna a una UN o a un grupo de UNs, no a ambos ni a ninguno")
    if un_id:
        un = await db.get(UnidadNegocio, un_id)
        if un is None or un.tenant_id != tenant_id:
            raise ErrorAPI(422, "UNIDAD_INVALIDA", "La unidad no pertenece al cliente")
    if grupo_id:
        g = await db.get(GrupoUN, grupo_id)
        if g is None or g.tenant_id != tenant_id:
            raise ErrorAPI(422, "GRUPO_INVALIDO", "El grupo no pertenece al cliente")
    if datos["periodo_fin"] < datos["periodo_inicio"]:
        raise ErrorAPI(422, "PERIODO_INVALIDO", "La fecha final no puede ser anterior a la inicial")
    p = Presupuesto(tenant_id=tenant_id, created_by=actor.id, **datos)
    db.add(p)
    await db.flush()
    await auditoria.registrar_actor(db, actor, "presupuestos.creado", request, tenant_id=tenant_id, recurso_tipo="presupuesto", recurso_id=p.id,
                                    despues={"nombre": p.nombre, "monto": str(p.monto), "un_id": str(un_id) if un_id else None,
                                             "grupo_id": str(grupo_id) if grupo_id else None})
    return p


async def obtener(db: AsyncSession, actor: Actor, presupuesto_id: UUID) -> Presupuesto:
    p = await db.get(Presupuesto, presupuesto_id)
    if p is None:
        raise no_encontrado("Presupuesto")
    if actor.es_superadmin:
        return p
    if actor.dominio == Dominio.tenant and p.tenant_id == actor.tenant_id:
        if actor.rol in (Rol.admin_un, Rol.supervisor_operadores):
            unidades = await _unidades_visibles(db, actor)
            if unidades is not None and p.un_id is not None and p.un_id not in set(unidades):
                raise no_encontrado("Presupuesto")
        return p
    if actor.dominio == Dominio.prestador:
        from services import catalogos_service

        if actor.prestador_id in await catalogos_service.prestadores_del_tenant(db, p.tenant_id):
            return p
    raise no_encontrado("Presupuesto")


async def actualizar(db: AsyncSession, actor: Actor, p: Presupuesto, cambios: dict[str, Any], request: Request | None = None) -> Presupuesto:
    if not actor.es_superadmin and actor.rol not in ESCRIBEN:
        raise prohibido("Solo el Admin empresa edita presupuestos")
    antes = auditoria.instantanea(p)
    for k, v in cambios.items():
        setattr(p, k, v)
    if p.periodo_fin < p.periodo_inicio:
        raise ErrorAPI(422, "PERIODO_INVALIDO", "La fecha final no puede ser anterior a la inicial")
    await db.flush()
    await auditoria.registrar_actor(db, actor, "presupuestos.editado", request, tenant_id=p.tenant_id, recurso_tipo="presupuesto", recurso_id=p.id,
                                    antes=antes, despues=auditoria.instantanea(p))
    await _revisar_umbrales(db, p)
    return p


async def listar(db: AsyncSession, actor: Actor, *, tenant_id: UUID | None = None, un_id: UUID | None = None, grupo_id: UUID | None = None,
                 vigentes: bool = False) -> list[dict[str, Any]]:
    if not actor.es_superadmin and actor.rol not in CONSULTAN:
        raise prohibido("Tu rol no consulta presupuestos")
    consulta = select(Presupuesto).order_by(Presupuesto.periodo_inicio.desc())
    if actor.es_superadmin:
        if tenant_id:
            consulta = consulta.where(Presupuesto.tenant_id == tenant_id)
    elif actor.dominio == Dominio.tenant:
        consulta = consulta.where(Presupuesto.tenant_id == actor.tenant_id)
        unidades = await _unidades_visibles(db, actor)
        if unidades is not None:
            grupos = list((await db.execute(select(GrupoUNMiembro.grupo_id).where(GrupoUNMiembro.unidad_id.in_(unidades)))).scalars())
            consulta = consulta.where(Presupuesto.un_id.in_(unidades) | Presupuesto.grupo_id.in_(grupos or [None]))
    else:
        from models.organizaciones import TenantPrestador

        tenants = list((await db.execute(select(TenantPrestador.tenant_id).where(TenantPrestador.prestador_id == actor.prestador_id))).scalars())
        consulta = consulta.where(Presupuesto.tenant_id.in_(tenants or [None]))
        if tenant_id:
            consulta = consulta.where(Presupuesto.tenant_id == tenant_id)
    if un_id:
        consulta = consulta.where(Presupuesto.un_id == un_id)
    if grupo_id:
        consulta = consulta.where(Presupuesto.grupo_id == grupo_id)
    if vigentes:
        hoy = date.today()
        consulta = consulta.where(Presupuesto.periodo_inicio <= hoy, Presupuesto.periodo_fin >= hoy, Presupuesto.activo.is_(True))
    return [await resumen(db, p) for p in (await db.execute(consulta)).scalars()]


async def resumen(db: AsyncSession, p: Presupuesto) -> dict[str, Any]:
    total = await consumido(db, p.id)
    compr = await comprometido(db, p)
    pct = (total / p.monto * 100).quantize(CENTAVO) if p.monto > CERO else CERO
    un = await db.get(UnidadNegocio, p.un_id) if p.un_id else None
    grupo = await db.get(GrupoUN, p.grupo_id) if p.grupo_id else None
    umbrales = sorted(Decimal(str(u)) for u in (p.umbrales_alerta_json or []))
    semaforo = "verde"
    for u in umbrales:
        if pct >= u:
            semaforo = "rojo" if u >= 100 else "amarillo"
    return {**auditoria.instantanea(p), "id": p.id, "tenant_id": p.tenant_id, "un_id": p.un_id, "grupo_id": p.grupo_id, "nombre": p.nombre,
            "un_codigo": un.codigo if un else None, "un_nombre": un.nombre if un else None, "grupo_nombre": grupo.nombre if grupo else None,
            "tipo_actividad": p.tipo_actividad.value, "periodo_inicio": p.periodo_inicio, "periodo_fin": p.periodo_fin, "monto": p.monto,
            "moneda": p.moneda, "umbrales_alerta_json": p.umbrales_alerta_json, "activo": p.activo, "consumido": total, "comprometido": compr,
            "disponible": (p.monto - total - compr).quantize(CENTAVO), "porcentaje": pct, "desviacion": (total - p.monto).quantize(CENTAVO),
            "semaforo": semaforo, "created_at": p.created_at, "updated_at": p.updated_at}


async def consumos(db: AsyncSession, actor: Actor, p: Presupuesto) -> list[dict[str, Any]]:
    filas = list((await db.execute(select(PresupuestoConsumo).where(PresupuestoConsumo.presupuesto_id == p.id)
                                   .order_by(PresupuestoConsumo.fecha.desc()))).scalars())
    if not filas:
        return []
    folios = {f.id: f for f in (await db.execute(select(Folio).where(Folio.id.in_({c.folio_id for c in filas if c.folio_id})))).scalars()}
    unidades = {u.id: u for u in (await db.execute(select(UnidadNegocio).where(UnidadNegocio.id.in_({c.un_id for c in filas if c.un_id})))).scalars()}
    return [{"id": c.id, "folio_id": c.folio_id, "numero_folio": folios[c.folio_id].numero_folio if c.folio_id in folios else None,
             "descripcion": folios[c.folio_id].descripcion[:120] if c.folio_id in folios else c.notas, "un_id": c.un_id,
             "un_codigo": unidades[c.un_id].codigo if c.un_id in unidades else None, "monto": c.monto, "fecha": c.fecha, "tipo": c.tipo.value,
             "created_at": c.created_at} for c in filas]


async def consolidado(db: AsyncSession, actor: Actor, *, tenant_id: UUID | None = None, vigentes: bool = True) -> dict[str, Any]:
    """Jerarquía de §6.8.5: Tenant → Grupo → UN, con presupuesto, consumido, comprometido, disponible, porcentaje y desviación."""
    presupuestos = await listar(db, actor, tenant_id=tenant_id, vigentes=vigentes)
    grupos: dict[str, dict[str, Any]] = {}
    unidades: dict[str, dict[str, Any]] = {}
    for p in presupuestos:
        destino = grupos if p["grupo_id"] else unidades
        clave = str(p["grupo_id"] or p["un_id"])
        fila = destino.setdefault(clave, {"id": clave, "nombre": p["grupo_nombre"] or f"{p['un_codigo']} · {p['un_nombre']}", "monto": CERO,
                                          "consumido": CERO, "comprometido": CERO, "presupuestos": []})
        for k in ("monto", "consumido", "comprometido"):
            fila[k] = fila[k] + p[k]
        fila["presupuestos"].append(p)
    def _cerrar(fila: dict[str, Any]) -> dict[str, Any]:
        pct = (fila["consumido"] / fila["monto"] * 100).quantize(CENTAVO) if fila["monto"] > CERO else CERO
        return {**fila, "disponible": (fila["monto"] - fila["consumido"] - fila["comprometido"]).quantize(CENTAVO), "porcentaje": pct,
                "desviacion": (fila["consumido"] - fila["monto"]).quantize(CENTAVO),
                "semaforo": "rojo" if pct >= 100 else ("amarillo" if pct >= 80 else "verde")}
    monto = sum((p["monto"] for p in presupuestos), CERO)
    total = sum((p["consumido"] for p in presupuestos), CERO)
    compr = sum((p["comprometido"] for p in presupuestos), CERO)
    pct = (total / monto * 100).quantize(CENTAVO) if monto > CERO else CERO
    return {"tenant": {"monto": monto, "consumido": total, "comprometido": compr, "disponible": (monto - total - compr).quantize(CENTAVO),
                       "porcentaje": pct, "desviacion": (total - monto).quantize(CENTAVO),
                       "semaforo": "rojo" if pct >= 100 else ("amarillo" if pct >= 80 else "verde")},
            "grupos": [_cerrar(g) for g in grupos.values()], "unidades": [_cerrar(u) for u in unidades.values()], "presupuestos": presupuestos}


async def disponible_para_folio(db: AsyncSession, folio: Folio) -> dict[str, Any] | None:
    """P04: solo informativo para el aprobador (la regla por monto del flujo multinivel no cambia)."""
    ps = await aplicables(db, tenant_id=folio.tenant_id, un_id=folio.un_id, tipo_folio=folio.tipo_folio, fecha=folio.capturado_at.date())
    if not ps:
        return None
    filas = [await resumen(db, p) for p in ps]
    menor = min(filas, key=lambda f: f["disponible"])
    return {"presupuesto_id": menor["id"], "nombre": menor["nombre"], "monto": menor["monto"], "consumido": menor["consumido"],
            "comprometido": menor["comprometido"], "disponible": menor["disponible"], "porcentaje": menor["porcentaje"], "semaforo": menor["semaforo"]}


async def monto_potencial_real(db: AsyncSession, tenant_id: UUID, un_id: UUID | None = None) -> Decimal:
    """P07: el monto potencial de «Por presupuesto» usa ahora el costo real de los folios asociados cuando existe."""
    from models.seguimiento import EstadoPresupuesto, HallazgoPresupuesto

    consulta = select(HallazgoPresupuesto).where(HallazgoPresupuesto.tenant_id == tenant_id, HallazgoPresupuesto.estado == EstadoPresupuesto.diferido)
    if un_id:
        consulta = consulta.where(HallazgoPresupuesto.un_id == un_id)
    total = CERO
    for h in (await db.execute(consulta)).scalars():
        real = None
        if h.folio_id:
            c = (await db.execute(select(FolioCosto).where(FolioCosto.folio_id == h.folio_id))).scalar_one_or_none()
            real = c.costo_total if c else None
        total += real if real is not None else (h.monto_estimado or CERO)
    return total.quantize(CENTAVO)
