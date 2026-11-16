"""Inicia ACMA móvil en Android usando el FastAPI local, sin publicar secretos.

En Android (emulador o móvil por USB) adb reverse redirige
http://localhost:8000 al puerto 8000 del equipo Windows.
Esto evita usar 10.0.2.2, que no es un origen web seguro para WebView.
No altera la base Supabase ni la configuración .env.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
MOBILE = ROOT / "mobile_flutter"
SALUD = "http://127.0.0.1:8000/api/salud"
BASE_ANDROID = "http://localhost:8000"


def buscar_flutter() -> str | None:
    encontrado = shutil.which("flutter")
    if encontrado:
        return encontrado
    home = Path.home()
    alternativas = [
        home / "develop" / "flutter" / "bin" / "flutter.bat",
        home / "flutter" / "bin" / "flutter.bat",
        Path("C:/src/flutter/bin/flutter.bat"),
        Path("C:/flutter/bin/flutter.bat"),
    ]
    flutter_home = os.environ.get("FLUTTER_ROOT") or os.environ.get("FLUTTER_HOME")
    if flutter_home:
        alternativas.insert(0, Path(flutter_home) / "bin" / "flutter.bat")
    return str(next((x for x in alternativas if x.is_file()), "")) or None


def buscar_adb() -> str | None:
    encontrado = shutil.which("adb")
    if encontrado:
        return encontrado
    alternativas = []
    for env in ("ANDROID_SDK_ROOT", "ANDROID_HOME"):
        if os.environ.get(env):
            alternativas.append(Path(os.environ[env]) / "platform-tools" / "adb.exe")
    if os.environ.get("LOCALAPPDATA"):
        alternativas.append(Path(os.environ["LOCALAPPDATA"]) / "Android" / "Sdk" / "platform-tools" / "adb.exe")
    alternativas.append(Path.home() / "AppData" / "Local" / "Android" / "Sdk" / "platform-tools" / "adb.exe")
    return str(next((x for x in alternativas if x.is_file()), "")) or None


def validar_backend() -> None:
    try:
        with urlopen(SALUD, timeout=6) as respuesta:
            datos = json.load(respuesta)
        if datos.get("estado") != "ok":
            raise RuntimeError("La API respondió, pero no devolvió estado=ok.")
    except Exception as exc:
        raise RuntimeError(
            "No se encuentra ACMA Web funcionando en http://127.0.0.1:8000.\n"
            "Abre otra ventana CMD, ejecuta PROBAR_ACMA_WEB.bat y déjala ABIERTA.\n"
            "Comprueba en el navegador http://127.0.0.1:8000/api/salud."
        ) from exc


def dispositivos_android(adb: str) -> list[str]:
    resultado = subprocess.run([adb, "devices"], text=True, capture_output=True, check=True)
    return [
        partes[0] for linea in resultado.stdout.splitlines()[1:]
        if (partes := linea.split()) and len(partes) >= 2 and partes[1] == "device"
    ]


def elegir_dispositivo(ids: list[str]) -> str:
    if not ids:
        raise RuntimeError(
            "No hay emulador Android encendido ni celular conectado por USB.\n"
            "Abre Android Studio > Device Manager > Start en un emulador,\n"
            "o conecta un teléfono Android con depuración USB autorizada."
        )
    if len(ids) == 1:
        print(f"Android detectado: {ids[0]}")
        return ids[0]
    print("Dispositivos Android encontrados:")
    for num, equipo in enumerate(ids, 1):
        print(f"  {num}. {equipo}")
    elegido = input("Número del Android donde abrir ACMA: ").strip()
    if not elegido.isdigit() or not 1 <= int(elegido) <= len(ids):
        raise ValueError("Número de dispositivo inválido.")
    return ids[int(elegido) - 1]


def ejecutar(comando: list[str], cwd: Path | None = None) -> None:
    # Nunca imprimir parámetros que contengan secretos.
    resultado = subprocess.run(comando, cwd=cwd, check=False)
    if resultado.returncode:
        raise RuntimeError(f"El paso terminó con error {resultado.returncode}.")


def main() -> int:
    print("\n=====================================================")
    print("   ACMA ANDROID - FLUTTER + SUPABASE (WEBVIEW LOCAL)")
    print("=====================================================")
    print("Las pantallas son las de React original dentro de Flutter.")
    print("Supabase sigue conectado SOLO desde FastAPI. Sin claves en Android.\n")

    flutter = buscar_flutter()
    if not flutter:
        raise RuntimeError(
            "Flutter SDK no está instalado o no se encontró en PATH.\n"
            "Instálalo desde https://docs.flutter.dev/install\n"
            "Abre CMD de nuevo, verifica 'flutter doctor' y reintenta."
        )
    adb = buscar_adb()
    if not adb:
        raise RuntimeError(
            "No se encontró adb (Android SDK Platform-Tools).\n"
            "Instala Android Studio con Android SDK/Platform-Tools y crea un emulador."
        )

    print("[1/5] Revisando FastAPI de ACMA y Supabase...")
    validar_backend()
    print("Servidor ACMA disponible en 127.0.0.1:8000.")

    print("[2/5] Buscando un emulador Android o teléfono por USB...")
    dispositivo = elegir_dispositivo(dispositivos_android(adb))

    print("[3/5] Generando únicamente las carpetas Android faltantes...")
    if not (MOBILE / "android" / "app" / "src" / "main" / "AndroidManifest.xml").exists():
        ejecutar(
            [flutter, "create", "--platforms=android",
             "--project-name", "acma_mobile", "."],
            cwd=MOBILE,
        )

    # Android 9+ bloquea HTTP salvo autorización explícita. La excepción se
    # declara solo en src/debug; NO se aplica al APK/AAB de producción.
    manifiesto_debug = MOBILE / "android" / "app" / "src" / "debug" / "AndroidManifest.xml"
    if not manifiesto_debug.exists():
        raise RuntimeError(
            "Falta AndroidManifest.xml de depuración en GitHub.\n"
            "Actualiza con git pull para tener el permiso HTTP solo para debug."
        )

    print("[4/5] Instalando dependencias Flutter y enlazando Android con localhost...")
    ejecutar([flutter, "pub", "get"], cwd=MOBILE)
    ejecutar([adb, "-s", dispositivo, "reverse", "tcp:8000", "tcp:8000"])
    print("Android localhost:8000 -> ACMA Windows 127.0.0.1:8000.")

    print("\n[5/5] Iniciando aplicación ACMA en el Android seleccionado...")
    print("Puede iniciar sesión con el superadmin existente y activar MFA.")
    print("CTRL+C para detener Flutter sin borrar datos ni cerrar FastAPI.\n")
    resultado = subprocess.run(
        [flutter, "run", "-d", dispositivo, "--debug",
         f"--dart-define=ACMA_BASE_URL={BASE_ANDROID}",
         "--dart-define=ACMA_ALLOW_HTTP=true"],
        cwd=MOBILE, check=False,
    )
    return resultado.returncode


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, RuntimeError, subprocess.SubprocessError, OSError) as exc:
        print("\n[ERROR ACMA FLUTTER] " + str(exc), file=sys.stderr)
        raise SystemExit(1) from None
    except KeyboardInterrupt:
        print("\nPrueba Flutter interrumpida.")
        raise SystemExit(130) from None
