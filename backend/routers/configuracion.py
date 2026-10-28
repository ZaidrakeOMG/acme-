"""Configuración clave-valor por tenant y por prestador, y permisos configurables de técnico y despachador."""
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Request
from sqlalchemy import select

from core.dependencias import DB, Actor, ActorActual, requiere_rol
from core.errors import ErrorAPI, no_encontrado
from models.auditoria import ConfiguracionPrestador, ConfiguracionTenant
from models.base import Rol
from models.organizaciones import TenantPrestador
from models.usuarios import Usuario
from schemas.comun import RESPUESTAS_ERROR
from schemas.configuracion import (
    ConfiguracionSalida, PermisoEfectivo, PermisosCambios, PermisosDespachadorCambios, ValorConfiguracion,
)
from services import auditoria, permisos_service

router = APIRouter(prefix="/api/configuracion", tags=["Configuración"], responses=RESPUESTAS_ERROR)

ADMIN_TENANT = requiere_rol(Rol.superadmin, Rol.admin_empresa)
ADMIN_PRESTADOR = requiere_rol(Rol.superadmin, Rol.admin_prestador)
LECTOR_PERMISOS = requiere_rol(Rol.superadmin, Rol.admin_prestador, Rol.despachador, Rol.mesa_control)
CLAVE = Path(pattern=r"^[a-z][a-z0-9_.]{1,79}$", description="Clave en minúsculas, p. ej. `minuta.requiere_validacion`")


def _tenant(actor: Actor, tenant_id: UUID | None) -> UUID:
    if actor.es_superadmin:
        if tenant_id is None:
            raise ErrorAPI(422, "TENANT_REQUERIDO", "Indica tenant_id")
        return tenant_id
    return actor.tenant_id  # type: ignore[return-value]


def _prestador(actor: Actor, prestador_id: UUID | None) -> UUID:
    if actor.es_superadmin:
        if prestador_id is None:
            raise ErrorAPI(422, "PRESTADOR_REQUERIDO", "Indica prestador_id")
        return prestador_id
    return actor.prestador_id  # type: ignore[return-value]


# ------------------------------------------------------------ tenant

@router.get("/tenant", response_model=list[ConfiguracionSalida], summary="Configuración del tenant")
async def listar_tenant(db: DB, actor: Actor = Depends(ADMIN_TENANT), tenant_id: UUID | None = None):
    t = _tenant(actor, tenant_id)
    return (await db.execute(select(ConfiguracionTenant).where(ConfiguracionTenant.tenant_id == t)
                             .order_by(ConfiguracionTenant.clave))).scalars().all()


@router.put("/tenant/{clave}", response_model=ConfiguracionSalida, summary="Guardar parámetro del tenant")
async def guardar_tenant(datos: ValorConfiguracion, request: Request, db: DB, clave: str = CLAVE,
                         actor: Actor = Depends(ADMIN_TENANT), tenant_id: UUID | None = None):
    t = _tenant(actor, tenant_id)
    fila = (await db.execute(select(ConfiguracionTenant).where(
        ConfiguracionTenant.tenant_id == t, ConfiguracionTenant.clave == clave))).scalar_one_or_none()
    antes = {"valor": fila.valor} if fila else None
    if fila is None:
        fila = ConfiguracionTenant(tenant_id=t, clave=clave, valor=datos.valor)
        db.add(fila)
    else:
        fila.valor = datos.valor
    await db.flush()
    await auditoria.registrar_actor(db, actor, "configuracion.tenant", request, tenant_id=t, recurso_tipo="configuracion_tenant",
                                    recurso_id=clave, antes=antes, despues={"valor": datos.valor})
    await db.commit()
    await db.refresh(fila)
    return fila


# --------------------------------------------------------- prestador

@router.get("/prestador", response_model=list[ConfiguracionSalida], summary="Configuración del prestador")
async def listar_prestador(db: DB, actor: Actor = Depends(ADMIN_PRESTADOR), prestador_id: UUID | None = None):
    p = _prestador(actor, prestador_id)
    return (await db.execute(select(ConfiguracionPrestador).where(ConfiguracionPrestador.prestador_id == p)
                             .order_by(ConfiguracionPrestador.clave))).scalars().all()


@router.put("/prestador/{clave}", response_model=ConfiguracionSalida, summary="Guardar parámetro del prestador")
async def guardar_prestador(datos: ValorConfiguracion, request: Request, db: DB, clave: str = CLAVE,
                            actor: Actor = Depends(ADMIN_PRESTADOR), prestador_id: UUID | None = None):
    p = _prestador(actor, prestador_id)
    fila = (await db.execute(select(ConfiguracionPrestador).where(
        ConfiguracionPrestador.prestador_id == p, ConfiguracionPrestador.clave == clave))).scalar_one_or_none()
    antes = {"valor": fila.valor} if fila else None
    if fila is None:
        fila = ConfiguracionPrestador(prestador_id=p, clave=clave, valor=datos.valor)
        db.add(fila)
    else:
        fila.valor = datos.valor
    await db.flush()
    await auditoria.registrar_actor(db, actor, "configuracion.prestador", request, prestador_id=p,
                                    recurso_tipo="configuracion_prestador", recurso_id=clave, antes=antes, despues={"valor": datos.valor})
    await db.commit()
    await db.refresh(fila)
    return fila


# ----------------------------------------------- permisos configurables

@router.get("/mis-permisos", summary="Permisos efectivos del usuario actual (técnico o despachador)",
            description="P05: la app de campo decide con ellos si muestra «Nuevo folio» (crear_folio_en_campo) o costos (ver_costo_refacciones).")
async def mis_permisos(db: DB, actor: ActorActual, tenant_id: UUID | None = None) -> list[dict]:
    if actor.rol == Rol.tecnico and actor.prestador_id:
        return await permisos_service.efectivos_de_tecnico(db, actor.prestador_id, actor.id)
    if actor.rol == Rol.despachador and actor.prestador_id:
        return [{"clave": p["clave"], "descripcion": p["descripcion"], "habilitado": p["habilitado"], "origen": "prestador", "razon": None}
                for p in await permisos_service.efectivos_despachador(db, actor.prestador_id, actor.id, tenant_id)]
    return []


@router.get("/permisos-tecnico", response_model=list[PermisoEfectivo], summary="Permisos del técnico (valor base del prestador)",
            description="Catálogo §6.8.3 con el valor configurado por el prestador. Grupos y overrides individuales llegan en P02.")
async def permisos_tecnico(db: DB, actor: Actor = Depends(LECTOR_PERMISOS), prestador_id: UUID | None = None):
    return await permisos_service.efectivos_tecnico(db, _prestador(actor, prestador_id))


@router.put("/permisos-tecnico", response_model=list[PermisoEfectivo], summary="Configurar permisos del técnico")
async def configurar_permisos_tecnico(datos: PermisosCambios, request: Request, db: DB,
                                      actor: Actor = Depends(ADMIN_PRESTADOR), prestador_id: UUID | None = None):
    p = _prestador(actor, prestador_id)
    cambios = await permisos_service.actualizar_tecnico(db, p, datos.valores)
    await auditoria.registrar_actor(db, actor, "permisos.tecnico", request, prestador_id=p, recurso_tipo="permisos_tecnico",
                                    recurso_id=p, antes={k: v[0] for k, v in cambios.items()},
                                    despues={k: v[1] for k, v in cambios.items()})
    await db.commit()
    return await permisos_service.efectivos_tecnico(db, p)


@router.get("/permisos-despachador", response_model=list[PermisoEfectivo], summary="Permisos del despachador",
            description="Sin parámetros: valor base del prestador. Con despachador_id y tenant_id: permisos efectivos de ese "
                        "despachador para ese cliente (§6.8.3b).")
async def permisos_despachador(db: DB, actor: Actor = Depends(LECTOR_PERMISOS), prestador_id: UUID | None = None,
                               despachador_id: UUID | None = None, tenant_id: UUID | None = None):
    if actor.rol == Rol.despachador:
        despachador_id = actor.id
    return await permisos_service.efectivos_despachador(db, _prestador(actor, prestador_id), despachador_id, tenant_id)


@router.put("/permisos-despachador", response_model=list[PermisoEfectivo], summary="Configurar permisos del despachador",
            description="Cada cambio queda en el log inmutable permisos_despachador_log y en auditoría.")
async def configurar_permisos_despachador(datos: PermisosDespachadorCambios, request: Request, db: DB,
                                          actor: Actor = Depends(ADMIN_PRESTADOR), prestador_id: UUID | None = None):
    p = _prestador(actor, prestador_id)
    if datos.despachador_id:
        despachador = await db.get(Usuario, datos.despachador_id)
        if despachador is None or despachador.prestador_id != p or despachador.rol != Rol.despachador:
            raise no_encontrado("Despachador")
        vinculo = (await db.execute(select(TenantPrestador.id).where(
            TenantPrestador.prestador_id == p, TenantPrestador.tenant_id == datos.tenant_id))).first()
        if vinculo is None:
            raise ErrorAPI(422, "TENANT_NO_VINCULADO", "El cliente no está vinculado a este prestador")
    cambios = await permisos_service.actualizar_despachador(db, p, datos.valores, actor.id, datos.despachador_id, datos.tenant_id)
    await auditoria.registrar_actor(db, actor, "permisos.despachador", request, prestador_id=p, recurso_tipo="permisos_despachador",
                                    recurso_id=datos.despachador_id or p, antes={k: v[0] for k, v in cambios.items()},
                                    despues={k: v[1] for k, v in cambios.items()})
    await db.commit()
    return await permisos_service.efectivos_despachador(db, p, datos.despachador_id, datos.tenant_id)

