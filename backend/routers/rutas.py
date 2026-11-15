"""Optimización de rutas, reasignación automática, ETA e incidencias del técnico (§6.8.2, §6.8.4). F2-06."""
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Query, Request
from sqlalchemy import func, select

from core.dependencias import DB, ActorActual
from core.errors import ErrorAPI, no_encontrado
from models.rutas import (
    DisparadorRecalculo, Mercado, MercadoUnidad, ProveedorDistancias, RutaParada, RutaPlan, RutaTiempoServicio,
    RutaTrazo,
)
from schemas.comun import Mensaje, RESPUESTAS_ERROR
from schemas.rutas import (
    CalcularEntrada, ConfiguracionRutasCambios, ConfiguracionRutasSalida, EtaSalida, IncidenciaEntrada,
    IncidenciaSalida, MercadoCambios, MercadoEntrada, MercadoSalida, MoverParadaEntrada, PlanDetalle,
    PropuestaSalida, RecalcularEntrada, RechazarPropuestaEntrada, SimulacionEntrada, TiempoServicioEntrada,
    TiempoServicioSalida, TrazoSalida, UnidadesDelMercado,
)
from services import auditoria
from services.rutas import eta as eta_service
from services.rutas import motor, planes_service, recalculo_service

router = APIRouter(prefix="/api/rutas", tags=["Optimización de rutas (VRPTW)"], responses=RESPUESTAS_ERROR)


def _prestador(actor, prestador_id: UUID | None = None) -> UUID:
    return planes_service._prestador_de(actor, prestador_id)


# ------------------------------------------------------------------ mercados
@router.get("/mercados", response_model=list[MercadoSalida], summary="Mercados del prestador",
            description="El mercado es el área de operación: agrupa las UNs de los clientes que se atienden "
                        "juntas, y es la unidad sobre la que se calcula la ruta del día.")
async def mercados(db: DB, actor: ActorActual, prestador_id: UUID | None = None, solo_activos: bool = True):
    planes_service._exigir(actor, planes_service.CONSULTAN, "consulta las rutas")
    destino = _prestador(actor, prestador_id)
    consulta = select(Mercado).where(Mercado.prestador_id == destino).order_by(Mercado.codigo)
    if solo_activos:
        consulta = consulta.where(Mercado.activo.is_(True))
    filas = list((await db.execute(consulta)).scalars())
    conteos = dict((await db.execute(select(MercadoUnidad.mercado_id, func.count())
                                     .where(MercadoUnidad.mercado_id.in_([m.id for m in filas] or [UUID(int=0)]))
                                     .group_by(MercadoUnidad.mercado_id))).all())
    return [MercadoSalida.model_validate({**m.__dict__, "unidades": conteos.get(m.id, 0)}) for m in filas]


@router.post("/mercados", response_model=MercadoSalida, status_code=201, summary="Crear un mercado")
async def crear_mercado(datos: MercadoEntrada, request: Request, db: DB, actor: ActorActual,
                        prestador_id: UUID | None = None):
    planes_service._exigir(actor, planes_service.CONFIGURAN, "configura los mercados")
    destino = _prestador(actor, prestador_id)
    if (await db.execute(select(Mercado.id).where(Mercado.prestador_id == destino,
                                                  Mercado.codigo == datos.codigo))).first():
        raise ErrorAPI(409, "MERCADO_DUPLICADO", f"Ya existe un mercado con el código {datos.codigo}")
    centro = None
    if datos.centro_lat is not None and datos.centro_lng is not None:
        centro = func.ST_GeogFromText(f"POINT({datos.centro_lng} {datos.centro_lat})")
    m = Mercado(prestador_id=destino, codigo=datos.codigo, nombre=datos.nombre,
                zona_horaria=datos.zona_horaria, centro=centro)
    db.add(m)
    await db.commit()
    await db.refresh(m)
    await auditoria.registrar_actor(db, actor, "rutas.mercado_alta", request, prestador_id=destino,
                                   recurso_tipo="mercados", recurso_id=m.id,
                                   despues={"codigo": m.codigo, "nombre": m.nombre})
    await db.commit()
    return MercadoSalida.model_validate({**m.__dict__, "unidades": 0})


@router.put("/mercados/{mercado_id}", response_model=MercadoSalida, summary="Editar un mercado")
async def editar_mercado(mercado_id: UUID, datos: MercadoCambios, request: Request, db: DB, actor: ActorActual):
    planes_service._exigir(actor, planes_service.CONFIGURAN, "configura los mercados")
    m = await motor.mercado_de(db, _prestador(actor), mercado_id)
    cambios = datos.model_dump(exclude_unset=True)
    if cambios.get("centro_lat") is not None and cambios.get("centro_lng") is not None:
        m.centro = func.ST_GeogFromText(f"POINT({cambios['centro_lng']} {cambios['centro_lat']})")
    for campo in ("nombre", "zona_horaria", "activo"):
        if campo in cambios and cambios[campo] is not None:
            setattr(m, campo, cambios[campo])
    await db.commit()
    await db.refresh(m)
    total = (await db.execute(select(func.count()).select_from(MercadoUnidad)
                              .where(MercadoUnidad.mercado_id == m.id))).scalar() or 0
    return MercadoSalida.model_validate({**m.__dict__, "unidades": total})


@router.post("/mercados/{mercado_id}/unidades", response_model=Mensaje, summary="Asignar unidades al mercado",
             description="Una UN pertenece a un mercado por prestador. Reasignarla la mueve de mercado.")
async def asignar_unidades(mercado_id: UUID, datos: UnidadesDelMercado, request: Request, db: DB,
                           actor: ActorActual):
    planes_service._exigir(actor, planes_service.CONFIGURAN, "configura los mercados")
    destino = _prestador(actor)
    m = await motor.mercado_de(db, destino, mercado_id)
    agregadas = 0
    for un_id in datos.un_ids:
        fila = (await db.execute(select(MercadoUnidad).where(
            MercadoUnidad.prestador_id == destino, MercadoUnidad.un_id == un_id))).scalar_one_or_none()
        if fila is None:
            db.add(MercadoUnidad(mercado_id=m.id, prestador_id=destino, un_id=un_id))
            agregadas += 1
        elif fila.mercado_id != m.id:
            fila.mercado_id = m.id
            agregadas += 1
    await db.commit()
    return Mensaje(mensaje=f"{agregadas} unidad(es) en el mercado {m.codigo}")


# ------------------------------------------------------------------ configuración
@router.get("/configuracion", response_model=ConfiguracionRutasSalida, summary="Pesos, jornada y umbrales",
            description="Los valores de ACT-2.1 vienen como default: distancia 1, SLA 600, criticidad 300, folio "
                        "sin asignar 5000, horas extra 240 y sin refacción 400, con jornada de 8 h, factor de "
                        "sinuosidad 1.4 y desvío de 500 m por 5 min. Se crea la primera vez que se consulta.")
async def configuracion(db: DB, actor: ActorActual, prestador_id: UUID | None = None,
                        mercado_id: UUID | None = None):
    planes_service._exigir(actor, planes_service.CONSULTAN, "consulta las rutas")
    cfg = await motor.configuracion(db, _prestador(actor, prestador_id), mercado_id)
    await db.commit()
    await db.refresh(cfg)
    return cfg


@router.put("/configuracion", response_model=ConfiguracionRutasSalida, summary="Cambiar la configuración",
            description="Solo el Admin prestador: los pesos cambian cómo se arman las rutas de todos sus técnicos.")
async def guardar_configuracion(datos: ConfiguracionRutasCambios, request: Request, db: DB, actor: ActorActual,
                                prestador_id: UUID | None = None, mercado_id: UUID | None = None):
    planes_service._exigir(actor, planes_service.CONFIGURAN, "configura las rutas")
    destino = _prestador(actor, prestador_id)
    cfg = await motor.configuracion(db, destino, mercado_id)
    antes = auditoria.instantanea(cfg)
    cambios = datos.model_dump(exclude_unset=True)
    if cambios.get("pesos_json") is not None:
        cfg.pesos_json = dict(cambios.pop("pesos_json"))
    for campo, valor in cambios.items():
        if valor is not None:
            setattr(cfg, campo, valor)
    cfg.configurado_por = actor.id
    await db.flush()
    await auditoria.registrar_actor(db, actor, "rutas.configuracion", request, prestador_id=destino,
                                   recurso_tipo="rutas_configuracion", recurso_id=cfg.id,
                                   antes=antes, despues=auditoria.instantanea(cfg))
    await db.commit()
    await db.refresh(cfg)
    return cfg


@router.get("/tiempos-servicio", response_model=list[TiempoServicioSalida],
            summary="Cuánto dura atender cada tipo de folio",
            description="Es el dato que más mueve la calidad de la ruta. ACMA sugiere el promedio real del "
                        "historial de atención del prestador y se puede ajustar por tipo de equipo.")
async def tiempos_servicio(db: DB, actor: ActorActual, prestador_id: UUID | None = None):
    planes_service._exigir(actor, planes_service.CONSULTAN, "consulta las rutas")
    from models.catalogos import TipoEquipo

    destino = _prestador(actor, prestador_id)
    filas = list((await db.execute(select(RutaTiempoServicio).where(
        RutaTiempoServicio.prestador_id == destino).order_by(RutaTiempoServicio.tipo_folio))).scalars())
    nombres = dict((await db.execute(select(TipoEquipo.id, TipoEquipo.nombre))).all())
    return [TiempoServicioSalida.model_validate({
        **f.__dict__, "tipo_folio": f.tipo_folio.value,
        "tipo_equipo": nombres.get(f.tipo_equipo_id) if f.tipo_equipo_id else None}) for f in filas]


@router.put("/tiempos-servicio", response_model=TiempoServicioSalida, summary="Fijar un tiempo de servicio")
async def guardar_tiempo_servicio(datos: TiempoServicioEntrada, request: Request, db: DB, actor: ActorActual,
                                  prestador_id: UUID | None = None):
    planes_service._exigir(actor, planes_service.CONFIGURAN, "configura las rutas")
    from models.folios import TipoFolio

    destino = _prestador(actor, prestador_id)
    tipo = TipoFolio(datos.tipo_folio)
    fila = (await db.execute(select(RutaTiempoServicio).where(
        RutaTiempoServicio.prestador_id == destino, RutaTiempoServicio.tipo_folio == tipo,
        RutaTiempoServicio.tipo_equipo_id == datos.tipo_equipo_id))).scalar_one_or_none()
    if fila is None:
        fila = RutaTiempoServicio(prestador_id=destino, tipo_folio=tipo, tipo_equipo_id=datos.tipo_equipo_id,
                                  minutos_estimados=datos.minutos_estimados, origen="configurado")
        db.add(fila)
    else:
        fila.minutos_estimados = datos.minutos_estimados
        fila.origen = "configurado"
    await db.commit()
    await db.refresh(fila)
    return TiempoServicioSalida.model_validate({**fila.__dict__, "tipo_folio": fila.tipo_folio.value,
                                                "tipo_equipo": None})


@router.post("/tiempos-servicio/sugerir", response_model=list[TiempoServicioSalida],
             summary="Sugerir los tiempos con el historial real",
             description="Promedio de `fecha_inicio_atencion` → `fecha_cierre` de los folios cerrados del "
                         "prestador, por tipo de folio y tipo de equipo. Solo escribe donde nadie configuró un "
                         "valor a mano.")
async def sugerir_tiempos(request: Request, db: DB, actor: ActorActual, prestador_id: UUID | None = None,
                          meses: int = Query(default=6, ge=1, le=36)):
    planes_service._exigir(actor, planes_service.CONFIGURAN, "configura las rutas")
    from services.rutas import tiempos_service

    destino = _prestador(actor, prestador_id)
    filas = await tiempos_service.sugerir(db, destino, meses)
    await db.commit()
    return filas


# ------------------------------------------------------------------ plan del día
@router.post("/calcular", response_model=PlanDetalle, summary="Calcular las rutas del día",
             description="Corre el optimizador y deja un plan en **borrador**: no asigna nada hasta que se "
                         "publica. Si ya hay un plan publicado del día, responde 409 y hay que usar el "
                         "recálculo parcial.")
async def calcular(datos: CalcularEntrada, request: Request, db: DB, actor: ActorActual):
    plan = await planes_service.calcular(db, actor, datos.mercado_id, datos.fecha or date.today(),
                                        request=request, prestador_id=datos.prestador_id)
    salida = await planes_service.detalle(db, actor, plan)
    await db.commit()
    return salida


@router.get("", response_model=PlanDetalle | None, summary="Plan del día de un mercado",
            description="El publicado o en curso; si no hay, el último borrador.")
async def plan_del_dia(db: DB, actor: ActorActual, mercado_id: UUID, fecha: date | None = None):
    plan = await planes_service.del_dia(db, actor, mercado_id, fecha or date.today())
    if plan is None:
        return None
    return await planes_service.detalle(db, actor, plan)


@router.get("/{plan_id}", response_model=PlanDetalle, summary="Un plan por id")
async def plan(plan_id: UUID, db: DB, actor: ActorActual):
    return await planes_service.detalle(db, actor, await planes_service.obtener(db, actor, plan_id))


@router.get("/{plan_id}/trazos", response_model=list[TrazoSalida], summary="Trazos para dibujar el mapa")
async def trazos(plan_id: UUID, db: DB, actor: ActorActual):
    from geoalchemy2 import Geometry

    from models.usuarios import Usuario

    plan = await planes_service.obtener(db, actor, plan_id)
    filas = (await db.execute(
        select(RutaTrazo, Usuario.nombre, func.ST_AsText(RutaTrazo.geometria.cast(Geometry())))
        .join(Usuario, Usuario.id == RutaTrazo.tecnico_id)
        .where(RutaTrazo.plan_id == plan.id).order_by(Usuario.nombre))).all()
    salida = []
    for trazo, nombre, texto in filas:
        puntos = []
        if texto and "(" in texto:
            for par in texto[texto.index("(") + 1:texto.rindex(")")].split(","):
                partes = par.strip().split()
                if len(partes) >= 2:
                    puntos.append([float(partes[1]), float(partes[0])])
        salida.append(TrazoSalida(tecnico_id=str(trazo.tecnico_id), tecnico=nombre,
                                  proveedor=trazo.proveedor.value, puntos=puntos))
    return salida


@router.post("/{plan_id}/paradas/{parada_id}/mover", response_model=PlanDetalle,
             summary="Mover una parada de técnico o de posición",
             description="Solo en borrador. Valida la habilidad certificada igual que la asignación (§6.8.2: "
                         "restricción dura) y recalcula las horas de las dos rutas tocadas.")
async def mover_parada(plan_id: UUID, parada_id: UUID, datos: MoverParadaEntrada, request: Request, db: DB,
                       actor: ActorActual):
    plan = await planes_service.obtener(db, actor, plan_id)
    salida = await planes_service.mover_parada(db, actor, plan, parada_id,
                                              tecnico_destino_id=datos.tecnico_destino_id,
                                              orden=datos.orden, request=request)
    await db.commit()
    return salida


@router.post("/{plan_id}/publicar", summary="Publicar el plan y asignar los folios",
             description="Lo único que toca la operación: asigna cada folio con la transición de §6.8.6, fija su "
                         "orden en ruta y avisa a cada técnico. Los folios ya asignados a mano se respetan.")
async def publicar(plan_id: UUID, request: Request, db: DB, actor: ActorActual):
    plan = await planes_service.obtener(db, actor, plan_id)
    salida = await planes_service.publicar(db, actor, plan, request=request)
    await db.commit()
    return salida


@router.post("/{plan_id}/cerrar", summary="Cerrar el plan del día")
async def cerrar(plan_id: UUID, request: Request, db: DB, actor: ActorActual):
    plan = await planes_service.obtener(db, actor, plan_id)
    await planes_service.cerrar(db, actor, plan, request=request)
    await db.commit()
    return {"plan_id": str(plan_id), "estado": "cerrado"}


# ------------------------------------------------------------------ recálculo y propuestas
@router.post("/{plan_id}/recalcular", response_model=PropuestaSalida, summary="Recalcular lo afectado",
             description="§6.8.2: recalcula **solo los folios pendientes** del técnico afectado más los huérfanos, "
                         "partiendo de dónde está cada técnico ahora. Con el modo `solo_sugerir` deja una "
                         "propuesta; con `aplicar_y_avisar` la aplica y notifica.")
async def recalcular(plan_id: UUID, datos: RecalcularEntrada, request: Request, db: DB, actor: ActorActual):
    plan = await planes_service.obtener(db, actor, plan_id)
    planes_service._exigir(actor, planes_service.CALCULAN, "recalcula rutas")
    r = await recalculo_service.recalcular_parcial(
        db, plan, disparador=datos.disparador, tecnico_id=datos.tecnico_id, folio_id=datos.folio_id,
        motivo=datos.motivo, actor=actor, request=request)
    await db.commit()
    return PropuestaSalida.model_validate({
        "id": str(r.id), "plan_id": str(r.plan_id), "disparador": r.disparador.value, "motivo": r.motivo,
        "movimientos": r.folios_movidos_json or [], "tecnicos_afectados": r.tecnicos_afectados or [],
        "vence_at": r.vence_at, "timestamp": r.timestamp, "tiempo_calculo_ms": r.tiempo_calculo_ms,
        "sin_asignar": (r.propuesta_json or {}).get("sin_asignar", [])})


@router.get("/propuestas/pendientes", response_model=list[PropuestaSalida],
            summary="Propuestas de reasignación por decidir",
            description="Lo que el tablero de operaciones muestra con aceptar/rechazar. Las vencidas se marcan "
                        "al consultar: una propuesta vieja describe una operación que ya cambió.")
async def propuestas(db: DB, actor: ActorActual, prestador_id: UUID | None = None):
    salida = await recalculo_service.pendientes(db, actor, prestador_id)
    await db.commit()
    return salida


@router.post("/propuestas/{recalculo_id}/aceptar", summary="Aceptar la propuesta y aplicarla")
async def aceptar(recalculo_id: UUID, request: Request, db: DB, actor: ActorActual):
    r = await recalculo_service.obtener(db, actor, recalculo_id)
    salida = await recalculo_service.aceptar(db, actor, r, request=request)
    await db.commit()
    return salida


@router.post("/propuestas/{recalculo_id}/rechazar", summary="Rechazar la propuesta")
async def rechazar(recalculo_id: UUID, datos: RechazarPropuestaEntrada, request: Request, db: DB,
                   actor: ActorActual):
    r = await recalculo_service.obtener(db, actor, recalculo_id)
    await recalculo_service.rechazar(db, actor, r, datos.razon, request=request)
    await db.commit()
    return {"recalculo_id": str(recalculo_id), "estado": "rechazada"}


@router.post("/{plan_id}/simulacion", summary="¿Qué pasa si…? sin aplicar nada",
             description="Mueve los folios indicados en memoria y devuelve cuánto cambia la distancia y cuántas "
                         "paradas se saldrían de ventana o de SLA. No escribe nada.")
async def simulacion(plan_id: UUID, datos: SimulacionEntrada, db: DB, actor: ActorActual):
    plan = await planes_service.obtener(db, actor, plan_id)
    planes_service._exigir(actor, planes_service.CALCULAN, "simula rutas")
    from services.rutas import simulacion_service

    return await simulacion_service.simular(db, plan, datos.movimientos)


# ------------------------------------------------------------------ ETA e incidencias
router_operacion = APIRouter(prefix="/api/operacion", tags=["Operaciones en tiempo real"],
                             responses=RESPUESTAS_ERROR)


@router_operacion.get("/eta", response_model=EtaSalida, summary="Hora estimada de llegada de un folio",
                      description="Lo que la tarjeta del folio muestra al operador: técnico y hora estimada. "
                                  "**No devuelve la posición del técnico** (§6.9.5, decidido en F2-03).")
async def eta_folio(db: DB, actor: ActorActual, folio_id: UUID):
    from models.folios import Folio

    folio = await db.get(Folio, folio_id)
    if folio is None:
        raise no_encontrado("Folio")
    # El folio es del cliente y del prestador que lo atiende: cualquiera de los dos ve su ETA, nadie más.
    if not actor.es_superadmin:
        if actor.tenant_id is not None and folio.tenant_id != actor.tenant_id:
            raise no_encontrado("Folio")
        if actor.prestador_id is not None and folio.prestador_id != actor.prestador_id:
            raise no_encontrado("Folio")
    return await eta_service.del_folio(db, folio)


@router_operacion.post("/eta/{plan_id}/refrescar", summary="Recalcular la ETA de un técnico con su posición de ahora")
async def refrescar_eta(plan_id: UUID, db: DB, actor: ActorActual, tecnico_id: UUID):
    plan = await planes_service.obtener(db, actor, plan_id)
    salida = await eta_service.recalcular_tecnico(db, plan, tecnico_id)
    await db.commit()
    return {"plan_id": str(plan_id), "tecnico_id": str(tecnico_id), "paradas": salida}


@router_operacion.get("/mi-ruta", summary="La ruta del día del técnico que la pide",
                      description="Sus paradas del plan publicado de hoy, en orden, con la hora estimada y las "
                                  "coordenadas de cada unidad para abrir la navegación. El técnico solo ve la "
                                  "suya: los endpoints de `/api/rutas` son del prestador.")
async def mi_ruta(db: DB, actor: ActorActual):
    from datetime import date

    from geoalchemy2 import Geometry

    from models.base import Rol
    from models.folios import Folio
    from models.rutas import EstadoPlanRuta
    from models.unidades import UnidadNegocio

    if not actor.es_superadmin and actor.rol != Rol.tecnico:
        raise ErrorAPI(403, "SOLO_TECNICO", "Esta es la ruta del técnico; el despachador la ve en «Rutas del día»")
    filas = (await db.execute(
        select(RutaParada, Folio, UnidadNegocio, RutaPlan,
               func.ST_Y(UnidadNegocio.ubicacion.cast(Geometry())),
               func.ST_X(UnidadNegocio.ubicacion.cast(Geometry())))
        .join(RutaPlan, RutaPlan.id == RutaParada.plan_id)
        .join(Folio, Folio.id == RutaParada.folio_id)
        .join(UnidadNegocio, UnidadNegocio.id == Folio.un_id)
        .where(RutaParada.tecnico_id == actor.id, RutaPlan.fecha == date.today(),
               RutaPlan.estado.in_((EstadoPlanRuta.publicado, EstadoPlanRuta.en_curso)))
        .order_by(RutaParada.orden))).all()
    if not filas:
        return {"tiene_ruta": False, "paradas": [],
                "mensaje": "Todavía no hay ruta publicada para hoy. El despachador la publica al inicio del día."}
    plan = filas[0][3]
    return {
        "tiene_ruta": True, "plan_id": str(plan.id), "fecha": plan.fecha,
        "km": float(sum(p.distancia_desde_anterior_km for p, *_ in filas)),
        "paradas": [{
            "folio_id": str(folio.id), "numero_folio": folio.numero_folio, "orden": parada.orden,
            "un_codigo": un.codigo, "un_nombre": un.nombre, "direccion": un.direccion,
            "estado_folio": folio.estado.value, "tipo_folio": folio.tipo_folio.value,
            "llegada_estimada": parada.llegada_estimada, "fin_estimado": parada.fin_estimado,
            "minutos_servicio": parada.minutos_servicio,
            "minutos_desde_anterior": parada.minutos_desde_anterior,
            "km_desde_anterior": float(parada.distancia_desde_anterior_km),
            "lat": float(lat) if lat is not None else None,
            "lng": float(lng) if lng is not None else None,
        } for parada, folio, un, _plan, lat, lng in filas],
    }


@router_operacion.post("/incidencia", response_model=IncidenciaSalida, status_code=201,
                       summary="El técnico reporta una incidencia",
                       description="Vehículo, salud u otra causa que le impide continuar (§6.8.2). Dispara el "
                                   "recálculo parcial de sus folios pendientes.")
async def incidencia(datos: IncidenciaEntrada, request: Request, db: DB, actor: ActorActual):
    from models.base import Rol

    if not actor.es_superadmin and actor.rol != Rol.tecnico:
        raise ErrorAPI(403, "SOLO_TECNICO", "La incidencia la reporta el técnico desde su app")
    if actor.prestador_id is None:
        raise ErrorAPI(422, "PRESTADOR_REQUERIDO", "El técnico no está asociado a un prestador")
    etiqueta = {"vehiculo": "vehículo", "salud": "salud", "otro": "otra causa"}[datos.tipo]
    motivo = f"Incidencia del técnico ({etiqueta})" + (f": {datos.detalle.strip()}" if datos.detalle.strip() else "")
    r = await recalculo_service.disparar(
        db, actor.prestador_id, DisparadorRecalculo.incidencia_tecnico, tecnico_id=actor.id,
        folio_id=datos.folio_id, motivo=motivo)
    await auditoria.registrar_actor(db, actor, "operacion.incidencia_tecnico", request,
                                   prestador_id=actor.prestador_id, recurso_tipo="usuario", recurso_id=actor.id,
                                   despues={"tipo": datos.tipo, "detalle": datos.detalle,
                                            "recalculo_id": str(r.id) if r else None})
    await db.commit()
    if r is None:
        return IncidenciaSalida(registrada=True, mensaje="Incidencia registrada. No hay ruta publicada hoy, "
                                                         "así que el despachador la atiende a mano.")
    return IncidenciaSalida(registrada=True, recalculo_id=str(r.id),
                            movimientos=len(r.folios_movidos_json or []),
                            mensaje="Incidencia registrada y ruta recalculada: el despachador la revisa.")
