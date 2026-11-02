"""Contador de SLA del folio, exclusiones, penalizaciones del período e iguala (§6.10.1). P10."""
from datetime import date
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.dependencias import DB, Actor, requiere_rol
from core.errors import ErrorAPI, no_encontrado
from models.base import EstadoPenalizacion, FormatoReporte, Rol
from models.contratos import Contrato
from models.folios import EstadoFolio, Folio, FolioSLA
from models.sla import FolioSLAExclusion, IgualaConsumoPeriodo, PenalizacionPeriodo
from schemas.comun import RESPUESTAS_ERROR
from schemas.sla import (
    CumplimientoContrato, ExclusionDecision, ExclusionEntrada, ExclusionSalida, IgualaSalida, PenalizacionCambio,
    PenalizacionSalida, SLAFolioSalida,
)
from services import bi_service, reportes_service, sla_service

router = APIRouter(prefix="/api/sla", tags=["SLA y penalizaciones"], responses=RESPUESTAS_ERROR)

CONSULTAN = requiere_rol(*sla_service.CONSULTAN)
REGISTRAN = requiere_rol(*sla_service.REGISTRAN_EXCLUSION)
APRUEBAN = requiere_rol(*sla_service.APRUEBAN_EXCLUSION)
REVISAN = requiere_rol(*sla_service.REVISAN_PENALIZACION)


async def _folio(db: AsyncSession, actor: Actor, folio_id: UUID) -> Folio:
    f = await db.get(Folio, folio_id)
    if f is None:
        raise no_encontrado("Folio")
    if actor.tenant_id and f.tenant_id != actor.tenant_id:
        raise no_encontrado("Folio")
    if actor.prestador_id and f.prestador_id != actor.prestador_id:
        raise no_encontrado("Folio")
    return f


async def _contrato(db: AsyncSession, actor: Actor, contrato_id: UUID) -> Contrato:
    c = await db.get(Contrato, contrato_id)
    if c is None:
        raise no_encontrado("Contrato")
    if actor.tenant_id and c.tenant_id != actor.tenant_id:
        raise no_encontrado("Contrato")
    if actor.prestador_id and c.prestador_id != actor.prestador_id:
        raise no_encontrado("Contrato")
    return c


@router.get("/folios/{folio_id}", response_model=SLAFolioSalida, summary="Contador de SLA del folio",
            description="Tiempo efectivo, límite, pausas por reasignación o espera de información, exclusiones y cumplimiento.")
async def sla_folio(folio_id: UUID, db: DB, actor: Actor = Depends(CONSULTAN)):
    folio = await _folio(db, actor, folio_id)
    return await sla_service.detalle(db, folio)


@router.post("/folios/{folio_id}/exclusiones", response_model=ExclusionSalida, status_code=201,
             summary="Registrar exclusión de SLA",
             description="El prestador registra la causa y el período; el Admin empresa la aprueba o rechaza (§6.10.1). "
                         "Solo los períodos aprobados se descuentan del contador.")
async def registrar_exclusion(folio_id: UUID, datos: ExclusionEntrada, request: Request, db: DB,
                              actor: Actor = Depends(REGISTRAN)):
    folio = await _folio(db, actor, folio_id)
    e = await sla_service.registrar_exclusion(db, actor, folio, causa=datos.causa, descripcion=datos.descripcion,
                                              inicio=datos.timestamp_inicio, fin=datos.timestamp_fin, request=request)
    salida = ExclusionSalida.model_validate(e, from_attributes=True)
    salida.numero_folio = folio.numero_folio
    await db.commit()
    return salida


@router.get("/exclusiones", response_model=list[ExclusionSalida], summary="Bandeja de exclusiones",
            description="Las pendientes de decisión del Admin empresa; con `pendientes=false` trae también las resueltas.")
async def listar_exclusiones(db: DB, actor: Actor = Depends(CONSULTAN), pendientes: bool = True,
                             folio_id: UUID | None = None):
    consulta = select(FolioSLAExclusion, Folio.numero_folio).join(Folio, Folio.id == FolioSLAExclusion.folio_id)
    if pendientes:
        consulta = consulta.where(FolioSLAExclusion.aprobada.is_(None))
    if folio_id:
        consulta = consulta.where(FolioSLAExclusion.folio_id == folio_id)
    salida = []
    for e, numero in (await db.execute(consulta.order_by(FolioSLAExclusion.created_at.desc()))).all():
        fila = ExclusionSalida.model_validate(e, from_attributes=True)
        fila.numero_folio = numero
        salida.append(fila)
    return salida


@router.post("/exclusiones/{exclusion_id}/decidir", response_model=ExclusionSalida, summary="Aprobar o rechazar la exclusión",
             description="Solo el Admin empresa (§6.10.1). Si el folio ya cerró, el contador y la penalización se recalculan.")
async def decidir_exclusion(exclusion_id: UUID, datos: ExclusionDecision, request: Request, db: DB,
                            actor: Actor = Depends(APRUEBAN)):
    e = await db.get(FolioSLAExclusion, exclusion_id)
    if e is None or (actor.tenant_id and e.tenant_id != actor.tenant_id):
        raise no_encontrado("Exclusión")
    e = await sla_service.decidir_exclusion(db, actor, e, aprobada=datos.aprobada, razon=datos.razon, request=request)
    folio = await db.get(Folio, e.folio_id)
    salida = ExclusionSalida.model_validate(e, from_attributes=True)
    salida.numero_folio = folio.numero_folio if folio else None
    await db.commit()
    return salida


@router.get("/contratos/{contrato_id}/cumplimiento", response_model=CumplimientoContrato,
            summary="Cumplimiento del contrato en el período")
async def cumplimiento(contrato_id: UUID, db: DB, actor: Actor = Depends(CONSULTAN),
                       desde: date | None = None, hasta: date | None = None):
    c = await _contrato(db, actor, contrato_id)
    f = await bi_service.filtro_de(db, actor, desde, hasta)
    f = bi_service.Filtro(f.desde, f.hasta, tenant_id=c.tenant_id, prestador_id=c.prestador_id)
    sla = await bi_service.cumplimiento_sla(db, f)
    pendientes = len([x for x in await sla_service.pendientes_exclusion(db, actor) if x.tenant_id == c.tenant_id])
    penal = await bi_service.penalizaciones(db, f)
    return CumplimientoContrato(contrato_id=c.id, periodo=f"{f.desde} a {f.hasta}", folios_cerrados=sla["total"],
                                cumplimiento_respuesta_pct=sla["respuesta_pct"], cumplimiento_resolucion_pct=sla["resolucion_pct"],
                                folios_incumplidos=penal["folios_incumplidos"], penalizacion=penal["monto"],
                                por_severidad=sla["por_severidad"], exclusiones_pendientes=pendientes)


@router.post("/contratos/{contrato_id}/penalizaciones/calcular", response_model=PenalizacionSalida,
             summary="Consolidar las penalizaciones del período",
             description="Recalcula el resumen mensual del contrato con el detalle de folios incumplidos. "
                         "Un período ya cerrado no se vuelve a calcular.")
async def calcular_penalizaciones(contrato_id: UUID, db: DB, actor: Actor = Depends(REVISAN),
                                  periodo: str = Query(default_factory=lambda: date.today().strftime("%Y-%m"),
                                                       pattern=r"^\d{4}-\d{2}$")):
    c = await _contrato(db, actor, contrato_id)
    registro = await sla_service.consolidar_penalizaciones(db, c, periodo)
    await db.commit()
    return registro


@router.get("/contratos/{contrato_id}/penalizaciones", response_model=list[PenalizacionSalida],
            summary="Penalizaciones por período del contrato")
async def listar_penalizaciones(contrato_id: UUID, db: DB, actor: Actor = Depends(CONSULTAN)):
    c = await _contrato(db, actor, contrato_id)
    return list((await db.execute(select(PenalizacionPeriodo).where(PenalizacionPeriodo.contrato_id == c.id)
                                   .order_by(PenalizacionPeriodo.periodo.desc()))).scalars())


@router.post("/penalizaciones/{registro_id}/estado", response_model=PenalizacionSalida,
             summary="Revisar o cerrar el período de penalizaciones",
             description="borrador → revisado → cerrado. El descuento en la factura CFDI es Fase 2: "
                         "`incluido_en_factura_id` se queda nulo.")
async def cambiar_estado_penalizacion(registro_id: UUID, datos: PenalizacionCambio, request: Request, db: DB,
                                      actor: Actor = Depends(REVISAN)):
    registro = await db.get(PenalizacionPeriodo, registro_id)
    if registro is None or (actor.prestador_id and registro.prestador_id != actor.prestador_id):
        raise no_encontrado("Período de penalizaciones")
    registro = await sla_service.revisar_penalizacion(db, actor, registro, estado=datos.estado, request=request)
    await db.commit()
    return registro


@router.get("/penalizaciones/{registro_id}/archivo", summary="Descargar el resumen de penalizaciones",
            description="PDF o Excel del período con el detalle de folios incumplidos (§6.10.1).")
async def archivo_penalizaciones(registro_id: UUID, db: DB, actor: Actor = Depends(CONSULTAN),
                                 formato: str = Query("pdf", pattern="^(pdf|xlsx)$")):
    registro = await db.get(PenalizacionPeriodo, registro_id)
    if registro is None:
        raise no_encontrado("Período de penalizaciones")
    if actor.prestador_id and registro.prestador_id != actor.prestador_id:
        raise no_encontrado("Período de penalizaciones")
    if actor.tenant_id and registro.tenant_id != actor.tenant_id:
        raise no_encontrado("Período de penalizaciones")
    anio, mes = (int(x) for x in registro.periodo.split("-"))
    ultimo = date(anio + (mes == 12), (mes % 12) + 1, 1)
    f = bi_service.Filtro(date(anio, mes, 1), ultimo, tenant_id=registro.tenant_id, prestador_id=registro.prestador_id)
    tema = await reportes_service._tema(db, registro.prestador_id)
    bloques = [
        {"titulo": f"Penalizaciones del período {registro.periodo}", "tipo": "kpi", "filas": [
            ("Folios cerrados", registro.total_folios), ("Folios incumplidos", registro.folios_incumplidos),
            ("Penalización", f"${registro.monto_penalizacion} {registro.moneda}"), ("Estado", registro.estado.value),
            ("Descuento en factura CFDI", "Fase 2")]},
        {"titulo": "Detalle de folios incumplidos", "tipo": "tabla",
         "columnas": ["Folio", "Límite (min)", "Efectivo (min)", "Pausado", "Excluido", "Penalización"],
         "filas": [(d.get("numero_folio"), d.get("limite_min"), d.get("efectivo_min"), d.get("pausado_min"),
                    d.get("excluido_min"), d.get("penalizacion")) for d in registro.detalle_json]},
    ]
    titulo = f"Penalizaciones por SLA · {registro.periodo}"
    if formato == "pdf":
        from services import pdf as pdf_mod

        datos = pdf_mod.html_a_pdf(reportes_service.a_html(titulo, tema, f, bloques))
        mime = "application/pdf"
    else:
        datos = reportes_service.a_excel(titulo, tema, f, bloques)
        mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    nombre = f"penalizaciones-{registro.periodo}.{formato}"
    return Response(content=datos, media_type=mime, headers={"Content-Disposition": f'attachment; filename="{nombre}"'})


@router.post("/contratos/{contrato_id}/iguala/calcular", response_model=IgualaSalida, summary="Consumo de la iguala del período",
             description="Correctivos incluidos contra atendidos (con los adicionales identificados) y preventivos ejecutados. "
                         "Dispara IGUALA_LIMITE_ALCANZADO al pasar el umbral.")
async def calcular_iguala(contrato_id: UUID, db: DB, actor: Actor = Depends(REVISAN),
                          periodo: str = Query(default_factory=lambda: date.today().strftime("%Y-%m"), pattern=r"^\d{4}-\d{2}$")):
    c = await _contrato(db, actor, contrato_id)
    registro = await sla_service.consumo_iguala(db, c, periodo)
    if registro is None:
        raise ErrorAPI(409, "CONTRATO_POR_EVENTO", "El contrato no está en modalidad iguala")
    await db.commit()
    return registro


@router.get("/contratos/{contrato_id}/iguala", response_model=list[IgualaSalida], summary="Histórico del consumo de la iguala")
async def listar_iguala(contrato_id: UUID, db: DB, actor: Actor = Depends(CONSULTAN)):
    c = await _contrato(db, actor, contrato_id)
    return list((await db.execute(select(IgualaConsumoPeriodo).where(IgualaConsumoPeriodo.contrato_id == c.id)
                                   .order_by(IgualaConsumoPeriodo.periodo.desc()))).scalars())
