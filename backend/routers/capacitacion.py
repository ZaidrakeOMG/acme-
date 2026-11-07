"""Capacitación y certificación de técnicos (§6.10.3). F2-01."""
import io
from datetime import date
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile
from openpyxl import Workbook

from core.dependencias import DB, Actor, ActorActual, requiere_rol
from core.errors import no_encontrado
from models.capacitacion import TecnicoCurso
from schemas.capacitacion import (
    AlertasConfigEntrada, AlertasConfigSalida, CursoCambios, CursoEntrada, CursoSalida, ExpedienteSalida,
    RegistroCursoEntrada, TecnicoDelClienteSalida, VencimientoSalida,
)
from schemas.comun import Mensaje, RESPUESTAS_ERROR
from services import auditoria, capacitacion_service as svc
from services.almacenamiento import obtener_almacenamiento

router = APIRouter(prefix="/api/capacitacion", tags=["Capacitación y certificación"], responses=RESPUESTAS_ERROR)

GESTIONAN = requiere_rol(*svc.GESTIONAN)
CONSULTAN = requiere_rol(*svc.CONSULTAN_PRESTADOR)
CLIENTE = requiere_rol(*svc.CONSULTAN_CLIENTE)


# ------------------------------------------------------------------ catálogo
@router.get("/cursos", response_model=list[CursoSalida], summary="Catálogo de cursos y certificaciones",
            description="El global (sin prestador) lo ve cualquiera con contexto; el propio, su prestador.")
async def listar_cursos(db: DB, actor: Actor = Depends(CONSULTAN), solo_activos: bool = False,
                        q: str | None = Query(default=None, max_length=100)):
    return await svc.listar_cursos(db, actor, solo_activos=solo_activos, q=q)


@router.post("/cursos", response_model=CursoSalida, status_code=201, summary="Crear curso",
             description="`global: true` (solo Superadmin) lo deja en el catálogo de plataforma. Un curso con "
                         "`habilidad_id` certifica esa habilidad al registrarse aprobado.")
async def crear_curso(datos: CursoEntrada, request: Request, db: DB, actor: Actor = Depends(GESTIONAN)):
    cuerpo = datos.model_dump(by_alias=True, exclude_none=False)
    curso = await svc.crear_curso(db, actor, request, cuerpo)
    await db.commit()
    await db.refresh(curso)
    return curso


@router.put("/cursos/{curso_id}", response_model=CursoSalida, summary="Editar curso")
async def editar_curso(curso_id: UUID, datos: CursoCambios, request: Request, db: DB,
                       actor: Actor = Depends(GESTIONAN)):
    curso = await svc.editar_curso(db, actor, request, curso_id, datos.model_dump(exclude_unset=True))
    await db.commit()
    await db.refresh(curso)
    return curso


# ------------------------------------------------------------------ cursos del técnico
@router.post("/tecnicos/{tecnico_id}/cursos", response_model=ExpedienteSalida, status_code=201,
             summary="Registrar un curso del técnico",
             description="Multipart con el certificado opcional (PDF, JPG, PNG o WebP, hasta 10 MB). Un curso "
                         "aprobado cuyo curso tenga habilidad la certifica automáticamente (§6.10.3).")
async def registrar_curso(tecnico_id: UUID, request: Request, db: DB, actor: Actor = Depends(GESTIONAN),
                          curso_id: UUID = Form(...), fecha_fin: date = Form(...),
                          fecha_inicio: date | None = Form(default=None),
                          calificacion: Decimal | None = Form(default=None),
                          # En esta version de FastAPI un `bool = Form(default=True)` llega False cuando el campo
                          # no viene (la casilla sin marcar del navegador), asi que se recibe como texto y se
                          # interpreta aqui: ausente = aprobado, que es el caso normal.
                          aprobado: str | None = Form(default=None),
                          folio_constancia: str | None = Form(default=None),
                          vigente_hasta: date | None = Form(default=None),
                          razon_vigencia: str = Form(default=""),
                          notas: str = Form(default=""),
                          certificado: UploadFile | None = File(default=None)):
    aprobado_real = True if aprobado is None else aprobado.strip().lower() in ("1", "true", "si", "sí", "on", "x")
    archivo = None
    if certificado is not None:
        contenido = await certificado.read(svc.MAX_CERTIFICADO_BYTES + 1)
        archivo = (contenido, certificado.filename or "constancia", certificado.content_type or "application/pdf")
    await svc.registrar_curso(db, actor, request, tecnico_id=tecnico_id, curso_id=curso_id, fecha_fin=fecha_fin,
                              fecha_inicio=fecha_inicio, calificacion=calificacion, aprobado=aprobado_real,
                              folio_constancia=folio_constancia, vigente_hasta=vigente_hasta,
                              razon_vigencia=razon_vigencia, notas=notas, certificado=archivo)
    await db.commit()
    return await svc.expediente(db, actor, tecnico_id)


@router.get("/tecnicos/{tecnico_id}/expediente", response_model=ExpedienteSalida,
            summary="Expediente del técnico: cursos, certificaciones y habilidades derivadas")
async def expediente(tecnico_id: UUID, db: DB, actor: Actor = Depends(CONSULTAN)):
    return await svc.expediente(db, actor, tecnico_id)


@router.get("/tecnicos/{tecnico_id}/certificado/{tecnico_curso_id}", summary="Descargar la constancia del curso",
            description="Se registra como acceso a datos sensibles (§6.9.5): es un documento personal del técnico.")
async def descargar_certificado(tecnico_id: UUID, tecnico_curso_id: UUID, request: Request, db: DB,
                                actor: Actor = Depends(GESTIONAN)) -> Response:
    registro = await db.get(TecnicoCurso, tecnico_curso_id)
    if registro is None or registro.tecnico_id != tecnico_id or not registro.certificado_key:
        raise no_encontrado("Constancia")
    try:
        datos = obtener_almacenamiento().leer(registro.certificado_key)
    except Exception:
        raise no_encontrado("Archivo")
    await auditoria.registrar_acceso_datos(db, actor, request, tabla="tecnico_cursos", registros=1,
                                           recurso_id=tecnico_curso_id,
                                           detalle={"documento": "constancia", "tecnico_id": str(tecnico_id)})
    await db.commit()
    return Response(datos, media_type=registro.certificado_mime or "application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{registro.certificado_nombre or "constancia"}"'})


@router.get("/vencimientos", response_model=list[VencimientoSalida],
            summary="Certificaciones por vencer y vencidas del prestador")
async def vencimientos(db: DB, actor: Actor = Depends(CONSULTAN),
                       dias: int | None = Query(default=None, ge=1, le=365)):
    return await svc.proximos_vencimientos(db, actor, dias)


# ------------------------------------------------------------------ vista del cliente
@router.get("/tecnicos-de-mis-unidades", response_model=list[TecnicoDelClienteSalida],
            summary="Certificaciones vigentes de los técnicos que atienden mis unidades (§6.10.3)",
            description="Técnicos habilitados para el cliente o que atendieron un folio suyo en los últimos 90 días. "
                        "No incluye calificaciones, cursos no aprobados ni documentos del prestador.")
async def tecnicos_de_mis_unidades(db: DB, actor: Actor = Depends(CLIENTE)):
    return await svc.tecnicos_de_mis_unidades(db, actor)


# ------------------------------------------------------------------ configuración de alertas
@router.get("/alertas/configuracion", response_model=AlertasConfigSalida,
            summary="Configuración de las alertas de vencimiento")
async def leer_configuracion(db: DB, actor: Actor = Depends(CONSULTAN)):
    cfg = await svc.configuracion(db, svc._prestador(actor))
    await db.commit()
    return cfg


@router.put("/alertas/configuracion", response_model=AlertasConfigSalida,
            summary="Días de anticipación y aviso al cliente")
async def guardar_configuracion(datos: AlertasConfigEntrada, request: Request, db: DB,
                                actor: Actor = Depends(GESTIONAN)):
    cfg = await svc.guardar_configuracion(db, actor, request, dias_anticipacion=datos.dias_anticipacion,
                                          notificar_cliente=datos.notificar_cliente, activa=datos.activa)
    await db.commit()
    await db.refresh(cfg)
    return cfg


# ------------------------------------------------------------------ exportación
@router.get("/tecnicos/{tecnico_id}/expediente.xlsx", summary="Expediente del técnico en Excel")
async def expediente_excel(tecnico_id: UUID, request: Request, db: DB, actor: Actor = Depends(CONSULTAN)) -> Response:
    datos = await svc.expediente(db, actor, tecnico_id)
    libro = Workbook()
    hoja = libro.active
    hoja.title = "Cursos"
    hoja.append(["Curso", "Tipo", "Proveedor", "Norma", "Inicio", "Término", "Calificación", "Aprobado",
                 "Constancia", "Vigente hasta", "Estado", "Habilidad"])
    for c in datos["cursos"]:
        hoja.append([c["curso"], c["tipo"], c["proveedor"], c["norma_referencia"], c["fecha_inicio"],
                     c["fecha_fin"], c["calificacion"], "Sí" if c["aprobado"] else "No", c["folio_constancia"],
                     c["vigente_hasta"], c["estado"], c["habilidad"]])
    segunda = libro.create_sheet("Habilidades")
    segunda.append(["Habilidad", "Clave", "Certificada", "Origen", "Certificación", "Vigencia", "Estado"])
    for h in datos["habilidades"]:
        segunda.append([h["habilidad"], h["clave"], "Sí" if h["certificada"] else "No", h["origen"],
                        h["fecha_certificacion"], h["vigencia_hasta"], h["estado"]])
    bufer = io.BytesIO()
    libro.save(bufer)
    await auditoria.registrar_acceso_datos(db, actor, request, tabla="tecnico_cursos",
                                           registros=len(datos["cursos"]), recurso_id=tecnico_id,
                                           detalle={"formato": "xlsx", "documento": "expediente"})
    await db.commit()
    nombre = f"expediente-{datos['tecnico_nombre'].replace(' ', '-').lower()}.xlsx"
    return Response(bufer.getvalue(),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{nombre}"'})


@router.get("/tecnicos/{tecnico_id}/expediente.pdf", summary="Expediente del técnico en PDF")
async def expediente_pdf(tecnico_id: UUID, request: Request, db: DB, actor: Actor = Depends(CONSULTAN)) -> Response:
    from services import pdf

    datos = await svc.expediente(db, actor, tecnico_id)
    filas = "".join(
        f"<tr><td>{c['curso']}</td><td>{c['tipo'] or ''}</td><td>{c['fecha_fin']}</td>"
        f"<td>{c['vigente_hasta'] or 'permanente'}</td><td>{c['estado']}</td></tr>"
        for c in datos["cursos"])
    html = (f"<html><head><meta charset='utf-8'><title>Expediente</title></head><body>"
            f"<h1>Expediente de capacitación</h1>"
            f"<p>{datos['tecnico_nombre']} · empleado {datos['numero_empleado'] or '—'}</p>"
            f"<table border='1' cellpadding='4'><tr><th>Curso</th><th>Tipo</th><th>Término</th>"
            f"<th>Vigente hasta</th><th>Estado</th></tr>{filas}</table></body></html>")
    await auditoria.registrar_acceso_datos(db, actor, request, tabla="tecnico_cursos",
                                           registros=len(datos["cursos"]), recurso_id=tecnico_id,
                                           detalle={"formato": "pdf", "documento": "expediente"})
    await db.commit()
    return Response(pdf.html_a_pdf(html), media_type="application/pdf",
                    headers={"Content-Disposition": 'attachment; filename="expediente.pdf"'})
