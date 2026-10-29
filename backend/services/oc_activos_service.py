"""Seguimiento de OC para instalación de activos (§6.10.7): el folio clasificado como instalación de activo en el formulario
(captura del operador o atención del técnico) espera la OC del cliente con los cinco estatus literales, queda retenido en
revisión con el trigger `pendiente_oc_cliente`, pasa a Autorizado automáticamente al autorizarse la OC y da de alta el equipo
en `equipos` (P02) al cerrarse. ACMA no genera la OC en el ERP del cliente. P08."""
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.dependencias import Actor
from core.errors import ErrorAPI, no_encontrado, prohibido
from models.base import Dominio, Rol
from models.catalogos import Equipo, EstadoActivo, TipoEquipo
from models.folios import EstadoFolio, Folio, RevisionManualTrigger, TriggerRevision
from models.formularios import FormularioRespuesta
from models.trabajos_especiales import DecisionOCRechazo, EstatusOCActivo, FolioActivoAutorizacion, FolioActivoHistorial
from models.unidades import UnidadNegocio
from models.usuarios import Usuario
from services import alertas_service, auditoria, folio_estados, folios_sla, notificaciones_service
from services.folio_estados import ACTOR_SISTEMA, ActorFolio
from services.preventivos_service import _unidades_visibles

S = EstatusOCActivo
ACTUALIZAN = {Rol.superadmin, Rol.admin_empresa}
CONSULTAN = {Rol.superadmin, Rol.admin_empresa, Rol.admin_un, Rol.supervisor_operadores, Rol.admin_prestador, Rol.mesa_control, Rol.despachador, Rol.direccion_prestador, Rol.supervisor_prestador}
# §6.10.7: estatus → destinos. `listo_para_asignar` lo fija el sistema al autorizarse la OC.
TRANSICIONES: dict[S, set[S]] = {
    S.pendiente_iniciar_tramite: {S.oc_en_tramite, S.oc_autorizada, S.oc_rechazada},
    S.oc_en_tramite: {S.oc_autorizada, S.oc_rechazada},
    S.oc_autorizada: {S.listo_para_asignar},
    S.listo_para_asignar: set(),
    S.oc_rechazada: set(),
}
ORDEN_DESTINOS = [S.oc_en_tramite, S.oc_autorizada, S.oc_rechazada]
NOMBRES = {S.pendiente_iniciar_tramite: "Pendiente de iniciar trámite", S.oc_en_tramite: "OC en trámite", S.oc_autorizada: "OC autorizada",
           S.listo_para_asignar: "Folio listo para asignar", S.oc_rechazada: "OC rechazada"}
AFIRMATIVOS = {"si", "sí", "true", "1", "yes", "verdadero"}


# ---------------------------------------------------------- detección

def _afirmativo(valor: Any, esperado: Any) -> bool:
    if valor is None:
        return False
    if esperado is None or esperado == "":
        return str(valor).strip().lower() in AFIRMATIVOS or valor is True
    if isinstance(valor, bool) or isinstance(esperado, bool):
        return (str(valor).strip().lower() in AFIRMATIVOS or valor is True) == (str(esperado).strip().lower() in AFIRMATIVOS or esperado is True)
    return str(valor).strip().lower() == str(esperado).strip().lower()


def detectar(esquema, respuestas: dict[str, Any]) -> dict[str, Any] | None:
    """Devuelve los datos del equipo mapeados cuando algún campo con `clasifica_instalacion_activo` responde afirmativamente."""
    for campo in esquema.campos:
        mapeo = getattr(campo, "clasifica_instalacion_activo", None)
        if not mapeo:
            continue
        if not _afirmativo(respuestas.get(campo.clave), mapeo.valor_afirmativo):
            continue
        datos = {"campo": campo.clave}
        for clave, destino in (("campo_tipo_equipo", "tipo_equipo"), ("campo_marca", "marca"), ("campo_modelo", "modelo"), ("campo_serie", "numero_serie"),
                               ("campo_valor_reposicion", "valor_reposicion"), ("campo_nombre", "nombre")):
            origen = getattr(mapeo, clave, None)
            if origen and respuestas.get(origen) not in (None, ""):
                datos[destino] = respuestas.get(origen)
        return datos
    return None


async def marcar(db: AsyncSession, folio: Folio, actor: ActorFolio, datos_equipo: dict[str, Any], *, origen: str, respuesta_id: UUID | None, request: Request | None = None) -> FolioActivoAutorizacion:
    existente = (await db.execute(select(FolioActivoAutorizacion).where(FolioActivoAutorizacion.folio_id == folio.id))).scalar_one_or_none()
    if existente is not None:
        if datos_equipo and not existente.datos_equipo_json:
            existente.datos_equipo_json = datos_equipo
            await db.flush()
        return existente
    folio.es_instalacion_activo = True
    aut = FolioActivoAutorizacion(folio_id=folio.id, tenant_id=folio.tenant_id, prestador_id=folio.prestador_id, un_id=folio.un_id, origen=origen, respuesta_id=respuesta_id,
                                  datos_equipo_json=datos_equipo, estatus_desde=datetime.now(UTC))
    db.add(aut)
    await db.flush()
    await _historial(db, folio, None, aut.estatus_multinivel.value, actor, f"Clasificado como instalación de activo en el formulario ({origen})")
    await folio_estados.comentar(db, folio, actor, "Folio clasificado como instalación de activo: espera la OC del cliente (§6.10.7)",
                                 {"origen": origen, "respuesta_id": str(respuesta_id) if respuesta_id else None}, evento="activo.clasificado")
    await auditoria.registrar(db, "oc_activos.clasificado", actor_rol=folio_estados.rol_de(actor), actor_id=getattr(actor, "id", None), tenant_id=folio.tenant_id,
                              prestador_id=folio.prestador_id, recurso_tipo="folio", recurso_id=folio.id, despues={"origen": origen, "datos_equipo": datos_equipo}, request=request)
    destinatarios = await notificaciones_service.destinatarios_por_rol(db, [Rol.admin_un], tenant_id=folio.tenant_id, un_id=folio.un_id)
    destinatarios += await notificaciones_service.destinatarios_por_rol(db, [Rol.admin_empresa], tenant_id=folio.tenant_id)
    await notificaciones_service.notificar(db, "oc_activo.pendiente", destinatarios, {"folio_id": str(folio.id), "numero_folio": folio.numero_folio},
                                           asunto=f"Folio {folio.numero_folio}: instalación de activo pendiente de OC", cuerpo=folio.descripcion[:300], url="/oc-activos",
                                           tenant_id=folio.tenant_id, prestador_id=folio.prestador_id)
    return aut


async def desde_respuesta(db: AsyncSession, actor: ActorFolio, r: FormularioRespuesta, esquema, *, origen: str, folio: Folio | None = None, request: Request | None = None) -> FolioActivoAutorizacion | None:
    """Gancho de P03/P04: al enviar un formulario de atención o al capturar con formulario de captura."""
    datos = detectar(esquema, r.respuestas_json or {})
    if datos is None:
        return None
    folio = folio or (await db.get(Folio, r.referencia_id) if r.referencia_id else None)
    if folio is None or folio.estado in (EstadoFolio.cerrado, EstadoFolio.cancelado):
        return None
    return await marcar(db, folio, actor, datos, origen=origen, respuesta_id=r.id, request=request)


# ------------------------------------------------------------- consultas

async def autorizacion_de(db: AsyncSession, folio_id: UUID) -> FolioActivoAutorizacion | None:
    return (await db.execute(select(FolioActivoAutorizacion).where(FolioActivoAutorizacion.folio_id == folio_id))).scalar_one_or_none()


async def _historial(db: AsyncSession, folio: Folio, anterior: str | None, nuevo: str, actor: ActorFolio, notas: str = "") -> None:
    db.add(FolioActivoHistorial(folio_id=folio.id, tenant_id=folio.tenant_id, prestador_id=folio.prestador_id, estatus_anterior=anterior, estatus_nuevo=nuevo,
                                actor_id=getattr(actor, "id", None), actor_rol=folio_estados.rol_de(actor), timestamp=datetime.now(UTC), notas=notas or ""))
    await db.flush()


async def historial_de(db: AsyncSession, folio_id: UUID) -> list[dict[str, Any]]:
    filas = list((await db.execute(select(FolioActivoHistorial).where(FolioActivoHistorial.folio_id == folio_id).order_by(FolioActivoHistorial.timestamp, FolioActivoHistorial.id))).scalars())
    nombres = {u.id: u.nombre for u in (await db.execute(select(Usuario).where(Usuario.id.in_({h.actor_id for h in filas if h.actor_id})))).scalars()} if any(h.actor_id for h in filas) else {}
    return [{"id": h.id, "estatus_anterior": h.estatus_anterior, "estatus_nuevo": h.estatus_nuevo, "actor_id": h.actor_id, "actor_nombre": nombres.get(h.actor_id), "actor_rol": h.actor_rol,
             "timestamp": h.timestamp, "notas": h.notas} for h in filas]


def serializar(aut: FolioActivoAutorizacion) -> dict[str, Any]:
    return {"id": aut.id, "folio_id": aut.folio_id, "tenant_id": aut.tenant_id, "prestador_id": aut.prestador_id, "un_id": aut.un_id, "estatus_multinivel": aut.estatus_multinivel.value,
            "estatus_nombre": NOMBRES[aut.estatus_multinivel], "estatus_desde": aut.estatus_desde, "dias_en_estatus": max(0, (datetime.now(UTC) - aut.estatus_desde).days),
            "numero_oc_provisional": aut.numero_oc_provisional, "numero_oc_definitivo": aut.numero_oc_definitivo, "fecha_autorizacion_erp": aut.fecha_autorizacion_erp,
            "registrado_por": aut.registrado_por, "notas": aut.notas, "decision_rechazo": aut.decision_rechazo.value if aut.decision_rechazo else None,
            "periodo_presupuestal_destino": aut.periodo_presupuestal_destino, "origen": aut.origen, "datos_equipo": aut.datos_equipo_json,
            "hallazgo_presupuesto_id": aut.hallazgo_presupuesto_id, "destinos": [d.value for d in ORDEN_DESTINOS if d in TRANSICIONES[aut.estatus_multinivel]],
            "created_at": aut.created_at, "updated_at": aut.updated_at}


async def obtener(db: AsyncSession, actor: Actor, folio_id: UUID) -> tuple[Folio, FolioActivoAutorizacion]:
    from services import folios_captura_service as captura

    if actor.rol not in CONSULTAN:
        raise prohibido("Tu rol no consulta el seguimiento de OC de activos")
    folio = await captura.obtener(db, actor, folio_id)
    aut = await autorizacion_de(db, folio.id)
    if aut is None:
        raise no_encontrado("Autorización de activo")
    return folio, aut


async def pendientes(db: AsyncSession, actor: Actor, tenant_id: UUID | None = None, incluir_resueltos: bool = False) -> list[dict[str, Any]]:
    """Vista «folios de activos pendientes de autorización» para Admin UN (sus UNs) y Admin empresa; el prestador la consulta por cliente."""
    from services import folios_captura_service as captura

    if actor.rol not in CONSULTAN:
        raise prohibido("Tu rol no consulta el seguimiento de OC de activos")
    consulta = select(FolioActivoAutorizacion).order_by(FolioActivoAutorizacion.estatus_desde)
    if not incluir_resueltos:
        consulta = consulta.where(FolioActivoAutorizacion.estatus_multinivel.in_((S.pendiente_iniciar_tramite, S.oc_en_tramite, S.oc_autorizada)))
    if actor.dominio == Dominio.tenant:
        consulta = consulta.where(FolioActivoAutorizacion.tenant_id == actor.tenant_id)
        unidades = await _unidades_visibles(db, actor)
        if unidades is not None:
            consulta = consulta.where(FolioActivoAutorizacion.un_id.in_(unidades))
    elif not actor.es_superadmin:
        consulta = consulta.where(FolioActivoAutorizacion.prestador_id == actor.prestador_id)
    if tenant_id:
        consulta = consulta.where(FolioActivoAutorizacion.tenant_id == tenant_id)
    filas = list((await db.execute(consulta)).scalars())
    if not filas:
        return []
    folios = {f.id: f for f in (await db.execute(select(Folio).where(Folio.id.in_([a.folio_id for a in filas])))).scalars()}
    resumenes = {r["id"]: r for r in await captura.resumen(db, [folios[a.folio_id] for a in filas if a.folio_id in folios])}
    return [{**serializar(a), "folio": resumenes.get(a.folio_id)} for a in filas if a.folio_id in resumenes]


# ------------------------------------------------------------ transiciones

async def cambiar_estatus(db: AsyncSession, actor: Actor, folio: Folio, aut: FolioActivoAutorizacion, nuevo: S, *, numero_oc_provisional: str | None = None,
                          numero_oc_definitivo: str | None = None, fecha_autorizacion_erp: date | None = None, notas: str = "", decision_rechazo: DecisionOCRechazo | None = None,
                          periodo_destino: str | None = None, request: Request | None = None) -> FolioActivoAutorizacion:
    """Transiciones literales de §6.10.7, todas por el Admin empresa salvo `listo_para_asignar` (sistema)."""
    if not actor.es_superadmin and actor.rol not in ACTUALIZAN:
        raise prohibido("Solo el Admin empresa registra el estatus de la OC en ACMA (§6.10.7)")
    if actor.dominio == Dominio.tenant and aut.tenant_id != actor.tenant_id:
        raise no_encontrado("Folio")
    if nuevo == S.listo_para_asignar or nuevo not in TRANSICIONES[aut.estatus_multinivel]:
        raise ErrorAPI(409, "TRANSICION_NO_PERMITIDA", f"El estatus {NOMBRES[aut.estatus_multinivel]} no pasa a {NOMBRES[nuevo]}",
                       [{"estatus_actual": aut.estatus_multinivel.value, "destinos_posibles": [d.value for d in ORDEN_DESTINOS if d in TRANSICIONES[aut.estatus_multinivel]]}])
    anterior = aut.estatus_multinivel
    antes = auditoria.instantanea(aut)
    if numero_oc_provisional is not None:
        aut.numero_oc_provisional = numero_oc_provisional.strip() or None
    if nuevo == S.oc_autorizada:
        if not (numero_oc_definitivo or "").strip() or fecha_autorizacion_erp is None:
            raise ErrorAPI(422, "OC_DEFINITIVA_REQUERIDA", "OC autorizada exige número de OC definitivo y fecha de autorización en el ERP")
        aut.numero_oc_definitivo, aut.fecha_autorizacion_erp = numero_oc_definitivo.strip(), fecha_autorizacion_erp
    if nuevo == S.oc_rechazada:
        if decision_rechazo is None:
            raise ErrorAPI(422, "DECISION_REQUERIDA", "OC rechazada exige la decisión: cancelar o reprogramar_periodo")
        if decision_rechazo == DecisionOCRechazo.reprogramar_periodo and not (periodo_destino or "").strip():
            raise ErrorAPI(422, "PERIODO_REQUERIDO", "Reprogramar exige el período presupuestal destino")
        aut.decision_rechazo, aut.periodo_presupuestal_destino = decision_rechazo, (periodo_destino or "").strip() or None
    aut.estatus_multinivel, aut.estatus_desde, aut.registrado_por = nuevo, datetime.now(UTC), actor.id
    if notas:
        aut.notas = notas
    await db.flush()
    await _historial(db, folio, anterior.value, nuevo.value, actor, notas)
    await auditoria.registrar_actor(db, actor, f"oc_activos.{nuevo.value}", request, tenant_id=folio.tenant_id, prestador_id=folio.prestador_id, recurso_tipo="folio", recurso_id=folio.id,
                                    antes=antes, despues=auditoria.instantanea(aut))
    await folio_estados.comentar(db, folio, actor, f"OC de activo: {NOMBRES[nuevo]}" + (f" ({aut.numero_oc_definitivo or aut.numero_oc_provisional})" if aut.numero_oc_definitivo or aut.numero_oc_provisional else ""),
                                 {"estatus": nuevo.value, "numero_oc_provisional": aut.numero_oc_provisional, "numero_oc_definitivo": aut.numero_oc_definitivo}, evento="activo.oc")
    if nuevo == S.oc_autorizada:
        await _listo_para_asignar(db, folio, aut, request)
    elif nuevo == S.oc_rechazada:
        await _rechazada(db, actor, folio, aut, notas, request)
    return aut


async def _listo_para_asignar(db: AsyncSession, folio: Folio, aut: FolioActivoAutorizacion, request: Request | None) -> None:
    """Sistema: resuelve el trigger y, si el folio seguía en revisión solo por la OC, lo autoriza (entra al flujo normal de asignación)."""
    trigger = (await db.execute(select(RevisionManualTrigger).where(RevisionManualTrigger.folio_id == folio.id, RevisionManualTrigger.trigger_tipo == TriggerRevision.pendiente_oc_cliente,
                                                                    RevisionManualTrigger.resuelto.is_(False)))).scalar_one_or_none()
    if trigger is not None:
        trigger.resuelto = True
    anterior = aut.estatus_multinivel
    aut.estatus_multinivel, aut.estatus_desde = S.listo_para_asignar, datetime.now(UTC)
    await db.flush()
    await _historial(db, folio, anterior.value, S.listo_para_asignar.value, ACTOR_SISTEMA, "OC autorizada en el ERP del cliente: el folio entra al flujo de asignación")
    pendientes_otros = (await db.execute(select(RevisionManualTrigger.id).where(RevisionManualTrigger.folio_id == folio.id, RevisionManualTrigger.resuelto.is_(False)))).first()
    contexto = {"oc_definitiva": aut.numero_oc_definitivo, "fecha_autorizacion_erp": aut.fecha_autorizacion_erp.isoformat() if aut.fecha_autorizacion_erp else None}
    if folio.estado == EstadoFolio.en_revision and pendientes_otros is None:
        await folio_estados.transicionar(db, folio, EstadoFolio.autorizado, ACTOR_SISTEMA, f"OC {aut.numero_oc_definitivo} autorizada en el ERP del cliente (§6.10.7)", contexto, request)
    elif folio.estado == EstadoFolio.en_revision:
        destinatarios = await notificaciones_service.destinatarios_por_rol(db, [Rol.despachador, Rol.admin_prestador], prestador_id=folio.prestador_id)
        await notificaciones_service.notificar(db, "folio.revision", destinatarios, {"folio_id": str(folio.id)}, asunto=f"Folio {folio.numero_folio}: OC autorizada; quedan triggers de revisión",
                                               cuerpo="Resuelve los triggers restantes para autorizar el folio", url=f"/folios/{folio.id}", tenant_id=folio.tenant_id, prestador_id=folio.prestador_id)
    destinatarios = await notificaciones_service.destinatarios_por_rol(db, [Rol.despachador, Rol.mesa_control], prestador_id=folio.prestador_id)
    await notificaciones_service.notificar(db, "oc_activo.autorizada", destinatarios, {"folio_id": str(folio.id), "numero_folio": folio.numero_folio, **contexto},
                                           asunto=f"Folio {folio.numero_folio} listo para asignar (OC {aut.numero_oc_definitivo})", cuerpo=folio.descripcion[:300], url=f"/folios/{folio.id}",
                                           tenant_id=folio.tenant_id, prestador_id=folio.prestador_id)


async def _rechazada(db: AsyncSession, actor: Actor, folio: Folio, aut: FolioActivoAutorizacion, notas: str, request: Request | None) -> None:
    """OC rechazada: `cancelar` cancela el folio con razón; `reprogramar_periodo` crea el registro en Por presupuesto (P07) con el período
    destino y cancela el folio (queda enlazado por `derivaciones`)."""
    razon = f"OC rechazada en el ERP del cliente ({aut.decision_rechazo.value})" + (f": {notas}" if notas else "")
    if aut.decision_rechazo == DecisionOCRechazo.reprogramar_periodo:
        from services.seguimiento import presupuesto

        hp = await presupuesto.crear(db, actor, tenant_id=folio.tenant_id, prestador_id=folio.prestador_id, un_id=folio.un_id, equipo_id=folio.equipo_id,
                                     descripcion=f"Instalación de activo diferida: {folio.descripcion}"[:4000], folio_id=folio.id, origen="oc_rechazada", monto_estimado=folio.monto_estimado)
        hp.periodo_presupuestal = aut.periodo_presupuestal_destino or hp.periodo_presupuestal
        aut.hallazgo_presupuesto_id = hp.id
        await db.flush()
        razon += f" · reprogramado al período {aut.periodo_presupuestal_destino}"
    if folio.estado not in (EstadoFolio.cerrado, EstadoFolio.cancelado):
        actor_cancela = ACTOR_SISTEMA if folio_estados.puede(ACTOR_SISTEMA, folio.estado, EstadoFolio.cancelado) else actor
        await folio_estados.transicionar(db, folio, EstadoFolio.cancelado, actor_cancela, razon, {"razon_cancelacion": razon, "decision_rechazo": aut.decision_rechazo.value,
                                                                                                  "periodo_presupuestal_destino": aut.periodo_presupuestal_destino,
                                                                                                  "hallazgo_presupuesto_id": str(aut.hallazgo_presupuesto_id) if aut.hallazgo_presupuesto_id else None}, request)
    destinatarios = await notificaciones_service.destinatarios_por_rol(db, [Rol.despachador, Rol.mesa_control], prestador_id=folio.prestador_id)
    destinatarios += await notificaciones_service.destinatarios_por_rol(db, [Rol.admin_un], tenant_id=folio.tenant_id, un_id=folio.un_id)
    await notificaciones_service.notificar(db, "oc_activo.rechazada", destinatarios, {"folio_id": str(folio.id), "numero_folio": folio.numero_folio, "decision": aut.decision_rechazo.value},
                                           asunto=f"Folio {folio.numero_folio}: OC rechazada ({aut.decision_rechazo.value})", cuerpo=razon, url=f"/folios/{folio.id}", tenant_id=folio.tenant_id,
                                           prestador_id=folio.prestador_id)


# ----------------------------------------------------- alta automática

def _decimal(valor: Any) -> Decimal | None:
    try:
        return Decimal(str(valor)) if valor not in (None, "") else None
    except (InvalidOperation, ValueError):
        return None


async def _tipo_equipo(db: AsyncSession, folio: Folio, valor: Any) -> TipoEquipo | None:
    if valor in (None, ""):
        return None
    try:
        tipo = await db.get(TipoEquipo, UUID(str(valor)))
        if tipo is not None:
            return tipo
    except (ValueError, TypeError):
        pass
    texto = str(valor).strip().lower()
    for t in (await db.execute(select(TipoEquipo).where(TipoEquipo.activa.is_(True)))).scalars():
        if t.nombre.strip().lower() == texto:
            return t
    return None


async def alta_equipo(db: AsyncSession, folio: Folio, actor: ActorFolio, aut: FolioActivoAutorizacion | None = None) -> Equipo:
    """§6.10.7: al cerrar el folio, el equipo instalado se da de alta con los datos mapeados del formulario; si falta el tipo de equipo
    queda `inactivo` con la alerta ACTIVO_INSTALADO_INCOMPLETO para que el Admin empresa complete la ficha."""
    aut = aut or await autorizacion_de(db, folio.id)
    datos = dict(aut.datos_equipo_json) if aut else {}
    base = await db.get(Equipo, folio.equipo_id)
    un = await db.get(UnidadNegocio, folio.un_id)
    tipo = await _tipo_equipo(db, folio, datos.get("tipo_equipo"))
    incompleto = tipo is None
    contrato = await folios_sla.contrato_vigente(db, base, (folio.fecha_cierre or datetime.now(UTC)).date()) if base else None
    codigo = f"ACT-{folio.numero_folio}"
    marca, modelo = (str(datos.get("marca") or "").strip() or None), (str(datos.get("modelo") or "").strip() or None)
    nombre = str(datos.get("nombre") or "").strip() or " ".join(x for x in ((tipo.nombre if tipo else None), marca, modelo) if x) or f"Activo instalado {folio.numero_folio}"
    equipo = Equipo(tenant_id=folio.tenant_id, un_id=folio.un_id, tipo_equipo_id=tipo.id if tipo else base.tipo_equipo_id, codigo=codigo, nombre=nombre[:160], marca=marca[:80] if marca else None,
                    modelo=modelo[:80] if modelo else None, numero_serie=(str(datos.get("numero_serie") or "").strip() or None), fecha_instalacion=(folio.fecha_cierre or datetime.now(UTC)).date(),
                    valor_reposicion=_decimal(datos.get("valor_reposicion")), estado=EstadoActivo.inactivo if incompleto else EstadoActivo.activo, contrato_id=contrato.id if contrato else None,
                    notas=f"Alta automática al cerrar el folio {folio.numero_folio} (§6.10.7)" + ("; falta el tipo de equipo" if incompleto else ""), criticidad=base.criticidad if base else None)
    # `equipos` solo lo escribe el tenant (RLS de P02); el cierre lo ejecuta el técnico del prestador, así que el alta va con el
    # contexto de sistema dentro de la misma transacción y luego se restaura el contexto del actor.
    from core.rls import CONTEXTO_SISTEMA, fijar_contexto

    previo = db.info.get("rls")
    await fijar_contexto(db, CONTEXTO_SISTEMA)
    try:
        db.add(equipo)
        await db.flush()
    finally:
        if previo is not None:
            await fijar_contexto(db, previo)
    folio.equipo_instalado_id = equipo.id
    await auditoria.registrar(db, "oc_activos.equipo_alta", actor_rol=folio_estados.rol_de(actor), actor_id=getattr(actor, "id", None), tenant_id=folio.tenant_id, prestador_id=folio.prestador_id,
                              recurso_tipo="equipo", recurso_id=equipo.id, despues={"codigo": codigo, "folio": folio.numero_folio, "incompleto": incompleto, "datos": datos})
    if aut is not None:
        await _historial(db, folio, aut.estatus_multinivel.value, aut.estatus_multinivel.value, actor, f"Equipo {codigo} dado de alta al cerrar" + (" (ficha incompleta)" if incompleto else ""))
    if incompleto:
        await alertas_service.disparar(db, "ACTIVO_INSTALADO_INCOMPLETO", tenant_id=folio.tenant_id, prestador_id=folio.prestador_id, entidad_tipo="equipo", entidad_id=equipo.id,
                                       datos={"codigo": codigo, "numero_folio": folio.numero_folio, "faltan": ["tipo_equipo"], "un": un.codigo if un else None})
        destinatarios = await notificaciones_service.destinatarios_por_rol(db, [Rol.admin_empresa], tenant_id=folio.tenant_id)
        await notificaciones_service.notificar(db, "oc_activo.equipo_incompleto", destinatarios, {"equipo_id": str(equipo.id), "folio_id": str(folio.id)},
                                               asunto=f"Completa la ficha del equipo {codigo} (instalado con el folio {folio.numero_folio})", cuerpo="Falta el tipo de equipo; el activo quedó inactivo",
                                               url="/catalogos", tenant_id=folio.tenant_id, prestador_id=folio.prestador_id)
    return equipo


@folio_estados.suscribir_validacion
async def _alta_al_cerrar(db: AsyncSession, folio: Folio, nuevo: EstadoFolio, actor: ActorFolio, contexto: dict) -> None:
    """Se ejecuta antes del UPDATE del cierre (el folio cerrado es inmutable), así `equipo_instalado_id` viaja en la misma transición."""
    if nuevo != EstadoFolio.cerrado or not folio.es_instalacion_activo or folio.equipo_instalado_id is not None:
        return
    equipo = await alta_equipo(db, folio, actor)
    contexto["equipo_instalado_id"] = str(equipo.id)
    contexto["equipo_instalado_codigo"] = equipo.codigo


async def detalle_folio(db: AsyncSession, folio: Folio) -> dict[str, Any] | None:
    aut = await autorizacion_de(db, folio.id)
    if aut is None:
        return None
    equipo = await db.get(Equipo, folio.equipo_instalado_id) if folio.equipo_instalado_id else None
    return {**serializar(aut), "historial": await historial_de(db, folio.id),
            "equipo_instalado": {"id": equipo.id, "codigo": equipo.codigo, "nombre": equipo.nombre, "estado": equipo.estado.value, "marca": equipo.marca, "modelo": equipo.modelo,
                                 "numero_serie": equipo.numero_serie} if equipo else None}
