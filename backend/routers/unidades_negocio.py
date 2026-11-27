"""Unidades de negocio (UN) con ubicación PostGIS y asignación de operadores/supervisores."""
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from geoalchemy2 import Geometry, WKTElement
from sqlalchemy import cast, delete, func, or_, select

from core.dependencias import DB, Actor, requiere_rol, validar_tenant
from core.errors import ErrorAPI, no_encontrado
from models.base import Rol
from models.unidades import GrupoUN, GrupoUNMiembro, UnidadNegocio, UsuarioGrupo, UsuarioUN
from models.usuarios import Usuario
from schemas.comun import RESPUESTAS_ERROR
from schemas.organizaciones import AsignacionUsuariosEntrada, Coordenadas, UnidadCambios, UnidadEntrada, UnidadSalida
from services import auditoria

router = APIRouter(prefix="/api/unidades-negocio", tags=["Unidades de negocio"], responses=RESPUESTAS_ERROR)

ADMIN = requiere_rol(Rol.superadmin)
LECTORES = requiere_rol(*Rol)
ROLES_ASIGNABLES_UN = {Rol.admin_un, Rol.supervisor_operadores, Rol.operador}

_LAT = func.ST_Y(cast(UnidadNegocio.ubicacion, Geometry))
_LNG = func.ST_X(cast(UnidadNegocio.ubicacion, Geometry))


def _punto(c: Coordenadas | None):
    return WKTElement(f"POINT({c.lng} {c.lat})", srid=4326) if c else None


def _salida(un: UnidadNegocio, lat: float | None, lng: float | None) -> UnidadSalida:
    return UnidadSalida(
        **{k: getattr(un, k) for k in UnidadSalida.model_fields if k != "ubicacion"},
        ubicacion=Coordenadas(lat=lat, lng=lng) if lat is not None and lng is not None else None,
    )


def filtro_visibilidad(actor: Actor):
    """UNs que el actor puede ver según su rol (§5). Se suma a la RLS por tenant."""
    if actor.rol in (Rol.admin_un, Rol.operador):
        return UnidadNegocio.id.in_(select(UsuarioUN.unidad_id).where(UsuarioUN.usuario_id == actor.id))
    if actor.rol == Rol.supervisor_operadores:
        por_grupo = select(GrupoUNMiembro.unidad_id).join(UsuarioGrupo, UsuarioGrupo.grupo_id == GrupoUNMiembro.grupo_id) \
            .where(UsuarioGrupo.usuario_id == actor.id)
        directas = select(UsuarioUN.unidad_id).where(UsuarioUN.usuario_id == actor.id)
        return or_(UnidadNegocio.id.in_(por_grupo), UnidadNegocio.id.in_(directas))
    if actor.rol == Rol.admin_empresa:
        return UnidadNegocio.tenant_id == actor.tenant_id
    return None  # superadmin y roles del prestador: la RLS limita a los tenants atendidos


async def _obtener(db, actor: Actor, unidad_id: UUID) -> tuple[UnidadNegocio, float | None, float | None]:
    consulta = select(UnidadNegocio, _LAT, _LNG).where(UnidadNegocio.id == unidad_id)
    filtro = filtro_visibilidad(actor)
    if filtro is not None:
        consulta = consulta.where(filtro)
    fila = (await db.execute(consulta)).first()
    if fila is None:
        raise no_encontrado("Unidad de negocio")
    return fila[0], fila[1], fila[2]


async def _validar_grupo(db, tenant_id: UUID, grupo_id: UUID | None) -> None:
    if grupo_id is None:
        return
    grupo = await db.get(GrupoUN, grupo_id)
    if grupo is None or grupo.tenant_id != tenant_id:
        raise ErrorAPI(422, "GRUPO_INVALIDO", "El grupo no pertenece al tenant de la unidad")


@router.get("", response_model=list[UnidadSalida], summary="Listar unidades de negocio",
            description="admin_empresa ve todas las de su tenant; admin_un y operador solo las asignadas; supervisor_operadores "
                        "las de sus grupos; los roles del prestador, las de los clientes que atienden.")
async def listar(db: DB, actor: Actor = Depends(LECTORES), tenant_id: UUID | None = None, grupo_id: UUID | None = None):
    consulta = select(UnidadNegocio, _LAT, _LNG).order_by(UnidadNegocio.nombre)
    filtro = filtro_visibilidad(actor)
    if filtro is not None:
        consulta = consulta.where(filtro)
    if tenant_id:
        consulta = consulta.where(UnidadNegocio.tenant_id == tenant_id)
    if grupo_id:
        consulta = consulta.where(or_(
            UnidadNegocio.grupo_id == grupo_id,
            UnidadNegocio.id.in_(select(GrupoUNMiembro.unidad_id).where(GrupoUNMiembro.grupo_id == grupo_id)),
        ))
    return [_salida(un, lat, lng) for un, lat, lng in (await db.execute(consulta)).all()]


@router.post("", response_model=UnidadSalida, status_code=201, summary="Crear unidad de negocio")
async def crear(datos: UnidadEntrada, request: Request, db: DB, actor: Actor = Depends(ADMIN)):
    tenant_id = datos.tenant_id if actor.es_superadmin else actor.tenant_id
    if tenant_id is None:
        raise ErrorAPI(422, "TENANT_REQUERIDO", "Indica tenant_id")
    validar_tenant(actor, tenant_id)
    await _validar_grupo(db, tenant_id, datos.grupo_id)
    un = UnidadNegocio(tenant_id=tenant_id, ubicacion=_punto(datos.ubicacion),
                       **datos.model_dump(exclude={"ubicacion", "tenant_id"}))
    db.add(un)
    await db.flush()
    if un.grupo_id:
        db.add(GrupoUNMiembro(tenant_id=tenant_id, grupo_id=un.grupo_id, unidad_id=un.id))
    await auditoria.registrar_actor(db, actor, "unidades_negocio.alta", request, tenant_id=tenant_id, recurso_tipo="unidad_negocio",
                                    recurso_id=un.id, despues=auditoria.instantanea(un))
    await db.commit()
    return _salida(*(await _obtener(db, actor, un.id)))


@router.get("/{unidad_id}", response_model=UnidadSalida, summary="Detalle de unidad de negocio")
async def detalle(unidad_id: UUID, db: DB, actor: Actor = Depends(LECTORES)):
    return _salida(*(await _obtener(db, actor, unidad_id)))


@router.patch("/{unidad_id}", response_model=UnidadSalida, summary="Modificar unidad de negocio")
async def modificar(unidad_id: UUID, datos: UnidadCambios, request: Request, db: DB, actor: Actor = Depends(ADMIN)):
    un, _, _ = await _obtener(db, actor, unidad_id)
    validar_tenant(actor, un.tenant_id)
    antes = auditoria.instantanea(un)
    cambios = datos.model_dump(exclude_unset=True)
    if "grupo_id" in cambios:
        await _validar_grupo(db, un.tenant_id, cambios["grupo_id"])
    if "ubicacion" in cambios:
        un.ubicacion = _punto(datos.ubicacion)
    for k, v in cambios.items():
        if k == "ubicacion" or (v is None and k != "grupo_id"):
            continue
        setattr(un, k, v)
    if cambios.get("grupo_id"):
        ya = (await db.execute(select(GrupoUNMiembro).where(
            GrupoUNMiembro.grupo_id == un.grupo_id, GrupoUNMiembro.unidad_id == un.id))).scalar_one_or_none()
        if ya is None:
            db.add(GrupoUNMiembro(tenant_id=un.tenant_id, grupo_id=un.grupo_id, unidad_id=un.id))
    await db.flush()
    await auditoria.registrar_actor(db, actor, "unidades_negocio.modificacion", request, tenant_id=un.tenant_id,
                                    recurso_tipo="unidad_negocio", recurso_id=un.id, antes=antes, despues=auditoria.instantanea(un))
    await db.commit()
    return _salida(*(await _obtener(db, actor, un.id)))


@router.get("/{unidad_id}/usuarios", response_model=list[UUID], summary="Usuarios asignados a la UN")
async def usuarios_asignados(unidad_id: UUID, db: DB, actor: Actor = Depends(ADMIN)):
    un, _, _ = await _obtener(db, actor, unidad_id)
    validar_tenant(actor, un.tenant_id)
    return (await db.execute(select(UsuarioUN.usuario_id).where(UsuarioUN.unidad_id == un.id))).scalars().all()


@router.put("/{unidad_id}/usuarios", response_model=list[UUID], summary="Asignar usuarios a la UN",
            description="Reemplaza la lista de admin_un, supervisores y operadores asignados a la UN.")
async def asignar_usuarios(unidad_id: UUID, datos: AsignacionUsuariosEntrada, request: Request, db: DB,
                           actor: Actor = Depends(ADMIN)):
    un, _, _ = await _obtener(db, actor, unidad_id)
    validar_tenant(actor, un.tenant_id)
    ids = set(datos.usuario_ids)
    if ids:
        validos = set((await db.execute(select(Usuario.id).where(
            Usuario.id.in_(ids), Usuario.tenant_id == un.tenant_id, Usuario.rol.in_(ROLES_ASIGNABLES_UN)))).scalars())
        invalidos = ids - validos
        if invalidos:
            raise ErrorAPI(422, "USUARIOS_INVALIDOS", "Usuarios inexistentes, de otro tenant o con rol no asignable a UN",
                           sorted(str(i) for i in invalidos))
    antes = set((await db.execute(select(UsuarioUN.usuario_id).where(UsuarioUN.unidad_id == un.id))).scalars())
    borrar = delete(UsuarioUN).where(UsuarioUN.unidad_id == un.id)
    if ids:
        borrar = borrar.where(UsuarioUN.usuario_id.not_in(ids))
    await db.execute(borrar)
    for uid in ids - antes:
        db.add(UsuarioUN(tenant_id=un.tenant_id, usuario_id=uid, unidad_id=un.id))
    await db.flush()
    await auditoria.registrar_actor(db, actor, "unidades_negocio.asignacion_usuarios", request, tenant_id=un.tenant_id,
                                    recurso_tipo="unidad_negocio", recurso_id=un.id,
                                    antes={"usuarios": sorted(map(str, antes))}, despues={"usuarios": sorted(map(str, ids))})
    await db.commit()
    return sorted(ids, key=str)
