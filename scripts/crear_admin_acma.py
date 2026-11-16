"""Repetir SOLO el seed inicial de ACMA si el asistente se interrumpió.

No genera ningún usuario ni contraseña prefijada en el repositorio.
Reutiliza seed_produccion: también crea las plantillas base de formularios.
"""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    if not (ROOT / ".env").is_file():
        raise RuntimeError("Primero configura .env con PROBAR_ACMA_WEB.bat")
    email = input("Correo REAL para el superadmin: ").strip().lower()
    nombre = input("Nombre del superadmin: ").strip()
    if not email or not nombre:
        raise ValueError("Correo y nombre son obligatorios")
    print("Crear administrador y catálogos sin datos de demostración.")
    result = subprocess.run(
        [sys.executable, "-m", "scripts.seed_produccion",
         "--email", email, "--nombre", nombre],
        cwd=ROOT / "backend",
        check=False,
    )
    if result.returncode:
        raise RuntimeError("No se completó la creación; revisa el error mostrado.")


if __name__ == "__main__":
    try:
        main()
    except (Exception, KeyboardInterrupt) as exc:
        print(f"ERROR ACMA: {exc}", file=sys.stderr)
        sys.exit(1)
