"""Formato de error estándar: { "codigo": "...", "mensaje": "...", "detalles": [...] }."""
import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError, IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("acma.errores")


class ErrorAPI(Exception):
    def __init__(self, estado: int, codigo: str, mensaje: str, detalles: list[Any] | None = None,
                 cabeceras: dict[str, str] | None = None):
        self.estado = estado
        self.codigo = codigo
        self.mensaje = mensaje
        self.detalles = detalles or []
        self.cabeceras = cabeceras


def no_encontrado(recurso: str = "Recurso") -> ErrorAPI:
    return ErrorAPI(404, "NO_ENCONTRADO", f"{recurso} no encontrado")


def prohibido(mensaje: str = "No tienes permiso para esta operación") -> ErrorAPI:
    return ErrorAPI(403, "PROHIBIDO", mensaje)


def no_autenticado(mensaje: str = "Autenticación requerida") -> ErrorAPI:
    return ErrorAPI(401, "NO_AUTENTICADO", mensaje, cabeceras={"WWW-Authenticate": "Bearer"})


def solicitud_invalida(mensaje: str, detalles: list[Any] | None = None, codigo: str = "SOLICITUD_INVALIDA") -> ErrorAPI:
    return ErrorAPI(422, codigo, mensaje, detalles)


def _cuerpo(codigo: str, mensaje: str, detalles: list[Any]) -> dict[str, Any]:
    return {"codigo": codigo, "mensaje": mensaje, "detalles": detalles}


_CODIGOS_HTTP = {400: "SOLICITUD_INVALIDA", 401: "NO_AUTENTICADO", 403: "PROHIBIDO", 404: "NO_ENCONTRADO",
                 405: "METODO_NO_PERMITIDO", 409: "CONFLICTO", 429: "DEMASIADAS_SOLICITUDES"}


def registrar_manejadores(app: FastAPI) -> None:
    @app.exception_handler(ErrorAPI)
    async def _error_api(_: Request, exc: ErrorAPI) -> JSONResponse:
        return JSONResponse(_cuerpo(exc.codigo, exc.mensaje, exc.detalles), status_code=exc.estado, headers=exc.cabeceras)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        codigo = _CODIGOS_HTTP.get(exc.status_code, "ERROR_HTTP")
        mensaje = exc.detail if isinstance(exc.detail, str) else "Error en la solicitud"
        return JSONResponse(_cuerpo(codigo, mensaje, []), status_code=exc.status_code, headers=getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def _validacion(_: Request, exc: RequestValidationError) -> JSONResponse:
        detalles = [
            {"campo": ".".join(str(p) for p in e.get("loc", []) if p != "body"), "mensaje": e.get("msg", "")}
            for e in exc.errors()
        ]
        return JSONResponse(_cuerpo("VALIDACION", "Datos de entrada inválidos", detalles), status_code=422)

    @app.exception_handler(IntegrityError)
    async def _integridad(_: Request, exc: IntegrityError) -> JSONResponse:
        log.info("Violación de integridad: %s", exc.orig)
        return JSONResponse(_cuerpo("CONFLICTO", "El registro viola una restricción de integridad (duplicado o referencia inválida)", []),
                            status_code=409)

    @app.exception_handler(DBAPIError)
    async def _bd(_: Request, exc: DBAPIError) -> JSONResponse:
        texto = str(exc.orig)
        if "row-level security" in texto or "insufficient_privilege" in texto or "permission denied" in texto:
            log.warning("Operación rechazada por políticas de BD: %s", texto)
            return JSONResponse(_cuerpo("PROHIBIDO", "Operación no permitida por las políticas de acceso", []), status_code=403)
        log.exception("Error de base de datos")
        return JSONResponse(_cuerpo("ERROR_INTERNO", "Error interno del servidor", []), status_code=500)

    @app.exception_handler(Exception)
    async def _general(_: Request, exc: Exception) -> JSONResponse:
        log.exception("Error no controlado", exc_info=exc)
        return JSONResponse(_cuerpo("ERROR_INTERNO", "Error interno del servidor", []), status_code=500)
