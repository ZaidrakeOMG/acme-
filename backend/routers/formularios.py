"""Motor de formularios (§4.3, §6.8.3c): diseño, versiones, asignaciones, catálogos, respuestas y evidencias."""
import json
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy import select

from core.dependencias import DB, Actor, ActorActual, requiere_rol
from core.errors import ErrorAPI, no_encontrado
from models.base import Rol
from models.formularios import (
    CalidadFotoDefault, CatalogoPersonalizado, Formulario, FormularioAsignacion, FormularioEvidencia, FormularioPermisoMesa,
    FormularioVersion,
)
from models.usuarios import Usuario
from schemas.comun import RESPUESTAS_ERROR, Mensaje
from schemas.formularios import (
    TIPOS_CAMPO, AsignacionEntrada, AsignacionSalida, CalidadFotoDefaults, CatalogoPersonalizadoEntrada, CatalogoPersonalizadoSalida,
    ClonarEntrada, DiffVersiones, EvidenciaSalida, FormularioCambios, FormularioEntrada, FormularioSalida, MiFormulario,
    OpcionesCatalogoSalida, PermisoMesaSalida, PermisosMesaEntrada, PublicarEntrada, RespuestaEntrada, RespuestaParcial,
    RespuestaSalida, VersionSalida,
)
from services import auditoria
from services.almacenamiento import obtener_almacenamiento
from services.formularios import servicio as svc

router = APIRouter(prefix="/api/formularios", tags=["Formularios"], responses=RESPUESTAS_ERROR)

DISENO = requiere_rol(Rol.superadmin, Rol.admin_prestador)
DISENO_Y_MESA = requiere_rol(Rol.superadmin, Rol.admin_prestador, Rol.mesa_control)


async def _salida(db, actor, f) -> FormularioSalida:
    return FormularioSalida(**await svc.salida(db, actor, f))


def _version_salida(v: FormularioVersion) -> VersionSalida:
    return VersionSalida(**{k: getattr(v, k) for k in ("id", "created_at", "updated_at", "version_hash", "formulario_id", "numero_version",
                                                       "esquema_json", "publicada_por", "notas_version")},
                         publicada_at=v.publicada_at.isoformat() if v.publicada_at else None)


def _respuesta_salida(r, nombre: str | None = None, numero_version: int | None = None, errores=None) -> RespuestaSalida:
    return RespuestaSalida(**{k: getattr(r, k) for k in ("id", "created_at", "updated_at", "version_hash", "formulario_id", "version_id",
                                                         "tenant_id", "prestador_id", "un_id", "equipo_id", "referencia_id", "respuestas_json",
                                                         "respondido_por", "inmutable")},
                           origen=r.origen.value, estado=r.estado.value, iniciado_at=r.iniciado_at.isoformat(),
                           enviado_at=r.enviado_at.isoformat() if r.enviado_at else None, numero_version=numero_version or 0,
                           nombre_formulario=nombre, errores=errores or [])


def _evidencia_salida(e: FormularioEvidencia, calidad: dict | None = None) -> EvidenciaSalida:
    return EvidenciaSalida(**{k: getattr(e, k) for k in ("id", "created_at", "updated_at", "version_hash", "respuesta_id", "campo_clave",
                                                         "archivo_key", "nombre_original", "mime", "bytes", "ancho_px", "alto_px", "geolat",
                                                         "geolng", "anotaciones_json", "orden", "etiqueta", "hash_sha256")},
                           tipo=e.tipo.value, exif_timestamp=e.exif_timestamp.isoformat() if e.exif_timestamp else None, calidad=calidad or {})


# ------------------------------------------------------------------ catálogo

@router.get("/tipos-campo", summary="Los 22 tipos de campo", description="Identificadores de §4.3 en orden y el contrato de `config` por tipo.")
async def tipos_campo(_: ActorActual) -> list[dict]:
    from schemas.formularios import CONFIG_POR_TIPO
    return [{"tipo": t, "config": CONFIG_POR_TIPO[t].model_json_schema()} for t in TIPOS_CAMPO]


@router.get("/opciones", response_model=OpcionesCatalogoSalida, summary="Opciones de un catálogo del sistema",
            description="Para campos enlazados a catálogo (§6.8.3c). `padre` filtra en cascada; `un_id`/`equipo_id` son el contexto del folio.")
async def opciones(db: DB, actor: ActorActual, catalogo: str, tenant_id: UUID | None = None, un_id: UUID | None = None,
                   equipo_id: UUID | None = None, padre: str | None = None, catalogo_personalizado_id: UUID | None = None):
    lista, aviso = await svc.opciones_catalogo(db, actor, catalogo, tenant_id, un_id, equipo_id, padre, catalogo_personalizado_id)
    return OpcionesCatalogoSalida(catalogo=catalogo, opciones=lista, aviso=aviso)


@router.get("/calidad-foto-defaults", response_model=CalidadFotoDefaults, summary="Defaults globales de calidad de foto")
async def calidad_defaults(db: DB, _: ActorActual):
    return CalidadFotoDefaults(**await svc.calidad_defaults(db))


@router.put("/calidad-foto-defaults", response_model=CalidadFotoDefaults, summary="Cambiar defaults de calidad (superadmin)")
async def calidad_defaults_put(datos: CalidadFotoDefaults, request: Request, db: DB, actor: Actor = Depends(requiere_rol(Rol.superadmin))):
    fila = (await db.execute(select(CalidadFotoDefault).where(CalidadFotoDefault.clave == "global"))).scalar_one()
    antes = auditoria.instantanea(fila)
    for k, v in datos.model_dump().items():
        setattr(fila, k, v)
    await db.flush()
    await auditoria.registrar_actor(db, actor, "formularios.calidad_foto_defaults", request, recurso_tipo="calidad_foto_defaults",
                                    recurso_id="global", antes=antes, despues=datos.model_dump())
    await db.commit()
    return datos


# --------------------------------------------------- formularios y versiones

@router.get("", response_model=list[FormularioSalida], summary="Listar formularios",
            description="Filtros: `tipo`, `alcance` (global|tenant), `estado`, `plantillas`. Los roles de uso solo ven publicados.")
async def listar(db: DB, actor: ActorActual, tipo: str | None = None, alcance: str | None = None, estado: str | None = None,
                 prestador_id: UUID | None = None, plantillas: bool | None = None):
    return [await _salida(db, actor, f) for f in await svc.listar(db, actor, tipo, alcance, estado, prestador_id, plantillas)]


@router.get("/plantillas", response_model=list[FormularioSalida], summary="Repositorio de plantillas base")
async def plantillas(db: DB, actor: Actor = Depends(DISENO_Y_MESA)):
    return [await _salida(db, actor, f) for f in await svc.listar(db, actor, None, None, None, None, True)]


@router.get("/mis-formularios", response_model=list[MiFormulario], summary="Formularios publicados para mi rol",
            description="Con mis respuestas en progreso (reanudables) y el conteo de enviadas.")
async def mis_formularios(db: DB, actor: ActorActual):
    salida = []
    for f, en_progreso, enviados in await svc.mis_formularios(db, actor):
        fs = await _salida(db, actor, f)
        salida.append(MiFormulario(formulario=fs, enviados=enviados,
                                   en_progreso=[_respuesta_salida(r, f.nombre, fs.numero_version_publicada) for r in en_progreso]))
    return salida


@router.get("/resolver", response_model=FormularioSalida, summary="Formulario aplicable (prioridad §6.8.3c)",
            description="`tipo` es el tipo de formulario; `tipo_folio` (correctivo, preventivo…) acota las asignaciones. Devuelve el publicado "
                        "más específico para cliente, tipo/familia de equipo y plan (§6.8.3c). P04 lo consume.")
async def resolver(db: DB, actor: ActorActual, tipo: str | None = None, tenant_id: UUID | None = None, tipo_equipo_id: UUID | None = None,
                   familia_equipo_id: UUID | None = None, plan_id: UUID | None = None, prestador_id: UUID | None = None,
                   tipo_folio: str | None = None):
    r = await svc.resolver(db, actor, tipo, tenant_id, tipo_equipo_id, familia_equipo_id, plan_id, prestador_id, tipo_folio)
    if r is None:
        raise ErrorAPI(404, "SIN_FORMULARIO", "No hay un formulario publicado asignado para ese contexto")
    f, v, _ = r
    salida = await _salida(db, actor, f)
    salida.esquema_json = v.esquema_json
    salida.version_actual = v.numero_version
    return salida


# ------------------------------------------------------- catálogos personalizados

async def _catalogo_salida(db, c: CatalogoPersonalizado) -> CatalogoPersonalizadoSalida:
    return CatalogoPersonalizadoSalida(**{k: getattr(c, k) for k in ("id", "created_at", "updated_at", "version_hash", "prestador_id", "tenant_id", "nombre", "clave", "activo")},
                                       opciones=await svc.opciones_de_catalogo(db, c.id))


@router.get("/catalogos-personalizados", response_model=list[CatalogoPersonalizadoSalida], summary="Catálogos personalizados del prestador")
async def catalogos_personalizados(db: DB, actor: ActorActual, prestador_id: UUID | None = None):
    consulta = select(CatalogoPersonalizado).where(CatalogoPersonalizado.activo.is_(True)).order_by(CatalogoPersonalizado.nombre)
    if actor.es_superadmin and prestador_id:
        consulta = consulta.where(CatalogoPersonalizado.prestador_id == prestador_id)
    return [await _catalogo_salida(db, c) for c in (await db.execute(consulta)).scalars()]


@router.post("/catalogos-personalizados", response_model=CatalogoPersonalizadoSalida, status_code=201, summary="Crear catálogo personalizado")
async def crear_catalogo(datos: CatalogoPersonalizadoEntrada, request: Request, db: DB, actor: Actor = Depends(DISENO), prestador_id: UUID | None = None):
    c = await svc.guardar_catalogo_personalizado(db, actor, datos, request, None, prestador_id)
    await db.commit()
    return await _catalogo_salida(db, c)


@router.put("/catalogos-personalizados/{catalogo_id}", response_model=CatalogoPersonalizadoSalida, summary="Reemplazar catálogo y sus opciones")
async def editar_catalogo(catalogo_id: UUID, datos: CatalogoPersonalizadoEntrada, request: Request, db: DB, actor: Actor = Depends(DISENO)):
    c = await db.get(CatalogoPersonalizado, catalogo_id)
    if c is None:
        raise no_encontrado("Catálogo")
    c = await svc.guardar_catalogo_personalizado(db, actor, datos, request, c, c.prestador_id)
    await db.commit()
    return await _catalogo_salida(db, c)


async def _nombre_y_version(db, r) -> tuple[str | None, int | None]:
    f = await db.get(Formulario, r.formulario_id)
    v = await db.get(FormularioVersion, r.version_id)
    return (f.nombre if f else None), (v.numero_version if v else None)


@router.get("/respuestas", response_model=list[RespuestaSalida], summary="Listar respuestas",
            description="Técnico/operador: solo las propias. Admins del tenant: las de su cliente. Filtros por formulario, origen, referencia y estado.")
async def respuestas(db: DB, actor: ActorActual, formulario_id: UUID | None = None, origen: str | None = None,
                     referencia_id: UUID | None = None, estado: str | None = None, mias: bool = False,
                     limite: int = Query(default=100, ge=1, le=1000)):
    salida = []
    for r in await svc.listar_respuestas(db, actor, formulario_id, origen, referencia_id, estado, mias, limite):
        nombre, numero = await _nombre_y_version(db, r)
        salida.append(_respuesta_salida(r, nombre, numero))
    return salida


@router.post("", response_model=FormularioSalida, status_code=201, summary="Crear formulario (borrador v1)")
async def crear(datos: FormularioEntrada, request: Request, db: DB, actor: Actor = Depends(DISENO)):
    f = await svc.crear(db, actor, datos, request)
    await db.commit()
    return await _salida(db, actor, f)


@router.get("/{formulario_id}", response_model=FormularioSalida, summary="Detalle con esquema de la versión más reciente")
async def detalle(formulario_id: UUID, db: DB, actor: ActorActual):
    return await _salida(db, actor, await svc.obtener(db, actor, formulario_id))


@router.put("/{formulario_id}", response_model=FormularioSalida, summary="Editar",
            description="En borrador edita la versión actual; si está publicado crea `numero_version + 1` en borrador (la publicada no cambia).")
async def editar(formulario_id: UUID, cambios: FormularioCambios, request: Request, db: DB, actor: Actor = Depends(DISENO_Y_MESA)):
    f = await svc.editar(db, actor, formulario_id, cambios, request)
    await db.commit()
    return await _salida(db, actor, f)


@router.post("/{formulario_id}/publicar", response_model=FormularioSalida, summary="Publicar la versión más reciente")
async def publicar(formulario_id: UUID, datos: PublicarEntrada, request: Request, db: DB, actor: Actor = Depends(DISENO_Y_MESA)):
    f = await svc.publicar(db, actor, formulario_id, datos.notas_version, request)
    await db.commit()
    return await _salida(db, actor, f)


@router.post("/{formulario_id}/archivar", response_model=FormularioSalida, summary="Archivar")
async def archivar(formulario_id: UUID, request: Request, db: DB, actor: Actor = Depends(DISENO)):
    f = await svc.archivar(db, actor, formulario_id, request)
    await db.commit()
    return await _salida(db, actor, f)


@router.post("/{formulario_id}/clonar", response_model=FormularioSalida, status_code=201, summary="Clonar (plantilla base o propio)")
async def clonar(formulario_id: UUID, datos: ClonarEntrada, request: Request, db: DB, actor: Actor = Depends(DISENO)):
    f = await svc.clonar(db, actor, formulario_id, datos, request)
    await db.commit()
    return await _salida(db, actor, f)


@router.get("/{formulario_id}/versiones", response_model=list[VersionSalida], summary="Historial de versiones")
async def versiones(formulario_id: UUID, db: DB, actor: Actor = Depends(DISENO_Y_MESA)):
    await svc.obtener(db, actor, formulario_id)
    filas = (await db.execute(select(FormularioVersion).where(FormularioVersion.formulario_id == formulario_id)
                              .order_by(FormularioVersion.numero_version))).scalars().all()
    return [_version_salida(v) for v in filas]


@router.get("/{formulario_id}/versiones/diff", response_model=DiffVersiones, summary="Comparar dos versiones")
async def diff(formulario_id: UUID, db: DB, de: int, a: int, actor: Actor = Depends(DISENO_Y_MESA)):
    await svc.obtener(db, actor, formulario_id)
    filas = {v.numero_version: v for v in (await db.execute(select(FormularioVersion).where(
        FormularioVersion.formulario_id == formulario_id, FormularioVersion.numero_version.in_([de, a])))).scalars()}
    if de not in filas or a not in filas:
        raise no_encontrado("Versión")
    return DiffVersiones(de=de, a=a, **svc.diff_esquemas(filas[de].esquema_json, filas[a].esquema_json))


@router.get("/{formulario_id}/versiones/{numero}", response_model=VersionSalida, summary="Una versión")
async def version(formulario_id: UUID, numero: int, db: DB, actor: Actor = Depends(DISENO_Y_MESA)):
    await svc.obtener(db, actor, formulario_id)
    v = (await db.execute(select(FormularioVersion).where(FormularioVersion.formulario_id == formulario_id,
                                                           FormularioVersion.numero_version == numero))).scalar_one_or_none()
    if v is None:
        raise no_encontrado("Versión")
    return _version_salida(v)


# --------------------------------------------------------------- asignaciones

@router.get("/{formulario_id}/asignaciones", response_model=list[AsignacionSalida], summary="Asignaciones del formulario")
async def asignaciones(formulario_id: UUID, db: DB, actor: Actor = Depends(DISENO_Y_MESA)):
    await svc.obtener(db, actor, formulario_id)
    return (await db.execute(select(FormularioAsignacion).where(FormularioAsignacion.formulario_id == formulario_id)
                             .order_by(FormularioAsignacion.prioridad.desc()))).scalars().all()


@router.post("/{formulario_id}/asignaciones", response_model=AsignacionSalida, status_code=201, summary="Asignar a cliente, tipo de folio, tipo/familia de equipo o plan")
async def asignar(formulario_id: UUID, datos: AsignacionEntrada, request: Request, db: DB, actor: Actor = Depends(DISENO)):
    a = await svc.crear_asignacion(db, actor, formulario_id, datos, request)
    await db.commit()
    return a


@router.delete("/asignaciones/{asignacion_id}", response_model=Mensaje, summary="Quitar asignación")
async def quitar_asignacion(asignacion_id: UUID, request: Request, db: DB, actor: Actor = Depends(DISENO)):
    a = await db.get(FormularioAsignacion, asignacion_id)
    if a is None or (not actor.es_superadmin and a.prestador_id != actor.prestador_id):
        raise no_encontrado("Asignación")
    await auditoria.registrar_actor(db, actor, "formularios.asignacion_eliminada", request, prestador_id=a.prestador_id, tenant_id=a.tenant_id,
                                    recurso_tipo="formulario_asignacion", recurso_id=a.id, antes=auditoria.instantanea(a))
    await db.delete(a)
    await db.commit()
    return Mensaje(mensaje="Asignación eliminada")


@router.get("/{formulario_id}/permisos-mesa", response_model=list[PermisoMesaSalida], summary="Usuarios de mesa que pueden editar el publicado")
async def permisos_mesa(formulario_id: UUID, db: DB, actor: Actor = Depends(DISENO)):
    await svc.obtener(db, actor, formulario_id)
    filas = (await db.execute(select(FormularioPermisoMesa, Usuario).join(Usuario, Usuario.id == FormularioPermisoMesa.usuario_id)
                              .where(FormularioPermisoMesa.formulario_id == formulario_id))).all()
    return [PermisoMesaSalida(usuario_id=p.usuario_id, nombre=u.nombre, puede_editar_publicado=p.puede_editar_publicado) for p, u in filas]


@router.put("/{formulario_id}/permisos-mesa", response_model=list[PermisoMesaSalida], summary="Definir permisos de mesa de control (§6.8.3c)")
async def permisos_mesa_put(formulario_id: UUID, datos: PermisosMesaEntrada, request: Request, db: DB, actor: Actor = Depends(DISENO)):
    f = await svc.obtener(db, actor, formulario_id)
    await svc.exigir_edicion(db, actor, f)
    if f.prestador_id is None:
        raise ErrorAPI(422, "PLANTILLA", "Las plantillas base no tienen permisos de mesa")
    ids = [p.usuario_id for p in datos.permisos]
    usuarios = {u.id: u for u in (await db.execute(select(Usuario).where(Usuario.id.in_(ids or [UUID(int=0)])))).scalars()}
    for p in datos.permisos:
        u = usuarios.get(p.usuario_id)
        if u is None or u.rol != Rol.mesa_control or u.prestador_id != f.prestador_id:
            raise ErrorAPI(422, "USUARIO_INVALIDO", "Solo usuarios de mesa de control del mismo prestador")
    existentes = (await db.execute(select(FormularioPermisoMesa).where(FormularioPermisoMesa.formulario_id == f.id))).scalars().all()
    for e in existentes:
        await db.delete(e)
    await db.flush()
    for p in datos.permisos:
        db.add(FormularioPermisoMesa(formulario_id=f.id, prestador_id=f.prestador_id, usuario_id=p.usuario_id, puede_editar_publicado=p.puede_editar_publicado))
    await db.flush()
    await auditoria.registrar_actor(db, actor, "formularios.permisos_mesa", request, prestador_id=f.prestador_id, recurso_tipo="formulario",
                                    recurso_id=f.id, despues={str(p.usuario_id): p.puede_editar_publicado for p in datos.permisos})
    await db.commit()
    return await permisos_mesa(formulario_id, db, actor)


# ------------------------------------------------------------------ respuestas

@router.post("/{formulario_id}/respuestas", response_model=RespuestaSalida, status_code=201, summary="Iniciar respuesta (en progreso)")
async def crear_respuesta(formulario_id: UUID, datos: RespuestaEntrada, request: Request, db: DB, actor: ActorActual):
    r = await svc.crear_respuesta(db, actor, formulario_id, datos, request)
    await db.commit()
    nombre, numero = await _nombre_y_version(db, r)
    return _respuesta_salida(r, nombre, numero)


@router.get("/respuestas/{respuesta_id}", response_model=RespuestaSalida, summary="Detalle de una respuesta",
            description="Incluye `errores` de validación pendientes si sigue en progreso.")
async def respuesta(respuesta_id: UUID, db: DB, actor: ActorActual):
    r = await svc.obtener_respuesta(db, actor, respuesta_id)
    nombre, numero = await _nombre_y_version(db, r)
    errores = await svc.errores_de(db, actor, r) if r.estado.value == "en_progreso" else []
    return _respuesta_salida(r, nombre, numero, errores)


@router.put("/respuestas/{respuesta_id}", response_model=RespuestaSalida, summary="Guardar parcial (reanudable)")
async def guardar(respuesta_id: UUID, datos: RespuestaParcial, db: DB, actor: ActorActual):
    r = await svc.obtener_respuesta(db, actor, respuesta_id)
    await svc.guardar_parcial(db, actor, r, datos.respuestas, datos.dispositivo)
    await db.commit()
    nombre, numero = await _nombre_y_version(db, r)
    return _respuesta_salida(r, nombre, numero, await svc.errores_de(db, actor, r))


@router.post("/respuestas/{respuesta_id}/enviar", response_model=RespuestaSalida, summary="Enviar (valida y vuelve inmutable)",
             description="Valida con el mismo motor que el cliente; recalcula concatenaciones, matemáticas y sellos; aplica geofencing.")
async def enviar(respuesta_id: UUID, request: Request, db: DB, actor: ActorActual):
    r = await svc.obtener_respuesta(db, actor, respuesta_id)
    await svc.enviar(db, actor, r, request)
    await db.commit()
    nombre, numero = await _nombre_y_version(db, r)
    return _respuesta_salida(r, nombre, numero)


@router.get("/respuestas/{respuesta_id}/evidencias", response_model=list[EvidenciaSalida], summary="Evidencias de la respuesta")
async def evidencias(respuesta_id: UUID, db: DB, actor: ActorActual):
    r = await svc.obtener_respuesta(db, actor, respuesta_id)
    filas = (await db.execute(select(FormularioEvidencia).where(FormularioEvidencia.respuesta_id == r.id)
                              .order_by(FormularioEvidencia.campo_clave, FormularioEvidencia.orden))).scalars().all()
    return [_evidencia_salida(e) for e in filas]


@router.post("/respuestas/{respuesta_id}/evidencias", response_model=EvidenciaSalida, status_code=201, summary="Subir evidencia",
             description="Multipart: `archivo`, `campo_clave`, opcionales `etiqueta`, `orden`, `anotaciones` (JSON), `imagen_anotada`, "
                         "`geolat`, `geolng`. Las fotos se validan contra los mínimos de calidad (422 FOTO_RECHAZADA).")
async def subir_evidencia(respuesta_id: UUID, request: Request, db: DB, actor: ActorActual, archivo: UploadFile = File(...),
                          campo_clave: str = Form(...), etiqueta: str | None = Form(default=None), orden: int | None = Form(default=None),
                          anotaciones: str | None = Form(default=None), imagen_anotada: UploadFile | None = File(default=None),
                          geolat: float | None = Form(default=None), geolng: float | None = Form(default=None)):
    r = await svc.obtener_respuesta(db, actor, respuesta_id)
    contenido = await archivo.read()
    anotada = await imagen_anotada.read() if imagen_anotada else None
    try:
        anot = json.loads(anotaciones) if anotaciones else None
    except json.JSONDecodeError:
        raise ErrorAPI(422, "ANOTACIONES_INVALIDAS", "anotaciones debe ser JSON")
    e, calidad = await svc.subir_evidencia(db, actor, r, campo_clave, contenido, archivo.filename or "archivo", archivo.content_type or "application/octet-stream",
                                           etiqueta, orden, anot, anotada, geolat, geolng, request)
    await db.commit()
    return _evidencia_salida(e, calidad)


@router.delete("/respuestas/{respuesta_id}/evidencias/{evidencia_id}", response_model=Mensaje, summary="Quitar evidencia (solo en progreso)")
async def eliminar_evidencia(respuesta_id: UUID, evidencia_id: UUID, db: DB, actor: ActorActual):
    r = await svc.obtener_respuesta(db, actor, respuesta_id)
    await svc.eliminar_evidencia(db, actor, r, evidencia_id)
    await db.commit()
    return Mensaje(mensaje="Evidencia eliminada")


@router.get("/respuestas/{respuesta_id}/evidencias/{evidencia_id}/archivo", summary="Descargar el archivo de una evidencia")
async def descargar_evidencia(respuesta_id: UUID, evidencia_id: UUID, db: DB, actor: ActorActual, anotada: bool = False) -> Response:
    r = await svc.obtener_respuesta(db, actor, respuesta_id)
    e = await db.get(FormularioEvidencia, evidencia_id)
    if e is None or e.respuesta_id != r.id:
        raise no_encontrado("Evidencia")
    clave = e.archivo_anotado_key if anotada and e.archivo_anotado_key else e.archivo_key
    try:
        datos = obtener_almacenamiento().leer(clave)
    except Exception:
        raise no_encontrado("Archivo")
    return Response(datos, media_type="image/png" if anotada and e.archivo_anotado_key else e.mime,
                    headers={"Content-Disposition": f'inline; filename="{e.nombre_original}"'})

