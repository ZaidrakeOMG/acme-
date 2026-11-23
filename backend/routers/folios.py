"""Folios (§4.1, §6.8.6, §6.8.7): captura con validaciones automáticas, ciclo de vida de 11 estados, archivo completo,
aprobación multinivel y configuración del flujo."""
from datetime import datetime
from uuid import UUID

from datetime import datetime as _dt

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from sqlalchemy import select

from core.dependencias import DB, Actor, ActorActual, requiere_rol
from core.errors import ErrorAPI, no_encontrado, prohibido
from models.base import Dominio, Rol
from models.folios import EstadoFolio, FolioKeywordAlerta, FolioRefaccion
from routers.catalogos_equipos import tenant_de
from routers.catalogos_tecnicos import prestador_de
from schemas.comun import RESPUESTAS_ERROR, Mensaje
from schemas.costos import FinancieroSalida, ValidarCostoEntrada  # P09
from schemas.folios import (
    AprobarEntrada, AsignarEntrada, AtencionEntrada, ConfiguracionAprobacion, ConfirmacionUNEntrada, EvidenciaFolioEntrada,
    EvidenciaFolioSalida, FlujoResumen, FolioDetalle, FolioEntrada, FolioResumen, HistorialSalida, KeywordEntrada, KeywordSalida,
    LlegadaEntrada, MontoEntrada, NivelConfigEntrada, NivelConfigSalida, NotasEntrada, PendienteAprobacion, PoliticasEntrada,
    PoliticasSalida, RazonEntrada, RechazarEntrada, RefaccionEntrada, RefaccionSalida, ReglaEntrada, ReglaSalida,
    SeveridadOverrideEntrada, TarjetaDuplicado, TransicionEntrada, TransicionTabla, VinculoFormularioSalida,
)
from schemas.sync import EncuestaEntrada, EncuestaSalida
from schemas.rastreo_folio import ConsentimientoUbicacion, PuntoUbicacionUsuario, MiRastreoFolio
from services import aprobacion_service, auditoria, folio_cierre_service, folio_estados
from services import folios_captura_service as svc
from services import rastreo_folios_service as rastreo

router = APIRouter(prefix="/api/folios", tags=["Folios"], responses=RESPUESTAS_ERROR)

TODOS = requiere_rol(*Rol)
CAPTURA = requiere_rol(Rol.superadmin, Rol.operador, Rol.admin_un, Rol.admin_empresa, Rol.supervisor_operadores, Rol.mesa_control,
                       Rol.tecnico, Rol.despachador)
ADMIN_TENANT = requiere_rol(Rol.superadmin, Rol.admin_empresa)
ADMIN_PRESTADOR = requiere_rol(Rol.superadmin, Rol.admin_prestador)
APROBADORES = requiere_rol(Rol.superadmin, Rol.admin_un, Rol.supervisor_operadores, Rol.admin_empresa)


async def _resumen(db, folio) -> FolioResumen:
    return FolioResumen(**(await svc.resumen(db, [folio]))[0])


def _politicas_salida(p) -> PoliticasSalida:
    return PoliticasSalida(**{k: getattr(p, k) for k in PoliticasSalida.model_fields})


def _tenant_configuracion(actor: Actor, tenant_id: UUID | None) -> UUID:
    """Configuración del flujo: el tenant del Admin empresa; superadmin indica ?tenant_id=."""
    return tenant_de(actor, tenant_id)



# Compartir solamente el GPS del usuario autenticado: exige opt-in desde su dispositivo.
# No acepta identificadores de otros usuarios ni permite activarlo remotamente.
@router.get("/{folio_id}/mi-rastreo", response_model=MiRastreoFolio)
async def mi_rastreo(folio_id: UUID, db: DB, actor: ActorActual):
    return await rastreo.mi_estado(db, actor, folio_id)


@router.post("/{folio_id}/compartir-ubicacion", response_model=MiRastreoFolio)
async def iniciar_rastreo(folio_id: UUID, datos: ConsentimientoUbicacion, db: DB, actor: ActorActual):
    if datos.acepto is not True:
        raise ErrorAPI(422, "CONSENTIMIENTO_REQUERIDO",
                       "Debes aceptar compartir TU posicion mientras el folio esta abierto")
    salida = await rastreo.empezar(db, actor, folio_id)
    await db.commit()
    return salida


@router.put("/{folio_id}/compartir-ubicacion", response_model=MiRastreoFolio)
async def actualizar_rastreo(folio_id: UUID, datos: PuntoUbicacionUsuario, db: DB, actor: ActorActual):
    salida = await rastreo.actualizar(db, actor, folio_id, datos.lat, datos.lng, datos.precision_m)
    await db.commit()
    return salida


@router.post("/{folio_id}/detener-ubicacion", response_model=MiRastreoFolio)
async def detener_rastreo(folio_id: UUID, db: DB, actor: ActorActual):
    salida = await rastreo.detener(db, actor, folio_id)
    await db.commit()
    return salida


# --------------------------------------------------------------- catálogo

@router.get("/transiciones", response_model=list[TransicionTabla], summary="Tabla de transiciones §6.8.6",
            description="Estado origen → destino → roles que pueden ejecutarla (incluido `sistema`). Es la misma tabla que usa el motor.")
async def transiciones(_: ActorActual):
    return folio_estados.tabla_transiciones()


@router.get("/verificar-duplicado", response_model=TarjetaDuplicado, summary="¿Hay folio abierto para el equipo?",
            description="Tarjeta enriquecida de §6.8.6: estado del folio existente y, de Asignado en adelante, técnico y ETA.")
async def verificar_duplicado(db: DB, equipo_id: UUID, actor: Actor = Depends(CAPTURA)):
    return TarjetaDuplicado(**await svc.tarjeta_duplicado(db, actor, equipo_id))


@router.get("/pendientes-aprobacion", response_model=list[PendienteAprobacion], summary="Bandeja del aprobador",
            description="Folios con flujo abierto cuyo nivel actual corresponde al rol del usuario y cuya UN puede ver.")
async def pendientes_aprobacion(db: DB, actor: Actor = Depends(APROBADORES)):
    salida = []
    for folio, flujo, config in await aprobacion_service.pendientes_para(db, actor):
        r = await _resumen(db, folio)
        salida.append(PendienteAprobacion(folio=r, flujo=r.flujo or FlujoResumen(
            id=flujo.id, nivel_actual=flujo.nivel_actual, nivel_maximo_requerido=flujo.nivel_maximo_requerido, estado=flujo.estado,
            iniciado_at=flujo.iniciado_at, resuelto_at=flujo.resuelto_at, rol_aprobador_actual=config.rol_aprobador if config else None),
            vence_at=r.flujo.vence_at if r.flujo else None))
    return salida


# ---------------------------------------------------------- configuración

@router.get("/politicas", response_model=PoliticasSalida, summary="Políticas de folios del tenant")
async def politicas(db: DB, actor: ActorActual, tenant_id: UUID | None = None):
    t = actor.tenant_id if actor.dominio == Dominio.tenant else tenant_id
    if t is None:
        raise ErrorAPI(422, "TENANT_REQUERIDO", "Indica tenant_id")
    return _politicas_salida(await aprobacion_service.politicas_de(db, t))


@router.put("/politicas", response_model=PoliticasSalida, summary="Cambiar políticas (bloqueo de duplicados, garantía, críticos, prefijo)",
            description="Admin empresa; el Admin prestador puede fijar `revision_obligatoria_garantia` de sus clientes (§6.8.6).")
async def politicas_put(datos: PoliticasEntrada, request: Request, db: DB, actor: ActorActual, tenant_id: UUID | None = None):
    if actor.rol not in (Rol.superadmin, Rol.admin_empresa, Rol.admin_prestador):
        raise prohibido("Solo Admin empresa (o Admin prestador para la revisión por garantía)")
    t = actor.tenant_id if actor.dominio == Dominio.tenant else tenant_id
    if t is None:
        raise ErrorAPI(422, "TENANT_REQUERIDO", "Indica tenant_id")
    cambios = datos.model_dump(exclude_unset=True, exclude_none=True)
    if actor.rol == Rol.admin_prestador and set(cambios) - {"revision_obligatoria_garantia"}:
        raise prohibido("El Admin prestador solo configura revision_obligatoria_garantia")
    p = await aprobacion_service.politicas_de(db, t)
    antes = _politicas_salida(p).model_dump(mode="json")
    for k, v in cambios.items():
        setattr(p, k, v)
    await db.flush()
    await auditoria.registrar_actor(db, actor, "folios.politicas", request, recurso_tipo="folio_politicas_tenant", recurso_id=p.id,
                                    tenant_id=t, antes=antes, despues=cambios)
    await db.commit()
    return _politicas_salida(p)


@router.get("/keywords", response_model=list[KeywordSalida], summary="Palabras de alerta del prestador")
async def keywords(db: DB, actor: Actor = Depends(requiere_rol(Rol.superadmin, Rol.admin_prestador, Rol.mesa_control, Rol.despachador)),
                   prestador_id: UUID | None = None):
    p = prestador_de(actor, prestador_id)
    filas = (await db.execute(select(FolioKeywordAlerta).where(FolioKeywordAlerta.prestador_id == p).order_by(FolioKeywordAlerta.palabra))).scalars()
    return [KeywordSalida.model_validate(k, from_attributes=True) for k in filas]


@router.put("/keywords", response_model=list[KeywordSalida], summary="Reemplazar palabras de alerta")
async def keywords_put(datos: list[KeywordEntrada], request: Request, db: DB, actor: Actor = Depends(ADMIN_PRESTADOR),
                       prestador_id: UUID | None = None):
    p = prestador_de(actor, prestador_id)
    actuales = (await db.execute(select(FolioKeywordAlerta).where(FolioKeywordAlerta.prestador_id == p))).scalars().all()
    for k in actuales:
        await db.delete(k)
    await db.flush()
    nuevas = [FolioKeywordAlerta(prestador_id=p, **d.model_dump()) for d in datos]
    db.add_all(nuevas)
    await db.flush()
    await auditoria.registrar_actor(db, actor, "folios.keywords", request, recurso_tipo="prestador", recurso_id=p, prestador_id=p,
                                    antes={"palabras": [k.palabra for k in actuales]}, despues={"palabras": [k.palabra for k in nuevas]})
    await db.commit()
    return [KeywordSalida.model_validate(k, from_attributes=True) for k in nuevas]


@router.get("/aprobacion/configuracion", response_model=ConfiguracionAprobacion, summary="Configuración del flujo multinivel",
            description="Políticas, reglas por criterio y configuración de los tres niveles (actor, tiempo límite, timeout).")
async def configuracion_aprobacion(db: DB, actor: Actor = Depends(requiere_rol(Rol.superadmin, Rol.admin_empresa, Rol.admin_un,
                                                                                 Rol.supervisor_operadores, Rol.admin_prestador,
                                                                                 Rol.mesa_control, Rol.despachador)),
                                   tenant_id: UUID | None = None):
    t = actor.tenant_id if actor.dominio == Dominio.tenant else tenant_id
    if t is None:
        raise ErrorAPI(422, "TENANT_REQUERIDO", "Indica tenant_id")
    return ConfiguracionAprobacion(
        politicas=_politicas_salida(await aprobacion_service.politicas_de(db, t)),
        reglas=[ReglaSalida.model_validate(r, from_attributes=True) for r in await aprobacion_service.reglas_de(db, t, solo_activas=False)],
        niveles=[NivelConfigSalida.model_validate(n, from_attributes=True) for n in sorted((await aprobacion_service.niveles_de(db, t)).values(), key=lambda n: n.nivel)],
    )


@router.put("/aprobacion/reglas", response_model=list[ReglaSalida], summary="Reemplazar reglas de activación",
            description="Umbrales A/B por monto, criticidad A/B → Nivel 2, tipo de trabajo. La regla más restrictiva gana.")
async def reglas_put(datos: list[ReglaEntrada], request: Request, db: DB, actor: Actor = Depends(ADMIN_TENANT), tenant_id: UUID | None = None):
    t = _tenant_configuracion(actor, tenant_id)
    creadas = await aprobacion_service.reemplazar_reglas(db, t, [d.model_dump() for d in datos])
    await auditoria.registrar_actor(db, actor, "folios.aprobacion_reglas", request, recurso_tipo="tenant", recurso_id=t, tenant_id=t,
                                    despues={"reglas": [d.model_dump(mode="json") for d in datos]})
    await db.commit()
    return [ReglaSalida.model_validate(r, from_attributes=True) for r in creadas]


@router.put("/aprobacion/niveles", response_model=list[NivelConfigSalida], summary="Configurar los niveles de aprobación",
            description="Nivel 1 Admin UN, Nivel 2 Supervisor de operadores (≈ supervisor regional), Nivel 3 Admin empresa. "
                        "El Nivel 3 solo admite bloquear_alertar o depende_criticidad.")
async def niveles_put(datos: list[NivelConfigEntrada], request: Request, db: DB, actor: Actor = Depends(ADMIN_TENANT), tenant_id: UUID | None = None):
    t = _tenant_configuracion(actor, tenant_id)
    filas = await aprobacion_service.reemplazar_niveles(db, t, [d.model_dump() for d in datos])
    await auditoria.registrar_actor(db, actor, "folios.aprobacion_niveles", request, recurso_tipo="tenant", recurso_id=t, tenant_id=t,
                                    despues={"niveles": [d.model_dump(mode="json") for d in datos]})
    await db.commit()
    return [NivelConfigSalida.model_validate(n, from_attributes=True) for n in filas]


# ------------------------------------------------------------- listado/alta

@router.get("", response_model=list[FolioResumen], summary="Listar folios",
            description="Alcance por rol (§5): Operador/Admin UN/Supervisor sus UNs; Admin empresa su tenant; roles del prestador los tenants que "
                        "atiende; Técnico solo los asignados a él. Filtros: tenant, UN, grupo de UNs, estado (repetible), severidad, técnico, fechas, tipo, q.")
async def listar(db: DB, actor: Actor = Depends(TODOS), tenant_id: UUID | None = None, un_id: UUID | None = None, grupo_id: UUID | None = None,
                 estado: list[EstadoFolio] | None = Query(default=None), severidad_id: UUID | None = None, tecnico_id: UUID | None = None,
                 desde: datetime | None = None, hasta: datetime | None = None, tipo_folio: str | None = None,
                 q: str | None = Query(default=None, max_length=100), limite: int = Query(default=200, ge=1, le=2000)):
    folios = await svc.listar(db, actor, tenant_id=tenant_id, un_id=un_id, grupo_id=grupo_id, estado=estado, severidad_id=severidad_id,
                              tecnico_id=tecnico_id, desde=desde, hasta=hasta, tipo_folio=tipo_folio, q=q, limite=limite)
    return [FolioResumen(**r) for r in await svc.resumen(db, folios)]


@router.post("", response_model=FolioResumen, status_code=201, summary="Capturar folio",
             description="Ejecuta las 8 validaciones automáticas de §6.8.6 en orden. Duplicado con bloqueo total → 409 FOLIO_DUPLICADO_BLOQUEADO; "
                         "sin bloqueo → 422 JUSTIFICACION_REQUERIDA hasta que se envíe `folio_duplicado_justificacion`. Técnico y Despachador "
                         "requieren su permiso configurable.")
async def crear(datos: FolioEntrada, request: Request, db: DB, actor: Actor = Depends(CAPTURA)):
    folio = await svc.crear(db, actor, datos, request)
    await db.commit()
    return await _resumen(db, folio)


@router.get("/{folio_id}", response_model=FolioDetalle, summary="Archivo completo del folio (§6.8.6)",
            description="Captura, formulario de captura, asignación, historial, evidencias, atención, refacciones, SLA, encuesta, triggers de "
                        "revisión, flujo y decisiones de aprobación. Chat (P05), reasignaciones (P06) y financiero (P09) vienen vacíos.")
async def detalle(folio_id: UUID, request: Request, db: DB, actor: Actor = Depends(TODOS)):
    folio = await svc.obtener(db, actor, folio_id)
    if folio.estado in (EstadoFolio.cerrado, EstadoFolio.cancelado):
        # §6.9.5: el historial de un folio cerrado es dato sensible.
        await auditoria.registrar_acceso_datos(db, actor, request, tabla="folios",
                                               recurso_id=folio.id, registros=1,
                                               detalle={"numero_folio": folio.numero_folio,
                                                         "estado": folio.estado.value})
        await db.commit()
    return FolioDetalle(**await svc.detalle(db, actor, folio))


@router.get("/{folio_id}/historial", response_model=list[HistorialSalida], summary="Historial inmutable de estados y eventos")
async def historial(folio_id: UUID, db: DB, actor: Actor = Depends(TODOS)):
    folio = await svc.obtener(db, actor, folio_id)
    return [HistorialSalida(**h) for h in await svc.historial(db, folio)]


# ------------------------------------------------------------- transiciones

async def _transicion(db, actor, folio_id, estado, notas="", contexto=None, request=None) -> FolioResumen:
    folio = await svc.obtener(db, actor, folio_id)
    await folio_estados.transicionar(db, folio, estado, actor, notas, contexto, request)
    await db.commit()
    return await _resumen(db, folio)


@router.post("/{folio_id}/transicion", response_model=FolioResumen, summary="Transición genérica (motor §6.8.6)",
             description="409 TRANSICION_NO_PERMITIDA si la tabla no la contempla para tu rol; 409 CIERRE_INCOMPLETO al cerrar sin atención o firma.")
async def transicion(folio_id: UUID, datos: TransicionEntrada, request: Request, db: DB, actor: Actor = Depends(TODOS)):
    folio = await svc.obtener(db, actor, folio_id)
    if datos.estado == EstadoFolio.asignado and datos.contexto.get("tecnico_id"):
        await svc.asignar(db, actor, folio, UUID(str(datos.contexto["tecnico_id"])), datos.contexto.get("razon"), datos.notas, request)
    elif datos.estado == EstadoFolio.autorizado and folio.estado == EstadoFolio.en_revision and not actor.es_superadmin:
        await svc.autorizar_manual(db, actor, folio, datos.notas, request)
    else:
        await folio_estados.transicionar(db, folio, datos.estado, actor, datos.notas, datos.contexto, request)
    await db.commit()
    return await _resumen(db, folio)


@router.post("/{folio_id}/autorizar", response_model=FolioResumen, summary="Autorizar (en revisión → autorizado)",
             description="Despachador/Admin prestador resuelven la excepción. Si el tenant tiene reglas de aprobación y el folio aún no pasó por el "
                         "flujo, en lugar de autorizar se inicia el flujo multinivel.")
async def autorizar(folio_id: UUID, datos: NotasEntrada, request: Request, db: DB, actor: Actor = Depends(TODOS)):
    folio = await svc.obtener(db, actor, folio_id)
    if actor.rol not in (Rol.despachador, Rol.admin_prestador, Rol.superadmin):
        raise ErrorAPI(409, "TRANSICION_NO_PERMITIDA", "Solo Despachador o Admin prestador autorizan en revisión",
                       [{"estado_actual": folio.estado.value, "destino": "autorizado", "roles_permitidos": ["admin_prestador", "despachador", "sistema"]}])
    await svc.autorizar_manual(db, actor, folio, datos.notas, request)
    await db.commit()
    return await _resumen(db, folio)


@router.post("/{folio_id}/pedir-informacion", response_model=FolioResumen, summary="Pedir información al operador")
async def pedir_informacion(folio_id: UUID, datos: NotasEntrada, request: Request, db: DB, actor: Actor = Depends(TODOS)):
    if not datos.notas.strip():
        raise ErrorAPI(422, "NOTAS_REQUERIDAS", "Indica qué información necesitas")
    return await _transicion(db, actor, folio_id, EstadoFolio.pendiente_informacion, datos.notas, None, request)


@router.post("/{folio_id}/responder-informacion", response_model=FolioResumen, summary="Responder la información solicitada")
async def responder_informacion(folio_id: UUID, datos: NotasEntrada, request: Request, db: DB, actor: Actor = Depends(TODOS)):
    if not datos.notas.strip():
        raise ErrorAPI(422, "NOTAS_REQUERIDAS", "Escribe la respuesta")
    return await _transicion(db, actor, folio_id, EstadoFolio.en_revision, datos.notas, {"respuesta_operador": datos.notas}, request)


@router.post("/{folio_id}/asignar", response_model=FolioResumen, summary="Asignar técnico",
             description="Restricción dura de habilidad (familia del equipo) salvo permiso `asignar_tecnico_sin_habilidad` del despachador con razón obligatoria.")
async def asignar(folio_id: UUID, datos: AsignarEntrada, request: Request, db: DB, actor: Actor = Depends(TODOS)):
    folio = await svc.obtener(db, actor, folio_id)
    if folio.estado == EstadoFolio.reasignado:
        await svc.asignar(db, actor, folio, datos.tecnico_id, datos.razon, datos.notas, request)
    else:
        await svc.asignar(db, actor, folio, datos.tecnico_id, datos.razon, datos.notas, request)
    await db.commit()
    return await _resumen(db, folio)


@router.post("/{folio_id}/en-camino", response_model=FolioResumen, summary="Técnico en camino")
async def en_camino(folio_id: UUID, datos: LlegadaEntrada, request: Request, db: DB, actor: Actor = Depends(TODOS)):
    return await _transicion(db, actor, folio_id, EstadoFolio.en_camino, datos.notas, {"geolat": datos.geolat, "geolng": datos.geolng}, request)


@router.post("/{folio_id}/confirmar-llegada", response_model=FolioResumen, summary="Confirmar llegada (en camino → en ejecución)")
async def confirmar_llegada(folio_id: UUID, datos: LlegadaEntrada, request: Request, db: DB, actor: Actor = Depends(TODOS)):
    return await _transicion(db, actor, folio_id, EstadoFolio.en_ejecucion, datos.notas, {"geolat": datos.geolat, "geolng": datos.geolng}, request)


@router.post("/{folio_id}/pendiente-refaccion", response_model=FolioResumen, summary="Pendiente de refacción")
async def pendiente_refaccion(folio_id: UUID, datos: NotasEntrada, request: Request, db: DB, actor: Actor = Depends(TODOS)):
    return await _transicion(db, actor, folio_id, EstadoFolio.pendiente_refaccion, datos.notas, None, request)


@router.post("/{folio_id}/reanudar", response_model=FolioResumen, summary="Reanudar ejecución (llegó la refacción)")
async def reanudar(folio_id: UUID, datos: NotasEntrada, request: Request, db: DB, actor: Actor = Depends(TODOS)):
    return await _transicion(db, actor, folio_id, EstadoFolio.en_ejecucion, datos.notas, None, request)


@router.post("/{folio_id}/cerrar", response_model=FolioResumen, summary="Cerrar folio",
             description="Requiere formulario de atención vinculado y evidencia de tipo firma; si falta alguno, 409 CIERRE_INCOMPLETO.")
async def cerrar(folio_id: UUID, datos: NotasEntrada, request: Request, db: DB, actor: Actor = Depends(TODOS)):
    return await _transicion(db, actor, folio_id, EstadoFolio.cerrado, datos.notas, None, request)


@router.post("/{folio_id}/cancelar", response_model=FolioResumen, summary="Cancelar folio (razón obligatoria)")
async def cancelar(folio_id: UUID, datos: RazonEntrada, request: Request, db: DB, actor: Actor = Depends(TODOS)):
    return await _transicion(db, actor, folio_id, EstadoFolio.cancelado, datos.razon, {"razon_cancelacion": datos.razon}, request)


@router.post("/{folio_id}/confirmar-un", response_model=FolioResumen, summary="Completar la confirmación de UN",
             description="Para folios en espera por `confirmacion_un_faltante`; vuelve a correr las validaciones automáticas.")
async def confirmar_un(folio_id: UUID, datos: ConfirmacionUNEntrada, request: Request, db: DB, actor: Actor = Depends(CAPTURA)):
    folio = await svc.obtener(db, actor, folio_id)
    await svc.confirmar_un(db, actor, folio, datos.geolat, datos.geolng, request)
    await db.commit()
    return await _resumen(db, folio)


@router.post("/{folio_id}/comentario", response_model=HistorialSalida, summary="Comentario administrativo en el historial",
             description="Lo único que admite un folio cerrado o cancelado (§6.8.6).")
async def comentario(folio_id: UUID, datos: NotasEntrada, request: Request, db: DB, actor: Actor = Depends(TODOS)):
    if not datos.notas.strip():
        raise ErrorAPI(422, "NOTAS_REQUERIDAS", "El comentario no puede ir vacío")
    folio = await svc.obtener(db, actor, folio_id)
    h = await folio_estados.comentar(db, folio, actor, datos.notas)
    await db.commit()
    return HistorialSalida(**{k: getattr(h, k) for k in HistorialSalida.model_fields if k != "actor_nombre"}, actor_nombre=actor.nombre)


@router.put("/{folio_id}/monto-estimado", response_model=FolioResumen, summary="Fijar monto estimado",
            description="Mesa de control, Despachador o Admin prestador, en capturado o en revisión (alimenta la regla por monto).")
async def monto_estimado(folio_id: UUID, datos: MontoEntrada, request: Request, db: DB, actor: Actor = Depends(TODOS)):
    folio = await svc.obtener(db, actor, folio_id)
    await svc.fijar_monto(db, actor, folio, datos.monto_estimado, request)
    await db.commit()
    return await _resumen(db, folio)


@router.put("/{folio_id}/severidad", response_model=FolioResumen, summary="Override de severidad (en revisión, razón obligatoria)")
async def severidad(folio_id: UUID, datos: SeveridadOverrideEntrada, request: Request, db: DB, actor: Actor = Depends(TODOS)):
    folio = await svc.obtener(db, actor, folio_id)
    await svc.override_severidad(db, actor, folio, datos.severidad_id, datos.razon, request)
    await db.commit()
    return await _resumen(db, folio)


# ------------------------------------------------- atención, evidencias, refacciones

@router.post("/{folio_id}/atencion", response_model=VinculoFormularioSalida, status_code=201, summary="Vincular formulario de atención",
             description="Respuesta enviada (origen folio_atencion) del técnico; sus evidencias (firma, fotos) se registran en el folio. P05 provee la UI.")
async def atencion(folio_id: UUID, datos: AtencionEntrada, request: Request, db: DB, actor: Actor = Depends(TODOS)):
    folio = await svc.obtener(db, actor, folio_id)
    v = await svc.vincular_atencion(db, actor, folio, datos.respuesta_id, request)
    await db.commit()
    return VinculoFormularioSalida(**await svc._vinculo(db, v))


@router.post("/{folio_id}/evidencias", response_model=EvidenciaFolioSalida, status_code=201, summary="Registrar evidencia del folio",
             description="Vincula una evidencia de formulario (P03) o un archivo ya almacenado, con tipo antes/durante/despues/firma/factura/otro.")
async def evidencias(folio_id: UUID, datos: EvidenciaFolioEntrada, db: DB, actor: Actor = Depends(TODOS)):
    folio = await svc.obtener(db, actor, folio_id)
    e = await svc.agregar_evidencia(db, actor, folio, datos.tipo, datos.evidencia_id, datos.archivo_key, datos.geolat, datos.geolng)
    await db.commit()
    return EvidenciaFolioSalida.model_validate(e, from_attributes=True)


@router.post("/{folio_id}/refacciones", response_model=RefaccionSalida, status_code=201, summary="Registrar refacción consumida",
             description="Con `articulo_id` descuenta del inventario (vehículo del técnico o `ubicacion_id`); sin él queda la "
                         "descripción libre con origen y costo. Las de origen `caja_chica` las aplica la aprobación del gasto (§6.4).")
async def refacciones(folio_id: UUID, datos: RefaccionEntrada, db: DB, actor: Actor = Depends(TODOS)):
    from services import inventario_service

    folio = await svc.obtener(db, actor, folio_id)
    if folio.estado in (EstadoFolio.cerrado, EstadoFolio.cancelado):
        raise ErrorAPI(409, "FOLIO_INMUTABLE", "El folio está cerrado o cancelado")
    if actor.rol == Rol.tecnico and folio.tecnico_id != actor.id:
        raise prohibido("El folio no está asignado a ti")
    cuerpo = datos.model_dump()
    ubicacion_id = cuerpo.pop("ubicacion_id", None)
    r = FolioRefaccion(folio_id=folio.id, tenant_id=folio.tenant_id, prestador_id=folio.prestador_id, **cuerpo)
    db.add(r)
    await db.flush()
    await inventario_service.consumir_en_folio(db, actor, folio, r, ubicacion_id=ubicacion_id)
    await db.commit()
    return RefaccionSalida.model_validate(r, from_attributes=True)


@router.post("/{folio_id}/costos/validar", response_model=FinancieroSalida, summary="Validar el costo del folio (Mesa de control o Admin prestador)",
             description="Ajuste con razón obligatoria. Al validarse se genera el evento ERP `registrar_gasto` y se registran "
                         "los consumos en todos los presupuestos aplicables (UN, grupo y tipo de actividad).")
async def validar_costo(folio_id: UUID, datos: ValidarCostoEntrada, request: Request, db: DB, actor: Actor = Depends(TODOS)):
    from services import costos_service

    folio = await svc.obtener(db, actor, folio_id)
    await costos_service.validar(db, actor, folio, ajuste=datos.ajuste, razon_ajuste=datos.razon_ajuste, costo_otros=datos.costo_otros,
                                 centro_costos=datos.centro_costos, request=request)
    await db.commit()
    return FinancieroSalida(**await costos_service.detalle_financiero(db, actor, folio))


@router.get("/{folio_id}/costos", response_model=FinancieroSalida, summary="Datos financieros del folio (§6.8.6)",
            description="Consultar los costos queda en la auditoría de acceso a datos sensibles (§6.9.5).")
async def costos(folio_id: UUID, request: Request, db: DB, actor: Actor = Depends(TODOS)):
    from services import costos_service

    folio = await svc.obtener(db, actor, folio_id)
    datos = await costos_service.detalle_financiero(db, actor, folio)
    if datos.get("visible"):
        await auditoria.registrar_acceso_datos(
            db, actor, request, tabla="folio_costos", recurso_id=folio.id,
            registros=1 if datos.get("costo") else 0,
            detalle={"numero_folio": folio.numero_folio, "refacciones": len(datos.get("refacciones") or []),
                     "gastos_caja_chica": len(datos.get("gastos_caja_chica") or [])})
        await db.commit()
    return FinancieroSalida(**datos)


# --------------------------------------------------------------- aprobación

@router.post("/{folio_id}/aprobacion/aprobar", response_model=FolioResumen, summary="Aprobar en el nivel actual",
             description="Último nivel requerido → autorizado; nivel intermedio → sube de nivel y notifica. `canal`: push, app o minuta.")
async def aprobar(folio_id: UUID, datos: AprobarEntrada, request: Request, db: DB, actor: Actor = Depends(APROBADORES)):
    folio = await svc.obtener(db, actor, folio_id)
    await aprobacion_service.aprobar(db, actor, folio, datos.canal, datos.notas, request)
    await db.commit()
    return await _resumen(db, folio)


@router.post("/{folio_id}/aprobacion/rechazar", response_model=FolioResumen, summary="Rechazar con razón (deriva a módulo de seguimiento)",
             description="Razones: por_presupuesto → Por presupuesto; requiere_cotizacion → Cotizaciones; seguimiento_interno → Seguimiento interno; "
                         "reprogramar → Reprogramación. El folio pasa a cancelado y queda el evento `folio.derivado_a_modulo` para P07.")
async def rechazar(folio_id: UUID, datos: RechazarEntrada, request: Request, db: DB, actor: Actor = Depends(APROBADORES)):
    folio = await svc.obtener(db, actor, folio_id)
    await aprobacion_service.rechazar(db, actor, folio, datos.canal, datos.razon_rechazo, datos.notas, request)
    await db.commit()
    return await _resumen(db, folio)


# ------------------------------------------------------------ cierre en campo (P05)

@router.post("/{folio_id}/firma", response_model=EvidenciaFolioSalida, status_code=201, summary="Firma del operador (cierre §6.8.6)",
             description="Multipart: `archivo` (PNG del trazo), `geolat`, `geolng`, `timestamp_dispositivo`. Solo el operador o Admin UN de la unidad, "
                         "con el folio en ejecución. Registra la evidencia tipo firma y avisa al operador que responda la encuesta.")
async def firma(folio_id: UUID, request: Request, db: DB, actor: Actor = Depends(TODOS), archivo: UploadFile = File(...),
                geolat: float | None = Form(default=None), geolng: float | None = Form(default=None), timestamp_dispositivo: _dt | None = Form(default=None)):
    folio = await svc.obtener(db, actor, folio_id)
    e = await folio_cierre_service.firmar(db, actor, folio, await archivo.read(), archivo.content_type or "image/png", geolat, geolng, timestamp_dispositivo, request)
    await db.commit()
    return EvidenciaFolioSalida.model_validate(e, from_attributes=True)


@router.get("/{folio_id}/encuesta/disponible", summary="¿Puede responderse la encuesta?")
async def encuesta_disponible(folio_id: UUID, db: DB, actor: Actor = Depends(TODOS)):
    folio = await svc.obtener(db, actor, folio_id)
    disponible, motivo = await folio_cierre_service.encuesta_disponible(db, folio)
    return {"disponible": disponible, "motivo": motivo}


@router.post("/{folio_id}/encuesta", response_model=EncuestaSalida, status_code=201, summary="Encuesta de satisfacción (NPS 0–10)",
             description="Usa el formulario de tipo encuesta resuelto por P03 si existe; con calificación ≤ 6 el comentario es obligatorio. "
                         "Se responde tras la firma, antes o después del cierre dentro del plazo del tenant (48 h por defecto).")
async def encuesta(folio_id: UUID, datos: EncuestaEntrada, request: Request, db: DB, actor: Actor = Depends(TODOS)):
    folio = await svc.obtener(db, actor, folio_id)
    enc = await folio_cierre_service.responder_encuesta(db, actor, folio, datos.nps_score, datos.comentario, datos.respuestas, datos.timestamp_dispositivo, request)
    await db.commit()
    return EncuestaSalida(folio_id=enc.folio_id, operador_id=enc.operador_id, nps_score=enc.nps_score, respuesta_id=enc.respuesta_id, timestamp=enc.timestamp)
