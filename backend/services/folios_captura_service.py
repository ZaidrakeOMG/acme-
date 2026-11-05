"""Captura de folios y validaciones automáticas (§6.8.6), alcance por rol, detalle del archivo y acciones.

Orden literal de validaciones al enviar:
 1. confirmacion_un → si falta, el folio queda en `capturado` (trigger confirmacion_un_faltante + notificación al operador).
 2. contrato activo → si no, `en_revision` + sin_contrato + notificación al despachador con el contrato vencido.
 3. duplicado abierto → 409 FOLIO_DUPLICADO_BLOQUEADO (bloqueo total) o justificación obligatoria (confirmación fuerte).
 4. severidad por matriz → si no está configurada, `en_revision` + severidad_no_configurada + MATRIZ_SEVERIDAD_INCOMPLETA.
 5. garantía vigente + revision_obligatoria_garantia → `en_revision` + garantia.
 6. tipos_falla.requiere_revision_manual → `en_revision` + tipo_falla_flag.
 7. fuera del horario de servicio del contrato → `en_revision` + fuera_horario + notificación al despachador.
 8. keyword de alerta en la descripción → `en_revision` + keyword_alerta.
Si todas pasan, el folio entra al punto de decisión del flujo multinivel (aprobacion_service.evaluar_al_capturar).
"""
import re
import unicodedata
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import Request
from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from core.dependencias import Actor, validar_tenant
from core.errors import ErrorAPI, no_encontrado, prohibido
from models.base import Dominio, Rol
from models.catalogos import Equipo, EstadoActivo, Habilidad, NivelSeveridadCatalogo, Tecnico, TecnicoHabilidad, TipoEquipo, TipoFalla
from models.contratos import Contrato
from models.folios import (
    ESTADOS_ABIERTOS, AprobacionAlertaTimeout, AprobacionDecision, AprobacionFlujo, EstadoFlujo, EstadoFolio, Folio,
    FolioEncuesta, FolioEstadoHistorial, FolioEvidencia, FolioFormularioAtencion, FolioFormularioCaptura, FolioKeywordAlerta,
    FolioRefaccion, FolioSLA, RevisionManualTrigger, SeveridadOrigen, TipoEvidenciaFolio, TriggerRevision,
)
from models.formularios import EstadoRespuesta, Formulario, FormularioEvidencia, FormularioRespuesta, FormularioVersion, OrigenRespuesta, TipoEvidencia
from models.unidades import GrupoUNMiembro, UnidadNegocio, UsuarioGrupo, UsuarioUN
from models.usuarios import Usuario
from schemas.folios import DIAS, FolioEntrada
from services import alertas_service, aprobacion_service, auditoria, catalogos_service, folio_estados, folios_sla, notificaciones, permisos_service, sla_service
from services.folio_estados import ACTOR_SISTEMA, ActorFolio

CREAN_SIEMPRE = {Rol.operador, Rol.admin_un, Rol.admin_empresa, Rol.supervisor_operadores, Rol.mesa_control, Rol.superadmin}
ROLES_PRESTADOR_GESTION = {Rol.admin_prestador, Rol.mesa_control, Rol.despachador, Rol.direccion_prestador, Rol.supervisor_prestador}
FIJAN_MONTO = {Rol.mesa_control, Rol.despachador, Rol.admin_prestador, Rol.superadmin}
OVERRIDE_SEVERIDAD = {Rol.despachador, Rol.admin_prestador, Rol.superadmin}


# ------------------------------------------------------------- alcance (§5)

def _unidades_visibles(actor: Actor):
    directas = select(UsuarioUN.unidad_id).where(UsuarioUN.usuario_id == actor.id)
    if actor.rol in (Rol.admin_un, Rol.operador):
        return directas
    por_grupo = (select(GrupoUNMiembro.unidad_id).join(UsuarioGrupo, UsuarioGrupo.grupo_id == GrupoUNMiembro.grupo_id)
                 .where(UsuarioGrupo.usuario_id == actor.id))
    return select(UnidadNegocio.id).where(or_(UnidadNegocio.id.in_(directas), UnidadNegocio.id.in_(por_grupo)))


def filtro_alcance(actor: Actor):
    """Operador/Admin UN/Supervisor: sus UNs; Admin empresa: su tenant; técnico: solo asignados a él (o capturados por él,
    cierra la decisión pendiente 3 de P01); roles del prestador: los tenants que atiende (RLS) y su prestador."""
    if actor.es_superadmin:
        return None
    if actor.rol in (Rol.admin_un, Rol.operador, Rol.supervisor_operadores):
        return Folio.un_id.in_(_unidades_visibles(actor))
    if actor.rol == Rol.admin_empresa:
        return Folio.tenant_id == actor.tenant_id
    if actor.rol == Rol.tecnico:
        return or_(Folio.tecnico_id == actor.id, Folio.capturado_por == actor.id)
    return Folio.prestador_id == actor.prestador_id


async def obtener(db: AsyncSession, actor: Actor, folio_id: UUID) -> Folio:
    consulta = select(Folio).where(Folio.id == folio_id)
    filtro = filtro_alcance(actor)
    if filtro is not None:
        consulta = consulta.where(filtro)
    folio = (await db.execute(consulta)).scalar_one_or_none()
    if folio is None:
        raise no_encontrado("Folio")
    return folio


# -------------------------------------------------------- permiso de captura

async def exigir_puede_crear(db: AsyncSession, actor: Actor, tenant_id: UUID) -> None:
    if actor.rol in CREAN_SIEMPRE:
        return
    if actor.rol == Rol.tecnico:
        permisos = await permisos_service.efectivos_de_tecnico(db, actor.prestador_id, actor.id)
        if any(p["clave"] == "crear_folio_en_campo" and p["habilitado"] for p in permisos):
            return
        raise prohibido("Tu prestador no te habilitó el permiso crear_folio_en_campo")
    if actor.rol == Rol.despachador:
        permisos = await permisos_service.efectivos_despachador(db, actor.prestador_id, actor.id, tenant_id)
        if any(p["clave"] == "crear_folios" and p["habilitado"] for p in permisos):
            return
        raise prohibido("No tienes habilitado el permiso crear_folios para este cliente")
    raise prohibido("Tu rol no captura folios")


# -------------------------------------------------------------- validaciones

def _normalizar(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto.lower()) if unicodedata.category(c) != "Mn")


async def keywords_detectadas(db: AsyncSession, prestador_id: UUID, tenant_id: UUID, descripcion: str) -> list[str]:
    filas = (await db.execute(select(FolioKeywordAlerta).where(
        FolioKeywordAlerta.prestador_id == prestador_id, FolioKeywordAlerta.activa.is_(True),
        or_(FolioKeywordAlerta.tenant_id.is_(None), FolioKeywordAlerta.tenant_id == tenant_id)))).scalars()
    texto = _normalizar(descripcion)
    return sorted({k.palabra for k in filas if re.search(rf"(?<!\w){re.escape(_normalizar(k.palabra))}(?!\w)", texto)})


def dentro_de_horario(horario: dict[str, Any] | None, momento: datetime, zona: str = "America/Mexico_City") -> bool:
    """`horario` = {"lunes": [["08:00","18:00"]], ...}; None = 24/7. Un día ausente o sin rangos = sin servicio."""
    if not horario:
        return True
    try:
        local = momento.astimezone(ZoneInfo(zona))
    except Exception:  # zona inválida en la UN
        local = momento.astimezone(ZoneInfo("America/Mexico_City"))
    rangos = horario.get(DIAS[local.weekday()]) or []
    hhmm = local.strftime("%H:%M")
    return any(inicio <= hhmm < fin for inicio, fin in rangos)


async def _avisar_despachador(db: AsyncSession, folio: Folio, asunto: str, cuerpo: str) -> None:
    from services import notificaciones_service

    destinatarios = await notificaciones_service.destinatarios_por_rol(db, ["despachador"], prestador_id=folio.prestador_id)
    await notificaciones_service.notificar(db, "folio.revision", destinatarios, {"folio_id": str(folio.id)}, asunto=asunto, cuerpo=cuerpo, url=f"/folios/{folio.id}",
                                           tenant_id=folio.tenant_id, prestador_id=folio.prestador_id, canales=["app", "push"])


async def _trigger(db: AsyncSession, folio: Folio, tipo: TriggerRevision, descripcion: str) -> None:
    db.add(RevisionManualTrigger(folio_id=folio.id, tenant_id=folio.tenant_id, prestador_id=folio.prestador_id, trigger_tipo=tipo,
                                 descripcion=descripcion))
    await db.flush()


async def _folio_abierto_del_equipo(db: AsyncSession, equipo_id: UUID, excluir: UUID | None = None) -> Folio | None:
    consulta = select(Folio).where(Folio.equipo_id == equipo_id, Folio.estado.in_(ESTADOS_ABIERTOS)).order_by(Folio.capturado_at)
    if excluir:
        consulta = consulta.where(Folio.id != excluir)
    return (await db.execute(consulta)).scalars().first()


async def tarjeta_duplicado(db: AsyncSession, actor: Actor, equipo_id: UUID) -> dict[str, Any]:
    """§6.8.6: estado del folio abierto existente y, de Asignado en adelante, técnico y ETA."""
    equipo = await db.get(Equipo, equipo_id)
    if equipo is None:
        raise no_encontrado("Equipo")
    if actor.dominio == Dominio.tenant:
        validar_tenant(actor, equipo.tenant_id)
    politicas = await aprobacion_service.politicas_de(db, equipo.tenant_id)
    existente = await _folio_abierto_del_equipo(db, equipo_id)
    if existente is None:
        return {"existe": False, "bloqueo_total": politicas.bloqueo_total_duplicados}
    tecnico = await db.get(Usuario, existente.tecnico_id) if existente.tecnico_id else None
    severidad = await db.get(NivelSeveridadCatalogo, existente.severidad_id) if existente.severidad_id else None
    return {
        "existe": True, "bloqueo_total": politicas.bloqueo_total_duplicados, "folio_id": existente.id, "numero_folio": existente.numero_folio,
        "estado": existente.estado, "descripcion": existente.descripcion[:300], "capturado_at": existente.capturado_at,
        "tecnico_nombre": tecnico.nombre if tecnico else None, "eta": existente.ventana_inicio,
        "severidad": severidad.nombre if severidad else None,
    }


async def _validar_y_resolver(db: AsyncSession, folio: Folio, equipo: Equipo, tipo_falla: TipoFalla, ahora: datetime,
                              request: Request | None) -> None:
    """Pasos 1, 2 y 4–8 (el 3, duplicado, se resuelve antes de insertar). Deja el folio en su estado resultante."""
    # 1. Confirmación de UN.
    if not folio.confirmacion_un:
        await _trigger(db, folio, TriggerRevision.confirmacion_un_faltante, "El operador no confirmó la unidad de negocio")
        from services import notificaciones_service

        await notificaciones_service.notificar(db, "folio.espera", [folio.capturado_por], {"folio_id": str(folio.id)}, asunto=f"Folio {folio.numero_folio} en espera",
                                               cuerpo="Confirma la unidad de negocio para continuar", url=f"/campo/folio/{folio.id}", tenant_id=folio.tenant_id,
                                               prestador_id=folio.prestador_id, canales=["app", "push"])
        return
    triggers: list[tuple[TriggerRevision, str]] = []
    # 2. Contrato activo.
    if not await catalogos_service.equipo_con_contrato_activo(db, equipo.id):
        contrato = await db.get(Contrato, equipo.contrato_id) if equipo.contrato_id else None
        detalle = (f"Contrato «{contrato.nombre}» vigente hasta {contrato.fecha_fin.isoformat()}" if contrato
                   else "El equipo no tiene contrato activo")
        triggers.append((TriggerRevision.sin_contrato, detalle))
        await _avisar_despachador(db, folio, f"Folio {folio.numero_folio}: equipo sin contrato activo", detalle)
    # 4. Severidad por la matriz.
    fila = await catalogos_service.resolver_severidad(db, folio.tenant_id, tipo_falla.id, equipo.tipo_equipo_id)
    if fila is None:
        tipo_equipo = await db.get(TipoEquipo, equipo.tipo_equipo_id)
        combinacion = f"{tipo_falla.descripcion} × {tipo_equipo.nombre if tipo_equipo else '?'}"
        triggers.append((TriggerRevision.severidad_no_configurada, f"Sin severidad en la matriz para «{combinacion}»"))
        # Mismo formato de datos que el evaluador de P02 (faltantes/ejemplos), referido al folio concreto.
        await alertas_service.disparar(db, "MATRIZ_SEVERIDAD_INCOMPLETA", tenant_id=folio.tenant_id, prestador_id=None,
                                       entidad_tipo="folio", entidad_id=folio.id,
                                       datos={"faltantes": 1, "ejemplos": [combinacion], "numero_folio": folio.numero_folio,
                                              "tipo_falla_id": str(tipo_falla.id), "tipo_equipo_id": str(equipo.tipo_equipo_id)})
    else:
        nivel, _flag = fila
        folio.severidad_id, folio.severidad_origen = nivel.id, SeveridadOrigen.automatica_matriz
    # 5. Garantía.
    politicas = await aprobacion_service.politicas_de(db, folio.tenant_id)
    if catalogos_service.en_garantia(equipo, ahora.date()) and politicas.revision_obligatoria_garantia:
        triggers.append((TriggerRevision.garantia, f"Equipo en garantía hasta {equipo.garantia_vigente_hasta.isoformat()}"))
    # 6. Flag global del tipo de falla.
    if tipo_falla.requiere_revision_manual:
        triggers.append((TriggerRevision.tipo_falla_flag, f"«{tipo_falla.descripcion}» requiere revisión manual (flag global)"))
    # 7. Horario de servicio del contrato.
    contrato = await folios_sla.contrato_vigente(db, equipo, ahora.date())
    if contrato is not None and contrato.horario_servicio_json:
        un = await db.get(UnidadNegocio, folio.un_id)
        if not dentro_de_horario(contrato.horario_servicio_json, ahora, un.zona_horaria if un else "America/Mexico_City"):
            detalle = f"Capturado fuera del horario de servicio del contrato «{contrato.nombre}»"
            triggers.append((TriggerRevision.fuera_horario, detalle))
            await _avisar_despachador(db, folio, f"Folio {folio.numero_folio} fuera de horario", detalle)
    # 8. Palabras clave de alerta.
    palabras = await keywords_detectadas(db, folio.prestador_id, folio.tenant_id, folio.descripcion)
    if palabras:
        triggers.append((TriggerRevision.keyword_alerta, "Palabras de alerta en la descripción: " + ", ".join(palabras)))
    # P08 §6.10.7: el folio de instalación de activo espera la OC del cliente; el flujo multinivel no se evalúa mientras tanto.
    if folio.es_instalacion_activo:
        triggers.append((TriggerRevision.pendiente_oc_cliente, "Instalación de activo: espera la OC autorizada en el ERP del cliente (§6.10.7)"))

    for tipo, detalle in triggers:
        await _trigger(db, folio, tipo, detalle)
    if triggers:
        await folio_estados.transicionar(db, folio, EstadoFolio.en_revision, ACTOR_SISTEMA,
                                         "Validación automática no resoluble: " + "; ".join(t.value for t, _ in triggers),
                                         {"triggers": [t.value for t, _ in triggers]}, request)
        return
    # P07 §6.10.5: el folio no crítico (severidad configurada por el tenant) espera la clasificación del Admin UN.
    from services import clasificacion_service

    if await clasificacion_service.requiere_clasificacion(db, folio):
        await _trigger(db, folio, TriggerRevision.pendiente_clasificacion, "Folio no crítico: pendiente de clasificación del Admin UN (§6.10.5)")
        await folio_estados.transicionar(db, folio, EstadoFolio.en_revision, ACTOR_SISTEMA, "Folio no crítico pendiente de clasificación (§6.10.5)",
                                         {"triggers": ["pendiente_clasificacion"]}, request)
        await clasificacion_service.notificar_pendiente(db, folio)
        return
    await aprobacion_service.evaluar_al_capturar(db, folio, equipo, request, ahora)


async def crear(db: AsyncSession, actor: Actor, datos: FolioEntrada, request: Request | None, ahora: datetime | None = None) -> Folio:
    ahora = ahora or datetime.now(UTC)
    un = await db.get(UnidadNegocio, datos.un_id)
    if un is None:
        raise ErrorAPI(422, "UNIDAD_INVALIDA", "La unidad de negocio no existe")
    if actor.dominio == Dominio.tenant:
        validar_tenant(actor, un.tenant_id)
        if actor.rol != Rol.admin_empresa:
            visible = (await db.execute(select(UnidadNegocio.id).where(UnidadNegocio.id == un.id, UnidadNegocio.id.in_(_unidades_visibles(actor))))).first()
            if visible is None:
                raise ErrorAPI(422, "UNIDAD_INVALIDA", "La unidad no está entre tus UNs asignadas")
    elif actor.es_superadmin and datos.tenant_id and datos.tenant_id != un.tenant_id:
        raise ErrorAPI(422, "UNIDAD_INVALIDA", "La unidad no pertenece al tenant indicado")
    tenant_id = un.tenant_id
    await exigir_puede_crear(db, actor, tenant_id)

    equipo = await db.get(Equipo, datos.equipo_id)
    if equipo is None or equipo.tenant_id != tenant_id or equipo.un_id != un.id:
        raise ErrorAPI(422, "EQUIPO_INVALIDO", "El equipo no existe o no pertenece a la unidad")
    if equipo.estado != EstadoActivo.activo:
        raise ErrorAPI(422, "EQUIPO_INVALIDO", "El equipo no está activo")
    tipo_falla = await db.get(TipoFalla, datos.tipo_falla_id)
    tipo_equipo = await db.get(TipoEquipo, equipo.tipo_equipo_id)
    if tipo_falla is None or not tipo_falla.activa or tipo_equipo is None or tipo_falla.familia_equipo_id != tipo_equipo.familia_id:
        raise ErrorAPI(422, "TIPO_FALLA_INVALIDO", "El tipo de falla no aplica a la familia del equipo")
    prestadores = await catalogos_service.prestadores_del_tenant(db, tenant_id)
    if tipo_falla.prestador_id not in prestadores:
        raise ErrorAPI(422, "TIPO_FALLA_INVALIDO", "El tipo de falla es de un prestador que no atiende a este cliente")
    if actor.dominio == Dominio.prestador and actor.prestador_id != tipo_falla.prestador_id:
        raise ErrorAPI(422, "TIPO_FALLA_INVALIDO", "El tipo de falla pertenece a otro prestador")
    prestador_id = tipo_falla.prestador_id

    # 3. Duplicado abierto (antes de insertar): bloqueo total o confirmación fuerte con justificación.
    existente = await _folio_abierto_del_equipo(db, equipo.id)
    if existente is not None:
        politicas = await aprobacion_service.politicas_de(db, tenant_id)
        if politicas.bloqueo_total_duplicados:
            await auditoria.registrar_actor(db, actor, "folio.duplicado_bloqueado", request, recurso_tipo="folio", recurso_id=existente.id,
                                            tenant_id=tenant_id, prestador_id=prestador_id,
                                            despues={"equipo_id": str(equipo.id), "folio_existente": existente.numero_folio})
            await db.commit()
            raise ErrorAPI(409, "FOLIO_DUPLICADO_BLOQUEADO",
                           f"Ya existe el folio abierto {existente.numero_folio} para este equipo y el cliente bloquea duplicados",
                           [{"folio_id": str(existente.id), "numero_folio": existente.numero_folio, "estado": existente.estado.value}])
        if not (datos.folio_duplicado_justificacion or "").strip():
            raise ErrorAPI(422, "JUSTIFICACION_REQUERIDA",
                           f"Ya existe el folio abierto {existente.numero_folio} para este equipo: indica en qué es diferente la falla",
                           [{"folio_id": str(existente.id), "numero_folio": existente.numero_folio, "estado": existente.estado.value}])
        datos.folio_duplicado_ref_id = existente.id
    else:
        datos.folio_duplicado_ref_id, datos.folio_duplicado_justificacion = None, None

    respuesta, version = None, None
    if datos.respuesta_id:
        respuesta = await db.get(FormularioRespuesta, datos.respuesta_id)
        if respuesta is None or respuesta.estado != EstadoRespuesta.enviado or respuesta.origen != OrigenRespuesta.folio_captura:
            raise ErrorAPI(422, "RESPUESTA_INVALIDA", "La respuesta del formulario de captura debe existir, ser de origen folio_captura y estar enviada")
        if respuesta.tenant_id not in (None, tenant_id):
            raise ErrorAPI(422, "RESPUESTA_INVALIDA", "La respuesta pertenece a otro cliente")
        if (await db.execute(select(FolioFormularioCaptura.id).where(FolioFormularioCaptura.respuesta_id == respuesta.id))).first():
            raise ErrorAPI(409, "RESPUESTA_YA_VINCULADA", "Esa respuesta ya está vinculada a otro folio")

    numero = (await db.execute(text("SELECT acma_siguiente_numero_folio(:t)"), {"t": tenant_id})).scalar_one()
    monto = datos.monto_estimado if actor.rol in FIJAN_MONTO else None
    folio = Folio(
        numero_folio=numero, tenant_id=tenant_id, prestador_id=prestador_id, un_id=un.id, equipo_id=equipo.id, tipo_falla_id=tipo_falla.id,
        tipo_folio=datos.tipo_folio, prioridad=datos.prioridad, descripcion=datos.descripcion.strip(),
        confirmacion_un=datos.confirmacion_un, confirmacion_un_timestamp=(datos.confirmacion_un_timestamp or ahora) if datos.confirmacion_un else None,
        confirmacion_un_geolat=datos.confirmacion_un_geolat, confirmacion_un_geolng=datos.confirmacion_un_geolng,
        folio_duplicado_justificacion=(datos.folio_duplicado_justificacion or "").strip() or None, folio_duplicado_ref_id=datos.folio_duplicado_ref_id,
        monto_estimado=monto, capturado_por=actor.id, capturado_at=ahora, geolat_captura=datos.geolat_captura, geolng_captura=datos.geolng_captura,
        fecha_falla=datos.fecha_falla or ahora,
    )
    db.add(folio)
    await db.flush()
    if respuesta is not None:
        version = await db.get(FormularioVersion, respuesta.version_id)
        db.add(FolioFormularioCaptura(folio_id=folio.id, tenant_id=tenant_id, prestador_id=prestador_id, respuesta_id=respuesta.id,
                                      formulario_id=respuesta.formulario_id, version_formulario=version.numero_version if version else 0))
        await db.flush()
    await folio_estados.registrar_historial(db, folio, actor, estado_anterior=None, estado_nuevo=EstadoFolio.capturado,
                                            notas="Folio capturado", contexto={"confirmacion_un": folio.confirmacion_un,
                                                                                "duplicado_de": str(existente.id) if existente else None})
    await auditoria.registrar_actor(db, actor, "folio.capturado", request, recurso_tipo="folio", recurso_id=folio.id, tenant_id=tenant_id,
                                    prestador_id=prestador_id, despues={"numero_folio": numero, "equipo_id": str(equipo.id),
                                                                        "tipo_falla": tipo_falla.descripcion, "duplicado_de": str(existente.id) if existente else None})
    await folio_estados.notificar_creacion(db, folio, actor)  # evento folio.creado (P05: chats del folio)
    if respuesta is not None and version is not None:
        # P08 §6.10.7: el operador clasifica el folio como instalación de activo en el formulario de captura.
        from schemas.formularios import EsquemaFormulario
        from services import oc_activos_service

        await oc_activos_service.desde_respuesta(db, actor, respuesta, EsquemaFormulario.model_validate(version.esquema_json), origen="captura", folio=folio, request=request)
    await _validar_y_resolver(db, folio, equipo, tipo_falla, ahora, request)
    return folio


async def confirmar_un(db: AsyncSession, actor: Actor, folio: Folio, geolat: float | None, geolng: float | None,
                       request: Request | None, ahora: datetime | None = None) -> Folio:
    """Completa la confirmación de UN de un folio en espera (paso 1) y vuelve a ejecutar las validaciones."""
    if folio.estado != EstadoFolio.capturado or folio.confirmacion_un:
        raise ErrorAPI(409, "CONFIRMACION_NO_APLICA", "El folio ya tiene confirmación de UN o no está en captura")
    if actor.rol not in CREAN_SIEMPRE and actor.id != folio.capturado_por:
        raise prohibido("Solo quien capturó el folio (o un rol de captura) confirma la unidad")
    ahora = ahora or datetime.now(UTC)
    folio.confirmacion_un, folio.confirmacion_un_timestamp = True, ahora
    folio.confirmacion_un_geolat, folio.confirmacion_un_geolng = geolat, geolng
    for t in (await db.execute(select(RevisionManualTrigger).where(
            RevisionManualTrigger.folio_id == folio.id, RevisionManualTrigger.trigger_tipo == TriggerRevision.confirmacion_un_faltante))).scalars():
        t.resuelto = True
    await db.flush()
    await folio_estados.comentar(db, folio, actor, "Unidad de negocio confirmada", {"geolat": geolat, "geolng": geolng}, evento="confirmacion_un")
    await auditoria.registrar_actor(db, actor, "folio.confirmacion_un", request, recurso_tipo="folio", recurso_id=folio.id,
                                    tenant_id=folio.tenant_id, prestador_id=folio.prestador_id, despues={"geolat": geolat, "geolng": geolng})
    equipo = await db.get(Equipo, folio.equipo_id)
    tipo_falla = await db.get(TipoFalla, folio.tipo_falla_id)
    await _validar_y_resolver(db, folio, equipo, tipo_falla, ahora, request)
    return folio


# ------------------------------------------------------------------ acciones

async def autorizar_manual(db: AsyncSession, actor: Actor, folio: Folio, notas: str, request: Request | None) -> Folio:
    """Despachador/Admin prestador resuelven la excepción de `en_revision`. Si el tenant tiene reglas de aprobación y aún no
    se evaluó el flujo para este folio, se inicia el flujo en lugar de autorizar (decisión pendiente de validación)."""
    if folio.estado != EstadoFolio.en_revision:
        raise ErrorAPI(409, "TRANSICION_NO_PERMITIDA", f"Autorizar aplica a folios en revisión (actual: {folio.estado.value})")
    if await aprobacion_service.flujo_abierto(db, folio.id):
        raise ErrorAPI(409, "FLUJO_ACTIVO", "El folio tiene un flujo de aprobación pendiente: decide con aprobar/rechazar")
    pendientes = (await db.execute(select(RevisionManualTrigger).where(
        RevisionManualTrigger.folio_id == folio.id, RevisionManualTrigger.resuelto.is_(False)))).scalars().all()
    for t in pendientes:
        t.resuelto = True
    if await aprobacion_service.ultimo_flujo(db, folio.id) is None:
        equipo = await db.get(Equipo, folio.equipo_id)
        reglas = await aprobacion_service.reglas_de(db, folio.tenant_id)
        nivel = aprobacion_service.nivel_entrada(reglas, monto=folio.monto_estimado, criticidad=equipo.criticidad, tipo_folio=folio.tipo_folio)
        if nivel is not None:
            await folio_estados.comentar(db, folio, actor, notas or "Revisión manual resuelta; inicia el flujo de aprobación",
                                         {"triggers_resueltos": [t.trigger_tipo.value for t in pendientes]}, evento="revision.resuelta")
            await aprobacion_service.evaluar_al_capturar(db, folio, equipo, request)
            return folio
    return await folio_estados.transicionar(db, folio, EstadoFolio.autorizado, actor, notas or "Autorizado tras revisión manual",
                                            {"triggers_resueltos": [t.trigger_tipo.value for t in pendientes]}, request)


async def tecnico_con_habilidad(db: AsyncSession, tecnico_usuario_id: UUID, folio: Folio) -> tuple[Usuario, bool, str | None]:
    """El técnico debe tener la habilidad de la familia del equipo (clave de habilidad ≈ familia; §6.8.6 'habilidad requerida')."""
    usuario = await db.get(Usuario, tecnico_usuario_id)
    if usuario is None or usuario.rol != Rol.tecnico or usuario.prestador_id != folio.prestador_id:
        raise ErrorAPI(422, "TECNICO_INVALIDO", "El técnico no existe o no es de este prestador")
    tecnico = (await db.execute(select(Tecnico).where(Tecnico.usuario_id == usuario.id))).scalar_one_or_none()
    equipo = await db.get(Equipo, folio.equipo_id)
    tipo = await db.get(TipoEquipo, equipo.tipo_equipo_id)
    from models.catalogos import FamiliaEquipo
    familia = await db.get(FamiliaEquipo, tipo.familia_id)
    if familia is None:
        return usuario, False, None
    requerida = familia.habilidad_clave or _normalizar(familia.nombre).replace(" ", "_")
    if tecnico is None:
        return usuario, False, requerida
    filas = (await db.execute(select(Habilidad.clave, Habilidad.nombre).join(TecnicoHabilidad, TecnicoHabilidad.habilidad_id == Habilidad.id)
                              .where(TecnicoHabilidad.tecnico_id == tecnico.id, Habilidad.activa.is_(True)))).all()
    req = _normalizar(requerida)
    tiene = any(_normalizar(clave) == req or _normalizar(nombre).startswith(req) or req.startswith(_normalizar(clave)) for clave, nombre in filas)
    if folio.plan_id:
        # P06: las tareas del plan exigen todas sus habilidades certificadas (§6.9.1).
        from models.preventivos import PlanTarea
        requeridas = set((await db.execute(select(PlanTarea.habilidad_requerida_id).where(
            PlanTarea.plan_id == folio.plan_id, PlanTarea.habilidad_requerida_id.is_not(None)))).scalars())
        if requeridas:
            certificadas = set((await db.execute(select(TecnicoHabilidad.habilidad_id).where(
                TecnicoHabilidad.tecnico_id == tecnico.id, TecnicoHabilidad.certificada.is_(True)))).scalars())
            faltan = requeridas - certificadas
            if faltan:
                nombres = (await db.execute(select(Habilidad.clave).where(Habilidad.id.in_(faltan)))).scalars().all()
                return usuario, False, f"{requerida} + plan: {', '.join(sorted(nombres))}"
    return usuario, tiene, requerida


async def asignar(db: AsyncSession, actor: Actor, folio: Folio, tecnico_id: UUID, razon: str | None, notas: str,
                  request: Request | None) -> Folio:
    folio_estados.exigir(actor, folio.estado, EstadoFolio.asignado)  # primero el rol (tabla §6.8.6), luego la habilidad
    usuario, tiene, requerida = await tecnico_con_habilidad(db, tecnico_id, folio)
    if not tiene:
        permitido = False
        if actor.rol == Rol.despachador:
            permisos = await permisos_service.efectivos_despachador(db, actor.prestador_id, actor.id, folio.tenant_id)
            permitido = any(p["clave"] == "asignar_tecnico_sin_habilidad" and p["habilitado"] for p in permisos)
        elif actor.es_superadmin:
            permitido = True
        if not permitido:
            raise ErrorAPI(409, "TECNICO_SIN_HABILIDAD", f"{usuario.nombre} no tiene la habilidad requerida ({requerida})",
                           [{"habilidad_requerida": requerida}])
        if not (razon or "").strip():
            raise ErrorAPI(422, "RAZON_REQUERIDA", "Asignar sin la habilidad requerida exige razón")
    tecnico = (await db.execute(select(Tecnico).where(Tecnico.usuario_id == usuario.id))).scalar_one_or_none()
    contexto = {"tecnico_id": str(usuario.id), "tecnico_nombre": usuario.nombre, "sin_habilidad": not tiene, "razon": razon,
                "vehiculo": tecnico.vehiculo_placas if tecnico else None}
    destino = EstadoFolio.asignado
    return await folio_estados.transicionar(db, folio, destino, actor, notas or f"Asignado a {usuario.nombre}", contexto, request)


async def fijar_monto(db: AsyncSession, actor: Actor, folio: Folio, monto: Decimal, request: Request | None) -> Folio:
    if actor.rol not in FIJAN_MONTO:
        raise prohibido("Solo Mesa de control, Despachador o Admin prestador fijan el monto estimado")
    if folio.estado not in (EstadoFolio.capturado, EstadoFolio.en_revision):
        raise ErrorAPI(409, "MONTO_NO_EDITABLE", "El monto estimado solo se fija en capturado o en revisión")
    antes = folio.monto_estimado
    folio.monto_estimado = monto
    await db.flush()
    await auditoria.registrar_actor(db, actor, "folio.monto_estimado", request, recurso_tipo="folio", recurso_id=folio.id,
                                    tenant_id=folio.tenant_id, prestador_id=folio.prestador_id,
                                    antes={"monto_estimado": antes}, despues={"monto_estimado": monto})
    return folio


async def override_severidad(db: AsyncSession, actor: Actor, folio: Folio, severidad_id: UUID, razon: str, request: Request | None) -> Folio:
    if actor.rol not in OVERRIDE_SEVERIDAD:
        raise prohibido("Solo Despachador o Admin prestador cambian la severidad")
    if folio.estado != EstadoFolio.en_revision:
        raise ErrorAPI(409, "SEVERIDAD_NO_EDITABLE", "La severidad solo se cambia en revisión")
    nivel = await db.get(NivelSeveridadCatalogo, severidad_id)
    if nivel is None or nivel.prestador_id != folio.prestador_id:
        raise ErrorAPI(422, "SEVERIDAD_INVALIDA", "Nivel de severidad inexistente o de otro prestador")
    antes = {"severidad_id": folio.severidad_id, "severidad_origen": folio.severidad_origen.value}
    folio.severidad_id, folio.severidad_origen = nivel.id, SeveridadOrigen.override_admin
    for t in (await db.execute(select(RevisionManualTrigger).where(
            RevisionManualTrigger.folio_id == folio.id, RevisionManualTrigger.trigger_tipo == TriggerRevision.severidad_no_configurada,
            RevisionManualTrigger.resuelto.is_(False)))).scalars():
        t.resuelto = True
    await db.flush()
    await folio_estados.comentar(db, folio, actor, f"Severidad cambiada a {nivel.nombre}: {razon}",
                                 {"severidad_id": str(nivel.id), "razon": razon}, evento="severidad.override")
    await auditoria.registrar_actor(db, actor, "folio.severidad_override", request, recurso_tipo="folio", recurso_id=folio.id,
                                    tenant_id=folio.tenant_id, prestador_id=folio.prestador_id, antes=antes,
                                    despues={"severidad_id": nivel.id, "severidad_origen": "override_admin", "razon": razon})
    return folio


async def vincular_atencion(db: AsyncSession, actor: Actor, folio: Folio, respuesta_id: UUID, request: Request | None) -> FolioFormularioAtencion:
    """Vincula la respuesta enviada del formulario de atención del técnico y registra sus evidencias (firma, fotos)."""
    if actor.rol == Rol.tecnico and folio.tecnico_id != actor.id:
        raise prohibido("El folio no está asignado a ti")
    if folio.estado not in (EstadoFolio.en_ejecucion, EstadoFolio.pendiente_refaccion):
        raise ErrorAPI(409, "ATENCION_NO_APLICA", "El formulario de atención se vincula con el folio en ejecución")
    r = await db.get(FormularioRespuesta, respuesta_id)
    if r is None or r.estado != EstadoRespuesta.enviado or r.origen != OrigenRespuesta.folio_atencion:
        raise ErrorAPI(422, "RESPUESTA_INVALIDA", "La respuesta debe ser de origen folio_atencion y estar enviada")
    if r.referencia_id not in (None, folio.id):
        raise ErrorAPI(422, "RESPUESTA_INVALIDA", "La respuesta hace referencia a otro folio")
    if (await db.execute(select(FolioFormularioAtencion.id).where(FolioFormularioAtencion.folio_id == folio.id))).first():
        raise ErrorAPI(409, "ATENCION_YA_VINCULADA", "El folio ya tiene formulario de atención")
    version = await db.get(FormularioVersion, r.version_id)
    v = FolioFormularioAtencion(folio_id=folio.id, tenant_id=folio.tenant_id, prestador_id=folio.prestador_id, respuesta_id=r.id,
                                formulario_id=r.formulario_id, version_formulario=version.numero_version if version else 0)
    db.add(v)
    evidencias = (await db.execute(select(FormularioEvidencia).where(FormularioEvidencia.respuesta_id == r.id))).scalars().all()
    for e in evidencias:
        tipo = TipoEvidenciaFolio.firma if e.tipo == TipoEvidencia.firma else TipoEvidenciaFolio.despues
        db.add(FolioEvidencia(folio_id=folio.id, tenant_id=folio.tenant_id, prestador_id=folio.prestador_id, evidencia_id=e.id, tipo=tipo,
                              archivo_key=e.archivo_key, geolat=e.geolat, geolng=e.geolng, timestamp_captura=e.created_at,
                              subido_por=r.respondido_por))
    await db.flush()
    await folio_estados.comentar(db, folio, actor, "Formulario de atención vinculado", {"respuesta_id": str(r.id), "evidencias": len(evidencias)},
                                 evento="atencion.vinculada")
    await auditoria.registrar_actor(db, actor, "folio.atencion_vinculada", request, recurso_tipo="folio", recurso_id=folio.id,
                                    tenant_id=folio.tenant_id, prestador_id=folio.prestador_id, despues={"respuesta_id": r.id})
    return v


async def agregar_evidencia(db: AsyncSession, actor: Actor, folio: Folio, tipo: TipoEvidenciaFolio, evidencia_id: UUID | None,
                            archivo_key: str | None, geolat: float | None, geolng: float | None) -> FolioEvidencia:
    if folio.estado in (EstadoFolio.cerrado, EstadoFolio.cancelado):
        raise ErrorAPI(409, "FOLIO_INMUTABLE", "El folio está cerrado o cancelado")
    if evidencia_id:
        e = await db.get(FormularioEvidencia, evidencia_id)
        if e is None:
            raise no_encontrado("Evidencia")
        archivo_key, geolat, geolng = e.archivo_key, e.geolat, e.geolng
    fila = FolioEvidencia(folio_id=folio.id, tenant_id=folio.tenant_id, prestador_id=folio.prestador_id, evidencia_id=evidencia_id, tipo=tipo,
                          archivo_key=archivo_key, geolat=geolat, geolng=geolng, subido_por=actor.id)
    db.add(fila)
    await db.flush()
    return fila


# ------------------------------------------------------------------ lecturas

async def listar(db: AsyncSession, actor: Actor, *, tenant_id: UUID | None, un_id: UUID | None, grupo_id: UUID | None,
                 estado: list[EstadoFolio] | None, severidad_id: UUID | None, tecnico_id: UUID | None, desde: datetime | None,
                 hasta: datetime | None, tipo_folio: str | None, q: str | None, limite: int) -> list[Folio]:
    consulta = select(Folio).order_by(Folio.capturado_at.desc()).limit(limite)
    filtro = filtro_alcance(actor)
    if filtro is not None:
        consulta = consulta.where(filtro)
    if tenant_id:
        consulta = consulta.where(Folio.tenant_id == tenant_id)
    if un_id:
        consulta = consulta.where(Folio.un_id == un_id)
    if grupo_id:
        consulta = consulta.where(Folio.un_id.in_(select(GrupoUNMiembro.unidad_id).where(GrupoUNMiembro.grupo_id == grupo_id)))
    if estado:
        consulta = consulta.where(Folio.estado.in_(estado))
    if severidad_id:
        consulta = consulta.where(Folio.severidad_id == severidad_id)
    if tecnico_id:
        consulta = consulta.where(Folio.tecnico_id == tecnico_id)
    if desde:
        consulta = consulta.where(Folio.capturado_at >= desde)
    if hasta:
        consulta = consulta.where(Folio.capturado_at <= hasta)
    if tipo_folio:
        consulta = consulta.where(Folio.tipo_folio == tipo_folio)
    if q:
        patron = f"%{q.lower()}%"
        consulta = consulta.where(or_(func.lower(Folio.numero_folio).like(patron), func.lower(Folio.descripcion).like(patron)))
    return list((await db.execute(consulta)).scalars())


async def resumen(db: AsyncSession, folios: list[Folio], ahora: datetime | None = None) -> list[dict[str, Any]]:
    """Enriquece la lista con UN, equipo, severidad, técnico, flujo activo y triggers pendientes (consultas por lote)."""
    if not folios:
        return []
    ahora = ahora or datetime.now(UTC)
    ids = [f.id for f in folios]
    unidades = {u.id: u for u in (await db.execute(select(UnidadNegocio).where(UnidadNegocio.id.in_({f.un_id for f in folios})))).scalars()}
    equipos = {e.id: e for e in (await db.execute(select(Equipo).where(Equipo.id.in_({f.equipo_id for f in folios})))).scalars()}
    fallas = {t.id: t for t in (await db.execute(select(TipoFalla).where(TipoFalla.id.in_({f.tipo_falla_id for f in folios if f.tipo_falla_id})))).scalars()}
    severidades = {n.id: n for n in (await db.execute(select(NivelSeveridadCatalogo).where(
        NivelSeveridadCatalogo.id.in_({f.severidad_id for f in folios if f.severidad_id})))).scalars()}
    usuarios_ids = {f.tecnico_id for f in folios if f.tecnico_id} | {f.capturado_por for f in folios}
    usuarios = {u.id: u for u in (await db.execute(select(Usuario).where(Usuario.id.in_(usuarios_ids)))).scalars()}
    flujos = {fl.folio_id: fl for fl in (await db.execute(select(AprobacionFlujo).where(
        AprobacionFlujo.folio_id.in_(ids)).order_by(AprobacionFlujo.iniciado_at))).scalars()}
    timeouts = {t.flujo_id: t.vence_at for t in (await db.execute(select(AprobacionAlertaTimeout).where(
        AprobacionAlertaTimeout.folio_id.in_(ids), AprobacionAlertaTimeout.procesado.is_(False)))).scalars()}
    triggers = {}
    for folio_id, n in (await db.execute(select(RevisionManualTrigger.folio_id, func.count()).where(
            RevisionManualTrigger.folio_id.in_(ids), RevisionManualTrigger.resuelto.is_(False)).group_by(RevisionManualTrigger.folio_id))).all():
        triggers[folio_id] = n
    niveles_cache: dict[UUID, dict] = {}
    planes: dict[UUID, str] = {}
    if any(f.plan_id for f in folios):
        from models.preventivos import PlanMantenimiento
        planes = {p.id: p.nombre for p in (await db.execute(select(PlanMantenimiento).where(PlanMantenimiento.id.in_({f.plan_id for f in folios if f.plan_id})))).scalars()}
    salida = []
    for f in folios:
        un, eq, tf, sev = unidades.get(f.un_id), equipos.get(f.equipo_id), fallas.get(f.tipo_falla_id), severidades.get(f.severidad_id)
        fl = flujos.get(f.id)
        flujo = None
        if fl is not None:
            if f.tenant_id not in niveles_cache:  # con setdefault el await corre por cada folio con flujo (P11a)
                niveles_cache[f.tenant_id] = await aprobacion_service.niveles_de(db, f.tenant_id)
            niveles = niveles_cache[f.tenant_id]
            cfg = niveles.get(fl.nivel_actual)
            flujo = {"id": fl.id, "nivel_actual": fl.nivel_actual, "nivel_maximo_requerido": fl.nivel_maximo_requerido, "estado": fl.estado,
                     "iniciado_at": fl.iniciado_at, "resuelto_at": fl.resuelto_at, "rol_aprobador_actual": cfg.rol_aprobador if cfg else None,
                     "vence_at": timeouts.get(fl.id)}
        salida.append({
            **{k: getattr(f, k) for k in ("id", "created_at", "updated_at", "version_hash", "numero_folio", "tenant_id", "prestador_id", "un_id",
                                          "equipo_id", "tipo_falla_id", "tipo_folio", "estado", "prioridad", "descripcion", "tecnico_id",
                                          "severidad_origen", "confirmacion_un", "monto_estimado", "capturado_por", "capturado_at", "fecha_falla",
                                          "fecha_inicio_atencion", "fecha_cierre", "razon_cancelacion", "plan_id", "calendario_id",
                                          "es_instalacion_activo", "equipo_instalado_id", "trabajo_especial_id")},
            "plan_nombre": planes.get(f.plan_id),
            "un_nombre": un.nombre if un else None, "un_codigo": un.codigo if un else None,
            "equipo_codigo": eq.codigo if eq else None, "equipo_nombre": eq.nombre if eq else None, "criticidad": eq.criticidad if eq else None,
            "tipo_falla": tf.descripcion if tf else None,
            "tecnico_nombre": usuarios[f.tecnico_id].nombre if f.tecnico_id in usuarios else None,
            "capturado_por_nombre": usuarios[f.capturado_por].nombre if f.capturado_por in usuarios else None,
            "severidad": {"id": sev.id, "clave": sev.clave, "nombre": sev.nombre, "orden": sev.orden, "color_hex": sev.color_hex} if sev else None,
            "flujo": flujo, "triggers_pendientes": triggers.get(f.id, 0),
            "antiguedad_horas": round((ahora - f.capturado_at).total_seconds() / 3600, 1),
        })
    return salida


async def historial(db: AsyncSession, folio: Folio) -> list[dict[str, Any]]:
    filas = (await db.execute(select(FolioEstadoHistorial).where(FolioEstadoHistorial.folio_id == folio.id)
                              .order_by(FolioEstadoHistorial.timestamp, FolioEstadoHistorial.id))).scalars().all()
    ids = {h.actor_id for h in filas if h.actor_id}
    nombres = {u.id: u.nombre for u in (await db.execute(select(Usuario).where(Usuario.id.in_(ids)))).scalars()} if ids else {}
    return [{"id": h.id, "evento": h.evento, "estado_anterior": h.estado_anterior, "estado_nuevo": h.estado_nuevo, "actor_id": h.actor_id,
             "actor_rol": h.actor_rol, "actor_nombre": nombres.get(h.actor_id), "timestamp": h.timestamp, "notas": h.notas,
             "datos_contexto_json": h.datos_contexto_json} for h in filas]


async def _vinculo(db: AsyncSession, v) -> dict[str, Any] | None:
    if v is None:
        return None
    r = await db.get(FormularioRespuesta, v.respuesta_id)
    f = await db.get(Formulario, v.formulario_id)
    return {"respuesta_id": v.respuesta_id, "formulario_id": v.formulario_id, "formulario_nombre": f.nombre if f else None,
            "version_formulario": v.version_formulario, "timestamp": v.timestamp, "respuestas_json": r.respuestas_json if r else {}}


async def _seguimiento_p07(db: AsyncSession, folio: Folio) -> dict[str, Any]:
    """Hallazgos del folio, registros en los módulos de seguimiento (rechazo §6.8.7, minuta §7.4 o clasificación §6.10.5) y clasificación."""
    from models.minutas import Hallazgo
    from models.seguimiento import Cotizacion, FolioClasificacion, HallazgoPresupuesto, Reprogramacion, SeguimientoInterno
    from services import hallazgos_service

    hallazgos = list((await db.execute(select(Hallazgo).where(Hallazgo.folio_id == folio.id).order_by(Hallazgo.timestamp))).scalars())
    derivaciones = []
    for modulo, modelo, ruta in (("cotizaciones", Cotizacion, "cotizaciones"), ("por_presupuesto", HallazgoPresupuesto, "presupuesto"),
                                 ("seguimiento_interno", SeguimientoInterno, "interno"), ("reprogramacion", Reprogramacion, "reprogramacion")):
        for r in (await db.execute(select(modelo).where(modelo.folio_id == folio.id))).scalars():
            derivaciones.append({"modulo": modulo, "ruta": ruta, "registro_id": r.id, "estado": r.estado.value, "origen": r.origen, "descripcion": r.descripcion,
                                 "numero": getattr(r, "numero", None), "created_at": r.created_at})
    clasificacion = (await db.execute(select(FolioClasificacion).where(FolioClasificacion.folio_id == folio.id))).scalar_one_or_none()
    return {"hallazgos": await hallazgos_service.enriquecer(db, hallazgos), "derivaciones": derivaciones,
            "clasificacion": {"opcion": clasificacion.opcion_clasificacion.value, "timestamp": clasificacion.timestamp, "dentro_de_plazo": clasificacion.dentro_de_plazo,
                              "horas_retraso": str(clasificacion.horas_retraso), "fecha_tentativa": clasificacion.fecha_tentativa, "modulo_destino": clasificacion.modulo_destino.value if clasificacion.modulo_destino else None,
                              "modulo_registro_id": clasificacion.modulo_registro_id, "admin_un_id": clasificacion.admin_un_id, "notas": clasificacion.notas} if clasificacion else None}


async def _p08(db: AsyncSession, folio: Folio) -> dict[str, Any]:
    """Trabajo especial vinculado (§6.10.6) y trámite de OC del activo (§6.10.7)."""
    from models.trabajos_especiales import TrabajoEspecial
    from services import oc_activos_service

    te = await db.get(TrabajoEspecial, folio.trabajo_especial_id) if folio.trabajo_especial_id else None
    return {"oc_activo": await oc_activos_service.detalle_folio(db, folio) if folio.es_instalacion_activo else None,
            "trabajo_especial": {"id": te.id, "numero": te.numero, "estado": te.estado.value, "urgencia": te.urgencia, "descripcion": te.descripcion, "monto": str(te.monto) if te.monto is not None else None,
                                 "fecha_programada": te.fecha_programada, "tecnico_responsable_id": te.tecnico_responsable_id, "tecnicos": te.tecnico_ids_json} if te else None}


async def _financiero(db: AsyncSession, actor: Actor, folio: Folio) -> dict[str, Any]:
    """P09: costo del folio, refacciones con su importe y gastos de caja chica (§6.8.6 «datos financieros»)."""
    from services import costos_service

    return await costos_service.detalle_financiero(db, actor, folio) or {}


async def _reasignaciones(db: AsyncSession, folio: Folio) -> list[dict[str, Any]]:
    from services import reasignacion_service  # import local: reasignacion_service depende de este módulo

    return await reasignacion_service.historial_folio(db, folio.id)


async def detalle(db: AsyncSession, actor: Actor, folio: Folio) -> dict[str, Any]:
    base = (await resumen(db, [folio]))[0]
    un = await db.get(UnidadNegocio, folio.un_id)
    equipo = await db.get(Equipo, folio.equipo_id)
    ref = await db.get(Folio, folio.folio_duplicado_ref_id) if folio.folio_duplicado_ref_id else None
    captura = {
        "capturado_por": folio.capturado_por, "capturado_por_nombre": base["capturado_por_nombre"], "capturado_at": folio.capturado_at,
        "un": {"id": un.id, "codigo": un.codigo, "nombre": un.nombre, "direccion": un.direccion} if un else {},
        "equipo": {"id": equipo.id, "codigo": equipo.codigo, "nombre": equipo.nombre, "criticidad": equipo.criticidad,
                   "garantia_vigente_hasta": equipo.garantia_vigente_hasta} if equipo else {},
        "tipo_falla": base["tipo_falla"], "descripcion": folio.descripcion, "geolat_captura": folio.geolat_captura, "geolng_captura": folio.geolng_captura,
        "confirmacion_un": folio.confirmacion_un, "confirmacion_un_timestamp": folio.confirmacion_un_timestamp,
        "confirmacion_un_geolat": folio.confirmacion_un_geolat, "confirmacion_un_geolng": folio.confirmacion_un_geolng,
        "folio_duplicado_justificacion": folio.folio_duplicado_justificacion, "folio_duplicado_ref_id": folio.folio_duplicado_ref_id,
        "folio_duplicado_ref_numero": ref.numero_folio if ref else None,
    }
    hist = await historial(db, folio)
    ultima_asignacion = next((h for h in reversed(hist) if h["evento"] == "transicion" and h["estado_nuevo"] == EstadoFolio.asignado), None)
    # El vehículo viene del historial (se guardó al asignar): los usuarios del tenant no leen la tabla `tecnicos` (RLS).
    asignacion = {"tecnico_id": folio.tecnico_id, "tecnico_nombre": base["tecnico_nombre"],
                  "asignado_at": ultima_asignacion["timestamp"] if ultima_asignacion else None,
                  "vehiculo": (ultima_asignacion["datos_contexto_json"].get("vehiculo") if ultima_asignacion else None), "orden_en_ruta": folio.orden_en_ruta,
                  "ventana_inicio": folio.ventana_inicio, "ventana_fin": folio.ventana_fin}
    cap = (await db.execute(select(FolioFormularioCaptura).where(FolioFormularioCaptura.folio_id == folio.id))).scalar_one_or_none()
    ate = (await db.execute(select(FolioFormularioAtencion).where(FolioFormularioAtencion.folio_id == folio.id))).scalar_one_or_none()
    evidencias = (await db.execute(select(FolioEvidencia).where(FolioEvidencia.folio_id == folio.id).order_by(FolioEvidencia.timestamp_captura))).scalars().all()
    refacciones = (await db.execute(select(FolioRefaccion).where(FolioRefaccion.folio_id == folio.id))).scalars().all()
    sla = (await db.execute(select(FolioSLA).where(FolioSLA.folio_id == folio.id))).scalar_one_or_none()
    encuesta = (await db.execute(select(FolioEncuesta).where(FolioEncuesta.folio_id == folio.id))).scalar_one_or_none()
    triggers = (await db.execute(select(RevisionManualTrigger).where(RevisionManualTrigger.folio_id == folio.id)
                                 .order_by(RevisionManualTrigger.timestamp))).scalars().all()
    decisiones = (await db.execute(select(AprobacionDecision).where(AprobacionDecision.folio_id == folio.id)
                                   .order_by(AprobacionDecision.timestamp))).scalars().all()
    nombres = {u.id: u.nombre for u in (await db.execute(select(Usuario).where(Usuario.id.in_({d.actor_id for d in decisiones if d.actor_id})))).scalars()} \
        if any(d.actor_id for d in decisiones) else {}
    flujo = await aprobacion_service.flujo_abierto(db, folio.id)
    puede_aprobar = bool(flujo) and folio.estado == EstadoFolio.en_revision and await aprobacion_service.es_aprobador(db, actor, folio, flujo)
    return {
        "folio": base, "captura": captura, "formulario_captura": await _vinculo(db, cap), "asignacion": asignacion, "historial": hist,
        "reasignaciones": await _reasignaciones(db, folio), "evidencias": evidencias, **await _seguimiento_p07(db, folio), **await _p08(db, folio),
        "formulario_atencion": await _vinculo(db, ate), "refacciones": refacciones,
        "sla": sla, "encuesta": encuesta, "triggers_revision": triggers, "aprobacion": base["flujo"],
        "sla_contador": await sla_service.detalle(db, folio),  # P10: pausas, exclusiones y cumplimiento
        "financiero": await _financiero(db, actor, folio),
        "decisiones": [{"id": d.id, "flujo_id": d.flujo_id, "nivel": d.nivel, "actor_id": d.actor_id, "actor_nombre": nombres.get(d.actor_id),
                        "decision": d.decision, "razon_rechazo": d.razon_rechazo, "modulo_destino": d.modulo_destino,
                        "modulo_destino_id": d.modulo_destino_id, "canal": d.canal, "timestamp": d.timestamp, "notas": d.notas} for d in decisiones],
        "chat": [], "acciones": folio_estados.destinos_de(actor, folio.estado), "puede_aprobar": puede_aprobar,
    }
