"""Tests offline del lanzador Flutter Android (no requieren SDK ni Supabase)."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import iniciar_flutter_acma as m


class LanzadorFlutter(unittest.TestCase):
    def test_no_inicia_flutter_si_no_existe_sdk(self):
        with patch.object(m, "buscar_flutter", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "Flutter SDK"):
                m.main()

    def test_solo_reconoce_dispositivos_autorizados(self):
        salida = (
            "List of devices attached\n"
            "emulator-5554\tdevice product:sdk_gphone\n"
            "ABCDE\tunauthorized\n"
            "12345\toffline\n"
            "\n"
        )
        with patch.object(m.subprocess, "run",
                          return_value=CompletedProcess(["adb", "devices"], 0, salida, "")):
            self.assertEqual(m.dispositivos_android("adb"), ["emulator-5554"])

    def test_lanzador_enlaza_localhost_sin_secretos(self):
        with tempfile.TemporaryDirectory() as temporal:
            mobile = Path(temporal)
            manifiesto = mobile / "android/app/src/main/AndroidManifest.xml"
            manifiesto.parent.mkdir(parents=True)
            manifiesto.write_text("<manifest/>", encoding="utf-8")
            debug = mobile / "android/app/src/debug/AndroidManifest.xml"
            debug.parent.mkdir(parents=True)
            debug.write_text("<manifest/>", encoding="utf-8")
            with (patch.object(m, "MOBILE", mobile),
                  patch.object(m, "buscar_flutter", return_value="flutter"),
                  patch.object(m, "buscar_adb", return_value="adb"),
                  patch.object(m, "validar_backend"),
                  patch.object(m, "comprobar_ndk"),
                  patch.object(m, "comprobar_plataforma_android"),
                  patch.object(m, "dispositivos_android", return_value=["emulator-5554"]),
                  patch.object(m, "ejecutar") as ejecutar,
                  patch.object(m.subprocess, "run", return_value=CompletedProcess([], 0)) as correr):
                self.assertEqual(m.main(), 0)
                ejecutar.assert_any_call(
                    ["adb", "-s", "emulator-5554", "reverse", "tcp:8000", "tcp:8000"]
                )
                ejecutar.assert_any_call(["flutter", "pub", "get"], cwd=mobile)
                args = correr.call_args.args[0]
                self.assertEqual(args[:4], ["flutter", "run", "-d", "emulator-5554"])
                self.assertIn("--dart-define=ACMA_BASE_URL=http://localhost:8000", args)
                self.assertIn("--dart-define=ACMA_ALLOW_HTTP=true", args)
                self.assertFalse(any("sb_secret" in argumento for argumento in args))

    def test_ndk_faltante_da_instrucciones_antes_de_compilar(self):
        with tempfile.TemporaryDirectory() as temporal:
            sdk = Path(temporal)
            with patch.object(m, "ruta_sdk_android", return_value=sdk):
                with self.assertRaisesRegex(RuntimeError, "SDK Tools") as fallo:
                    m.comprobar_ndk()
                self.assertIn("28.2.13676358", str(fallo.exception))
                self.assertIn("Show Package Details", str(fallo.exception))

    def test_ndk_instalado_no_bloquea_flutter(self):
        with tempfile.TemporaryDirectory() as temporal:
            sdk = Path(temporal)
            path = sdk / "ndk" / m.NDK_VERSION / "source.properties"
            path.parent.mkdir(parents=True)
            path.write_text("Pkg.Revision = 28.2.13676358\n", encoding="utf-8")
            with patch.object(m, "ruta_sdk_android", return_value=sdk):
                m.comprobar_ndk()

    def test_plataforma_36_faltante_se_detecta_antes_de_compilar(self):
        with tempfile.TemporaryDirectory() as temporal:
            sdk = Path(temporal)
            with patch.object(m, "ruta_sdk_android", return_value=sdk):
                with self.assertRaisesRegex(RuntimeError, "SDK Platforms") as fallo:
                    m.comprobar_plataforma_android()
                self.assertIn("android-36", str(fallo.exception))
                self.assertIn("Android 16.0", str(fallo.exception))

    def test_plataforma_36_incompleta_no_pasa_verificacion(self):
        with tempfile.TemporaryDirectory() as temporal:
            sdk = Path(temporal)
            carpeta = sdk / "platforms" / "android-36"
            carpeta.mkdir(parents=True)
            (carpeta / "source.properties").write_text(
                "Pkg.Revision = 2\n", encoding="utf-8"
            )
            with patch.object(m, "ruta_sdk_android", return_value=sdk):
                with self.assertRaisesRegex(RuntimeError, "incompleta"):
                    m.comprobar_plataforma_android()

    def test_plataforma_36_completa_pasa_verificacion(self):
        with tempfile.TemporaryDirectory() as temporal:
            sdk = Path(temporal)
            carpeta = sdk / "platforms" / "android-36"
            carpeta.mkdir(parents=True)
            (carpeta / "source.properties").write_text(
                "Pkg.Revision = 2\n", encoding="utf-8"
            )
            (carpeta / "android.jar").write_bytes(b"PRUEBA")
            with patch.object(m, "ruta_sdk_android", return_value=sdk):
                m.comprobar_plataforma_android()

    def test_railway_abre_android_sin_servidor_local(self):
        with tempfile.TemporaryDirectory() as temporal:
            movil = Path(temporal)
            manifest = movil / "android/app/src/main/AndroidManifest.xml"
            manifest.parent.mkdir(parents=True)
            manifest.write_text("<manifest/>", encoding="utf-8")
            with (patch.object(m, "MOBILE", movil),
                  patch.object(m, "buscar_flutter", return_value="flutter"),
                  patch.object(m, "buscar_adb", return_value="adb"),
                  patch.object(m, "dispositivos_android", return_value=["emulator-5554"]),
                  patch.object(m, "validar_backend") as backend,
                  patch.object(m, "comprobar_ndk"),
                  patch.object(m, "comprobar_plataforma_android"),
                  patch.object(m, "ejecutar") as ejecutar,
                  patch.object(m.subprocess, "run",
                               return_value=CompletedProcess([], 0)) as ejecutar_flutter):
                self.assertEqual(m.iniciar_railway(), 0)
                backend.assert_not_called()
                ejecutar.assert_called_once_with(["flutter", "pub", "get"], cwd=movil)
                comando = ejecutar_flutter.call_args.args[0]
                self.assertEqual(comando[:4], ["flutter", "run", "-d", "emulator-5554"])
                self.assertIn(
                    "--dart-define=ACMA_BASE_URL=https://acme-production-ee493e67.up.railway.app",
                    comando,
                )
                self.assertNotIn("--dart-define=ACMA_ALLOW_HTTP=true", comando)
                self.assertNotIn("reverse", comando)

    def test_web_bat_no_exige_py_con_venv_existente(self):
        lanzador = (ROOT / "PROBAR_ACMA_WEB.bat").read_text(encoding="utf-8")
        self.assertIn(
            'if not exist "backend\\.venv\\Scripts\\python.exe" (\n  where py',
            lanzador,
        )
        self.assertIn(
            '"backend\\.venv\\Scripts\\python.exe" scripts\\diagnosticar_env_supabase.py',
            lanzador,
        )

    def test_bat_usa_python_existente_y_no_exige_launcher_py(self):
        lanzador = (ROOT / "PROBAR_ACMA_FLUTTER_ANDROID.bat").read_text(encoding="utf-8")
        self.assertIn('if exist "backend\\.venv\\Scripts\\python.exe" goto :python_venv', lanzador)
        self.assertIn('"backend\\.venv\\Scripts\\python.exe" scripts\\iniciar_flutter_acma.py %ACMA_MODO%', lanzador)
        self.assertIn("if not errorlevel 1 goto :python_path", lanzador)
        self.assertNotIn("No se encontro el lanzador py de Python 3.12", lanzador)
        self.assertIn('set "ACMA_MODO=--railway"', lanzador)
        self.assertIn('if /I "%~1"=="--local" set "ACMA_MODO="', lanzador)

    def test_manifest_android_solo_debug_permite_http(self):
        ruta = ROOT / "mobile_flutter/android/app/src/debug/AndroidManifest.xml"
        manifest = ET.parse(ruta).getroot()
        android = "{http://schemas.android.com/apk/res/android}"
        app = manifest.find("application")
        self.assertIsNotNone(app)
        self.assertEqual(app.attrib.get(android + "usesCleartextTraffic"), "true")
        self.assertEqual(manifest.tag, "manifest")
        contenido = (ROOT / "mobile_flutter/lib/configuracion_acma.dart").read_text("utf-8")
        self.assertIn("!kReleaseMode && _permitirHttpLocal", contenido)


if __name__ == "__main__":
    unittest.main(verbosity=2)
