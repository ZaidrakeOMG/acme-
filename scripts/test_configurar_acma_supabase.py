"""Tests offline del asistente de Supabase; nunca conecta ni modifica la BD."""
import tempfile
import httpx
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from configurar_acma_supabase import (
    referencia_proyecto, validar_dsn_privilegiado,
    dsn_para_acma, escribir_env, PROYECTO_ACMA_URL, solicitar_clave_secreta,
    comprobar_bucket,
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

    def test_secret_api_key_retry_paste_vacio_o_publicable(self):
        with tempfile.TemporaryDirectory() as carpeta:
            destino = Path(carpeta) / ".env.supabase_clave_local"
            with patch("configurar_acma_supabase.CLAVE_TEMPORAL", destino):
                with patch("configurar_acma_supabase.getpass.getpass", side_effect=[
                    "", "sb_publishable_simulacion",
                    "sb_secret_clave-falsa-para-pruebas",
                ]):
                    valor = solicitar_clave_secreta()
                    self.assertEqual(valor, "sb_secret_clave-falsa-para-pruebas")
                # No solicita de nuevo la contraseña, aun cuando falló Storage.
                with patch("configurar_acma_supabase.getpass.getpass",
                           side_effect=AssertionError("No volver a pedir clave")):
                    self.assertEqual(solicitar_clave_secreta(), valor)
            self.assertEqual(destino.read_text(encoding="utf-8").strip(), valor)

    def test_secret_api_key_no_acepta_tres_entradas_vacias(self):
        with tempfile.TemporaryDirectory() as carpeta:
            with patch("configurar_acma_supabase.CLAVE_TEMPORAL", Path(carpeta) / "clave"):
                with patch("configurar_acma_supabase.getpass.getpass", side_effect=["", " ", ""]):
                    with self.assertRaises(ValueError):
                        solicitar_clave_secreta()

    def test_storage_sb_secret_solo_apikey_y_crea_bucket_privado_si_falta(self):
        peticiones = []
        estado = {"existe": False}

        def responder(peticion):
            peticiones.append(peticion)
            self.assertEqual(peticion.headers.get("apikey"), "sb_secret_ficticia_test")
            self.assertNotIn("authorization", peticion.headers)
            if peticion.url.path == "/storage/v1/bucket/acma":
                if not estado["existe"]:
                    return httpx.Response(404, json={"code": "BucketNotFound"})
                return httpx.Response(
                    200, json={"id": "acma", "name": "acma", "public": False}
                )
            if peticion.url.path == "/storage/v1/bucket" and peticion.method == "POST":
                self.assertIs(json.loads(peticion.read())["public"], False)
                estado["existe"] = True
                return httpx.Response(200, json={"name": "acma"})
            return httpx.Response(500)

        cliente_real = httpx.Client
        with patch("httpx.Client", side_effect=lambda **kw:
                   cliente_real(transport=httpx.MockTransport(responder), **kw)):
            comprobar_bucket("https://prueba.supabase.co", "sb_secret_ficticia_test")
        self.assertEqual([p.method for p in peticiones], ["GET", "POST", "GET"])

    def test_storage_invalid_jwt_explica_codigo_sin_imprimir_la_clave(self):
        def responder(peticion):
            self.assertNotIn("authorization", peticion.headers)
            return httpx.Response(400, json={"code": "InvalidJWT"})
        cliente_real = httpx.Client
        with patch("httpx.Client", side_effect=lambda **kw:
                   cliente_real(transport=httpx.MockTransport(responder), **kw)):
            with self.assertRaisesRegex(RuntimeError, "HTTP 400 .*InvalidJWT"):
                comprobar_bucket("https://prueba.supabase.co", "sb_secret_ficticia_test")

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
