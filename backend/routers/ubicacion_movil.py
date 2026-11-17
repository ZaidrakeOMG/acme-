"""Ubicación voluntaria de usuarios de ACMA Android.

Solo última posición y permiso por usuario para consultar el mapa. Sin
seguimiento en segundo plano, sin ubicaciones de usuarios sin consentimiento.
Los datos se filtran por tenant/prestador y RLS es segunda barrera.
"""
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import text

from core.dependencias import DB, Actor, ActorActual, requiere_rol
from core.errors import ErrorAPI, no_encontrado, prohibido
from models.base import Rol
from services import auditoria

router = APIRouter(prefix="/api/ubicacion-movil", tags=["Ubicación móvil"])


class Consentimiento(BaseModel):
    acepto: bool


class Coordenadas(BaseModel):
    lat: float = Field(ge=-90, le=90, allow_inf_nan=False)
    lng: float = Field(ge=-180, le=180, allow_inf_nan=False)
    precision_m: float = Field(ge=0, le=100000, allow_inf_nan=False)


class PermisoVisor(BaseModel):
    habilitado: bool


async def _puede_ver(db, actor: Actor) -> bool:
    if actor.es_superadmin:
        return True
    permiso = await db.scalar(text(
        "SELECT habilitado FROM ubicacion_movil_visores WHERE usuario_id = :uid"
    ), {"uid": actor.id})
    return permiso is True


@router.get("/estado", summary="Mi consentimiento y permiso para ver el mapa")
async def estado(db: DB, actor: ActorActual) -> dict:
    ubicacion = (await db.execute(text(
        "SELECT activa, consentimiento_at, ultima_ubicacion_at "
        "FROM ubicaciones_movil WHERE usuario_id = :uid"
    ), {"uid": actor.id})).mappings().first()
    return {
        "activa": bool(ubicacion and ubicacion["activa"]),
        "consentimiento_at": ubicacion["consentimiento_at"] if ubicacion else None,
        "ultima_ubicacion_at": ubicacion["ultima_ubicacion_at"] if ubicacion else None,
        "puede_ver_mapa": await _puede_ver(db, actor),
        "puede_administrar_visores": actor.es_superadmin,
    }


@router.post("/activar", summary="Iniciar mi ubicación tras permiso explícito")
async def activar(datos: Consentimiento, request: Request, db: DB, actor: ActorActual) -> dict:
    if not datos.acepto:
        raise ErrorAPI(422, "CONSENTIMIENTO_REQUERIDO", "Activa la ubicación expresamente desde Android.")
    await db.execute(text("""
        INSERT INTO ubicaciones_movil (
          usuario_id, tenant_id, prestador_id, activa, consentimiento_at,
          lat, lng, precision_m, ultima_ubicacion_at, actualizado_at
        ) VALUES (:uid, :tenant, :prestador, true, now(), NULL, NULL, NULL, NULL, now())
        ON CONFLICT (usuario_id) DO UPDATE SET
          tenant_id = EXCLUDED.tenant_id,
          prestador_id = EXCLUDED.prestador_id,
          activa = true, consentimiento_at = now(),
          lat = NULL, lng = NULL, precision_m = NULL,
          ultima_ubicacion_at = NULL, actualizado_at = now()
    """), {"uid": actor.id, "tenant": actor.tenant_id, "prestador": actor.prestador_id})
    await auditoria.registrar(
        db, "ubicacion_movil.activar", actor_id=actor.id, actor_rol=actor.rol.value,
        tenant_id=actor.tenant_id, prestador_id=actor.prestador_id,
        recurso_tipo="ubicaciones_movil", recurso_id=actor.id, request=request,
        despues={"consentimiento": True},
    )
    await db.commit()
    return {"activa": True, "mensaje": "Compartición iniciada. Solo mientras ACMA esté abierto."}


@router.post("/posicion", summary="Actualizar mi última ubicación visible")
async def posicion(datos: Coordenadas, db: DB, actor: ActorActual) -> dict:
    # Verificar consentimiento ANTES de aceptar una posición, incluso si la
    # última actualización fue hace menos de 15 s.
    activado = await db.scalar(text(
        "SELECT activa FROM ubicaciones_movil WHERE usuario_id = :uid"
    ), {"uid": actor.id})
    if activado is not True:
        raise prohibido("Debes activar voluntariamente el uso compartido de tu ubicación.")
    resultado = await db.execute(text("""
      UPDATE ubicaciones_movil
      SET lat = :lat, lng = :lng, precision_m = :precision,
          ultima_ubicacion_at = now(), actualizado_at = now()
      WHERE usuario_id = :uid AND activa = true
        AND (ultima_ubicacion_at IS NULL OR ultima_ubicacion_at < now() - interval '15 seconds')
      RETURNING ultima_ubicacion_at
    """), {"lat": datos.lat, "lng": datos.lng, "precision": datos.precision_m, "uid": actor.id})
    fecha = resultado.scalar_one_or_none()
    await db.commit()
    return {"aceptada": fecha is not None, "ultima_ubicacion_at": fecha}


@router.post("/detener", summary="Dejar de compartir y borrar mi última posición")
async def detener(request: Request, db: DB, actor: ActorActual) -> dict:
    # Privacidad: eliminar coordenadas y consentimiento en vez de solo marcar
    # la fila como inactiva.
    await db.execute(text("DELETE FROM ubicaciones_movil WHERE usuario_id = :uid"), {"uid": actor.id})
    await auditoria.registrar(
        db, "ubicacion_movil.detener", actor_id=actor.id, actor_rol=actor.rol.value,
        tenant_id=actor.tenant_id, prestador_id=actor.prestador_id,
        recurso_tipo="ubicaciones_movil", recurso_id=actor.id, request=request,
        despues={"consentimiento": False},
    )
    await db.commit()
    return {"activa": False, "mensaje": "Compartición detenida y última posición eliminada."}


@router.get("/mapa", summary="Últimas ubicaciones de usuarios con consentimiento")
async def mapa(request: Request, db: DB, actor: ActorActual) -> list[dict]:
    if not await _puede_ver(db, actor):
        raise prohibido("Un administrador debe habilitar tu acceso al mapa de personal.")
    # La regla de ámbito se valida en SQL y TAMBIÉN en la política RLS.
    # Un visor tenant no puede ver un usuario prestador, ni al revés.
    condiciones = ""
    params: dict = {}
    if not actor.es_superadmin:
        if actor.tenant_id:
            condiciones = " AND p.tenant_id = :org"
            params["org"] = actor.tenant_id
        elif actor.prestador_id:
            condiciones = " AND p.prestador_id = :org"
            params["org"] = actor.prestador_id
        else:
            raise prohibido("Tu usuario no pertenece a una organización de ACMA.")
    filas = (await db.execute(text(f"""
      SELECT p.usuario_id, u.nombre, u.rol::text AS rol, p.lat, p.lng,
             p.precision_m, p.ultima_ubicacion_at
      FROM ubicaciones_movil p
      JOIN usuarios u ON u.id = p.usuario_id
      WHERE p.activa = true AND p.consentimiento_at IS NOT NULL
        AND p.ultima_ubicacion_at >= now() - interval '5 minutes'
        AND u.estado = 'activo' {condiciones}
      ORDER BY p.ultima_ubicacion_at DESC
      LIMIT 500
    """), params)).mappings().all()
    await auditoria.registrar_acceso_datos(
        db, actor, request, tabla="ubicaciones_movil", registros=len(filas),
        detalle={"tipo": "posicion_actual_sin_historial"},
    )
    await db.commit()
    return [dict(fila) for fila in filas]


@router.get("/admin/usuarios", summary="Configurar quién puede consultar ubicaciones")
async def administrables(db: DB, actor: Actor = Depends(requiere_rol(Rol.superadmin))) -> list[dict]:
    filas = (await db.execute(text("""
      SELECT u.id, u.nombre, u.email, u.rol::text AS rol,
             COALESCE(v.habilitado, false) AS habilitado
      FROM usuarios u
      LEFT JOIN ubicacion_movil_visores v ON v.usuario_id = u.id
      WHERE u.estado = 'activo'
      ORDER BY u.nombre ASC
      LIMIT 1000
    """))).mappings().all()
    return [dict(fila) for fila in filas]


@router.put("/admin/usuarios/{usuario_id}", summary="Conceder o retirar lectura del mapa")
async def guardar_permiso(usuario_id: UUID, datos: PermisoVisor, request: Request, db: DB,
                          actor: Actor = Depends(requiere_rol(Rol.superadmin))) -> dict:
    usuario = await db.scalar(text("SELECT 1 FROM usuarios WHERE id = :uid AND estado = 'activo'"),
                              {"uid": usuario_id})
    if not usuario:
        raise no_encontrado("Usuario")
    await db.execute(text("""
      INSERT INTO ubicacion_movil_visores (usuario_id, habilitado, otorgado_por, actualizado_at)
      VALUES (:uid, :habilitado, :actor, now())
      ON CONFLICT (usuario_id) DO UPDATE
      SET habilitado = EXCLUDED.habilitado,
          otorgado_por = EXCLUDED.otorgado_por,
          actualizado_at = now()
    """), {"uid": usuario_id, "habilitado": datos.habilitado, "actor": actor.id})
    await auditoria.registrar(
        db, "ubicacion_movil.permiso", actor_id=actor.id, actor_rol=actor.rol.value,
        recurso_tipo="ubicacion_movil_visores", recurso_id=usuario_id, request=request,
        despues={"habilitado": datos.habilitado},
    )
    await db.commit()
    return {"usuario_id": usuario_id, "habilitado": datos.habilitado}
