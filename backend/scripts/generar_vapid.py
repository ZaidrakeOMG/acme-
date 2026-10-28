"""Genera un par de claves VAPID para el push PWA (web-push) y lo imprime para pegarlo en .env.

  backend\\.venv\\Scripts\\python -m scripts.generar_vapid
"""
import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


def generar() -> tuple[str, str]:
    privada = ec.generate_private_key(ec.SECP256R1())
    numero = privada.private_numbers().private_value.to_bytes(32, "big")
    publica = privada.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()  # noqa: E731
    return b64(publica), b64(numero)


if __name__ == "__main__":
    publica, privada = generar()
    print(f"VAPID_CLAVE_PUBLICA={publica}")
    print(f"VAPID_CLAVE_PRIVADA={privada}")
