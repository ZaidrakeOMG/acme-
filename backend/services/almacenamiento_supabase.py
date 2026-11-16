"""Supabase Storage opcional. Los datos llegan ya cifrados por AlmacenamientoCifrado.

Nunca usar SUPABASE_SECRET_KEY en Flutter, React o un frontend público.
El bucket debe existir y ser PRIVADO; la API FastAPI autoriza el acceso.
"""
from pathlib import PurePosixPath
from urllib.parse import quote

import httpx


class AlmacenamientoSupabase:
    def __init__(self, *, url: str, key: str, bucket: str,
                 transport: httpx.BaseTransport | None = None) -> None:
        if not url.startswith("https://") or not key or not bucket:
            raise ValueError("Se requiere URL HTTPS, clave privada del servidor y bucket")
        self.base = url.rstrip("/")
        self.key = key
        self.bucket = bucket
        self._transport = transport

    def _url_objeto(self, clave: str, *, autenticado: bool = False) -> str:
        if (not clave or clave.startswith("/") or "\\" in clave or
                ".." in PurePosixPath(clave).parts):
            raise ValueError("Ruta de objeto inválida")
        tramo = "object/authenticated" if autenticado else "object"
        return (f"{self.base}/storage/v1/{tramo}/"
                f"{quote(self.bucket, safe='')}/{quote(clave, safe='/')}")

    @property
    def _headers(self) -> dict[str, str]:
        # Las nuevas claves sb_secret_ son opacas, NO son JWT.
        # Enviar Authorization: Bearer sb_secret_ provoca InvalidJWT (HTTP 400).
        # La cabecera apikey es suficiente para claves sb_* en Supabase.
        if self.key.startswith(("sb_secret_", "sb_publishable_")):
            return {"apikey": self.key}
        # Compatibilidad con claves legacy service_role, que SÍ son JWT.
        return {"apikey": self.key, "Authorization": f"Bearer {self.key}"}

    def guardar(self, clave: str, datos: bytes, tipo_contenido: str, *,
                dueno: str | None = None) -> None:
        # El contenido está cifrado por el adaptador externo. No registrar ni los
        # bytes ni la clave secreta en logs.
        headers = {**self._headers, "x-upsert": "true",
                   "content-type": "application/octet-stream"}
        with httpx.Client(timeout=60, transport=self._transport) as cliente:
            respuesta = cliente.post(self._url_objeto(clave), content=datos, headers=headers)
            respuesta.raise_for_status()

    def leer(self, clave: str) -> bytes:
        with httpx.Client(timeout=60, transport=self._transport) as cliente:
            respuesta = cliente.get(self._url_objeto(clave, autenticado=True),
                                    headers=self._headers)
            respuesta.raise_for_status()
            return respuesta.content

    def comprobar(self) -> None:
        """Comprueba que el bucket privado existe sin modificar archivos."""
        with httpx.Client(timeout=10, transport=self._transport) as cliente:
            respuesta = cliente.get(
                f"{self.base}/storage/v1/bucket/{quote(self.bucket, safe='')}",
                headers=self._headers,
            )
            respuesta.raise_for_status()
            metadata = respuesta.json()
            if metadata.get("id", self.bucket) != self.bucket or metadata.get("public") is not False:
                raise RuntimeError(
                    "El bucket de ACMA debe existir y ser PRIVADO; no cargar evidencias públicas"
                )
