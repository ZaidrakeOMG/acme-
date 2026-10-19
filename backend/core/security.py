"""Primitivas de seguridad: contraseñas (argon2), JWT, cifrado AES-256-GCM, TOTP y tokens opacos."""
import base64
import hashlib
import hmac
import re
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pyotp
import segno
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from core.config import config

_hasher = PasswordHasher()

# ----------------------------------------------------------------- contraseñas

# §6.9.5: mínimo 10 caracteres con complejidad.
_REGLAS_CONTRASENA = [
    (re.compile(r".{10,}"), "al menos 10 caracteres"),
    (re.compile(r"[a-z]"), "una minúscula"),
    (re.compile(r"[A-Z]"), "una mayúscula"),
    (re.compile(r"\d"), "un número"),
    (re.compile(r"[^A-Za-z0-9]"), "un símbolo"),
]


def errores_politica_contrasena(contrasena: str) -> list[str]:
    return [f"La contraseña requiere {msg}" for patron, msg in _REGLAS_CONTRASENA if not patron.search(contrasena)]


def hashear_contrasena(contrasena: str) -> str:
    return _hasher.hash(contrasena)


def verificar_contrasena(hash_: str, contrasena: str) -> bool:
    try:
        return _hasher.verify(hash_, contrasena)
    except (VerificationError, InvalidHashError):
        return False


# Hash ficticio para igualar tiempos cuando el email no existe.
HASH_FICTICIO = _hasher.hash("contrasena-ficticia-para-tiempo-constante")

# ----------------------------------------------------------------------- JWT

TIPO_ACCESO = "acceso"
TIPO_MFA = "mfa"


def crear_jwt(datos: dict[str, Any], tipo: str, minutos: int) -> str:
    ahora = datetime.now(UTC)
    carga = {**datos, "tipo": tipo, "iat": ahora, "exp": ahora + timedelta(minutes=minutos), "jti": uuid.uuid4().hex}
    return jwt.encode(carga, config.jwt_secreto, algorithm=config.jwt_algoritmo)


def decodificar_jwt(token: str, tipo: str) -> dict[str, Any]:
    """Lanza jwt.PyJWTError si el token es inválido, expiró o no es del tipo esperado."""
    carga = jwt.decode(token, config.jwt_secreto, algorithms=[config.jwt_algoritmo])
    if carga.get("tipo") != tipo:
        raise jwt.InvalidTokenError("Tipo de token incorrecto")
    return carga


# ---------------------------------------------------------- tokens opacos

def nuevo_token_opaco() -> str:
    return secrets.token_urlsafe(48)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# --------------------------------------------- cifrado en reposo AES-256-GCM

def _clave() -> bytes:
    clave = base64.b64decode(config.clave_cifrado)
    if len(clave) != 32:
        raise RuntimeError("CLAVE_CIFRADO debe ser base64 de 32 bytes (AES-256)")
    return clave


def cifrar(texto: str) -> str:
    nonce = secrets.token_bytes(12)
    cifrado = AESGCM(_clave()).encrypt(nonce, texto.encode(), b"acma")
    return "v1:" + base64.b64encode(nonce + cifrado).decode()


def descifrar(valor: str) -> str:
    version, _, cuerpo = valor.partition(":")
    if version != "v1":
        raise ValueError("Formato de cifrado desconocido")
    datos = base64.b64decode(cuerpo)
    return AESGCM(_clave()).decrypt(datos[:12], datos[12:], b"acma").decode()


# ------------------------------------------------------------------- TOTP

EMISOR_MFA = "ACMA"


def nuevo_secreto_totp() -> str:
    return pyotp.random_base32()


def uri_totp(secreto: str, email: str) -> str:
    return pyotp.TOTP(secreto).provisioning_uri(name=email, issuer_name=EMISOR_MFA)


def qr_svg_data_uri(uri: str) -> str:
    return segno.make(uri, error="m").svg_data_uri(scale=5)


def verificar_totp(secreto: str, codigo: str) -> bool:
    return pyotp.TOTP(secreto).verify(codigo.strip(), valid_window=1)


def nuevos_codigos_recuperacion(cantidad: int = 10) -> list[str]:
    return [f"{secrets.token_hex(4)}-{secrets.token_hex(4)}" for _ in range(cantidad)]


def hash_codigo_recuperacion(codigo: str) -> str:
    normalizado = codigo.strip().lower().replace(" ", "")
    return hmac.new(_clave(), normalizado.encode(), hashlib.sha256).hexdigest()
