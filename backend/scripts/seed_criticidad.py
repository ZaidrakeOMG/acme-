"""Datos demo de F2-05: configuración con los pesos literales de §6.9.3, un historial de fallas corto para tres
equipos (sin él no hay criticidad A que salga del cálculo ni modos de falla que sugerir), las evaluaciones de los
doce equipos demo con los cuatro niveles representados, diez modos de falla (seis sugeridos desde el historial y
cuatro a mano) y seis acciones de mitigación en distintos estados: una vencida y una implementada hace más de cuatro
meses, con efectividad ya medible.

**Por qué el seed crea folios:** la criticidad es `probabilidad × impacto`, y la probabilidad sale del historial. Un
equipo que no ha fallado nunca **no** puede dar nivel A por más impacto que tenga, que es justo lo que ISO 55000
quiere decir. Así que para que la demo muestre un A calculado (y no uno puesto a mano) hace falta que ese equipo
tenga fallas de verdad en los últimos doce meses. Son folios cerrados escritos directo, con el prefijo `CR-`, como
los del histórico sintético de P10: no pasan por la máquina de estados porque no interesan sus chats ni su SLA, solo
su fecha y su tipo de falla.

Idempotente: no hace nada si ya existe la configuración de criticidad del cliente demo. Se ejecuta desde seed_dev
(o solo: `python -m scripts.seed_criticidad`).
"""
import asyncio
import random
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select

from core.rls import CONTEXTO_SISTEMA
from models.catalogos import Equipo, NivelSeveridadCatalogo, TipoEquipo, TipoFalla
from models.criticidad import (
    ActivoRiesgoMitigacion, CriticidadConfiguracion, EstadoMitigacion, MotivoEvaluacion, OrigenModoFalla,
    TipoMitigacion,
)
from models.folios import EstadoFolio, Folio, SeveridadOrigen, TipoFolio
from models.formularios import (
    CatalogoPersonalizado, CatalogoPersonalizadoOpcion, EstadoRespuesta, Formulario, FormularioRespuesta,
    OrigenRespuesta,
)
from models.organizaciones import Prestador, Tenant
from models.preventivos import PlanMantenimiento
from models.usuarios import Usuario
from scripts.seed_folios import actor_de
from services import criticidad_service, riesgo_service

PREFIJO = "CR-"

# Historial de fallas por equipo: (codigo, probabilidad a la que debe llegar, tipos de falla que se repiten).
# El seed **completa** el historial hasta el minimo de la banda de `ESCALA_PROBABILIDAD_DEFAULT` (1-2 = 2,
# 3-5 = 3, 6-11 = 4, 12+ = 5) contando los correctivos cerrados que el equipo ya tenga de los otros seeds: asi la
# probabilidad de la demo no depende de cuantos folios haya dejado antes el seed base. Ningun equipo apunta a la
# banda 1 (cero fallas) justamente porque el seed puede agregar fallas, no quitarlas.
HISTORIAL = [
    ("EQ-0001", 5, ["No enciende", "No enfría"]),
    ("EQ-0002", 5, ["No enfría", "Ruido inusual"]),
    ("EQ-0005", 4, ["No enfría", "Gotea agua"]),
    ("EQ-0003", 3, ["No enciende", "Ruido inusual"]),
    ("EQ-0006", 3, ["No enfría"]),
    ("EQ-0004", 2, ["No enciende"]),
    ("EQ-0007", 2, ["No enciende"]),
    ("EQ-0008", 2, ["No enciende"]),
    ("EQ-0009", 2, ["No enciende"]),
    ("EQ-0010", 2, ["No enciende"]),
    ("EQ-0011", 2, ["No enciende"]),
    ("EQ-0012", 2, ["No enciende"]),
]

# Minimo de fallas en 12 meses de cada banda de probabilidad (la misma escala literal de §6.9.3).
MINIMO_POR_PROBABILIDAD = {1: 0, 2: 1, 3: 3, 4: 6, 5: 12}

# Los tres equipos de los que sale el FMEA sugerido (dos modos por equipo: seis en total).
CON_FMEA_SUGERIDO = ["EQ-0001", "EQ-0002", "EQ-0005"]

# Dimensiones por equipo (§6.9.3, escala 1-5). El indice es `probabilidad x impacto / 25 x 100`, asi que con la
# probabilidad del historial de arriba salen los cuatro niveles: A 86.00 (EQ-0001) y 93.00 (EQ-0002), B 51.60 y
# 58.40, C 26.40 / 27.60 / 21.20 / 21.20, D 14.00 / 11.20 / 8.80 / 8.00. Los dos criticos son EQ-0001 (con plan)
# y EQ-0002 (sin plan, el caso que la alerta ACTIVO_CRITICO_SIN_PLAN debe cazar).
EVALUACIONES: list[dict[str, Any]] = [
    {"codigo": "EQ-0001", "operacional": 5, "seguridad": 4, "economico": 4, "imagen": 4,
     "nota": "Refrigerador vertical de exhibicion: si se detiene se pierde el producto y lo ve el cliente"},
    {"codigo": "EQ-0002", "operacional": 5, "seguridad": 5, "economico": 4, "imagen": 4,
     "nota": "Camara de congelacion sin plan de mantenimiento: el caso que la alerta debe cazar"},
    {"codigo": "EQ-0003", "operacional": 5, "seguridad": 4, "economico": 4, "imagen": 4},
    {"codigo": "EQ-0004", "operacional": 4, "seguridad": 3, "economico": 3, "imagen": 3},
    {"codigo": "EQ-0005", "operacional": 4, "seguridad": 4, "economico": 3, "imagen": 3},
    {"codigo": "EQ-0006", "operacional": 3, "seguridad": 2, "economico": 2, "imagen": 2},
    {"codigo": "EQ-0007", "operacional": 3, "seguridad": 3, "economico": 2, "imagen": 2},
    {"codigo": "EQ-0008", "operacional": 3, "seguridad": 3, "economico": 2, "imagen": 2},
    {"codigo": "EQ-0009", "operacional": 2, "seguridad": 2, "economico": 1, "imagen": 2},
    {"codigo": "EQ-0010", "operacional": 2, "seguridad": 1, "economico": 1, "imagen": 2},
    {"codigo": "EQ-0011", "operacional": 1, "seguridad": 1, "economico": 1, "imagen": 2},
    {"codigo": "EQ-0012", "operacional": 1, "seguridad": 1, "economico": 1, "imagen": 1},
]

# Modos de falla a mano (los otros seis salen del historial con `riesgo_service.sugerir`).
MODOS_MANUALES = [
    {"codigo": "EQ-0001", "descripcion_falla": "Pérdida de carga de refrigerante por fuga en el serpentín",
     "causa_probable": "Corrosión por condensados en el serpentín del evaporador",
     "efecto_operacional": "La cámara no sostiene la temperatura y el producto se pierde en pocas horas",
     "severidad": 5, "frecuencia_historica": 3, "deteccion": 4},
    {"codigo": "EQ-0002", "descripcion_falla": "Falla del motor del ventilador del condensador",
     "causa_probable": "Rodamientos sin lubricación y acumulación de polvo",
     "efecto_operacional": "El equipo trabaja sobrecargado hasta que el compresor corta por alta presión",
     "severidad": 4, "frecuencia_historica": 3, "deteccion": 3},
    {"codigo": "EQ-0005", "descripcion_falla": "Empaque de puerta vencido",
     "causa_probable": "Uso continuo y limpieza con químicos agresivos",
     "efecto_operacional": "Entra aire caliente, sube el consumo y se forma hielo",
     "severidad": 3, "frecuencia_historica": 2, "deteccion": 2},
    # Genérico del tipo de equipo: aplica a todos los minisplits del cliente sin repetir el análisis.
    {"tipo_equipo": "Minisplit", "descripcion_falla": "Drenaje tapado por biopelícula",
     "causa_probable": "Falta de limpieza de la charola y del drenaje en temporada de lluvias",
     "efecto_operacional": "El agua escurre al interior del local y moja instalaciones",
     "severidad": 3, "frecuencia_historica": 3, "deteccion": 2},
]


async def sembrar_criticidad(db) -> bool:
    prestador = (await db.execute(select(Prestador).where(Prestador.rfc == "PDE200101AB1"))).scalar_one_or_none()
    tenant = (await db.execute(select(Tenant).where(Tenant.rfc == "CDE200101XY2"))).scalar_one_or_none()
    if prestador is None or tenant is None:
        return False
    if (await db.execute(select(CriticidadConfiguracion.id).where(
            CriticidadConfiguracion.tenant_id == tenant.id))).first():
        return False

    usuarios = {u.email: u for u in (await db.execute(select(Usuario))).scalars()}
    admin_empresa, admin_prestador = usuarios["admin.empresa@acma.dev"], usuarios["admin.prestador@acma.dev"]
    actor_ae, actor_ap = actor_de(admin_empresa), actor_de(admin_prestador)
    equipos = {e.codigo: e for e in (await db.execute(select(Equipo).where(Equipo.tenant_id == tenant.id))).scalars()}
    tipos_equipo = {t.nombre: t for t in (await db.execute(select(TipoEquipo))).scalars()}
    fallas = {f.descripcion: f for f in (await db.execute(
        select(TipoFalla).where(TipoFalla.prestador_id == prestador.id))).scalars()}
    niveles = {n.clave: n for n in (await db.execute(
        select(NivelSeveridadCatalogo).where(NivelSeveridadCatalogo.prestador_id == prestador.id))).scalars()}

    # ------------------------------------------------------------- configuración (los defaults literales de §6.9.3)
    cfg = await criticidad_service.configuracion(db, tenant.id)
    cfg.configurado_por = admin_empresa.id
    await db.flush()

    # ------------------------------------------------------------- historial corto de fallas
    await _sembrar_historial(db, tenant, prestador, equipos, fallas, niveles, usuarios)

    # ------------------------------------------------------------- evaluaciones de los doce equipos
    por_nivel: dict[str, int] = {}
    for ev in EVALUACIONES:
        equipo = equipos.get(ev["codigo"])
        if equipo is None:
            continue
        fila = await criticidad_service.evaluar(
            db, actor_ae, equipo,
            {k: ev[k] for k in ("operacional", "seguridad", "economico", "imagen")},
            motivo=MotivoEvaluacion.evaluacion_inicial,
            razon=ev.get("nota", "Evaluación inicial del parque (demo)"), exigir_rol=False)
        por_nivel[fila.nivel] = por_nivel.get(fila.nivel, 0) + 1
    await db.flush()

    # ------------------------------------------------------------- modos de falla sugeridos desde el historial
    sugeridos = 0
    for codigo in CON_FMEA_SUGERIDO:
        equipo = equipos.get(codigo)
        if equipo is None:
            continue
        propuestas = await riesgo_service.sugerir(db, actor_ap, equipo)
        for p in propuestas[:2]:   # las dos más frecuentes de cada equipo: seis en total
            await riesgo_service.crear_modo(db, actor_ap, {
                "equipo_id": str(equipo.id), "descripcion_falla": p["descripcion_falla"],
                "tipo_falla_id": str(p["tipo_falla_id"]) if p["tipo_falla_id"] else None,
                "causa_probable": p["causa_probable"],
                "efecto_operacional": "Detectado desde el historial de correctivos del equipo",
                "severidad": p["severidad"], "frecuencia_historica": p["frecuencia_historica"],
                "fallas_12m": p["fallas_12m"], "origen": "sugerido"})
            sugeridos += 1

    # ------------------------------------------------------------- modos de falla a mano
    modos_por_descripcion = {}
    for m in MODOS_MANUALES:
        datos = {k: v for k, v in m.items() if k not in ("codigo", "tipo_equipo")}
        if m.get("codigo"):
            equipo = equipos.get(m["codigo"])
            if equipo is None:
                continue
            datos["equipo_id"] = str(equipo.id)
        else:
            tipo = tipos_equipo.get(m["tipo_equipo"])
            if tipo is None:
                continue
            datos.update({"tipo_equipo_id": str(tipo.id), "tenant_id": str(tenant.id)})
        modo = await riesgo_service.crear_modo(db, actor_ap, datos)
        modos_por_descripcion[modo.descripcion_falla] = modo
    await db.flush()

    # ------------------------------------------------------------- seis acciones de mitigación
    hoy = date.today()
    planes = {p.nombre: p for p in (await db.execute(
        select(PlanMantenimiento).where(PlanMantenimiento.prestador_id == prestador.id))).scalars()}
    plan_refri = next((p for n, p in planes.items() if "refrigerador" in n.lower()), None)
    fuga = modos_por_descripcion.get("Pérdida de carga de refrigerante por fuga en el serpentín")
    ventilador = modos_por_descripcion.get("Falla del motor del ventilador del condensador")
    empaque = modos_por_descripcion.get("Empaque de puerta vencido")
    drenaje = modos_por_descripcion.get("Drenaje tapado por biopelícula")

    acciones = []
    if fuga is not None:
        # Implementada hace más de cuatro meses: su efectividad ya se puede medir contra el historial.
        a = await riesgo_service.crear_mitigacion(db, actor_ap, fuga, {
            "accion_mitigacion": "Prueba de hermeticidad trimestral y cambio del tramo corroído del serpentín",
            "tipo": "plan_preventivo" if plan_refri else "otro",
            "plan_mantenimiento_id": str(plan_refri.id) if plan_refri else None,
            "responsable_id": str(admin_prestador.id), "fecha_compromiso": (hoy - timedelta(days=150)).isoformat()})
        await riesgo_service.cambiar_estado(db, actor_ap, a, EstadoMitigacion.implementada,
                                            fecha_implementacion=hoy - timedelta(days=140))
        acciones.append(a)
        # Vencida: pasó su fecha compromiso y sigue propuesta.
        acciones.append(await riesgo_service.crear_mitigacion(db, actor_ap, fuga, {
            "accion_mitigacion": "Instalar detector de fuga de refrigerante con aviso al despachador",
            "tipo": "rediseno", "responsable_id": str(admin_prestador.id),
            "fecha_compromiso": (hoy - timedelta(days=20)).isoformat()}))
    if ventilador is not None:
        en_proceso = await riesgo_service.crear_mitigacion(db, actor_ap, ventilador, {
            "accion_mitigacion": "Mantener en inventario el motor del ventilador del condensador",
            "tipo": "refaccion_en_inventario", "articulo_id": await _articulo_motor(db, prestador),
            "responsable_id": str(admin_prestador.id), "fecha_compromiso": (hoy + timedelta(days=30)).isoformat()})
        await riesgo_service.cambiar_estado(db, actor_ap, en_proceso, EstadoMitigacion.en_proceso)
        acciones.append(en_proceso)
        acciones.append(await riesgo_service.crear_mitigacion(db, actor_ap, ventilador, {
            "accion_mitigacion": "Capacitar al equipo en lubricación de rodamientos de ventilador",
            "tipo": "capacitacion", "curso_id": await _curso(db, prestador),
            "responsable_id": str(admin_prestador.id), "fecha_compromiso": (hoy + timedelta(days=60)).isoformat()}))
    if empaque is not None:
        descartada = await riesgo_service.crear_mitigacion(db, actor_ap, empaque, {
            "accion_mitigacion": "Cambiar el empaque cada seis meses sin importar su estado",
            "tipo": "otro", "responsable_id": str(admin_prestador.id),
            "fecha_compromiso": (hoy - timedelta(days=5)).isoformat()})
        await riesgo_service.cambiar_estado(db, actor_ap, descartada, EstadoMitigacion.descartada,
                                            razon="El empaque dura más de un año: se revisa en el preventivo y se "
                                                  "cambia solo cuando el sello falla")
        acciones.append(descartada)
    if drenaje is not None:
        acciones.append(await riesgo_service.crear_mitigacion(db, actor_ap, drenaje, {
            "accion_mitigacion": "Limpieza de charola y drenaje al inicio de la temporada de lluvias",
            "tipo": "plan_preventivo" if planes else "otro",
            "plan_mantenimiento_id": str(next(iter(planes.values())).id) if planes else None,
            "responsable_id": str(admin_prestador.id), "fecha_compromiso": (hoy + timedelta(days=90)).isoformat()}))
    await db.flush()
    print(f"  criticidad: {len(EVALUACIONES)} equipos evaluados {por_nivel}, "
          f"{sugeridos} modos sugeridos + {len(modos_por_descripcion)} a mano, {len(acciones)} mitigaciones")
    return True


async def _articulo_motor(db, prestador) -> str | None:
    from models.inventario import Articulo

    a = (await db.execute(select(Articulo).where(Articulo.prestador_id == prestador.id,
                                                  Articulo.activo.is_(True)).limit(1))).scalar_one_or_none()
    return str(a.id) if a else None


async def _curso(db, prestador) -> str | None:
    from models.capacitacion import CursoCatalogo

    c = (await db.execute(select(CursoCatalogo).where(CursoCatalogo.prestador_id == prestador.id)
                          .limit(1))).scalar_one_or_none()
    return str(c.id) if c else None


async def _sembrar_historial(db, tenant, prestador, equipos, fallas, niveles, usuarios) -> int:
    """Correctivos cerrados repartidos en doce meses, con su tipo de falla y su causa raíz, para que la probabilidad
    y las sugerencias del FMEA tengan de dónde salir. Escritos directo, como el histórico sintético de P10."""
    rnd = random.Random(55000)
    operador = usuarios.get("operador@acma.dev")
    tecnico = usuarios.get("tecnico1@acma.dev")
    severidades = [niveles.get(c) for c in ("alta", "critica", "media") if niveles.get(c)]
    if (await db.execute(select(Folio.id).where(Folio.numero_folio.like(f"{PREFIJO}%")))).first():
        return 0   # idempotente por el prefijo, como el historico sintetico de P10
    causas = await _opciones_causa_raiz(db, tenant)
    formulario = (await db.execute(select(Formulario).where(
        Formulario.nombre.ilike("%Cierre de correctivo%"), Formulario.tenant_id.is_not(None)).limit(1))).scalar_one_or_none()
    creados = 0
    desde = datetime.now(UTC) - timedelta(days=365)
    for codigo, probabilidad, descripciones in HISTORIAL:
        equipo = equipos.get(codigo)
        if equipo is None:
            continue
        # Lo que el equipo ya trae de los otros seeds cuenta igual para la probabilidad: se completa, no se duplica.
        ya_tiene = int((await db.execute(select(func.count(Folio.id)).where(
            Folio.equipo_id == equipo.id, Folio.tipo_folio == TipoFolio.correctivo,
            Folio.estado == EstadoFolio.cerrado, Folio.fecha_cierre >= desde))).scalar() or 0)
        cuantos = max(0, MINIMO_POR_PROBABILIDAD[probabilidad] - ya_tiene)
        for i in range(cuantos):
            # Repartidos en los últimos 11 meses, sin llegar a hoy: el último mes queda limpio a propósito para que
            # la efectividad de la mitigación implementada se pueda leer.
            dias = 20 + int((330 - 20) * (i / max(1, cuantos - 1)))
            capturado = datetime.now(UTC) - timedelta(days=dias, hours=rnd.randint(0, 20))
            cierre = capturado + timedelta(hours=rnd.randint(3, 40))
            falla = fallas.get(descripciones[i % len(descripciones)])
            nivel = severidades[i % len(severidades)] if severidades else None
            folio = Folio(
                tenant_id=tenant.id, prestador_id=prestador.id, un_id=equipo.un_id, equipo_id=equipo.id,
                numero_folio=f"{PREFIJO}{codigo[-4:]}{i:02d}",
                tipo_falla_id=falla.id if falla else None, tipo_folio=TipoFolio.correctivo,
                estado=EstadoFolio.cerrado,
                descripcion=f"{descripciones[i % len(descripciones)]} (historial para el análisis de criticidad)",
                severidad_id=nivel.id if nivel else None, severidad_origen=SeveridadOrigen.automatica_matriz,
                confirmacion_un=True, capturado_por=operador.id if operador else None, capturado_at=capturado,
                fecha_falla=capturado - timedelta(minutes=rnd.randint(10, 120)),
                fecha_inicio_atencion=capturado + timedelta(hours=rnd.randint(1, 6)), fecha_cierre=cierre,
                tecnico_id=tecnico.id if tecnico else None)
            db.add(folio)
            await db.flush()
            creados += 1
            # La causa raíz vive en la respuesta del formulario de atención (P03): es de donde el FMEA la lee.
            if formulario is not None and causas:
                causa = causas[i % len(causas)]
                r = FormularioRespuesta(
                    formulario_id=formulario.id, version_id=formulario.version_publicada_id, tenant_id=tenant.id,
                    prestador_id=prestador.id, un_id=equipo.un_id, equipo_id=equipo.id,
                    origen=OrigenRespuesta.folio_atencion, referencia_id=folio.id,
                    respuestas_json={"causa_raiz": causa}, respondido_por=tecnico.id if tecnico else None,
                    contexto_json={"sistema": {}, "sellos": {}}, estado=EstadoRespuesta.enviado, enviado_at=cierre,
                    inmutable=True)
                db.add(r)
    await db.flush()
    return creados


async def _opciones_causa_raiz(db, tenant) -> list[str]:
    filas = (await db.execute(select(CatalogoPersonalizadoOpcion.valor)
                              .join(CatalogoPersonalizado, CatalogoPersonalizado.id == CatalogoPersonalizadoOpcion.catalogo_id)
                              .where(CatalogoPersonalizado.clave == "causa_raiz",
                                     CatalogoPersonalizado.tenant_id == tenant.id))).scalars()
    return list(filas)


async def main() -> None:
    from core.db import nueva_sesion

    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        hecho = await sembrar_criticidad(db)
        await db.commit()
        print("Criticidad demo sembrada." if hecho else "Ya existía la configuración de criticidad: no se hizo nada.")


if __name__ == "__main__":
    asyncio.run(main())
