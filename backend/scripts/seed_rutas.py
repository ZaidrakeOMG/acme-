"""Datos demo de F2-06: mercado, configuración del optimizador, folios del día con ventanas y SLA variados, un
plan calculado y publicado, un técnico desviado y una propuesta de reasignación pendiente.

**Por qué el seed crea folios propios:** la ruta se calcula sobre los folios **abiertos de hoy**, y los del seed
base ya están cerrados o repartidos entre meses. Son folios autorizados escritos directo con el prefijo `RT-`,
como el histórico sintético de P10, con ventanas de horario distintas, equipos de criticidad distinta y algunos
con refacción prevista, para que se vea de verdad cómo el optimizador los acomoda.

El técnico desviado y la propuesta pendiente existen para poder ver la pantalla con algo que decidir: sin una
propuesta en la bandeja, el tablero de operaciones se ve vacío y no se entiende qué hace.
"""
import asyncio
import random
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import func, select

from core.db import nueva_sesion
from core.rls import CONTEXTO_SISTEMA
from models.base import Rol
from models.catalogos import Equipo, NivelSeveridadCatalogo, Tecnico, TipoFalla
from models.folios import EstadoFolio, Folio, SeveridadOrigen, TipoFolio
from models.operaciones import EstadoJornada, JornadaTecnico, TecnicoPosicion
from models.organizaciones import Prestador, Tenant
from models.rutas import (
    DisparadorRecalculo, EstadoPlanRuta, Mercado, MercadoUnidad, ModoReasignacionAutomatica, PESOS_DEFAULT,
    VELOCIDADES_DEFAULT,
)
from models.unidades import UnidadNegocio
from models.usuarios import Usuario
from scripts.seed_folios import actor_de

PREFIJO = "RT-"
TECNICOS_DEMO = ["tecnico1@acma.dev", "tecnico2@acma.dev", "tecnico3@acma.dev", "tecnico4@acma.dev"]
MERCADO = ("CDMX-CENTRO", "Ciudad de México · zona centro")

# Los 18 folios del día: (familia, ventana, severidad, con_refaccion). La ventana es la hora local de la jornada;
# «None» significa «cuando se pueda», que es el caso normal.
FOLIOS_DEMO = [
    ("Refrigeración", None, "critica", True),
    ("Refrigeración", (9, 11), "alta", False),
    ("Refrigeración", None, "media", False),
    ("Climatización", (8, 10), "alta", True),
    ("Climatización", None, "media", False),
    ("Climatización", (14, 17), "baja", False),
    ("Iluminación", None, "baja", False),
    ("Iluminación", (11, 13), "media", False),
    ("Iluminación", None, "muy_baja", False),
    ("Refrigeración", (10, 12), "critica", False),
    ("Climatización", None, "alta", True),
    ("Iluminación", None, "media", False),
    ("Refrigeración", None, "alta", False),
    ("Climatización", (15, 18), "media", False),
    ("Iluminación", None, "baja", False),
    ("Refrigeración", (8, 9), "critica", False),
    ("Climatización", None, "baja", False),
    ("Iluminación", None, "media", False),
]


async def sembrar_rutas(db) -> bool:
    prestador = (await db.execute(select(Prestador).where(Prestador.rfc == "PDE200101AB1"))).scalar_one_or_none()
    tenant = (await db.execute(select(Tenant).where(Tenant.rfc == "CDE200101XY2"))).scalar_one_or_none()
    if prestador is None or tenant is None:
        return False
    if (await db.execute(select(Mercado.id).where(Mercado.prestador_id == prestador.id))).first():
        return False

    rnd = random.Random(60000)
    usuarios = {u.email: u for u in (await db.execute(select(Usuario))).scalars()}
    operador = usuarios["operador@acma.dev"]
    despachador = usuarios["despachador@acma.dev"]
    actor_desp = actor_de(despachador)
    unidades = list((await db.execute(select(UnidadNegocio).where(
        UnidadNegocio.tenant_id == tenant.id).order_by(UnidadNegocio.codigo))).scalars())
    if not unidades:
        return False

    # ------------------------------------------------------------- mercado con sus unidades
    centro_lat = sum(19.43 for _ in unidades) / len(unidades)
    mercado = Mercado(prestador_id=prestador.id, codigo=MERCADO[0], nombre=MERCADO[1],
                      centro=func.ST_GeogFromText("POINT(-99.1332 19.4326)"))
    db.add(mercado)
    await db.flush()
    for un in unidades:
        db.add(MercadoUnidad(mercado_id=mercado.id, prestador_id=prestador.id, un_id=un.id))
    await db.flush()

    # ------------------------------------------------------------- configuración del optimizador
    from services.rutas import motor, planes_service, recalculo_service

    cfg = await motor.configuracion(db, prestador.id, mercado.id)
    cfg.pesos_json = {**PESOS_DEFAULT}
    cfg.velocidades_json = {**VELOCIDADES_DEFAULT}
    cfg.hora_inicio_jornada = time(8, 0)
    cfg.configurado_por = usuarios["admin.prestador@acma.dev"].id
    # El demo queda en `solo_sugerir`: la propuesta espera en la bandeja y no mueve nada sola. Es el default y es
    # lo que conviene ver primero.
    cfg.modo_reasignacion_automatica = ModoReasignacionAutomatica.solo_sugerir
    # El demo y las pruebas no necesitan los 30 s del default: con 15 s la solución ya es buena para 3 técnicos y
    # el seed no se vuelve eterno (con 5 s y casi cien folios no alcanza a encontrar la primera solución). En producción conviene dejar el default.
    cfg.segundos_limite_calculo = 15
    await db.flush()
    # **No se corre `tiempos_service.sugerir()` en el demo a propósito.** La medición del historial es correcta y
    # es la buena con datos reales, pero el histórico sintético de P10 cierra los folios horas o días después de
    # empezar a atenderlos, así que la mediana sale en cuatro horas por visita y cada técnico apenas alcanzaría una
    # parada. El demo se queda con los tiempos literales (60 min correctivo, 90 min preventivo) y «Sugerir con el
    # historial» queda como botón en la pantalla, que es donde tiene sentido con datos de verdad.

    # ------------------------------------------------------------- folios del día
    equipos_por_familia: dict[str, list[Equipo]] = {}
    from models.catalogos import FamiliaEquipo, TipoEquipo

    for familia in ("Refrigeración", "Climatización", "Iluminación"):
        fam = (await db.execute(select(FamiliaEquipo).where(FamiliaEquipo.nombre == familia))).scalar_one_or_none()
        if fam is None:
            continue
        equipos_por_familia[familia] = list((await db.execute(
            select(Equipo).join(TipoEquipo, TipoEquipo.id == Equipo.tipo_equipo_id)
            .where(Equipo.tenant_id == tenant.id, TipoEquipo.familia_id == fam.id)
            .order_by(Equipo.codigo).limit(8))).scalars())
    fallas = {f.descripcion: f for f in (await db.execute(
        select(TipoFalla).where(TipoFalla.prestador_id == prestador.id))).scalars()}
    niveles = {n.clave: n for n in (await db.execute(
        select(NivelSeveridadCatalogo).where(NivelSeveridadCatalogo.prestador_id == prestador.id))).scalars()}
    hoy = date.today()
    inicio = datetime.combine(hoy, time(8, 0), tzinfo=UTC)

    # Idempotente por el número de folio: si el mercado se borró a mano pero los folios siguen, no se duplican.
    ya_estan = {n for (n,) in (await db.execute(select(Folio.numero_folio).where(
        Folio.numero_folio.like(f"{PREFIJO}%")))).all()}
    creados = 0
    for i, (familia, ventana, severidad, con_refaccion) in enumerate(FOLIOS_DEMO):
        if f"{PREFIJO}{i + 1:04d}" in ya_estan:
            continue
        candidatos = equipos_por_familia.get(familia) or []
        if not candidatos:
            continue
        equipo = candidatos[i % len(candidatos)]
        nivel = niveles.get(severidad)
        falla = next((f for f in fallas.values() if f is not None), None)
        folio = Folio(
            tenant_id=tenant.id, prestador_id=prestador.id, un_id=equipo.un_id, equipo_id=equipo.id,
            numero_folio=f"{PREFIJO}{i + 1:04d}", tipo_folio=TipoFolio.correctivo,
            estado=EstadoFolio.autorizado,
            descripcion=f"Folio del día para la ruta ({familia.lower()})",
            tipo_falla_id=falla.id if falla else None,
            severidad_id=nivel.id if nivel else None, severidad_origen=SeveridadOrigen.automatica_matriz,
            confirmacion_un=True, capturado_por=operador.id,
            capturado_at=datetime.now(UTC) - timedelta(hours=rnd.randint(1, 6)),
            fecha_falla=datetime.now(UTC) - timedelta(hours=rnd.randint(2, 8)),
            ventana_inicio=inicio + timedelta(hours=ventana[0] - 8) if ventana else None,
            ventana_fin=inicio + timedelta(hours=ventana[1] - 8) if ventana else None)
        db.add(folio)
        creados += 1
    await db.flush()

    # ------------------------------------------------------------- jornadas de los técnicos
    # Solo los cuatro técnicos del demo: la base de desarrollo arrastra decenas más de las pruebas de carga de
    # P11a, y abrirles jornada a todos convertiría el plan del día en un problema de 50 vehículos que no se parece
    # a la operación que se quiere mostrar.
    tecnicos = list((await db.execute(
        select(Tecnico, Usuario).join(Usuario, Usuario.id == Tecnico.usuario_id)
        .where(Usuario.prestador_id == prestador.id, Usuario.rol == Rol.tecnico,
               Usuario.email.in_(TECNICOS_DEMO))
        .order_by(Usuario.email))).all())
    abiertas = 0
    for tecnico, _usuario in tecnicos:
        ya = (await db.execute(select(JornadaTecnico).where(
            JornadaTecnico.tecnico_id == tecnico.id,
            JornadaTecnico.estado == EstadoJornada.activa))).scalars().first()
        if ya is not None:
            continue
        db.add(JornadaTecnico(prestador_id=prestador.id, tecnico_id=tecnico.id,
                              inicio=datetime.now(UTC) - timedelta(hours=1),
                              estado=EstadoJornada.activa, aviso_aceptado_at=datetime.now(UTC) - timedelta(days=5)))
        abiertas += 1
    await db.flush()

    # ------------------------------------------------------------- plan calculado y publicado
    plan = await planes_service.calcular(db, actor_desp, mercado.id, hoy, prestador_id=prestador.id)
    await db.flush()
    publicado = await planes_service.publicar(db, actor_desp, plan)
    await db.flush()

    # ------------------------------------------------------------- un técnico desviado
    desviado = await _sembrar_desvio(db, prestador, tecnicos, plan)

    # ------------------------------------------------------------- una propuesta pendiente
    propuesta = None
    if desviado is not None:
        propuesta = await recalculo_service.recalcular_parcial(
            db, plan, disparador=DisparadorRecalculo.desvio, tecnico_id=desviado,
            motivo="Desvío de ruta detectado en el seed demo (500 m por más de 5 minutos)")
    await db.flush()
    print(f"  rutas: mercado {mercado.codigo} con {len(unidades)} UN, {creados} folios del día, "
          f"{abiertas} jornadas, plan {plan.estado.value} con {publicado['asignados']} asignados y "
          f"{plan.folios_sin_asignar} sin asignar, "
          f"propuesta {'pendiente' if propuesta and propuesta.folios_movidos_json else 'sin movimientos'}")
    return True


async def _sembrar_desvio(db, prestador, tecnicos, plan) -> object | None:
    """Posiciones de un técnico alejándose de su siguiente destino, para que el evaluador de desvío lo cace.

    Con el proveedor `estimado` la regla pide que la distancia al destino **aumente de forma sostenida** y que el
    técnico esté fuera del corredor de 2 km alrededor de la línea recta: estas posiciones cumplen las dos.
    """
    from models.rutas import RutaParada

    primera = (await db.execute(select(RutaParada).where(RutaParada.plan_id == plan.id)
                                .order_by(RutaParada.orden))).scalars().first()
    if primera is None:
        return None
    tecnico = next((t for t, u in tecnicos if u.id == primera.tecnico_id), None)
    if tecnico is None:
        return None
    jornada = (await db.execute(select(JornadaTecnico).where(
        JornadaTecnico.tecnico_id == tecnico.id,
        JornadaTecnico.estado == EstadoJornada.activa))).scalars().first()
    if jornada is None:
        return None
    ahora = datetime.now(UTC)
    # Se aleja hacia el poniente, fuera del corredor, en seis lecturas de dos minutos.
    for i in range(6):
        lng = -99.14 - 0.03 * (i + 1)
        db.add(TecnicoPosicion(
            prestador_id=prestador.id, tecnico_id=tecnico.id, jornada_id=jornada.id,
            posicion=func.ST_GeogFromText(f"POINT({lng} 19.40)"),
            precision_m=12, capturada_at=ahora - timedelta(minutes=12 - 2 * i)))
    tecnico.ultima_posicion = func.ST_GeogFromText(f"POINT({-99.14 - 0.03 * 6} 19.40)")
    tecnico.ultima_posicion_at = ahora
    await db.flush()
    return primera.tecnico_id


async def main() -> None:
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        ok = await sembrar_rutas(db)
        await db.commit()
    print("Rutas demo sembradas." if ok else "No se sembró: ya existía el mercado o falta el seed base.")


if __name__ == "__main__":
    asyncio.run(main())
