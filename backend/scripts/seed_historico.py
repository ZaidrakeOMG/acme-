"""Histórico sintético de 12 meses para probar los comparativos multi-período y medir los tiempos de ACT-8.4.

Genera al menos 1,000 folios cerrados repartidos entre las 3 UNs del seed, con su costo, su `folio_sla` calculado y una
proporción realista de preventivos e incumplimientos. Va aparte del seed normal porque tarda y no hace falta para
trabajar en el día a día:

    python -m scripts.seed_historico            # 1,200 folios en 12 meses
    python -m scripts.seed_historico 2000 18    # 2,000 folios en 18 meses

Es idempotente por el prefijo del número de folio (`HX-`): si ya hay histórico, no vuelve a generarlo.
"""
import asyncio
import random
import sys
import time
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select

from core.rls import CONTEXTO_SISTEMA
from models.base import NivelSeveridad
from models.catalogos import Equipo, NivelSeveridadCatalogo, TipoFalla
from models.contratos import ContratoSLA
from models.costos import FolioCosto
from models.folios import EstadoFolio, Folio, FolioSLA, SeveridadOrigen, TipoFolio
from models.organizaciones import Prestador, Tenant
from models.unidades import UnidadNegocio
from models.usuarios import Usuario
from services import folios_sla

PREFIJO = "HX-"
PESOS_SEVERIDAD = [("muy_baja", 10), ("baja", 25), ("media", 35), ("alta", 20), ("critica", 10)]
# Proporción de tipos de folio y de incumplimientos del histórico.
PCT_PREVENTIVOS = 25
PCT_INCUMPLIDOS = 18


def _severidad(rnd: random.Random) -> str:
    total = sum(p for _, p in PESOS_SEVERIDAD)
    tiro = rnd.randint(1, total)
    acumulado = 0
    for clave, peso in PESOS_SEVERIDAD:
        acumulado += peso
        if tiro <= acumulado:
            return clave
    return "media"


async def sembrar_historico(db, cantidad: int = 1200, meses: int = 12, semilla: int = 20261102) -> dict:
    inicio_reloj = time.monotonic()
    prestador = (await db.execute(select(Prestador).where(Prestador.rfc == "PDE200101AB1"))).scalar_one_or_none()
    tenant = (await db.execute(select(Tenant).where(Tenant.rfc == "CDE200101XY2"))).scalar_one_or_none()
    if prestador is None or tenant is None:
        return {"creados": 0, "motivo": "falta el seed base"}
    if (await db.execute(select(Folio.id).where(Folio.numero_folio.like(f"{PREFIJO}%")))).first():
        existentes = (await db.execute(select(func.count()).select_from(Folio).where(
            Folio.numero_folio.like(f"{PREFIJO}%")))).scalar_one()
        return {"creados": 0, "existentes": int(existentes), "motivo": "ya hay histórico"}

    rnd = random.Random(semilla)
    unidades = list((await db.execute(select(UnidadNegocio).where(UnidadNegocio.tenant_id == tenant.id))).scalars())
    equipos = list((await db.execute(select(Equipo).where(Equipo.tenant_id == tenant.id))).scalars())
    fallas = list((await db.execute(select(TipoFalla).where(TipoFalla.prestador_id == prestador.id))).scalars())
    niveles = {n.clave: n for n in (await db.execute(select(NivelSeveridadCatalogo).where(
        NivelSeveridadCatalogo.prestador_id == prestador.id))).scalars()}
    tecnicos = list((await db.execute(select(Usuario).where(Usuario.prestador_id == prestador.id,
                                                            Usuario.rol == "tecnico"))).scalars())
    operador = (await db.execute(select(Usuario).where(Usuario.email == "operador@acma.dev"))).scalar_one_or_none()
    if not (unidades and equipos and fallas and niveles):
        return {"creados": 0, "motivo": "faltan catálogos"}
    slas = {}
    for s in (await db.execute(select(ContratoSLA).where(ContratoSLA.prestador_id == prestador.id))).scalars():
        slas.setdefault(s.nivel_severidad_id, s)

    hoy = date.today()
    dias = meses * 30
    creados = 0
    for i in range(1, cantidad + 1):
        atras = rnd.randint(1, dias)
        capturado = datetime.now(UTC) - timedelta(days=atras, hours=rnd.randint(0, 23), minutes=rnd.randint(0, 59))
        equipo = rnd.choice(equipos)
        un = next((u for u in unidades if u.id == equipo.un_id), unidades[0])
        clave = _severidad(rnd)
        nivel = niveles.get(clave) or next(iter(niveles.values()))
        preventivo = rnd.randint(1, 100) <= PCT_PREVENTIVOS
        sla = slas.get(nivel.id)
        limite_min = (sla.tiempo_resolucion_horas if sla else nivel.tiempo_resolucion_horas) * 60
        incumple = rnd.randint(1, 100) <= PCT_INCUMPLIDOS
        efectivo = int(limite_min * (rnd.uniform(1.05, 2.4) if incumple else rnd.uniform(0.15, 0.9)))
        atencion = capturado + timedelta(minutes=rnd.randint(20, max(30, limite_min // 3)))
        cierre = capturado + timedelta(minutes=efectivo)
        folio = Folio(
            tenant_id=tenant.id, prestador_id=prestador.id, un_id=un.id, equipo_id=equipo.id,
            numero_folio=f"{PREFIJO}{i:06d}",
            tipo_falla_id=None if preventivo else rnd.choice(fallas).id,
            tipo_folio=TipoFolio.preventivo if preventivo else TipoFolio.correctivo,
            estado=EstadoFolio.cerrado,
            descripcion=("Mantenimiento preventivo programado del histórico sintético" if preventivo
                         else "Falla correctiva del histórico sintético para los comparativos de BI"),
            severidad_id=nivel.id, severidad_origen=SeveridadOrigen.automatica_matriz, confirmacion_un=True,
            capturado_por=operador.id if operador else None,
            capturado_at=capturado, fecha_falla=capturado - timedelta(minutes=rnd.randint(5, 180)),
            fecha_inicio_atencion=atencion, fecha_cierre=cierre,
            tecnico_id=rnd.choice(tecnicos).id if tecnicos else None,
        )
        db.add(folio)
        await db.flush()
        horas = Decimal(rnd.randint(1, 8))
        tarifa = Decimal(rnd.choice([450, 520, 600]))
        refacciones = Decimal(rnd.randint(0, 9000))
        total = (refacciones + horas * tarifa).quantize(Decimal("0.01"))
        db.add(FolioCosto(folio_id=folio.id, tenant_id=tenant.id, prestador_id=prestador.id,
                          costo_refacciones=refacciones, costo_mano_obra=(horas * tarifa).quantize(Decimal("0.01")),
                          costo_otros=Decimal("0"), ajuste=Decimal("0"), costo_total=total, moneda="MXN",
                          horas_mano_obra=horas, tarifa_hora=tarifa, origen_horas="calculadas",
                          centro_costos="MANTENIMIENTO", razon_ajuste="", detalle_json={"historico": True},
                          validado_at=cierre + timedelta(hours=2)))
        db.add(FolioSLA(folio_id=folio.id, tenant_id=tenant.id, prestador_id=prestador.id, nivel_severidad_id=nivel.id,
                        contrato_sla_id=sla.id if sla else None,
                        tiempo_respuesta_prometido_horas=(sla.tiempo_respuesta_horas if sla else nivel.tiempo_respuesta_horas),
                        tiempo_resolucion_prometido_horas=(sla.tiempo_resolucion_horas if sla else nivel.tiempo_resolucion_horas),
                        tiempo_inicio=capturado, tiempo_respuesta_at=atencion, tiempo_fin=cierre,
                        limite_respuesta_min=(sla.tiempo_respuesta_horas if sla else nivel.tiempo_respuesta_horas) * 60,
                        limite_sla_min=limite_min, tiempo_pausado_min=0, tiempo_exclusion_min=0,
                        tiempo_efectivo_min=efectivo,
                        tiempo_respuesta_efectivo_min=int((atencion - capturado).total_seconds() // 60),
                        tiempo_respuesta_real_min=int((atencion - capturado).total_seconds() // 60),
                        tiempo_resolucion_real_min=efectivo,
                        cumplimiento_respuesta=not incumple or rnd.random() < 0.5,
                        cumplimiento_resolucion=not incumple, cumplimiento=not incumple,
                        penalizacion_calculada=(total * Decimal("0.07")).quantize(Decimal("0.01")) if incumple else Decimal("0"),
                        penalizacion_detalle_json={"historico": True} if incumple else {}))
        creados += 1
        if creados % 200 == 0:
            await db.flush()
    await db.flush()
    segundos = round(time.monotonic() - inicio_reloj, 1)
    return {"creados": creados, "meses": meses, "segundos": segundos,
             "incumplidos_aprox": round(creados * PCT_INCUMPLIDOS / 100)}


async def main() -> None:
    from core.db import nueva_sesion

    cantidad = int(sys.argv[1]) if len(sys.argv) > 1 else 1200
    meses = int(sys.argv[2]) if len(sys.argv) > 2 else 12
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        resumen = await sembrar_historico(db, cantidad, meses)
        await db.commit()
    print(resumen)


if __name__ == "__main__":
    asyncio.run(main())
