"""Ficha de activos, depreciación con los cuatro métodos de §6.9.4, TCO por período y análisis reemplazar vs. reparar.
La criticidad A/B/C/D y el FMEA los calcula `criticidad_service` (ISO 55000, F2-05) y la ficha los muestra con su
origen; el MTBF y el MTTR por activo siguen pendientes. P09."""
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.dependencias import Actor
from core.errors import ErrorAPI, no_encontrado, prohibido
from models.activos import ActivoDepreciacion, ActivoDepreciacionHistorial, ActivoReemplazoAlerta, ActivoTCOSnapshot, DecisionReemplazo, MetodoDepreciacion
from models.auditoria import ConfiguracionTenant
from models.base import Dominio, Rol
from models.catalogos import Equipo, TipoEquipo
from models.contratos import Contrato
from models.costos import FolioCosto
from models.folios import EstadoFolio, Folio, FolioRefaccion, TipoFolio
from models.unidades import UnidadNegocio
from models.usuarios import Usuario
from services import alertas_service, auditoria, notificaciones_service, permisos_service
from services.folio_estados import ACTOR_SISTEMA, ActorFolio
from services.preventivos_service import _unidades_visibles

CONSULTAN = {Rol.superadmin, Rol.admin_empresa, Rol.admin_un, Rol.supervisor_operadores, Rol.admin_prestador, Rol.mesa_control, Rol.despachador,
             Rol.direccion_prestador, Rol.supervisor_prestador}
CONFIGURAN = {Rol.superadmin, Rol.admin_empresa}
CERO = Decimal("0")
CENTAVO = Decimal("0.01")
UMBRAL_DEFECTO = Decimal("70")
CLAVE_UMBRAL = "umbral_reemplazo_pct"
# F2-04: el método «unidades de producción» ya funciona; estos dos avisos son lo que falta por configurar.
MENSAJE_MEDIDORES = "MEDIDOR_NO_CONFIGURADO"
MENSAJE_SIN_VIDA_UNIDADES = "SIN_VIDA_UTIL_EN_UNIDADES"
TIPOS_CORRECTIVOS = (TipoFolio.correctivo, TipoFolio.especial)


def periodo_de(d: date) -> str:
    return f"{d.year}-{d.month:02d}"


async def umbral_reemplazo(db: AsyncSession, tenant_id: UUID) -> Decimal:
    fila = (await db.execute(select(ConfiguracionTenant).where(ConfiguracionTenant.tenant_id == tenant_id,
                                                               ConfiguracionTenant.clave == CLAVE_UMBRAL))).scalar_one_or_none()
    try:
        return Decimal(str(fila.valor)) if fila is not None else UMBRAL_DEFECTO
    except Exception:  # noqa: BLE001
        return UMBRAL_DEFECTO


async def guardar_umbral(db: AsyncSession, actor: Actor, tenant_id: UUID, valor: Decimal, request: Request | None = None) -> Decimal:
    if not actor.es_superadmin and actor.rol not in CONFIGURAN:
        raise prohibido("Solo el Admin empresa configura el umbral de reemplazo")
    fila = (await db.execute(select(ConfiguracionTenant).where(ConfiguracionTenant.tenant_id == tenant_id,
                                                               ConfiguracionTenant.clave == CLAVE_UMBRAL))).scalar_one_or_none()
    if fila is None:
        fila = ConfiguracionTenant(tenant_id=tenant_id, clave=CLAVE_UMBRAL, valor=float(valor))
        db.add(fila)
    else:
        fila.valor = float(valor)
    await db.flush()
    await auditoria.registrar_actor(db, actor, "activos.umbral_reemplazo", request, tenant_id=tenant_id, recurso_tipo="configuracion_tenant",
                                    recurso_id=fila.id, despues={"umbral_reemplazo_pct": float(valor)})
    return valor


async def obtener_equipo(db: AsyncSession, actor: Actor, equipo_id: UUID) -> Equipo:
    if not actor.es_superadmin and actor.rol not in CONSULTAN and actor.rol != Rol.tecnico:
        raise prohibido("Tu rol no consulta la ficha de activos")
    e = await db.get(Equipo, equipo_id)
    if e is None:
        raise no_encontrado("Equipo")
    if actor.es_superadmin:
        return e
    if actor.rol == Rol.tecnico:
        permisos = {p["clave"]: p["habilitado"] for p in await permisos_service.efectivos_de_tecnico(db, actor.prestador_id, actor.id)}
        if not permisos.get("ver_historial_equipo", False):
            raise prohibido("No tienes habilitado ver_historial_equipo (§6.8.3)")
        from services import catalogos_service

        if actor.prestador_id not in await catalogos_service.prestadores_del_tenant(db, e.tenant_id):
            raise no_encontrado("Equipo")
        return e
    if actor.dominio == Dominio.tenant:
        if e.tenant_id != actor.tenant_id:
            raise no_encontrado("Equipo")
        unidades = await _unidades_visibles(db, actor)
        if unidades is not None and e.un_id not in set(unidades):
            raise no_encontrado("Equipo")
        return e
    from services import catalogos_service

    if actor.prestador_id in await catalogos_service.prestadores_del_tenant(db, e.tenant_id):
        return e
    raise no_encontrado("Equipo")


# ------------------------------------------------------------ depreciación

async def configuracion(db: AsyncSession, equipo_id: UUID) -> ActivoDepreciacion | None:
    return (await db.execute(select(ActivoDepreciacion).where(ActivoDepreciacion.equipo_id == equipo_id))).scalar_one_or_none()


async def guardar_depreciacion(db: AsyncSession, actor: Actor, equipo: Equipo, datos: dict[str, Any], request: Request | None = None) -> ActivoDepreciacion:
    if not actor.es_superadmin and actor.rol not in CONFIGURAN:
        raise prohibido("Solo el Admin empresa configura la depreciación del activo")
    if datos.get("equipo_medidor_id") is not None:
        # F2-04: el medidor de la depreciación tiene que ser uno de los del propio equipo.
        from models.medidores import EquipoMedidor

        m = await db.get(EquipoMedidor, datos["equipo_medidor_id"])
        if m is None or m.equipo_id != equipo.id:
            raise ErrorAPI(422, "MEDIDOR_INVALIDO", "Ese medidor no es de este equipo")
    d = await configuracion(db, equipo.id)
    if d is None:
        d = ActivoDepreciacion(equipo_id=equipo.id, tenant_id=equipo.tenant_id)
        db.add(d)
    antes = auditoria.instantanea(d)
    for k, v in datos.items():
        if v is not None:
            setattr(d, k, v)
    d.configurado_por = actor.id
    await db.flush()
    await auditoria.registrar_actor(db, actor, "activos.depreciacion_configurada", request, tenant_id=equipo.tenant_id, recurso_tipo="activo_depreciacion",
                                    recurso_id=d.id, antes=antes, despues=auditoria.instantanea(d))
    return d


def _meses(desde: date, hasta: date) -> int:
    return max(0, (hasta.year - desde.year) * 12 + (hasta.month - desde.month))


def valor_en_libros(equipo: Equipo, d: ActivoDepreciacion | None, hasta: date,
                    unidades_usadas: Decimal | None = None, unidades_periodo: Decimal | None = None) -> tuple[Decimal, Decimal, str]:
    """Devuelve (valor_en_libros, depreciacion_del_periodo, aviso). Los cuatro métodos literales de §6.9.4.

    `unidades_usadas` son las unidades que lleva el activo desde que empezó a depreciarse y `unidades_periodo` las
    del período; las lee `libros_con_unidades()` del medidor configurado (F2-04, ACT-8.3). Sin medidor se usa el
    campo manual `unidades_acumuladas`, que es lo que había en P09."""
    costo = equipo.costo_adquisicion or CERO
    if d is None or costo <= CERO:
        return costo, CERO, ""
    salvamento = d.valor_salvamento or CERO
    base = max(costo - salvamento, CERO)
    meses = _meses(d.fecha_inicio, hasta)
    if d.metodo == MetodoDepreciacion.manual:
        return (d.valor_en_libros_manual if d.valor_en_libros_manual is not None else costo), CERO, ""
    if d.metodo == MetodoDepreciacion.unidades_produccion:
        # §6.9.4: depreciación del período = (costo − residual) × (unidades del período ÷ vida útil en unidades).
        vida = Decimal(d.unidades_vida_util or 0)
        if vida <= CERO:
            return (d.valor_en_libros_manual if d.valor_en_libros_manual is not None else costo), CERO, MENSAJE_SIN_VIDA_UNIDADES
        usadas = unidades_usadas if unidades_usadas is not None else Decimal(d.unidades_acumuladas or 0)
        periodo = unidades_periodo if unidades_periodo is not None else CERO
        acumulada = min(base, (base * max(CERO, usadas) / vida).quantize(CENTAVO))
        previas = min(base, (base * max(CERO, usadas - max(CERO, periodo)) / vida).quantize(CENTAVO))
        aviso = "" if d.equipo_medidor_id is not None else MENSAJE_MEDIDORES
        return (costo - acumulada).quantize(CENTAVO), (acumulada - previas).quantize(CENTAVO), aviso
    vida_meses = max(1, (d.vida_util_anios or 1) * 12)
    if d.metodo == MetodoDepreciacion.linea_recta:
        por_mes = (base / vida_meses).quantize(CENTAVO)
        acumulada = min(base, (por_mes * meses).quantize(CENTAVO))
        return (costo - acumulada).quantize(CENTAVO), (por_mes if acumulada < base else CERO), ""
    # Doble saldo decreciente: tasa 2/vida sobre el valor en libros, sin bajar del salvamento.
    tasa_mensual = Decimal("2") / Decimal(str(vida_meses))
    valor = costo
    ultimo = CERO
    for _ in range(meses):
        if valor <= salvamento:
            valor, ultimo = salvamento, CERO
            break
        ultimo = (valor * tasa_mensual).quantize(CENTAVO)
        if valor - ultimo < salvamento:
            ultimo = (valor - salvamento).quantize(CENTAVO)
        valor = (valor - ultimo).quantize(CENTAVO)
    return valor, ultimo, ""


async def unidades_del_activo(db: AsyncSession, d: ActivoDepreciacion | None, hasta: date) -> tuple[Decimal | None, Decimal | None]:
    """(unidades desde el inicio de la depreciación, unidades del período) leídas del medidor configurado.
    Devuelve (None, None) cuando no hay medidor: entonces manda el campo manual. F2-04, ACT-8.3."""
    if d is None or d.metodo != MetodoDepreciacion.unidades_produccion or d.equipo_medidor_id is None:
        return None, None
    from services import medidores_service

    inicio = d.unidades_al_inicio
    if inicio is None:
        inicio = await medidores_service.acumulado_a_la_fecha(db, d.equipo_medidor_id, d.fecha_inicio)
    acumulado = await medidores_service.acumulado_a_la_fecha(db, d.equipo_medidor_id, hasta)
    usadas = max(CERO, (Decimal(acumulado) - Decimal(inicio)).quantize(CENTAVO))
    primer_dia = date(hasta.year, hasta.month, 1)
    del_periodo = await medidores_service.unidades_entre(db, d.equipo_medidor_id, primer_dia - timedelta(days=1), hasta)
    return usadas, min(usadas, del_periodo)


async def libros_con_unidades(db: AsyncSession, equipo: Equipo, d: ActivoDepreciacion | None,
                              hasta: date) -> tuple[Decimal, Decimal, str, Decimal | None, Decimal | None]:
    """`valor_en_libros` resolviendo antes las unidades del medidor. Devuelve además las unidades, que el historial
    guarda para que se pueda auditar el cálculo."""
    usadas, periodo = await unidades_del_activo(db, d, hasta)
    libros, dep, aviso = valor_en_libros(equipo, d, hasta, usadas, periodo)
    return libros, dep, aviso, usadas, periodo


async def calcular_depreciacion(db: AsyncSession, equipo: Equipo, hasta: date | None = None) -> ActivoDepreciacionHistorial | None:
    """Tarea mensual: escribe el valor en libros del período en `activo_depreciacion_historial` (idempotente por período)."""
    hasta = hasta or date.today()
    d = await configuracion(db, equipo.id)
    if d is None or (equipo.costo_adquisicion or CERO) <= CERO:
        return None
    periodo = periodo_de(hasta)
    existente = (await db.execute(select(ActivoDepreciacionHistorial).where(ActivoDepreciacionHistorial.equipo_id == equipo.id,
                                                                            ActivoDepreciacionHistorial.periodo == periodo))).scalar_one_or_none()
    if existente is not None:
        return existente
    libros, periodo_dep, _aviso, usadas, unidades_periodo = await libros_con_unidades(db, equipo, d, hasta)
    h = ActivoDepreciacionHistorial(equipo_id=equipo.id, tenant_id=equipo.tenant_id, periodo=periodo, valor_en_libros=libros,
                                    depreciacion_periodo=periodo_dep, depreciacion_acumulada=((equipo.costo_adquisicion or CERO) - libros).quantize(CENTAVO),
                                    metodo_aplicado=d.metodo, unidades_periodo=unidades_periodo, unidades_acumuladas=usadas)
    db.add(h)
    await db.flush()
    # El acumulado del medidor también queda en la configuración: es lo que la ficha muestra sin recalcular.
    if usadas is not None:
        d.unidades_acumuladas = usadas
        await db.flush()
    return h


async def historial_depreciacion(db: AsyncSession, equipo_id: UUID, limite: int = 36) -> list[ActivoDepreciacionHistorial]:
    return list((await db.execute(select(ActivoDepreciacionHistorial).where(ActivoDepreciacionHistorial.equipo_id == equipo_id)
                                   .order_by(ActivoDepreciacionHistorial.periodo.desc()).limit(limite))).scalars())


# -------------------------------------------------------------------- TCO

async def costo_hora_inactividad(db: AsyncSession, equipo: Equipo) -> Decimal:
    """El valor del equipo manda; si no, el default del tipo de equipo que configura el tenant (§6.9.4)."""
    if equipo.costo_hora_inactividad is not None:
        return equipo.costo_hora_inactividad
    tipo = await db.get(TipoEquipo, equipo.tipo_equipo_id)
    return (tipo.costo_hora_inactividad_default if tipo and tipo.costo_hora_inactividad_default is not None else CERO)


async def componentes_tco(db: AsyncSession, equipo: Equipo, hasta: date | None = None) -> dict[str, Any]:
    """Los seis componentes literales de §6.9.4. `costo_refacciones` es el desglose ya contenido en preventivos y correctivos."""
    hasta = hasta or date.today()
    limite = datetime.combine(hasta, datetime.max.time(), tzinfo=UTC)
    folios = list((await db.execute(select(Folio).where(Folio.equipo_id == equipo.id, Folio.estado == EstadoFolio.cerrado,
                                                        Folio.fecha_cierre <= limite))).scalars())
    costos = {c.folio_id: c for c in (await db.execute(select(FolioCosto).where(
        FolioCosto.folio_id.in_([f.id for f in folios])))).scalars()} if folios else {}
    preventivos = sum((costos[f.id].costo_total for f in folios if f.tipo_folio == TipoFolio.preventivo and f.id in costos), CERO)
    correctivos = sum((costos[f.id].costo_total for f in folios if f.tipo_folio in TIPOS_CORRECTIVOS and f.id in costos), CERO)
    refacciones = CERO
    if folios:
        refacciones = Decimal(str((await db.execute(select(func.coalesce(func.sum(FolioRefaccion.cantidad * FolioRefaccion.costo_unitario), 0)).where(
            FolioRefaccion.folio_id.in_([f.id for f in folios])))).scalar() or 0))
    horas = CERO
    for f in folios:
        if f.tipo_folio in TIPOS_CORRECTIVOS and f.fecha_cierre and f.fecha_falla:
            horas += Decimal(str(round((f.fecha_cierre - f.fecha_falla).total_seconds() / 3600, 2)))
    tarifa = await costo_hora_inactividad(db, equipo)
    downtime = (horas * tarifa).quantize(CENTAVO)
    d = await configuracion(db, equipo.id)
    residual, _dep, aviso, _usadas, _periodo = await libros_con_unidades(db, equipo, d, hasta)
    adquisicion = equipo.costo_adquisicion or CERO
    reposicion = (d.valor_reposicion if d and d.valor_reposicion else equipo.valor_reposicion) or CERO
    tco = (adquisicion + preventivos + correctivos + downtime - residual).quantize(CENTAVO)
    pct = (tco / reposicion * 100).quantize(CENTAVO) if reposicion > CERO else CERO
    return {"periodo": periodo_de(hasta), "costo_adquisicion": adquisicion, "costo_preventivos": Decimal(str(preventivos)).quantize(CENTAVO),
            "costo_correctivos": Decimal(str(correctivos)).quantize(CENTAVO), "costo_refacciones": refacciones.quantize(CENTAVO),
            "costo_downtime": downtime, "horas_downtime": horas.quantize(CENTAVO), "valor_residual": residual, "tco_total": tco,
            "valor_reposicion": reposicion or None, "porcentaje_vs_reposicion": pct, "folios": len(folios), "aviso": aviso}


async def calcular_tco(db: AsyncSession, equipo: Equipo, hasta: date | None = None, actor: ActorFolio = ACTOR_SISTEMA) -> ActivoTCOSnapshot:
    """Snapshot del período (idempotente por equipo+período) y alerta de reemplazo cuando supera el umbral del tenant."""
    hasta = hasta or date.today()
    c = await componentes_tco(db, equipo, hasta)
    s = (await db.execute(select(ActivoTCOSnapshot).where(ActivoTCOSnapshot.equipo_id == equipo.id,
                                                           ActivoTCOSnapshot.periodo == c["periodo"]))).scalar_one_or_none()
    if s is None:
        s = ActivoTCOSnapshot(equipo_id=equipo.id, tenant_id=equipo.tenant_id, un_id=equipo.un_id, periodo=c["periodo"])
        db.add(s)
    for k in ("costo_adquisicion", "costo_preventivos", "costo_correctivos", "costo_refacciones", "costo_downtime", "horas_downtime",
              "valor_residual", "tco_total", "valor_reposicion", "porcentaje_vs_reposicion"):
        setattr(s, k, c[k])
    await db.flush()
    await _revisar_reemplazo(db, equipo, s, actor)
    return s


async def _revisar_reemplazo(db: AsyncSession, equipo: Equipo, s: ActivoTCOSnapshot, actor: ActorFolio) -> ActivoReemplazoAlerta | None:
    if not s.valor_reposicion or s.valor_reposicion <= CERO:
        return None
    umbral = await umbral_reemplazo(db, equipo.tenant_id)
    if s.porcentaje_vs_reposicion < umbral:
        return None
    abierta = (await db.execute(select(ActivoReemplazoAlerta).where(ActivoReemplazoAlerta.equipo_id == equipo.id,
                                                                     ActivoReemplazoAlerta.decision.is_(None)))).scalars().first()
    if abierta is not None:
        abierta.tco_al_momento, abierta.porcentaje_alcanzado = s.tco_total, s.porcentaje_vs_reposicion
        await db.flush()
        return abierta
    a = ActivoReemplazoAlerta(equipo_id=equipo.id, tenant_id=equipo.tenant_id, tco_al_momento=s.tco_total, valor_reposicion=s.valor_reposicion,
                              porcentaje_umbral=umbral, porcentaje_alcanzado=s.porcentaje_vs_reposicion)
    db.add(a)
    await db.flush()
    await alertas_service.disparar(db, "ACTIVO_REEMPLAZO", tenant_id=equipo.tenant_id, prestador_id=None, entidad_tipo="equipo", entidad_id=equipo.id,
                                   datos={"codigo": equipo.codigo, "tco": str(s.tco_total), "valor_reposicion": str(s.valor_reposicion),
                                          "porcentaje": str(s.porcentaje_vs_reposicion), "umbral": str(umbral), "alerta_id": str(a.id)})
    destinatarios = await notificaciones_service.destinatarios_por_rol(db, [Rol.admin_empresa], tenant_id=equipo.tenant_id)
    destinatarios += await notificaciones_service.destinatarios_por_rol(db, [Rol.admin_un], tenant_id=equipo.tenant_id, un_id=equipo.un_id)
    await notificaciones_service.notificar(db, "activo.reemplazo", destinatarios,
                                           {"equipo_id": str(equipo.id), "alerta_id": str(a.id), "porcentaje": str(s.porcentaje_vs_reposicion)},
                                           asunto=f"Reemplazo recomendado: {equipo.codigo} acumula {s.porcentaje_vs_reposicion}% de su valor de reposición",
                                           cuerpo=f"TCO ${s.tco_total:,.2f} contra ${s.valor_reposicion:,.2f} de reposición (umbral {umbral}%).",
                                           url=f"/activos/{equipo.id}", tenant_id=equipo.tenant_id)
    return a


async def calcular_mes(db: AsyncSession, hasta: date | None = None) -> dict[str, int]:
    """Tarea mensual: depreciación y TCO de todos los equipos activos con costo de adquisición."""
    hasta = hasta or date.today()
    resumen = {"equipos": 0, "depreciaciones": 0, "snapshots": 0, "alertas": 0}
    equipos = list((await db.execute(select(Equipo).where(Equipo.costo_adquisicion.is_not(None)))).scalars())
    for e in equipos:
        resumen["equipos"] += 1
        if await calcular_depreciacion(db, e, hasta) is not None:
            resumen["depreciaciones"] += 1
        s = await calcular_tco(db, e, hasta)
        resumen["snapshots"] += 1
        if s.valor_reposicion and s.porcentaje_vs_reposicion >= await umbral_reemplazo(db, e.tenant_id):
            resumen["alertas"] += 1
    return resumen


# --------------------------------------------------- reemplazar vs. reparar

async def alertas_reemplazo(db: AsyncSession, actor: Actor, *, pendientes: bool = True) -> list[dict[str, Any]]:
    if not actor.es_superadmin and actor.rol not in CONSULTAN:
        raise prohibido("Tu rol no consulta las alertas de reemplazo")
    consulta = select(ActivoReemplazoAlerta).order_by(ActivoReemplazoAlerta.fecha_alerta.desc())
    if actor.dominio == Dominio.tenant and not actor.es_superadmin:
        consulta = consulta.where(ActivoReemplazoAlerta.tenant_id == actor.tenant_id)
        unidades = await _unidades_visibles(db, actor)
        if unidades is not None:
            consulta = consulta.where(ActivoReemplazoAlerta.equipo_id.in_(select(Equipo.id).where(Equipo.un_id.in_(unidades))))
    if pendientes:
        consulta = consulta.where(ActivoReemplazoAlerta.decision.is_(None))
    filas = list((await db.execute(consulta)).scalars())
    if not filas:
        return []
    equipos = {e.id: e for e in (await db.execute(select(Equipo).where(Equipo.id.in_({a.equipo_id for a in filas})))).scalars()}
    unidades = {u.id: u for u in (await db.execute(select(UnidadNegocio).where(UnidadNegocio.id.in_({e.un_id for e in equipos.values()})))).scalars()}
    salida = []
    for a in filas:
        e = equipos.get(a.equipo_id)
        un = unidades.get(e.un_id) if e else None
        salida.append({**auditoria.instantanea(a), "id": a.id, "equipo_id": a.equipo_id, "tenant_id": a.tenant_id, "equipo_codigo": e.codigo if e else None,
                       "equipo_nombre": e.nombre if e else None, "un_codigo": un.codigo if un else None, "fecha_alerta": a.fecha_alerta,
                       "tco_al_momento": a.tco_al_momento, "valor_reposicion": a.valor_reposicion, "porcentaje_umbral": a.porcentaje_umbral,
                       "porcentaje_alcanzado": a.porcentaje_alcanzado, "decision": a.decision.value if a.decision else None, "razon": a.razon,
                       "decidido_por": a.decidido_por, "decidido_at": a.decidido_at, "trabajo_especial_id": a.trabajo_especial_id,
                       "created_at": a.created_at, "updated_at": a.updated_at})
    return salida


async def decidir_reemplazo(db: AsyncSession, actor: Actor, alerta: ActivoReemplazoAlerta, decision: DecisionReemplazo, razon: str = "",
                            request: Request | None = None) -> dict[str, Any]:
    """Aceptar genera el trabajo especial de reemplazo (§6.9.4) en estado `creado` para que el prestador lo cotice y envíe;
    posponer exige razón documentada."""
    if not actor.es_superadmin and actor.rol not in CONFIGURAN:
        raise prohibido("Solo el Admin empresa decide sobre la recomendación de reemplazo")
    if actor.dominio == Dominio.tenant and alerta.tenant_id != actor.tenant_id:
        raise no_encontrado("Alerta de reemplazo")
    if alerta.decision is not None:
        raise ErrorAPI(409, "ALERTA_YA_RESUELTA", f"La alerta ya fue {alerta.decision.value}")
    if decision == DecisionReemplazo.pospuesto and not (razon or "").strip():
        raise ErrorAPI(422, "RAZON_REQUERIDA", "Posponer el reemplazo exige razón documentada")
    equipo = await db.get(Equipo, alerta.equipo_id)
    alerta.decision, alerta.razon, alerta.decidido_por, alerta.decidido_at = decision, (razon or "").strip(), actor.id, datetime.now(UTC)
    te = None
    if decision == DecisionReemplazo.aceptado:
        te = await _trabajo_especial_de_reemplazo(db, actor, equipo, alerta, request)
        alerta.trabajo_especial_id = te.id
    await db.flush()
    await auditoria.registrar_actor(db, actor, f"activos.reemplazo_{decision.value}", request, tenant_id=alerta.tenant_id,
                                    recurso_tipo="activo_reemplazo_alerta", recurso_id=alerta.id,
                                    despues={"equipo": equipo.codigo if equipo else None, "razon": razon, "trabajo_especial_id": str(te.id) if te else None})
    return {"alerta": alerta, "trabajo_especial": te}


async def _trabajo_especial_de_reemplazo(db: AsyncSession, actor: Actor, equipo: Equipo, alerta: ActivoReemplazoAlerta, request: Request | None):
    """El TE figura creado por el Admin prestador (usuario administrador del prestador) y el historial registra qué Admin
    empresa aceptó la recomendación: el cliente solo crea TE de urgencia (§6.10.6) y este debe cotizarse."""
    from core.dependencias import Actor as ActorDep
    from services import catalogos_service, trabajos_especiales_service
    from services.preventivos_service import _usuario_capturador

    prestadores = await catalogos_service.prestadores_del_tenant(db, equipo.tenant_id)
    if not prestadores:
        raise ErrorAPI(422, "SIN_PRESTADOR", "El cliente no tiene prestador vinculado para generar el trabajo especial de reemplazo")
    prestador_id = prestadores[0]
    usuario_id = await _usuario_capturador(db, prestador_id, None)
    u = await db.get(Usuario, usuario_id)
    sintetico = ActorDep(id=usuario_id, email=u.email if u else "sistema@acma", nombre=u.nombre if u else "sistema", rol=Rol.admin_prestador,
                         dominio=Dominio.prestador, tenant_id=None, prestador_id=prestador_id, sesion_id=None)
    descripcion = (f"Reemplazo recomendado del equipo {equipo.codigo} · {equipo.nombre}: el costo total de propiedad acumulado "
                   f"(${alerta.tco_al_momento:,.2f}) alcanzó el {alerta.porcentaje_alcanzado}% de su valor de reposición "
                   f"(${alerta.valor_reposicion:,.2f}), por encima del umbral del {alerta.porcentaje_umbral}% (§6.9.4).")
    te = await trabajos_especiales_service.crear(db, sintetico, tenant_id=equipo.tenant_id, un_id=equipo.un_id, equipo_id=equipo.id,
                                                 descripcion=descripcion, detalle={"origen": "reemplazo_tco", "alerta_id": str(alerta.id),
                                                                                   "aceptado_por": str(actor.id), "tco": str(alerta.tco_al_momento)},
                                                 prestador_id=prestador_id, request=request)
    await trabajos_especiales_service._historial(db, te, te.estado.value, te.estado.value, actor,
                                                 f"Generado al aceptar la recomendación de reemplazo del activo {equipo.codigo}",
                                                 {"alerta_id": str(alerta.id), "aceptado_por": str(actor.id), "rol": actor.rol.value})
    return te


# ------------------------------------------------------------------ ficha

async def listado(db: AsyncSession, actor: Actor, *, tenant_id: UUID | None = None, un_id: UUID | None = None, con_alerta: bool = False) -> list[dict[str, Any]]:
    """Listado con TCO y alerta de reemplazo."""
    if not actor.es_superadmin and actor.rol not in CONSULTAN:
        raise prohibido("Tu rol no consulta el módulo de activos")
    consulta = select(Equipo).order_by(Equipo.codigo)
    if actor.es_superadmin:
        if tenant_id:
            consulta = consulta.where(Equipo.tenant_id == tenant_id)
    elif actor.dominio == Dominio.tenant:
        consulta = consulta.where(Equipo.tenant_id == actor.tenant_id)
        unidades = await _unidades_visibles(db, actor)
        if unidades is not None:
            consulta = consulta.where(Equipo.un_id.in_(unidades))
    else:
        from services import catalogos_service

        tenants = list((await db.execute(select(Equipo.tenant_id).distinct())).scalars())
        permitidos = [t for t in tenants if actor.prestador_id in await catalogos_service.prestadores_del_tenant(db, t)]
        consulta = consulta.where(Equipo.tenant_id.in_(permitidos or [None]))
    if un_id:
        consulta = consulta.where(Equipo.un_id == un_id)
    equipos = list((await db.execute(consulta)).scalars())
    if not equipos:
        return []
    ids = [e.id for e in equipos]
    snapshots: dict[UUID, ActivoTCOSnapshot] = {}
    for s in (await db.execute(select(ActivoTCOSnapshot).where(ActivoTCOSnapshot.equipo_id.in_(ids)).order_by(ActivoTCOSnapshot.periodo))).scalars():
        snapshots[s.equipo_id] = s
    alertas = {a.equipo_id: a for a in (await db.execute(select(ActivoReemplazoAlerta).where(
        ActivoReemplazoAlerta.equipo_id.in_(ids), ActivoReemplazoAlerta.decision.is_(None)))).scalars()}
    unidades = {u.id: u for u in (await db.execute(select(UnidadNegocio).where(UnidadNegocio.id.in_({e.un_id for e in equipos})))).scalars()}
    salida = []
    for e in equipos:
        s, a = snapshots.get(e.id), alertas.get(e.id)
        if con_alerta and a is None:
            continue
        un = unidades.get(e.un_id)
        salida.append({"id": e.id, "codigo": e.codigo, "nombre": e.nombre, "marca": e.marca, "modelo": e.modelo, "numero_serie": e.numero_serie,
                       "estado": e.estado.value, "criticidad": e.criticidad, "un_id": e.un_id, "un_codigo": un.codigo if un else None,
                       "un_nombre": un.nombre if un else None, "tenant_id": e.tenant_id, "costo_adquisicion": e.costo_adquisicion,
                       "fecha_adquisicion": e.fecha_adquisicion, "fecha_instalacion": e.fecha_instalacion, "valor_reposicion": e.valor_reposicion,
                       "numero_activo_fijo_erp": e.numero_activo_fijo_erp, "tco_total": s.tco_total if s else None,
                       "porcentaje_vs_reposicion": s.porcentaje_vs_reposicion if s else None, "periodo_tco": s.periodo if s else None,
                       "alerta_reemplazo": bool(a), "alerta_reemplazo_id": a.id if a else None})
    return salida


async def _origen_de_criticidad(db: AsyncSession, equipo: Equipo) -> str:
    """De dónde viene el nivel que muestra la ficha: el cálculo de F2-05, un ajuste manual del Admin empresa, o el
    campo que se capturaba a mano antes de que existiera la evaluación."""
    from services import criticidad_service

    fila = await criticidad_service.vigente(db, equipo.id)
    if fila is None:
        return "manual" if equipo.criticidad else "sin evaluar"
    origen = fila.origen.value if hasattr(fila.origen, "value") else str(fila.origen)
    return "calculado (ISO 55000 §6.9.3)" if origen == "calculado" else "ajuste manual del Admin empresa"


async def ficha(db: AsyncSession, actor: Actor, equipo: Equipo) -> dict[str, Any]:
    """§6.9.4: datos del equipo, contrato y garantía, criticidad con su origen, historial de folios con costos y
    causa, preventivos con desvío, refacciones consumidas, depreciación y TCO. MTBF y MTTR por activo: pendientes."""
    from services import folios_captura_service as captura
    from services.preventivos_service import texto_desvio

    un = await db.get(UnidadNegocio, equipo.un_id)
    contrato = await db.get(Contrato, equipo.contrato_id) if equipo.contrato_id else None
    tipo = await db.get(TipoEquipo, equipo.tipo_equipo_id)
    folios = list((await db.execute(select(Folio).where(Folio.equipo_id == equipo.id).order_by(Folio.capturado_at.desc()))).scalars())
    costos = {c.folio_id: c for c in (await db.execute(select(FolioCosto).where(FolioCosto.folio_id.in_([f.id for f in folios])))).scalars()} if folios else {}
    resumenes = {r["id"]: r for r in await captura.resumen(db, folios)} if folios else {}
    refacciones = list((await db.execute(select(FolioRefaccion).where(FolioRefaccion.folio_id.in_([f.id for f in folios]))
                                          .order_by(FolioRefaccion.created_at.desc()))).scalars()) if folios else []
    d = await configuracion(db, equipo.id)
    componentes = await componentes_tco(db, equipo)
    unidades_hoy, unidades_periodo = await unidades_del_activo(db, d, date.today())
    historial = await historial_depreciacion(db, equipo.id)
    alerta = (await db.execute(select(ActivoReemplazoAlerta).where(ActivoReemplazoAlerta.equipo_id == equipo.id)
                                .order_by(ActivoReemplazoAlerta.fecha_alerta.desc()))).scalars().first()
    ver_costos = True
    if actor.rol == Rol.tecnico and not actor.es_superadmin:
        permisos = {p["clave"]: p["habilitado"] for p in await permisos_service.efectivos_de_tecnico(db, actor.prestador_id, actor.id)}
        ver_costos = bool(permisos.get("ver_costo_refacciones", False))
    historial_folios = []
    for f in folios:
        r, c = resumenes.get(f.id, {}), costos.get(f.id)
        historial_folios.append({"id": f.id, "numero_folio": f.numero_folio, "tipo_folio": f.tipo_folio.value, "estado": f.estado.value,
                                 "tipo_falla": r.get("tipo_falla"), "descripcion": f.descripcion[:160], "capturado_at": f.capturado_at,
                                 "fecha_cierre": f.fecha_cierre, "tecnico_nombre": r.get("tecnico_nombre"),
                                 "costo_total": c.costo_total if c and ver_costos else None, "costo_validado": bool(c and c.validado_at),
                                 "severidad": r.get("severidad"), "plan_nombre": r.get("plan_nombre"),
                                 "desvio": texto_desvio((f.fecha_cierre.date() - f.fecha_falla.date()).days) if f.tipo_folio == TipoFolio.preventivo and f.fecha_cierre else None})
    return {
        "equipo": {"id": equipo.id, "codigo": equipo.codigo, "nombre": equipo.nombre, "marca": equipo.marca, "modelo": equipo.modelo,
                   "numero_serie": equipo.numero_serie, "estado": equipo.estado.value, "criticidad": equipo.criticidad,
                   "criticidad_origen": await _origen_de_criticidad(db, equipo), "tipo_equipo": tipo.nombre if tipo else None,
                   "un_id": equipo.un_id, "un_codigo": un.codigo if un else None, "un_nombre": un.nombre if un else None,
                   "fecha_instalacion": equipo.fecha_instalacion, "fecha_adquisicion": equipo.fecha_adquisicion,
                   "costo_adquisicion": equipo.costo_adquisicion, "valor_reposicion": equipo.valor_reposicion,
                   "costo_hora_inactividad": await costo_hora_inactividad(db, equipo), "numero_activo_fijo_erp": equipo.numero_activo_fijo_erp,
                   "garantia_vigente_hasta": equipo.garantia_vigente_hasta, "tenant_id": equipo.tenant_id},
        "contrato": None if contrato is None else {"id": contrato.id, "nombre": contrato.nombre, "modalidad": contrato.modalidad.value,
                                                   "fecha_inicio": contrato.fecha_inicio, "fecha_fin": contrato.fecha_fin, "estado": contrato.estado.value},
        "historial_folios": historial_folios,
        "refacciones": [{"id": r.id, "descripcion": r.descripcion, "cantidad": r.cantidad, "origen": r.origen.value,
                         "costo_unitario": r.costo_unitario if ver_costos else None, "folio_id": r.folio_id,
                         "importe": (r.cantidad * r.costo_unitario).quantize(CENTAVO) if ver_costos else None} for r in refacciones[:100]],
        "depreciacion": None if d is None else {"metodo": d.metodo.value, "vida_util_anios": d.vida_util_anios, "valor_salvamento": d.valor_salvamento,
                                                "valor_reposicion": d.valor_reposicion, "unidades_vida_util": d.unidades_vida_util,
                                                "unidades_acumuladas": unidades_hoy if unidades_hoy is not None else d.unidades_acumuladas,
                                                "valor_en_libros_manual": d.valor_en_libros_manual,
                                                "fecha_inicio": d.fecha_inicio, "aviso": componentes["aviso"],
                                                "equipo_medidor_id": d.equipo_medidor_id, "unidades_al_inicio": d.unidades_al_inicio,
                                                "unidades_periodo": unidades_periodo},
        "depreciacion_historial": [{"periodo": h.periodo, "valor_en_libros": h.valor_en_libros, "depreciacion_periodo": h.depreciacion_periodo,
                                    "depreciacion_acumulada": h.depreciacion_acumulada, "metodo_aplicado": h.metodo_aplicado.value,
                                    "unidades_periodo": h.unidades_periodo, "unidades_acumuladas": h.unidades_acumuladas}
                                   for h in reversed(historial)],
        "medidores": await medidores_de_la_ficha(db, actor, equipo),
        "tco": componentes,
        "tco_historial": [{"periodo": s.periodo, "tco_total": s.tco_total, "porcentaje_vs_reposicion": s.porcentaje_vs_reposicion,
                           "costo_preventivos": s.costo_preventivos, "costo_correctivos": s.costo_correctivos, "costo_refacciones": s.costo_refacciones,
                           "costo_downtime": s.costo_downtime, "valor_residual": s.valor_residual}
                          for s in (await db.execute(select(ActivoTCOSnapshot).where(ActivoTCOSnapshot.equipo_id == equipo.id)
                                                      .order_by(ActivoTCOSnapshot.periodo))).scalars()],
        "alerta_reemplazo": None if alerta is None else {"id": alerta.id, "fecha_alerta": alerta.fecha_alerta, "tco_al_momento": alerta.tco_al_momento,
                                                         "valor_reposicion": alerta.valor_reposicion, "porcentaje_umbral": alerta.porcentaje_umbral,
                                                         "porcentaje_alcanzado": alerta.porcentaje_alcanzado,
                                                         "decision": alerta.decision.value if alerta.decision else None, "razon": alerta.razon,
                                                         "trabajo_especial_id": alerta.trabajo_especial_id},
        "umbral_reemplazo_pct": await umbral_reemplazo(db, equipo.tenant_id),
        "fase_2": ["MTBF y MTTR por activo"],
    }


async def medidores_de_la_ficha(db: AsyncSession, actor: Actor, equipo: Equipo) -> list[dict[str, Any]]:
    """Pestaña «Medidores» de la ficha (F2-04). Vive aquí para que la ficha salga en una sola llamada."""
    from services import medidores_service

    return await medidores_service.resumen_de_equipo(db, actor, equipo)
