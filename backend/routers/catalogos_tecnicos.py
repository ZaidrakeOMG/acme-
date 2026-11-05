"""Catálogos del prestador: habilidades, técnicos (§6.3, §6.10.8), grupos y permisos (§6.8.3) y severidades."""
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, or_, select, text

from core.dependencias import DB, Actor, requiere_rol
from core.errors import ErrorAPI, no_encontrado
from core.security import errores_politica_contrasena, hashear_contrasena_async
from models.base import Dominio, Rol
from models.catalogos import Habilidad, NivelSeveridadCatalogo, Tecnico, TecnicoHabilidad, TecnicoTenantHabilitado
from models.organizaciones import TenantPrestador
from models.permisos import GrupoTecnicoPermiso, GrupoTecnicos, TecnicoGrupo, TecnicoPermisoOverride
from models.usuarios import Usuario
from schemas.catalogos import (
    GrupoDeTecnicoEntrada, GrupoTecnicosEntrada, GrupoTecnicosSalida, HabilidadCambios, HabilidadEntrada,
    HabilidadesEntrada, HabilidadSalida, OverridesEntrada, PermisoEfectivoTecnico, SeveridadCambios, SeveridadSalida,
    TecnicoCambios, TecnicoEntrada, TecnicoSalida, TenantsHabilitadosEntrada,
)
from schemas.comun import RESPUESTAS_ERROR
from schemas.configuracion import PermisosCambios
from services import auditoria, catalogos_service, permisos_service

router = APIRouter(prefix="/api/catalogos", tags=["Catálogos · técnicos y severidades"], responses=RESPUESTAS_ERROR)

ADMIN = requiere_rol(Rol.superadmin, Rol.admin_prestador)
LECTURA = requiere_rol(Rol.superadmin, Rol.admin_prestador, Rol.mesa_control, Rol.despachador)
LECTURA_SEVERIDADES = requiere_rol(Rol.superadmin, Rol.admin_prestador, Rol.mesa_control, Rol.despachador,
                                   Rol.admin_empresa, Rol.admin_un)
_EMAIL_EXISTE = text("SELECT EXISTS (SELECT 1 FROM auth_identidad_por_email(:e))")


def prestador_de(actor: Actor, prestador_id: UUID | None) -> UUID:
    """Ámbito del prestador: el propio; superadmin lo indica con ?prestador_id=."""
    if actor.es_superadmin:
        if prestador_id is None:
            raise ErrorAPI(422, "PRESTADOR_REQUERIDO", "Indica prestador_id")
        return prestador_id
    if actor.prestador_id is None:
        raise ErrorAPI(403, "PROHIBIDO", "Tu usuario no pertenece a un prestador")
    return actor.prestador_id


# ------------------------------------------------------------- habilidades

@router.get("/habilidades", response_model=list[HabilidadSalida], summary="Habilidades del prestador")
async def listar_habilidades(db: DB, actor: Actor = Depends(LECTURA), prestador_id: UUID | None = None,
                             incluir_inactivas: bool = False):
    p = prestador_de(actor, prestador_id)
    consulta = select(Habilidad).where(Habilidad.prestador_id == p).order_by(Habilidad.nombre)
    if not incluir_inactivas:
        consulta = consulta.where(Habilidad.activa.is_(True))
    return (await db.execute(consulta)).scalars().all()


@router.post("/habilidades", response_model=HabilidadSalida, status_code=201, summary="Crear habilidad")
async def crear_habilidad(datos: HabilidadEntrada, request: Request, db: DB, actor: Actor = Depends(ADMIN),
                          prestador_id: UUID | None = None):
    p = prestador_de(actor, prestador_id)
    h = Habilidad(prestador_id=p, **datos.model_dump())
    db.add(h)
    await db.flush()
    await auditoria.registrar_actor(db, actor, "catalogos.habilidad_alta", request, prestador_id=p, recurso_tipo="habilidad",
                                    recurso_id=h.id, despues=auditoria.instantanea(h))
    await db.commit()
    return h


@router.patch("/habilidades/{habilidad_id}", response_model=HabilidadSalida, summary="Modificar habilidad")
async def modificar_habilidad(habilidad_id: UUID, datos: HabilidadCambios, request: Request, db: DB,
                              actor: Actor = Depends(ADMIN), prestador_id: UUID | None = None):
    p = prestador_de(actor, prestador_id)
    h = await db.get(Habilidad, habilidad_id)
    if h is None or h.prestador_id != p:
        raise no_encontrado("Habilidad")
    antes = auditoria.instantanea(h)
    for k, v in datos.model_dump(exclude_unset=True, exclude_none=True).items():
        setattr(h, k, v)
    await db.flush()
    await auditoria.registrar_actor(db, actor, "catalogos.habilidad_modificacion", request, prestador_id=p,
                                    recurso_tipo="habilidad", recurso_id=h.id, antes=antes, despues=auditoria.instantanea(h))
    await db.commit()
    await db.refresh(h)
    return h


# ---------------------------------------------------------------- técnicos

async def _salida_tecnico(db, t: Tecnico, usuario: Usuario | None = None) -> TecnicoSalida:
    usuario = usuario or await db.get(Usuario, t.usuario_id)
    hoy = date.today()
    habilidades = (await db.execute(
        select(TecnicoHabilidad, Habilidad).join(Habilidad, Habilidad.id == TecnicoHabilidad.habilidad_id)
        .where(TecnicoHabilidad.tecnico_id == t.id).order_by(Habilidad.nombre))).all()
    tenants = (await db.execute(select(TecnicoTenantHabilitado.tenant_id).where(
        TecnicoTenantHabilitado.tecnico_id == t.id, TecnicoTenantHabilitado.activo.is_(True)))).scalars().all()
    grupo = (await db.execute(select(TecnicoGrupo.grupo_id).where(TecnicoGrupo.tecnico_id == t.usuario_id))).scalar_one_or_none()
    return TecnicoSalida(
        **{k: getattr(t, k) for k in ("id", "created_at", "updated_at", "version_hash", "prestador_id", "usuario_id",
                                      "numero_empleado", "telefono", "vehiculo_placas", "estado", "fecha_ingreso")},
        nombre=usuario.nombre, email=usuario.email,
        habilidades=[{
            "habilidad_id": h.id, "clave": h.clave, "nombre": h.nombre, "certificada": th.certificada,
            "fecha_certificacion": th.fecha_certificacion, "vigencia_hasta": th.vigencia_hasta, "origen": th.origen,
            "vigente": th.certificada and (th.vigencia_hasta is None or th.vigencia_hasta >= hoy),
        } for th, h in habilidades],
        tenants_habilitados=list(tenants), grupo_id=grupo,
    )


async def _tecnico(db, actor: Actor, tecnico_id: UUID, prestador_id: UUID | None) -> Tecnico:
    p = prestador_de(actor, prestador_id)
    t = await db.get(Tecnico, tecnico_id)
    if t is None or t.prestador_id != p:
        raise no_encontrado("Técnico")
    return t


@router.get("/tecnicos", response_model=list[TecnicoSalida], summary="Listar técnicos",
            description="Búsqueda por nombre, correo o número de empleado (`q`, desde 1 caracter) y filtro por habilidad certificada.")
async def listar_tecnicos(db: DB, actor: Actor = Depends(LECTURA), prestador_id: UUID | None = None,
                          q: str | None = Query(default=None, max_length=100), habilidad_id: UUID | None = None,
                          solo_activos: bool = False, limite: int = Query(default=200, ge=1, le=1000)):
    p = prestador_de(actor, prestador_id)
    consulta = (select(Tecnico, Usuario).join(Usuario, Usuario.id == Tecnico.usuario_id)
                .where(Tecnico.prestador_id == p).order_by(Usuario.nombre).limit(limite))
    if q:
        patron = f"%{q.lower()}%"
        consulta = consulta.where(or_(func.lower(Usuario.nombre).like(patron), func.lower(Usuario.email).like(patron),
                                      func.lower(func.coalesce(Tecnico.numero_empleado, "")).like(patron)))
    if habilidad_id:
        consulta = consulta.where(Tecnico.id.in_(select(TecnicoHabilidad.tecnico_id).where(
            TecnicoHabilidad.habilidad_id == habilidad_id, TecnicoHabilidad.certificada.is_(True))))
    if solo_activos:
        consulta = consulta.where(Tecnico.estado == "activo")
    return [await _salida_tecnico(db, t, u) for t, u in (await db.execute(consulta)).all()]


@router.post("/tecnicos", response_model=TecnicoSalida, status_code=201, summary="Crear técnico",
             description="Vincula un usuario existente con rol técnico (`usuario_id`) o crea uno nuevo (`email`, `nombre`, `contrasena`).")
async def crear_tecnico(datos: TecnicoEntrada, request: Request, db: DB, actor: Actor = Depends(ADMIN),
                        prestador_id: UUID | None = None):
    p = prestador_de(actor, prestador_id)
    if datos.usuario_id:
        usuario = await db.get(Usuario, datos.usuario_id)
        if usuario is None or usuario.prestador_id != p or usuario.rol != Rol.tecnico:
            raise ErrorAPI(422, "USUARIO_INVALIDO", "El usuario debe existir, ser del prestador y tener rol técnico")
        ya = (await db.execute(select(Tecnico.id).where(Tecnico.usuario_id == usuario.id))).first()
        if ya:
            raise ErrorAPI(409, "TECNICO_DUPLICADO", "Ese usuario ya tiene ficha de técnico")
    else:
        errores = errores_politica_contrasena(datos.contrasena or "")
        if errores:
            raise ErrorAPI(422, "POLITICA_CONTRASENA", "La contraseña no cumple la política", errores)
        if (await db.execute(_EMAIL_EXISTE, {"e": datos.email})).scalar():
            raise ErrorAPI(409, "EMAIL_DUPLICADO", "Ya existe un usuario con ese correo")
        usuario = Usuario(email=str(datos.email).lower(), nombre=datos.nombre, telefono=datos.telefono, rol=Rol.tecnico,
                          dominio=Dominio.prestador, prestador_id=p, password_hash=await hashear_contrasena_async(datos.contrasena))
        db.add(usuario)
        await db.flush()
        await auditoria.registrar_actor(db, actor, "usuarios.alta", request, prestador_id=p, recurso_tipo="usuario",
                                        recurso_id=usuario.id, despues=auditoria.instantanea(usuario))
    t = Tecnico(prestador_id=p, usuario_id=usuario.id, numero_empleado=datos.numero_empleado,
                telefono=datos.telefono or usuario.telefono, vehiculo_placas=datos.vehiculo_placas, fecha_ingreso=datos.fecha_ingreso)
    db.add(t)
    await db.flush()
    await auditoria.registrar_actor(db, actor, "catalogos.tecnico_alta", request, prestador_id=p, recurso_tipo="tecnico",
                                    recurso_id=t.id, despues=auditoria.instantanea(t))
    await db.commit()
    return await _salida_tecnico(db, t, usuario)


@router.get("/tecnicos/{tecnico_id}", response_model=TecnicoSalida, summary="Ficha del técnico")
async def detalle_tecnico(tecnico_id: UUID, db: DB, actor: Actor = Depends(LECTURA), prestador_id: UUID | None = None):
    return await _salida_tecnico(db, await _tecnico(db, actor, tecnico_id, prestador_id))


@router.patch("/tecnicos/{tecnico_id}", response_model=TecnicoSalida, summary="Modificar técnico")
async def modificar_tecnico(tecnico_id: UUID, datos: TecnicoCambios, request: Request, db: DB, actor: Actor = Depends(ADMIN),
                            prestador_id: UUID | None = None):
    t = await _tecnico(db, actor, tecnico_id, prestador_id)
    antes = auditoria.instantanea(t)
    for k, v in datos.model_dump(exclude_unset=True).items():
        if v is not None or k in ("numero_empleado", "vehiculo_placas", "fecha_ingreso", "telefono"):
            setattr(t, k, v)
    await db.flush()
    await auditoria.registrar_actor(db, actor, "catalogos.tecnico_modificacion", request, prestador_id=t.prestador_id,
                                    recurso_tipo="tecnico", recurso_id=t.id, antes=antes, despues=auditoria.instantanea(t))
    await db.commit()
    await db.refresh(t)
    return await _salida_tecnico(db, t)


@router.put("/tecnicos/{tecnico_id}/habilidades", response_model=TecnicoSalida, summary="Definir habilidades del técnico",
            description="Reemplaza la lista de habilidades con su certificación y vigencia.")
async def definir_habilidades(tecnico_id: UUID, datos: HabilidadesEntrada, request: Request, db: DB,
                              actor: Actor = Depends(ADMIN), prestador_id: UUID | None = None):
    t = await _tecnico(db, actor, tecnico_id, prestador_id)
    ids = {h.habilidad_id for h in datos.habilidades}
    if len(ids) != len(datos.habilidades):
        raise ErrorAPI(422, "HABILIDAD_REPETIDA", "Una habilidad aparece más de una vez")
    if ids:
        validas = set((await db.execute(select(Habilidad.id).where(
            Habilidad.id.in_(ids), Habilidad.prestador_id == t.prestador_id))).scalars())
        if ids - validas:
            raise ErrorAPI(422, "HABILIDADES_INVALIDAS", "Habilidades inexistentes o de otro prestador", sorted(map(str, ids - validas)))
    actuales = {th.habilidad_id: th for th in (await db.execute(
        select(TecnicoHabilidad).where(TecnicoHabilidad.tecnico_id == t.id))).scalars()}
    antes = {str(k): v.certificada for k, v in actuales.items()}
    for hid, fila in actuales.items():
        if hid not in ids:
            await db.delete(fila)
    for h in datos.habilidades:
        fila = actuales.get(h.habilidad_id)
        if fila is None:
            db.add(TecnicoHabilidad(prestador_id=t.prestador_id, tecnico_id=t.id, **h.model_dump()))
        else:
            for k, v in h.model_dump().items():
                setattr(fila, k, v)
    await db.flush()
    await auditoria.registrar_actor(db, actor, "catalogos.tecnico_habilidades", request, prestador_id=t.prestador_id,
                                    recurso_tipo="tecnico", recurso_id=t.id, antes=antes,
                                    despues={str(h.habilidad_id): h.certificada for h in datos.habilidades})
    await db.commit()
    return await _salida_tecnico(db, t)


@router.put("/tecnicos/{tecnico_id}/tenants", response_model=TecnicoSalida, summary="Tenants habilitados del técnico",
            description="§6.10.8: clientes adicionales que puede atender. Solo tenants vinculados al prestador.")
async def definir_tenants(tecnico_id: UUID, datos: TenantsHabilitadosEntrada, request: Request, db: DB,
                          actor: Actor = Depends(ADMIN), prestador_id: UUID | None = None):
    t = await _tecnico(db, actor, tecnico_id, prestador_id)
    ids = set(datos.tenant_ids)
    if ids:
        vinculados = set((await db.execute(select(TenantPrestador.tenant_id).where(
            TenantPrestador.prestador_id == t.prestador_id, TenantPrestador.tenant_id.in_(ids)))).scalars())
        if ids - vinculados:
            raise ErrorAPI(422, "TENANT_NO_VINCULADO", "Clientes no vinculados al prestador", sorted(map(str, ids - vinculados)))
    actuales = {f.tenant_id: f for f in (await db.execute(
        select(TecnicoTenantHabilitado).where(TecnicoTenantHabilitado.tecnico_id == t.id))).scalars()}
    antes = sorted(str(k) for k, v in actuales.items() if v.activo)
    for tid, fila in actuales.items():
        fila.activo = tid in ids
    for tid in ids - set(actuales):
        db.add(TecnicoTenantHabilitado(prestador_id=t.prestador_id, tecnico_id=t.id, tenant_id=tid, habilitado_por=actor.id))
    await db.flush()
    await auditoria.registrar_actor(db, actor, "catalogos.tecnico_tenants", request, prestador_id=t.prestador_id,
                                    recurso_tipo="tecnico", recurso_id=t.id, antes={"tenants": antes},
                                    despues={"tenants": sorted(map(str, ids))})
    await db.commit()
    return await _salida_tecnico(db, t)


# ------------------------------------------------- grupos y permisos (§6.8.3)

async def _salida_grupo(db, g: GrupoTecnicos) -> GrupoTecnicosSalida:
    permisos = {r.permiso_clave: r.habilitado for r in (await db.execute(
        select(GrupoTecnicoPermiso).where(GrupoTecnicoPermiso.grupo_id == g.id))).scalars()}
    return GrupoTecnicosSalida(**{k: getattr(g, k) for k in ("id", "created_at", "updated_at", "version_hash",
                                                             "prestador_id", "nombre", "descripcion")}, permisos=permisos)


async def _grupo(db, p: UUID, grupo_id: UUID) -> GrupoTecnicos:
    g = await db.get(GrupoTecnicos, grupo_id)
    if g is None or g.prestador_id != p:
        raise no_encontrado("Grupo de técnicos")
    return g


@router.get("/grupos-tecnicos", response_model=list[GrupoTecnicosSalida], summary="Grupos de técnicos (Junior, Senior…)")
async def listar_grupos(db: DB, actor: Actor = Depends(LECTURA), prestador_id: UUID | None = None):
    p = prestador_de(actor, prestador_id)
    grupos = (await db.execute(select(GrupoTecnicos).where(GrupoTecnicos.prestador_id == p).order_by(GrupoTecnicos.nombre))).scalars()
    return [await _salida_grupo(db, g) for g in grupos]


@router.post("/grupos-tecnicos", response_model=GrupoTecnicosSalida, status_code=201, summary="Crear grupo de técnicos")
async def crear_grupo(datos: GrupoTecnicosEntrada, request: Request, db: DB, actor: Actor = Depends(ADMIN),
                      prestador_id: UUID | None = None):
    p = prestador_de(actor, prestador_id)
    g = GrupoTecnicos(prestador_id=p, **datos.model_dump())
    db.add(g)
    await db.flush()
    await auditoria.registrar_actor(db, actor, "catalogos.grupo_tecnicos_alta", request, prestador_id=p,
                                    recurso_tipo="grupo_tecnicos", recurso_id=g.id, despues=auditoria.instantanea(g))
    await db.commit()
    return await _salida_grupo(db, g)


@router.put("/grupos-tecnicos/{grupo_id}/permisos", response_model=GrupoTecnicosSalida, summary="Permisos del grupo")
async def permisos_grupo(grupo_id: UUID, datos: PermisosCambios, request: Request, db: DB, actor: Actor = Depends(ADMIN),
                         prestador_id: UUID | None = None):
    p = prestador_de(actor, prestador_id)
    g = await _grupo(db, p, grupo_id)
    await permisos_service.validar_claves_tecnico(db, set(datos.valores))
    actuales = {r.permiso_clave: r for r in (await db.execute(
        select(GrupoTecnicoPermiso).where(GrupoTecnicoPermiso.grupo_id == g.id))).scalars()}
    antes = {k: v.habilitado for k, v in actuales.items()}
    for clave, valor in datos.valores.items():
        if clave in actuales:
            actuales[clave].habilitado = valor
        else:
            db.add(GrupoTecnicoPermiso(prestador_id=p, grupo_id=g.id, permiso_clave=clave, habilitado=valor))
    await db.flush()
    await auditoria.registrar_actor(db, actor, "permisos.grupo_tecnicos", request, prestador_id=p, recurso_tipo="grupo_tecnicos",
                                    recurso_id=g.id, antes=antes, despues=datos.valores)
    await db.commit()
    return await _salida_grupo(db, g)


@router.put("/tecnicos/{tecnico_id}/grupo", response_model=TecnicoSalida, summary="Asignar grupo al técnico")
async def asignar_grupo(tecnico_id: UUID, datos: GrupoDeTecnicoEntrada, request: Request, db: DB,
                        actor: Actor = Depends(ADMIN), prestador_id: UUID | None = None):
    t = await _tecnico(db, actor, tecnico_id, prestador_id)
    actual = (await db.execute(select(TecnicoGrupo).where(TecnicoGrupo.tecnico_id == t.usuario_id))).scalar_one_or_none()
    antes = str(actual.grupo_id) if actual else None
    if datos.grupo_id is None:
        if actual:
            await db.delete(actual)
    else:
        await _grupo(db, t.prestador_id, datos.grupo_id)
        if actual:
            actual.grupo_id = datos.grupo_id
            actual.fecha_asignacion = date.today()
        else:
            db.add(TecnicoGrupo(prestador_id=t.prestador_id, tecnico_id=t.usuario_id, grupo_id=datos.grupo_id))
    await db.flush()
    await auditoria.registrar_actor(db, actor, "permisos.tecnico_grupo", request, prestador_id=t.prestador_id,
                                    recurso_tipo="tecnico", recurso_id=t.id, antes={"grupo_id": antes},
                                    despues={"grupo_id": str(datos.grupo_id) if datos.grupo_id else None})
    await db.commit()
    return await _salida_tecnico(db, t)


@router.put("/tecnicos/{tecnico_id}/permisos", response_model=list[PermisoEfectivoTecnico], summary="Overrides individuales",
            description="Sobrescribe permisos del técnico por encima o por debajo de su grupo (`habilitado: null` elimina el override).")
async def definir_overrides(tecnico_id: UUID, datos: OverridesEntrada, request: Request, db: DB,
                            actor: Actor = Depends(ADMIN), prestador_id: UUID | None = None):
    t = await _tecnico(db, actor, tecnico_id, prestador_id)
    await permisos_service.validar_claves_tecnico(db, {o.permiso_clave for o in datos.overrides})
    actuales = {r.permiso_clave: r for r in (await db.execute(
        select(TecnicoPermisoOverride).where(TecnicoPermisoOverride.tecnico_id == t.usuario_id))).scalars()}
    antes = {k: v.habilitado for k, v in actuales.items()}
    for o in datos.overrides:
        fila = actuales.get(o.permiso_clave)
        if o.habilitado is None:
            if fila:
                await db.delete(fila)
            continue
        if fila is None:
            db.add(TecnicoPermisoOverride(prestador_id=t.prestador_id, tecnico_id=t.usuario_id, permiso_clave=o.permiso_clave,
                                          habilitado=o.habilitado, razon=o.razon, modificado_por=actor.id))
        else:
            fila.habilitado, fila.razon, fila.modificado_por = o.habilitado, o.razon, actor.id
    await db.flush()
    await auditoria.registrar_actor(db, actor, "permisos.tecnico_override", request, prestador_id=t.prestador_id,
                                    recurso_tipo="tecnico", recurso_id=t.id, antes=antes,
                                    despues={o.permiso_clave: o.habilitado for o in datos.overrides})
    await db.commit()
    return await permisos_service.efectivos_de_tecnico(db, t.prestador_id, t.usuario_id)


@router.get("/tecnicos/{tecnico_id}/permisos-efectivos", response_model=list[PermisoEfectivoTecnico],
            summary="Permisos efectivos del técnico", description="Override individual > grupo > valor del prestador > default del catálogo.")
async def permisos_efectivos(tecnico_id: UUID, db: DB, actor: Actor = Depends(LECTURA), prestador_id: UUID | None = None):
    t = await _tecnico(db, actor, tecnico_id, prestador_id)
    return await permisos_service.efectivos_de_tecnico(db, t.prestador_id, t.usuario_id)


# --------------------------------------------------------------- severidades

@router.get("/severidades", response_model=list[SeveridadSalida], summary="Niveles de severidad",
            description="Los 5 niveles del prestador (§6.10.1). Los usuarios del tenant ven los de sus prestadores vigentes.")
async def listar_severidades(db: DB, actor: Actor = Depends(LECTURA_SEVERIDADES), prestador_id: UUID | None = None):
    consulta = select(NivelSeveridadCatalogo).order_by(NivelSeveridadCatalogo.prestador_id, NivelSeveridadCatalogo.orden)
    if actor.dominio == Dominio.tenant:
        consulta = consulta.where(NivelSeveridadCatalogo.prestador_id.in_(
            await catalogos_service.prestadores_del_tenant(db, actor.tenant_id)))
    else:
        consulta = consulta.where(NivelSeveridadCatalogo.prestador_id == prestador_de(actor, prestador_id))
    return (await db.execute(consulta)).scalars().all()


@router.patch("/severidades/{nivel_id}", response_model=SeveridadSalida, summary="Modificar nivel de severidad",
              description="Nombre, color y tiempos de referencia. La clave y el orden (1 = muy baja … 5 = crítica) son fijos.")
async def modificar_severidad(nivel_id: UUID, datos: SeveridadCambios, request: Request, db: DB, actor: Actor = Depends(ADMIN),
                              prestador_id: UUID | None = None):
    p = prestador_de(actor, prestador_id)
    n = await db.get(NivelSeveridadCatalogo, nivel_id)
    if n is None or n.prestador_id != p:
        raise no_encontrado("Nivel de severidad")
    antes = auditoria.instantanea(n)
    for k, v in datos.model_dump(exclude_unset=True, exclude_none=True).items():
        setattr(n, k, v)
    if n.tiempo_resolucion_horas < n.tiempo_respuesta_horas:
        raise ErrorAPI(422, "TIEMPOS_INVALIDOS", "El tiempo de resolución no puede ser menor al de respuesta")
    await db.flush()
    await auditoria.registrar_actor(db, actor, "catalogos.severidad_modificacion", request, prestador_id=p,
                                    recurso_tipo="nivel_severidad", recurso_id=n.id, antes=antes, despues=auditoria.instantanea(n))
    await db.commit()
    await db.refresh(n)
    return n

