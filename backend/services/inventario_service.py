"""Inventario del prestador con los tres orígenes de refacciones (§6.4): almacén (Tipo A), orden de compra (Tipo B) y
caja chica (Tipo C, en `caja_chica_service`). Cada movimiento recalcula `existencias` y el costo promedio ponderado en la
misma transacción; `movimientos_inventario` es append-only. P09."""
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.dependencias import Actor
from core.errors import ErrorAPI, no_encontrado, prohibido
from models.base import Dominio, Rol
from models.chat import ReglaConflicto, SincronizacionConflicto
from models.folios import EstadoFolio, Folio, FolioRefaccion, OrigenRefaccion
from models.inventario import (
    Articulo, EstadoOrdenCompra, Existencia, MovimientoInventario, OrdenCompra, OrdenCompraPartida, TipoMovimientoInventario,
    TipoUbicacionInventario, UbicacionInventario,
)
from models.usuarios import Usuario
from services import alertas_service, auditoria, notificaciones_service
from services.folio_estados import ACTOR_SISTEMA, ActorFolio

ESCRIBEN = {Rol.superadmin, Rol.admin_prestador}
GESTIONAN = ESCRIBEN | {Rol.despachador, Rol.mesa_control}
CONSULTAN = GESTIONAN | {Rol.tecnico, Rol.direccion_prestador, Rol.supervisor_prestador}
CERO = Decimal("0")


def _rol(actor: ActorFolio):
    return "sistema" if actor is ACTOR_SISTEMA else actor.rol


def exigir(actor: ActorFolio, roles: set, accion: str) -> None:
    if actor is ACTOR_SISTEMA or getattr(actor, "es_superadmin", False):
        return
    if actor.rol not in roles:
        raise prohibido(f"{accion}: solo {', '.join(sorted(r.value for r in roles if r != Rol.superadmin))}")


def _prestador_de(actor: ActorFolio, prestador_id: UUID | None = None) -> UUID:
    pid = prestador_id if (prestador_id and getattr(actor, "es_superadmin", False)) else getattr(actor, "prestador_id", None) or prestador_id
    if pid is None:
        raise ErrorAPI(422, "PRESTADOR_REQUERIDO", "Indica el prestador del inventario")
    return pid


# ------------------------------------------------------------- artículos

async def crear_articulo(db: AsyncSession, actor: Actor, datos: dict[str, Any], request: Request | None = None) -> Articulo:
    exigir(actor, ESCRIBEN, "Dar de alta artículos")
    prestador_id = _prestador_de(actor, datos.pop("prestador_id", None))
    codigo = str(datos["codigo"]).strip().upper()
    if (await db.execute(select(Articulo.id).where(Articulo.prestador_id == prestador_id, func.upper(Articulo.codigo) == codigo))).first():
        raise ErrorAPI(409, "ARTICULO_DUPLICADO", f"Ya existe un artículo con el código {codigo}")
    a = Articulo(prestador_id=prestador_id, **{**datos, "codigo": codigo})
    db.add(a)
    await db.flush()
    await auditoria.registrar_actor(db, actor, "inventario.articulo_creado", request, prestador_id=prestador_id, recurso_tipo="articulo", recurso_id=a.id,
                                    despues={"codigo": a.codigo, "descripcion": a.descripcion})
    return a


async def obtener_articulo(db: AsyncSession, actor: Actor, articulo_id: UUID) -> Articulo:
    a = await db.get(Articulo, articulo_id)
    if a is None or (not actor.es_superadmin and a.prestador_id != actor.prestador_id):
        raise no_encontrado("Artículo")
    return a


async def actualizar_articulo(db: AsyncSession, actor: Actor, a: Articulo, cambios: dict[str, Any], request: Request | None = None) -> Articulo:
    exigir(actor, ESCRIBEN, "Editar artículos")
    antes = auditoria.instantanea(a)
    for k, v in cambios.items():
        setattr(a, k, v)
    await db.flush()
    await auditoria.registrar_actor(db, actor, "inventario.articulo_editado", request, prestador_id=a.prestador_id, recurso_tipo="articulo", recurso_id=a.id,
                                    antes=antes, despues=auditoria.instantanea(a))
    return a


async def listar_articulos(db: AsyncSession, actor: Actor, *, q: str | None = None, categoria: str | None = None, activo: bool | None = None) -> list[Articulo]:
    exigir(actor, CONSULTAN, "Consultar el catálogo de artículos")
    consulta = select(Articulo).order_by(Articulo.codigo)
    if not actor.es_superadmin:
        consulta = consulta.where(Articulo.prestador_id == actor.prestador_id)
    if q:
        patron = f"%{q.strip()}%"
        consulta = consulta.where(Articulo.codigo.ilike(patron) | Articulo.descripcion.ilike(patron) | Articulo.numero_parte.ilike(patron))
    if categoria:
        consulta = consulta.where(Articulo.categoria == categoria)
    if activo is not None:
        consulta = consulta.where(Articulo.activo.is_(activo))
    return list((await db.execute(consulta)).scalars())


# ------------------------------------------------------------ ubicaciones

async def crear_ubicacion(db: AsyncSession, actor: Actor, datos: dict[str, Any], request: Request | None = None) -> UbicacionInventario:
    exigir(actor, ESCRIBEN, "Dar de alta almacenes y vehículos")
    prestador_id = _prestador_de(actor, datos.pop("prestador_id", None))
    tecnico_id = datos.get("tecnico_id")
    if datos.get("tipo") == TipoUbicacionInventario.vehiculo and tecnico_id:
        u = await db.get(Usuario, tecnico_id)
        if u is None or u.rol != Rol.tecnico or u.prestador_id != prestador_id:
            raise ErrorAPI(422, "TECNICO_INVALIDO", "El vehículo se asigna a un técnico del prestador")
        if (await db.execute(select(UbicacionInventario.id).where(UbicacionInventario.tecnico_id == tecnico_id,
                                                                  UbicacionInventario.tipo == TipoUbicacionInventario.vehiculo))).first():
            raise ErrorAPI(409, "VEHICULO_DUPLICADO", "El técnico ya tiene un vehículo de inventario")
    ub = UbicacionInventario(prestador_id=prestador_id, **datos)
    db.add(ub)
    await db.flush()
    await auditoria.registrar_actor(db, actor, "inventario.ubicacion_creada", request, prestador_id=prestador_id, recurso_tipo="ubicacion_inventario",
                                    recurso_id=ub.id, despues={"nombre": ub.nombre, "tipo": ub.tipo.value})
    return ub


async def listar_ubicaciones(db: AsyncSession, actor: Actor, *, tipo: TipoUbicacionInventario | None = None) -> list[UbicacionInventario]:
    exigir(actor, CONSULTAN, "Consultar almacenes y vehículos")
    consulta = select(UbicacionInventario).order_by(UbicacionInventario.tipo, UbicacionInventario.nombre)
    if not actor.es_superadmin:
        consulta = consulta.where(UbicacionInventario.prestador_id == actor.prestador_id)
    if tipo:
        consulta = consulta.where(UbicacionInventario.tipo == tipo)
    if actor.rol == Rol.tecnico:
        consulta = consulta.where(UbicacionInventario.tecnico_id == actor.id)  # §6.4: el técnico solo ve su vehículo
    return list((await db.execute(consulta)).scalars())


async def vehiculo_de(db: AsyncSession, tecnico_id: UUID | None) -> UbicacionInventario | None:
    if tecnico_id is None:
        return None
    return (await db.execute(select(UbicacionInventario).where(UbicacionInventario.tecnico_id == tecnico_id,
                                                               UbicacionInventario.tipo == TipoUbicacionInventario.vehiculo))).scalars().first()


async def almacen_principal(db: AsyncSession, prestador_id: UUID) -> UbicacionInventario | None:
    return (await db.execute(select(UbicacionInventario).where(UbicacionInventario.prestador_id == prestador_id,
                                                               UbicacionInventario.tipo == TipoUbicacionInventario.almacen,
                                                               UbicacionInventario.activo.is_(True)).order_by(UbicacionInventario.created_at))).scalars().first()


async def existencia(db: AsyncSession, ubicacion: UbicacionInventario, articulo_id: UUID, crear: bool = True) -> Existencia | None:
    e = (await db.execute(select(Existencia).where(Existencia.ubicacion_id == ubicacion.id, Existencia.articulo_id == articulo_id))).scalar_one_or_none()
    if e is None and crear:
        e = Existencia(prestador_id=ubicacion.prestador_id, ubicacion_id=ubicacion.id, articulo_id=articulo_id, cantidad=CERO, costo_promedio=CERO)
        db.add(e)
        await db.flush()
    return e


# ------------------------------------------------------------ movimientos

def _promedio_ponderado(cantidad_actual: Decimal, costo_actual: Decimal, cantidad_entra: Decimal, costo_entra: Decimal) -> Decimal:
    """Costo promedio ponderado (regla elegida en P09): la salida no lo cambia; la entrada lo promedia por cantidad."""
    total = cantidad_actual + cantidad_entra
    if total <= CERO:
        return costo_entra if costo_entra > CERO else costo_actual
    valor = (max(cantidad_actual, CERO) * costo_actual) + (cantidad_entra * costo_entra)
    return (valor / total).quantize(Decimal("0.01"))


async def _mover(db: AsyncSession, actor: ActorFolio, *, prestador_id: UUID, articulo: Articulo, tipo: TipoMovimientoInventario, cantidad: Decimal,
                 origen_ub: UbicacionInventario | None, destino_ub: UbicacionInventario | None, costo_unitario: Decimal | None = None,
                 origen: OrigenRefaccion = OrigenRefaccion.almacen, folio_id: UUID | None = None, oc_id: UUID | None = None,
                 gasto_id: UUID | None = None, refaccion_id: UUID | None = None, tenant_id: UUID | None = None, referencia: str | None = None,
                 razon: str = "", permitir_negativo: bool = False, momento: datetime | None = None) -> MovimientoInventario:
    """Aplica el movimiento sobre `existencias` y lo registra. Devuelve la fila append-only."""
    if cantidad <= CERO and tipo != TipoMovimientoInventario.ajuste:
        raise ErrorAPI(422, "CANTIDAD_INVALIDA", "La cantidad debe ser mayor que cero")
    costo = costo_unitario if costo_unitario is not None else articulo.costo_unitario_vigente
    negativo = None
    if origen_ub is not None:
        e = await existencia(db, origen_ub, articulo.id)
        if costo_unitario is None and e.costo_promedio > CERO:
            costo = e.costo_promedio
        nueva = e.cantidad - cantidad
        if nueva < CERO and not permitir_negativo:
            raise ErrorAPI(409, "STOCK_INSUFICIENTE", f"{origen_ub.nombre} tiene {e.cantidad} de {articulo.codigo} y se piden {cantidad}",
                           [{"ubicacion_id": str(origen_ub.id), "disponible": str(e.cantidad), "solicitado": str(cantidad)}])
        e.cantidad = nueva
        if nueva < CERO:
            negativo = e
    if destino_ub is not None:
        d = await existencia(db, destino_ub, articulo.id)
        d.costo_promedio = _promedio_ponderado(d.cantidad, d.costo_promedio, cantidad, costo)
        d.cantidad = d.cantidad + cantidad
    if tipo == TipoMovimientoInventario.ajuste and origen_ub is None and destino_ub is not None:
        pass  # el ajuste positivo ya se aplicó como entrada al destino
    m = MovimientoInventario(prestador_id=prestador_id, tenant_id=tenant_id, articulo_id=articulo.id,
                             ubicacion_origen_id=origen_ub.id if origen_ub else None, ubicacion_destino_id=destino_ub.id if destino_ub else None,
                             tipo=tipo, cantidad=cantidad, costo_unitario=costo, origen=origen, folio_id=folio_id, oc_id=oc_id,
                             gasto_caja_chica_id=gasto_id, refaccion_id=refaccion_id, referencia_externa=referencia, razon=razon,
                             registrado_por=getattr(actor, "id", None), timestamp_dispositivo=momento, timestamp=datetime.now(UTC))
    db.add(m)
    await db.flush()
    if negativo is not None:
        await _alerta_negativo(db, articulo, origen_ub, negativo, folio_id)
    await _revisar_minimo(db, articulo, origen_ub)
    return m


async def _alerta_negativo(db: AsyncSession, articulo: Articulo, ubicacion: UbicacionInventario, e: Existencia, folio_id: UUID | None) -> None:
    await alertas_service.disparar(db, "STOCK_NEGATIVO", tenant_id=None, prestador_id=articulo.prestador_id, entidad_tipo="existencia", entidad_id=e.id,
                                   datos={"articulo": articulo.codigo, "ubicacion": ubicacion.nombre, "cantidad": str(e.cantidad), "folio_id": str(folio_id) if folio_id else None})
    destinatarios = await notificaciones_service.destinatarios_por_rol(db, [Rol.despachador, Rol.admin_prestador], prestador_id=articulo.prestador_id)
    await notificaciones_service.notificar(db, "inventario.stock_negativo", destinatarios,
                                           {"articulo_id": str(articulo.id), "ubicacion_id": str(ubicacion.id), "cantidad": str(e.cantidad)},
                                           asunto=f"Existencia negativa: {articulo.codigo} en {ubicacion.nombre} ({e.cantidad})",
                                           cuerpo="Dos consumos offline se aplicaron sobre la misma existencia (merge con alerta, §6.2). Ajusta el inventario.",
                                           url="/inventario?vista=existencias", prestador_id=articulo.prestador_id)


async def _revisar_minimo(db: AsyncSession, articulo: Articulo, ubicacion: UbicacionInventario | None) -> None:
    if ubicacion is None:
        return
    e = await existencia(db, ubicacion, articulo.id, crear=False)
    if e is None:
        return
    minimo = e.stock_minimo if e.stock_minimo is not None else articulo.stock_minimo_default
    if minimo > CERO and CERO <= e.cantidad <= minimo:
        await alertas_service.disparar(db, "STOCK_MINIMO", tenant_id=None, prestador_id=articulo.prestador_id, entidad_tipo="existencia", entidad_id=e.id,
                                       datos={"articulo": articulo.codigo, "ubicacion": ubicacion.nombre, "cantidad": str(e.cantidad), "minimo": str(minimo)})


async def entrada(db: AsyncSession, actor: Actor, *, articulo_id: UUID, ubicacion_id: UUID, cantidad: Decimal, costo_unitario: Decimal | None,
                  referencia: str | None = None, razon: str = "", request: Request | None = None) -> MovimientoInventario:
    exigir(actor, GESTIONAN, "Registrar entradas de inventario")
    a = await obtener_articulo(db, actor, articulo_id)
    ub = await _ubicacion(db, actor, ubicacion_id)
    m = await _mover(db, actor, prestador_id=a.prestador_id, articulo=a, tipo=TipoMovimientoInventario.entrada, cantidad=cantidad, origen_ub=None,
                     destino_ub=ub, costo_unitario=costo_unitario, referencia=referencia, razon=razon)
    if costo_unitario is not None and costo_unitario > CERO:
        a.costo_unitario_vigente = costo_unitario
    await auditoria.registrar_actor(db, actor, "inventario.entrada", request, prestador_id=a.prestador_id, recurso_tipo="movimiento_inventario", recurso_id=m.id,
                                    despues={"articulo": a.codigo, "cantidad": str(cantidad), "ubicacion": ub.nombre})
    return m


async def traspaso(db: AsyncSession, actor: Actor, *, articulo_id: UUID, origen_id: UUID, destino_id: UUID, cantidad: Decimal, razon: str = "",
                   request: Request | None = None) -> MovimientoInventario:
    """Carga de la unidad: almacén → vehículo (o entre almacenes)."""
    exigir(actor, GESTIONAN, "Traspasar inventario")
    a = await obtener_articulo(db, actor, articulo_id)
    o, d = await _ubicacion(db, actor, origen_id), await _ubicacion(db, actor, destino_id)
    if o.id == d.id:
        raise ErrorAPI(422, "UBICACIONES_IGUALES", "El origen y el destino deben ser distintos")
    m = await _mover(db, actor, prestador_id=a.prestador_id, articulo=a, tipo=TipoMovimientoInventario.traspaso, cantidad=cantidad, origen_ub=o,
                     destino_ub=d, razon=razon)
    await auditoria.registrar_actor(db, actor, "inventario.traspaso", request, prestador_id=a.prestador_id, recurso_tipo="movimiento_inventario", recurso_id=m.id,
                                    despues={"articulo": a.codigo, "cantidad": str(cantidad), "origen": o.nombre, "destino": d.nombre})
    return m


async def ajuste(db: AsyncSession, actor: Actor, *, articulo_id: UUID, ubicacion_id: UUID, cantidad: Decimal, razon: str,
                 request: Request | None = None) -> MovimientoInventario:
    """`cantidad` es el delta: positivo suma, negativo resta. Exige razón."""
    exigir(actor, ESCRIBEN, "Ajustar inventario")
    if not (razon or "").strip() or len(razon.strip()) < 5:
        raise ErrorAPI(422, "RAZON_REQUERIDA", "El ajuste de inventario exige razón (mínimo 5 caracteres)")
    a = await obtener_articulo(db, actor, articulo_id)
    ub = await _ubicacion(db, actor, ubicacion_id)
    positivo = cantidad > CERO
    m = await _mover(db, actor, prestador_id=a.prestador_id, articulo=a, tipo=TipoMovimientoInventario.ajuste, cantidad=abs(cantidad),
                     origen_ub=None if positivo else ub, destino_ub=ub if positivo else None, razon=razon.strip(), permitir_negativo=True)
    await auditoria.registrar_actor(db, actor, "inventario.ajuste", request, prestador_id=a.prestador_id, recurso_tipo="movimiento_inventario", recurso_id=m.id,
                                    despues={"articulo": a.codigo, "delta": str(cantidad), "ubicacion": ub.nombre, "razon": razon})
    return m


async def _ubicacion(db: AsyncSession, actor: Actor, ubicacion_id: UUID) -> UbicacionInventario:
    ub = await db.get(UbicacionInventario, ubicacion_id)
    if ub is None or (not getattr(actor, "es_superadmin", False) and getattr(actor, "prestador_id", None) not in (None, ub.prestador_id)):
        raise no_encontrado("Ubicación de inventario")
    return ub


# ------------------------------------------------------- consumo en folio

async def consumir_en_folio(db: AsyncSession, actor: ActorFolio, folio: Folio, refaccion: FolioRefaccion, *, ubicacion_id: UUID | None = None,
                            permitir_negativo: bool = False, momento: datetime | None = None) -> MovimientoInventario | None:
    """§6.4: descuenta del vehículo del técnico (o del almacén indicado). Sin `articulo_id` solo se guarda la descripción libre.
    Técnicos compartidos (§6.10.8): el inventario es del prestador y el costo se imputa al tenant del folio."""
    if refaccion.articulo_id is None:
        return None
    a = await db.get(Articulo, refaccion.articulo_id)
    if a is None or a.prestador_id != folio.prestador_id:
        raise ErrorAPI(422, "ARTICULO_INVALIDO", "El artículo no pertenece al inventario del prestador del folio")
    ub = None
    if ubicacion_id:
        ub = await db.get(UbicacionInventario, ubicacion_id)
        if ub is None or ub.prestador_id != folio.prestador_id:
            raise no_encontrado("Ubicación de inventario")
    else:
        ub = await vehiculo_de(db, folio.tecnico_id) or await almacen_principal(db, folio.prestador_id)
    if ub is None:
        raise ErrorAPI(422, "SIN_UBICACION", "El prestador no tiene almacén ni vehículo para descontar la refacción")
    if refaccion.origen == OrigenRefaccion.caja_chica:
        return None  # lo aplica `caja_chica_service` al aprobar (entrada + salida inmediata)
    e = await existencia(db, ub, a.id, crear=False)
    costo = refaccion.costo_unitario if refaccion.costo_unitario > CERO else (e.costo_promedio if e and e.costo_promedio > CERO else a.costo_unitario_vigente)
    m = await _mover(db, actor, prestador_id=folio.prestador_id, articulo=a, tipo=TipoMovimientoInventario.consumo_folio, cantidad=refaccion.cantidad,
                     origen_ub=ub, destino_ub=None, costo_unitario=costo, origen=refaccion.origen, folio_id=folio.id, refaccion_id=refaccion.id,
                     tenant_id=folio.tenant_id, razon=f"Consumo en {folio.numero_folio}", permitir_negativo=permitir_negativo, momento=momento)
    refaccion.ubicacion_id = ub.id
    if refaccion.costo_unitario <= CERO:
        refaccion.costo_unitario = costo
    await db.flush()
    return m


async def aplicar_consumo_offline(db: AsyncSession, actor: Actor, refaccion: FolioRefaccion, dispositivo_id: str | None, momento: datetime | None) -> None:
    """Gancho §6.2 «merge con alerta»: ambos consumos se aplican; si la existencia queda negativa se registra el conflicto."""
    if refaccion.articulo_id is None:
        return
    folio = await db.get(Folio, refaccion.folio_id)
    if folio is None:
        return
    antes = None
    ub = await vehiculo_de(db, folio.tecnico_id) or await almacen_principal(db, folio.prestador_id)
    if ub is not None:
        e = await existencia(db, ub, refaccion.articulo_id, crear=False)
        antes = e.cantidad if e else CERO
    m = await consumir_en_folio(db, actor, folio, refaccion, permitir_negativo=True, momento=momento)
    if m is None or ub is None:
        return
    e = await existencia(db, ub, refaccion.articulo_id, crear=False)
    if e is not None and e.cantidad < CERO:
        db.add(SincronizacionConflicto(usuario_id=actor.id, tenant_id=folio.tenant_id, prestador_id=folio.prestador_id, dispositivo_id=dispositivo_id,
                                       entidad="existencias", entidad_id=e.id, regla_aplicada=ReglaConflicto.merge_alerta,
                                       datos_cliente_json={"refaccion_id": str(refaccion.id), "cantidad": str(refaccion.cantidad), "folio": folio.numero_folio},
                                       datos_servidor_json={"cantidad_antes": str(antes), "cantidad_despues": str(e.cantidad), "ubicacion_id": str(ub.id)}))
        await db.flush()


# ------------------------------------------------------- órdenes de compra

async def siguiente_numero_oc(db: AsyncSession, prestador_id: UUID) -> str:
    n = (await db.execute(select(func.count()).select_from(OrdenCompra).where(OrdenCompra.prestador_id == prestador_id))).scalar() or 0
    return f"OC-{n + 1:06d}"


async def crear_oc(db: AsyncSession, actor: Actor, *, folio_id: UUID | None, proveedor: str, partidas: list[dict[str, Any]], notas: str = "",
                   ubicacion_destino_id: UUID | None = None, request: Request | None = None) -> OrdenCompra:
    """§6.4 Tipo B: el Despachador o el Admin prestador crean la OC desde el folio cuando el técnico reporta `pendiente_refaccion`."""
    exigir(actor, GESTIONAN, "Crear órdenes de compra")
    if not partidas:
        raise ErrorAPI(422, "PARTIDAS_REQUERIDAS", "La orden de compra necesita al menos una partida")
    folio = await db.get(Folio, folio_id) if folio_id else None
    prestador_id = folio.prestador_id if folio else _prestador_de(actor)
    if folio is not None and not actor.es_superadmin and folio.prestador_id != actor.prestador_id:
        raise no_encontrado("Folio")
    oc = OrdenCompra(prestador_id=prestador_id, tenant_id=folio.tenant_id if folio else None, numero=await siguiente_numero_oc(db, prestador_id),
                     folio_id=folio.id if folio else None, proveedor=proveedor.strip(), notas=notas, created_by=actor.id,
                     ubicacion_destino_id=ubicacion_destino_id or (await almacen_principal(db, prestador_id)).id if await almacen_principal(db, prestador_id) else None,
                     estado_desde=datetime.now(UTC))
    db.add(oc)
    await db.flush()
    total = CERO
    for p in partidas:
        a = await obtener_articulo(db, actor, UUID(str(p["articulo_id"])))
        cantidad, costo = Decimal(str(p.get("cantidad", 1))), Decimal(str(p.get("costo_unitario", a.costo_unitario_vigente)))
        db.add(OrdenCompraPartida(prestador_id=prestador_id, oc_id=oc.id, articulo_id=a.id, cantidad=cantidad, costo_unitario=costo))
        total += cantidad * costo
    oc.total = total.quantize(Decimal("0.01"))
    await db.flush()
    await auditoria.registrar_actor(db, actor, "inventario.oc_creada", request, prestador_id=prestador_id, tenant_id=oc.tenant_id, recurso_tipo="orden_compra",
                                    recurso_id=oc.id, despues={"numero": oc.numero, "total": str(oc.total), "folio_id": str(folio_id) if folio_id else None})
    destinatarios = await notificaciones_service.destinatarios_por_rol(db, [Rol.admin_prestador], prestador_id=prestador_id)
    await notificaciones_service.notificar(db, "oc.creada", destinatarios, {"oc_id": str(oc.id), "numero": oc.numero, "total": str(oc.total)},
                                           asunto=f"Orden de compra {oc.numero} por ${oc.total:,.2f} pendiente de aprobación", cuerpo=f"Proveedor {oc.proveedor}",
                                           url=f"/inventario?vista=ordenes&oc={oc.id}", prestador_id=prestador_id, tenant_id=oc.tenant_id)
    return oc


async def obtener_oc(db: AsyncSession, actor: Actor, oc_id: UUID) -> OrdenCompra:
    oc = await db.get(OrdenCompra, oc_id)
    if oc is None:
        raise no_encontrado("Orden de compra")
    if actor.es_superadmin:
        return oc
    if actor.dominio == Dominio.prestador and oc.prestador_id == actor.prestador_id:
        return oc
    if actor.dominio == Dominio.tenant and oc.tenant_id == actor.tenant_id:
        return oc
    raise no_encontrado("Orden de compra")


async def partidas_de(db: AsyncSession, oc_id: UUID) -> list[OrdenCompraPartida]:
    return list((await db.execute(select(OrdenCompraPartida).where(OrdenCompraPartida.oc_id == oc_id).order_by(OrdenCompraPartida.created_at))).scalars())


async def aprobar_oc(db: AsyncSession, actor: Actor, oc: OrdenCompra, request: Request | None = None) -> OrdenCompra:
    """Al aprobarse se genera el evento ERP `generar_oc` (§6.6); el adaptador lo procesa en Fase 2."""
    exigir(actor, ESCRIBEN, "Aprobar órdenes de compra")
    if oc.estado != EstadoOrdenCompra.borrador:
        raise ErrorAPI(409, "TRANSICION_NO_PERMITIDA", f"Una orden {oc.estado.value} no se aprueba")
    oc.estado, oc.estado_desde, oc.aprobada_por, oc.aprobada_at = EstadoOrdenCompra.aprobada, datetime.now(UTC), actor.id, datetime.now(UTC)
    await db.flush()
    from services.erp import eventos as erp_eventos

    await erp_eventos.generar_oc(db, oc, await partidas_de(db, oc.id))
    await auditoria.registrar_actor(db, actor, "inventario.oc_aprobada", request, prestador_id=oc.prestador_id, tenant_id=oc.tenant_id,
                                    recurso_tipo="orden_compra", recurso_id=oc.id, despues={"numero": oc.numero, "total": str(oc.total)})
    destinatarios = await notificaciones_service.destinatarios_por_rol(db, [Rol.despachador, Rol.mesa_control], prestador_id=oc.prestador_id)
    await notificaciones_service.notificar(db, "oc.aprobada", destinatarios, {"oc_id": str(oc.id), "numero": oc.numero},
                                           asunto=f"Orden de compra {oc.numero} aprobada", cuerpo=f"Proveedor {oc.proveedor} · ${oc.total:,.2f}",
                                           url=f"/inventario?vista=ordenes&oc={oc.id}", prestador_id=oc.prestador_id, tenant_id=oc.tenant_id)
    return oc


async def recibir_oc(db: AsyncSession, actor: Actor, oc: OrdenCompra, recibidas: dict[str, Decimal] | None = None,
                     request: Request | None = None) -> OrdenCompra:
    """La refacción entra al almacén y queda disponible para asignarse al folio; el folio vuelve a `en_ejecucion`."""
    exigir(actor, GESTIONAN, "Recibir órdenes de compra")
    if oc.estado not in (EstadoOrdenCompra.aprobada, EstadoOrdenCompra.enviada_erp):
        raise ErrorAPI(409, "TRANSICION_NO_PERMITIDA", f"Una orden {oc.estado.value} no se recibe")
    destino = await db.get(UbicacionInventario, oc.ubicacion_destino_id) if oc.ubicacion_destino_id else await almacen_principal(db, oc.prestador_id)
    if destino is None:
        raise ErrorAPI(422, "SIN_ALMACEN", "El prestador no tiene almacén para recibir la orden")
    for p in await partidas_de(db, oc.id):
        cantidad = Decimal(str((recibidas or {}).get(str(p.articulo_id), p.cantidad - p.recibido)))
        if cantidad <= CERO:
            continue
        a = await db.get(Articulo, p.articulo_id)
        await _mover(db, actor, prestador_id=oc.prestador_id, articulo=a, tipo=TipoMovimientoInventario.entrada, cantidad=cantidad, origen_ub=None,
                     destino_ub=destino, costo_unitario=p.costo_unitario, origen=OrigenRefaccion.oc, folio_id=oc.folio_id, oc_id=oc.id,
                     tenant_id=oc.tenant_id, referencia=oc.numero, razon=f"Recepción de {oc.numero}")
        p.recibido = p.recibido + cantidad
        if p.costo_unitario > CERO:
            a.costo_unitario_vigente = p.costo_unitario
    oc.estado, oc.estado_desde, oc.recibida_at = EstadoOrdenCompra.recibida, datetime.now(UTC), datetime.now(UTC)
    await db.flush()
    await auditoria.registrar_actor(db, actor, "inventario.oc_recibida", request, prestador_id=oc.prestador_id, tenant_id=oc.tenant_id,
                                    recurso_tipo="orden_compra", recurso_id=oc.id, despues={"numero": oc.numero, "destino": destino.nombre})
    folio = await db.get(Folio, oc.folio_id) if oc.folio_id else None
    if folio is not None and folio.estado == EstadoFolio.pendiente_refaccion:
        destinatarios = await notificaciones_service.destinatarios_por_rol(db, [Rol.despachador, Rol.admin_prestador], prestador_id=oc.prestador_id)
        await notificaciones_service.notificar(db, "oc.recibida", destinatarios, {"oc_id": str(oc.id), "numero": oc.numero, "folio_id": str(folio.id)},
                                               asunto=f"Refacción de {oc.numero} recibida: {folio.numero_folio} puede reanudarse",
                                               cuerpo="Reanuda el folio para que el técnico continúe.", url=f"/folios/{folio.id}",
                                               prestador_id=oc.prestador_id, tenant_id=oc.tenant_id)
    return oc


async def cancelar_oc(db: AsyncSession, actor: Actor, oc: OrdenCompra, razon: str, request: Request | None = None) -> OrdenCompra:
    exigir(actor, GESTIONAN, "Cancelar órdenes de compra")
    if oc.estado in (EstadoOrdenCompra.recibida, EstadoOrdenCompra.cancelada):
        raise ErrorAPI(409, "TRANSICION_NO_PERMITIDA", f"Una orden {oc.estado.value} ya no se cancela")
    if not (razon or "").strip():
        raise ErrorAPI(422, "RAZON_REQUERIDA", "Cancelar una orden de compra exige razón")
    oc.estado, oc.estado_desde, oc.razon_cancelacion = EstadoOrdenCompra.cancelada, datetime.now(UTC), razon.strip()
    await db.flush()
    await auditoria.registrar_actor(db, actor, "inventario.oc_cancelada", request, prestador_id=oc.prestador_id, tenant_id=oc.tenant_id,
                                    recurso_tipo="orden_compra", recurso_id=oc.id, despues={"numero": oc.numero, "razon": razon})
    return oc


async def listar_ocs(db: AsyncSession, actor: Actor, *, estado: EstadoOrdenCompra | None = None, folio_id: UUID | None = None) -> list[OrdenCompra]:
    exigir(actor, CONSULTAN | {Rol.admin_empresa, Rol.admin_un}, "Consultar órdenes de compra")
    consulta = select(OrdenCompra).order_by(OrdenCompra.created_at.desc())
    if actor.es_superadmin:
        pass
    elif actor.dominio == Dominio.prestador:
        consulta = consulta.where(OrdenCompra.prestador_id == actor.prestador_id)
    else:
        consulta = consulta.where(OrdenCompra.tenant_id == actor.tenant_id)
    if estado:
        consulta = consulta.where(OrdenCompra.estado == estado)
    if folio_id:
        consulta = consulta.where(OrdenCompra.folio_id == folio_id)
    return list((await db.execute(consulta)).scalars())


# -------------------------------------------------------------- lecturas

async def listar_existencias(db: AsyncSession, actor: Actor, *, ubicacion_id: UUID | None = None, articulo_id: UUID | None = None,
                             solo_bajo_minimo: bool = False) -> list[dict[str, Any]]:
    exigir(actor, CONSULTAN, "Consultar existencias")
    consulta = select(Existencia, Articulo, UbicacionInventario).join(Articulo, Articulo.id == Existencia.articulo_id).join(
        UbicacionInventario, UbicacionInventario.id == Existencia.ubicacion_id).order_by(UbicacionInventario.nombre, Articulo.codigo)
    if not actor.es_superadmin:
        consulta = consulta.where(Existencia.prestador_id == actor.prestador_id)
    if actor.rol == Rol.tecnico:
        consulta = consulta.where(UbicacionInventario.tecnico_id == actor.id)
    if ubicacion_id:
        consulta = consulta.where(Existencia.ubicacion_id == ubicacion_id)
    if articulo_id:
        consulta = consulta.where(Existencia.articulo_id == articulo_id)
    salida = []
    for e, a, u in (await db.execute(consulta)).all():
        minimo = e.stock_minimo if e.stock_minimo is not None else a.stock_minimo_default
        bajo = minimo > CERO and e.cantidad <= minimo
        if solo_bajo_minimo and not bajo:
            continue
        salida.append({"id": e.id, "ubicacion_id": u.id, "ubicacion": u.nombre, "ubicacion_tipo": u.tipo.value, "articulo_id": a.id, "codigo": a.codigo,
                       "descripcion": a.descripcion, "unidad": a.unidad, "categoria": a.categoria, "cantidad": e.cantidad, "stock_minimo": minimo,
                       "costo_promedio": e.costo_promedio, "bajo_minimo": bajo, "updated_at": e.updated_at})
    return salida


async def listar_movimientos(db: AsyncSession, actor: Actor, *, articulo_id: UUID | None = None, ubicacion_id: UUID | None = None,
                             folio_id: UUID | None = None, limite: int = 200) -> list[dict[str, Any]]:
    exigir(actor, CONSULTAN, "Consultar movimientos de inventario")
    consulta = select(MovimientoInventario).order_by(MovimientoInventario.timestamp.desc()).limit(min(limite, 500))
    if not actor.es_superadmin:
        consulta = consulta.where(MovimientoInventario.prestador_id == actor.prestador_id)
    if articulo_id:
        consulta = consulta.where(MovimientoInventario.articulo_id == articulo_id)
    if ubicacion_id:
        consulta = consulta.where((MovimientoInventario.ubicacion_origen_id == ubicacion_id) | (MovimientoInventario.ubicacion_destino_id == ubicacion_id))
    if folio_id:
        consulta = consulta.where(MovimientoInventario.folio_id == folio_id)
    filas = list((await db.execute(consulta)).scalars())
    if not filas:
        return []
    articulos = {a.id: a for a in (await db.execute(select(Articulo).where(Articulo.id.in_({m.articulo_id for m in filas})))).scalars()}
    ids_ub = {m.ubicacion_origen_id for m in filas} | {m.ubicacion_destino_id for m in filas}
    ubicaciones = {u.id: u.nombre for u in (await db.execute(select(UbicacionInventario).where(UbicacionInventario.id.in_({i for i in ids_ub if i})))).scalars()}
    folios = {f.id: f.numero_folio for f in (await db.execute(select(Folio).where(Folio.id.in_({m.folio_id for m in filas if m.folio_id})))).scalars()} if any(m.folio_id for m in filas) else {}
    return [{"id": m.id, "timestamp": m.timestamp, "tipo": m.tipo.value, "origen": m.origen.value, "cantidad": m.cantidad, "costo_unitario": m.costo_unitario,
             "articulo_id": m.articulo_id, "codigo": articulos[m.articulo_id].codigo if m.articulo_id in articulos else None,
             "descripcion": articulos[m.articulo_id].descripcion if m.articulo_id in articulos else None,
             "ubicacion_origen": ubicaciones.get(m.ubicacion_origen_id), "ubicacion_destino": ubicaciones.get(m.ubicacion_destino_id),
             "folio_id": m.folio_id, "numero_folio": folios.get(m.folio_id), "razon": m.razon, "referencia_externa": m.referencia_externa,
             "registrado_por": m.registrado_por} for m in filas]


async def tiene_materiales(db: AsyncSession, tecnico_id: UUID, folio: Folio) -> tuple[bool | None, list[str]]:
    """P06: `refaccion_ok` compara los materiales previstos del plan y las refacciones del folio contra el vehículo del técnico destino."""
    from models.preventivos import PlanMaterial

    requeridos: dict[UUID, Decimal] = {}
    for r in (await db.execute(select(FolioRefaccion).where(FolioRefaccion.folio_id == folio.id, FolioRefaccion.articulo_id.is_not(None)))).scalars():
        requeridos[r.articulo_id] = requeridos.get(r.articulo_id, CERO) + r.cantidad
    if folio.plan_id:
        for pm in (await db.execute(select(PlanMaterial).where(PlanMaterial.plan_id == folio.plan_id, PlanMaterial.articulo_id.is_not(None)))).scalars():
            requeridos[pm.articulo_id] = max(requeridos.get(pm.articulo_id, CERO), pm.cantidad_estandar)
    if not requeridos:
        return None, []
    ub = await vehiculo_de(db, tecnico_id)
    if ub is None:
        return False, ["El técnico destino no tiene vehículo de inventario registrado"]
    faltantes = []
    for articulo_id, cantidad in requeridos.items():
        e = await existencia(db, ub, articulo_id, crear=False)
        if e is None or e.cantidad < cantidad:
            a = await db.get(Articulo, articulo_id)
            faltantes.append(f"{a.codigo if a else articulo_id}: requiere {cantidad}, tiene {e.cantidad if e else 0}")
    return (not faltantes), faltantes
