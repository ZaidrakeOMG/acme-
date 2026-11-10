"""ACMA — API (FastAPI). Ejecutar desde backend/:  uvicorn main:app --port 8000"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response

from core.config import config
from core.errors import registrar_manejadores
from core.middleware import configurar_cors, instalar_middleware
from core.observabilidad import configurar_logs, estado_dependencias
from routers import (
    alertas, auditoria, auth, biblioteca, capacitacion, catalogos_equipos, catalogos_importar,
    catalogos_tecnicos, chat, configuracion, contratos, mensajeria, operacion,
    activos, caja_chica, clasificacion, erp, folios, formularios, grupos_un, inventario, minutas, notificaciones, oc_activos, prestadores, presupuestos,
    preventivos, push, reasignaciones, seguimiento, sla, bi, sync, tenants, trabajos_especiales, unidades_negocio, usuarios,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
configurar_logs()  # P11a: en produccion (LOG_JSON=true) deja una linea JSON por evento


@asynccontextmanager
async def ciclo_de_vida(_: FastAPI):
    # uvicorn y gunicorn rehacen su configuracion de logs DESPUES de importar este modulo, y entonces cada linea
    # sale dos veces (su manejador y el de la raiz). Al arrancar se vuelve a aplicar la nuestra y queda una sola.
    configurar_logs()
    yield


app = FastAPI(
    lifespan=ciclo_de_vida,
    title="ACMA API",
    version="0.1.0",
    description="Plataforma SaaS multitenant de gestión de mantenimiento. Fase 1 · P01 Cimientos + P02 Catálogos + P03 Formularios + P04 Folios + P05 Campo, offline y chat + P06 Preventivos y reasignaciones + P07 Minuta, notificaciones y seguimiento + P08 Trabajos especiales + P09 Inventario, costos y activos + P10 Contratos/SLA, alertas y BI + P11a Endurecimiento. Segunda etapa · F2-01 Capacitación y biblioteca + F2-02 WhatsApp y SMS + F2-03 Operaciones en tiempo real.\n\n"
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
               trabajos_especiales, oc_activos, inventario, caja_chica, presupuestos, erp, activos, sla, bi,
               capacitacion, biblioteca, mensajeria, operacion):
    app.include_router(modulo.router)

# F2-03: el WebSocket del tablero va fuera de `/api` (como el del chat de P05), por el proxy de desarrollo.
app.include_router(operacion.router_ws)


@app.get("/api/salud", tags=["Sistema"], summary="Estado del servicio",
         description="Comprobacion ligera: dice que el proceso atiende peticiones. La usa el healthcheck del "
                     "contenedor, asi que no consulta dependencias: si Redis se cae, no hay que reiniciar la API.")
async def salud() -> dict:
    return {"estado": "ok", "entorno": config.acma_entorno, "version": app.version}


@app.get("/api/salud/detalle", tags=["Sistema"], summary="Estado de las dependencias",
         description="Base de datos, Redis, almacenamiento de archivos y Celery, cada uno con su limite de tiempo. "
                     "Responde 503 si alguna falla: es el endpoint que vigila el monitoreo (P11a).")
async def salud_detalle(respuesta: Response) -> dict:
    estado = await estado_dependencias()
    if estado["estado"] != "ok":
        respuesta.status_code = 503
    return {**estado, "entorno": config.acma_entorno, "version": app.version}
