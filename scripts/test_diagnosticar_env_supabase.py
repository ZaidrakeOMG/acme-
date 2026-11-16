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

    def test_env_docker_no_se_mueve_si_usuario_cancela(self):
        with tempfile.TemporaryDirectory() as carpeta:
            raiz = Path(carpeta)
            env = raiz / ".env"
            original = "DB_SCHEMA=public\n"
            env.write_text(original, encoding="utf-8")
            with patch.object(d, "ENV", env), patch.object(d, "ROOT", raiz):
                with patch("builtins.input", return_value="CANCELAR"):
                    self.assertEqual(d.main(), 2)
            self.assertEqual(env.read_text(encoding="utf-8"), original)

    def test_no_hay_cambio_sin_confirmacion(self):
        with tempfile.TemporaryDirectory() as carpeta:
            env = Path(carpeta) / ".env"
            env.write_text("DB_SCHEMA=public\n", encoding="utf-8")
            with patch.object(d, "ENV", env), patch.object(d, "ROOT", Path(carpeta)):
                with patch("builtins.input", return_value="CANCELAR"):
                    with self.assertRaises(SystemExit):
                        d.corregir_solo_esquema("DB_SCHEMA=public\n", {"DB_SCHEMA": "public"})
            self.assertEqual(env.read_text(encoding="utf-8"), "DB_SCHEMA=public\n")


if __name__ == "__main__":
    unittest.main(verbosity=2)
