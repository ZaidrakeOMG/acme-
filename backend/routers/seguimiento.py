"""Los cuatro módulos de seguimiento (§7.7–7.9): listados con filtros, Kanban (cambio de estado con historial), vista por UN,
reporte ejecutivo (JSON, PDF y Excel), cotizaciones con PDF y envío externo, períodos presupuestales. P07."""
import io
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from sqlalchemy import func, select

from core.dependencias import DB, Actor, requiere_rol
from core.errors import ErrorAPI, no_encontrado, prohibido
from models.base import Dominio, Rol
from models.catalogos import Equipo
from models.folios import Folio, ModuloDestino
from models.minutas import Hallazgo
from models.seguimiento import (
    Cotizacion, EstadoCotizacion, EstadoPresupuesto, EstadoReprogramacion, EstadoSeguimientoInterno, HallazgoPresupuesto, PeriodoPresupuestal, Reprogramacion, SeguimientoInterno,
)
from models.unidades import UnidadNegocio
from models.usuarios import Usuario
from routers.catalogos_equipos import tenant_de
from schemas.comun import RESPUESTAS_ERROR
from schemas.minutas import (
    CambioEstadoEntrada, CotizacionSalida, CrearRegistroEntrada, EnvioExternoEntrada, HistorialModuloSalida, NotasEntrada, PeriodoEntrada, PeriodoSalida, PorUNSalida,
    PrepararCotizacionEntrada, PresupuestoSalida, ReactivarEntrada, ReporteEjecutivo, ReprogramacionSalida, ResponderCotizacionEntrada, SeguimientoInternoSalida,
)
from services import auditoria
from services.seguimiento import base, cotizaciones, interno, presupuesto, reprogramacion
from services.seguimiento.base import MODELOS

router = APIRouter(tags=["Módulos de seguimiento"], responses=RESPUESTAS_ERROR)
TODOS = requiere_rol(*Rol)
MODULO_POR_RUTA = {"cotizaciones": ModuloDestino.cotizaciones, "presupuesto": ModuloDestino.por_presupuesto, "interno": ModuloDestino.seguimiento_interno,
                   "reprogramacion": ModuloDestino.reprogramacion, "por_presupuesto": ModuloDestino.por_presupuesto, "seguimiento_interno": ModuloDestino.seguimiento_interno}
SERVICIOS = {ModuloDestino.cotizaciones: cotizaciones, ModuloDestino.por_presupuesto: presupuesto, ModuloDestino.seguimiento_interno: interno, ModuloDestino.reprogramacion: reprogramacion}
SALIDAS = {ModuloDestino.cotizaciones: CotizacionSalida, ModuloDestino.por_presupuesto: PresupuestoSalida, ModuloDestino.seguimiento_interno: SeguimientoInternoSalida,
           ModuloDestino.reprogramacion: ReprogramacionSalida}
ESTADOS = {ModuloDestino.cotizaciones: EstadoCotizacion, ModuloDestino.por_presupuesto: EstadoPresupuesto, ModuloDestino.seguimiento_interno: EstadoSeguimientoInterno,
           ModuloDestino.reprogramacion: EstadoReprogramacion}
FINALES = {"resuelto", "cancelado", "descartado", "convertida", "rechazada", "reactivado"}
PROXIMA_ALERTA = {
    ModuloDestino.cotizaciones: {"solicitada": "COTIZACION_SIN_PREPARAR", "en_preparacion": "COTIZACION_SIN_ENVIAR", "enviada": "COTIZACION_SIN_RESPUESTA", "autorizada": "COTIZACION_AUTORIZADA_SIN_CONVERTIR"},
    ModuloDestino.por_presupuesto: {"diferido": "PRESUPUESTO_SIN_REVISION"},
    ModuloDestino.seguimiento_interno: {"registrado": "SEGUIMIENTO_SIN_UPDATE", "en_gestion": "SEGUIMIENTO_SIN_UPDATE", "con_proveedor": "SEGUIMIENTO_INTERNO_FECHA_VENCIDA"},
    ModuloDestino.reprogramacion: {"pendiente_fecha": "REPROGRAMACION_SIN_FECHA", "fecha_asignada": "REPROGRAMACION_FECHA_PROXIMA", "tercero_confirmado": "REPROGRAMACION_FECHA_VENCIDA", "en_ejecucion": "REPROGRAMACION_SIN_CIERRE"},
}


def _modulo(ruta: str) -> ModuloDestino:
    m = MODULO_POR_RUTA.get(ruta)
    if m is None:
        raise ErrorAPI(404, "MODULO_DESCONOCIDO", f"Módulo {ruta} no existe; usa cotizaciones, presupuesto, interno o reprogramacion")
    return m


def _destinos(modulo: ModuloDestino, registro, actor: Actor) -> list[str]:
    tabla = {ModuloDestino.cotizaciones: cotizaciones.TRANSICIONES, ModuloDestino.seguimiento_interno: interno.TRANSICIONES, ModuloDestino.reprogramacion: reprogramacion.TRANSICIONES}.get(modulo)
    if tabla is None:
        return ["reactivado", "descartado"] if registro.estado == EstadoPresupuesto.diferido and (actor.es_superadmin or actor.rol in presupuesto.DECIDEN) else []
    return [d.value for d, roles in tabla[registro.estado].items() if actor.es_superadmin or actor.rol in roles]


async def _serializar(db, actor: Actor, modulo: ModuloDestino, registros: list) -> list[dict[str, Any]]:
    if not registros:
        return []
    ids = [r.id for r in registros]
    alertas = await base.alertas_activas(db, ids)
    unidades = {u.id: u for u in (await db.execute(select(UnidadNegocio).where(UnidadNegocio.id.in_({r.un_id for r in registros})))).scalars()}
    equipos = {e.id: e for e in (await db.execute(select(Equipo).where(Equipo.id.in_({r.equipo_id for r in registros if r.equipo_id})))).scalars()} if any(r.equipo_id for r in registros) else {}
    folios = {f.id: f for f in (await db.execute(select(Folio).where(Folio.id.in_({r.folio_id for r in registros if r.folio_id})))).scalars()} if any(r.folio_id for r in registros) else {}
    hallazgos = {h.id: h for h in (await db.execute(select(Hallazgo).where(Hallazgo.id.in_({r.hallazgo_id for r in registros if r.hallazgo_id})))).scalars()} if any(r.hallazgo_id for r in registros) else {}
    salida = []
    for r in registros:
        un, eq, f, h = unidades.get(r.un_id), equipos.get(r.equipo_id), folios.get(r.folio_id), hallazgos.get(r.hallazgo_id)
        d = {**auditoria.instantanea(r), "id": r.id, "hallazgo_id": r.hallazgo_id, "folio_id": r.folio_id, "tenant_id": r.tenant_id, "prestador_id": r.prestador_id, "un_id": r.un_id,
             "equipo_id": r.equipo_id, "created_at": r.created_at, "updated_at": r.updated_at, "estado_desde": r.estado_desde,
             "numero_folio": f.numero_folio if f else None, "un_codigo": un.codigo if un else None, "un_nombre": un.nombre if un else None, "equipo_codigo": eq.codigo if eq else None,
             "dias_en_estado": base.dias_en_estado(r), "alertas_activas": alertas.get(r.id, []), "urgencia_hallazgo": h.nivel_urgencia if h else None,
             "proxima_alerta": None if r.estado.value in FINALES else PROXIMA_ALERTA[modulo].get(r.estado.value), "destinos": _destinos(modulo, r, actor)}
        for k in ("fecha_solicitud", "fecha_preparacion", "fecha_envio", "fecha_respuesta", "ultima_revision", "decidido_at", "ultima_actualizacion", "cerrado_at", "fecha_resolucion",
                  "solicitado_por", "preparado_por", "respondido_por", "decidido_por", "responsable_un", "cerrado_por", "reactivado_registro_id", "folio_coordinado_id", "trabajo_especial_id"):
            if hasattr(r, k):
                d[k] = getattr(r, k)
        if modulo == ModuloDestino.cotizaciones:
            d["pdf_disponible"] = r.pdf_key is not None
            d["estado_trabajo_especial"] = None  # P08
            d["envios_externos"] = [{"id": e.id, "destinatarios": e.destinatarios_json, "comentario": e.comentario, "timestamp": e.timestamp, "enviado_por": e.enviado_por, "estado_entrega": e.estado_entrega}
                                    for e in await cotizaciones.envios_externos(db, r)]
        salida.append(d)
    return salida


# ----------------------------------------------------------- cotizaciones

@router.post("/api/seguimiento/cotizaciones/{registro_id}/preparar", response_model=CotizacionSalida, summary="Preparar (descripción, monto, partidas)")
async def preparar(registro_id: UUID, datos: PrepararCotizacionEntrada, request: Request, db: DB, actor: Actor = Depends(TODOS)):
    c = await base.obtener(db, actor, Cotizacion, registro_id)
    await cotizaciones.preparar(db, actor, c, descripcion=datos.descripcion, monto=datos.monto, detalle=datos.detalle, request=request)
    await db.commit()
    return CotizacionSalida(**(await _serializar(db, actor, ModuloDestino.cotizaciones, [c]))[0])


@router.post("/api/seguimiento/cotizaciones/{registro_id}/enviar", response_model=CotizacionSalida, summary="Enviar al cliente (PDF + notificación al Admin UN y Admin empresa)")
async def enviar(registro_id: UUID, request: Request, db: DB, actor: Actor = Depends(TODOS)):
    c = await base.obtener(db, actor, Cotizacion, registro_id)
    await cotizaciones.enviar_cliente(db, actor, c, request)
    await db.commit()
    return CotizacionSalida(**(await _serializar(db, actor, ModuloDestino.cotizaciones, [c]))[0])


@router.post("/api/seguimiento/cotizaciones/{registro_id}/responder", response_model=CotizacionSalida, summary="Autorizar o rechazar (Admin UN / Admin empresa)")
async def responder(registro_id: UUID, datos: ResponderCotizacionEntrada, request: Request, db: DB, actor: Actor = Depends(TODOS)):
    c = await base.obtener(db, actor, Cotizacion, registro_id)
    await cotizaciones.responder(db, actor, c, datos.autorizar, datos.notas, datos.pasar_a_presupuesto_si_rechaza, request)
    await db.commit()
    return CotizacionSalida(**(await _serializar(db, actor, ModuloDestino.cotizaciones, [c]))[0])


@router.post("/api/seguimiento/cotizaciones/{registro_id}/convertir", summary="Convertir en Trabajo Especial (gancho P08)")
async def convertir(registro_id: UUID, db: DB, actor: Actor = Depends(TODOS)):
    c = await base.obtener(db, actor, Cotizacion, registro_id)
    await cotizaciones.convertir_en_trabajo_especial(db, actor, c)


@router.get("/api/seguimiento/cotizaciones/{registro_id}/pdf", summary="Descargar PDF de la cotización (§7.7)")
async def pdf_cotizacion(registro_id: UUID, db: DB, actor: Actor = Depends(TODOS)):
    c = await base.obtener(db, actor, Cotizacion, registro_id)
    datos = await cotizaciones.pdf_de(db, c)
    await db.commit()
    return Response(datos, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{c.numero}.pdf"', "X-Hash-SHA256": c.hash_pdf or ""})


@router.post("/api/seguimiento/cotizaciones/{registro_id}/enviar-externo", summary="Enviar el PDF por correo a destinatarios externos (licitación) sin cambiar el estado")
async def enviar_externo(registro_id: UUID, datos: EnvioExternoEntrada, request: Request, db: DB, actor: Actor = Depends(TODOS)) -> dict[str, Any]:
    c = await base.obtener(db, actor, Cotizacion, registro_id)
    e = await cotizaciones.enviar_externo(db, actor, c, datos.destinatarios, datos.comentario, request)
    await db.commit()
    return {"id": e.id, "destinatarios": e.destinatarios_json, "comentario": e.comentario, "asunto": e.asunto, "timestamp": e.timestamp, "estado_entrega": e.estado_entrega, "estado_cotizacion": c.estado.value}


# ------------------------------------------------------------ presupuesto

@router.post("/api/seguimiento/presupuesto/{registro_id}/reactivar", summary="Reactivar: folio directo autorizado o cotización")
async def reactivar(registro_id: UUID, datos: ReactivarEntrada, request: Request, db: DB, actor: Actor = Depends(TODOS)) -> dict[str, Any]:
    hp = await base.obtener(db, actor, HallazgoPresupuesto, registro_id)
    hp, registro = await presupuesto.reactivar(db, actor, hp, datos.como, datos.notas, request)
    await db.commit()
    salida = PresupuestoSalida(**(await _serializar(db, actor, ModuloDestino.por_presupuesto, [hp]))[0]).model_dump()
    salida["registro"] = {"tipo": datos.como, "id": registro.id, "numero": getattr(registro, "numero", None) or getattr(registro, "numero_folio", None)}
    return salida


@router.post("/api/seguimiento/presupuesto/{registro_id}/descartar", response_model=PresupuestoSalida, summary="Descartar definitivamente (razón obligatoria)")
async def descartar(registro_id: UUID, datos: NotasEntrada, request: Request, db: DB, actor: Actor = Depends(TODOS)):
    hp = await base.obtener(db, actor, HallazgoPresupuesto, registro_id)
    await presupuesto.descartar(db, actor, hp, datos.notas, request)
    await db.commit()
    return PresupuestoSalida(**(await _serializar(db, actor, ModuloDestino.por_presupuesto, [hp]))[0])


@router.post("/api/seguimiento/presupuesto/{registro_id}/revisar", response_model=PresupuestoSalida, summary="Marcar revisado (reinicia el contador de 30 días)")
async def revisar(registro_id: UUID, datos: NotasEntrada, request: Request, db: DB, actor: Actor = Depends(TODOS)):
    hp = await base.obtener(db, actor, HallazgoPresupuesto, registro_id)
    await presupuesto.revisar(db, actor, hp, datos.notas, request)
    await db.commit()
    return PresupuestoSalida(**(await _serializar(db, actor, ModuloDestino.por_presupuesto, [hp]))[0])


@router.get("/api/seguimiento/presupuesto/monto-potencial", summary="Trabajo potencial diferido por UN (prestador)")
async def monto_potencial(db: DB, actor: Actor = Depends(TODOS), tenant_id: UUID | None = None) -> list[dict[str, Any]]:
    filas = await presupuesto.monto_potencial(db, actor, tenant_id)
    unidades = {u.id: u for u in (await db.execute(select(UnidadNegocio).where(UnidadNegocio.id.in_({f["un_id"] for f in filas})))).scalars()} if filas else {}
    return [{**f, "un_codigo": unidades[f["un_id"]].codigo if f["un_id"] in unidades else None, "un_nombre": unidades[f["un_id"]].nombre if f["un_id"] in unidades else None} for f in filas]


# -------------------------------------------------------- interno / reprog

@router.post("/api/seguimiento/interno/{registro_id}/actualizar", response_model=SeguimientoInternoSalida, summary="Registrar una novedad sin cambiar de estado")
async def actualizar_interno(registro_id: UUID, datos: NotasEntrada, request: Request, db: DB, actor: Actor = Depends(TODOS)):
    s = await base.obtener(db, actor, SeguimientoInterno, registro_id)
    await interno.actualizar(db, actor, s, datos.notas, request)
    await db.commit()
    return SeguimientoInternoSalida(**(await _serializar(db, actor, ModuloDestino.seguimiento_interno, [s]))[0])


@router.post("/api/seguimiento/reprogramacion/{registro_id}/confirmar-tercero", summary="Variante A: el tercero completó su parte → folio para el técnico")
async def confirmar_tercero(registro_id: UUID, datos: NotasEntrada, request: Request, db: DB, actor: Actor = Depends(TODOS)) -> dict[str, Any]:
    r = await base.obtener(db, actor, Reprogramacion, registro_id)
    r, folio = await reprogramacion.confirmar_tercero(db, actor, r, datos.notas, request)
    await db.commit()
    salida = ReprogramacionSalida(**(await _serializar(db, actor, ModuloDestino.reprogramacion, [r]))[0]).model_dump()
    salida["folio"] = {"id": folio.id, "numero_folio": folio.numero_folio, "estado": folio.estado.value}
    return salida


# ---------------------------------------------------------- períodos

@router.get("/api/seguimiento/periodos-presupuestales", response_model=PeriodoSalida | None, summary="Período presupuestal del tenant (Admin empresa)")
async def periodo(db: DB, actor: Actor = Depends(requiere_rol(Rol.superadmin, Rol.admin_empresa, Rol.admin_un, Rol.admin_prestador, Rol.despachador, Rol.mesa_control)),
                  tenant_id: UUID | None = None):
    t = tenant_id if (actor.es_superadmin or actor.dominio == Dominio.prestador) else actor.tenant_id
    if t is None:
        raise ErrorAPI(422, "TENANT_REQUERIDO", "Indica tenant_id")
    p = await presupuesto.periodo_tenant(db, t)
    if p is None:
        return None
    return PeriodoSalida(**{**auditoria.instantanea(p), "periodo_actual": presupuesto.periodo_actual(p.tipo, p.fechas_json)})


@router.put("/api/seguimiento/periodos-presupuestales", response_model=PeriodoSalida, summary="Definir el período presupuestal (mensual, trimestral, semestral, anual o fechas)")
async def guardar_periodo(datos: PeriodoEntrada, request: Request, db: DB, actor: Actor = Depends(requiere_rol(Rol.superadmin, Rol.admin_empresa)), tenant_id: UUID | None = None):
    t = tenant_de(actor, tenant_id)
    p = await presupuesto.periodo_tenant(db, t)
    if p is None:
        p = PeriodoPresupuestal(tenant_id=t)
        db.add(p)
    p.tipo, p.fechas_json, p.activo = datos.tipo, [f.isoformat() for f in datos.fechas], True
    await db.flush()
    await auditoria.registrar_actor(db, actor, "presupuesto.periodo", request, tenant_id=t, recurso_tipo="periodo_presupuestal", recurso_id=p.id,
                                    despues={"tipo": datos.tipo.value, "fechas": p.fechas_json})
    await db.commit()
    return PeriodoSalida(**{**auditoria.instantanea(p), "periodo_actual": presupuesto.periodo_actual(p.tipo, p.fechas_json)})


# --------------------------------------------------------------- reporte

async def _reporte(db, actor: Actor, desde: date | None, hasta: date | None, tenant_id: UUID | None) -> dict[str, Any]:
    base.exigir_rol(actor, {Rol.superadmin, Rol.admin_empresa, Rol.admin_prestador, Rol.direccion_prestador, Rol.mesa_control}, "Reporte ejecutivo")
    filtros = {"tenant_id": tenant_id, "desde": datetime.combine(desde, datetime.min.time(), tzinfo=UTC) if desde else None,
               "hasta": datetime.combine(hasta, datetime.max.time(), tzinfo=UTC) if hasta else None}
    promedios: dict[str, float | None] = {}
    totales: dict[str, int] = {}
    for clave, m, campo_cierre, finales in (("cotizaciones", ModuloDestino.cotizaciones, "fecha_respuesta", (EstadoCotizacion.autorizada, EstadoCotizacion.rechazada, EstadoCotizacion.convertida)),
                                            ("por_presupuesto", ModuloDestino.por_presupuesto, "decidido_at", (EstadoPresupuesto.reactivado, EstadoPresupuesto.descartado)),
                                            ("seguimiento_interno", ModuloDestino.seguimiento_interno, "cerrado_at", (EstadoSeguimientoInterno.resuelto, EstadoSeguimientoInterno.cancelado)),
                                            ("reprogramacion", ModuloDestino.reprogramacion, "fecha_resolucion", (EstadoReprogramacion.resuelto, EstadoReprogramacion.cancelado))):
        registros = await SERVICIOS[m].listar(db, actor, filtros)
        totales[clave] = len(registros)
        cerrados = [((getattr(r, campo_cierre) or r.updated_at) - r.created_at).total_seconds() / 86400 for r in registros if r.estado in finales]
        promedios[clave] = round(sum(cerrados) / len(cerrados), 1) if cerrados else None
    cots = await cotizaciones.listar(db, actor, filtros)
    por_estado = {e.value: sum(c.estado == e for c in cots) for e in EstadoCotizacion}
    respondidas = por_estado["autorizada"] + por_estado["rechazada"] + por_estado["convertida"]
    tasa = round((por_estado["autorizada"] + por_estado["convertida"]) * 100 / respondidas, 1) if respondidas else 0.0
    # Hallazgos recurrentes por tipo de equipo.
    from models.catalogos import TipoEquipo

    consulta = select(TipoEquipo.nombre, func.count()).select_from(Hallazgo).join(Equipo, Equipo.id == Hallazgo.equipo_id).join(TipoEquipo, TipoEquipo.id == Equipo.tipo_equipo_id)
    if tenant_id:
        consulta = consulta.where(Hallazgo.tenant_id == tenant_id)
    elif actor.dominio == Dominio.tenant:
        consulta = consulta.where(Hallazgo.tenant_id == actor.tenant_id)
    elif actor.dominio == Dominio.prestador:
        consulta = consulta.where(Hallazgo.prestador_id == actor.prestador_id)
    if filtros["desde"]:
        consulta = consulta.where(Hallazgo.timestamp >= filtros["desde"])
    if filtros["hasta"]:
        consulta = consulta.where(Hallazgo.timestamp <= filtros["hasta"])
    recurrentes = [{"tipo_equipo": n, "total": t} for n, t in (await db.execute(consulta.group_by(TipoEquipo.nombre).order_by(func.count().desc()).limit(10))).all()]
    monto = await presupuesto.monto_potencial(db, actor, tenant_id) if actor.rol != Rol.admin_un else []
    unidades = {u.id: u.codigo for u in (await db.execute(select(UnidadNegocio).where(UnidadNegocio.id.in_({f["un_id"] for f in monto})))).scalars()} if monto else {}
    return {"desde": desde, "hasta": hasta, "tiempo_promedio_resolucion_dias": promedios, "totales": totales, "tasa_conversion_cotizaciones": tasa, "cotizaciones": por_estado,
            "hallazgos_recurrentes": recurrentes, "monto_potencial": [{**f, "un_codigo": unidades.get(f["un_id"]), "monto_potencial": str(f["monto_potencial"])} for f in monto]}


@router.get("/api/seguimiento/reporte/ejecutivo", response_model=ReporteEjecutivo, summary="Reporte ejecutivo del período (§7.8)")
async def reporte(db: DB, actor: Actor = Depends(TODOS), desde: date | None = None, hasta: date | None = None, tenant_id: UUID | None = None):
    return ReporteEjecutivo(**await _reporte(db, actor, desde, hasta, tenant_id))


@router.get("/api/seguimiento/reporte/ejecutivo.xlsx", summary="Reporte ejecutivo en Excel")
async def reporte_excel(db: DB, actor: Actor = Depends(TODOS), desde: date | None = None, hasta: date | None = None, tenant_id: UUID | None = None):
    from openpyxl import Workbook

    r = await _reporte(db, actor, desde, hasta, tenant_id)
    wb = Workbook()
    ws = wb.active
    ws.title = "Resumen"
    ws.append(["Reporte ejecutivo de seguimiento", f"{desde or ''} – {hasta or ''}"])
    ws.append([])
    ws.append(["Módulo", "Registros", "Tiempo promedio de resolución (días)"])
    for k, v in r["totales"].items():
        ws.append([k, v, r["tiempo_promedio_resolucion_dias"].get(k)])
    ws.append([])
    ws.append(["Tasa de conversión de cotizaciones (%)", r["tasa_conversion_cotizaciones"]])
    for k, v in r["cotizaciones"].items():
        ws.append([f"Cotizaciones {k}", v])
    ws2 = wb.create_sheet("Hallazgos recurrentes")
    ws2.append(["Tipo de equipo", "Hallazgos"])
    for h in r["hallazgos_recurrentes"]:
        ws2.append([h["tipo_equipo"], h["total"]])
    ws3 = wb.create_sheet("Monto potencial")
    ws3.append(["UN", "Diferidos", "Monto potencial"])
    for m in r["monto_potencial"]:
        ws3.append([m["un_codigo"], m["diferidos"], float(Decimal(m["monto_potencial"]))])
    buf = io.BytesIO()
    wb.save(buf)
    return Response(buf.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": 'attachment; filename="reporte-seguimiento.xlsx"'})


@router.get("/api/seguimiento/reporte/ejecutivo.pdf", summary="Reporte ejecutivo en PDF")
async def reporte_pdf(db: DB, actor: Actor = Depends(TODOS), desde: date | None = None, hasta: date | None = None, tenant_id: UUID | None = None):
    import html as _html

    from services import pdf as pdf_svc

    r = await _reporte(db, actor, desde, hasta, tenant_id)
    e = _html.escape
    filas = "".join(f"<tr><td>{e(k)}</td><td>{v}</td><td>{r['tiempo_promedio_resolucion_dias'].get(k) if r['tiempo_promedio_resolucion_dias'].get(k) is not None else '—'}</td></tr>" for k, v in r["totales"].items())
    recurrentes = "".join(f"<li>{e(h['tipo_equipo'])}: {h['total']}</li>" for h in r["hallazgos_recurrentes"]) or "<li>Sin hallazgos</li>"
    html = f"""<html><body><h1>Reporte ejecutivo de seguimiento</h1><p>Período: {desde or '—'} a {hasta or '—'}</p>
    <h2>Tiempo promedio de resolución por módulo</h2><table><tr><th>Módulo</th><th>Registros</th><th>Días promedio</th></tr>{filas}</table>
    <h2>Cotizaciones</h2><p>Tasa de conversión: {r['tasa_conversion_cotizaciones']}%</p><ul>{''.join(f'<li>{e(k)}: {v}</li>' for k, v in r['cotizaciones'].items())}</ul>
    <h2>Hallazgos recurrentes por tipo de equipo</h2><ul>{recurrentes}</ul></body></html>"""
    return Response(pdf_svc.html_a_pdf(html), media_type="application/pdf", headers={"Content-Disposition": 'attachment; filename="reporte-seguimiento.pdf"'})



# ------------------------------------------------------------- listados

@router.get("/api/seguimiento/{modulo}", summary="Listado con filtros (§7.8): tenant, UN, período, estado y urgencia del hallazgo",
            description="Cada fila trae estado, días en el estado, alertas activas y próxima alerta. En Cotizaciones, la columna «Estado del trabajo especial» (P08) viene vacía.")
async def listar(modulo: str, db: DB, actor: Actor = Depends(TODOS), tenant_id: UUID | None = None, un_id: UUID | None = None, estado: str | None = None,
                 desde: date | None = None, hasta: date | None = None, urgencia: str | None = None) -> list[dict[str, Any]]:
    m = _modulo(modulo)
    estado_enum = ESTADOS[m](estado) if estado else None
    registros = await SERVICIOS[m].listar(db, actor, {"tenant_id": tenant_id, "un_id": un_id, "estado": estado_enum, "desde": desde, "hasta": hasta})
    filas = await _serializar(db, actor, m, registros)
    if urgencia:
        filas = [f for f in filas if f["urgencia_hallazgo"] is not None and f["urgencia_hallazgo"].value == urgencia]
    return [SALIDAS[m](**f).model_dump() for f in filas]


@router.get("/api/seguimiento/por-un/{un_id}", response_model=PorUNSalida, summary="Vista por UN: los cuatro módulos consolidados")
async def por_un(un_id: UUID, db: DB, actor: Actor = Depends(TODOS)):
    base.exigir_rol(actor, base.PRESTADOR | {Rol.admin_un, Rol.admin_empresa, Rol.supervisor_operadores}, "Vista por UN")
    salida: dict[str, Any] = {"un_id": un_id}
    for ruta, m in (("cotizaciones", ModuloDestino.cotizaciones), ("por_presupuesto", ModuloDestino.por_presupuesto), ("seguimiento_interno", ModuloDestino.seguimiento_interno),
                    ("reprogramacion", ModuloDestino.reprogramacion)):
        registros = await SERVICIOS[m].listar(db, actor, {"un_id": un_id})
        salida[ruta] = [SALIDAS[m](**f) for f in await _serializar(db, actor, m, registros)]
    return PorUNSalida(**salida)


@router.get("/api/seguimiento/{modulo}/{registro_id}", summary="Detalle del registro con historial")
async def detalle(modulo: str, registro_id: UUID, db: DB, actor: Actor = Depends(TODOS)) -> dict[str, Any]:
    m = _modulo(modulo)
    r = await base.obtener(db, actor, MODELOS[m], registro_id)
    fila = SALIDAS[m](**(await _serializar(db, actor, m, [r]))[0]).model_dump()
    hist = await base.historial_de(db, m, r.id)
    nombres = {u.id: u.nombre for u in (await db.execute(select(Usuario).where(Usuario.id.in_({h.usuario_id for h in hist if h.usuario_id})))).scalars()} if hist else {}
    fila["historial"] = [HistorialModuloSalida(id=h.id, modulo=h.modulo, registro_id=h.registro_id, estado_anterior=h.estado_anterior, estado_nuevo=h.estado_nuevo, usuario_id=h.usuario_id,
                                               usuario_nombre=nombres.get(h.usuario_id), actor_rol=h.actor_rol, timestamp=h.timestamp, notas=h.notas, datos_json=h.datos_json).model_dump() for h in hist]
    return fila


@router.post("/api/seguimiento/{modulo}", status_code=201, summary="Alta directa en un módulo (Admin UN / Admin empresa / prestador)")
async def crear(modulo: str, datos: CrearRegistroEntrada, request: Request, db: DB, actor: Actor = Depends(TODOS)) -> dict[str, Any]:
    m = _modulo(modulo)
    base.exigir_rol(actor, base.CLIENTE | base.PRESTADOR, "Crear registros de seguimiento")
    un = await db.get(UnidadNegocio, datos.un_id)
    if un is None or (actor.dominio == Dominio.tenant and un.tenant_id != actor.tenant_id):
        raise no_encontrado("Unidad")
    from models.organizaciones import TenantPrestador

    prestador_id = actor.prestador_id or (await db.execute(select(TenantPrestador.prestador_id).where(TenantPrestador.tenant_id == un.tenant_id))).scalar()
    comunes = dict(tenant_id=un.tenant_id, prestador_id=prestador_id, un_id=un.id, equipo_id=datos.equipo_id, descripcion=datos.descripcion, hallazgo_id=datos.hallazgo_id,
                   folio_id=datos.folio_id, origen="directo")
    if m == ModuloDestino.cotizaciones:
        r = await cotizaciones.crear(db, actor, **comunes, request=request)
    elif m == ModuloDestino.por_presupuesto:
        r = await presupuesto.crear(db, actor, **comunes)
    elif m == ModuloDestino.seguimiento_interno:
        r = await interno.crear(db, actor, **comunes)
    else:
        r = await reprogramacion.crear(db, actor, **comunes, motivo=datos.motivo, fecha_tentativa=datos.fecha_tentativa, trabajo_coordinado=datos.trabajo_coordinado,
                                       variante=datos.variante, proveedor=datos.proveedor)
    await db.commit()
    return SALIDAS[m](**(await _serializar(db, actor, m, [r]))[0]).model_dump()


@router.post("/api/seguimiento/{modulo}/{registro_id}/estado", summary="Cambiar estado (Kanban y acciones): valida rol, campos y justificación; registra historial")
async def cambiar_estado(modulo: str, registro_id: UUID, datos: CambioEstadoEntrada, request: Request, db: DB, actor: Actor = Depends(TODOS)) -> dict[str, Any]:
    m = _modulo(modulo)
    r = await base.obtener(db, actor, MODELOS[m], registro_id)
    try:
        nuevo = ESTADOS[m](datos.estado)
    except ValueError:
        raise ErrorAPI(422, "ESTADO_INVALIDO", f"Estado {datos.estado} no existe en {modulo}") from None
    await SERVICIOS[m].cambiar_estado(db, actor, r, nuevo, datos.notas, request, proveedor=datos.proveedor, fecha_acordada=datos.fecha_acordada,
                                      referencia_tercero=datos.referencia_tercero, descripcion=datos.descripcion, monto=datos.monto, detalle=datos.detalle,
                                      pasar_a_presupuesto=datos.pasar_a_presupuesto, como=datos.como)
    await db.commit()
    return SALIDAS[m](**(await _serializar(db, actor, m, [r]))[0]).model_dump()


__all__ = ["router", "prohibido"]
