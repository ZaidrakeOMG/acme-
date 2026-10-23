"""Permisos configurables del técnico (§6.8.3) y del despachador (§6.8.3b)."""
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ErrorAPI
from models.base import AplicaPermiso
from models.permisos import (
    GrupoTecnicoPermiso, PermisoCatalogo, PermisoDespachador, PermisoDespachadorLog, PermisoTecnico, TecnicoGrupo,
    TecnicoPermisoOverride,
)


async def catalogo(db: AsyncSession, aplica_a: AplicaPermiso) -> list[PermisoCatalogo]:
    return list((await db.execute(
        select(PermisoCatalogo).where(PermisoCatalogo.aplica_a == aplica_a).order_by(PermisoCatalogo.clave)
    )).scalars())


async def sembrar_defaults(db: AsyncSession, prestador_id: UUID) -> None:
    """Crea los valores base del prestador con los defaults del documento de diseño."""
    for p in await catalogo(db, AplicaPermiso.tecnico):
        db.add(PermisoTecnico(prestador_id=prestador_id, permiso_clave=p.clave, habilitado=p.valor_default))
    for p in await catalogo(db, AplicaPermiso.despachador):
        db.add(PermisoDespachador(prestador_id=prestador_id, permiso_clave=p.clave, habilitado=p.valor_default))
    await db.flush()


async def efectivos_tecnico(db: AsyncSession, prestador_id: UUID) -> list[dict]:
    valores = {r.permiso_clave: r.habilitado for r in (await db.execute(
        select(PermisoTecnico).where(PermisoTecnico.prestador_id == prestador_id))).scalars()}
    return [
        {"clave": p.clave, "aplica_a": p.aplica_a, "descripcion": p.descripcion, "valor_default": p.valor_default,
         "habilitado": valores.get(p.clave, p.valor_default)}
        for p in await catalogo(db, AplicaPermiso.tecnico)
    ]


async def efectivos_despachador(db: AsyncSession, prestador_id: UUID, despachador_id: UUID | None = None,
                                tenant_id: UUID | None = None) -> list[dict]:
    """Resolución: permiso por despachador+cliente > valor base del prestador > default del catálogo."""
    filas = (await db.execute(select(PermisoDespachador).where(PermisoDespachador.prestador_id == prestador_id))).scalars().all()
    base = {f.permiso_clave: f.habilitado for f in filas if f.despachador_id is None}
    especificos = {f.permiso_clave: f.habilitado for f in filas
                   if despachador_id and f.despachador_id == despachador_id and f.tenant_id == tenant_id}
    return [
        {"clave": p.clave, "aplica_a": p.aplica_a, "descripcion": p.descripcion, "valor_default": p.valor_default,
         "habilitado": especificos.get(p.clave, base.get(p.clave, p.valor_default))}
        for p in await catalogo(db, AplicaPermiso.despachador)
    ]


async def _validar_claves(db: AsyncSession, aplica_a: AplicaPermiso, valores: dict[str, bool]) -> None:
    validas = {p.clave for p in await catalogo(db, aplica_a)}
    invalidas = sorted(set(valores) - validas)
    if invalidas:
        raise ErrorAPI(422, "PERMISO_DESCONOCIDO", "Permisos no reconocidos", invalidas)


async def actualizar_tecnico(db: AsyncSession, prestador_id: UUID, valores: dict[str, bool]) -> dict[str, tuple[bool | None, bool]]:
    await _validar_claves(db, AplicaPermiso.tecnico, valores)
    actuales = {r.permiso_clave: r for r in (await db.execute(
        select(PermisoTecnico).where(PermisoTecnico.prestador_id == prestador_id))).scalars()}
    cambios = {}
    for clave, habilitado in valores.items():
        fila = actuales.get(clave)
        if fila is None:
            db.add(PermisoTecnico(prestador_id=prestador_id, permiso_clave=clave, habilitado=habilitado))
            cambios[clave] = (None, habilitado)
        elif fila.habilitado != habilitado:
            cambios[clave] = (fila.habilitado, habilitado)
            fila.habilitado = habilitado
    await db.flush()
    return cambios


async def actualizar_despachador(db: AsyncSession, prestador_id: UUID, valores: dict[str, bool], actor_id: UUID,
                                 despachador_id: UUID | None, tenant_id: UUID | None) -> dict[str, tuple[bool | None, bool]]:
    await _validar_claves(db, AplicaPermiso.despachador, valores)
    filas = (await db.execute(select(PermisoDespachador).where(
        PermisoDespachador.prestador_id == prestador_id,
        PermisoDespachador.despachador_id.is_(None) if despachador_id is None else PermisoDespachador.despachador_id == despachador_id,
        PermisoDespachador.tenant_id.is_(None) if tenant_id is None else PermisoDespachador.tenant_id == tenant_id,
    ))).scalars().all()
    actuales = {f.permiso_clave: f for f in filas}
    cambios = {}
    for clave, habilitado in valores.items():
        fila = actuales.get(clave)
        anterior = fila.habilitado if fila else None
        if fila is None:
            db.add(PermisoDespachador(prestador_id=prestador_id, despachador_id=despachador_id, tenant_id=tenant_id,
                                      permiso_clave=clave, habilitado=habilitado, configurado_por=actor_id))
        elif fila.habilitado != habilitado:
            fila.habilitado = habilitado
            fila.configurado_por = actor_id
        else:
            continue
        cambios[clave] = (anterior, habilitado)
        db.add(PermisoDespachadorLog(prestador_id=prestador_id, despachador_id=despachador_id, tenant_id=tenant_id,
                                     permiso_clave=clave, valor_anterior=anterior, valor_nuevo=habilitado, modificado_por=actor_id))
    await db.flush()
    return cambios


# --------------------------------------------- técnico individual (§6.8.3)

async def efectivos_de_tecnico(db: AsyncSession, prestador_id: UUID, usuario_id: UUID) -> list[dict]:
    """Resolución: override individual > grupo del técnico > valor base del prestador > default del catálogo."""
    base = {r.permiso_clave: r.habilitado for r in (await db.execute(
        select(PermisoTecnico).where(PermisoTecnico.prestador_id == prestador_id))).scalars()}
    asignacion = (await db.execute(select(TecnicoGrupo).where(TecnicoGrupo.tecnico_id == usuario_id))).scalar_one_or_none()
    grupo = {}
    if asignacion:
        grupo = {r.permiso_clave: r.habilitado for r in (await db.execute(
            select(GrupoTecnicoPermiso).where(GrupoTecnicoPermiso.grupo_id == asignacion.grupo_id))).scalars()}
    overrides = {r.permiso_clave: r for r in (await db.execute(
        select(TecnicoPermisoOverride).where(TecnicoPermisoOverride.tecnico_id == usuario_id))).scalars()}
    resultado = []
    for p in await catalogo(db, AplicaPermiso.tecnico):
        if p.clave in overrides:
            valor, origen, razon = overrides[p.clave].habilitado, "override", overrides[p.clave].razon
        elif p.clave in grupo:
            valor, origen, razon = grupo[p.clave], "grupo", None
        elif p.clave in base:
            valor, origen, razon = base[p.clave], "prestador", None
        else:
            valor, origen, razon = p.valor_default, "catalogo", None
        resultado.append({"clave": p.clave, "descripcion": p.descripcion, "habilitado": valor, "origen": origen, "razon": razon})
    return resultado


async def validar_claves_tecnico(db: AsyncSession, claves: set[str]) -> None:
    await _validar_claves(db, AplicaPermiso.tecnico, {c: True for c in claves})
