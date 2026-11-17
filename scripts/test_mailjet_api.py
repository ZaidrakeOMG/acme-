"""Pruebas offline de Mailjet HTTPS: sin credenciales ni correos reales."""
from __future__ import annotations

import base64
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import httpx

RAIZ = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "mailjet_api", RAIZ / "backend" / "services" / "mailjet_api.py"
)
assert spec is not None and spec.loader is not None
modulo = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = modulo
spec.loader.exec_module(modulo)


class MailjetAPITests(unittest.IsolatedAsyncioTestCase):
    async def _simular(self, responder, **cambios):
        peticiones = []
        def capturar(req: httpx.Request) -> httpx.Response:
            peticiones.append(req)
            return responder(req)

        real = httpx.AsyncClient
        with patch.object(modulo.httpx, "AsyncClient", side_effect=lambda *a, **k: real(
            *a, transport=httpx.MockTransport(capturar), **k)):
            resultado = await modulo.enviar_mailjet(
                api_key="api_publica_prueba",
                secret_key="secreto_privado_prueba",
                remitente="ACMA <zaid@ejemplo.com>",
                destinatarios=["usuario@ejemplo.com"],
                asunto="Recuperación ACMA",
                html="<a href='https://acma.ejemplo.com/restablecer?token=MUY_SECRETO'>Abrir</a>",
                texto="Recupera tu contraseña",
                **cambios,
            )
        return resultado, peticiones

    async def test_envio_por_https_con_autenticacion_y_sin_fuga(self):
        resultado, reqs = await self._simular(lambda req: httpx.Response(200, json={
            "Messages": [{"Status": "success", "To": [{"MessageID": 456}]}],
        }))
        self.assertEqual(resultado, ("enviada", "mailjet:aceptada"))
        self.assertEqual(len(reqs), 1)
        req = reqs[0]
        self.assertEqual(str(req.url), "https://api.mailjet.com/v3.1/send")
        esperado = base64.b64encode(b"api_publica_prueba:secreto_privado_prueba").decode()
        self.assertEqual(req.headers["Authorization"], f"Basic {esperado}")
        payload = json.loads(req.content)
        self.assertEqual(payload["Messages"][0]["From"],
                         {"Email": "zaid@ejemplo.com", "Name": "ACMA"})
        self.assertEqual(payload["Messages"][0]["To"], [{"Email": "usuario@ejemplo.com"}])
        self.assertNotIn("secreto_privado_prueba", req.content.decode())
        self.assertNotIn("MUY_SECRETO", resultado[1])

    async def test_error_403_cuando_remitente_no_verificado(self):
        resultado, _ = await self._simular(
            lambda req: httpx.Response(403, json={"ErrorMessage": "datos privados"}))
        self.assertEqual(resultado, ("fallida", "mailjet:http_403"))

    async def test_error_401_sin_claves_validas(self):
        resultado, _ = await self._simular(
            lambda req: httpx.Response(401, json={"ErrorMessage": "datos privados"}))
        self.assertEqual(resultado, ("fallida", "mailjet:http_401"))

    async def test_rechazo_por_mensaje_aunque_http_sea_200(self):
        resultado, _ = await self._simular(lambda req: httpx.Response(200, json={
            "Messages": [{"Status": "error", "Errors": [{"ErrorMessage": "secreto"}]}],
        }))
        self.assertEqual(resultado, ("fallida", "mailjet:mensaje_rechazado"))

    async def test_respuesta_invalida(self):
        resultado, _ = await self._simular(lambda req: httpx.Response(200, text="imposible"))
        self.assertEqual(resultado, ("fallida", "mailjet:respuesta_invalida"))

    async def test_envio_individual_sin_exponer_otro_destinatario(self):
        peticiones = []
        def responder(req):
            peticiones.append(json.loads(req.content))
            return httpx.Response(200, json={
                "Messages": [{"Status": "success"}, {"Status": "success"}],
            })
        # No se permiten pasar destinatarios duplicados al helper _simular.
        with patch.object(modulo.httpx, "AsyncClient", side_effect=lambda *a, **k: httpx.AsyncClient(
            *a, transport=httpx.MockTransport(responder), **k)):
            resultado = await modulo.enviar_mailjet(
                api_key="publica", secret_key="privada", remitente="ACMA <zaid@ejemplo.com>",
                destinatarios=["uno@ejemplo.com", "dos@ejemplo.com"],
                asunto="Hola", html="<p>Hola</p>", texto="Hola",
                adjuntos=[("prueba.pdf", b"%PDF-test")],
            )
        self.assertEqual(resultado[0], "enviada")
        mensajes = peticiones[0]["Messages"]
        self.assertEqual(len(mensajes), 2)
        self.assertEqual(mensajes[0]["To"], [{"Email": "uno@ejemplo.com"}])
        self.assertEqual(mensajes[1]["To"], [{"Email": "dos@ejemplo.com"}])
        self.assertEqual(mensajes[0]["Attachments"][0]["ContentType"], "application/pdf")
        self.assertEqual(base64.b64decode(mensajes[0]["Attachments"][0]["Base64Content"]), b"%PDF-test")

    async def test_no_llamar_api_sin_credenciales(self):
        estado, detalle = await modulo.enviar_mailjet(
            api_key="", secret_key="", remitente="", destinatarios=["usuario@ejemplo.com"],
            asunto="Reset", html="<p>Hola</p>", texto="Hola")
        self.assertEqual((estado, detalle), ("fallida", "mailjet:configuracion_incompleta"))

    async def test_red_devuelve_tipo_de_error_sin_datos(self):
        def responder(req):
            raise httpx.ConnectError("contraseña secreta: https://ejemplo.com/?token=token")
        resultado, _ = await self._simular(responder)
        self.assertEqual(resultado, ("fallida", "mailjet:red_ConnectError"))


class ConfiguracionTests(unittest.TestCase):
    def test_mailjet_se_activa_solo_por_opt_in(self):
        correo = (RAIZ / "backend" / "services" / "correo.py").read_text(encoding="utf-8")
        config = (RAIZ / "backend" / "core" / "config.py").read_text(encoding="utf-8")
        self.assertIn('correo_proveedor: str = "auto"', config)
        self.assertIn('if seleccionado != "auto":', correo)
        self.assertIn('if config.resend_api_key:', correo)
        self.assertIn('config.mailjet_secret_key', correo)

    def test_restauracion_no_requiere_celery_y_falla_si_falta_config(self):
        s = (RAIZ / "backend" / "services" / "auth_service.py").read_text(encoding="utf-8")
        desde = s.index("async def solicitar_restablecimiento(")
        hasta = s.index("async def confirmar_restablecimiento(", desde)
        fragmento = s[desde:hasta]
        self.assertIn("not correo.recuperacion_configurada()", fragmento)
        self.assertIn("enviar_ahora=True", fragmento)
        self.assertIn("CORREO_NO_CONFIGURADO", fragmento)


if __name__ == "__main__":
    unittest.main(verbosity=2)
