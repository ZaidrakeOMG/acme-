"""Políticas CSP diferenciadas: API estricta y SPA React funcional.

Un único default-src 'none' aplicado a toda la app impedía cargar los
bundles de Vite en /assets y provocaba una pantalla completamente blanca.
La API sigue usando la política restrictiva original; los documentos web
solo pueden cargar recursos de los orígenes necesarios.
"""

CSP_API = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"

# Swagger/ReDoc originales, utilizados únicamente fuera de producción.
CSP_DOCS = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "img-src 'self' data: https://fastapi.tiangolo.com; "
    "frame-ancestors 'none'"
)

# React/Vite carga JS y CSS desde /assets, PWA desde /sw.js, imágenes
# locales y datos QR. Las peticiones API son same-origin; los websockets
# se usan en campo/chat. No se permite eval ni inline JavaScript.
CSP_WEB = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob: https:; "
    "font-src 'self' data:; "
    "connect-src 'self' ws: wss:; "
    "worker-src 'self' blob:; "
    "media-src 'self' blob:; "
    "frame-src 'self' blob:; "
    "manifest-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)


def politica_csp_para_ruta(ruta: str, *, es_produccion: bool) -> str:
    if ruta.startswith(("/docs", "/redoc")) and not es_produccion:
        return CSP_DOCS
    if ruta == "/openapi.json" or ruta.startswith(("/api/", "/ws/")):
        return CSP_API
    return CSP_WEB
