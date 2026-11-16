"""Tests offline del asistente de Supabase; nunca conecta ni modifica la BD."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from configurar_acma_supabase import (
    referencia_proyecto, validar_dsn_privilegiado,
    dsn_para_acma, escribir_env, PROYECTO_ACMA_URL,
)

REF = "abcdefghijk1234567890"
URL = f"https://{REF}.supabase.co"


class TestConfiguracion(unittest.TestCase):
    def test_proyecto_publico_valido(self):
        self.assertEqual(PROYECTO_ACMA_URL, 'https://mrtmwmqzueqamzfveyev.supabase.co')
        self.assertEqual(referencia_proyecto(PROYECTO_ACMA_URL), 'mrtmwmqzueqamzfveyev')
        self.assertEqual(referencia_proyecto(URL), REF)
        with self.assertRaises(ValueError):
            referencia_proyecto("http://inseguro.supabase.co")

    def test_dsn_session_pooler_requiere_ref_y_5432(self):
        dsn = (
            f"postgresql://postgres.{REF}:clave@"
            "aws-1-us-west-1.pooler.supabase.com:5432/postgres"
        )
        partes, pooler = validar_dsn_privilegiado(dsn, REF)
        self.assertTrue(pooler)
        app = dsn_para_acma(partes, REF, pooler, "s3gura?clave")
        self.assertIn(f"acma_api.{REF}:", app)
        self.assertIn("s3gura%3Fclave", app)
        self.assertIn("ssl=require", app)
        with self.assertRaises(ValueError):
            validar_dsn_privilegiado(dsn.replace(":5432/", ":6543/"), REF)
        with self.assertRaises(ValueError):
            validar_dsn_privilegiado(dsn.replace(f"postgres.{REF}", "postgres.otro"), REF)

    def test_dsn_directo(self):
        p, pooler = validar_dsn_privilegiado(
            f"postgresql://postgres:clave@db.{REF}.supabase.co:5432/postgres",
            REF,
        )
        self.assertFalse(pooler)
        app = dsn_para_acma(p, REF, pooler, "valida")
        self.assertIn(f"acma_api:valida@db.{REF}.supabase.co:5432", app)

    def test_env_secreto_no_se_sobrescribe(self):
        with tempfile.TemporaryDirectory() as carpeta:
            destino = Path(carpeta) / ".env"
            with patch("configurar_acma_supabase.ENV", destino):
                escribir_env("postgresql+asyncpg://acma_api:clave@prueba/postgres", URL, "sb_secret_ejemplo")
                s = destino.read_text(encoding="utf-8")
                self.assertIn("DB_SCHEMA=acma", s)
                self.assertIn("MFA_OBLIGATORIO=true", s)
                self.assertIn("ALMACENAMIENTO_MODO=supabase", s)
                self.assertNotIn("postgres:clave@prueba", s)
                with self.assertRaises(FileExistsError):
                    escribir_env("otro", URL, "otra")


if __name__ == "__main__":
    unittest.main(verbosity=2)
