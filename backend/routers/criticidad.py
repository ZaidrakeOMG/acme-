"""Criticidad de activos, modos de falla y mitigaciones (ISO 55000, §6.9.3). F2-05."""
from dataclasses import replace
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Query, Request

from core.dependencias import DB, ActorActual
from core.errors import ErrorAPI, no_encontrado
from models.criticidad import ActivoModoFalla, ActivoRiesgoMitigacion, MotivoEvaluacion
from schemas.comun import RESPUESTAS_ERROR
from schemas.criticidad import (
    AceptarSugerencias, AjusteManualEntrada, ConfiguracionCambios, ConfiguracionSalida, CriticidadSalida,
    EstadoMitigacionEntrada, EvaluacionEntrada, EvaluacionHistorial, EvaluacionMasivaEntrada, FilaRegistro,
    MitigacionEntrada, MitigacionPendiente, MitigacionSalida, ModoFallaCambios, ModoFallaEntrada, ModoFallaSalida,
    ResumenCriticidad, SugerenciaModoFalla,
)
from services import criticidad_service as svc
from services import riesgo_service as riesgo

router = APIRouter(prefix="/api/criticidad", tags=["Criticidad de activos (ISO 55000)"], responses=RESPUESTAS_ERROR)
router_modos = APIRouter(prefix="/api/modos-falla", tags=["Modos de falla (FMEA)"], responses=RESPUESTAS_ERROR)
router_mitigaciones = APIRouter(prefix="/api/mitigaciones", tags=["Mitigación de riesgo"], responses=RESPUESTAS_ERROR)


def _tenant_de(actor, tenant_id: UUID | None) -> UUID:
    destino = tenant_id if (tenant_id and (actor.es_superadmin or actor.dominio.value != "tenant")) else actor.tenant_id
    if destino is None:
        raise ErrorAPI(422, "TENANT_REQUERIDO", "Indica el cliente (tenant_id)")
    return destino


# ------------------------------------------------------------------ configuración
@router.get("/configuracion", response_model=ConfiguracionSalida, summary="Pesos, escalas y rangos del cliente",
            description="Los valores literales de §6.9.3 vienen como default: operacional 30 %, seguridad 35 %, "
                        "económico 25 % e imagen 10 %, con los rangos de nivel A 80–100, B 50–79, C 20–49 y "
                        "D 0–19. Se crean la primera vez que se consultan.")
async def configuracion(db: DB, actor: ActorActual, tenant_id: UUID | None = None):
    svc._exigir(actor, svc.CONSULTAN, "consulta la configuración de criticidad")
    cfg = await svc.configuracion(db, _tenant_de(actor, tenant_id))
    await db.commit()
    await db.refresh(cfg)
    return cfg


@router.put("/configuracion", response_model=ConfiguracionSalida, summary="Cambiar pesos, escalas y rangos",
            description="Solo el Admin empresa. Los cuatro pesos tienen que sumar 100 %: si no, el índice deja de "
                        "significar lo que dice (422 PESOS_NO_SUMAN_100).")
async def guardar_configuracion(datos: ConfiguracionCambios, request: Request, db: DB, actor: ActorActual,
                                tenant_id: UUID | None = None):
    cuerpo = datos.model_dump(exclude_unset=True)
    if cuerpo.get("pesos_json") is not None:
        cuerpo["pesos_json"] = dict(cuerpo["pesos_json"])
    cfg = await svc.guardar_configuracion(db, actor, _tenant_de(actor, tenant_id), cuerpo, request)
    await db.commit()
    await db.refresh(cfg)
    return cfg


# ------------------------------------------------------------------ registro y resumen
@router.get("", response_model=list[FilaRegistro], summary="Registro de activos con su criticidad",
            description="Ordenado por índice. Es la base del reporte de certificación ISO 55000 y de la pantalla "
                        "del módulo. El Admin UN solo ve los activos de sus unidades.")
async def listado(db: DB, actor: ActorActual, tenant_id: UUID | None = None,
                  nivel: str | None = Query(default=None, pattern="^[ABCD]$"),
                  solo_revision_vencida: bool = False):
    return await svc.listado(db, actor, tenant_id=tenant_id, nivel=nivel,
                             solo_revision_vencida=solo_revision_vencida)


@router.get("/resumen", response_model=ResumenCriticidad, summary="Distribución por nivel y pendientes",
            description="Lo que va al tablero del cliente: activos por nivel, activos A sin plan de mantenimiento, "
                        "acciones de mitigación vencidas y revisiones de criticidad vencidas.")
async def resumen(db: DB, actor: ActorActual, tenant_id: UUID | None = None):
    return await svc.resumen(db, actor, tenant_id)


@router.get("/matriz", summary="Matriz de riesgo probabilidad × impacto",
            description="Matriz 5×5 con los activos ubicados en cada celda y su conteo (§6.9.3).")
async def matriz(db: DB, actor: ActorActual, tenant_id: UUID | None = None):
    return await svc.matriz_riesgo(db, actor, tenant_id)


# ------------------------------------------------------------------ evaluación por equipo
@router.get("/equipos/{equipo_id}", summary="Criticidad del equipo con su desglose",
            description="El nivel y el índice con cómo se formó: la probabilidad (y de dónde salió) y cada "
                        "dimensión con su peso y su aporte. Sin evaluar, devuelve la guía del formulario y la "
                        "propuesta automática del impacto económico.")
async def detalle(equipo_id: UUID, db: DB, actor: ActorActual):
    equipo = await svc.equipo_visible(db, actor, equipo_id)
    svc._exigir(actor, svc.CONSULTAN, "consulta la criticidad de los activos")
    datos = await svc.detalle(db, equipo)
    await db.commit()
    return datos


@router.post("/equipos/{equipo_id}", response_model=CriticidadSalida, summary="Evaluar la criticidad de un equipo",
             description="Las cuatro dimensiones las evalúa el Admin empresa o el Admin UN; la probabilidad la pone "
                         "ACMA con el historial de fallas. Cada evaluación queda en el historial y, si cambia el "
                         "nivel, se avisa al Admin prestador y al Despachador.")
async def evaluar(equipo_id: UUID, datos: EvaluacionEntrada, request: Request, db: DB, actor: ActorActual):
    equipo = await svc.equipo_visible(db, actor, equipo_id)
    fila = await svc.evaluar(db, actor, equipo, datos.dimensiones.model_dump(), motivo=datos.motivo,
                             razon=datos.razon, request=request)
    await db.commit()
    await db.refresh(fila)
    return fila


@router.post("/equipos/{equipo_id}/ajuste", response_model=CriticidadSalida, summary="Ajustar el nivel a mano",
             description="Solo el Admin empresa, con razón obligatoria. El ajuste se conserva hasta la próxima "
                         "revisión: el recálculo semanal respeta el nivel manual.")
async def ajustar(equipo_id: UUID, datos: AjusteManualEntrada, request: Request, db: DB, actor: ActorActual):
    equipo = await svc.equipo_visible(db, actor, equipo_id)
    fila = await svc.ajustar_manual(db, actor, equipo, datos.nivel, datos.razon, request)
    await db.commit()
    await db.refresh(fila)
    return fila


@router.post("/equipos/{equipo_id}/recalcular", summary="Recalcular con el historial de hoy",
             description="Lo mismo que hace la tarea semanal para un equipo. Solo registra una evaluación en el "
                         "historial si cambia el nivel.")
async def recalcular(equipo_id: UUID, db: DB, actor: ActorActual):
    equipo = await svc.equipo_visible(db, actor, equipo_id)
    svc._exigir(actor, svc.EVALUAN, "recalcula la criticidad de los activos")
    r = await svc.recalcular(db, equipo, motivo=MotivoEvaluacion.revision_periodica, actor_id=actor.id)
    await db.commit()
    return r


@router.get("/equipos/{equipo_id}/historial", response_model=list[EvaluacionHistorial],
            summary="Historial de evaluaciones del equipo",
            description="Append-only: la trazabilidad que pide una auditoría ISO 55000.")
async def historial(equipo_id: UUID, db: DB, actor: ActorActual, limite: int = Query(default=50, ge=1, le=200)):
    await svc.equipo_visible(db, actor, equipo_id)
    svc._exigir(actor, svc.CONSULTAN, "consulta la criticidad de los activos")
    return await svc.historial(db, equipo_id, limite)


@router.post("/masiva", summary="Evaluación masiva por tipo de equipo",
             description="Asigna las mismas dimensiones a todos los equipos de un tipo y después se ajustan los "
                         "particulares: 200 equipos no se evalúan de uno en uno.")
async def masiva(datos: EvaluacionMasivaEntrada, request: Request, db: DB, actor: ActorActual):
    r = await svc.evaluar_masivo(db, actor, _tenant_de(actor, datos.tenant_id), datos.tipo_equipo_id,
                                 datos.dimensiones.model_dump(), solo_sin_evaluar=datos.solo_sin_evaluar,
                                 request=request)
    await db.commit()
    return r


# ------------------------------------------------------------------ modos de falla
@router.get("/guia", summary="Guía del formulario de evaluación",
            description="La descripción literal de cada nivel 1–5 de las cuatro dimensiones de §6.9.3, para armar "
                        "el formulario guiado.")
async def guia(db: DB, actor: ActorActual):
    svc._exigir(actor, svc.CONSULTAN, "consulta la criticidad de los activos")
    from models.criticidad import ETIQUETA_NIVEL, IMPLICACIONES_POR_NIVEL

    return {"dimensiones": svc.GUIA_DIMENSIONES, "niveles": ETIQUETA_NIVEL,
            "implicaciones": IMPLICACIONES_POR_NIVEL}


@router_modos.get("/sugerencias", response_model=list[SugerenciaModoFalla],
                  summary="Modos de falla propuestos desde el historial",
                  description="Los tipos de falla más frecuentes de los correctivos cerrados del equipo, con su "
                              "causa raíz más común (catálogo de P03) y la severidad que la operación ya les dio. "
                              "Quien los revisa los acepta, los edita o los descarta.")
async def sugerencias(db: DB, actor: ActorActual, equipo_id: UUID, meses: int = Query(default=12, ge=1, le=60)):
    equipo = await riesgo.equipo_visible(db, actor, equipo_id)
    return await riesgo.sugerir(db, actor, equipo, meses)


@router_modos.get("", response_model=list[ModoFallaSalida], summary="Modos de falla de un equipo",
                  description="Incluye los genéricos de su tipo de equipo, que sirven para no repetir el análisis "
                              "en cada equipo igual.")
async def modos(db: DB, actor: ActorActual, equipo_id: UUID, incluir_genericos: bool = True,
                solo_activos: bool = True):
    equipo = await riesgo.equipo_visible(db, actor, equipo_id)
    riesgo._exigir(actor, "consulta el análisis de riesgo")
    return await riesgo.modos_de_equipo(db, equipo, incluir_genericos=incluir_genericos, solo_activos=solo_activos)


@router_modos.get("/matriz", summary="Matriz de riesgo 5×5 de los modos de falla",
                  description="Severidad × frecuencia, con el conteo por celda y por categoría "
                              "(bajo, medio, alto, crítico).")
async def matriz_modos(db: DB, actor: ActorActual, tenant_id: UUID | None = None):
    return await riesgo.matriz(db, actor, tenant_id)


@router_modos.post("", response_model=ModoFallaSalida, status_code=201, summary="Registrar un modo de falla",
                   description="De un equipo **o** genérico de un tipo de equipo, nunca de los dos. El nivel de "
                               "riesgo se calcula: severidad × frecuencia, y × detección si se captura.")
async def crear_modo(datos: ModoFallaEntrada, request: Request, db: DB, actor: ActorActual):
    modo = await riesgo.crear_modo(db, actor, datos.model_dump(exclude_none=True), request)
    await db.commit()
    await db.refresh(modo)
    return modo


@router_modos.post("/aceptar-sugerencias", response_model=list[ModoFallaSalida], status_code=201,
                   summary="Aceptar en lote los modos propuestos",
                   description="Quedan marcados como `sugerido`, para distinguir lo que salió del historial de lo "
                               "que escribió una persona.")
async def aceptar(datos: AceptarSugerencias, request: Request, db: DB, actor: ActorActual):
    equipo = await riesgo.equipo_visible(db, actor, datos.equipo_id)
    creados = await riesgo.aceptar_sugerencias(db, actor, equipo,
                                               [s.model_dump(exclude_none=True) for s in datos.sugerencias], request)
    await db.commit()
    for m in creados:
        await db.refresh(m)
    return creados


@router_modos.put("/{modo_id}", response_model=ModoFallaSalida, summary="Editar un modo de falla")
async def editar_modo(modo_id: UUID, datos: ModoFallaCambios, request: Request, db: DB, actor: ActorActual):
    modo = await db.get(ActivoModoFalla, modo_id)
    if modo is None:
        raise no_encontrado("Modo de falla")
    if modo.equipo_id:
        await riesgo.equipo_visible(db, actor, modo.equipo_id)
    elif not actor.es_superadmin and actor.dominio.value == "tenant" and modo.tenant_id != actor.tenant_id:
        raise no_encontrado("Modo de falla")
    modo = await riesgo.editar_modo(db, actor, modo, datos.model_dump(exclude_unset=True), request)
    await db.commit()
    await db.refresh(modo)
    return modo


# ------------------------------------------------------------------ mitigaciones
@router_mitigaciones.get("", response_model=list[MitigacionSalida], summary="Mitigaciones de un modo de falla")
async def mitigaciones(db: DB, actor: ActorActual, modo_falla_id: UUID):
    modo = await db.get(ActivoModoFalla, modo_falla_id)
    if modo is None:
        raise no_encontrado("Modo de falla")
    if modo.equipo_id:
        await riesgo.equipo_visible(db, actor, modo.equipo_id)
    riesgo._exigir(actor, "consulta el análisis de riesgo")
    return await riesgo.mitigaciones_de(db, modo_falla_id)


@router_mitigaciones.get("/pendientes", response_model=list[MitigacionPendiente],
                         summary="Bandeja de acciones por implementar",
                         description="Lo propuesto y en proceso, con lo vencido primero y los días de retraso.")
async def pendientes(db: DB, actor: ActorActual, tenant_id: UUID | None = None, solo_vencidas: bool = False):
    return await riesgo.pendientes(db, actor, tenant_id, solo_vencidas)


@router_mitigaciones.post("", response_model=MitigacionSalida, status_code=201,
                          summary="Registrar una acción de mitigación",
                          description="Una de tipo `plan_preventivo` se vincula a un plan de mantenimiento, una de "
                                      "`capacitacion` a un curso y una de `refaccion_en_inventario` a un artículo.")
async def crear_mitigacion(datos: MitigacionEntrada, request: Request, db: DB, actor: ActorActual):
    modo = await db.get(ActivoModoFalla, datos.modo_falla_id)
    if modo is None:
        raise no_encontrado("Modo de falla")
    if modo.equipo_id:
        await riesgo.equipo_visible(db, actor, modo.equipo_id)
    m = await riesgo.crear_mitigacion(db, actor, modo, datos.model_dump(exclude_none=True), request)
    await db.commit()
    await db.refresh(m)
    return m


@router_mitigaciones.post("/{mitigacion_id}/estado", response_model=MitigacionSalida,
                          summary="Cambiar el estado de la acción",
                          description="Al marcarla `implementada` se mide la efectividad: las fallas y el MTBF del "
                                      "equipo en los 6 meses previos contra los posteriores.")
async def cambiar_estado(mitigacion_id: UUID, datos: EstadoMitigacionEntrada, request: Request, db: DB,
                         actor: ActorActual):
    m = await db.get(ActivoRiesgoMitigacion, mitigacion_id)
    if m is None:
        raise no_encontrado("Mitigación")
    modo = await db.get(ActivoModoFalla, m.modo_falla_id)
    if modo is not None and modo.equipo_id:
        await riesgo.equipo_visible(db, actor, modo.equipo_id)
    m = await riesgo.cambiar_estado(db, actor, m, datos.estado, fecha_implementacion=datos.fecha_implementacion,
                                    razon=datos.razon, request=request)
    await db.commit()
    await db.refresh(m)
    return m


@router_mitigaciones.get("/{mitigacion_id}/efectividad", summary="Efectividad medida de la acción",
                         description="Compara los 6 meses anteriores a la implementación contra los posteriores. "
                                     "Antes de 90 días responde «sin datos suficientes»: la diferencia sería ruido.")
async def efectividad(mitigacion_id: UUID, db: DB, actor: ActorActual):
    m = await db.get(ActivoRiesgoMitigacion, mitigacion_id)
    if m is None:
        raise no_encontrado("Mitigación")
    modo = await db.get(ActivoModoFalla, m.modo_falla_id)
    if modo is not None and modo.equipo_id:
        await riesgo.equipo_visible(db, actor, modo.equipo_id)
    riesgo._exigir(actor, "consulta el análisis de riesgo")
    return await riesgo.efectividad(db, m)


# ------------------------------------------------------------------ reportes de certificación
router_reportes = APIRouter(prefix="/api/reportes/iso55000", tags=["Reportes ISO 55000"], responses=RESPUESTAS_ERROR)


@router_reportes.get("", summary="Qué reportes de certificación hay",
                     description="Los cinco de §6.9.3 con lo que demuestra cada uno ante un auditor.")
async def plantillas(db: DB, actor: ActorActual):
    from services import reportes_iso55000

    svc._exigir(actor, svc.CONSULTAN, "consulta los reportes de certificación")
    return [{"tipo": k, "nombre": v} for k, v in reportes_iso55000.PLANTILLAS.items()]


@router_reportes.get("/{tipo}", summary="Descargar un reporte de certificación (PDF o Excel)",
                     description="`iso_registro`, `iso_matriz`, `iso_modos_falla`, `iso_mejora_continua` e "
                                 "`iso_historial`. Usa el mismo generador de P10, así que sale con el logo y los "
                                 "colores del prestador y queda registrado en `reportes_generados`. La descarga se "
                                 "anota en la bitácora de acceso a datos sensibles (§6.9.5).")
async def descargar(tipo: str, request: Request, db: DB, actor: ActorActual,
                    formato: str = Query(default="pdf", pattern="^(pdf|excel)$"),
                    desde: date | None = None, hasta: date | None = None, tenant_id: UUID | None = None,
                    un_id: UUID | None = None):
    from fastapi import Response

    from models.base import FormatoReporte
    from services import auditoria, bi_service, reportes_iso55000, reportes_service

    if tipo not in reportes_iso55000.PLANTILLAS:
        raise ErrorAPI(422, "TIPO_DESCONOCIDO",
                       f"Los reportes disponibles son {', '.join(reportes_iso55000.PLANTILLAS)}")
    f = await bi_service.filtro_de(db, actor, desde, hasta, None, un_id)
    if tenant_id and (actor.es_superadmin or actor.dominio.value != "tenant"):
        # El filtro de P10 es inmutable a proposito: el prestador apunta a uno de sus clientes con una copia.
        f = replace(f, tenant_id=tenant_id)
    fmt = FormatoReporte(formato)
    registro, archivo = await reportes_service.generar(db, actor, tipo=tipo, formato=fmt, filtro=f, request=request)
    await auditoria.registrar_acceso_datos(db, actor, request, tabla="reportes_generados", recurso_id=registro.id,
                                           registros=registro.filas,
                                           detalle={"tipo": tipo, "formato": formato, "iso55000": True})
    await db.commit()
    mime = ("application/pdf" if fmt == FormatoReporte.pdf
            else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    ext = "pdf" if fmt == FormatoReporte.pdf else "xlsx"
    nombre = f"{tipo}-{f.desde}-{f.hasta}.{ext}"
    return Response(content=archivo, media_type=mime,
                    headers={"Content-Disposition": f'attachment; filename="{nombre}"',
                             "X-Reporte-Id": str(registro.id), "X-Reporte-Ms": str(registro.ms_generacion)})
