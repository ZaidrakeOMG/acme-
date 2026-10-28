"""Entradas a los módulos desde los tres orígenes (§7.4 respuesta a la minuta, §6.10.5 clasificación, §6.8.7 rechazo en el flujo
multinivel) y el folio correctivo directo «autorizar reparar sin cotización»."""
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from fastapi import Request
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from core.dependencias import Actor
from models.catalogos import Equipo, NivelSeveridadCatalogo
from models.folios import AprobacionDecision, DecisionAprobacion, EstadoFolio, Folio, ModuloDestino, SeveridadOrigen, TipoFolio
from models.minutas import Hallazgo, OpcionRespuesta
from models.seguimiento import OpcionClasificacion, VarianteCoordinado
from services import auditoria, folio_estados, notificaciones_service
from services.folio_estados import ACTOR_SISTEMA, ActorFolio
from services.seguimiento import cotizaciones, interno, presupuesto, reprogramacion

OPCION_A_MODULO = {
    OpcionRespuesta.cotizacion: ModuloDestino.cotizaciones, OpcionRespuesta.por_presupuesto: ModuloDestino.por_presupuesto,
    OpcionRespuesta.seguimiento_interno: ModuloDestino.seguimiento_interno, OpcionRespuesta.reprogramacion: ModuloDestino.reprogramacion,
}
CLASIFICACION_A_MODULO = {
    OpcionClasificacion.cotizacion: ModuloDestino.cotizaciones, OpcionClasificacion.presupuesto: ModuloDestino.por_presupuesto,
    OpcionClasificacion.seguimiento_interno: ModuloDestino.seguimiento_interno, OpcionClasificacion.reprogramacion: ModuloDestino.reprogramacion,
}


async def folio_directo(db: AsyncSession, actor: ActorFolio, *, tenant_id: UUID, prestador_id: UUID, un_id: UUID, equipo_id: UUID | None, descripcion: str,
                        contexto: dict[str, Any], folio_origen_id: UUID | None = None, request: Request | None = None) -> Folio:
    """Folio correctivo capturado por el sistema que pasa directo a Autorizado (sin flujo multinivel: el cliente ya decidió)."""
    equipo = await db.get(Equipo, equipo_id) if equipo_id else None
    if equipo is None and folio_origen_id:
        origen = await db.get(Folio, folio_origen_id)
        equipo = await db.get(Equipo, origen.equipo_id) if origen else None
    if equipo is None:
        equipo = (await db.execute(select(Equipo).where(Equipo.un_id == un_id).order_by(Equipo.codigo))).scalars().first()
    if equipo is None:
        from core.errors import ErrorAPI

        raise ErrorAPI(422, "EQUIPO_REQUERIDO", "La UN no tiene equipos: el folio correctivo necesita un equipo")
    origen = await db.get(Folio, folio_origen_id) if folio_origen_id else None
    severidad_id = origen.severidad_id if origen and origen.severidad_id else (await db.execute(
        select(NivelSeveridadCatalogo.id).where(NivelSeveridadCatalogo.prestador_id == prestador_id, NivelSeveridadCatalogo.activo.is_(True)).order_by(NivelSeveridadCatalogo.orden))).scalar()
    numero = (await db.execute(text("SELECT acma_siguiente_numero_folio(:t)"), {"t": tenant_id})).scalar_one()
    ahora = datetime.now(UTC)
    capturador = getattr(actor, "id", None) or (origen.capturado_por if origen else None)
    if capturador is None:
        from services.preventivos_service import _usuario_capturador

        capturador = await _usuario_capturador(db, prestador_id, None)
    folio = Folio(numero_folio=numero, tenant_id=tenant_id, prestador_id=prestador_id, un_id=un_id, equipo_id=equipo.id, tipo_falla_id=origen.tipo_falla_id if origen else None,
                  tipo_folio=TipoFolio.correctivo, descripcion=descripcion[:4000], confirmacion_un=True, confirmacion_un_timestamp=ahora, severidad_id=severidad_id,
                  severidad_origen=SeveridadOrigen.automatica_matriz, capturado_por=capturador, capturado_at=ahora, fecha_falla=ahora, folio_duplicado_ref_id=folio_origen_id)
    db.add(folio)
    await db.flush()
    await folio_estados.registrar_historial(db, folio, actor, estado_anterior=None, estado_nuevo=EstadoFolio.capturado,
                                            notas="Folio correctivo generado desde un módulo de seguimiento", contexto=contexto)
    await auditoria.registrar(db, "folio.directo_generado", actor_rol=folio_estados.rol_de(actor), actor_id=getattr(actor, "id", None), tenant_id=tenant_id,
                              prestador_id=prestador_id, recurso_tipo="folio", recurso_id=folio.id, despues={"numero_folio": numero, **contexto})
    await folio_estados.notificar_creacion(db, folio, actor)
    await folio_estados.transicionar(db, folio, EstadoFolio.autorizado, ACTOR_SISTEMA, "Autorizado por el cliente sin cotización (§7.4)", contexto, request)
    return folio


async def desde_hallazgo(db: AsyncSession, actor: Actor, h: Hallazgo, opcion: OpcionRespuesta, *, notas: str = "", fecha_tentativa: date | None = None,
                         proveedor: str | None = None, trabajo_coordinado: bool = False, variante: VarianteCoordinado | None = None, request: Request | None = None):
    """§7.4: efecto literal de cada opción. Devuelve (modulo_destino, registro | folio | None)."""
    comunes = dict(tenant_id=h.tenant_id, prestador_id=h.prestador_id, un_id=h.un_id, equipo_id=h.equipo_id, descripcion=h.descripcion, hallazgo_id=h.id, folio_id=h.folio_id)
    if opcion == OpcionRespuesta.enterado:
        return None, None
    if opcion == OpcionRespuesta.autorizar_reparar:
        folio = await folio_directo(db, actor, tenant_id=h.tenant_id, prestador_id=h.prestador_id, un_id=h.un_id, equipo_id=h.equipo_id,
                                    descripcion=f"Hallazgo autorizado sin cotización: {h.descripcion}", contexto={"hallazgo_id": str(h.id), "origen": "minuta"},
                                    folio_origen_id=h.folio_id, request=request)
        return None, folio
    if opcion == OpcionRespuesta.cotizacion:
        return ModuloDestino.cotizaciones, await cotizaciones.crear(db, actor, **comunes, origen="minuta", request=request)
    if opcion == OpcionRespuesta.por_presupuesto:
        return ModuloDestino.por_presupuesto, await presupuesto.crear(db, actor, **comunes, origen="minuta")
    if opcion == OpcionRespuesta.seguimiento_interno:
        return ModuloDestino.seguimiento_interno, await interno.crear(db, actor, **comunes, origen="minuta")
    if opcion == OpcionRespuesta.reprogramacion:
        return ModuloDestino.reprogramacion, await reprogramacion.crear(db, actor, **comunes, origen="minuta", motivo=notas, fecha_tentativa=fecha_tentativa,
                                                                        trabajo_coordinado=trabajo_coordinado, variante=variante, proveedor=proveedor)
    raise ValueError(opcion)


async def desde_clasificacion(db: AsyncSession, actor: Actor, folio: Folio, opcion: OpcionClasificacion, *, fecha_tentativa: date | None, notas: str,
                              request: Request | None):
    """§6.10.5: efecto de las cinco opciones (la opción `autorizado` la ejecuta clasificacion_service)."""
    comunes = dict(tenant_id=folio.tenant_id, prestador_id=folio.prestador_id, un_id=folio.un_id, equipo_id=folio.equipo_id,
                   descripcion=f"Folio {folio.numero_folio}: {folio.descripcion}", folio_id=folio.id)
    if opcion == OpcionClasificacion.presupuesto:
        return ModuloDestino.por_presupuesto, await presupuesto.crear(db, actor, **comunes, origen="clasificacion", monto_estimado=folio.monto_estimado)
    if opcion == OpcionClasificacion.cotizacion:
        return ModuloDestino.cotizaciones, await cotizaciones.crear(db, actor, **comunes, origen="clasificacion", request=request)
    if opcion == OpcionClasificacion.seguimiento_interno:
        return ModuloDestino.seguimiento_interno, await interno.crear(db, actor, **comunes, origen="clasificacion")
    if opcion == OpcionClasificacion.reprogramacion:
        return ModuloDestino.reprogramacion, await reprogramacion.crear(db, actor, **comunes, origen="clasificacion", motivo=notas, fecha_tentativa=fecha_tentativa)
    return None, None


async def desde_derivacion(db: AsyncSession, folio: Folio, decision: AprobacionDecision):
    """§6.8.7: el rechazo del flujo multinivel deriva el folio al módulo; completa `modulo_destino_id`."""
    if decision.modulo_destino is None or decision.modulo_destino_id is not None:
        return None
    comunes = dict(tenant_id=folio.tenant_id, prestador_id=folio.prestador_id, un_id=folio.un_id, equipo_id=folio.equipo_id,
                   descripcion=f"Folio {folio.numero_folio} rechazado en aprobación: {folio.descripcion}", folio_id=folio.id)
    actor = ACTOR_SISTEMA
    if decision.modulo_destino == ModuloDestino.por_presupuesto:
        registro = await presupuesto.crear(db, actor, **comunes, origen="aprobacion_rechazada", monto_estimado=folio.monto_estimado)
    elif decision.modulo_destino == ModuloDestino.cotizaciones:
        registro = await cotizaciones.crear(db, actor, **comunes, origen="aprobacion_rechazada", solicitado_por=decision.actor_id)
    elif decision.modulo_destino == ModuloDestino.seguimiento_interno:
        registro = await interno.crear(db, actor, **comunes, origen="aprobacion_rechazada", responsable_un=decision.actor_id)
    else:
        registro = await reprogramacion.crear(db, actor, **comunes, origen="aprobacion_rechazada", motivo=decision.notas or "Rechazado: reprogramar a otra fecha")
    decision.modulo_destino_id = registro.id
    await folio_estados.comentar(db, folio, ACTOR_SISTEMA, f"Registro creado en el módulo {decision.modulo_destino.value}",
                                 {"modulo_destino": decision.modulo_destino.value, "modulo_destino_id": str(registro.id), "decision_id": str(decision.id), "procesado_por_p07": True},
                                 evento="folio.derivado_a_modulo")
    await db.flush()
    return registro


async def procesar_derivaciones_pendientes(db: AsyncSession) -> int:
    """Rechazos ya registrados (P04) sin registro en su módulo: migra los folios demo y cualquier rezago."""
    decisiones = (await db.execute(select(AprobacionDecision).where(AprobacionDecision.decision == DecisionAprobacion.rechazado,
                                                                    AprobacionDecision.modulo_destino.is_not(None), AprobacionDecision.modulo_destino_id.is_(None)))).scalars().all()
    n = 0
    for d in decisiones:
        folio = await db.get(Folio, d.folio_id)
        if folio and await desde_derivacion(db, folio, d):
            n += 1
    return n


async def notificar_entrada(db: AsyncSession, modulo: ModuloDestino | None, registro, tenant_id: UUID, prestador_id: UUID, un_id: UUID, titulo: str) -> None:
    """Aviso de bandeja al prestador cuando el cliente abre un registro que el prestador debe ver (los módulos de cotización ya avisan)."""
    if modulo in (None, ModuloDestino.cotizaciones):
        return
    from models.base import Rol

    destinatarios = await notificaciones_service.destinatarios_por_rol(db, [Rol.despachador, Rol.admin_prestador], prestador_id=prestador_id)
    await notificaciones_service.notificar(db, "seguimiento.cambio_estado", destinatarios, {"modulo": modulo.value, "registro_id": str(registro.id)}, asunto=titulo,
                                           url=f"/seguimiento/{modulo.value}/{registro.id}", tenant_id=tenant_id, prestador_id=prestador_id, canales=["app"])
