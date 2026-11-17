"""Comprobación de iconos ACMA para web/PWA/Android (sin dependencias)."""
from __future__ import annotations

import struct
import unittest
import xml.etree.ElementTree as ET
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "frontend" / "public"
PNG_SIG = b"\x89PNG\r\n\x1a\n"


def _png(path: Path) -> tuple[int, int, bytes]:
    data = path.read_bytes()
    if not data.startswith(PNG_SIG):
        raise AssertionError(f"{path.name}: firma PNG invalida")
    pos, contenido = 8, bytearray()
    ancho = alto = 0
    while pos + 12 <= len(data):
        largo = struct.unpack(">I", data[pos:pos + 4])[0]
        tipo = data[pos + 4:pos + 8]
        fin = pos + 12 + largo
        if fin > len(data):
            raise AssertionError(f"{path.name}: chunk truncado")
        chunk = data[pos + 8:pos + 8 + largo]
        crc = struct.unpack(">I", data[pos + 8 + largo:fin])[0]
        if zlib.crc32(tipo + chunk) & 0xFFFFFFFF != crc:
            raise AssertionError(f"{path.name}: CRC no coincide")
        if tipo == b"IHDR":
            ancho, alto, profundidad, color, compresion, filtro, entrelazado = struct.unpack(">IIBBBBB", chunk)
            if (profundidad, color, compresion, filtro, entrelazado) != (8, 3, 0, 0, 0):
                raise AssertionError(f"{path.name}: formato inesperado")
        elif tipo == b"IDAT":
            contenido.extend(chunk)
        elif tipo == b"IEND":
            break
        pos = fin
    pixeles = zlib.decompress(contenido)
    if len(pixeles) != (ancho + 1) * alto:
        raise AssertionError(f"{path.name}: datos de imagen incompletos")
    if any(pixeles[fila * (ancho + 1)] != 0 for fila in range(alto)):
        raise AssertionError(f"{path.name}: filtro no esperado")
    return ancho, alto, pixeles


class TestMarcaAcma(unittest.TestCase):
    def test_svg_de_la_marca_oficial(self):
        ruta = PUBLIC / "icono.svg"
        raiz = ET.parse(ruta).getroot()
        self.assertEqual(raiz.attrib["viewBox"], "0 0 1254 1254")
        texto = ruta.read_text(encoding="utf-8")
        self.assertIn('fill="#222222"', texto)
        self.assertIn('fill="#ac092a"', texto)
        self.assertIn('aria-label="ACMA"', texto)

    def test_iconos_png_pwa_y_android(self):
        for size in (192, 512):
            with self.subTest(size=size):
                ancho, alto, data = _png(PUBLIC / f"icono-{size}.png")
                self.assertEqual((ancho, alto), (size, size))
                self.assertIn(2, data)
                self.assertIn(3, data)
        config = (ROOT / "mobile_flutter" / "pubspec.yaml").read_text(encoding="utf-8")
        self.assertIn("image_path: ../frontend/public/icono-512.png", config)
        vite = (ROOT / "frontend" / "vite.config.ts").read_text(encoding="utf-8")
        self.assertIn("icono-192.png", vite)
        self.assertIn("icono-512.png", vite)


if __name__ == "__main__":
    unittest.main(verbosity=2)
