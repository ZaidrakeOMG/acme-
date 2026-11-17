"""Validación offline de la ruta simple Safari y del diseño de ACMA.

No accede a Supabase ni genera tokens reales ni envía correos.
"""
from __future__ import annotations

import ast
import html
from pathlib import Path
import re
from string import Template
import unittest

from starlette.responses import HTMLResponse

ROOT = Path(__file__).resolve().parents[1]
PAGINA = ROOT / "backend/routers/recuperacion_web.py"


def _formulario_aislado():
    """Ejecuta solamente renderer puro (sin importar base de datos de producción)."""
    source = ast.parse(PAGINA.read_text(encoding="utf-8"))
    seleccionados = []
    nombres = {"_TOKEN", "_HTML", "_CABECERAS", "_pagina", "_formulario"}
    for nodo in source.body:
        if isinstance(nodo, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id in nombres for t in nodo.targets
        ):
            seleccionados.append(nodo)
        elif isinstance(nodo, ast.FunctionDef) and nodo.name in nombres:
            seleccionados.append(nodo)
    scope = {"re": re, "Template": Template, "html": html, "HTMLResponse": HTMLResponse}
    exec(compile(ast.fix_missing_locations(ast.Module(body=seleccionados, type_ignores=[])),
                 str(PAGINA), "exec"), scope)
    return scope["_formulario"], scope["_TOKEN"]


class SafariResetTests(unittest.TestCase):
    def test_formulario_no_necesita_react_ni_javascript(self):
        formulario, token_re = _formulario_aislado()
        token = "aaa.bbb_123.CCC-456"
        self.assertTrue(token_re.fullmatch(token))
        respuesta = formulario(token)
        pagina = respuesta.body.decode("utf-8")
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.headers["cache-control"], "no-store, max-age=0")
        self.assertIn('name="viewport"', pagina)
        self.assertIn('action="/restablecer/seguro"', pagina)
        self.assertIn('name="confirmacion"', pagina)
        self.assertIn('name="token" value="' + token + '"', pagina)
        self.assertNotIn("<script", pagina.lower())
        self.assertNotIn("/assets/", pagina)
        self.assertNotIn("react", pagina.lower())
        self.assertIn("Guardar contraseña nueva", pagina)

    def test_el_token_se_escapa_en_el_html(self):
        formulario, _ = _formulario_aislado()
        pagina = formulario('abc" onfocus="alert(1)').body.decode("utf-8")
        self.assertIn('value="abc&quot; onfocus=&quot;alert(1)"', pagina)
        self.assertNotIn('value="abc" onfocus=', pagina)

    def test_ruta_va_antes_del_montaje_static_spa(self):
        main = (ROOT / "backend/main.py").read_text(encoding="utf-8")
        self.assertIn("app.include_router(recuperacion_web.router)", main)
        self.assertLess(main.index("app.include_router(recuperacion_web.router)"),
                        main.index("instalar_frontend(app)"))
        source = PAGINA.read_text(encoding="utf-8")
        self.assertIn('@router.get("/restablecer/seguro"', source)
        self.assertIn('@router.post("/restablecer/seguro"', source)
        self.assertIn("auth_service.confirmar_restablecimiento(db, request, token, nueva)", source)
        self.assertIn("db.rollback()", source)

    def test_pwa_no_intercepta_formulario_simple(self):
        vite = (ROOT / "frontend/vite.config.ts").read_text(encoding="utf-8")
        self.assertIn("navigateFallbackDenylist:", vite)
        self.assertIn("restablecer\\/seguro", vite)

    def test_componentes_movil_usan_las_clases_de_distribucion(self):
        ui = (ROOT / "frontend/src/components/ui.tsx").read_text(encoding="utf-8")
        css = (ROOT / "frontend/src/index.css").read_text(encoding="utf-8")
        shell = (ROOT / "frontend/src/components/AppShell.tsx").read_text(encoding="utf-8")
        self.assertIn('className="acma-tabla w-full', ui)
        self.assertIn('className="acma-tabla-vacia"', ui)
        self.assertIn(".acma-tabla tbody", css)
        self.assertIn("(min-width: 1024px)", css)
        self.assertIn("(max-width: 1023px)", css)
        self.assertIn("lg:sticky", shell)
        self.assertIn("matchMedia('(max-width: 1023px)')", shell)


if __name__ == "__main__":
    unittest.main(verbosity=2)
