"""Mensajería por WhatsApp y SMS: configuración, plantillas, bitácora, consumo y webhooks (§6.1). F2-02."""
import json
import logging
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse

from core.config import config
from core.db import nueva_sesion
from core.dependencias import DB, Actor, ActorActual, requiere_rol
from core.errors import no_encontrado, prohibido
from core.rls import CONTEXTO_SISTEMA, ContextoRLS
from models.base import EstadoRegistro, Rol
from models.mensajeria import CanalMensajeria, MensajeriaPlantilla
from models.usuarios import Usuario
from schemas.comun import RESPUESTAS_ERROR
from schemas.mensajeria import (
    ConfiguracionEntrada, ConfiguracionSalida, ConsumoSalida, EnvioSalida, PlantillaCambios, PlantillaSalida,
    PruebaEntrada, VistaPreviaSalida, WebhookSimuladoEntrada,
)
from services import mensajeria_service as svc
from services.mensajeria import plantillas as catalogo
from services.mensajeria import proveedores, telefonos

log = logging.getLogger("acma.mensajeria")

router = APIRouter(prefix="/api/mensajeria", tags=["Mensajería (WhatsApp y SMS)"], responses=RESPUESTAS_ERROR)

CONFIGURAN = requiere_rol(Rol.superadmin, Rol.admin_prestador, Rol.admin_empresa)
CONSULTAN = requiere_rol(Rol.superadmin, Rol.admin_prestador, Rol.admin_empresa, Rol.mesa_control,
                         Rol.direccion_prestador)


# ------------------------------------------------------------------ configuración
@router.get("/configuracion", response_model=ConfiguracionSalida | None,
            summary="Configuración efectiva de mensajería",
            description="La fila del tenant si existe y, si no, la del prestador. El Admin empresa ve la de su "
                        "empresa.")
async def ver_configuracion(db: DB, actor: Actor = Depends(CONSULTAN), prestador_id: UUID | None = None,
                            tenant_id: UUID | None = None):
    prestador = prestador_id if actor.rol == Rol.superadmin else (actor.prestador_id or prestador_id)
    tenant = actor.tenant_id or tenant_id
    if prestador is None and tenant is not None:
        from models.organizaciones import TenantPrestador
        from sqlalchemy import select

        prestador = (await db.execute(select(TenantPrestador.prestador_id).where(
            TenantPrestador.tenant_id == tenant, TenantPrestador.estado == EstadoRegistro.activo).limit(1))).scalar()
    return await svc.configuracion(db, prestador, tenant)


@router.put("/configuracion", response_model=ConfiguracionSalida, summary="Guardar la configuración de mensajería")
async def guardar_configuracion(datos: ConfiguracionEntrada, request: Request, db: DB,
                                actor: Actor = Depends(CONFIGURAN), prestador_id: UUID | None = None):
    prestador = prestador_id if actor.rol == Rol.superadmin else actor.prestador_id
    tenant = datos.tenant_id
    if actor.rol == Rol.admin_empresa:
        tenant = actor.tenant_id
        if prestador is None:
            from models.organizaciones import TenantPrestador
            from sqlalchemy import select

            prestador = (await db.execute(select(TenantPrestador.prestador_id).where(
                TenantPrestador.tenant_id == tenant,
                TenantPrestador.estado == EstadoRegistro.activo).limit(1))).scalar()
    if prestador is None:
        raise no_encontrado("Prestador")
    cambios = datos.model_dump(exclude_unset=True, exclude={"tenant_id"})
    if "eventos_whatsapp" in cambios:
        cambios["eventos_whatsapp_json"] = cambios.pop("eventos_whatsapp")
    if "eventos_sms" in cambios:
        cambios["eventos_sms_json"] = cambios.pop("eventos_sms")
    if cambios.get("horario_silencio") is not None:
        cambios["horario_silencio_json"] = cambios.pop("horario_silencio")
    else:
        cambios.pop("horario_silencio", None)
    cfg = await svc.guardar_configuracion(db, actor, prestador, tenant, cambios, request)
    await db.commit()
    await db.refresh(cfg)
    return cfg


@router.get("/modos", summary="Modo de cada canal y qué falta para producción")
async def modos(_: ActorActual) -> dict:
    return {
        "whatsapp": {"modo": proveedores.modo_de_canal("whatsapp"),
                     "proveedor": proveedores.nombre_proveedor("whatsapp"),
                     "remitente": proveedores.remitente_de("whatsapp")},
        "sms": {"modo": proveedores.modo_de_canal("sms"), "proveedor": proveedores.nombre_proveedor("sms"),
                "remitente": proveedores.remitente_de("sms")},
        "pendiente_para_produccion": [
            "Plantillas aprobadas por Meta (categoría utility).",
            "Número de negocio verificado en WhatsApp Business.",
            "URL pública de los webhooks configurada en Meta y en Twilio.",
        ],
        "guia": "docs/operacion/mensajeria.md",
    }


@router.get("/consumo", response_model=ConsumoSalida, summary="Consumo y costo estimado del mes")
async def consumo(db: DB, actor: Actor = Depends(CONSULTAN), prestador_id: UUID | None = None,
                  tenant_id: UUID | None = None):
    prestador = prestador_id if actor.rol == Rol.superadmin else (actor.prestador_id or prestador_id)
    tenant = actor.tenant_id or tenant_id
    if prestador is None:
        from models.organizaciones import TenantPrestador
        from sqlalchemy import select

        prestador = (await db.execute(select(TenantPrestador.prestador_id).where(
            TenantPrestador.tenant_id == tenant).limit(1))).scalar()
    if prestador is None:
        raise no_encontrado("Prestador")
    return await svc.consumo(db, prestador, tenant)


# ------------------------------------------------------------------ plantillas
@router.get("/plantillas", response_model=list[PlantillaSalida], summary="Plantillas por canal y su aprobación")
async def listar_plantillas(db: DB, actor: Actor = Depends(CONSULTAN), canal: CanalMensajeria | None = None):
    return await svc.listar_plantillas(db, actor, canal.value if canal else None)


@router.put("/plantillas/{plantilla_id}", response_model=PlantillaSalida, summary="Editar una plantilla",
            description="El Admin prestador que edita una plantilla base de la plataforma recibe una copia propia "
                        "en borrador: la base no se toca. Cambiar el cuerpo sube la versión.")
async def editar_plantilla(plantilla_id: UUID, datos: PlantillaCambios, request: Request, db: DB,
                           actor: ActorActual):
    f = await svc.editar_plantilla(db, actor, plantilla_id, datos.model_dump(exclude_unset=True), request)
    await db.commit()
    await db.refresh(f)
    definicion = catalogo.POR_CLAVE.get(f.clave)
    return PlantillaSalida(**svc.plantilla_dict(f), nombre=definicion.nombre if definicion else f.clave,
                           evento=definicion.evento if definicion else "", es_global=f.prestador_id is None)


@router.get("/plantillas/{plantilla_id}/vista-previa", response_model=VistaPreviaSalida,
            summary="Vista previa con datos de ejemplo (tal como se verá en WhatsApp o en el SMS)")
async def vista_previa(plantilla_id: UUID, db: DB, _: Actor = Depends(CONSULTAN)):
    f = await db.get(MensajeriaPlantilla, plantilla_id)
    if f is None:
        raise no_encontrado("Plantilla")
    return svc.vista_previa(f)


@router.get("/plantillas/{plantilla_id}/exportar", summary="Plantilla en el formato que pide Meta para aprobarla")
async def exportar_plantilla(plantilla_id: UUID, db: DB, _: Actor = Depends(CONFIGURAN)):
    f = await db.get(MensajeriaPlantilla, plantilla_id)
    if f is None:
        raise no_encontrado("Plantilla")
    if f.canal != CanalMensajeria.whatsapp:
        raise prohibido("Solo las plantillas de WhatsApp se someten a aprobación")
    return svc.exportar_para_meta(f)


# ------------------------------------------------------------------ bitácora y prueba
@router.get("/envios", response_model=list[EnvioSalida], summary="Bitácora de envíos con su estado de entrega")
async def listar_envios(db: DB, actor: Actor = Depends(CONSULTAN), canal: CanalMensajeria | None = None,
                        estado: str | None = None, evento: str | None = None, usuario_id: UUID | None = None,
                        folio_id: UUID | None = None, desde: date | None = None,
                        limite: int = Query(default=100, ge=1, le=500)):
    filas = await svc.listar_envios(db, actor, canal=canal.value if canal else None, estado=estado, evento=evento,
                                    usuario_id=usuario_id, folio_id=folio_id, desde=desde, limite=limite)
    return [EnvioSalida(**svc.envio_dict(f)) for f in filas]


@router.post("/prueba", summary="Enviar un mensaje de prueba a un número verificado",
             description="En modo `stub` el mensaje solo se guarda como vista previa. En modo `prueba` el proveedor "
                         "entrega únicamente a los números verificados en su panel.")
async def prueba(datos: PruebaEntrada, db: DB, actor: Actor = Depends(CONFIGURAN)) -> dict:
    r = await svc.prueba_de_envio(db, actor, datos.canal.value, datos.telefono, datos.clave)
    await db.commit()
    return r


@router.post("/reintentar", summary="Reintentar ahora los envíos fallidos (operación / pruebas)")
async def reintentar(db: DB, _: Actor = Depends(requiere_rol(Rol.superadmin, Rol.admin_prestador))) -> dict:
    r = await svc.reintentar_pendientes(db)
    await db.commit()
    return r


# ------------------------------------------------------------------ enlace corto propio
@router.get("/enlaces/{codigo}", summary="Destino de un enlace corto /l/{codigo}",
            description="Público a propósito: lo abre quien recibió el mensaje, que no tiene sesión en el "
                        "navegador. Solo devuelve una ruta de ACMA y registra el clic; el destino exige sesión.")
async def enlace(codigo: str) -> dict:
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        datos = await svc.resolver_enlace(db, codigo)
        await db.commit()
    return datos


@router.get("/minutas/{token}.pdf", summary="PDF de la minuta por enlace firmado (el botón de WhatsApp)")
async def pdf_de_minuta(token: str) -> Response:
    carga = svc.leer_token_pdf(token)
    from models.minutas import Minuta
    from services import minuta_service

    async with nueva_sesion(CONTEXTO_SISTEMA) as sistema:
        usuario = await sistema.get(Usuario, UUID(carga["sub"])) if carga.get("sub") else None
        if usuario is None or usuario.estado != EstadoRegistro.activo:
            raise prohibido("El enlace del PDF ya no es válido")
        contexto = ContextoRLS(usuario_id=usuario.id, tenant_id=usuario.tenant_id,
                               prestador_id=usuario.prestador_id, rol=usuario.rol.value)
    async with nueva_sesion(contexto) as db:
        minuta = await db.get(Minuta, UUID(carga["mid"]))
        if minuta is None:
            raise no_encontrado("Minuta")
        contenido = await minuta_service.pdf_de(db, minuta)
        await db.commit()
    return Response(content=contenido, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="minuta-{carga["mid"][:8]}.pdf"'})


# ------------------------------------------------------------------ webhooks
@router.get("/webhook/meta", summary="Verificación del webhook de Meta (hub.challenge)")
async def verificar_webhook_meta(request: Request) -> Response:
    parametros = request.query_params
    if parametros.get("hub.mode") == "subscribe" and config.whatsapp_verify_token \
            and parametros.get("hub.verify_token") == config.whatsapp_verify_token:
        return PlainTextResponse(parametros.get("hub.challenge", ""))
    return PlainTextResponse("verificación rechazada", status_code=403)


@router.post("/webhook/meta", summary="Estados de entrega y mensajes entrantes de WhatsApp Cloud API",
             description="Valida la firma `X-Hub-Signature-256` con el secreto de la app. En desarrollo el webhook "
                         "no es alcanzable desde internet: usa `/webhook/simular`.")
async def webhook_meta(request: Request) -> JSONResponse:
    cuerpo = await request.body()
    cabeceras = {k.lower(): v for k, v in request.headers.items()}
    if not proveedores.por_nombre("meta_cloud").validar_webhook(cuerpo, cabeceras):
        log.warning("Webhook de Meta con firma inválida")
        return JSONResponse({"codigo": "FIRMA_INVALIDA", "mensaje": "Firma no válida", "detalles": []},
                            status_code=403)
    try:
        datos = json.loads(cuerpo or b"{}")
    except json.JSONDecodeError:
        return JSONResponse({"codigo": "SOLICITUD_INVALIDA", "mensaje": "Cuerpo no es JSON", "detalles": []},
                            status_code=422)
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        resumen = await svc.webhook_meta(db, datos)
        await db.commit()
    return JSONResponse(resumen)


@router.post("/webhook/twilio", summary="Estados y mensajes entrantes de Twilio")
async def webhook_twilio(request: Request) -> JSONResponse:
    cuerpo = await request.body()
    cabeceras = {k.lower(): v for k, v in request.headers.items()}
    cabeceras["x-acma-url"] = str(request.url)
    if not proveedores.por_nombre("twilio").validar_webhook(cuerpo, cabeceras):
        log.warning("Webhook de Twilio con firma inválida")
        return JSONResponse({"codigo": "FIRMA_INVALIDA", "mensaje": "Firma no válida", "detalles": []},
                            status_code=403)
    from urllib.parse import parse_qsl

    formulario = dict(parse_qsl(cuerpo.decode("utf-8", "ignore"), keep_blank_values=True))
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        resumen = await svc.webhook_twilio(db, formulario)
        await db.commit()
    return JSONResponse(resumen)


@router.post("/webhook/simular", summary="Simular un webhook (desarrollo: el proveedor no alcanza tu máquina)",
             description="Cambia el estado de un envío o entrega un mensaje entrante como si viniera del "
                         "proveedor. Solo administradores y nunca en producción.")
async def simular_webhook(datos: WebhookSimuladoEntrada, db: DB,
                          actor: Actor = Depends(CONFIGURAN)) -> dict:
    if config.es_produccion:
        raise prohibido("La simulación de webhooks no existe en producción")
    resumen: dict[str, object] = {}
    # El webhook de verdad lo atiende el sistema, no un usuario: un mensaje puede venir de un número que no está en
    # la plataforma, y esa fila no tiene dueño a quien atribuirla. La simulación corre con el mismo contexto.
    async with nueva_sesion(CONTEXTO_SISTEMA) as sistema:
        if datos.mensaje_id and datos.estado:
            envio = await svc.actualizar_estado(sistema, "stub", datos.mensaje_id, datos.estado)
            resumen["estado"] = envio.estado.value if envio else "envío no encontrado"
        if datos.telefono and (datos.texto or datos.boton):
            respuesta = await svc.procesar_entrante(sistema, canal=datos.canal.value, telefono=datos.telefono,
                                                    texto_mensaje=datos.texto, boton=datos.boton, proveedor="stub")
            resumen["accion"] = respuesta.accion_ejecutada or "registrada"
            resumen["usuario_resuelto"] = respuesta.usuario_id is not None
        await sistema.commit()
    await svc.auditoria.registrar_actor(db, actor, "mensajeria.webhook_simulado", None, despues=dict(resumen))
    await db.commit()
    return resumen


# ------------------------------------------------------------------ vista previa del modo stub
@router.get("/simulados", summary="Últimos mensajes del proveedor simulado (modo stub)",
            description="Lo que se habría enviado: el cuerpo, los botones y el enlace corto. Es la forma de revisar "
                        "el canal sin contratar nada.")
async def simulados(_: Actor = Depends(CONSULTAN), limite: int = Query(default=20, ge=1, le=200)) -> dict:
    from services.mensajeria.stub import ENVIADOS

    return {"modo_whatsapp": proveedores.modo_de_canal("whatsapp"), "modo_sms": proveedores.modo_de_canal("sms"),
            "mensajes": list(reversed(ENVIADOS[-limite:]))}


# ------------------------------------------------------------------ aviso de privacidad
@router.get("/aviso-privacidad", summary="Texto del uso del teléfono para notificaciones operativas")
async def aviso(_: ActorActual) -> dict:
    return {"texto": telefonos.AVISO_PRIVACIDAD, "palabra_baja": svc.PALABRA_BAJA,
            "palabra_alta": svc.PALABRA_ALTA}
