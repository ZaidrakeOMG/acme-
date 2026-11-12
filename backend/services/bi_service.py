"""Dashboards por rol e indicadores de negocio (§6.8.4, §6.8.5, §5.1, §5.2, §7.5). P10.

Todo se calcula en el servidor sobre la jerarquía Tenant → Grupo de UNs → UN y se guarda en Redis con TTL corto
(`TTL_CACHE`, 120 s: los tableros se consultan en ráfagas y un minuto de desfase es aceptable para KPIs operativos;
sin Redis el cálculo simplemente se repite). Cada indicador está documentado en `docs/bi/indicadores.md` (ACT-8.1).
"""
import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import config
from core.dependencias import Actor
from core.errors import prohibido
from models.alertas import AlertaHistorial
from models.base import Dominio, EstadoAlerta, EstadoRegistro, ModalidadContrato, Rol
from models.catalogos import Equipo, NivelSeveridadCatalogo
from models.contratos import Contrato
from models.costos import FolioCosto, Presupuesto
from models.folios import EstadoFolio, Folio, FolioSLA, TipoFolio
from models.inventario import EstadoGastoCajaChica, Existencia, FondoCajaChica, GastoCajaChica
from models.minutas import Hallazgo
from models.preventivos import PreventivoCalendario
from models.seguimiento import Cotizacion, EstadoCotizacion
from models.sla import PenalizacionPeriodo
from models.trabajos_especiales import TrabajoEspecial
from models.unidades import GrupoUN, GrupoUNMiembro, UnidadNegocio
from models.usuarios import Usuario

log = logging.getLogger("acma.bi")
TTL_CACHE = 120  # segundos
CERO = Decimal("0")
CENTAVO = Decimal("0.01")
# §5.1: el Supervisor de operadores ve conteos de sus grupos, nunca montos ni el detalle del folio.
SIN_FINANZAS = {Rol.supervisor_operadores}
TABLEROS = {
    Rol.admin_empresa: "cliente", Rol.admin_un: "cliente", Rol.supervisor_operadores: "supervision",
    Rol.admin_prestador: "prestador", Rol.mesa_control: "prestador", Rol.despachador: "jornada",
    Rol.supervisor_prestador: "prestador", Rol.direccion_prestador: "direccion", Rol.superadmin: "prestador",
}


@dataclass(frozen=True)
class Filtro:
    """Período y nivel de la jerarquía de §6.8.5."""

    desde: date
    hasta: date
    tenant_id: UUID | None = None
    prestador_id: UUID | None = None
    grupo_id: UUID | None = None
    un_id: UUID | None = None

    def clave(self, sufijo: str) -> str:
        crudo = json.dumps({**self.__dict__, "desde": str(self.desde), "hasta": str(self.hasta),
                            **{k: str(v) for k, v in self.__dict__.items() if isinstance(v, UUID)}}, sort_keys=True, default=str)
        return f"acma:bi:{sufijo}:{hashlib.sha256(crudo.encode()).hexdigest()[:24]}"

    @property
    def inicio(self) -> datetime:
        return datetime.combine(self.desde, datetime.min.time(), tzinfo=UTC)

    @property
    def fin(self) -> datetime:
        return datetime.combine(self.hasta, datetime.min.time(), tzinfo=UTC) + timedelta(days=1)

    def anterior(self) -> "Filtro":
        dias = (self.hasta - self.desde).days + 1
        return Filtro(self.desde - timedelta(days=dias), self.desde - timedelta(days=1), self.tenant_id,
                      self.prestador_id, self.grupo_id, self.un_id)

    def anio_anterior(self) -> "Filtro":
        return Filtro(self.desde.replace(year=self.desde.year - 1), self.hasta.replace(year=self.hasta.year - 1),
                      self.tenant_id, self.prestador_id, self.grupo_id, self.un_id)


def periodo_por_defecto() -> tuple[date, date]:
    hoy = date.today()
    return hoy.replace(day=1), hoy


async def filtro_de(db: AsyncSession, actor: Actor, desde: date | None, hasta: date | None,
                    grupo_id: UUID | None = None, un_id: UUID | None = None) -> Filtro:
    """Fija el período y encierra al actor en su dominio: el cliente ve su tenant, el prestador su cartera."""
    d, h = periodo_por_defecto()
    f = Filtro(desde or d, hasta or h, grupo_id=grupo_id, un_id=un_id)
    if actor.rol == Rol.superadmin:
        return f
    if actor.dominio == Dominio.tenant:
        f = Filtro(f.desde, f.hasta, tenant_id=actor.tenant_id, grupo_id=grupo_id, un_id=un_id)
        if actor.rol == Rol.admin_un and un_id is None:
            unidades = await uns_del_usuario(db, actor)
            f = Filtro(f.desde, f.hasta, tenant_id=actor.tenant_id, un_id=unidades[0] if len(unidades) == 1 else None)
        return f
    return Filtro(f.desde, f.hasta, prestador_id=actor.prestador_id, tenant_id=f.tenant_id, grupo_id=grupo_id, un_id=un_id)


async def uns_del_usuario(db: AsyncSession, actor: Actor) -> list[UUID]:
    """Admin UN: sus UNs asignadas. Supervisor de operadores: todas las UNs de sus grupos (§6.8.5)."""
    from models.unidades import UsuarioGrupo, UsuarioUN

    directas = list((await db.execute(select(UsuarioUN.unidad_id).where(UsuarioUN.usuario_id == actor.id))).scalars())
    grupos = list((await db.execute(select(UsuarioGrupo.grupo_id).where(UsuarioGrupo.usuario_id == actor.id))).scalars())
    if grupos:
        directas += list((await db.execute(select(GrupoUNMiembro.unidad_id).where(GrupoUNMiembro.grupo_id.in_(grupos)))).scalars())
    return list(dict.fromkeys(directas))


async def _uns_del_filtro(db: AsyncSession, f: Filtro) -> list[UUID] | None:
    if f.un_id:
        return [f.un_id]
    if f.grupo_id:
        return list((await db.execute(select(GrupoUNMiembro.unidad_id).where(GrupoUNMiembro.grupo_id == f.grupo_id))).scalars())
    return None


async def _acotar(db: AsyncSession, consulta: Select, f: Filtro, modelo=Folio) -> Select:
    if f.tenant_id:
        consulta = consulta.where(modelo.tenant_id == f.tenant_id)
    if f.prestador_id:
        consulta = consulta.where(modelo.prestador_id == f.prestador_id)
    uns = await _uns_del_filtro(db, f)
    if uns is not None:
        consulta = consulta.where(modelo.un_id.in_(uns or [UUID(int=0)]))
    return consulta


# ------------------------------------------------------------------- caché
async def _cache_leer(clave: str) -> dict | None:
    try:
        import redis.asyncio as redis_async

        cliente = redis_async.from_url(config.redis_url, decode_responses=True)
        crudo = await cliente.get(clave)
        await cliente.aclose()
        return json.loads(crudo) if crudo else None
    except Exception as e:  # sin Redis el tablero se recalcula
        log.debug("BI sin caché (%s)", e)
        return None


async def _cache_guardar(clave: str, valor: dict) -> None:
    try:
        import redis.asyncio as redis_async

        cliente = redis_async.from_url(config.redis_url, decode_responses=True)
        await cliente.set(clave, json.dumps(valor, default=str), ex=TTL_CACHE)
        await cliente.aclose()
    except Exception:
        pass


# -------------------------------------------------------------- indicadores
async def folios_por_estado(db: AsyncSession, f: Filtro) -> dict[str, int]:
    consulta = await _acotar(db, select(Folio.estado, func.count()).where(Folio.capturado_at >= f.inicio,
                                                                          Folio.capturado_at < f.fin).group_by(Folio.estado), f)
    return {e.value: n for e, n in (await db.execute(consulta)).all()}


async def folios_por_severidad(db: AsyncSession, f: Filtro) -> dict[str, int]:
    consulta = await _acotar(db, select(NivelSeveridadCatalogo.nombre, func.count())
                             .join(Folio, Folio.severidad_id == NivelSeveridadCatalogo.id)
                             .where(Folio.capturado_at >= f.inicio, Folio.capturado_at < f.fin)
                             .group_by(NivelSeveridadCatalogo.nombre), f)
    return {nombre: n for nombre, n in (await db.execute(consulta)).all()}


async def cumplimiento_sla(db: AsyncSession, f: Filtro) -> dict[str, Any]:
    """Cumplimiento de respuesta y resolución por severidad sobre los folios cerrados del período (§6.10.1)."""
    consulta = await _acotar(db, select(FolioSLA, Folio, NivelSeveridadCatalogo.nombre)
                             .join(Folio, Folio.id == FolioSLA.folio_id)
                             .outerjoin(NivelSeveridadCatalogo, NivelSeveridadCatalogo.id == FolioSLA.nivel_severidad_id)
                             .where(Folio.estado == EstadoFolio.cerrado, Folio.fecha_cierre >= f.inicio,
                                    Folio.fecha_cierre < f.fin), f)
    filas = (await db.execute(consulta)).all()
    por_sev: dict[str, dict[str, int]] = {}
    for fila, _folio, nombre in filas:
        d = por_sev.setdefault(nombre or "sin severidad", {"total": 0, "respuesta_ok": 0, "resolucion_ok": 0, "penalizados": 0})
        d["total"] += 1
        d["respuesta_ok"] += 1 if fila.cumplimiento_respuesta else 0
        d["resolucion_ok"] += 1 if fila.cumplimiento_resolucion else 0
        d["penalizados"] += 1 if fila.cumplimiento is False else 0
    total = sum(d["total"] for d in por_sev.values())
    return {
        "total": total,
        "respuesta_pct": str(_pct(sum(d["respuesta_ok"] for d in por_sev.values()), total)),
        "resolucion_pct": str(_pct(sum(d["resolucion_ok"] for d in por_sev.values()), total)),
        "por_severidad": {k: {**v, "respuesta_pct": str(_pct(v["respuesta_ok"], v["total"])),
                              "resolucion_pct": str(_pct(v["resolucion_ok"], v["total"]))} for k, v in por_sev.items()},
    }


def _pct(parte: int, total: int) -> Decimal:
    return CERO if not total else (Decimal(parte * 100) / Decimal(total)).quantize(CENTAVO)


async def mttr(db: AsyncSession, f: Filtro) -> dict[str, Any]:
    """MTTR (glosario): promedio de horas desde que se reporta el correctivo hasta que el folio cierra."""
    consulta = await _acotar(db, select(Folio.capturado_at, Folio.fecha_cierre).where(
        Folio.tipo_folio == TipoFolio.correctivo, Folio.estado == EstadoFolio.cerrado,
        Folio.fecha_cierre >= f.inicio, Folio.fecha_cierre < f.fin), f)
    horas = [(c - a).total_seconds() / 3600 for a, c in (await db.execute(consulta)).all() if a and c]
    return {"folios": len(horas), "horas": str(Decimal(sum(horas) / len(horas)).quantize(CENTAVO)) if horas else "0.00"}


async def mtbf(db: AsyncSession, f: Filtro) -> dict[str, Any]:
    """MTBF (glosario): promedio de horas de operación entre fallas correctivas consecutivas del mismo equipo."""
    consulta = await _acotar(db, select(Folio.equipo_id, Folio.capturado_at).where(
        Folio.tipo_folio == TipoFolio.correctivo, Folio.capturado_at >= f.inicio, Folio.capturado_at < f.fin
    ).order_by(Folio.equipo_id, Folio.capturado_at), f)
    por_equipo: dict[UUID, list[datetime]] = {}
    for equipo_id, cuando in (await db.execute(consulta)).all():
        por_equipo.setdefault(equipo_id, []).append(cuando)
    intervalos = [(b - a).total_seconds() / 3600 for fechas in por_equipo.values() for a, b in zip(fechas, fechas[1:])]
    return {"equipos": len(por_equipo), "intervalos": len(intervalos),
            "horas": str(Decimal(sum(intervalos) / len(intervalos)).quantize(CENTAVO)) if intervalos else "0.00",
            "aviso": "" if intervalos else "Se necesitan al menos dos fallas del mismo equipo en el período"}


async def gasto_vs_presupuesto(db: AsyncSession, f: Filtro) -> dict[str, Any]:
    from services import presupuestos_service

    consulta = select(Presupuesto).where(Presupuesto.activo.is_(True), Presupuesto.periodo_inicio <= f.hasta,
                                         Presupuesto.periodo_fin >= f.desde)
    if f.tenant_id:
        consulta = consulta.where(Presupuesto.tenant_id == f.tenant_id)
    uns = await _uns_del_filtro(db, f)
    if uns is not None:
        consulta = consulta.where(or_(Presupuesto.un_id.in_(uns), Presupuesto.un_id.is_(None)))
    filas = list((await db.execute(consulta)).scalars())
    monto = sum((Decimal(p.monto) for p in filas), CERO)
    consumido = CERO
    for p in filas:
        consumido += await presupuestos_service.consumido(db, p.id)
    return {"presupuestos": len(filas), "monto": str(monto), "consumido": str(consumido),
            "disponible": str(monto - consumido), "porcentaje": str(_pct(int(consumido), int(monto)) if monto else CERO)}


async def costo_total(db: AsyncSession, f: Filtro) -> dict[str, Any]:
    consulta = await _acotar(db, select(func.coalesce(func.sum(FolioCosto.costo_total), 0), func.count())
                             .join(Folio, Folio.id == FolioCosto.folio_id)
                             .where(Folio.fecha_cierre >= f.inicio, Folio.fecha_cierre < f.fin), f)
    total, n = (await db.execute(consulta)).one()
    return {"folios": n, "total": str(Decimal(total or 0).quantize(CENTAVO))}


async def top_equipos(db: AsyncSession, f: Filtro, por: str = "costo", limite: int = 10) -> list[dict]:
    """Top 10 equipos por costo acumulado o por número de fallas del período."""
    campo = func.coalesce(func.sum(FolioCosto.costo_total), 0) if por == "costo" else func.count(Folio.id)
    consulta = (select(Equipo.id, Equipo.codigo, Equipo.nombre, campo.label("valor"), func.count(Folio.id).label("fallas"))
                .join(Folio, Folio.equipo_id == Equipo.id))
    if por == "costo":
        consulta = consulta.outerjoin(FolioCosto, FolioCosto.folio_id == Folio.id)
    consulta = consulta.where(Folio.capturado_at >= f.inicio, Folio.capturado_at < f.fin)
    consulta = await _acotar(db, consulta, f)
    consulta = consulta.group_by(Equipo.id, Equipo.codigo, Equipo.nombre).order_by(func.coalesce(campo, 0).desc()).limit(limite)
    return [{"equipo_id": str(i), "codigo": c, "nombre": n, "valor": str(Decimal(v or 0).quantize(CENTAVO)), "fallas": fa}
            for i, c, n, v, fa in (await db.execute(consulta)).all()]


async def preventivos(db: AsyncSession, f: Filtro) -> dict[str, Any]:
    """Cumplimiento y desvío promedio del calendario de preventivos (P06)."""
    consulta = select(PreventivoCalendario).where(PreventivoCalendario.fecha_programada >= f.desde,
                                                  PreventivoCalendario.fecha_programada <= f.hasta)
    if f.tenant_id:
        consulta = consulta.where(PreventivoCalendario.tenant_id == f.tenant_id)
    if f.prestador_id:
        consulta = consulta.where(PreventivoCalendario.prestador_id == f.prestador_id)
    uns = await _uns_del_filtro(db, f)
    if uns is not None:
        consulta = consulta.where(PreventivoCalendario.un_id.in_(uns or [UUID(int=0)]))
    filas = list((await db.execute(consulta)).scalars())
    ejecutados = [x for x in filas if x.fecha_real is not None]
    desvios = [abs(int(x.desvio_dias or 0)) for x in ejecutados]
    return {"programados": len(filas), "ejecutados": len(ejecutados),
            "cumplimiento_pct": str(_pct(len(ejecutados), len(filas))),
            "desvio_promedio_dias": str(Decimal(sum(desvios) / len(desvios)).quantize(CENTAVO)) if desvios else "0.00"}


async def hallazgos(db: AsyncSession, f: Filtro) -> dict[str, Any]:
    consulta = select(Hallazgo).where(Hallazgo.created_at >= f.inicio, Hallazgo.created_at < f.fin)
    if f.tenant_id:
        consulta = consulta.where(Hallazgo.tenant_id == f.tenant_id)
    if f.prestador_id:
        consulta = consulta.where(Hallazgo.prestador_id == f.prestador_id)
    filas = list((await db.execute(consulta)).scalars())
    cot = select(func.count()).select_from(Cotizacion).where(Cotizacion.hallazgo_id.is_not(None),
                                                             Cotizacion.created_at >= f.inicio, Cotizacion.created_at < f.fin)
    if f.tenant_id:
        cot = cot.where(Cotizacion.tenant_id == f.tenant_id)
    convertidos = (await db.execute(cot)).scalar_one()
    return {"total": len(filas), "convertidos_a_cotizacion": int(convertidos or 0),
            "conversion_pct": str(_pct(int(convertidos or 0), len(filas)))}


async def cotizaciones(db: AsyncSession, f: Filtro) -> dict[str, Any]:
    consulta = select(Cotizacion).where(Cotizacion.created_at >= f.inicio, Cotizacion.created_at < f.fin)
    if f.tenant_id:
        consulta = consulta.where(Cotizacion.tenant_id == f.tenant_id)
    if f.prestador_id:
        consulta = consulta.where(Cotizacion.prestador_id == f.prestador_id)
    filas = list((await db.execute(consulta)).scalars())
    autorizadas = [c for c in filas if c.estado in (EstadoCotizacion.autorizada, EstadoCotizacion.convertida)]
    monto = sum((Decimal(c.monto or 0) for c in autorizadas), CERO)
    return {"total": len(filas), "autorizadas": len(autorizadas), "conversion_pct": str(_pct(len(autorizadas), len(filas))),
            "monto_autorizado": str(monto.quantize(CENTAVO))}


async def trabajos_especiales(db: AsyncSession, f: Filtro) -> dict[str, Any]:
    consulta = select(TrabajoEspecial).where(TrabajoEspecial.created_at >= f.inicio, TrabajoEspecial.created_at < f.fin)
    if f.tenant_id:
        consulta = consulta.where(TrabajoEspecial.tenant_id == f.tenant_id)
    if f.prestador_id:
        consulta = consulta.where(TrabajoEspecial.prestador_id == f.prestador_id)
    filas = list((await db.execute(consulta)).scalars())
    return {"total": len(filas), "urgencias": sum(1 for t in filas if t.urgencia),
            "por_estado": {e: sum(1 for t in filas if t.estado.value == e) for e in {t.estado.value for t in filas}}}


async def carga_por_tecnico(db: AsyncSession, f: Filtro) -> list[dict]:
    """Folios asignados y cerrados por técnico (sin productividad ni venta por técnico, que son Fase 2)."""
    consulta = await _acotar(db, select(Usuario.id, Usuario.nombre,
                                        func.count(Folio.id).label("asignados"),
                                        func.count(Folio.fecha_cierre).label("cerrados"))
                             .join(Folio, Folio.tecnico_id == Usuario.id)
                             .where(Folio.capturado_at >= f.inicio, Folio.capturado_at < f.fin), f)
    consulta = consulta.group_by(Usuario.id, Usuario.nombre).order_by(func.count(Folio.id).desc())
    return [{"tecnico_id": str(i), "nombre": n, "asignados": a, "cerrados": c}
            for i, n, a, c in (await db.execute(consulta)).all()]


async def penalizaciones(db: AsyncSession, f: Filtro) -> dict[str, Any]:
    consulta = select(PenalizacionPeriodo).where(PenalizacionPeriodo.periodo >= f.desde.strftime("%Y-%m"),
                                                 PenalizacionPeriodo.periodo <= f.hasta.strftime("%Y-%m"))
    if f.tenant_id:
        consulta = consulta.where(PenalizacionPeriodo.tenant_id == f.tenant_id)
    if f.prestador_id:
        consulta = consulta.where(PenalizacionPeriodo.prestador_id == f.prestador_id)
    filas = list((await db.execute(consulta)).scalars())
    return {"periodos": len(filas), "folios_incumplidos": sum(x.folios_incumplidos for x in filas),
            "monto": str(sum((Decimal(x.monto_penalizacion) for x in filas), CERO).quantize(CENTAVO)),
            "detalle": [{"periodo": x.periodo, "estado": x.estado.value, "monto": str(x.monto_penalizacion),
                         "folios_incumplidos": x.folios_incumplidos} for x in filas]}


async def iguala(db: AsyncSession, f: Filtro) -> list[dict]:
    from services import sla_service

    consulta = select(Contrato).where(Contrato.estado == EstadoRegistro.activo, Contrato.modalidad == ModalidadContrato.iguala)
    if f.tenant_id:
        consulta = consulta.where(Contrato.tenant_id == f.tenant_id)
    if f.prestador_id:
        consulta = consulta.where(Contrato.prestador_id == f.prestador_id)
    salida = []
    for c in (await db.execute(consulta)).scalars():
        registro = await sla_service.consumo_iguala(db, c, f.hasta.strftime("%Y-%m"))
        if registro is None:
            continue
        salida.append({"contrato": c.nombre, "periodo": registro.periodo,
                       "correctivos_incluidos": registro.correctivos_incluidos,
                       "correctivos_atendidos": registro.correctivos_atendidos,
                       "correctivos_adicionales": registro.correctivos_adicionales,
                       "preventivos_incluidos": registro.preventivos_incluidos,
                       "preventivos_ejecutados": registro.preventivos_ejecutados,
                       "tarifa_mensual": str(registro.tarifa_mensual)})
    return salida


async def inventario_y_caja(db: AsyncSession, f: Filtro) -> dict[str, Any]:
    bajo = (await db.execute(select(func.count()).select_from(Existencia).where(
        Existencia.cantidad <= Existencia.stock_minimo, Existencia.stock_minimo > 0))).scalar_one()
    fondos = list((await db.execute(select(FondoCajaChica).where(
        *( [FondoCajaChica.prestador_id == f.prestador_id] if f.prestador_id else [])))).scalars())
    gastos = list((await db.execute(select(GastoCajaChica).where(
        GastoCajaChica.timestamp >= f.inicio, GastoCajaChica.timestamp < f.fin,
        *([GastoCajaChica.prestador_id == f.prestador_id] if f.prestador_id else [])))).scalars())
    return {"existencias_bajo_minimo": int(bajo or 0),
            "fondos": len(fondos), "saldo_fondos": str(sum((Decimal(x.saldo_actual) for x in fondos), CERO)),
            "gastos": len(gastos), "gastos_por_aprobar": sum(1 for g in gastos if g.estado == EstadoGastoCajaChica.capturado),
            "monto_gastos": str(sum((Decimal(g.monto) for g in gastos), CERO).quantize(CENTAVO))}


async def alertas_abiertas(db: AsyncSession, f: Filtro) -> int:
    consulta = select(func.count()).select_from(AlertaHistorial).where(AlertaHistorial.atendida_at.is_(None))
    if f.tenant_id:
        consulta = consulta.where(AlertaHistorial.tenant_id == f.tenant_id)
    if f.prestador_id:
        consulta = consulta.where(AlertaHistorial.prestador_id == f.prestador_id)
    return int((await db.execute(consulta)).scalar_one() or 0)


async def jornada(db: AsyncSession, f: Filtro) -> dict[str, Any]:
    """Indicadores globales de jornada de §6.8.4: se montan sobre el listado de folios del despachador. Desde F2-03
    los muestra también la pantalla de operaciones en tiempo real, junto al mapa en vivo."""
    hoy = date.today()
    dia = Filtro(hoy, hoy, f.tenant_id, f.prestador_id)
    consulta = await _acotar(db, select(Folio).where(Folio.capturado_at >= dia.inicio, Folio.capturado_at < dia.fin), dia)
    folios = list((await db.execute(consulta)).scalars())
    completados = [x for x in folios if x.estado == EstadoFolio.cerrado]
    activos = await _acotar(db, select(func.count(func.distinct(Folio.tecnico_id))).where(
        Folio.tecnico_id.is_not(None), Folio.estado.in_([EstadoFolio.asignado, EstadoFolio.en_camino,
                                                         EstadoFolio.en_ejecucion, EstadoFolio.pendiente_refaccion])), dia)
    horas = [(x.fecha_cierre - x.fecha_inicio_atencion).total_seconds() / 3600
             for x in completados if x.fecha_cierre and x.fecha_inicio_atencion]
    return {"completados": len(completados), "total_dia": len(folios),
            "tecnicos_activos": int((await db.execute(activos)).scalar_one() or 0),
            "alertas_abiertas": await alertas_abiertas(db, dia),
            "tiempo_promedio_atencion_horas": str(Decimal(sum(horas) / len(horas)).quantize(CENTAVO)) if horas else "0.00",
            # F2-03 trajo el mapa en vivo y el GPS; lo que sigue esperando es el bloque de rutas.
            "aviso_fase_2": "El desvío de ruta y el ETA por tráfico llegan con el bloque de optimización de rutas (Fase 2)"}


# ------------------------------------------------------- jerarquía §6.8.5
async def comparativo_jerarquia(db: AsyncSession, f: Filtro) -> dict[str, Any]:
    """Compara grupos entre sí y UNs entre sí dentro del período (§6.8.5)."""
    grupos = list((await db.execute(select(GrupoUN).where(
        *([GrupoUN.tenant_id == f.tenant_id] if f.tenant_id else [])))).scalars())
    unidades = list((await db.execute(select(UnidadNegocio).where(
        *([UnidadNegocio.tenant_id == f.tenant_id] if f.tenant_id else [])))).scalars())
    salida_grupos = []
    for g in grupos:
        hijo = Filtro(f.desde, f.hasta, f.tenant_id, f.prestador_id, grupo_id=g.id)
        salida_grupos.append({"id": str(g.id), "nombre": g.nombre, **await _resumen_nivel(db, hijo)})
    salida_uns = []
    for u in unidades:
        hijo = Filtro(f.desde, f.hasta, f.tenant_id, f.prestador_id, un_id=u.id)
        salida_uns.append({"id": str(u.id), "nombre": f"{u.codigo} · {u.nombre}", **await _resumen_nivel(db, hijo)})
    return {"grupos": salida_grupos, "unidades": salida_uns}


async def _resumen_nivel(db: AsyncSession, f: Filtro) -> dict[str, Any]:
    estados = await folios_por_estado(db, f)
    sla = await cumplimiento_sla(db, f)
    costo = await costo_total(db, f)
    return {"folios": sum(estados.values()), "cerrados": estados.get("cerrado", 0),
            "sla_resolucion_pct": sla["resolucion_pct"], "costo": costo["total"]}


# ---------------------------------------------------------------- tableros
async def tablero(db: AsyncSession, actor: Actor, f: Filtro, comparativos: bool = True) -> dict[str, Any]:
    """Arma el tablero que corresponde al rol (§5.1, §5.2, §7.5) con su caché de TTL corto."""
    tipo = TABLEROS.get(actor.rol)
    if tipo is None:
        raise prohibido("Tu rol no tiene tablero de BI")
    clave = f.clave(f"{tipo}:{actor.rol.value}:{int(comparativos)}")
    guardado = await _cache_leer(clave)
    if guardado is not None:
        return {**guardado, "cache": True}
    datos = await _armar(db, actor, f, tipo)
    if comparativos and tipo in ("cliente", "prestador", "direccion"):
        datos["comparativo_periodo"] = {
            "anterior": await _resumen_nivel(db, f.anterior()),
            "anio_anterior": await _resumen_nivel(db, f.anio_anterior()),
        }
    datos["periodo"] = {"desde": str(f.desde), "hasta": str(f.hasta)}
    datos["rol"] = actor.rol.value
    datos["tipo"] = tipo
    datos["ttl_cache_segundos"] = TTL_CACHE
    await _cache_guardar(clave, datos)
    return {**datos, "cache": False}


async def _armar(db: AsyncSession, actor: Actor, f: Filtro, tipo: str) -> dict[str, Any]:
    if tipo == "supervision":
        # §5.1 literal: conteos y SLA en riesgo de sus grupos; sin finanzas y sin detalle de folios.
        uns = await uns_del_usuario(db, actor)
        propio = Filtro(f.desde, f.hasta, f.tenant_id, f.prestador_id, grupo_id=f.grupo_id,
                        un_id=f.un_id if f.un_id in uns else None)
        if propio.un_id is None and propio.grupo_id is None and uns:
            propio = Filtro(f.desde, f.hasta, f.tenant_id, f.prestador_id)
        en_riesgo = await _alertas_por_clave(db, propio, ("SLA_RESPUESTA_EN_RIESGO", "SLA_RESOLUCION_EN_RIESGO"))
        return {"folios_por_estado": await folios_por_estado(db, propio),
                "folios_por_severidad": await folios_por_severidad(db, propio),
                "sla_en_riesgo": en_riesgo,
                "sin_finanzas": True,
                "aviso": "Tu rol ve el consolidado de sus grupos: sin información financiera ni detalle de cada folio (§5.1)."}
    if tipo == "jornada":
        return {"jornada": await jornada(db, f), "folios_por_estado": await folios_por_estado(db, f)}
    if tipo == "cliente":
        return {
            "gasto_vs_presupuesto": await gasto_vs_presupuesto(db, f),
            "cumplimiento_sla": await cumplimiento_sla(db, f),
            "mttr": await mttr(db, f), "mtbf": await mtbf(db, f),
            "folios_por_estado": await folios_por_estado(db, f),
            "folios_por_severidad": await folios_por_severidad(db, f),
            "preventivos": await preventivos(db, f),
            "hallazgos": await hallazgos(db, f),
            "trabajos_especiales": await trabajos_especiales(db, f),
            "costo": await costo_total(db, f),
            "top_equipos_costo": await top_equipos(db, f, "costo"),
            "top_equipos_fallas": await top_equipos(db, f, "fallas"),
            "jerarquia": await comparativo_jerarquia(db, f),
            # F2-05 (§6.9.3): distribución de activos por nivel de criticidad, activos A sin plan y acciones de
            # mitigación vencidas. Son los tres números que el cliente mira para su gestión de activos.
            "criticidad": await criticidad(db, actor, f),
            "calificacion_admin_un": await _calificacion(db, actor, f) if actor.rol == Rol.admin_un else None,
        }
    if tipo == "direccion":
        return {
            "cumplimiento_sla": await cumplimiento_sla(db, f),
            "penalizaciones": await penalizaciones(db, f),
            "costo": await costo_total(db, f),
            "folios_por_estado": await folios_por_estado(db, f),
            "escalaciones": await _alertas_por_clave(db, f, tuple(await _claves_escalacion(db, f))),
            "solo_lectura": True,
        }
    return {  # prestador: Admin prestador, Mesa de control, Supervisor del prestador y superadmin
        "folios_por_estado": await folios_por_estado(db, f),
        "folios_por_cliente": await _por_cliente(db, f),
        "cumplimiento_sla": await cumplimiento_sla(db, f),
        "penalizaciones": await penalizaciones(db, f),
        "iguala": await iguala(db, f),
        "cotizaciones": await cotizaciones(db, f),
        "carga_por_tecnico": await carga_por_tecnico(db, f),
        "preventivos": await preventivos(db, f),
        "inventario_y_caja": await inventario_y_caja(db, f),
        "mttr": await mttr(db, f),
        "criticidad": await criticidad(db, actor, f),   # F2-05: el prestador ve los activos críticos sin plan
        "solo_lectura": actor.rol in (Rol.supervisor_prestador, Rol.direccion_prestador),
    }


async def criticidad(db: AsyncSession, actor: Actor, f: Filtro) -> dict[str, Any]:
    """F2-05 (§6.9.3): activos por nivel, activos A sin plan de mantenimiento, mitigaciones y revisiones vencidas.
    No depende del período: la criticidad es el estado de hoy del parque, no un acumulado del mes."""
    from services import criticidad_service

    try:
        return await criticidad_service.resumen(db, actor, f.tenant_id)
    except Exception:  # noqa: BLE001 — un rol sin acceso al módulo no debe tumbar el tablero completo
        return {"por_nivel": {}, "total": 0, "criticos_sin_plan": 0, "criticos_sin_plan_ids": [],
                "mitigaciones_vencidas": 0, "revisiones_vencidas": 0}


async def _claves_escalacion(db: AsyncSession, f: Filtro | None = None):
    from services import alertas_service

    efectivas = await alertas_service.escalaciones(
        db, tenant_id=f.tenant_id if f else None, prestador_id=f.prestador_id if f else None)
    return [e["clave"] for e in efectivas]


async def _alertas_por_clave(db: AsyncSession, f: Filtro, claves: tuple[str, ...]) -> list[dict]:
    if not claves:
        return []
    consulta = select(AlertaHistorial).where(AlertaHistorial.clave_alerta.in_(claves),
                                             AlertaHistorial.timestamp_disparo >= f.inicio,
                                             AlertaHistorial.timestamp_disparo < f.fin)
    if f.tenant_id:
        consulta = consulta.where(AlertaHistorial.tenant_id == f.tenant_id)
    if f.prestador_id:
        consulta = consulta.where(AlertaHistorial.prestador_id == f.prestador_id)
    filas = list((await db.execute(consulta.order_by(AlertaHistorial.timestamp_disparo.desc()).limit(200))).scalars())
    return [{"id": str(a.id), "clave": a.clave_alerta, "disparo": a.timestamp_disparo, "datos": a.datos_contexto_json,
             "atendida": a.atendida_at is not None, "escalada": a.escalada,
             "estado": a.estado.value if isinstance(a.estado, EstadoAlerta) else str(a.estado)} for a in filas]


async def _por_cliente(db: AsyncSession, f: Filtro) -> list[dict]:
    from models.organizaciones import Tenant

    consulta = (select(Tenant.razon_social, Folio.estado, func.count()).join(Folio, Folio.tenant_id == Tenant.id)
                .where(Folio.capturado_at >= f.inicio, Folio.capturado_at < f.fin))
    if f.prestador_id:
        consulta = consulta.where(Folio.prestador_id == f.prestador_id)
    filas = (await db.execute(consulta.group_by(Tenant.razon_social, Folio.estado))).all()
    salida: dict[str, dict[str, int]] = {}
    for nombre, estado, n in filas:
        salida.setdefault(nombre, {})[estado.value] = n
    return [{"cliente": k, "por_estado": v, "total": sum(v.values())} for k, v in sorted(salida.items())]


async def _calificacion(db: AsyncSession, actor: Actor, f: Filtro) -> dict | None:
    from models.seguimiento import AdminUNCalificacion

    fila = (await db.execute(select(AdminUNCalificacion).where(
        AdminUNCalificacion.usuario_id == actor.id).order_by(AdminUNCalificacion.created_at.desc()))).scalars().first()
    if fila is None:
        return None
    return {"periodo": fila.periodo, "calificacion": str(fila.calificacion_final),
            "clasificados_en_plazo": fila.folios_clasificados_tiempo, "tardios": fila.folios_tardios,
            "sin_clasificar": fila.folios_sin_clasificar, "minutas_respondidas": fila.minutas_respondidas}
