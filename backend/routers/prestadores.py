"""Prestadores de servicio. Alta: superadmin. Datos fiscales cifrados con AES-256; logo en MinIO."""
import json
import uuid
from uuid import UUID

from fastapi import APIRouter, Depends, File, Request, UploadFile
from sqlalchemy import select

from core.dependencias import DB, Actor, requiere_rol
from core.errors import ErrorAPI, no_encontrado, prohibido
from core.security import cifrar, descifrar
from models.base import Rol
from models.organizaciones import Prestador
from schemas.comun import RESPUESTAS_ERROR
from schemas.organizaciones import DatosFiscales, PrestadorCambios, PrestadorEntrada, PrestadorSalida
from services import auditoria, permisos_service
from services.almacenamiento import obtener_almacenamiento

router = APIRouter(prefix="/api/prestadores", tags=["Prestadores"], responses=RESPUESTAS_ERROR)

SUPERADMIN = requiere_rol(Rol.superadmin)
ADMIN = requiere_rol(Rol.superadmin, Rol.admin_prestador)
TIPOS_LOGO = {"image/png": "png", "image/jpeg": "jpg", "image/svg+xml": "svg", "image/webp": "webp"}
MAX_LOGO = 1_000_000


def _salida(p: Prestador, ver_fiscales: bool) -> PrestadorSalida:
    salida = PrestadorSalida.model_validate(p)
    if ver_fiscales and p.datos_fiscales_cifrados:
        salida.datos_fiscales = DatosFiscales(**json.loads(descifrar(p.datos_fiscales_cifrados)))
    return salida


async def _obtener(db, actor: Actor, prestador_id: UUID) -> Prestador:
    p = await db.get(Prestador, prestador_id)
    if p is None or (actor.rol != Rol.superadmin and actor.prestador_id != p.id):
        raise no_encontrado("Prestador")
    return p


@router.get("", response_model=list[PrestadorSalida], summary="Listar prestadores",
            description="superadmin ve todos; admin_prestador solo el suyo. Los datos fiscales se omiten en el listado.")
async def listar(db: DB, actor: Actor = Depends(ADMIN)):
    consulta = select(Prestador).order_by(Prestador.razon_social)
    if actor.rol != Rol.superadmin:
        consulta = consulta.where(Prestador.id == actor.prestador_id)
    return [_salida(p, False) for p in (await db.execute(consulta)).scalars()]


@router.post("", response_model=PrestadorSalida, status_code=201, summary="Crear prestador",
             description="Crea el prestador y sus permisos configurables con los valores por defecto (§6.8.3 y §6.8.3b).")
async def crear(datos: PrestadorEntrada, request: Request, db: DB, actor: Actor = Depends(SUPERADMIN)):
    valores = datos.model_dump(exclude={"datos_fiscales"})
    p = Prestador(**valores)
    if datos.datos_fiscales:
        p.datos_fiscales_cifrados = cifrar(datos.datos_fiscales.model_dump_json())
    db.add(p)
    await db.flush()
    await permisos_service.sembrar_defaults(db, p.id)
    await auditoria.registrar_actor(db, actor, "prestadores.alta", request, prestador_id=p.id, recurso_tipo="prestador",
                                    recurso_id=p.id, despues=auditoria.instantanea(p))
    await db.commit()
    return _salida(p, True)


@router.get("/{prestador_id}", response_model=PrestadorSalida, summary="Detalle de prestador",
            description="Incluye datos fiscales descifrados. El acceso queda en la auditoría.")
async def detalle(prestador_id: UUID, request: Request, db: DB, actor: Actor = Depends(ADMIN)):
    p = await _obtener(db, actor, prestador_id)
    if p.datos_fiscales_cifrados:
        await auditoria.registrar_actor(db, actor, "datos_sensibles.consulta", request, prestador_id=p.id,
                                        recurso_tipo="prestador.datos_fiscales", recurso_id=p.id)
        await db.commit()
    return _salida(p, True)


@router.patch("/{prestador_id}", response_model=PrestadorSalida, summary="Modificar prestador",
              description="admin_prestador modifica su prestador (no su estado); superadmin cualquiera.")
async def modificar(prestador_id: UUID, datos: PrestadorCambios, request: Request, db: DB, actor: Actor = Depends(ADMIN)):
    p = await _obtener(db, actor, prestador_id)
    cambios = datos.model_dump(exclude_unset=True, exclude_none=True, exclude={"datos_fiscales"})
    if actor.rol != Rol.superadmin and "estado" in cambios:
        raise prohibido("Solo el superadmin cambia el estado de un prestador")
    antes = auditoria.instantanea(p)
    for k, v in cambios.items():
        setattr(p, k, v)
    if datos.datos_fiscales is not None:
        p.datos_fiscales_cifrados = cifrar(datos.datos_fiscales.model_dump_json())
    await db.flush()
    await auditoria.registrar_actor(db, actor, "prestadores.modificacion", request, prestador_id=p.id, recurso_tipo="prestador",
                                    recurso_id=p.id, antes=antes, despues=auditoria.instantanea(p))
    await db.commit()
    await db.refresh(p)
    return _salida(p, True)


@router.post("/{prestador_id}/logo", response_model=PrestadorSalida, summary="Subir logo",
             description="PNG, JPG, SVG o WebP de hasta 1 MB. Se guarda en el almacenamiento S3 y se registra su key.")
async def subir_logo(prestador_id: UUID, request: Request, db: DB, archivo: UploadFile = File(...),
                     actor: Actor = Depends(ADMIN)):
    p = await _obtener(db, actor, prestador_id)
    extension = TIPOS_LOGO.get(archivo.content_type or "")
    if extension is None:
        raise ErrorAPI(422, "TIPO_ARCHIVO_INVALIDO", "El logo debe ser PNG, JPG, SVG o WebP")
    datos = await archivo.read(MAX_LOGO + 1)
    if len(datos) > MAX_LOGO:
        raise ErrorAPI(413, "ARCHIVO_DEMASIADO_GRANDE", "El logo no puede exceder 1 MB")
    clave = f"prestadores/{p.id}/logo-{uuid.uuid4().hex[:8]}.{extension}"
    obtener_almacenamiento().guardar(clave, datos, archivo.content_type or "application/octet-stream")
    p.logo_key = clave
    await db.flush()
    await auditoria.registrar_actor(db, actor, "prestadores.logo", request, prestador_id=p.id, recurso_tipo="prestador",
                                    recurso_id=p.id, despues={"logo_key": clave})
    await db.commit()
    await db.refresh(p)
    return _salida(p, True)
