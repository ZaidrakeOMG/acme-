"""Prepara el manifiesto Android de RELEASE y comprueba la URL de ACMA IONOS.

La compilacion release usa HTTPS y nunca depende de adb reverse.
Este archivo cambia SOLO el manifiesto Android generado localmente por Flutter.
No modifica Supabase, contraseñas ni ninguna tabla.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "mobile_flutter" / "android" / "app" / "src" / "main" / "AndroidManifest.xml"
ANDROID = "{http://schemas.android.com/apk/res/android}"
PERMISOS = (
    "android.permission.INTERNET",
    "android.permission.CAMERA",
    "android.permission.ACCESS_FINE_LOCATION",
    "android.permission.ACCESS_COARSE_LOCATION",
)


def validar_url(url: str) -> str:
    url = url.strip().rstrip("/")
    try:
        partes = urlsplit(url)
        puerto = partes.port
    except ValueError as exc:
        raise ValueError("URL publica invalida.") from exc
    if (
        partes.scheme != "https"
        or not partes.hostname
        or partes.username is not None
        or partes.password is not None
        or partes.path
        or partes.query
        or partes.fragment
        or (puerto is not None and puerto != 443)
    ):
        raise ValueError("La URL de ACMA debe ser solo https://dominio (sin rutas, claves ni puertos HTTP).")
    return url


def preparar_manifest(ruta: Path) -> list[str]:
    if not ruta.is_file():
        raise RuntimeError(
            "No existe el proyecto Android generado. Desde mobile_flutter ejecuta "
            "'flutter create --platforms=android --project-name acma_mobile .' y vuelve a intentar."
        )
    ET.register_namespace("android", "http://schemas.android.com/apk/res/android")
    arbol = ET.parse(ruta)
    raiz = arbol.getroot()
    if raiz.tag != "manifest":
        raise ValueError("AndroidManifest.xml no es un manifiesto Android.")
    aplicacion = raiz.find("application")
    if aplicacion is None:
        raise ValueError("AndroidManifest.xml debe tener application.")
    if aplicacion.get(ANDROID + "label") in {None, "acma_mobile"}:
        aplicacion.set(ANDROID + "label", "ACMA")
    if aplicacion.get(ANDROID + "usesCleartextTraffic") == "true":
        raise ValueError(
            "AndroidManifest principal permite HTTP sin cifrar. "
            "Retira usesCleartextTraffic=true; debe estar solo en src/debug."
        )
    existentes = {
        elemento.get(ANDROID + "name")
        for elemento in raiz.findall("uses-permission")
    }
    nuevos = [permiso for permiso in PERMISOS if permiso not in existentes]
    for indice, permiso in enumerate(nuevos):
        elemento = ET.Element("uses-permission")
        elemento.set(ANDROID + "name", permiso)
        raiz.insert(indice, elemento)
    if nuevos or aplicacion.get(ANDROID + "label") == "ACMA":
        ET.indent(arbol, space="    ")
        arbol.write(ruta, encoding="utf-8", xml_declaration=True)
    return nuevos


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("url", help="URL publica HTTPS, ej. https://acma.ejemplo.com")
    opciones = parser.parse_args()
    try:
        url = validar_url(opciones.url)
        cambios = preparar_manifest(MANIFEST)
        print("[OK] Dominio HTTPS valido para APK.")
        print("[OK] AndroidManifest de release preparado; permisos: " + str(len(PERMISOS)))
        print("[OK] Permisos nuevos: " + str(len(cambios)))
        print("[OK] No se habilito HTTP en release ni se agregaron claves de Supabase.")
        print("[INFO] Compila con: flutter build apk --release --dart-define=ACMA_BASE_URL=" + url)
    except (OSError, ValueError, RuntimeError, ET.ParseError) as exc:
        print("[ERROR APK ACMA] " + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
