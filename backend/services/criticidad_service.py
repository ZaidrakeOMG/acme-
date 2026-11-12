"""Análisis de criticidad por activo (ISO 55000, §6.9.3). F2-05.

**La fórmula es la del diseño, literal:**

    criticidad = probabilidad de falla × impacto ponderado
    impacto ponderado = Σ (dimensión 1–5 × su peso) ÷ 100          → queda en 1–5
    índice 0–100      = (probabilidad × impacto ponderado) ÷ 25 × 100

Las cuatro dimensiones y sus pesos son los de §6.9.3 (operacional 30 %, seguridad 35 %, económico 25 %, imagen
10 %) y se configuran por cliente, con un CHECK en la base que exige que sumen 100: si no suman, el índice deja de
significar lo que dice significar.

**Lo que el diseño no fijaba y aquí se decide** (anotado en `CONTEXTO.md` y en `docs/decisiones_para_validar.md`):
- La **escala de probabilidad**: el diseño dice «basada en historial de ACMA» sin dar los cortes. ACMA usa el número
  de correctivos cerrados del equipo en 12 meses (0 → 1, 1–2 → 2, 3–5 → 3, 6–11 → 4, 12+ → 5), configurable. Con
  `por_mtbf` configurado y suficientes fallas, usa el MTBF del equipo en lugar del conteo.
- La **normalización a 0–100**: dividir entre 25 (el producto máximo, 5×5) y multiplicar por 100. Por eso el índice
  mínimo real es 4 (1×1) y no 0.
- Los **rangos intermedios del impacto económico**: §6.9.3 solo fija los extremos ($5,000 y $500,000).
- Qué hacer con un **equipo sin historia**: se usa la probabilidad típica de su tipo de equipo en el cliente y, si
  tampoco hay, la del mismo tipo en toda la plataforma **anonimizada** (solo el número, nunca de quién), y la
  evaluación queda marcada como `probabilidad_estimada`.

La precisión de todo esto depende del historial: en desarrollo se calibra con el histórico sintético y en producción
conviene recalibrar a los 6–12 meses de operación real.
"""
import logging
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from uuid import UUID

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.dependencias import Actor
from core.errors import ErrorAPI, no_encontrado, prohibido
from core.rls import CONTEXTO_SISTEMA, fijar_contexto
from models.base import Dominio, Rol
from models.catalogos import Equipo, TipoEquipo
from models.costos import FolioCosto
from models.criticidad import (
    DIMENSIONES, ActivoCriticidad, CriticidadConfiguracion, CriticidadEvaluacion, MotivoEvaluacion, OrigenCriticidad,
)
from models.folios import EstadoFolio, Folio, TipoFolio
from services import auditoria, notificaciones

log = logging.getLogger("acma.criticidad")
CERO = Decimal("0")
CENTAVO = Decimal("0.01")
NIVELES = ("A", "B", "C", "D")

# Quién hace qué (§6.9.3 y §5.1): el cliente evalúa (es su operación la que se afecta) y el prestador consulta y
# registra riesgo.
EVALUAN = {Rol.superadmin, Rol.admin_empresa, Rol.admin_un}
CONFIGURAN = {Rol.superadmin, Rol.admin_empresa}
CONSULTAN = EVALUAN | {Rol.admin_prestador, Rol.mesa_control, Rol.despachador, Rol.supervisor_operadores,
                       Rol.direccion_prestador, Rol.supervisor_prestador}
# El FMEA lo arma quien conoce el equipo: el prestador que lo mantiene y el cliente que lo opera.
REGISTRAN_RIESGO = {Rol.superadmin, Rol.admin_empresa, Rol.admin_un, Rol.admin_prestador, Rol.mesa_control,
                    Rol.despachador}

# Descripción literal de cada nivel 1–5 de §6.9.3, para el formulario guiado.
GUIA_DIMENSIONES = {
    "operacional": {"pregunta": "¿Cuánto afecta la falla a la operación de la unidad?", "peso_default": 30,
                    "niveles": {1: "Sin impacto", 2: "Molestia menor", 3: "Afecta parte de la operación",
                                4: "Detiene un proceso importante", 5: "Cierre total"}},
    "seguridad": {"pregunta": "¿Puede la falla generar riesgo para personas o instalaciones?", "peso_default": 35,
                  "niveles": {1: "Sin riesgo", 2: "Riesgo leve", 3: "Riesgo con lesión menor posible",
                              4: "Riesgo de lesión seria", 5: "Riesgo de accidente grave"}},
    "economico": {"pregunta": "¿Cuál es el costo estimado de la falla?", "peso_default": 25,
                  "niveles": {1: "Menor a $5,000", 2: "De $5,000 a $25,000", 3: "De $25,000 a $100,000",
                              4: "De $100,000 a $500,000", 5: "Mayor a $500,000"}},
    "imagen": {"pregunta": "¿Afecta la falla la experiencia del cliente final?", "peso_default": 10,
               "niveles": {1: "Sin impacto visible", 2: "Lo nota el personal", 3: "Lo nota algún cliente",
                           4: "Lo notan varios clientes", 5: "Afecta directamente al cliente"}},
}


# ------------------------------------------------------------------ alcance

async def equipo_visible(db: AsyncSession, actor: Actor, equipo_id: UUID) -> Equipo:
    """Mismo alcance que la ficha del activo y que los medidores: se reutiliza para no tener dos reglas distintas."""
    from services import medidores_service

    return await medidores_service.equipo_visible(db, actor, equipo_id)


def _exigir(actor: Actor, roles: set[Rol], que: str) -> None:
    if not actor.es_superadmin and actor.rol not in roles:
        raise prohibido(f"Tu rol no {que}")


# ------------------------------------------------------------------ configuración

async def configuracion(db: AsyncSession, tenant_id: UUID) -> CriticidadConfiguracion:
    """La del cliente, creándola con los valores literales de §6.9.3 la primera vez."""
    from models.criticidad import (
        ESCALA_PROBABILIDAD_DEFAULT, IMPLICACIONES_DEFAULT, MESES_REVISION_DEFAULT, PESOS_DEFAULT,
        RANGOS_ECONOMICO_DEFAULT, RANGOS_NIVEL_DEFAULT,
    )

    cfg = (await db.execute(select(CriticidadConfiguracion).where(
        CriticidadConfiguracion.tenant_id == tenant_id))).scalar_one_or_none()
    if cfg is None:
        # Los valores se pasan explícitos: el ORM manda su propio default (`{}`) y se saltaría el de la columna, que
        # además rompería el CHECK de que los pesos sumen 100.
        cfg = CriticidadConfiguracion(
            tenant_id=tenant_id, pesos_json=dict(PESOS_DEFAULT),
            rangos_economico_json=[dict(r) for r in RANGOS_ECONOMICO_DEFAULT],
            escala_probabilidad_json={**ESCALA_PROBABILIDAD_DEFAULT},
            rangos_nivel_json=[dict(r) for r in RANGOS_NIVEL_DEFAULT],
            meses_revision=MESES_REVISION_DEFAULT,
            implicaciones_activas_json={k: dict(v) for k, v in IMPLICACIONES_DEFAULT.items()})
        db.add(cfg)
        await db.flush()
        await db.refresh(cfg)
    return cfg


def _validar_pesos(pesos: dict[str, Any]) -> dict[str, int]:
    faltantes = [d for d in DIMENSIONES if d not in pesos]
    if faltantes:
        raise ErrorAPI(422, "PESOS_INCOMPLETOS", f"Faltan los pesos de: {', '.join(faltantes)}")
    limpios = {}
    for d in DIMENSIONES:
        try:
            limpios[d] = int(pesos[d])
        except (TypeError, ValueError):
            raise ErrorAPI(422, "PESOS_INVALIDOS", f"El peso de {d} debe ser un número entero") from None
        if limpios[d] < 0:
            raise ErrorAPI(422, "PESOS_INVALIDOS", f"El peso de {d} no puede ser negativo")
    total = sum(limpios.values())
    if total != 100:
        raise ErrorAPI(422, "PESOS_NO_SUMAN_100",
                       f"Los pesos de las cuatro dimensiones suman {total} %: tienen que sumar 100 % para que el "
                       f"índice signifique lo que dice (§6.9.3)")
    return limpios


async def guardar_configuracion(db: AsyncSession, actor: Actor, tenant_id: UUID, cambios: dict[str, Any],
                                request: Request | None = None) -> CriticidadConfiguracion:
    _exigir(actor, CONFIGURAN, "configura la criticidad de los activos")
    if not actor.es_superadmin and tenant_id != actor.tenant_id:
        raise no_encontrado("Cliente")
    cfg = await configuracion(db, tenant_id)
    antes = auditoria.instantanea(cfg)
    if cambios.get("pesos_json") is not None:
        cfg.pesos_json = _validar_pesos(cambios["pesos_json"])
    for campo in ("rangos_economico_json", "rangos_nivel_json", "escala_probabilidad_json", "implicaciones_activas_json"):
        if cambios.get(campo) is not None:
            setattr(cfg, campo, cambios[campo])
    if cambios.get("meses_revision") is not None:
        meses = int(cambios["meses_revision"])
        if not 1 <= meses <= 60:
            raise ErrorAPI(422, "MESES_INVALIDOS", "Los meses de revisión van de 1 a 60")
        cfg.meses_revision = meses
    cfg.configurado_por = actor.id
    await db.flush()
    await auditoria.registrar_actor(db, actor, "criticidad.configuracion", request, tenant_id=tenant_id,
                                    recurso_tipo="criticidad_configuracion", recurso_id=cfg.id, antes=antes,
                                    despues=auditoria.instantanea(cfg))
    return cfg


# ------------------------------------------------------------------ la fórmula (pura: se prueba sin base)

def impacto_ponderado(dimensiones: dict[str, Any], pesos: dict[str, Any]) -> Decimal:
    """Σ (dimensión × peso) ÷ 100. Con los pesos de §6.9.3 y dimensiones 1–5, queda entre 1.00 y 5.00."""
    total = CERO
    for d in DIMENSIONES:
        valor = Decimal(str(dimensiones.get(d, 1)))
        if not Decimal("1") <= valor <= Decimal("5"):
            raise ErrorAPI(422, "DIMENSION_INVALIDA", f"La dimensión {d} va de 1 a 5 (llegó {valor})")
        total += valor * Decimal(str(pesos.get(d, 0)))
    return (total / Decimal("100")).quantize(CENTAVO, rounding=ROUND_HALF_UP)


def indice_de(probabilidad: Decimal, impacto: Decimal) -> Decimal:
    """(probabilidad × impacto) ÷ 25 × 100. El producto máximo es 25 (5×5), así que el índice llega a 100."""
    bruto = Decimal(str(probabilidad)) * Decimal(str(impacto))
    return (bruto / Decimal("25") * Decimal("100")).quantize(CENTAVO, rounding=ROUND_HALF_UP)


def nivel_de(indice: Decimal, rangos: list[dict[str, Any]] | None = None) -> str:
    """Rangos literales de §6.9.3: A 80–100, B 50–79, C 20–49, D 0–19. El índice es decimal, así que la frontera se
    lee como «desde»: 79.2 es B y 80.0 es A."""
    indice = Decimal(str(indice))
    for r in sorted(rangos or [], key=lambda x: Decimal(str(x.get("desde", 0))), reverse=True):
        if indice >= Decimal(str(r.get("desde", 0))):
            return str(r["nivel"])
    if not rangos:
        if indice >= 80:
            return "A"
        if indice >= 50:
            return "B"
        if indice >= 20:
            return "C"
    return "D"


def _nivel_por_rango(valor: Decimal, rangos: list[dict[str, Any]]) -> int:
    """Primer rango cuyo `hasta` no se pasa; `hasta: null` es el último."""
    for r in sorted(rangos, key=lambda x: (x.get("hasta") is None, x.get("hasta") or 0)):
        tope = r.get("hasta")
        if tope is None or valor <= Decimal(str(tope)):
            return int(r["nivel"])
    return 5


# ------------------------------------------------------------------ probabilidad desde el historial

async def _correctivos_cerrados(db: AsyncSession, equipo_id: UUID, desde: datetime) -> int:
    return int((await db.execute(select(func.count(Folio.id)).where(
        Folio.equipo_id == equipo_id, Folio.tipo_folio == TipoFolio.correctivo,
        Folio.estado == EstadoFolio.cerrado, Folio.fecha_cierre >= desde))).scalar() or 0)


async def _mtbf_horas(db: AsyncSession, equipo_id: UUID, desde: datetime) -> Decimal | None:
    """Horas promedio entre fallas consecutivas del equipo. Misma definición que el MTBF del tablero (P10)."""
    fechas = list((await db.execute(select(Folio.capturado_at).where(
        Folio.equipo_id == equipo_id, Folio.tipo_folio == TipoFolio.correctivo,
        Folio.capturado_at >= desde).order_by(Folio.capturado_at))).scalars())
    if len(fechas) < 2:
        return None
    intervalos = [(b - a).total_seconds() / 3600 for a, b in zip(fechas, fechas[1:])]
    return Decimal(str(sum(intervalos) / len(intervalos))).quantize(CENTAVO)


async def _meses_de_historia(db: AsyncSession, equipo: Equipo) -> int:
    """Meses que ACMA lleva observando el activo, que es lo que le da peso al conteo de fallas.

    Un activo **sin un solo folio** no ha sido observado: devuelve 0 y la probabilidad se estima del tipo de
    equipo, aunque su ficha declare que se instaló hace años. Con folios, la observación se cuenta desde lo más
    antiguo que ACMA sabe de él: su fecha de instalación declarada o su primer folio. Medirla solo desde el primer
    folio dejaba a un activo de 2024 con una sola falla reciente como si fuera nuevo, y su probabilidad salía
    prestada del tipo de equipo en lugar de su propio historial."""
    primero = (await db.execute(select(func.min(Folio.capturado_at)).where(Folio.equipo_id == equipo.id))).scalar()
    if primero is None:
        return 0
    inicio = min(equipo.fecha_instalacion, primero.date()) if equipo.fecha_instalacion else primero.date()
    hoy = date.today()
    return max(0, (hoy.year - inicio.year) * 12 + (hoy.month - inicio.month))


async def _probabilidad_del_tipo(db: AsyncSession, equipo: Equipo, cfg: CriticidadConfiguracion,
                                 toda_la_plataforma: bool) -> Decimal | None:
    """Promedio de la probabilidad ya evaluada de los equipos del mismo tipo. Con `toda_la_plataforma` cruza
    clientes, así que se lee con contexto de sistema y **solo** se devuelve el número: nunca de quién salió."""
    consulta = (select(func.avg(ActivoCriticidad.probabilidad))
                .join(Equipo, Equipo.id == ActivoCriticidad.equipo_id)
                .where(Equipo.tipo_equipo_id == equipo.tipo_equipo_id, Equipo.id != equipo.id,
                       ActivoCriticidad.probabilidad_estimada.is_(False)))
    if not toda_la_plataforma:
        consulta = consulta.where(Equipo.tenant_id == equipo.tenant_id)
        promedio = (await db.execute(consulta)).scalar()
    else:
        previo = db.info.get("rls")
        await fijar_contexto(db, CONTEXTO_SISTEMA)
        try:
            promedio = (await db.execute(consulta)).scalar()
        finally:
            if previo is not None:
                await fijar_contexto(db, previo)
    return Decimal(str(promedio)).quantize(CENTAVO) if promedio is not None else None


async def probabilidad_de(db: AsyncSession, equipo: Equipo, cfg: CriticidadConfiguracion) -> dict[str, Any]:
    """{valor, estimada, origen, detalle}: la probabilidad 1–5 del equipo y de dónde salió."""
    escala = cfg.escala_probabilidad_json or {}
    meses = int(escala.get("meses", 12))
    desde = datetime.now(UTC) - timedelta(days=30 * meses)
    fallas = await _correctivos_cerrados(db, equipo.id, desde)
    historia = await _meses_de_historia(db, equipo)
    minimo = int(escala.get("minimo_meses_historia", 6))

    if historia < minimo:
        # Sin historia propia: primero el tipo de equipo en el cliente, después el mismo tipo en la plataforma.
        del_tipo = await _probabilidad_del_tipo(db, equipo, cfg, toda_la_plataforma=False)
        origen = "tipo_equipo_cliente"
        if del_tipo is None:
            del_tipo = await _probabilidad_del_tipo(db, equipo, cfg, toda_la_plataforma=True)
            origen = "tipo_equipo_plataforma"
        if del_tipo is None:
            del_tipo, origen = Decimal("2.00"), "sin_referencia"
        return {"valor": del_tipo, "estimada": True, "origen": origen,
                "detalle": {"meses_historia": historia, "minimo_meses": minimo, "fallas_12m": fallas,
                            "nota": "El equipo no tiene historia suficiente en ACMA: se usó la referencia del tipo "
                                    "de equipo y la evaluación queda marcada como estimada."}}

    por_mtbf = escala.get("por_mtbf") or []
    if por_mtbf and fallas >= int(escala.get("minimo_fallas_para_mtbf", 3)):
        mtbf = await _mtbf_horas(db, equipo.id, desde)
        if mtbf is not None:
            # Menos horas entre fallas = más probabilidad, así que los rangos se leen al revés.
            nivel = 5
            for r in sorted(por_mtbf, key=lambda x: Decimal(str(x.get("desde_horas", 0)))):
                if mtbf >= Decimal(str(r.get("desde_horas", 0))):
                    nivel = int(r["nivel"])
            return {"valor": Decimal(nivel), "estimada": False, "origen": "mtbf_equipo",
                    "detalle": {"mtbf_horas": str(mtbf), "fallas_12m": fallas, "meses": meses}}

    rangos = escala.get("por_fallas") or []
    nivel = _nivel_por_rango(Decimal(fallas), rangos) if rangos else min(5, 1 + fallas)
    texto = next((r.get("texto", "") for r in rangos if int(r["nivel"]) == nivel), "")
    return {"valor": Decimal(nivel), "estimada": False, "origen": "historial_equipo",
            "detalle": {"fallas_12m": fallas, "meses": meses, "texto": texto, "meses_historia": historia}}


# ------------------------------------------------------------------ impacto económico propuesto

async def economico_propuesto(db: AsyncSession, equipo: Equipo, cfg: CriticidadConfiguracion) -> dict[str, Any]:
    """§6.9.3 pide evaluar el costo de la falla. El operacional, el de seguridad y el de imagen los juzga una
    persona; el económico ACMA lo **propone** con lo que ya sabe: el costo promedio de los correctivos del equipo
    más el costo de su inactividad (P09). Quien evalúa puede ajustarlo."""
    from services import activos_service

    costos = list((await db.execute(
        select(FolioCosto.costo_total).join(Folio, Folio.id == FolioCosto.folio_id)
        .where(Folio.equipo_id == equipo.id, Folio.tipo_folio == TipoFolio.correctivo,
               Folio.estado == EstadoFolio.cerrado))).scalars())
    promedio = (sum((Decimal(c) for c in costos), CERO) / Decimal(len(costos))).quantize(CENTAVO) if costos else CERO
    horas = list((await db.execute(select(Folio.fecha_falla, Folio.fecha_cierre).where(
        Folio.equipo_id == equipo.id, Folio.tipo_folio == TipoFolio.correctivo,
        Folio.estado == EstadoFolio.cerrado))).all())
    inactividad = CERO
    if horas:
        tarifa = await activos_service.costo_hora_inactividad(db, equipo)
        duraciones = [Decimal(str((c - f).total_seconds() / 3600)) for f, c in horas if f and c]
        if duraciones:
            inactividad = ((sum(duraciones, CERO) / Decimal(len(duraciones))) * tarifa).quantize(CENTAVO)
    estimado = (promedio + inactividad).quantize(CENTAVO)
    nivel = _nivel_por_rango(estimado, cfg.rangos_economico_json or [])
    return {"nivel": nivel, "costo_estimado": str(estimado), "costo_promedio_correctivo": str(promedio),
            "costo_inactividad_promedio": str(inactividad), "correctivos": len(costos),
            "nota": "Propuesta a partir del historial del equipo; se puede ajustar." if costos
                    else "El equipo no tiene correctivos cerrados con costo: la propuesta es el nivel más bajo."}


# ------------------------------------------------------------------ evaluación

async def _sincronizar_equipo(db: AsyncSession, equipo: Equipo, nivel: str) -> None:
    """`equipos.criticidad` (P04) es el campo que leen la aprobación multinivel y el resto del sistema. Lo escribe
    el tenant por la RLS de P02, y aquí puede estar evaluando el sistema (tarea semanal), así que el cambio va con
    contexto de sistema dentro de la misma transacción, como el alta de equipos de P08."""
    if equipo.criticidad == nivel:
        return
    previo = db.info.get("rls")
    await fijar_contexto(db, CONTEXTO_SISTEMA)
    try:
        equipo.criticidad = nivel
        await db.flush()
    finally:
        if previo is not None:
            await fijar_contexto(db, previo)


async def vigente(db: AsyncSession, equipo_id: UUID) -> ActivoCriticidad | None:
    return (await db.execute(select(ActivoCriticidad).where(ActivoCriticidad.equipo_id == equipo_id))).scalar_one_or_none()


async def _registrar_evaluacion(db: AsyncSession, equipo: Equipo, fila: ActivoCriticidad, *,
                                indice_anterior: Decimal | None, nivel_anterior: str | None,
                                motivo: MotivoEvaluacion, razon: str, actor_id: UUID | None) -> CriticidadEvaluacion:
    ev = CriticidadEvaluacion(
        equipo_id=equipo.id, tenant_id=equipo.tenant_id, indice_anterior=indice_anterior,
        indice_nuevo=fila.indice_criticidad, nivel_anterior=nivel_anterior, nivel_nuevo=fila.nivel,
        dimensiones_json=fila.dimensiones_json, probabilidad=fila.probabilidad,
        impacto_ponderado=fila.impacto_ponderado, motivo=motivo, razon=razon, evaluado_por=actor_id)
    db.add(ev)
    await db.flush()
    return ev


async def _avisar_cambio_de_nivel(db: AsyncSession, equipo: Equipo, anterior: str | None, nuevo: str) -> None:
    """§6.9.3: el nivel cambia las implicaciones de mantenimiento y el nivel de aprobación, así que el prestador
    tiene que enterarse sin ir a buscarlo."""
    from services import catalogos_service

    prestadores = await catalogos_service.prestadores_del_tenant(db, equipo.tenant_id)
    notificaciones.enviar(
        roles=["admin_prestador", "despachador"], tenant_id=equipo.tenant_id,
        prestador_id=prestadores[0] if prestadores else None,
        titulo=f"Criticidad del equipo {equipo.codigo}: {anterior or 'sin evaluar'} → {nuevo}",
        cuerpo=f"{equipo.nombre} quedó en criticidad {nuevo}. Cambian sus implicaciones de mantenimiento y el nivel "
               f"de aprobación de sus folios.",
        datos={"equipo_id": str(equipo.id), "nivel_anterior": anterior, "nivel_nuevo": nuevo,
               "url": f"/activos/{equipo.id}?vista=criticidad"},
        canales=["app", "push", "email"])


async def evaluar(db: AsyncSession, actor: Actor, equipo: Equipo, dimensiones: dict[str, Any], *,
                  motivo: MotivoEvaluacion = MotivoEvaluacion.evaluacion_inicial, razon: str = "",
                  request: Request | None = None, exigir_rol: bool = True) -> ActivoCriticidad:
    """Evalúa (o reevalúa) un equipo con las cuatro dimensiones y la probabilidad del historial."""
    if exigir_rol:
        _exigir(actor, EVALUAN, "evalúa la criticidad de los activos")
    cfg = await configuracion(db, equipo.tenant_id)
    pesos = _validar_pesos(cfg.pesos_json or {})
    impacto = impacto_ponderado(dimensiones, pesos)
    prob = await probabilidad_de(db, equipo, cfg)
    indice = indice_de(prob["valor"], impacto)
    nivel = nivel_de(indice, cfg.rangos_nivel_json)

    fila = await vigente(db, equipo.id)
    indice_anterior = Decimal(fila.indice_criticidad) if fila else None
    nivel_anterior = fila.nivel if fila else None
    if fila is None:
        fila = ActivoCriticidad(equipo_id=equipo.id, tenant_id=equipo.tenant_id, nivel=nivel)
        db.add(fila)
    fila.indice_criticidad, fila.nivel = indice, nivel
    fila.probabilidad, fila.probabilidad_estimada, fila.probabilidad_origen = prob["valor"], prob["estimada"], prob["origen"]
    fila.impacto_ponderado = impacto
    fila.dimensiones_json = {**{d: int(dimensiones.get(d, 1)) for d in DIMENSIONES},
                             "pesos": pesos, "probabilidad": prob["detalle"]}
    fila.origen, fila.razon_manual = OrigenCriticidad.calculado, ""
    fila.evaluado_por, fila.fecha_evaluacion = actor.id, date.today()
    fila.proxima_revision = date.today() + timedelta(days=30 * int(cfg.meses_revision))
    await db.flush()

    await _registrar_evaluacion(db, equipo, fila, indice_anterior=indice_anterior, nivel_anterior=nivel_anterior,
                                motivo=motivo, razon=razon, actor_id=actor.id)
    await _sincronizar_equipo(db, equipo, nivel)
    if nivel_anterior != nivel:
        await _avisar_cambio_de_nivel(db, equipo, nivel_anterior, nivel)
    await auditoria.registrar_actor(db, actor, "criticidad.evaluacion", request, tenant_id=equipo.tenant_id,
                                    recurso_tipo="activo_criticidad", recurso_id=fila.id,
                                    antes={"indice": str(indice_anterior) if indice_anterior is not None else None,
                                           "nivel": nivel_anterior},
                                    despues={"indice": str(indice), "nivel": nivel, "dimensiones": dimensiones,
                                             "probabilidad": str(prob["valor"]), "motivo": motivo.value})
    return fila


async def evaluar_masivo(db: AsyncSession, actor: Actor, tenant_id: UUID, tipo_equipo_id: UUID,
                         dimensiones: dict[str, Any], *, solo_sin_evaluar: bool = True,
                         request: Request | None = None) -> dict[str, Any]:
    """§6.9.3 en la práctica: 200 equipos no se evalúan de uno en uno. Se asignan las mismas dimensiones a todos los
    equipos de un tipo y después se ajustan los particulares."""
    _exigir(actor, EVALUAN, "evalúa la criticidad de los activos")
    if not actor.es_superadmin and tenant_id != actor.tenant_id:
        raise no_encontrado("Cliente")
    tipo = await db.get(TipoEquipo, tipo_equipo_id)
    if tipo is None:
        raise no_encontrado("Tipo de equipo")
    equipos = list((await db.execute(select(Equipo).where(Equipo.tenant_id == tenant_id,
                                                          Equipo.tipo_equipo_id == tipo_equipo_id))).scalars())
    from services.preventivos_service import _unidades_visibles

    unidades = await _unidades_visibles(db, actor)
    if unidades is not None:
        equipos = [e for e in equipos if e.un_id in set(unidades)]
    evaluados, omitidos, por_nivel = 0, 0, {n: 0 for n in NIVELES}
    for equipo in equipos:
        if solo_sin_evaluar and await vigente(db, equipo.id) is not None:
            omitidos += 1
            continue
        fila = await evaluar(db, actor, equipo, dimensiones, motivo=MotivoEvaluacion.evaluacion_inicial,
                             razon=f"Evaluación masiva del tipo {tipo.nombre}", request=request, exigir_rol=False)
        por_nivel[fila.nivel] += 1
        evaluados += 1
    await db.flush()
    return {"tipo_equipo": tipo.nombre, "equipos": len(equipos), "evaluados": evaluados, "omitidos": omitidos,
            "por_nivel": por_nivel}


async def ajustar_manual(db: AsyncSession, actor: Actor, equipo: Equipo, nivel: str, razon: str,
                         request: Request | None = None) -> ActivoCriticidad:
    """El Admin empresa puede fijar el nivel a mano con razón obligatoria. Se conserva hasta la próxima revisión:
    el recálculo semanal respeta `origen = manual`."""
    _exigir(actor, CONFIGURAN, "ajusta la criticidad a mano")
    if nivel not in NIVELES:
        raise ErrorAPI(422, "NIVEL_INVALIDO", f"El nivel va de A a D (llegó {nivel})")
    if not (razon or "").strip():
        raise ErrorAPI(422, "RAZON_REQUERIDA", "Un ajuste manual exige razón: es lo que lee la auditoría")
    cfg = await configuracion(db, equipo.tenant_id)
    fila = await vigente(db, equipo.id)
    if fila is None:
        raise ErrorAPI(409, "SIN_EVALUACION",
                       "Evalúa el activo antes de ajustar su nivel: el ajuste manual se apoya en el cálculo")
    anterior_indice, anterior_nivel = Decimal(fila.indice_criticidad), fila.nivel
    fila.nivel = nivel
    fila.origen, fila.razon_manual = OrigenCriticidad.manual, razon.strip()
    fila.evaluado_por, fila.fecha_evaluacion = actor.id, date.today()
    fila.proxima_revision = date.today() + timedelta(days=30 * int(cfg.meses_revision))
    await db.flush()
    await _registrar_evaluacion(db, equipo, fila, indice_anterior=anterior_indice, nivel_anterior=anterior_nivel,
                                motivo=MotivoEvaluacion.ajuste_manual, razon=razon.strip(), actor_id=actor.id)
    await _sincronizar_equipo(db, equipo, nivel)
    if anterior_nivel != nivel:
        await _avisar_cambio_de_nivel(db, equipo, anterior_nivel, nivel)
    await auditoria.registrar_actor(db, actor, "criticidad.ajuste_manual", request, tenant_id=equipo.tenant_id,
                                    recurso_tipo="activo_criticidad", recurso_id=fila.id,
                                    antes={"nivel": anterior_nivel, "indice": str(anterior_indice)},
                                    despues={"nivel": nivel, "razon": razon})
    return fila


async def recalcular(db: AsyncSession, equipo: Equipo, *, motivo: MotivoEvaluacion,
                     actor_id: UUID | None = None) -> dict[str, Any]:
    """Recalcula con el historial de hoy y las dimensiones ya evaluadas. **Solo escribe una evaluación si cambia el
    nivel**: si el índice se mueve de 62.1 a 63.4 no hace falta ensuciar la traza de auditoría."""
    fila = await vigente(db, equipo.id)
    if fila is None:
        return {"estado": "sin_evaluacion"}
    if fila.origen == OrigenCriticidad.manual:
        return {"estado": "manual_vigente", "nivel": fila.nivel}
    cfg = await configuracion(db, equipo.tenant_id)
    pesos = _validar_pesos(cfg.pesos_json or {})
    dimensiones = {d: int((fila.dimensiones_json or {}).get(d, 1)) for d in DIMENSIONES}
    impacto = impacto_ponderado(dimensiones, pesos)
    prob = await probabilidad_de(db, equipo, cfg)
    indice = indice_de(prob["valor"], impacto)
    nivel = nivel_de(indice, cfg.rangos_nivel_json)
    anterior_indice, anterior_nivel = Decimal(fila.indice_criticidad), fila.nivel
    fila.indice_criticidad, fila.probabilidad = indice, prob["valor"]
    fila.probabilidad_estimada, fila.probabilidad_origen = prob["estimada"], prob["origen"]
    fila.impacto_ponderado = impacto
    fila.dimensiones_json = {**dimensiones, "pesos": pesos, "probabilidad": prob["detalle"]}
    if nivel == anterior_nivel:
        await db.flush()
        return {"estado": "sin_cambio", "nivel": nivel, "indice": str(indice)}
    fila.nivel = nivel
    await db.flush()
    await _registrar_evaluacion(db, equipo, fila, indice_anterior=anterior_indice, nivel_anterior=anterior_nivel,
                                motivo=motivo, razon="Recálculo automático con el historial de fallas",
                                actor_id=actor_id)
    await _sincronizar_equipo(db, equipo, nivel)
    await _avisar_cambio_de_nivel(db, equipo, anterior_nivel, nivel)
    log.info("Criticidad de %s: %s → %s (índice %s)", equipo.codigo, anterior_nivel, nivel, indice)
    return {"estado": "cambio", "nivel_anterior": anterior_nivel, "nivel": nivel, "indice": str(indice)}


async def recalcular_todos(db: AsyncSession) -> dict[str, int]:
    """Tarea semanal: recalcula la probabilidad de todo lo evaluado con el historial nuevo."""
    resumen = {"revisados": 0, "cambios": 0, "manuales": 0, "errores": 0}
    filas = list((await db.execute(select(ActivoCriticidad))).scalars())
    for fila in filas:
        equipo = await db.get(Equipo, fila.equipo_id)
        if equipo is None:
            continue
        resumen["revisados"] += 1
        try:
            punto = await db.begin_nested()
            r = await recalcular(db, equipo, motivo=MotivoEvaluacion.recalculo_por_historial)
            await punto.commit()
        except Exception:  # noqa: BLE001 — un equipo mal configurado no detiene al resto
            await punto.rollback()
            resumen["errores"] += 1
            log.exception("No se pudo recalcular la criticidad del equipo %s", fila.equipo_id)
            continue
        if r["estado"] == "cambio":
            resumen["cambios"] += 1
        elif r["estado"] == "manual_vigente":
            resumen["manuales"] += 1
    await db.flush()
    return resumen


# ------------------------------------------------------------------ consultas

async def historial(db: AsyncSession, equipo_id: UUID, limite: int = 50) -> list[CriticidadEvaluacion]:
    return list((await db.execute(select(CriticidadEvaluacion).where(CriticidadEvaluacion.equipo_id == equipo_id)
                                   .order_by(CriticidadEvaluacion.timestamp.desc()).limit(limite))).scalars())


async def detalle(db: AsyncSession, equipo: Equipo) -> dict[str, Any]:
    """Lo que pinta la pestaña «Criticidad y riesgo» de la ficha: el nivel, el índice y su desglose."""
    from models.criticidad import ETIQUETA_NIVEL, IMPLICACIONES_POR_NIVEL

    cfg = await configuracion(db, equipo.tenant_id)
    fila = await vigente(db, equipo.id)
    if fila is None:
        # Misma forma que la rama evaluada, para que la pantalla no tenga que leer dos estructuras distintas:
        # `probabilidad` siempre es el numero (o None sin evaluar) y el detalle siempre va aparte.
        prob = await probabilidad_de(db, equipo, cfg)
        return {"evaluado": False, "nivel_manual": equipo.criticidad, "guia": GUIA_DIMENSIONES,
                "pesos": cfg.pesos_json, "economico_propuesto": await economico_propuesto(db, equipo, cfg),
                "probabilidad": None, "probabilidad_estimada": prob["estimada"],
                "probabilidad_origen": prob["origen"], "probabilidad_detalle": prob["detalle"],
                "probabilidad_si_se_evalua": prob["valor"],
                "meses_revision": cfg.meses_revision}
    dims = fila.dimensiones_json or {}
    pesos = dims.get("pesos") or cfg.pesos_json or {}
    return {
        "evaluado": True, "nivel": fila.nivel, "etiqueta": ETIQUETA_NIVEL.get(fila.nivel, ""),
        "implicaciones": IMPLICACIONES_POR_NIVEL.get(fila.nivel, ""),
        "indice_criticidad": fila.indice_criticidad, "probabilidad": fila.probabilidad,
        "probabilidad_estimada": fila.probabilidad_estimada, "probabilidad_origen": fila.probabilidad_origen,
        "probabilidad_detalle": dims.get("probabilidad") or {},
        "impacto_ponderado": fila.impacto_ponderado,
        "dimensiones": [{"clave": d, "valor": int(dims.get(d, 1)), "peso": int(pesos.get(d, 0)),
                         "aporte": str((Decimal(str(dims.get(d, 1))) * Decimal(str(pesos.get(d, 0))) / Decimal("100")).quantize(CENTAVO)),
                         "pregunta": GUIA_DIMENSIONES[d]["pregunta"],
                         "texto": GUIA_DIMENSIONES[d]["niveles"].get(int(dims.get(d, 1)), "")} for d in DIMENSIONES],
        "origen": fila.origen.value if hasattr(fila.origen, "value") else str(fila.origen),
        "razon_manual": fila.razon_manual, "fecha_evaluacion": fila.fecha_evaluacion,
        "proxima_revision": fila.proxima_revision, "evaluado_por": fila.evaluado_por,
        "revision_vencida": bool(fila.proxima_revision and fila.proxima_revision < date.today()),
        "guia": GUIA_DIMENSIONES, "pesos": pesos, "meses_revision": cfg.meses_revision,
    }


async def _tenants_visibles(db: AsyncSession, actor: Actor) -> list[UUID] | None:
    """None = todos (superadmin). Para el prestador, los clientes que atiende."""
    if actor.es_superadmin:
        return None
    if actor.dominio == Dominio.tenant:
        return [actor.tenant_id] if actor.tenant_id else []
    from models.organizaciones import TenantPrestador

    return list((await db.execute(select(TenantPrestador.tenant_id).where(
        TenantPrestador.prestador_id == actor.prestador_id))).scalars())


async def resumen(db: AsyncSession, actor: Actor, tenant_id: UUID | None = None) -> dict[str, Any]:
    """Distribución por nivel, activos A sin plan y acciones de mitigación vencidas: lo del tablero del cliente."""
    _exigir(actor, CONSULTAN, "consulta la criticidad de los activos")
    from models.criticidad import ActivoRiesgoMitigacion, EstadoMitigacion
    from models.preventivos import EquipoPlan, EstadoPlan, PlanMantenimiento

    tenants = await _tenants_visibles(db, actor)
    consulta = select(ActivoCriticidad.nivel, func.count(ActivoCriticidad.id)).group_by(ActivoCriticidad.nivel)
    if tenant_id:
        consulta = consulta.where(ActivoCriticidad.tenant_id == tenant_id)
    elif tenants is not None:
        consulta = consulta.where(ActivoCriticidad.tenant_id.in_(tenants or [UUID(int=0)]))
    por_nivel = {n: 0 for n in NIVELES}
    for nivel, total in (await db.execute(consulta)).all():
        por_nivel[str(nivel)] = int(total)

    criticos = select(ActivoCriticidad.equipo_id).where(ActivoCriticidad.nivel == "A")
    if tenant_id:
        criticos = criticos.where(ActivoCriticidad.tenant_id == tenant_id)
    elif tenants is not None:
        criticos = criticos.where(ActivoCriticidad.tenant_id.in_(tenants or [UUID(int=0)]))
    ids = list((await db.execute(criticos)).scalars())
    con_plan = set((await db.execute(select(EquipoPlan.equipo_id).join(
        PlanMantenimiento, PlanMantenimiento.id == EquipoPlan.plan_id).where(
        EquipoPlan.equipo_id.in_(ids or [UUID(int=0)]), EquipoPlan.activo.is_(True),
        PlanMantenimiento.estado == EstadoPlan.activo))).scalars())
    sin_plan = [i for i in ids if i not in con_plan]

    vencidas = select(func.count(ActivoRiesgoMitigacion.id)).where(
        ActivoRiesgoMitigacion.estado.in_((EstadoMitigacion.propuesta, EstadoMitigacion.en_proceso)),
        ActivoRiesgoMitigacion.fecha_compromiso < date.today())
    if tenant_id:
        vencidas = vencidas.where(ActivoRiesgoMitigacion.tenant_id == tenant_id)
    elif tenants is not None:
        vencidas = vencidas.where(ActivoRiesgoMitigacion.tenant_id.in_(tenants or [UUID(int=0)]))

    revisiones = select(func.count(ActivoCriticidad.id)).where(ActivoCriticidad.proxima_revision < date.today())
    if tenant_id:
        revisiones = revisiones.where(ActivoCriticidad.tenant_id == tenant_id)
    elif tenants is not None:
        revisiones = revisiones.where(ActivoCriticidad.tenant_id.in_(tenants or [UUID(int=0)]))

    return {"por_nivel": por_nivel, "total": sum(por_nivel.values()),
            "criticos_sin_plan": len(sin_plan), "criticos_sin_plan_ids": [str(i) for i in sin_plan],
            "mitigaciones_vencidas": int((await db.execute(vencidas)).scalar() or 0),
            "revisiones_vencidas": int((await db.execute(revisiones)).scalar() or 0)}


async def listado(db: AsyncSession, actor: Actor, *, tenant_id: UUID | None = None, nivel: str | None = None,
                  solo_revision_vencida: bool = False) -> list[dict[str, Any]]:
    """Registro de activos con su criticidad: la base del reporte de certificación y de la pantalla del módulo."""
    _exigir(actor, CONSULTAN, "consulta la criticidad de los activos")
    from models.unidades import UnidadNegocio

    tenants = await _tenants_visibles(db, actor)
    consulta = (select(ActivoCriticidad, Equipo, UnidadNegocio, TipoEquipo)
                .join(Equipo, Equipo.id == ActivoCriticidad.equipo_id)
                .join(UnidadNegocio, UnidadNegocio.id == Equipo.un_id)
                .join(TipoEquipo, TipoEquipo.id == Equipo.tipo_equipo_id)
                .order_by(ActivoCriticidad.indice_criticidad.desc()))
    if tenant_id:
        consulta = consulta.where(ActivoCriticidad.tenant_id == tenant_id)
    elif tenants is not None:
        consulta = consulta.where(ActivoCriticidad.tenant_id.in_(tenants or [UUID(int=0)]))
    if nivel:
        consulta = consulta.where(ActivoCriticidad.nivel == nivel)
    if solo_revision_vencida:
        consulta = consulta.where(ActivoCriticidad.proxima_revision < date.today())
    from services.preventivos_service import _unidades_visibles

    unidades = await _unidades_visibles(db, actor)
    if unidades is not None:
        consulta = consulta.where(Equipo.un_id.in_(unidades or [UUID(int=0)]))
    salida = []
    for fila, equipo, un, tipo in (await db.execute(consulta)).all():
        salida.append({
            "equipo_id": equipo.id, "codigo": equipo.codigo, "nombre": equipo.nombre, "tipo_equipo": tipo.nombre,
            "un_codigo": un.codigo, "un_nombre": un.nombre, "tenant_id": equipo.tenant_id,
            "nivel": fila.nivel, "indice_criticidad": fila.indice_criticidad, "probabilidad": fila.probabilidad,
            "probabilidad_estimada": fila.probabilidad_estimada, "impacto_ponderado": fila.impacto_ponderado,
            "origen": fila.origen.value if hasattr(fila.origen, "value") else str(fila.origen),
            "fecha_evaluacion": fila.fecha_evaluacion, "proxima_revision": fila.proxima_revision,
            "revision_vencida": bool(fila.proxima_revision and fila.proxima_revision < date.today()),
        })
    return salida


async def matriz_riesgo(db: AsyncSession, actor: Actor, tenant_id: UUID | None = None) -> dict[str, Any]:
    """Matriz 5×5 probabilidad × impacto con los activos ubicados y el conteo por celda (§6.9.3, reporte ISO)."""
    filas = await listado(db, actor, tenant_id=tenant_id)
    celdas: dict[str, dict[str, Any]] = {}
    for f in filas:
        p = int(Decimal(str(f["probabilidad"])).to_integral_value(rounding=ROUND_HALF_UP))
        i = int(Decimal(str(f["impacto_ponderado"])).to_integral_value(rounding=ROUND_HALF_UP))
        clave = f"{p}x{i}"
        celda = celdas.setdefault(clave, {"probabilidad": p, "impacto": i, "total": 0, "equipos": []})
        celda["total"] += 1
        celda["equipos"].append({"equipo_id": str(f["equipo_id"]), "codigo": f["codigo"], "nivel": f["nivel"]})
    return {"celdas": list(celdas.values()), "total": len(filas)}
