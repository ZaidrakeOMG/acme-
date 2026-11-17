"""Pruebas offline del correo y la ruta de recuperación en web/móvil.

No accede a cuentas, no envía correos y no requiere secretos reales.
"""
from __future__ import annotations

import html
from html.parser import HTMLParser
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class _Enlaces(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.enlaces = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.enlaces.append(dict(attrs).get("href"))


class RecuperacionEnlaceTests(unittest.TestCase):
    def test_correo_incluye_boton_y_url_para_copiar(self):
        plantilla = (ROOT / "backend/plantillas/correo/restablecer.html").read_text(encoding="utf-8")
        url = "https://acme.example.com/restablecer?token=prueba.ABC_123-xyz&referencia=uno"
        contenido = plantilla.format_map({
            "cuerpo": html.escape("Si no fuiste tú, ignora el correo."),
            "url": html.escape(url, quote=True),
            "color_primario": "#1C3D8F",
        })
        self.assertIn("Cambiar contraseña", contenido)
        self.assertIn("copia y pega", contenido)
        self.assertIn(html.escape(url, quote=True), contenido)
        parser = _Enlaces()
        parser.feed(contenido)
        self.assertEqual(parser.enlaces, [url, url])
        self.assertIn(">https://acme.example.com/restablecer?token=", contenido)

    def test_recuperacion_solo_utiliza_plantilla_nueva_para_este_evento(self):
        fuente = (ROOT / "backend/services/notificaciones_service.py").read_text(encoding="utf-8")
        desde = fuente.index("async def _enviar_email(")
        hasta = fuente.index("\n# ---------------------------------------------------------------- bandeja", desde)
        bloque = fuente[desde:hasta]
        self.assertIn('n.evento == "auth.restablecer_contrasena"', bloque)
        self.assertIn('correo.plantilla("restablecer"', bloque)
        self.assertIn('url=url', bloque)
        self.assertIn('correo.plantilla("generico"', bloque)
        self.assertLess(bloque.index('correo.plantilla("restablecer"'), bloque.index('correo.plantilla("generico"'))

    def test_ruta_abierta_aunque_haya_sesion(self):
        app = (ROOT / "frontend/src/App.tsx").read_text(encoding="utf-8")
        self.assertIn("useLocation", app)
        self.assertIn("if (pathname === '/restablecer') return <Restablecer />", app)
        self.assertLess(app.index("if (pathname === '/restablecer')"), app.index("if (!usuario)"))

    def test_enlace_apunta_a_ruta_publica_con_token(self):
        codigo = (ROOT / "backend/services/auth_service.py").read_text(encoding="utf-8")
        self.assertIn('enlace = f"{config.app_url_publica}/restablecer?token={token}"', codigo)
        self.assertIn('url=enlace', codigo)


if __name__ == "__main__":
    unittest.main(verbosity=2)
