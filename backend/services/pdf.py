"""PDF de minutas y cotizaciones. Motor principal WeasyPrint (HTML → PDF con el diseño del prestador); si WeasyPrint no puede
cargarse (en Windows requiere el runtime GTK/Pango) se usa un generador mínimo en Python puro que conserva el texto y la
estructura. El SHA-256 del archivo se guarda como firma de integridad (`hash_pdf`)."""
import hashlib
import html as _html
import logging
import re
import zlib
from datetime import UTC, datetime

log = logging.getLogger("acma.pdf")
_MOTOR: str | None = None


def motor() -> str:
    global _MOTOR
    if _MOTOR is None:
        import contextlib
        import io

        try:
            with contextlib.redirect_stderr(io.StringIO()):  # WeasyPrint imprime su diagnóstico de librerías nativas en stderr
                import weasyprint  # noqa: F401

            _MOTOR = "weasyprint"
        except Exception as e:  # noqa: BLE001 — OSError por librerías nativas ausentes
            log.warning("WeasyPrint no disponible (%s); se usa el generador PDF mínimo", str(e).splitlines()[0][:120])
            _MOTOR = "minimo"
    return _MOTOR


def html_a_pdf(html: str) -> bytes:
    if motor() == "weasyprint":
        from weasyprint import HTML

        return HTML(string=html, base_url=".").write_pdf()
    return _pdf_minimo(_html_a_lineas(html))


def sha256(datos: bytes) -> str:
    return hashlib.sha256(datos).hexdigest()


# ------------------------------------------------------------ generador mínimo

def _html_a_lineas(html: str) -> list[tuple[str, str]]:
    """Convierte el HTML en líneas (estilo, texto): h1/h2/h3/p/li/td se vuelven líneas; el resto de etiquetas se quita."""
    t = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.S | re.I)
    t = re.sub(r"<head>.*?</head>", "", t, flags=re.S | re.I)
    lineas: list[tuple[str, str]] = []
    for m in re.finditer(r"<(h1|h2|h3|p|li|tr|div)[^>]*>(.*?)</\1>|<br\s*/?>", t, flags=re.S | re.I):
        etiqueta = (m.group(1) or "br").lower()
        texto = _html.unescape(re.sub(r"<[^>]+>", " ", m.group(2) or "")).strip()
        texto = re.sub(r"\s+", " ", texto)
        if etiqueta == "tr":
            texto = " | ".join(x.strip() for x in re.split(r"\s{2,}\|?\s*", texto) if x.strip()) if texto else ""
        if texto or etiqueta == "br":
            estilo = "h1" if etiqueta == "h1" else "h2" if etiqueta in ("h2", "h3") else "p"
            lineas.append((estilo, ("• " + texto) if etiqueta == "li" else texto))
    if not lineas:
        texto = _html.unescape(re.sub(r"<[^>]+>", " ", t))
        lineas = [("p", l.strip()) for l in texto.splitlines() if l.strip()]
    return lineas


def _escapar_pdf(s: str) -> str:
    s = s.encode("cp1252", "replace").decode("cp1252")
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _envolver(texto: str, ancho: int) -> list[str]:
    palabras, lineas, actual = texto.split(" "), [], ""
    for p in palabras:
        if len(actual) + len(p) + 1 > ancho and actual:
            lineas.append(actual)
            actual = p
        else:
            actual = f"{actual} {p}".strip()
    if actual:
        lineas.append(actual)
    return lineas or [""]


def _pdf_minimo(lineas: list[tuple[str, str]]) -> bytes:
    """PDF 1.4 válido con Helvetica, varias páginas, texto en WinAnsi (sin dependencias)."""
    ancho_pt, alto_pt, margen = 595, 842, 50
    paginas: list[list[str]] = []
    y = alto_pt - margen
    ops: list[str] = []
    for estilo, texto in lineas:
        tam, salto, ancho_chars = {"h1": (16, 24, 60), "h2": (13, 19, 75), "p": (10, 14, 95)}[estilo]
        fuente = "/F2" if estilo != "p" else "/F1"
        for frag in _envolver(texto, ancho_chars):
            if y < margen + salto:
                paginas.append(ops)
                ops, y = [], alto_pt - margen
            ops.append(f"BT {fuente} {tam} Tf {margen} {y:.1f} Td ({_escapar_pdf(frag)}) Tj ET")
            y -= salto
        if estilo != "p":
            y -= 4
    paginas.append(ops)

    objetos: list[bytes] = []

    def agregar(contenido: bytes) -> int:
        objetos.append(contenido)
        return len(objetos)

    fuente1 = agregar(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    fuente2 = agregar(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
    ids_paginas: list[int] = []
    padre = len(objetos) + 1 + 2 * len(paginas)  # el objeto /Pages va al final
    for ops_pagina in paginas:
        flujo = zlib.compress("\n".join(ops_pagina).encode("cp1252", "replace"))
        contenido = agregar(b"<< /Length " + str(len(flujo)).encode() + b" /Filter /FlateDecode >>\nstream\n" + flujo + b"\nendstream")
        pagina = agregar(f"<< /Type /Page /Parent {padre} 0 R /MediaBox [0 0 {ancho_pt} {alto_pt}] /Contents {contenido} 0 R "
                         f"/Resources << /Font << /F1 {fuente1} 0 R /F2 {fuente2} 0 R >> >> >>".encode())
        ids_paginas.append(pagina)
    pages = agregar(f"<< /Type /Pages /Kids [{' '.join(f'{i} 0 R' for i in ids_paginas)}] /Count {len(ids_paginas)} >>".encode())
    assert pages == padre
    catalogo = agregar(f"<< /Type /Catalog /Pages {pages} 0 R >>".encode())
    fecha = datetime.now(UTC).strftime("D:%Y%m%d%H%M%SZ")
    info = agregar(f"<< /Producer (ACMA PDF minimo) /CreationDate ({fecha}) >>".encode())

    salida = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    posiciones = []
    for i, obj in enumerate(objetos, start=1):
        posiciones.append(len(salida))
        salida += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(salida)
    salida += f"xref\n0 {len(objetos) + 1}\n0000000000 65535 f \n".encode()
    for p in posiciones:
        salida += f"{p:010d} 00000 n \n".encode()
    salida += f"trailer\n<< /Size {len(objetos) + 1} /Root {catalogo} 0 R /Info {info} 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(salida)
