"""Datos demo de P07: configuración de la minuta (con validación, 19:00, ventana 30 min, plazo 24 h), período presupuestal
trimestral, severidades no críticas, hallazgos en 6 folios, 2 peticiones, minutas de los últimos 3 días (una respondida, una
vencida, una pendiente de validación), cotizaciones en distintos estados con PDF, diferidos, seguimientos internos,
reprogramaciones (una con 2 fechas vencidas), 4 folios pendientes de clasificar y la calificación del período. Idempotente."""
import asyncio
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import select

from core.rls import CONTEXTO_SISTEMA
from models.catalogos import Equipo, FamiliaEquipo, TipoEquipo, TipoFalla
from models.folios import CanalAprobacion, Folio
from models.minutas import CanalNotificacion, EstadoMinuta, Hallazgo, Minuta, ModoMinuta, NivelUrgencia, OpcionRespuesta, OrigenHallazgo, OrigenPeticion, PeticionCliente, TipoHallazgo
from models.organizaciones import Prestador, Tenant
from models.seguimiento import (
    ClasificacionConfiguracion, EstadoReprogramacion, EstadoSeguimientoInterno, PeriodoPresupuestal, Reprogramacion, TipoPeriodoPresupuestal, VarianteCoordinado,
)
from models.unidades import UnidadNegocio
from models.usuarios import Usuario
from schemas.folios import FolioEntrada
from scripts.seed_folios import actor_de
from services import clasificacion_service, minuta_service
from services import folios_captura_service as captura
from services.seguimiento import base as seg_base, cotizaciones, entradas, interno, reprogramacion


async def sembrar_minuta(db) -> bool:
    prestador = (await db.execute(select(Prestador).where(Prestador.rfc == "PDE200101AB1"))).scalar_one_or_none()
    tenant = (await db.execute(select(Tenant).where(Tenant.rfc == "CDE200101XY2"))).scalar_one_or_none()
    if prestador is None or tenant is None:
        return False
    if (await db.execute(select(Minuta.id).where(Minuta.tenant_id == tenant.id))).first():
        return False
    usuarios = {u.email: u for u in (await db.execute(select(Usuario))).scalars()}
    admin_prestador, despachador, mesa = usuarios["admin.prestador@acma.dev"], usuarios["despachador@acma.dev"], usuarios["mesa.control@acma.dev"]
    admin_un, admin_empresa, operador = usuarios["admin.un@acma.dev"], usuarios["admin.empresa@acma.dev"], usuarios["operador@acma.dev"]
    tecnico1, tecnico2 = usuarios["tecnico1@acma.dev"], usuarios["tecnico2@acma.dev"]
    unidades = list((await db.execute(select(UnidadNegocio).where(UnidadNegocio.tenant_id == tenant.id).order_by(UnidadNegocio.codigo))).scalars())
    equipos = {e.codigo: e for e in (await db.execute(select(Equipo).where(Equipo.tenant_id == tenant.id))).scalars()}
    folios = {f.numero_folio: f for f in (await db.execute(select(Folio).where(Folio.tenant_id == tenant.id).order_by(Folio.numero_folio))).scalars()}
    hoy = date.today()
    d1, d2 = hoy - timedelta(days=2), hoy - timedelta(days=1)

    # --------------------------------------------------- configuración
    cfg = await minuta_service.configuracion(db, prestador.id, tenant.id)
    cfg.modo, cfg.hora_envio, cfg.ventana_validacion_min, cfg.plazo_respuesta_horas = ModoMinuta.automatica, time(19, 0), 30, 24
    db.add(PeriodoPresupuestal(tenant_id=tenant.id, tipo=TipoPeriodoPresupuestal.trimestral, fechas_json=[], activo=True))
    await db.flush()

    # --------------------------------------------------- hallazgos y peticiones (6 folios, 3 días)
    def folio_de(codigo: str, *, estado=None) -> Folio:
        for f in folios.values():
            if f.equipo_id == equipos[codigo].id and (estado is None or f.estado.value == estado):
                return f
        return next(f for f in folios.values() if f.equipo_id == equipos[codigo].id)

    def ts(d: date, h: int) -> datetime:
        return datetime(d.year, d.month, d.day, h, 0, tzinfo=UTC)

    plan_h = [
        (folio_de("EQ-0001", estado="cerrado"), "Empaque de la puerta del refrigerador vencido; pierde frío por la noche.", NivelUrgencia.media, TipoHallazgo.correctivo, ts(d1, 16)),
        (folio_de("EQ-0005", estado="cerrado"), "El compresor del refrigerador de Polanco vibra más de lo normal; revisar soportes.", NivelUrgencia.alta, TipoHallazgo.preventivo, ts(d1, 17)),
        (folio_de("EQ-0003"), "Tubería de drenaje del minisplit rota: gotea sobre la caja registradora.", NivelUrgencia.alta, TipoHallazgo.correctivo, ts(d2, 15)),
        (folio_de("EQ-0004"), "Balastro del pasillo con olor a quemado; riesgo eléctrico.", NivelUrgencia.critica, TipoHallazgo.correctivo, ts(d2, 18)),
        (folio_de("EQ-0007"), "Filtros del minisplit de Polanco saturados; requiere reemplazo.", NivelUrgencia.baja, TipoHallazgo.preventivo, ts(hoy, 10)),
        (folio_de("EQ-0012"), "Lámpara del almacén sin difusor; el operador pide uno nuevo.", NivelUrgencia.baja, TipoHallazgo.correctivo, ts(hoy, 11)),
    ]
    hallazgos = []
    for folio, desc, urg, tipo, cuando in plan_h:
        h = Hallazgo(folio_id=folio.id, tenant_id=tenant.id, prestador_id=prestador.id, un_id=folio.un_id, equipo_id=folio.equipo_id, descripcion=desc, nivel_urgencia=urg, tipo=tipo,
                     origen=OrigenHallazgo.formulario_atencion if tipo == TipoHallazgo.preventivo else OrigenHallazgo.manual, capturado_por=tecnico1.id, timestamp=cuando)
        db.add(h)
        hallazgos.append(h)
    db.add(PeticionCliente(folio_id=folio_de("EQ-0003").id, tenant_id=tenant.id, prestador_id=prestador.id, un_id=unidades[0].id,
                           texto="El gerente pide que la próxima visita sea antes de las 9:00 para no interrumpir la apertura.", origen=OrigenPeticion.chat,
                           capturado_por=operador.id, timestamp=ts(d2, 15)))
    db.add(PeticionCliente(folio_id=folio_de("EQ-0007").id, tenant_id=tenant.id, prestador_id=prestador.id, un_id=unidades[1].id,
                           texto="Revisar también el extractor de la cocina en la siguiente visita.", origen=OrigenPeticion.formulario, capturado_por=admin_un.id, timestamp=ts(hoy, 10)))
    await db.flush()

    # --------------------------------------------------- minutas: d1 respondida, d2 vencida, hoy pendiente de validación
    minutas_d1 = await minuta_service.generar(db, prestador.id, tenant.id, d1, forzar=True)
    for m in minutas_d1:  # automática: ya enviadas
        m.timestamp_envio = ts(d1, 19)
    await db.flush()
    actor_un, actor_ae, actor_des, actor_ap = actor_de(admin_un), actor_de(admin_empresa), actor_de(despachador), actor_de(admin_prestador)
    m_un1 = next(m for m in minutas_d1 if m.un_id == hallazgos[0].un_id)
    m_global1 = next(m for m in minutas_d1 if m.un_id is None)
    # Respuestas §7.4: cotización y seguimiento interno (Admin UN desde la app), autorizar reparar (Admin empresa desde el correo).
    await minuta_service.responder(db, actor_un, m_un1, hallazgos[0], OpcionRespuesta.cotizacion, notas="Cotizar cambio de empaque", canal=CanalNotificacion.app,
                                   fecha_tentativa=None, proveedor=None, trabajo_coordinado=False, variante=None, request=None)
    await minuta_service.responder(db, actor_ae, m_global1, hallazgos[1], OpcionRespuesta.autorizar_reparar, notas="Repárenlo esta semana", canal=CanalNotificacion.email,
                                   fecha_tentativa=None, proveedor=None, trabajo_coordinado=False, variante=None, request=None)
    await db.flush()

    minutas_d2 = await minuta_service.generar(db, prestador.id, tenant.id, d2, forzar=True)
    for m in minutas_d2:
        m.timestamp_envio, m.vence_respuesta_at = ts(d2, 19), ts(d2, 19) + timedelta(hours=24)
    await db.flush()
    m_un2 = next(m for m in minutas_d2 if m.un_id == hallazgos[2].un_id)
    # Una respuesta (reprogramación con tercero) y el resto vence sin respuesta.
    await minuta_service.responder(db, actor_un, m_un2, hallazgos[2], OpcionRespuesta.reprogramacion, notas="Lo atiende el plomero del centro comercial",
                                   canal=CanalNotificacion.push, fecha_tentativa=hoy - timedelta(days=5), proveedor="Plomería del Centro", trabajo_coordinado=True,
                                   variante=VarianteCoordinado.A, request=None)
    await minuta_service.vencer_respuestas(db, datetime.now(UTC))

    cfg.modo = ModoMinuta.con_validacion
    await db.flush()
    minutas_hoy = await minuta_service.generar(db, prestador.id, tenant.id, hoy, forzar=True)
    for m in minutas_hoy:
        m.timestamp_generacion = datetime.now(UTC) - timedelta(minutes=10)
    await db.flush()

    # --------------------------------------------------- módulos: cotizaciones (3 estados), diferidos, internos, reprogramaciones
    cot1 = (await db.execute(select(cotizaciones.Cotizacion).where(cotizaciones.Cotizacion.hallazgo_id == hallazgos[0].id))).scalar_one()
    await cotizaciones.preparar(db, actor_des, cot1, descripcion="Cambio de empaque magnético de puerta y ajuste de bisagras",
                                monto=Decimal("1850.00"), detalle={"partidas": [{"descripcion": "Empaque magnético", "cantidad": 1, "importe": "1250.00"}, {"descripcion": "Mano de obra", "cantidad": 1, "importe": "600.00"}]}, request=None)
    await cotizaciones.enviar_cliente(db, actor_des, cot1, None)
    cot2 = await cotizaciones.crear(db, actor_un, tenant_id=tenant.id, prestador_id=prestador.id, un_id=unidades[1].id, equipo_id=equipos["EQ-0006"].id,
                                    descripcion="Reemplazo del evaporador de la cámara de congelación de Polanco", hallazgo_id=None, folio_id=None, origen="directo", request=None)
    await cotizaciones.preparar(db, actor_ap, cot2, descripcion="Reemplazo del evaporador de la cámara de congelación", monto=Decimal("18400.00"), detalle=None, request=None)
    await cotizaciones.enviar_cliente(db, actor_ap, cot2, None)
    await cotizaciones.responder(db, actor_ae, cot2, True, "Autorizada; programar la próxima semana", None, None)
    cot3 = await cotizaciones.crear(db, actor_un, tenant_id=tenant.id, prestador_id=prestador.id, un_id=unidades[2].id, equipo_id=equipos["EQ-0011"].id,
                                    descripcion="Carga de gas y revisión de fugas del minisplit de Coyoacán", hallazgo_id=None, folio_id=None, origen="directo", request=None)
    await cotizaciones.enviar_externo(db, actor_ae, cot2, ["compras@clientedemo.mx"], "Para su expediente de licitación", None)

    # Diferidos: el folio rechazado por presupuesto de P04 (migración de la derivación) + uno directo.
    await entradas.procesar_derivaciones_pendientes(db)
    from services.seguimiento import presupuesto

    await presupuesto.crear(db, actor_un, tenant_id=tenant.id, prestador_id=prestador.id, un_id=unidades[2].id, equipo_id=equipos["EQ-0010"].id,
                            descripcion="Cambio de puerta de la cámara de congelación de Coyoacán (bisagras vencidas)", origen="directo", monto_estimado=Decimal("9500.00"))
    # Seguimientos internos: uno registrado y uno con proveedor.
    s1 = await interno.crear(db, actor_un, tenant_id=tenant.id, prestador_id=prestador.id, un_id=unidades[0].id, equipo_id=equipos["EQ-0002"].id,
                             descripcion="Garantía del fabricante de la cámara de congelación: ruido del ventilador", origen="directo")
    s2 = await interno.crear(db, actor_ae, tenant_id=tenant.id, prestador_id=prestador.id, un_id=unidades[1].id, equipo_id=equipos["EQ-0008"].id,
                             descripcion="Anuncio luminoso: el cliente lo atiende con su proveedor de rotulación", origen="directo")
    await interno.cambiar_estado(db, actor_ae, s2, EstadoSeguimientoInterno.con_proveedor, "Proveedor confirmado", None, proveedor="Rótulos del Norte",
                                 fecha_acordada=hoy + timedelta(days=6), referencia_tercero="RN-2291")
    _ = s1
    # Reprogramaciones: la del hallazgo (variante A, 2 fechas vencidas) y una pendiente de fecha.
    r1 = (await db.execute(select(Reprogramacion).where(Reprogramacion.hallazgo_id == hallazgos[2].id))).scalar_one()
    await reprogramacion.registrar_fecha_vencida(db, r1, hoy)
    await reprogramacion.cambiar_estado(db, actor_un, r1, EstadoReprogramacion.fecha_asignada, "Nueva fecha con el plomero", None, proveedor="Plomería del Centro",
                                        fecha_acordada=hoy - timedelta(days=2), referencia_tercero="PC-118")
    await reprogramacion.registrar_fecha_vencida(db, r1, hoy)
    await reprogramacion.crear(db, actor_un, tenant_id=tenant.id, prestador_id=prestador.id, un_id=unidades[2].id, equipo_id=equipos["EQ-0012"].id,
                               descripcion="Reemplazo de luminarias del almacén por el proveedor eléctrico del centro comercial", origen="directo",
                               motivo="Requiere corte de energía coordinado con el centro comercial")
    await db.flush()

    # --------------------------------------------------- clasificación: config + 4 folios no críticos pendientes
    db.add(ClasificacionConfiguracion(tenant_id=tenant.id, severidades_no_criticas_json=["muy_baja", "baja", "media"], plazo_horas=24, umbral_calificacion=70,
                                      admin_empresa_puede_clasificar=True))
    await db.flush()
    familias = {f.nombre: f for f in (await db.execute(select(FamiliaEquipo))).scalars()}
    tipos = {t.id: t for t in (await db.execute(select(TipoEquipo))).scalars()}
    fallas = {}
    for tf in (await db.execute(select(TipoFalla).where(TipoFalla.prestador_id == prestador.id))).scalars():
        familia = next(f for f in familias.values() if f.id == tf.familia_equipo_id)
        fallas[(familia.nombre, tf.descripcion)] = tf
    capturas = [
        ("EQ-0003", ("Climatización", "Gotea agua"), "El minisplit del centro gotea sobre el mostrador (no urgente).", operador, ts(hoy, 16)),
        ("EQ-0008", ("Iluminación", "No enciende"), "Dos tubos del anuncio luminoso apagados.", admin_un, ts(hoy, 16)),
        ("EQ-0011", ("Climatización", "No enfría"), "El minisplit de Coyoacán enfría poco por las tardes.", admin_empresa, ts(d2, 16)),
        ("EQ-0012", ("Iluminación", "No enciende"), "Lámpara del pasillo trasero fundida.", admin_empresa, ts(d2, 17)),
    ]
    for codigo, falla, desc, quien, cuando in capturas:
        e = equipos[codigo]
        if tipos[e.tipo_equipo_id].familia_id != familias[falla[0]].id:
            continue
        datos = FolioEntrada(un_id=e.un_id, equipo_id=e.id, tipo_falla_id=fallas[falla].id, descripcion=desc, confirmacion_un=True, confirmacion_un_geolat=19.4326,
                             confirmacion_un_geolng=-99.1332, geolat_captura=19.4326, geolng_captura=-99.1332,
                             folio_duplicado_justificacion="Falla distinta a la del folio abierto (demo P07)")
        f = await captura.crear(db, actor_de(quien), datos, None, cuando)
        # Los dos de ayer ya están fuera de plazo (plazo 24 h): el trigger conserva la hora de captura.
        from models.folios import RevisionManualTrigger, TriggerRevision

        for t in (await db.execute(select(RevisionManualTrigger).where(RevisionManualTrigger.folio_id == f.id, RevisionManualTrigger.trigger_tipo == TriggerRevision.pendiente_clasificacion))).scalars():
            t.timestamp = cuando
    await db.flush()
    await clasificacion_service.calificar(db, tenant.id, clasificacion_service.periodo_de(hoy))
    await db.flush()
    _ = (mesa, tecnico2, cot3, seg_base, CanalAprobacion)
    return True


async def main() -> None:
    from core.db import nueva_sesion

    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        ok = await sembrar_minuta(db)
        await db.commit()
    print("Minuta y seguimiento demo creados." if ok else "Ya existían o faltan los datos base.")


if __name__ == "__main__":
    asyncio.run(main())
