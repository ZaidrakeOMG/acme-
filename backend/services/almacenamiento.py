"""Almacenamiento de archivos S3-compatible detrás de una interfaz (MinIO en dev, memoria en pruebas)."""
import io
from functools import lru_cache
from typing import Protocol

from core.config import config


class Almacenamiento(Protocol):
    def guardar(self, clave: str, datos: bytes, tipo_contenido: str) -> None: ...
    def leer(self, clave: str) -> bytes: ...


class AlmacenamientoMemoria:
    def __init__(self) -> None:
        self.objetos: dict[str, tuple[bytes, str]] = {}

    def guardar(self, clave: str, datos: bytes, tipo_contenido: str) -> None:
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

    def guardar(self, clave: str, datos: bytes, tipo_contenido: str) -> None:
        self.cliente.put_object(self.bucket, clave, io.BytesIO(datos), len(datos), content_type=tipo_contenido)

    def leer(self, clave: str) -> bytes:
        respuesta = self.cliente.get_object(self.bucket, clave)
        try:
            return respuesta.read()
        finally:
            respuesta.close()
            respuesta.release_conn()


@lru_cache
def obtener_almacenamiento() -> Almacenamiento:
    if config.almacenamiento_modo == "memoria":
        return AlmacenamientoMemoria()
    return AlmacenamientoMinio()
