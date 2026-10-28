"""Datos demo de P06: formulario preventivo del prestador, 3 planes con triggers de Fase 1, 6 equipos con plan, calendario
con 8 preventivos (2 ejecutados con desvío ±, 1 reprogramado + su nueva fecha, 1 cancelado, 3 programados), noviembre
publicado, el catálogo de 7 razones de reasignación y 3 reasignaciones forzadas. Idempotente: no hace nada si ya hay planes
del prestador demo. Se ejecuta desde seed_dev (o solo: `python -m scripts.seed_preventivos`)."""
import asyncio
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select

from core.rls import CONTEXTO_SISTEMA
from models.catalogos import Equipo, Habilidad, TipoEquipo
from models.folios import CanalAprobacion, EstadoFolio, Folio
from models.formularios import (
    EstadoRespuesta, Formulario, FormularioAsignacion, FormularioEvidencia, FormularioRespuesta, OrigenRespuesta, TipoEvidencia,
)
from models.organizaciones import Prestador, Tenant
from models.preventivos import PlanMantenimiento, RazonReasignacion, TipoAutorizacionPreventivo
from models.unidades import UnidadNegocio
from models.usuarios import Usuario
from scripts.plantillas_formularios import INSPECCION_PREVENTIVA
from scripts.seed_folios import actor_de
from services import chat_service, folio_estados, planes_service, preventivos_service, reasignacion_service  # noqa: F401 — registran ganchos
from services import folios_captura_service as captura

PLANES: list[dict[str, Any]] = [
    {"nombre": "Mantenimiento trimestral de refrigeradores", "tipo_equipo": "Refrigerador vertical", "tiempo_ventana_dias": 7,
     "descripcion": "Limpieza de condensador, revisión de empaques y medición de temperatura cada 3 meses.",
     "triggers": [{"tipo_trigger": "tiempo_fijo", "parametros_json": {"cada": 3, "unidad": "meses"}}],
     "tareas": [("Limpieza de condensador y serpentín", 30, "refrigeracion"), ("Revisión de empaques de puerta", 10, None),
                ("Medición de temperatura interna y ciclo del compresor", 15, "refrigeracion"), ("Revisión de conexiones eléctricas", 10, "electricidad")],
     "materiales": [("Limpiador de serpentín", "1", "litro"), ("Refrigerante R-134a", "0.50", "kg"), ("Empaque de puerta", "1", "pieza")],
     "equipos": [("EQ-0001", date(2026, 7, 5)), ("EQ-0005", date(2026, 7, 12)), ("EQ-0009", date(2026, 8, 18))]},
    {"nombre": "Limpieza semestral de minisplits", "tipo_equipo": "Minisplit", "tiempo_ventana_dias": 10,
     "descripcion": "Lavado de filtros y evaporador, revisión de drenaje y carga de gas cada 180 días.",
     "triggers": [{"tipo_trigger": "tiempo_fijo", "parametros_json": {"cada_dias": 180}}],
     "tareas": [("Lavado de filtros y evaporador", 40, "hvac"), ("Revisión de drenaje y charola", 10, None), ("Verificación de presión de gas", 15, "hvac")],
     "materiales": [("Espuma limpiadora de evaporador", "1", "lata"), ("Filtro de aire", "2", "pieza")],
     "equipos": [("EQ-0003", date(2026, 4, 23)), ("EQ-0007", date(2026, 4, 25))]},
    {"nombre": "Revisión anual de iluminación", "tipo_equipo": "Lámpara LED de techo", "tiempo_ventana_dias": 15,
     "descripcion": "Cada 15 de enero: prueba de luminarias, balastros y tableros.",
     "triggers": [{"tipo_trigger": "calendario", "parametros_json": {"mes": 1, "dia": 15}}],
     "tareas": [("Prueba de encendido de todas las luminarias", 20, "iluminacion"), ("Revisión de tablero y protecciones", 15, "electricidad")],
     "materiales": [("Tubo LED 18 W", "2", "pieza")],
     "equipos": [("EQ-0004", date(2026, 1, 15))]},
]


async def sembrar_preventivos(db) -> bool:
    prestador = (await db.execute(select(Prestador).where(Prestador.rfc == "PDE200101AB1"))).scalar_one_or_none()
    tenant = (await db.execute(select(Tenant).where(Tenant.rfc == "CDE200101XY2"))).scalar_one_or_none()
    if prestador is None or tenant is None:
        return False
    if (await db.execute(select(PlanMantenimiento.id).where(PlanMantenimiento.prestador_id == prestador.id))).first():
        return False
    from scripts.seed_dev import _formulario

    usuarios = {u.email: u for u in (await db.execute(select(Usuario))).scalars()}
    admin_prestador, despachador, admin_un = usuarios["admin.prestador@acma.dev"], usuarios["despachador@acma.dev"], usuarios["admin.un@acma.dev"]
    tecnico1, tecnico2, tecnico4 = usuarios["tecnico1@acma.dev"], usuarios["tecnico2@acma.dev"], usuarios["tecnico4@acma.dev"]
    habilidades = {h.clave: h.id for h in (await db.execute(select(Habilidad).where(Habilidad.prestador_id == prestador.id))).scalars()}
    tipos = {t.nombre: t for t in (await db.execute(select(TipoEquipo).where(TipoEquipo.tenant_id.is_(None)))).scalars()}
    equipos = {e.codigo: e for e in (await db.execute(select(Equipo).where(Equipo.tenant_id == tenant.id))).scalars()}
    unidades = {u.codigo: u for u in (await db.execute(select(UnidadNegocio).where(UnidadNegocio.tenant_id == tenant.id))).scalars()}

    # Razones (§6.8.2) — las crea la migración para prestadores existentes y `crear prestador` para los nuevos; aquí por si faltan.
    if not (await db.execute(select(RazonReasignacion.id).where(RazonReasignacion.prestador_id == prestador.id))).first():
        await reasignacion_service.sembrar_razones(db, prestador.id)
    razones = {r.descripcion: r for r in (await db.execute(select(RazonReasignacion).where(RazonReasignacion.prestador_id == prestador.id))).scalars()}

    # Formulario preventivo del prestador (clon de la plantilla) asignado a los folios preventivos.
    plantilla = (await db.execute(select(Formulario).where(Formulario.nombre == "Inspección preventiva", Formulario.es_plantilla_base.is_(True)))).scalar_one()
    form_prev = await _formulario(db, prestador_id=prestador.id, tenant_id=None, nombre="Inspección preventiva · Prestador Demo", tipo="preventivo",
                                  roles=["tecnico"], esquema=INSPECCION_PREVENTIVA, descripcion="Lista de verificación del preventivo (clon de la plantilla)",
                                  publicado_por=admin_prestador.id, clonado_de=plantilla.id)
    db.add(FormularioAsignacion(formulario_id=form_prev.id, prestador_id=prestador.id, tenant_id=None, tipo_folio="preventivo", prioridad=5))
    await db.flush()

    # Planes con triggers de Fase 1, tareas (con habilidad requerida) y materiales; equipos con fecha base.
    actor_ap = actor_de(admin_prestador)
    planes = {}
    for p in PLANES:
        datos = {"nombre": p["nombre"], "descripcion": p["descripcion"], "tipo_equipo_id": tipos[p["tipo_equipo"]].id, "tenant_id": None, "estado": "activo",
                 "tiempo_ventana_dias": p["tiempo_ventana_dias"], "formulario_id": form_prev.id, "nivel_severidad_id": None,
                 "triggers": [{**t, "logica_combinacion": None} for t in p["triggers"]],
                 "tareas": [{"orden": i + 1, "descripcion": d, "tiempo_estimado_min": m, "habilidad_requerida_id": habilidades[h] if h else None}
                            for i, (d, m, h) in enumerate(p["tareas"])],
                 "materiales": [{"descripcion": d, "cantidad_estandar": c, "unidad": u, "articulo_id": None} for d, c, u in p["materiales"]]}
        plan = await planes_service.crear(db, actor_ap, datos, None, prestador.id)
        planes[p["nombre"]] = plan
        for codigo, fecha_base in p["equipos"]:
            await planes_service.asignar_equipo(db, actor_ap, plan, equipos[codigo].id, fecha_base, None)
    await db.flush()

    # Generación "nocturna" simulada: 5 de octubre (EQ-0001 el 05 y EQ-0005 el 12) y 20 de octubre (EQ-0003 el 20 y EQ-0007 el 22).
    await preventivos_service.generar_programados(db, date(2026, 10, 5))
    await preventivos_service.generar_programados(db, date(2026, 10, 20))
    folios = {f.equipo_id: f for f in (await db.execute(select(Folio).where(Folio.tenant_id == tenant.id, Folio.plan_id.is_not(None)))).scalars()}
    f1, f5, f3, f7 = (folios[equipos[c].id] for c in ("EQ-0001", "EQ-0005", "EQ-0003", "EQ-0007"))
    actor_des = actor_de(despachador)

    async def asignar(folio, tecnico):
        await captura.asignar(db, actor_des, folio, tecnico.id, None, "", None)

    async def ejecutar_y_cerrar(folio, tecnico, cierre: datetime, respuestas: dict):
        act = actor_de(tecnico)
        await folio_estados.transicionar(db, folio, EstadoFolio.en_camino, act, "Salgo al preventivo")
        await folio_estados.transicionar(db, folio, EstadoFolio.en_ejecucion, act, "Llegué a la UN", {"geolat": 19.4326, "geolng": -99.1332})
        r = FormularioRespuesta(formulario_id=form_prev.id, version_id=form_prev.version_publicada_id, tenant_id=tenant.id, prestador_id=prestador.id,
                                un_id=folio.un_id, equipo_id=folio.equipo_id, origen=OrigenRespuesta.folio_atencion, referencia_id=folio.id,
                                respuestas_json=respuestas, respondido_por=tecnico.id, contexto_json={"sistema": {}, "sellos": {}})
        db.add(r)
        await db.flush()
        db.add(FormularioEvidencia(respuesta_id=r.id, tenant_id=tenant.id, prestador_id=prestador.id, campo_clave="firma", tipo=TipoEvidencia.firma,
                                   archivo_key=f"demo/{r.id}/firma.png", nombre_original="firma.png", mime="image/png", bytes=1024, ancho_px=400, alto_px=200,
                                   hash_sha256="0" * 64))
        await db.flush()
        r.estado, r.enviado_at = EstadoRespuesta.enviado, cierre
        await db.flush()
        await captura.vincular_atencion(db, act, folio, r.id, None)
        await folio_estados.transicionar(db, folio, EstadoFolio.cerrado, act, "Preventivo concluido; el operador firmó", momento=cierre)

    # a) EQ-0001: ejecutado 2 días después (técnico 1).
    await asignar(f1, tecnico1)
    await ejecutar_y_cerrar(f1, tecnico1, datetime(2026, 10, 7, 17, 30, tzinfo=UTC), {"estado_general": "bueno", "observaciones": "Condensador limpio; empaques en buen estado."})
    # b) EQ-0005: asignado al técnico 1, reasignado sin habilidad por el Admin prestador al técnico 2 (incidencia), ejecutado 3 días antes.
    await asignar(f5, tecnico1)
    await reasignacion_service.reasignar(db, actor_ap, f5, tecnico2.id, razones["Incidencia del técnico"].id, "Tomás tuvo una descompostura del vehículo",
                                         True, "Único técnico disponible en la zona; supervisado por teléfono", None)
    await ejecutar_y_cerrar(f5, tecnico2, datetime(2026, 10, 9, 12, 0, tzinfo=UTC), {"estado_general": "regular", "observaciones": "Se recargó refrigerante."})
    # c) EQ-0003: asignado al técnico 2, reasignado al técnico 4 (optimización de ruta) y reprogramado al 3 de noviembre con autorización del Admin UN.
    await asignar(f3, tecnico2)
    await reasignacion_service.reasignar(db, actor_des, f3, tecnico4.id, razones["Optimización de ruta"].id, "Tania ya estará en la sucursal ese día", True, None, None)
    a = await preventivos_service.solicitar(db, actor_des, f3, TipoAutorizacionPreventivo.reprogramacion, "La sucursal tendrá inventario el 20; piden moverlo",
                                            date(2026, 11, 3), None)
    await preventivos_service.resolver(db, actor_de(admin_un), a, True, "De acuerdo, el 3 de noviembre", CanalAprobacion.app, None)
    # d) EQ-0007: asignado al técnico 4, reasignado al técnico 2 (prioridad de cliente) y cancelado con autorización.
    await asignar(f7, tecnico4)
    await reasignacion_service.reasignar(db, actor_des, f7, tecnico2.id, razones["Prioridad de cliente"].id, "Tania atiende un crítico en Polanco", True, None, None)
    a = await preventivos_service.solicitar(db, actor_des, f7, TipoAutorizacionPreventivo.cancelacion, "El minisplit se reemplazará en noviembre", None, None)
    await preventivos_service.resolver(db, actor_de(admin_un), a, True, "Confirmado por la sucursal", CanalAprobacion.app, None)

    # Calendario manual de noviembre: UN completa sin equipo, dos equipos con plan; y el mes publicado.
    await preventivos_service.crear_calendario(db, actor_des, [
        {"un_id": unidades["SUC-002"].id, "equipo_id": None, "plan_id": None, "tecnico_id": tecnico2.id, "fecha_programada": date(2026, 11, 10),
         "descripcion": "Revisión general de la sucursal (preventivo de UN)"},
        {"un_id": equipos["EQ-0009"].un_id, "equipo_id": equipos["EQ-0009"].id, "plan_id": planes["Mantenimiento trimestral de refrigeradores"].id,
         "tecnico_id": tecnico1.id, "fecha_programada": date(2026, 11, 18), "descripcion": ""},
        {"un_id": equipos["EQ-0011"].un_id, "equipo_id": equipos["EQ-0011"].id, "plan_id": planes["Limpieza semestral de minisplits"].id,
         "tecnico_id": None, "fecha_programada": date(2026, 11, 25), "descripcion": "Limpieza de filtros antes de temporada"},
    ], tenant.id, None)
    await preventivos_service.publicar_mes(db, actor_des, "2026-11", tenant.id, None)
    await db.flush()
    return True


async def main() -> None:
    from core.db import nueva_sesion

    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        ok = await sembrar_preventivos(db)
        await db.commit()
    print("Preventivos demo creados." if ok else "Los preventivos demo ya existían o faltan los datos base.")


if __name__ == "__main__":
    asyncio.run(main())
