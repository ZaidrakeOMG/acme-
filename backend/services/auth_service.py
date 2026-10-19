"""Autenticación: login, MFA TOTP, sesiones con refresh rotativo y detección de reúso."""
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import Request
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from core import security
from core.config import config
from core.errors import ErrorAPI, no_autenticado
from core.middleware import ip_cliente
from core.rls import ContextoRLS, fijar_contexto
from models.base import ROLES_MFA_OBLIGATORIO, EstadoRegistro
from models.organizaciones import Prestador, TenantPrestador
from models.usuarios import HistorialContrasena, Sesion, Usuario
from services import auditoria

CREDENCIALES_INVALIDAS = ErrorAPI(401, "CREDENCIALES_INVALIDAS", "Correo o contraseña incorrectos")


@dataclass
class ResultadoLogin:
    usuario: Usuario | None = None
    tokens: dict | None = None
    token_mfa: str | None = None
    mfa_enrolamiento_requerido: bool = False


def contexto_de(usuario_id: uuid.UUID, rol: str, tenant_id: uuid.UUID | None, prestador_id: uuid.UUID | None) -> ContextoRLS:
    return ContextoRLS(usuario_id=usuario_id, tenant_id=tenant_id, prestador_id=prestador_id, rol=str(rol))


async def _identidad(db: AsyncSession, *, email: str | None = None, usuario_id: uuid.UUID | None = None):
    if email is not None:
        fila = (await db.execute(text("SELECT * FROM auth_identidad_por_email(:e)"), {"e": email})).first()
    else:
        fila = (await db.execute(text("SELECT * FROM auth_identidad_por_id(:i)"), {"i": usuario_id})).first()
    return fila


async def cargar_como_usuario(db: AsyncSession, usuario_id: uuid.UUID) -> Usuario | None:
    """Fija el contexto RLS del propio usuario y lo carga (bootstrap sin contexto previo)."""
    fila = await _identidad(db, usuario_id=usuario_id)
    if fila is None:
        return None
    await fijar_contexto(db, contexto_de(fila.id, fila.rol, fila.tenant_id, fila.prestador_id))
    return await db.get(Usuario, fila.id)


def requiere_mfa(usuario: Usuario) -> bool:
    return usuario.mfa_habilitado or (config.mfa_obligatorio and usuario.rol in ROLES_MFA_OBLIGATORIO)


async def _auditar(db: AsyncSession, evento: str, request: Request, usuario: Usuario | None = None, **datos) -> None:
    await auditoria.registrar(
        db, evento,
        actor_id=usuario.id if usuario else None,
        actor_rol=usuario.rol.value if usuario else None,
        tenant_id=usuario.tenant_id if usuario else None,
        prestador_id=usuario.prestador_id if usuario else None,
        recurso_tipo="usuario", recurso_id=usuario.id if usuario else None,
        despues=datos or None, request=request,
    )


async def _registrar_fallo(db: AsyncSession, request: Request, email: str, usuario: Usuario | None, motivo: str) -> None:
    await db.execute(
        text("SELECT auth_registrar_intento_fallido(:ip, :e, :u)"),
        {"ip": ip_cliente(request), "e": email[:254], "u": usuario.id if usuario else None},
    )
    if usuario is not None:
        usuario.intentos_fallidos += 1
        if usuario.intentos_fallidos >= config.login_max_intentos:
            usuario.bloqueado_hasta = datetime.now(UTC) + timedelta(minutes=config.login_bloqueo_minutos)
            usuario.intentos_fallidos = 0
            await _auditar(db, "auth.usuario_bloqueado", request, usuario, minutos=config.login_bloqueo_minutos)
    await _auditar(db, "auth.login_fallido", request, usuario, email=email, motivo=motivo)
    await db.commit()


async def _verificar_limite_ip(db: AsyncSession, request: Request) -> None:
    fallos = (await db.execute(
        text("SELECT auth_fallos_recientes_ip(:ip, :m)"),
        {"ip": ip_cliente(request), "m": config.login_ventana_minutos},
    )).scalar_one()
    if fallos >= config.login_max_intentos:
        await _auditar(db, "auth.limite_ip", request, None, ip=ip_cliente(request), fallos=fallos)
        await db.commit()
        raise ErrorAPI(429, "DEMASIADOS_INTENTOS",
                       f"Demasiados intentos fallidos desde esta IP. Intenta en {config.login_ventana_minutos} minutos.",
                       cabeceras={"Retry-After": str(config.login_ventana_minutos * 60)})


def _verificar_bloqueo(usuario: Usuario) -> None:
    if usuario.bloqueado_hasta and usuario.bloqueado_hasta > datetime.now(UTC):
        restantes = int((usuario.bloqueado_hasta - datetime.now(UTC)).total_seconds() // 60) + 1
        raise ErrorAPI(423, "USUARIO_BLOQUEADO",
                       f"Usuario bloqueado temporalmente por intentos fallidos. Intenta en {restantes} minutos.")


async def login(db: AsyncSession, request: Request, email: str, contrasena: str, dispositivo: str | None) -> ResultadoLogin:
    await _verificar_limite_ip(db, request)
    fila = await _identidad(db, email=email)
    if fila is None:
        security.verificar_contrasena(security.HASH_FICTICIO, contrasena)
        await _registrar_fallo(db, request, email, None, "email_inexistente")
        raise CREDENCIALES_INVALIDAS

    await fijar_contexto(db, contexto_de(fila.id, fila.rol, fila.tenant_id, fila.prestador_id))
    usuario = await db.get(Usuario, fila.id)
    assert usuario is not None
    _verificar_bloqueo(usuario)

    if not security.verificar_contrasena(usuario.password_hash, contrasena):
        await _registrar_fallo(db, request, email, usuario, "contrasena_incorrecta")
        raise CREDENCIALES_INVALIDAS
    if usuario.estado != EstadoRegistro.activo:
        await _registrar_fallo(db, request, email, usuario, "usuario_inactivo")
        raise CREDENCIALES_INVALIDAS

    usuario.intentos_fallidos = 0
    usuario.bloqueado_hasta = None

    if requiere_mfa(usuario):
        enrolar = not usuario.mfa_habilitado
        token_mfa = security.crear_jwt(
            {"sub": str(usuario.id), "proposito": "enrolar" if enrolar else "verificar", "dispositivo": dispositivo},
            security.TIPO_MFA, config.jwt_mfa_minutos,
        )
        await _auditar(db, "auth.login_mfa_pendiente", request, usuario, enrolamiento=enrolar)
        await db.commit()
        return ResultadoLogin(usuario=usuario, token_mfa=token_mfa, mfa_enrolamiento_requerido=enrolar)

    tokens = await crear_sesion(db, request, usuario, dispositivo)
    await _auditar(db, "auth.login_exitoso", request, usuario, mfa=False)
    await db.commit()
    return ResultadoLogin(usuario=usuario, tokens=tokens)


# ----------------------------------------------------------------- sesiones

def _token_acceso(usuario: Usuario, sesion_id: uuid.UUID) -> str:
    return security.crear_jwt(
        {
            "sub": str(usuario.id),
            "rol": usuario.rol.value,
            "dominio": usuario.dominio.value,
            "tenant_id": str(usuario.tenant_id) if usuario.tenant_id else None,
            "prestador_id": str(usuario.prestador_id) if usuario.prestador_id else None,
            "sid": str(sesion_id),
        },
        security.TIPO_ACCESO,
        config.jwt_acceso_minutos,
    )


async def crear_sesion(db: AsyncSession, request: Request, usuario: Usuario, dispositivo: str | None,
                       familia_id: uuid.UUID | None = None, padre_id: uuid.UUID | None = None) -> dict:
    refresh = security.nuevo_token_opaco()
    sesion = Sesion(
        id=uuid.uuid4(),
        usuario_id=usuario.id,
        familia_id=familia_id or uuid.uuid4(),
        padre_id=padre_id,
        token_hash=security.hash_token(refresh),
        dispositivo=(dispositivo or "")[:200] or None,
        user_agent=(request.headers.get("user-agent") or "")[:500],
        ip_origen=ip_cliente(request),
        expira_at=datetime.now(UTC) + timedelta(days=config.refresh_dias),
    )
    db.add(sesion)
    usuario.ultimo_acceso_at = datetime.now(UTC)
    await db.flush()
    return {
        "access_token": _token_acceso(usuario, sesion.id),
        "refresh_token": refresh,
        "token_type": "bearer",
        "expira_en": config.jwt_acceso_minutos * 60,
    }


async def _revocar_familia(db: AsyncSession, familia_id: uuid.UUID, motivo: str) -> None:
    await db.execute(
        update(Sesion)
        .where(Sesion.familia_id == familia_id, Sesion.revocada_at.is_(None))
        .values(revocada_at=func.now(), motivo_revocacion=motivo)
    )


async def refrescar(db: AsyncSession, request: Request, refresh_token: str) -> tuple[Usuario, dict]:
    token_hash = security.hash_token(refresh_token)
    usuario_id = (await db.execute(text("SELECT auth_usuario_de_sesion(:h)"), {"h": token_hash})).scalar_one_or_none()
    if usuario_id is None:
        raise no_autenticado("Refresh token inválido")
    usuario = await cargar_como_usuario(db, usuario_id)
    if usuario is None:
        raise no_autenticado("Refresh token inválido")

    sesion = (await db.execute(select(Sesion).where(Sesion.token_hash == token_hash).with_for_update())).scalar_one()
    if sesion.rotada_at is not None or sesion.revocada_at is not None:
        # Reúso de un refresh ya rotado o revocado: posible robo. Se invalida toda la familia.
        await _revocar_familia(db, sesion.familia_id, "reuso_detectado")
        await _auditar(db, "auth.refresh_reuso_detectado", request, usuario, familia_id=str(sesion.familia_id))
        await db.commit()
        raise ErrorAPI(401, "TOKEN_REUTILIZADO", "Se detectó reúso del token de sesión; todas las sesiones de este acceso fueron cerradas")
    if sesion.expira_at <= datetime.now(UTC):
        raise no_autenticado("La sesión expiró; inicia sesión de nuevo")
    if usuario.estado != EstadoRegistro.activo:
        await _revocar_familia(db, sesion.familia_id, "usuario_inactivo")
        await db.commit()
        raise no_autenticado("Usuario inactivo")

    sesion.rotada_at = datetime.now(UTC)
    sesion.ultimo_acceso_at = datetime.now(UTC)
    tokens = await crear_sesion(db, request, usuario, sesion.dispositivo, familia_id=sesion.familia_id, padre_id=sesion.id)
    await db.commit()
    return usuario, tokens


async def cerrar_sesion(db: AsyncSession, request: Request, actor) -> None:
    if actor.sesion_id:
        sesion = await db.get(Sesion, actor.sesion_id)
        if sesion:
            await _revocar_familia(db, sesion.familia_id, "logout")
    await auditoria.registrar_actor(db, actor, "auth.logout", request, recurso_tipo="usuario", recurso_id=actor.id)
    await db.commit()


# ----------------------------------------------------------------------- MFA

async def usuario_desde_token_mfa(db: AsyncSession, token_mfa: str) -> tuple[Usuario, dict]:
    try:
        claims = security.decodificar_jwt(token_mfa, security.TIPO_MFA)
    except jwt.PyJWTError:
        raise ErrorAPI(401, "TOKEN_MFA_INVALIDO", "El token de verificación MFA es inválido o expiró; inicia sesión de nuevo")
    usuario = await cargar_como_usuario(db, uuid.UUID(claims["sub"]))
    if usuario is None or usuario.estado != EstadoRegistro.activo:
        raise ErrorAPI(401, "TOKEN_MFA_INVALIDO", "Usuario inválido")
    return usuario, claims


async def configurar_mfa(db: AsyncSession, request: Request, usuario: Usuario) -> dict:
    if usuario.mfa_habilitado:
        raise ErrorAPI(409, "MFA_YA_HABILITADO", "El MFA ya está habilitado; deshabilítalo antes de reconfigurarlo")
    secreto = security.nuevo_secreto_totp()
    usuario.mfa_secreto_cifrado = security.cifrar(secreto)
    uri = security.uri_totp(secreto, usuario.email)
    await _auditar(db, "auth.mfa_setup", request, usuario)
    await db.commit()
    return {"secreto": secreto, "uri": uri, "qr_svg": security.qr_svg_data_uri(uri)}


def _codigo_totp_valido(usuario: Usuario, codigo: str) -> bool:
    if not usuario.mfa_secreto_cifrado:
        return False
    return security.verificar_totp(security.descifrar(usuario.mfa_secreto_cifrado), codigo)


def _consumir_codigo_recuperacion(usuario: Usuario, codigo: str) -> bool:
    h = security.hash_codigo_recuperacion(codigo)
    if h in (usuario.mfa_codigos_recuperacion or []):
        usuario.mfa_codigos_recuperacion = [c for c in usuario.mfa_codigos_recuperacion if c != h]
        return True
    return False


def _emitir_codigos(usuario: Usuario) -> list[str]:
    codigos = security.nuevos_codigos_recuperacion()
    usuario.mfa_codigos_recuperacion = [security.hash_codigo_recuperacion(c) for c in codigos]
    return codigos


async def _fallo_mfa(db: AsyncSession, request: Request, usuario: Usuario) -> None:
    await _registrar_fallo(db, request, usuario.email, usuario, "codigo_mfa_invalido")
    raise ErrorAPI(401, "CODIGO_MFA_INVALIDO", "Código de verificación incorrecto")


async def verificar_mfa_login(db: AsyncSession, request: Request, token_mfa: str, codigo: str) -> tuple[Usuario, dict, list[str] | None]:
    """Segundo paso del login. Si el usuario estaba enrolando, activa el MFA y devuelve códigos de recuperación."""
    usuario, claims = await usuario_desde_token_mfa(db, token_mfa)
    _verificar_bloqueo(usuario)
    codigos: list[str] | None = None
    if usuario.mfa_habilitado:
        if not (_codigo_totp_valido(usuario, codigo) or _consumir_codigo_recuperacion(usuario, codigo)):
            await _fallo_mfa(db, request, usuario)
    else:
        if not usuario.mfa_secreto_cifrado:
            raise ErrorAPI(409, "MFA_SIN_CONFIGURAR", "Primero configura el MFA (POST /api/auth/mfa/setup)")
        if not _codigo_totp_valido(usuario, codigo):
            await _fallo_mfa(db, request, usuario)
        usuario.mfa_habilitado = True
        codigos = _emitir_codigos(usuario)
        await _auditar(db, "auth.mfa_habilitado", request, usuario)
    usuario.intentos_fallidos = 0
    tokens = await crear_sesion(db, request, usuario, claims.get("dispositivo"))
    await _auditar(db, "auth.login_exitoso", request, usuario, mfa=True)
    await db.commit()
    return usuario, tokens, codigos


async def activar_mfa_autenticado(db: AsyncSession, request: Request, usuario: Usuario, codigo: str) -> list[str]:
    """Enrolamiento voluntario desde una sesión ya iniciada."""
    if usuario.mfa_habilitado:
        raise ErrorAPI(409, "MFA_YA_HABILITADO", "El MFA ya está habilitado")
    if not usuario.mfa_secreto_cifrado:
        raise ErrorAPI(409, "MFA_SIN_CONFIGURAR", "Primero configura el MFA (POST /api/auth/mfa/setup)")
    if not _codigo_totp_valido(usuario, codigo):
        await _fallo_mfa(db, request, usuario)
    usuario.mfa_habilitado = True
    codigos = _emitir_codigos(usuario)
    await _auditar(db, "auth.mfa_habilitado", request, usuario)
    await db.commit()
    return codigos


async def deshabilitar_mfa(db: AsyncSession, request: Request, usuario: Usuario, codigo: str) -> None:
    if config.mfa_obligatorio and usuario.rol in ROLES_MFA_OBLIGATORIO:
        raise ErrorAPI(403, "MFA_OBLIGATORIO", "Tu rol requiere MFA; no puede deshabilitarse")
    if not usuario.mfa_habilitado:
        raise ErrorAPI(409, "MFA_NO_HABILITADO", "El MFA no está habilitado")
    if not _codigo_totp_valido(usuario, codigo):
        await _fallo_mfa(db, request, usuario)
    usuario.mfa_habilitado = False
    usuario.mfa_secreto_cifrado = None
    usuario.mfa_codigos_recuperacion = []
    await _auditar(db, "auth.mfa_deshabilitado", request, usuario)
    await db.commit()


async def regenerar_codigos(db: AsyncSession, request: Request, usuario: Usuario, codigo: str) -> list[str]:
    if not usuario.mfa_habilitado:
        raise ErrorAPI(409, "MFA_NO_HABILITADO", "El MFA no está habilitado")
    if not _codigo_totp_valido(usuario, codigo):
        await _fallo_mfa(db, request, usuario)
    codigos = _emitir_codigos(usuario)
    await _auditar(db, "auth.mfa_codigos_regenerados", request, usuario)
    await db.commit()
    return codigos


# ------------------------------------------------------------- contraseñas

HISTORIAL_CONTRASENAS = 10


async def cambiar_contrasena(db: AsyncSession, request: Request, usuario: Usuario, actual: str, nueva: str) -> None:
    if not security.verificar_contrasena(usuario.password_hash, actual):
        raise ErrorAPI(400, "CONTRASENA_ACTUAL_INCORRECTA", "La contraseña actual es incorrecta")
    errores = security.errores_politica_contrasena(nueva)
    if errores:
        raise ErrorAPI(422, "POLITICA_CONTRASENA", "La contraseña no cumple la política", errores)
    previas = (await db.execute(
        select(HistorialContrasena.password_hash).where(HistorialContrasena.usuario_id == usuario.id)
        .order_by(HistorialContrasena.created_at.desc()).limit(HISTORIAL_CONTRASENAS - 1)
    )).scalars().all()
    if any(security.verificar_contrasena(h, nueva) for h in [usuario.password_hash, *previas]):
        raise ErrorAPI(422, "CONTRASENA_REPETIDA", f"No puedes reutilizar ninguna de tus últimas {HISTORIAL_CONTRASENAS} contraseñas")
    db.add(HistorialContrasena(usuario_id=usuario.id, password_hash=usuario.password_hash))
    usuario.password_hash = security.hashear_contrasena(nueva)
    usuario.password_actualizado_at = datetime.now(UTC)
    await _auditar(db, "auth.contrasena_cambiada", request, usuario)
    await db.commit()


# ------------------------------------------------------------------ perfil

async def tema_del_usuario(db: AsyncSession, usuario: Usuario) -> dict:
    """Color primario configurable por prestador (§ identidad visual)."""
    prestador_id = usuario.prestador_id
    if prestador_id is None and usuario.tenant_id is not None:
        prestador_id = (await db.execute(
            select(TenantPrestador.prestador_id).where(
                TenantPrestador.tenant_id == usuario.tenant_id, TenantPrestador.estado == EstadoRegistro.activo
            ).order_by(TenantPrestador.vigencia_inicio).limit(1)
        )).scalar_one_or_none()
    if prestador_id:
        p = await db.get(Prestador, prestador_id)
        if p:
            return {"color_primario": p.color_primario, "color_acento": p.color_acento, "prestador": p.razon_social}
    return {"color_primario": "#1C3D8F", "color_acento": "#A2C62B", "prestador": None}


def perfil(usuario: Usuario) -> dict:
    return {
        "id": usuario.id, "email": usuario.email, "nombre": usuario.nombre, "telefono": usuario.telefono,
        "rol": usuario.rol, "dominio": usuario.dominio, "tenant_id": usuario.tenant_id,
        "prestador_id": usuario.prestador_id, "mfa_habilitado": usuario.mfa_habilitado,
        "mfa_obligatorio": config.mfa_obligatorio and usuario.rol in ROLES_MFA_OBLIGATORIO,
    }

