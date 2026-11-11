"""Planes de mantenimiento con los seis triggers de §6.9.1.

P06 dejó `tiempo_fijo` y `calendario`; F2-04 habilita `medidor_umbral`, `medidor_intervalo`, `evento` y `combinado`,
cuya evaluación vive en `triggers_service`. Aquí queda lo que no depende de medidores: la validación de parámetros,
la próxima fecha de los triggers por fecha y el alta/edición del plan.

Cada trigger tiene una `clave` estable dentro del plan (`t1`, `t2`, …). Antes una edición borraba y recreaba los
triggers, así que sus id cambiaban; el `combinado` apunta a otros triggers, y con ids volátiles no había a qué
apuntar. Ahora la edición hace upsert por clave: el id sobrevive y el combinado también. La API acepta y devuelve
`triggers_ids` (que es lo que ve la interfaz) y por dentro se guardan las claves.
"""
import calendar
from datetime import date, timedelta
from typing import Any
from uuid import UUID

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.dependencias import Actor
from core.errors import ErrorAPI, no_encontrado, prohibido
from models.base import Dominio, Rol
from models.catalogos import Equipo, Habilidad, NivelSeveridadCatalogo, TipoEquipo
from models.formularios import EstadoFormulario, Formulario, TipoFormulario
from models.medidores import EVENTOS_TRIGGER, EventoTriggerCatalogo
from models.preventivos import (
    TRIGGERS_POR_FECHA, EquipoPlan, EstadoPlan, PlanMantenimiento, PlanMaterial, PlanTarea, PlanTrigger, TipoTrigger,
)
from services import auditoria, catalogos_service

EDITAN = {Rol.superadmin, Rol.admin_prestador, Rol.despachador}
CONSULTAN = EDITAN | {Rol.mesa_control, Rol.supervisor_prestador, Rol.direccion_prestador, Rol.admin_empresa, Rol.admin_un, Rol.supervisor_operadores}
UNIDADES = {"dias": 1, "semanas": 7}


# ------------------------------------------------------------- triggers

def validar_trigger(tipo: TipoTrigger, parametros: dict[str, Any], claves_validas: set[str] | None = None,
                    eventos_validos: set[str] | None = None) -> dict[str, Any]:
    """Normaliza los parámetros de un trigger y devuelve solo lo que el tipo usa (lo demás se descarta)."""
    tipo = TipoTrigger(tipo)
    if tipo not in TRIGGERS_POR_FECHA:
        from services import triggers_service

        return triggers_service.validar_parametros(tipo, parametros, claves_validas or set(),
                                                   eventos_validos or set(EVENTOS_TRIGGER))
    p = dict(parametros or {})
    if tipo == TipoTrigger.tiempo_fijo:
        if "cada_dias" in p:
            if not isinstance(p["cada_dias"], int) or p["cada_dias"] < 1:
                raise ErrorAPI(422, "TRIGGER_INVALIDO", "cada_dias debe ser un entero positivo")
            return {"cada_dias": p["cada_dias"]}
        cada, unidad = p.get("cada"), p.get("unidad")
        if not isinstance(cada, int) or cada < 1 or unidad not in ("dias", "semanas", "meses"):
            raise ErrorAPI(422, "TRIGGER_INVALIDO", "tiempo_fijo requiere {cada_dias: N} o {cada: N, unidad: dias|semanas|meses}")
        return {"cada": cada, "unidad": unidad}
    # calendario: {"mes": M, "dia": D} o {"fechas": ["MM-DD" | "AAAA-MM-DD", ...]}
    if "fechas" in p:
        fechas = p["fechas"]
        if not isinstance(fechas, list) or not fechas:
            raise ErrorAPI(422, "TRIGGER_INVALIDO", "fechas debe ser una lista no vacía")
        for f in fechas:
            partes = str(f).split("-")
            if len(partes) not in (2, 3) or not all(x.isdigit() for x in partes):
                raise ErrorAPI(422, "TRIGGER_INVALIDO", f"Fecha inválida: {f} (usa MM-DD o AAAA-MM-DD)")
            mes, dia = int(partes[-2]), int(partes[-1])
            if not (1 <= mes <= 12 and 1 <= dia <= 31):
                raise ErrorAPI(422, "TRIGGER_INVALIDO", f"Fecha inválida: {f}")
        return {"fechas": [str(f) for f in fechas]}
    mes, dia = p.get("mes"), p.get("dia")
    if not isinstance(mes, int) or not isinstance(dia, int) or not (1 <= mes <= 12 and 1 <= dia <= 31):
        raise ErrorAPI(422, "TRIGGER_INVALIDO", "calendario requiere {mes: 1-12, dia: 1-31} o {fechas: [...]}")
    return {"mes": mes, "dia": dia}


def _fecha_segura(anio: int, mes: int, dia: int) -> date:
    return date(anio, mes, min(dia, calendar.monthrange(anio, mes)[1]))


def sumar_meses(d: date, meses: int) -> date:
    total = d.month - 1 + meses
    anio, mes = d.year + total // 12, total % 12 + 1
    return _fecha_segura(anio, mes, d.day)


def proxima_fecha_trigger(tipo: TipoTrigger, parametros: dict[str, Any], desde: date, hoy: date | None = None) -> date | None:
    """Próxima fecha de activación a partir de `desde` (última ejecución o fecha de alta). Meses de distinta longitud se
    recortan al último día. Para calendario devuelve la primera fecha fija posterior a `desde`."""
    hoy = hoy or date.today()
    if tipo == TipoTrigger.tiempo_fijo:
        if "cada_dias" in parametros:
            return desde + timedelta(days=int(parametros["cada_dias"]))
        cada, unidad = int(parametros["cada"]), parametros["unidad"]
        if unidad == "meses":
            return sumar_meses(desde, cada)
        return desde + timedelta(days=cada * UNIDADES[unidad])
    if TipoTrigger(tipo) == TipoTrigger.calendario:
        candidatas: list[date] = []
        if "fechas" in parametros:
            for f in parametros["fechas"]:
                partes = [int(x) for x in str(f).split("-")]
                if len(partes) == 3:
                    candidatas.append(_fecha_segura(*partes))
                else:
                    for anio in (desde.year, desde.year + 1, desde.year + 2):
                        candidatas.append(_fecha_segura(anio, partes[0], partes[1]))
        else:
            for anio in (desde.year, desde.year + 1, desde.year + 2):
                candidatas.append(_fecha_segura(anio, int(parametros["mes"]), int(parametros["dia"])))
        futuras = sorted(c for c in candidatas if c > desde)
        return futuras[0] if futuras else None
    return None  # Fase 2


def proxima_fecha_plan(triggers: list[PlanTrigger], desde: date, hoy: date | None = None) -> date | None:
    """Próxima fecha de los triggers **por fecha**. La de los triggers por medidor la proyecta
    `triggers_service.proyeccion` con el uso real, porque necesita leer la base."""
    fechas = [f for t in triggers if t.tipo_trigger in TRIGGERS_POR_FECHA
              for f in [proxima_fecha_trigger(t.tipo_trigger, t.parametros_json or {}, desde, hoy)] if f]
    return min(fechas) if fechas else None


# ------------------------------------------------------------------ CRUD

def _prestador_de(actor: Actor, prestador_id: UUID | None) -> UUID:
    if actor.es_superadmin:
        if prestador_id is None:
            raise ErrorAPI(422, "PRESTADOR_REQUERIDO", "Indica prestador_id")
        return prestador_id
    if actor.prestador_id is None:
        raise prohibido("Tu usuario no pertenece a un prestador")
    return actor.prestador_id


def exigir_edicion(actor: Actor) -> None:
    if actor.rol not in EDITAN:
        raise prohibido("Solo Admin prestador y Despachador administran planes")


async def obtener(db: AsyncSession, actor: Actor, plan_id: UUID) -> PlanMantenimiento:
    plan = await db.get(PlanMantenimiento, plan_id)
    if plan is None:
        raise no_encontrado("Plan")
    if actor.dominio == Dominio.prestador and plan.prestador_id != actor.prestador_id:
        raise no_encontrado("Plan")
    if actor.dominio == Dominio.tenant:
        if plan.tenant_id not in (None, actor.tenant_id) or plan.prestador_id not in await catalogos_service.prestadores_del_tenant(db, actor.tenant_id):
            raise no_encontrado("Plan")
    return plan


async def listar(db: AsyncSession, actor: Actor, prestador_id: UUID | None, tipo_equipo_id: UUID | None, solo_activos: bool) -> list[PlanMantenimiento]:
    consulta = select(PlanMantenimiento).order_by(PlanMantenimiento.nombre)
    if actor.dominio == Dominio.tenant:
        consulta = consulta.where(PlanMantenimiento.prestador_id.in_(await catalogos_service.prestadores_del_tenant(db, actor.tenant_id)),
                                  (PlanMantenimiento.tenant_id.is_(None)) | (PlanMantenimiento.tenant_id == actor.tenant_id))
    else:
        consulta = consulta.where(PlanMantenimiento.prestador_id == _prestador_de(actor, prestador_id))
    if tipo_equipo_id:
        consulta = consulta.where(PlanMantenimiento.tipo_equipo_id == tipo_equipo_id)
    if solo_activos:
        consulta = consulta.where(PlanMantenimiento.estado == EstadoPlan.activo)
    return list((await db.execute(consulta)).scalars())


def _triggers_salida(triggers: list[PlanTrigger]) -> list[dict[str, Any]]:
    """Los combinados guardan claves; la interfaz trabaja con ids, así que se resuelven aquí."""
    por_clave = {t.clave: t for t in triggers}
    salida = []
    for t in triggers:
        parametros = dict(t.parametros_json or {})
        if t.tipo_trigger == TipoTrigger.combinado:
            parametros["triggers_ids"] = [str(por_clave[c].id) for c in parametros.get("triggers_claves", []) if c in por_clave]
        salida.append({"id": t.id, "clave": t.clave, "tipo_trigger": t.tipo_trigger, "parametros_json": parametros,
                       "logica_combinacion": t.logica_combinacion})
    return salida


async def detalle(db: AsyncSession, plan: PlanMantenimiento) -> dict[str, Any]:
    triggers = (await db.execute(select(PlanTrigger).where(PlanTrigger.plan_id == plan.id).order_by(PlanTrigger.clave))).scalars().all()
    tareas = (await db.execute(select(PlanTarea).where(PlanTarea.plan_id == plan.id).order_by(PlanTarea.orden))).scalars().all()
    materiales = (await db.execute(select(PlanMaterial).where(PlanMaterial.plan_id == plan.id).order_by(PlanMaterial.created_at))).scalars().all()
    equipos = (await db.execute(select(EquipoPlan).where(EquipoPlan.plan_id == plan.id))).scalars().all()
    tipo = await db.get(TipoEquipo, plan.tipo_equipo_id)
    formulario = await db.get(Formulario, plan.formulario_id) if plan.formulario_id else None
    return {
        **{k: getattr(plan, k) for k in ("id", "created_at", "updated_at", "version_hash", "prestador_id", "tenant_id", "tipo_equipo_id", "nombre",
                                         "descripcion", "version", "estado", "tiempo_ventana_dias", "formulario_id", "nivel_severidad_id", "created_by")},
        "tipo_equipo_nombre": tipo.nombre if tipo else None, "formulario_nombre": formulario.nombre if formulario else None,
        "triggers": _triggers_salida(list(triggers)),
        "tareas": [{"id": t.id, "orden": t.orden, "descripcion": t.descripcion, "tiempo_estimado_min": t.tiempo_estimado_min, "habilidad_requerida_id": t.habilidad_requerida_id} for t in tareas],
        "materiales": [{"id": m.id, "articulo_id": m.articulo_id, "descripcion": m.descripcion, "cantidad_estandar": m.cantidad_estandar, "unidad": m.unidad} for m in materiales],
        "equipos": [{"id": e.id, "equipo_id": e.equipo_id, "tenant_id": e.tenant_id, "activo": e.activo, "fecha_proxima_ejecucion": e.fecha_proxima_ejecucion,
                     "fecha_ultima_ejecucion": e.fecha_ultima_ejecucion, "fecha_alta": e.fecha_alta,
                     "ultimo_valor_medidor": e.ultimo_valor_medidor} for e in equipos],
    }


async def _validar_encabezado(db: AsyncSession, prestador_id: UUID, datos: dict[str, Any]) -> None:
    tipo = await db.get(TipoEquipo, datos["tipo_equipo_id"])
    if tipo is None or (tipo.tenant_id is not None and datos.get("tenant_id") not in (None, tipo.tenant_id)):
        raise ErrorAPI(422, "TIPO_EQUIPO_INVALIDO", "El tipo de equipo no existe o es de otro cliente")
    if datos.get("tenant_id") and datos["tenant_id"] not in await _tenants_del_prestador(db, prestador_id):
        raise ErrorAPI(422, "TENANT_NO_VINCULADO", "El cliente no está vinculado a este prestador")
    if datos.get("formulario_id"):
        f = await db.get(Formulario, datos["formulario_id"])
        if f is None or f.tipo != TipoFormulario.preventivo or f.estado != EstadoFormulario.publicado or (f.prestador_id not in (None, prestador_id)):
            raise ErrorAPI(422, "FORMULARIO_INVALIDO", "El formulario debe ser de tipo preventivo, publicado y del prestador")
    if datos.get("nivel_severidad_id"):
        n = await db.get(NivelSeveridadCatalogo, datos["nivel_severidad_id"])
        if n is None or n.prestador_id != prestador_id:
            raise ErrorAPI(422, "SEVERIDAD_INVALIDA", "Nivel de severidad de otro prestador")


async def _tenants_del_prestador(db: AsyncSession, prestador_id: UUID) -> list[UUID]:
    from models.organizaciones import TenantPrestador

    return list((await db.execute(select(TenantPrestador.tenant_id).where(TenantPrestador.prestador_id == prestador_id))).scalars())


async def _eventos_validos(db: AsyncSession) -> set[str]:
    return {c for c in (await db.execute(select(EventoTriggerCatalogo.clave).where(
        EventoTriggerCatalogo.activo.is_(True)))).scalars()} or set(EVENTOS_TRIGGER)


async def _guardar_triggers(db: AsyncSession, plan: PlanMantenimiento, triggers: list[dict]) -> None:
    """Upsert por `clave`: los triggers conservan su id entre ediciones, que es lo que necesita el combinado.

    Dos pasadas: primero los triggers simples (ya sabemos todas las claves del plan) y después los combinados, que
    se validan contra esas claves. `triggers_ids` del payload se traduce a claves con los triggers que ya existen.
    """
    existentes = {t.clave: t for t in (await db.execute(select(PlanTrigger).where(PlanTrigger.plan_id == plan.id))).scalars()}
    por_id = {str(t.id): clave for clave, t in existentes.items()}
    eventos = await _eventos_validos(db)

    # Claves definitivas: la que trae el payload (si no choca) o `tN` por posición.
    entradas: list[tuple[str, dict]] = []
    usadas: set[str] = set()
    for i, t in enumerate(triggers, start=1):
        clave = str(t.get("clave") or "").strip() or f"t{i}"
        while clave in usadas:
            clave = f"{clave}_{i}"
        usadas.add(clave)
        entradas.append((clave, t))
    claves_validas = set(usadas)

    def _traducir(p: dict[str, Any]) -> dict[str, Any]:
        """`triggers_ids` (lo que maneja la interfaz) → `triggers_claves` (lo que se guarda)."""
        p = dict(p or {})
        if p.get("triggers_claves"):
            return p
        claves = [por_id.get(str(x)) or str(x) for x in (p.get("triggers_ids") or [])]
        p["triggers_claves"] = [c for c in claves if c]
        return p

    orden = sorted(entradas, key=lambda e: 1 if TipoTrigger(e[1]["tipo_trigger"]) == TipoTrigger.combinado else 0)
    for clave, t in orden:
        tipo = TipoTrigger(t["tipo_trigger"])
        crudos = t.get("parametros_json") or {}
        if tipo == TipoTrigger.combinado:
            crudos = _traducir(crudos)
        parametros = validar_trigger(tipo, crudos, claves_validas, eventos)
        fila = existentes.get(clave)
        if fila is None:
            fila = PlanTrigger(plan_id=plan.id, prestador_id=plan.prestador_id, clave=clave)
            db.add(fila)
        fila.tipo_trigger = tipo
        fila.parametros_json = parametros
        fila.logica_combinacion = t.get("logica_combinacion") or parametros.get("logica")
    for clave, fila in existentes.items():
        if clave not in claves_validas:
            await db.delete(fila)
    await db.flush()


async def _reemplazar_hijos(db: AsyncSession, plan: PlanMantenimiento, triggers: list[dict] | None, tareas: list[dict] | None, materiales: list[dict] | None) -> None:
    if triggers is not None:
        await _guardar_triggers(db, plan, triggers)
    if tareas is not None:
        for t in (await db.execute(select(PlanTarea).where(PlanTarea.plan_id == plan.id))).scalars():
            await db.delete(t)
        for i, t in enumerate(tareas, start=1):
            if t.get("habilidad_requerida_id"):
                h = await db.get(Habilidad, t["habilidad_requerida_id"])
                if h is None or h.prestador_id != plan.prestador_id:
                    raise ErrorAPI(422, "HABILIDAD_INVALIDA", "La habilidad no existe o es de otro prestador")
            db.add(PlanTarea(plan_id=plan.id, prestador_id=plan.prestador_id, orden=t.get("orden") or i, descripcion=t["descripcion"],
                             tiempo_estimado_min=t.get("tiempo_estimado_min") or 0, habilidad_requerida_id=t.get("habilidad_requerida_id")))
    if materiales is not None:
        for m in (await db.execute(select(PlanMaterial).where(PlanMaterial.plan_id == plan.id))).scalars():
            await db.delete(m)
        for m in materiales:
            db.add(PlanMaterial(plan_id=plan.id, prestador_id=plan.prestador_id, articulo_id=m.get("articulo_id"), descripcion=m["descripcion"],
                                cantidad_estandar=m.get("cantidad_estandar") or 1, unidad=m.get("unidad") or "pieza"))
    await db.flush()


async def crear(db: AsyncSession, actor: Actor, datos: dict[str, Any], request: Request | None, prestador_id: UUID | None = None) -> PlanMantenimiento:
    exigir_edicion(actor)
    p = _prestador_de(actor, prestador_id)
    await _validar_encabezado(db, p, datos)
    plan = PlanMantenimiento(prestador_id=p, tenant_id=datos.get("tenant_id"), tipo_equipo_id=datos["tipo_equipo_id"], nombre=datos["nombre"],
                             descripcion=datos.get("descripcion") or "", tiempo_ventana_dias=datos.get("tiempo_ventana_dias", 7), formulario_id=datos.get("formulario_id"),
                             nivel_severidad_id=datos.get("nivel_severidad_id"), created_by=actor.id, estado=EstadoPlan(datos.get("estado") or "activo"))
    db.add(plan)
    await db.flush()
    await _reemplazar_hijos(db, plan, datos.get("triggers") or [], datos.get("tareas") or [], datos.get("materiales") or [])
    await auditoria.registrar_actor(db, actor, "planes.alta", request, recurso_tipo="plan_mantenimiento", recurso_id=plan.id, prestador_id=p,
                                    tenant_id=plan.tenant_id, despues={"nombre": plan.nombre, "triggers": datos.get("triggers")})
    return plan


async def editar(db: AsyncSession, actor: Actor, plan: PlanMantenimiento, cambios: dict[str, Any], request: Request | None) -> PlanMantenimiento:
    exigir_edicion(actor)
    if actor.dominio == Dominio.prestador and plan.prestador_id != actor.prestador_id:
        raise no_encontrado("Plan")
    encabezado = {k: v for k, v in cambios.items() if k in ("tenant_id", "tipo_equipo_id", "nombre", "descripcion", "estado", "tiempo_ventana_dias", "formulario_id", "nivel_severidad_id")}
    if encabezado:
        await _validar_encabezado(db, plan.prestador_id, {"tipo_equipo_id": plan.tipo_equipo_id, "tenant_id": plan.tenant_id, **encabezado})
        antes = auditoria.instantanea(plan)
        for k, v in encabezado.items():
            setattr(plan, k, EstadoPlan(v) if k == "estado" else v)
        await auditoria.registrar_actor(db, actor, "planes.modificacion", request, recurso_tipo="plan_mantenimiento", recurso_id=plan.id,
                                        prestador_id=plan.prestador_id, tenant_id=plan.tenant_id, antes=antes, despues=auditoria.instantanea(plan))
    await _reemplazar_hijos(db, plan, cambios.get("triggers"), cambios.get("tareas"), cambios.get("materiales"))
    if encabezado or any(k in cambios for k in ("triggers", "tareas", "materiales")):
        plan.version += 1  # una edición = una versión, cambie el encabezado, los hijos o ambos
    if any(k in cambios for k in ("triggers", "tareas", "materiales")):
        # Al cambiar los triggers se recalcula la próxima fecha de los equipos sin ejecución pendiente.
        await recalcular_proximas_fechas(db, plan)
    await db.flush()
    return plan


async def recalcular_proximas_fechas(db: AsyncSession, plan: PlanMantenimiento) -> None:
    """Próxima fecha de cada equipo del plan. Con triggers por medidor o por evento la calcula `triggers_service`,
    que sabe leer el uso real; con los de fecha basta el calendario."""
    from services import triggers_service

    triggers = (await db.execute(select(PlanTrigger).where(PlanTrigger.plan_id == plan.id))).scalars().all()
    tipos = {t.tipo_trigger for t in triggers}
    for ep in (await db.execute(select(EquipoPlan).where(EquipoPlan.plan_id == plan.id, EquipoPlan.activo.is_(True)))).scalars():
        if tipos - TRIGGERS_POR_FECHA:
            equipo = await db.get(Equipo, ep.equipo_id)
            if equipo is not None:
                await triggers_service._proyectar_asignacion(db, plan, ep, equipo, list(triggers), date.today())
                continue
        ep.fecha_proxima_ejecucion = proxima_fecha_plan(triggers, ep.fecha_ultima_ejecucion or ep.fecha_alta)


# --------------------------------------------------------- planes por equipo

async def asignar_equipo(db: AsyncSession, actor: Actor, plan: PlanMantenimiento, equipo_id: UUID, fecha_base: date | None, request: Request | None) -> EquipoPlan:
    exigir_edicion(actor)
    equipo = await db.get(Equipo, equipo_id)
    if equipo is None or equipo.tipo_equipo_id != plan.tipo_equipo_id:
        raise ErrorAPI(422, "EQUIPO_INVALIDO", "El equipo no existe o no es del tipo del plan")
    if plan.tenant_id and equipo.tenant_id != plan.tenant_id:
        raise ErrorAPI(422, "EQUIPO_INVALIDO", "El equipo es de otro cliente")
    if equipo.tenant_id not in await _tenants_del_prestador(db, plan.prestador_id):
        raise ErrorAPI(422, "EQUIPO_INVALIDO", "El cliente del equipo no está vinculado al prestador")
    existente = (await db.execute(select(EquipoPlan).where(EquipoPlan.plan_id == plan.id, EquipoPlan.equipo_id == equipo.id))).scalar_one_or_none()
    triggers = (await db.execute(select(PlanTrigger).where(PlanTrigger.plan_id == plan.id))).scalars().all()
    base = fecha_base or date.today()
    if existente is None:
        existente = EquipoPlan(equipo_id=equipo.id, plan_id=plan.id, prestador_id=plan.prestador_id, tenant_id=equipo.tenant_id, fecha_alta=base)
        db.add(existente)
    existente.activo = True
    existente.fecha_alta = base
    existente.fecha_proxima_ejecucion = proxima_fecha_plan(triggers, existente.fecha_ultima_ejecucion or base)
    await db.flush()
    if {t.tipo_trigger for t in triggers} - TRIGGERS_POR_FECHA:
        # Con triggers por medidor o por evento la fecha la proyecta el uso real, no el calendario.
        from services import triggers_service

        await triggers_service._proyectar_asignacion(db, plan, existente, equipo, list(triggers), date.today())
    await auditoria.registrar_actor(db, actor, "planes.equipo_asignado", request, recurso_tipo="plan_mantenimiento", recurso_id=plan.id,
                                    prestador_id=plan.prestador_id, tenant_id=equipo.tenant_id,
                                    despues={"equipo_id": equipo.id, "fecha_proxima_ejecucion": existente.fecha_proxima_ejecucion})
    return existente


async def desactivar_equipo(db: AsyncSession, actor: Actor, plan: PlanMantenimiento, equipo_id: UUID, request: Request | None) -> None:
    exigir_edicion(actor)
    ep = (await db.execute(select(EquipoPlan).where(EquipoPlan.plan_id == plan.id, EquipoPlan.equipo_id == equipo_id))).scalar_one_or_none()
    if ep is None:
        raise no_encontrado("Asignación del plan")
    ep.activo = False
    await db.flush()
    await auditoria.registrar_actor(db, actor, "planes.equipo_desactivado", request, recurso_tipo="plan_mantenimiento", recurso_id=plan.id,
                                    prestador_id=plan.prestador_id, tenant_id=ep.tenant_id, despues={"equipo_id": equipo_id})


async def planes_del_equipo(db: AsyncSession, equipo_id: UUID) -> list[tuple[EquipoPlan, PlanMantenimiento]]:
    return list((await db.execute(select(EquipoPlan, PlanMantenimiento).join(PlanMantenimiento, PlanMantenimiento.id == EquipoPlan.plan_id)
                                  .where(EquipoPlan.equipo_id == equipo_id))).all())
