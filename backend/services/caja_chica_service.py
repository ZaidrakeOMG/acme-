"""Caja chica con captura manual (§6.4 Tipo C y §6.5): fondo fijo por técnico, captura de la factura desde la atención del
folio (operable offline), aprobación en un toque del Admin prestador que genera los tres registros de §6.4 en una sola
transacción, y reposición diaria en Excel (12 columnas literales de §6.5) y XML de póliza. P09."""
import base64
import io
import xml.etree.ElementTree as ET
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import Request
from openpyxl import Workbook
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.dependencias import Actor
from core.errors import ErrorAPI, no_encontrado, prohibido
from models.base import EstadoRegistro, Rol
from models.folios import EstadoFolio, Folio, FolioEvidencia, FolioRefaccion, OrigenRefaccion, TipoEvidenciaFolio
from models.inventario import (
    Articulo, EstadoGastoCajaChica, FondoCajaChica, FormatoPoliza, GastoCajaChica, PolizaExportacion, TipoMovimientoInventario, UbicacionInventario,
)
from models.organizaciones import Prestador
from models.usuarios import Usuario
from services import alertas_service, auditoria, inventario_service, notificaciones_service, permisos_service, sat_validator
from services.almacenamiento import obtener_almacenamiento
from services.folio_estados import ActorFolio

ADMINISTRAN = {Rol.superadmin, Rol.admin_prestador}
CONSULTAN = ADMINISTRAN | {Rol.despachador, Rol.mesa_control, Rol.direccion_prestador}
CERO = Decimal("0")
# §6.5: columnas literales del reporte de reposición.
COLUMNAS_POLIZA = ["Fecha", "Proveedor", "RFC", "Folio fiscal", "Descripción", "Monto", "IVA", "Total", "Centro de costos", "Cuenta contable",
                   "Técnico", "Folio de servicio"]


# ----------------------------------------------------------------- fondos

async def fondo_de(db: AsyncSession, prestador_id: UUID, tecnico_id: UUID) -> FondoCajaChica | None:
    return (await db.execute(select(FondoCajaChica).where(FondoCajaChica.prestador_id == prestador_id,
                                                          FondoCajaChica.tecnico_id == tecnico_id))).scalar_one_or_none()


async def crear_fondo(db: AsyncSession, actor: Actor, *, tecnico_id: UUID, monto_inicial: Decimal, umbral_alerta_pct: Decimal | None = None,
                      request: Request | None = None) -> FondoCajaChica:
    if not actor.es_superadmin and actor.rol not in ADMINISTRAN:
        raise prohibido("Solo el Admin prestador autoriza fondos de caja chica")
    u = await db.get(Usuario, tecnico_id)
    if u is None or u.rol != Rol.tecnico or (actor.prestador_id and u.prestador_id != actor.prestador_id):
        raise ErrorAPI(422, "TECNICO_INVALIDO", "El fondo de caja chica se autoriza a un técnico del prestador")
    prestador_id = u.prestador_id
    if await fondo_de(db, prestador_id, tecnico_id):
        raise ErrorAPI(409, "FONDO_DUPLICADO", "El técnico ya tiene un fondo de caja chica")
    f = FondoCajaChica(prestador_id=prestador_id, tecnico_id=tecnico_id, monto_inicial=monto_inicial, saldo_actual=monto_inicial,
                       umbral_alerta_pct=umbral_alerta_pct if umbral_alerta_pct is not None else Decimal("20"))
    db.add(f)
    await db.flush()
    await auditoria.registrar_actor(db, actor, "caja_chica.fondo_creado", request, prestador_id=prestador_id, recurso_tipo="fondo_caja_chica",
                                    recurso_id=f.id, despues={"tecnico_id": str(tecnico_id), "monto_inicial": str(monto_inicial)})
    return f


async def reponer_fondo(db: AsyncSession, actor: Actor, fondo: FondoCajaChica, monto: Decimal | None = None, request: Request | None = None) -> FondoCajaChica:
    """§6.5: el Admin prestador restablece el saldo del fondo tras entregar la póliza de reposición al contador."""
    if not actor.es_superadmin and actor.rol not in ADMINISTRAN:
        raise prohibido("Solo el Admin prestador repone el fondo")
    antes = auditoria.instantanea(fondo)
    fondo.saldo_actual = monto if monto is not None else fondo.monto_inicial
    fondo.fecha_ultima_reposicion = date.today()
    await db.flush()
    await auditoria.registrar_actor(db, actor, "caja_chica.fondo_repuesto", request, prestador_id=fondo.prestador_id, recurso_tipo="fondo_caja_chica",
                                    recurso_id=fondo.id, antes=antes, despues=auditoria.instantanea(fondo))
    return fondo


async def listar_fondos(db: AsyncSession, actor: Actor) -> list[dict[str, Any]]:
    consulta = select(FondoCajaChica).order_by(FondoCajaChica.created_at)
    if actor.rol == Rol.tecnico:
        consulta = consulta.where(FondoCajaChica.tecnico_id == actor.id)
    elif not actor.es_superadmin:
        if actor.rol not in CONSULTAN:
            raise prohibido("Tu rol no consulta los fondos de caja chica")
        consulta = consulta.where(FondoCajaChica.prestador_id == actor.prestador_id)
    fondos = list((await db.execute(consulta)).scalars())
    if not fondos:
        return []
    nombres = {u.id: u.nombre for u in (await db.execute(select(Usuario).where(Usuario.id.in_({f.tecnico_id for f in fondos})))).scalars()}
    salida = []
    for f in fondos:
        pendientes = (await db.execute(select(func.count()).select_from(GastoCajaChica).where(
            GastoCajaChica.fondo_id == f.id, GastoCajaChica.estado == EstadoGastoCajaChica.capturado))).scalar() or 0
        pct = (f.saldo_actual / f.monto_inicial * 100) if f.monto_inicial > CERO else Decimal("100")
        salida.append({**auditoria.instantanea(f), "id": f.id, "tecnico_id": f.tecnico_id, "tecnico_nombre": nombres.get(f.tecnico_id),
                       "prestador_id": f.prestador_id, "monto_inicial": f.monto_inicial, "saldo_actual": f.saldo_actual, "moneda": f.moneda,
                       "umbral_alerta_pct": f.umbral_alerta_pct, "fecha_ultima_reposicion": f.fecha_ultima_reposicion, "activo": f.activo,
                       "porcentaje_saldo": pct.quantize(Decimal("0.01")), "bajo_umbral": pct <= f.umbral_alerta_pct,
                       "gastos_pendientes": pendientes, "created_at": f.created_at, "updated_at": f.updated_at})
    return salida


# ------------------------------------------------------------------ gastos

async def capturar_gasto(db: AsyncSession, actor: ActorFolio, *, folio_id: UUID | None, proveedor: str, rfc_proveedor: str | None, uuid_cfdi: str | None,
                         descripcion: str, numero_parte: str | None, subtotal: Decimal, iva: Decimal, monto: Decimal | None = None,
                         articulo_id: UUID | None = None, cantidad: Decimal = Decimal("1"), imagen_base64: str | None = None, nombre_imagen: str | None = None,
                         mime: str | None = None, evidencia_id: UUID | None = None, centro_costos: str = "", cuenta_contable: str = "",
                         momento: datetime | None = None, tecnico_id: UUID | None = None, request: Request | None = None) -> GastoCajaChica:
    """El técnico captura la factura desde la atención del folio (P05). Requiere el permiso `usar_caja_chica` (§6.8.3)."""
    tecnico_id = tecnico_id or getattr(actor, "id", None)
    u = await db.get(Usuario, tecnico_id)
    if u is None:
        raise no_encontrado("Técnico")
    prestador_id = u.prestador_id
    if u.rol == Rol.tecnico:
        permisos = {p["clave"]: p["habilitado"] for p in await permisos_service.efectivos_de_tecnico(db, prestador_id, u.id)}
        if not permisos.get("usar_caja_chica", False):
            raise ErrorAPI(403, "SIN_PERMISO_CAJA_CHICA", f"{u.nombre} no tiene habilitado usar_caja_chica (§6.8.3)")
    fondo = await fondo_de(db, prestador_id, tecnico_id)
    if fondo is None or not fondo.activo:
        raise ErrorAPI(409, "SIN_FONDO", "El técnico no tiene un fondo de caja chica activo")
    folio = await db.get(Folio, folio_id) if folio_id else None
    if folio is not None:
        if folio.prestador_id != prestador_id:
            raise no_encontrado("Folio")
        if folio.estado in (EstadoFolio.cerrado, EstadoFolio.cancelado):
            raise ErrorAPI(409, "FOLIO_INMUTABLE", "El folio está cerrado o cancelado")
        if getattr(actor, "rol", None) == Rol.tecnico and folio.tecnico_id != actor.id:
            raise prohibido("El folio no está asignado a ti")
    total = monto if monto is not None else (subtotal + iva)
    imagen_key = None
    if imagen_base64:
        datos = base64.b64decode(imagen_base64)
        imagen_key = f"caja_chica/{prestador_id}/{datetime.now(UTC):%Y/%m}/{(nombre_imagen or 'factura.jpg')[:60]}-{int(datetime.now(UTC).timestamp() * 1000)}"
        obtener_almacenamiento().guardar(imagen_key, datos, mime or "image/jpeg")
    g = GastoCajaChica(prestador_id=prestador_id, tenant_id=folio.tenant_id if folio else None, fondo_id=fondo.id, folio_id=folio.id if folio else None,
                       tecnico_id=tecnico_id, proveedor=proveedor.strip()[:200], rfc_proveedor=(rfc_proveedor or "").strip().upper() or None,
                       uuid_cfdi=(uuid_cfdi or "").strip() or None, descripcion=descripcion.strip()[:300], numero_parte=(numero_parte or "").strip() or None,
                       articulo_id=articulo_id, cantidad=cantidad, subtotal=subtotal, iva=iva, monto=total, imagen_key=imagen_key, evidencia_id=evidencia_id,
                       centro_costos=centro_costos, cuenta_contable=cuenta_contable, timestamp_dispositivo=momento, timestamp=momento or datetime.now(UTC))
    db.add(g)
    await db.flush()
    # Fase 1: el validador SAT es `stub` y deja el CFDI en `no_validado` dejando constancia de la consulta.
    if g.uuid_cfdi:
        r = await sat_validator.validar(db, prestador_id=prestador_id, uuid_cfdi=g.uuid_cfdi, rfc_emisor=g.rfc_proveedor, total=g.monto, gasto_id=g.id)
        g.estado_cfdi = r.estado
    if folio is not None and imagen_key:
        db.add(FolioEvidencia(folio_id=folio.id, tenant_id=folio.tenant_id, prestador_id=prestador_id, evidencia_id=evidencia_id,
                              tipo=TipoEvidenciaFolio.factura, archivo_key=imagen_key, subido_por=tecnico_id))
    await db.flush()
    await auditoria.registrar(db, "caja_chica.gasto_capturado", actor_rol=str(getattr(actor, "rol", "tecnico")), actor_id=getattr(actor, "id", None),
                              prestador_id=prestador_id, tenant_id=g.tenant_id, recurso_tipo="gasto_caja_chica", recurso_id=g.id,
                              despues={"proveedor": g.proveedor, "monto": str(g.monto), "folio_id": str(folio.id) if folio else None}, request=request)
    destinatarios = await notificaciones_service.destinatarios_por_rol(db, [Rol.admin_prestador], prestador_id=prestador_id)
    await notificaciones_service.notificar(db, "caja_chica.por_aprobar", destinatarios,
                                           {"gasto_id": str(g.id), "monto": str(g.monto), "proveedor": g.proveedor, "tiene_foto": bool(imagen_key),
                                            "folio_id": str(folio.id) if folio else None},
                                           asunto=f"Gasto de caja chica por ${g.monto:,.2f} de {u.nombre}: aprueba o rechaza",
                                           cuerpo=f"{g.proveedor} · {g.descripcion[:160]}" + (f" · folio {folio.numero_folio}" if folio else ""),
                                           url=f"/caja-chica?gasto={g.id}", prestador_id=prestador_id, tenant_id=g.tenant_id)
    return g


async def obtener_gasto(db: AsyncSession, actor: Actor, gasto_id: UUID) -> GastoCajaChica:
    g = await db.get(GastoCajaChica, gasto_id)
    if g is None:
        raise no_encontrado("Gasto de caja chica")
    if actor.es_superadmin:
        return g
    if actor.rol == Rol.tecnico and g.tecnico_id == actor.id:
        return g
    if actor.rol in CONSULTAN and g.prestador_id == actor.prestador_id:
        return g
    raise no_encontrado("Gasto de caja chica")


async def aprobar_gasto(db: AsyncSession, actor: Actor, g: GastoCajaChica, request: Request | None = None) -> dict[str, Any]:
    """§6.4 Tipo C: al aprobar, en una sola transacción, alta de la refacción vinculada al folio, movimiento de inventario
    (entrada + salida inmediata con origen `caja_chica`) y el gasto que afecta el saldo del fondo. El folio se desbloquea."""
    if not actor.es_superadmin and actor.rol not in ADMINISTRAN:
        raise prohibido("Solo el Admin prestador aprueba los gastos de caja chica")
    if g.estado != EstadoGastoCajaChica.capturado:
        raise ErrorAPI(409, "GASTO_YA_RESUELTO", f"El gasto ya está {g.estado.value}")
    fondo = await db.get(FondoCajaChica, g.fondo_id)
    if fondo is None:
        raise no_encontrado("Fondo de caja chica")
    if fondo.saldo_actual < g.monto:
        # §6.7: el fondo no puede quedar en saldo negativo.
        raise ErrorAPI(409, "SALDO_INSUFICIENTE", f"El fondo tiene ${fondo.saldo_actual:,.2f} y el gasto es de ${g.monto:,.2f}",
                       [{"saldo_actual": str(fondo.saldo_actual), "monto": str(g.monto)}])
    folio = await db.get(Folio, g.folio_id) if g.folio_id else None
    refaccion = None
    movimientos: list[UUID] = []
    if folio is not None:
        refaccion = FolioRefaccion(folio_id=folio.id, tenant_id=folio.tenant_id, prestador_id=folio.prestador_id, articulo_id=g.articulo_id,
                                   descripcion=g.descripcion[:200], cantidad=g.cantidad, origen=OrigenRefaccion.caja_chica,
                                   costo_unitario=(g.subtotal / g.cantidad).quantize(Decimal("0.01")) if g.cantidad > CERO else g.subtotal,
                                   gasto_caja_chica_id=g.id)
        db.add(refaccion)
        await db.flush()
    if g.articulo_id:
        articulo = await db.get(Articulo, g.articulo_id)
        ubicacion = await inventario_service.vehiculo_de(db, g.tecnico_id) or await inventario_service.almacen_principal(db, g.prestador_id)
        if articulo is not None and ubicacion is not None:
            costo = (g.subtotal / g.cantidad).quantize(Decimal("0.01")) if g.cantidad > CERO else g.subtotal
            entrada = await inventario_service._mover(db, actor, prestador_id=g.prestador_id, articulo=articulo, tipo=TipoMovimientoInventario.entrada,
                                                      cantidad=g.cantidad, origen_ub=None, destino_ub=ubicacion, costo_unitario=costo,
                                                      origen=OrigenRefaccion.caja_chica, folio_id=g.folio_id, gasto_id=g.id, tenant_id=g.tenant_id,
                                                      referencia=g.uuid_cfdi, razon=f"Compra de caja chica: {g.proveedor}")
            salida = await inventario_service._mover(db, actor, prestador_id=g.prestador_id, articulo=articulo, tipo=TipoMovimientoInventario.consumo_folio,
                                                     cantidad=g.cantidad, origen_ub=ubicacion, destino_ub=None, costo_unitario=costo,
                                                     origen=OrigenRefaccion.caja_chica, folio_id=g.folio_id, gasto_id=g.id,
                                                     refaccion_id=refaccion.id if refaccion else None, tenant_id=g.tenant_id,
                                                     razon="Salida inmediata al folio (§6.4 Tipo C)", permitir_negativo=True)
            movimientos = [entrada.id, salida.id]
            if refaccion is not None:
                refaccion.ubicacion_id = ubicacion.id
    fondo.saldo_actual = fondo.saldo_actual - g.monto
    g.estado, g.aprobado_por, g.aprobado_at = EstadoGastoCajaChica.aprobado, actor.id, datetime.now(UTC)
    await db.flush()
    await auditoria.registrar_actor(db, actor, "caja_chica.gasto_aprobado", request, prestador_id=g.prestador_id, tenant_id=g.tenant_id,
                                    recurso_tipo="gasto_caja_chica", recurso_id=g.id,
                                    despues={"monto": str(g.monto), "saldo_fondo": str(fondo.saldo_actual), "refaccion_id": str(refaccion.id) if refaccion else None,
                                             "movimientos": [str(m) for m in movimientos]})
    await _revisar_fondo(db, fondo)
    await notificaciones_service.notificar(db, "caja_chica.resuelto", [g.tecnico_id], {"gasto_id": str(g.id), "estado": "aprobado", "monto": str(g.monto)},
                                           asunto=f"Gasto de caja chica aprobado: ${g.monto:,.2f}",
                                           cuerpo="Puedes continuar con la instalación; el folio queda desbloqueado para cierre.",
                                           url=f"/campo/folio/{g.folio_id}" if g.folio_id else "/caja-chica", prestador_id=g.prestador_id, tenant_id=g.tenant_id)
    return {"gasto": g, "refaccion": refaccion, "movimientos": movimientos, "saldo_fondo": fondo.saldo_actual}


async def rechazar_gasto(db: AsyncSession, actor: Actor, g: GastoCajaChica, razon: str, request: Request | None = None) -> GastoCajaChica:
    if not actor.es_superadmin and actor.rol not in ADMINISTRAN:
        raise prohibido("Solo el Admin prestador rechaza los gastos de caja chica")
    if g.estado != EstadoGastoCajaChica.capturado:
        raise ErrorAPI(409, "GASTO_YA_RESUELTO", f"El gasto ya está {g.estado.value}")
    if not (razon or "").strip():
        raise ErrorAPI(422, "RAZON_REQUERIDA", "Rechazar un gasto de caja chica exige razón")
    g.estado, g.razon_rechazo, g.aprobado_por, g.aprobado_at = EstadoGastoCajaChica.rechazado, razon.strip(), actor.id, datetime.now(UTC)
    await db.flush()
    await auditoria.registrar_actor(db, actor, "caja_chica.gasto_rechazado", request, prestador_id=g.prestador_id, tenant_id=g.tenant_id,
                                    recurso_tipo="gasto_caja_chica", recurso_id=g.id, despues={"monto": str(g.monto), "razon": razon})
    await notificaciones_service.notificar(db, "caja_chica.resuelto", [g.tecnico_id], {"gasto_id": str(g.id), "estado": "rechazado", "razon": razon},
                                           asunto=f"Gasto de caja chica rechazado: ${g.monto:,.2f}", cuerpo=razon,
                                           url=f"/campo/folio/{g.folio_id}" if g.folio_id else "/caja-chica", prestador_id=g.prestador_id, tenant_id=g.tenant_id)
    return g


async def _revisar_fondo(db: AsyncSession, fondo: FondoCajaChica) -> None:
    if fondo.monto_inicial <= CERO:
        return
    pct = fondo.saldo_actual / fondo.monto_inicial * 100
    if pct > fondo.umbral_alerta_pct:
        return
    await alertas_service.disparar(db, "FONDO_CAJA_CHICA_BAJO", tenant_id=None, prestador_id=fondo.prestador_id, entidad_tipo="fondo_caja_chica",
                                   entidad_id=fondo.id, datos={"saldo": str(fondo.saldo_actual), "monto_inicial": str(fondo.monto_inicial),
                                                                "porcentaje": str(pct.quantize(Decimal("0.01")))})
    destinatarios = await notificaciones_service.destinatarios_por_rol(db, [Rol.admin_prestador], prestador_id=fondo.prestador_id)
    await notificaciones_service.notificar(db, "caja_chica.fondo_bajo", destinatarios, {"fondo_id": str(fondo.id), "saldo": str(fondo.saldo_actual)},
                                           asunto=f"Fondo de caja chica bajo: ${fondo.saldo_actual:,.2f} ({pct:.0f}% del autorizado)",
                                           cuerpo="Genera la póliza de reposición y repón el fondo.", url="/caja-chica", prestador_id=fondo.prestador_id)


async def listar_gastos(db: AsyncSession, actor: Actor, *, estado: EstadoGastoCajaChica | None = None, fondo_id: UUID | None = None,
                        folio_id: UUID | None = None, desde: date | None = None, hasta: date | None = None) -> list[dict[str, Any]]:
    consulta = select(GastoCajaChica).order_by(GastoCajaChica.timestamp.desc())
    if actor.rol == Rol.tecnico:
        consulta = consulta.where(GastoCajaChica.tecnico_id == actor.id)
    elif not actor.es_superadmin:
        if actor.rol not in CONSULTAN:
            raise prohibido("Tu rol no consulta los gastos de caja chica")
        consulta = consulta.where(GastoCajaChica.prestador_id == actor.prestador_id)
    if estado:
        consulta = consulta.where(GastoCajaChica.estado == estado)
    if fondo_id:
        consulta = consulta.where(GastoCajaChica.fondo_id == fondo_id)
    if folio_id:
        consulta = consulta.where(GastoCajaChica.folio_id == folio_id)
    if desde:
        consulta = consulta.where(GastoCajaChica.timestamp >= datetime.combine(desde, datetime.min.time(), tzinfo=UTC))
    if hasta:
        consulta = consulta.where(GastoCajaChica.timestamp <= datetime.combine(hasta, datetime.max.time(), tzinfo=UTC))
    gastos = list((await db.execute(consulta)).scalars())
    return await serializar(db, gastos)


async def serializar(db: AsyncSession, gastos: list[GastoCajaChica]) -> list[dict[str, Any]]:
    if not gastos:
        return []
    nombres = {u.id: u.nombre for u in (await db.execute(select(Usuario).where(Usuario.id.in_(
        {g.tecnico_id for g in gastos} | {g.aprobado_por for g in gastos if g.aprobado_por})))).scalars()}
    folios = {f.id: f.numero_folio for f in (await db.execute(select(Folio).where(Folio.id.in_({g.folio_id for g in gastos if g.folio_id})))).scalars()} if any(g.folio_id for g in gastos) else {}
    articulos = {a.id: a.codigo for a in (await db.execute(select(Articulo).where(Articulo.id.in_({g.articulo_id for g in gastos if g.articulo_id})))).scalars()} if any(g.articulo_id for g in gastos) else {}
    return [{**auditoria.instantanea(g), "id": g.id, "prestador_id": g.prestador_id, "tenant_id": g.tenant_id, "fondo_id": g.fondo_id, "folio_id": g.folio_id,
             "numero_folio": folios.get(g.folio_id), "tecnico_id": g.tecnico_id, "tecnico_nombre": nombres.get(g.tecnico_id), "articulo_id": g.articulo_id,
             "articulo_codigo": articulos.get(g.articulo_id), "aprobado_por": g.aprobado_por, "aprobado_por_nombre": nombres.get(g.aprobado_por),
             "estado": g.estado.value, "estado_cfdi": g.estado_cfdi.value, "imagen_disponible": bool(g.imagen_key), "created_at": g.created_at,
             "updated_at": g.updated_at, "timestamp": g.timestamp} for g in gastos]


async def imagen_de(db: AsyncSession, actor: Actor, g: GastoCajaChica) -> tuple[bytes, str]:
    if not g.imagen_key:
        raise no_encontrado("Imagen de la factura")
    return obtener_almacenamiento().leer(g.imagen_key), "image/jpeg"


# -------------------------------------------------------- reposición diaria

def excel_poliza(filas: list[list[Any]], fecha: date, prestador: Prestador | None, total: Decimal) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Reposición"
    ws.append([f"Reposición de caja chica · {prestador.razon_social if prestador else ''} · {fecha.isoformat()}"])
    ws.append([])
    ws.append(COLUMNAS_POLIZA)
    for f in filas:
        ws.append(f)
    ws.append([])
    ws.append(["", "", "", "", "Total", "", "", float(total)])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def xml_poliza(filas: list[list[Any]], fecha: date, prestador: Prestador | None, total: Decimal) -> bytes:
    raiz = ET.Element("Poliza", {"tipo": "egresos", "fecha": fecha.isoformat(), "concepto": "Reposición de caja chica",
                                 "rfc": prestador.rfc if prestador else "", "total": f"{total:.2f}"})
    for f in filas:
        ET.SubElement(raiz, "Movimiento", {"fecha": str(f[0]), "proveedor": str(f[1]), "rfc": str(f[2] or ""), "uuid": str(f[3] or ""),
                                           "concepto": str(f[4]), "subtotal": f"{Decimal(str(f[5])):.2f}", "iva": f"{Decimal(str(f[6])):.2f}",
                                           "cargo": f"{Decimal(str(f[7])):.2f}", "centroCostos": str(f[8] or ""), "cuenta": str(f[9] or ""),
                                           "tecnico": str(f[10] or ""), "folio": str(f[11] or "")})
    return ET.tostring(raiz, encoding="utf-8", xml_declaration=True)


async def generar_poliza(db: AsyncSession, actor: ActorFolio, *, prestador_id: UUID, fondo_id: UUID | None = None, fecha: date | None = None,
                         request: Request | None = None) -> PolizaExportacion | None:
    """§6.5: consolida los gastos aprobados del día por fondo y genera el documento de reposición (Excel + XML)."""
    fecha = fecha or date.today()
    consulta = select(GastoCajaChica).where(GastoCajaChica.prestador_id == prestador_id, GastoCajaChica.estado == EstadoGastoCajaChica.aprobado,
                                            GastoCajaChica.poliza_id.is_(None),
                                            GastoCajaChica.aprobado_at >= datetime.combine(fecha, datetime.min.time(), tzinfo=UTC),
                                            GastoCajaChica.aprobado_at <= datetime.combine(fecha, datetime.max.time(), tzinfo=UTC))
    if fondo_id:
        consulta = consulta.where(GastoCajaChica.fondo_id == fondo_id)
    gastos = list((await db.execute(consulta.order_by(GastoCajaChica.aprobado_at))).scalars())
    if not gastos:
        return None
    if fondo_id is None and len({g.fondo_id for g in gastos}) == 1:
        fondo_id = gastos[0].fondo_id
    existente = (await db.execute(select(PolizaExportacion).where(PolizaExportacion.prestador_id == prestador_id, PolizaExportacion.fecha == fecha,
                                                                   PolizaExportacion.fondo_id == fondo_id))).scalar_one_or_none()
    if existente is not None:
        return existente
    nombres = {u.id: u.nombre for u in (await db.execute(select(Usuario).where(Usuario.id.in_({g.tecnico_id for g in gastos})))).scalars()}
    folios = {f.id: f.numero_folio for f in (await db.execute(select(Folio).where(Folio.id.in_({g.folio_id for g in gastos if g.folio_id})))).scalars()} if any(g.folio_id for g in gastos) else {}
    filas = [[g.timestamp.date().isoformat(), g.proveedor, g.rfc_proveedor or "", g.uuid_cfdi or "", g.descripcion, float(g.subtotal), float(g.iva),
              float(g.monto), g.centro_costos, g.cuenta_contable, nombres.get(g.tecnico_id, ""), folios.get(g.folio_id, "")] for g in gastos]
    total = sum((g.monto for g in gastos), CERO)
    prestador = await db.get(Prestador, prestador_id)
    p = PolizaExportacion(prestador_id=prestador_id, fondo_id=fondo_id, fecha=fecha, total=total, gastos=len(gastos), formato=FormatoPoliza.excel,
                          generado_por=getattr(actor, "id", None))
    db.add(p)
    await db.flush()
    almacen = obtener_almacenamiento()
    p.archivo_key = f"caja_chica/polizas/{prestador_id}/{fecha.isoformat()}-{p.id}.xlsx"
    almacen.guardar(p.archivo_key, excel_poliza(filas, fecha, prestador, total), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    p.archivo_xml_key = f"caja_chica/polizas/{prestador_id}/{fecha.isoformat()}-{p.id}.xml"
    almacen.guardar(p.archivo_xml_key, xml_poliza(filas, fecha, prestador, total), "application/xml")
    for g in gastos:
        g.poliza_id = p.id
    await db.flush()
    from services.erp import eventos as erp_eventos

    await erp_eventos.poliza_caja_chica(db, p, gastos)
    await auditoria.registrar(db, "caja_chica.poliza_generada", actor_rol=str(getattr(actor, "rol", "sistema")), actor_id=getattr(actor, "id", None),
                              prestador_id=prestador_id, recurso_tipo="poliza_exportacion", recurso_id=p.id,
                              despues={"fecha": fecha.isoformat(), "total": str(total), "gastos": len(gastos)}, request=request)
    destinatarios = await notificaciones_service.destinatarios_por_rol(db, [Rol.admin_prestador], prestador_id=prestador_id)
    await notificaciones_service.notificar(db, "caja_chica.poliza", destinatarios, {"poliza_id": str(p.id), "total": str(total), "gastos": len(gastos)},
                                           asunto=f"Póliza de reposición de caja chica del {fecha.isoformat()}: ${total:,.2f}",
                                           cuerpo=f"{len(gastos)} gastos consolidados. Descarga el Excel o el XML para tu contador.",
                                           url="/caja-chica?vista=polizas", prestador_id=prestador_id)
    return p


async def generar_polizas_del_dia(db: AsyncSession, actor: ActorFolio, fecha: date | None = None) -> dict[str, int]:
    """Tarea al cierre de jornada: una póliza por prestador con gastos aprobados sin consolidar."""
    fecha = fecha or date.today()
    resumen = {"polizas": 0, "gastos": 0}
    prestadores = (await db.execute(select(Prestador.id).where(Prestador.estado == EstadoRegistro.activo))).scalars().all()
    for pid in prestadores:
        p = await generar_poliza(db, actor, prestador_id=pid, fecha=fecha)
        if p is not None:
            resumen["polizas"] += 1
            resumen["gastos"] += p.gastos
    return resumen


async def listar_polizas(db: AsyncSession, actor: Actor) -> list[PolizaExportacion]:
    if not actor.es_superadmin and actor.rol not in CONSULTAN:
        raise prohibido("Tu rol no consulta las pólizas de caja chica")
    consulta = select(PolizaExportacion).order_by(PolizaExportacion.fecha.desc())
    if not actor.es_superadmin:
        consulta = consulta.where(PolizaExportacion.prestador_id == actor.prestador_id)
    return list((await db.execute(consulta)).scalars())


async def archivo_poliza(db: AsyncSession, actor: Actor, poliza_id: UUID, formato: str) -> tuple[bytes, str, str]:
    p = await db.get(PolizaExportacion, poliza_id)
    if p is None or (not actor.es_superadmin and p.prestador_id != actor.prestador_id):
        raise no_encontrado("Póliza")
    clave = p.archivo_xml_key if formato == "xml" else p.archivo_key
    if not clave:
        raise no_encontrado("Archivo de la póliza")
    mime = "application/xml" if formato == "xml" else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return obtener_almacenamiento().leer(clave), mime, f"reposicion-{p.fecha}.{'xml' if formato == 'xml' else 'xlsx'}"


async def gastos_pendientes_de_folio(db: AsyncSession, folio_id: UUID) -> int:
    """El folio no se bloquea por el gasto: §6.4 dice que al aprobar «el folio se desbloquea para cierre»."""
    return (await db.execute(select(func.count()).select_from(GastoCajaChica).where(
        GastoCajaChica.folio_id == folio_id, GastoCajaChica.estado == EstadoGastoCajaChica.capturado))).scalar() or 0
