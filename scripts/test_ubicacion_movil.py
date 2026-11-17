"""Controles offline de ubicación móvil: ninguna llamada de red ni datos reales."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
ROUTER = (ROOT / "backend/routers/ubicacion_movil.py").read_text(encoding="utf-8")
MIGRATION = (ROOT / "backend/alembic/versions/0019_ubicacion_movil_consentida.py").read_text(encoding="utf-8")
UI = (ROOT / "frontend/src/pages/ubicacion/UbicacionMovil.tsx").read_text(encoding="utf-8")
FLUTTER = (ROOT / "mobile_flutter/lib/main.dart").read_text(encoding="utf-8")
MAILJET = (ROOT / "backend/services/mailjet_api.py").read_text(encoding="utf-8")


class UbicacionPrivadaTests(unittest.TestCase):
    def test_migracion_rls_y_restriccion_anon(self):
        self.assertIn('revision = "0019"', MIGRATION)
        self.assertIn('down_revision = "0018"', MIGRATION)
        self.assertIn('rls("ubicaciones_movil"', MIGRATION)
        self.assertIn('rls("ubicacion_movil_visores"', MIGRATION)
        self.assertIn("acma_ctx_usuario()", MIGRATION)
        self.assertIn("acma_ctx_tenant()", MIGRATION)
        self.assertIn("acma_ctx_prestador()", MIGRATION)
        self.assertIn("habilitado = true", MIGRATION)
        self.assertIn("REVOKE ALL ON ubicacion_movil_visores, ubicaciones_movil FROM PUBLIC", MIGRATION)
        self.assertIn("FROM anon", MIGRATION)
        self.assertIn("FROM authenticated", MIGRATION)

    def test_gps_requiere_consentimiento_de_cada_persona(self):
        self.assertIn('if not datos.acepto:', ROUTER)
        self.assertIn("CONSENTIMIENTO_REQUERIDO", ROUTER)
        self.assertIn('WHERE usuario_id = :uid', ROUTER)
        self.assertIn('if activado is not True:', ROUTER)
        self.assertIn('DELETE FROM ubicaciones_movil WHERE usuario_id = :uid', ROUTER)
        self.assertIn("interval '15 seconds'", ROUTER)
        self.assertIn("interval '5 minutes'", ROUTER)
        self.assertIn('limit 500', ROUTER.lower())

    def test_permisos_solo_superadmin_y_datos_filtrados_por_empresa(self):
        self.assertEqual(ROUTER.count("Depends(requiere_rol(Rol.superadmin))"), 2)
        self.assertIn("if not await _puede_ver(db, actor)", ROUTER)
        self.assertIn("p.tenant_id = :org", ROUTER)
        self.assertIn("p.prestador_id = :org", ROUTER)
        self.assertIn('"habilitado": !usuario.habilitado', UI)
        self.assertIn("permiso", UI.lower())

    def test_android_sin_rastreo_automatico_ni_segundo_plano(self):
        self.assertIn('onPageFinished: (url)', FLUTTER)
        self.assertIn("window.__ACMA_ANDROID__=true", FLUTTER)
        self.assertIn("Comenzar a compartir", UI)
        self.assertIn('getCurrentPosition', UI)
        self.assertIn('watchPosition', UI)
        self.assertIn('visibilitychange', UI)
        self.assertIn('clearWatch', UI)
        self.assertIn("Detener y borrar ubicación", UI)
        self.assertNotIn("ACCESS_BACKGROUND_LOCATION", FLUTTER)

    def test_mailjet_no_reescribe_enlaces_de_restauracion(self):
        self.assertIn('"TrackClicks": "disabled"', MAILJET)
        self.assertIn('"TrackOpens": "disabled"', MAILJET)


if __name__ == "__main__":
    unittest.main(verbosity=2)
