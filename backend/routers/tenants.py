"""Tenants (empresas cliente) y su vínculo con prestadores. Alta y vínculos: solo superadmin."""
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select

from core.dependencias import DB, Actor, requiere_rol
from core.errors import no_encontrado, prohibido
from models.base import Rol
from models.organizaciones import Prestador, Tenant, TenantPrestador
from schemas.comun import RESPUESTAS_ERROR
from schemas.organizaciones import TenantCambios, TenantEntrada, TenantSalida, VinculoPrestadorEntrada, VinculoSalida
from services import auditoria

router = APIRouter(prefix="/api/tenants", tags=["Tenants"], responses=RESPUESTAS_ERROR)

LECTORES = requiere_rol(Rol.superadmin, Rol.admin_empresa, Rol.admin_prestador, Rol.mesa_control,
                        Rol.despachador, Rol.direccion_prestador, Rol.supervisor_prestador)
SUPERADMIN = requiere_rol(Rol.superadmin)


async def _obtener(db, actor: Actor, tenant_id: UUID) -> Tenant:
    tenant = await db.get(Tenant, tenant_id)
    if tenant is None:
        raise no_encontrado("Tenant")
    if actor.rol == Rol.admin_empresa and tenant.id != actor.tenant_id:
        raise no_encontrado("Tenant")
    return tenant


@router.get("", response_model=list[TenantSalida], summary="Listar tenants",
            description="superadmin ve todos; admin_empresa su propio tenant; los roles del prestador ven los clientes que atienden.")
async def listar(db: DB, actor: Actor = Depends(LECTORES)):
    consulta = select(Tenant).order_by(Tenant.razon_social)
    if actor.rol == Rol.admin_empresa:
        consulta = consulta.where(Tenant.id == actor.tenant_id)
    elif actor.prestador_id:
        consulta = consulta.join(TenantPrestador, TenantPrestador.tenant_id == Tenant.id).where(
            TenantPrestador.prestador_id == actor.prestador_id).distinct()
    return (await db.execute(consulta)).scalars().all()


@router.post("", response_model=TenantSalida, status_code=201, summary="Crear tenant")
async def crear(datos: TenantEntrada, request: Request, db: DB, actor: Actor = Depends(SUPERADMIN)):
    tenant = Tenant(**datos.model_dump())
    db.add(tenant)
    await db.flush()
    await auditoria.registrar_actor(db, actor, "tenants.alta", request, tenant_id=tenant.id, recurso_tipo="tenant",
                                    recurso_id=tenant.id, despues=auditoria.instantanea(tenant))
    await db.commit()
    return tenant


@router.get("/{tenant_id}", response_model=TenantSalida, summary="Detalle de tenant")
async def detalle(tenant_id: UUID, db: DB, actor: Actor = Depends(LECTORES)):
    return await _obtener(db, actor, tenant_id)


@router.patch("/{tenant_id}", response_model=TenantSalida, summary="Modificar tenant",
              description="Solo superadmin modifica clientes.")
async def modificar(tenant_id: UUID, datos: TenantCambios, request: Request, db: DB,
                    actor: Actor = Depends(SUPERADMIN)):
    tenant = await _obtener(db, actor, tenant_id)
    cambios = datos.model_dump(exclude_unset=True, exclude_none=True)
    if actor.rol == Rol.admin_empresa and set(cambios) - {"moneda", "zona_horaria"}:
        raise prohibido("Solo puedes modificar moneda y zona horaria")
    antes = auditoria.instantanea(tenant)
    for k, v in cambios.items():
        setattr(tenant, k, v)
    await db.flush()
    await auditoria.registrar_actor(db, actor, "tenants.modificacion", request, tenant_id=tenant.id, recurso_tipo="tenant",
                                    recurso_id=tenant.id, antes=antes, despues=auditoria.instantanea(tenant))
    await db.commit()
    await db.refresh(tenant)
    return tenant


@router.get("/{tenant_id}/prestadores", response_model=list[VinculoSalida], summary="Prestadores del tenant",
            description="Relaciones tenant–prestador con su vigencia.")
async def vinculos(tenant_id: UUID, db: DB, actor: Actor = Depends(LECTORES)):
    await _obtener(db, actor, tenant_id)
    consulta = select(TenantPrestador).where(TenantPrestador.tenant_id == tenant_id)
    if actor.prestador_id:
        consulta = consulta.where(TenantPrestador.prestador_id == actor.prestador_id)
    return (await db.execute(consulta.order_by(TenantPrestador.vigencia_inicio))).scalars().all()


@router.post("/{tenant_id}/prestadores", response_model=VinculoSalida, status_code=201, summary="Vincular prestador",
             description="Crea la relación N:N tenant–prestador con vigencia.")
async def vincular(tenant_id: UUID, datos: VinculoPrestadorEntrada, request: Request, db: DB, actor: Actor = Depends(SUPERADMIN)):
    await _obtener(db, actor, tenant_id)
    if await db.get(Prestador, datos.prestador_id) is None:
        raise no_encontrado("Prestador")
    vinculo = TenantPrestador(tenant_id=tenant_id, **datos.model_dump())
    db.add(vinculo)
    await db.flush()
    await auditoria.registrar_actor(db, actor, "tenants.vinculo_prestador", request, tenant_id=tenant_id,
                                    prestador_id=datos.prestador_id, recurso_tipo="tenant_prestador", recurso_id=vinculo.id,
                                    despues=auditoria.instantanea(vinculo))
    await db.commit()
    return vinculo
