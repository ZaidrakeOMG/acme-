"""Pruebas offline del diagnóstico .env de ACMA: no se conecta a Supabase."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import diagnosticar_env_supabase as d


class TestDiagnosticoEnv(unittest.TestCase):
    def test_configuracion_original_docker_no_se_reescribe(self):
        config = {
            "DATABASE_URL": "postgresql+asyncpg://acma_api:pass@localhost:5442/acma",
            "ALMACENAMIENTO_MODO": "minio",
            "DB_SCHEMA": "public",
        }
        self.assertFalse(d.es_dsn_supabase(config["DATABASE_URL"]))

    def test_supabase_privado_detectado(self):
        ref = "abcdefghijk1234567890"
        self.assertTrue(d.es_dsn_supabase(
            f"postgresql+asyncpg://acma_api.{ref}:credencial@aws-0-us-west-1.pooler.supabase.com:5432/postgres?ssl=require"
        ))
        self.assertTrue(d.es_url_publica_supabase(f"https://{ref}.supabase.co"))
        self.assertFalse(d.es_dsn_supabase("postgresql://acma_api@host.invalido/postgres"))

    def test_reparacion_respalda_y_no_modifica_secretos(self):
        with tempfile.TemporaryDirectory() as carpeta:
            raiz = Path(carpeta)
            env = raiz / ".env"
            original = (
                "DATABASE_URL=postgresql+asyncpg://acma_api:clave@db.abcdefghijk1234567890.supabase.co/postgres\n"
                "SUPABASE_SECRET_KEY=valor_privado_que_no_se_imprime\n"
                "DB_SCHEMA=public\n"
            )
            env.write_text(original, encoding="utf-8")
            with patch.object(d, "ENV", env), patch.object(d, "ROOT", raiz):
                with patch("builtins.input", return_value="CORREGIR"):
                    d.corregir_solo_esquema(original, {"DB_SCHEMA": "public"})
            actualizado = env.read_text(encoding="utf-8")
            self.assertIn("DB_SCHEMA=acma", actualizado)
            self.assertIn("SUPABASE_SECRET_KEY=valor_privado_que_no_se_imprime", actualizado)
            self.assertEqual((raiz / ".env.respaldo_antes_db_schema").read_text(encoding="utf-8"), original)

    def test_env_docker_se_respalda_solo_con_confirmacion(self):
        with tempfile.TemporaryDirectory() as carpeta:
            raiz = Path(carpeta)
            env = raiz / ".env"
            original = "DATABASE_URL=postgresql+asyncpg://acma_api:clave@localhost:5442/acma\n"
            env.write_text(original, encoding="utf-8")
            with patch.object(d, "ENV", env), patch.object(d, "ROOT", raiz):
                with patch("builtins.input", return_value="RESPALDAR"):
                    self.assertEqual(d.main(), 3)
            self.assertFalse(env.exists())
            self.assertEqual(
                (raiz / ".env.respaldo_anterior").read_text(encoding="utf-8"),
                original,
            )

    def test_env_docker_se_respalda_automaticamente_sin_esperar_input(self):
        with tempfile.TemporaryDirectory() as carpeta:
            raiz = Path(carpeta)
            env = raiz / ".env"
            original = "DB_SCHEMA=public\n"
            env.write_text(original, encoding="utf-8")
            with patch.object(d, "ENV", env), patch.object(d, "ROOT", raiz):
                with patch("builtins.input", side_effect=AssertionError("NO debe pedir RESPALDAR")):
                    self.assertEqual(d.main(), 3)
            self.assertFalse(env.exists())
            self.assertEqual((raiz / ".env.respaldo_anterior").read_text(encoding="utf-8"), original)

    def test_no_hay_cambio_sin_confirmacion(self):
        with tempfile.TemporaryDirectory() as carpeta:
            env = Path(carpeta) / ".env"
            env.write_text("DB_SCHEMA=public\n", encoding="utf-8")
            with patch.object(d, "ENV", env), patch.object(d, "ROOT", Path(carpeta)):
                with patch("builtins.input", return_value="CANCELAR"):
                    with self.assertRaises(SystemExit):
                        d.corregir_solo_esquema("DB_SCHEMA=public\n", {"DB_SCHEMA": "public"})
            self.assertEqual(env.read_text(encoding="utf-8"), "DB_SCHEMA=public\n")


    def test_solo_validar_no_pide_claves_ni_mueve_env_incompleto(self):
        with tempfile.TemporaryDirectory() as carpeta:
            raiz = Path(carpeta)
            env = raiz / ".env"
            original = "DB_SCHEMA=public\nDATABASE_URL=postgresql+asyncpg://local\n"
            env.write_text(original, encoding="utf-8")
            with patch.object(d, "ENV", env), patch.object(d, "ROOT", raiz):
                with patch("builtins.input", side_effect=AssertionError("No pedir claves")):
                    self.assertEqual(d.main(solo_validar=True), 2)
            self.assertEqual(env.read_text(encoding="utf-8"), original)
            self.assertFalse((raiz / ".env.respaldo_anterior").exists())

    def test_solo_validar_no_corrige_schema_sin_confirmacion(self):
        with tempfile.TemporaryDirectory() as carpeta:
            raiz = Path(carpeta)
            env = raiz / ".env"
            original = (
                "DB_SCHEMA=public\n"
                "DATABASE_URL=postgresql+asyncpg://acma_api.ejemploref:clave@aws-1-us-east-1.pooler.supabase.com:5432/postgres?ssl=require\n"
                "SUPABASE_URL=https://ejemploref.supabase.co\n"
                "SUPABASE_SECRET_KEY=clave_local\n"
                "ALMACENAMIENTO_MODO=supabase\n"
            )
            env.write_text(original, encoding="utf-8")
            with patch.object(d, "ENV", env), patch.object(d, "ROOT", raiz):
                with patch("builtins.input", side_effect=AssertionError("No pedir confirmacion")):
                    self.assertEqual(d.main(solo_validar=True), 2)
            self.assertEqual(env.read_text(encoding="utf-8"), original)

    def test_solo_validar_env_completo_sin_prompts(self):
        with tempfile.TemporaryDirectory() as carpeta:
            raiz = Path(carpeta)
            env = raiz / ".env"
            original = (
                "DB_SCHEMA=acma\n"
                "DATABASE_URL=postgresql+asyncpg://acma_api.ejemploref:clave@aws-1-us-east-1.pooler.supabase.com:5432/postgres?ssl=require\n"
                "SUPABASE_URL=https://ejemploref.supabase.co\n"
                "SUPABASE_SECRET_KEY=clave_local\n"
                "ALMACENAMIENTO_MODO=supabase\n"
            )
            env.write_text(original, encoding="utf-8")
            with patch.object(d, "ENV", env), patch.object(d, "ROOT", raiz):
                with patch("builtins.input", side_effect=AssertionError("No pedir credenciales")):
                    self.assertEqual(d.main(solo_validar=True), 0)
            self.assertEqual(env.read_text(encoding="utf-8"), original)


if __name__ == "__main__":
    unittest.main(verbosity=2)
