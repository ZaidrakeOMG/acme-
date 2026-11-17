"""Pruebas sin red ni secretos del envío HTTPS de restablecimiento."""
from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import httpx

RAIZ = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "resend_api", RAIZ / "backend" / "services" / "resend_api.py")
assert spec is not None and spec.loader is not None
modulo = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = modulo
spec.loader.exec_module(modulo)


class ResendAPITests(unittest.IsolatedAsyncioTestCase):
    async def test_envia_por_https_con_bearer_sin_fugas(self):
        capturados = []

        def responder(req: httpx.Request) -> httpx.Response:
            capturados.append(req)
            return httpx.Response(200, json={"id": "email_prueba_1"})

        real = httpx.AsyncClient
        def cliente_falso(*a, **k):
            return real(*a, transport=httpx.MockTransport(responder), **k)

        with patch.object(modulo.httpx, "AsyncClient", side_effect=cliente_falso):
            estado, detalle = await modulo.enviar_resend(
                api_key="re_api_prueba", remitente="ACMA <no-reply@correo.ejemplo.com>",
                destinatarios=["cliente@example.com"],
                asunto="Restablece tu contraseña", html="<p>Hola</p>",
                texto="Hola",
            )
        self.assertEqual((estado, detalle), ("enviada", "resend:email_prueba_1"))
        self.assertEqual(len(capturados), 1)
        req = capturados[0]
        self.assertEqual(str(req.url), "https://api.resend.com/emails")
        self.assertEqual(req.headers["Authorization"], "Bearer re_api_prueba")
        data = json.loads(req.content.decode())
        self.assertEqual(data["to"], ["cliente@example.com"])
        self.assertEqual(data["from"], "ACMA <no-reply@correo.ejemplo.com>")
        self.assertNotIn("re_api_prueba", req.content.decode())

    async def test_rechaza_sin_remitente_real(self):
        estado, detalle = await modulo.enviar_resend(
            api_key="re_api_prueba", remitente="", destinatarios=["cliente@example.com"],
            asunto="Restablecer", html="<p>X</p>", texto="X")
        self.assertEqual((estado, detalle), ("fallida", "resend:configuracion_incompleta"))

    async def test_error_http_no_devuelve_tokens_ni_credenciales(self):
        def responder(req: httpx.Request) -> httpx.Response:
            return httpx.Response(403, json={"message": "secreto-prohibido"})

        real = httpx.AsyncClient
        with patch.object(modulo.httpx, "AsyncClient", side_effect=lambda *a, **k: real(
            *a, transport=httpx.MockTransport(responder), **k)):
            estado, detalle = await modulo.enviar_resend(
                api_key="re_super_secreto", remitente="ACMA <no-reply@ejemplo.com>",
                destinatarios=["cliente@example.com"], asunto="Reset",
                html="<a href='https://app.ejemplo.com/restablecer?token=SECRETO'>Restablecer</a>",
                texto="Reset")
        self.assertEqual((estado, detalle), ("fallida", "resend:http_403"))
        self.assertNotIn("SECRETO", detalle)
        self.assertNotIn("re_super_secreto", detalle)

    async def test_error_red_resumido(self):
        def responder(req: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("token o contraseña en un error de red")
        real = httpx.AsyncClient
        with patch.object(modulo.httpx, "AsyncClient", side_effect=lambda *a, **k: real(
            *a, transport=httpx.MockTransport(responder), **k)):
            estado, detalle = await modulo.enviar_resend(
                api_key="re_super_secreto", remitente="ACMA <no-reply@ejemplo.com>",
                destinatarios=["cliente@example.com"], asunto="Reset",
                html="<p>Reset</p>", texto="Reset")
        self.assertEqual((estado, detalle), ("fallida", "resend:red_ConnectError"))


class ResetConfigTests(unittest.TestCase):
    def test_reset_inmediato_sin_celery_y_sin_stub_en_produccion(self):
        s = (RAIZ / "backend" / "services" / "auth_service.py").read_text(encoding="utf-8")
        desde = s.index("async def solicitar_restablecimiento(")
        hasta = s.index("async def confirmar_restablecimiento(", desde)
        reset = s[desde:hasta]
        self.assertIn('not correo.recuperacion_configurada()', reset)
        self.assertIn('enviar_ahora=True', reset)
        self.assertIn('CORREO_NO_CONFIGURADO', reset)


if __name__ == "__main__":
    unittest.main(verbosity=2)
