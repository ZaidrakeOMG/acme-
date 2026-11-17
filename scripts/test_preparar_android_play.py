"""Validaciones offline de configuración release Play Store, sin secretos reales."""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "scripts"))
import preparar_android_play as play

GRADLE_FLUTTER = """plugins {
    id("com.android.application")
    id("dev.flutter.flutter-gradle-plugin")
}
android {
    namespace = "com.example.acma_mobile"
    compileSdk = flutter.compileSdkVersion
    ndkVersion = flutter.ndkVersion

    defaultConfig {
        applicationId = "com.example.acma_mobile"
        minSdk = flutter.minSdkVersion
        targetSdk = flutter.targetSdkVersion
        versionCode = flutter.versionCode
    }

    buildTypes {
        release {
            signingConfig = signingConfigs.getByName("debug")
        }
    }
}
flutter {
    source = "../.."
}
"""


class AndroidPlayTests(unittest.TestCase):
    def test_aplica_id_api_36_y_keystore_release(self):
        r = play.preparar_gradle(GRADLE_FLUTTER, "com.zaidrakeomg.acma")
        self.assertIn('applicationId = "com.zaidrakeomg.acma"', r)
        self.assertIn("compileSdk = 36", r)
        self.assertIn("targetSdk = 36", r)
        self.assertIn('signingConfig = signingConfigs.getByName("release")', r)
        self.assertIn("ACMA_PLAYSTORE_RELEASE", r)
        self.assertIn('rootProject.file("key.properties")', r)
        self.assertNotIn('signingConfig = signingConfigs.getByName("debug")', r)

    def test_idempotente(self):
        r = play.preparar_gradle(GRADLE_FLUTTER, "com.zaidrakeomg.acma")
        self.assertEqual(play.preparar_gradle(r, "com.zaidrakeomg.acma"), r)

    def test_exige_id_unico_y_gradle_valido(self):
        for appid in ("com.example.app", "org.test", "com.example", "INVALID_APP", ""):
            with self.subTest(id=appid), self.assertRaises(ValueError):
                play.preparar_gradle(GRADLE_FLUTTER, appid)
        with self.assertRaises(ValueError):
            play.preparar_gradle("hello", "com.zaidrakeomg.acma")

    def test_firma_ausente_no_pasa(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(ValueError, "key.properties"):
                play.verificar_firma(Path(d) / "key.properties")

    def test_firma_usa_llave_privada_existente(self):
        with tempfile.TemporaryDirectory() as d:
            carpeta = Path(d)
            llave = carpeta / "fake.jks"
            llave.write_bytes(b"LLAVE_DE_PRUEBA")
            propiedades = carpeta / "key.properties"
            propiedades.write_text(
                "storePassword=pass_prueba\n"
                "keyPassword=pass_prueba\n"
                "keyAlias=upload\n"
                f"storeFile={llave.as_posix()}\n",
                encoding="utf-8"
            )
            play.verificar_firma(propiedades)

    def test_firma_faltante_propiedad_no_pasa(self):
        with tempfile.TemporaryDirectory() as d:
            propiedades = Path(d) / "key.properties"
            propiedades.write_text("keyAlias=upload\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "incompleto"):
                play.verificar_firma(propiedades)

    def test_icono_android_no_exige_ios(self):
        texto = (RAIZ / "mobile_flutter/pubspec.yaml").read_text(encoding="utf-8")
        self.assertIn("flutter_launcher_icons:", texto)
        self.assertIn("  android: true", texto)
        self.assertIn("  ios: false", texto)


if __name__ == "__main__":
    unittest.main(verbosity=2)
