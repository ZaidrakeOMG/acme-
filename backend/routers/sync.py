"""Sincronización offline (§6.2 capa 3): paquete incremental de catálogos, lote de mutaciones idempotente y evidencias en dos pasos."""
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile

from core.dependencias import DB, Actor, ActorActual, requiere_rol
from models.base import Rol
from schemas.comun import RESPUESTAS_ERROR
from schemas.formularios import EvidenciaSalida
from schemas.sync import ConflictoSalida, IniciarEvidenciaEntrada, IniciarEvidenciaSalida, LoteMutaciones, ResultadoMutacionSalida
from services import chat_service, sync_service

router = APIRouter(prefix="/api/sync", tags=["Sincronización offline"], responses=RESPUESTAS_ERROR)


@router.get("/catalogos", summary="Paquete incremental de catálogos (§6.2 capa 3)",
            description="Solo registros con `updated_at > desde`. Operador: UNs asignadas, equipos (con contrato activo), familias/tipos, tipos de falla, "
                        "severidades y formularios de captura. Técnico: folios asignados con su formulario de atención resuelto, formularios de "
                        "preventivo, refacciones (P09) y biblioteca (Fase 2). Incluye bajas lógicas (`activo = false`).")
async def catalogos(db: DB, actor: ActorActual, desde: datetime | None = None, dispositivo_id: str | None = Query(default=None, max_length=120),
                    version_app: str | None = Query(default=None, max_length=40), plataforma: str | None = Query(default=None, max_length=60)):
    salida = await sync_service.catalogos(db, actor, desde, dispositivo_id, version_app, plataforma)
    await db.commit()
    return salida


@router.post("/mutaciones", response_model=list[ResultadoMutacionSalida], summary="Aplicar la cola offline",
             description="Lote ordenado de operaciones con `id_cliente`; se aplican en orden, idempotentes, y una rechazada no detiene a las siguientes. "
                         "Capturas en campo → client-wins (se conserva `timestamp_dispositivo` como hora real); conflictos en `sincronizacion_conflictos`.")
async def mutaciones(lote: LoteMutaciones, request: Request, db: DB, actor: ActorActual):
    resultados, publicar = await sync_service.aplicar_mutaciones(db, actor, lote, request)
    await db.commit()
    for mensaje, nombre in publicar:
        await chat_service.publicar_mensaje(db, mensaje, nombre)
    return [ResultadoMutacionSalida(**r) for r in resultados]


@router.post("/evidencias/iniciar", response_model=IniciarEvidenciaSalida, summary="Paso 1: declarar una evidencia (metadatos + hash)",
             description="Si el hash ya existe en la respuesta o el `id_cliente` ya se procesó, no se vuelve a subir.")
async def iniciar_evidencia(datos: IniciarEvidenciaEntrada, db: DB, actor: ActorActual):
    salida = await sync_service.iniciar_evidencia(db, actor, datos)
    await db.commit()
    return IniciarEvidenciaSalida(**salida)


@router.put("/evidencias/{id_cliente}/archivo", response_model=EvidenciaSalida, summary="Paso 2: subir el binario (reintentable)")
async def subir_evidencia(id_cliente: UUID, request: Request, db: DB, actor: ActorActual, archivo: UploadFile = File(...), respuesta_id: str = Form(...),
                          campo_clave: str = Form(...), hash_sha256: str | None = Form(default=None), etiqueta: str | None = Form(default=None),
                          geolat: float | None = Form(default=None), geolng: float | None = Form(default=None),
                          dispositivo_id: str | None = Form(default=None), timestamp_dispositivo: datetime | None = Form(default=None)):
    from routers.formularios import _evidencia_salida

    contenido = await archivo.read()
    e, resultado = await sync_service.subir_evidencia(db, actor, id_cliente, respuesta_id, campo_clave, contenido, archivo.filename or "evidencia",
                                                      archivo.content_type or "application/octet-stream", hash_sha256, etiqueta, geolat, geolng,
                                                      dispositivo_id, timestamp_dispositivo, request)
    await db.commit()
    salida = _evidencia_salida(e, {"resultado": resultado})
    return salida


@router.get("/conflictos", response_model=list[ConflictoSalida], summary="Conflictos de sincronización registrados")
async def conflictos(db: DB, actor: Actor = Depends(requiere_rol(*Rol)), limite: int = Query(default=100, ge=1, le=1000)):
    return [ConflictoSalida.model_validate(c) for c in await sync_service.conflictos_de(db, actor, limite)]
