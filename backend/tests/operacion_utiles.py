"""Ayudas compartidas por las pruebas de operaciones en tiempo real (F2-03)."""
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, text

from core.db import nueva_sesion
from core.rls import CONTEXTO_SISTEMA
from tests.folios_utiles import TEC, TEC2, TEC4

# Las tres unidades del cliente demo (coordenadas de seed_dev) y un punto lejos de todas.
CENTRO = (19.4326, -99.1332)
POLANCO = (19.4333, -99.1950)
COYOACAN = (19.3467, -99.1617)
AVENIDA = (19.4005, -99.1700)

TECNICOS = (TEC, TEC2, TEC4)


def ahora() -> datetime:
    return datetime.now(UTC)


def punto(lat_lng: tuple[float, float], segundos_atras: float = 0, **extra: Any) -> dict[str, Any]:
    lat, lng = lat_lng
    return {"lat": lat, "lng": lng,
            "capturada_at": (ahora() - timedelta(seconds=segundos_atras)).isoformat(),
            "precision_m": extra.pop("precision_m", 10), **extra}


async def jornada(cliente, auth, email=TEC, **cuerpo) -> dict:
    r = await cliente.post("/api/operacion/jornada/iniciar", headers=await auth(email),
                           json={"dispositivo_id": "pruebas", "acepta_aviso": True, **cuerpo})
    assert r.status_code in (200, 201), r.text
    return r.json()


async def mi_jornada(cliente, auth, email=TEC) -> dict:
    r = await cliente.get("/api/operacion/mi-jornada", headers=await auth(email))
    assert r.status_code == 200, r.text
    return r.json()


async def cerrar(cliente, auth, email=TEC) -> dict:
    r = await cliente.post("/api/operacion/jornada/cerrar", headers=await auth(email))
    assert r.status_code == 200, r.text
    return r.json()


async def enviar(cliente, auth, posiciones: list[dict], email=TEC, esperado=200) -> dict:
    r = await cliente.post("/api/operacion/posiciones", headers=await auth(email),
                           json={"posiciones": posiciones})
    assert r.status_code == esperado, r.text
    return r.json()


async def tablero(cliente, auth, email) -> dict:
    r = await cliente.get("/api/operacion/tablero", headers=await auth(email))
    assert r.status_code == 200, r.text
    return r.json()


async def tecnico_de(email: str):
    """Ficha del técnico (con su última posición y estatus) directo de la base."""
    from models.catalogos import Tecnico
    from models.usuarios import Usuario

    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        fila = (await db.execute(select(Tecnico, Usuario).join(Usuario, Usuario.id == Tecnico.usuario_id)
                                 .where(Usuario.email == email))).first()
        if fila is None:
            return None
        tecnico, usuario = fila
        coord = (await db.execute(text(
            "SELECT ST_Y(ultima_posicion::geometry) AS lat, ST_X(ultima_posicion::geometry) AS lng "
            "FROM tecnicos WHERE id = :id"), {"id": str(tecnico.id)})).first()
        return {"id": tecnico.id, "usuario_id": tecnico.usuario_id, "prestador_id": tecnico.prestador_id,
                "nombre": usuario.nombre, "estatus": tecnico.estatus_operativo.value,
                "ultima_posicion_at": tecnico.ultima_posicion_at, "bateria_pct": tecnico.ultima_bateria_pct,
                "lat": coord.lat if coord else None, "lng": coord.lng if coord else None}


async def mover(email: str, lat_lng: tuple[float, float], minutos_atras: float = 0) -> None:
    """Deja la última posición del técnico donde la prueba la necesita, sin pasar por la API."""
    from models.catalogos import Tecnico
    from models.usuarios import Usuario

    lat, lng = lat_lng
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        tecnico_id = (await db.execute(select(Tecnico.id).join(Usuario, Usuario.id == Tecnico.usuario_id)
                                       .where(Usuario.email == email))).scalar_one()
        await db.execute(text(
            "UPDATE tecnicos SET ultima_posicion = ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography, "
            "ultima_posicion_at = :at WHERE id = :id"),
            {"lng": lng, "lat": lat, "at": datetime.now(UTC) - timedelta(minutes=minutos_atras),
             "id": str(tecnico_id)})
        await db.commit()


async def sembrar_quieto(email: str, lat_lng: tuple[float, float], minutos: float = 30,
                         radio_m: float = 10) -> None:
    """Posiciones del técnico dentro de un radio pequeño durante los últimos `minutos`: el caso de tiempo muerto."""
    import random

    from geoalchemy2 import WKTElement

    from models.catalogos import Tecnico
    from models.operaciones import JornadaTecnico, TecnicoPosicion
    from models.usuarios import Usuario

    lat, lng = lat_lng
    grados = radio_m / 111_320
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        tecnico = (await db.execute(select(Tecnico).join(Usuario, Usuario.id == Tecnico.usuario_id)
                                    .where(Usuario.email == email))).scalar_one()
        jornada_abierta = (await db.execute(select(JornadaTecnico).where(
            JornadaTecnico.tecnico_id == tecnico.id, JornadaTecnico.estado != "cerrada"))).scalar_one()
        base = datetime.now(UTC)
        for i in range(int(minutos)):
            db.add(TecnicoPosicion(
                prestador_id=tecnico.prestador_id, tecnico_id=tecnico.id, jornada_id=jornada_abierta.id,
                posicion=WKTElement(
                    f"POINT({lng + random.uniform(-grados, grados)} {lat + random.uniform(-grados, grados)})",
                    srid=4326),
                precision_m=8, capturada_at=base - timedelta(minutes=minutos - i), recibida_at=base))
        await db.execute(text(
            "UPDATE tecnicos SET ultima_posicion = ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography, "
            "ultima_posicion_at = :at WHERE id = :id"),
            {"lng": lng, "lat": lat, "at": base, "id": str(tecnico.id)})
        await db.commit()


async def limpiar_posiciones(email: str | None = None) -> None:
    """Vacía el historial de posiciones para que cada escenario empiece de cero.

    `tecnico_posiciones` solo tiene políticas de SELECT e INSERT y la RLS está **forzada**, así que un DELETE no
    se lleva nada ni siquiera con el dueño del esquema: el historial es append-only y la retención se hace
    soltando particiones (igual que la auditoría de P11a). En pruebas se vacía con TRUNCATE, que es DDL y no pasa
    por la RLS; `email` se acepta por claridad en la llamada, pero el vaciado es de la tabla completa.
    """
    import os

    from sqlalchemy.ext.asyncio import create_async_engine

    duenio = create_async_engine(os.environ["TEST_DATABASE_MIGRATIONS_URL"].replace(
        "postgresql://", "postgresql+asyncpg://"), isolation_level="AUTOCOMMIT")
    try:
        async with duenio.connect() as con:
            await con.execute(text("TRUNCATE TABLE tecnico_posiciones"))
    finally:
        await duenio.dispose()


async def evaluar(clave: str) -> int:
    """Corre el evaluador de esa alerta como lo hace el beat, con el contexto del sistema."""
    from models.alertas import AlertaCatalogo
    from workers.tareas import EVALUADORES

    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        alerta = (await db.execute(select(AlertaCatalogo).where(AlertaCatalogo.clave == clave))).scalar_one()
        disparadas = await EVALUADORES[clave](db, alerta)
        await db.commit()
        return disparadas


async def seguimientos(email: str, tipo: str | None = None) -> list[dict]:
    from models.catalogos import Tecnico
    from models.operaciones import AlertaOperacionSeguimiento
    from models.usuarios import Usuario

    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        tecnico_id = (await db.execute(select(Tecnico.id).join(Usuario, Usuario.id == Tecnico.usuario_id)
                                       .where(Usuario.email == email))).scalar_one()
        consulta = select(AlertaOperacionSeguimiento).where(AlertaOperacionSeguimiento.tecnico_id == tecnico_id)
        if tipo:
            consulta = consulta.where(AlertaOperacionSeguimiento.tipo == tipo)
        filas = (await db.execute(consulta.order_by(AlertaOperacionSeguimiento.created_at.desc()))).scalars().all()
        return [{"id": s.id, "tipo": s.tipo, "push_at": s.push_al_tecnico_at, "respuesta": s.respuesta_tecnico,
                 "respondida_at": s.respondida_at, "escalada_at": s.escalada_at, "folio_id": s.folio_id,
                 "datos": s.datos_json, "created_at": s.created_at} for s in filas]


async def alertas_de(clave: str, entidad_id=None) -> list[dict]:
    from models.alertas import AlertaHistorial

    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        consulta = select(AlertaHistorial).where(AlertaHistorial.clave_alerta == clave)
        if entidad_id is not None:
            consulta = consulta.where(AlertaHistorial.entidad_id == entidad_id)
        filas = (await db.execute(consulta.order_by(AlertaHistorial.timestamp_disparo.desc()))).scalars().all()
        return [{"id": a.id, "datos": a.datos_contexto_json, "escalada": a.escalada,
                 "timestamp": a.timestamp_disparo} for a in filas]
