"""Catálogos del tenant y plataforma: familias y tipos de equipo (cascada §4.3), equipos (§6.8.6), tipos de falla y matriz."""
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, or_, select

from core.dependencias import DB, Actor, requiere_rol, validar_tenant
from core.errors import ErrorAPI, no_encontrado, prohibido
from models.base import Dominio, Rol
from models.catalogos import Equipo, EstadoActivo, FamiliaEquipo, NivelSeveridadCatalogo, TipoEquipo, TipoFalla, TipoFallaSeveridad
from models.contratos import Contrato
from models.unidades import UnidadNegocio
from routers.catalogos_tecnicos import prestador_de
from routers.unidades_negocio import filtro_visibilidad
from schemas.catalogos import (
    CeldaMatriz, EquipoCambios, EquipoEntrada, EquipoSalida, FamiliaCambios, FamiliaEntrada, FamiliaSalida,
    MatrizMasivaEntrada, MatrizSalida, NivelMatriz, SeveridadResuelta, TipoEquipoCambios, TipoEquipoEntrada,
    TipoEquipoSalida, TipoFallaCambios, TipoFallaEntrada, TipoFallaSalida,
)
from schemas.comun import RESPUESTAS_ERROR
from services import auditoria, catalogos_service

router = APIRouter(prefix="/api/catalogos", tags=["Catálogos · equipos, fallas y matriz"], responses=RESPUESTAS_ERROR)

TODOS = requiere_rol(*Rol)
ADMIN_TENANT = requiere_rol(Rol.superadmin)
ADMIN_EQUIPOS = requiere_rol(Rol.superadmin)
ADMIN_PRESTADOR = requiere_rol(Rol.superadmin)
LECTURA_FALLAS = requiere_rol(Rol.superadmin, Rol.admin_prestador, Rol.mesa_control, Rol.despachador, Rol.tecnico,
                              Rol.admin_empresa, Rol.admin_un, Rol.supervisor_operadores, Rol.operador)


def tenant_de(actor: Actor, tenant_id: UUID | None) -> UUID:
    if actor.es_superadmin:
        if tenant_id is None:
            raise ErrorAPI(422, "TENANT_REQUERIDO", "Indica tenant_id")
        return tenant_id
    if actor.tenant_id is None:
        raise prohibido("Tu usuario no pertenece a un cliente")
    return actor.tenant_id


def _tenant_opcional(actor: Actor, tenant_id: UUID | None) -> UUID | None:
    """Ámbito de lectura de familias/tipos: el tenant del actor; superadmin y prestador pueden indicar uno."""
    return actor.tenant_id if actor.dominio == Dominio.tenant else tenant_id


# ----------------------------------------------------------- familias

def _familia_salida(f: FamiliaEquipo) -> FamiliaSalida:
    return FamiliaSalida(**{k: getattr(f, k) for k in FamiliaSalida.model_fields if k != "es_global"}, es_global=f.tenant_id is None)


@router.get("/familias-equipo", response_model=list[FamiliaSalida], summary="Familias de equipo",
            description="Globales de plataforma más las propias del tenant.")
async def listar_familias(db: DB, actor: Actor = Depends(TODOS), tenant_id: UUID | None = None, incluir_inactivas: bool = False):
    t = _tenant_opcional(actor, tenant_id)
    consulta = select(FamiliaEquipo).where(or_(FamiliaEquipo.tenant_id.is_(None), FamiliaEquipo.tenant_id == t)).order_by(FamiliaEquipo.nombre)
    if not incluir_inactivas:
        consulta = consulta.where(FamiliaEquipo.activa.is_(True))
    return [_familia_salida(f) for f in (await db.execute(consulta)).scalars()]


def _ambito_global(actor: Actor, es_global: bool, tenant_id: UUID | None) -> UUID | None:
    if es_global:
        if not actor.es_superadmin:
            raise prohibido("Solo el superadmin crea catálogos globales")
        return None
    return tenant_de(actor, tenant_id)


@router.post("/familias-equipo", response_model=FamiliaSalida, status_code=201, summary="Crear familia de equipo",
             description="`global: true` (solo superadmin) crea una familia de plataforma visible para todos los tenants.")
async def crear_familia(datos: FamiliaEntrada, request: Request, db: DB, actor: Actor = Depends(ADMIN_TENANT),
                        tenant_id: UUID | None = None):
    t = _ambito_global(actor, datos.global_, tenant_id)
    f = FamiliaEquipo(tenant_id=t, nombre=datos.nombre, descripcion=datos.descripcion, habilidad_clave=datos.habilidad_clave)
    db.add(f)
    await db.flush()
    await auditoria.registrar_actor(db, actor, "catalogos.familia_alta", request, tenant_id=t, recurso_tipo="familia_equipo",
                                    recurso_id=f.id, despues=auditoria.instantanea(f))
    await db.commit()
    return _familia_salida(f)


async def _familia_editable(db, actor: Actor, familia_id: UUID, tenant_id: UUID | None) -> FamiliaEquipo:
    f = await db.get(FamiliaEquipo, familia_id)
    if f is None:
        raise no_encontrado("Familia")
    if f.tenant_id is None:
        if not actor.es_superadmin:
            raise prohibido("Las familias globales solo las edita el superadmin")
    else:
        validar_tenant(actor, f.tenant_id)
        if actor.es_superadmin and tenant_id and f.tenant_id != tenant_id:
            raise no_encontrado("Familia")
    return f


@router.patch("/familias-equipo/{familia_id}", response_model=FamiliaSalida, summary="Modificar familia")
async def modificar_familia(familia_id: UUID, datos: FamiliaCambios, request: Request, db: DB, actor: Actor = Depends(ADMIN_TENANT),
                            tenant_id: UUID | None = None):
    f = await _familia_editable(db, actor, familia_id, tenant_id)
    antes = auditoria.instantanea(f)
    for k, v in datos.model_dump(exclude_unset=True, exclude_none=True).items():
        setattr(f, k, v)
    await db.flush()
    await auditoria.registrar_actor(db, actor, "catalogos.familia_modificacion", request, tenant_id=f.tenant_id,
                                    recurso_tipo="familia_equipo", recurso_id=f.id, antes=antes, despues=auditoria.instantanea(f))
    await db.commit()
    await db.refresh(f)
    return _familia_salida(f)


# -------------------------------------------------------- tipos de equipo

def _tipo_salida(t: TipoEquipo) -> TipoEquipoSalida:
    return TipoEquipoSalida(**{k: getattr(t, k) for k in TipoEquipoSalida.model_fields if k != "es_global"}, es_global=t.tenant_id is None)


@router.get("/tipos-equipo", response_model=list[TipoEquipoSalida], summary="Tipos de equipo",
            description="Cascada §4.3: `familia_id` devuelve solo los tipos de esa familia.")
async def listar_tipos_equipo(db: DB, actor: Actor = Depends(TODOS), tenant_id: UUID | None = None,
                              familia_id: UUID | None = None, incluir_inactivos: bool = False):
    t = _tenant_opcional(actor, tenant_id)
    consulta = select(TipoEquipo).where(or_(TipoEquipo.tenant_id.is_(None), TipoEquipo.tenant_id == t)).order_by(TipoEquipo.nombre)
    if familia_id:
        consulta = consulta.where(TipoEquipo.familia_id == familia_id)
    if not incluir_inactivos:
        consulta = consulta.where(TipoEquipo.activa.is_(True))
    return [_tipo_salida(x) for x in (await db.execute(consulta)).scalars()]


@router.post("/tipos-equipo", response_model=TipoEquipoSalida, status_code=201, summary="Crear tipo de equipo",
             description="Un tenant puede crear tipos dentro de familias globales o propias.")
async def crear_tipo_equipo(datos: TipoEquipoEntrada, request: Request, db: DB, actor: Actor = Depends(ADMIN_TENANT),
                            tenant_id: UUID | None = None):
    t = _ambito_global(actor, datos.global_, tenant_id)
    familia = await catalogos_service.familia_visible(db, datos.familia_id, t)
    if familia is None or (t is None and familia.tenant_id is not None):
        raise ErrorAPI(422, "FAMILIA_INVALIDA", "La familia no existe o no es visible para este ámbito")
    x = TipoEquipo(tenant_id=t, familia_id=datos.familia_id, nombre=datos.nombre, descripcion=datos.descripcion)
    db.add(x)
    await db.flush()
    await auditoria.registrar_actor(db, actor, "catalogos.tipo_equipo_alta", request, tenant_id=t, recurso_tipo="tipo_equipo",
                                    recurso_id=x.id, despues=auditoria.instantanea(x))
    await db.commit()
    return _tipo_salida(x)


@router.patch("/tipos-equipo/{tipo_id}", response_model=TipoEquipoSalida, summary="Modificar tipo de equipo")
async def modificar_tipo_equipo(tipo_id: UUID, datos: TipoEquipoCambios, request: Request, db: DB,
                                actor: Actor = Depends(ADMIN_TENANT), tenant_id: UUID | None = None):
    x = await db.get(TipoEquipo, tipo_id)
    if x is None:
        raise no_encontrado("Tipo de equipo")
    if x.tenant_id is None:
        if not actor.es_superadmin:
            raise prohibido("Los tipos globales solo los edita el superadmin")
    else:
        validar_tenant(actor, x.tenant_id)
    antes = auditoria.instantanea(x)
    for k, v in datos.model_dump(exclude_unset=True, exclude_none=True).items():
        setattr(x, k, v)
    await db.flush()
    await auditoria.registrar_actor(db, actor, "catalogos.tipo_equipo_modificacion", request, tenant_id=x.tenant_id,
                                    recurso_tipo="tipo_equipo", recurso_id=x.id, antes=antes, despues=auditoria.instantanea(x))
    await db.commit()
    await db.refresh(x)
    return _tipo_salida(x)


# ----------------------------------------------------------------- equipos

def _equipo_salida(e: Equipo, familia_id: UUID | None, con_contrato: bool) -> EquipoSalida:
    return EquipoSalida(**{k: getattr(e, k) for k in EquipoSalida.model_fields
                           if k not in ("familia_id", "con_contrato_activo", "en_garantia")},
                        familia_id=familia_id, con_contrato_activo=con_contrato, en_garantia=catalogos_service.en_garantia(e))


def _consulta_equipos(actor: Actor):
    consulta = (select(Equipo, TipoEquipo.familia_id, catalogos_service.CON_CONTRATO)
                .join(TipoEquipo, TipoEquipo.id == Equipo.tipo_equipo_id)
                .join(UnidadNegocio, UnidadNegocio.id == Equipo.un_id))
    filtro = filtro_visibilidad(actor)  # misma visibilidad por UN que en unidades_negocio (§5)
    return consulta.where(filtro) if filtro is not None else consulta


async def _equipo(db, actor: Actor, equipo_id: UUID) -> tuple[Equipo, UUID, bool]:
    fila = (await db.execute(_consulta_equipos(actor).where(Equipo.id == equipo_id))).first()
    if fila is None:
        raise no_encontrado("Equipo")
    return fila[0], fila[1], bool(fila[2])


async def _validar_equipo(db, actor: Actor, tenant_id: UUID, un_id: UUID | None, tipo_equipo_id: UUID | None,
                          contrato_id: UUID | None) -> None:
    if un_id is not None:
        consulta = select(UnidadNegocio).where(UnidadNegocio.id == un_id, UnidadNegocio.tenant_id == tenant_id)
        filtro = filtro_visibilidad(actor)
        if filtro is not None:
            consulta = consulta.where(filtro)
        if (await db.execute(consulta)).scalar_one_or_none() is None:
            raise ErrorAPI(422, "UNIDAD_INVALIDA", "La unidad no existe, es de otro cliente o no la administras")
    if tipo_equipo_id is not None:
        tipo = await db.get(TipoEquipo, tipo_equipo_id)
        if tipo is None or (tipo.tenant_id is not None and tipo.tenant_id != tenant_id):
            raise ErrorAPI(422, "TIPO_EQUIPO_INVALIDO", "El tipo de equipo no existe o no es visible para el cliente")
    if contrato_id is not None:
        c = await db.get(Contrato, contrato_id)
        if c is None or c.tenant_id != tenant_id:
            raise ErrorAPI(422, "CONTRATO_INVALIDO", "El contrato no existe o es de otro cliente")


@router.get("/equipos", response_model=list[EquipoSalida], summary="Listar equipos",
            description="Filtros: `un_id`, `q` (código, nombre, serie), `con_contrato=true` devuelve solo equipos con contrato "
                        "activo (selector filtrado §6.8.6). Técnico y despachador ven los de los clientes que atienden.")
async def listar_equipos(db: DB, actor: Actor = Depends(TODOS), tenant_id: UUID | None = None, un_id: UUID | None = None,
                         q: str | None = Query(default=None, max_length=100), con_contrato: bool = False,
                         solo_activos: bool = True, limite: int = Query(default=500, ge=1, le=5000)):
    consulta = _consulta_equipos(actor).order_by(Equipo.codigo).limit(limite)
    if actor.es_superadmin and tenant_id:
        consulta = consulta.where(Equipo.tenant_id == tenant_id)
    if un_id:
        consulta = consulta.where(Equipo.un_id == un_id)
    if q:
        patron = f"%{q.lower()}%"
        consulta = consulta.where(or_(func.lower(Equipo.codigo).like(patron), func.lower(Equipo.nombre).like(patron),
                                      func.lower(func.coalesce(Equipo.numero_serie, "")).like(patron)))
    if con_contrato:
        consulta = consulta.where(catalogos_service.CON_CONTRATO.is_(True))
    if solo_activos:
        consulta = consulta.where(Equipo.estado == EstadoActivo.activo)
    return [_equipo_salida(e, fam, bool(cc)) for e, fam, cc in (await db.execute(consulta)).all()]


@router.post("/equipos", response_model=EquipoSalida, status_code=201, summary="Crear equipo",
             description="admin_un solo en sus UNs asignadas. `contrato_id` vacío = cobertura por contrato de todas las UN.")
async def crear_equipo(datos: EquipoEntrada, request: Request, db: DB, actor: Actor = Depends(ADMIN_EQUIPOS),
                       tenant_id: UUID | None = None):
    t = tenant_de(actor, tenant_id)
    await _validar_equipo(db, actor, t, datos.un_id, datos.tipo_equipo_id, datos.contrato_id)
    e = Equipo(tenant_id=t, **datos.model_dump())
    db.add(e)
    await db.flush()
    await auditoria.registrar_actor(db, actor, "catalogos.equipo_alta", request, tenant_id=t, recurso_tipo="equipo",
                                    recurso_id=e.id, despues=auditoria.instantanea(e))
    await db.commit()
    return _equipo_salida(*(await _equipo(db, actor, e.id)))


@router.get("/equipos/{equipo_id}", response_model=EquipoSalida, summary="Ficha del equipo")
async def detalle_equipo(equipo_id: UUID, db: DB, actor: Actor = Depends(TODOS)):
    return _equipo_salida(*(await _equipo(db, actor, equipo_id)))


@router.patch("/equipos/{equipo_id}", response_model=EquipoSalida, summary="Modificar equipo")
async def modificar_equipo(equipo_id: UUID, datos: EquipoCambios, request: Request, db: DB, actor: Actor = Depends(ADMIN_EQUIPOS)):
    e, _, _ = await _equipo(db, actor, equipo_id)
    validar_tenant(actor, e.tenant_id)
    cambios = datos.model_dump(exclude_unset=True)
    await _validar_equipo(db, actor, e.tenant_id, cambios.get("un_id"), cambios.get("tipo_equipo_id"), cambios.get("contrato_id"))
    antes = auditoria.instantanea(e)
    nulos_permitidos = {"marca", "modelo", "numero_serie", "fecha_instalacion", "valor_reposicion", "garantia_vigente_hasta", "contrato_id", "criticidad"}
    for k, v in cambios.items():
        if v is not None or k in nulos_permitidos:
            setattr(e, k, v)
    await db.flush()
    await auditoria.registrar_actor(db, actor, "catalogos.equipo_modificacion", request, tenant_id=e.tenant_id,
                                    recurso_tipo="equipo", recurso_id=e.id, antes=antes, despues=auditoria.instantanea(e))
    await db.commit()
    return _equipo_salida(*(await _equipo(db, actor, e.id)))


# ----------------------------------------------------------- tipos de falla

@router.get("/tipos-falla", response_model=list[TipoFallaSalida], summary="Tipos de falla",
            description="Cascada §4.3: `familia_id` filtra por familia del equipo. Los usuarios del tenant ven los de sus prestadores.")
async def listar_tipos_falla(db: DB, actor: Actor = Depends(LECTURA_FALLAS), prestador_id: UUID | None = None,
                             familia_id: UUID | None = None, incluir_inactivos: bool = False):
    consulta = select(TipoFalla).order_by(TipoFalla.descripcion)
    if actor.dominio == Dominio.tenant:
        consulta = consulta.where(TipoFalla.prestador_id.in_(await catalogos_service.prestadores_del_tenant(db, actor.tenant_id)))
    else:
        consulta = consulta.where(TipoFalla.prestador_id == prestador_de(actor, prestador_id))
    if familia_id:
        consulta = consulta.where(TipoFalla.familia_equipo_id == familia_id)
    if not incluir_inactivos:
        consulta = consulta.where(TipoFalla.activa.is_(True))
    return (await db.execute(consulta)).scalars().all()


@router.post("/tipos-falla", response_model=TipoFallaSalida, status_code=201, summary="Crear tipo de falla",
             description="`requiere_revision_manual` solo lo acepta el superadmin (flag global §6.8.6).")
async def crear_tipo_falla(datos: TipoFallaEntrada, request: Request, db: DB, actor: Actor = Depends(ADMIN_PRESTADOR),
                           prestador_id: UUID | None = None):
    p = prestador_de(actor, prestador_id)
    if datos.requiere_revision_manual is not None and not actor.es_superadmin:
        raise prohibido("Solo el superadmin configura requiere_revision_manual")
    familia = await db.get(FamiliaEquipo, datos.familia_equipo_id)
    if familia is None or familia.tenant_id is not None:
        raise ErrorAPI(422, "FAMILIA_INVALIDA", "Los tipos de falla se definen sobre familias globales de plataforma")
    x = TipoFalla(prestador_id=p, descripcion=datos.descripcion, familia_equipo_id=datos.familia_equipo_id,
                  requiere_revision_manual=bool(datos.requiere_revision_manual))
    db.add(x)
    await db.flush()
    await auditoria.registrar_actor(db, actor, "catalogos.tipo_falla_alta", request, prestador_id=p, recurso_tipo="tipo_falla",
                                    recurso_id=x.id, despues=auditoria.instantanea(x))
    await db.commit()
    return x


@router.patch("/tipos-falla/{tipo_falla_id}", response_model=TipoFallaSalida, summary="Modificar tipo de falla")
async def modificar_tipo_falla(tipo_falla_id: UUID, datos: TipoFallaCambios, request: Request, db: DB,
                               actor: Actor = Depends(ADMIN_PRESTADOR), prestador_id: UUID | None = None):
    x = await db.get(TipoFalla, tipo_falla_id)
    if x is None or (not actor.es_superadmin and x.prestador_id != actor.prestador_id):
        raise no_encontrado("Tipo de falla")
    cambios = datos.model_dump(exclude_unset=True, exclude_none=True)
    if "requiere_revision_manual" in cambios and not actor.es_superadmin:
        raise prohibido("Solo el superadmin cambia requiere_revision_manual")
    if "familia_equipo_id" in cambios:
        familia = await db.get(FamiliaEquipo, cambios["familia_equipo_id"])
        if familia is None or familia.tenant_id is not None:
            raise ErrorAPI(422, "FAMILIA_INVALIDA", "Los tipos de falla se definen sobre familias globales de plataforma")
    antes = auditoria.instantanea(x)
    for k, v in cambios.items():
        setattr(x, k, v)
    await db.flush()
    evento = "catalogos.tipo_falla_flag" if "requiere_revision_manual" in cambios else "catalogos.tipo_falla_modificacion"
    await auditoria.registrar_actor(db, actor, evento, request, prestador_id=x.prestador_id, recurso_tipo="tipo_falla",
                                    recurso_id=x.id, antes=antes, despues=auditoria.instantanea(x))
    await db.commit()
    await db.refresh(x)
    return x


# ------------------------------------------------------- matriz de severidad

@router.get("/matriz-severidad", response_model=MatrizSalida, summary="Matriz tipo de falla × tipo de equipo",
            description="Filas: tipos de falla de los prestadores del tenant; columnas: tipos de equipo visibles; celdas configuradas.")
async def obtener_matriz(db: DB, actor: Actor = Depends(requiere_rol(Rol.superadmin, Rol.admin_empresa, Rol.admin_un,
                                                                     Rol.admin_prestador, Rol.mesa_control, Rol.despachador)),
                         tenant_id: UUID | None = None):
    if actor.dominio == Dominio.tenant:
        t = actor.tenant_id
    elif actor.es_superadmin:
        t = tenant_de(actor, tenant_id)
    else:
        if tenant_id is None or tenant_id not in set((await db.execute(select(Contrato.tenant_id).where(
                Contrato.prestador_id == actor.prestador_id))).scalars()):
            raise ErrorAPI(422, "TENANT_REQUERIDO", "Indica un tenant_id con contrato con tu prestador")
        t = tenant_id
    return await catalogos_service.matriz(db, t)


async def _aplicar_celdas(db, actor: Actor, t: UUID, celdas: list[CeldaMatriz]) -> tuple[dict, dict]:
    prestadores = await catalogos_service.prestadores_del_tenant(db, t)
    fallas = {f.id: f for f in (await db.execute(select(TipoFalla).where(TipoFalla.prestador_id.in_(prestadores)))).scalars()}
    tipos = {x.id: x for x in (await db.execute(select(TipoEquipo).where(
        or_(TipoEquipo.tenant_id.is_(None), TipoEquipo.tenant_id == t)))).scalars()}
    niveles = {n.id: n for n in (await db.execute(select(NivelSeveridadCatalogo).where(
        NivelSeveridadCatalogo.prestador_id.in_(prestadores)))).scalars()}
    existentes = {(c.tipo_falla_id, c.tipo_equipo_id): c for c in (await db.execute(
        select(TipoFallaSeveridad).where(TipoFallaSeveridad.tenant_id == t))).scalars()}
    antes, despues = {}, {}
    for c in celdas:
        f, x = fallas.get(c.tipo_falla_id), tipos.get(c.tipo_equipo_id)
        if f is None or x is None:
            raise ErrorAPI(422, "CELDA_INVALIDA", f"Tipo de falla o de equipo no válido: {c.tipo_falla_id} × {c.tipo_equipo_id}")
        if f.familia_equipo_id != x.familia_id:
            raise ErrorAPI(422, "FAMILIA_DISTINTA", f"«{f.descripcion}» y «{x.nombre}» pertenecen a familias distintas")
        clave = f"{c.tipo_falla_id}|{c.tipo_equipo_id}"
        fila = existentes.get((c.tipo_falla_id, c.tipo_equipo_id))
        antes[clave] = str(fila.nivel_severidad_id) if fila and fila.activa else None
        if c.nivel_severidad_id is None:
            if fila:
                await db.delete(fila)
                existentes.pop((c.tipo_falla_id, c.tipo_equipo_id))
            despues[clave] = None
            continue
        nivel = niveles.get(c.nivel_severidad_id)
        if nivel is None or nivel.prestador_id != f.prestador_id:
            raise ErrorAPI(422, "NIVEL_INVALIDO", "El nivel de severidad debe ser del mismo prestador que el tipo de falla")
        if fila is None:
            fila = TipoFallaSeveridad(tenant_id=t, tipo_falla_id=c.tipo_falla_id, tipo_equipo_id=c.tipo_equipo_id)
            db.add(fila)
            existentes[(c.tipo_falla_id, c.tipo_equipo_id)] = fila
        fila.nivel_severidad_id, fila.configurado_por, fila.activa = c.nivel_severidad_id, actor.id, True
        despues[clave] = str(c.nivel_severidad_id)
    await db.flush()
    return antes, despues


@router.put("/matriz-severidad/celda", response_model=MatrizSalida, summary="Configurar una celda de la matriz")
async def celda_matriz(datos: CeldaMatriz, request: Request, db: DB, actor: Actor = Depends(ADMIN_TENANT), tenant_id: UUID | None = None):
    t = tenant_de(actor, tenant_id)
    antes, despues = await _aplicar_celdas(db, actor, t, [datos])
    await auditoria.registrar_actor(db, actor, "catalogos.matriz_celda", request, tenant_id=t, recurso_tipo="tipo_falla_severidad",
                                    recurso_id=t, antes=antes, despues=despues)
    await db.commit()
    return await catalogos_service.matriz(db, t)


@router.put("/matriz-severidad", response_model=MatrizSalida, summary="Configurar varias celdas (carga masiva)")
async def matriz_masiva(datos: MatrizMasivaEntrada, request: Request, db: DB, actor: Actor = Depends(ADMIN_TENANT),
                        tenant_id: UUID | None = None):
    t = tenant_de(actor, tenant_id)
    antes, despues = await _aplicar_celdas(db, actor, t, datos.celdas)
    await auditoria.registrar_actor(db, actor, "catalogos.matriz_masiva", request, tenant_id=t, recurso_tipo="tipo_falla_severidad",
                                    recurso_id=t, antes=antes, despues=despues)
    await db.commit()
    return await catalogos_service.matriz(db, t)


@router.get("/matriz-severidad/resolver", response_model=SeveridadResuelta, summary="Resolver severidad",
            description="Nivel configurado para la combinación tipo de falla × tipo de equipo del tenant, o 404 "
                        "`SEVERIDAD_NO_CONFIGURADA`. Lo consume la captura de folios (P04).")
async def resolver(db: DB, tipo_falla_id: UUID, tipo_equipo_id: UUID, actor: Actor = Depends(LECTURA_FALLAS),
                   tenant_id: UUID | None = None):
    t = actor.tenant_id if actor.dominio == Dominio.tenant else tenant_id
    if t is None:
        raise ErrorAPI(422, "TENANT_REQUERIDO", "Indica tenant_id")
    fila = await catalogos_service.resolver_severidad(db, t, tipo_falla_id, tipo_equipo_id)
    if fila is None:
        raise ErrorAPI(404, "SEVERIDAD_NO_CONFIGURADA", "No hay severidad configurada para esa combinación; el folio irá a revisión")
    nivel, revision = fila
    return SeveridadResuelta(tipo_falla_id=tipo_falla_id, tipo_equipo_id=tipo_equipo_id,
                             nivel=NivelMatriz.model_validate(nivel, from_attributes=True),
                             tiempo_respuesta_horas=nivel.tiempo_respuesta_horas, tiempo_resolucion_horas=nivel.tiempo_resolucion_horas,
                             requiere_revision_manual=revision)

