"""Ubicacion opt-in del propio usuario, independiente de los folios.

Solo guarda ultima coordenada por usuario, nunca un recorrido. RLS forzada
protege por actor y organizacion; las posiciones caducan despues de 90 s.
"""
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.dependencias import Actor
from core.errors import ErrorAPI, prohibido
from models.base import Rol

ROLES_VISUALIZAN = {Rol.superadmin, Rol.admin_prestador, Rol.mesa_control,
                    Rol.despachador, Rol.admin_empresa}


def _sesion(actor: Actor) -> UUID:
    if actor.sesion_id is None:
        raise prohibido("Necesitas una sesión autenticada para compartir tu GPS")
    return actor.sesion_id


async def iniciar(db: AsyncSession, actor: Actor, dispositivo: str) -> dict:
    sid = _sesion(actor)
    await db.execute(text("""
        INSERT INTO rastreo_usuarios
          (usuario_id, sesion_id, tenant_id, prestador_id, dispositivo,
           lat, lng, precision_m, consentido_at, ultima_at, expira_at)
        VALUES (:id, :sid, :tenant, :prestador, :dispositivo,
                NULL, NULL, NULL, now(), NULL, now() + interval '90 seconds')
        ON CONFLICT (usuario_id) DO UPDATE SET
          sesion_id=EXCLUDED.sesion_id, tenant_id=EXCLUDED.tenant_id,
          prestador_id=EXCLUDED.prestador_id, dispositivo=EXCLUDED.dispositivo,
          lat=NULL, lng=NULL, precision_m=NULL, consentido_at=now(),
          ultima_at=NULL, expira_at=now() + interval '90 seconds'
    """), {"id": actor.id, "sid": sid, "tenant": actor.tenant_id,
           "prestador": actor.prestador_id, "dispositivo": dispositivo})
    return {"compartiendo": True, "ultima_at": None}


async def actualizar(db: AsyncSession, actor: Actor, lat: float, lng: float,
                     precision_m: float | None) -> dict:
    sid = _sesion(actor)
    if lat == 0 and lng == 0:
        raise ErrorAPI(422, "UBICACION_INVALIDA", "Coordenadas no válidas")
    fila = (await db.execute(text("""
        UPDATE rastreo_usuarios
           SET lat=:lat, lng=:lng, precision_m=:precision,
               ultima_at=now(), expira_at=now() + interval '90 seconds'
         WHERE usuario_id=:id AND sesion_id=:sid AND expira_at > now()
     RETURNING ultima_at
    """), {"lat": lat, "lng": lng, "precision": precision_m,
           "id": actor.id, "sid": sid})).first()
    if fila is None:
        raise ErrorAPI(409, "CONSENTIMIENTO_REQUERIDO",
                       "Tu sesión de ubicación venció o fue detenida; vuelve a activarla")
    return {"compartiendo": True, "ultima_at": fila[0]}


async def detener(db: AsyncSession, actor: Actor) -> dict:
    await db.execute(text("""
        DELETE FROM rastreo_usuarios WHERE usuario_id=:id AND sesion_id=:sid
    """), {"id": actor.id, "sid": _sesion(actor)})
    return {"compartiendo": False, "ultima_at": None}


async def mi_estado(db: AsyncSession, actor: Actor) -> dict:
    fila = (await db.execute(text("""
        SELECT ultima_at FROM rastreo_usuarios
         WHERE usuario_id=:id AND sesion_id=:sid AND expira_at > now()
    """), {"id": actor.id, "sid": _sesion(actor)})).first()
    return {"compartiendo": fila is not None, "ultima_at": fila[0] if fila else None}


async def usuarios_activos(db: AsyncSession, actor: Actor) -> list[dict]:
    if actor.rol not in ROLES_VISUALIZAN:
        raise prohibido("Este perfil no puede ver la ubicación de otros usuarios")
    filas = (await db.execute(text("""
        SELECT r.usuario_id, COALESCE(u.nombre, 'Usuario compartiendo') AS usuario_nombre,
               r.dispositivo, r.lat, r.lng, r.precision_m, r.ultima_at
          FROM rastreo_usuarios r
          LEFT JOIN usuarios u ON u.id = r.usuario_id
         WHERE r.expira_at > now()
           AND r.ultima_at > now() - interval '90 seconds'
           AND r.lat IS NOT NULL AND r.lng IS NOT NULL
           AND (:plataforma
              OR (:prestador_ok AND r.prestador_id=:prestador)
              OR (:tenant_ok AND r.tenant_id=:tenant))
         ORDER BY r.ultima_at DESC LIMIT 300
    """), {"plataforma": actor.es_superadmin,
           "prestador_ok": actor.rol in {Rol.admin_prestador, Rol.mesa_control, Rol.despachador},
           "prestador": actor.prestador_id,
           "tenant_ok": actor.rol == Rol.admin_empresa,
           "tenant": actor.tenant_id})).mappings().all()
    return [dict(f) for f in filas]
