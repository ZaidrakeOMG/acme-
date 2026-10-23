"""Evidencias de formularios: control de calidad de fotos (§6.8.3c), EXIF/GPS, hash y almacenamiento en MinIO."""
from __future__ import annotations

import hashlib
import io
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from PIL import Image, ImageOps, UnidentifiedImageError
from PIL.ExifTags import GPSTAGS, TAGS

from core.errors import ErrorAPI

MIME_IMAGEN = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
MIME_AUDIO = {"audio/webm": "webm", "audio/ogg": "ogg", "audio/mpeg": "mp3", "audio/mp4": "m4a", "audio/wav": "wav", "audio/x-wav": "wav"}
MIME_POR_TIPO_ARCHIVO = {
    "pdf": {"application/pdf"},
    "imagen": set(MIME_IMAGEN),
    "hoja_calculo": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "text/csv", "application/vnd.ms-excel"},
    "documento": {"application/pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "text/plain"},
}
MAX_BYTES_IMAGEN = 25_000_000

# Tabla de cuantización de luminancia del estándar JPEG (IJG). Permite estimar la calidad con que se guardó un JPEG.
_TABLA_LUMINANCIA_STD = [
    16, 11, 10, 16, 24, 40, 51, 61, 12, 12, 14, 19, 26, 58, 60, 55, 14, 13, 16, 24, 40, 57, 69, 56,
    14, 17, 22, 29, 51, 87, 80, 62, 18, 22, 37, 56, 68, 109, 103, 77, 24, 35, 55, 64, 81, 104, 113, 92,
    49, 64, 78, 87, 103, 121, 120, 101, 72, 92, 95, 98, 112, 100, 103, 99,
]


@dataclass
class AnalisisImagen:
    ancho: int
    alto: int
    formato: str
    calidad_jpeg: int | None = None  # 1..100 estimada; None si no es JPEG
    compresion_pct: int | None = None  # 100 - calidad
    exif_timestamp: datetime | None = None
    geolat: float | None = None
    geolng: float | None = None
    problemas: list[str] = field(default_factory=list)


def estimar_calidad_jpeg(imagen: Image.Image) -> int | None:
    tablas = getattr(imagen, "quantization", None)
    if not tablas or 0 not in tablas:
        return None
    tabla = list(tablas[0])
    if len(tabla) != 64:
        return None
    escala = sum(tabla) / sum(_TABLA_LUMINANCIA_STD) * 100  # porcentaje de escalado respecto al estándar
    if escala <= 0:
        return 100
    calidad = 5000 / escala if escala >= 100 else (200 - escala) / 2
    return int(max(1, min(100, round(calidad))))


def _gps_a_decimal(valor, ref: str | None) -> float | None:
    try:
        grados, minutos, segundos = (float(x) for x in valor)
    except (TypeError, ValueError):
        return None
    decimal = grados + minutos / 60 + segundos / 3600
    if ref in ("S", "W"):
        decimal = -decimal
    return round(decimal, 7)


def analizar_imagen(contenido: bytes) -> AnalisisImagen:
    try:
        imagen = Image.open(io.BytesIO(contenido))
        imagen.load()
    except (UnidentifiedImageError, OSError):
        raise ErrorAPI(422, "IMAGEN_INVALIDA", "El archivo no es una imagen válida")
    orientada = ImageOps.exif_transpose(imagen) or imagen
    analisis = AnalisisImagen(ancho=orientada.width, alto=orientada.height, formato=(imagen.format or "").lower())
    if analisis.formato == "jpeg":
        analisis.calidad_jpeg = estimar_calidad_jpeg(imagen)
        if analisis.calidad_jpeg is not None:
            analisis.compresion_pct = 100 - analisis.calidad_jpeg
    try:
        exif = imagen.getexif()
    except Exception:  # pragma: no cover - EXIF corrupto
        exif = None
    if exif:
        etiquetas = {TAGS.get(k, k): v for k, v in exif.items()}
        for clave in ("DateTimeOriginal", "DateTime"):
            crudo = etiquetas.get(clave)
            if crudo is None:
                try:
                    crudo = exif.get_ifd(0x8769).get(0x9003)  # DateTimeOriginal en el sub-IFD EXIF
                except Exception:
                    crudo = None
            if isinstance(crudo, str):
                try:
                    analisis.exif_timestamp = datetime.strptime(crudo[:19], "%Y:%m:%d %H:%M:%S")
                    break
                except ValueError:
                    continue
        try:
            gps = exif.get_ifd(0x8825)
        except Exception:
            gps = None
        if gps:
            datos = {GPSTAGS.get(k, k): v for k, v in gps.items()}
            analisis.geolat = _gps_a_decimal(datos.get("GPSLatitude"), datos.get("GPSLatitudeRef"))
            analisis.geolng = _gps_a_decimal(datos.get("GPSLongitude"), datos.get("GPSLongitudeRef"))
    return analisis


def verificar_calidad(analisis: AnalisisImagen, bytes_: int, calidad: dict[str, Any]) -> list[str]:
    """Mínimos configurados por campo (con los defaults globales ya resueltos). Devuelve los problemas."""
    problemas = []
    if bytes_ < calidad["tamano_minimo_kb"] * 1024:
        problemas.append(f"La foto pesa {bytes_ // 1024} KB; el mínimo es {calidad['tamano_minimo_kb']} KB")
    if analisis.ancho < calidad["resolucion_minima_ancho"] or analisis.alto < calidad["resolucion_minima_alto"]:
        problemas.append(f"Resolución {analisis.ancho}×{analisis.alto} px; el mínimo es "
                         f"{calidad['resolucion_minima_ancho']}×{calidad['resolucion_minima_alto']} px")
    if analisis.compresion_pct is not None and analisis.compresion_pct > calidad["compresion_maxima_pct"]:
        problemas.append(f"La foto está comprimida al {analisis.compresion_pct}%; el máximo es {calidad['compresion_maxima_pct']}%")
    return problemas


def hash_sha256(contenido: bytes) -> str:
    return hashlib.sha256(contenido).hexdigest()


def clave_archivo(duenio: uuid.UUID | str, respuesta_id: uuid.UUID, campo: str, extension: str, sufijo: str = "") -> str:
    return f"evidencias/{duenio}/{respuesta_id}/{campo}-{uuid.uuid4().hex[:10]}{sufijo}.{extension}"


def extension_de(mime: str, nombre: str) -> str:
    if mime in MIME_IMAGEN:
        return MIME_IMAGEN[mime]
    if mime in MIME_AUDIO:
        return MIME_AUDIO[mime]
    if mime == "application/pdf":
        return "pdf"
    return (nombre.rsplit(".", 1)[-1].lower() if "." in nombre else "bin")[:8]
