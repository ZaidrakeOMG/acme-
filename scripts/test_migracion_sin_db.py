"""Pruebas rápidas para integración React y Storage Supabase sin base de datos.

Ejecución: python scripts/test_migracion_sin_db.py
"""
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.frontend_integrado import instalar_frontend
from services.almacenamiento_supabase import AlmacenamientoSupabase


class SmokeSinBase(unittest.TestCase):
    def test_frontend_rutas_y_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            carpeta = Path(tmp)
            (carpeta / "index.html").write_text("<main>ACMA</main>", encoding="utf-8")
            (carpeta / "assets").mkdir()
            (carpeta / "assets" / "app.js").write_text("console.log('acma')", encoding="utf-8")
            app = FastAPI()

            @app.get("/api/salud")
            def salud():
                return {"estado": "ok"}

            self.assertTrue(instalar_frontend(app, carpeta))
            cliente = TestClient(app)
            self.assertEqual(cliente.get("/").status_code, 200)
            self.assertEqual(cliente.get("/folios/nuevo").status_code, 200)
            self.assertEqual(cliente.get("/api/salud").json(), {"estado": "ok"})
            self.assertEqual(cliente.get("/api/no-existe").status_code, 404)
            self.assertEqual(cliente.get("/assets/no-existe.js").status_code, 404)
            self.assertEqual(cliente.get("/assets/app.js").status_code, 200)

    def test_supabase_privado_lectura_escritura_y_bucket(self):
        solicitudes = []

        def responder(peticion):
            solicitudes.append(peticion)
            if peticion.method == "POST":
                return httpx.Response(200, json={"Key": "pruebas/folio.jpg"})
            if peticion.url.path.startswith("/storage/v1/bucket/"):
                return httpx.Response(200, json={"name": "acma"})
            return httpx.Response(200, content=b"contenido_cifrado")

        storage = AlmacenamientoSupabase(
            url="https://supabase-prueba.example.com",
            key="secret_test_servidor",
            bucket="acma",
            transport=httpx.MockTransport(responder),
        )
        storage.guardar("pruebas/folio.jpg", b"contenido_cifrado", "image/jpeg")
        self.assertEqual(storage.leer("pruebas/folio.jpg"), b"contenido_cifrado")
        storage.comprobar()
        self.assertEqual(len(solicitudes), 3)
        self.assertEqual(solicitudes[0].headers["x-upsert"], "true")
        self.assertTrue(all("secret_test_servidor" not in str(p.url) for p in solicitudes))
        with self.assertRaises(ValueError):
            storage.leer("../fuera")


if __name__ == "__main__":
    unittest.main(verbosity=2)
