"""Primitivas de seguridad: contraseñas (argon2), JWT, cifrado AES-256-GCM, TOTP y tokens opacos."""
import asyncio
import base64
import hashlib
import hmac
import re
import secrets
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pyotp
import segno
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

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


# argon2 es memory-hard a propósito: cada hash o verificación cuesta ~110 ms de CPU con 4 hilos. Dentro del event loop
# eso bloquea TODAS las peticiones del proceso (medido en P11a: con 70 usuarios el login tardaba segundos y arrastraba
# al resto), así que va en un hilo aparte y con tope de concurrencia para que una tanda de logins no se coma la CPU.
# Los parámetros se dejan en el default de argon2-cffi (t=3, m=64 MiB, p=4), más fuertes que el mínimo de OWASP.
_turnos_hash: asyncio.Semaphore | None = None


def _turno() -> asyncio.Semaphore:
    global _turnos_hash
    if _turnos_hash is None:  # se crea en el loop que lo usa
        _turnos_hash = asyncio.Semaphore(max(1, config.hash_concurrencia))
    return _turnos_hash


async def hashear_contrasena_async(contrasena: str) -> str:
    async with _turno():
        return await asyncio.to_thread(hashear_contrasena, contrasena)


async def verificar_contrasena_async(hash_: str, contrasena: str) -> bool:
    async with _turno():
        return await asyncio.to_thread(verificar_contrasena, hash_, contrasena)


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


# ------------------- cifrado de archivos con llave por tenant (§6.9.5, dis. 2.5 «llaves por tenant»)

# Sobre: ACMA1 | version | largo del dueño | dueño | nonce(12) | AES-256-GCM(datos). El dueño viaja en claro porque
# es solo un identificador de la llave (nunca un dato del negocio) y porque así la lectura no necesita saber de quién
# era el archivo: deriva la llave de lo que trae el sobre y no puede equivocarse.
SOBRE_MAGIA = b"ACMA1"
SOBRE_VERSION = 1
DUENO_PLATAFORMA = "plataforma"


def clave_por_dueno(dueno: str) -> bytes:
    """Llave AES-256 derivada de la llave maestra para ese dueño (tenant, prestador o la plataforma).

    HKDF-SHA256 con la llave maestra como IKM: dos dueños nunca comparten llave y la maestra no se usa directamente,
    así que comprometer el archivo de un cliente no abre los de los demás.
    """
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=b"acma.archivos.v1",
                info=f"dueno={dueno}".encode()).derive(_clave())


def cifrar_archivo(datos: bytes, *, clave_objeto: str, dueno: str | None) -> bytes:
    """Cifra el contenido de un objeto del almacenamiento. `clave_objeto` se liga como datos autenticados."""
    duenio = (dueno or DUENO_PLATAFORMA).encode()
    if len(duenio) > 255:
        raise ValueError("Identificador de dueño demasiado largo")
    nonce = secrets.token_bytes(12)
    cuerpo = AESGCM(clave_por_dueno(duenio.decode())).encrypt(nonce, datos, clave_objeto.encode())
    return SOBRE_MAGIA + bytes([SOBRE_VERSION, len(duenio)]) + duenio + nonce + cuerpo


def descifrar_archivo(blob: bytes, *, clave_objeto: str) -> bytes:
    """Descifra lo que devuelve el almacenamiento. Lo que no trae sobre se devuelve tal cual.

    Esa tolerancia es para los archivos escritos antes de P11a: siguen legibles y se vuelven a guardar cifrados
    cuando el flujo los regenera.
    """
    if not blob.startswith(SOBRE_MAGIA) or len(blob) < len(SOBRE_MAGIA) + 2:
        return blob
    version, largo = blob[len(SOBRE_MAGIA)], blob[len(SOBRE_MAGIA) + 1]
    if version != SOBRE_VERSION:
        raise ValueError(f"Sobre de cifrado version {version} desconocido")
    inicio = len(SOBRE_MAGIA) + 2
    dueno = blob[inicio:inicio + largo].decode()
    nonce = blob[inicio + largo:inicio + largo + 12]
    return AESGCM(clave_por_dueno(dueno)).decrypt(nonce, blob[inicio + largo + 12:], clave_objeto.encode())


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


def paso_totp_valido(secreto: str, codigo: str, ventana: int = 1) -> int | None:
    """Paso de 30 s con el que coincide el código, o None. Permite rechazar la reutilización del mismo paso (§6.9.5)."""
    totp = pyotp.TOTP(secreto)
    ahora = int(time.time())
    limpio = codigo.strip()
    for desfase in range(-ventana, ventana + 1):
        momento = ahora + desfase * totp.interval
        if hmac.compare_digest(totp.at(momento), limpio):
            return momento // totp.interval
    return None


def nuevos_codigos_recuperacion(cantidad: int = 10) -> list[str]:
    return [f"{secrets.token_hex(4)}-{secrets.token_hex(4)}" for _ in range(cantidad)]


def hash_codigo_recuperacion(codigo: str) -> str:
    normalizado = codigo.strip().lower().replace(" ", "")
    return hmac.new(_clave(), normalizado.encode(), hashlib.sha256).hexdigest()
