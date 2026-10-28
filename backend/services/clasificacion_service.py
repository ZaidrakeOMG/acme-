"""Clasificación de folios no críticos y calificación del Admin UN (§6.10.5). P07.

Un folio cuya severidad está en `severidades_no_criticas_json` del tenant no entra al flujo multinivel: queda en `en_revision`
con el trigger `pendiente_clasificacion` hasta que el Admin UN elige una de las cinco opciones (decisión pendiente)."""
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.dependencias import Actor
from core.errors import ErrorAPI, no_encontrado, prohibido
from models.base import EstadoRegistro, Rol
from models.catalogos import NivelSeveridadCatalogo
from models.folios import EstadoFolio, Folio, FolioSLA, RevisionManualTrigger, TriggerRevision
from models.minutas import EstadoMinuta, Minuta
from models.seguimiento import AdminUNCalificacion, ClasificacionConfiguracion, FolioClasificacion, OpcionClasificacion
from models.unidades import UnidadNegocio, UsuarioUN
from models.usuarios import Usuario
from services import alertas_service, auditoria, folio_estados, notificaciones_service
from services.folio_estados import ACTOR_SISTEMA
from services.preventivos_service import _unidades_visibles
from services.seguimiento import entradas

OPCIONES = {
    OpcionClasificacion.presupuesto: "Pendiente por presupuesto", OpcionClasificacion.reprogramacion: "Pendiente por reprogramación",
    OpcionClasificacion.cotizacion: "Pendiente por cotización", OpcionClasificacion.autorizado: "Autorizado", OpcionClasificacion.seguimiento_interno: "Seguimiento interno",
}


# ------------------------------------------------------------ configuración

async def configuracion(db: AsyncSession, tenant_id: UUID, crear: bool = False) -> ClasificacionConfiguracion | None:
    c = (await db.execute(select(ClasificacionConfiguracion).where(ClasificacionConfiguracion.tenant_id == tenant_id))).scalar_one_or_none()
    if c is None and crear:
        c = ClasificacionConfiguracion(tenant_id=tenant_id)
        db.add(c)
        await db.flush()
    return c


async def guardar_configuracion(db: AsyncSession, actor: Actor, tenant_id: UUID, cambios: dict[str, Any], request: Request | None) -> ClasificacionConfiguracion:
    if actor.rol not in (Rol.superadmin, Rol.admin_empresa):
        raise prohibido("Solo el Admin empresa configura la clasificación de folios no críticos")
    if actor.rol == Rol.admin_empresa and actor.tenant_id != tenant_id:
        raise no_encontrado("Tenant")
    c = await configuracion(db, tenant_id, crear=True)
    antes = auditoria.instantanea(c)
    for k, v in cambios.items():
        if v is not None and k in ("severidades_no_criticas_json", "plazo_horas", "umbral_calificacion", "admin_empresa_puede_clasificar", "puntos_json", "activa"):
            setattr(c, k, v)
    await db.flush()
    await auditoria.registrar_actor(db, actor, "clasificacion.configuracion", request, tenant_id=tenant_id, recurso_tipo="clasificacion_configuracion", recurso_id=c.id,
                                    antes=antes, despues=auditoria.instantanea(c))
    return c


async def requiere_clasificacion(db: AsyncSession, folio: Folio) -> bool:
    """Al capturar: ¿el folio es no crítico según el tenant?"""
    if folio.severidad_id is None:
        return False
    c = await configuracion(db, folio.tenant_id)
    if c is None or not c.activa:
        return False
    nivel = await db.get(NivelSeveridadCatalogo, folio.severidad_id)
    return bool(nivel) and nivel.clave in set(c.severidades_no_criticas_json)


async def notificar_pendiente(db: AsyncSession, folio: Folio) -> None:
    c = await configuracion(db, folio.tenant_id)
    destinatarios = await notificaciones_service.destinatarios_por_rol(db, [Rol.admin_un], tenant_id=folio.tenant_id, un_id=folio.un_id)
    if c and c.admin_empresa_puede_clasificar:
        destinatarios += await notificaciones_service.destinatarios_por_rol(db, [Rol.admin_empresa], tenant_id=folio.tenant_id)
    await notificaciones_service.notificar(db, "clasificacion.pendiente", destinatarios, {"folio_id": str(folio.id)},
                                           asunto=f"Folio {folio.numero_folio} no crítico: clasifícalo en {c.plazo_horas if c else 24} h", cuerpo=folio.descripcion[:200],
                                           url="/clasificacion", tenant_id=folio.tenant_id, prestador_id=folio.prestador_id)


# ---------------------------------------------------------------- pendientes

async def _trigger_pendiente(db: AsyncSession, folio_id: UUID) -> RevisionManualTrigger | None:
    return (await db.execute(select(RevisionManualTrigger).where(RevisionManualTrigger.folio_id == folio_id, RevisionManualTrigger.trigger_tipo == TriggerRevision.pendiente_clasificacion,
                                                                 RevisionManualTrigger.resuelto.is_(False)))).scalars().first()


async def puede_clasificar(db: AsyncSession, actor: Actor, folio: Folio) -> bool:
    if actor.es_superadmin:
        return True
    if actor.tenant_id != folio.tenant_id:
        return False
    if actor.rol == Rol.admin_un:
        return folio.un_id in (await _unidades_visibles(db, actor) or [])
    if actor.rol == Rol.admin_empresa:
        c = await configuracion(db, folio.tenant_id)
        return bool(c and c.admin_empresa_puede_clasificar)
    return False


async def pendientes(db: AsyncSession, actor: Actor, ahora: datetime | None = None) -> list[dict[str, Any]]:
    """Folios no críticos sin clasificar de las UNs del Admin UN (o de todo el tenant para el Admin empresa habilitado)."""
    if actor.rol not in (Rol.superadmin, Rol.admin_un, Rol.admin_empresa, Rol.supervisor_operadores):
        raise prohibido("La clasificación es del Admin UN (y del Admin empresa si está habilitado)")
    ahora = ahora or datetime.now(UTC)
    consulta = select(Folio, RevisionManualTrigger).join(RevisionManualTrigger, RevisionManualTrigger.folio_id == Folio.id).where(
        RevisionManualTrigger.trigger_tipo == TriggerRevision.pendiente_clasificacion, RevisionManualTrigger.resuelto.is_(False), Folio.estado == EstadoFolio.en_revision)
    if not actor.es_superadmin:
        consulta = consulta.where(Folio.tenant_id == actor.tenant_id)
        unidades = await _unidades_visibles(db, actor)
        if unidades is not None:
            consulta = consulta.where(Folio.un_id.in_(unidades))
    filas = (await db.execute(consulta.order_by(RevisionManualTrigger.timestamp))).all()
    if not filas:
        return []
    from services import folios_captura_service

    cfgs: dict[UUID, ClasificacionConfiguracion | None] = {}
    resumenes = {r["id"]: r for r in await folios_captura_service.resumen(db, [f for f, _ in filas], ahora)}
    salida = []
    for folio, trigger in filas:
        if folio.tenant_id not in cfgs:
            cfgs[folio.tenant_id] = await configuracion(db, folio.tenant_id)
        plazo_h = cfgs[folio.tenant_id].plazo_horas if cfgs[folio.tenant_id] else 24
        plazo_at = trigger.timestamp + timedelta(hours=plazo_h)
        restante = (plazo_at - ahora).total_seconds() / 3600
        salida.append({"folio": resumenes[folio.id], "pendiente_desde": trigger.timestamp, "plazo_at": plazo_at, "horas_restantes": round(restante, 1), "vencido": restante < 0,
                       "opciones": [{"valor": o.value, "texto": t} for o, t in OPCIONES.items()]})
    return salida


async def clasificar(db: AsyncSession, actor: Actor, folio: Folio, opcion: OpcionClasificacion, *, fecha_tentativa: date | None, notas: str, request: Request | None) -> FolioClasificacion:
    if not await puede_clasificar(db, actor, folio):
        raise prohibido("Solo el Admin UN de la unidad (o el Admin empresa habilitado) clasifica el folio")
    trigger = await _trigger_pendiente(db, folio.id)
    if trigger is None or folio.estado != EstadoFolio.en_revision:
        raise ErrorAPI(409, "FOLIO_NO_PENDIENTE", "El folio no está pendiente de clasificación")
    if opcion == OpcionClasificacion.reprogramacion and fecha_tentativa is None:
        raise ErrorAPI(422, "FECHA_TENTATIVA_REQUERIDA", "La reprogramación pide una fecha tentativa")
    c = await configuracion(db, folio.tenant_id)
    ahora = datetime.now(UTC)
    plazo_at = trigger.timestamp + timedelta(hours=c.plazo_horas if c else 24)
    retraso = max(Decimal("0"), Decimal(str(round((ahora - plazo_at).total_seconds() / 3600, 2))))
    modulo, registro = await entradas.desde_clasificacion(db, actor, folio, opcion, fecha_tentativa=fecha_tentativa, notas=notas, request=request)
    fc = FolioClasificacion(folio_id=folio.id, tenant_id=folio.tenant_id, prestador_id=folio.prestador_id, un_id=folio.un_id, admin_un_id=actor.id, opcion_clasificacion=opcion,
                            timestamp=ahora, plazo_at=plazo_at, dentro_de_plazo=retraso == 0, horas_retraso=retraso, fecha_tentativa=fecha_tentativa, modulo_destino=modulo,
                            modulo_registro_id=registro.id if registro is not None else None, notas=notas or "")
    db.add(fc)
    trigger.resuelto = True
    await db.flush()
    contexto = {"clasificacion": opcion.value, "clasificacion_id": str(fc.id), "dentro_de_plazo": fc.dentro_de_plazo, "modulo_destino": modulo.value if modulo else None,
                "modulo_destino_id": str(registro.id) if registro is not None else None}
    if opcion == OpcionClasificacion.autorizado:
        await folio_estados.transicionar(db, folio, EstadoFolio.autorizado, ACTOR_SISTEMA, f"Autorizado por {actor.nombre} al clasificar (§6.10.5)", contexto, request)
        sla = (await db.execute(select(FolioSLA).where(FolioSLA.folio_id == folio.id))).scalar_one_or_none()
        if sla is not None:
            sla.autorizado_en, sla.excluir_sla_por_cliente = ahora, not fc.dentro_de_plazo
    else:
        razon = f"Clasificado por {actor.nombre}: {OPCIONES[opcion]} (§6.10.5); continúa en el módulo {modulo.value if modulo else ''}"
        await folio_estados.transicionar(db, folio, EstadoFolio.cancelado, ACTOR_SISTEMA, razon, {**contexto, "razon_cancelacion": razon}, request)
        await folio_estados.comentar(db, folio, ACTOR_SISTEMA, f"Derivado al módulo {modulo.value if modulo else ''}", {**contexto, "procesado_por_p07": True}, evento="folio.derivado_a_modulo")
    await db.flush()
    await auditoria.registrar_actor(db, actor, "clasificacion.folio", request, tenant_id=folio.tenant_id, prestador_id=folio.prestador_id, recurso_tipo="folio", recurso_id=folio.id,
                                    despues={"opcion": opcion.value, "dentro_de_plazo": fc.dentro_de_plazo, "horas_retraso": str(retraso), "modulo_destino": modulo.value if modulo else None})
    await entradas.notificar_entrada(db, modulo, registro, folio.tenant_id, folio.prestador_id, folio.un_id, f"Folio {folio.numero_folio} clasificado: {OPCIONES[opcion]}")
    if opcion == OpcionClasificacion.autorizado:
        destinatarios = await notificaciones_service.destinatarios_por_rol(db, [Rol.despachador], prestador_id=folio.prestador_id)
        await notificaciones_service.notificar(db, "folio.estado", destinatarios, {"folio_id": str(folio.id)}, asunto=f"Folio {folio.numero_folio} autorizado por el cliente",
                                               cuerpo="Clasificado como Autorizado: puedes asignarlo.", url=f"/folios/{folio.id}", tenant_id=folio.tenant_id, prestador_id=folio.prestador_id)
    return fc


async def clasificacion_de(db: AsyncSession, folio_id: UUID) -> FolioClasificacion | None:
    return (await db.execute(select(FolioClasificacion).where(FolioClasificacion.folio_id == folio_id))).scalar_one_or_none()


# --------------------------------------------------------------- calificación

def periodo_de(d: date) -> str:
    return f"{d.year}-{d.month:02d}"


async def calificar(db: AsyncSession, tenant_id: UUID, periodo: str, cerrar: bool = False, ahora: datetime | None = None) -> list[AdminUNCalificacion]:
    """Puntos configurables (`puntos_json`): base − retraso proporcional en clasificaciones − folios sin clasificar vencidos −
    minutas vencidas; alerta de bajo desempeño al Admin empresa bajo el umbral."""
    ahora = ahora or datetime.now(UTC)
    c = await configuracion(db, tenant_id) or ClasificacionConfiguracion(tenant_id=tenant_id)
    p = c.puntos_json or {}
    base, por_hora, tope, sin_resp, tardia = int(p.get("base", 100)), float(p.get("clasificacion_tarde_por_hora", 2)), float(p.get("clasificacion_tarde_max", 20)), \
        float(p.get("minuta_sin_respuesta", 10)), float(p.get("minuta_tardia", 5))
    anio, mes = int(periodo[:4]), int(periodo[5:7])
    inicio = datetime(anio, mes, 1, tzinfo=UTC)
    fin = datetime(anio + (mes == 12), mes % 12 + 1, 1, tzinfo=UTC)
    admins = (await db.execute(select(Usuario).where(Usuario.tenant_id == tenant_id, Usuario.rol == Rol.admin_un, Usuario.estado == EstadoRegistro.activo))).scalars().all()
    salida = []
    for u in admins:
        unidades = set((await db.execute(select(UsuarioUN.unidad_id).where(UsuarioUN.usuario_id == u.id))).scalars())
        clasif = (await db.execute(select(FolioClasificacion).where(FolioClasificacion.tenant_id == tenant_id, FolioClasificacion.admin_un_id == u.id,
                                                                     FolioClasificacion.timestamp >= inicio, FolioClasificacion.timestamp < fin))).scalars().all()
        eventos: list[dict[str, Any]] = []
        puntos = float(base)
        a_tiempo = sum(f.dentro_de_plazo for f in clasif)
        tardios = [f for f in clasif if not f.dentro_de_plazo]
        for f in tardios:
            descuento = min(tope, float(f.horas_retraso) * por_hora)
            puntos -= descuento
            eventos.append({"tipo": "clasificacion_tardia", "folio_id": str(f.folio_id), "horas_retraso": str(f.horas_retraso), "descuento": descuento})
        # Pendientes vencidos hoy (aún sin clasificar) de sus UNs.
        sin_clasificar = 0
        if unidades:
            pend = (await db.execute(select(RevisionManualTrigger).join(Folio, Folio.id == RevisionManualTrigger.folio_id).where(
                Folio.tenant_id == tenant_id, Folio.un_id.in_(unidades), Folio.estado == EstadoFolio.en_revision, RevisionManualTrigger.resuelto.is_(False),
                RevisionManualTrigger.trigger_tipo == TriggerRevision.pendiente_clasificacion, RevisionManualTrigger.timestamp >= inicio, RevisionManualTrigger.timestamp < fin))).scalars().all()
            for t in pend:
                horas = (ahora - t.timestamp - timedelta(hours=c.plazo_horas)).total_seconds() / 3600
                if horas > 0:
                    sin_clasificar += 1
                    descuento = min(tope, horas * por_hora)
                    puntos -= descuento
                    eventos.append({"tipo": "folio_sin_clasificar", "folio_id": str(t.folio_id), "horas_retraso": round(horas, 1), "descuento": descuento})
        minutas = (await db.execute(select(Minuta).where(Minuta.tenant_id == tenant_id, Minuta.un_id.in_(unidades) if unidades else False,
                                                         Minuta.fecha >= inicio.date(), Minuta.fecha < fin.date(),
                                                         Minuta.estado.in_((EstadoMinuta.respondida, EstadoMinuta.vencida))))).scalars().all() if unidades else []
        respondidas = sum(m.estado == EstadoMinuta.respondida and (m.vence_respuesta_at is None or (m.respondida_at or ahora) <= m.vence_respuesta_at) for m in minutas)
        minutas_tardias = 0
        for m in minutas:
            if m.estado == EstadoMinuta.vencida and m.respondida_at is None:
                puntos -= sin_resp
                eventos.append({"tipo": "minuta_sin_respuesta", "minuta_id": str(m.id), "fecha": m.fecha.isoformat(), "descuento": sin_resp})
                minutas_tardias += 1
            elif m.vence_respuesta_at and m.respondida_at and m.respondida_at > m.vence_respuesta_at:
                puntos -= tardia
                eventos.append({"tipo": "minuta_tardia", "minuta_id": str(m.id), "fecha": m.fecha.isoformat(), "descuento": tardia})
                minutas_tardias += 1
        final = Decimal(str(max(0.0, min(float(base), puntos)))).quantize(Decimal("0.01"))
        cal = (await db.execute(select(AdminUNCalificacion).where(AdminUNCalificacion.tenant_id == tenant_id, AdminUNCalificacion.usuario_id == u.id,
                                                                  AdminUNCalificacion.periodo == periodo))).scalar_one_or_none()
        if cal is None:
            cal = AdminUNCalificacion(tenant_id=tenant_id, usuario_id=u.id, un_id=next(iter(unidades), None), periodo=periodo)
            db.add(cal)
        bajo_antes = (cal.calificacion_final if cal.calificacion_final is not None else Decimal(base)) < c.umbral_calificacion
        cal.puntos_total, cal.folios_clasificados_tiempo, cal.folios_tardios, cal.folios_sin_clasificar = base, a_tiempo, len(tardios), sin_clasificar
        cal.minutas_respondidas, cal.minutas_tardias, cal.calificacion_final, cal.eventos_json, cal.calculada_at, cal.cerrada = respondidas, minutas_tardias, final, eventos, ahora, cerrar
        await db.flush()
        if final < c.umbral_calificacion and not bajo_antes:
            await alertas_service.disparar(db, "ADMIN_UN_BAJO_DESEMPENO", tenant_id=tenant_id, prestador_id=None, entidad_tipo="admin_un_calificacion", entidad_id=cal.id,
                                           datos={"usuario_id": str(u.id), "periodo": periodo, "calificacion": str(final), "umbral": c.umbral_calificacion})
            destinatarios = await notificaciones_service.destinatarios_por_rol(db, [Rol.admin_empresa], tenant_id=tenant_id)
            await notificaciones_service.notificar(db, "calificacion.bajo_desempeno", destinatarios, {"usuario_id": str(u.id), "periodo": periodo, "calificacion": str(final), "eventos": eventos},
                                                   asunto=f"Bajo desempeño: {u.nombre} con {final} puntos en {periodo}",
                                                   cuerpo=f"{len(tardios)} clasificaciones tardías, {sin_clasificar} folios sin clasificar, {minutas_tardias} minutas sin respuesta o tardías.",
                                                   url="/clasificacion?vista=calificacion", tenant_id=tenant_id)
        salida.append(cal)
    return salida


async def calificar_periodo_actual(db: AsyncSession) -> int:
    hoy = date.today()
    n = 0
    for tenant_id in (await db.execute(select(ClasificacionConfiguracion.tenant_id).where(ClasificacionConfiguracion.activa.is_(True)))).scalars():
        n += len(await calificar(db, tenant_id, periodo_de(hoy), cerrar=False))
        if hoy.day == 1:  # cierre del período anterior
            anterior = (hoy.replace(day=1) - timedelta(days=1))
            await calificar(db, tenant_id, periodo_de(anterior), cerrar=True)
    return n


async def calificaciones(db: AsyncSession, actor: Actor, periodo: str | None) -> list[dict[str, Any]]:
    if actor.rol not in (Rol.superadmin, Rol.admin_empresa, Rol.admin_un):
        raise prohibido("La calificación la consultan el Admin empresa y el propio Admin UN")
    consulta = select(AdminUNCalificacion).order_by(AdminUNCalificacion.periodo.desc())
    if not actor.es_superadmin:
        consulta = consulta.where(AdminUNCalificacion.tenant_id == actor.tenant_id)
    if actor.rol == Rol.admin_un:
        consulta = consulta.where(AdminUNCalificacion.usuario_id == actor.id)
    if periodo:
        consulta = consulta.where(AdminUNCalificacion.periodo == periodo)
    filas = (await db.execute(consulta.limit(200))).scalars().all()
    nombres = {u.id: u.nombre for u in (await db.execute(select(Usuario).where(Usuario.id.in_({f.usuario_id for f in filas})))).scalars()} if filas else {}
    unidades = {u.id: u for u in (await db.execute(select(UnidadNegocio).where(UnidadNegocio.id.in_({f.un_id for f in filas if f.un_id})))).scalars()} if any(f.un_id for f in filas) else {}
    return [{**auditoria.instantanea(f), "id": f.id, "tenant_id": f.tenant_id, "usuario_id": f.usuario_id, "un_id": f.un_id, "created_at": f.created_at, "updated_at": f.updated_at,
             "calculada_at": f.calculada_at, "usuario_nombre": nombres.get(f.usuario_id), "un_codigo": unidades[f.un_id].codigo if f.un_id in unidades else None} for f in filas]
