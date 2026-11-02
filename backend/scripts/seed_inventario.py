"""Datos demo de P09: 25 artículos en 4 categorías, 1 almacén y un vehículo por técnico con existencias (2 bajo mínimo),
3 órdenes de compra (borrador, aprobada y recibida), fondos de caja chica de 2 técnicos con 5 gastos y una póliza de ayer,
tarifas de mano de obra, costos validados en los folios cerrados, presupuestos trimestrales (uno al 85% y otro excedido),
configuración ERP con eventos generados, y datos de activos con 12 meses de snapshots y una alerta de reemplazo. Idempotente."""
import asyncio
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from core.rls import CONTEXTO_SISTEMA
from models.activos import ActivoDepreciacion, ActivoTCOSnapshot, MetodoDepreciacion
from models.catalogos import Equipo, Tecnico, TipoEquipo
from models.costos import Presupuesto, TarifaManoObra, TipoActividadPresupuesto
from models.folios import EstadoFolio, Folio, FolioRefaccion, OrigenRefaccion, TipoFolio
from models.inventario import Articulo, EstadoGastoCajaChica, TipoUbicacionInventario, UbicacionInventario
from models.organizaciones import Prestador, Tenant
from models.unidades import GrupoUN, UnidadNegocio
from models.usuarios import Usuario
from scripts.seed_folios import actor_de
from services import activos_service, caja_chica_service, costos_service, inventario_service, presupuestos_service
from services.erp import eventos as erp_eventos

CATEGORIAS = {
    "Refrigeración": [("REF-001", "Empaque magnético de puerta 1.80 m", "pieza", "1250.00", 4), ("REF-002", "Compresor 1/3 HP R-134a", "pieza", "6800.00", 1),
                      ("REF-003", "Termostato digital -20/+10 °C", "pieza", "890.00", 2), ("REF-004", "Ventilador evaporador 10 W", "pieza", "640.00", 3),
                      ("REF-005", "Gas refrigerante R-134a 1 kg", "kilogramo", "480.00", 6), ("REF-006", "Filtro deshidratador 1/4", "pieza", "210.00", 5),
                      ("REF-007", "Resistencia de deshielo 220 V", "pieza", "720.00", 2)],
    "Climatización": [("CLI-001", "Filtro de aire minisplit 12000 BTU", "pieza", "320.00", 8), ("CLI-002", "Capacitor 35+5 µF", "pieza", "260.00", 6),
                      ("CLI-003", "Bomba de condensados 220 V", "pieza", "1480.00", 2), ("CLI-004", "Tubería de cobre 1/4 (rollo 15 m)", "rollo", "2100.00", 1),
                      ("CLI-005", "Control remoto universal", "pieza", "380.00", 3), ("CLI-006", "Gas refrigerante R-410A 1 kg", "kilogramo", "620.00", 4),
                      ("CLI-007", "Aislante térmico 1/2 (tramo 2 m)", "tramo", "95.00", 10)],
    "Iluminación": [("ILU-001", "Lámpara LED 50 W luz fría", "pieza", "420.00", 12), ("ILU-002", "Balastro electrónico 2x32 W", "pieza", "310.00", 5),
                    ("ILU-003", "Tubo LED T8 18 W", "pieza", "150.00", 20), ("ILU-004", "Fotocelda 220 V", "pieza", "240.00", 4),
                    ("ILU-005", "Difusor acrílico 60x60", "pieza", "180.00", 6), ("ILU-006", "Luminaria de emergencia 2x5 W", "pieza", "680.00", 3)],
    "Consumibles": [("CON-001", "Cinta de aislar 3M (rollo)", "rollo", "48.00", 24), ("CON-002", "Silicón estructural transparente", "cartucho", "120.00", 10),
                    ("CON-003", "Juego de fusibles 10 A (10 pz)", "paquete", "85.00", 8), ("CON-004", "Limpiador de serpentines 1 L", "litro", "260.00", 6),
                    ("CON-005", "Guantes de nitrilo (par)", "par", "35.00", 30)],
}
# Artículos que quedan por debajo del mínimo en el almacén (alerta STOCK_MINIMO).
BAJO_MINIMO = {"REF-002": (Decimal("1"), Decimal("2")), "CLI-004": (Decimal("0"), Decimal("1"))}


async def sembrar_inventario(db) -> bool:
    prestador = (await db.execute(select(Prestador).where(Prestador.rfc == "PDE200101AB1"))).scalar_one_or_none()
    tenant = (await db.execute(select(Tenant).where(Tenant.rfc == "CDE200101XY2"))).scalar_one_or_none()
    if prestador is None or tenant is None:
        return False
    if (await db.execute(select(Articulo.id).where(Articulo.prestador_id == prestador.id))).first():
        return False
    usuarios = {u.email: u for u in (await db.execute(select(Usuario))).scalars()}
    admin_prestador, despachador, mesa = usuarios["admin.prestador@acma.dev"], usuarios["despachador@acma.dev"], usuarios["mesa.control@acma.dev"]
    admin_empresa = usuarios["admin.empresa@acma.dev"]
    tecnicos = [usuarios[e] for e in ("tecnico1@acma.dev", "tecnico2@acma.dev", "tecnico3@acma.dev", "tecnico4@acma.dev") if e in usuarios]
    a_ap, a_des, a_mesa, a_ae = (actor_de(u) for u in (admin_prestador, despachador, mesa, admin_empresa))
    unidades = list((await db.execute(select(UnidadNegocio).where(UnidadNegocio.tenant_id == tenant.id).order_by(UnidadNegocio.codigo))).scalars())
    hoy = date.today()

    # ------------------------------------------------ artículos y ubicaciones
    articulos: dict[str, Articulo] = {}
    for categoria, lista in CATEGORIAS.items():
        for codigo, descripcion, unidad, costo, minimo in lista:
            a = Articulo(prestador_id=prestador.id, codigo=codigo, descripcion=descripcion, unidad=unidad, categoria=categoria,
                         costo_unitario_vigente=Decimal(costo), stock_minimo_default=Decimal(str(minimo)), numero_parte=f"NP-{codigo[-3:]}")
            db.add(a)
            articulos[codigo] = a
    await db.flush()
    almacen = UbicacionInventario(prestador_id=prestador.id, tipo=TipoUbicacionInventario.almacen, nombre="Almacén central")
    db.add(almacen)
    await db.flush()
    filas_tecnico = {t.usuario_id: t for t in (await db.execute(select(Tecnico).where(Tecnico.prestador_id == prestador.id))).scalars()}
    vehiculos: dict[str, UbicacionInventario] = {}
    for u in tecnicos:
        t = filas_tecnico.get(u.id)
        v = UbicacionInventario(prestador_id=prestador.id, tipo=TipoUbicacionInventario.vehiculo, nombre=f"Vehículo de {u.nombre.split()[0]}",
                                tecnico_id=u.id, placas=t.vehiculo_placas if t else None)
        db.add(v)
        vehiculos[u.email] = v
    await db.flush()

    # --------------------------------------------- existencias y movimientos
    for codigo, a in articulos.items():
        # Holgura sobre el mínimo para que solo los dos artículos de BAJO_MINIMO disparen la alerta.
        cantidad = (a.stock_minimo_default * Decimal("3") + Decimal("6")).quantize(Decimal("1"))
        if codigo in BAJO_MINIMO:
            cantidad, _ = BAJO_MINIMO[codigo]
            if cantidad > 0:
                await inventario_service.entrada(db, a_ap, articulo_id=a.id, ubicacion_id=almacen.id, cantidad=cantidad,
                                                 costo_unitario=a.costo_unitario_vigente, referencia="INV-INICIAL", razon="Inventario inicial (demo)")
            continue
        await inventario_service.entrada(db, a_ap, articulo_id=a.id, ubicacion_id=almacen.id, cantidad=cantidad,
                                         costo_unitario=a.costo_unitario_vigente, referencia="INV-INICIAL", razon="Inventario inicial (demo)")
    # Carga de las unidades: traspaso almacén → vehículo de los dos técnicos principales.
    for email, codigos in (("tecnico1@acma.dev", ["REF-001", "REF-005", "CON-001", "CON-003"]), ("tecnico4@acma.dev", ["CLI-001", "CLI-006", "ILU-001", "CON-002"])):
        if email not in vehiculos:
            continue
        for codigo in codigos:
            await inventario_service.traspaso(db, a_ap, articulo_id=articulos[codigo].id, origen_id=almacen.id, destino_id=vehiculos[email].id,
                                              cantidad=Decimal("3"), razon="Carga de la unidad (demo)")
            e = await inventario_service.existencia(db, vehiculos[email], articulos[codigo].id)
            e.stock_minimo = Decimal("1")  # el vehículo tiene su propio mínimo, no el del almacén
    await db.flush()

    # ------------------------------------------------------ órdenes de compra
    folio_refaccion = (await db.execute(select(Folio).where(Folio.tenant_id == tenant.id, Folio.estado == EstadoFolio.pendiente_refaccion))).scalars().first()
    oc_borrador = await inventario_service.crear_oc(db, a_des, folio_id=folio_refaccion.id if folio_refaccion else None, proveedor="Refacciones del Norte",
                                                    partidas=[{"articulo_id": articulos["REF-002"].id, "cantidad": Decimal("2")}], notas="Compresor para el folio en espera")
    oc_aprobada = await inventario_service.crear_oc(db, a_des, folio_id=None, proveedor="Climas y Equipos SA",
                                                    partidas=[{"articulo_id": articulos["CLI-003"].id, "cantidad": Decimal("2")},
                                                              {"articulo_id": articulos["CLI-004"].id, "cantidad": Decimal("2")}])
    await inventario_service.aprobar_oc(db, a_ap, oc_aprobada)
    oc_recibida = await inventario_service.crear_oc(db, a_mesa, folio_id=None, proveedor="Iluminación Industrial MX",
                                                    partidas=[{"articulo_id": articulos["ILU-002"].id, "cantidad": Decimal("6"), "costo_unitario": Decimal("298.00")}])
    await inventario_service.aprobar_oc(db, a_ap, oc_recibida)
    await inventario_service.recibir_oc(db, a_ap, oc_recibida)
    await db.flush()

    # ------------------------------------------------------------- caja chica
    fondos = {}
    for email, monto in (("tecnico1@acma.dev", Decimal("5000.00")), ("tecnico4@acma.dev", Decimal("3000.00"))):
        if email in usuarios:
            fondos[email] = await caja_chica_service.crear_fondo(db, a_ap, tecnico_id=usuarios[email].id, monto_inicial=monto)
    await db.flush()
    folios_abiertos = list((await db.execute(select(Folio).where(Folio.tenant_id == tenant.id, Folio.estado.in_(
        (EstadoFolio.en_ejecucion, EstadoFolio.asignado, EstadoFolio.pendiente_refaccion))).order_by(Folio.numero_folio))).scalars())
    plan_gastos = [
        ("tecnico1@acma.dev", "Refaccionaria El Tornillo", "RET850101AB2", "Manguera de drenaje 1 m", Decimal("180.00"), Decimal("28.80"), "aprobado", None),
        ("tecnico1@acma.dev", "Ferretería Industrial", "FIN900505XY9", "Abrazaderas inoxidables (6 pz)", Decimal("240.00"), Decimal("38.40"), "aprobado", "CON-001"),
        ("tecnico4@acma.dev", "Climas Express", "CEX010203QW4", "Capacitor de arranque 45 µF", Decimal("310.00"), Decimal("49.60"), "aprobado", "CLI-002"),
        ("tecnico4@acma.dev", "Refaccionaria El Tornillo", "RET850101AB2", "Juego de empaques universales", Decimal("420.00"), Decimal("67.20"), "capturado", None),
        ("tecnico1@acma.dev", "Materiales del Centro", None, "Cinta de teflón (sin factura fiscal)", Decimal("90.00"), Decimal("0.00"), "rechazado", None),
    ]
    ayer = datetime.now(UTC) - timedelta(days=1)
    for i, (email, proveedor, rfc, descripcion, subtotal, iva, estado, codigo) in enumerate(plan_gastos):
        if email not in fondos:
            continue
        # El gasto se captura desde la atención del folio: solo folios asignados a ese técnico.
        suyos = [f for f in folios_abiertos if f.tecnico_id == usuarios[email].id]
        folio = suyos[i % len(suyos)] if suyos else None
        g = await caja_chica_service.capturar_gasto(db, actor_de(usuarios[email]), folio_id=folio.id if folio else None, proveedor=proveedor,
                                                    rfc_proveedor=rfc, uuid_cfdi=f"A1B2C3D4-0000-0000-0000-{i:012d}" if rfc else None,
                                                    descripcion=descripcion, numero_parte=None, subtotal=subtotal, iva=iva,
                                                    articulo_id=articulos[codigo].id if codigo else None, centro_costos="MANTENIMIENTO",
                                                    cuenta_contable="5101-001", tecnico_id=usuarios[email].id)
        if estado == "aprobado":
            await caja_chica_service.aprobar_gasto(db, a_ap, g)
            g.aprobado_at = ayer if i < 3 else g.aprobado_at
            g.timestamp = ayer if i < 3 else g.timestamp
        elif estado == "rechazado":
            await caja_chica_service.rechazar_gasto(db, a_ap, g, "Sin comprobante fiscal: no se puede deducir")
    await db.flush()
    await caja_chica_service.generar_poliza(db, a_ap, prestador_id=prestador.id, fecha=ayer.date())
    await db.flush()

    # -------------------------------------------- tarifas y costos de folios
    db.add_all([
        TarifaManoObra(prestador_id=prestador.id, tenant_id=None, tipo_folio=None, tarifa_hora=Decimal("450.00"), vigente_desde=hoy - timedelta(days=180)),
        TarifaManoObra(prestador_id=prestador.id, tenant_id=tenant.id, tipo_folio=TipoFolio.preventivo, tarifa_hora=Decimal("380.00"), vigente_desde=hoy - timedelta(days=90)),
        TarifaManoObra(prestador_id=prestador.id, tenant_id=tenant.id, tipo_folio=TipoFolio.especial, tarifa_hora=Decimal("620.00"), vigente_desde=hoy - timedelta(days=90)),
    ])
    await db.flush()
    cerrados = list((await db.execute(select(Folio).where(Folio.tenant_id == tenant.id, Folio.estado == EstadoFolio.cerrado)
                                      .order_by(Folio.numero_folio))).scalars())
    for i, f in enumerate(cerrados):
        if not (await db.execute(select(FolioRefaccion.id).where(FolioRefaccion.folio_id == f.id))).first():
            codigo = ["REF-001", "CLI-001", "ILU-003", "CON-001"][i % 4]
            a = articulos[codigo]
            db.add(FolioRefaccion(folio_id=f.id, tenant_id=f.tenant_id, prestador_id=f.prestador_id, articulo_id=a.id, descripcion=a.descripcion,
                                  cantidad=Decimal("1"), origen=OrigenRefaccion.almacen, costo_unitario=a.costo_unitario_vigente))
            await db.flush()
        c = await costos_service.calcular(db, f, a_mesa, forzar=True)
        if i < max(1, len(cerrados) - 1):
            await costos_service.validar(db, a_mesa, f, centro_costos="MANTENIMIENTO")
        _ = c
    await db.flush()

    # ------------------------------------------------------- presupuestos
    inicio_t = date(hoy.year, ((hoy.month - 1) // 3) * 3 + 1, 1)
    fin_t = (date(inicio_t.year + (1 if inicio_t.month + 3 > 12 else 0), (inicio_t.month + 3 - 1) % 12 + 1, 1) - timedelta(days=1))
    grupo = (await db.execute(select(GrupoUN).where(GrupoUN.tenant_id == tenant.id))).scalars().first()
    # Monto calibrado contra el costo real ya validado: la primera UN queda ~85 % y la segunda, excedida.
    from models.costos import FolioCosto as _FC

    por_un: dict = {}
    for f in cerrados:
        c = (await db.execute(select(_FC).where(_FC.folio_id == f.id))).scalar_one_or_none()
        if c is not None and c.validado_at is not None and inicio_t <= (f.fecha_cierre.date() if f.fecha_cierre else hoy) <= fin_t:
            por_un[f.un_id] = por_un.get(f.un_id, Decimal("0")) + c.costo_total
    for i, un in enumerate(unidades[:3]):
        gastado = por_un.get(un.id, Decimal("0"))
        if i == 0:
            monto = (gastado / Decimal("0.85")).quantize(Decimal("0.01")) if gastado > 0 else Decimal("60000.00")
        elif i == 1:
            monto = (gastado * Decimal("0.8")).quantize(Decimal("0.01")) if gastado > 0 else Decimal("12000.00")
        else:
            monto = Decimal("90000.00")
        await presupuestos_service.crear(db, a_ae, {"nombre": f"Mantenimiento {un.codigo} · {inicio_t.year}-T{(inicio_t.month - 1) // 3 + 1}",
                                                    "un_id": un.id, "tipo_actividad": TipoActividadPresupuesto.todos, "periodo_inicio": inicio_t,
                                                    "periodo_fin": fin_t, "monto": max(monto, Decimal("100.00")), "umbrales_alerta_json": [50, 80, 100]})
    if grupo is not None:
        await presupuestos_service.crear(db, a_ae, {"nombre": f"Grupo {grupo.nombre} · correctivos", "grupo_id": grupo.id,
                                                    "tipo_actividad": TipoActividadPresupuesto.correctivo, "periodo_inicio": inicio_t,
                                                    "periodo_fin": fin_t, "monto": Decimal("45000.00"), "umbrales_alerta_json": [60, 85, 100]})
    await db.flush()
    # Los folios ya validados se cargan a los presupuestos recién creados.
    from models.costos import FolioCosto

    for f in cerrados:
        c = (await db.execute(select(FolioCosto).where(FolioCosto.folio_id == f.id))).scalar_one_or_none()
        if c is not None and c.validado_at is not None:
            await presupuestos_service.registrar_consumo(db, f, c, a_mesa)
    await db.flush()

    # ---------------------------------------------------------------- ERP
    cfg = await erp_eventos.configuracion(db, prestador.id, crear=True)
    cfg.columnas_excel_json = list(erp_eventos.COLUMNAS_DEFECTO)
    cfg.cuentas_contables_json = {"generar_oc": "2101-001", "registrar_gasto": "5101-001", "crear_activo_fijo": "1201-001", "poliza_caja_chica": "1105-001"}
    cfg.centros_costos_json = {"registrar_gasto": "MANTENIMIENTO", "poliza_caja_chica": "ADMINISTRACION"}
    await db.flush()
    for f in (await db.execute(select(Folio).where(Folio.tenant_id == tenant.id, Folio.equipo_instalado_id.is_not(None)))).scalars():
        instalado = await db.get(Equipo, f.equipo_instalado_id)
        if instalado is not None:
            await erp_eventos.crear_activo_fijo(db, f, instalado)
    await db.flush()

    # ------------------------------------------------------------ activos
    equipos = list((await db.execute(select(Equipo).where(Equipo.tenant_id == tenant.id).order_by(Equipo.codigo))).scalars())
    tipos = {t.id: t for t in (await db.execute(select(TipoEquipo))).scalars()}
    for t in tipos.values():
        if t.costo_hora_inactividad_default is None:
            t.costo_hora_inactividad_default = Decimal("350.00")
    datos_activos = [(Decimal("85000.00"), 10, MetodoDepreciacion.linea_recta, Decimal("95000.00")),
                     (Decimal("210000.00"), 15, MetodoDepreciacion.linea_recta, Decimal("240000.00")),
                     (Decimal("32000.00"), 8, MetodoDepreciacion.doble_saldo_decreciente, Decimal("36000.00")),
                     (Decimal("18000.00"), 5, MetodoDepreciacion.linea_recta, Decimal("21000.00")),
                     (Decimal("12000.00"), 5, MetodoDepreciacion.doble_saldo_decreciente, Decimal("9000.00")),
                     (Decimal("75000.00"), 10, MetodoDepreciacion.manual, Decimal("82000.00"))]
    for e, (costo, vida, metodo, reposicion) in zip(equipos[:6], datos_activos, strict=False):
        e.costo_adquisicion = costo
        e.fecha_adquisicion = hoy - timedelta(days=365 * 4 + 30)
        e.valor_reposicion = reposicion
        e.costo_hora_inactividad = Decimal("420.00") if e.criticidad in ("A", "B") else None
        db.add(ActivoDepreciacion(equipo_id=e.id, tenant_id=e.tenant_id, metodo=metodo, vida_util_anios=vida,
                                  valor_salvamento=(costo * Decimal("0.1")).quantize(Decimal("0.01")), valor_reposicion=reposicion,
                                  valor_en_libros_manual=(costo * Decimal("0.45")).quantize(Decimal("0.01")) if metodo == MetodoDepreciacion.manual else None,
                                  fecha_inicio=hoy - timedelta(days=365 * 4 + 30), configurado_por=admin_empresa.id))
    await db.flush()
    # 12 meses de snapshots para los seis equipos y una alerta de reemplazo en el último.
    for e, (costo, _vida, _metodo, reposicion) in zip(equipos[:6], datos_activos, strict=False):
        for atras in range(11, -1, -1):
            cuando = date(hoy.year, hoy.month, 1) - timedelta(days=atras * 30)
            await activos_service.calcular_depreciacion(db, e, cuando)
            await activos_service.calcular_tco(db, e, cuando, a_ae)
    # El equipo 5 (depreciación acelerada y reposición baja) queda sobre el umbral con un TCO alto.
    if len(equipos) >= 5:
        objetivo = equipos[4]
        ultimo = (await db.execute(select(ActivoTCOSnapshot).where(ActivoTCOSnapshot.equipo_id == objetivo.id)
                                    .order_by(ActivoTCOSnapshot.periodo.desc()))).scalars().first()
        if ultimo is not None:
            ultimo.costo_correctivos = Decimal("4200.00")
            ultimo.costo_downtime = Decimal("3800.00")
            ultimo.tco_total = (ultimo.costo_adquisicion + ultimo.costo_correctivos + ultimo.costo_downtime - ultimo.valor_residual).quantize(Decimal("0.01"))
            ultimo.porcentaje_vs_reposicion = (ultimo.tco_total / ultimo.valor_reposicion * 100).quantize(Decimal("0.01")) if ultimo.valor_reposicion else Decimal("0")
            await db.flush()
            await activos_service._revisar_reemplazo(db, objetivo, ultimo, a_ae)
    await db.flush()
    _ = oc_borrador
    return True


async def main() -> None:
    from core.db import nueva_sesion

    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        ok = await sembrar_inventario(db)
        await db.commit()
    print("Inventario, caja chica, presupuestos y activos demo creados." if ok else "Ya existían (o falta el seed base).")


if __name__ == "__main__":
    asyncio.run(main())
