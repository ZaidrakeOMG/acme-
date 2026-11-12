"""Reportes ejecutivos exportables y programados (ACT-8.4). P10.

Tres plantillas por destinatario (`cliente`, `prestador`, `jornada`), generadas en el servidor en PDF (WeasyPrint con el
generador mínimo de respaldo) y Excel (openpyxl) con el logo y los colores del prestador. Cada generación queda en
`reportes_generados` con su `archivo_key`, el número de filas y los milisegundos que tardó (ACT-8.4 pide medir el tiempo
con volúmenes de 1,000+ folios).
"""
import html as _html
import io
import logging
import time
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.dependencias import Actor
from core.errors import ErrorAPI, prohibido
from models.base import Dominio, FormatoReporte, PeriodicidadReporte, Rol
from models.organizaciones import Prestador
from models.reportes import ReporteGenerado, ReporteProgramado
from services import auditoria, bi_service, pdf, reportes_iso55000
from services.almacenamiento import dueno_de, obtener_almacenamiento
from services.bi_service import Filtro

log = logging.getLogger("acma.reportes")

PLANTILLAS = {
    "cliente": "Reporte ejecutivo del cliente",
    "prestador": "Reporte ejecutivo del prestador",
    "jornada": "Cierre de jornada",
    # F2-05: los cinco de certificación ISO 55000 (§6.9.3). Mismo generador, mismas secciones.
    **reportes_iso55000.PLANTILLAS,
}
# Quién puede pedir cada plantilla (§5.1, §5.2).
PERMISOS = {
    "cliente": {Rol.superadmin, Rol.admin_empresa, Rol.admin_un, Rol.admin_prestador, Rol.mesa_control},
    "prestador": {Rol.superadmin, Rol.admin_prestador, Rol.mesa_control, Rol.direccion_prestador, Rol.supervisor_prestador},
    "jornada": {Rol.superadmin, Rol.admin_prestador, Rol.supervisor_prestador, Rol.despachador, Rol.mesa_control},
    **{clave: reportes_iso55000.PERMISOS for clave in reportes_iso55000.PLANTILLAS},
}


def e(v: Any) -> str:
    return _html.escape("" if v is None else str(v))


async def _tema(db: AsyncSession, prestador_id: UUID | None) -> dict[str, str]:
    p = await db.get(Prestador, prestador_id) if prestador_id else None
    return {"nombre": p.razon_social if p else "ACMA", "primario": (p.color_primario if p else None) or "#1C3D8F",
            "acento": (p.color_acento if p else None) or "#A2C62B"}


# ----------------------------------------------------------- composición
async def secciones(db: AsyncSession, actor: Actor, tipo: str, f: Filtro) -> list[dict[str, Any]]:
    """Cada sección es {titulo, tipo: 'kpi'|'tabla', filas} para que PDF y Excel compartan el contenido."""
    if tipo in reportes_iso55000.PLANTILLAS:
        return await reportes_iso55000.secciones(db, actor, tipo, f)
    if tipo == "jornada":
        j = await bi_service.jornada(db, f)
        return [
            {"titulo": "Indicadores de la jornada", "tipo": "kpi", "filas": [
                ("Folios completados", f"{j['completados']} de {j['total_dia']}"),
                ("Técnicos con folios activos", j["tecnicos_activos"]),
                ("Alertas abiertas", j["alertas_abiertas"]),
                ("Tiempo promedio de atención (h)", j["tiempo_promedio_atencion_horas"]),
            ]},
            {"titulo": "Folios del período por estado", "tipo": "tabla", "columnas": ["Estado", "Folios"],
             "filas": sorted((await bi_service.folios_por_estado(db, f)).items())},
        ]
    if tipo == "prestador":
        sla = await bi_service.cumplimiento_sla(db, f)
        pen = await bi_service.penalizaciones(db, f)
        cot = await bi_service.cotizaciones(db, f)
        prev = await bi_service.preventivos(db, f)
        return [
            {"titulo": "Resumen del período", "tipo": "kpi", "filas": [
                ("Folios cerrados con SLA medido", sla["total"]),
                ("Cumplimiento de respuesta", f"{sla['respuesta_pct']} %"),
                ("Cumplimiento de resolución", f"{sla['resolucion_pct']} %"),
                ("Folios incumplidos", pen["folios_incumplidos"]),
                ("Penalización acumulada", f"${pen['monto']}"),
                ("Cotizaciones autorizadas", f"{cot['autorizadas']} de {cot['total']} ({cot['conversion_pct']} %)"),
                ("Monto cotizado autorizado", f"${cot['monto_autorizado']}"),
                ("Cumplimiento de preventivos", f"{prev['cumplimiento_pct']} %"),
            ]},
            {"titulo": "Folios por cliente", "tipo": "tabla", "columnas": ["Cliente", "Total", "Cerrados"],
             "filas": [(x["cliente"], x["total"], x["por_estado"].get("cerrado", 0)) for x in await bi_service._por_cliente(db, f)]},
            {"titulo": "Cumplimiento de SLA por severidad", "tipo": "tabla",
             "columnas": ["Severidad", "Folios", "Respuesta %", "Resolución %", "Penalizados"],
             "filas": [(k, v["total"], v["respuesta_pct"], v["resolucion_pct"], v["penalizados"])
                       for k, v in sorted(sla["por_severidad"].items())]},
            {"titulo": "Penalizaciones por período", "tipo": "tabla", "columnas": ["Período", "Estado", "Incumplidos", "Monto"],
             "filas": [(x["periodo"], x["estado"], x["folios_incumplidos"], x["monto"]) for x in pen["detalle"]]},
            {"titulo": "Consumo de iguala", "tipo": "tabla",
             "columnas": ["Contrato", "Período", "Correctivos incluidos", "Atendidos", "Adicionales", "Preventivos ejecutados"],
             "filas": [(x["contrato"], x["periodo"], x["correctivos_incluidos"], x["correctivos_atendidos"],
                        x["correctivos_adicionales"], x["preventivos_ejecutados"]) for x in await bi_service.iguala(db, f)]},
            {"titulo": "Carga por técnico", "tipo": "tabla", "columnas": ["Técnico", "Asignados", "Cerrados"],
             "filas": [(x["nombre"], x["asignados"], x["cerrados"]) for x in await bi_service.carga_por_tecnico(db, f)]},
        ]
    gasto = await bi_service.gasto_vs_presupuesto(db, f)
    sla = await bi_service.cumplimiento_sla(db, f)
    prev = await bi_service.preventivos(db, f)
    hal = await bi_service.hallazgos(db, f)
    mttr = await bi_service.mttr(db, f)
    mtbf = await bi_service.mtbf(db, f)
    anterior = await bi_service._resumen_nivel(db, f.anterior())
    anio = await bi_service._resumen_nivel(db, f.anio_anterior())
    jer = await bi_service.comparativo_jerarquia(db, f)
    return [
        {"titulo": "Resumen del período", "tipo": "kpi", "filas": [
            ("Presupuesto del período", f"${gasto['monto']}"),
            ("Consumido", f"${gasto['consumido']} ({gasto['porcentaje']} %)"),
            ("Disponible", f"${gasto['disponible']}"),
            ("Cumplimiento de resolución", f"{sla['resolucion_pct']} %"),
            ("MTTR (h)", mttr["horas"]),
            ("MTBF (h)", mtbf["horas"] + (f" · {mtbf['aviso']}" if mtbf["aviso"] else "")),
            ("Cumplimiento de preventivos", f"{prev['cumplimiento_pct']} %"),
            ("Hallazgos convertidos a cotización", f"{hal['convertidos_a_cotizacion']} de {hal['total']}"),
        ]},
        {"titulo": "Comparativo multi-período", "tipo": "tabla",
         "columnas": ["Período", "Folios", "Cerrados", "Resolución %", "Costo"],
         "filas": [("Actual", *_fila_nivel(await bi_service._resumen_nivel(db, f))),
                   ("Anterior", *_fila_nivel(anterior)), ("Mismo del año anterior", *_fila_nivel(anio))]},
        {"titulo": "Cumplimiento de SLA por severidad", "tipo": "tabla",
         "columnas": ["Severidad", "Folios", "Respuesta %", "Resolución %"],
         "filas": [(k, v["total"], v["respuesta_pct"], v["resolucion_pct"]) for k, v in sorted(sla["por_severidad"].items())]},
        {"titulo": "Comparativo por grupo", "tipo": "tabla", "columnas": ["Grupo", "Folios", "Cerrados", "Resolución %", "Costo"],
         "filas": [(x["nombre"], *_fila_nivel(x)) for x in jer["grupos"]]},
        {"titulo": "Comparativo por unidad de negocio", "tipo": "tabla",
         "columnas": ["Unidad", "Folios", "Cerrados", "Resolución %", "Costo"],
         "filas": [(x["nombre"], *_fila_nivel(x)) for x in jer["unidades"]]},
        {"titulo": "Top 10 equipos por costo", "tipo": "tabla", "columnas": ["Código", "Equipo", "Costo", "Fallas"],
         "filas": [(x["codigo"], x["nombre"], x["valor"], x["fallas"]) for x in await bi_service.top_equipos(db, f, "costo")]},
    ]


def _fila_nivel(n: dict) -> tuple:
    return n["folios"], n["cerrados"], n["sla_resolucion_pct"], n["costo"]


# ------------------------------------------------------------------ salida
def a_html(titulo: str, tema: dict[str, str], f: Filtro, bloques: list[dict]) -> str:
    partes = [f"<h1>{e(titulo)}</h1>",
              f"<p class='meta'>{e(tema['nombre'])} · período {f.desde} a {f.hasta} · generado {datetime.now(UTC):%d/%m/%Y %H:%M} UTC</p>"]
    for b in bloques:
        partes.append(f"<h2>{e(b['titulo'])}</h2>")
        if b["tipo"] == "kpi":
            partes.append("<table class='kpi'>" + "".join(f"<tr><th>{e(k)}</th><td>{e(v)}</td></tr>" for k, v in b["filas"]) + "</table>")
        elif b["filas"]:
            partes.append("<table><tr>" + "".join(f"<th>{e(c)}</th>" for c in b["columnas"]) + "</tr>"
                          + "".join("<tr>" + "".join(f"<td>{e(c)}</td>" for c in fila) + "</tr>" for fila in b["filas"]) + "</table>")
        else:
            partes.append("<p>Sin datos en el período.</p>")
    estilo = (f"body{{font-family:Arial;font-size:12px;color:#1f2937}} h1{{color:{tema['primario']};font-size:18px}}"
              f" h2{{font-size:14px;border-bottom:2px solid {tema['acento']}}} .meta{{color:#6b7280}}"
              " table{border-collapse:collapse;width:100%;margin-bottom:10px} td,th{border-bottom:1px solid #ddd;padding:5px;text-align:left}"
              " .kpi th{width:45%}")
    return f"<html><head><meta charset='utf-8'><style>{estilo}</style></head><body>{''.join(partes)}</body></html>"


def a_excel(titulo: str, tema: dict[str, str], f: Filtro, bloques: list[dict]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Resumen"
    relleno = PatternFill("solid", fgColor=tema["primario"].lstrip("#"))
    ws.append([titulo])
    ws["A1"].font = Font(bold=True, size=14)
    ws.append([f"{tema['nombre']} · período {f.desde} a {f.hasta}"])
    ws.append([])
    for b in bloques:
        hoja = ws if b["tipo"] == "kpi" else wb.create_sheet(b["titulo"][:31])
        if b["tipo"] == "kpi":
            hoja.append([b["titulo"]])
            hoja.cell(hoja.max_row, 1).font = Font(bold=True)
            for k, v in b["filas"]:
                hoja.append([k, v])
            hoja.append([])
            continue
        hoja.append(b["columnas"])
        for celda in hoja[1]:
            celda.font = Font(bold=True, color="FFFFFF")
            celda.fill = relleno
        for fila in b["filas"]:
            hoja.append(list(fila))
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


# ---------------------------------------------------------------- generar
async def generar(db: AsyncSession, actor: Actor, *, tipo: str, formato: FormatoReporte, filtro: Filtro,
                  programado: ReporteProgramado | None = None, request=None) -> tuple[ReporteGenerado, bytes]:
    if tipo not in PLANTILLAS:
        raise ErrorAPI(422, "TIPO_DESCONOCIDO", f"Las plantillas disponibles son {', '.join(PLANTILLAS)}")
    if actor.rol not in PERMISOS[tipo]:
        raise prohibido(f"Tu rol no puede generar el reporte «{PLANTILLAS[tipo]}»")
    inicio = time.monotonic()
    bloques = await secciones(db, actor, tipo, filtro)
    tema = await _tema(db, filtro.prestador_id or actor.prestador_id)
    titulo = PLANTILLAS[tipo]
    if formato == FormatoReporte.pdf:
        datos = pdf.html_a_pdf(a_html(titulo, tema, filtro, bloques))
        mime, ext = "application/pdf", "pdf"
    else:
        datos = a_excel(titulo, tema, filtro, bloques)
        mime, ext = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"
    ms = int((time.monotonic() - inicio) * 1000)
    filas = sum(len(b["filas"]) for b in bloques)
    clave = (f"reportes/{filtro.tenant_id or filtro.prestador_id or 'plataforma'}/{tipo}-{filtro.desde}-{filtro.hasta}"
             f"-{datetime.now(UTC):%Y%m%d%H%M%S}.{ext}")
    obtener_almacenamiento().guardar(clave, datos, mime, dueno=dueno_de(filtro.tenant_id, filtro.prestador_id))
    registro = ReporteGenerado(programado_id=programado.id if programado else None, tenant_id=filtro.tenant_id,
                               prestador_id=filtro.prestador_id, tipo_reporte=tipo, formato=formato,
                               filtros_json={"desde": str(filtro.desde), "hasta": str(filtro.hasta),
                                             "grupo_id": str(filtro.grupo_id) if filtro.grupo_id else None,
                                             "un_id": str(filtro.un_id) if filtro.un_id else None},
                               archivo_key=clave, filas=filas, ms_generacion=ms, generado_por=getattr(actor, "id", None))
    db.add(registro)
    await db.flush()
    if getattr(actor, "id", None) is not None:
        await auditoria.registrar_actor(db, actor, "reporte.generado", request, tenant_id=filtro.tenant_id,
                                        prestador_id=filtro.prestador_id, recurso_tipo="reportes_generados",
                                        recurso_id=registro.id,
                                        despues={"tipo": tipo, "formato": formato.value, "ms": ms, "filas": filas})
    log.info("Reporte %s (%s) en %s ms con %s filas", tipo, formato.value, ms, filas)
    return registro, datos


# ------------------------------------------------------------ programados
async def crear_programado(db: AsyncSession, actor: Actor, datos: dict[str, Any]) -> ReporteProgramado:
    tipo = datos.get("tipo_reporte")
    if tipo not in PLANTILLAS:
        raise ErrorAPI(422, "TIPO_DESCONOCIDO", f"Las plantillas disponibles son {', '.join(PLANTILLAS)}")
    if actor.rol not in PERMISOS[tipo]:
        raise prohibido(f"Tu rol no puede programar el reporte «{PLANTILLAS[tipo]}»")
    r = ReporteProgramado(
        tenant_id=actor.tenant_id if actor.dominio == Dominio.tenant else None,
        prestador_id=actor.prestador_id if actor.dominio != Dominio.tenant else None,
        nombre=(datos.get("nombre") or PLANTILLAS[tipo])[:160], tipo_reporte=tipo,
        filtros_json=datos.get("filtros_json") or {}, formato=FormatoReporte(datos.get("formato") or "pdf"),
        periodicidad=PeriodicidadReporte(datos.get("periodicidad") or "mensual"),
        dia_hora=(datos.get("dia_hora") or "08:00")[:16],
        destinatarios_json=[str(x) for x in (datos.get("destinatarios_json") or [])],
        activo=bool(datos.get("activo", True)), created_by=actor.id)
    db.add(r)
    await db.flush()
    return r


async def listar_programados(db: AsyncSession, actor: Actor) -> list[ReporteProgramado]:
    consulta = select(ReporteProgramado).order_by(ReporteProgramado.created_at.desc())
    if actor.rol != Rol.superadmin:
        if actor.dominio == Dominio.tenant:
            consulta = consulta.where(ReporteProgramado.tenant_id == actor.tenant_id)
        else:
            consulta = consulta.where(ReporteProgramado.prestador_id == actor.prestador_id)
    return list((await db.execute(consulta)).scalars())


def toca_hoy(r: ReporteProgramado, hoy: date | None = None) -> bool:
    """¿Le corresponde envío hoy? `dia_hora` admite "08:00", "lunes 08:00" o "1 08:00" (día del mes)."""
    hoy = hoy or date.today()
    partes = r.dia_hora.split()
    if r.periodicidad == PeriodicidadReporte.diaria:
        return True
    if r.periodicidad == PeriodicidadReporte.semanal:
        dias = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]
        objetivo = partes[0].lower() if len(partes) > 1 else "lunes"
        return dias.index(objetivo) == hoy.weekday() if objetivo in dias else hoy.weekday() == 0
    dia = int(partes[0]) if len(partes) > 1 and partes[0].isdigit() else 1
    return hoy.day == min(dia, 28)


def periodo_de(r: ReporteProgramado, hoy: date | None = None) -> tuple[date, date]:
    from datetime import timedelta

    hoy = hoy or date.today()
    if r.periodicidad == PeriodicidadReporte.diaria:
        return hoy, hoy
    if r.periodicidad == PeriodicidadReporte.semanal:
        return hoy - timedelta(days=7), hoy
    primero = hoy.replace(day=1)
    anterior = primero - timedelta(days=1)
    return anterior.replace(day=1), anterior
