"""Trabajos especiales (§6.10.6 y §7.9): creación por el prestador o de urgencia por el cliente, validación del cliente por
botón, programación con técnicos, ejecución en campo a través de un folio operativo `tipo_folio = especial` sincronizado en
ambas direcciones, cierre con formulario, evidencia y firma, cancelación con razón, cotización retroactiva y reporte. P08."""
import base64
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.dependencias import Actor
from core.errors import ErrorAPI, no_encontrado, prohibido
from models.base import Dominio, EstadoRegistro, Rol
from models.catalogos import Equipo, NivelSeveridadCatalogo, TipoEquipo
from models.folios import EstadoFolio, Folio, FolioEvidencia, FolioFormularioAtencion, SeveridadOrigen, TipoEvidenciaFolio, TipoFolio
from models.formularios import Formulario, FormularioEvidencia, TipoFormulario
from models.minutas import Hallazgo
from models.seguimiento import Cotizacion, EstadoCotizacion
from models.trabajos_especiales import DecisionTECliente, EstadoTrabajoEspecial, TEEvidencia, TEHistorial, TERespuestaCliente, TipoEvidenciaTE, TrabajoEspecial
from models.unidades import UnidadNegocio
from models.usuarios import Usuario
from services import alertas_service, auditoria, folio_estados, notificaciones_service, permisos_service
from services.almacenamiento import obtener_almacenamiento
from services.folio_estados import ACTOR_SISTEMA, ActorFolio
from services.formularios import servicio as formularios
from services.preventivos_service import _actor_prestador, _unidades_visibles, _usuario_capturador
from services.seguimiento import base as seg_base

E = EstadoTrabajoEspecial
SISTEMA = "sistema"
PRESTADOR = {Rol.superadmin, Rol.admin_prestador, Rol.mesa_control, Rol.despachador}
CLIENTE = {Rol.superadmin, Rol.admin_empresa, Rol.admin_un}
PROGRAMAN = {Rol.superadmin, Rol.despachador, Rol.admin_prestador}
EJECUTAN = {Rol.superadmin, Rol.tecnico, SISTEMA}
CANCELAN = {Rol.superadmin, Rol.admin_prestador, Rol.mesa_control, Rol.despachador}
CONSULTAN = PRESTADOR | CLIENTE | {Rol.supervisor_operadores, Rol.direccion_prestador, Rol.supervisor_prestador, Rol.tecnico}
FINALES = {E.cerrado, E.cancelado}
ANTES_DE_PROGRAMAR = {E.creado, E.enviado_cliente, E.aceptado, E.rechazado}

# §6.10.6: estado → (destino → roles). `creado → programado` solo para TE de urgencia (se valida en `exigir`).
TRANSICIONES: dict[E, dict[E, set]] = {
    E.creado: {E.enviado_cliente: PRESTADOR, E.programado: PROGRAMAN, E.cancelado: CANCELAN},
    E.enviado_cliente: {E.aceptado: CLIENTE, E.rechazado: CLIENTE, E.cancelado: CANCELAN},
    E.aceptado: {E.programado: PROGRAMAN, E.cancelado: CANCELAN},
    E.rechazado: {E.enviado_cliente: PRESTADOR, E.cancelado: CANCELAN},
    E.programado: {E.en_ejecucion: EJECUTAN, E.cancelado: CANCELAN},
    E.en_ejecucion: {E.cerrado: EJECUTAN, E.cancelado: CANCELAN},
    E.cerrado: {},
    E.cancelado: {},
}
NOMBRES_ESTADO = {
    E.creado: "Creado", E.enviado_cliente: "Enviado al cliente", E.aceptado: "Aceptado", E.rechazado: "Rechazado", E.programado: "Programado",
    E.en_ejecucion: "En ejecución", E.cerrado: "Cerrado", E.cancelado: "Cancelado",
}


def rol_de(actor: ActorFolio) -> str:
    return seg_base.rol_de(actor)


def _rol(actor: ActorFolio):
    return SISTEMA if actor is ACTOR_SISTEMA else actor.rol


def puede(actor: ActorFolio, te: TrabajoEspecial, destino: E) -> bool:
    roles = TRANSICIONES[te.estado].get(destino)
    if roles is None:
        return False
    if getattr(actor, "es_superadmin", False):
        return True
    rol = _rol(actor)
    if te.estado == E.creado and destino == E.programado and not te.urgencia:
        return False  # el TE ordinario pasa por la validación del cliente
    if destino == E.cancelado and rol in (Rol.admin_empresa, Rol.admin_un):
        # §6.10.6: el cliente solo cancela sus TE de urgencia antes de programarlos.
        return te.urgencia and te.estado in ANTES_DE_PROGRAMAR and te.creado_por_rol in ("admin_empresa", "admin_un")
    return rol in roles


def exigir(actor: ActorFolio, te: TrabajoEspecial, destino: E) -> None:
    if puede(actor, te, destino):
        return
    permitidos = TRANSICIONES[te.estado]
    if destino not in permitidos or (te.estado == E.creado and destino == E.programado and not te.urgencia):
        raise ErrorAPI(409, "TRANSICION_NO_PERMITIDA", f"Un trabajo especial {NOMBRES_ESTADO[te.estado].lower()} no pasa a {NOMBRES_ESTADO[destino].lower()}",
                       [{"estado_actual": te.estado.value, "destino": destino.value, "destinos_posibles": destinos_de(actor, te)}])
    raise ErrorAPI(409, "TRANSICION_NO_PERMITIDA", f"El rol {rol_de(actor)} no puede pasar el trabajo especial a {NOMBRES_ESTADO[destino].lower()}",
                   [{"estado_actual": te.estado.value, "destino": destino.value, "roles_permitidos": sorted(str(getattr(r, "value", r)) for r in permitidos.get(destino, set()))}])


def destinos_de(actor: ActorFolio, te: TrabajoEspecial) -> list[str]:
    return [d.value for d in TRANSICIONES[te.estado] if puede(actor, te, d)]


# ------------------------------------------------------------- consultas

async def siguiente_numero(db: AsyncSession, prestador_id: UUID) -> str:
    n = (await db.execute(select(func.count()).select_from(TrabajoEspecial).where(TrabajoEspecial.prestador_id == prestador_id))).scalar() or 0
    return f"TE-{n + 1:06d}"


async def _alcance(db: AsyncSession, actor: Actor, consulta):
    if actor.es_superadmin:
        return consulta
    if actor.dominio == Dominio.tenant:
        consulta = consulta.where(TrabajoEspecial.tenant_id == actor.tenant_id)
        unidades = await _unidades_visibles(db, actor)
        if unidades is not None:
            consulta = consulta.where(TrabajoEspecial.un_id.in_(unidades))
        return consulta
    consulta = consulta.where(TrabajoEspecial.prestador_id == actor.prestador_id)
    if actor.rol == Rol.tecnico:
        consulta = consulta.where(TrabajoEspecial.tecnico_ids_json.contains([str(actor.id)]))
    return consulta


async def obtener(db: AsyncSession, actor: Actor, te_id: UUID) -> TrabajoEspecial:
    if actor.rol not in CONSULTAN:
        raise prohibido("Tu rol no consulta trabajos especiales")
    te = (await db.execute(await _alcance(db, actor, select(TrabajoEspecial).where(TrabajoEspecial.id == te_id)))).scalar_one_or_none()
    if te is None:
        raise no_encontrado("Trabajo especial")
    return te


async def listar(db: AsyncSession, actor: Actor, filtros: dict[str, Any]) -> list[TrabajoEspecial]:
    if actor.rol not in CONSULTAN:
        raise prohibido("Tu rol no consulta trabajos especiales")
    consulta = await _alcance(db, actor, select(TrabajoEspecial).order_by(TrabajoEspecial.created_at.desc()))
    if filtros.get("tenant_id"):
        consulta = consulta.where(TrabajoEspecial.tenant_id == filtros["tenant_id"])
    if filtros.get("un_id"):
        consulta = consulta.where(TrabajoEspecial.un_id == filtros["un_id"])
    if filtros.get("estado"):
        consulta = consulta.where(TrabajoEspecial.estado == filtros["estado"])
    if filtros.get("urgencia") is not None:
        consulta = consulta.where(TrabajoEspecial.urgencia.is_(bool(filtros["urgencia"])))
    if filtros.get("desde"):
        consulta = consulta.where(TrabajoEspecial.created_at >= filtros["desde"])
    if filtros.get("hasta"):
        consulta = consulta.where(TrabajoEspecial.created_at <= filtros["hasta"])
    if filtros.get("por_validar"):
        consulta = consulta.where(TrabajoEspecial.estado == E.enviado_cliente)
    return list((await db.execute(consulta)).scalars())


async def historial_de(db: AsyncSession, te_id: UUID) -> list[TEHistorial]:
    return list((await db.execute(select(TEHistorial).where(TEHistorial.trabajo_especial_id == te_id).order_by(TEHistorial.timestamp, TEHistorial.id))).scalars())


async def _historial(db: AsyncSession, te: TrabajoEspecial, anterior: str | None, nuevo: str, actor: ActorFolio, notas: str = "", datos: dict | None = None) -> None:
    db.add(TEHistorial(trabajo_especial_id=te.id, tenant_id=te.tenant_id, prestador_id=te.prestador_id, estado_anterior=anterior, estado_nuevo=nuevo,
                       actor_id=getattr(actor, "id", None), actor_rol=rol_de(actor), timestamp=datetime.now(UTC), notas=notas or "", datos_json=auditoria.a_json(datos or {})))
    await db.flush()


async def _notificar(db: AsyncSession, te: TrabajoEspecial, evento: str, destinatarios: list[UUID], asunto: str, cuerpo: str = "", **extra) -> None:
    destinatarios = [d for d in dict.fromkeys(destinatarios) if d]
    if not destinatarios:
        return
    await notificaciones_service.notificar(db, evento, destinatarios, {"trabajo_especial_id": str(te.id), "numero": te.numero, "estado": te.estado.value, "urgencia": te.urgencia, **extra},
                                           asunto=asunto, cuerpo=cuerpo or te.descripcion[:300], url=f"/trabajos-especiales?registro={te.id}", tenant_id=te.tenant_id,
                                           prestador_id=te.prestador_id)


async def _cliente_de(db: AsyncSession, te: TrabajoEspecial) -> list[UUID]:
    return await notificaciones_service.destinatarios_por_rol(db, [Rol.admin_un, Rol.admin_empresa], tenant_id=te.tenant_id, un_id=te.un_id)


async def _prestador_de(db: AsyncSession, te: TrabajoEspecial, roles=(Rol.despachador, Rol.mesa_control, Rol.admin_prestador)) -> list[UUID]:
    return await notificaciones_service.destinatarios_por_rol(db, list(roles), prestador_id=te.prestador_id)


# -------------------------------------------------------------- creación

async def _resolver_formulario(db: AsyncSession, te_prestador: UUID, usuario_id: UUID, tenant_id: UUID, equipo: Equipo | None) -> UUID | None:
    tipo = await db.get(TipoEquipo, equipo.tipo_equipo_id) if equipo else None
    r = await formularios.resolver(db, _actor_prestador(te_prestador, usuario_id), TipoFormulario.trabajo_especial.value, tenant_id,
                                   equipo.tipo_equipo_id if equipo else None, tipo.familia_id if tipo else None, None, te_prestador, TipoFolio.especial.value)
    return r[0].id if r else None


async def crear(db: AsyncSession, actor: Actor, *, tenant_id: UUID | None, un_id: UUID, equipo_id: UUID | None, descripcion: str, detalle: dict | None = None,
                monto: Decimal | None = None, formulario_id: UUID | None = None, cotizacion_id: UUID | None = None, hallazgo_id: UUID | None = None,
                urgencia: bool = False, prestador_id: UUID | None = None, request: Request | None = None) -> TrabajoEspecial:
    """Admin prestador, Mesa de control y Despachador crean TE ordinarios; Admin empresa y Admin UN solo TE de urgencia (§6.10.6)."""
    un = await db.get(UnidadNegocio, un_id)
    if un is None:
        raise ErrorAPI(422, "UNIDAD_INVALIDA", "La unidad de negocio no existe")
    if actor.dominio == Dominio.tenant:
        if not urgencia:
            raise prohibido("El cliente solo crea trabajos especiales de urgencia; los ordinarios los crea el prestador")
        if actor.rol not in (Rol.admin_empresa, Rol.admin_un):
            raise prohibido("Solo el Admin empresa o el Admin UN crean trabajos especiales de urgencia")
        if un.tenant_id != actor.tenant_id:
            raise no_encontrado("Unidad de negocio")
        unidades = await _unidades_visibles(db, actor)
        if unidades is not None and un.id not in set(unidades):
            raise ErrorAPI(422, "UNIDAD_INVALIDA", "La unidad no está entre tus UNs asignadas")
        monto = None  # §6.10.6: sin costo al crear; se formaliza con la cotización retroactiva
    elif not actor.es_superadmin and actor.rol not in (Rol.admin_prestador, Rol.mesa_control, Rol.despachador):
        raise prohibido("Solo Admin prestador, Mesa de control y Despachador crean trabajos especiales")
    tenant_id = un.tenant_id
    if actor.dominio == Dominio.prestador:
        from services import catalogos_service

        if actor.prestador_id not in await catalogos_service.prestadores_del_tenant(db, tenant_id):
            raise no_encontrado("Unidad de negocio")
        prestador_id = actor.prestador_id
    if prestador_id is None:
        from services import catalogos_service

        prestadores = await catalogos_service.prestadores_del_tenant(db, tenant_id)
        if not prestadores:
            raise ErrorAPI(422, "SIN_PRESTADOR", "El cliente no tiene prestador vinculado")
        prestador_id = prestadores[0]
    equipo = await db.get(Equipo, equipo_id) if equipo_id else None
    if equipo_id and (equipo is None or equipo.un_id != un.id):
        raise ErrorAPI(422, "EQUIPO_INVALIDO", "El equipo no pertenece a la unidad")
    if formulario_id:
        f = await db.get(Formulario, formulario_id)
        if f is None or f.tipo != TipoFormulario.trabajo_especial:
            raise ErrorAPI(422, "FORMULARIO_INVALIDO", "El formulario debe ser de tipo trabajo_especial")
    else:
        formulario_id = await _resolver_formulario(db, prestador_id, actor.id, tenant_id, equipo)
    te = TrabajoEspecial(numero=await siguiente_numero(db, prestador_id), tenant_id=tenant_id, prestador_id=prestador_id, un_id=un.id, equipo_id=equipo.id if equipo else None,
                         cotizacion_id=cotizacion_id, hallazgo_id=hallazgo_id, descripcion=descripcion.strip()[:4000], detalle_json=detalle or {}, urgencia=urgencia,
                         creado_por_id=actor.id, creado_por_rol=actor.rol.value, formulario_id=formulario_id, monto=monto, estado_desde=datetime.now(UTC))
    db.add(te)
    await db.flush()
    await _historial(db, te, None, te.estado.value, actor, "Creado de urgencia por el cliente (§6.10.6)" if urgencia else ("Creado desde cotización autorizada" if cotizacion_id else "Creado"),
                     {"cotizacion_id": str(cotizacion_id) if cotizacion_id else None, "urgencia": urgencia})
    await auditoria.registrar_actor(db, actor, "trabajos_especiales.creado", request, tenant_id=tenant_id, prestador_id=prestador_id, recurso_tipo="trabajo_especial",
                                    recurso_id=te.id, despues={"numero": te.numero, "urgencia": urgencia, "cotizacion_id": cotizacion_id, "monto": monto})
    if urgencia:
        await _notificar(db, te, "trabajo_especial.urgencia", await _prestador_de(db, te), f"TE de urgencia {te.numero} creado por {actor.nombre} ({un.codigo})")
    return te


async def desde_cotizacion(db: AsyncSession, actor: Actor, c: Cotizacion, request: Request | None = None) -> TrabajoEspecial:
    """§7.7 M1 Autorizada → Convertida: el TE hereda tenant, UN, equipo, descripción, monto y el contexto del hallazgo original."""
    from services.seguimiento import cotizaciones

    cotizaciones.exigir(actor, c, EstadoCotizacion.convertida)
    if c.trabajo_especial_id:
        raise ErrorAPI(409, "COTIZACION_YA_CONVERTIDA", "La cotización ya tiene un trabajo especial")
    hallazgo = await db.get(Hallazgo, c.hallazgo_id) if c.hallazgo_id else None
    detalle = {"partidas": c.detalle_json.get("partidas", []), "hallazgo": hallazgo.descripcion if hallazgo else None, "cotizacion_numero": c.numero}
    te = await crear(db, actor, tenant_id=c.tenant_id, un_id=c.un_id, equipo_id=c.equipo_id, descripcion=c.descripcion, detalle=detalle, monto=c.monto,
                     cotizacion_id=c.id, hallazgo_id=c.hallazgo_id, prestador_id=c.prestador_id, request=request)
    te.moneda = c.moneda
    c.trabajo_especial_id = te.id
    anterior = seg_base.transicionar(c, EstadoCotizacion.convertida)
    await db.flush()
    await seg_base.historial(db, cotizaciones.MODULO, c, anterior, c.estado.value, actor, f"Convertida en trabajo especial {te.numero}", {"trabajo_especial_id": str(te.id)})
    await auditoria.registrar_actor(db, actor, "cotizaciones.convertida", request, tenant_id=c.tenant_id, prestador_id=c.prestador_id, recurso_tipo="cotizacion", recurso_id=c.id,
                                    despues={"numero": c.numero, "trabajo_especial": te.numero})
    return te


# ------------------------------------------------------- folio operativo

async def _crear_folio_operativo(db: AsyncSession, actor: ActorFolio, te: TrabajoEspecial, request: Request | None) -> Folio:
    """Al programar, el TE se vuelve operable en la app del técnico (P05) a través de un folio `especial` vinculado (decisión pendiente)."""
    from sqlalchemy import text

    equipo = await db.get(Equipo, te.equipo_id) if te.equipo_id else None
    if equipo is None:
        equipo = (await db.execute(select(Equipo).where(Equipo.un_id == te.un_id).order_by(Equipo.codigo))).scalars().first()
    if equipo is None:
        raise ErrorAPI(422, "EQUIPO_REQUERIDO", "La UN no tiene equipos: el folio operativo del trabajo especial necesita un equipo")
    severidad_id = (await db.execute(select(NivelSeveridadCatalogo.id).where(NivelSeveridadCatalogo.prestador_id == te.prestador_id, NivelSeveridadCatalogo.activo.is_(True))
                                     .order_by(NivelSeveridadCatalogo.orden))).scalar()
    numero = (await db.execute(text("SELECT acma_siguiente_numero_folio(:t)"), {"t": te.tenant_id})).scalar_one()
    ahora = datetime.now(UTC)
    capturador = await _usuario_capturador(db, te.prestador_id, te.creado_por_id if te.creado_por_rol in ("admin_prestador", "despachador", "mesa_control") else None)
    folio = Folio(numero_folio=numero, tenant_id=te.tenant_id, prestador_id=te.prestador_id, un_id=te.un_id, equipo_id=equipo.id, tipo_falla_id=None, tipo_folio=TipoFolio.especial,
                  descripcion=f"Trabajo especial {te.numero}: {te.descripcion}"[:4000], confirmacion_un=True, confirmacion_un_timestamp=ahora, severidad_id=severidad_id,
                  severidad_origen=SeveridadOrigen.automatica_matriz, capturado_por=capturador, capturado_at=ahora, fecha_falla=ahora, trabajo_especial_id=te.id,
                  monto_estimado=te.monto)
    db.add(folio)
    await db.flush()
    contexto = {"trabajo_especial_id": str(te.id), "numero_te": te.numero, "urgencia": te.urgencia, "fecha_programada": te.fecha_programada.isoformat() if te.fecha_programada else None}
    await folio_estados.registrar_historial(db, folio, actor, estado_anterior=None, estado_nuevo=EstadoFolio.capturado, notas="Folio operativo del trabajo especial", contexto=contexto)
    await auditoria.registrar(db, "folio.trabajo_especial_generado", actor_rol=rol_de(actor), actor_id=getattr(actor, "id", None), tenant_id=te.tenant_id,
                              prestador_id=te.prestador_id, recurso_tipo="folio", recurso_id=folio.id, despues={"numero_folio": numero, **contexto})
    await folio_estados.notificar_creacion(db, folio, actor)
    await folio_estados.transicionar(db, folio, EstadoFolio.autorizado, ACTOR_SISTEMA, "Trabajo especial aceptado por el cliente (§6.10.6)", contexto, request)
    responsable = await db.get(Usuario, te.tecnico_responsable_id)
    adicionales = [t for t in te.tecnico_ids_json if t != str(te.tecnico_responsable_id)]
    await folio_estados.transicionar(db, folio, EstadoFolio.asignado, ACTOR_SISTEMA, f"Asignado al técnico responsable {responsable.nombre if responsable else ''} (trabajo especial)",
                                     {**contexto, "tecnico_id": str(te.tecnico_responsable_id), "tecnico_nombre": responsable.nombre if responsable else None, "tecnicos_adicionales": adicionales}, request)
    return folio


async def _validar_tecnicos(db: AsyncSession, te: TrabajoEspecial, tecnicos: list[UUID], responsable: UUID | None) -> tuple[list[str], UUID]:
    tecnicos = list(dict.fromkeys(tecnicos))
    if not tecnicos:
        raise ErrorAPI(422, "TECNICOS_REQUERIDOS", "Programar exige al menos un técnico")
    responsable = responsable or tecnicos[0]
    if responsable not in tecnicos:
        tecnicos.insert(0, responsable)
    for tid in tecnicos:
        u = await db.get(Usuario, tid)
        if u is None or u.rol != Rol.tecnico or u.prestador_id != te.prestador_id or u.estado != EstadoRegistro.activo:
            raise ErrorAPI(422, "TECNICO_INVALIDO", "Cada técnico debe existir, ser técnico activo y pertenecer al prestador")
        permisos = {p["clave"]: p["habilitado"] for p in await permisos_service.efectivos_de_tecnico(db, te.prestador_id, u.id)}
        if not permisos.get("ejecutar_trabajos_especiales", False):
            raise ErrorAPI(409, "TECNICO_SIN_PERMISO", f"{u.nombre} no tiene habilitado ejecutar_trabajos_especiales (§6.8.3)", [{"tecnico_id": str(u.id)}])
    return [str(t) for t in tecnicos], responsable


# --------------------------------------------------- requisitos de cierre

async def requisitos_cierre(db: AsyncSession, te: TrabajoEspecial) -> list[str]:
    """§6.10.6 Cerrado: formulario del TE enviado, evidencia fotográfica de cierre y firma del cliente."""
    faltan: list[str] = []
    if te.folio_id is None:
        return ["folio_operativo"]
    atencion = (await db.execute(select(FolioFormularioAtencion.id).where(FolioFormularioAtencion.folio_id == te.folio_id))).first()
    if atencion is None and te.respuesta_formulario_id is None:
        faltan.append("formulario_te")
    firma = (await db.execute(select(FolioEvidencia.id).where(FolioEvidencia.folio_id == te.folio_id, FolioEvidencia.tipo == TipoEvidenciaFolio.firma))).first()
    firma_te = (await db.execute(select(TEEvidencia.id).where(TEEvidencia.trabajo_especial_id == te.id, TEEvidencia.tipo == TipoEvidenciaTE.firma))).first()
    if firma is None and firma_te is None:
        faltan.append("firma")
    cierre = (await db.execute(select(TEEvidencia.id).where(TEEvidencia.trabajo_especial_id == te.id, TEEvidencia.tipo == TipoEvidenciaTE.cierre))).first()
    fotos = (await db.execute(select(FolioEvidencia.id).where(FolioEvidencia.folio_id == te.folio_id, FolioEvidencia.tipo.in_((TipoEvidenciaFolio.despues, TipoEvidenciaFolio.durante))))).first()
    if cierre is None and fotos is None:
        faltan.append("evidencia_cierre")
    return faltan


# ------------------------------------------------------- cambiar estado

async def cambiar_estado_te(db: AsyncSession, actor: ActorFolio, te: TrabajoEspecial, nuevo: E, notas: str = "", request: Request | None = None, **campos: Any) -> TrabajoEspecial:
    """Función única de transición (§6.10.6): valida destino y rol, exige los campos de cada paso, escribe `te_historial`, audita,
    notifica (P07) y sincroniza el folio operativo (eventos de chat incluidos)."""
    exigir(actor, te, nuevo)
    if isinstance(actor, Actor) and actor.dominio == Dominio.tenant and te.tenant_id != actor.tenant_id:
        raise no_encontrado("Trabajo especial")
    anterior = te.estado
    ahora = datetime.now(UTC)
    datos: dict[str, Any] = {}

    if nuevo == E.enviado_cliente:
        for k in ("descripcion", "monto", "detalle"):
            v = campos.get(k)
            if v is not None:
                setattr(te, "detalle_json" if k == "detalle" else k, v.strip()[:4000] if k == "descripcion" else v)
        te.version_enviada += 1
        te.enviado_at = ahora
        datos["version_enviada"] = te.version_enviada
    elif nuevo in (E.aceptado, E.rechazado):
        comentario = (notas or "").strip()
        if nuevo == E.rechazado and len(comentario) < 5:
            raise ErrorAPI(422, "COMENTARIO_REQUERIDO", "Rechazar un trabajo especial exige comentario (mínimo 5 caracteres)")
        if isinstance(actor, Actor) and actor.rol == Rol.admin_un:
            unidades = await _unidades_visibles(db, actor)
            if unidades is not None and te.un_id not in set(unidades):
                raise no_encontrado("Trabajo especial")
        canal = str(campos.get("canal") or "app")
        db.add(TERespuestaCliente(trabajo_especial_id=te.id, tenant_id=te.tenant_id, prestador_id=te.prestador_id, version_enviada=te.version_enviada,
                                  respondido_por=getattr(actor, "id", None), decision=DecisionTECliente(nuevo.value), comentario=comentario, canal=canal, timestamp=ahora))
        datos.update({"version_enviada": te.version_enviada, "canal": canal, "comentario": comentario})
        if nuevo == E.aceptado:
            te.aceptado_at = ahora
    elif nuevo == E.programado:
        fecha = campos.get("fecha_programada")
        if not fecha:
            raise ErrorAPI(422, "FECHA_REQUERIDA", "Programar exige fecha_programada")
        te.fecha_programada = fecha if isinstance(fecha, date) else date.fromisoformat(str(fecha))
        tecnicos, responsable = await _validar_tecnicos(db, te, [UUID(str(t)) for t in (campos.get("tecnico_ids") or [])], UUID(str(campos["tecnico_responsable_id"])) if campos.get("tecnico_responsable_id") else None)
        te.tecnico_ids_json, te.tecnico_responsable_id, te.programado_at = tecnicos, responsable, ahora
        datos.update({"fecha_programada": te.fecha_programada.isoformat(), "tecnicos": tecnicos, "responsable": str(responsable), "sin_validacion_cliente": anterior == E.creado})
    elif nuevo == E.en_ejecucion:
        _exigir_responsable(actor, te)
        te.fecha_inicio = te.fecha_inicio or ahora
    elif nuevo == E.cerrado:
        _exigir_responsable(actor, te)
        faltan = await requisitos_cierre(db, te)
        if faltan:
            raise ErrorAPI(409, "CIERRE_TE_INCOMPLETO", "Para cerrar el trabajo especial faltan el formulario del TE, la evidencia fotográfica de cierre y/o la firma del cliente", faltan)
        te.fecha_cierre = ahora
        if te.respuesta_formulario_id is None and te.folio_id:
            vinculo = (await db.execute(select(FolioFormularioAtencion).where(FolioFormularioAtencion.folio_id == te.folio_id))).scalar_one_or_none()
            te.respuesta_formulario_id = vinculo.respuesta_id if vinculo else None
    elif nuevo == E.cancelado:
        razon = seg_base.exigir_justificacion(notas or campos.get("razon"), "Cancelar un trabajo especial")
        te.razon_cancelacion = razon
        notas = razon

    te.estado, te.estado_desde = nuevo, ahora
    await db.flush()
    await _historial(db, te, anterior.value, nuevo.value, actor, notas, datos)
    await auditoria.registrar(db, f"trabajos_especiales.{nuevo.value}", actor_rol=rol_de(actor), actor_id=getattr(actor, "id", None), tenant_id=te.tenant_id, prestador_id=te.prestador_id,
                              recurso_tipo="trabajo_especial", recurso_id=te.id, antes={"estado": anterior.value}, despues={"estado": nuevo.value, "notas": notas, **auditoria.a_json(datos)},
                              request=request)

    # Efectos posteriores: folio operativo, notificaciones y eventos de chat.
    if nuevo == E.enviado_cliente:
        await _notificar(db, te, "trabajo_especial.enviado", await _cliente_de(db, te), f"Trabajo especial {te.numero} v{te.version_enviada}: acéptalo o recházalo",
                         f"{te.descripcion[:200]} · monto {('$' + format(te.monto, ',.2f') + ' ' + te.moneda) if te.monto is not None else 'por definir'}", version=te.version_enviada)
    elif nuevo == E.aceptado:
        await _notificar(db, te, "trabajo_especial.aceptado", [te.creado_por_id] + await _prestador_de(db, te, (Rol.despachador,)), f"El cliente aceptó el trabajo especial {te.numero}", notas)
    elif nuevo == E.rechazado:
        await _notificar(db, te, "trabajo_especial.rechazado", [te.creado_por_id] + await _prestador_de(db, te, (Rol.despachador,)), f"El cliente rechazó el trabajo especial {te.numero}", notas)
    elif nuevo == E.programado:
        folio = await _crear_folio_operativo(db, actor, te, request)
        te.folio_id = folio.id
        await db.flush()
        await _evento_chat(db, folio, "trabajo_especial.programado", f"Trabajo especial {te.numero} programado para {te.fecha_programada.isoformat()}", {"trabajo_especial_id": str(te.id)})
        await _notificar(db, te, "trabajo_especial.programado", await _cliente_de(db, te), f"Trabajo especial {te.numero} programado para el {te.fecha_programada.strftime('%d/%m/%Y')}",
                         f"{te.descripcion[:200]} · folio operativo {folio.numero_folio}", fecha_programada=te.fecha_programada.isoformat(), folio_id=str(folio.id))
        await _notificar(db, te, "trabajo_especial.programado", [UUID(t) for t in te.tecnico_ids_json], f"Tienes el trabajo especial {te.numero} el {te.fecha_programada.strftime('%d/%m/%Y')}",
                         folio_id=str(folio.id))
    elif nuevo == E.en_ejecucion:
        await _sincronizar_folio(db, te, actor, EstadoFolio.en_ejecucion, request)
    elif nuevo == E.cerrado:
        await _sincronizar_folio(db, te, actor, EstadoFolio.cerrado, request)
        await _notificar(db, te, "trabajo_especial.cerrado", await _cliente_de(db, te) + await _prestador_de(db, te, (Rol.despachador, Rol.mesa_control)),
                         f"Trabajo especial {te.numero} terminado{' (urgencia)' if te.urgencia else ''}")
    elif nuevo == E.cancelado:
        await _sincronizar_folio(db, te, actor, EstadoFolio.cancelado, request, razon=te.razon_cancelacion)
        destinatarios = await _cliente_de(db, te) + await _prestador_de(db, te, (Rol.despachador,)) + [te.creado_por_id]
        await _notificar(db, te, "trabajo_especial.cancelado", destinatarios, f"Trabajo especial {te.numero} cancelado: {te.razon_cancelacion}")
    return te


def _exigir_responsable(actor: ActorFolio, te: TrabajoEspecial) -> None:
    if isinstance(actor, Actor) and actor.rol == Rol.tecnico and str(actor.id) != str(te.tecnico_responsable_id):
        raise prohibido("Solo el técnico responsable (jefe de cuadrilla) ejecuta las transiciones del trabajo especial")


async def _evento_chat(db: AsyncSession, folio: Folio, tipo: str, texto: str, datos: dict) -> None:
    from models.chat import CanalChat, EstadoChat
    from services import chat_service

    chats = await chat_service.chats_del_folio(db, folio.id)
    for canal in (CanalChat.campo, CanalChat.operativo):
        if canal in chats and chats[canal].estado == EstadoChat.activo:
            await chat_service.evento_sistema(db, chats[canal], tipo, texto, datos)


def _actor_para_folio(actor: ActorFolio, te: TrabajoEspecial, folio: Folio, destino: EstadoFolio) -> ActorFolio:
    """El folio sigue la tabla literal de §6.8.6: si el actor del TE no puede ejecutar la transición (p. ej. Mesa de control
    cancela un folio asignado, o el sistema cierra), se usa un actor del prestador con el id real del usuario (decisión pendiente)."""
    if folio_estados.puede(actor, folio.estado, destino):
        return actor
    if destino == EstadoFolio.cancelado:
        return Actor(id=getattr(actor, "id", None), email="sistema@acma", nombre=getattr(actor, "nombre", "sistema"), rol=Rol.admin_prestador, dominio=Dominio.prestador,
                     tenant_id=None, prestador_id=te.prestador_id, sesion_id=None)
    if destino in (EstadoFolio.en_camino, EstadoFolio.en_ejecucion, EstadoFolio.cerrado):
        return ACTOR_SISTEMA
    return actor


async def _sincronizar_folio(db: AsyncSession, te: TrabajoEspecial, actor: ActorFolio, destino: EstadoFolio, request: Request | None, razon: str | None = None) -> None:
    """TE → folio: en_ejecucion ↔ en_ejecucion, cerrado ↔ cerrado y la cancelación en cualquiera cancela al otro."""
    if te.folio_id is None:
        return
    folio = await db.get(Folio, te.folio_id)
    if folio is None or folio.estado == destino or folio.estado in (EstadoFolio.cerrado, EstadoFolio.cancelado):
        return
    contexto = {"trabajo_especial_id": str(te.id), "numero_te": te.numero, "sincronizado_desde": "trabajo_especial"}
    if destino == EstadoFolio.en_ejecucion:
        if folio.estado == EstadoFolio.asignado:
            await folio_estados.transicionar(db, folio, EstadoFolio.en_camino, _actor_para_folio(actor, te, folio, EstadoFolio.en_camino), "Inicio del trabajo especial", contexto, request)
        if folio.estado == EstadoFolio.en_camino:
            await folio_estados.transicionar(db, folio, EstadoFolio.en_ejecucion, _actor_para_folio(actor, te, folio, EstadoFolio.en_ejecucion), "Trabajo especial en ejecución", contexto, request)
    elif destino == EstadoFolio.cerrado:
        if folio.estado == EstadoFolio.en_ejecucion:
            await folio_estados.transicionar(db, folio, EstadoFolio.cerrado, _actor_para_folio(actor, te, folio, EstadoFolio.cerrado), "Trabajo especial cerrado", contexto, request)
    elif destino == EstadoFolio.cancelado:
        if folio_estados.TRANSICIONES.get(folio.estado, {}).get(EstadoFolio.cancelado) is not None:
            await folio_estados.transicionar(db, folio, EstadoFolio.cancelado, _actor_para_folio(actor, te, folio, EstadoFolio.cancelado), f"Trabajo especial cancelado: {razon}",
                                             {**contexto, "razon_cancelacion": razon}, request)


@folio_estados.suscribir_validacion
async def _validar_cierre_te(db: AsyncSession, folio: Folio, nuevo: EstadoFolio, actor: ActorFolio, contexto: dict) -> None:
    """Cerrar el folio operativo exige también la evidencia fotográfica de cierre del TE (§6.10.6)."""
    if nuevo != EstadoFolio.cerrado or not folio.trabajo_especial_id:
        return
    te = await db.get(TrabajoEspecial, folio.trabajo_especial_id)
    if te is None or te.estado in FINALES:
        return
    faltan = await requisitos_cierre(db, te)
    if faltan:
        raise ErrorAPI(409, "CIERRE_TE_INCOMPLETO", "Para cerrar el trabajo especial faltan el formulario del TE, la evidencia fotográfica de cierre y/o la firma del cliente", faltan)


@folio_estados.suscribir
async def _al_transicionar_folio(db: AsyncSession, folio: Folio, anterior: EstadoFolio, nuevo: EstadoFolio, actor: ActorFolio, contexto: dict) -> None:
    """Folio → TE: el técnico opera desde la app de P05 y el TE refleja el avance."""
    if not folio.trabajo_especial_id:
        return
    te = await db.get(TrabajoEspecial, folio.trabajo_especial_id)
    if te is None or te.estado in FINALES:
        return
    destino = {EstadoFolio.en_ejecucion: E.en_ejecucion, EstadoFolio.cerrado: E.cerrado, EstadoFolio.cancelado: E.cancelado}.get(nuevo)
    if destino is None or te.estado == destino:
        return
    actor_te = actor if puede(actor, te, destino) else ACTOR_SISTEMA
    if destino == E.cancelado:
        await cambiar_estado_te(db, _actor_para_folio(actor, te, folio, EstadoFolio.cancelado) if not puede(actor, te, destino) else actor, te, destino,
                                folio.razon_cancelacion or "Folio operativo cancelado", None, razon=folio.razon_cancelacion or "Folio operativo cancelado")
        return
    if destino == E.en_ejecucion and te.estado != E.programado:
        return
    if destino == E.cerrado and te.estado != E.en_ejecucion:
        if te.estado == E.programado:
            await cambiar_estado_te(db, actor_te if puede(actor_te, te, E.en_ejecucion) else ACTOR_SISTEMA, te, E.en_ejecucion, "Sincronizado desde el folio")
        else:
            return
    await cambiar_estado_te(db, actor_te if puede(actor_te, te, destino) else ACTOR_SISTEMA, te, destino, "Sincronizado desde el folio operativo")


# -------------------------------------------------------------- acciones

async def agregar_evidencia(db: AsyncSession, actor: Actor, te: TrabajoEspecial, *, tipo: TipoEvidenciaTE, evidencia_id: UUID | None, contenido_base64: str | None,
                            nombre: str | None, mime: str | None, geolat: float | None, geolng: float | None, request: Request | None) -> TEEvidencia:
    if te.estado in FINALES:
        raise ErrorAPI(409, "TE_FINAL", "El trabajo especial ya está cerrado o cancelado")
    if actor.rol == Rol.tecnico and str(actor.id) not in te.tecnico_ids_json:
        raise prohibido("El trabajo especial no está asignado a ti")
    archivo_key = ""
    if evidencia_id:
        ev = await db.get(FormularioEvidencia, evidencia_id)
        if ev is None:
            raise no_encontrado("Evidencia")
        archivo_key, geolat, geolng = ev.archivo_key, ev.geolat if geolat is None else geolat, ev.geolng if geolng is None else geolng
    elif contenido_base64:
        datos = base64.b64decode(contenido_base64)
        archivo_key = f"trabajos_especiales/{te.tenant_id}/{te.numero}/{uuid.uuid4().hex}-{(nombre or 'evidencia.jpg')[:80]}"
        obtener_almacenamiento().guardar(archivo_key, datos, mime or "image/jpeg")
    else:
        raise ErrorAPI(422, "EVIDENCIA_REQUERIDA", "Indica evidencia_id (formulario) o contenido_base64")
    e = TEEvidencia(trabajo_especial_id=te.id, tenant_id=te.tenant_id, prestador_id=te.prestador_id, tipo=tipo, evidencia_id=evidencia_id, archivo_key=archivo_key, geolat=geolat, geolng=geolng,
                    timestamp=datetime.now(UTC), subido_por=actor.id)
    db.add(e)
    await db.flush()
    await _historial(db, te, te.estado.value, te.estado.value, actor, f"Evidencia de {tipo.value}", {"evidencia_te_id": str(e.id)})
    return e


async def evidencias_de(db: AsyncSession, te: TrabajoEspecial) -> list[TEEvidencia]:
    return list((await db.execute(select(TEEvidencia).where(TEEvidencia.trabajo_especial_id == te.id).order_by(TEEvidencia.timestamp))).scalars())


async def cotizacion_retroactiva(db: AsyncSession, actor: Actor, te: TrabajoEspecial, *, descripcion: str | None, monto: Decimal | None, detalle: dict | None,
                                 request: Request | None) -> Cotizacion:
    """§6.10.6 TE de urgencia: cotización retroactiva opcional, vinculada en ambas direcciones; no bloquea el cierre."""
    from services.seguimiento import cotizaciones

    seg_base.exigir_rol(actor, PRESTADOR, "Crear la cotización retroactiva")
    if te.cotizacion_id or te.cotizacion_retroactiva_id:
        raise ErrorAPI(409, "TE_CON_COTIZACION", "El trabajo especial ya tiene cotización vinculada")
    c = await cotizaciones.crear(db, actor, tenant_id=te.tenant_id, prestador_id=te.prestador_id, un_id=te.un_id, equipo_id=te.equipo_id, descripcion=descripcion or te.descripcion,
                                 hallazgo_id=te.hallazgo_id, folio_id=te.folio_id, origen="retroactiva", request=request)
    c.trabajo_especial_id = te.id
    if monto is not None or detalle is not None:
        await cotizaciones.preparar(db, actor, c, descripcion=None, monto=monto, detalle=detalle, request=request)
    te.cotizacion_retroactiva_id = c.id
    if monto is not None and te.monto is None:
        te.monto = monto
    await db.flush()
    await _historial(db, te, te.estado.value, te.estado.value, actor, f"Cotización retroactiva {c.numero}", {"cotizacion_id": str(c.id), "monto": str(monto) if monto is not None else None})
    return c


# ------------------------------------------------------------ serialización

async def serializar(db: AsyncSession, actor: ActorFolio, tes: list[TrabajoEspecial]) -> list[dict[str, Any]]:
    if not tes:
        return []
    unidades = {u.id: u for u in (await db.execute(select(UnidadNegocio).where(UnidadNegocio.id.in_({t.un_id for t in tes})))).scalars()}
    equipos = {e.id: e for e in (await db.execute(select(Equipo).where(Equipo.id.in_({t.equipo_id for t in tes if t.equipo_id})))).scalars()} if any(t.equipo_id for t in tes) else {}
    folios = {f.id: f for f in (await db.execute(select(Folio).where(Folio.id.in_({t.folio_id for t in tes if t.folio_id})))).scalars()} if any(t.folio_id for t in tes) else {}
    cot_ids = {t.cotizacion_id for t in tes if t.cotizacion_id} | {t.cotizacion_retroactiva_id for t in tes if t.cotizacion_retroactiva_id}
    cotizaciones = {c.id: c for c in (await db.execute(select(Cotizacion).where(Cotizacion.id.in_(cot_ids)))).scalars()} if cot_ids else {}
    ids_usuarios = {t.creado_por_id for t in tes} | {t.tecnico_responsable_id for t in tes} | {UUID(x) for t in tes for x in t.tecnico_ids_json}
    usuarios = {u.id: u.nombre for u in (await db.execute(select(Usuario).where(Usuario.id.in_({i for i in ids_usuarios if i})))).scalars()}
    alertas = await seg_base.alertas_activas(db, [t.id for t in tes])
    from models.costos import FolioCosto  # P09: el monto real del TE es el costo de su folio operativo

    costos = {c.folio_id: c for c in (await db.execute(select(FolioCosto).where(
        FolioCosto.folio_id.in_({t.folio_id for t in tes if t.folio_id})))).scalars()} if any(t.folio_id for t in tes) else {}
    salida = []
    for t in tes:
        un, eq, f = unidades.get(t.un_id), equipos.get(t.equipo_id), folios.get(t.folio_id)
        c, cr = cotizaciones.get(t.cotizacion_id), cotizaciones.get(t.cotizacion_retroactiva_id)
        costo = costos.get(t.folio_id)
        salida.append({**auditoria.instantanea(t), "costo_real": costo.costo_total if costo else None, "costo_validado": bool(costo and costo.validado_at),
                       "id": t.id, "tenant_id": t.tenant_id, "prestador_id": t.prestador_id, "un_id": t.un_id, "equipo_id": t.equipo_id, "cotizacion_id": t.cotizacion_id,
                       "hallazgo_id": t.hallazgo_id, "formulario_id": t.formulario_id, "respuesta_formulario_id": t.respuesta_formulario_id, "cotizacion_retroactiva_id": t.cotizacion_retroactiva_id,
                       "tecnico_responsable_id": t.tecnico_responsable_id, "folio_id": t.folio_id, "creado_por_id": t.creado_por_id, "created_at": t.created_at, "updated_at": t.updated_at,
                       "estado_desde": t.estado_desde, "enviado_at": t.enviado_at, "aceptado_at": t.aceptado_at, "programado_at": t.programado_at, "fecha_inicio": t.fecha_inicio, "fecha_cierre": t.fecha_cierre,
                       "un_codigo": un.codigo if un else None, "un_nombre": un.nombre if un else None, "equipo_codigo": eq.codigo if eq else None, "equipo_nombre": eq.nombre if eq else None,
                       "numero_folio": f.numero_folio if f else None, "estado_folio": f.estado.value if f else None, "cotizacion_numero": c.numero if c else None,
                       "cotizacion_estado": c.estado.value if c else None, "cotizacion_retroactiva_numero": cr.numero if cr else None, "creado_por_nombre": usuarios.get(t.creado_por_id),
                       "tecnico_responsable_nombre": usuarios.get(t.tecnico_responsable_id), "tecnicos": [{"id": x, "nombre": usuarios.get(UUID(x))} for x in t.tecnico_ids_json],
                       "dias_en_estado": seg_base.dias_en_estado(t), "alertas_activas": alertas.get(t.id, []), "destinos": destinos_de(actor, t)})
    return salida


async def detalle(db: AsyncSession, actor: Actor, te: TrabajoEspecial) -> dict[str, Any]:
    d = (await serializar(db, actor, [te]))[0]
    hist = await historial_de(db, te.id)
    respuestas = list((await db.execute(select(TERespuestaCliente).where(TERespuestaCliente.trabajo_especial_id == te.id).order_by(TERespuestaCliente.timestamp))).scalars())
    nombres = {u.id: u.nombre for u in (await db.execute(select(Usuario).where(Usuario.id.in_({h.actor_id for h in hist if h.actor_id} | {r.respondido_por for r in respuestas if r.respondido_por})))).scalars()}
    d["historial"] = [{"id": h.id, "estado_anterior": h.estado_anterior, "estado_nuevo": h.estado_nuevo, "actor_id": h.actor_id, "actor_nombre": nombres.get(h.actor_id), "actor_rol": h.actor_rol,
                       "timestamp": h.timestamp, "notas": h.notas, "datos_json": h.datos_json} for h in hist]
    d["respuestas_cliente"] = [{"id": r.id, "version_enviada": r.version_enviada, "respondido_por": r.respondido_por, "respondido_por_nombre": nombres.get(r.respondido_por), "decision": r.decision.value,
                                "comentario": r.comentario, "canal": r.canal, "timestamp": r.timestamp} for r in respuestas]
    d["evidencias"] = [{"id": e.id, "tipo": e.tipo.value, "evidencia_id": e.evidencia_id, "archivo_key": e.archivo_key, "geolat": e.geolat, "geolng": e.geolng, "timestamp": e.timestamp, "subido_por": e.subido_por}
                       for e in await evidencias_de(db, te)]
    d["requisitos_cierre_faltantes"] = await requisitos_cierre(db, te) if te.estado in (E.programado, E.en_ejecucion) else []
    d["puede_responder"] = te.estado == E.enviado_cliente and (actor.es_superadmin or actor.rol in (Rol.admin_empresa, Rol.admin_un))
    return d


# ---------------------------------------------------------------- minuta

async def seccion_minuta(db: AsyncSession, tenant_id: UUID, prestador_id: UUID, un_id: UUID | None, inicio: datetime, fin: datetime) -> dict[str, list[dict[str, Any]]]:
    """§7.3: nuevos solicitados en el día, en proceso y terminados en el día con evidencia fotográfica de cierre y etiqueta de urgencia."""
    consulta = select(TrabajoEspecial).where(TrabajoEspecial.tenant_id == tenant_id, TrabajoEspecial.prestador_id == prestador_id)
    if un_id:
        consulta = consulta.where(TrabajoEspecial.un_id == un_id)
    tes = list((await db.execute(consulta.order_by(TrabajoEspecial.created_at))).scalars())
    unidades = {u.id: u for u in (await db.execute(select(UnidadNegocio).where(UnidadNegocio.id.in_({t.un_id for t in tes})))).scalars()} if tes else {}
    salida: dict[str, list[dict[str, Any]]] = {"nuevos": [], "en_proceso": [], "terminados": []}
    for t in tes:
        un = unidades.get(t.un_id)
        fila = {"trabajo_especial_id": str(t.id), "numero": t.numero, "descripcion": t.descripcion, "un": f"{un.codigo} · {un.nombre}" if un else "", "estado": t.estado.value,
                "urgencia": t.urgencia, "monto": str(t.monto) if t.monto is not None else None, "fecha_programada": t.fecha_programada.isoformat() if t.fecha_programada else None}
        if inicio <= t.created_at < fin:
            salida["nuevos"].append(fila)
        if t.estado == E.cerrado and t.fecha_cierre and inicio <= t.fecha_cierre < fin:
            fotos = [e for e in await evidencias_de(db, t) if e.tipo == TipoEvidenciaTE.cierre]
            if not fotos and t.folio_id:
                fotos = list((await db.execute(select(FolioEvidencia).where(FolioEvidencia.folio_id == t.folio_id, FolioEvidencia.tipo.in_((TipoEvidenciaFolio.despues, TipoEvidenciaFolio.durante))))).scalars())
            salida["terminados"].append({**fila, "evidencias_cierre": [e.archivo_key for e in fotos], "fecha_cierre": t.fecha_cierre.isoformat()})
        elif t.estado in (E.aceptado, E.programado, E.en_ejecucion, E.enviado_cliente, E.rechazado) and not (inicio <= t.created_at < fin):
            salida["en_proceso"].append(fila)
    return salida


# --------------------------------------------------------------- reporte

async def reporte(db: AsyncSession, actor: Actor, desde: date | None, hasta: date | None, tenant_id: UUID | None) -> dict[str, Any]:
    if actor.rol not in CONSULTAN - {Rol.tecnico}:
        raise prohibido("Tu rol no consulta el reporte de trabajos especiales")
    filtros = {"tenant_id": tenant_id, "desde": datetime.combine(desde, datetime.min.time(), tzinfo=UTC) if desde else None,
               "hasta": datetime.combine(hasta, datetime.max.time(), tzinfo=UTC) if hasta else None}
    tes = await listar(db, actor, filtros)
    por_estado = {e.value: 0 for e in E}
    for t in tes:
        por_estado[t.estado.value] += 1
    etapas = {"creado_a_enviado": [], "enviado_a_respuesta": [], "aceptado_a_programado": [], "programado_a_cierre": []}
    for t in tes:
        if t.enviado_at:
            etapas["creado_a_enviado"].append((t.enviado_at - t.created_at).total_seconds() / 86400)
        if t.enviado_at and t.aceptado_at:
            etapas["enviado_a_respuesta"].append((t.aceptado_at - t.enviado_at).total_seconds() / 86400)
        if t.aceptado_at and t.programado_at:
            etapas["aceptado_a_programado"].append((t.programado_at - t.aceptado_at).total_seconds() / 86400)
        if t.programado_at and t.fecha_cierre:
            etapas["programado_a_cierre"].append((t.fecha_cierre - t.programado_at).total_seconds() / 86400)
    promedios = {k: (round(sum(v) / len(v), 2) if v else None) for k, v in etapas.items()}
    urgencias = sum(1 for t in tes if t.urgencia)
    monto = sum((t.monto for t in tes if t.monto is not None and t.estado != E.cancelado), Decimal("0"))
    return {"desde": desde, "hasta": hasta, "total": len(tes), "por_estado": por_estado, "tiempo_promedio_etapas_dias": promedios,
            "porcentaje_urgencias": round(urgencias * 100 / len(tes), 1) if tes else 0, "urgencias": urgencias, "monto_total": str(monto),
            "sin_cotizacion_retroactiva": sum(1 for t in tes if t.urgencia and not t.cotizacion_retroactiva_id and t.estado == E.cerrado)}


async def disparar_incompleto(db: AsyncSession, clave: str, te: TrabajoEspecial, datos: dict) -> None:
    await alertas_service.disparar(db, clave, tenant_id=te.tenant_id, prestador_id=te.prestador_id, entidad_tipo="trabajo_especial", entidad_id=te.id, datos=datos)
