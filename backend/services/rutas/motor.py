"""Armado del problema VRPTW desde la base y ejecución del modelo (F2-06, ACT-2.1 y ACT-2.2).

**Dos transportes, un solo modelo.** `modelo_ortools.resolver()` es el motor; este módulo decide cómo llegar a él:

- `en_proceso`: lo importa y lo corre aquí mismo. Es lo que pasa en Linux y en producción.
- `sidecar`: se lo pide por HTTP al contenedor `solver`. Es lo que pasa en Windows, donde el Control de
  aplicaciones inteligente bloquea el binario nativo de OR-Tools.
- `auto` (default): prueba en proceso y, si OR-Tools no carga, usa el contenedor.

El modelo no cambia según el transporte: el mismo archivo se monta en la imagen del contenedor. Si el solver no
responde, el cálculo **falla con un error claro** en lugar de inventar una ruta peor sin avisar.

Las consultas van **en bloque**, no por par técnico-folio: con 50 técnicos y 300 folios, preguntar la habilidad y
la refacción uno por uno serían 15,000 viajes a la base.
"""
import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from uuid import UUID

from geoalchemy2 import Geometry
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import config
from core.errors import ErrorAPI
from models.base import EstadoRegistro, Rol
from models.catalogos import (
    Equipo, EstadoActivo, FamiliaEquipo, Habilidad, Tecnico, TecnicoHabilidad, TipoEquipo,
)
from models.criticidad import ActivoCriticidad
from models.folios import EstadoFolio, Folio, FolioSLA, TipoFolio
from models.rutas import (
    PESOS_DEFAULT, Mercado, MercadoUnidad, ProveedorDistancias, RutaTiempoServicio, RutasConfiguracion,
)
from models.unidades import UnidadNegocio
from services.rutas import distancias as dist

log = logging.getLogger("acma.rutas.motor")

# Estados en los que un folio todavía se puede planear. Uno en ejecución ya tiene al técnico en la unidad: entra al
# problema pero fijo, nunca se mueve (§6.8.2).
PLANEABLES = (EstadoFolio.autorizado, EstadoFolio.asignado, EstadoFolio.reasignado, EstadoFolio.en_camino)
EN_EJECUCION = (EstadoFolio.en_ejecucion, EstadoFolio.pendiente_refaccion)


@dataclass
class ParadaProblema:
    folio_id: UUID
    numero_folio: str
    un_id: UUID
    punto: dist.Punto
    habilidad: str | None
    servicio_min: int
    criticidad: str
    sla_limite_min: int | None
    articulo_id: UUID | None
    fijo_tecnico: UUID | None
    ventana: tuple[int, int]


@dataclass
class TecnicoProblema:
    usuario_id: UUID
    nombre: str
    punto: dist.Punto
    inicio_min: int
    fin_min: int
    habilidades: set[str] = field(default_factory=set)
    articulos: set[UUID] = field(default_factory=set)


@dataclass
class Problema:
    """Lo que entra al modelo, ya con los nodos numerados: los técnicos primero, después las paradas."""
    tecnicos: list[TecnicoProblema]
    paradas: list[ParadaProblema]
    inicio_dia: datetime
    pesos: dict[str, int]
    limite_s: int
    proveedor: ProveedorDistancias
    parametros_distancia: dist.ParametrosDistancia

    @property
    def puntos(self) -> list[dist.Punto]:
        return [t.punto for t in self.tecnicos] + [p.punto for p in self.paradas]


# ------------------------------------------------------------------ configuración

async def configuracion(db: AsyncSession, prestador_id: UUID, mercado_id: UUID | None = None) -> RutasConfiguracion:
    """La del mercado si existe, si no la general del prestador, creándola con los literales de ACT-2.1."""
    from models.rutas import (
        DURACION_JORNADA_DEFAULT, FACTOR_SINUOSIDAD_DEFAULT, SEGUNDOS_LIMITE_DEFAULT, TIEMPO_SERVICIO_DEFAULT,
        VELOCIDADES_DEFAULT,
    )

    if mercado_id is not None:
        propia = (await db.execute(select(RutasConfiguracion).where(
            RutasConfiguracion.prestador_id == prestador_id,
            RutasConfiguracion.mercado_id == mercado_id))).scalar_one_or_none()
        if propia is not None:
            return propia
    general = (await db.execute(select(RutasConfiguracion).where(
        RutasConfiguracion.prestador_id == prestador_id,
        RutasConfiguracion.mercado_id.is_(None)))).scalar_one_or_none()
    if general is not None:
        return general
    # Los defaults se pasan explícitos: el `default=dict` del ORM gana al DEFAULT de la columna y dejaría los
    # pesos vacíos. Es la misma lección que F2-05 (ver `criticidad_service.configuracion`).
    general = RutasConfiguracion(
        prestador_id=prestador_id, mercado_id=None, pesos_json={**PESOS_DEFAULT},
        velocidades_json={**VELOCIDADES_DEFAULT}, factor_sinuosidad=FACTOR_SINUOSIDAD_DEFAULT,
        duracion_jornada_min=DURACION_JORNADA_DEFAULT, tiempo_servicio_default_min=TIEMPO_SERVICIO_DEFAULT,
        segundos_limite_calculo=SEGUNDOS_LIMITE_DEFAULT)
    db.add(general)
    await db.flush()
    return general


async def mercado_de(db: AsyncSession, prestador_id: UUID, mercado_id: UUID) -> Mercado:
    m = await db.get(Mercado, mercado_id)
    if m is None or m.prestador_id != prestador_id:
        raise ErrorAPI(404, "NO_ENCONTRADO", "Mercado no encontrado")
    return m


async def unidades_del_mercado(db: AsyncSession, mercado_id: UUID) -> list[UUID]:
    return list((await db.execute(select(MercadoUnidad.un_id).where(
        MercadoUnidad.mercado_id == mercado_id))).scalars())


# ------------------------------------------------------------------ datos en bloque

async def _habilidad_por_familia(db: AsyncSession) -> dict[UUID, str]:
    """Habilidad requerida por familia de equipo, con la misma regla de §6.8.6 que usa la captura."""
    filas = (await db.execute(select(FamiliaEquipo.id, FamiliaEquipo.habilidad_clave, FamiliaEquipo.nombre))).all()
    salida = {}
    for fid, clave, nombre in filas:
        salida[fid] = clave or str(nombre or "").lower().replace(" ", "_")
    return salida


async def _habilidades_certificadas(db: AsyncSession, prestador_id: UUID) -> dict[UUID, set[str]]:
    """Por usuario del técnico, las claves de habilidad **certificadas y vigentes** (F2-01, §6.10.3)."""
    hoy = date.today()
    filas = (await db.execute(
        select(Tecnico.usuario_id, Habilidad.clave, TecnicoHabilidad.certificada, TecnicoHabilidad.vigencia_hasta)
        .join(TecnicoHabilidad, TecnicoHabilidad.tecnico_id == Tecnico.id)
        .join(Habilidad, Habilidad.id == TecnicoHabilidad.habilidad_id)
        .where(Tecnico.prestador_id == prestador_id))).all()
    salida: dict[UUID, set[str]] = {}
    for usuario_id, clave, certificada, vigencia in filas:
        if not certificada or (vigencia is not None and vigencia < hoy):
            continue
        salida.setdefault(usuario_id, set()).add(clave)
    return salida


async def _articulos_en_vehiculo(db: AsyncSession, prestador_id: UUID) -> dict[UUID, set[UUID]]:
    """Artículos con existencia en el vehículo de cada técnico (P09), por usuario del técnico."""
    from models.inventario import Existencia, TipoUbicacionInventario, UbicacionInventario

    filas = (await db.execute(
        select(UbicacionInventario.tecnico_id, Existencia.articulo_id)
        .join(Existencia, Existencia.ubicacion_id == UbicacionInventario.id)
        .where(UbicacionInventario.prestador_id == prestador_id,
               UbicacionInventario.tipo == TipoUbicacionInventario.vehiculo,
               UbicacionInventario.tecnico_id.is_not(None), Existencia.cantidad > 0))).all()
    por_tecnico_id: dict[UUID, set[UUID]] = {}
    for tecnico_id, articulo_id in filas:
        por_tecnico_id.setdefault(tecnico_id, set()).add(articulo_id)
    if not por_tecnico_id:
        return {}
    usuarios = dict((await db.execute(select(Tecnico.id, Tecnico.usuario_id).where(
        Tecnico.id.in_(list(por_tecnico_id))))).all())
    return {usuarios[t]: a for t, a in por_tecnico_id.items() if t in usuarios}


async def _articulo_principal(db: AsyncSession, folio_ids: list[UUID]) -> dict[UUID, UUID]:
    """El artículo que el folio necesita, para el peso `sin_refaccion`. Se toma uno —el del material del plan o la
    refacción prevista— porque el modelo solo necesita saber si el técnico trae lo del folio, no el inventario."""
    from models.folios import FolioRefaccion
    from models.preventivos import PlanMaterial

    if not folio_ids:
        return {}
    salida: dict[UUID, UUID] = {}
    for folio_id, articulo_id in (await db.execute(select(FolioRefaccion.folio_id, FolioRefaccion.articulo_id).where(
            FolioRefaccion.folio_id.in_(folio_ids), FolioRefaccion.articulo_id.is_not(None)))).all():
        salida.setdefault(folio_id, articulo_id)
    planes = dict((await db.execute(select(Folio.id, Folio.plan_id).where(
        Folio.id.in_(folio_ids), Folio.plan_id.is_not(None)))).all())
    if planes:
        materiales: dict[UUID, UUID] = {}
        for plan_id, articulo_id in (await db.execute(select(PlanMaterial.plan_id, PlanMaterial.articulo_id).where(
                PlanMaterial.plan_id.in_(list(set(planes.values()))),
                PlanMaterial.articulo_id.is_not(None)))).all():
            materiales.setdefault(plan_id, articulo_id)
        for folio_id, plan_id in planes.items():
            if folio_id not in salida and plan_id in materiales:
                salida[folio_id] = materiales[plan_id]
    return salida


async def _tiempos_servicio(db: AsyncSession, prestador_id: UUID) -> dict[tuple[str, UUID | None], int]:
    filas = (await db.execute(select(RutaTiempoServicio).where(
        RutaTiempoServicio.prestador_id == prestador_id))).scalars()
    return {(f.tipo_folio.value, f.tipo_equipo_id): f.minutos_estimados for f in filas}


async def _jornadas_abiertas(db: AsyncSession, prestador_id: UUID) -> dict[UUID, Any]:
    from models.operaciones import EstadoJornada, JornadaTecnico

    filas = (await db.execute(
        select(JornadaTecnico, Tecnico.usuario_id)
        .join(Tecnico, Tecnico.id == JornadaTecnico.tecnico_id)
        .where(JornadaTecnico.prestador_id == prestador_id,
               JornadaTecnico.estado == EstadoJornada.activa))).all()
    return {usuario_id: j for j, usuario_id in filas}


# ------------------------------------------------------------------ armado

async def armar(db: AsyncSession, prestador_id: UUID, mercado_id: UUID, fecha: date, *,
                cfg: RutasConfiguracion | None = None,
                solo_tecnicos: list[UUID] | None = None,
                solo_folios: list[UUID] | None = None,
                posiciones: dict[UUID, dist.Punto] | None = None) -> Problema:
    """Arma el problema del día para un mercado. `solo_tecnicos`/`solo_folios` son lo que usa el recálculo parcial
    (§6.8.2: solo los folios pendientes del técnico afectado); `posiciones` permite partir de dónde está cada uno
    ahora en lugar del centro del mercado."""
    cfg = cfg or await configuracion(db, prestador_id, mercado_id)
    mercado = await mercado_de(db, prestador_id, mercado_id)
    unidades = await unidades_del_mercado(db, mercado_id)
    if not unidades:
        raise ErrorAPI(422, "MERCADO_SIN_UNIDADES",
                       "El mercado no tiene unidades de negocio asignadas: no hay a dónde ir")

    inicio_dia = datetime.combine(fecha, cfg.hora_inicio_jornada, tzinfo=UTC)

    # ------------------------------------------------- folios a planear
    estados = (*PLANEABLES, *EN_EJECUCION)
    consulta = (select(Folio, UnidadNegocio, Equipo, TipoEquipo)
                .join(UnidadNegocio, UnidadNegocio.id == Folio.un_id)
                .outerjoin(Equipo, Equipo.id == Folio.equipo_id)
                .outerjoin(TipoEquipo, TipoEquipo.id == Equipo.tipo_equipo_id)
                .where(Folio.prestador_id == prestador_id, Folio.un_id.in_(unidades),
                       Folio.estado.in_(estados)))
    if solo_folios is not None:
        consulta = consulta.where(Folio.id.in_(solo_folios or [UUID(int=0)]))
    filas = (await db.execute(consulta)).all()

    habilidad_familia = await _habilidad_por_familia(db)
    folio_ids = [f.id for f, *_ in filas]
    articulos = await _articulo_principal(db, folio_ids)
    tiempos = await _tiempos_servicio(db, prestador_id)
    criticidades = dict((await db.execute(select(ActivoCriticidad.equipo_id, ActivoCriticidad.nivel).where(
        ActivoCriticidad.equipo_id.in_([e.id for _, _, e, _ in filas if e is not None] or [UUID(int=0)])))).all())
    slas = dict((await db.execute(select(FolioSLA.folio_id, FolioSLA.tiempo_respuesta_prometido_horas).where(
        FolioSLA.folio_id.in_(folio_ids or [UUID(int=0)])))).all())

    paradas: list[ParadaProblema] = []
    for folio, un, equipo, tipo in filas:
        # Sin coordenadas no se puede rutear; el folio sale en «sin asignar» con su motivo.
        punto = await _punto_de_un(db, un)
        if punto is None:
            continue
        habilidad = habilidad_familia.get(tipo.familia_id) if tipo is not None else None
        servicio = (tiempos.get((folio.tipo_folio.value, equipo.tipo_equipo_id if equipo else None))
                    or tiempos.get((folio.tipo_folio.value, None))
                    or cfg.tiempo_servicio_default_min)
        nivel = criticidades.get(equipo.id) if equipo is not None else None
        limite = None
        horas = slas.get(folio.id)
        if horas:
            # Holgura: lo que queda del SLA de respuesta contado desde que se capturó el folio.
            vence = folio.capturado_at + timedelta(hours=int(horas))
            limite = int((vence - inicio_dia).total_seconds() // 60)
        ventana = _ventana_de(folio, inicio_dia, cfg)
        fijo = folio.tecnico_id if folio.estado in EN_EJECUCION else None
        paradas.append(ParadaProblema(
            folio_id=folio.id, numero_folio=folio.numero_folio, un_id=un.id, punto=punto, habilidad=habilidad,
            servicio_min=int(servicio), criticidad=str(nivel or equipo.criticidad if equipo else None) or "C",
            sla_limite_min=limite, articulo_id=articulos.get(folio.id), fijo_tecnico=fijo, ventana=ventana))

    # ------------------------------------------------- técnicos con jornada
    jornadas = await _jornadas_abiertas(db, prestador_id)
    certificadas = await _habilidades_certificadas(db, prestador_id)
    en_vehiculo = await _articulos_en_vehiculo(db, prestador_id)
    from models.usuarios import Usuario

    consulta_t = (select(Usuario, Tecnico)
                  .join(Tecnico, Tecnico.usuario_id == Usuario.id)
                  .where(Usuario.prestador_id == prestador_id, Usuario.rol == Rol.tecnico,
                         Usuario.estado == EstadoRegistro.activo, Tecnico.estado == EstadoActivo.activo))
    if solo_tecnicos is not None:
        consulta_t = consulta_t.where(Usuario.id.in_(solo_tecnicos or [UUID(int=0)]))
    centro = await _punto_centro(db, mercado, unidades)
    tecnicos: list[TecnicoProblema] = []
    for usuario, tecnico in (await db.execute(consulta_t)).all():
        # Solo los técnicos con jornada abierta entran: el plan del día se calcula sobre quien de verdad trabaja.
        if solo_tecnicos is None and usuario.id not in jornadas:
            continue
        punto = (posiciones or {}).get(usuario.id) or await _punto_tecnico(db, tecnico) or centro
        tecnicos.append(TecnicoProblema(
            usuario_id=usuario.id, nombre=usuario.nombre, punto=punto,
            inicio_min=0, fin_min=int(cfg.duracion_jornada_min),
            habilidades=certificadas.get(usuario.id, set()), articulos=en_vehiculo.get(usuario.id, set())))

    return Problema(tecnicos=tecnicos, paradas=paradas, inicio_dia=inicio_dia,
                    pesos={**PESOS_DEFAULT, **(cfg.pesos_json or {})},
                    limite_s=int(cfg.segundos_limite_calculo), proveedor=cfg.proveedor_distancias,
                    parametros_distancia=dist.ParametrosDistancia.desde(cfg))


def _ventana_de(folio: Folio, inicio_dia: datetime, cfg: RutasConfiguracion) -> tuple[int, int]:
    """Ventana del folio en minutos desde el inicio del día. La del folio (P04) manda; si no tiene, la jornada."""
    desde, hasta = 0, int(cfg.duracion_jornada_min)
    if folio.ventana_inicio is not None:
        desde = max(0, int((folio.ventana_inicio - inicio_dia).total_seconds() // 60))
    if folio.ventana_fin is not None:
        hasta = max(desde, int((folio.ventana_fin - inicio_dia).total_seconds() // 60))
    return desde, hasta


async def _punto_de_un(db: AsyncSession, un: UnidadNegocio) -> dist.Punto | None:
    fila = (await db.execute(select(func.ST_Y(UnidadNegocio.ubicacion.cast(Geometry())),
                                    func.ST_X(UnidadNegocio.ubicacion.cast(Geometry())))
                             .where(UnidadNegocio.id == un.id))).first()
    if not fila or fila[0] is None:
        return None
    return dist.Punto(lat=float(fila[0]), lng=float(fila[1]))


async def _punto_tecnico(db: AsyncSession, tecnico: Tecnico) -> dist.Punto | None:
    """Se consulta en SQL, no por el atributo del objeto: una columna GEOGRAPHY recién escrita con una función SQL
    está expirada en el ORM y leerla dispararía IO donde no se puede (MissingGreenlet)."""
    fila = (await db.execute(select(func.ST_Y(Tecnico.ultima_posicion.cast(Geometry())),
                                    func.ST_X(Tecnico.ultima_posicion.cast(Geometry())))
                             .where(Tecnico.id == tecnico.id))).first()
    if not fila or fila[0] is None:
        return None
    return dist.Punto(lat=float(fila[0]), lng=float(fila[1]))


async def _punto_centro(db: AsyncSession, mercado: Mercado, unidades: list[UUID]) -> dist.Punto:
    """Donde arranca un técnico sin posición conocida: el centro del mercado, o el promedio de sus unidades."""
    fila = (await db.execute(select(func.ST_Y(Mercado.centro.cast(Geometry())),
                                    func.ST_X(Mercado.centro.cast(Geometry())))
                             .where(Mercado.id == mercado.id))).first()
    if fila and fila[0] is not None:
        return dist.Punto(lat=float(fila[0]), lng=float(fila[1]))
    fila = (await db.execute(select(func.avg(func.ST_Y(UnidadNegocio.ubicacion.cast(Geometry()))),
                                    func.avg(func.ST_X(UnidadNegocio.ubicacion.cast(Geometry()))))
                             .where(UnidadNegocio.id.in_(unidades),
                                    UnidadNegocio.ubicacion.is_not(None)))).first()
    if fila and fila[0] is not None:
        return dist.Punto(lat=float(fila[0]), lng=float(fila[1]))
    return dist.Punto(lat=19.4326, lng=-99.1332)   # Ciudad de México, para no dejar el problema sin origen


# ------------------------------------------------------------------ ejecución

def transporte_efectivo() -> str:
    from services.rutas import modelo_ortools

    modo = (config.rutas_motor_transporte or "auto").lower()
    if modo == "en_proceso":
        return "en_proceso"
    if modo == "sidecar":
        return "sidecar"
    return "en_proceso" if modelo_ortools.ortools_disponible() else "sidecar"


async def resolver(db: AsyncSession, problema: Problema) -> dict[str, Any]:
    """Arma las matrices, corre el modelo por el transporte que toque y devuelve el resultado del modelo."""
    metros, segundos = await dist.matriz(db, problema.puntos, problema.inicio_dia,
                                         proveedor=problema.proveedor,
                                         parametros=problema.parametros_distancia)
    crudo = {
        "tecnicos": [{"id": str(t.usuario_id), "nodo_inicio": i, "inicio_s": t.inicio_min * 60,
                      "fin_s": t.fin_min * 60, "habilidades": sorted(t.habilidades),
                      "refacciones": [str(a) for a in sorted(t.articulos, key=str)]}
                     for i, t in enumerate(problema.tecnicos)],
        "paradas": [{"id": str(p.folio_id), "nodo": len(problema.tecnicos) + j,
                     "habilidad": p.habilidad, "servicio_s": p.servicio_min * 60,
                     "ventana": [p.ventana[0] * 60, p.ventana[1] * 60], "criticidad": p.criticidad,
                     "sla_limite_s": None if p.sla_limite_min is None else p.sla_limite_min * 60,
                     "articulo": str(p.articulo_id) if p.articulo_id else None,
                     "fijo_tecnico": str(p.fijo_tecnico) if p.fijo_tecnico else None}
                    for j, p in enumerate(problema.paradas)],
        "segundos": segundos, "metros": metros, "pesos": problema.pesos, "limite_s": problema.limite_s,
    }
    modo = transporte_efectivo()
    if modo == "en_proceso":
        from services.rutas import modelo_ortools

        return {**modelo_ortools.resolver(crudo), "transporte": "en_proceso"}
    return {**await _por_sidecar(crudo, problema.limite_s), "transporte": "sidecar"}


async def _por_sidecar(crudo: dict[str, Any], limite_s: int) -> dict[str, Any]:
    import asyncio

    import httpx

    url = config.rutas_solver_url.rstrip("/") + "/resolver"
    ultimo: Exception | None = None
    # Tres intentos con espera creciente. El contenedor se reinicia solo (`restart: unless-stopped`) y mientras
    # arranca deja caer la conexión; en un equipo con poca memoria eso pasa de verdad, y un reinicio del solver no
    # debe verse como «no hay ruta». Las esperas suman ~6 s en el peor caso.
    for intento, espera in enumerate((1, 5, 0)):
        try:
            async with httpx.AsyncClient(timeout=limite_s + 30) as cliente:
                r = await cliente.post(url, json=crudo)
                r.raise_for_status()
                return r.json()
        except Exception as e:  # noqa: BLE001
            ultimo = e
            if espera:
                await asyncio.sleep(espera)
    # Mejor un error claro que una ruta inventada: el despachador tiene que saber que el motor no respondió.
    raise ErrorAPI(503, "SOLVER_NO_DISPONIBLE",
                   f"El optimizador de rutas no respondió en {url}. Levántalo con "
                   f"«docker compose up -d solver» y vuelve a calcular.",
                   [{"detalle": str(ultimo)[:200]}]) from ultimo
