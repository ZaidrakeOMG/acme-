"""Servicio del motor de formularios: permisos §6.8.3c, versionado, resolución de asignaciones, catálogos del
sistema para el renderizador, respuestas (parcial / envío con validación en servidor) y evidencias."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import Request
from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from core.dependencias import Actor
from core.errors import ErrorAPI, no_encontrado, prohibido
from models.base import Dominio, EstadoRegistro, Rol
from models.catalogos import Equipo, EstadoActivo, FamiliaEquipo, Tecnico, TipoEquipo, TipoFalla
from models.formularios import (
    CalidadFotoDefault, CatalogoPersonalizado, CatalogoPersonalizadoOpcion, EstadoFormulario, EstadoRespuesta, Formulario,
    FormularioAsignacion, FormularioEvidencia, FormularioPermisoMesa, FormularioRespuesta, FormularioVersion, TipoEvidencia,
)
from models.organizaciones import TenantPrestador
from models.unidades import UnidadNegocio
from models.usuarios import Usuario
from schemas.formularios import (
    AsignacionEntrada, Campo, CatalogoPersonalizadoEntrada, ClonarEntrada, EsquemaFormulario, FormularioCambios,
    FormularioEntrada, FuenteCatalogo, RespuestaEntrada,
)
from services import alertas_service, auditoria, catalogos_service
from services.almacenamiento import obtener_almacenamiento
from services.formularios import evidencias as ev
from services.formularios.validacion import Contexto, validar
from services.transcripcion import transcriptor

ROLES_DISENO = {Rol.superadmin, Rol.admin_prestador}
TIPO_EVIDENCIA_POR_CAMPO = {"fotografia": "foto", "firma": "firma", "dibujo": "dibujo", "archivo": "archivo", "audio": "audio"}


# ------------------------------------------------------------ permisos

def prestador_de(actor: Actor, prestador_id: UUID | None) -> UUID | None:
    """Prestador para crear/listar: el propio; superadmin elige (None = plataforma)."""
    if actor.es_superadmin:
        return prestador_id
    if actor.prestador_id is None:
        raise prohibido("Tu usuario no pertenece a un prestador")
    return actor.prestador_id


async def _permiso_mesa(db: AsyncSession, actor: Actor, formulario: Formulario) -> bool:
    fila = (await db.execute(select(FormularioPermisoMesa).where(
        FormularioPermisoMesa.formulario_id == formulario.id, FormularioPermisoMesa.usuario_id == actor.id))).scalar_one_or_none()
    return bool(fila and fila.puede_editar_publicado)


async def puede_editar(db: AsyncSession, actor: Actor, formulario: Formulario) -> bool:
    if actor.es_superadmin:
        return True
    if actor.rol == Rol.admin_prestador:
        return formulario.prestador_id == actor.prestador_id
    if actor.rol == Rol.mesa_control and formulario.prestador_id == actor.prestador_id:
        return formulario.estado == EstadoFormulario.publicado and await _permiso_mesa(db, actor, formulario)
    return False


async def exigir_edicion(db: AsyncSession, actor: Actor, formulario: Formulario) -> None:
    if not await puede_editar(db, actor, formulario):
        raise prohibido("No puedes modificar este formulario")


async def _tenant_vinculado(db: AsyncSession, prestador_id: UUID | None, tenant_id: UUID | None) -> None:
    if tenant_id is None:
        return
    if prestador_id is None:
        raise ErrorAPI(422, "ALCANCE_INVALIDO", "Las plantillas de plataforma no pueden tener alcance de un cliente")
    vinculo = (await db.execute(select(TenantPrestador.id).where(
        TenantPrestador.tenant_id == tenant_id, TenantPrestador.prestador_id == prestador_id))).first()
    if vinculo is None:
        raise ErrorAPI(422, "TENANT_NO_VINCULADO", "El cliente no está vinculado a este prestador")


# ----------------------------------------------------------- versiones

async def version_actual(db: AsyncSession, formulario_id: UUID) -> FormularioVersion:
    return (await db.execute(select(FormularioVersion).where(FormularioVersion.formulario_id == formulario_id)
                             .order_by(FormularioVersion.numero_version.desc()).limit(1))).scalar_one()


async def version_publicada(db: AsyncSession, formulario: Formulario) -> FormularioVersion | None:
    if formulario.version_publicada_id is None:
        return None
    return await db.get(FormularioVersion, formulario.version_publicada_id)


async def salida(db: AsyncSession, actor: Actor, f: Formulario) -> dict[str, Any]:
    v = await version_actual(db, f.id)
    publicada = await version_publicada(db, f)
    return {
        **{k: getattr(f, k) for k in ("id", "created_at", "updated_at", "version_hash", "prestador_id", "tenant_id", "nombre",
                                      "descripcion", "tipo", "rol_destino", "estado", "version_publicada_id", "es_plantilla_base",
                                      "clonado_de_id")},
        "version_actual": v.numero_version, "numero_version_publicada": publicada.numero_version if publicada else None,
        "esquema_json": v.esquema_json, "puede_editar": await puede_editar(db, actor, f),
    }


async def obtener(db: AsyncSession, actor: Actor, formulario_id: UUID) -> Formulario:
    f = await db.get(Formulario, formulario_id)
    if f is None:
        raise no_encontrado("Formulario")
    # RLS ya limita; para roles de uso (tenant, técnico…) solo son visibles los publicados y los de su rol.
    if actor.rol not in ROLES_DISENO and actor.rol != Rol.mesa_control:
        if f.estado != EstadoFormulario.publicado:
            raise no_encontrado("Formulario")
    return f


async def listar(db: AsyncSession, actor: Actor, tipo: str | None, alcance: str | None, estado: str | None,
                 prestador_id: UUID | None, plantillas: bool | None) -> list[Formulario]:
    consulta = select(Formulario).order_by(Formulario.nombre)
    if actor.es_superadmin and prestador_id:
        consulta = consulta.where(Formulario.prestador_id == prestador_id)
    elif actor.dominio == Dominio.prestador:
        consulta = consulta.where(or_(Formulario.prestador_id == actor.prestador_id, Formulario.es_plantilla_base.is_(True)))
    if actor.rol not in ROLES_DISENO and actor.rol != Rol.mesa_control:
        consulta = consulta.where(Formulario.estado == EstadoFormulario.publicado)
    if plantillas is not None:
        consulta = consulta.where(Formulario.es_plantilla_base.is_(plantillas))
    if tipo:
        consulta = consulta.where(Formulario.tipo == tipo)
    if estado:
        consulta = consulta.where(Formulario.estado == estado)
    if alcance == "global":
        consulta = consulta.where(Formulario.tenant_id.is_(None))
    elif alcance == "tenant":
        consulta = consulta.where(Formulario.tenant_id.is_not(None))
    return list((await db.execute(consulta)).scalars())


async def crear(db: AsyncSession, actor: Actor, datos: FormularioEntrada, request: Request) -> Formulario:
    if actor.rol not in ROLES_DISENO:
        raise prohibido("Solo el superadmin y el admin del prestador diseñan formularios")
    prestador_id = prestador_de(actor, datos.prestador_id)
    if datos.es_plantilla_base and not actor.es_superadmin:
        raise prohibido("Solo el superadmin crea plantillas base")
    if datos.es_plantilla_base:
        prestador_id = None
    await _tenant_vinculado(db, prestador_id, datos.tenant_id)
    f = Formulario(prestador_id=prestador_id, tenant_id=datos.tenant_id, nombre=datos.nombre, descripcion=datos.descripcion,
                   tipo=datos.tipo, rol_destino=[r.value for r in datos.rol_destino], es_plantilla_base=datos.es_plantilla_base)
    db.add(f)
    await db.flush()
    db.add(FormularioVersion(formulario_id=f.id, prestador_id=prestador_id, tenant_id=datos.tenant_id, numero_version=1,
                             esquema_json=datos.esquema.model_dump(mode="json")))
    await db.flush()
    await auditoria.registrar_actor(db, actor, "formularios.alta", request, prestador_id=prestador_id, tenant_id=datos.tenant_id,
                                    recurso_tipo="formulario", recurso_id=f.id, despues=auditoria.instantanea(f))
    return f


async def editar(db: AsyncSession, actor: Actor, formulario_id: UUID, cambios: FormularioCambios, request: Request) -> Formulario:
    f = await obtener(db, actor, formulario_id)
    await exigir_edicion(db, actor, f)
    if f.estado == EstadoFormulario.archivado:
        raise ErrorAPI(409, "FORMULARIO_ARCHIVADO", "Un formulario archivado no se edita; clónalo")
    antes = auditoria.instantanea(f)
    if actor.rol == Rol.mesa_control:
        # §6.8.3c: la mesa solo ajusta el esquema de un publicado (nueva versión); no cambia alcance ni rol destino.
        if cambios.model_dump(exclude_unset=True, exclude={"esquema", "notas_version"}):
            raise prohibido("La mesa de control solo puede editar el contenido del formulario")
    if cambios.tenant_id is not None or "tenant_id" in cambios.model_fields_set:
        await _tenant_vinculado(db, f.prestador_id, cambios.tenant_id)
    for k in ("nombre", "descripcion", "tipo"):
        v = getattr(cambios, k)
        if v is not None:
            setattr(f, k, v)
    if cambios.rol_destino is not None:
        f.rol_destino = [r.value for r in cambios.rol_destino]
    if "tenant_id" in cambios.model_fields_set:
        f.tenant_id = cambios.tenant_id
    v = await version_actual(db, f.id)
    if cambios.esquema is not None or cambios.notas_version is not None:
        esquema = cambios.esquema.model_dump(mode="json") if cambios.esquema else v.esquema_json
        if v.publicada_at is not None:
            # Versión publicada: inmutable. Se abre numero_version + 1 en borrador.
            v = FormularioVersion(formulario_id=f.id, prestador_id=f.prestador_id, tenant_id=f.tenant_id,
                                  numero_version=v.numero_version + 1, esquema_json=esquema, notas_version=cambios.notas_version or "")
            db.add(v)
        else:
            v.esquema_json = esquema
            if cambios.notas_version is not None:
                v.notas_version = cambios.notas_version
    if "tenant_id" in cambios.model_fields_set and v.publicada_at is None:
        v.tenant_id = f.tenant_id
    await db.flush()
    await auditoria.registrar_actor(db, actor, "formularios.modificacion", request, prestador_id=f.prestador_id, tenant_id=f.tenant_id,
                                    recurso_tipo="formulario", recurso_id=f.id, antes=antes,
                                    despues={**auditoria.instantanea(f), "version": v.numero_version})
    return f


async def publicar(db: AsyncSession, actor: Actor, formulario_id: UUID, notas: str, request: Request) -> Formulario:
    f = await obtener(db, actor, formulario_id)
    await exigir_edicion(db, actor, f)
    v = await version_actual(db, f.id)
    if v.publicada_at is not None:
        raise ErrorAPI(409, "SIN_CAMBIOS", f"La versión {v.numero_version} ya está publicada; edita el formulario para crear una nueva")
    EsquemaFormulario.model_validate(v.esquema_json)  # re-validar el contrato antes de publicar
    v.publicada_at = datetime.now(UTC)
    v.publicada_por = actor.id
    if notas:
        v.notas_version = notas
    anterior = f.version_publicada_id
    f.version_publicada_id = v.id
    f.estado = EstadoFormulario.publicado
    await db.flush()
    await auditoria.registrar_actor(db, actor, "formularios.publicacion", request, prestador_id=f.prestador_id, tenant_id=f.tenant_id,
                                    recurso_tipo="formulario", recurso_id=f.id, antes={"version_publicada_id": anterior},
                                    despues={"version_publicada_id": v.id, "numero_version": v.numero_version, "notas": v.notas_version})
    return f


async def archivar(db: AsyncSession, actor: Actor, formulario_id: UUID, request: Request) -> Formulario:
    f = await obtener(db, actor, formulario_id)
    if actor.rol == Rol.mesa_control:
        raise prohibido("La mesa de control no archiva formularios")
    await exigir_edicion(db, actor, f)
    antes = auditoria.instantanea(f)
    f.estado = EstadoFormulario.archivado
    await db.flush()
    await auditoria.registrar_actor(db, actor, "formularios.archivado", request, prestador_id=f.prestador_id, tenant_id=f.tenant_id,
                                    recurso_tipo="formulario", recurso_id=f.id, antes=antes, despues=auditoria.instantanea(f))
    return f


async def clonar(db: AsyncSession, actor: Actor, formulario_id: UUID, datos: ClonarEntrada, request: Request) -> Formulario:
    if actor.rol not in ROLES_DISENO:
        raise prohibido("Solo el superadmin y el admin del prestador clonan formularios")
    origen = await db.get(Formulario, formulario_id)
    if origen is None:
        raise no_encontrado("Formulario")
    if not (origen.es_plantilla_base or actor.es_superadmin or origen.prestador_id == actor.prestador_id):
        raise no_encontrado("Formulario")
    prestador_id = prestador_de(actor, datos.prestador_id)
    await _tenant_vinculado(db, prestador_id, datos.tenant_id)
    fuente = await version_publicada(db, origen) or await version_actual(db, origen.id)
    f = Formulario(prestador_id=prestador_id, tenant_id=datos.tenant_id, nombre=datos.nombre or f"{origen.nombre} (copia)",
                   descripcion=origen.descripcion, tipo=origen.tipo, rol_destino=list(origen.rol_destino), clonado_de_id=origen.id)
    db.add(f)
    await db.flush()
    db.add(FormularioVersion(formulario_id=f.id, prestador_id=prestador_id, tenant_id=datos.tenant_id, numero_version=1,
                             esquema_json=fuente.esquema_json, notas_version=f"Clonado de «{origen.nombre}» v{fuente.numero_version}"))
    await db.flush()
    await auditoria.registrar_actor(db, actor, "formularios.clonado", request, prestador_id=prestador_id, tenant_id=datos.tenant_id,
                                    recurso_tipo="formulario", recurso_id=f.id, antes={"origen_id": origen.id}, despues=auditoria.instantanea(f))
    return f


def diff_esquemas(a: dict, b: dict) -> dict[str, list[str]]:
    ca = {c["clave"]: c for s in a["secciones"] for c in s["campos"]}
    cb = {c["clave"]: c for s in b["secciones"] for c in s["campos"]}
    return {
        "agregados": sorted(set(cb) - set(ca)),
        "quitados": sorted(set(ca) - set(cb)),
        "modificados": sorted(k for k in set(ca) & set(cb) if ca[k] != cb[k]),
    }


# --------------------------------------------------------- asignaciones

async def crear_asignacion(db: AsyncSession, actor: Actor, formulario_id: UUID, datos: AsignacionEntrada, request: Request) -> FormularioAsignacion:
    f = await obtener(db, actor, formulario_id)
    if actor.rol not in ROLES_DISENO:
        raise prohibido("Solo el admin del prestador asigna formularios")
    await exigir_edicion(db, actor, f)
    if f.prestador_id is None:
        raise ErrorAPI(422, "PLANTILLA_NO_ASIGNABLE", "Las plantillas base no se asignan; clónalas en un prestador")
    tenant_id = datos.tenant_id if f.tenant_id is None else f.tenant_id
    await _tenant_vinculado(db, f.prestador_id, tenant_id)
    if datos.tipo_equipo_id and await db.get(TipoEquipo, datos.tipo_equipo_id) is None:
        raise ErrorAPI(422, "TIPO_EQUIPO_INVALIDO", "Tipo de equipo inexistente")
    if datos.familia_equipo_id and await db.get(FamiliaEquipo, datos.familia_equipo_id) is None:
        raise ErrorAPI(422, "FAMILIA_INVALIDA", "Familia inexistente")
    # §6.8.3c: específico de tenant > global; dentro de cada uno, la coincidencia más específica.
    prioridad = (8 if tenant_id else 0) + (4 if datos.tipo_equipo_id else 0) + (2 if datos.familia_equipo_id else 0) \
        + (1 if datos.plan_mantenimiento_id else 0) + (1 if datos.tipo_folio else 0)
    a = FormularioAsignacion(formulario_id=f.id, prestador_id=f.prestador_id, tenant_id=tenant_id, tipo_folio=datos.tipo_folio,
                             tipo_equipo_id=datos.tipo_equipo_id, familia_equipo_id=datos.familia_equipo_id,
                             plan_mantenimiento_id=datos.plan_mantenimiento_id, prioridad=prioridad, activa=datos.activa)
    db.add(a)
    await db.flush()
    await auditoria.registrar_actor(db, actor, "formularios.asignacion", request, prestador_id=f.prestador_id, tenant_id=tenant_id,
                                    recurso_tipo="formulario_asignacion", recurso_id=a.id, despues=auditoria.instantanea(a))
    return a


async def resolver(db: AsyncSession, actor: Actor, tipo: str | None, tenant_id: UUID | None, tipo_equipo_id: UUID | None,
                   familia_equipo_id: UUID | None, plan_id: UUID | None, prestador_id: UUID | None, tipo_folio: str | None = None) -> tuple[Formulario, FormularioVersion, FormularioAsignacion] | None:
    """Formulario publicado aplicable con la prioridad de §6.8.3c. Lo consume P04 al abrir un folio."""
    if actor.dominio == Dominio.tenant:
        tenant_id = actor.tenant_id
    if tenant_id is None:
        raise ErrorAPI(422, "TENANT_REQUERIDO", "Indica tenant_id")
    prestadores = [actor.prestador_id] if actor.prestador_id else await catalogos_service.prestadores_del_tenant(db, tenant_id)
    if actor.es_superadmin and prestador_id:
        prestadores = [prestador_id]
    if tipo_equipo_id and not familia_equipo_id:
        te = await db.get(TipoEquipo, tipo_equipo_id)
        familia_equipo_id = te.familia_id if te else None
    consulta = (select(FormularioAsignacion, Formulario).join(Formulario, Formulario.id == FormularioAsignacion.formulario_id)
                .where(FormularioAsignacion.activa.is_(True), FormularioAsignacion.prestador_id.in_(prestadores),
                       Formulario.estado == EstadoFormulario.publicado, Formulario.version_publicada_id.is_not(None),
                       or_(FormularioAsignacion.tenant_id.is_(None), FormularioAsignacion.tenant_id == tenant_id),
                       or_(FormularioAsignacion.tipo_equipo_id.is_(None), FormularioAsignacion.tipo_equipo_id == tipo_equipo_id),
                       or_(FormularioAsignacion.familia_equipo_id.is_(None), FormularioAsignacion.familia_equipo_id == familia_equipo_id),
                       or_(FormularioAsignacion.plan_mantenimiento_id.is_(None), FormularioAsignacion.plan_mantenimiento_id == plan_id)))
    if tipo:
        consulta = consulta.where(Formulario.tipo == tipo)
    if tipo_folio:
        consulta = consulta.where(or_(FormularioAsignacion.tipo_folio.is_(None), FormularioAsignacion.tipo_folio == tipo_folio))
    filas = (await db.execute(consulta)).all()
    if not filas:
        return None
    def puntaje(fila):
        a, f = fila
        return ((8 if a.tenant_id else 0) + (4 if a.tipo_equipo_id else 0) + (2 if a.familia_equipo_id else 0)
                + (1 if a.plan_mantenimiento_id else 0) + (1 if a.tipo_folio else 0), a.prioridad, a.updated_at)
    a, f = max(filas, key=puntaje)
    v = await db.get(FormularioVersion, f.version_publicada_id)
    return f, v, a


# ------------------------------------------- catálogos para el renderizador

async def opciones_catalogo(db: AsyncSession, actor: Actor, catalogo: str, tenant_id: UUID | None, un_id: UUID | None,
                            equipo_id: UUID | None, padre: str | None, catalogo_personalizado_id: UUID | None) -> tuple[list[dict], str | None]:
    if actor.dominio == Dominio.tenant:
        tenant_id = actor.tenant_id
    opciones: list[dict] = []
    aviso = None
    if catalogo == "equipos_tenant":
        consulta = select(Equipo).where(Equipo.estado == EstadoActivo.activo).order_by(Equipo.codigo)
        if tenant_id:
            consulta = consulta.where(Equipo.tenant_id == tenant_id)
        if un_id:
            consulta = consulta.where(Equipo.un_id == un_id)
        if padre:
            consulta = consulta.where(Equipo.un_id == UUID(padre))
        opciones = [{"valor": str(e.id), "etiqueta": f"{e.codigo} · {e.nombre}", "padre": str(e.un_id),
                     "extra": {"tipo_equipo_id": str(e.tipo_equipo_id), "numero_serie": e.numero_serie, "marca": e.marca, "modelo": e.modelo}}
                    for e in (await db.execute(consulta)).scalars()]
    elif catalogo == "unidades_negocio":
        consulta = select(UnidadNegocio).where(UnidadNegocio.estado == EstadoRegistro.activo).order_by(UnidadNegocio.nombre)
        if tenant_id:
            consulta = consulta.where(UnidadNegocio.tenant_id == tenant_id)
        opciones = [{"valor": str(u.id), "etiqueta": f"{u.codigo} · {u.nombre}", "descripcion": u.direccion, "padre": None, "extra": {}}
                    for u in (await db.execute(consulta)).scalars()]
    elif catalogo == "tecnicos_prestador":
        consulta = (select(Tecnico, Usuario).join(Usuario, Usuario.id == Tecnico.usuario_id)
                    .where(Tecnico.estado == EstadoActivo.activo).order_by(Usuario.nombre))
        if tenant_id and not actor.prestador_id:
            consulta = consulta.where(Tecnico.prestador_id.in_(await catalogos_service.prestadores_del_tenant(db, tenant_id)))
        opciones = [{"valor": str(t.id), "etiqueta": u.nombre, "descripcion": t.numero_empleado, "padre": None, "extra": {}}
                    for t, u in (await db.execute(consulta)).all()]
    elif catalogo == "tipos_falla":
        consulta = select(TipoFalla).where(TipoFalla.activa.is_(True)).order_by(TipoFalla.descripcion)
        if tenant_id and not actor.prestador_id:
            consulta = consulta.where(TipoFalla.prestador_id.in_(await catalogos_service.prestadores_del_tenant(db, tenant_id)))
        if padre:
            consulta = consulta.where(TipoFalla.familia_equipo_id == UUID(padre))
        opciones = [{"valor": str(t.id), "etiqueta": t.descripcion, "padre": str(t.familia_equipo_id),
                     "extra": {"requiere_revision_manual": t.requiere_revision_manual}} for t in (await db.execute(consulta)).scalars()]
    elif catalogo == "tipos_equipo":
        consulta = select(TipoEquipo).where(TipoEquipo.activa.is_(True), or_(TipoEquipo.tenant_id.is_(None), TipoEquipo.tenant_id == tenant_id)).order_by(TipoEquipo.nombre)
        if padre:
            consulta = consulta.where(TipoEquipo.familia_id == UUID(padre))
        opciones = [{"valor": str(t.id), "etiqueta": t.nombre, "padre": str(t.familia_id), "extra": {}} for t in (await db.execute(consulta)).scalars()]
    elif catalogo == "familias_equipo":
        consulta = select(FamiliaEquipo).where(FamiliaEquipo.activa.is_(True), or_(FamiliaEquipo.tenant_id.is_(None), FamiliaEquipo.tenant_id == tenant_id)).order_by(FamiliaEquipo.nombre)
        opciones = [{"valor": str(f.id), "etiqueta": f.nombre, "padre": None, "extra": {}} for f in (await db.execute(consulta)).scalars()]
    elif catalogo == "materiales":
        aviso = "El catálogo de materiales y refacciones se habilita en P09 (inventario)"
    elif catalogo == "proveedores_externos":
        aviso = "El catálogo de proveedores externos se habilita en P08 (trabajos especiales)"
    elif catalogo == "catalogo_personalizado":
        if catalogo_personalizado_id is None:
            raise ErrorAPI(422, "CATALOGO_REQUERIDO", "Indica catalogo_personalizado_id")
        filas = (await db.execute(select(CatalogoPersonalizadoOpcion).where(
            CatalogoPersonalizadoOpcion.catalogo_id == catalogo_personalizado_id, CatalogoPersonalizadoOpcion.activa.is_(True))
            .order_by(CatalogoPersonalizadoOpcion.orden, CatalogoPersonalizadoOpcion.etiqueta))).scalars().all()
        por_id = {o.id: o for o in filas}
        opciones = [{"valor": o.valor, "etiqueta": o.etiqueta, "padre": por_id[o.padre_opcion_id].valor if o.padre_opcion_id in por_id else None, "extra": {}}
                    for o in filas if not padre or (o.padre_opcion_id in por_id and por_id[o.padre_opcion_id].valor == padre)]
    else:
        raise ErrorAPI(404, "CATALOGO_DESCONOCIDO", f"Catálogo {catalogo} no existe")
    return opciones, aviso


async def _resolutor(db: AsyncSession, actor: Actor, respuesta: FormularioRespuesta, respuestas: dict[str, Any]):
    """Valores válidos de un campo enlazado a catálogo, para validar en servidor igual que en cliente."""
    cache: dict[str, list[str] | None] = {}

    async def resolver_async(campo: Campo) -> list[str] | None:
        fuente = campo.fuente_opciones
        if not isinstance(fuente, FuenteCatalogo):
            return None
        padre = None
        if fuente.campo_padre:
            v = respuestas.get(fuente.campo_padre)
            padre = str(v) if isinstance(v, (str, int)) else None
        clave = f"{fuente.catalogo}|{fuente.catalogo_personalizado_id}|{padre}|{fuente.filtro_contexto}"
        if clave not in cache:
            try:
                opciones, _ = await opciones_catalogo(db, actor, fuente.catalogo, respuesta.tenant_id,
                                                      respuesta.un_id if fuente.filtro_contexto else None, respuesta.equipo_id,
                                                      padre, fuente.catalogo_personalizado_id)
                cache[clave] = [o["valor"] for o in opciones]
            except ErrorAPI:
                cache[clave] = None
        return cache[clave]

    resultados: dict[str, list[str] | None] = {}
    esquema = EsquemaFormulario.model_validate((await db.get(FormularioVersion, respuesta.version_id)).esquema_json)
    for campo in esquema.campos:
        if isinstance(campo.fuente_opciones, FuenteCatalogo):
            resultados[campo.clave] = await resolver_async(campo)
    return lambda campo: resultados.get(campo.clave)


# ----------------------------------------------------------- respuestas

async def _esquema_de(db: AsyncSession, respuesta: FormularioRespuesta) -> tuple[EsquemaFormulario, FormularioVersion]:
    v = await db.get(FormularioVersion, respuesta.version_id)
    return EsquemaFormulario.model_validate(v.esquema_json), v


async def _evidencias_de(db: AsyncSession, respuesta_id: UUID) -> dict[str, list[dict]]:
    filas = (await db.execute(select(FormularioEvidencia).where(FormularioEvidencia.respuesta_id == respuesta_id)
                              .order_by(FormularioEvidencia.orden))).scalars().all()
    por_campo: dict[str, list[dict]] = {}
    for e in filas:
        por_campo.setdefault(e.campo_clave, []).append({"id": str(e.id), "tipo": e.tipo.value, "etiqueta": e.etiqueta})
    return por_campo


def _puede_responder(actor: Actor, f: Formulario) -> bool:
    return actor.es_superadmin or actor.rol.value in (f.rol_destino or [])


async def crear_respuesta(db: AsyncSession, actor: Actor, formulario_id: UUID, datos: RespuestaEntrada, request: Request) -> FormularioRespuesta:
    f = await obtener(db, actor, formulario_id)
    if f.estado != EstadoFormulario.publicado or f.version_publicada_id is None:
        raise ErrorAPI(409, "FORMULARIO_NO_PUBLICADO", "Solo se responden formularios publicados")
    if not _puede_responder(actor, f):
        raise prohibido("Este formulario no está dirigido a tu rol")
    if actor.dominio == Dominio.tenant:
        tenant_id = actor.tenant_id
    else:
        tenant_id = datos.contexto.tenant_id or f.tenant_id
        if tenant_id and f.prestador_id and not actor.es_superadmin:
            await _tenant_vinculado(db, f.prestador_id, tenant_id)
    if f.tenant_id and tenant_id != f.tenant_id:
        raise prohibido("El formulario es específico de otro cliente")
    un_id, equipo_id = datos.contexto.un_id, datos.contexto.equipo_id
    if un_id:
        un = await db.get(UnidadNegocio, un_id)
        if un is None or (tenant_id and un.tenant_id != tenant_id):
            raise ErrorAPI(422, "UNIDAD_INVALIDA", "La unidad no existe o es de otro cliente")
    if equipo_id:
        e = await db.get(Equipo, equipo_id)
        if e is None or (tenant_id and e.tenant_id != tenant_id):
            raise ErrorAPI(422, "EQUIPO_INVALIDO", "El equipo no existe o es de otro cliente")
    r = FormularioRespuesta(formulario_id=f.id, version_id=f.version_publicada_id, tenant_id=tenant_id,
                            prestador_id=actor.prestador_id or f.prestador_id, un_id=un_id, equipo_id=equipo_id, origen=datos.origen,
                            referencia_id=datos.referencia_id, respondido_por=actor.id, dispositivo_json=datos.dispositivo,
                            contexto_json={"sistema": datos.contexto.sistema, "sellos": {}})
    db.add(r)
    await db.flush()
    await db.refresh(r)
    if datos.respuestas:
        await guardar_parcial(db, actor, r, datos.respuestas, None)
    return r


async def obtener_respuesta(db: AsyncSession, actor: Actor, respuesta_id: UUID) -> FormularioRespuesta:
    r = await db.get(FormularioRespuesta, respuesta_id)
    if r is None:
        raise no_encontrado("Respuesta")
    if actor.rol in (Rol.tecnico, Rol.operador, Rol.supervisor_operadores, Rol.supervisor_prestador, Rol.direccion_prestador) \
            and r.respondido_por != actor.id:
        raise no_encontrado("Respuesta")
    return r


def _exigir_autor_en_progreso(actor: Actor, r: FormularioRespuesta) -> None:
    if r.estado == EstadoRespuesta.enviado:
        raise ErrorAPI(409, "RESPUESTA_INMUTABLE", "La respuesta ya fue enviada y no puede modificarse")
    if r.respondido_por != actor.id and not actor.es_superadmin:
        raise prohibido("Solo quien inició la respuesta puede continuarla")


async def guardar_parcial(db: AsyncSession, actor: Actor, r: FormularioRespuesta, respuestas: dict[str, Any],
                          dispositivo: dict | None) -> FormularioRespuesta:
    _exigir_autor_en_progreso(actor, r)
    esquema, _ = await _esquema_de(db, r)
    sellos = dict(r.contexto_json.get("sellos", {}))
    ahora = datetime.now(UTC)
    for campo in esquema.campos:
        # Sellos "al llegar a la sección" / "por condición": el servidor fija la hora en que recibe el primer valor.
        if campo.tipo == "sello_fecha_hora" and campo.config["trigger"] in ("al_llegar_seccion", "por_condicion") \
                and respuestas.get(campo.clave) and campo.clave not in sellos:
            sellos[campo.clave] = ahora.isoformat()
    ctx = Contexto(evidencias=await _evidencias_de(db, r.id), sistema=r.contexto_json.get("sistema", {}), sellos=sellos,
                   iniciado_at=r.iniciado_at.replace(tzinfo=None), hoy=ahora.replace(tzinfo=None))
    normalizadas, _ = validar(esquema, respuestas, ctx, estricto=False)
    # Se conservan también los valores aún inválidos para poder reanudar; la validación estricta llega al enviar.
    r.respuestas_json = {**{k: v for k, v in respuestas.items() if esquema.campo(k)}, **normalizadas}
    r.contexto_json = {**r.contexto_json, "sellos": sellos}
    if dispositivo is not None:
        r.dispositivo_json = dispositivo
    await db.flush()
    return r


async def errores_de(db: AsyncSession, actor: Actor, r: FormularioRespuesta) -> list[dict[str, str]]:
    esquema, _ = await _esquema_de(db, r)
    ctx = Contexto(evidencias=await _evidencias_de(db, r.id), sistema=r.contexto_json.get("sistema", {}),
                   sellos=r.contexto_json.get("sellos", {}), iniciado_at=r.iniciado_at.replace(tzinfo=None),
                   resolutor=await _resolutor(db, actor, r, r.respuestas_json))
    _, errores = validar(esquema, r.respuestas_json, ctx, estricto=True)
    return errores


async def enviar(db: AsyncSession, actor: Actor, r: FormularioRespuesta, request: Request) -> FormularioRespuesta:
    _exigir_autor_en_progreso(actor, r)
    esquema, version = await _esquema_de(db, r)
    ahora = datetime.now(UTC)
    ctx = Contexto(evidencias=await _evidencias_de(db, r.id), sistema=r.contexto_json.get("sistema", {}),
                   sellos=r.contexto_json.get("sellos", {}), iniciado_at=r.iniciado_at.replace(tzinfo=None),
                   enviado_at=ahora.replace(tzinfo=None), resolutor=await _resolutor(db, actor, r, r.respuestas_json))
    normalizadas, errores = validar(esquema, r.respuestas_json, ctx, estricto=True)
    if errores:
        raise ErrorAPI(422, "RESPUESTA_INVALIDA", "La respuesta tiene errores de validación", errores)
    geofencing = await _geofencing(db, actor, r, esquema, normalizadas, request)
    r.respuestas_json = normalizadas
    r.contexto_json = {**r.contexto_json, "geofencing": geofencing, "version": version.numero_version}
    r.enviado_at = ahora
    r.estado = EstadoRespuesta.enviado
    r.inmutable = True
    await db.flush()
    await auditoria.registrar_actor(db, actor, "formularios.respuesta_enviada", request, tenant_id=r.tenant_id, prestador_id=r.prestador_id,
                                    recurso_tipo="formulario_respuesta", recurso_id=r.id,
                                    despues={"formulario_id": str(r.formulario_id), "version": version.numero_version, "origen": r.origen.value,
                                             "referencia_id": str(r.referencia_id) if r.referencia_id else None})
    return r


async def _geofencing(db: AsyncSession, actor: Actor, r: FormularioRespuesta, esquema: EsquemaFormulario,
                      respuestas: dict[str, Any], request: Request) -> dict[str, Any]:
    """§4.3 geolocalizacion: distancia a la UN con PostGIS; fuera del radio dispara la alerta; ajuste manual va a auditoría."""
    resultado: dict[str, Any] = {}
    for campo in esquema.campos:
        if campo.tipo != "geolocalizacion" or campo.clave not in respuestas:
            continue
        v = respuestas[campo.clave]
        if v.get("ajustada"):
            await auditoria.registrar_actor(db, actor, "formularios.geolocalizacion_ajustada", request, tenant_id=r.tenant_id,
                                            prestador_id=r.prestador_id, recurso_tipo="formulario_respuesta", recurso_id=r.id,
                                            antes={"lat": v["lat_original"], "lng": v["lng_original"]}, despues={"lat": v["lat"], "lng": v["lng"], "campo": campo.clave})
        if r.un_id is None:
            continue
        distancia = (await db.execute(text(
            "SELECT ST_Distance(ubicacion, ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography) FROM unidades_negocio WHERE id = :un"),
            {"lng": v["lng"], "lat": v["lat"], "un": r.un_id})).scalar()
        if distancia is None:
            resultado[campo.clave] = {"distancia_m": None, "fuera": False}
            continue
        fuera = distancia > campo.config["geofencing_radio_m"]
        resultado[campo.clave] = {"distancia_m": round(distancia, 1), "fuera": fuera, "radio_m": campo.config["geofencing_radio_m"]}
        if fuera and campo.config["alertar_fuera_un"]:
            exceso = distancia - campo.config["geofencing_radio_m"]
            efectivas = await alertas_service.listar_efectivas(db, r.tenant_id, None if r.tenant_id else r.prestador_id)
            umbral = next((float(a["umbral_valor"]) for a in efectivas if a["clave"] == "GEOLOCALIZACION_FUERA_DE_UN"), 0.0)
            if exceso > umbral:
                # Destinatarios: despachador y admin del prestador; con ambos dueños la ven el prestador y el cliente.
                await alertas_service.disparar(db, "GEOLOCALIZACION_FUERA_DE_UN", tenant_id=r.tenant_id,
                                               prestador_id=r.prestador_id, entidad_tipo="formulario_respuesta",
                                               entidad_id=r.id, datos={"campo": campo.clave, "distancia_m": round(distancia, 1),
                                                                       "radio_m": campo.config["geofencing_radio_m"], "un_id": str(r.un_id)})
    return resultado


async def listar_respuestas(db: AsyncSession, actor: Actor, formulario_id: UUID | None, origen: str | None, referencia_id: UUID | None,
                            estado: str | None, solo_mias: bool, limite: int) -> list[FormularioRespuesta]:
    consulta = select(FormularioRespuesta).order_by(FormularioRespuesta.updated_at.desc()).limit(limite)
    roles_propios = (Rol.tecnico, Rol.operador, Rol.supervisor_operadores, Rol.supervisor_prestador, Rol.direccion_prestador)
    if solo_mias or actor.rol in roles_propios:
        consulta = consulta.where(FormularioRespuesta.respondido_por == actor.id)
    if formulario_id:
        consulta = consulta.where(FormularioRespuesta.formulario_id == formulario_id)
    if origen:
        consulta = consulta.where(FormularioRespuesta.origen == origen)
    if referencia_id:
        consulta = consulta.where(FormularioRespuesta.referencia_id == referencia_id)
    if estado:
        consulta = consulta.where(FormularioRespuesta.estado == estado)
    return list((await db.execute(consulta)).scalars())


async def mis_formularios(db: AsyncSession, actor: Actor) -> list[tuple[Formulario, list[FormularioRespuesta], int]]:
    publicados = (await db.execute(select(Formulario).where(Formulario.estado == EstadoFormulario.publicado,
                                                            Formulario.es_plantilla_base.is_(False)).order_by(Formulario.nombre))).scalars().all()
    resultado = []
    for f in publicados:
        if not _puede_responder(actor, f):
            continue
        if actor.dominio == Dominio.tenant and f.tenant_id and f.tenant_id != actor.tenant_id:
            continue
        en_progreso = (await db.execute(select(FormularioRespuesta).where(
            FormularioRespuesta.formulario_id == f.id, FormularioRespuesta.respondido_por == actor.id,
            FormularioRespuesta.estado == EstadoRespuesta.en_progreso).order_by(FormularioRespuesta.updated_at.desc()))).scalars().all()
        enviados = (await db.execute(select(func.count()).select_from(FormularioRespuesta).where(
            FormularioRespuesta.formulario_id == f.id, FormularioRespuesta.respondido_por == actor.id,
            FormularioRespuesta.estado == EstadoRespuesta.enviado))).scalar_one()
        resultado.append((f, list(en_progreso), enviados))
    return resultado


# ------------------------------------------------------------ evidencias

async def calidad_defaults(db: AsyncSession) -> dict[str, int]:
    fila = (await db.execute(select(CalidadFotoDefault).where(CalidadFotoDefault.clave == "global"))).scalar_one()
    return {k: getattr(fila, k) for k in ("tamano_minimo_kb", "resolucion_minima_ancho", "resolucion_minima_alto", "compresion_maxima_pct")}


async def subir_evidencia(db: AsyncSession, actor: Actor, r: FormularioRespuesta, campo_clave: str, contenido: bytes, nombre: str,
                          mime: str, etiqueta: str | None, orden: int | None, anotaciones: dict | None, anotada: bytes | None,
                          geolat: float | None, geolng: float | None, request: Request) -> tuple[FormularioEvidencia, dict]:
    _exigir_autor_en_progreso(actor, r)
    esquema, _ = await _esquema_de(db, r)
    campo = esquema.campo(campo_clave)
    if campo is None or campo.tipo not in TIPO_EVIDENCIA_POR_CAMPO:
        raise ErrorAPI(422, "CAMPO_INVALIDO", "El campo no existe o no admite evidencias")
    tipo = TIPO_EVIDENCIA_POR_CAMPO[campo.tipo]
    if not contenido:
        raise ErrorAPI(422, "ARCHIVO_VACIO", "El archivo está vacío")
    existentes = (await db.execute(select(FormularioEvidencia).where(
        FormularioEvidencia.respuesta_id == r.id, FormularioEvidencia.campo_clave == campo_clave))).scalars().all()
    cfg = campo.config
    calidad: dict[str, Any] = {"ok": True}
    ancho = alto = None
    exif_ts = None
    if campo.tipo == "fotografia":
        if mime not in ev.MIME_IMAGEN:
            raise ErrorAPI(422, "FORMATO_NO_SOPORTADO", "La foto debe ser JPEG, PNG o WebP")
        if len(existentes) >= cfg["cantidad_max"]:
            raise ErrorAPI(422, "LIMITE_FOTOS", f"Este campo admite máximo {cfg['cantidad_max']} foto(s)")
        if len(contenido) > ev.MAX_BYTES_IMAGEN:
            raise ErrorAPI(413, "ARCHIVO_DEMASIADO_GRANDE", "La imagen excede 25 MB")
        analisis = ev.analizar_imagen(contenido)
        minimos = {**await calidad_defaults(db), **{k: v for k, v in cfg["calidad"].items() if v is not None}}
        problemas = ev.verificar_calidad(analisis, len(contenido), minimos)
        calidad = {"ok": not problemas, "problemas": problemas, "ancho": analisis.ancho, "alto": analisis.alto,
                   "bytes": len(contenido), "compresion_pct": analisis.compresion_pct, "minimos": minimos}
        if problemas:
            raise ErrorAPI(422, "FOTO_RECHAZADA", "La foto no cumple los mínimos de calidad; vuelve a tomarla", problemas)
        ancho, alto, exif_ts = analisis.ancho, analisis.alto, analisis.exif_timestamp
        geolat = analisis.geolat if analisis.geolat is not None else geolat
        geolng = analisis.geolng if analisis.geolng is not None else geolng
        if etiqueta is None and cfg["etiquetas_secuencia"]:
            indice = len(existentes)
            etiqueta = cfg["etiquetas_secuencia"][indice] if indice < len(cfg["etiquetas_secuencia"]) else None
    elif campo.tipo in ("firma", "dibujo"):
        if mime not in ev.MIME_IMAGEN:
            raise ErrorAPI(422, "FORMATO_NO_SOPORTADO", "La firma o dibujo debe ser una imagen PNG/JPEG")
        if campo.tipo == "firma" and existentes:
            raise ErrorAPI(409, "FIRMA_DUPLICADA", "La firma ya fue capturada")
        analisis = ev.analizar_imagen(contenido)
        ancho, alto = analisis.ancho, analisis.alto
    elif campo.tipo == "archivo":
        permitidos: set[str] = set()
        for t in cfg["tipos_permitidos"]:
            if t == "cualquiera":
                permitidos = set()
                break
            permitidos |= ev.MIME_POR_TIPO_ARCHIVO[t]
        if permitidos and mime not in permitidos:
            raise ErrorAPI(422, "FORMATO_NO_SOPORTADO", f"Tipo de archivo no permitido: {mime}")
        if len(contenido) > cfg["tamano_maximo_mb"] * 1024 * 1024:
            raise ErrorAPI(413, "ARCHIVO_DEMASIADO_GRANDE", f"El archivo excede {cfg['tamano_maximo_mb']} MB")
        if len(existentes) >= cfg["cantidad_max"]:
            raise ErrorAPI(422, "LIMITE_ARCHIVOS", f"Este campo admite máximo {cfg['cantidad_max']} archivo(s)")
        if mime in ev.MIME_IMAGEN:
            analisis = ev.analizar_imagen(contenido)
            ancho, alto = analisis.ancho, analisis.alto
    elif campo.tipo == "audio":
        if not mime.startswith("audio/"):
            raise ErrorAPI(422, "FORMATO_NO_SOPORTADO", "Se esperaba un archivo de audio")
        if existentes:
            for e in existentes:  # volver a grabar sustituye la nota anterior
                await db.delete(e)
            await db.flush()
    duenio = r.tenant_id or r.prestador_id
    extension = ev.extension_de(mime, nombre)
    clave = ev.clave_archivo(duenio, r.id, campo_clave, extension)
    almacen = obtener_almacenamiento()
    almacen.guardar(clave, contenido, mime)
    anotada_key = None
    if anotada and campo.tipo in ("fotografia", "archivo") and cfg.get("permitir_anotacion", cfg.get("permitir_anotacion_imagen", True)):
        anotada_key = ev.clave_archivo(duenio, r.id, campo_clave, "png", "-anotada")
        almacen.guardar(anotada_key, anotada, "image/png")  # la imagen compuesta se guarda aparte; el original no se toca
    anot = dict(anotaciones or {})
    if campo.tipo == "audio" and cfg["transcripcion"]:
        anot["transcripcion"] = transcriptor.transcribir(clave, mime)
    evidencia = FormularioEvidencia(respuesta_id=r.id, tenant_id=r.tenant_id, prestador_id=r.prestador_id, campo_clave=campo_clave,
                                    tipo=TipoEvidencia(tipo), archivo_key=clave, archivo_anotado_key=anotada_key, nombre_original=nombre[:255],
                                    mime=mime, bytes=len(contenido), ancho_px=ancho, alto_px=alto, geolat=geolat, geolng=geolng,
                                    exif_timestamp=exif_ts, anotaciones_json=anot, orden=orden if orden is not None else len(existentes),
                                    etiqueta=etiqueta, hash_sha256=ev.hash_sha256(contenido))
    db.add(evidencia)
    await db.flush()
    await auditoria.registrar_actor(db, actor, "formularios.evidencia", request, tenant_id=r.tenant_id, prestador_id=r.prestador_id,
                                    recurso_tipo="formulario_evidencia", recurso_id=evidencia.id,
                                    despues={"campo": campo_clave, "tipo": tipo, "hash": evidencia.hash_sha256, "geolat": geolat, "geolng": geolng})
    return evidencia, calidad


async def eliminar_evidencia(db: AsyncSession, actor: Actor, r: FormularioRespuesta, evidencia_id: UUID) -> None:
    _exigir_autor_en_progreso(actor, r)
    e = await db.get(FormularioEvidencia, evidencia_id)
    if e is None or e.respuesta_id != r.id:
        raise no_encontrado("Evidencia")
    await db.delete(e)
    await db.flush()


# ------------------------------------------------- catálogos personalizados

async def guardar_catalogo_personalizado(db: AsyncSession, actor: Actor, datos: CatalogoPersonalizadoEntrada, request: Request,
                                         existente: CatalogoPersonalizado | None, prestador_id: UUID | None) -> CatalogoPersonalizado:
    if actor.rol not in ROLES_DISENO:
        raise prohibido("Solo el admin del prestador gestiona catálogos personalizados")
    p = prestador_de(actor, prestador_id)
    if p is None:
        raise ErrorAPI(422, "PRESTADOR_REQUERIDO", "Indica prestador_id")
    await _tenant_vinculado(db, p, datos.tenant_id)
    c = existente or CatalogoPersonalizado(prestador_id=p)
    if existente and existente.prestador_id != p:
        raise no_encontrado("Catálogo")
    c.nombre, c.clave, c.tenant_id = datos.nombre, datos.clave, datos.tenant_id
    db.add(c)
    await db.flush()
    actuales = {o.valor: o for o in (await db.execute(select(CatalogoPersonalizadoOpcion).where(
        CatalogoPersonalizadoOpcion.catalogo_id == c.id))).scalars()}
    nuevas: dict[str, CatalogoPersonalizadoOpcion] = {}
    for i, o in enumerate(datos.opciones):
        fila = actuales.get(o.valor) or CatalogoPersonalizadoOpcion(catalogo_id=c.id, prestador_id=p, tenant_id=datos.tenant_id, valor=o.valor)
        fila.etiqueta, fila.orden, fila.activa, fila.tenant_id = o.etiqueta, o.orden or i, o.activa, datos.tenant_id
        db.add(fila)
        nuevas[o.valor] = fila
    for valor, fila in actuales.items():
        if valor not in nuevas:
            fila.activa = False
    await db.flush()
    for o in datos.opciones:  # cascada propia: padre por valor
        nuevas[o.valor].padre_opcion_id = nuevas[o.padre_valor].id if o.padre_valor and o.padre_valor in nuevas else None
    await db.flush()
    await auditoria.registrar_actor(db, actor, "formularios.catalogo_personalizado", request, prestador_id=p, tenant_id=datos.tenant_id,
                                    recurso_tipo="catalogo_personalizado", recurso_id=c.id, despues={"clave": c.clave, "opciones": len(datos.opciones)})
    return c


async def opciones_de_catalogo(db: AsyncSession, catalogo_id: UUID) -> list[CatalogoPersonalizadoOpcion]:
    return list((await db.execute(select(CatalogoPersonalizadoOpcion).where(CatalogoPersonalizadoOpcion.catalogo_id == catalogo_id)
                                  .order_by(CatalogoPersonalizadoOpcion.orden, CatalogoPersonalizadoOpcion.etiqueta))).scalars())

