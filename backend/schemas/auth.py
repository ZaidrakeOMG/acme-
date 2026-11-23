from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from models.base import Dominio, Rol


class LoginEntrada(BaseModel):
    email: EmailStr
    contrasena: str = Field(min_length=1, max_length=200)
    dispositivo: str | None = Field(default=None, max_length=200)


class Tokens(BaseModel):
    """P11a: el refresh token ya no viaja en el cuerpo, va en la cookie `httpOnly` `acma_refresh` (§6.9.5)."""

    access_token: str
    token_type: str = "bearer"
    expira_en: int = Field(description="Segundos de vida del token de acceso")
    sesion_expira_en: int = Field(default=0, description="Segundos restantes de sesión persistente (30 días general, 7 días administradores por defecto)")
    csrf: str = Field(default="", description="Mismo valor que la cookie `acma_csrf`; va en la cabecera X-ACMA-CSRF")


class Perfil(BaseModel):
    modulos_habilitados: list[str] | None = None
    id: UUID
    email: str
    nombre: str
    telefono: str | None = None
    rol: Rol
    dominio: Dominio
    tenant_id: UUID | None = None
    prestador_id: UUID | None = None
    mfa_habilitado: bool
    mfa_obligatorio: bool
    contrasena_vencida: bool = False


class Tema(BaseModel):
    color_primario: str
    color_acento: str
    prestador: str | None = None


class PerfilConTema(Perfil):
    tema: Tema


class LoginSalida(BaseModel):
    mfa_requerido: bool = False
    mfa_enrolamiento_requerido: bool = False
    token_mfa: str | None = Field(default=None, description="Token temporal (5 min) para el paso de MFA")
    tokens: Tokens | None = None
    usuario: Perfil | None = None
    cambio_contrasena_requerido: bool = Field(default=False, description="§6.9.5: contraseña vencida (90 días)")


class MfaTokenOpcional(BaseModel):
    token_mfa: str | None = Field(default=None, description="Token temporal del login; omítelo si ya tienes sesión")


class MfaVerificarEntrada(MfaTokenOpcional):
    codigo: str = Field(min_length=6, max_length=20, description="Código TOTP de 6 dígitos o código de recuperación")


class MfaCodigoEntrada(BaseModel):
    codigo: str = Field(min_length=6, max_length=20)


class MfaSetupSalida(BaseModel):
    secreto: str
    uri: str
    qr_svg: str = Field(description="QR en data URI SVG para escanear con la app autenticadora")


class MfaVerificarSalida(BaseModel):
    tokens: Tokens | None = None
    usuario: Perfil | None = None
    codigos_recuperacion: list[str] | None = Field(default=None, description="Se muestran una sola vez")
    cambio_contrasena_requerido: bool = False


class CodigosRecuperacion(BaseModel):
    codigos_recuperacion: list[str]


class CambioContrasena(BaseModel):
    actual: str = Field(min_length=1, max_length=200)
    nueva: str = Field(min_length=10, max_length=200)


class RestablecerSolicitud(BaseModel):
    email: EmailStr


class RestablecerConfirmacion(BaseModel):
    token: str = Field(min_length=20, max_length=400)
    nueva: str = Field(min_length=10, max_length=200)
