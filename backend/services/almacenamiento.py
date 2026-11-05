"""Almacenamiento de archivos S3-compatible detrás de una interfaz (MinIO en dev, memoria en pruebas).

P11a · cifrado en reposo: nada se escribe en claro. `AlmacenamientoCifrado` envuelve al backend y cifra cada objeto
con AES-256-GCM usando una llave derivada por dueño (tenant, prestador o plataforma), como pide el diseño §2.5
«archivos en Object Storage con llaves por tenant». El dueño se declara al guardar y viaja en el sobre, así que leer
no necesita saberlo. Lo escrito antes de P11a sigue legible porque el sobre se detecta por su marca.
"""
import io
from functools import lru_cache
from typing import Protocol

from core.config import config
from core.security import cifrar_archivo, descifrar_archivo


class Almacenamiento(Protocol):
    def guardar(self, clave: str, datos: bytes, tipo_contenido: str, *, dueno: str | None = None) -> None: ...
    def leer(self, clave: str) -> bytes: ...


class AlmacenamientoMemoria:
    def __init__(self) -> None:
        self.objetos: dict[str, tuple[bytes, str]] = {}

    def guardar(self, clave: str, datos: bytes, tipo_contenido: str, *, dueno: str | None = None) -> None:
        self.objetos[clave] = (datos, tipo_contenido)

    def leer(self, clave: str) -> bytes:
        return self.objetos[clave][0]


class AlmacenamientoMinio:
    def __init__(self) -> None:
        from minio import Minio

        self.cliente = Minio(config.minio_endpoint, access_key=config.minio_root_user,
                             secret_key=config.minio_root_password, secure=config.minio_seguro)
        self.bucket = config.minio_bucket
        if not self.cliente.bucket_exists(self.bucket):
            self.cliente.make_bucket(self.bucket)

    def guardar(self, clave: str, datos: bytes, tipo_contenido: str, *, dueno: str | None = None) -> None:
        self.cliente.put_object(self.bucket, clave, io.BytesIO(datos), len(datos), content_type=tipo_contenido)

    def leer(self, clave: str) -> bytes:
        respuesta = self.cliente.get_object(self.bucket, clave)
        try:
            return respuesta.read()
        finally:
            respuesta.close()
            respuesta.release_conn()


class AlmacenamientoCifrado:
    """Cifra al guardar y descifra al leer; el backend solo ve bytes opacos."""

    def __init__(self, backend: Almacenamiento) -> None:
        self.backend = backend

    def guardar(self, clave: str, datos: bytes, tipo_contenido: str, *, dueno: str | None = None) -> None:
        self.backend.guardar(clave, cifrar_archivo(datos, clave_objeto=clave, dueno=dueno), tipo_contenido)

    def leer(self, clave: str) -> bytes:
        return descifrar_archivo(self.backend.leer(clave), clave_objeto=clave)


def dueno_de(tenant_id=None, prestador_id=None) -> str | None:
    """Dueño de la llave de cifrado: el cliente cuando el archivo es suyo, el prestador cuando no hay cliente.

    Devuelve None para los archivos de la plataforma (correo saliente, por ejemplo), que usan la llave general.
    """
    duenio = tenant_id or prestador_id
    return str(duenio) if duenio else None


@lru_cache
def obtener_almacenamiento() -> Almacenamiento:
    backend = AlmacenamientoMemoria() if config.almacenamiento_modo == "memoria" else AlmacenamientoMinio()
    return AlmacenamientoCifrado(backend)
