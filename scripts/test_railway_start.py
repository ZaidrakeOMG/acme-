"""Pruebas de arranque Railway sin red ni secretos reales."""
from __future__ import annotations

from pathlib import Path
import importlib.util
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
RUTA = ROOT / "backend" / "railway_start.py"
spec = importlib.util.spec_from_file_location("railway_start", RUTA)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def entorno() -> dict[str, str]:
    return {
        "DATABASE_URL": "postgresql+asyncpg://u:p@host.invalid:5432/postgres",
        "SUPABASE_URL": "https://test.supabase.co",
        "SUPABASE_SECRET_KEY": "clave_de_prueba_local",
        "JWT_SECRETO": "esta_es_una_clave_solo_de_prueba_12345",
        "CLAVE_CIFRADO": "valor_de_prueba_no_real",
    }


class RailwayStart(unittest.TestCase):
    def test_configurar_dominio_railway_automatico(self):
        e = entorno()
        e["RAILWAY_PUBLIC_DOMAIN"] = "acma-ejemplo.up.railway.app"
        mod.preparar_entorno(e)
        self.assertEqual(e["APP_URL_PUBLICA"], "https://acma-ejemplo.up.railway.app")
        self.assertEqual(e["CORS_ORIGENES"], "https://acma-ejemplo.up.railway.app")
        self.assertEqual(e["ACMA_ENTORNO"], "produccion")
        self.assertEqual(e["MFA_OBLIGATORIO"], "true")
        self.assertEqual(e["TIEMPO_REAL_MODO"], "local")
        self.assertEqual(e["DB_SCHEMA"], "acma")

    def test_respetar_url_ionos_configurada(self):
        e = entorno()
        e.update({
            "APP_URL_PUBLICA": "https://acma.empresa.com",
            "CORS_ORIGENES": "https://acma.empresa.com",
        })
        mod.preparar_entorno(e)
        self.assertEqual(e["APP_URL_PUBLICA"], "https://acma.empresa.com")

    def test_exigir_dominio_publico(self):
        with self.assertRaisesRegex(ValueError, "Genera un dominio"):
            mod.preparar_entorno(entorno())

    def test_no_aceptar_dominio_malicioso(self):
        for dominio in ("https://example.com", "dominio.com/ruta", "a.com; comando",
                        "https://abc.up.railway.app", "example.com\nOTRO_VALOR=x"):
            e = entorno()
            e["RAILWAY_PUBLIC_DOMAIN"] = dominio
            with self.subTest(dominio=dominio), self.assertRaises(ValueError):
                mod.preparar_entorno(e)

    def test_exigir_secretos_y_no_publicarlos(self):
        e = {"RAILWAY_PUBLIC_DOMAIN": "acma.up.railway.app"}
        with self.assertRaisesRegex(ValueError, "DATABASE_URL"):
            mod.preparar_entorno(e)

    def test_bloquear_mfa_desactivado(self):
        e = entorno()
        e["RAILWAY_PUBLIC_DOMAIN"] = "acma.up.railway.app"
        e["MFA_OBLIGATORIO"] = "false"
        with self.assertRaisesRegex(ValueError, "MFA_OBLIGATORIO"):
            mod.preparar_entorno(e)

    def test_bloquear_entorno_no_produccion(self):
        e = entorno()
        e["RAILWAY_PUBLIC_DOMAIN"] = "acma.up.railway.app"
        e["ACMA_ENTORNO"] = "desarrollo"
        with self.assertRaisesRegex(ValueError, "ACMA_ENTORNO"):
            mod.preparar_entorno(e)

    def test_main_lanza_uvicorn_con_puerto_railway(self):
        e = entorno()
        e["RAILWAY_PUBLIC_DOMAIN"] = "acma.up.railway.app"
        e["PORT"] = "5678"
        with patch.dict(mod.os.environ, e, clear=True), patch.object(mod.os, "execvp") as ejecutar:
            self.assertEqual(mod.main(), 0)
            ejecutar.assert_called_once()
            self.assertEqual(ejecutar.call_args.args[0], "uvicorn")
            args = ejecutar.call_args.args[1]
            self.assertEqual(args[args.index("--port") + 1], "5678")


if __name__ == "__main__":
    unittest.main(verbosity=2)
