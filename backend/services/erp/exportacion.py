"""Exportación universal por período (§6.6): XML con estructura estándar de pólizas contables y Excel con columnas
configurables en `erp_configuracion.columnas_excel_json`. Marca los eventos incluidos. P09."""
import io
import xml.etree.ElementTree as ET
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import Request
from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.dependencias import Actor
from core.errors import ErrorAPI, no_encontrado, prohibido
from models.base import Rol
from models.costos import ErpEventoPendiente, ErpExportacion, EstadoEventoERP, OperacionERP
from models.inventario import FormatoPoliza
from models.organizaciones import Prestador
from services import auditoria
from services.almacenamiento import obtener_almacenamiento
from services.erp import eventos as erp_eventos

EXPORTAN = {Rol.superadmin, Rol.admin_prestador}
CONCEPTO = {
    OperacionERP.generar_oc: "Orden de compra",
    OperacionERP.registrar_gasto: "Gasto de folio de servicio",
    OperacionERP.crear_activo_fijo: "Alta de activo fijo",
    OperacionERP.poliza_caja_chica: "Póliza de reposición de caja chica",
}


def _decimal(valor: Any) -> Decimal:
    try:
        return Decimal(str(valor or 0))
    except Exception:  # noqa: BLE001
        return Decimal("0")


def _fila(e: ErpEventoPendiente, cuentas: dict[str, Any], centros: dict[str, Any]) -> dict[str, Any]:
    p = e.payload_json or {}
    total = _decimal(p.get("total") or p.get("valor_reposicion"))
    subtotal = _decimal(p.get("costo_refacciones")) + _decimal(p.get("costo_mano_obra")) + _decimal(p.get("costo_otros")) if e.operacion == OperacionERP.registrar_gasto else total
    referencia = p.get("numero") or p.get("numero_folio") or p.get("codigo") or str(e.entidad_id or "")
    return {
        "fecha": str(p.get("fecha") or p.get("fecha_cierre") or e.created_at.date().isoformat())[:10],
        "tipo": e.operacion.value,
        "referencia": referencia,
        "concepto": CONCEPTO.get(e.operacion, e.operacion.value),
        "centro_costos": p.get("centro_costos") or centros.get(e.operacion.value, ""),
        "cuenta_contable": cuentas.get(e.operacion.value, ""),
        "subtotal": subtotal or total,
        "iva": _decimal(p.get("iva")),
        "total": total or subtotal,
        "moneda": p.get("moneda") or "MXN",
        "entidad": e.entidad,
        "entidad_id": str(e.entidad_id or ""),
    }


def xml_polizas(prestador: Prestador | None, desde: date, hasta: date, filas: list[dict[str, Any]]) -> bytes:
    """Estructura estándar de pólizas contables: una póliza por evento con su movimiento de cargo."""
    raiz = ET.Element("Polizas", {"version": "1.0", "rfc": (prestador.rfc if prestador else ""), "razonSocial": (prestador.razon_social if prestador else ""),
                                  "desde": desde.isoformat(), "hasta": hasta.isoformat(), "generado": datetime.now(UTC).isoformat()})
    for i, f in enumerate(filas, start=1):
        pol = ET.SubElement(raiz, "Poliza", {"numero": str(i), "fecha": str(f["fecha"]), "concepto": f["concepto"], "tipo": f["tipo"]})
        ET.SubElement(pol, "Movimiento", {"cuenta": str(f["cuenta_contable"]), "centroCostos": str(f["centro_costos"]), "referencia": str(f["referencia"]),
                                          "cargo": f"{f['total']:.2f}", "abono": "0.00", "moneda": str(f["moneda"])})
    return ET.tostring(raiz, encoding="utf-8", xml_declaration=True)


def excel_eventos(columnas: list[str], filas: list[dict[str, Any]], titulo: str) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Exportación ERP"
    ws.append([titulo])
    ws.append([])
    ws.append([c.replace("_", " ").capitalize() for c in columnas])
    for f in filas:
        ws.append([float(f[c]) if isinstance(f.get(c), Decimal) else f.get(c, "") for c in columnas])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


async def exportar(db: AsyncSession, actor: Actor, *, desde: date, hasta: date, formato: FormatoPoliza = FormatoPoliza.excel,
                   prestador_id: UUID | None = None, request: Request | None = None) -> ErpExportacion:
    if not actor.es_superadmin and actor.rol not in EXPORTAN:
        raise prohibido("Solo el Admin prestador genera la exportación para el ERP")
    pid = prestador_id if (prestador_id and actor.es_superadmin) else actor.prestador_id
    if pid is None:
        raise ErrorAPI(422, "PRESTADOR_REQUERIDO", "Indica el prestador")
    if hasta < desde:
        raise ErrorAPI(422, "PERIODO_INVALIDO", "La fecha final no puede ser anterior a la inicial")
    cfg = await erp_eventos.configuracion(db, pid, crear=True)
    columnas = [c for c in (cfg.columnas_excel_json or erp_eventos.COLUMNAS_DEFECTO)]
    pendientes = list((await db.execute(select(ErpEventoPendiente).where(
        ErpEventoPendiente.prestador_id == pid, ErpEventoPendiente.exportacion_id.is_(None),
        ErpEventoPendiente.created_at >= datetime.combine(desde, datetime.min.time(), tzinfo=UTC),
        ErpEventoPendiente.created_at <= datetime.combine(hasta, datetime.max.time(), tzinfo=UTC)).order_by(ErpEventoPendiente.created_at))).scalars())
    filas = [_fila(e, cfg.cuentas_contables_json or {}, cfg.centros_costos_json or {}) for e in pendientes]
    prestador = await db.get(Prestador, pid)
    exp = ErpExportacion(prestador_id=pid, periodo_inicio=desde, periodo_fin=hasta, formato=formato, eventos_incluidos=len(pendientes),
                         total=sum((f["total"] for f in filas), Decimal("0")), generado_por=actor.id)
    db.add(exp)
    await db.flush()
    almacen = obtener_almacenamiento()
    titulo = f"Exportación ERP {prestador.razon_social if prestador else ''} · {desde} a {hasta}"
    exp.archivo_key = f"erp/{pid}/{exp.id}.xlsx"
    almacen.guardar(exp.archivo_key, excel_eventos(columnas, filas, titulo), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    exp.archivo_xml_key = f"erp/{pid}/{exp.id}.xml"
    almacen.guardar(exp.archivo_xml_key, xml_polizas(prestador, desde, hasta, filas), "application/xml")
    for e in pendientes:
        e.exportacion_id = exp.id
        if e.estado == EstadoEventoERP.pendiente:
            e.estado, e.procesado_at = EstadoEventoERP.procesado, datetime.now(UTC)
            e.respuesta_json = {**(e.respuesta_json or {}), "exportacion_id": str(exp.id), "detalle": "Incluido en la exportación universal"}
    await db.flush()
    await auditoria.registrar_actor(db, actor, "erp.exportacion", request, prestador_id=pid, recurso_tipo="erp_exportacion", recurso_id=exp.id,
                                    despues={"desde": desde.isoformat(), "hasta": hasta.isoformat(), "eventos": len(pendientes), "total": str(exp.total)})
    return exp


async def archivo(db: AsyncSession, actor: Actor, exportacion_id: UUID, formato: str) -> tuple[bytes, str, str]:
    exp = await db.get(ErpExportacion, exportacion_id)
    if exp is None or (not actor.es_superadmin and exp.prestador_id != actor.prestador_id):
        raise no_encontrado("Exportación")
    clave = exp.archivo_xml_key if formato == "xml" else exp.archivo_key
    if not clave:
        raise no_encontrado("Archivo de la exportación")
    mime = "application/xml" if formato == "xml" else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return obtener_almacenamiento().leer(clave), mime, f"erp-{exp.periodo_inicio}-{exp.periodo_fin}.{'xml' if formato == 'xml' else 'xlsx'}"


async def listar_eventos(db: AsyncSession, actor: Actor, *, estado: EstadoEventoERP | None = None, limite: int = 100) -> list[ErpEventoPendiente]:
    if not actor.es_superadmin and actor.rol not in EXPORTAN | {Rol.mesa_control, Rol.despachador, Rol.direccion_prestador}:
        raise prohibido("Tu rol no consulta los eventos del ERP")
    consulta = select(ErpEventoPendiente).order_by(ErpEventoPendiente.created_at.desc()).limit(min(limite, 500))
    if not actor.es_superadmin:
        consulta = consulta.where(ErpEventoPendiente.prestador_id == actor.prestador_id)
    if estado:
        consulta = consulta.where(ErpEventoPendiente.estado == estado)
    return list((await db.execute(consulta)).scalars())


async def listar_exportaciones(db: AsyncSession, actor: Actor) -> list[ErpExportacion]:
    if not actor.es_superadmin and actor.rol not in EXPORTAN | {Rol.direccion_prestador}:
        raise prohibido("Tu rol no consulta las exportaciones del ERP")
    consulta = select(ErpExportacion).order_by(ErpExportacion.created_at.desc())
    if not actor.es_superadmin:
        consulta = consulta.where(ErpExportacion.prestador_id == actor.prestador_id)
    return list((await db.execute(consulta)).scalars())
