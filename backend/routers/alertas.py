"""Catálogo de alertas, umbrales por tenant/prestador, historial y supresiones temporales (§6.9.6)."""
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select

from core.dependencias import DB, Actor, ActorActual, requiere_rol
from core.errors import ErrorAPI, no_encontrado, prohibido
from models.alertas import AlertaCatalogo, AlertaHistorial, AlertaSupresion
from models.base import EstadoAlerta, Rol
from schemas.comun import RESPUESTAS_ERROR
from schemas.configuracion import (
    AlertaCatalogoCambios, AlertaCatalogoSalida, AlertaConfiguracionEntrada, AlertaEfectiva, AlertaHistorialSalida,
    SupresionEntrada, SupresionSalida,
)
from schemas.sla import AtenderEntrada, EscalacionEntrada
from services import alertas_service as svc
from services import auditoria

router = APIRouter(prefix="/api/alertas", tags=["Alertas"], responses=RESPUESTAS_ERROR)

ADMINS = requiere_rol(Rol.superadmin, Rol.admin_empresa, Rol.admin_prestador)
SUPERADMIN = requiere_rol(Rol.superadmin)
LECTORES_HISTORIAL = requiere_rol(Rol.superadmin, Rol.admin_empresa, Rol.admin_un, Rol.admin_prestador,
                                  Rol.direccion_prestador, Rol.mesa_control, Rol.despachador)


def duenio(actor: Actor, tenant_id: UUID | None, prestador_id: UUID | None) -> tuple[UUID | None, UUID | None]:
    """Ámbito de configuración: el tenant o el prestador del actor; superadmin elige uno."""
    if actor.es_superadmin:
        if (tenant_id is None) == (prestador_id is None):
            raise ErrorAPI(422, "AMBITO_REQUERIDO", "Indica tenant_id o prestador_id (solo uno)")
        return tenant_id, prestador_id
    if actor.tenant_id:
        return actor.tenant_id, None
    if actor.prestador_id:
        return None, actor.prestador_id
    raise prohibido()


@router.get("/catalogo", response_model=list[AlertaCatalogoSalida], summary="Catálogo de alertas",
            description="Los 20 tipos de alerta del diseño con umbral por defecto y rango permitido.")
async def catalogo(db: DB, _: ActorActual):
    return (await db.execute(select(AlertaCatalogo).order_by(AlertaCatalogo.clave))).scalars().all()


@router.patch("/catalogo/{clave}", response_model=AlertaCatalogoSalida, summary="Modificar default y rango (superadmin)",
              description="Solo el superadmin cambia el umbral por defecto y los rangos mínimo y máximo.")
async def modificar_catalogo(clave: str, datos: AlertaCatalogoCambios, request: Request, db: DB,
                             actor: Actor = Depends(requiere_rol(Rol.superadmin))):
    cat = await svc.obtener_catalogo(db, clave)
    antes = auditoria.instantanea(cat)
    for k, v in datos.model_dump(exclude_unset=True, exclude_none=True).items():
        setattr(cat, k, v)
    if not (cat.umbral_min <= cat.umbral_default <= cat.umbral_max):
        raise ErrorAPI(422, "RANGO_INVALIDO", "Debe cumplirse umbral_min <= umbral_default <= umbral_max")
    await db.flush()
    await auditoria.registrar_actor(db, actor, "alertas.catalogo_modificado", request, recurso_tipo="alerta_catalogo",
                                    recurso_id=clave, antes=antes, despues=auditoria.instantanea(cat))
    await db.commit()
    await db.refresh(cat)
    return cat


@router.get("/configuracion", response_model=list[AlertaEfectiva], summary="Umbrales efectivos",
            description="Configuración efectiva de cada alerta para el tenant o prestador del usuario.")
async def configuracion(db: DB, actor: Actor = Depends(ADMINS), tenant_id: UUID | None = None, prestador_id: UUID | None = None):
    t, p = duenio(actor, tenant_id, prestador_id)
    return await svc.listar_efectivas(db, t, p)


@router.put("/configuracion/{clave}", response_model=AlertaEfectiva, summary="Personalizar umbral",
            description="El umbral debe quedar dentro del rango definido por el superadmin.")
async def configurar(clave: str, datos: AlertaConfiguracionEntrada, request: Request, db: DB, actor: Actor = Depends(SUPERADMIN),
                     tenant_id: UUID | None = None, prestador_id: UUID | None = None):
    t, p = duenio(actor, tenant_id, prestador_id)
    cat = await svc.obtener_catalogo(db, clave)
    svc.validar_fase(cat, activa=datos.activa)
    antes, despues = await svc.configurar(db, clave, t, p, umbral_valor=datos.umbral_valor, parametros=datos.parametros,
                                          canales=datos.canales, destinatarios_roles=datos.destinatarios_roles, activa=datos.activa)
    await auditoria.registrar_actor(db, actor, "alertas.umbral_configurado", request, tenant_id=t, prestador_id=p,
                                    recurso_tipo="alerta_configuracion", recurso_id=clave, antes=antes, despues=despues)
    await db.commit()
    return despues


@router.delete("/configuracion/{clave}", response_model=AlertaEfectiva, summary="Restablecer umbral por defecto")
async def restablecer(clave: str, request: Request, db: DB, actor: Actor = Depends(SUPERADMIN),
                      tenant_id: UUID | None = None, prestador_id: UUID | None = None):
    t, p = duenio(actor, tenant_id, prestador_id)
    despues = await svc.restablecer(db, clave, t, p)
    await auditoria.registrar_actor(db, actor, "alertas.umbral_restablecido", request, tenant_id=t, prestador_id=p,
                                    recurso_tipo="alerta_configuracion", recurso_id=clave, despues=despues)
    await db.commit()
    return despues


@router.get("/historial", response_model=list[AlertaHistorialSalida], summary="Historial de alertas disparadas")
async def historial(db: DB, actor: Actor = Depends(LECTORES_HISTORIAL), clave: str | None = None,
                    estado: EstadoAlerta | None = None, limite: int = Query(default=100, ge=1, le=1000)):
    consulta = select(AlertaHistorial).order_by(AlertaHistorial.timestamp_disparo.desc()).limit(limite)
    if actor.tenant_id:
        consulta = consulta.where(AlertaHistorial.tenant_id == actor.tenant_id)
    elif actor.prestador_id:
        consulta = consulta.where(AlertaHistorial.prestador_id == actor.prestador_id)
    if clave:
        consulta = consulta.where(AlertaHistorial.clave_alerta == clave)
    if estado:
        consulta = consulta.where(AlertaHistorial.estado == estado)
    return (await db.execute(consulta)).scalars().all()


@router.post("/historial/{alerta_id}/vista", response_model=AlertaHistorialSalida, summary="Marcar alerta como vista")
async def marcar_vista(alerta_id: UUID, db: DB, actor: Actor = Depends(LECTORES_HISTORIAL)):
    h = await db.get(AlertaHistorial, alerta_id)
    if h is None or (actor.tenant_id and h.tenant_id != actor.tenant_id) or (actor.prestador_id and h.prestador_id != actor.prestador_id):
        raise no_encontrado("Alerta")
    if h.estado == EstadoAlerta.disparada:
        h.estado = EstadoAlerta.vista
        h.timestamp_vista = datetime.now(UTC)
    await db.commit()
    await db.refresh(h)
    return h


@router.get("/supresiones", response_model=list[SupresionSalida], summary="Supresiones temporales")
async def supresiones(db: DB, actor: Actor = Depends(ADMINS), tenant_id: UUID | None = None, prestador_id: UUID | None = None,
                      solo_activas: bool = True):
    t, p = duenio(actor, tenant_id, prestador_id)
    consulta = select(AlertaSupresion).where(*svc._filtro_duenio(AlertaSupresion, t, p)).order_by(AlertaSupresion.desde.desc())
    if solo_activas:
        consulta = consulta.where(AlertaSupresion.activa.is_(True), AlertaSupresion.hasta > datetime.now(UTC))
    return (await db.execute(consulta)).scalars().all()


@router.post("/supresiones", response_model=SupresionSalida, status_code=201, summary="Suprimir una alerta temporalmente")
async def suprimir(datos: SupresionEntrada, request: Request, db: DB, actor: Actor = Depends(SUPERADMIN),
                   tenant_id: UUID | None = None, prestador_id: UUID | None = None):
    t, p = duenio(actor, tenant_id, prestador_id)
    await svc.obtener_catalogo(db, datos.clave_alerta)
    if datos.hasta <= datetime.now(UTC):
        raise ErrorAPI(422, "FECHA_INVALIDA", "La supresión debe terminar en el futuro")
    s = AlertaSupresion(clave_alerta=datos.clave_alerta, tenant_id=t, prestador_id=p, entidad_id=datos.entidad_id,
                        suprimida_por=actor.id, razon=datos.razon, desde=datetime.now(UTC), hasta=datos.hasta)
    db.add(s)
    await db.flush()
    await auditoria.registrar_actor(db, actor, "alertas.supresion", request, tenant_id=t, prestador_id=p,
                                    recurso_tipo="alerta_supresion", recurso_id=s.id, despues=auditoria.instantanea(s))
    await db.commit()
    return s


@router.post("/supresiones/{supresion_id}/desactivar", response_model=SupresionSalida, summary="Terminar una supresión")
async def desactivar_supresion(supresion_id: UUID, request: Request, db: DB, actor: Actor = Depends(SUPERADMIN),
                               tenant_id: UUID | None = None, prestador_id: UUID | None = None):
    t, p = duenio(actor, tenant_id, prestador_id)
    s = await db.get(AlertaSupresion, supresion_id)
    if s is None or s.tenant_id != t or s.prestador_id != p:
        raise no_encontrado("Supresión")
    s.activa = False
    await db.flush()
    await auditoria.registrar_actor(db, actor, "alertas.supresion_terminada", request, tenant_id=t, prestador_id=p,
                                    recurso_tipo="alerta_supresion", recurso_id=s.id)
    await db.commit()
    await db.refresh(s)
    return s


# ------------------------------------------------------------------- P10
@router.get("/panel", response_model=list[AlertaHistorialSalida], summary="Panel de alertas del usuario",
            description="Feed de las alertas activas cuyos roles destinatarios incluyen al usuario (§6.9.6). "
                        "Con `pendientes=false` trae también las ya atendidas.")
async def panel(db: DB, actor: ActorActual, clave: str | None = None, pendientes: bool = True,
                limite: int = Query(default=100, ge=1, le=500)):
    filas = await svc.panel(db, actor, clave=clave, pendientes=pendientes, limite=limite)
    descripciones = {c.clave: c.descripcion for c in (await db.execute(select(AlertaCatalogo))).scalars()}
    salida = []
    for h in filas:
        fila = AlertaHistorialSalida.model_validate(h, from_attributes=True)
        fila.descripcion = descripciones.get(h.clave_alerta)
        salida.append(fila)
    return salida


@router.post("/historial/{alerta_id}/atender", response_model=AlertaHistorialSalida, summary="Atender una alerta",
             description="La marca como resuelta con una nota; deja de contar como alerta abierta en los tableros.")
async def atender(alerta_id: UUID, datos: AtenderEntrada, request: Request, db: DB, actor: ActorActual):
    h = await db.get(AlertaHistorial, alerta_id)
    if h is None or (actor.tenant_id and h.tenant_id != actor.tenant_id) or (actor.prestador_id and h.prestador_id != actor.prestador_id):
        raise no_encontrado("Alerta")
    h = await svc.atender(db, actor, h, datos.nota)
    await auditoria.registrar_actor(db, actor, "alertas.atendida", request, tenant_id=h.tenant_id, prestador_id=h.prestador_id,
                                    recurso_tipo="alerta_historial", recurso_id=h.id, despues={"nota": h.nota_atencion})
    await db.commit()
    await db.refresh(h)
    return h


@router.get("/escalaciones", response_model=list[AlertaEfectiva], summary="Escalaciones configuradas",
            description="Alertas que escalan desde otra: el umbral se mide desde el disparo de la alerta origen (§6.9.6). "
                        "Resueltas para el tenant o el prestador del usuario.")
async def escalaciones(db: DB, actor: ActorActual):
    return await svc.escalaciones(db, tenant_id=actor.tenant_id, prestador_id=actor.prestador_id)


@router.put("/escalaciones", response_model=AlertaEfectiva, summary="Encadenar una alerta a su escalación",
            description="El Admin prestador encadena alertas críticas a una escalación a Dirección dentro de su prestador; "
                        "el Superadmin cambia el default del catálogo. `escalacion_de` vacío desconecta la cadena.")
async def configurar_escalacion(datos: EscalacionEntrada, request: Request, db: DB,
                                actor: Actor = Depends(SUPERADMIN)):
    salida = await svc.configurar_escalacion(db, actor, datos.clave, datos.escalacion_de)
    await auditoria.registrar_actor(db, actor, "alertas.escalacion_configurada", request, recurso_tipo="alerta_catalogo",
                                    recurso_id=datos.clave, despues={"escalacion_de": salida["escalacion_de"]})
    await db.commit()
    return salida
