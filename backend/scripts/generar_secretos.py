"""Genera JWT_SECRETO y CLAVE_CIFRADO (AES-256) para copiar al .env.

Ejecutar desde backend/:  .venv\\Scripts\\python -m scripts.generar_secretos
"""
import base64
import secrets

if __name__ == "__main__":
    print(f"JWT_SECRETO={secrets.token_urlsafe(48)}")
    print(f"CLAVE_CIFRADO={base64.b64encode(secrets.token_bytes(32)).decode()}")
    print("\nCambiar CLAVE_CIFRADO con datos existentes vuelve ilegibles los secretos MFA y datos fiscales ya guardados.")
