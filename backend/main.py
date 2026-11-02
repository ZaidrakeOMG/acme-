"""ACMA — API (FastAPI). Ejecutar desde backend/:  uvicorn main:app --port 8000"""
import logging

from fastapi import FastAPI

from core.config import config
from core.errors import registrar_manejadores
from core.middleware import configurar_cors, instalar_middleware
from routers import (
    alertas, auditoria, auth, catalogos_equipos, catalogos_importar, catalogos_tecnicos, chat, configuracion, contratos,
    activos, caja_chica, clasificacion, erp, folios, formularios, grupos_un, inventario, minutas, notificaciones, oc_activos, prestadores, presupuestos,
    preventivos, push, reasignaciones, seguimiento, sla, bi, sync, tenants, trabajos_especiales, unidades_negocio, usuarios,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(
    title="ACMA API",
    version="0.1.0",
    description="Plataforma SaaS multitenant de gestión de mantenimiento. Fase 1 · P01 Cimientos + P02 Catálogos + P03 Formularios + P04 Folios + P05 Campo, offline y chat + P06 Preventivos y reasignaciones + P07 Minuta, notificaciones y seguimiento + P08 Trabajos especiales + P09 Inventario, costos y activos + P10 Contratos/SLA, alertas y BI.\n\n"
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
               catalogos_tecnicos, catalogos_equipos, catalogos_importar, formularios, folios, chat, sync, push, preventivos, reasignaciones, minutas, seguimiento, clasificacion, notificaciones,
               trabajos_especiales, oc_activos, inventario, caja_chica, presupuestos, erp, activos, sla, bi):
    app.include_router(modulo.router)


@app.get("/api/salud", tags=["Sistema"], summary="Estado del servicio")
async def salud() -> dict:
    return {"estado": "ok", "entorno": config.acma_entorno}
