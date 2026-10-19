"""Grupos de unidades de negocio (§6.8.5): miembros N:N y supervisores asignados."""
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy import delete, select

from core.dependencias import DB, Actor, requiere_rol, validar_tenant
from core.errors import ErrorAPI, no_encontrado
from models.base import Rol
from models.unidades import GrupoUN, GrupoUNMiembro, UnidadNegocio, UsuarioGrupo
from models.usuarios import Usuario
from schemas.comun import RESPUESTAS_ERROR
from schemas.organizaciones import AsignacionUsuariosEntrada, GrupoCambios, GrupoEntrada, GrupoSalida, MiembrosEntrada
from services import auditoria

router = APIRouter(prefix="/api/grupos-un", tags=["Grupos de UNs"], responses=RESPUESTAS_ERROR)

ADMIN = requiere_rol(Rol.superadmin, Rol.admin_empresa)
LECTORES = requiere_rol(Rol.superadmin, Rol.admin_empresa, Rol.supervisor_operadores, Rol.admin_prestador,
                        Rol.mesa_control, Rol.despachador, Rol.direccion_prestador, Rol.supervisor_prestador)


async def _salida(db, grupo: GrupoUN) -> GrupoSalida:
    unidades = (await db.execute(select(GrupoUNMiembro.unidad_id).where(GrupoUNMiembro.grupo_id == grupo.id))).scalars().all()
    supervisores = (await db.execute(select(UsuarioGrupo.usuario_id).where(UsuarioGrupo.grupo_id == grupo.id))).scalars().all()
    return GrupoSalida(**{k: getattr(grupo, k) for k in GrupoSalida.model_fields if k not in ("unidad_ids", "supervisor_ids")},
                       unidad_ids=list(unidades), supervisor_ids=list(supervisores))


async def _obtener(db, actor: Actor, grupo_id: UUID) -> GrupoUN:
    grupo = await db.get(GrupoUN, grupo_id)
    if grupo is None:
        raise no_encontrado("Grupo")
    if actor.rol in (Rol.admin_empresa, Rol.supervisor_operadores) and grupo.tenant_id != actor.tenant_id:
        raise no_encontrado("Grupo")
    if actor.rol == Rol.supervisor_operadores:
        asignado = (await db.execute(select(UsuarioGrupo.id).where(
            UsuarioGrupo.grupo_id == grupo.id, UsuarioGrupo.usuario_id == actor.id))).first()
        if asignado is None:
            raise no_encontrado("Grupo")
    return grupo


async def _validar_responsable(db, tenant_id: UUID, responsable_id: UUID | None) -> None:
    if responsable_id is None:
        return
    u = await db.get(Usuario, responsable_id)
    if u is None or u.tenant_id != tenant_id:
        raise ErrorAPI(422, "RESPONSABLE_INVALIDO", "El responsable debe ser un usuario del mismo tenant")


@router.get("", response_model=list[GrupoSalida], summary="Listar grupos de UNs",
            description="supervisor_operadores ve solo sus grupos asignados.")
async def listar(db: DB, actor: Actor = Depends(LECTORES), tenant_id: UUID | None = None):
    consulta = select(GrupoUN).order_by(GrupoUN.nombre)
    if actor.rol == Rol.admin_empresa:
        consulta = consulta.where(GrupoUN.tenant_id == actor.tenant_id)
    elif actor.rol == Rol.supervisor_operadores:
        consulta = consulta.where(GrupoUN.id.in_(select(UsuarioGrupo.grupo_id).where(UsuarioGrupo.usuario_id == actor.id)))
    if tenant_id:
        consulta = consulta.where(GrupoUN.tenant_id == tenant_id)
    return [await _salida(db, g) for g in (await db.execute(consulta)).scalars()]


@router.post("", response_model=GrupoSalida, status_code=201, summary="Crear grupo de UNs")
async def crear(datos: GrupoEntrada, request: Request, db: DB, actor: Actor = Depends(ADMIN)):
    tenant_id = datos.tenant_id if actor.es_superadmin else actor.tenant_id
    if tenant_id is None:
        raise ErrorAPI(422, "TENANT_REQUERIDO", "Indica tenant_id")
    validar_tenant(actor, tenant_id)
    await _validar_responsable(db, tenant_id, datos.responsable_id)
    grupo = GrupoUN(tenant_id=tenant_id, **datos.model_dump(exclude={"tenant_id"}))
    db.add(grupo)
    await db.flush()
    await auditoria.registrar_actor(db, actor, "grupos_un.alta", request, tenant_id=tenant_id, recurso_tipo="grupo_un",
                                    recurso_id=grupo.id, despues=auditoria.instantanea(grupo))
    await db.commit()
    return await _salida(db, grupo)


@router.get("/{grupo_id}", response_model=GrupoSalida, summary="Detalle de grupo")
async def detalle(grupo_id: UUID, db: DB, actor: Actor = Depends(LECTORES)):
    return await _salida(db, await _obtener(db, actor, grupo_id))


@router.patch("/{grupo_id}", response_model=GrupoSalida, summary="Modificar grupo")
async def modificar(grupo_id: UUID, datos: GrupoCambios, request: Request, db: DB, actor: Actor = Depends(ADMIN)):
    grupo = await _obtener(db, actor, grupo_id)
    validar_tenant(actor, grupo.tenant_id)
    cambios = datos.model_dump(exclude_unset=True)
    if "responsable_id" in cambios:
        await _validar_responsable(db, grupo.tenant_id, cambios["responsable_id"])
    antes = auditoria.instantanea(grupo)
    for k, v in cambios.items():
        if v is not None or k == "responsable_id":
            setattr(grupo, k, v)
    await db.flush()
    await auditoria.registrar_actor(db, actor, "grupos_un.modificacion", request, tenant_id=grupo.tenant_id,
                                    recurso_tipo="grupo_un", recurso_id=grupo.id, antes=antes, despues=auditoria.instantanea(grupo))
    await db.commit()
    await db.refresh(grupo)
    return await _salida(db, grupo)


@router.put("/{grupo_id}/unidades", response_model=GrupoSalida, summary="Definir UNs del grupo",
            description="Reemplaza las UNs miembro. Una UN puede pertenecer a varios grupos.")
async def definir_unidades(grupo_id: UUID, datos: MiembrosEntrada, request: Request, db: DB, actor: Actor = Depends(ADMIN)):
    grupo = await _obtener(db, actor, grupo_id)
    validar_tenant(actor, grupo.tenant_id)
    ids = set(datos.unidad_ids)
    if ids:
        validas = set((await db.execute(select(UnidadNegocio.id).where(
            UnidadNegocio.id.in_(ids), UnidadNegocio.tenant_id == grupo.tenant_id))).scalars())
        if ids - validas:
            raise ErrorAPI(422, "UNIDADES_INVALIDAS", "Unidades inexistentes o de otro tenant", sorted(map(str, ids - validas)))
    actuales = set((await db.execute(select(GrupoUNMiembro.unidad_id).where(GrupoUNMiembro.grupo_id == grupo.id))).scalars())
    borrar = delete(GrupoUNMiembro).where(GrupoUNMiembro.grupo_id == grupo.id)
    if ids:
        borrar = borrar.where(GrupoUNMiembro.unidad_id.not_in(ids))
    await db.execute(borrar)
    for uid in ids - actuales:
        db.add(GrupoUNMiembro(tenant_id=grupo.tenant_id, grupo_id=grupo.id, unidad_id=uid))
    await db.flush()
    await auditoria.registrar_actor(db, actor, "grupos_un.miembros", request, tenant_id=grupo.tenant_id, recurso_tipo="grupo_un",
                                    recurso_id=grupo.id, antes={"unidades": sorted(map(str, actuales))},
                                    despues={"unidades": sorted(map(str, ids))})
    await db.commit()
    return await _salida(db, grupo)


@router.put("/{grupo_id}/supervisores", response_model=GrupoSalida, summary="Asignar supervisores al grupo",
            description="Reemplaza los supervisores de operadores asignados al grupo.")
async def definir_supervisores(grupo_id: UUID, datos: AsignacionUsuariosEntrada, request: Request, db: DB,
                               actor: Actor = Depends(ADMIN)):
    grupo = await _obtener(db, actor, grupo_id)
    validar_tenant(actor, grupo.tenant_id)
    ids = set(datos.usuario_ids)
    if ids:
        validos = set((await db.execute(select(Usuario.id).where(
            Usuario.id.in_(ids), Usuario.tenant_id == grupo.tenant_id, Usuario.rol == Rol.supervisor_operadores))).scalars())
        if ids - validos:
            raise ErrorAPI(422, "USUARIOS_INVALIDOS", "Solo se asignan supervisores de operadores del mismo tenant",
                           sorted(map(str, ids - validos)))
    actuales = set((await db.execute(select(UsuarioGrupo.usuario_id).where(UsuarioGrupo.grupo_id == grupo.id))).scalars())
    borrar = delete(UsuarioGrupo).where(UsuarioGrupo.grupo_id == grupo.id)
    if ids:
        borrar = borrar.where(UsuarioGrupo.usuario_id.not_in(ids))
    await db.execute(borrar)
    for uid in ids - actuales:
        db.add(UsuarioGrupo(tenant_id=grupo.tenant_id, usuario_id=uid, grupo_id=grupo.id))
    await db.flush()
    await auditoria.registrar_actor(db, actor, "grupos_un.supervisores", request, tenant_id=grupo.tenant_id,
                                    recurso_tipo="grupo_un", recurso_id=grupo.id, antes={"supervisores": sorted(map(str, actuales))},
                                    despues={"supervisores": sorted(map(str, ids))})
    await db.commit()
    return await _salida(db, grupo)
