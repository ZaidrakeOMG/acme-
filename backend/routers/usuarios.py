"""Administración de usuarios. superadmin: todos; admin_empresa: su tenant; admin_prestador: su prestador."""
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select, text, update

from core.dependencias import DB, Actor, ActorActual, requiere_rol
from core.errors import ErrorAPI, no_encontrado, prohibido
from core.modulos import validar_modulos
from core.security import errores_politica_contrasena, hashear_contrasena_async
from models.base import ROLES_PRESTADOR, ROLES_TENANT, Dominio, EstadoRegistro, Rol, dominio_de_rol
from models.usuarios import Sesion, Usuario
from schemas.comun import RESPUESTAS_ERROR
from schemas.mensajeria import CodigoEntrada, ConsentimientoEntrada, TelefonoEntrada, TelefonoSalida
from schemas.organizaciones import UsuarioCambios, UsuarioEntrada, UsuarioSalida
from services import auditoria

router = APIRouter(prefix="/api/usuarios", tags=["Usuarios"], responses=RESPUESTAS_ERROR)

ADMINS = requiere_rol(Rol.superadmin, Rol.admin_empresa, Rol.admin_prestador)
# El correo es único en toda la plataforma; la búsqueda no depende de la RLS del actor.
_EMAIL_EXISTE = text("SELECT EXISTS (SELECT 1 FROM auth_identidad_por_email(:e))")


def _roles_asignables(actor: Actor) -> set[Rol]:
    if actor.rol == Rol.superadmin:
        return set(Rol)
    if actor.rol == Rol.admin_empresa:
        return set(ROLES_TENANT)
    if actor.rol == Rol.admin_prestador:
        return set(ROLES_PRESTADOR)
    return set()


def _puede_administrar(actor: Actor, usuario: Usuario) -> bool:
    if actor.rol == Rol.superadmin:
        return True
    if actor.rol == Rol.admin_empresa:
        return usuario.dominio == Dominio.tenant and usuario.tenant_id == actor.tenant_id
    if actor.rol == Rol.admin_prestador:
        return usuario.dominio == Dominio.prestador and usuario.prestador_id == actor.prestador_id
    return False


async def _obtener(db, actor: Actor, usuario_id: UUID) -> Usuario:
    usuario = await db.get(Usuario, usuario_id)
    if usuario is None or not _puede_administrar(actor, usuario):
        raise no_encontrado("Usuario")
    return usuario


@router.get("", response_model=list[UsuarioSalida], summary="Listar usuarios",
            description="Usuarios que el administrador puede gestionar. Filtros opcionales por rol, estado y texto.")
async def listar(db: DB, actor: Actor = Depends(ADMINS),
                 rol: Rol | None = None, estado: EstadoRegistro | None = None,
                 tenant_id: UUID | None = None, prestador_id: UUID | None = None,
                 q: str | None = Query(default=None, max_length=100),
                 limite: int = Query(default=200, ge=1, le=1000), desplazamiento: int = Query(default=0, ge=0)):
    consulta = select(Usuario)
    if actor.rol == Rol.admin_empresa:
        consulta = consulta.where(Usuario.tenant_id == actor.tenant_id)
    elif actor.rol == Rol.admin_prestador:
        consulta = consulta.where(Usuario.prestador_id == actor.prestador_id)
    else:
        if tenant_id:
            consulta = consulta.where(Usuario.tenant_id == tenant_id)
        if prestador_id:
            consulta = consulta.where(Usuario.prestador_id == prestador_id)
    if rol:
        consulta = consulta.where(Usuario.rol == rol)
    if estado:
        consulta = consulta.where(Usuario.estado == estado)
    if q:
        patron = f"%{q.lower()}%"
        consulta = consulta.where(func.lower(Usuario.nombre).like(patron) | func.lower(Usuario.email).like(patron))
    consulta = consulta.order_by(Usuario.nombre).limit(limite).offset(desplazamiento)
    return (await db.execute(consulta)).scalars().all()


@router.post("", response_model=UsuarioSalida, status_code=201, summary="Crear usuario",
             description="admin_empresa crea roles de su tenant; admin_prestador, roles de su prestador; "
                         "superadmin cualquier rol indicando tenant_id o prestador_id.")
async def crear(datos: UsuarioEntrada, request: Request, db: DB, actor: Actor = Depends(ADMINS)):
    if datos.rol not in _roles_asignables(actor):
        raise prohibido(f"No puedes crear usuarios con rol {datos.rol.value}")
    errores = errores_politica_contrasena(datos.contrasena)
    if errores:
        raise ErrorAPI(422, "POLITICA_CONTRASENA", "La contraseña no cumple la política", errores)

    dominio = dominio_de_rol(datos.rol)
    tenant_id = prestador_id = None
    if dominio == Dominio.tenant:
        tenant_id = actor.tenant_id if actor.rol != Rol.superadmin else datos.tenant_id
        if tenant_id is None:
            raise ErrorAPI(422, "TENANT_REQUERIDO", "Los roles del dominio tenant requieren tenant_id")
    elif dominio == Dominio.prestador:
        prestador_id = actor.prestador_id if actor.rol != Rol.superadmin else datos.prestador_id
        if prestador_id is None:
            raise ErrorAPI(422, "PRESTADOR_REQUERIDO", "Los roles del dominio prestador requieren prestador_id")

    existe = (await db.execute(_EMAIL_EXISTE, {"e": datos.email})).scalar()
    if existe:
        raise ErrorAPI(409, "EMAIL_DUPLICADO", "Ya existe un usuario con ese correo")

    validar_modulos(datos.modulos_habilitados)
    usuario = Usuario(
        modulos_habilitados=(None if datos.rol == Rol.superadmin else datos.modulos_habilitados),
        email=datos.email.lower(), nombre=datos.nombre, telefono=datos.telefono, rol=datos.rol, dominio=dominio,
        tenant_id=tenant_id, prestador_id=prestador_id, password_hash=await hashear_contrasena_async(datos.contrasena),
    )
    db.add(usuario)
    await db.flush()
    await auditoria.registrar_actor(db, actor, "usuarios.alta", request, tenant_id=tenant_id, prestador_id=prestador_id,
                                    recurso_tipo="usuario", recurso_id=usuario.id, despues=auditoria.instantanea(usuario))
    await db.commit()
    return usuario


# ------------------------------------------------------------------ mi teléfono y mis consentimientos (F2-02)
# Van antes de `/{usuario_id}`: FastAPI resuelve las rutas en el orden en que se declaran y «me» no es un UUID.
def _salida_telefono(usuario: Usuario) -> TelefonoSalida:
    from services.mensajeria import telefonos

    return TelefonoSalida(**telefonos.estado_de_canales(usuario), aviso_privacidad=telefonos.AVISO_PRIVACIDAD)


@router.get("/me/telefono", response_model=TelefonoSalida, summary="Mi teléfono móvil y mis consentimientos",
            description="Nunca devuelve el número completo: solo su máscara (§6.9.5).")
async def mi_telefono(db: DB, actor: ActorActual):
    usuario = await db.get(Usuario, actor.id)
    return _salida_telefono(usuario)


@router.put("/me/telefono", response_model=TelefonoSalida, summary="Guardar mi teléfono móvil",
            description="Lo guarda cifrado y **sin verificar**: cambiar el número obliga a verificarlo otra vez.")
async def guardar_mi_telefono(datos: TelefonoEntrada, request: Request, db: DB, actor: ActorActual):
    from services.mensajeria import telefonos

    usuario = await db.get(Usuario, actor.id)
    e164 = telefonos.normalizar(datos.telefono)
    telefonos.guardar(usuario, e164)
    await auditoria.registrar_actor(db, actor, "usuarios.telefono", request, recurso_tipo="usuario",
                                    recurso_id=usuario.id,
                                    despues={"telefono": usuario.telefono_movil_mascara, "verificado": False})
    await db.commit()
    await db.refresh(usuario)
    return _salida_telefono(usuario)


@router.delete("/me/telefono", response_model=TelefonoSalida, summary="Quitar mi teléfono móvil",
               description="Sin número no hay canal: se borran también los consentimientos de WhatsApp y SMS.")
async def borrar_mi_telefono(request: Request, db: DB, actor: ActorActual):
    from services.mensajeria import telefonos

    usuario = await db.get(Usuario, actor.id)
    telefonos.borrar(usuario)
    await auditoria.registrar_actor(db, actor, "usuarios.telefono_baja", request, recurso_tipo="usuario",
                                    recurso_id=usuario.id, despues={"telefono": None})
    await db.commit()
    await db.refresh(usuario)
    return _salida_telefono(usuario)


@router.post("/me/telefono/codigo", summary="Enviarme el código de verificación por WhatsApp o SMS",
             description="Código de un solo uso, válido 10 minutos. En modo `stub` queda en la bitácora y en el log.")
async def pedir_codigo(db: DB, actor: ActorActual, canal: str = Query(default="sms", pattern="^(whatsapp|sms)$")) -> dict:
    from services import mensajeria_service

    usuario = await db.get(Usuario, actor.id)
    r = await mensajeria_service.enviar_codigo(db, usuario, canal)
    await db.commit()
    return r


@router.post("/me/telefono/verificar", response_model=TelefonoSalida, summary="Verificar mi teléfono con el código")
async def verificar_telefono(datos: CodigoEntrada, request: Request, db: DB, actor: ActorActual):
    from services.mensajeria import telefonos

    usuario = await db.get(Usuario, actor.id)
    try:
        telefonos.verificar_codigo(usuario, datos.codigo)
    finally:
        await db.commit()  # los intentos fallidos también se guardan
    await auditoria.registrar_actor(db, actor, "usuarios.telefono_verificado", request, recurso_tipo="usuario",
                                    recurso_id=usuario.id, despues={"telefono": usuario.telefono_movil_mascara})
    await db.commit()
    await db.refresh(usuario)
    return _salida_telefono(usuario)


@router.put("/me/consentimiento", response_model=TelefonoSalida, summary="Dar o quitar el consentimiento de un canal",
            description="Equivale a escribir ALTA o BAJA por WhatsApp o SMS. Queda en la bitácora con su fecha.")
async def consentimiento(datos: ConsentimientoEntrada, request: Request, db: DB, actor: ActorActual):
    from services.mensajeria import telefonos

    usuario = await db.get(Usuario, actor.id)
    if datos.acepta and usuario.telefono_verificado_at is None:
        raise ErrorAPI(409, "TELEFONO_SIN_VERIFICAR",
                       "Verifica tu teléfono antes de activar WhatsApp o SMS")
    telefonos.fijar_consentimiento(usuario, datos.canal.value, datos.acepta)
    await auditoria.registrar_actor(db, actor, "usuarios.consentimiento", request, recurso_tipo="usuario",
                                    recurso_id=usuario.id,
                                    despues={"canal": datos.canal.value, "acepta": datos.acepta,
                                             "telefono": usuario.telefono_movil_mascara})
    await db.commit()
    await db.refresh(usuario)
    return _salida_telefono(usuario)


@router.get("/{usuario_id}", response_model=UsuarioSalida, summary="Detalle de usuario")
async def detalle(usuario_id: UUID, db: DB, actor: Actor = Depends(ADMINS)):
    return await _obtener(db, actor, usuario_id)


@router.patch("/{usuario_id}", response_model=UsuarioSalida, summary="Modificar usuario",
              description="Cambia nombre, teléfono, rol (dentro del mismo dominio) o estado. Desactivar revoca sus sesiones.")
async def modificar(usuario_id: UUID, datos: UsuarioCambios, request: Request, db: DB, actor: Actor = Depends(ADMINS)):
    usuario = await _obtener(db, actor, usuario_id)
    antes = auditoria.instantanea(usuario)
    cambios = datos.model_dump(exclude_unset=True)

    if "rol" in cambios and cambios["rol"] != usuario.rol:
        nuevo = cambios["rol"]
        if usuario.id == actor.id:
            raise prohibido("No puedes cambiar tu propio rol")
        if nuevo not in _roles_asignables(actor) or dominio_de_rol(nuevo) != usuario.dominio:
            raise prohibido(f"No puedes asignar el rol {nuevo.value} a este usuario")
    if 'modulos_habilitados' in cambios:
        validar_modulos(cambios['modulos_habilitados'])
        if usuario.rol == Rol.superadmin:
            raise prohibido('No se pueden limitar los módulos del superadmin')
    if cambios.get("estado") and cambios["estado"] != EstadoRegistro.activo and usuario.id == actor.id:
        raise prohibido("No puedes desactivarte a ti mismo")

    for campo, valor in cambios.items():
        if valor is not None or campo == 'modulos_habilitados':
            setattr(usuario, campo, valor)
    # Cambiar de rol restaura sus accesos por rol, salvo que se especifiquen nuevos módulos.
    if 'rol' in cambios and 'modulos_habilitados' not in cambios:
        usuario.modulos_habilitados = None
    if "rol" in cambios or 'modulos_habilitados' in cambios or (cambios.get("estado") and cambios["estado"] != EstadoRegistro.activo):
        await db.execute(update(Sesion).where(Sesion.usuario_id == usuario.id, Sesion.revocada_at.is_(None))
                         .values(revocada_at=func.now(), motivo_revocacion="cambio_perfil"))
    await db.flush()
    evento = "usuarios.cambio_rol" if "rol" in cambios else "usuarios.modificacion"
    await auditoria.registrar_actor(db, actor, evento, request, tenant_id=usuario.tenant_id, prestador_id=usuario.prestador_id,
                                    recurso_tipo="usuario", recurso_id=usuario.id, antes=antes, despues=auditoria.instantanea(usuario))
    await db.commit()
    await db.refresh(usuario)
    return usuario


@router.delete('/{usuario_id}', status_code=204, summary='Dar de baja el acceso de un usuario')
async def eliminar(usuario_id: UUID, request: Request, db: DB, actor: Actor = Depends(ADMINS)):
    # Baja lógica: los folios, auditorías y referencias a este usuario se conservan.
    usuario = await _obtener(db, actor, usuario_id)
    if usuario.id == actor.id:
        raise prohibido('No puedes eliminar tu propia cuenta')
    antes = auditoria.instantanea(usuario)
    usuario.estado = EstadoRegistro.inactivo
    await db.execute(update(Sesion).where(Sesion.usuario_id == usuario.id, Sesion.revocada_at.is_(None))
                     .values(revocada_at=func.now(), motivo_revocacion='baja_usuario'))
    await db.flush()
    await auditoria.registrar_actor(db, actor, 'usuarios.baja', request, tenant_id=usuario.tenant_id,
                                    prestador_id=usuario.prestador_id, recurso_tipo='usuario',
                                    recurso_id=usuario.id, antes=antes, despues=auditoria.instantanea(usuario))
    await db.commit()
