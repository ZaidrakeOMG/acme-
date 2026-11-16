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
