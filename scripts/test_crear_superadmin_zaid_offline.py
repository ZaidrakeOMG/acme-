"""Pruebas estáticas offline: creación de superadmin sin DB ni secretos."""
from pathlib import Path
import ast
import unittest

ROOT = Path(__file__).resolve().parents[1]
PY = ROOT / "backend" / "scripts" / "crear_superadmin_zaid.py"
BAT = ROOT / "CREAR_SUPERADMIN_ZAID.bat"


class AltaAdminOffline(unittest.TestCase):
    def test_codigo_compila_y_correo_se_configura(self):
        codigo = PY.read_text(encoding="utf-8")
        arbol = ast.parse(codigo)
        self.assertIn('CORREO = "zaidfarjat@gmail.com"', codigo)
        self.assertIn('NOMBRE = "Zaid Farjat"', codigo)
        self.assertIn('Rol.superadmin', codigo)
        self.assertIn('Dominio', codigo)
        self.assertIn('CONTEXTO_SISTEMA', codigo)
        self.assertIn('acma_api', codigo)
        self.assertTrue(any(isinstance(x, ast.AsyncFunctionDef) for x in ast.walk(arbol)))

    def test_contrasena_no_queda_versionada_y_se_valida(self):
        codigo = PY.read_text(encoding="utf-8")
        lanzador = BAT.read_text(encoding="utf-8")
        # El valor provisto por el usuario nunca debe guardarse en Git.
        self.assertNotIn("ZaiDrakeOMG25", codigo + lanzador)
        self.assertIn("getpass.getpass", codigo)
        self.assertIn("errores_politica_contrasena", codigo)
        self.assertIn("hashear_contrasena_async", codigo)
        self.assertIn("password_actualizado_at", codigo)

    def test_no_se_modifican_cuentas_anteriores(self):
        codigo = PY.read_text(encoding="utf-8")
        self.assertIn("anterior is not None", codigo)
        self.assertIn("return False", codigo)
        self.assertIn("db.add(nuevo)", codigo)
        self.assertIn("db.commit()", codigo)


if __name__ == "__main__":
    unittest.main(verbosity=2)
