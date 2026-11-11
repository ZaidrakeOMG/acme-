"""Datos demo de F2-04: catálogo global con los seis tipos de medidor de §6.9.2, seis equipos industriales con su
medidor, 60 días de lecturas con los cuatro métodos, una lectura anómala en revisión, un reinicio de marcador,
cuatro planes con los triggers nuevos (uno a punto de dispararse) y un activo que se deprecia por unidades
producidas.

Los equipos de la demo de Fase 1 son refrigeradores, minisplits y lámparas: no tienen marcador que leer. Este seed
agrega los seis que pide §6.9.2 (compresor con horas, elevador con ciclos, generador con kilómetros, motor con
kWh, línea de producción con unidades y un tanque con un medidor personalizado) en la primera UN.

Idempotente: no hace nada si ya existen los tipos de medidor globales. Se ejecuta desde seed_dev
(o solo: `python -m scripts.seed_medidores`).
"""
import asyncio
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from core.rls import CONTEXTO_SISTEMA
from models.activos import ActivoDepreciacion, MetodoDepreciacion
from models.catalogos import Equipo, FamiliaEquipo, TipoEquipo
from models.medidores import (
    CategoriaMedidor, EquipoMedidor, MetodoActualizacionMedidor, TipoCambioMedidor, TipoMedidor,
)
from models.organizaciones import Prestador, Tenant
from models.preventivos import EquipoPlan, PlanMantenimiento
from models.unidades import UnidadNegocio
from models.usuarios import Usuario
from scripts.seed_folios import actor_de
from services import medidores_service, planes_service

# ------------------------------------------------------------------ catálogo global (§6.9.2, los seis literales)
TIPOS: list[dict[str, Any]] = [
    {"nombre": "Horas de operación", "unidad": "h", "categoria": "horas", "decimales": 1, "requiere_foto": True,
     "descripcion": "Horómetro del equipo. Ejemplo de §6.9.2: cambio de aceite cada 500 h de operación del compresor."},
    {"nombre": "Ciclos", "unidad": "ciclos", "categoria": "ciclos", "decimales": 0,
     "descripcion": "Conteo de operaciones. Ejemplo de §6.9.2: revisión de cables del elevador cada 50,000 ciclos."},
    {"nombre": "Kilómetros", "unidad": "km", "categoria": "distancia", "decimales": 0,
     "descripcion": "Odómetro de equipos móviles. Ejemplo de §6.9.2: mantenimiento mayor cada 10,000 km."},
    {"nombre": "Energía consumida", "unidad": "kWh", "categoria": "energia", "decimales": 0,
     "descripcion": "Consumo acumulado. Ejemplo de §6.9.2: revisión de rodamientos cada 50,000 kWh."},
    {"nombre": "Unidades producidas", "unidad": "piezas", "categoria": "unidades", "decimales": 0,
     "descripcion": "Producción acumulada. Ejemplo de §6.9.2: mantenimiento de banda cada 100,000 unidades."},
    {"nombre": "Litros tratados", "unidad": "L", "categoria": "personalizado", "decimales": 0,
     "descripcion": "Medidor personalizado: cualquier variable numérica que el cliente quiera medir."},
]

# ------------------------------------------------------------------ equipos industriales de la demo
FAMILIA_INDUSTRIAL = "Equipos industriales"
EQUIPOS: list[dict[str, Any]] = [
    # codigo, nombre, tipo de equipo, medidor, incremento por día, valor máximo del marcador, costo
    {"codigo": "EQ-1001", "nombre": "Compresor de aire sala de máquinas", "tipo": "Compresor de aire",
     "medidor": "Horas de operación", "metodo": "operador", "incremento": "8", "maximo": "99999",
     "serie_medidor": "HM-884210", "costo": "180000"},
    {"codigo": "EQ-1002", "nombre": "Elevador de carga andén", "tipo": "Elevador de carga",
     "medidor": "Ciclos", "metodo": "importacion", "incremento": "820", "maximo": None,
     "serie_medidor": "CT-55012", "costo": "420000"},
    {"codigo": "EQ-1003", "nombre": "Generador móvil 60 kVA", "tipo": "Generador móvil",
     "medidor": "Kilómetros", "metodo": "tecnico", "incremento": "24", "maximo": "1000",
     "serie_medidor": "OD-7781", "costo": "310000"},
    {"codigo": "EQ-1004", "nombre": "Motor eléctrico bomba principal", "tipo": "Motor eléctrico",
     "medidor": "Energía consumida", "metodo": "importacion", "incremento": "300", "maximo": None,
     "serie_medidor": "KW-30091", "costo": "95000"},
    {"codigo": "EQ-1005", "nombre": "Línea de empaque 1", "tipo": "Línea de producción",
     "medidor": "Unidades producidas", "metodo": "importacion", "incremento": "1200", "maximo": None,
     "serie_medidor": "PC-11204", "costo": "1200000"},
    {"codigo": "EQ-1006", "nombre": "Planta de tratamiento de agua", "tipo": "Tanque de tratamiento",
     "medidor": "Litros tratados", "metodo": "estimado", "incremento": "4500", "maximo": None,
     "serie_medidor": None, "costo": "260000"},
]

DIAS_HISTORIA = 60
# Qué método usa la lectura de cada día, para que el historial se vea como se ve en la realidad: el operador casi
# todos los días, el técnico cuando pasa por el equipo y la importación cuando el SCADA la manda.
def _metodo_del_dia(base: str, dia: int) -> MetodoActualizacionMedidor:
    if base == "importacion":
        return MetodoActualizacionMedidor.importacion
    if base == "estimado":
        return MetodoActualizacionMedidor.estimado
    if base == "tecnico":
        return MetodoActualizacionMedidor.tecnico
    return (MetodoActualizacionMedidor.tecnico if dia % 14 == 0 else MetodoActualizacionMedidor.operador)


# Cada cuántos días hay lectura (un odómetro no se lee a diario; un contador de producción sí).
CADENCIA = {"EQ-1001": 1, "EQ-1002": 1, "EQ-1003": 5, "EQ-1004": 1, "EQ-1005": 1, "EQ-1006": 3}


async def sembrar_medidores(db) -> bool:
    prestador = (await db.execute(select(Prestador).where(Prestador.rfc == "PDE200101AB1"))).scalar_one_or_none()
    tenant = (await db.execute(select(Tenant).where(Tenant.rfc == "CDE200101XY2"))).scalar_one_or_none()
    if prestador is None or tenant is None:
        return False
    if (await db.execute(select(TipoMedidor.id).where(TipoMedidor.prestador_id.is_(None),
                                                      TipoMedidor.tenant_id.is_(None)))).first():
        return False

    usuarios = {u.email: u for u in (await db.execute(select(Usuario))).scalars()}
    admin_prestador = usuarios["admin.prestador@acma.dev"]
    operador, tecnico1 = usuarios["operador@acma.dev"], usuarios["tecnico1@acma.dev"]
    actor_ap, actor_op, actor_tec = actor_de(admin_prestador), actor_de(operador), actor_de(tecnico1)
    un = (await db.execute(select(UnidadNegocio).where(UnidadNegocio.tenant_id == tenant.id)
                           .order_by(UnidadNegocio.codigo))).scalars().first()

    # ------------------------------------------------------------- catálogo global de tipos
    tipos: dict[str, TipoMedidor] = {}
    for t in TIPOS:
        fila = TipoMedidor(prestador_id=None, tenant_id=None, nombre=t["nombre"], unidad=t["unidad"],
                           categoria=CategoriaMedidor(t["categoria"]), descripcion=t["descripcion"],
                           decimales=t.get("decimales", 0), requiere_foto=t.get("requiere_foto", False),
                           permite_estimacion=True)
        db.add(fila)
        tipos[t["nombre"]] = fila
    await db.flush()

    # ------------------------------------------------------------- familia y tipos de equipo industriales
    familia = FamiliaEquipo(tenant_id=None, nombre=FAMILIA_INDUSTRIAL, habilidad_clave="electricidad")
    db.add(familia)
    await db.flush()
    tipos_equipo: dict[str, TipoEquipo] = {}
    for nombre in ("Compresor de aire", "Elevador de carga", "Generador móvil", "Motor eléctrico",
                   "Línea de producción", "Tanque de tratamiento"):
        te = TipoEquipo(tenant_id=None, familia_id=familia.id, nombre=nombre)
        db.add(te)
        tipos_equipo[nombre] = te
    await db.flush()

    hoy = date.today()
    inicio = hoy - timedelta(days=DIAS_HISTORIA)
    equipos: dict[str, Equipo] = {}
    medidores: dict[str, EquipoMedidor] = {}
    for e in EQUIPOS:
        equipo = Equipo(tenant_id=tenant.id, un_id=un.id, tipo_equipo_id=tipos_equipo[e["tipo"]].id,
                        codigo=e["codigo"], nombre=e["nombre"], marca="Industrial", modelo=e["codigo"],
                        numero_serie=f"SN{e['codigo'][-4:]}", fecha_instalacion=inicio - timedelta(days=400),
                        valor_reposicion=Decimal(e["costo"]), criticidad="B",
                        notas="Equipo con medidor (F2-04, §6.9.2)")
        equipo.costo_adquisicion = Decimal(e["costo"])
        equipo.fecha_adquisicion = inicio - timedelta(days=400)
        db.add(equipo)
        await db.flush()
        equipos[e["codigo"]] = equipo
        medidor = await medidores_service.alta_medidor(db, actor_ap, equipo, {
            "tipo_medidor_id": tipos[e["medidor"]].id, "valor_inicial": Decimal("0"),
            "metodo_actualizacion": e["metodo"], "valor_maximo": Decimal(e["maximo"]) if e["maximo"] else None,
            "numero_serie_medidor": e["serie_medidor"], "instalado_en": inicio - timedelta(days=400)}, None)
        medidores[e["codigo"]] = medidor
        await medidores_service.configurar_estimacion(db, actor_ap, medidor, {
            "incremento_por_dia": Decimal(e["incremento"]),
            "horario_operacion_json": {"dias": ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado"],
                                       "horas_por_dia": 8},
            "activa": e["metodo"] == "estimado", "desde": inicio}, None)
    await db.flush()

    # ------------------------------------------------------------- 60 días de lecturas
    # `evaluar=False`: todavía no hay planes asignados y así el sembrado no hace trabajo inútil por cada lectura.
    for e in EQUIPOS:
        medidor = medidores[e["codigo"]]
        incremento = Decimal(e["incremento"])
        cadencia = CADENCIA[e["codigo"]]
        acumulado_marcador = Decimal("0")
        for dia in range(cadencia, DIAS_HISTORIA + 1, cadencia):
            momento = datetime.combine(inicio + timedelta(days=dia), datetime.min.time(), tzinfo=UTC) + timedelta(hours=7)
            acumulado_marcador += incremento * cadencia
            # El generador da la vuelta a los 2,000 km: se registra el reinicio y el acumulado sigue avanzando.
            if medidor.valor_maximo is not None and acumulado_marcador > medidor.valor_maximo:
                await medidores_service.registrar_cambio(
                    db, actor_ap, medidor, tipo=TipoCambioMedidor.reinicio, valor_nuevo=Decimal("0"),
                    motivo=f"El odómetro llegó a su tope de {medidor.valor_maximo} km y volvió a cero", momento=momento)
                acumulado_marcador = incremento * cadencia
            actor = actor_op if e["metodo"] == "operador" else actor_tec
            await medidores_service.registrar_lectura(
                db, actor, medidor, valor=acumulado_marcador, metodo=_metodo_del_dia(e["metodo"], dia),
                timestamp_dispositivo=momento, evaluar=False)
    await db.flush()

    # Una lectura anómala en revisión: el SCADA del motor mandó un salto de diez veces lo normal (§6.9.2).
    motor = medidores["EQ-1004"]
    anomala = await medidores_service.registrar_lectura(
        db, actor_ap, motor, valor=Decimal(motor.valor_actual) + Decimal("9000"),
        metodo=MetodoActualizacionMedidor.importacion,
        timestamp_dispositivo=datetime.now(UTC) - timedelta(hours=3), evaluar=False)
    assert anomala["anomalia"], "La lectura demo del motor debía quedar en revisión"

    # ------------------------------------------------------------- los cuatro planes nuevos (§6.9.1)
    planes = await _sembrar_planes(db, actor_ap, prestador, tipos, tipos_equipo, equipos, medidores)

    # ------------------------------------------------------------- un activo que se deprecia por unidades
    linea = equipos["EQ-1005"]
    db.add(ActivoDepreciacion(
        equipo_id=linea.id, tenant_id=tenant.id, metodo=MetodoDepreciacion.unidades_produccion,
        vida_util_anios=10, valor_salvamento=Decimal("100000"), valor_reposicion=Decimal("1350000"),
        unidades_vida_util=Decimal("2000000"), unidades_al_inicio=Decimal("0"), fecha_inicio=inicio,
        equipo_medidor_id=medidores["EQ-1005"].id, configurado_por=admin_prestador.id))
    await db.flush()
    print(f"  medidores: {len(TIPOS)} tipos globales, {len(EQUIPOS)} equipos con medidor, {len(planes)} planes nuevos")
    return True


async def _sembrar_planes(db, actor_ap, prestador, tipos, tipos_equipo, equipos, medidores) -> list[PlanMantenimiento]:
    """Los cuatro triggers nuevos con los ejemplos literales de §6.9.1.

    El del compresor queda **a punto de dispararse** para la demostración: 480 h de 500, así que la alerta
    `MEDIDOR_PROXIMO_PM` (10 % del intervalo) ya está disparada y el folio nacerá con las próximas lecturas.
    """
    salida = []
    horas, ciclos = tipos["Horas de operación"], tipos["Ciclos"]

    # 1) Por medidor — umbral: cambio de aceite a las 500 h (ejemplo literal de §6.9.1).
    aceite = await planes_service.crear(db, actor_ap, {
        "nombre": "Cambio de aceite del compresor a las 500 h", "tipo_equipo_id": tipos_equipo["Compresor de aire"].id,
        "descripcion": "Trigger por medidor (umbral): cuando el horómetro llega a 500 h de operación.",
        "tenant_id": None, "estado": "activo", "tiempo_ventana_dias": 5, "formulario_id": None, "nivel_severidad_id": None,
        "triggers": [{"tipo_trigger": "medidor_umbral", "clave": "t1",
                      "parametros_json": {"tipo_medidor_id": str(horas.id), "umbral": 500}}],
        "tareas": [{"orden": 1, "descripcion": "Drenar y reponer aceite sintético", "tiempo_estimado_min": 45, "habilidad_requerida_id": None},
                   {"orden": 2, "descripcion": "Cambiar filtro de aceite y revisar fugas", "tiempo_estimado_min": 25, "habilidad_requerida_id": None},
                   {"orden": 3, "descripcion": "Registrar la lectura del horómetro", "tiempo_estimado_min": 5, "habilidad_requerida_id": None}],
        "materiales": [{"descripcion": "Aceite sintético ISO 46", "cantidad_estandar": "4", "unidad": "litro", "articulo_id": None},
                       {"descripcion": "Filtro de aceite", "cantidad_estandar": "1", "unidad": "pieza", "articulo_id": None}],
    }, None, prestador.id)
    await planes_service.asignar_equipo(db, actor_ap, aceite, equipos["EQ-1001"].id, None, None)
    salida.append(aceite)

    # 2) Por medidor — intervalo: revisión de banda cada 10,000 ciclos (ejemplo literal de §6.9.1).
    banda = await planes_service.crear(db, actor_ap, {
        "nombre": "Revisión de cables del elevador cada 10,000 ciclos", "tipo_equipo_id": tipos_equipo["Elevador de carga"].id,
        "descripcion": "Trigger por medidor (intervalo): cada 10,000 ciclos desde el último mantenimiento.",
        "tenant_id": None, "estado": "activo", "tiempo_ventana_dias": 7, "formulario_id": None, "nivel_severidad_id": None,
        "triggers": [{"tipo_trigger": "medidor_intervalo", "clave": "t1",
                      "parametros_json": {"tipo_medidor_id": str(ciclos.id), "intervalo": 10000}}],
        "tareas": [{"orden": 1, "descripcion": "Inspección visual y medición de desgaste de cables", "tiempo_estimado_min": 40, "habilidad_requerida_id": None},
                   {"orden": 2, "descripcion": "Lubricación de guías y registro de la lectura", "tiempo_estimado_min": 20, "habilidad_requerida_id": None}],
        "materiales": [{"descripcion": "Grasa para cable de acero", "cantidad_estandar": "1", "unidad": "kg", "articulo_id": None}],
    }, None, prestador.id)
    ep_banda = await planes_service.asignar_equipo(db, actor_ap, banda, equipos["EQ-1002"].id, None, None)
    # Último PM a los 40,000 ciclos: el próximo toca a los 50,000 y el elevador lleva ~49,200.
    ep_banda.ultimo_valor_medidor = Decimal("40000")
    medidores["EQ-1002"].valor_ultimo_pm = Decimal("40000")
    salida.append(banda)

    # 3) Por evento: inspección después de cualquier falla correctiva grave (ejemplo literal de §6.9.1).
    inspeccion = await planes_service.crear(db, actor_ap, {
        "nombre": "Inspección tras falla correctiva grave", "tipo_equipo_id": tipos_equipo["Motor eléctrico"].id,
        "descripcion": "Trigger por evento: al cerrarse un correctivo de severidad alta o crítica en el equipo.",
        "tenant_id": None, "estado": "activo", "tiempo_ventana_dias": 3, "formulario_id": None, "nivel_severidad_id": None,
        "triggers": [{"tipo_trigger": "evento", "clave": "t1",
                      "parametros_json": {"evento": "falla_correctiva_grave", "severidades": ["alta", "critica"]}}],
        "tareas": [{"orden": 1, "descripcion": "Análisis de causa raíz con el técnico que atendió", "tiempo_estimado_min": 30, "habilidad_requerida_id": None},
                   {"orden": 2, "descripcion": "Medición de vibración y temperatura de rodamientos", "tiempo_estimado_min": 35, "habilidad_requerida_id": None}],
        "materiales": [],
    }, None, prestador.id)
    await planes_service.asignar_equipo(db, actor_ap, inspeccion, equipos["EQ-1004"].id, None, None)
    salida.append(inspeccion)

    # 4) Combinado OR: 90 días O 400 horas, lo que ocurra primero (ejemplo literal de §6.9.1).
    combinado = await planes_service.crear(db, actor_ap, {
        "nombre": "Revisión del compresor: 90 días o 400 horas", "tipo_equipo_id": tipos_equipo["Compresor de aire"].id,
        "descripcion": "Trigger combinado con lógica OR: lo que ocurra primero entre 90 días y 400 h de operación.",
        "tenant_id": None, "estado": "activo", "tiempo_ventana_dias": 7, "formulario_id": None, "nivel_severidad_id": None,
        "triggers": [
            {"tipo_trigger": "tiempo_fijo", "clave": "t1", "parametros_json": {"cada_dias": 90}},
            {"tipo_trigger": "medidor_umbral", "clave": "t2",
             "parametros_json": {"tipo_medidor_id": str(horas.id), "umbral": 400}},
            {"tipo_trigger": "combinado", "clave": "t3", "logica_combinacion": "OR",
             "parametros_json": {"triggers_claves": ["t1", "t2"], "logica": "OR"}},
        ],
        "tareas": [{"orden": 1, "descripcion": "Revisión general: correas, presiones y purgas", "tiempo_estimado_min": 50, "habilidad_requerida_id": None}],
        "materiales": [],
    }, None, prestador.id)
    # Se asigna al segundo compresor que no existe en la demo: queda sobre el mismo EQ-1001 con un último PM alto,
    # para que no nazca el folio al sembrar y se pueda ver la simulación del combinado.
    ep_comb = await planes_service.asignar_equipo(db, actor_ap, combinado, equipos["EQ-1001"].id, None, None)
    ep_comb.ultimo_valor_medidor = Decimal("480")
    salida.append(combinado)
    await db.flush()
    return salida


async def main() -> None:
    from core.db import nueva_sesion

    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        hecho = await sembrar_medidores(db)
        await db.commit()
        print("Medidores demo sembrados." if hecho else "Ya existían los tipos de medidor globales: no se hizo nada.")


if __name__ == "__main__":
    asyncio.run(main())
