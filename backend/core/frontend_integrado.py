"""Sirve el build de React desde FastAPI sin modificar rutas ni componentes."""
from pathlib import Path

from fastapi import FastAPI
from starlette.exceptions import HTTPException
from starlette.staticfiles import StaticFiles


class SPAStaticFiles(StaticFiles):
    """Fallback a index.html solo para páginas de React, nunca para APIs ni assets."""

    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except HTTPException as error:
            reservado = path.split("/", 1)[0] in {"api", "ws", "docs", "redoc", "openapi.json"}
            if error.status_code != 404 or reservado or Path(path).suffix:
                raise
            return await super().get_response("index.html", scope)


def instalar_frontend(app: FastAPI, dist: Path | None = None) -> bool:
    """Integra el build si existe; en desarrollo Vite sigue funcionando igual."""
    raiz = dist or Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if not (raiz / "index.html").is_file():
        return False
    app.mount("/", SPAStaticFiles(directory=str(raiz), html=True), name="frontend")
    return True
