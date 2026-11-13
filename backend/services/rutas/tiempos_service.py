"""Tiempos de servicio sugeridos con el historial real de atención (F2-06).

Cuánto dura atender un folio es el dato que más mueve la calidad de la ruta, y es el único que ACMA puede medir
solo: `fecha_inicio_atencion` → `fecha_cierre` de los folios cerrados, por tipo de folio y tipo de equipo.

**Dos decisiones que no son cosméticas**, y que costaron un defecto antes de tomarlas:

1. **Mediana, no promedio.** Un folio que se cerró tres días después de empezar a atenderse no fue tres días de
   trabajo en sitio: fue espera (una refacción, el cliente sin acceso). Esos casos arrastran el promedio y en el
   demo lo dejaban en el tope de 1,440 minutos, con lo cual **cada parada se comía la jornada completa** y la ruta
   salía de una sola parada por técnico. La mediana no se deja arrastrar.
2. **Se descartan las muestras más largas que una jornada.** Por lo mismo: no son tiempo de visita. Si el folio
   tardó más que un día de trabajo, lo que se midió fue la espera, no el servicio.

Y el resultado se **acota a la jornada**: un tiempo de servicio mayor que la jornada vuelve el folio imposible de
rutear por construcción, lo que no ayuda a nadie.

**Solo escribe donde nadie configuró un valor a mano** (`origen = 'configurado'` se respeta): la medición informa,
no manda sobre lo que una persona decidió.
"""
import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.catalogos import Equipo, TipoEquipo
from models.folios import EstadoFolio, Folio
from models.rutas import RutaTiempoServicio

log = logging.getLogger("acma.rutas.tiempos")

MINIMO_MUESTRAS = 5      # con menos, la mediana es anécdota
MINUTOS_MINIMOS = 5
# Tope del resultado y de las muestras que se consideran: una jornada de ocho horas. Lo que pasa de ahí es espera,
# no visita.
MINUTOS_MAXIMOS = 480


async def medir(db: AsyncSession, prestador_id: UUID, meses: int = 6) -> list[dict]:
    """Promedio de minutos de atención por (tipo de folio, tipo de equipo), con su número de muestras."""
    desde = datetime.now(UTC) - timedelta(days=30 * meses)
    duracion = func.extract("epoch", Folio.fecha_cierre - Folio.fecha_inicio_atencion) / 60
    filas = (await db.execute(
        select(Folio.tipo_folio, Equipo.tipo_equipo_id,
               func.percentile_cont(0.5).within_group(duracion),
               func.count())
        .outerjoin(Equipo, Equipo.id == Folio.equipo_id)
        .where(Folio.prestador_id == prestador_id, Folio.estado == EstadoFolio.cerrado,
               Folio.fecha_inicio_atencion.is_not(None), Folio.fecha_cierre.is_not(None),
               Folio.fecha_cierre >= desde,
               duracion > 0, duracion <= MINUTOS_MAXIMOS)
        .group_by(Folio.tipo_folio, Equipo.tipo_equipo_id))).all()
    salida = []
    for tipo_folio, tipo_equipo_id, mediana, muestras in filas:
        if mediana is None or muestras < MINIMO_MUESTRAS:
            continue
        minutos = int(max(MINUTOS_MINIMOS, min(MINUTOS_MAXIMOS, round(float(mediana)))))
        salida.append({"tipo_folio": tipo_folio, "tipo_equipo_id": tipo_equipo_id,
                       "minutos_estimados": minutos, "muestras": int(muestras)})
    return salida


async def sugerir(db: AsyncSession, prestador_id: UUID, meses: int = 6) -> list:
    """Escribe las sugerencias donde no haya un valor configurado a mano y devuelve las filas resultantes."""
    from schemas.rutas import TiempoServicioSalida

    medidos = await medir(db, prestador_id, meses)
    nombres = dict((await db.execute(select(TipoEquipo.id, TipoEquipo.nombre))).all())
    for m in medidos:
        fila = (await db.execute(select(RutaTiempoServicio).where(
            RutaTiempoServicio.prestador_id == prestador_id,
            RutaTiempoServicio.tipo_folio == m["tipo_folio"],
            RutaTiempoServicio.tipo_equipo_id == m["tipo_equipo_id"]))).scalar_one_or_none()
        if fila is None:
            db.add(RutaTiempoServicio(
                prestador_id=prestador_id, tipo_folio=m["tipo_folio"], tipo_equipo_id=m["tipo_equipo_id"],
                minutos_estimados=m["minutos_estimados"], origen="historial", muestras=m["muestras"]))
        elif fila.origen != "configurado":
            fila.minutos_estimados = m["minutos_estimados"]
            fila.origen = "historial"
            fila.muestras = m["muestras"]
    await db.flush()
    filas = list((await db.execute(select(RutaTiempoServicio).where(
        RutaTiempoServicio.prestador_id == prestador_id).order_by(RutaTiempoServicio.tipo_folio))).scalars())
    log.info("tiempos de servicio sugeridos para %s: %s medidos sobre %s filas", prestador_id, len(medidos),
             len(filas))
    return [TiempoServicioSalida.model_validate({
        **f.__dict__, "tipo_folio": f.tipo_folio.value,
        "tipo_equipo": nombres.get(f.tipo_equipo_id) if f.tipo_equipo_id else None}) for f in filas]
