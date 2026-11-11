"""Calendario de preventivos (§7.6), generación automática de folios preventivos desde planes y calendario manual,
ciclo de vida del preventivo con autorizaciones formales de reprogramación y cancelación (§6.9.1) y desvío en días."""
import calendar
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi import Request
from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from core.dependencias import Actor
from core.errors import ErrorAPI, no_encontrado, prohibido
from models.base import Dominio, EstadoRegistro, Rol
from models.catalogos import Equipo, NivelSeveridadCatalogo, TipoEquipo
from models.chat import CanalChat
from models.folios import EstadoFolio, Folio, FolioEstadoHistorial, SeveridadOrigen, TipoFolio
from models.organizaciones import TenantPrestador
from models.preventivos import (
    AutorizacionPreventivo, CalendarioPublicacion, EquipoPlan, EstadoAutorizacion, EstadoEjecucionPlan, EstadoPlan, EstadoPreventivo,
    OrigenPreventivo, PlanEjecucion, PlanMantenimiento, PlanTarea, PlanTrigger, PreventivoCalendario, TipoAutorizacionPreventivo,
)
from models.unidades import GrupoUNMiembro, UnidadNegocio, UsuarioGrupo, UsuarioUN
from models.usuarios import Usuario
from services import auditoria, chat_service, folio_estados, notificaciones, planes_service, push_service
from services.folio_estados import ACTOR_SISTEMA, ActorFolio
from services.formularios import servicio as formularios

CARGAN = {Rol.superadmin, Rol.admin_prestador, Rol.despachador, Rol.mesa_control}
CONSULTAN = CARGAN | {Rol.admin_empresa, Rol.admin_un, Rol.supervisor_operadores, Rol.supervisor_prestador, Rol.direccion_prestador, Rol.tecnico}
SOLICITAN = {Rol.superadmin, Rol.despachador, Rol.admin_prestador, Rol.mesa_control}
AUTORIZAN = {Rol.superadmin, Rol.admin_un, Rol.admin_empresa}
HORIZONTE_DIAS = 7


def texto_desvio(desvio: int | None) -> str:
    """Texto literal de §7.6 para la minuta."""
    if desvio is None:
        return "pendiente de ejecución"
    if desvio == 0:
        return "realizado en la fecha programada"
    n = abs(desvio)
    dias = "día" if n == 1 else "días"
    return f"realizado {n} {dias} antes de lo programado" if desvio < 0 else f"realizado con {n} {dias} de retraso"


def primer_dia(mes: str | date) -> date:
    if isinstance(mes, date):
        return mes.replace(day=1)
    anio, m = (int(x) for x in str(mes).split("-")[:2])
    return date(anio, m, 1)


def rango_mes(mes: date) -> tuple[date, date]:
    inicio = mes.replace(day=1)
    return inicio, inicio.replace(day=calendar.monthrange(inicio.year, inicio.month)[1])


# ------------------------------------------------------------ alcance

async def _unidades_visibles(db: AsyncSession, actor: Actor) -> list[UUID] | None:
    if actor.rol in (Rol.admin_un, Rol.operador):
        return list((await db.execute(select(UsuarioUN.unidad_id).where(UsuarioUN.usuario_id == actor.id))).scalars())
    if actor.rol == Rol.supervisor_operadores:
        por_grupo = select(GrupoUNMiembro.unidad_id).join(UsuarioGrupo, UsuarioGrupo.grupo_id == GrupoUNMiembro.grupo_id).where(UsuarioGrupo.usuario_id == actor.id)
        directas = select(UsuarioUN.unidad_id).where(UsuarioUN.usuario_id == actor.id)
        return list((await db.execute(select(UnidadNegocio.id).where(or_(UnidadNegocio.id.in_(por_grupo), UnidadNegocio.id.in_(directas))))).scalars())
    return None


async def _filtro_actor(db: AsyncSession, actor: Actor, consulta, modelo):
    if actor.dominio == Dominio.tenant:
        consulta = consulta.where(modelo.tenant_id == actor.tenant_id)
        unidades = await _unidades_visibles(db, actor)
        if unidades is not None and hasattr(modelo, "un_id"):
            consulta = consulta.where(modelo.un_id.in_(unidades))
    elif actor.dominio == Dominio.prestador:
        consulta = consulta.where(modelo.prestador_id == actor.prestador_id)
    return consulta


async def _prestador_de_tenant(db: AsyncSession, actor: Actor, tenant_id: UUID | None) -> tuple[UUID, UUID]:
    """(prestador_id, tenant_id) para una carga: el prestador del actor y un cliente vinculado."""
    if actor.dominio == Dominio.prestador:
        p = actor.prestador_id
    elif actor.es_superadmin:
        if tenant_id is None:
            raise ErrorAPI(422, "TENANT_REQUERIDO", "Indica tenant_id")
        p = (await db.execute(select(TenantPrestador.prestador_id).where(TenantPrestador.tenant_id == tenant_id, TenantPrestador.estado == EstadoRegistro.activo))).scalar()
        if p is None:
            raise ErrorAPI(422, "TENANT_NO_VINCULADO", "El cliente no tiene prestador vinculado")
    else:
        raise prohibido("Solo el prestador carga el calendario")
    if tenant_id is None:
        raise ErrorAPI(422, "TENANT_REQUERIDO", "Indica tenant_id")
    vinculado = (await db.execute(select(TenantPrestador.id).where(TenantPrestador.tenant_id == tenant_id, TenantPrestador.prestador_id == p,
                                                                   TenantPrestador.estado == EstadoRegistro.activo))).first()
    if vinculado is None:
        raise ErrorAPI(422, "TENANT_NO_VINCULADO", "El cliente no está vinculado a este prestador")
    return p, tenant_id


# ---------------------------------------------------------- calendario

async def crear_calendario(db: AsyncSession, actor: Actor, filas: list[dict[str, Any]], tenant_id: UUID | None, request: Request | None) -> list[PreventivoCalendario]:
    if actor.rol not in CARGAN:
        raise prohibido("Solo Despachador, Mesa de control y Admin prestador cargan el calendario")
    p, t = await _prestador_de_tenant(db, actor, tenant_id)
    creadas = []
    for f in filas:
        un = await db.get(UnidadNegocio, f["un_id"])
        if un is None or un.tenant_id != t:
            raise ErrorAPI(422, "UNIDAD_INVALIDA", "La unidad no existe o es de otro cliente")
        equipo = None
        if f.get("equipo_id"):
            equipo = await db.get(Equipo, f["equipo_id"])
            if equipo is None or equipo.un_id != un.id:
                raise ErrorAPI(422, "EQUIPO_INVALIDO", "El equipo no existe o no pertenece a la unidad")
        if f.get("tecnico_id"):
            tec = await db.get(Usuario, f["tecnico_id"])
            if tec is None or tec.rol != Rol.tecnico or tec.prestador_id != p:
                raise ErrorAPI(422, "TECNICO_INVALIDO", "El técnico no existe o es de otro prestador")
        plan = None
        if f.get("plan_id"):
            plan = await db.get(PlanMantenimiento, f["plan_id"])
            if plan is None or plan.prestador_id != p:
                raise ErrorAPI(422, "PLAN_INVALIDO", "El plan no existe o es de otro prestador")
        fila = PreventivoCalendario(prestador_id=p, tenant_id=t, un_id=un.id, equipo_id=equipo.id if equipo else None, plan_id=plan.id if plan else None,
                                    tecnico_id=f.get("tecnico_id"), fecha_programada=f["fecha_programada"], fecha_programada_original=f["fecha_programada"],
                                    origen=OrigenPreventivo.plan if plan else OrigenPreventivo.manual, descripcion=f.get("descripcion") or "", cargado_por=actor.id)
        db.add(fila)
        creadas.append(fila)
    await db.flush()
    await auditoria.registrar_actor(db, actor, "preventivos.calendario_carga", request, recurso_tipo="preventivos_calendario", recurso_id=t, tenant_id=t,
                                    prestador_id=p, despues={"filas": len(creadas), "fechas": sorted({str(c.fecha_programada) for c in creadas})})
    return creadas


async def listar_calendario(db: AsyncSession, actor: Actor, mes: str | None, tenant_id: UUID | None, un_id: UUID | None,
                            estado: EstadoPreventivo | None, desde: date | None = None, hasta: date | None = None) -> list[dict[str, Any]]:
    if actor.rol not in CONSULTAN:
        raise prohibido("Tu rol no consulta el calendario")
    consulta = select(PreventivoCalendario).order_by(PreventivoCalendario.fecha_programada, PreventivoCalendario.created_at)
    consulta = await _filtro_actor(db, actor, consulta, PreventivoCalendario)
    if mes:
        inicio, fin = rango_mes(primer_dia(mes))
        consulta = consulta.where(PreventivoCalendario.fecha_programada.between(inicio, fin))
    if desde:
        consulta = consulta.where(PreventivoCalendario.fecha_programada >= desde)
    if hasta:
        consulta = consulta.where(PreventivoCalendario.fecha_programada <= hasta)
    if tenant_id:
        consulta = consulta.where(PreventivoCalendario.tenant_id == tenant_id)
    if un_id:
        consulta = consulta.where(PreventivoCalendario.un_id == un_id)
    if estado:
        consulta = consulta.where(PreventivoCalendario.estado == estado)
    if actor.rol == Rol.tecnico:
        consulta = consulta.where(PreventivoCalendario.tecnico_id == actor.id)
    filas = (await db.execute(consulta)).scalars().all()
    return await enriquecer(db, filas)


async def enriquecer(db: AsyncSession, filas: list[PreventivoCalendario]) -> list[dict[str, Any]]:
    if not filas:
        return []
    unidades = {u.id: u for u in (await db.execute(select(UnidadNegocio).where(UnidadNegocio.id.in_({f.un_id for f in filas})))).scalars()}
    equipos = {e.id: e for e in (await db.execute(select(Equipo).where(Equipo.id.in_({f.equipo_id for f in filas if f.equipo_id})))).scalars()}
    planes = {p.id: p for p in (await db.execute(select(PlanMantenimiento).where(PlanMantenimiento.id.in_({f.plan_id for f in filas if f.plan_id})))).scalars()}
    usuarios = {u.id: u for u in (await db.execute(select(Usuario).where(Usuario.id.in_({f.tecnico_id for f in filas if f.tecnico_id})))).scalars()}
    folios = {f.id: f for f in (await db.execute(select(Folio).where(Folio.id.in_({x.folio_id for x in filas if x.folio_id})))).scalars()}
    salida = []
    for f in filas:
        un, eq, plan, tec, folio = unidades.get(f.un_id), equipos.get(f.equipo_id), planes.get(f.plan_id), usuarios.get(f.tecnico_id), folios.get(f.folio_id)
        salida.append({
            **{k: getattr(f, k) for k in ("id", "created_at", "updated_at", "version_hash", "prestador_id", "tenant_id", "un_id", "equipo_id", "plan_id", "tecnico_id",
                                          "fecha_programada", "fecha_programada_original", "fecha_real", "desvio_dias", "estado", "folio_id", "formulario_id",
                                          "origen", "descripcion", "cargado_por", "reprogramado_desde_id",
                                          "plan_trigger_id", "valor_medidor")},
            "un_codigo": un.codigo if un else None, "un_nombre": un.nombre if un else None, "equipo_codigo": eq.codigo if eq else None,
            "equipo_nombre": eq.nombre if eq else None, "plan_nombre": plan.nombre if plan else None, "tecnico_nombre": tec.nombre if tec else None,
            "numero_folio": folio.numero_folio if folio else None, "estado_folio": folio.estado if folio else None, "texto_desvio": texto_desvio(f.desvio_dias),
        })
    return salida


async def editar_calendario(db: AsyncSession, actor: Actor, fila: PreventivoCalendario, cambios: dict[str, Any], request: Request | None) -> PreventivoCalendario:
    if actor.rol not in CARGAN:
        raise prohibido("Solo el prestador edita el calendario")
    if actor.dominio == Dominio.prestador and fila.prestador_id != actor.prestador_id:
        raise no_encontrado("Preventivo")
    if fila.folio_id is not None and "fecha_programada" in cambios:
        raise ErrorAPI(409, "REQUIERE_AUTORIZACION", "Con folio generado, la fecha solo cambia con una reprogramación autorizada")
    antes = auditoria.instantanea(fila)
    for k in ("tecnico_id", "equipo_id", "descripcion", "fecha_programada"):
        if k in cambios:
            setattr(fila, k, cambios[k])
    await db.flush()
    await auditoria.registrar_actor(db, actor, "preventivos.calendario_edicion", request, recurso_tipo="preventivos_calendario", recurso_id=fila.id,
                                    tenant_id=fila.tenant_id, prestador_id=fila.prestador_id, antes=antes, despues=auditoria.instantanea(fila))
    return fila


async def publicar_mes(db: AsyncSession, actor: Actor, mes: str, tenant_id: UUID | None, request: Request | None) -> CalendarioPublicacion:
    """§7.6: al cerrar el mes, ACMA envía el calendario al Admin empresa y a cada Admin UN. Emite `calendario.publicado`
    (push + log aquí; correo en P07)."""
    if actor.rol not in CARGAN:
        raise prohibido("Solo el prestador publica el calendario")
    p, t = await _prestador_de_tenant(db, actor, tenant_id)
    inicio, fin = rango_mes(primer_dia(mes))
    total = (await db.execute(select(func.count()).select_from(PreventivoCalendario).where(
        PreventivoCalendario.prestador_id == p, PreventivoCalendario.tenant_id == t, PreventivoCalendario.fecha_programada.between(inicio, fin)))).scalar() or 0
    if not total:
        raise ErrorAPI(409, "MES_VACIO", f"No hay preventivos cargados para {inicio.strftime('%m/%Y')}")
    pub = (await db.execute(select(CalendarioPublicacion).where(CalendarioPublicacion.prestador_id == p, CalendarioPublicacion.tenant_id == t,
                                                                CalendarioPublicacion.mes == inicio))).scalar_one_or_none()
    if pub is None:
        pub = CalendarioPublicacion(prestador_id=p, tenant_id=t, mes=inicio)
        db.add(pub)
    pub.publicado_por, pub.publicado_at, pub.total_preventivos = actor.id, datetime.now(UTC), total
    await db.flush()
    destinatarios = list((await db.execute(select(Usuario.id).where(Usuario.tenant_id == t, Usuario.rol.in_([Rol.admin_empresa, Rol.admin_un]),
                                                                    Usuario.estado == EstadoRegistro.activo))).scalars())
    titulo = f"Calendario de preventivos de {inicio.strftime('%m/%Y')} publicado"
    from services import notificaciones_service

    await notificaciones_service.notificar(db, "calendario.publicado", destinatarios, {"mes": inicio.isoformat(), "tenant_id": str(t), "total": total}, asunto=titulo,
                                           cuerpo=f"{total} preventivo(s) programados para {inicio.strftime('%m/%Y')}.", url="/preventivos/calendario", tenant_id=t, prestador_id=p,
                                           canales=["app", "push", "email"])
    # Compatibilidad con la bitácora de P06 (roles explícitos).
    notificaciones.enviar(roles=["admin_empresa", "admin_un"], usuarios=destinatarios, tenant_id=t, prestador_id=p, titulo=titulo,
                          cuerpo=f"{total} preventivo(s) programados", datos={"evento": "calendario.publicado", "mes": inicio.isoformat(), "tenant_id": str(t)},
                          canales=["push", "email"])
    await auditoria.registrar_actor(db, actor, "preventivos.calendario_publicado", request, recurso_tipo="calendario_publicacion", recurso_id=pub.id,
                                    tenant_id=t, prestador_id=p, despues={"mes": inicio.isoformat(), "total": total, "destinatarios": len(destinatarios)})
    return pub


async def publicaciones(db: AsyncSession, actor: Actor, tenant_id: UUID | None) -> list[CalendarioPublicacion]:
    consulta = select(CalendarioPublicacion).order_by(CalendarioPublicacion.mes.desc())
    consulta = await _filtro_actor(db, actor, consulta, CalendarioPublicacion)
    if tenant_id:
        consulta = consulta.where(CalendarioPublicacion.tenant_id == tenant_id)
    return list((await db.execute(consulta)).scalars())


# -------------------------------------------------- generación de folios

def _actor_prestador(prestador_id: UUID, usuario_id: UUID) -> Actor:
    """Actor sintético del prestador para resolver formularios (P03) en tareas de sistema."""
    return Actor(id=usuario_id, email="sistema@acma", nombre="sistema", rol=Rol.admin_prestador, dominio=Dominio.prestador, tenant_id=None,
                 prestador_id=prestador_id, sesion_id=None)


def _actor_de_usuario(u: Usuario) -> Actor:
    from models.base import dominio_de_rol

    return Actor(id=u.id, email=u.email, nombre=u.nombre, rol=u.rol, dominio=dominio_de_rol(u.rol), tenant_id=u.tenant_id, prestador_id=u.prestador_id, sesion_id=None)


async def _usuario_capturador(db: AsyncSession, prestador_id: UUID, preferido: UUID | None) -> UUID:
    if preferido:
        return preferido
    u = (await db.execute(select(Usuario.id).where(Usuario.prestador_id == prestador_id, Usuario.rol.in_([Rol.admin_prestador, Rol.despachador]),
                                                   Usuario.estado == EstadoRegistro.activo).order_by(Usuario.created_at))).scalar()
    if u is None:
        raise ErrorAPI(422, "SIN_USUARIO_PRESTADOR", "El prestador no tiene administrador ni despachador activo")
    return u


async def _severidad_preventivo(db: AsyncSession, prestador_id: UUID, plan: PlanMantenimiento | None) -> UUID | None:
    if plan and plan.nivel_severidad_id:
        return plan.nivel_severidad_id
    return (await db.execute(select(NivelSeveridadCatalogo.id).where(NivelSeveridadCatalogo.prestador_id == prestador_id, NivelSeveridadCatalogo.activo.is_(True))
                             .order_by(NivelSeveridadCatalogo.orden))).scalar()


async def _resolver_formulario(db: AsyncSession, prestador_id: UUID, capturador: UUID, tenant_id: UUID, equipo: Equipo, plan: PlanMantenimiento | None) -> UUID | None:
    if plan and plan.formulario_id:
        return plan.formulario_id
    tipo = await db.get(TipoEquipo, equipo.tipo_equipo_id)
    r = await formularios.resolver(db, _actor_prestador(prestador_id, capturador), "preventivo", tenant_id, equipo.tipo_equipo_id,
                                   tipo.familia_id if tipo else None, plan.id if plan else None, prestador_id, "preventivo")
    return r[0].id if r else None


async def generar_folio_preventivo(db: AsyncSession, cal: PreventivoCalendario, plan: PlanMantenimiento | None, hoy: date) -> Folio:
    """§6.9.1: en la fecha programada el sistema genera el folio preventivo y pasa directo a Autorizado."""
    if cal.equipo_id is None:
        raise ErrorAPI(422, "EQUIPO_REQUERIDO", "El preventivo de UN completa necesita un equipo para generar el folio")
    equipo = await db.get(Equipo, cal.equipo_id)
    capturador = await _usuario_capturador(db, cal.prestador_id, cal.cargado_por or (plan.created_by if plan else None))
    numero = (await db.execute(text("SELECT acma_siguiente_numero_folio(:t)"), {"t": cal.tenant_id})).scalar_one()
    descripcion = cal.descripcion or (f"Mantenimiento preventivo: {plan.nombre}" if plan else "Mantenimiento preventivo programado")
    cal.formulario_id = cal.formulario_id or await _resolver_formulario(db, cal.prestador_id, capturador, cal.tenant_id, equipo, plan)
    ahora = datetime.now(UTC)
    folio = Folio(numero_folio=numero, tenant_id=cal.tenant_id, prestador_id=cal.prestador_id, un_id=cal.un_id, equipo_id=equipo.id, tipo_falla_id=None,
                  tipo_folio=TipoFolio.preventivo, descripcion=descripcion, confirmacion_un=True, confirmacion_un_timestamp=ahora,
                  severidad_id=await _severidad_preventivo(db, cal.prestador_id, plan), severidad_origen=SeveridadOrigen.automatica_matriz,
                  capturado_por=capturador, capturado_at=ahora, fecha_falla=datetime.combine(cal.fecha_programada, datetime.min.time(), tzinfo=UTC),
                  plan_id=plan.id if plan else None, calendario_id=cal.id, tecnico_id=None)
    db.add(folio)
    await db.flush()
    await folio_estados.registrar_historial(db, folio, ACTOR_SISTEMA, estado_anterior=None, estado_nuevo=EstadoFolio.capturado,
                                            notas="Folio preventivo generado por el sistema", contexto={"calendario_id": str(cal.id), "plan_id": str(plan.id) if plan else None,
                                                                                                        "fecha_programada": cal.fecha_programada.isoformat(), "origen": cal.origen.value})
    await auditoria.registrar(db, "folio.preventivo_generado", actor_rol="sistema", tenant_id=folio.tenant_id, prestador_id=folio.prestador_id, recurso_tipo="folio",
                              recurso_id=folio.id, despues={"numero_folio": numero, "calendario_id": cal.id, "plan_id": plan.id if plan else None})
    await folio_estados.notificar_creacion(db, folio, ACTOR_SISTEMA)
    await folio_estados.transicionar(db, folio, EstadoFolio.autorizado, ACTOR_SISTEMA, "Preventivo autorizado al configurar el plan/calendario (§6.9.1)",
                                     {"calendario_id": str(cal.id)})
    cal.folio_id, cal.estado = folio.id, EstadoPreventivo.generado
    if cal.tecnico_id:
        # Técnico ya programado en el calendario: queda sugerido; la asignación formal la hace el despachador.
        await folio_estados.comentar(db, folio, ACTOR_SISTEMA, "Técnico sugerido por el calendario", {"tecnico_id": str(cal.tecnico_id)}, evento="preventivo.tecnico_sugerido")
    await db.flush()
    return folio


async def generar_programados(db: AsyncSession, hoy: date | None = None, horizonte_dias: int = HORIZONTE_DIAS) -> dict[str, int]:
    """Tarea nocturna: planes con `fecha_proxima_ejecucion` dentro del horizonte y calendario manual con fecha dentro del
    horizonte sin folio. Idempotente: no duplica si corre dos veces."""
    hoy = hoy or date.today()
    limite = hoy + timedelta(days=horizonte_dias)
    resumen = {"planes": 0, "manuales": 0, "omitidos": 0, "errores": 0}
    asignaciones = (await db.execute(select(EquipoPlan, PlanMantenimiento).join(PlanMantenimiento, PlanMantenimiento.id == EquipoPlan.plan_id).where(
        EquipoPlan.activo.is_(True), PlanMantenimiento.estado == EstadoPlan.activo, EquipoPlan.fecha_proxima_ejecucion.is_not(None),
        EquipoPlan.fecha_proxima_ejecucion <= limite))).all()
    for ep, plan in asignaciones:
        fecha = ep.fecha_proxima_ejecucion
        ya = (await db.execute(select(PlanEjecucion.id).where(PlanEjecucion.plan_id == plan.id, PlanEjecucion.equipo_id == ep.equipo_id,
                                                              PlanEjecucion.fecha_programada == fecha))).first()
        if ya:
            resumen["omitidos"] += 1
            continue
        # F2-04: mientras siga abierto el preventivo anterior de este plan en este equipo, no nace otro. Con
        # triggers por medidor la fecha próxima se reproyecta todos los días, así que sin este candado un plan
        # podía generar un folio diario.
        from services import triggers_service

        if await triggers_service._folio_abierto(db, plan.id, ep.equipo_id) is not None:
            resumen["omitidos"] += 1
            continue
        equipo = await db.get(Equipo, ep.equipo_id)
        try:
            punto = await db.begin_nested()
            # F2-04: el origen lo decide el trigger que explica esa fecha, para que el calendario diga «por
            # medidor» o «por evento» en lugar de etiquetar todo como «plan» (§6.9.1).
            from services import triggers_service

            origen, trigger, valor = await triggers_service.origen_y_trigger(db, plan, ep, equipo, hoy)
            cal = PreventivoCalendario(prestador_id=plan.prestador_id, tenant_id=ep.tenant_id, un_id=equipo.un_id, equipo_id=equipo.id, plan_id=plan.id,
                                       fecha_programada=fecha, fecha_programada_original=fecha, origen=origen, descripcion=f"Mantenimiento preventivo: {plan.nombre}",
                                       cargado_por=plan.created_by, plan_trigger_id=trigger.id if trigger else None, valor_medidor=valor)
            db.add(cal)
            await db.flush()
            folio = await generar_folio_preventivo(db, cal, plan, hoy)
            db.add(PlanEjecucion(plan_id=plan.id, prestador_id=plan.prestador_id, tenant_id=ep.tenant_id, equipo_id=equipo.id, folio_id=folio.id, calendario_id=cal.id,
                                 formulario_id=cal.formulario_id, fecha_programada=fecha, estado=EstadoEjecucionPlan.generada,
                                 plan_trigger_id=trigger.id if trigger else None, valor_medidor=valor))
            triggers = (await db.execute(select(PlanTrigger).where(PlanTrigger.plan_id == plan.id))).scalars().all()
            ep.fecha_proxima_ejecucion = planes_service.proxima_fecha_plan(triggers, fecha, hoy)
            await db.flush()
            await punto.commit()
            resumen["planes"] += 1
        except Exception:  # noqa: BLE001 — un equipo con error no detiene la generación del resto
            await punto.rollback()
            resumen["errores"] += 1
    manuales = (await db.execute(select(PreventivoCalendario).where(
        PreventivoCalendario.origen == OrigenPreventivo.manual, PreventivoCalendario.estado == EstadoPreventivo.programado,
        PreventivoCalendario.folio_id.is_(None), PreventivoCalendario.fecha_programada <= limite))).scalars().all()
    for cal in manuales:
        if cal.equipo_id is None:
            resumen["omitidos"] += 1
            continue
        try:
            punto = await db.begin_nested()
            plan = await db.get(PlanMantenimiento, cal.plan_id) if cal.plan_id else None
            await generar_folio_preventivo(db, cal, plan, hoy)
            await punto.commit()
            resumen["manuales"] += 1
        except Exception:  # noqa: BLE001
            await punto.rollback()
            resumen["errores"] += 1
    await db.flush()
    return resumen


# ----------------------------------------------------- ciclo de vida

async def _folio_preventivo(db: AsyncSession, folio: Folio) -> PreventivoCalendario | None:
    if folio.tipo_folio != TipoFolio.preventivo:
        raise ErrorAPI(409, "NO_ES_PREVENTIVO", "El folio no es preventivo")
    return await db.get(PreventivoCalendario, folio.calendario_id) if folio.calendario_id else None


async def solicitar(db: AsyncSession, actor: Actor, folio: Folio, tipo: TipoAutorizacionPreventivo, razon: str, fecha_nueva: date | None,
                    request: Request | None) -> AutorizacionPreventivo:
    if actor.rol not in SOLICITAN:
        raise prohibido("Solo el Despachador (o Admin prestador / Mesa de control) solicita reprogramación o cancelación")
    cal = await _folio_preventivo(db, folio)
    if folio.estado in (EstadoFolio.cerrado, EstadoFolio.cancelado):
        raise ErrorAPI(409, "FOLIO_FINAL", "El folio ya está cerrado o cancelado")
    if tipo == TipoAutorizacionPreventivo.reprogramacion and fecha_nueva is None:
        raise ErrorAPI(422, "FECHA_REQUERIDA", "La reprogramación requiere fecha nueva")
    pendiente = (await db.execute(select(AutorizacionPreventivo.id).where(AutorizacionPreventivo.folio_id == folio.id,
                                                                          AutorizacionPreventivo.estado == EstadoAutorizacion.pendiente))).first()
    if pendiente:
        raise ErrorAPI(409, "SOLICITUD_PENDIENTE", "Ya hay una solicitud pendiente de autorización para este folio")
    a = AutorizacionPreventivo(folio_id=folio.id, prestador_id=folio.prestador_id, tenant_id=folio.tenant_id, calendario_id=cal.id if cal else None, tipo=tipo,
                               solicitado_por=actor.id, razon=razon.strip(), fecha_nueva=fecha_nueva, fecha_solicitud=datetime.now(UTC))
    db.add(a)
    await db.flush()
    texto = (f"Solicitud de reprogramación al {fecha_nueva.isoformat()}: {razon}" if tipo == TipoAutorizacionPreventivo.reprogramacion
             else f"Solicitud de cancelación: {razon}")
    await folio_estados.comentar(db, folio, actor, texto, {"autorizacion_id": str(a.id), "tipo": tipo.value, "fecha_nueva": fecha_nueva.isoformat() if fecha_nueva else None},
                                 evento=f"preventivo.solicitud_{tipo.value}")
    chats = await chat_service.chats_del_folio(db, folio.id)
    if CanalChat.operativo in chats:
        await chat_service.evento_sistema(db, chats[CanalChat.operativo], f"preventivo.solicitud_{tipo.value}", texto, {"autorizacion_id": str(a.id)})
    destinatarios = await _autorizadores(db, folio)
    from services import notificaciones_service

    await notificaciones_service.notificar(db, "autorizacion.solicitada", destinatarios, {"autorizacion_id": str(a.id), "folio_id": str(folio.id)},
                                           asunto=f"Preventivo {folio.numero_folio}: autorización pendiente", cuerpo=texto, url="/preventivos/autorizaciones",
                                           tenant_id=folio.tenant_id, prestador_id=folio.prestador_id)
    await auditoria.registrar_actor(db, actor, f"preventivos.solicitud_{tipo.value}", request, recurso_tipo="folio", recurso_id=folio.id, tenant_id=folio.tenant_id,
                                    prestador_id=folio.prestador_id, despues={"autorizacion_id": a.id, "razon": razon, "fecha_nueva": fecha_nueva})
    return a


async def _autorizadores(db: AsyncSession, folio: Folio) -> list[UUID]:
    admins_un = (await db.execute(select(Usuario.id).join(UsuarioUN, UsuarioUN.usuario_id == Usuario.id).where(
        UsuarioUN.unidad_id == folio.un_id, Usuario.rol == Rol.admin_un, Usuario.estado == EstadoRegistro.activo))).scalars().all()
    admins_emp = (await db.execute(select(Usuario.id).where(Usuario.tenant_id == folio.tenant_id, Usuario.rol == Rol.admin_empresa,
                                                            Usuario.estado == EstadoRegistro.activo))).scalars().all()
    return list({*admins_un, *admins_emp})


async def puede_autorizar(db: AsyncSession, actor: Actor, folio: Folio) -> bool:
    if actor.es_superadmin:
        return True
    if actor.tenant_id != folio.tenant_id:
        return False
    if actor.rol == Rol.admin_empresa:
        return True
    if actor.rol == Rol.admin_un:
        return (await db.execute(select(UsuarioUN.id).where(UsuarioUN.usuario_id == actor.id, UsuarioUN.unidad_id == folio.un_id))).first() is not None
    return False


async def resolver(db: AsyncSession, actor: Actor, a: AutorizacionPreventivo, autorizar: bool, notas: str, canal, request: Request | None) -> AutorizacionPreventivo:
    folio = await db.get(Folio, a.folio_id)
    if not await puede_autorizar(db, actor, folio):
        raise prohibido("Solo el Admin UN de la unidad o el Admin empresa autorizan")
    if a.estado != EstadoAutorizacion.pendiente:
        raise ErrorAPI(409, "SOLICITUD_RESUELTA", "La solicitud ya fue resuelta")
    a.autorizado_por, a.fecha_autorizacion, a.notas_respuesta, a.canal = actor.id, datetime.now(UTC), notas or "", canal
    a.estado = EstadoAutorizacion.autorizada if autorizar else EstadoAutorizacion.rechazada
    await db.flush()
    evento = f"preventivos.{a.tipo.value}_{'autorizada' if autorizar else 'rechazada'}"
    await auditoria.registrar_actor(db, actor, evento, request, recurso_tipo="folio", recurso_id=folio.id, tenant_id=folio.tenant_id, prestador_id=folio.prestador_id,
                                    despues={"autorizacion_id": a.id, "canal": canal.value, "notas": notas})
    chats = await chat_service.chats_del_folio(db, folio.id)
    if not autorizar:
        await folio_estados.comentar(db, folio, actor, f"Solicitud de {a.tipo.value} rechazada: {notas}", {"autorizacion_id": str(a.id)}, evento=f"preventivo.{a.tipo.value}_rechazada")
        if CanalChat.operativo in chats:
            await chat_service.evento_sistema(db, chats[CanalChat.operativo], f"preventivo.{a.tipo.value}_rechazada", f"{actor.nombre} rechazó la {a.tipo.value}", {})
        return a
    cal = await db.get(PreventivoCalendario, a.calendario_id) if a.calendario_id else None
    solicitante = await db.get(Usuario, a.solicitado_por)
    if a.tipo == TipoAutorizacionPreventivo.cancelacion:
        # §6.8.6 no deja cancelar al rol sistema desde asignado/en camino: la cancelación la ejecuta quien la solicitó
        # (Despachador / Admin prestador) con la autorización en el contexto; Mesa de control la ejecuta como el prestador.
        ejecutor = _actor_de_usuario(solicitante) if solicitante else _actor_prestador(folio.prestador_id, a.solicitado_por)
        if not folio_estados.puede(ejecutor, folio.estado, EstadoFolio.cancelado):
            ejecutor = _actor_prestador(folio.prestador_id, a.solicitado_por)
        razon = f"Cancelación autorizada por {actor.nombre}: {a.razon}"
        await folio_estados.transicionar(db, folio, EstadoFolio.cancelado, ejecutor, razon, {"razon_cancelacion": razon, "autorizacion_id": str(a.id)}, request)
        if cal:
            cal.estado = EstadoPreventivo.cancelado
        for pe in (await db.execute(select(PlanEjecucion).where(PlanEjecucion.folio_id == folio.id))).scalars():
            pe.estado = EstadoEjecucionPlan.cancelada
    else:
        if cal is not None:
            nueva = PreventivoCalendario(prestador_id=cal.prestador_id, tenant_id=cal.tenant_id, un_id=cal.un_id, equipo_id=cal.equipo_id, plan_id=cal.plan_id,
                                         tecnico_id=cal.tecnico_id, fecha_programada=a.fecha_nueva, fecha_programada_original=cal.fecha_programada_original or cal.fecha_programada,
                                         estado=EstadoPreventivo.generado, folio_id=folio.id, formulario_id=cal.formulario_id, origen=cal.origen, descripcion=cal.descripcion,
                                         cargado_por=cal.cargado_por, reprogramado_desde_id=cal.id)
            db.add(nueva)
            cal.estado, cal.folio_id = EstadoPreventivo.reprogramado, cal.folio_id  # el histórico conserva el folio
            await db.flush()
            folio.calendario_id = nueva.id
            for pe in (await db.execute(select(PlanEjecucion).where(PlanEjecucion.folio_id == folio.id))).scalars():
                pe.fecha_programada, pe.calendario_id = a.fecha_nueva, nueva.id
        folio.fecha_falla = datetime.combine(a.fecha_nueva, datetime.min.time(), tzinfo=UTC)
        await db.flush()
        await folio_estados.comentar(db, folio, actor, f"Reprogramado al {a.fecha_nueva.isoformat()} con autorización de {actor.nombre}",
                                     {"autorizacion_id": str(a.id), "fecha_nueva": a.fecha_nueva.isoformat()}, evento="preventivo.reprogramado")
        if CanalChat.operativo in chats:
            await chat_service.evento_sistema(db, chats[CanalChat.operativo], "preventivo.reprogramado", f"Preventivo reprogramado al {a.fecha_nueva.isoformat()}", {"autorizacion_id": str(a.id)})
    if solicitante:
        await push_service.enviar_a_usuarios(db, [solicitante.id], f"Folio {folio.numero_folio}: {a.tipo.value} autorizada", a.razon, {"url": f"/folios/{folio.id}"})
    return a


async def autorizaciones_de(db: AsyncSession, actor: Actor, folio_id: UUID | None, estado: EstadoAutorizacion | None) -> list[dict[str, Any]]:
    consulta = select(AutorizacionPreventivo).order_by(AutorizacionPreventivo.fecha_solicitud.desc())
    if actor.dominio == Dominio.tenant:
        consulta = consulta.where(AutorizacionPreventivo.tenant_id == actor.tenant_id)
        if actor.rol == Rol.admin_un:
            consulta = consulta.join(Folio, Folio.id == AutorizacionPreventivo.folio_id).where(
                Folio.un_id.in_(select(UsuarioUN.unidad_id).where(UsuarioUN.usuario_id == actor.id)))
        elif actor.rol not in (Rol.admin_empresa,):
            raise prohibido("Tu rol no consulta autorizaciones")
    elif actor.dominio == Dominio.prestador:
        consulta = consulta.where(AutorizacionPreventivo.prestador_id == actor.prestador_id)
    if folio_id:
        consulta = consulta.where(AutorizacionPreventivo.folio_id == folio_id)
    if estado:
        consulta = consulta.where(AutorizacionPreventivo.estado == estado)
    filas = (await db.execute(consulta)).scalars().all()
    if not filas:
        return []
    folios = {f.id: f for f in (await db.execute(select(Folio).where(Folio.id.in_({a.folio_id for a in filas})))).scalars()}
    usuarios = {u.id: u.nombre for u in (await db.execute(select(Usuario).where(Usuario.id.in_({a.solicitado_por for a in filas} | {a.autorizado_por for a in filas if a.autorizado_por})))).scalars()}
    return [{**{k: getattr(a, k) for k in ("id", "folio_id", "tenant_id", "prestador_id", "calendario_id", "tipo", "solicitado_por", "autorizado_por", "fecha_solicitud",
                                           "fecha_autorizacion", "razon", "fecha_nueva", "estado", "canal", "notas_respuesta")},
             "numero_folio": folios[a.folio_id].numero_folio if a.folio_id in folios else None, "estado_folio": folios[a.folio_id].estado if a.folio_id in folios else None,
             "fecha_programada": folios[a.folio_id].fecha_falla.date() if a.folio_id in folios else None,
             "solicitado_por_nombre": usuarios.get(a.solicitado_por), "autorizado_por_nombre": usuarios.get(a.autorizado_por),
             "puede_resolver": a.estado == EstadoAutorizacion.pendiente and a.folio_id in folios and await puede_autorizar(db, actor, folios[a.folio_id])} for a in filas]


# ----------------------------------------------------- ganchos del motor

@folio_estados.suscribir_validacion
async def _cancelacion_requiere_autorizacion(db: AsyncSession, folio: Folio, nuevo: EstadoFolio, actor: ActorFolio, contexto: dict) -> None:
    """§6.9.1: el Despachador no puede cancelar un preventivo sin la autorización formal del Admin UN o Admin empresa."""
    if folio.tipo_folio != TipoFolio.preventivo or nuevo != EstadoFolio.cancelado or actor is ACTOR_SISTEMA or getattr(actor, "es_superadmin", False):
        return
    if getattr(actor, "rol", None) in (Rol.admin_empresa, Rol.admin_un):
        return  # quien autoriza puede cancelar directamente
    if contexto.get("autorizacion_id"):
        return
    raise ErrorAPI(409, "REQUIERE_AUTORIZACION", "Cancelar un preventivo exige la autorización formal del Admin UN o Admin empresa: usa solicitar-cancelacion")


@folio_estados.suscribir
async def _al_cerrar_preventivo(db: AsyncSession, folio: Folio, _anterior, nuevo: EstadoFolio, actor, contexto) -> None:
    """Al cerrar: fecha real, desvío en días (§7.6) y próxima fecha del plan desde la última ejecución.

    F2-04: antes de recalcular se mueve el último PM del medidor (`triggers_service.al_cerrar`), porque la próxima
    fecha de un plan por intervalo se cuenta desde ahí. Ejecutar el plan reinicia **todos** sus triggers, incluidos
    los de un combinado, que es lo que pide §6.9.1."""
    if nuevo != EstadoFolio.cerrado or folio.tipo_folio != TipoFolio.preventivo:
        return
    from services import triggers_service

    await triggers_service.al_cerrar(db, folio)
    fecha_real = (folio.fecha_cierre or datetime.now(UTC)).date()
    cal = await db.get(PreventivoCalendario, folio.calendario_id) if folio.calendario_id else None
    if cal is not None:
        cal.fecha_real, cal.desvio_dias, cal.estado = fecha_real, (fecha_real - cal.fecha_programada).days, EstadoPreventivo.ejecutado
    for pe in (await db.execute(select(PlanEjecucion).where(PlanEjecucion.folio_id == folio.id))).scalars():
        pe.fecha_real, pe.desvio_dias, pe.estado = fecha_real, (fecha_real - pe.fecha_programada).days, EstadoEjecucionPlan.ejecutada
        ep = (await db.execute(select(EquipoPlan).where(EquipoPlan.plan_id == pe.plan_id, EquipoPlan.equipo_id == pe.equipo_id))).scalar_one_or_none()
        if ep is not None:
            ep.fecha_ultima_ejecucion = fecha_real
            triggers = (await db.execute(select(PlanTrigger).where(PlanTrigger.plan_id == pe.plan_id))).scalars().all()
            ep.fecha_proxima_ejecucion = planes_service.proxima_fecha_plan(triggers, fecha_real)
            equipo = await db.get(Equipo, pe.equipo_id)
            plan = await db.get(PlanMantenimiento, pe.plan_id)
            if equipo is not None and plan is not None and {t.tipo_trigger for t in triggers} - set(planes_service.TRIGGERS_POR_FECHA):
                await triggers_service._proyectar_asignacion(db, plan, ep, equipo, list(triggers), fecha_real)
    await db.flush()


@folio_estados.suscribir
async def _eventos_de_trigger(db: AsyncSession, folio: Folio, _anterior, nuevo: EstadoFolio, actor, contexto) -> None:
    """§6.9.1 «Por evento»: el cierre de un correctivo es lo que escuchan `falla_correctiva_grave`,
    `fallas_repetidas` y `reemplazo_componente`. Se usa el gancho de `transicionar()` que ya existe (P04), no un
    sondeo."""
    if nuevo != EstadoFolio.cerrado or folio.tipo_folio == TipoFolio.preventivo or folio.equipo_id is None:
        return
    from services import triggers_service

    for clave in ("falla_correctiva_grave", "fallas_repetidas", "reemplazo_componente"):
        await triggers_service.evaluar_evento(db, clave, equipo_id=folio.equipo_id,
                                              datos={"folio_id": str(folio.id), "numero_folio": folio.numero_folio})


async def tareas_y_materiales(db: AsyncSession, folio: Folio) -> dict[str, Any]:
    """Para la app del técnico: lista de verificación del plan y materiales estándar."""
    if not folio.plan_id:
        return {"tareas": [], "materiales": []}
    from models.preventivos import PlanMaterial

    tareas = (await db.execute(select(PlanTarea).where(PlanTarea.plan_id == folio.plan_id).order_by(PlanTarea.orden))).scalars().all()
    materiales = (await db.execute(select(PlanMaterial).where(PlanMaterial.plan_id == folio.plan_id))).scalars().all()
    return {"tareas": [{"id": t.id, "orden": t.orden, "descripcion": t.descripcion, "tiempo_estimado_min": t.tiempo_estimado_min, "habilidad_requerida_id": t.habilidad_requerida_id} for t in tareas],
            "materiales": [{"id": m.id, "descripcion": m.descripcion, "cantidad_estandar": m.cantidad_estandar, "unidad": m.unidad, "articulo_id": m.articulo_id} for m in materiales]}
