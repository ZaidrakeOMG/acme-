"""Respaldo y restauración (§6.9.5, ACT-10.1): el guion de respaldo produce algo restaurable y el de restauración
lo verifica. P11a.

**No corre en la suite normal.** Levanta y borra bases de datos y necesita `docker compose`, así que se activa a
propósito:

    ACMA_PRUEBA_RESPALDO=1 .venv/Scripts/python -m pytest tests/test_respaldo.py -s

Es la prueba trimestral de `docs/operacion/recuperacion_desastres.md` en un comando: respalda la base de pruebas,
restaura en una base aparte y comprueba que los conteos coinciden. Sobre la base de **pruebas**, nunca producción.
"""
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
ACTIVA = os.environ.get("ACMA_PRUEBA_RESPALDO") == "1"
pytestmark = pytest.mark.skipif(
    not ACTIVA, reason="prueba de respaldo: se activa con ACMA_PRUEBA_RESPALDO=1 (levanta y borra bases)")


def _bash() -> str:
    """El `bash` de Git, no el de WSL.

    En Windows, `bash` en el PATH suele ser el lanzador de WSL, que no ve las rutas de Windows ni el docker
    del host. Se puede forzar con ACMA_BASH.
    """
    import shutil

    if os.environ.get("ACMA_BASH"):
        return os.environ["ACMA_BASH"]
    if os.name != "nt":
        return "bash"
    for ruta in ("C:/Program Files/Git/bin/bash.exe", "C:/Program Files (x86)/Git/bin/bash.exe"):
        if Path(ruta).exists():
            return ruta
    encontrado = shutil.which("bash")
    if encontrado and "system32" not in encontrado.lower():
        return encontrado
    pytest.skip("no se encontró el bash de Git; define ACMA_BASH")


def _correr(guion: str, *args: str, destino: Path) -> str:
    entorno = {
        **os.environ,
        "RESPALDO_DIR": str(destino),
        "COMPOSE_FILE": "docker-compose.yml",
        "POSTGRES_DB": "acma_test",
        "POSTGRES_SUPERUSER": os.environ.get("POSTGRES_SUPERUSER", "acma_super"),
        # Git Bash convierte las rutas que empiezan con / al pasarlas a docker; /tmp es ruta DEL CONTENEDOR.
        "MSYS2_ARG_CONV_EXCL": "/tmp",
    }
    r = subprocess.run([_bash(), f"scripts/{guion}", *args], cwd=RAIZ, env=entorno,
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1800)
    salida = (r.stdout or "") + (r.stderr or "")
    print(salida)
    assert r.returncode == 0, f"{guion} falló:\n{salida}"
    return salida


def test_respaldo_y_restauracion_de_la_base_de_pruebas(tmp_path, datos):
    """El ciclo completo: respaldar, restaurar en otra base y que los conteos cuadren."""
    # `datos` garantiza que la base de pruebas tenga el seed aplicado y, por tanto, algo que contar.
    destino = tmp_path / "respaldos"

    salida = _correr("respaldo.sh", "--solo-base", destino=destino)
    assert "dump válido" in salida, "el respaldo debe verificarse a sí mismo"
    dumps = sorted((destino / "diario").glob("acma_*.dump"))
    assert len(dumps) == 1, f"se esperaba un dump, hay {len(dumps)}"
    dump = dumps[0]
    assert dump.stat().st_size > 100_000, "un dump de la base de pruebas no puede ser tan chico"

    # El registro de conteos acompaña al dump: es lo que hace verificable la restauración.
    registro = dump.with_suffix(".txt").read_text(encoding="utf-8")
    tablas = dict(l.split(",") for l in registro.splitlines() if "," in l)
    assert int(tablas["folios"]) > 0 and int(tablas["usuarios"]) > 0, tablas

    base_ensayo = "acma_prueba_respaldo_pytest"
    try:
        salida = _correr("restaurar.sh", str(dump), "--base", base_ensayo, destino=destino)
        for tabla in tablas:
            assert f"{tabla}: {tablas[tabla]} ✓" in salida, f"no se cotejó {tabla}:\n{salida}"
        assert "Restauración completa" in salida
        # El esquema restaurado es el que espera la aplicación.
        version = re.search(r"Versión de esquema restaurada: (\d+)", salida)
        assert version, salida
        actual = subprocess.run([sys.executable, "-m", "alembic", "heads"], cwd=RAIZ / "backend",
                                capture_output=True, text=True, timeout=120).stdout
        assert version.group(1) in actual, f"restauró {version.group(1)} y la app espera {actual.strip()}"
    finally:
        subprocess.run(["docker", "compose", "exec", "-T", "postgres", "psql", "-U",
                        os.environ.get("POSTGRES_SUPERUSER", "acma_super"), "-d", "postgres",
                        "-c", f"DROP DATABASE IF EXISTS {base_ensayo};"], cwd=RAIZ, capture_output=True, timeout=300)
