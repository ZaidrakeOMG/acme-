"""Minuta del día (§7.1–7.5): generación por UN y global, validación del despachador con ventana, entrega por correo (HTML +
PDF firmado con SHA-256), push y bandeja, respuesta del Admin UN con las seis opciones de §7.4 y vencimiento. P07."""
import html as _html
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import Request
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import config
from core.dependencias import Actor
from core.errors import ErrorAPI, no_encontrado, prohibido
from models.base import Dominio, EstadoRegistro, Rol
from models.catalogos import Equipo
from models.folios import AprobacionFlujo, AprobacionNivelConfig, EstadoFlujo, EstadoFolio, Folio, FolioEstadoHistorial
from models.minutas import (
    CanalNotificacion, EstadoMinuta, EstadoNotificacion, EstadoRespuestaHallazgo, Hallazgo, Minuta, MinutaConfiguracion, MinutaDestinatario, MinutaRespuesta,
    MinutaSeccion, ModoMinuta, OpcionRespuesta, PeticionCliente, TipoMinuta,
)
from models.organizaciones import Prestador, Tenant, TenantPrestador
from models.preventivos import EstadoPreventivo, PreventivoCalendario
from models.seguimiento import (
    Cotizacion, EstadoCotizacion, EstadoPresupuesto, EstadoReprogramacion, EstadoSeguimientoInterno, HallazgoPresupuesto, Reprogramacion, SeguimientoInterno,
    VarianteCoordinado,
)
from models.unidades import UnidadNegocio, UsuarioUN
from models.usuarios import Usuario
from services import alertas_service, auditoria, correo, notificaciones_service, pdf
from services.almacenamiento import dueno_de, obtener_almacenamiento
from services.folio_estados import ACTOR_SISTEMA
from services.preventivos_service import _unidades_visibles, texto_desvio
from services.seguimiento import entradas, presupuesto

SECCIONES = ["contadores", "preventivos", "hallazgos", "cotizaciones", "trabajos_especiales", "peticiones", "pendientes_autorizacion", "recordatorio_presupuesto"]
TITULOS = {"contadores": "Estatus acumulado de módulos de seguimiento", "preventivos": "Mantenimientos preventivos realizados", "hallazgos": "Hallazgos importantes",
           "cotizaciones": "Cotizaciones", "trabajos_especiales": "Trabajos especiales", "peticiones": "Peticiones especiales del cliente",
           "pendientes_autorizacion": "Folios pendientes de tu autorización", "recordatorio_presupuesto": "Recordatorio de hallazgos diferidos por presupuesto"}
VALIDAN = {Rol.superadmin, Rol.despachador, Rol.admin_prestador, Rol.mesa_control}
RESPONDEN = {Rol.superadmin, Rol.admin_un, Rol.admin_empresa}
CONSULTAN = VALIDAN | RESPONDEN | {Rol.supervisor_operadores, Rol.direccion_prestador, Rol.supervisor_prestador, Rol.operador}
OPCIONES = {
    OpcionRespuesta.enterado: "Enterado sin observaciones", OpcionRespuesta.cotizacion: "Cotización", OpcionRespuesta.autorizar_reparar: "Autorizar reparar sin cotización",
    OpcionRespuesta.por_presupuesto: "Por presupuesto", OpcionRespuesta.seguimiento_interno: "Seguimiento interno", OpcionRespuesta.reprogramacion: "Reprogramación",
}


# ------------------------------------------------------------ configuración

async def configuracion(db: AsyncSession, prestador_id: UUID, tenant_id: UUID, crear: bool = True) -> MinutaConfiguracion | None:
    c = (await db.execute(select(MinutaConfiguracion).where(MinutaConfiguracion.prestador_id == prestador_id, MinutaConfiguracion.tenant_id == tenant_id))).scalar_one_or_none()
    if c is None and crear:
        c = MinutaConfiguracion(prestador_id=prestador_id, tenant_id=tenant_id)
        db.add(c)
        await db.flush()
    return c


async def guardar_configuracion(db: AsyncSession, actor: Actor, prestador_id: UUID, tenant_id: UUID, cambios: dict[str, Any], request: Request | None) -> MinutaConfiguracion:
    if actor.rol not in (Rol.superadmin, Rol.admin_prestador):
        raise prohibido("Solo el Admin prestador configura la minuta de cada cliente")
    c = await configuracion(db, prestador_id, tenant_id)
    antes = auditoria.instantanea(c)
    for k, v in cambios.items():
        if v is not None and k in ("modo", "hora_envio", "ventana_validacion_min", "plazo_respuesta_horas", "dias_sin_respuesta_alerta", "dias_cotizacion_sin_respuesta",
                                   "dias_presupuesto_sin_revision", "dias_interno_sin_actualizar"):
            setattr(c, k, ModoMinuta(v) if k == "modo" else v)
    await db.flush()
    await auditoria.registrar_actor(db, actor, "minuta.configuracion", request, tenant_id=tenant_id, prestador_id=prestador_id, recurso_tipo="minuta_configuracion",
                                    recurso_id=c.id, antes=antes, despues=auditoria.instantanea(c))
    return c


# --------------------------------------------------------------- contenido

def _rango(fecha: date, zona: str) -> tuple[datetime, datetime]:
    tz = ZoneInfo(zona or "America/Mexico_City")
    inicio = datetime.combine(fecha, time.min, tzinfo=tz)
    return inicio.astimezone(UTC), (inicio + timedelta(days=1)).astimezone(UTC)


async def unidades_con_actividad(db: AsyncSession, tenant_id: UUID, prestador_id: UUID, fecha: date, zona: str) -> list[UUID]:
    """UNs del tenant con algo que contar ese día: eventos de folio, hallazgos, peticiones o preventivos ejecutados."""
    inicio, fin = _rango(fecha, zona)
    folios = select(Folio.un_id).join(FolioEstadoHistorial, FolioEstadoHistorial.folio_id == Folio.id).where(
        Folio.tenant_id == tenant_id, Folio.prestador_id == prestador_id, FolioEstadoHistorial.timestamp >= inicio, FolioEstadoHistorial.timestamp < fin)
    hallazgos = select(Hallazgo.un_id).where(Hallazgo.tenant_id == tenant_id, Hallazgo.prestador_id == prestador_id, Hallazgo.timestamp >= inicio, Hallazgo.timestamp < fin)
    peticiones = select(PeticionCliente.un_id).where(PeticionCliente.tenant_id == tenant_id, PeticionCliente.timestamp >= inicio, PeticionCliente.timestamp < fin)
    preventivos = select(PreventivoCalendario.un_id).where(PreventivoCalendario.tenant_id == tenant_id, PreventivoCalendario.prestador_id == prestador_id,
                                                           PreventivoCalendario.fecha_real == fecha)
    ids = set()
    for consulta in (folios, hallazgos, peticiones, preventivos):
        ids |= set((await db.execute(consulta)).scalars())
    return sorted(ids, key=str)


async def contadores(db: AsyncSession, tenant_id: UUID, un_id: UUID | None, cfg: MinutaConfiguracion, hoy: date) -> dict[str, Any]:
    """Bloque 1 (§7.3): cuatro contadores acumulados con color y umbral."""
    ahora = datetime.now(UTC)

    def filtro(modelo):
        cond = [modelo.tenant_id == tenant_id]
        if un_id:
            cond.append(modelo.un_id == un_id)
        return and_(*cond)

    cot = (await db.execute(select(Cotizacion).where(filtro(Cotizacion), Cotizacion.estado.in_((EstadoCotizacion.solicitada, EstadoCotizacion.en_preparacion, EstadoCotizacion.enviada))))).scalars().all()
    limite_cot = ahora - timedelta(days=cfg.dias_cotizacion_sin_respuesta)
    cot_rojo = any(c.estado == EstadoCotizacion.enviada and (c.fecha_envio or c.estado_desde) < limite_cot for c in cot)
    pre = (await db.execute(select(HallazgoPresupuesto).where(filtro(HallazgoPresupuesto), HallazgoPresupuesto.estado == EstadoPresupuesto.diferido))).scalars().all()
    pre_amarillo = any(p.ultima_revision < ahora - timedelta(days=cfg.dias_presupuesto_sin_revision) for p in pre)
    inte = (await db.execute(select(SeguimientoInterno).where(filtro(SeguimientoInterno), SeguimientoInterno.estado.in_(
        (EstadoSeguimientoInterno.registrado, EstadoSeguimientoInterno.en_gestion, EstadoSeguimientoInterno.con_proveedor))))).scalars().all()
    inte_amarillo = any(s.ultima_actualizacion < ahora - timedelta(days=cfg.dias_interno_sin_actualizar) for s in inte)
    rep = (await db.execute(select(Reprogramacion).where(filtro(Reprogramacion), Reprogramacion.estado.in_(
        (EstadoReprogramacion.pendiente_fecha, EstadoReprogramacion.fecha_asignada, EstadoReprogramacion.tercero_confirmado, EstadoReprogramacion.en_ejecucion))))).scalars().all()
    rep_rojo = any((r.fecha_acordada is not None and r.fecha_acordada < hoy) or (r.fechas_vencidas_count > 0 and r.fecha_acordada is None) for r in rep)
    return {
        "cotizaciones": {"total": len(cot), "pendientes_enviar": sum(c.estado != EstadoCotizacion.enviada for c in cot), "pendientes_autorizar": sum(c.estado == EstadoCotizacion.enviada for c in cot),
                         "color": "rojo" if cot_rojo else "verde", "umbral": f"más de {cfg.dias_cotizacion_sin_respuesta} días sin respuesta"},
        "por_presupuesto": {"total": len(pre), "color": "amarillo" if pre_amarillo else "verde", "umbral": f"más de {cfg.dias_presupuesto_sin_revision} días sin revisión"},
        "seguimiento_interno": {"total": len(inte), "color": "amarillo" if inte_amarillo else "verde", "umbral": f"más de {cfg.dias_interno_sin_actualizar} días sin actualización"},
        "reprogramacion": {"total": len(rep), "color": "rojo" if rep_rojo else "verde", "umbral": "fechas de ejecución vencidas", "con_tercero": sum(r.proveedor_tercero is not None for r in rep)},
    }


async def _preventivos_del_dia(db: AsyncSession, tenant_id: UUID, prestador_id: UUID, un_id: UUID | None, fecha: date) -> list[dict[str, Any]]:
    consulta = select(PreventivoCalendario).where(PreventivoCalendario.tenant_id == tenant_id, PreventivoCalendario.prestador_id == prestador_id,
                                                  PreventivoCalendario.fecha_real == fecha, PreventivoCalendario.estado == EstadoPreventivo.ejecutado)
    if un_id:
        consulta = consulta.where(PreventivoCalendario.un_id == un_id)
    filas = (await db.execute(consulta.order_by(PreventivoCalendario.un_id))).scalars().all()
    salida = []
    for c in filas:
        folio = await db.get(Folio, c.folio_id) if c.folio_id else None
        equipo = await db.get(Equipo, c.equipo_id) if c.equipo_id else None
        un = await db.get(UnidadNegocio, c.un_id)
        tecnico = await db.get(Usuario, folio.tecnico_id) if folio and folio.tecnico_id else None
        salida.append({"calendario_id": str(c.id), "folio_id": str(folio.id) if folio else None, "numero_folio": folio.numero_folio if folio else None,
                       "un": f"{un.codigo} · {un.nombre}" if un else "", "equipo": f"{equipo.codigo} · {equipo.nombre}" if equipo else "UN completa",
                       "tecnico": tecnico.nombre if tecnico else "—", "hora": folio.fecha_cierre.isoformat() if folio and folio.fecha_cierre else None,
                       "fecha_programada": c.fecha_programada.isoformat(), "fecha_real": c.fecha_real.isoformat() if c.fecha_real else None,
                       "desvio_dias": c.desvio_dias, "texto_desvio": texto_desvio(c.desvio_dias)})
    return salida


async def _hallazgos_del_dia(db: AsyncSession, tenant_id: UUID, prestador_id: UUID, un_id: UUID | None, inicio: datetime, fin: datetime) -> list[dict[str, Any]]:
    from services import hallazgos_service

    consulta = select(Hallazgo).where(Hallazgo.tenant_id == tenant_id, Hallazgo.prestador_id == prestador_id,
                                      or_(and_(Hallazgo.timestamp >= inicio, Hallazgo.timestamp < fin),
                                          and_(Hallazgo.estado_respuesta == EstadoRespuestaHallazgo.pendiente, Hallazgo.timestamp < inicio)))
    if un_id:
        consulta = consulta.where(Hallazgo.un_id == un_id)
    filas = (await db.execute(consulta.order_by(Hallazgo.timestamp))).scalars().all()
    salida = []
    for h in await hallazgos_service.enriquecer(db, list(filas)):
        salida.append({"hallazgo_id": str(h["id"]), "descripcion": h["descripcion"], "equipo": f"{h['equipo_codigo']} · {h['equipo_nombre']}" if h["equipo_codigo"] else "—",
                       "un": f"{h['un_codigo']} · {h['un_nombre']}", "urgencia": h["nivel_urgencia"].value if hasattr(h["nivel_urgencia"], "value") else str(h["nivel_urgencia"]),
                       "foto_url": h["foto_url"], "tipo": h["tipo"].value if hasattr(h["tipo"], "value") else str(h["tipo"]), "numero_folio": h["numero_folio"],
                       "estado_respuesta": h["estado_respuesta"].value if hasattr(h["estado_respuesta"], "value") else str(h["estado_respuesta"]),
                       "opcion_respuesta": h["opcion_respuesta"].value if h["opcion_respuesta"] is not None and hasattr(h["opcion_respuesta"], "value") else h["opcion_respuesta"],
                       "pendiente_de_dias_anteriores": h["timestamp"] < inicio, "timestamp": h["timestamp"].isoformat()})
    return salida


async def _cotizaciones_pendientes(db: AsyncSession, tenant_id: UUID, prestador_id: UUID, un_id: UUID | None) -> dict[str, list[dict[str, Any]]]:
    consulta = select(Cotizacion).where(Cotizacion.tenant_id == tenant_id, Cotizacion.prestador_id == prestador_id,
                                        Cotizacion.estado.in_((EstadoCotizacion.solicitada, EstadoCotizacion.en_preparacion, EstadoCotizacion.enviada)))
    if un_id:
        consulta = consulta.where(Cotizacion.un_id == un_id)
    filas = (await db.execute(consulta.order_by(Cotizacion.fecha_solicitud))).scalars().all()
    salida: dict[str, list[dict[str, Any]]] = {"pendientes_enviar": [], "pendientes_autorizar": []}
    for c in filas:
        un = await db.get(UnidadNegocio, c.un_id)
        eq = await db.get(Equipo, c.equipo_id) if c.equipo_id else None
        fila = {"cotizacion_id": str(c.id), "numero": c.numero, "un": f"{un.codigo} · {un.nombre}" if un else "", "equipo": f"{eq.codigo} · {eq.nombre}" if eq else "—",
                "descripcion": c.descripcion, "monto": str(c.monto) if c.monto is not None else None, "estado": c.estado.value,
                "dias": (datetime.now(UTC) - (c.fecha_envio or c.fecha_solicitud)).days}
        salida["pendientes_autorizar" if c.estado == EstadoCotizacion.enviada else "pendientes_enviar"].append(fila)
    return salida


async def _peticiones_del_dia(db: AsyncSession, tenant_id: UUID, un_id: UUID | None, inicio: datetime, fin: datetime) -> list[dict[str, Any]]:
    consulta = select(PeticionCliente).where(PeticionCliente.tenant_id == tenant_id, PeticionCliente.timestamp >= inicio, PeticionCliente.timestamp < fin)
    if un_id:
        consulta = consulta.where(PeticionCliente.un_id == un_id)
    filas = (await db.execute(consulta.order_by(PeticionCliente.timestamp))).scalars().all()
    salida = []
    for p in filas:
        un = await db.get(UnidadNegocio, p.un_id)
        quien = await db.get(Usuario, p.capturado_por) if p.capturado_por else None
        folio = await db.get(Folio, p.folio_id) if p.folio_id else None
        salida.append({"peticion_id": str(p.id), "texto": p.texto, "un": f"{un.codigo} · {un.nombre}" if un else "", "origen": p.origen.value,
                       "capturado_por": quien.nombre if quien else "—", "numero_folio": folio.numero_folio if folio else None, "timestamp": p.timestamp.isoformat()})
    return salida


async def _pendientes_autorizacion(db: AsyncSession, tenant_id: UUID, un_id: UUID | None) -> list[dict[str, Any]]:
    """§6.8.7 canal minuta: folios en revisión con flujo activo en el nivel cuyo aprobador es el destinatario."""
    consulta = select(Folio, AprobacionFlujo).join(AprobacionFlujo, AprobacionFlujo.folio_id == Folio.id).where(
        Folio.tenant_id == tenant_id, Folio.estado == EstadoFolio.en_revision, AprobacionFlujo.estado == EstadoFlujo.activo)
    if un_id:
        consulta = consulta.where(Folio.un_id == un_id)
    niveles = {n.nivel: n for n in (await db.execute(select(AprobacionNivelConfig).where(AprobacionNivelConfig.tenant_id == tenant_id))).scalars()}
    salida = []
    for folio, flujo in (await db.execute(consulta)).all():
        cfg = niveles.get(flujo.nivel_actual)
        salida.append({"folio_id": str(folio.id), "numero_folio": folio.numero_folio, "descripcion": folio.descripcion[:200], "nivel": flujo.nivel_actual,
                       "rol_aprobador": cfg.rol_aprobador.value if cfg else None, "monto_estimado": str(folio.monto_estimado) if folio.monto_estimado is not None else None})
    return salida


async def _recordatorio_presupuesto(db: AsyncSession, tenant_id: UUID, un_id: UUID | None, fecha: date, tipo: TipoMinuta) -> list[dict[str, Any]] | None:
    """§7.7 M2: la primera minuta global del mes y la del inicio de cada período presupuestal recuerdan los diferidos."""
    if tipo != TipoMinuta.global_:
        return None
    periodo = await presupuesto.periodo_tenant(db, tenant_id)
    primera_del_mes = not (await db.execute(select(Minuta.id).where(Minuta.tenant_id == tenant_id, Minuta.tipo == TipoMinuta.global_, Minuta.fecha >= fecha.replace(day=1),
                                                                   Minuta.fecha < fecha))).first()
    inicio_periodo = bool(periodo) and presupuesto.inicio_de_periodo(periodo.tipo, periodo.fechas_json, fecha)
    if not primera_del_mes and not inicio_periodo:
        return None
    diferidos = await presupuesto.diferidos_de(db, tenant_id, un_id)
    salida = []
    for d in diferidos:
        un = await db.get(UnidadNegocio, d.un_id)
        salida.append({"hallazgo_presupuesto_id": str(d.id), "descripcion": d.descripcion, "un": f"{un.codigo} · {un.nombre}" if un else "", "periodo": d.periodo_presupuestal,
                       "dias_diferido": (datetime.now(UTC) - d.estado_desde).days, "monto_estimado": str(d.monto_estimado) if d.monto_estimado is not None else None,
                       "motivo": "inicio de período presupuestal" if inicio_periodo else "minuta mensual"})
    return salida


async def _trabajos_especiales_del_dia(db: AsyncSession, tenant_id: UUID, prestador_id: UUID, un_id: UUID | None, inicio: datetime, fin: datetime) -> dict[str, Any]:
    """§7.3 (P08): nuevos solicitados en el día, en proceso y terminados en el día con evidencia fotográfica de cierre y etiqueta de urgencia."""
    from services import trabajos_especiales_service

    return await trabajos_especiales_service.seccion_minuta(db, tenant_id, prestador_id, un_id, inicio, fin)


async def construir_secciones(db: AsyncSession, tenant_id: UUID, prestador_id: UUID, un_id: UUID | None, fecha: date, zona: str, cfg: MinutaConfiguracion,
                              tipo: TipoMinuta) -> dict[str, Any]:
    inicio, fin = _rango(fecha, zona)
    secciones = {
        "contadores": await contadores(db, tenant_id, un_id, cfg, fecha),
        "preventivos": await _preventivos_del_dia(db, tenant_id, prestador_id, un_id, fecha),
        "hallazgos": await _hallazgos_del_dia(db, tenant_id, prestador_id, un_id, inicio, fin),
        "cotizaciones": await _cotizaciones_pendientes(db, tenant_id, prestador_id, un_id),
        "trabajos_especiales": await _trabajos_especiales_del_dia(db, tenant_id, prestador_id, un_id, inicio, fin),
        "peticiones": await _peticiones_del_dia(db, tenant_id, un_id, inicio, fin),
        "pendientes_autorizacion": await _pendientes_autorizacion(db, tenant_id, un_id),
    }
    recordatorio = await _recordatorio_presupuesto(db, tenant_id, un_id, fecha, tipo)
    if recordatorio is not None:
        secciones["recordatorio_presupuesto"] = recordatorio
    return secciones


# -------------------------------------------------------------- generación

async def generar(db: AsyncSession, prestador_id: UUID, tenant_id: UUID, fecha: date, *, actor=None, forzar: bool = False, request: Request | None = None) -> list[Minuta]:
    """Una minuta por UN con actividad y una global si hubo actividad en el tenant. Idempotente por (tenant, prestador, fecha, tipo, UN)."""
    tenant = await db.get(Tenant, tenant_id)
    cfg = await configuracion(db, prestador_id, tenant_id)
    zona = tenant.zona_horaria if tenant else "America/Mexico_City"
    unidades = await unidades_con_actividad(db, tenant_id, prestador_id, fecha, zona)
    if not unidades and not forzar:
        return []
    creadas: list[Minuta] = []
    objetivos: list[tuple[TipoMinuta, UUID | None]] = [(TipoMinuta.un, u) for u in unidades] + [(TipoMinuta.global_, None)]
    for tipo, un_id in objetivos:
        existe = (await db.execute(select(Minuta.id).where(Minuta.tenant_id == tenant_id, Minuta.prestador_id == prestador_id, Minuta.fecha == fecha, Minuta.tipo == tipo,
                                                           Minuta.un_id == un_id if un_id else Minuta.un_id.is_(None)))).first()
        if existe:
            continue
        secciones = await construir_secciones(db, tenant_id, prestador_id, un_id, fecha, zona, cfg, tipo)
        m = Minuta(tenant_id=tenant_id, prestador_id=prestador_id, un_id=un_id, fecha=fecha, tipo=tipo, modo=cfg.modo, timestamp_generacion=datetime.now(UTC),
                   urgente=any(v.get("color") == "rojo" for v in secciones["contadores"].values()) or any(h["urgencia"] == "critica" for h in secciones["hallazgos"]),
                   estado=EstadoMinuta.pendiente_validacion if cfg.modo == ModoMinuta.con_validacion else EstadoMinuta.borrador)
        db.add(m)
        await db.flush()
        for orden, (clave, contenido) in enumerate(secciones.items()):
            db.add(MinutaSeccion(minuta_id=m.id, tenant_id=tenant_id, prestador_id=prestador_id, seccion=clave, orden=orden, contenido_json=contenido if isinstance(contenido, dict) else {"items": contenido}))
        await db.flush()
        await auditoria.registrar(db, "minuta.generada", actor_rol=str(getattr(actor, "rol", "sistema")) if actor else "sistema", actor_id=getattr(actor, "id", None),
                                  tenant_id=tenant_id, prestador_id=prestador_id, recurso_tipo="minuta", recurso_id=m.id,
                                  despues={"fecha": fecha.isoformat(), "tipo": tipo.value, "un_id": un_id, "modo": cfg.modo.value})
        creadas.append(m)
    if not creadas:
        return []
    if cfg.modo == ModoMinuta.con_validacion:
        destinatarios = await notificaciones_service.destinatarios_por_rol(db, [Rol.despachador], prestador_id=prestador_id)
        await notificaciones_service.notificar(db, "minuta.pendiente_validacion", destinatarios, {"fecha": fecha.isoformat(), "minutas": [str(m.id) for m in creadas]},
                                               asunto=f"Minuta del {fecha.isoformat()} de {tenant.razon_social if tenant else ''} pendiente de validación",
                                               cuerpo=f"{len(creadas)} minuta(s). Tienes {cfg.ventana_validacion_min} minutos para revisar, anotar y aprobar; después se envía automáticamente.",
                                               url="/minutas?estado=pendiente_validacion", tenant_id=tenant_id, prestador_id=prestador_id)
    else:
        for m in creadas:
            await enviar(db, m)
    return creadas


def _secciones_dict(secciones: list[MinutaSeccion]) -> dict[str, Any]:
    salida = {}
    for s in sorted(secciones, key=lambda x: x.orden):
        c = s.contenido_json
        salida[s.seccion] = c["items"] if isinstance(c, dict) and set(c) == {"items"} else c
    return salida


async def secciones_de(db: AsyncSession, minuta_id: UUID) -> dict[str, Any]:
    return _secciones_dict(list((await db.execute(select(MinutaSeccion).where(MinutaSeccion.minuta_id == minuta_id))).scalars()))


async def html_minuta(db: AsyncSession, m: Minuta) -> str:
    """Vista HTML (correo y PDF) con las secciones literales de §7.3."""
    e = _html.escape
    prestador = await db.get(Prestador, m.prestador_id)
    tenant = await db.get(Tenant, m.tenant_id)
    un = await db.get(UnidadNegocio, m.un_id) if m.un_id else None
    s = await secciones_de(db, m.id)
    c = s.get("contadores", {})
    color = {"rojo": "#fee2e2", "amarillo": "#fef3c7", "verde": "#dcfce7"}
    partes = [f"<h1>Minuta del día {m.fecha.strftime('%d/%m/%Y')} — {e(un.codigo + ' · ' + un.nombre if un else 'Global · ' + (tenant.razon_social if tenant else ''))}</h1>",
              f"<p>{e(prestador.razon_social if prestador else '')} · generada {m.timestamp_generacion.astimezone(ZoneInfo(tenant.zona_horaria if tenant else 'America/Mexico_City')).strftime('%d/%m/%Y %H:%M')}"
              f"{' · <strong class=urgente>URGENTE</strong>' if m.urgente else ''}</p>"]
    if m.notas_despachador:
        partes.append(f"<p><strong>Notas del despachador:</strong> {e(m.notas_despachador)}</p>")
    partes.append(f"<h2>{TITULOS['contadores']}</h2><table><tr>")
    for clave, titulo in (("cotizaciones", "Cotizaciones"), ("por_presupuesto", "Por presupuesto"), ("seguimiento_interno", "Seguimiento interno"), ("reprogramacion", "Reprogramación")):
        v = c.get(clave, {})
        partes.append(f"<td style='background:{color.get(v.get('color'), '#f3f4f6')};padding:8px'><strong>{titulo}</strong><br>{v.get('total', 0)}<br><small>{e(str(v.get('umbral', '')))}</small></td>")
    partes.append("</tr></table>")
    partes.append(f"<h2>{TITULOS['preventivos']}</h2>")
    prev = s.get("preventivos", [])
    partes.append("<table><tr><th>UN</th><th>Equipo</th><th>Técnico</th><th>Hora</th><th>Programado</th><th>Comparativa</th></tr>" + "".join(
        f"<tr><td>{e(p['un'])}</td><td>{e(p['equipo'])}</td><td>{e(p['tecnico'])}</td><td>{e((p['hora'] or '')[11:16])}</td><td>{e(p['fecha_programada'])}</td><td>{e(p['texto_desvio'])}</td></tr>" for p in prev)
                  + "</table>" if prev else "<p>Sin preventivos ejecutados.</p>")
    partes.append(f"<h2>{TITULOS['hallazgos']}</h2>")
    hal = s.get("hallazgos", [])
    partes.append("<table><tr><th>Descripción</th><th>Equipo</th><th>Urgencia</th><th>Foto</th><th>Respuesta</th></tr>" + "".join(
        f"<tr><td>{e(h['descripcion'])}{' <small>(pendiente de días anteriores)</small>' if h.get('pendiente_de_dias_anteriores') else ''}</td><td>{e(h['equipo'])}</td>"
        f"<td>{e(h['urgencia'])}</td><td>{'sí' if h.get('foto_url') else '—'}</td><td>{e(OPCIONES.get(OpcionRespuesta(h['opcion_respuesta']), '') if h.get('opcion_respuesta') else 'pendiente')}</td></tr>" for h in hal)
                  + "</table>" if hal else "<p>Sin hallazgos.</p>")
    cot = s.get("cotizaciones", {})
    partes.append(f"<h2>{TITULOS['cotizaciones']}</h2>")
    for clave, titulo in (("pendientes_enviar", "Pendientes de enviar al cliente"), ("pendientes_autorizar", "Pendientes de autorización")):
        lista = cot.get(clave, [])
        partes.append(f"<h3>{titulo} ({len(lista)})</h3>" + ("<table><tr><th>Número</th><th>UN</th><th>Equipo</th><th>Descripción</th><th>Monto</th></tr>" + "".join(
            f"<tr><td>{e(x['numero'])}</td><td>{e(x['un'])}</td><td>{e(x['equipo'])}</td><td>{e(x['descripcion'])}</td><td>{e(x['monto'] or '—')}</td></tr>" for x in lista) + "</table>" if lista else "<p>Ninguna.</p>"))
    te = s.get("trabajos_especiales", {})
    partes.append(f"<h2>{TITULOS['trabajos_especiales']}</h2>")
    for clave, titulo in (("nuevos", "Nuevos solicitados en el día"), ("en_proceso", "En proceso"), ("terminados", "Terminados en el día")):
        lista = te.get(clave, []) if isinstance(te, dict) else []
        partes.append(f"<h3>{titulo} ({len(lista)})</h3>" + ("<table><tr><th>Número</th><th>UN</th><th>Descripción</th><th>Estado</th><th>Monto</th><th>Evidencia</th></tr>" + "".join(
            f"<tr><td>{e(x['numero'])}{' <strong class=urgente>URGENCIA</strong>' if x.get('urgencia') else ''}</td><td>{e(x['un'])}</td><td>{e(x['descripcion'])}</td><td>{e(x['estado'])}</td>"
            f"<td>{e(x['monto'] or '—')}</td><td>{len(x.get('evidencias_cierre', [])) or '—'}</td></tr>" for x in lista) + "</table>" if lista else "<p>Ninguno.</p>"))
    pet = s.get("peticiones", [])
    partes.append(f"<h2>{TITULOS['peticiones']}</h2>" + ("<ul>" + "".join(f"<li>{e(p['texto'])} <small>({e(p['un'])} · {e(p['capturado_por'])})</small></li>" for p in pet) + "</ul>" if pet else "<p>Sin peticiones.</p>"))
    pend = s.get("pendientes_autorizacion", [])
    if pend:
        partes.append(f"<h2>{TITULOS['pendientes_autorizacion']}</h2><ul>" + "".join(f"<li>{e(p['numero_folio'])} · Nivel {p['nivel']} · {e(p['descripcion'])}</li>" for p in pend) + "</ul>")
    rec = s.get("recordatorio_presupuesto")
    if rec is not None:
        partes.append(f"<h2>{TITULOS['recordatorio_presupuesto']}</h2>" + ("<ul>" + "".join(f"<li>{e(r['descripcion'])} <small>({e(r['un'])} · {r['dias_diferido']} días · {e(r['motivo'])})</small></li>" for r in rec) + "</ul>" if rec else "<p>Sin hallazgos diferidos.</p>"))
    cuerpo = "".join(partes)
    return f"<html><head><meta charset='utf-8'><style>body{{font-family:Arial;font-size:12px;color:#1f2937}} h1{{color:{prestador.color_primario if prestador else '#1C3D8F'};font-size:18px}} h2{{font-size:14px;border-bottom:2px solid {prestador.color_acento if prestador else '#A2C62B'}}} table{{border-collapse:collapse;width:100%}} td,th{{border-bottom:1px solid #ddd;padding:5px;text-align:left;vertical-align:top}} .urgente{{color:#991b1b}}</style></head><body>{cuerpo}</body></html>", cuerpo


async def generar_pdf(db: AsyncSession, m: Minuta) -> bytes:
    html, _ = await html_minuta(db, m)
    datos = pdf.html_a_pdf(html)
    m.pdf_key = f"minutas/{m.tenant_id}/{m.fecha.isoformat()}/{m.tipo.value}-{m.un_id or 'global'}.pdf"
    m.hash_pdf = pdf.sha256(datos)
    obtener_almacenamiento().guardar(m.pdf_key, datos, "application/pdf", dueno=dueno_de(m.tenant_id, m.prestador_id))
    await db.flush()
    return datos


async def pdf_de(db: AsyncSession, m: Minuta) -> bytes:
    if m.pdf_key:
        try:
            return obtener_almacenamiento().leer(m.pdf_key)
        except Exception:  # noqa: BLE001
            pass
    return await generar_pdf(db, m)


async def destinatarios_de(db: AsyncSession, m: Minuta) -> list[UUID]:
    if m.tipo == TipoMinuta.global_:
        return await notificaciones_service.destinatarios_por_rol(db, [Rol.admin_empresa], tenant_id=m.tenant_id)
    return await notificaciones_service.destinatarios_por_rol(db, [Rol.admin_un], tenant_id=m.tenant_id, un_id=m.un_id)


async def enviar(db: AsyncSession, m: Minuta, *, sin_validacion: bool = False) -> Minuta:
    """§7.5: correo HTML + PDF firmado, push de dos líneas con badge de urgencia y bandeja; destinatarios por tipo."""
    if m.estado in (EstadoMinuta.enviada, EstadoMinuta.respondida, EstadoMinuta.vencida):
        return m
    await generar_pdf(db, m)
    cfg = await configuracion(db, m.prestador_id, m.tenant_id)
    s = await secciones_de(db, m.id)
    pendientes = [h for h in s.get("hallazgos", []) if h["estado_respuesta"] == "pendiente"]
    ahora = datetime.now(UTC)
    m.estado, m.timestamp_envio, m.enviada_sin_validacion = EstadoMinuta.enviada, ahora, sin_validacion
    m.vence_respuesta_at = ahora + timedelta(hours=cfg.plazo_respuesta_horas) if pendientes else None
    await db.flush()
    tenant = await db.get(Tenant, m.tenant_id)
    un = await db.get(UnidadNegocio, m.un_id) if m.un_id else None
    ambito = f" de {un.codigo} · {un.nombre}" if un else f" global de {tenant.razon_social if tenant else ''}"
    _, cuerpo_html = await html_minuta(db, m)
    c = s.get("contadores", {})
    resumen = f"{len(s.get('preventivos', []))} preventivo(s), {len(s.get('hallazgos', []))} hallazgo(s) ({len(pendientes)} por responder), " \
              f"{c.get('cotizaciones', {}).get('total', 0)} cotización(es) abiertas."
    rojos = [k for k, v in c.items() if v.get("color") == "rojo"]
    destinatarios = await destinatarios_de(db, m)
    url = f"/minutas/{m.id}"
    creadas = await notificaciones_service.notificar(
        db, "minuta.enviada", destinatarios, {"minuta_id": str(m.id), "fecha": m.fecha.isoformat(), "tipo": m.tipo.value, "urgente": m.urgente,
                                               "html_valores": {"saludo": "Buenas tardes,", "fecha": m.fecha.strftime("%d/%m/%Y"), "ambito": ambito, "resumen": resumen,
                                                                "urgente_html": "<p class='urgente'>⚠ Hay módulos en rojo: " + ", ".join(rojos) + "</p>" if rojos else "",
                                                                "contadores_html": "", "secciones_html": cuerpo_html, "notas_html": "", "hash_pdf": m.hash_pdf}},
        asunto=f"{'[URGENTE] ' if m.urgente else ''}Minuta del {m.fecha.strftime('%d/%m/%Y')}{ambito}", cuerpo=resumen, url=url, tenant_id=m.tenant_id, prestador_id=m.prestador_id,
        canales=["app", "push", "email"], plantilla="minuta", adjuntos=[{"nombre": f"minuta-{m.fecha.isoformat()}.pdf", "clave": m.pdf_key, "mime": "application/pdf"}])
    # F2-02 (§7.5): para quien lo pidió en sus preferencias, la minuta también sale por WhatsApp o SMS como resumen
    # de máximo 5 puntos con el enlace firmado al PDF. Va en una llamada aparte porque `canales` fuerza la lista
    # para todos los destinatarios, y estos canales son opcionales por usuario.
    for uid in destinatarios:
        extra = [c for c in await notificaciones_service.canales_de(db, uid, "minuta.enviada")
                 if c in ("whatsapp", "sms")]
        if not extra:
            continue
        creadas += await notificaciones_service.notificar(
            db, "minuta.enviada", [uid], {"minuta_id": str(m.id), "fecha": m.fecha.isoformat(), "tipo": m.tipo.value,
                                          "urgente": m.urgente},
            asunto=f"Minuta del {m.fecha.strftime('%d/%m/%Y')}{ambito}", cuerpo=resumen, url=url,
            tenant_id=m.tenant_id, prestador_id=m.prestador_id, canales=extra)

    for n in creadas:
        db.add(MinutaDestinatario(minuta_id=m.id, tenant_id=m.tenant_id, prestador_id=m.prestador_id, usuario_id=n.usuario_id, canal=n.canal,
                                  estado_entrega=n.estado if n.estado != EstadoNotificacion.pendiente else EstadoNotificacion.enviada, timestamp=ahora, notificacion_id=n.id))
    await db.flush()
    await auditoria.registrar(db, "minuta.enviada", actor_rol="sistema", tenant_id=m.tenant_id, prestador_id=m.prestador_id, recurso_tipo="minuta", recurso_id=m.id,
                              despues={"destinatarios": len(destinatarios), "hash_pdf": m.hash_pdf, "sin_validacion": sin_validacion, "urgente": m.urgente})
    return m


async def validar(db: AsyncSession, actor: Actor, m: Minuta, notas: str, request: Request | None) -> Minuta:
    if actor.rol not in VALIDAN:
        raise prohibido("Solo el Despachador (o Admin prestador / Mesa de control) valida la minuta")
    if actor.dominio == Dominio.prestador and m.prestador_id != actor.prestador_id:
        raise no_encontrado("Minuta")
    if m.estado != EstadoMinuta.pendiente_validacion:
        raise ErrorAPI(409, "MINUTA_NO_PENDIENTE", f"La minuta está {m.estado.value}")
    m.validada_por, m.notas_despachador = actor.id, (notas or "").strip()
    await db.flush()
    await auditoria.registrar_actor(db, actor, "minuta.validada", request, tenant_id=m.tenant_id, prestador_id=m.prestador_id, recurso_tipo="minuta", recurso_id=m.id,
                                    despues={"notas": m.notas_despachador})
    return await enviar(db, m)


async def vencer_validaciones(db: AsyncSession, ahora: datetime | None = None) -> int:
    """Ventana de validación vencida: se envía automáticamente y queda registrado «enviada sin validación» (decisión pendiente)."""
    ahora = ahora or datetime.now(UTC)
    filas = (await db.execute(select(Minuta).where(Minuta.estado == EstadoMinuta.pendiente_validacion))).scalars().all()
    n = 0
    for m in filas:
        cfg = await configuracion(db, m.prestador_id, m.tenant_id)
        if m.timestamp_generacion + timedelta(minutes=cfg.ventana_validacion_min) <= ahora:
            await enviar(db, m, sin_validacion=True)
            n += 1
    return n


async def vencer_respuestas(db: AsyncSession, ahora: datetime | None = None) -> int:
    ahora = ahora or datetime.now(UTC)
    filas = (await db.execute(select(Minuta).where(Minuta.estado == EstadoMinuta.enviada, Minuta.vence_respuesta_at.is_not(None), Minuta.vence_respuesta_at <= ahora))).scalars().all()
    n = 0
    for m in filas:
        m.estado = EstadoMinuta.vencida
        await db.flush()
        await alertas_service.disparar(db, "MINUTA_SIN_RESPUESTA", tenant_id=m.tenant_id, prestador_id=m.prestador_id, entidad_tipo="minuta", entidad_id=m.id,
                                       datos={"fecha": m.fecha.isoformat(), "tipo": m.tipo.value, "un_id": str(m.un_id) if m.un_id else None})
        destinatarios = await notificaciones_service.destinatarios_por_rol(db, [Rol.admin_empresa], tenant_id=m.tenant_id)
        destinatarios += await notificaciones_service.destinatarios_por_rol(db, [Rol.despachador], prestador_id=m.prestador_id)
        await notificaciones_service.notificar(db, "minuta.vencida", destinatarios, {"minuta_id": str(m.id)}, asunto=f"Minuta del {m.fecha.isoformat()} vencida sin respuesta",
                                               cuerpo="El Admin UN no respondió los hallazgos dentro del plazo; afecta su calificación del período.", url=f"/minutas/{m.id}",
                                               tenant_id=m.tenant_id, prestador_id=m.prestador_id)
        await auditoria.registrar(db, "minuta.vencida", actor_rol="sistema", tenant_id=m.tenant_id, prestador_id=m.prestador_id, recurso_tipo="minuta", recurso_id=m.id)
        n += 1
    return n


# --------------------------------------------------------------- respuesta

async def puede_responder(db: AsyncSession, actor: Actor, m: Minuta) -> bool:
    if actor.es_superadmin:
        return True
    if actor.tenant_id != m.tenant_id:
        return False
    if actor.rol == Rol.admin_empresa:
        return True
    if actor.rol == Rol.admin_un:
        unidades = await _unidades_visibles(db, actor)
        return m.un_id is None or m.un_id in (unidades or [])
    return False


async def responder(db: AsyncSession, actor: Actor, m: Minuta, hallazgo: Hallazgo, opcion: OpcionRespuesta, *, notas: str, canal: CanalNotificacion,
                    fecha_tentativa: date | None, proveedor: str | None, trabajo_coordinado: bool, variante: VarianteCoordinado | None, request: Request | None) -> MinutaRespuesta:
    """§7.4: una de seis opciones por hallazgo con su efecto literal; al responder todos, la minuta pasa a `respondida`."""
    if actor.rol not in RESPONDEN:
        raise prohibido("Solo el Admin UN o el Admin empresa responden la minuta")
    if not await puede_responder(db, actor, m):
        raise no_encontrado("Minuta")
    if m.estado not in (EstadoMinuta.enviada, EstadoMinuta.vencida, EstadoMinuta.respondida):
        raise ErrorAPI(409, "MINUTA_NO_ENVIADA", "La minuta aún no se ha enviado")
    s = await secciones_de(db, m.id)
    if str(hallazgo.id) not in {h["hallazgo_id"] for h in s.get("hallazgos", [])}:
        raise ErrorAPI(404, "HALLAZGO_NO_EN_MINUTA", "El hallazgo no forma parte de esta minuta")
    if hallazgo.estado_respuesta == EstadoRespuestaHallazgo.respondido:
        raise ErrorAPI(409, "HALLAZGO_RESPONDIDO", f"El hallazgo ya fue respondido ({hallazgo.opcion_respuesta.value if hallazgo.opcion_respuesta else ''})")
    if hallazgo.un_id and actor.rol == Rol.admin_un and hallazgo.un_id not in (await _unidades_visibles(db, actor) or []):
        raise no_encontrado("Hallazgo")
    modulo, registro = await entradas.desde_hallazgo(db, actor, hallazgo, opcion, notas=notas, fecha_tentativa=fecha_tentativa, proveedor=proveedor,
                                                     trabajo_coordinado=trabajo_coordinado, variante=variante, request=request)
    ahora = datetime.now(UTC)
    hallazgo.estado_respuesta, hallazgo.opcion_respuesta, hallazgo.respondido_por, hallazgo.respondido_at = EstadoRespuestaHallazgo.respondido, opcion, actor.id, ahora
    es_folio = modulo is None and registro is not None
    hallazgo.modulo_destino, hallazgo.modulo_registro_id = modulo, (registro.id if registro is not None and not es_folio else None)
    r = MinutaRespuesta(minuta_id=m.id, tenant_id=m.tenant_id, prestador_id=m.prestador_id, hallazgo_id=hallazgo.id, opcion_elegida=opcion, usuario_id=actor.id, timestamp=ahora,
                        notas=notas or "", canal=canal, modulo_destino=modulo, modulo_registro_id=hallazgo.modulo_registro_id, folio_generado_id=registro.id if es_folio else None)
    db.add(r)
    await db.flush()
    # Refleja la respuesta en la sección guardada de la minuta (y en la global/UN hermana del mismo día).
    for sec in (await db.execute(select(MinutaSeccion).join(Minuta, Minuta.id == MinutaSeccion.minuta_id).where(
            Minuta.tenant_id == m.tenant_id, Minuta.fecha == m.fecha, MinutaSeccion.seccion == "hallazgos"))).scalars():
        items = sec.contenido_json.get("items", [])
        if any(h["hallazgo_id"] == str(hallazgo.id) for h in items):
            sec.contenido_json = {"items": [{**h, "estado_respuesta": "respondido", "opcion_respuesta": opcion.value} if h["hallazgo_id"] == str(hallazgo.id) else h for h in items]}
    await db.flush()
    await auditoria.registrar_actor(db, actor, "minuta.respuesta", request, tenant_id=m.tenant_id, prestador_id=m.prestador_id, recurso_tipo="minuta", recurso_id=m.id,
                                    despues={"hallazgo_id": hallazgo.id, "opcion": opcion.value, "canal": canal.value, "modulo_destino": modulo.value if modulo else None,
                                             "registro_id": registro.id if registro is not None else None})
    await entradas.notificar_entrada(db, modulo, registro, m.tenant_id, m.prestador_id, hallazgo.un_id, f"Hallazgo respondido: {OPCIONES[opcion]}")
    if modulo is None and registro is None:
        destinatarios = await notificaciones_service.destinatarios_por_rol(db, [Rol.despachador], prestador_id=m.prestador_id)
        await notificaciones_service.notificar(db, "hallazgo.respuesta", destinatarios, {"hallazgo_id": str(hallazgo.id), "opcion": opcion.value},
                                               asunto=f"Hallazgo: {OPCIONES[opcion]}", cuerpo=hallazgo.descripcion[:200], url=f"/minutas/{m.id}", tenant_id=m.tenant_id,
                                               prestador_id=m.prestador_id, canales=["app"])
    await _cerrar_si_completa(db, m)
    return r


async def _cerrar_si_completa(db: AsyncSession, m: Minuta) -> None:
    s = await secciones_de(db, m.id)
    ids = [UUID(h["hallazgo_id"]) for h in s.get("hallazgos", [])]
    pendientes = (await db.execute(select(func.count()).select_from(Hallazgo).where(Hallazgo.id.in_(ids), Hallazgo.estado_respuesta == EstadoRespuestaHallazgo.pendiente))).scalar() if ids else 0
    if pendientes == 0 and m.estado in (EstadoMinuta.enviada, EstadoMinuta.vencida):
        m.estado, m.respondida_at = EstadoMinuta.respondida, datetime.now(UTC)
        await db.flush()
        destinatarios = await notificaciones_service.destinatarios_por_rol(db, [Rol.despachador, Rol.admin_prestador], prestador_id=m.prestador_id)
        await notificaciones_service.notificar(db, "minuta.respondida", destinatarios, {"minuta_id": str(m.id)}, asunto=f"Minuta del {m.fecha.isoformat()} respondida",
                                               url=f"/minutas/{m.id}", tenant_id=m.tenant_id, prestador_id=m.prestador_id, canales=["app"])


# ---------------------------------------------------------------- consulta

async def alcance(db: AsyncSession, actor: Actor, consulta):
    if actor.es_superadmin:
        return consulta
    if actor.dominio == Dominio.tenant:
        consulta = consulta.where(Minuta.tenant_id == actor.tenant_id, Minuta.estado.in_((EstadoMinuta.enviada, EstadoMinuta.respondida, EstadoMinuta.vencida)))
        unidades = await _unidades_visibles(db, actor)
        if unidades is not None:
            consulta = consulta.where(or_(Minuta.un_id.in_(unidades), Minuta.un_id.is_(None)) if actor.rol != Rol.admin_un else Minuta.un_id.in_(unidades))
        return consulta
    return consulta.where(Minuta.prestador_id == actor.prestador_id)


async def listar(db: AsyncSession, actor: Actor, filtros: dict[str, Any]) -> list[Minuta]:
    if actor.rol not in CONSULTAN:
        raise prohibido("Tu rol no consulta minutas")
    consulta = await alcance(db, actor, select(Minuta).order_by(Minuta.fecha.desc(), Minuta.tipo, Minuta.created_at))
    for k in ("tenant_id", "un_id", "estado", "tipo"):
        if filtros.get(k):
            consulta = consulta.where(getattr(Minuta, k) == filtros[k])
    if filtros.get("desde"):
        consulta = consulta.where(Minuta.fecha >= filtros["desde"])
    if filtros.get("hasta"):
        consulta = consulta.where(Minuta.fecha <= filtros["hasta"])
    return list((await db.execute(consulta.limit(300))).scalars())


async def obtener(db: AsyncSession, actor: Actor, minuta_id: UUID) -> Minuta:
    if actor.rol not in CONSULTAN:
        raise prohibido("Tu rol no consulta minutas")
    m = (await db.execute(await alcance(db, actor, select(Minuta).where(Minuta.id == minuta_id)))).scalar_one_or_none()
    if m is None:
        raise no_encontrado("Minuta")
    return m


async def resumen(db: AsyncSession, lista: list[Minuta]) -> list[dict[str, Any]]:
    if not lista:
        return []
    unidades = {u.id: u for u in (await db.execute(select(UnidadNegocio).where(UnidadNegocio.id.in_({m.un_id for m in lista if m.un_id})))).scalars()} if any(m.un_id for m in lista) else {}
    tenants = {t.id: t for t in (await db.execute(select(Tenant).where(Tenant.id.in_({m.tenant_id for m in lista})))).scalars()}
    nombres = {u.id: u.nombre for u in (await db.execute(select(Usuario).where(Usuario.id.in_({m.validada_por for m in lista if m.validada_por})))).scalars()} if any(m.validada_por for m in lista) else {}
    conteos = {}
    for minuta_id, sec in (await db.execute(select(MinutaSeccion.minuta_id, MinutaSeccion).where(MinutaSeccion.minuta_id.in_([m.id for m in lista]), MinutaSeccion.seccion.in_(("hallazgos", "contadores"))))).all():
        conteos.setdefault(minuta_id, {})[sec.seccion] = sec.contenido_json
    salida = []
    for m in lista:
        un, t = unidades.get(m.un_id), tenants.get(m.tenant_id)
        h = conteos.get(m.id, {}).get("hallazgos", {}).get("items", [])
        c = conteos.get(m.id, {}).get("contadores", {})
        salida.append({**auditoria.instantanea(m), "id": m.id, "tenant_id": m.tenant_id, "prestador_id": m.prestador_id, "un_id": m.un_id, "validada_por": m.validada_por,
                       "timestamp_generacion": m.timestamp_generacion, "timestamp_envio": m.timestamp_envio, "vence_respuesta_at": m.vence_respuesta_at, "respondida_at": m.respondida_at,
                       "created_at": m.created_at, "updated_at": m.updated_at, "un_codigo": un.codigo if un else None, "un_nombre": un.nombre if un else None,
                       "tenant_nombre": t.razon_social if t else None, "validada_por_nombre": nombres.get(m.validada_por), "hallazgos": len(h),
                       "hallazgos_pendientes": sum(x.get("estado_respuesta") == "pendiente" for x in h), "colores": {k: v.get("color") for k, v in c.items()} if isinstance(c, dict) else {}})
    return salida


def _entrega(envio) -> dict[str, Any] | None:
    """Estado de entrega de un mensaje de WhatsApp o SMS, como lo cuenta la pantalla de la minuta (F2-02)."""
    if envio is None:
        return None
    return {"estado": envio.estado.value, "proveedor": envio.proveedor.value, "telefono": envio.telefono_mascara,
            "enviado_at": envio.enviado_at, "entregado_at": envio.entregado_at, "leido_at": envio.leido_at,
            "abierto_at": envio.abierto_at, "motivo": envio.detalle_error or envio.codigo_error}


async def detalle(db: AsyncSession, actor: Actor, m: Minuta) -> dict[str, Any]:
    from services import hallazgos_service

    base = (await resumen(db, [m]))[0]
    s = await secciones_de(db, m.id)
    ids = [UUID(h["hallazgo_id"]) for h in s.get("hallazgos", [])]
    hallazgos = list((await db.execute(select(Hallazgo).where(Hallazgo.id.in_(ids)))).scalars()) if ids else []
    respuestas = list((await db.execute(select(MinutaRespuesta).where(MinutaRespuesta.minuta_id == m.id).order_by(MinutaRespuesta.timestamp))).scalars())
    destinatarios = list((await db.execute(select(MinutaDestinatario).where(MinutaDestinatario.minuta_id == m.id))).scalars())
    nombres = {u.id: u.nombre for u in (await db.execute(select(Usuario).where(Usuario.id.in_({d.usuario_id for d in destinatarios} | {r.usuario_id for r in respuestas if r.usuario_id})))).scalars()} \
        if destinatarios or respuestas else {}
    # F2-02 (§7.5): para los canales de mensajeria, el estado real de la entrega lo informa el proveedor.
    from services import mensajeria_service

    mensajeria = await mensajeria_service.envios_de_notificaciones(
        db, [d.notificacion_id for d in destinatarios if d.notificacion_id])
    return {**base, "secciones": s, "hallazgos_detalle": await hallazgos_service.enriquecer(db, hallazgos),
            "respuestas": [{"id": r.id, "hallazgo_id": r.hallazgo_id, "opcion_elegida": r.opcion_elegida, "usuario_id": r.usuario_id, "usuario_nombre": nombres.get(r.usuario_id),
                            "timestamp": r.timestamp, "notas": r.notas, "canal": r.canal, "modulo_destino": r.modulo_destino, "modulo_registro_id": r.modulo_registro_id,
                            "folio_generado_id": r.folio_generado_id} for r in respuestas],
            "destinatarios": [{"usuario_id": d.usuario_id, "nombre": nombres.get(d.usuario_id), "canal": d.canal, "estado_entrega": d.estado_entrega, "timestamp": d.timestamp,
                               "entrega_mensajeria": _entrega(mensajeria.get(d.notificacion_id))} for d in destinatarios],
            "puede_validar": m.estado == EstadoMinuta.pendiente_validacion and actor.rol in VALIDAN, "puede_responder": await puede_responder(db, actor, m) and actor.rol in RESPONDEN,
            "opciones": [{"valor": o.value, "texto": t} for o, t in OPCIONES.items()], "pdf_disponible": m.pdf_key is not None}


# --------------------------------------------------------- tarea periódica

async def generar_pendientes(db: AsyncSession, ahora: datetime | None = None, forzar_hora: bool = False) -> dict[str, int]:
    """Por cada vínculo tenant-prestador activo: si ya pasó la hora de envío local y no hay minuta de hoy, la genera. También vence
    ventanas de validación y plazos de respuesta."""
    ahora = ahora or datetime.now(UTC)
    resumen_ = {"generadas": 0, "sin_actividad": 0, "ya_generadas": 0, "validaciones_vencidas": 0, "respuestas_vencidas": 0}
    vinculos = (await db.execute(select(TenantPrestador).where(TenantPrestador.estado == EstadoRegistro.activo))).scalars().all()
    for v in vinculos:
        tenant = await db.get(Tenant, v.tenant_id)
        zona = ZoneInfo(tenant.zona_horaria if tenant else "America/Mexico_City")
        local = ahora.astimezone(zona)
        cfg = await configuracion(db, v.prestador_id, v.tenant_id)
        if not forzar_hora and local.time() < cfg.hora_envio:
            continue
        hoy = local.date()
        existe = (await db.execute(select(Minuta.id).where(Minuta.tenant_id == v.tenant_id, Minuta.prestador_id == v.prestador_id, Minuta.fecha == hoy))).first()
        if existe:
            resumen_["ya_generadas"] += 1
            continue
        creadas = await generar(db, v.prestador_id, v.tenant_id, hoy)
        resumen_["generadas" if creadas else "sin_actividad"] += 1
    resumen_["validaciones_vencidas"] = await vencer_validaciones(db, ahora)
    resumen_["respuestas_vencidas"] = await vencer_respuestas(db, ahora)
    return resumen_
