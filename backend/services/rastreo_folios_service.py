"""Rastreo opt-in del propio usuario asociado al folio, no rastreo de terceros.

Android, iOS y desktop usan HTTPS y el permiso nativo del navegador. Se guarda
solo el ultimo punto y caduca a los 90 s. La consulta del supervisor es de
solo lectura, limitada al prestador del folio.
"""
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.dependencias import Actor
from core.errors import ErrorAPI, no_encontrado, prohibido
from models.folios import ESTADOS_FINALES, Folio


async def folio_propio(db: AsyncSession, actor: Actor, folio_id: UUID, *, permitir_cerrado: bool = False) -> Folio:
    folio = await db.get(Folio, folio_id)
    if folio is None:
        raise no_encontrado("Folio")
    if not (actor.es_superadmin or folio.capturado_por == actor.id or folio.tecnico_id == actor.id):
        raise prohibido("Solo quien capturo el folio o el tecnico asignado puede compartir SU ubicacion")
    if not permitir_cerrado and folio.estado in ESTADOS_FINALES:
        raise ErrorAPI(409, "FOLIO_FINALIZADO", "El folio ya finalizo; no admite rastreo")
    if actor.sesion_id is None:
        raise prohibido("Necesitas una sesion vigente para compartir la ubicacion")
    return folio


async def empezar(db: AsyncSession, actor: Actor, folio_id: UUID) -> dict:
    folio = await folio_propio(db, actor, folio_id)
    await db.execute(text("""
        INSERT INTO rastreos_usuario_folio
            (folio_id, usuario_id, sesion_id, prestador_id, lat, lng, precision_m, aceptado_at, ultima_at, expira_at)
        VALUES (:folio, :usuario, :sesion, :prestador, NULL, NULL, NULL, now(), NULL,
                now() + interval '90 seconds')
        ON CONFLICT (folio_id, usuario_id) DO UPDATE
        SET sesion_id = EXCLUDED.sesion_id, prestador_id = EXCLUDED.prestador_id,
            lat = NULL, lng = NULL, precision_m = NULL, ultima_at = NULL,
            aceptado_at = now(), expira_at = now() + interval '90 seconds'
    """), {"folio": folio.id, "usuario": actor.id, "sesion": actor.sesion_id,
           "prestador": folio.prestador_id})
    return {"compartiendo": True, "ultima_at": None}


async def actualizar(db: AsyncSession, actor: Actor, folio_id: UUID,
                     lat: float, lng: float, precision_m: float | None) -> dict:
    await folio_propio(db, actor, folio_id)
    if lat == 0 and lng == 0:
        raise ErrorAPI(422, "UBICACION_INVALIDA", "El GPS no entrego coordenadas validas")
    fila = (await db.execute(text("""
        UPDATE rastreos_usuario_folio
           SET lat = :lat, lng = :lng, precision_m = :precision,
               ultima_at = now(), expira_at = now() + interval '90 seconds'
         WHERE folio_id = :folio AND usuario_id = :usuario AND sesion_id = :sesion
           AND expira_at > now()
     RETURNING ultima_at
    """), {"lat": lat, "lng": lng, "precision": precision_m, "folio": folio_id,
           "usuario": actor.id, "sesion": actor.sesion_id})).first()
    if fila is None:
        raise ErrorAPI(409, "CONSENTIMIENTO_REQUERIDO",
                       "La sesion de compartir ubicacion caduco; activala de nuevo")
    return {"compartiendo": True, "ultima_at": fila[0]}


async def detener(db: AsyncSession, actor: Actor, folio_id: UUID) -> dict:
    await folio_propio(db, actor, folio_id, permitir_cerrado=True)
    await db.execute(text("""
        DELETE FROM rastreos_usuario_folio
         WHERE folio_id = :folio AND usuario_id = :usuario AND sesion_id = :sesion
    """), {"folio": folio_id, "usuario": actor.id, "sesion": actor.sesion_id})
    return {"compartiendo": False, "ultima_at": None}


async def mi_estado(db: AsyncSession, actor: Actor, folio_id: UUID) -> dict:
    await folio_propio(db, actor, folio_id, permitir_cerrado=True)
    fila = (await db.execute(text("""
        SELECT ultima_at FROM rastreos_usuario_folio
         WHERE folio_id = :folio AND usuario_id = :usuario AND sesion_id = :sesion
           AND expira_at > now()
    """), {"folio": folio_id, "usuario": actor.id, "sesion": actor.sesion_id})).first()
    return {"compartiendo": fila is not None, "ultima_at": fila[0] if fila else None}


async def ubicaciones_compartidas(db: AsyncSession, actor: Actor) -> list[dict]:
    # defensa en profundidad; el router también exige el rol de despacho.
    from services.operacion_service import VEN_TABLERO
    if actor.rol not in VEN_TABLERO:
        raise prohibido("Solo personal de despacho puede ver el GPS de otros usuarios")
    filas = (await db.execute(text("""
        SELECT r.folio_id, r.usuario_id, u.nombre, r.lat, r.lng,
               r.precision_m, r.ultima_at
          FROM rastreos_usuario_folio r
          JOIN folios f ON f.id = r.folio_id
          JOIN usuarios u ON u.id = r.usuario_id
         WHERE r.expira_at > now()
           AND r.ultima_at > now() - interval '90 seconds'
           AND r.lat IS NOT NULL AND r.lng IS NOT NULL
           AND f.estado::text NOT IN ('cerrado', 'cancelado')
           AND (:plataforma OR r.prestador_id = :prestador)
         ORDER BY r.ultima_at DESC
         LIMIT 300
    """), {"plataforma": actor.es_superadmin, "prestador": actor.prestador_id})).mappings().all()
    return [dict(f) for f in filas]
