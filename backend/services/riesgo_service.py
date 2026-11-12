"""FMEA simplificado: modos de falla por activo, acciones de mitigación y su efectividad medida (§6.9.3). F2-05.

**Lo que ACMA aporta y una hoja de cálculo no:** la frecuencia de cada modo de falla no la teclea nadie, sale del
historial de folios. El servicio *propone* los modos de falla de un equipo con sus tipos de falla y sus causas raíz
más frecuentes, y una persona los acepta, los edita o los descarta.

**Nivel de riesgo** = severidad × frecuencia, y × detección cuando se captura (el RPN clásico del FMEA). §6.9.3 pide
severidad × frecuencia; la detección es opcional porque no todos los clientes la evalúan, y cuando está, el número
deja de ser comparable con los que no la tienen: por eso la categoría (bajo/medio/alto/crítico) se calcula siempre
con severidad × frecuencia, que es lo que ubica el modo en la matriz 5×5.

**Efectividad de una mitigación**: se comparan los seis meses anteriores a la implementación contra los seis
posteriores, en dos números —las fallas del equipo y su MTBF—. Hasta que pasen 90 días dice «sin datos
suficientes»: antes de eso la comparación es ruido, no medición.
"""
import logging
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.dependencias import Actor
from core.errors import ErrorAPI, no_encontrado, prohibido
from models.catalogos import Equipo, NivelSeveridadCatalogo, TipoEquipo, TipoFalla
from models.criticidad import (
    ActivoModoFalla, ActivoRiesgoMitigacion, EstadoMitigacion, OrigenModoFalla, TipoMitigacion,
)
from models.folios import EstadoFolio, Folio, TipoFolio
from models.formularios import FormularioRespuesta, OrigenRespuesta
from services import auditoria

log = logging.getLogger("acma.riesgo")
DIAS_MINIMOS_EFECTIVIDAD = 90
MESES_VENTANA = 6

# Severidad propuesta desde la severidad del folio: es la escala que ya usa la operación.
SEVERIDAD_POR_CLAVE = {"muy_baja": 1, "baja": 2, "media": 3, "alta": 4, "critica": 5}


def nivel_riesgo(severidad: int, frecuencia: int, deteccion: int | None = None) -> int:
    return int(severidad) * int(frecuencia) * (int(deteccion) if deteccion else 1)


def categoria_riesgo(severidad: int, frecuencia: int) -> str:
    """Categoría de la matriz 5×5, siempre con severidad × frecuencia para que sea comparable entre clientes."""
    producto = int(severidad) * int(frecuencia)
    if producto >= 16:
        return "critico"
    if producto >= 10:
        return "alto"
    if producto >= 5:
        return "medio"
    return "bajo"


def _fecha(valor: Any) -> date | None:
    """Las fechas pueden llegar ya convertidas (API, con Pydantic) o como texto ISO (seed, importador)."""
    if valor is None or isinstance(valor, date):
        return valor
    try:
        return date.fromisoformat(str(valor)[:10])
    except ValueError:
        raise ErrorAPI(422, "FECHA_INVALIDA", f"Fecha inválida: {valor} (usa AAAA-MM-DD)") from None


def frecuencia_desde_fallas(fallas: int) -> int:
    """Misma idea que la escala de probabilidad de la criticidad, en 12 meses: 0 → 1, 1–2 → 2, 3–5 → 3, 6–11 → 4,
    12+ → 5."""
    if fallas <= 0:
        return 1
    if fallas <= 2:
        return 2
    if fallas <= 5:
        return 3
    if fallas <= 11:
        return 4
    return 5


def _exigir(actor: Actor, que: str) -> None:
    from services.criticidad_service import REGISTRAN_RIESGO

    if not actor.es_superadmin and actor.rol not in REGISTRAN_RIESGO:
        raise prohibido(f"Tu rol no {que}")


async def equipo_visible(db: AsyncSession, actor: Actor, equipo_id: UUID) -> Equipo:
    from services import medidores_service

    return await medidores_service.equipo_visible(db, actor, equipo_id)


# ------------------------------------------------------------------ sugerencias desde el historial

async def _causas_raiz(db: AsyncSession, folio_ids: list[UUID]) -> dict[UUID, str]:
    """La causa raíz que el técnico eligió en el formulario de atención (catálogo «Causa raíz» de P03)."""
    if not folio_ids:
        return {}
    filas = (await db.execute(select(FormularioRespuesta.referencia_id, FormularioRespuesta.respuestas_json).where(
        FormularioRespuesta.referencia_id.in_(folio_ids),
        FormularioRespuesta.origen == OrigenRespuesta.folio_atencion))).all()
    salida: dict[UUID, str] = {}
    for referencia, respuestas in filas:
        valor = (respuestas or {}).get("causa_raiz")
        if valor:
            salida[referencia] = str(valor)
    return salida


async def _etiquetas_causa(db: AsyncSession, tenant_id: UUID) -> dict[str, str]:
    from models.formularios import CatalogoPersonalizado, CatalogoPersonalizadoOpcion

    filas = (await db.execute(select(CatalogoPersonalizadoOpcion.valor, CatalogoPersonalizadoOpcion.etiqueta)
                              .join(CatalogoPersonalizado, CatalogoPersonalizado.id == CatalogoPersonalizadoOpcion.catalogo_id)
                              .where(CatalogoPersonalizado.clave == "causa_raiz",
                                     CatalogoPersonalizado.tenant_id == tenant_id))).all()
    return {v: e for v, e in filas}


async def sugerir(db: AsyncSession, actor: Actor, equipo: Equipo, meses: int = 12) -> list[dict[str, Any]]:
    """Modos de falla propuestos: los tipos de falla más frecuentes de los correctivos cerrados del equipo, con la
    causa raíz más común de cada uno y la severidad que la operación ya les asignó."""
    _exigir(actor, "consulta el análisis de riesgo")
    desde = datetime.now(UTC) - timedelta(days=30 * meses)
    filas = (await db.execute(
        select(Folio.id, Folio.tipo_falla_id, TipoFalla.descripcion, NivelSeveridadCatalogo.clave)
        .outerjoin(TipoFalla, TipoFalla.id == Folio.tipo_falla_id)
        .outerjoin(NivelSeveridadCatalogo, NivelSeveridadCatalogo.id == Folio.severidad_id)
        .where(Folio.equipo_id == equipo.id, Folio.tipo_folio == TipoFolio.correctivo,
               Folio.estado == EstadoFolio.cerrado, Folio.fecha_cierre >= desde))).all()
    if not filas:
        return []
    causas = await _causas_raiz(db, [f[0] for f in filas])
    etiquetas = await _etiquetas_causa(db, equipo.tenant_id)
    existentes = {m.tipo_falla_id for m in await modos_de_equipo(db, equipo) if m.tipo_falla_id}

    agrupado: dict[UUID | None, dict[str, Any]] = {}
    for folio_id, tipo_falla_id, descripcion, severidad_clave in filas:
        g = agrupado.setdefault(tipo_falla_id, {"tipo_falla_id": tipo_falla_id,
                                                "descripcion_falla": descripcion or "Falla sin tipo registrado",
                                                "fallas_12m": 0, "severidades": [], "causas": {}})
        g["fallas_12m"] += 1
        if severidad_clave:
            g["severidades"].append(SEVERIDAD_POR_CLAVE.get(str(severidad_clave), 3))
        causa = causas.get(folio_id)
        if causa:
            g["causas"][causa] = g["causas"].get(causa, 0) + 1

    salida = []
    for g in sorted(agrupado.values(), key=lambda x: x["fallas_12m"], reverse=True):
        severidad = max(g["severidades"]) if g["severidades"] else 3
        frecuencia = frecuencia_desde_fallas(g["fallas_12m"])
        causa_valor = max(g["causas"], key=g["causas"].get) if g["causas"] else None
        salida.append({
            "descripcion_falla": g["descripcion_falla"], "tipo_falla_id": g["tipo_falla_id"],
            "causa_probable": etiquetas.get(causa_valor, causa_valor or ""),
            "severidad": severidad, "frecuencia_historica": frecuencia, "fallas_12m": g["fallas_12m"],
            "nivel_riesgo": nivel_riesgo(severidad, frecuencia),
            "categoria": categoria_riesgo(severidad, frecuencia),
            "ya_registrado": g["tipo_falla_id"] in existentes,
            "nota": f"{g['fallas_12m']} falla(s) en {meses} meses"
                    + (f"; causa más frecuente: {etiquetas.get(causa_valor, causa_valor)}" if causa_valor else ""),
        })
    return salida


# ------------------------------------------------------------------ modos de falla

async def modos_de_equipo(db: AsyncSession, equipo: Equipo, incluir_genericos: bool = True,
                          solo_activos: bool = True) -> list[ActivoModoFalla]:
    consulta = select(ActivoModoFalla).where(ActivoModoFalla.tenant_id == equipo.tenant_id)
    if incluir_genericos:
        consulta = consulta.where((ActivoModoFalla.equipo_id == equipo.id)
                                  | (ActivoModoFalla.tipo_equipo_id == equipo.tipo_equipo_id))
    else:
        consulta = consulta.where(ActivoModoFalla.equipo_id == equipo.id)
    if solo_activos:
        consulta = consulta.where(ActivoModoFalla.activo.is_(True))
    return list((await db.execute(consulta.order_by(ActivoModoFalla.nivel_riesgo.desc()))).scalars())


async def crear_modo(db: AsyncSession, actor: Actor, datos: dict[str, Any],
                     request: Request | None = None) -> ActivoModoFalla:
    _exigir(actor, "registra modos de falla")
    equipo_id, tipo_equipo_id = datos.get("equipo_id"), datos.get("tipo_equipo_id")
    if bool(equipo_id) == bool(tipo_equipo_id):
        raise ErrorAPI(422, "DUENIO_REQUERIDO",
                       "Un modo de falla es de un equipo **o** genérico de un tipo de equipo, no de los dos")
    if equipo_id:
        equipo = await equipo_visible(db, actor, UUID(str(equipo_id)))
        tenant_id = equipo.tenant_id
    else:
        tipo = await db.get(TipoEquipo, UUID(str(tipo_equipo_id)))
        if tipo is None:
            raise no_encontrado("Tipo de equipo")
        tenant_id = datos.get("tenant_id") or actor.tenant_id
        if tenant_id is None:
            raise ErrorAPI(422, "TENANT_REQUERIDO", "Indica el cliente del modo de falla genérico")
        if not actor.es_superadmin and actor.dominio.value == "tenant" and tenant_id != actor.tenant_id:
            raise no_encontrado("Cliente")
    severidad = int(datos.get("severidad") or 3)
    frecuencia = int(datos.get("frecuencia_historica") or 1)
    deteccion = int(datos["deteccion"]) if datos.get("deteccion") else None
    for nombre, valor in (("severidad", severidad), ("frecuencia_historica", frecuencia)):
        if not 1 <= valor <= 5:
            raise ErrorAPI(422, "ESCALA_INVALIDA", f"{nombre} va de 1 a 5")
    if deteccion is not None and not 1 <= deteccion <= 5:
        raise ErrorAPI(422, "ESCALA_INVALIDA", "deteccion va de 1 a 5")
    modo = ActivoModoFalla(
        tenant_id=tenant_id, equipo_id=UUID(str(equipo_id)) if equipo_id else None,
        tipo_equipo_id=UUID(str(tipo_equipo_id)) if tipo_equipo_id else None,
        descripcion_falla=str(datos["descripcion_falla"])[:300],
        tipo_falla_id=UUID(str(datos["tipo_falla_id"])) if datos.get("tipo_falla_id") else None,
        causa_probable=datos.get("causa_probable") or "", efecto_operacional=datos.get("efecto_operacional") or "",
        severidad=severidad, frecuencia_historica=frecuencia, fallas_12m=int(datos.get("fallas_12m") or 0),
        deteccion=deteccion, nivel_riesgo=nivel_riesgo(severidad, frecuencia, deteccion),
        origen=OrigenModoFalla(datos.get("origen") or "manual"), registrado_por=actor.id)
    db.add(modo)
    await db.flush()
    await auditoria.registrar_actor(db, actor, "riesgo.modo_falla_alta", request, tenant_id=tenant_id,
                                    recurso_tipo="activo_modo_falla", recurso_id=modo.id,
                                    despues={"descripcion": modo.descripcion_falla, "severidad": severidad,
                                             "frecuencia": frecuencia, "nivel_riesgo": modo.nivel_riesgo})
    return modo


async def aceptar_sugerencias(db: AsyncSession, actor: Actor, equipo: Equipo, sugerencias: list[dict[str, Any]],
                              request: Request | None = None) -> list[ActivoModoFalla]:
    """Alta en lote de los modos propuestos que la persona aceptó, marcados como `sugerido`."""
    creados = []
    for s in sugerencias:
        creados.append(await crear_modo(db, actor, {**s, "equipo_id": str(equipo.id), "origen": "sugerido"}, request))
    return creados


async def editar_modo(db: AsyncSession, actor: Actor, modo: ActivoModoFalla, cambios: dict[str, Any],
                      request: Request | None = None) -> ActivoModoFalla:
    _exigir(actor, "edita modos de falla")
    antes = auditoria.instantanea(modo)
    for campo in ("descripcion_falla", "causa_probable", "efecto_operacional", "activo"):
        if cambios.get(campo) is not None:
            setattr(modo, campo, cambios[campo])
    for campo in ("severidad", "frecuencia_historica", "deteccion"):
        if cambios.get(campo) is not None:
            valor = int(cambios[campo])
            if not 1 <= valor <= 5:
                raise ErrorAPI(422, "ESCALA_INVALIDA", f"{campo} va de 1 a 5")
            setattr(modo, campo, valor)
    if cambios.get("tipo_falla_id") is not None:
        modo.tipo_falla_id = UUID(str(cambios["tipo_falla_id"])) if cambios["tipo_falla_id"] else None
    modo.nivel_riesgo = nivel_riesgo(modo.severidad, modo.frecuencia_historica, modo.deteccion)
    await db.flush()
    await auditoria.registrar_actor(db, actor, "riesgo.modo_falla_modificacion", request, tenant_id=modo.tenant_id,
                                    recurso_tipo="activo_modo_falla", recurso_id=modo.id, antes=antes,
                                    despues=auditoria.instantanea(modo))
    return modo


async def refrescar_frecuencias(db: AsyncSession, equipo: Equipo) -> int:
    """La frecuencia histórica de los modos de falla con tipo de falla se vuelve a leer del historial: es un dato
    medido, no capturado. Lo llama la tarea semanal junto con el recálculo de criticidad."""
    desde = datetime.now(UTC) - timedelta(days=365)
    conteos = {tipo_falla_id: int(total) for tipo_falla_id, total in (await db.execute(
        select(Folio.tipo_falla_id, func.count(Folio.id)).where(
            Folio.equipo_id == equipo.id, Folio.tipo_folio == TipoFolio.correctivo,
            Folio.estado == EstadoFolio.cerrado, Folio.fecha_cierre >= desde).group_by(Folio.tipo_falla_id))).all()}
    cambiados = 0
    for modo in await modos_de_equipo(db, equipo, incluir_genericos=False, solo_activos=True):
        if modo.tipo_falla_id is None:
            continue
        fallas = conteos.get(modo.tipo_falla_id, 0)
        frecuencia = frecuencia_desde_fallas(fallas)
        if modo.fallas_12m != fallas or modo.frecuencia_historica != frecuencia:
            modo.fallas_12m, modo.frecuencia_historica = fallas, frecuencia
            modo.nivel_riesgo = nivel_riesgo(modo.severidad, frecuencia, modo.deteccion)
            cambiados += 1
    await db.flush()
    return cambiados


async def matriz(db: AsyncSession, actor: Actor, tenant_id: UUID | None = None) -> dict[str, Any]:
    """Matriz de riesgo 5×5 de los modos de falla (severidad × frecuencia) con su conteo por celda."""
    _exigir(actor, "consulta el análisis de riesgo")
    from services.criticidad_service import _tenants_visibles

    tenants = await _tenants_visibles(db, actor)
    consulta = select(ActivoModoFalla).where(ActivoModoFalla.activo.is_(True))
    if tenant_id:
        consulta = consulta.where(ActivoModoFalla.tenant_id == tenant_id)
    elif tenants is not None:
        consulta = consulta.where(ActivoModoFalla.tenant_id.in_(tenants or [UUID(int=0)]))
    modos = list((await db.execute(consulta)).scalars())
    celdas: dict[str, dict[str, Any]] = {}
    for m in modos:
        clave = f"{m.severidad}x{m.frecuencia_historica}"
        celda = celdas.setdefault(clave, {"severidad": m.severidad, "frecuencia": m.frecuencia_historica, "total": 0,
                                          "categoria": categoria_riesgo(m.severidad, m.frecuencia_historica),
                                          "modos": []})
        celda["total"] += 1
        celda["modos"].append({"id": str(m.id), "descripcion": m.descripcion_falla,
                               "equipo_id": str(m.equipo_id) if m.equipo_id else None,
                               "nivel_riesgo": m.nivel_riesgo})
    return {"celdas": list(celdas.values()), "total": len(modos),
            "por_categoria": {c: sum(1 for m in modos if categoria_riesgo(m.severidad, m.frecuencia_historica) == c)
                              for c in ("bajo", "medio", "alto", "critico")}}


# ------------------------------------------------------------------ mitigaciones

async def mitigaciones_de(db: AsyncSession, modo_falla_id: UUID) -> list[ActivoRiesgoMitigacion]:
    return list((await db.execute(select(ActivoRiesgoMitigacion).where(
        ActivoRiesgoMitigacion.modo_falla_id == modo_falla_id).order_by(ActivoRiesgoMitigacion.created_at))).scalars())


async def crear_mitigacion(db: AsyncSession, actor: Actor, modo: ActivoModoFalla, datos: dict[str, Any],
                           request: Request | None = None) -> ActivoRiesgoMitigacion:
    _exigir(actor, "registra acciones de mitigación")
    tipo = TipoMitigacion(datos.get("tipo") or "otro")
    if tipo == TipoMitigacion.plan_preventivo and not datos.get("plan_mantenimiento_id"):
        raise ErrorAPI(422, "PLAN_REQUERIDO",
                       "Una mitigación de tipo «plan preventivo» se vincula a un plan de mantenimiento")
    if tipo == TipoMitigacion.capacitacion and not datos.get("curso_id"):
        raise ErrorAPI(422, "CURSO_REQUERIDO", "Una mitigación de tipo «capacitación» se vincula a un curso")
    if tipo == TipoMitigacion.refaccion_en_inventario and not datos.get("articulo_id"):
        raise ErrorAPI(422, "ARTICULO_REQUERIDO", "Una mitigación de inventario se vincula a un artículo")
    m = ActivoRiesgoMitigacion(
        modo_falla_id=modo.id, tenant_id=modo.tenant_id, accion_mitigacion=str(datos["accion_mitigacion"]).strip(),
        tipo=tipo,
        plan_mantenimiento_id=UUID(str(datos["plan_mantenimiento_id"])) if datos.get("plan_mantenimiento_id") else None,
        curso_id=UUID(str(datos["curso_id"])) if datos.get("curso_id") else None,
        articulo_id=UUID(str(datos["articulo_id"])) if datos.get("articulo_id") else None,
        responsable_id=UUID(str(datos["responsable_id"])) if datos.get("responsable_id") else None,
        fecha_compromiso=_fecha(datos.get("fecha_compromiso")), registrado_por=actor.id)
    if not m.accion_mitigacion:
        raise ErrorAPI(422, "ACCION_REQUERIDA", "Describe la acción de mitigación")
    db.add(m)
    await db.flush()
    await auditoria.registrar_actor(db, actor, "riesgo.mitigacion_alta", request, tenant_id=modo.tenant_id,
                                    recurso_tipo="activo_riesgo_mitigacion", recurso_id=m.id,
                                    despues={"accion": m.accion_mitigacion, "tipo": tipo.value,
                                             "fecha_compromiso": str(m.fecha_compromiso) if m.fecha_compromiso else None})
    return m


async def cambiar_estado(db: AsyncSession, actor: Actor, m: ActivoRiesgoMitigacion, estado: EstadoMitigacion, *,
                         fecha_implementacion: date | None = None, razon: str = "",
                         request: Request | None = None) -> ActivoRiesgoMitigacion:
    _exigir(actor, "cambia el estado de las mitigaciones")
    antes = auditoria.instantanea(m)
    if estado == EstadoMitigacion.implementada:
        m.fecha_implementacion = _fecha(fecha_implementacion) or date.today()
        if m.fecha_implementacion > date.today():
            raise ErrorAPI(422, "FECHA_FUTURA", "La fecha de implementación no puede estar en el futuro")
    if estado == EstadoMitigacion.descartada:
        if not (razon or "").strip():
            raise ErrorAPI(422, "RAZON_REQUERIDA", "Descartar una mitigación exige razón")
        m.razon_descarte = razon.strip()
    m.estado = estado
    await db.flush()
    if estado == EstadoMitigacion.implementada:
        m.efectividad_json = await efectividad(db, m)
        await db.flush()
    await auditoria.registrar_actor(db, actor, "riesgo.mitigacion_estado", request, tenant_id=m.tenant_id,
                                    recurso_tipo="activo_riesgo_mitigacion", recurso_id=m.id, antes=antes,
                                    despues=auditoria.instantanea(m))
    return m


async def _fallas_y_mtbf(db: AsyncSession, equipo_id: UUID, desde: datetime, hasta: datetime) -> dict[str, Any]:
    fechas = list((await db.execute(select(Folio.capturado_at).where(
        Folio.equipo_id == equipo_id, Folio.tipo_folio == TipoFolio.correctivo,
        Folio.capturado_at >= desde, Folio.capturado_at < hasta).order_by(Folio.capturado_at))).scalars())
    intervalos = [(b - a).total_seconds() / 3600 for a, b in zip(fechas, fechas[1:])]
    mtbf = (Decimal(str(sum(intervalos) / len(intervalos))).quantize(Decimal("0.01")) if intervalos else None)
    return {"fallas": len(fechas), "mtbf_horas": str(mtbf) if mtbf is not None else None}


async def efectividad(db: AsyncSession, m: ActivoRiesgoMitigacion) -> dict[str, Any]:
    """Antes contra después de la implementación, en fallas y en MTBF. «Sin datos suficientes» hasta los 90 días."""
    if m.fecha_implementacion is None:
        return {"estado": "sin_implementar",
                "nota": "La acción todavía no se implementa: no hay nada que comparar."}
    modo = await db.get(ActivoModoFalla, m.modo_falla_id)
    if modo is None or modo.equipo_id is None:
        return {"estado": "no_aplicable",
                "nota": "El modo de falla es genérico de un tipo de equipo: la efectividad se mide por equipo."}
    corte = datetime.combine(m.fecha_implementacion, datetime.min.time(), tzinfo=UTC)
    dias = (date.today() - m.fecha_implementacion).days
    antes = await _fallas_y_mtbf(db, modo.equipo_id, corte - timedelta(days=30 * MESES_VENTANA), corte)
    despues = await _fallas_y_mtbf(db, modo.equipo_id, corte, min(datetime.now(UTC), corte + timedelta(days=30 * MESES_VENTANA)))
    base = {"estado": "medida", "dias_desde_implementacion": dias, "ventana_meses": MESES_VENTANA,
            "antes": antes, "despues": despues}
    if dias < DIAS_MINIMOS_EFECTIVIDAD:
        return {**base, "estado": "sin_datos_suficientes",
                "nota": f"Faltan {DIAS_MINIMOS_EFECTIVIDAD - dias} días para poder comparar: antes de {DIAS_MINIMOS_EFECTIVIDAD} "
                        f"días la diferencia es ruido, no medición."}
    delta_fallas = antes["fallas"] - despues["fallas"]
    veredicto = "mejoro" if delta_fallas > 0 else "sin_cambio" if delta_fallas == 0 else "empeoro"
    mejora_mtbf = None
    if antes["mtbf_horas"] and despues["mtbf_horas"]:
        a, d = Decimal(antes["mtbf_horas"]), Decimal(despues["mtbf_horas"])
        if a > 0:
            mejora_mtbf = str(((d - a) / a * Decimal("100")).quantize(Decimal("0.01")))
    return {**base, "delta_fallas": delta_fallas, "veredicto": veredicto, "mejora_mtbf_pct": mejora_mtbf,
            "nota": f"{antes['fallas']} falla(s) en los {MESES_VENTANA} meses previos contra {despues['fallas']} "
                    f"después de implementar."}


async def pendientes(db: AsyncSession, actor: Actor, tenant_id: UUID | None = None,
                     solo_vencidas: bool = False) -> list[dict[str, Any]]:
    """Bandeja de acciones de mitigación: lo que está propuesto o en proceso, con lo vencido primero."""
    _exigir(actor, "consulta el análisis de riesgo")
    from services.criticidad_service import _tenants_visibles

    tenants = await _tenants_visibles(db, actor)
    consulta = (select(ActivoRiesgoMitigacion, ActivoModoFalla, Equipo)
                .join(ActivoModoFalla, ActivoModoFalla.id == ActivoRiesgoMitigacion.modo_falla_id)
                .outerjoin(Equipo, Equipo.id == ActivoModoFalla.equipo_id)
                .where(ActivoRiesgoMitigacion.estado.in_((EstadoMitigacion.propuesta, EstadoMitigacion.en_proceso)))
                .order_by(ActivoRiesgoMitigacion.fecha_compromiso.asc().nullslast()))
    if tenant_id:
        consulta = consulta.where(ActivoRiesgoMitigacion.tenant_id == tenant_id)
    elif tenants is not None:
        consulta = consulta.where(ActivoRiesgoMitigacion.tenant_id.in_(tenants or [UUID(int=0)]))
    if solo_vencidas:
        consulta = consulta.where(ActivoRiesgoMitigacion.fecha_compromiso < date.today())
    salida = []
    for m, modo, equipo in (await db.execute(consulta)).all():
        salida.append({
            "id": m.id, "accion_mitigacion": m.accion_mitigacion, "tipo": m.tipo, "estado": m.estado,
            "fecha_compromiso": m.fecha_compromiso, "responsable_id": m.responsable_id,
            "vencida": bool(m.fecha_compromiso and m.fecha_compromiso < date.today()),
            "dias_vencida": (date.today() - m.fecha_compromiso).days if m.fecha_compromiso and m.fecha_compromiso < date.today() else 0,
            "modo_falla_id": modo.id, "modo_falla": modo.descripcion_falla, "nivel_riesgo": modo.nivel_riesgo,
            "equipo_id": equipo.id if equipo else None, "equipo_codigo": equipo.codigo if equipo else None,
            "equipo_nombre": equipo.nombre if equipo else None, "tenant_id": m.tenant_id,
        })
    return salida
