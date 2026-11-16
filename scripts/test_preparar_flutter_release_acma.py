"""Pruebas offline para generar APK HTTPS con el manifiesto de producción correcto."""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import preparar_flutter_release_acma as m


class ApkIonOS(unittest.TestCase):
    def test_no_permitir_http_ni_localhost(self):
        invalidas = (
            "http://acma.example.com",
            "http://localhost:8000",
            "https://acma.example.com/login",
            "https://acma.example.com?apikey=secreto",
            "https://user:password@acma.example.com",
            "https://acma.example.com:8000",
        )
        for url in invalidas:
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    m.validar_url(url)

    def test_permitir_dominio_https(self):
        self.assertEqual(
            m.validar_url(" https://acma.example.com/ "),
            "https://acma.example.com",
        )

    def test_manifest_release_permisos_y_no_http(self):
        with tempfile.TemporaryDirectory() as temporal:
            archivo = Path(temporal) / "AndroidManifest.xml"
            archivo.write_text(
                '<manifest xmlns:android="http://schemas.android.com/apk/res/android">'
                '<application android:label="ACMA" /></manifest>',
                encoding="utf-8",
            )
            self.assertEqual(len(m.preparar_manifest(archivo)), len(m.PERMISOS))
            self.assertEqual(m.preparar_manifest(archivo), [])
            raiz = ET.parse(archivo).getroot()
            permisos = [
                elemento.get(m.ANDROID + "name")
                for elemento in raiz.findall("uses-permission")
            ]
            self.assertEqual(set(permisos), set(m.PERMISOS))
            app = raiz.find("application")
            self.assertIsNotNone(app)
            self.assertNotEqual(app.get(m.ANDROID + "usesCleartextTraffic"), "true")

    def test_rechazar_http_en_manifiesto_principal(self):
        with tempfile.TemporaryDirectory() as temporal:
            archivo = Path(temporal) / "AndroidManifest.xml"
            archivo.write_text(
                '<manifest xmlns:android="http://schemas.android.com/apk/res/android">'
                '<application android:usesCleartextTraffic="true" /></manifest>',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "HTTP sin cifrar"):
                m.preparar_manifest(archivo)


if __name__ == "__main__":
    unittest.main(verbosity=2)
