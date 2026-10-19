"""Autenticación: login en dos pasos con MFA, refresh rotativo, logout y perfil."""
import uuid

from fastapi import APIRouter, Request

from core.dependencias import DB, ActorActual
from core.errors import no_autenticado
from models.usuarios import Usuario
from schemas.auth import (
    CambioContrasena, CodigosRecuperacion, LoginEntrada, LoginSalida, MfaCodigoEntrada, MfaSetupSalida,
    MfaTokenOpcional, MfaVerificarEntrada, MfaVerificarSalida, PerfilConTema, RefreshEntrada, Tokens,
)
from schemas.comun import RESPUESTAS_ERROR, Mensaje
from services import auth_service as svc

router = APIRouter(prefix="/api/auth", tags=["Autenticación"], responses=RESPUESTAS_ERROR)


async def _usuario_mfa(db, request: Request, token_mfa: str | None) -> Usuario:
    """Para setup de MFA: vale el token temporal del login o una sesión iniciada."""
    if token_mfa:
        usuario, _ = await svc.usuario_desde_token_mfa(db, token_mfa)
        return usuario
    claims = getattr(request.state, "claims", None)
    if not claims:
        raise no_autenticado()
    usuario = await svc.cargar_como_usuario(db, uuid.UUID(claims["sub"]))
    if usuario is None:
        raise no_autenticado()
    return usuario


@router.post("/login", response_model=LoginSalida, summary="Iniciar sesión",
             description="Valida correo y contraseña. Si el rol exige MFA (superadmin, admin_prestador, admin_empresa, "
                         "direccion_prestador) o el usuario lo tiene activo, devuelve `token_mfa` y debe completarse con "
                         "`POST /api/auth/mfa/verify`. Aplica límite por IP y bloqueo temporal por usuario.")
async def login(datos: LoginEntrada, request: Request, db: DB) -> LoginSalida:
    r = await svc.login(db, request, datos.email, datos.contrasena, datos.dispositivo)
    if r.token_mfa:
        return LoginSalida(mfa_requerido=True, mfa_enrolamiento_requerido=r.mfa_enrolamiento_requerido, token_mfa=r.token_mfa)
    return LoginSalida(tokens=Tokens(**r.tokens), usuario=svc.perfil(r.usuario))


@router.post("/refresh", response_model=Tokens, summary="Renovar tokens",
             description="Rota el refresh token (7 días) y emite un nuevo token de acceso (15 min). Presentar un refresh "
                         "ya usado invalida toda la familia de sesiones (detección de reúso).")
async def refresh(datos: RefreshEntrada, request: Request, db: DB) -> Tokens:
    _, tokens = await svc.refrescar(db, request, datos.refresh_token)
    return Tokens(**tokens)


@router.post("/logout", response_model=Mensaje, summary="Cerrar sesión", description="Revoca la sesión actual y su familia de refresh tokens.")
async def logout(actor: ActorActual, request: Request, db: DB) -> Mensaje:
    await svc.cerrar_sesion(db, request, actor)
    return Mensaje(mensaje="Sesión cerrada")


@router.get("/yo", response_model=PerfilConTema, summary="Perfil del usuario actual",
            description="Datos del usuario autenticado y colores de su prestador.")
async def yo(actor: ActorActual, db: DB) -> PerfilConTema:
    usuario = await db.get(Usuario, actor.id)
    return PerfilConTema(**svc.perfil(usuario), tema=await svc.tema_del_usuario(db, usuario))


@router.post("/cambiar-contrasena", response_model=Mensaje, summary="Cambiar contraseña",
             description="Mínimo 10 caracteres con mayúscula, minúscula, número y símbolo; no repite las últimas 10.")
async def cambiar_contrasena(datos: CambioContrasena, actor: ActorActual, request: Request, db: DB) -> Mensaje:
    usuario = await db.get(Usuario, actor.id)
    await svc.cambiar_contrasena(db, request, usuario, datos.actual, datos.nueva)
    return Mensaje(mensaje="Contraseña actualizada")


@router.post("/mfa/setup", response_model=MfaSetupSalida, summary="Configurar MFA (QR TOTP)",
             description="Genera un secreto TOTP y su QR. Acepta el `token_mfa` del login (enrolamiento obligatorio) "
                         "o una sesión iniciada (enrolamiento voluntario). Se activa al verificar el primer código.")
async def mfa_setup(datos: MfaTokenOpcional, request: Request, db: DB) -> MfaSetupSalida:
    usuario = await _usuario_mfa(db, request, datos.token_mfa)
    return MfaSetupSalida(**await svc.configurar_mfa(db, request, usuario))


@router.post("/mfa/verify", response_model=MfaVerificarSalida, summary="Verificar código MFA",
             description="Con `token_mfa`: segundo paso del login (acepta TOTP o código de recuperación) y emite la sesión; "
                         "si el usuario estaba enrolando, activa el MFA y devuelve 10 códigos de recuperación. "
                         "Sin `token_mfa` y con sesión: activa el MFA configurado.")
async def mfa_verify(datos: MfaVerificarEntrada, request: Request, db: DB) -> MfaVerificarSalida:
    if datos.token_mfa:
        usuario, tokens, codigos = await svc.verificar_mfa_login(db, request, datos.token_mfa, datos.codigo)
        return MfaVerificarSalida(tokens=Tokens(**tokens), usuario=svc.perfil(usuario), codigos_recuperacion=codigos)
    usuario = await _usuario_mfa(db, request, None)
    codigos = await svc.activar_mfa_autenticado(db, request, usuario, datos.codigo)
    return MfaVerificarSalida(usuario=svc.perfil(usuario), codigos_recuperacion=codigos)


@router.post("/mfa/disable", response_model=Mensaje, summary="Deshabilitar MFA",
             description="Requiere un código TOTP válido. No permitido para roles con MFA obligatorio.")
async def mfa_disable(datos: MfaCodigoEntrada, actor: ActorActual, request: Request, db: DB) -> Mensaje:
    usuario = await db.get(Usuario, actor.id)
    await svc.deshabilitar_mfa(db, request, usuario, datos.codigo)
    return Mensaje(mensaje="MFA deshabilitado")


@router.post("/mfa/codigos-recuperacion", response_model=CodigosRecuperacion, summary="Regenerar códigos de recuperación",
             description="Invalida los códigos anteriores y emite 10 nuevos. Requiere un código TOTP válido.")
async def mfa_regenerar(datos: MfaCodigoEntrada, actor: ActorActual, request: Request, db: DB) -> CodigosRecuperacion:
    usuario = await db.get(Usuario, actor.id)
    return CodigosRecuperacion(codigos_recuperacion=await svc.regenerar_codigos(db, request, usuario, datos.codigo))
