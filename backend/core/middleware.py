"""Middleware HTTP: contexto RLS desde el JWT, cabeceras de seguridad y bitácora de accesos a la API."""
import logging
import time
import uuid
from datetime import UTC, datetime

import jwt
from fastapi import FastAPI, Request
from sqlalchemy import insert

from core.config import config
from core.csp import politica_csp_para_ruta
from core.rls import ContextoRLS
from core.security import TIPO_ACCESO, decodificar_jwt

log = logging.getLogger("acma.middleware")

def _uuid_o_none(valor: str | None) -> uuid.UUID | None:
    return uuid.UUID(valor) if valor else None


def contexto_desde_claims(claims: dict) -> ContextoRLS:
    return ContextoRLS(
        usuario_id=_uuid_o_none(claims.get("sub")),
        tenant_id=_uuid_o_none(claims.get("tenant_id")),
        prestador_id=_uuid_o_none(claims.get("prestador_id")),
        rol=claims.get("rol"),
    )


def ip_cliente(request: Request) -> str:
    return request.client.host if request.client else "desconocida"


def instalar_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def _acma(request: Request, call_next):
        inicio = time.perf_counter()
        request.state.claims = None
        request.state.contexto_rls = ContextoRLS()

        autorizacion = request.headers.get("authorization", "")
        if autorizacion.lower().startswith("bearer "):
            try:
                claims = decodificar_jwt(autorizacion[7:].strip(), TIPO_ACCESO)
                request.state.claims = claims
                request.state.contexto_rls = contexto_desde_claims(claims)
            except (jwt.PyJWTError, ValueError):
                pass  # usuario_actual() responderá 401

        respuesta = await call_next(request)

        ruta = request.url.path
        # La CSP de API niega scripts; la SPA React requiere cargar el bundle
        # propio de Vite. Nunca aplicar default-src 'none' al HTML de /
        # porque eso deja la página blanca aun cuando FastAPI responde 200.
        respuesta.headers["Content-Security-Policy"] = politica_csp_para_ruta(
            ruta, es_produccion=config.es_produccion
        )
        if config.es_produccion:  # en HTTP local un HSTS cacheado dejaria el navegador exigiendo TLS
            respuesta.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        respuesta.headers["X-Frame-Options"] = "DENY"
        respuesta.headers["X-Content-Type-Options"] = "nosniff"
        respuesta.headers["Referrer-Policy"] = "no-referrer"
        respuesta.headers["Permissions-Policy"] = "camera=(self), geolocation=(self), microphone=()"
        respuesta.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        respuesta.headers["Cross-Origin-Resource-Policy"] = "same-origin"
        if ruta.startswith("/api/"):
            respuesta.headers.setdefault("Cache-Control", "no-store")
            await _registrar_acceso(request, respuesta.status_code, inicio)
        return respuesta


async def _registrar_acceso(request: Request, codigo: int, inicio: float) -> None:
    # Import diferido: evita ciclo core.db -> core.middleware en pruebas que sustituyen el engine.
    from core.db import nueva_sesion
    from models.auditoria import AuditAccesoAPI

    contexto: ContextoRLS = request.state.contexto_rls
    try:
        async with nueva_sesion(ContextoRLS()) as sesion:
            await sesion.execute(
                insert(AuditAccesoAPI).values(
                    id=uuid.uuid4(),
                    created_at=datetime.now(UTC),
                    metodo=request.method,
                    ruta=request.url.path[:300],
                    codigo_respuesta=codigo,
                    duracion_ms=int((time.perf_counter() - inicio) * 1000),
                    usuario_id=contexto.usuario_id,
                    tenant_id=contexto.tenant_id,
                    prestador_id=contexto.prestador_id,
                    ip_origen=ip_cliente(request),
                    user_agent=(request.headers.get("user-agent") or "")[:500],
                )
            )
            await sesion.commit()
    except Exception:  # la bitácora nunca debe tumbar la respuesta
        log.exception("No se pudo registrar el acceso a la API")


def configurar_cors(app: FastAPI) -> None:
    from fastapi.middleware.cors import CORSMiddleware

    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.lista_cors,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        # CABECERA_CSRF (P11a): sin ella el navegador no podria mandar el doble envio desde otro origen.
        allow_headers=["Authorization", "Content-Type", "X-ACMA-CSRF"],
        max_age=600,
    )
