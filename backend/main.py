"""ACMA — API (FastAPI). Ejecutar desde backend/:  uvicorn main:app --port 8000"""
import logging

from fastapi import FastAPI

from core.config import config
from core.errors import registrar_manejadores
from core.middleware import configurar_cors, instalar_middleware
from routers import (
    alertas, auditoria, auth, catalogos_equipos, catalogos_importar, catalogos_tecnicos, configuracion, contratos,
    folios, formularios, grupos_un, prestadores, tenants, unidades_negocio, usuarios,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(
    title="ACMA API",
    version="0.1.0",
    description="Plataforma SaaS multitenant de gestión de mantenimiento. Fase 1 · P01 Cimientos + P02 Catálogos + P03 Formularios + P04 Folios.\n\n"
                "Errores con formato estándar `{codigo, mensaje, detalles}`. Autenticación Bearer JWT (15 min) "
                "con refresh rotativo (7 días) y MFA TOTP para roles críticos.",
    docs_url=None if config.es_produccion else "/docs",
    redoc_url=None if config.es_produccion else "/redoc",
    openapi_url=None if config.es_produccion else "/openapi.json",
)

registrar_manejadores(app)
instalar_middleware(app)
configurar_cors(app)

for modulo in (auth, usuarios, tenants, prestadores, unidades_negocio, grupos_un, contratos, alertas, configuracion, auditoria,
               catalogos_tecnicos, catalogos_equipos, catalogos_importar, formularios, folios):
    app.include_router(modulo.router)


@app.get("/api/salud", tags=["Sistema"], summary="Estado del servicio")
async def salud() -> dict:
    return {"estado": "ok", "entorno": config.acma_entorno}
