"""Biblioteca de manuales y contenido de servicio contractual (§6.10.4). F2-01."""
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile

from core.dependencias import DB, Actor, ActorActual, requiere_rol
from core.errors import no_encontrado, prohibido
from models.capacitacion import CategoriaManual
from schemas.capacitacion import (
    ApoyoDeFolioSalida, ContenidoEntrada, ContenidoGuardado, ContenidoSalida, DescargaOfflineEntrada,
    DescargaOfflineSalida, EnlaceDescargaSalida, ManualSalida, VersionManualSalida,
)
from schemas.comun import Mensaje, RESPUESTAS_ERROR
from services import biblioteca_service as svc

router = APIRouter(prefix="/api/biblioteca", tags=["Biblioteca de manuales"], responses=RESPUESTAS_ERROR)

GESTIONAN_MANUALES = requiere_rol(*svc.GESTIONAN_MANUALES)
GESTIONAN_CONTENIDO = requiere_rol(*svc.GESTIONAN_CONTENIDO)
CONSULTAN_MANUALES = requiere_rol(*svc.CONSULTAN_MANUALES)
CONSULTAN_CONTENIDO = requiere_rol(*svc.CONSULTAN_CONTENIDO)


# ------------------------------------------------------------------ manuales
@router.get("/manuales", response_model=list[ManualSalida], summary="Manuales vigentes",
            description="Con `solo_mis_folios` el técnico ve solo los de los tipos de equipo de sus folios "
                        "asignados. El técnico necesita el permiso `acceder_manuales` (§6.8.3).")
async def listar_manuales(db: DB, actor: Actor = Depends(CONSULTAN_MANUALES),
                          tipo_equipo_id: UUID | None = None, solo_mis_folios: bool = False,
                          q: str | None = Query(default=None, max_length=100)):
    return await svc.listar_manuales(db, actor, tipo_equipo_id=tipo_equipo_id, q=q,
                                     solo_mis_folios=solo_mis_folios)


@router.post("/manuales", response_model=ManualSalida, status_code=201, summary="Subir un manual",
             description="Multipart. PDF, imágenes o video corto, hasta 50 MB.")
async def subir_manual(request: Request, db: DB, actor: Actor = Depends(GESTIONAN_MANUALES),
                       tipo_equipo_id: UUID = Form(...), titulo: str = Form(...),
                       categoria: CategoriaManual = Form(default=CategoriaManual.otro),
                       descripcion: str = Form(default=""), archivo: UploadFile = File(...)):
    contenido = await archivo.read(svc.MAX_BYTES + 1)
    manual = await svc.subir_manual(db, actor, request, tipo_equipo_id=tipo_equipo_id, titulo=titulo,
                                    categoria=categoria, descripcion=descripcion,
                                    archivo=(contenido, archivo.filename or "manual",
                                             archivo.content_type or "application/pdf"))
    await db.commit()
    return await svc.fila_de_manual(db, manual.id)


@router.post("/manuales/{manual_id}/versiones", response_model=ManualSalida, status_code=201,
             summary="Subir una versión nueva",
             description="Reemplaza la vigente y conserva la anterior en el historial (§6.10.4).")
async def nueva_version(manual_id: UUID, request: Request, db: DB, actor: Actor = Depends(GESTIONAN_MANUALES),
                        notas: str = Form(default=""), archivo: UploadFile = File(...)):
    contenido = await archivo.read(svc.MAX_BYTES + 1)
    manual = await svc.nueva_version(db, actor, request, manual_id,
                                     archivo=(contenido, archivo.filename or "manual",
                                              archivo.content_type or "application/pdf"), notas=notas)
    await db.commit()
    return await svc.fila_de_manual(db, manual.id)


@router.get("/manuales/{manual_id}/versiones", response_model=list[VersionManualSalida],
            summary="Historial de versiones (solo Admin prestador)")
async def versiones(manual_id: UUID, db: DB, actor: Actor = Depends(GESTIONAN_MANUALES)):
    return await svc.versiones(db, actor, manual_id)


@router.delete("/manuales/{manual_id}", response_model=Mensaje, summary="Desactivar un manual")
async def desactivar(manual_id: UUID, request: Request, db: DB, actor: Actor = Depends(GESTIONAN_MANUALES)):
    await svc.desactivar_manual(db, actor, request, manual_id)
    await db.commit()
    return Mensaje(mensaje="Manual desactivado")


# ------------------------------------------------------------------ descargas
@router.get("/manuales/{manual_id}/enlace", response_model=EnlaceDescargaSalida,
            summary="Enlace firmado de 5 minutos para abrir el manual",
            description="Los archivos se guardan cifrados con la llave de su dueño (P11a), así que los sirve la "
                        "API: este enlace permite al visor del navegador abrirlos sin cabecera de autorización.")
async def enlace_manual(manual_id: UUID, db: DB, actor: ActorActual,
                        version: int | None = Query(default=None, ge=1)):
    manual = await svc.obtener_manual(db, actor, manual_id)
    if actor.rol not in svc.CONSULTAN_MANUALES:
        raise prohibido("Tu rol no consulta la biblioteca")
    if actor.rol.value == "tecnico":
        await svc._exigir_permiso_manuales(db, actor)
    if version is not None and version != manual.version and actor.rol not in svc.GESTIONAN_MANUALES:
        raise prohibido("Las versiones anteriores solo las consulta el Admin prestador")
    token = svc.firmar_descarga(clase="manual", recurso_id=manual_id, usuario_id=actor.id,
                                version=version or manual.version)
    return EnlaceDescargaSalida(url=f"/api/biblioteca/archivo?token={token}",
                                expira_en_segundos=svc.MINUTOS_DESCARGA * 60,
                                nombre=manual.nombre_original, mime=manual.mime)


@router.get("/contenido/{contenido_id}/enlace", response_model=EnlaceDescargaSalida,
            summary="Enlace firmado del documento del contenido de servicio")
async def enlace_contenido(contenido_id: UUID, db: DB, actor: ActorActual):
    if actor.rol not in svc.CONSULTAN_CONTENIDO:
        raise prohibido("Tu rol no consulta el contenido de servicio")
    lista = await svc.listar_contenido(db, actor)
    elegido = next((c for c in lista if c["id"] == contenido_id and c["tiene_archivo"]), None)
    if elegido is None:
        raise no_encontrado("Documento del contenido de servicio")
    token = svc.firmar_descarga(clase="contenido", recurso_id=contenido_id, usuario_id=actor.id,
                                version=elegido["version"])
    return EnlaceDescargaSalida(url=f"/api/biblioteca/archivo?token={token}",
                                expira_en_segundos=svc.MINUTOS_DESCARGA * 60,
                                nombre=f"{elegido['titulo']}.pdf", mime="application/pdf")


@router.get("/archivo", summary="Servir el archivo de un enlace firmado",
            description="El token lleva el recurso, la versión y el usuario; vence en 5 minutos. No necesita "
                        "cabecera de autorización porque la firma ya identifica al usuario.")
async def archivo(token: str = Query(..., min_length=20)) -> Response:
    datos, nombre, mime = await svc.archivo_firmado(token)
    return Response(datos, media_type=mime,
                    headers={"Content-Disposition": f'inline; filename="{nombre}"',
                             "Cache-Control": "no-store"})


# ------------------------------------------------------------------ contenido de servicio
@router.get("/contenido", response_model=list[ContenidoSalida], summary="Contenido de servicio contractual",
            description="El cliente ve el suyo; el técnico, solo el de los folios que tiene asignados (§6.10.4).")
async def listar_contenido(db: DB, actor: Actor = Depends(CONSULTAN_CONTENIDO),
                           tipo_equipo_id: UUID | None = None, incluir_inactivos: bool = False):
    return await svc.listar_contenido(db, actor, tipo_equipo_id=tipo_equipo_id,
                                      incluir_inactivos=incluir_inactivos)


@router.post("/contenido", response_model=ContenidoGuardado, status_code=201,
             summary="Definir o reemplazar el contenido de servicio",
             description="Si ya había uno vigente para ese contrato y tipo de equipo, se archiva y este nace con la "
                         "versión siguiente. Si no coincide con la iguala del contrato, devuelve avisos sin bloquear.")
async def guardar_contenido(datos: ContenidoEntrada, request: Request, db: DB,
                            actor: Actor = Depends(GESTIONAN_CONTENIDO)):
    contenido, avisos = await svc.guardar_contenido(
        db, actor, request, tipo_equipo_id=datos.tipo_equipo_id, contrato_id=datos.contrato_id,
        titulo=datos.titulo, puntos_revision=[p.model_dump() for p in datos.puntos_revision],
        periodicidad=datos.periodicidad, correctivos_iguala=datos.correctivos_iguala,
        preventivos_iguala=datos.preventivos_iguala)
    await db.commit()
    lista = await svc.listar_contenido(db, actor, tipo_equipo_id=datos.tipo_equipo_id)
    fila = next((c for c in lista if c["id"] == contenido.id), None)
    if fila is None:
        raise no_encontrado("Contenido de servicio")
    return ContenidoGuardado(contenido=ContenidoSalida(**fila), avisos=avisos)


@router.post("/contenido/{contenido_id}/documento", response_model=ContenidoSalida,
             summary="Adjuntar el documento del contenido de servicio")
async def subir_documento(contenido_id: UUID, request: Request, db: DB,
                          actor: Actor = Depends(GESTIONAN_CONTENIDO), archivo: UploadFile = File(...)):
    from models.capacitacion import ContenidoServicio
    from services.almacenamiento import dueno_de, obtener_almacenamiento

    contenido = await db.get(ContenidoServicio, contenido_id)
    if contenido is None or contenido.tenant_id != actor.tenant_id:
        raise no_encontrado("Contenido de servicio")
    datos = await archivo.read(svc.MAX_BYTES + 1)
    extension = svc._validar_archivo(datos, archivo.content_type or "application/pdf")
    contenido.archivo_key = f"contenido_servicio/{contenido.tenant_id}/{contenido.id}/v{contenido.version}.{extension}"
    contenido.nombre_original = (archivo.filename or "contenido")[:255]
    contenido.mime, contenido.bytes = archivo.content_type or "application/pdf", len(datos)
    obtener_almacenamiento().guardar(contenido.archivo_key, datos, contenido.mime,
                                     dueno=dueno_de(contenido.tenant_id, None))
    await db.flush()
    from services import auditoria

    await auditoria.registrar_actor(db, actor, "biblioteca.contenido_documento", request,
                                    recurso_tipo="contenido_servicio", recurso_id=contenido.id,
                                    despues={"bytes": len(datos)})
    await db.commit()
    lista = await svc.listar_contenido(db, actor, tipo_equipo_id=contenido.tipo_equipo_id)
    fila = next((c for c in lista if c["id"] == contenido_id), None)
    if fila is None:
        raise no_encontrado("Contenido de servicio")
    return ContenidoSalida(**fila)


# ------------------------------------------------------------------ uso sin señal
@router.get("/offline", response_model=list[DescargaOfflineSalida],
            summary="Lo que el técnico tiene guardado en su dispositivo",
            description="Marca lo desactualizado cuando hay una versión más nueva del manual o del contenido.")
async def mis_descargas(db: DB, actor: ActorActual):
    return await svc.mis_descargas(db, actor)


@router.post("/offline", response_model=Mensaje, status_code=201,
             summary="Registrar que un archivo se guardó o se borró del dispositivo",
             description="Lo llama la app del técnico; sin señal viaja por la cola de mutaciones de P05.")
async def registrar_descarga(datos: DescargaOfflineEntrada, db: DB, actor: ActorActual):
    await svc.registrar_descarga(db, actor, manual_id=datos.manual_id, contenido_id=datos.contenido_id,
                                 version=datos.version, dispositivo_id=datos.dispositivo_id,
                                 en_dispositivo=datos.en_dispositivo)
    await db.commit()
    return Mensaje(mensaje="Registrado" if datos.en_dispositivo else "Borrado registrado")


# ------------------------------------------------------------------ apoyo durante la atención
@router.get("/folios/{folio_id}/apoyo", response_model=ApoyoDeFolioSalida,
            summary="Puntos de revisión y manuales del folio",
            description="Una sola llamada para la app del técnico al abrir el folio (§6.10.4). Lo que el rol no "
                        "puede consultar viene vacío en lugar de dar 403.")
async def apoyo_de_folio(folio_id: UUID, db: DB, actor: ActorActual):
    return await svc.apoyo_de_folio(db, actor, folio_id)
