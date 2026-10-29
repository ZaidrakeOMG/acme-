"""Datos demo de P08: formulario publicado de tipo `trabajo_especial`, permiso `ejecutar_trabajos_especiales` para Tomás y Tania,
8 trabajos especiales (uno por estado: creado, enviado al cliente con dos versiones y un rechazo, aceptado, rechazado, programado desde
la cotización autorizada de P07, de urgencia en ejecución creado por el Admin UN, cerrado con evidencia y firma, cancelado), y 4 folios
de instalación de activo (pendiente de iniciar trámite, OC en trámite, OC autorizada → listo para asignar, y uno cerrado con el equipo
dado de alta). Idempotente."""
import asyncio
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from core.rls import CONTEXTO_SISTEMA
from models.catalogos import Equipo, FamiliaEquipo, TipoEquipo, TipoFalla
from models.folios import EstadoFolio, Folio
from models.formularios import EstadoRespuesta, Formulario, FormularioAsignacion, FormularioEvidencia, FormularioRespuesta, OrigenRespuesta, TipoEvidencia
from models.organizaciones import Prestador, Tenant
from models.permisos import TecnicoPermisoOverride
from models.seguimiento import Cotizacion, EstadoCotizacion
from models.trabajos_especiales import EstadoTrabajoEspecial as E, EstatusOCActivo, DecisionOCRechazo, TrabajoEspecial
from models.unidades import UnidadNegocio
from models.usuarios import Usuario
from schemas.folios import FolioEntrada
from scripts.seed_folios import EN_HORARIO, actor_de
from services import folio_estados, oc_activos_service
from services import folios_captura_service as captura
from services import trabajos_especiales_service as te_svc
from services.seguimiento import cotizaciones

ESQUEMA_TE = {"secciones": [{"clave": "trabajo", "titulo": "Trabajo especial", "campos": [
    {"clave": "descripcion_trabajo", "tipo": "texto_amplio", "etiqueta": "Descripción detallada del trabajo", "obligatorio": True, "config": {"longitud_min": 5, "longitud_max": 2000}},
    {"clave": "materiales", "tipo": "texto_amplio", "etiqueta": "Materiales a utilizar", "config": {"longitud_min": 0, "longitud_max": 2000}},
    {"clave": "tiempo_estimado_horas", "tipo": "texto", "etiqueta": "Tiempo estimado (horas)", "config": {"longitud_min": 0, "longitud_max": 10, "formato": "numeros"}},
    {"clave": "accesos_especiales", "tipo": "si_no", "etiqueta": "¿Requiere accesos especiales?", "config": {}},
    {"clave": "seguridad", "tipo": "texto", "etiqueta": "Consideraciones de seguridad", "config": {"longitud_min": 0, "longitud_max": 300}},
]}, {"clave": "cierre", "titulo": "Puntos de verificación al cierre", "campos": [
    {"clave": "verificacion_funcional", "tipo": "si_no", "etiqueta": "Verificación funcional realizada", "obligatorio": True, "config": {}},
    {"clave": "foto_cierre", "tipo": "fotografia", "etiqueta": "Evidencia fotográfica de cierre", "obligatorio": True, "config": {"cantidad_min": 1, "cantidad_max": 6}},
    {"clave": "firma", "tipo": "firma", "etiqueta": "Firma del cliente", "config": {}},
]}]}

ESQUEMA_CAPTURA_ACTIVO = {"secciones": [{"clave": "activo", "titulo": "Instalación de activo", "campos": [
    {"clave": "es_activo", "tipo": "si_no", "etiqueta": "¿Es instalación de un activo nuevo?", "obligatorio": True, "config": {},
     "clasifica_instalacion_activo": {"valor_afirmativo": "si", "campo_tipo_equipo": "tipo_equipo_nuevo", "campo_marca": "marca", "campo_modelo": "modelo", "campo_serie": "serie",
                                      "campo_valor_reposicion": "valor"}},
    {"clave": "tipo_equipo_nuevo", "tipo": "texto", "etiqueta": "Tipo de equipo", "config": {"longitud_min": 0, "longitud_max": 120}},
    {"clave": "marca", "tipo": "texto", "etiqueta": "Marca", "config": {"longitud_min": 0, "longitud_max": 80}},
    {"clave": "modelo", "tipo": "texto", "etiqueta": "Modelo", "config": {"longitud_min": 0, "longitud_max": 80}},
    {"clave": "serie", "tipo": "texto", "etiqueta": "Número de serie", "config": {"longitud_min": 0, "longitud_max": 80}},
    {"clave": "valor", "tipo": "texto", "etiqueta": "Valor de reposición", "config": {"longitud_min": 0, "longitud_max": 20}},
]}]}


async def sembrar_trabajos_especiales(db) -> bool:
    from scripts.seed_dev import _formulario

    prestador = (await db.execute(select(Prestador).where(Prestador.rfc == "PDE200101AB1"))).scalar_one_or_none()
    tenant = (await db.execute(select(Tenant).where(Tenant.rfc == "CDE200101XY2"))).scalar_one_or_none()
    if prestador is None or tenant is None:
        return False
    if (await db.execute(select(TrabajoEspecial.id).where(TrabajoEspecial.tenant_id == tenant.id))).first():
        return False
    usuarios = {u.email: u for u in (await db.execute(select(Usuario))).scalars()}
    admin_prestador, despachador, mesa = usuarios["admin.prestador@acma.dev"], usuarios["despachador@acma.dev"], usuarios["mesa.control@acma.dev"]
    admin_un, admin_empresa, operador = usuarios["admin.un@acma.dev"], usuarios["admin.empresa@acma.dev"], usuarios["operador@acma.dev"]
    tecnico1, tecnico4 = usuarios["tecnico1@acma.dev"], usuarios["tecnico4@acma.dev"]
    unidades = list((await db.execute(select(UnidadNegocio).where(UnidadNegocio.tenant_id == tenant.id).order_by(UnidadNegocio.codigo))).scalars())
    equipos = {e.codigo: e for e in (await db.execute(select(Equipo).where(Equipo.tenant_id == tenant.id))).scalars()}
    a_ap, a_des, a_mesa, a_ae, a_un, a_t1, a_t4 = (actor_de(u) for u in (admin_prestador, despachador, mesa, admin_empresa, admin_un, tecnico1, tecnico4))
    hoy = date.today()

    # ----------------------------------------------- permisos y formularios
    for u in (tecnico1, tecnico4):
        db.add(TecnicoPermisoOverride(prestador_id=prestador.id, tecnico_id=u.id, permiso_clave="ejecutar_trabajos_especiales", habilitado=True,
                                      razon="Técnico senior habilitado para trabajos especiales (demo P08)", modificado_por=admin_prestador.id))
    form_te = await _formulario(db, prestador_id=prestador.id, tenant_id=None, nombre="Trabajo especial (global)", tipo="trabajo_especial", roles=["tecnico"],
                                esquema=ESQUEMA_TE, descripcion="Formulario del trabajo especial: descripción, materiales, accesos, seguridad y puntos de verificación al cierre",
                                publicado_por=admin_prestador.id)
    db.add(FormularioAsignacion(formulario_id=form_te.id, prestador_id=prestador.id, tenant_id=None, tipo_folio="especial", prioridad=3))
    form_activo = await _formulario(db, prestador_id=prestador.id, tenant_id=tenant.id, nombre="Captura de folio · instalación de activo", tipo="captura_operador",
                                    roles=["operador", "admin_un", "admin_empresa"], esquema=ESQUEMA_CAPTURA_ACTIVO,
                                    descripcion="Clasifica el folio como instalación de activo y captura los datos del equipo para el alta automática (§6.10.7)",
                                    publicado_por=admin_prestador.id)
    await db.flush()

    # ----------------------------------------------------- trabajos especiales
    async def nuevo(actor, un, descripcion, *, equipo=None, monto=None, urgencia=False, detalle=None):
        return await te_svc.crear(db, actor, tenant_id=tenant.id, un_id=un.id, equipo_id=equipo.id if equipo else None, descripcion=descripcion, detalle=detalle or {},
                                  monto=Decimal(monto) if monto is not None else None, urgencia=urgencia, request=None)

    async def mover(actor, te, estado, notas="", **campos):
        return await te_svc.cambiar_estado_te(db, actor, te, estado, notas, None, **campos)

    # 1. Creado (Mesa de control, solicitud directa del cliente).
    await nuevo(a_mesa, unidades[0], "Instalación de cortina de aire en la entrada principal de la sucursal Centro", monto="6200.00",
                detalle={"materiales": "Cortina de aire 90 cm, soportes, cableado", "tiempo_estimado_horas": 4})
    # 2. Enviado al cliente con dos versiones (la primera rechazada por el Admin empresa).
    te2 = await nuevo(a_des, unidades[1], "Reubicación del anuncio luminoso de Polanco a la fachada norte", equipo=equipos["EQ-0008"], monto="9800.00")
    await mover(a_des, te2, E.enviado_cliente, "Versión inicial")
    await mover(a_ae, te2, E.rechazado, "El monto excede lo acordado; revisen la mano de obra", canal="email")
    await mover(a_des, te2, E.enviado_cliente, "Se ajustó la mano de obra", monto=Decimal("8400.00"))
    # 3. Aceptado por el Admin UN (pendiente de programar).
    te3 = await nuevo(a_ap, unidades[0], "Mantenimiento mayor de la cámara de congelación: cambio de aislamiento de puerta", equipo=equipos["EQ-0002"], monto="12500.00")
    await mover(a_ap, te3, E.enviado_cliente)
    await mover(a_un, te3, E.aceptado, "Adelante, coordinen con el gerente", canal="app")
    # 4. Rechazado (el prestador decide si reenviar o cancelar).
    te4 = await nuevo(a_ap, unidades[2], "Pintura epóxica del piso del almacén de Coyoacán", monto="15800.00")
    await mover(a_ap, te4, E.enviado_cliente)
    await mover(a_ae, te4, E.rechazado, "No está en el presupuesto de este trimestre", canal="app")
    # 5. Programado desde la cotización autorizada de P07 (COT-00002): hereda UN, equipo, descripción y monto.
    cot = (await db.execute(select(Cotizacion).where(Cotizacion.tenant_id == tenant.id, Cotizacion.estado == EstadoCotizacion.autorizada).order_by(Cotizacion.numero))).scalars().first()
    if cot is not None:
        te5 = await cotizaciones.convertir_en_trabajo_especial(db, a_des, cot, None)
        await mover(a_des, te5, E.enviado_cliente, "Programación del reemplazo del evaporador")
        await mover(a_ae, te5, E.aceptado, "Autorizado; confirmen fecha", canal="email")
        await mover(a_des, te5, E.programado, "Cuadrilla de dos técnicos", fecha_programada=hoy + timedelta(days=3), tecnico_ids=[tecnico1.id, tecnico4.id], tecnico_responsable_id=tecnico1.id)
    # 6. De urgencia creado por el Admin UN: sin monto; el prestador lo programa directo y Tania lo inicia.
    te6 = await nuevo(a_un, unidades[0], "Fuga de agua en la cámara de congelación: requiere plomero hoy mismo (urgencia)", equipo=equipos["EQ-0002"], urgencia=True)
    await mover(a_des, te6, E.programado, "Urgencia: se programa sin validación", fecha_programada=hoy, tecnico_ids=[tecnico4.id], tecnico_responsable_id=tecnico4.id)
    await mover(a_t4, te6, E.en_ejecucion, "Llegué a la sucursal")
    # 7. Cerrado ayer con formulario del TE, evidencia fotográfica y firma del cliente.
    te7 = await nuevo(a_ap, unidades[1], "Instalación de luminarias LED en el estacionamiento de Polanco", equipo=equipos["EQ-0007"], monto="18900.00")
    await mover(a_ap, te7, E.enviado_cliente)
    await mover(a_ae, te7, E.aceptado, "Autorizado", canal="app")
    await mover(a_des, te7, E.programado, "", fecha_programada=hoy - timedelta(days=1), tecnico_ids=[tecnico1.id], tecnico_responsable_id=tecnico1.id)
    await mover(a_t1, te7, E.en_ejecucion, "Inicio de la instalación")
    folio7 = await db.get(Folio, te7.folio_id)
    r = FormularioRespuesta(formulario_id=form_te.id, version_id=form_te.version_publicada_id, tenant_id=tenant.id, prestador_id=prestador.id, un_id=folio7.un_id, equipo_id=folio7.equipo_id,
                            origen=OrigenRespuesta.folio_atencion, referencia_id=folio7.id, respondido_por=tecnico1.id, contexto_json={"sistema": {}, "sellos": {}},
                            respuestas_json={"descripcion_trabajo": "Se instalaron 12 luminarias LED con fotocelda", "materiales": "12 luminarias LED 50 W, cable, fotocelda",
                                             "tiempo_estimado_horas": "6", "accesos_especiales": False, "seguridad": "Trabajo en altura con arnés", "verificacion_funcional": True})
    db.add(r)
    await db.flush()
    db.add(FormularioEvidencia(respuesta_id=r.id, tenant_id=tenant.id, prestador_id=prestador.id, campo_clave="foto_cierre", tipo=TipoEvidencia.foto, archivo_key=f"demo/{r.id}/cierre.jpg",
                               nombre_original="cierre.jpg", mime="image/jpeg", bytes=204800, ancho_px=1600, alto_px=1200, hash_sha256="1" * 64))
    db.add(FormularioEvidencia(respuesta_id=r.id, tenant_id=tenant.id, prestador_id=prestador.id, campo_clave="firma", tipo=TipoEvidencia.firma, archivo_key=f"demo/{r.id}/firma.png",
                               nombre_original="firma.png", mime="image/png", bytes=1024, ancho_px=400, alto_px=200, hash_sha256="2" * 64))
    await db.flush()
    r.estado, r.enviado_at = EstadoRespuesta.enviado, datetime.now(UTC) - timedelta(hours=20)
    await db.flush()
    await captura.vincular_atencion(db, a_t1, folio7, r.id, None)
    await mover(a_t1, te7, E.cerrado, "Instalación concluida; el gerente firmó")
    te7.fecha_cierre = datetime.now(UTC) - timedelta(hours=19)
    # 8. Cancelado con razón por el Admin prestador.
    te8 = await nuevo(a_des, unidades[2], "Impermeabilización del techo del almacén de Coyoacán", monto="22000.00")
    await mover(a_des, te8, E.enviado_cliente)
    await mover(a_ap, te8, E.cancelado, "El cliente contrató el servicio con otro proveedor")
    await db.flush()

    # --------------------------------------------- folios de instalación de activo
    familias = {f.nombre: f for f in (await db.execute(select(FamiliaEquipo))).scalars()}
    tipos = {t.id: t for t in (await db.execute(select(TipoEquipo))).scalars()}
    fallas = {}
    for tf in (await db.execute(select(TipoFalla).where(TipoFalla.prestador_id == prestador.id))).scalars():
        familia = next(f for f in familias.values() if f.id == tf.familia_equipo_id)
        fallas[(familia.nombre, tf.descripcion)] = tf

    async def folio_activo(quien, codigo, descripcion, datos_equipo, cuando, falla_desc="No enciende"):
        e = equipos[codigo]
        familia = next(f for f in familias.values() if f.id == tipos[e.tipo_equipo_id].familia_id)
        falla = fallas[(familia.nombre, falla_desc)]
        resp = FormularioRespuesta(formulario_id=form_activo.id, version_id=form_activo.version_publicada_id, tenant_id=tenant.id, prestador_id=prestador.id, un_id=e.un_id, equipo_id=e.id,
                                   origen=OrigenRespuesta.folio_captura, respondido_por=quien.id, respuestas_json={"es_activo": True, **datos_equipo}, contexto_json={"sistema": {}, "sellos": {}},
                                   estado=EstadoRespuesta.enviado, enviado_at=cuando)
        db.add(resp)
        await db.flush()
        datos = FolioEntrada(un_id=e.un_id, equipo_id=e.id, tipo_falla_id=falla.id, descripcion=descripcion, confirmacion_un=True, confirmacion_un_geolat=19.4326, confirmacion_un_geolng=-99.1332,
                             geolat_captura=19.4326, geolng_captura=-99.1332, respuesta_id=resp.id, folio_duplicado_justificacion="Instalación de activo nuevo, distinta a la falla abierta (demo P08)")
        return await captura.crear(db, actor_de(quien), datos, None, cuando)

    t0 = EN_HORARIO + timedelta(days=1)
    tipo_ref = next(t for t in tipos.values() if t.nombre == "Refrigerador vertical")
    f1 = await folio_activo(operador, "EQ-0001", "Instalación de un refrigerador vertical adicional para bebidas en la sucursal Centro",
                            {"tipo_equipo_nuevo": tipo_ref.nombre, "marca": "Imbera", "modelo": "VR-12", "serie": "IMB-2026-0451", "valor": "28500"}, t0)
    f2 = await folio_activo(admin_un, "EQ-0005", "Instalación de minisplit nuevo en la oficina administrativa de Polanco",
                            {"tipo_equipo_nuevo": "Minisplit", "marca": "Mirage", "modelo": "X3 12000 BTU", "serie": "MRG-77A21", "valor": "14900"}, t0 + timedelta(hours=1))
    f3 = await folio_activo(admin_empresa, "EQ-0006", "Instalación de cámara de congelación modular en Coyoacán",
                            {"tipo_equipo_nuevo": "Cámara de congelación", "marca": "Torrey", "modelo": "CF-20", "serie": "TRY-CF20-0098", "valor": "185000"}, t0 + timedelta(hours=2))
    f4 = await folio_activo(operador, "EQ-0004", "Instalación de lámpara de emergencia nueva en el pasillo de bodega",
                            {"tipo_equipo_nuevo": "", "marca": "Philips", "modelo": "EM-200", "serie": "PH-EM-5521", "valor": "2300"}, t0 - timedelta(days=4))
    await db.flush()
    _, aut2 = await oc_activos_service.obtener(db, a_ae, f2.id)
    await oc_activos_service.cambiar_estatus(db, a_ae, f2, aut2, EstatusOCActivo.oc_en_tramite, numero_oc_provisional="OC-PROV-2026-118", notas="Solicitud creada en SAP", request=None)
    _, aut3 = await oc_activos_service.obtener(db, a_ae, f3.id)
    await oc_activos_service.cambiar_estatus(db, a_ae, f3, aut3, EstatusOCActivo.oc_en_tramite, numero_oc_provisional="OC-PROV-2026-121", request=None)
    await oc_activos_service.cambiar_estatus(db, a_ae, f3, aut3, EstatusOCActivo.oc_autorizada, numero_oc_definitivo="4500123987", fecha_autorizacion_erp=hoy - timedelta(days=1),
                                             notas="OC liberada por compras", request=None)
    # f4: OC autorizada hace días, ejecutado y cerrado → alta automática del equipo (sin tipo de equipo: queda inactivo con alerta).
    _, aut4 = await oc_activos_service.obtener(db, a_ae, f4.id)
    await oc_activos_service.cambiar_estatus(db, a_ae, f4, aut4, EstatusOCActivo.oc_autorizada, numero_oc_definitivo="4500123900", fecha_autorizacion_erp=hoy - timedelta(days=3), request=None)
    await captura.asignar(db, a_des, f4, tecnico4.id, None, "", None)
    await folio_estados.transicionar(db, f4, EstadoFolio.en_camino, a_t4, "Salgo hacia la UN")
    await folio_estados.transicionar(db, f4, EstadoFolio.en_ejecucion, a_t4, "Llegué a la UN", {"geolat": 19.4326, "geolng": -99.1332})
    atencion = (await db.execute(select(Formulario).where(Formulario.nombre == "Cierre de correctivo · Cliente Demo"))).scalar_one()
    ra = FormularioRespuesta(formulario_id=atencion.id, version_id=atencion.version_publicada_id, tenant_id=tenant.id, prestador_id=prestador.id, un_id=f4.un_id, equipo_id=f4.equipo_id,
                             origen=OrigenRespuesta.folio_atencion, referencia_id=f4.id, respuestas_json={"diagnostico": "Lámpara de emergencia instalada y probada.", "resuelto": True},
                             respondido_por=tecnico4.id, contexto_json={"sistema": {}, "sellos": {}})
    db.add(ra)
    await db.flush()
    db.add(FormularioEvidencia(respuesta_id=ra.id, tenant_id=tenant.id, prestador_id=prestador.id, campo_clave="firma", tipo=TipoEvidencia.firma, archivo_key=f"demo/{ra.id}/firma.png",
                               nombre_original="firma.png", mime="image/png", bytes=1024, ancho_px=400, alto_px=200, hash_sha256="3" * 64))
    await db.flush()
    ra.estado, ra.enviado_at = EstadoRespuesta.enviado, datetime.now(UTC) - timedelta(days=1)
    await db.flush()
    await captura.vincular_atencion(db, a_t4, f4, ra.id, None)
    await folio_estados.transicionar(db, f4, EstadoFolio.cerrado, a_t4, "Instalación concluida; el operador firmó")
    await db.flush()
    _ = (f1, DecisionOCRechazo)
    return True


async def main() -> None:
    from core.db import nueva_sesion

    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        ok = await sembrar_trabajos_especiales(db)
        await db.commit()
    print("Trabajos especiales y OC de activos demo creados." if ok else "Ya existían (o falta el seed base).")


if __name__ == "__main__":
    asyncio.run(main())
