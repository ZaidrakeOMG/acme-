"""Minuta del día (§7.1–7.5), hallazgos y peticiones (P07)."""
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response

from core.dependencias import DB, Actor, ActorActual, requiere_rol
from core.errors import ErrorAPI, no_encontrado, prohibido
from models.base import Dominio, Rol
from models.minutas import Hallazgo
from routers.catalogos_equipos import tenant_de
from schemas.comun import RESPUESTAS_ERROR, Mensaje
from schemas.minutas import (
    HallazgoEntrada, HallazgoSalida, MarcarMensajeEntrada, MinutaConfiguracionEntrada, MinutaConfiguracionSalida, MinutaDetalle, MinutaResumen, PeticionSalida,
    ResponderHallazgoEntrada, RespuestaMinutaSalida, ValidarEntrada,
)
from services import chat_service, hallazgos_service, minuta_service

router = APIRouter(tags=["Minuta del día"], responses=RESPUESTAS_ERROR)
TODOS = requiere_rol(*Rol)


async def _ambito(db, actor: Actor, tenant_id: UUID | None, prestador_id: UUID | None) -> tuple[UUID, UUID]:
    """(prestador, tenant) para configuración y generación: el prestador del actor + un cliente vinculado; superadmin indica ambos."""
    from models.organizaciones import TenantPrestador
    from sqlalchemy import select

    if actor.es_superadmin:
        if tenant_id is None:
            raise ErrorAPI(422, "TENANT_REQUERIDO", "Indica tenant_id")
        p = prestador_id or (await db.execute(select(TenantPrestador.prestador_id).where(TenantPrestador.tenant_id == tenant_id))).scalar()
        if p is None:
            raise ErrorAPI(422, "TENANT_NO_VINCULADO", "El cliente no tiene prestador")
        return p, tenant_id
    if actor.dominio == Dominio.prestador:
        if tenant_id is None:
            raise ErrorAPI(422, "TENANT_REQUERIDO", "Indica tenant_id")
        v = (await db.execute(select(TenantPrestador.id).where(TenantPrestador.tenant_id == tenant_id, TenantPrestador.prestador_id == actor.prestador_id))).first()
        if v is None:
            raise no_encontrado("Cliente")
        return actor.prestador_id, tenant_id
    p = (await db.execute(select(TenantPrestador.prestador_id).where(TenantPrestador.tenant_id == actor.tenant_id))).scalar()
    return p, actor.tenant_id


# ---------------------------------------------------------- configuración

@router.get("/api/minutas/configuracion", response_model=MinutaConfiguracionSalida, summary="Configuración de la minuta por cliente (§7.2)")
async def configuracion(db: DB, actor: Actor = Depends(requiere_rol(Rol.superadmin, Rol.admin_prestador, Rol.despachador, Rol.mesa_control, Rol.admin_empresa)),
                        tenant_id: UUID | None = None, prestador_id: UUID | None = None):
    p, t = await _ambito(db, actor, tenant_id, prestador_id)
    c = await minuta_service.configuracion(db, p, t)
    await db.commit()
    return MinutaConfiguracionSalida.model_validate(c)


@router.put("/api/minutas/configuracion", response_model=MinutaConfiguracionSalida, summary="Guardar configuración (Admin prestador)",
            description="Modo automático o con validación del despachador, hora de envío, ventana de validación, plazo de respuesta y umbrales de los contadores.")
async def guardar_configuracion(datos: MinutaConfiguracionEntrada, request: Request, db: DB, actor: Actor = Depends(requiere_rol(Rol.superadmin, Rol.admin_prestador)),
                                tenant_id: UUID | None = None, prestador_id: UUID | None = None):
    p, t = await _ambito(db, actor, tenant_id, prestador_id)
    c = await minuta_service.guardar_configuracion(db, actor, p, t, datos.model_dump(exclude_unset=True), request)
    await db.commit()
    return MinutaConfiguracionSalida.model_validate(c)


# ---------------------------------------------------------------- minutas

@router.post("/api/minutas/generar", response_model=list[MinutaResumen], summary="Generar la minuta de una fecha (manual)",
             description="Misma lógica que la tarea beat: una minuta por UN con actividad y una global. `forzar` genera la global aunque no haya actividad.")
async def generar(request: Request, db: DB, actor: Actor = Depends(requiere_rol(Rol.superadmin, Rol.admin_prestador, Rol.despachador, Rol.mesa_control)),
                  fecha: date = Query(default_factory=date.today), tenant_id: UUID | None = None, prestador_id: UUID | None = None, forzar: bool = False):
    p, t = await _ambito(db, actor, tenant_id, prestador_id)
    creadas = await minuta_service.generar(db, p, t, fecha, actor=actor, forzar=forzar, request=request)
    await db.commit()
    return [MinutaResumen(**m) for m in await minuta_service.resumen(db, creadas)]


@router.post("/api/minutas/procesar-pendientes", summary="Ejecutar ahora la tarea periódica (generar a la hora, vencer ventanas y plazos)")
async def procesar_pendientes(db: DB, actor: Actor = Depends(requiere_rol(Rol.superadmin, Rol.admin_prestador)), forzar_hora: bool = False):
    resumen = await minuta_service.generar_pendientes(db, forzar_hora=forzar_hora)
    await db.commit()
    return resumen


@router.get("/api/minutas", response_model=list[MinutaResumen], summary="Minutas por fecha, UN y estado",
            description="Prestador: todas las de sus clientes (incluidas pendientes de validación). Cliente: las enviadas de su tenant (Admin UN: sus UNs).")
async def listar(db: DB, actor: Actor = Depends(TODOS), tenant_id: UUID | None = None, un_id: UUID | None = None, estado: str | None = None, tipo: str | None = None,
                 desde: date | None = None, hasta: date | None = None):
    lista = await minuta_service.listar(db, actor, {"tenant_id": tenant_id, "un_id": un_id, "estado": estado, "tipo": tipo, "desde": desde, "hasta": hasta})
    return [MinutaResumen(**m) for m in await minuta_service.resumen(db, lista)]


@router.get("/api/minutas/{minuta_id}", response_model=MinutaDetalle, summary="Minuta completa: secciones, hallazgos, respuestas y entregas")
async def detalle(minuta_id: UUID, db: DB, actor: Actor = Depends(TODOS)):
    m = await minuta_service.obtener(db, actor, minuta_id)
    return MinutaDetalle(**await minuta_service.detalle(db, actor, m))


@router.get("/api/minutas/{minuta_id}/pdf", summary="PDF de la minuta (firmado con SHA-256)")
async def pdf(minuta_id: UUID, db: DB, actor: Actor = Depends(TODOS)):
    m = await minuta_service.obtener(db, actor, minuta_id)
    datos = await minuta_service.pdf_de(db, m)
    await db.commit()
    return Response(datos, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="minuta-{m.fecha.isoformat()}-{m.tipo.value}.pdf"',
                                                                  "X-Hash-SHA256": m.hash_pdf or ""})


@router.post("/api/minutas/{minuta_id}/validar", response_model=MinutaDetalle, summary="Validar y enviar (Despachador)",
             description="Añade notas del despachador y envía: correo HTML con PDF adjunto, push de dos líneas y bandeja.")
async def validar(minuta_id: UUID, datos: ValidarEntrada, request: Request, db: DB, actor: Actor = Depends(TODOS)):
    m = await minuta_service.obtener(db, actor, minuta_id)
    await minuta_service.validar(db, actor, m, datos.notas, request)
    await db.commit()
    return MinutaDetalle(**await minuta_service.detalle(db, actor, m))


@router.post("/api/minutas/{minuta_id}/hallazgos/{hallazgo_id}/responder", response_model=RespuestaMinutaSalida, status_code=201,
             summary="Responder un hallazgo con una de las seis opciones (§7.4)",
             description="enterado → registro; cotización → módulo Cotizaciones y aviso al prestador; autorizar_reparar → folio correctivo autorizado; "
                         "por_presupuesto / seguimiento_interno / reprogramacion → su módulo. `canal` = app | email | push.")
async def responder(minuta_id: UUID, hallazgo_id: UUID, datos: ResponderHallazgoEntrada, request: Request, db: DB, actor: Actor = Depends(TODOS)):
    m = await minuta_service.obtener(db, actor, minuta_id)
    h = await db.get(Hallazgo, hallazgo_id)
    if h is None:
        raise no_encontrado("Hallazgo")
    r = await minuta_service.responder(db, actor, m, h, datos.opcion, notas=datos.notas, canal=datos.canal, fecha_tentativa=datos.fecha_tentativa, proveedor=datos.proveedor,
                                       trabajo_coordinado=datos.trabajo_coordinado, variante=datos.variante, request=request)
    await db.commit()
    from models.usuarios import Usuario

    u = await db.get(Usuario, actor.id)
    return RespuestaMinutaSalida(id=r.id, hallazgo_id=r.hallazgo_id, opcion_elegida=r.opcion_elegida, usuario_id=r.usuario_id, usuario_nombre=u.nombre if u else None,
                                 timestamp=r.timestamp, notas=r.notas, canal=r.canal, modulo_destino=r.modulo_destino, modulo_registro_id=r.modulo_registro_id,
                                 folio_generado_id=r.folio_generado_id)


# -------------------------------------------------------------- hallazgos

@router.get("/api/hallazgos", response_model=list[HallazgoSalida], summary="Hallazgos (por tenant, UN, folio, estado de respuesta)")
async def hallazgos(db: DB, actor: Actor = Depends(TODOS), tenant_id: UUID | None = None, un_id: UUID | None = None, folio_id: UUID | None = None,
                    estado_respuesta: str | None = None, desde: date | None = None, hasta: date | None = None):
    lista = await hallazgos_service.listar(db, actor, {"tenant_id": tenant_id, "un_id": un_id, "folio_id": folio_id, "estado_respuesta": estado_respuesta, "desde": desde, "hasta": hasta})
    return [HallazgoSalida(**h) for h in await hallazgos_service.enriquecer(db, lista)]


@router.post("/api/hallazgos", response_model=HallazgoSalida, status_code=201, summary="Capturar un hallazgo manual")
async def crear_hallazgo(datos: HallazgoEntrada, request: Request, db: DB, actor: Actor = Depends(TODOS)):
    if datos.un_id is None and datos.folio_id is None:
        raise ErrorAPI(422, "UNIDAD_REQUERIDA", "Indica un_id o folio_id")
    h = await hallazgos_service.crear_manual(db, actor, datos.model_dump(), request)
    await db.commit()
    return HallazgoSalida(**(await hallazgos_service.enriquecer(db, [h]))[0])


@router.get("/api/hallazgos/{hallazgo_id}", response_model=HallazgoSalida, summary="Detalle del hallazgo")
async def hallazgo(hallazgo_id: UUID, db: DB, actor: Actor = Depends(TODOS)):
    h = await hallazgos_service.obtener(db, actor, hallazgo_id)
    return HallazgoSalida(**(await hallazgos_service.enriquecer(db, [h]))[0])


@router.get("/api/peticiones", response_model=list[PeticionSalida], summary="Peticiones especiales del cliente")
async def peticiones(db: DB, actor: Actor = Depends(TODOS), tenant_id: UUID | None = None, un_id: UUID | None = None, folio_id: UUID | None = None):
    return [PeticionSalida.model_validate(p) for p in await hallazgos_service.peticiones(db, actor, {"tenant_id": tenant_id, "un_id": un_id, "folio_id": folio_id})]


@router.post("/api/chats/{chat_id}/mensajes/{mensaje_id}/marcar", summary="Marcar un mensaje del chat como hallazgo o petición especial",
             description="Técnico, operador, Admin UN o Despachador. El hallazgo entra a la minuta del día con origen `chat`.")
async def marcar_mensaje(chat_id: UUID, mensaje_id: UUID, datos: MarcarMensajeEntrada, request: Request, db: DB, actor: ActorActual):
    from models.chat import ChatMensaje

    chat = await chat_service.obtener_chat(db, chat_id)
    await chat_service.exigir_participante(db, actor, chat)
    mensaje = await db.get(ChatMensaje, mensaje_id)
    if mensaje is None:
        raise no_encontrado("Mensaje")
    registro = await hallazgos_service.desde_mensaje(db, actor, chat, mensaje, como=datos.como, urgencia=datos.nivel_urgencia, request=request)
    await db.commit()
    if datos.como == "hallazgo":
        return {"tipo": "hallazgo", "registro": HallazgoSalida(**(await hallazgos_service.enriquecer(db, [registro]))[0])}
    return {"tipo": "peticion", "registro": PeticionSalida.model_validate(registro)}


__all__ = ["router", "tenant_de", "prohibido", "Mensaje"]
