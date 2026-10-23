"""Importador CSV/Excel de catálogos (§6.3): plantilla → vista previa → confirmar o cancelar."""
import uuid
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy import select

from core.dependencias import DB, Actor, requiere_rol
from core.errors import ErrorAPI, no_encontrado, prohibido
from models.base import Dominio, Rol
from models.catalogos import EstadoImportacion, ImportacionCatalogo
from routers.catalogos_equipos import tenant_de
from routers.catalogos_tecnicos import prestador_de
from schemas.catalogos import ImportacionSalida
from schemas.comun import RESPUESTAS_ERROR
from services import auditoria, importador_service as imp
from services.almacenamiento import obtener_almacenamiento

router = APIRouter(prefix="/api/catalogos/importar", tags=["Catálogos · importador"], responses=RESPUESTAS_ERROR)

IMPORTADORES = requiere_rol(Rol.superadmin, Rol.admin_prestador, Rol.admin_empresa)
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _catalogo(clave: str) -> imp.Catalogo:
    cat = imp.CATALOGOS.get(clave)
    if cat is None:
        raise ErrorAPI(404, "CATALOGO_DESCONOCIDO", f"Catálogo «{clave}» no soportado. Disponibles: {', '.join(imp.CATALOGOS)}")
    return cat


def _ambito(actor: Actor, cat: imp.Catalogo, tenant_id: UUID | None, prestador_id: UUID | None) -> tuple[UUID | None, UUID | None]:
    """Tenant o prestador que importa, según el propietario del catálogo (§6.3)."""
    if cat.dominio == Dominio.tenant:
        if not actor.es_superadmin and actor.dominio != Dominio.tenant:
            raise prohibido(f"El catálogo {cat.nombre} lo importa el administrador del cliente")
        return tenant_de(actor, tenant_id), None
    if not actor.es_superadmin and actor.dominio != Dominio.prestador:
        raise prohibido(f"El catálogo {cat.nombre} lo importa el administrador del prestador")
    return None, prestador_de(actor, prestador_id)


def _salida(i: ImportacionCatalogo, resultado: dict | None = None) -> ImportacionSalida:
    return ImportacionSalida(
        **{k: getattr(i, k) for k in ("id", "created_at", "updated_at", "version_hash", "tenant_id", "prestador_id", "catalogo",
                                      "archivo_nombre", "total_filas", "filas_ok", "filas_error", "errores_json", "duplicados_json")},
        estado=i.estado.value, vista_previa=[{k: v for k, v in f.items() if not k.startswith("_") and k != "contrasena"} | {"fila": f["_fila"]}
                                             for f in i.filas_validas_json[:50]],
        resultado=resultado,
    )


@router.get("/catalogos", summary="Catálogos importables y sus columnas")
async def catalogos(_: Actor = Depends(IMPORTADORES)) -> list[dict]:
    return [{"clave": c.clave, "nombre": c.nombre, "propietario": c.dominio.value,
             "columnas": [{"nombre": col.nombre, "requerida": col.requerida, "descripcion": col.descripcion, "ejemplo": col.ejemplo}
                          for col in c.columnas]} for c in imp.CATALOGOS.values()]


@router.get("/{catalogo}/plantilla", summary="Descargar plantilla Excel",
            description="Hoja con las columnas requeridas y una fila de ejemplo, más una hoja de instrucciones.")
async def plantilla(catalogo: str, _: Actor = Depends(IMPORTADORES)) -> Response:
    cat = _catalogo(catalogo)
    return Response(imp.plantilla_xlsx(cat), media_type=XLSX,
                    headers={"Content-Disposition": f'attachment; filename="plantilla_{cat.clave}.xlsx"'})


@router.post("/{catalogo}", response_model=ImportacionSalida, status_code=201, summary="Subir archivo (vista previa)",
             description="Valida el CSV/Excel y devuelve filas válidas, errores (fila, columna, motivo) y duplicados. "
                         "Nada se aplica hasta confirmar. Máximo 10,000 filas.")
async def subir(catalogo: str, request: Request, db: DB, archivo: UploadFile = File(...), actor: Actor = Depends(IMPORTADORES),
                tenant_id: UUID | None = None, prestador_id: UUID | None = None):
    cat = _catalogo(catalogo)
    t, p = _ambito(actor, cat, tenant_id, prestador_id)
    contenido = await archivo.read(imp.MAX_BYTES + 1)
    nombre = archivo.filename or "archivo"
    columnas, filas = imp.leer_archivo(nombre, contenido)
    r = await imp.validar(db, cat, columnas, filas, t, p)
    clave = f"importaciones/{t or p}/{uuid.uuid4().hex}-{nombre[-80:]}"
    obtener_almacenamiento().guardar(clave, contenido, archivo.content_type or "application/octet-stream")
    i = ImportacionCatalogo(tenant_id=t, prestador_id=p, catalogo=cat.clave, archivo_nombre=nombre[:255], archivo_key=clave,
                            total_filas=r.total, filas_ok=len(r.validas), filas_error=len(r.errores), errores_json=r.errores,
                            duplicados_json=r.duplicados, filas_validas_json=r.validas, ejecutada_por=actor.id)
    db.add(i)
    await db.flush()
    await auditoria.registrar_actor(db, actor, "catalogos.importacion_vista_previa", request, tenant_id=t, prestador_id=p,
                                    recurso_tipo="importacion", recurso_id=i.id,
                                    despues={"catalogo": cat.clave, "archivo": nombre, "total": r.total, "ok": len(r.validas),
                                             "errores": len(r.errores), "duplicados": len(r.duplicados)})
    await db.commit()
    return _salida(i)


async def _importacion(db, actor: Actor, importacion_id: UUID) -> ImportacionCatalogo:
    i = (await db.execute(select(ImportacionCatalogo).where(ImportacionCatalogo.id == importacion_id))).scalar_one_or_none()
    if i is None:
        raise no_encontrado("Importación")
    if not actor.es_superadmin and i.tenant_id != actor.tenant_id and i.prestador_id != actor.prestador_id:
        raise no_encontrado("Importación")
    return i


@router.get("/{importacion_id}", response_model=ImportacionSalida, summary="Estado de una importación")
async def detalle(importacion_id: UUID, db: DB, actor: Actor = Depends(IMPORTADORES)):
    return _salida(await _importacion(db, actor, importacion_id))


@router.post("/{importacion_id}/confirmar", response_model=ImportacionSalida, summary="Confirmar importación",
             description="Aplica solo las filas válidas de la vista previa. Las filas con error y los duplicados se omiten.")
async def confirmar(importacion_id: UUID, request: Request, db: DB, actor: Actor = Depends(IMPORTADORES)):
    i = await _importacion(db, actor, importacion_id)
    if i.estado != EstadoImportacion.vista_previa:
        raise ErrorAPI(409, "IMPORTACION_CERRADA", f"La importación ya está {i.estado.value}")
    if not i.filas_validas_json:
        raise ErrorAPI(422, "SIN_FILAS_VALIDAS", "No hay filas válidas que aplicar")
    resultado = await imp.aplicar(db, i.catalogo, i.filas_validas_json, i.tenant_id, i.prestador_id, actor.id)
    i.estado = EstadoImportacion.confirmada
    i.confirmada_at = datetime.now(UTC)
    i.filas_validas_json = []  # no conservar contraseñas ni datos ya aplicados
    await db.flush()
    await auditoria.registrar_actor(db, actor, "catalogos.importacion_confirmada", request, tenant_id=i.tenant_id,
                                    prestador_id=i.prestador_id, recurso_tipo="importacion", recurso_id=i.id,
                                    despues={"catalogo": i.catalogo, **resultado})
    await db.commit()
    return _salida(i, resultado)


@router.post("/{importacion_id}/cancelar", response_model=ImportacionSalida, summary="Cancelar importación")
async def cancelar(importacion_id: UUID, request: Request, db: DB, actor: Actor = Depends(IMPORTADORES)):
    i = await _importacion(db, actor, importacion_id)
    if i.estado != EstadoImportacion.vista_previa:
        raise ErrorAPI(409, "IMPORTACION_CERRADA", f"La importación ya está {i.estado.value}")
    i.estado = EstadoImportacion.cancelada
    i.filas_validas_json = []
    await db.flush()
    await auditoria.registrar_actor(db, actor, "catalogos.importacion_cancelada", request, tenant_id=i.tenant_id,
                                    prestador_id=i.prestador_id, recurso_tipo="importacion", recurso_id=i.id)
    await db.commit()
    return _salida(i)
