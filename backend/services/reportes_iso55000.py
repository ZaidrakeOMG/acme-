"""Reportes que respaldan una certificación ISO 55000 (§6.9.3, §2). F2-05.

No traen un generador nuevo: arman las mismas secciones `{titulo, tipo, columnas, filas}` que ya comparten el PDF y
el Excel de P10, así que `reportes_service.generar()` los produce en los dos formatos, con el logo y los colores
del prestador, y los deja registrados en `reportes_generados` con su tiempo de generación.

Los cinco que pide el prompt, y por qué cada uno le sirve a un auditor:

| Clave | Qué demuestra |
|---|---|
| `iso_registro` | Que cada activo tiene criticidad documentada, con fecha y próxima revisión. |
| `iso_matriz` | Que el riesgo está ubicado: probabilidad × impacto con los activos en cada celda. |
| `iso_modos_falla` | Que los modos de falla están analizados y tienen plan de mitigación con responsable. |
| `iso_mejora_continua` | Que la gestión mejora: MTBF y MTTR por nivel, mes a mes, y cobertura de preventivos. |
| `iso_historial` | La trazabilidad: cada cambio de criticidad, cuándo, por qué y quién. |
"""
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.dependencias import Actor
from models.base import Rol
from models.catalogos import Equipo
from models.criticidad import (
    ETIQUETA_NIVEL, IMPLICACIONES_POR_NIVEL, ActivoCriticidad, ActivoModoFalla, ActivoRiesgoMitigacion,
    CriticidadEvaluacion,
)
from models.folios import EstadoFolio, Folio, TipoFolio
from models.preventivos import EquipoPlan, EstadoPlan, PlanMantenimiento
from models.usuarios import Usuario
from services import criticidad_service, riesgo_service

NIVELES = ("A", "B", "C", "D")

PLANTILLAS = {
    "iso_registro": "ISO 55000 · Registro de activos con criticidad",
    "iso_matriz": "ISO 55000 · Matriz de riesgo por activo",
    "iso_modos_falla": "ISO 55000 · Modos de falla y plan de mitigación",
    "iso_mejora_continua": "ISO 55000 · Mejora continua: MTBF, MTTR y cobertura de preventivos",
    "iso_historial": "ISO 55000 · Historial de evaluaciones de criticidad",
}
# El cliente descarga los de su tenant; el prestador, los de los clientes que atiende (§5.1, §5.2).
PERMISOS = {Rol.superadmin, Rol.admin_empresa, Rol.admin_un, Rol.admin_prestador, Rol.mesa_control,
            Rol.direccion_prestador}


def _mes(d: date) -> str:
    return f"{d.year}-{d.month:02d}"


async def _niveles_por_equipo(db: AsyncSession, tenant_ids: list[UUID] | None,
                              tenant_id: UUID | None) -> dict[UUID, str]:
    consulta = select(ActivoCriticidad.equipo_id, ActivoCriticidad.nivel)
    if tenant_id:
        consulta = consulta.where(ActivoCriticidad.tenant_id == tenant_id)
    elif tenant_ids is not None:
        consulta = consulta.where(ActivoCriticidad.tenant_id.in_(tenant_ids or [UUID(int=0)]))
    return {e: str(n) for e, n in (await db.execute(consulta)).all()}


async def _mtbf_mttr_por_nivel(db: AsyncSession, niveles: dict[UUID, str], desde: date,
                               hasta: date) -> list[tuple]:
    """Tendencia mensual de MTBF y MTTR agrupada por nivel de criticidad, con la misma definición del tablero."""
    inicio = datetime.combine(desde, datetime.min.time(), tzinfo=UTC)
    fin = datetime.combine(hasta, datetime.max.time(), tzinfo=UTC)
    filas = (await db.execute(select(Folio.equipo_id, Folio.capturado_at, Folio.fecha_cierre).where(
        Folio.tipo_folio == TipoFolio.correctivo, Folio.equipo_id.in_(list(niveles) or [UUID(int=0)]),
        Folio.capturado_at >= inicio, Folio.capturado_at <= fin).order_by(Folio.equipo_id, Folio.capturado_at))).all()
    # (mes, nivel) → horas de reparación y fechas por equipo para los intervalos entre fallas.
    reparacion: dict[tuple[str, str], list[float]] = {}
    por_equipo: dict[UUID, list[datetime]] = {}
    for equipo_id, capturado, cierre in filas:
        nivel = niveles.get(equipo_id, "D")
        por_equipo.setdefault(equipo_id, []).append(capturado)
        if cierre:
            reparacion.setdefault((_mes(cierre.date()), nivel), []).append((cierre - capturado).total_seconds() / 3600)
    entre_fallas: dict[tuple[str, str], list[float]] = {}
    for equipo_id, fechas in por_equipo.items():
        nivel = niveles.get(equipo_id, "D")
        for a, b in zip(fechas, fechas[1:]):
            entre_fallas.setdefault((_mes(b.date()), nivel), []).append((b - a).total_seconds() / 3600)
    claves = sorted(set(reparacion) | set(entre_fallas))
    salida = []
    for mes, nivel in claves:
        mttr = reparacion.get((mes, nivel)) or []
        mtbf = entre_fallas.get((mes, nivel)) or []
        salida.append((mes, nivel, len(mttr),
                       f"{sum(mttr) / len(mttr):.2f}" if mttr else "sin datos",
                       f"{sum(mtbf) / len(mtbf):.2f}" if mtbf else "sin datos"))
    return salida


async def _cobertura_preventivos(db: AsyncSession, niveles: dict[UUID, str]) -> list[tuple]:
    """Porcentaje de activos A y B con plan activo, y su cumplimiento del calendario (§6.9.3 implicación de PM)."""
    from services import bi_service

    con_plan = set((await db.execute(
        select(EquipoPlan.equipo_id).join(PlanMantenimiento, PlanMantenimiento.id == EquipoPlan.plan_id)
        .where(EquipoPlan.equipo_id.in_(list(niveles) or [UUID(int=0)]), EquipoPlan.activo.is_(True),
               PlanMantenimiento.estado == EstadoPlan.activo))).scalars())
    salida = []
    for nivel in NIVELES:
        equipos = [e for e, n in niveles.items() if n == nivel]
        if not equipos:
            continue
        cubiertos = sum(1 for e in equipos if e in con_plan)
        pct = Decimal(cubiertos * 100) / Decimal(len(equipos))
        ejecutados = int((await db.execute(select(func.count(Folio.id)).where(
            Folio.equipo_id.in_(equipos), Folio.tipo_folio == TipoFolio.preventivo,
            Folio.estado == EstadoFolio.cerrado))).scalar() or 0)
        salida.append((nivel, ETIQUETA_NIVEL[nivel], len(equipos), cubiertos, f"{pct.quantize(Decimal('0.01'))} %",
                       ejecutados))
    return salida


async def secciones(db: AsyncSession, actor: Actor, tipo: str, f) -> list[dict[str, Any]]:
    """Las secciones del reporte, en el mismo formato que las de P10."""
    tenant_ids = await criticidad_service._tenants_visibles(db, actor)
    tenant_id = f.tenant_id
    niveles = await _niveles_por_equipo(db, tenant_ids, tenant_id)
    resumen = await criticidad_service.resumen(db, actor, tenant_id)

    cabecera = {"titulo": "Resumen de la gestión de activos", "tipo": "kpi", "filas": [
        ("Activos con criticidad evaluada", resumen["total"]),
        *[(f"Nivel {n} ({ETIQUETA_NIVEL[n]})", resumen["por_nivel"].get(n, 0)) for n in NIVELES],
        ("Activos A sin plan de mantenimiento", resumen["criticos_sin_plan"]),
        ("Revisiones de criticidad vencidas", resumen["revisiones_vencidas"]),
        ("Acciones de mitigación vencidas", resumen["mitigaciones_vencidas"]),
    ]}

    if tipo == "iso_registro":
        filas = await criticidad_service.listado(db, actor, tenant_id=tenant_id)
        return [cabecera,
                {"titulo": "Registro de activos", "tipo": "tabla",
                 "columnas": ["Código", "Activo", "Tipo", "Unidad", "Nivel", "Índice", "Probabilidad", "Impacto",
                              "Origen", "Evaluado", "Próxima revisión"],
                 "filas": [(x["codigo"], x["nombre"], x["tipo_equipo"], x["un_codigo"], x["nivel"],
                            str(x["indice_criticidad"]), str(x["probabilidad"]) + (" (estimada)" if x["probabilidad_estimada"] else ""),
                            str(x["impacto_ponderado"]), x["origen"], str(x["fecha_evaluacion"]),
                            str(x["proxima_revision"] or "") + (" · vencida" if x["revision_vencida"] else ""))
                           for x in filas]},
                {"titulo": "Implicaciones de mantenimiento por nivel", "tipo": "tabla",
                 "columnas": ["Nivel", "Etiqueta", "Implicaciones (§6.9.3)"],
                 "filas": [(n, ETIQUETA_NIVEL[n], IMPLICACIONES_POR_NIVEL[n]) for n in NIVELES]}]

    if tipo == "iso_matriz":
        matriz = await criticidad_service.matriz_riesgo(db, actor, tenant_id)
        celdas = sorted(matriz["celdas"], key=lambda c: (-c["probabilidad"], -c["impacto"]))
        return [cabecera,
                {"titulo": "Matriz de riesgo (probabilidad × impacto)", "tipo": "tabla",
                 "columnas": ["Probabilidad", "Impacto", "Activos", "Códigos"],
                 "filas": [(c["probabilidad"], c["impacto"], c["total"],
                            ", ".join(f"{x['codigo']} ({x['nivel']})" for x in c["equipos"][:20]))
                           for c in celdas]},
                {"titulo": "Matriz de riesgo de los modos de falla (severidad × frecuencia)", "tipo": "tabla",
                 "columnas": ["Severidad", "Frecuencia", "Categoría", "Modos de falla"],
                 "filas": [(c["severidad"], c["frecuencia"], c["categoria"], c["total"])
                           for c in sorted((await riesgo_service.matriz(db, actor, tenant_id))["celdas"],
                                           key=lambda c: (-c["severidad"], -c["frecuencia"]))]}]

    if tipo == "iso_modos_falla":
        consulta = (select(ActivoModoFalla, Equipo).outerjoin(Equipo, Equipo.id == ActivoModoFalla.equipo_id)
                    .where(ActivoModoFalla.activo.is_(True)).order_by(ActivoModoFalla.nivel_riesgo.desc()))
        if tenant_id:
            consulta = consulta.where(ActivoModoFalla.tenant_id == tenant_id)
        elif tenant_ids is not None:
            consulta = consulta.where(ActivoModoFalla.tenant_id.in_(tenant_ids or [UUID(int=0)]))
        modos = (await db.execute(consulta)).all()
        usuarios = {u.id: u.nombre for u in (await db.execute(select(Usuario))).scalars()}
        acciones = []
        for modo, _equipo in modos:
            for m in await riesgo_service.mitigaciones_de(db, modo.id):
                efect = m.efectividad_json or {}
                acciones.append((modo.descripcion_falla, m.accion_mitigacion,
                                 m.tipo.value if hasattr(m.tipo, "value") else str(m.tipo),
                                 usuarios.get(m.responsable_id, "sin responsable"),
                                 str(m.fecha_compromiso or ""), str(m.fecha_implementacion or ""),
                                 m.estado.value if hasattr(m.estado, "value") else str(m.estado),
                                 efect.get("veredicto") or efect.get("estado") or "sin medir"))
        return [cabecera,
                {"titulo": "Modos de falla analizados", "tipo": "tabla",
                 "columnas": ["Activo", "Modo de falla", "Causa probable", "Efecto", "Severidad", "Frecuencia",
                              "Detección", "Riesgo", "Categoría", "Origen"],
                 "filas": [(equipo.codigo if equipo else "genérico del tipo", modo.descripcion_falla,
                            modo.causa_probable, modo.efecto_operacional, modo.severidad, modo.frecuencia_historica,
                            modo.deteccion or "no evaluada", modo.nivel_riesgo,
                            riesgo_service.categoria_riesgo(modo.severidad, modo.frecuencia_historica),
                            modo.origen.value if hasattr(modo.origen, "value") else str(modo.origen))
                           for modo, equipo in modos]},
                {"titulo": "Plan de mitigación", "tipo": "tabla",
                 "columnas": ["Modo de falla", "Acción", "Tipo", "Responsable", "Compromiso", "Implementación",
                              "Estado", "Efectividad"],
                 "filas": acciones}]

    if tipo == "iso_mejora_continua":
        desde = f.desde if hasattr(f, "desde") else date.today() - timedelta(days=365)
        hasta = f.hasta if hasattr(f, "hasta") else date.today()
        return [cabecera,
                {"titulo": "Tendencia de MTBF y MTTR por nivel de criticidad", "tipo": "tabla",
                 "columnas": ["Mes", "Nivel", "Correctivos cerrados", "MTTR (h)", "MTBF (h)"],
                 "filas": await _mtbf_mttr_por_nivel(db, niveles, desde, hasta)},
                {"titulo": "Cobertura de mantenimiento preventivo por nivel", "tipo": "tabla",
                 "columnas": ["Nivel", "Etiqueta", "Activos", "Con plan activo", "Cobertura", "Preventivos cerrados"],
                 "filas": await _cobertura_preventivos(db, niveles)}]

    # iso_historial
    consulta = (select(CriticidadEvaluacion, Equipo).join(Equipo, Equipo.id == CriticidadEvaluacion.equipo_id)
                .order_by(CriticidadEvaluacion.timestamp.desc()).limit(2000))
    if tenant_id:
        consulta = consulta.where(CriticidadEvaluacion.tenant_id == tenant_id)
    elif tenant_ids is not None:
        consulta = consulta.where(CriticidadEvaluacion.tenant_id.in_(tenant_ids or [UUID(int=0)]))
    filas = (await db.execute(consulta)).all()
    usuarios = {u.id: u.nombre for u in (await db.execute(select(Usuario))).scalars()}
    return [cabecera,
            {"titulo": "Historial de evaluaciones de criticidad", "tipo": "tabla",
             "columnas": ["Fecha", "Activo", "Nivel anterior", "Nivel nuevo", "Índice anterior", "Índice nuevo",
                          "Motivo", "Razón", "Evaluó"],
             "filas": [(ev.timestamp.strftime("%Y-%m-%d %H:%M"), equipo.codigo, ev.nivel_anterior or "sin evaluar",
                        ev.nivel_nuevo, str(ev.indice_anterior or ""), str(ev.indice_nuevo),
                        ev.motivo.value if hasattr(ev.motivo, "value") else str(ev.motivo), ev.razon,
                        usuarios.get(ev.evaluado_por, "sistema"))
                       for ev, equipo in filas]}]
