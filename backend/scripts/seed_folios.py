"""Datos demo de P04 (folios): políticas y prefijo, reglas y niveles de aprobación, criticidad de los 12 equipos, palabras
clave de alerta, horario de servicio del contrato y 15 folios en distintos estados. Idempotente: no hace nada si ya hay
folios del tenant demo. Se ejecuta desde seed_dev (o solo: `python -m scripts.seed_folios`)."""
import asyncio
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select

from core.dependencias import Actor
from core.rls import CONTEXTO_SISTEMA
from models.base import Rol, dominio_de_rol
from models.catalogos import Equipo, FamiliaEquipo, TipoEquipo, TipoFalla, TipoFallaSeveridad
from models.contratos import Contrato
from models.folios import (
    AprobacionNivelConfig, AprobacionRegla, CanalAprobacion, ComportamientoTimeout, CriterioAprobacion, EstadoFolio, Folio,
    FolioKeywordAlerta, FolioPoliticasTenant, RazonRechazo,
)
from models.formularios import (
    EstadoRespuesta, Formulario, FormularioEvidencia, FormularioRespuesta, OrigenRespuesta, TipoEvidencia,
)
from models.organizaciones import Prestador, Tenant
from models.unidades import UnidadNegocio
from models.usuarios import Usuario
from schemas.folios import FolioEntrada
from services import aprobacion_service, folio_estados
from services import folios_captura_service as captura

# Criticidad por posición dentro de cada UN (refrigerador B, cámara A, climatización C, iluminación D).
CRITICIDAD_POR_POSICION = ["B", "A", "C", "D"]
KEYWORDS = ["incendio", "humo", "chispas", "fuga de gas"]
HORARIO_DEMO = {"lunes": [["08:00", "20:00"]], "martes": [["08:00", "20:00"]], "miercoles": [["08:00", "20:00"]],
                "jueves": [["08:00", "20:00"]], "viernes": [["08:00", "20:00"]], "sabado": [["09:00", "14:00"]]}
HABILIDAD_POR_FAMILIA = {"Refrigeración": "refrigeracion", "Climatización": "hvac", "Iluminación": "iluminacion"}
# Lunes 2026-10-26 10:00 CDMX (dentro de horario) y domingo 2026-10-25 03:00 CDMX (fuera).
EN_HORARIO = datetime(2026, 10, 26, 16, 0, tzinfo=UTC)
FUERA_HORARIO = datetime(2026, 10, 25, 9, 0, tzinfo=UTC)


def actor_de(u: Usuario) -> Actor:
    return Actor(id=u.id, email=u.email, nombre=u.nombre, rol=u.rol, dominio=dominio_de_rol(u.rol), tenant_id=u.tenant_id,
                 prestador_id=u.prestador_id, sesion_id=None)


async def sembrar_folios(db) -> bool:
    prestador = (await db.execute(select(Prestador).where(Prestador.rfc == "PDE200101AB1"))).scalar_one_or_none()
    tenant = (await db.execute(select(Tenant).where(Tenant.rfc == "CDE200101XY2"))).scalar_one_or_none()
    if prestador is None or tenant is None:
        return False
    if (await db.execute(select(Folio.id).where(Folio.tenant_id == tenant.id))).first():
        return False

    usuarios = {u.email: u for u in (await db.execute(select(Usuario))).scalars()}
    operador, admin_un, admin_empresa = usuarios["operador@acma.dev"], usuarios["admin.un@acma.dev"], usuarios["admin.empresa@acma.dev"]
    supervisor, despachador, mesa = usuarios["supervisor.operadores@acma.dev"], usuarios["despachador@acma.dev"], usuarios["mesa.control@acma.dev"]
    tecnico1, tecnico2, tecnico4 = usuarios["tecnico1@acma.dev"], usuarios["tecnico2@acma.dev"], usuarios["tecnico4@acma.dev"]
    unidades = list((await db.execute(select(UnidadNegocio).where(UnidadNegocio.tenant_id == tenant.id).order_by(UnidadNegocio.codigo))).scalars())
    equipos = {e.codigo: e for e in (await db.execute(select(Equipo).where(Equipo.tenant_id == tenant.id))).scalars()}
    familias = {f.nombre: f for f in (await db.execute(select(FamiliaEquipo))).scalars()}
    tipos = {t.id: t for t in (await db.execute(select(TipoEquipo))).scalars()}
    fallas = {}
    for tf in (await db.execute(select(TipoFalla).where(TipoFalla.prestador_id == prestador.id))).scalars():
        familia = next(f for f in familias.values() if f.id == tf.familia_equipo_id)
        fallas[(familia.nombre, tf.descripcion)] = tf

    # ------------------------------------------------------- configuración
    db.add(FolioPoliticasTenant(tenant_id=tenant.id, bloqueo_total_duplicados=False, revision_obligatoria_garantia=True,
                                autorizacion_automatica_criticos=False, aprobacion_secuencial=False, prefijo_folio="CD"))
    db.add_all([
        AprobacionRegla(tenant_id=tenant.id, nivel=1, criterio=CriterioAprobacion.monto, operador="<", valor_json={"monto": 5000}),
        AprobacionRegla(tenant_id=tenant.id, nivel=2, criterio=CriterioAprobacion.monto, operador="entre", valor_json={"min": 5000, "max": 20000}),
        AprobacionRegla(tenant_id=tenant.id, nivel=3, criterio=CriterioAprobacion.monto, operador=">=", valor_json={"monto": 20000}),
        AprobacionRegla(tenant_id=tenant.id, nivel=2, criterio=CriterioAprobacion.criticidad, operador="en", valor_json={"valores": ["A", "B"]}),
        AprobacionRegla(tenant_id=tenant.id, nivel=1, criterio=CriterioAprobacion.tipo_trabajo, operador="igual", valor_json={"tipo": "preventivo"}),
        AprobacionRegla(tenant_id=tenant.id, nivel=2, criterio=CriterioAprobacion.tipo_trabajo, operador="igual", valor_json={"tipo": "especial"}),
        AprobacionNivelConfig(tenant_id=tenant.id, nivel=1, rol_aprobador=Rol.admin_un, tiempo_limite_horas=4,
                              comportamiento_timeout=ComportamientoTimeout.escalar),
        AprobacionNivelConfig(tenant_id=tenant.id, nivel=2, rol_aprobador=Rol.supervisor_operadores, tiempo_limite_horas=12,
                              comportamiento_timeout=ComportamientoTimeout.depende_criticidad),
        AprobacionNivelConfig(tenant_id=tenant.id, nivel=3, rol_aprobador=Rol.admin_empresa, tiempo_limite_horas=24,
                              comportamiento_timeout=ComportamientoTimeout.bloquear_alertar),
    ])
    for palabra in KEYWORDS:
        db.add(FolioKeywordAlerta(prestador_id=prestador.id, tenant_id=None, palabra=palabra))
    for nombre, clave in HABILIDAD_POR_FAMILIA.items():
        if nombre in familias:
            familias[nombre].habilidad_clave = clave
    for i, codigo in enumerate(sorted(equipos)):
        equipos[codigo].criticidad = CRITICIDAD_POR_POSICION[i % 4]
    contrato = (await db.execute(select(Contrato).where(Contrato.tenant_id == tenant.id, Contrato.nombre == "Contrato de mantenimiento 2026"))).scalar_one()
    contrato.horario_servicio_json = HORARIO_DEMO
    fallas[("Iluminación", "Parpadea")].requiere_revision_manual = True  # flag global (rol sistema en el seed)
    await db.flush()

    # ------------------------------------------------------------ folios
    async def nuevo(actor_u, codigo, falla, descripcion, *, ahora=EN_HORARIO, confirmacion=True, tipo="correctivo", monto=None,
                    justificacion=None) -> Folio:
        e = equipos[codigo]
        familia = next(f for f in familias.values() if f.id == tipos[e.tipo_equipo_id].familia_id)
        un = next(u for u in unidades if u.id == e.un_id)
        datos = FolioEntrada(un_id=un.id, equipo_id=e.id, tipo_falla_id=fallas[(familia.nombre, falla)].id, descripcion=descripcion,
                             tipo_folio=tipo, confirmacion_un=confirmacion, confirmacion_un_geolat=19.4326, confirmacion_un_geolng=-99.1332,
                             geolat_captura=19.4326, geolng_captura=-99.1332, monto_estimado=monto, folio_duplicado_justificacion=justificacion)
        return await captura.crear(db, actor_de(actor_u), datos, None, ahora)

    async def aprobar(folio, aprobador):
        await aprobacion_service.aprobar(db, actor_de(aprobador), folio, CanalAprobacion.app, "Aprobado (demo)", None)

    async def asignar(folio, tecnico):
        await captura.asignar(db, actor_de(despachador), folio, tecnico.id, None, "", None)

    async def ejecutar(folio, tecnico):
        await asignar(folio, tecnico)
        await folio_estados.transicionar(db, folio, EstadoFolio.en_camino, actor_de(tecnico), "Salgo hacia la UN")
        await folio_estados.transicionar(db, folio, EstadoFolio.en_ejecucion, actor_de(tecnico), "Llegué a la UN", {"geolat": 19.4326, "geolng": -99.1332})

    # A. Cerrado (EQ-0001, criticidad B → Nivel 2 → aprueba el supervisor → técnico 1 cierra con atención y firma).
    f_cerrado = await nuevo(operador, "EQ-0001", "No enfría", "El refrigerador no mantiene la temperatura; producto en riesgo.", ahora=datetime(2026, 10, 19, 15, 0, tzinfo=UTC))
    await aprobar(f_cerrado, supervisor)
    await ejecutar(f_cerrado, tecnico1)
    atencion_form = (await db.execute(select(Formulario).where(Formulario.nombre == "Cierre de correctivo · Cliente Demo"))).scalar_one()
    r = FormularioRespuesta(formulario_id=atencion_form.id, version_id=atencion_form.version_publicada_id, tenant_id=tenant.id, prestador_id=prestador.id,
                            un_id=f_cerrado.un_id, equipo_id=f_cerrado.equipo_id, origen=OrigenRespuesta.folio_atencion, referencia_id=f_cerrado.id,
                            respuestas_json={"diagnostico": "Compresor con fuga de refrigerante; se recargó y selló.", "resuelto": True},
                            respondido_por=tecnico1.id, contexto_json={"sistema": {}, "sellos": {}})
    db.add(r)
    await db.flush()
    db.add(FormularioEvidencia(respuesta_id=r.id, tenant_id=tenant.id, prestador_id=prestador.id, campo_clave="firma", tipo=TipoEvidencia.firma,
                               archivo_key=f"demo/{r.id}/firma.png", nombre_original="firma.png", mime="image/png", bytes=1024, ancho_px=400, alto_px=200,
                               hash_sha256="0" * 64))
    await db.flush()
    r.estado, r.enviado_at = EstadoRespuesta.enviado, datetime(2026, 10, 19, 18, 0, tzinfo=UTC)
    await db.flush()
    await captura.vincular_atencion(db, actor_de(tecnico1), f_cerrado, r.id, None)
    await folio_estados.transicionar(db, f_cerrado, EstadoFolio.cerrado, actor_de(tecnico1), "Servicio concluido; el operador firmó")

    # B. Cancelado por rechazo en aprobación (EQ-0005, B → Nivel 2; el supervisor rechaza por presupuesto).
    f_rechazado = await nuevo(admin_un, "EQ-0005", "Ruido inusual", "Ruido metálico intermitente en el refrigerador de Polanco.", ahora=datetime(2026, 10, 20, 16, 0, tzinfo=UTC))
    await aprobacion_service.rechazar(db, actor_de(supervisor), f_rechazado, CanalAprobacion.minuta, RazonRechazo.por_presupuesto,
                                      "Sin presupuesto este mes; se difiere", None)

    # 1. Capturado en espera (sin confirmación de UN).
    await nuevo(operador, "EQ-0001", "No enfría", "Vuelve a fallar el refrigerador; no confirmé la unidad.", confirmacion=False)
    # 2. En revisión: sin contrato.
    await nuevo(admin_un, "EQ-0002", "No enciende", "La cámara de congelación no enciende desde la madrugada.")
    # 3. En revisión: garantía (equipo 9 en garantía y revisión obligatoria).
    await nuevo(admin_empresa, "EQ-0009", "Ruido inusual", "Zumbido fuerte en el refrigerador en garantía.")
    # 4. En revisión: flag global del tipo de falla («Parpadea»).
    f_flag = await nuevo(operador, "EQ-0004", "Parpadea", "La lámpara del pasillo parpadea de forma constante.")
    # 5. En revisión: fuera del horario de servicio (domingo de madrugada).
    await nuevo(admin_un, "EQ-0007", "Gotea agua", "El minisplit gotea sobre la caja registradora.", ahora=FUERA_HORARIO)
    # 6. En revisión: palabra clave de alerta.
    await nuevo(operador, "EQ-0003", "No enfría", "No enfría y sale humo del compresor del minisplit.")
    # 7. En revisión: severidad no configurada (se retira temporalmente la celda de la matriz).
    e11 = equipos["EQ-0011"]
    celda = (await db.execute(select(TipoFallaSeveridad).where(
        TipoFallaSeveridad.tenant_id == tenant.id, TipoFallaSeveridad.tipo_falla_id == fallas[("Climatización", "No enciende")].id,
        TipoFallaSeveridad.tipo_equipo_id == e11.tipo_equipo_id))).scalar_one()
    respaldo = {"nivel_severidad_id": celda.nivel_severidad_id, "configurado_por": celda.configurado_por}
    await db.delete(celda)
    await db.flush()
    await nuevo(admin_empresa, "EQ-0011", "No enciende", "El minisplit de Coyoacán no enciende.")
    db.add(TipoFallaSeveridad(tenant_id=tenant.id, tipo_falla_id=fallas[("Climatización", "No enciende")].id, tipo_equipo_id=e11.tipo_equipo_id, **respaldo))
    await db.flush()
    # 8. Flujo en Nivel 2 (activo A).
    await nuevo(admin_empresa, "EQ-0010", "No enfría", "La cámara de congelación de Coyoacán pierde frío.", monto=None)
    # 9. Flujo en Nivel 1 (activo D, monto bajo fijado por mesa de control).
    f_n1 = await nuevo(admin_un, "EQ-0008", "No enciende", "Anuncio luminoso apagado.")
    await captura.fijar_monto(db, actor_de(mesa), f_n1, Decimal("1200"), None)
    # 10. Pendiente de información (flag «Parpadea» → el despachador pide más datos).
    f_pi = await nuevo(admin_empresa, "EQ-0012", "Parpadea", "La lámpara del almacén parpadea por las noches.")
    await folio_estados.transicionar(db, f_pi, EstadoFolio.pendiente_informacion, actor_de(despachador), "¿Parpadea todo el día o solo al encender?")
    # 11. Autorizado (EQ-0005 libre tras el rechazo; B → Nivel 2 aprobado).
    f_aut = await nuevo(admin_un, "EQ-0005", "No enfría", "Refrigerador de Polanco a 12 °C.")
    await aprobar(f_aut, supervisor)
    # 12. Asignado (duplicado con justificación sobre EQ-0004; D → Nivel 1 aprobado por Admin UN; técnico 4 iluminación).
    f_asig = await nuevo(admin_un, "EQ-0004", "No enciende", "Ahora la lámpara no enciende en absoluto.",
                         justificacion="Es una falla diferente: antes parpadeaba, ahora no enciende")
    await aprobar(f_asig, admin_un)
    await asignar(f_asig, tecnico4)
    # 13. En ejecución (duplicado con justificación sobre EQ-0003; C → Nivel 1; técnico 2 HVAC).
    f_ejec = await nuevo(admin_un, "EQ-0003", "No enciende", "Después de la falla anterior, el minisplit ya no enciende.",
                         justificacion="Falla distinta: el equipo quedó sin encender")
    await aprobar(f_ejec, admin_un)
    await ejecutar(f_ejec, tecnico2)
    await db.flush()
    _ = f_flag
    return True


async def main() -> None:
    from core.db import nueva_sesion

    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        creado = await sembrar_folios(db)
        await db.commit()
    print("Folios demo creados." if creado else "Ya había folios demo; no se modificó nada.")


if __name__ == "__main__":
    asyncio.run(main())
