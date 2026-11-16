"""Sirve el build React desde FastAPI sin modificar pantallas ni endpoints."""
from pathlib import Path

from fastapi import FastAPI
from starlette.exceptions import HTTPException
from starlette.responses import PlainTextResponse
from starlette.staticfiles import StaticFiles


class SPAStaticFiles(StaticFiles):
    """Fallback de React Router para navegación; no devuelve HTML como API o JS."""

    async def get_response(self, path: str, scope):
        try:
            respuesta = await super().get_response(path, scope)
        except HTTPException as error:
            if error.status_code != 404:
                raise
            respuesta = PlainTextResponse("Not Found", status_code=404)

        primer_segmento = path.lstrip("/").split("/", 1)[0]
        reservado = primer_segmento in {"api", "ws", "docs", "redoc", "openapi.json", ".well-known"}
        es_archivo = bool(Path(path).suffix)

        if scope.get("method", "GET") in {"GET", "HEAD"} and respuesta.status_code == 404 and not reservado and not es_archivo:
            return await super().get_response("index.html", scope)
        return respuesta


def instalar_frontend(app: FastAPI, dist: Path | None = None) -> bool:
    """Integra el build si existe. Durante desarrollo se puede usar Vite igual."""
    raiz = dist or Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if not (raiz / "index.html").is_file():
        return False
    app.mount("/", SPAStaticFiles(directory=str(raiz), html=True), name="frontend")
    return True
