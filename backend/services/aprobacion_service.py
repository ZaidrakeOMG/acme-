"""Flujo de aprobación multinivel (§6.8.7). Sub-proceso interno de `en_revision`: el folio conserva sus 11 estados.

- Nivel de entrada: reglas del tenant por monto, criticidad del activo y tipo de trabajo; la más restrictiva gana.
- Sin reglas (o ninguna aplica): el folio no entra a flujo y pasa a `autorizado` (decisión pendiente de validación).
- Críticos A/B con `autorizacion_automatica_criticos`: directo a `autorizado` con decisión `auto_aprobado` (canal sistema).
- Decisiones append-only; timeouts evaluados por Celery cada minuto con las cuatro opciones de §6.8.7.
"""
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import Request
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.dependencias import Actor
from core.errors import ErrorAPI, prohibido
from models.base import Rol
from models.catalogos import Equipo
from models.folios import (
    CRITICOS, MODULO_POR_RAZON, AprobacionAlertaTimeout, AprobacionDecision, AprobacionFlujo, AprobacionNivelConfig,
    AprobacionRegla, CanalAprobacion, ComportamientoTimeout, Criticidad, CriterioAprobacion, DecisionAprobacion, EstadoFlujo,
    EstadoFolio, Folio, FolioPoliticasTenant, RazonRechazo, TipoFolio,
)
from models.unidades import GrupoUNMiembro, UnidadNegocio, UsuarioGrupo, UsuarioUN
from services import alertas_service, auditoria, folio_estados, folios_sla, notificaciones  # noqa: F401 (folios_sla suscribe SLA)
from services.folio_estados import ACTOR_SISTEMA, ActorFolio

ESTADOS_FLUJO_ABIERTO = (EstadoFlujo.activo, EstadoFlujo.bloqueado)


# ------------------------------------------------------------ configuración

async def politicas_de(db: AsyncSession, tenant_id: UUID) -> FolioPoliticasTenant:
    p = (await db.execute(select(FolioPoliticasTenant).where(FolioPoliticasTenant.tenant_id == tenant_id))).scalar_one_or_none()
    if p is None:
        p = FolioPoliticasTenant(tenant_id=tenant_id)
        db.add(p)
        await db.flush()
    return p


async def reglas_de(db: AsyncSession, tenant_id: UUID, solo_activas: bool = True) -> list[AprobacionRegla]:
    consulta = select(AprobacionRegla).where(AprobacionRegla.tenant_id == tenant_id).order_by(AprobacionRegla.nivel, AprobacionRegla.criterio)
    if solo_activas:
        consulta = consulta.where(AprobacionRegla.activa.is_(True))
    return list((await db.execute(consulta)).scalars())


async def niveles_de(db: AsyncSession, tenant_id: UUID) -> dict[int, AprobacionNivelConfig]:
    filas = (await db.execute(select(AprobacionNivelConfig).where(AprobacionNivelConfig.tenant_id == tenant_id))).scalars()
    return {n.nivel: n for n in filas}


async def reemplazar_reglas(db: AsyncSession, tenant_id: UUID, nuevas: list[dict[str, Any]]) -> list[AprobacionRegla]:
    for r in await reglas_de(db, tenant_id, solo_activas=False):
        await db.delete(r)
    await db.flush()
    creadas = [AprobacionRegla(tenant_id=tenant_id, **n) for n in nuevas]
    db.add_all(creadas)
    await db.flush()
    return creadas


async def reemplazar_niveles(db: AsyncSession, tenant_id: UUID, nuevos: list[dict[str, Any]]) -> list[AprobacionNivelConfig]:
    niveles = {n["nivel"] for n in nuevos}
    if len(niveles) != len(nuevos):
        raise ErrorAPI(422, "NIVEL_DUPLICADO", "Cada nivel se configura una sola vez")
    for n in nuevos:
        # Validación de §6.8.7 también en servicio (además del CHECK de la tabla).
        if n["nivel"] == 3 and n["comportamiento_timeout"] not in (ComportamientoTimeout.bloquear_alertar, ComportamientoTimeout.depende_criticidad):
            raise ErrorAPI(422, "TIMEOUT_NIVEL_3", "El Nivel 3 solo admite bloquear_alertar o depende_criticidad")
    actuales = await niveles_de(db, tenant_id)
    for nivel, fila in actuales.items():
        if nivel not in niveles:
            await db.delete(fila)
    resultado = []
    for n in nuevos:
        fila = actuales.get(n["nivel"])
        if fila is None:
            fila = AprobacionNivelConfig(tenant_id=tenant_id, **n)
            db.add(fila)
        else:
            for k, v in n.items():
                setattr(fila, k, v)
        resultado.append(fila)
    await db.flush()
    return sorted(resultado, key=lambda f: f.nivel)


# ------------------------------------------------------- nivel de entrada

def _monto_aplica(regla: AprobacionRegla, monto: Decimal) -> bool:
    v = regla.valor_json or {}
    try:
        if regla.operador == "entre":
            return Decimal(str(v["min"])) <= monto < Decimal(str(v["max"]))
        m = Decimal(str(v["monto"]))
    except (KeyError, ArithmeticError, ValueError):
        return False
    return {"<": monto < m, "<=": monto <= m, ">": monto > m, ">=": monto >= m}.get(regla.operador, False)


def regla_aplica(regla: AprobacionRegla, *, monto: Decimal | None, criticidad: str | None, tipo_folio: TipoFolio) -> bool:
    if regla.criterio == CriterioAprobacion.monto:
        return _monto_aplica(regla, monto if monto is not None else Decimal("0"))
    v = regla.valor_json or {}
    if regla.criterio == CriterioAprobacion.criticidad:
        return criticidad is not None and criticidad in (v.get("valores") or [])
    if regla.operador == "igual":
        return tipo_folio.value == v.get("tipo")
    return tipo_folio.value in (v.get("valores") or [])


def nivel_entrada(reglas: list[AprobacionRegla], *, monto: Decimal | None, criticidad: str | None, tipo_folio: TipoFolio) -> int | None:
    """La regla más restrictiva (nivel más alto) gana. None si no hay reglas o ninguna aplica."""
    aplicables = [r.nivel for r in reglas if regla_aplica(r, monto=monto, criticidad=criticidad, tipo_folio=tipo_folio)]
    return max(aplicables) if aplicables else None


# ------------------------------------------------------------------ flujo

async def flujo_abierto(db: AsyncSession, folio_id: UUID) -> AprobacionFlujo | None:
    return (await db.execute(select(AprobacionFlujo).where(
        AprobacionFlujo.folio_id == folio_id, AprobacionFlujo.estado.in_(ESTADOS_FLUJO_ABIERTO)))).scalars().first()


async def ultimo_flujo(db: AsyncSession, folio_id: UUID) -> AprobacionFlujo | None:
    return (await db.execute(select(AprobacionFlujo).where(AprobacionFlujo.folio_id == folio_id)
                             .order_by(AprobacionFlujo.iniciado_at.desc()))).scalars().first()


async def _decidir(db: AsyncSession, flujo: AprobacionFlujo, nivel: int, decision: DecisionAprobacion, canal: CanalAprobacion,
                   actor_id: UUID | None = None, razon: RazonRechazo | None = None, notas: str = "") -> AprobacionDecision:
    d = AprobacionDecision(flujo_id=flujo.id, folio_id=flujo.folio_id, tenant_id=flujo.tenant_id, prestador_id=flujo.prestador_id,
                           nivel=nivel, actor_id=actor_id, decision=decision, razon_rechazo=razon,
                           modulo_destino=MODULO_POR_RAZON[razon] if razon else None, canal=canal, notas=notas,
                           timestamp=datetime.now(UTC))
    db.add(d)
    await db.flush()
    return d


async def _programar_timeout(db: AsyncSession, flujo: AprobacionFlujo, config: AprobacionNivelConfig | None,
                             ahora: datetime) -> AprobacionAlertaTimeout | None:
    if config is None:
        return None
    # El plazo corre desde el momento real en que se programa (no desde `ahora`, que puede ser una fecha de captura simulada).
    t = AprobacionAlertaTimeout(flujo_id=flujo.id, folio_id=flujo.folio_id, tenant_id=flujo.tenant_id, prestador_id=flujo.prestador_id,
                                nivel=flujo.nivel_actual, vence_at=datetime.now(UTC) + timedelta(hours=config.tiempo_limite_horas))
    db.add(t)
    await db.flush()
    return t


async def _cerrar_timeouts(db: AsyncSession, flujo: AprobacionFlujo, accion: str, ahora: datetime) -> None:
    pendientes = (await db.execute(select(AprobacionAlertaTimeout).where(
        AprobacionAlertaTimeout.flujo_id == flujo.id, AprobacionAlertaTimeout.procesado.is_(False)))).scalars()
    for t in pendientes:
        t.procesado, t.accion_ejecutada, t.procesado_at = True, accion, ahora


async def _notificar_nivel(db: AsyncSession, folio: Folio, flujo: AprobacionFlujo, config: AprobacionNivelConfig | None) -> None:
    """P07: `notificar()` resuelve canal por preferencia del usuario; los Admin UN solo los de la UN del folio."""
    from services import notificaciones_service

    rol = config.rol_aprobador.value if config else None
    destinatarios = await notificaciones_service.destinatarios_por_rol(db, [rol], tenant_id=folio.tenant_id, un_id=folio.un_id) if rol else []
    await notificaciones_service.notificar(db, "aprobacion.pendiente", destinatarios, {"folio_id": str(folio.id), "flujo_id": str(flujo.id), "nivel": flujo.nivel_actual},
                                           asunto=f"Folio {folio.numero_folio} pendiente de tu autorización", cuerpo=f"Nivel {flujo.nivel_actual}: aprobar o rechazar. {folio.descripcion[:160]}",
                                           url=f"/folios/{folio.id}", tenant_id=folio.tenant_id, prestador_id=folio.prestador_id,
                                           canales=[c for c in (config.notificar_por_json if config else ["app", "push", "email"]) if c in ("app", "push", "email", "whatsapp", "sms")] or None)


async def iniciar_flujo(db: AsyncSession, folio: Folio, nivel_requerido: int, politicas: FolioPoliticasTenant,
                        ahora: datetime | None = None) -> AprobacionFlujo:
    ahora = ahora or datetime.now(UTC)
    niveles = await niveles_de(db, folio.tenant_id)
    inicial = 1 if politicas.aprobacion_secuencial else nivel_requerido
    flujo = AprobacionFlujo(folio_id=folio.id, tenant_id=folio.tenant_id, prestador_id=folio.prestador_id, nivel_actual=inicial,
                            nivel_maximo_requerido=nivel_requerido, iniciado_at=ahora)
    db.add(flujo)
    await db.flush()
    await _programar_timeout(db, flujo, niveles.get(inicial), ahora)
    await folio_estados.comentar(db, folio, ACTOR_SISTEMA, f"Inicia flujo de aprobación en Nivel {inicial} (máximo requerido: Nivel {nivel_requerido})",
                                 {"flujo_id": str(flujo.id), "nivel": inicial, "nivel_maximo": nivel_requerido}, evento="aprobacion.inicio")
    await _notificar_nivel(db, folio, flujo, niveles.get(inicial))
    return flujo


async def evaluar_al_capturar(db: AsyncSession, folio: Folio, equipo: Equipo, request: Request | None = None,
                              ahora: datetime | None = None) -> str:
    """Punto de decisión D_MULTI tras las validaciones automáticas. Devuelve 'autorizado' o 'en_revision'."""
    politicas = await politicas_de(db, folio.tenant_id)
    reglas = await reglas_de(db, folio.tenant_id)
    criticidad = equipo.criticidad
    nivel = nivel_entrada(reglas, monto=folio.monto_estimado, criticidad=criticidad, tipo_folio=folio.tipo_folio)
    if nivel is None:
        await folio_estados.transicionar(db, folio, EstadoFolio.autorizado, ACTOR_SISTEMA,
                                         "Validaciones automáticas superadas; sin reglas de aprobación aplicables", {"flujo": None}, request)
        return "autorizado"
    if politicas.autorizacion_automatica_criticos and criticidad in {c.value for c in CRITICOS}:
        ahora = ahora or datetime.now(UTC)
        flujo = AprobacionFlujo(folio_id=folio.id, tenant_id=folio.tenant_id, prestador_id=folio.prestador_id, nivel_actual=nivel,
                                nivel_maximo_requerido=nivel, estado=EstadoFlujo.aprobado, iniciado_at=ahora, resuelto_at=ahora)
        db.add(flujo)
        await db.flush()
        await _decidir(db, flujo, nivel, DecisionAprobacion.auto_aprobado, CanalAprobacion.sistema,
                       notas=f"Activo crítico {criticidad} con autorización automática del tenant")
        await folio_estados.transicionar(db, folio, EstadoFolio.autorizado, ACTOR_SISTEMA,
                                         f"Autorización automática: activo crítico {criticidad}", {"flujo_id": str(flujo.id)}, request)
        return "autorizado"
    if folio.estado != EstadoFolio.en_revision:
        await folio_estados.transicionar(db, folio, EstadoFolio.en_revision, ACTOR_SISTEMA,
                                         f"Validaciones superadas; entra al flujo de aprobación multinivel (Nivel {nivel})",
                                         {"nivel_entrada": nivel}, request)
    await iniciar_flujo(db, folio, nivel, politicas, ahora)
    return "en_revision"


# ------------------------------------------------------------- aprobadores

async def un_visible_para(db: AsyncSession, actor: Actor, un_id: UUID) -> bool:
    if actor.rol == Rol.admin_empresa:
        un = await db.get(UnidadNegocio, un_id)
        return un is not None and un.tenant_id == actor.tenant_id
    directas = select(UsuarioUN.unidad_id).where(UsuarioUN.usuario_id == actor.id)
    por_grupo = (select(GrupoUNMiembro.unidad_id).join(UsuarioGrupo, UsuarioGrupo.grupo_id == GrupoUNMiembro.grupo_id)
                 .where(UsuarioGrupo.usuario_id == actor.id))
    consulta = select(UnidadNegocio.id).where(UnidadNegocio.id == un_id)
    if actor.rol == Rol.supervisor_operadores:
        consulta = consulta.where(or_(UnidadNegocio.id.in_(directas), UnidadNegocio.id.in_(por_grupo)))
    else:
        consulta = consulta.where(UnidadNegocio.id.in_(directas))
    return (await db.execute(consulta)).first() is not None


async def es_aprobador(db: AsyncSession, actor: Actor, folio: Folio, flujo: AprobacionFlujo) -> bool:
    if actor.es_superadmin:
        return True
    config = (await niveles_de(db, folio.tenant_id)).get(flujo.nivel_actual)
    if config is None or actor.rol != config.rol_aprobador or actor.tenant_id != folio.tenant_id:
        return False
    return await un_visible_para(db, actor, folio.un_id)


async def pendientes_para(db: AsyncSession, actor: Actor) -> list[tuple[Folio, AprobacionFlujo, AprobacionNivelConfig | None]]:
    """Bandeja del aprobador: flujos abiertos cuyo nivel actual corresponde a su rol y cuya UN puede ver."""
    consulta = (select(Folio, AprobacionFlujo).join(AprobacionFlujo, AprobacionFlujo.folio_id == Folio.id)
                .where(AprobacionFlujo.estado.in_(ESTADOS_FLUJO_ABIERTO)).order_by(AprobacionFlujo.iniciado_at))
    if not actor.es_superadmin:
        consulta = consulta.where(Folio.tenant_id == actor.tenant_id)
    salida = []
    cache: dict[UUID, dict[int, AprobacionNivelConfig]] = {}
    for folio, flujo in (await db.execute(consulta)).all():
        if folio.tenant_id not in cache:  # el await de un setdefault se evalua siempre: seria una consulta por folio
            cache[folio.tenant_id] = await niveles_de(db, folio.tenant_id)
        niveles = cache[folio.tenant_id]
        config = niveles.get(flujo.nivel_actual)
        if actor.es_superadmin or (config and config.rol_aprobador == actor.rol and await un_visible_para(db, actor, folio.un_id)):
            salida.append((folio, flujo, config))
    return salida


async def _exigir_decision_posible(db: AsyncSession, actor: Actor, folio: Folio) -> AprobacionFlujo:
    flujo = await flujo_abierto(db, folio.id)
    if flujo is None or folio.estado != EstadoFolio.en_revision:
        raise ErrorAPI(409, "SIN_FLUJO_ACTIVO", "El folio no tiene un flujo de aprobación pendiente")
    if not await es_aprobador(db, actor, folio, flujo):
        raise prohibido(f"No eres el aprobador del Nivel {flujo.nivel_actual} de este folio")
    return flujo


async def aprobar(db: AsyncSession, actor: Actor, folio: Folio, canal: CanalAprobacion, notas: str, request: Request | None) -> AprobacionFlujo:
    flujo = await _exigir_decision_posible(db, actor, folio)
    ahora = datetime.now(UTC)
    nivel = flujo.nivel_actual
    decision = await _decidir(db, flujo, nivel, DecisionAprobacion.aprobado, canal, actor.id, notas=notas)
    await _cerrar_timeouts(db, flujo, "aprobado", ahora)
    await auditoria.registrar_actor(db, actor, "folio.aprobacion.aprobado", request, recurso_tipo="folio", recurso_id=folio.id,
                                    tenant_id=folio.tenant_id, prestador_id=folio.prestador_id,
                                    despues={"nivel": nivel, "canal": canal.value, "decision_id": str(decision.id)})
    if nivel >= flujo.nivel_maximo_requerido:
        flujo.estado, flujo.resuelto_at = EstadoFlujo.aprobado, ahora
        await folio_estados.transicionar(db, folio, EstadoFolio.autorizado, ACTOR_SISTEMA, f"Aprobado en Nivel {nivel} por {actor.nombre}",
                                         {"flujo_id": str(flujo.id), "nivel": nivel, "canal": canal.value, "aprobador_id": str(actor.id)}, request)
    else:
        flujo.nivel_actual, flujo.estado = nivel + 1, EstadoFlujo.activo
        niveles = await niveles_de(db, folio.tenant_id)
        await _programar_timeout(db, flujo, niveles.get(flujo.nivel_actual), ahora)
        await folio_estados.comentar(db, folio, actor, f"Aprobado en Nivel {nivel}; sube a Nivel {flujo.nivel_actual}",
                                     {"flujo_id": str(flujo.id), "nivel": flujo.nivel_actual, "canal": canal.value}, evento="aprobacion.aprobado")
        await _notificar_nivel(db, folio, flujo, niveles.get(flujo.nivel_actual))
    await db.flush()
    return flujo


async def rechazar(db: AsyncSession, actor: Actor, folio: Folio, canal: CanalAprobacion, razon: RazonRechazo, notas: str,
                   request: Request | None) -> AprobacionFlujo:
    flujo = await _exigir_decision_posible(db, actor, folio)
    ahora = datetime.now(UTC)
    nivel = flujo.nivel_actual
    decision = await _decidir(db, flujo, nivel, DecisionAprobacion.rechazado, canal, actor.id, razon=razon, notas=notas)
    flujo.estado, flujo.resuelto_at = EstadoFlujo.rechazado, ahora
    await _cerrar_timeouts(db, flujo, "rechazado", ahora)
    destino = MODULO_POR_RAZON[razon]
    await auditoria.registrar_actor(db, actor, "folio.aprobacion.rechazado", request, recurso_tipo="folio", recurso_id=folio.id,
                                    tenant_id=folio.tenant_id, prestador_id=folio.prestador_id,
                                    despues={"nivel": nivel, "canal": canal.value, "razon_rechazo": razon.value, "modulo_destino": destino.value})
    razon_texto = f"Rechazado en aprobación (Nivel {nivel}) por {actor.nombre}: {razon.value}" + (f" — {notas}" if notas else "")
    await folio_estados.transicionar(db, folio, EstadoFolio.cancelado, ACTOR_SISTEMA, razon_texto,
                                     {"razon_cancelacion": razon_texto, "flujo_id": str(flujo.id), "razon_rechazo": razon.value,
                                      "modulo_destino": destino.value, "decision_id": str(decision.id)}, request)
    # P07: el rechazo crea el registro en el módulo de seguimiento y completa modulo_destino_id de la decisión.
    from services.seguimiento import entradas

    await entradas.desde_derivacion(db, folio, decision)
    await db.flush()
    return flujo


# ---------------------------------------------------------------- timeouts

async def _bloquear(db: AsyncSession, folio: Folio, flujo: AprobacionFlujo, ahora: datetime, config: AprobacionNivelConfig | None) -> str:
    await _decidir(db, flujo, flujo.nivel_actual, DecisionAprobacion.bloqueado, CanalAprobacion.sistema,
                   notas="Tiempo límite vencido: bloqueado en espera de decisión humana")
    flujo.estado = EstadoFlujo.bloqueado
    await folio_estados.comentar(db, folio, ACTOR_SISTEMA, f"Aprobación bloqueada por timeout en Nivel {flujo.nivel_actual}",
                                 {"flujo_id": str(flujo.id), "nivel": flujo.nivel_actual}, evento="aprobacion.bloqueado")
    await alertas_service.disparar(db, "APROBACION_BLOQUEADA", tenant_id=folio.tenant_id, prestador_id=folio.prestador_id,
                                   entidad_tipo="folio", entidad_id=folio.id,
                                   datos={"numero_folio": folio.numero_folio, "nivel": flujo.nivel_actual,
                                          "rol_aprobador": config.rol_aprobador.value if config else None})
    from services import notificaciones_service

    roles = [config.rol_aprobador.value if config else "admin_empresa", "admin_empresa", "despachador"]
    destinatarios = await notificaciones_service.destinatarios_por_rol(db, roles, tenant_id=folio.tenant_id, prestador_id=folio.prestador_id, un_id=folio.un_id)
    await notificaciones_service.notificar(db, "aprobacion.bloqueada", destinatarios, {"folio_id": str(folio.id), "nivel": flujo.nivel_actual},
                                           asunto=f"Folio {folio.numero_folio} bloqueado en aprobación", cuerpo=f"Nivel {flujo.nivel_actual} sin respuesta",
                                           url=f"/folios/{folio.id}", tenant_id=folio.tenant_id, prestador_id=folio.prestador_id)
    return "bloquear_alertar"


async def _autorizar_automatico(db: AsyncSession, folio: Folio, flujo: AprobacionFlujo, ahora: datetime, motivo: str) -> str:
    await _decidir(db, flujo, flujo.nivel_actual, DecisionAprobacion.auto_aprobado, CanalAprobacion.sistema, notas=motivo)
    flujo.estado, flujo.resuelto_at = EstadoFlujo.aprobado, ahora
    await folio_estados.transicionar(db, folio, EstadoFolio.autorizado, ACTOR_SISTEMA, motivo,
                                     {"flujo_id": str(flujo.id), "nivel": flujo.nivel_actual, "timeout": True})
    return "autorizar_automatico"


async def _escalar(db: AsyncSession, folio: Folio, flujo: AprobacionFlujo, ahora: datetime,
                   niveles: dict[int, AprobacionNivelConfig]) -> str:
    await _decidir(db, flujo, flujo.nivel_actual, DecisionAprobacion.escalado, CanalAprobacion.sistema,
                   notas="Tiempo límite vencido: escalado al siguiente nivel")
    flujo.nivel_actual += 1
    flujo.nivel_maximo_requerido = max(flujo.nivel_maximo_requerido, flujo.nivel_actual)
    flujo.estado = EstadoFlujo.activo
    await _programar_timeout(db, flujo, niveles.get(flujo.nivel_actual), ahora)
    await folio_estados.comentar(db, folio, ACTOR_SISTEMA, f"Escalado por timeout al Nivel {flujo.nivel_actual}",
                                 {"flujo_id": str(flujo.id), "nivel": flujo.nivel_actual}, evento="aprobacion.escalado")
    await _notificar_nivel(db, folio, flujo, niveles.get(flujo.nivel_actual))
    return "escalar"


async def evaluar_timeouts(db: AsyncSession, ahora: datetime | None = None) -> dict[str, int]:
    """Worker `evaluar_timeouts_aprobacion` (cada minuto). Aplica literalmente las cuatro opciones de §6.8.7."""
    ahora = ahora or datetime.now(UTC)
    resumen = {"vencidos": 0, "escalar": 0, "bloquear_alertar": 0, "autorizar_automatico": 0, "depende_criticidad": 0, "omitidos": 0}
    vencidos = (await db.execute(select(AprobacionAlertaTimeout).where(
        AprobacionAlertaTimeout.procesado.is_(False), AprobacionAlertaTimeout.vence_at <= ahora)
        .order_by(AprobacionAlertaTimeout.vence_at))).scalars().all()
    for t in vencidos:
        resumen["vencidos"] += 1
        flujo = await db.get(AprobacionFlujo, t.flujo_id)
        folio = await db.get(Folio, t.folio_id)
        t.procesado, t.procesado_at = True, ahora
        if flujo is None or folio is None or flujo.estado != EstadoFlujo.activo or flujo.nivel_actual != t.nivel \
                or folio.estado != EstadoFolio.en_revision:
            t.accion_ejecutada = "omitido"
            resumen["omitidos"] += 1
            continue
        niveles = await niveles_de(db, folio.tenant_id)
        config = niveles.get(t.nivel)
        comportamiento = config.comportamiento_timeout if config else ComportamientoTimeout.bloquear_alertar
        await alertas_service.disparar(db, "APROBACION_PENDIENTE_VENCIDA", tenant_id=folio.tenant_id, prestador_id=folio.prestador_id,
                                       entidad_tipo="folio", entidad_id=folio.id,
                                       datos={"numero_folio": folio.numero_folio, "nivel": t.nivel, "comportamiento": comportamiento.value})
        if comportamiento == ComportamientoTimeout.escalar and t.nivel < 3:
            accion = await _escalar(db, folio, flujo, ahora, niveles)
        elif comportamiento == ComportamientoTimeout.autorizar_automatico and t.nivel < 3:
            accion = await _autorizar_automatico(db, folio, flujo, ahora, f"Autorizado automáticamente por timeout en Nivel {t.nivel}")
        elif comportamiento == ComportamientoTimeout.depende_criticidad:
            equipo = await db.get(Equipo, folio.equipo_id)
            if equipo is not None and equipo.criticidad in {c.value for c in CRITICOS}:
                await _autorizar_automatico(db, folio, flujo, ahora, f"Timeout en Nivel {t.nivel}: activo crítico {equipo.criticidad}, autorizado")
            else:
                await _bloquear(db, folio, flujo, ahora, config)
            accion = "depende_criticidad"
        else:
            accion = await _bloquear(db, folio, flujo, ahora, config)
        t.accion_ejecutada = accion
        resumen[accion] += 1
    await db.flush()
    return resumen
