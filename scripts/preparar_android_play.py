"""Configura Android 16 (API 36), ID propio y firma RELEASE para Google Play.

Solo modifica android/app/build.gradle.kts generado por Flutter. No crea ni
versiona llaves privadas. La firma debe existir en android/key.properties,
fuera de Git. Sin firma real no se debe entregar un AAB a Play Console.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
GRADLE = ROOT / "mobile_flutter/android/app/build.gradle.kts"
KEY_PROPERTIES = ROOT / "mobile_flutter/android/key.properties"
ID_PREDETERMINADO = "com.zaidrakeomg.acma"
ID_VALIDO = re.compile(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*){2,}")

DECLARACION_CLAVES = """// ACMA_PLAYSTORE_RELEASE
val acmaKeyProperties = Properties()
val acmaKeyPropertiesFile = rootProject.file("key.properties")
if (acmaKeyPropertiesFile.exists()) {
    FileInputStream(acmaKeyPropertiesFile).use { acmaKeyProperties.load(it) }
}

"""
BLOQUE_FIRMA = """    signingConfigs {
        create("release") {
            if (acmaKeyPropertiesFile.exists()) {
                keyAlias = acmaKeyProperties.getProperty("keyAlias")
                keyPassword = acmaKeyProperties.getProperty("keyPassword")
                storeFile = file(acmaKeyProperties.getProperty("storeFile"))
                storePassword = acmaKeyProperties.getProperty("storePassword")
            }
        }
    }

"""


def preparar_gradle(contenido: str, identificador: str) -> str:
    if not ID_VALIDO.fullmatch(identificador) or identificador.startswith("com.example."):
        raise ValueError("Identificador Android inválido; debe ser único (p. ej. com.zaidrakeomg.acma).")
    if "plugins {" not in contenido or "android {" not in contenido:
        raise ValueError("build.gradle.kts no corresponde a plantilla Flutter Android.")
    for clave, valor in (
        ("applicationId", f'"{identificador}"'),
        ("compileSdk", "36"),
        ("targetSdk", "36"),
    ):
        patron = rf"(?m)^(\s*){clave}\s*=\s*[^\n]+"
        contenido, numero = re.subn(
            patron, lambda m, k=clave, v=valor: m.group(1) + k + " = " + v,
            contenido, count=1,
        )
        if numero != 1:
            raise ValueError(f"No se encontró {clave} en build.gradle.kts.")
    if "ACMA_PLAYSTORE_RELEASE" not in contenido:
        contenido = (
            "import java.util.Properties\nimport java.io.FileInputStream\n\n" + contenido
        )
        contenido = contenido.replace("android {", DECLARACION_CLAVES + "android {", 1)
        patron_buildtypes = re.search(r"(?m)^    buildTypes\s*\{", contenido)
        if patron_buildtypes is None:
            raise ValueError("No se encontró el bloque buildTypes de Gradle.")
        contenido = (
            contenido[:patron_buildtypes.start()]
            + BLOQUE_FIRMA
            + contenido[patron_buildtypes.start():]
        )
    anterior = 'signingConfig = signingConfigs.getByName("debug")'
    nuevo = 'signingConfig = signingConfigs.getByName("release")'
    if anterior in contenido:
        contenido = contenido.replace(anterior, nuevo, 1)
    elif nuevo not in contenido:
        raise ValueError("No se encontró signingConfig en buildTypes.release.")
    return contenido


def verificar_firma(archivo: Path) -> None:
    if not archivo.is_file():
        raise ValueError(
            "Falta android/key.properties. Genera tu upload-keystore.jks y configura "
            "storeFile, storePassword, keyAlias y keyPassword (ver PLAYSTORE_ANDROID.md)."
        )
    pares: dict[str, str] = {}
    for linea in archivo.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if linea and not linea.startswith(("#", "!")) and "=" in linea:
            k, v = linea.split("=", 1)
            pares[k.strip()] = v.strip()
    faltan = [k for k in ("storeFile", "storePassword", "keyAlias", "keyPassword")
              if not pares.get(k)]
    if faltan:
        raise ValueError("key.properties incompleto (campos): " + ", ".join(faltan))
    ruta = Path(pares["storeFile"].replace("\\\\", "\\"))
    if not ruta.is_absolute():
        ruta = ROOT / "mobile_flutter/android/app" / ruta
    if not ruta.is_file():
        raise ValueError("No se encontró el archivo upload-keystore.jks indicado por storeFile.")
    if len(pares["storePassword"]) < 6 or len(pares["keyPassword"]) < 6:
        raise ValueError("Contraseña de firma demasiado corta.")
    # No imprimir ni contraseñas ni la ruta de la llave.


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--application-id", default=ID_PREDETERMINADO)
    parser.add_argument("--verificar-firma", action="store_true")
    args = parser.parse_args()
    try:
        if args.verificar_firma:
            verificar_firma(KEY_PROPERTIES)
        texto = GRADLE.read_text(encoding="utf-8")
        nuevo = preparar_gradle(texto, args.application_id)
        if nuevo != texto:
            GRADLE.write_text(nuevo, encoding="utf-8")
        print("[OK] applicationId=" + args.application_id)
        print("[OK] Android compileSdk=36, targetSdk=36.")
        print("[OK] Gradle release usa exclusivamente la clave upload privada.")
        print("[INFO] NO subas key.properties ni archivos .jks a GitHub.")
        if args.verificar_firma:
            print("[OK] Configuración de firma presente; comprobar AAB firmado tras compilar.")
    except (OSError, ValueError, UnicodeError) as error:
        print("[ERROR PLAY] " + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
