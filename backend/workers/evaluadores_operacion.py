"""Detección automática de la pantalla de operaciones (§6.8.4). F2-03.

Dos evaluadores, cada minuto, con los umbrales de la configuración central de alertas (P10):

* **TECNICO_TIEMPO_MUERTO** (default 20 min): el técnico en jornada activa que no se mueve —todas sus posiciones del
  periodo dentro de un radio de 50 m— en un punto que **no** es la unidad destino de su folio en curso. Dispara la
  alerta al despachador y un push al técnico preguntándole si necesita apoyo. A los 10 minutos sin respuesta,
  escala al Admin prestador.
* **TECNICO_SIN_SENAL** (default 15 min): jornada activa sin posiciones recibidas. Marca el estatus y avisa al
  despachador. **No genera emergencia**: el despachador decide qué hacer (§6.8.4).

`TECNICO_DESVIO_RUTA` sigue sin evaluador a propósito: necesita la ruta planeada del bloque de optimización de
rutas y permanece en Fase 2.
"""
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from models.alertas import AlertaCatalogo
from models.base import Rol
from models.catalogos import EstadoActivo, Tecnico
from models.folios import EstadoFolio, Folio
from models.operaciones import (
    AlertaOperacionSeguimiento, CerradaPorJornada, EstadoJornada, EstatusOperativo, JornadaTecnico,
)
from models.usuarios import Usuario
from services import alertas_service, notificaciones_service, operacion_service, push_service
from workers.tareas import registrar_evaluador

log = logging.getLogger("acma.evaluadores.operacion")


async def _jornadas_activas(db: AsyncSession) -> list[tuple[JornadaTecnico, Tecnico]]:
    filas = (await db.execute(
        select(JornadaTecnico, Tecnico).join(Tecnico, Tecnico.id == JornadaTecnico.tecnico_id)
        .where(JornadaTecnico.estado == EstadoJornada.activa, Tecnico.estado == EstadoActivo.activo))).all()
    return [(j, t) for j, t in filas]


async def _seguimiento_abierto(db: AsyncSession, tecnico_id, tipo: str) -> AlertaOperacionSeguimiento | None:
    return (await db.execute(select(AlertaOperacionSeguimiento).where(
        AlertaOperacionSeguimiento.tecnico_id == tecnico_id, AlertaOperacionSeguimiento.tipo == tipo,
        AlertaOperacionSeguimiento.respondida_at.is_(None),
        AlertaOperacionSeguimiento.created_at >= datetime.now(UTC) - timedelta(hours=8)
    ).order_by(AlertaOperacionSeguimiento.created_at.desc()).limit(1))).scalar_one_or_none()


async def _folio_en_curso(db: AsyncSession, tecnico: Tecnico) -> Folio | None:
    return (await db.execute(select(Folio).where(
        Folio.tecnico_id == tecnico.usuario_id,
        Folio.estado.in_((EstadoFolio.en_camino, EstadoFolio.en_ejecucion))
    ).order_by(Folio.orden_en_ruta.nulls_last(), Folio.capturado_at).limit(1))).scalar_one_or_none()


async def _avisar_despachador(db: AsyncSession, tecnico: Tecnico, clave: str, asunto: str, cuerpo: str,
                              datos: dict) -> None:
    destinatarios = await notificaciones_service.destinatarios_por_rol(
        db, [Rol.despachador, Rol.mesa_control], prestador_id=tecnico.prestador_id)
    if destinatarios:
        await notificaciones_service.notificar(db, "alerta", destinatarios, {"alerta": clave, **datos},
                                               asunto=asunto, cuerpo=cuerpo, url="/operaciones",
                                               prestador_id=tecnico.prestador_id)


@registrar_evaluador("TECNICO_TIEMPO_MUERTO")
async def tecnico_tiempo_muerto(db: AsyncSession, alerta: AlertaCatalogo) -> int:
    """Técnico detenido fuera de su destino: alerta al despachador y push al técnico (§6.8.4)."""
    ahora = datetime.now(UTC)
    disparadas = 0
    for jornada, tecnico in await _jornadas_activas(db):
        minutos = await operacion_service.umbral_alerta(db, tecnico.prestador_id, alerta.clave,
                                                        operacion_service.MINUTOS_TIEMPO_MUERTO)
        parametros = {**(alerta.parametros_default or {})}
        conf = await alertas_service.configuracion(db, alerta.clave, tenant_id=None,
                                                   prestador_id=tecnico.prestador_id)
        if conf is not None:
            parametros |= conf.parametros or {}
        radio = float(parametros.get("radio_m") or operacion_service.RADIO_TIEMPO_MUERTO_M)
        desde = ahora - timedelta(minutes=minutos)
        fila = (await db.execute(text("""
            SELECT count(*) AS cuantas, min(capturada_at) AS primera,
                   max(ST_Distance(posicion, (SELECT posicion FROM tecnico_posiciones
                                               WHERE tecnico_id = :t ORDER BY capturada_at DESC LIMIT 1))) AS radio_m
              FROM tecnico_posiciones WHERE tecnico_id = :t AND capturada_at >= :desde"""),
            {"t": str(tecnico.id), "desde": desde})).one()
        if not fila.cuantas or fila.cuantas < 2 or fila.radio_m is None:
            continue  # sin datos del periodo no se puede afirmar que esté detenido (eso lo ve TECNICO_SIN_SENAL)
        if float(fila.radio_m) > radio:
            continue
        # Tiene que llevar detenido el periodo completo, no solo los últimos dos puntos.
        if fila.primera > desde + timedelta(minutes=max(1.0, minutos * 0.2)):
            continue
        folio = await _folio_en_curso(db, tecnico)
        if folio is not None and await _dentro_de_la_un(db, tecnico, folio):
            continue  # está en la unidad destino: ahí no es tiempo muerto, es el trabajo
        if await _seguimiento_abierto(db, tecnico.id, alerta.clave) is not None:
            continue
        historial = await alertas_service.disparar(
            db, alerta.clave, tenant_id=None, prestador_id=tecnico.prestador_id, entidad_tipo="tecnico",
            entidad_id=tecnico.id,
            datos={"minutos": int(minutos), "radio_m": radio, "folio_id": str(folio.id) if folio else None,
                   "ultima_posicion_at": tecnico.ultima_posicion_at.isoformat() if tecnico.ultima_posicion_at else None,
                   # El feed del tablero muestra esta línea: sin ella la alerta solo decía el nombre.
                   "etiqueta": f"Sin moverse desde las {operacion_service.hora_local(ahora - timedelta(minutes=minutos))}"})
        if historial is None:
            continue
        usuario = await db.get(Usuario, tecnico.usuario_id)
        seguimiento = AlertaOperacionSeguimiento(
            prestador_id=tecnico.prestador_id, alerta_historial_id=historial.id, tipo=alerta.clave,
            tecnico_id=tecnico.id, folio_id=folio.id if folio else None, jornada_id=jornada.id,
            datos_json={"minutos": int(minutos), "radio_m": radio})
        db.add(seguimiento)
        await db.flush()
        # §6.8.4: push al técnico con dos respuestas. Si no contesta en 10 min, escala.
        try:
            enviados = await push_service.enviar_a_usuarios(
                db, [tecnico.usuario_id], "¿Todo bien?",
                f"Llevas {int(minutos)} minutos sin moverte. ¿Necesitas apoyo?",
                {"url": "/campo", "seguimiento_id": str(seguimiento.id), "tipo": alerta.clave,
                 "respuestas": ["estoy_bien", "necesito_apoyo"]})
            if enviados:
                seguimiento.push_al_tecnico_at = ahora
        except Exception:  # noqa: BLE001 — sin suscripción push el técnico lo ve al abrir la app
            log.info("Push de tiempo muerto no entregado al técnico %s", tecnico.id)
        seguimiento.push_al_tecnico_at = seguimiento.push_al_tecnico_at or ahora
        await db.flush()
        await _avisar_despachador(
            db, tecnico, alerta.clave, f"{usuario.nombre if usuario else 'Un técnico'} lleva {int(minutos)} min sin moverse",
            "Se le preguntó si necesita apoyo; si no responde en 10 minutos, se escala al Admin prestador.",
            {"tecnico": usuario.nombre if usuario else "", "tecnico_id": str(tecnico.id),
             "seguimiento_id": str(seguimiento.id)})
        await operacion_service.publicar(db, tecnico.prestador_id, {
            "evento": "alerta", "clave": alerta.clave, "tecnico_id": str(tecnico.id),
            "seguimiento_id": str(seguimiento.id), "minutos": int(minutos)})
        disparadas += 1
    return disparadas


async def _dentro_de_la_un(db: AsyncSession, tecnico: Tecnico, folio: Folio) -> bool:
    radio = int(await operacion_service.ajuste(db, tecnico.prestador_id, "operacion.geocerca_radio_m",
                                               operacion_service.RADIO_GEOCERCA_M))
    distancia = (await db.execute(text(
        "SELECT ST_Distance(un.ubicacion, t.ultima_posicion) FROM unidades_negocio un, tecnicos t "
        " WHERE un.id = :un AND t.id = :t AND un.ubicacion IS NOT NULL AND t.ultima_posicion IS NOT NULL"),
        {"un": str(folio.un_id), "t": str(tecnico.id)})).scalar()
    return distancia is not None and float(distancia) <= radio


@registrar_evaluador("TECNICO_SIN_SENAL")
async def tecnico_sin_senal(db: AsyncSession, alerta: AlertaCatalogo) -> int:
    """Jornada activa sin posiciones: marcador gris y aviso. Sin emergencia automática (§6.8.4)."""
    ahora = datetime.now(UTC)
    disparadas = 0
    for jornada, tecnico in await _jornadas_activas(db):
        minutos = await operacion_service.umbral_alerta(db, tecnico.prestador_id, alerta.clave,
                                                        operacion_service.MINUTOS_SIN_SENAL)
        limite = ahora - timedelta(minutes=minutos)
        referencia = tecnico.ultima_posicion_at or jornada.inicio
        if referencia > limite:
            continue
        await operacion_service.recalcular_estatus(db, tecnico, ahora=ahora)
        if await _seguimiento_abierto(db, tecnico.id, alerta.clave) is not None:
            continue
        usuario = await db.get(Usuario, tecnico.usuario_id)
        desde_hhmm = operacion_service.hora_local(referencia)
        historial = await alertas_service.disparar(
            db, alerta.clave, tenant_id=None, prestador_id=tecnico.prestador_id, entidad_tipo="tecnico",
            entidad_id=tecnico.id,
            datos={"minutos": int(minutos), "sin_senal_desde": referencia.isoformat(),
                   "etiqueta": f"Sin señal desde {desde_hhmm}"})
        if historial is None:
            continue
        db.add(AlertaOperacionSeguimiento(
            prestador_id=tecnico.prestador_id, alerta_historial_id=historial.id, tipo=alerta.clave,
            tecnico_id=tecnico.id, jornada_id=jornada.id,
            datos_json={"sin_senal_desde": referencia.isoformat(), "minutos": int(minutos)}))
        await db.flush()
        await _avisar_despachador(
            db, tecnico, alerta.clave,
            f"Sin señal de {usuario.nombre if usuario else 'un técnico'} desde las {desde_hhmm}",
            "No se ha recibido su posición. Decide si hay que llamarlo: el sistema no genera ninguna emergencia.",
            {"tecnico": usuario.nombre if usuario else "", "tecnico_id": str(tecnico.id)})
        await operacion_service.publicar(db, tecnico.prestador_id, {
            "evento": "alerta", "clave": alerta.clave, "tecnico_id": str(tecnico.id),
            "etiqueta": f"Sin señal desde {desde_hhmm}"})
        disparadas += 1
    return disparadas


# ----------------------------------------------------------------- escalación y cierre automático

async def escalar_sin_respuesta(db: AsyncSession, ahora: datetime | None = None) -> int:
    """§6.8.4: 10 minutos sin respuesta del técnico y la alerta de tiempo muerto escala al Admin prestador."""
    ahora = ahora or datetime.now(UTC)
    pendientes = list((await db.execute(select(AlertaOperacionSeguimiento).where(
        AlertaOperacionSeguimiento.tipo == "TECNICO_TIEMPO_MUERTO",
        AlertaOperacionSeguimiento.respondida_at.is_(None),
        AlertaOperacionSeguimiento.escalada_at.is_(None),
        AlertaOperacionSeguimiento.push_al_tecnico_at.is_not(None)))).scalars())
    escaladas = 0
    for seguimiento in pendientes:
        minutos = int(await operacion_service.ajuste(db, seguimiento.prestador_id,
                                                     "operacion.escalacion_min", operacion_service.MINUTOS_ESCALACION))
        if seguimiento.push_al_tecnico_at > ahora - timedelta(minutes=minutos):
            continue
        seguimiento.escalada_at = ahora
        tecnico = await db.get(Tecnico, seguimiento.tecnico_id)
        usuario = await db.get(Usuario, tecnico.usuario_id) if tecnico else None
        if seguimiento.alerta_historial_id:
            from models.alertas import AlertaHistorial

            historial = await db.get(AlertaHistorial, seguimiento.alerta_historial_id)
            if historial is not None:
                historial.escalada = True
        destinatarios = await notificaciones_service.destinatarios_por_rol(
            db, [Rol.admin_prestador], prestador_id=seguimiento.prestador_id)
        if destinatarios:
            await notificaciones_service.notificar(
                db, "alerta", destinatarios,
                {"alerta": seguimiento.tipo, "tecnico_id": str(seguimiento.tecnico_id), "severidad": "critica",
                 "escalada": True, "seguimiento_id": str(seguimiento.id)},
                asunto=f"Sin respuesta de {usuario.nombre if usuario else 'un técnico'} al aviso de tiempo muerto",
                cuerpo=f"Pasaron {minutos} minutos desde el aviso y no ha contestado.", url="/operaciones",
                prestador_id=seguimiento.prestador_id)
        await operacion_service.publicar(db, seguimiento.prestador_id, {
            "evento": "escalacion", "tecnico_id": str(seguimiento.tecnico_id), "tipo": seguimiento.tipo})
        escaladas += 1
    await db.flush()
    return escaladas


async def cerrar_jornadas_inactivas(db: AsyncSession, ahora: datetime | None = None) -> int:
    """Jornada que el técnico no cerró: sin posiciones ni folios abiertos en X horas, la cierra el sistema."""
    ahora = ahora or datetime.now(UTC)
    cerradas = 0
    for jornada, tecnico in await _jornadas_activas(db):
        horas = float(await operacion_service.ajuste(db, tecnico.prestador_id, "operacion.jornada_cierre_horas",
                                                     operacion_service.HORAS_CIERRE_AUTOMATICO))
        limite = ahora - timedelta(hours=horas)
        if (tecnico.ultima_posicion_at or jornada.inicio) > limite:
            continue
        if jornada.inicio > limite:
            continue
        abiertos = (await db.execute(select(Folio.id).where(
            Folio.tecnico_id == tecnico.usuario_id,
            Folio.estado.in_((EstadoFolio.en_camino, EstadoFolio.en_ejecucion))).limit(1))).first()
        if abiertos:
            continue
        await operacion_service.cerrar_jornada(db, None, jornada=jornada,  # type: ignore[arg-type]
                                               cerrada_por=CerradaPorJornada.sistema)
        cerradas += 1
    return cerradas


async def marcar_sin_senal(db: AsyncSession, ahora: datetime | None = None) -> int:
    """Pone en `sin_senal` (y recalcula lo demás) a los técnicos en jornada, para que el mapa no mienta."""
    ahora = ahora or datetime.now(UTC)
    cambiados = 0
    for _jornada, tecnico in await _jornadas_activas(db):
        anterior = tecnico.estatus_operativo
        nuevo = await operacion_service.recalcular_estatus(db, tecnico, ahora=ahora)
        if nuevo != anterior:
            cambiados += 1
    # Los que no tienen jornada no deben quedarse con un estatus viejo.
    sueltos = list((await db.execute(select(Tecnico).where(
        Tecnico.estatus_operativo != EstatusOperativo.fuera_de_jornada))).scalars())
    for tecnico in sueltos:
        if await operacion_service.jornada_abierta(db, tecnico.id) is None:
            await operacion_service.recalcular_estatus(db, tecnico, ahora=ahora)
            cambiados += 1
    return cambiados
