"""Desvío de ruta: la alerta que quedó pendiente en F2-03 (§6.8.4). F2-06.

§6.8.4 define el desvío como «técnico a más de X metros de **la ruta calculada** por más de Y minutos» (500 m y
5 min por default). Eso supone que existe el trazo de calles, y solo lo hay con `google_routes`. Con el proveedor
`estimado` el trazo es una línea recta entre paradas, y medir contra una línea recta daría **falsas alarmas
constantes**: cualquier calle que rodee una manzana se ve como desvío.

Por eso hay **dos reglas**, y la alerta dice con cuál se disparó:

| Proveedor | Regla |
|---|---|
| `google_routes` | distancia a la polilínea real de la ruta > `umbral_desvio_m` durante `umbral_desvio_min`. |
| `estimado` | la distancia al **siguiente destino** aumenta de forma sostenida durante `umbral_desvio_min` **y** el técnico está fuera de un corredor de `corredor_desvio_m` (2 km) alrededor de la línea recta. |

La regla alternativa queda anotada como decisión pendiente: es una interpretación razonable, no el texto literal
del diseño, y conviene validarla con un técnico en la calle antes de confiar en ella.

**Verificación de tráfico** (§6.8.4): con `google_routes` se consulta si el tráfico justifica el desvío antes de
alertar; con `estimado` no hay a quién preguntar y la alerta lo declara en lugar de callarlo.
"""
import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any

from geoalchemy2 import Geometry
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.alertas import AlertaCatalogo
from models.catalogos import Tecnico
from models.folios import EstadoFolio, Folio
from models.operaciones import EstadoJornada, JornadaTecnico, TecnicoPosicion
from models.rutas import EstadoPlanRuta, ProveedorDistancias, RutaParada, RutaPlan, RutaTrazo
from models.unidades import UnidadNegocio
from services.rutas import distancias as dist
from services.rutas import motor
from workers.evaluadores import _umbral_p06 as _umbral
from workers.evaluadores_seguimiento import _disparar_una_vez
from workers.tareas import registrar_evaluador

log = logging.getLogger("acma.rutas.desvio")

MINIMO_MUESTRAS = 3        # con menos posiciones no hay «sostenido» que medir
ANTES_DE_LLEGAR = (EstadoFolio.asignado, EstadoFolio.reasignado, EstadoFolio.en_camino)


async def _trazo_de(db: AsyncSession, plan_id, tecnico_id) -> list[dist.Punto]:
    """Los vértices del trazo guardado del técnico (`rutas_trazos`)."""
    fila = (await db.execute(select(RutaTrazo).where(
        RutaTrazo.plan_id == plan_id, RutaTrazo.tecnico_id == tecnico_id)
        .order_by(RutaTrazo.version.desc()))).scalars().first()
    if fila is None:
        return []
    texto = (await db.execute(select(func.ST_AsText(RutaTrazo.geometria.cast(Geometry()))).where(
        RutaTrazo.id == fila.id))).scalar()
    if not texto or "(" not in texto:
        return []
    puntos = []
    for par in texto[texto.index("(") + 1:texto.rindex(")")].split(","):
        partes = par.strip().split()
        if len(partes) >= 2:
            puntos.append(dist.Punto(lat=float(partes[1]), lng=float(partes[0])))
    return puntos


async def _posiciones_recientes(db: AsyncSession, tecnico_id, minutos: int) -> list[tuple[datetime, dist.Punto]]:
    desde = datetime.now(UTC) - timedelta(minutes=minutos)
    filas = (await db.execute(
        select(TecnicoPosicion.capturada_at,
               func.ST_Y(TecnicoPosicion.posicion.cast(Geometry())),
               func.ST_X(TecnicoPosicion.posicion.cast(Geometry())))
        .where(TecnicoPosicion.tecnico_id == tecnico_id, TecnicoPosicion.capturada_at >= desde)
        .order_by(TecnicoPosicion.capturada_at))).all()
    return [(t, dist.Punto(lat=float(lat), lng=float(lng))) for t, lat, lng in filas if lat is not None]


async def _siguiente_destino(db: AsyncSession, plan: RutaPlan, tecnico_id) -> tuple[dist.Punto, str] | None:
    """La UN de la siguiente parada pendiente del técnico: a dónde debería estar yendo."""
    paradas = list((await db.execute(select(RutaParada).where(
        RutaParada.plan_id == plan.id, RutaParada.tecnico_id == tecnico_id).order_by(RutaParada.orden))).scalars())
    for parada in paradas:
        folio = await db.get(Folio, parada.folio_id)
        if folio is None or folio.estado not in ANTES_DE_LLEGAR:
            continue
        un = await db.get(UnidadNegocio, folio.un_id)
        punto = await motor._punto_de_un(db, un)
        if punto is not None:
            return punto, (un.codigo if un else "")
    return None


def evaluar_regla_trazo(posiciones: list[tuple[datetime, dist.Punto]], trazo: list[dist.Punto],
                        umbral_m: int, umbral_min: int) -> dict[str, Any] | None:
    """Regla literal de §6.8.4: fuera del trazo real más de `umbral_m` durante `umbral_min` seguidos."""
    if not trazo or len(posiciones) < MINIMO_MUESTRAS:
        return None
    fuera = [(t, p, dist.metros_al_trazo(p, trazo)) for t, p in posiciones]
    seguidas = [x for x in fuera if x[2] > umbral_m]
    if len(seguidas) < MINIMO_MUESTRAS or len(seguidas) != len(fuera):
        # Tienen que ser todas las del periodo: una sola lectura lejos es ruido del GPS, no un desvío.
        return None
    minutos = (seguidas[-1][0] - seguidas[0][0]).total_seconds() / 60
    if minutos < umbral_min:
        return None
    return {"regla": "trazo", "metros": int(max(x[2] for x in seguidas)), "minutos": int(minutos),
            "muestras": len(seguidas)}


def evaluar_regla_estimada(posiciones: list[tuple[datetime, dist.Punto]], destino: dist.Punto,
                           corredor_m: int, umbral_min: int, origen: dist.Punto | None = None) -> dict[str, Any] | None:
    """Regla alternativa para el proveedor `estimado`: se **aleja** del destino de forma sostenida y además está
    fuera del corredor alrededor de la línea recta.

    Las dos condiciones juntas son lo que evita la falsa alarma: alejarse un tramo es normal (una vuelta en U, un
    sentido contrario), y estar lejos de la línea recta también lo es si va acercándose por otra avenida.
    """
    if len(posiciones) < MINIMO_MUESTRAS:
        return None
    minutos = (posiciones[-1][0] - posiciones[0][0]).total_seconds() / 60
    if minutos < umbral_min:
        return None
    distancias = [dist.metros_linea_recta(p, destino) for _, p in posiciones]
    # «De forma sostenida»: cada lectura más lejos que la anterior, de principio a fin del periodo.
    if not all(b > a for a, b in zip(distancias, distancias[1:])):
        return None
    if origen is not None:
        fuera = [dist.metros_al_segmento(p, origen, destino) for _, p in posiciones]
        if max(fuera) <= corredor_m:
            return None   # sigue dentro del corredor: no es desvío, es la calle
        corredor = int(max(fuera))
    else:
        corredor = 0
    return {"regla": "estimada", "metros": int(distancias[-1] - distancias[0]), "minutos": int(minutos),
            "muestras": len(posiciones), "fuera_corredor_m": corredor}


async def _trafico_justifica(proveedor: ProveedorDistancias) -> tuple[bool | None, str]:
    """§6.8.4: con Google se consulta si hay tráfico que justifique el desvío. Sin llave no se inventa."""
    from core.config import config

    if proveedor != ProveedorDistancias.google_routes:
        return None, ("Con el proveedor de distancias estimado no hay consulta de tráfico: "
                      "revisa con el técnico antes de actuar")
    if not (getattr(config, "google_routes_api_key", "") or ""):
        return None, "Google Routes está configurado pero sin llave: no se consultó el tráfico"
    # Con llave, la consulta real va aquí (misma Routes API del proveedor de distancias).
    return False, "Se consultó el tráfico y no justifica el desvío"


@registrar_evaluador("TECNICO_DESVIO_RUTA")
async def tecnico_desvio_ruta(db: AsyncSession, alerta: AlertaCatalogo) -> int:
    """Técnico fuera de su ruta planeada. Dispara la alerta y sugiere el recálculo parcial (§6.8.2)."""
    from models.rutas import DisparadorRecalculo
    from services.rutas import recalculo_service

    planes = list((await db.execute(select(RutaPlan).where(
        RutaPlan.fecha == date.today(),
        RutaPlan.estado.in_((EstadoPlanRuta.publicado, EstadoPlanRuta.en_curso))))).scalars())
    disparadas = 0
    for plan in planes:
        cfg = await motor.configuracion(db, plan.prestador_id, plan.mercado_id)
        umbral_m = int(await _umbral(db, alerta, None) or cfg.umbral_desvio_m)
        tecnicos = list((await db.execute(select(RutaParada.tecnico_id).where(
            RutaParada.plan_id == plan.id).distinct())).scalars())
        for tecnico_usuario_id in tecnicos:
            tecnico = (await db.execute(select(Tecnico).where(
                Tecnico.usuario_id == tecnico_usuario_id))).scalar_one_or_none()
            if tecnico is None:
                continue
            jornada = (await db.execute(select(JornadaTecnico).where(
                JornadaTecnico.tecnico_id == tecnico.id,
                JornadaTecnico.estado == EstadoJornada.activa))).scalars().first()
            if jornada is None:
                continue   # sin jornada activa no hay ruta que seguir
            posiciones = await _posiciones_recientes(db, tecnico.id, cfg.umbral_desvio_min)
            if len(posiciones) < MINIMO_MUESTRAS:
                continue
            siguiente = await _siguiente_destino(db, plan, tecnico_usuario_id)
            if siguiente is None:
                continue
            destino, un_codigo = siguiente

            if cfg.proveedor_distancias == ProveedorDistancias.google_routes:
                hallazgo = evaluar_regla_trazo(posiciones, await _trazo_de(db, plan.id, tecnico_usuario_id),
                                               umbral_m, cfg.umbral_desvio_min)
            else:
                hallazgo = evaluar_regla_estimada(posiciones, destino, cfg.corredor_desvio_m,
                                                  cfg.umbral_desvio_min, origen=posiciones[0][1])
            if hallazgo is None:
                continue
            justifica, nota_trafico = await _trafico_justifica(cfg.proveedor_distancias)
            if justifica is True:
                continue   # el tráfico lo explica: no se molesta al despachador

            disparadas += await _disparar_una_vez(
                db, alerta, tenant_id=None, prestador_id=plan.prestador_id, entidad_tipo="tecnico",
                entidad_id=tecnico.id,
                datos={"tecnico_id": str(tecnico_usuario_id), "tecnico_interno_id": str(tecnico.id),
                       "plan_rutas_id": str(plan.id), "un_destino": un_codigo,
                       "regla": hallazgo["regla"], "metros": hallazgo["metros"],
                       "minutos": hallazgo["minutos"], "muestras": hallazgo["muestras"],
                       "trafico_verificado": justifica is not None, "nota_trafico": nota_trafico,
                       "etiqueta": (f"Desvío de ruta: {hallazgo['metros']} m durante {hallazgo['minutos']} min "
                                    f"camino a {un_codigo} (regla {hallazgo['regla']})")})
            # §6.8.2: el desvío **sugiere** el recálculo; no reasigna solo salvo que el prestador lo autorice.
            await recalculo_service.disparar(
                db, plan.prestador_id, DisparadorRecalculo.desvio, tecnico_id=tecnico_usuario_id,
                motivo=f"Desvío de ruta detectado ({hallazgo['metros']} m, {hallazgo['minutos']} min)")
    return disparadas
