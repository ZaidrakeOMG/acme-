"""Dashboards por rol y reportes ejecutivos (§6.8.4, §6.8.5, §5.1, §5.2, §7.5, ACT-8.1/8.4). P10."""
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import select

from core.dependencias import DB, Actor, ActorActual
from core.errors import no_encontrado
from models.base import FormatoReporte, Rol
from models.reportes import ReporteGenerado, ReporteProgramado
from schemas.comun import RESPUESTAS_ERROR
from schemas.sla import GeneradoSalida, ProgramadoCambios, ProgramadoEntrada, ProgramadoSalida, ReporteEntrada
from services import bi_service, reportes_service
from services.almacenamiento import obtener_almacenamiento

router = APIRouter(prefix="/api/bi", tags=["Inteligencia de negocio"], responses=RESPUESTAS_ERROR)

MIME = {FormatoReporte.pdf: "application/pdf",
        FormatoReporte.excel: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
EXT = {FormatoReporte.pdf: "pdf", FormatoReporte.excel: "xlsx"}


@router.get("/tablero", summary="Tablero del rol",
            description="Arma el tablero que corresponde al rol (§5.1, §5.2, §7.5) con filtros de período y de nivel "
                        "(tenant, grupo o UN). El Supervisor de operadores recibe `sin_finanzas: true` y solo conteos. "
                        "Caché en Redis con TTL de 120 s.")
async def tablero(db: DB, actor: ActorActual, desde: date | None = None, hasta: date | None = None,
                  grupo_id: UUID | None = None, un_id: UUID | None = None, comparativos: bool = True):
    f = await bi_service.filtro_de(db, actor, desde, hasta, grupo_id, un_id)
    return await bi_service.tablero(db, actor, f, comparativos)


@router.get("/jornada", summary="Indicadores globales de jornada (§6.8.4)",
            description="Folios completados sobre el total del día, técnicos con folios activos, alertas abiertas y "
                        "tiempo promedio de atención. El mapa en vivo y el GPS son Fase 2.")
async def jornada(db: DB, actor: ActorActual):
    f = await bi_service.filtro_de(db, actor, None, None)
    return await bi_service.jornada(db, f)


@router.get("/indicador/{nombre}", summary="Un indicador suelto",
            description="Para las tablas de detalle del tablero: folios_por_estado, folios_por_severidad, "
                        "cumplimiento_sla, mttr, mtbf, gasto_vs_presupuesto, costo_total, top_equipos, preventivos, "
                        "hallazgos, cotizaciones, trabajos_especiales, carga_por_tecnico, penalizaciones, iguala, "
                        "inventario_y_caja, comparativo_jerarquia.")
async def indicador(nombre: str, db: DB, actor: ActorActual, desde: date | None = None, hasta: date | None = None,
                    grupo_id: UUID | None = None, un_id: UUID | None = None, por: str = Query("costo", pattern="^(costo|fallas)$")):
    permitidos = {
        "folios_por_estado", "folios_por_severidad", "cumplimiento_sla", "mttr", "mtbf", "gasto_vs_presupuesto",
        "costo_total", "top_equipos", "preventivos", "hallazgos", "cotizaciones", "trabajos_especiales",
        "carga_por_tecnico", "penalizaciones", "iguala", "inventario_y_caja", "comparativo_jerarquia",
    }
    if nombre not in permitidos:
        raise no_encontrado("Indicador")
    if actor.rol in bi_service.SIN_FINANZAS and nombre in {"gasto_vs_presupuesto", "costo_total", "penalizaciones",
                                                           "iguala", "inventario_y_caja", "cotizaciones"}:
        from core.errors import prohibido

        raise prohibido("Tu rol no tiene acceso a información financiera (§5.1)")
    f = await bi_service.filtro_de(db, actor, desde, hasta, grupo_id, un_id)
    fn = getattr(bi_service, nombre)
    return {"indicador": nombre, "periodo": {"desde": str(f.desde), "hasta": str(f.hasta)},
            "valor": await (fn(db, f, por) if nombre == "top_equipos" else fn(db, f))}


# ------------------------------------------------------------- reportes
@router.post("/reportes/generar", summary="Generar un reporte ahora",
             description="Devuelve el archivo (PDF o Excel) y deja el registro en `reportes_generados` con el tiempo de "
                         "generación. Plantillas: cliente, prestador y jornada.")
async def generar(datos: ReporteEntrada, request: Request, db: DB, actor: ActorActual):
    f = await bi_service.filtro_de(db, actor, datos.desde, datos.hasta, datos.grupo_id, datos.un_id)
    registro, archivo = await reportes_service.generar(db, actor, tipo=datos.tipo_reporte, formato=datos.formato,
                                                      filtro=f, request=request)
    await db.commit()
    nombre = f"{datos.tipo_reporte}-{f.desde}-{f.hasta}.{EXT[datos.formato]}"
    return Response(content=archivo, media_type=MIME[datos.formato],
                    headers={"Content-Disposition": f'attachment; filename="{nombre}"',
                             "X-Reporte-Id": str(registro.id), "X-Reporte-Ms": str(registro.ms_generacion)})


@router.get("/reportes/generados", response_model=list[GeneradoSalida], summary="Historial de reportes generados")
async def generados(db: DB, actor: ActorActual, limite: int = Query(50, ge=1, le=200)):
    consulta = select(ReporteGenerado).order_by(ReporteGenerado.generado_at.desc()).limit(limite)
    if actor.rol != Rol.superadmin:
        if actor.tenant_id:
            consulta = consulta.where(ReporteGenerado.tenant_id == actor.tenant_id)
        else:
            consulta = consulta.where(ReporteGenerado.prestador_id == actor.prestador_id)
    return list((await db.execute(consulta)).scalars())


@router.get("/reportes/generados/{reporte_id}/archivo", summary="Descargar un reporte ya generado")
async def archivo(reporte_id: UUID, db: DB, actor: ActorActual):
    r = await db.get(ReporteGenerado, reporte_id)
    if r is None:
        raise no_encontrado("Reporte")
    if actor.rol != Rol.superadmin and r.tenant_id != actor.tenant_id and r.prestador_id != actor.prestador_id:
        raise no_encontrado("Reporte")
    datos = obtener_almacenamiento().leer(r.archivo_key)
    nombre = r.archivo_key.rsplit("/", 1)[-1]
    return Response(content=datos, media_type=MIME[r.formato],
                    headers={"Content-Disposition": f'attachment; filename="{nombre}"'})


@router.get("/reportes/programados", response_model=list[ProgramadoSalida], summary="Reportes programados")
async def listar_programados(db: DB, actor: ActorActual):
    return await reportes_service.listar_programados(db, actor)


@router.post("/reportes/programados", response_model=ProgramadoSalida, status_code=201, summary="Programar un reporte",
             description="Periodicidad diaria, semanal o mensual; `dia_hora` admite «08:00», «lunes 08:00» o «1 08:00». "
                         "La tarea beat lo genera y lo envía por correo a los destinatarios.")
async def crear_programado(datos: ProgramadoEntrada, db: DB, actor: ActorActual):
    r = await reportes_service.crear_programado(db, actor, datos.model_dump())
    await db.commit()
    return r


@router.patch("/reportes/programados/{programado_id}", response_model=ProgramadoSalida, summary="Modificar un reporte programado")
async def editar_programado(programado_id: UUID, datos: ProgramadoCambios, db: DB, actor: ActorActual):
    r = await db.get(ReporteProgramado, programado_id)
    if r is None or (actor.rol != Rol.superadmin and r.tenant_id != actor.tenant_id and r.prestador_id != actor.prestador_id):
        raise no_encontrado("Reporte programado")
    for k, v in datos.model_dump(exclude_unset=True, mode="json").items():
        if v is not None:
            setattr(r, k, v)
    await db.flush()
    await db.commit()
    return r


@router.delete("/reportes/programados/{programado_id}", status_code=204, summary="Quitar un reporte programado")
async def borrar_programado(programado_id: UUID, db: DB, actor: ActorActual):
    r = await db.get(ReporteProgramado, programado_id)
    if r is None or (actor.rol != Rol.superadmin and r.tenant_id != actor.tenant_id and r.prestador_id != actor.prestador_id):
        raise no_encontrado("Reporte programado")
    await db.delete(r)
    await db.commit()
    return Response(status_code=204)
