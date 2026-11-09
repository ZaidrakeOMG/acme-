"""Datos demo de F2-01: catálogo de 8 cursos (3 globales y 5 del prestador, 4 ligados a habilidades y uno DC-3),
historial de los 4 técnicos con constancias de ejemplo (una certificación vencida, una por vencer en 10 días y una
sin vigencia), configuración de alertas con aviso al cliente, 6 manuales para 3 tipos de equipo (2 con dos
versiones) y contenido de servicio del cliente demo para 2 tipos de equipo, coherente con la iguala de P10.

Idempotente: si el catálogo de cursos del prestador demo ya existe, no hace nada.

Ejecutar desde backend/:  .venv/Scripts/python -m scripts.seed_capacitacion
"""
import asyncio
import hashlib
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from core.rls import CONTEXTO_SISTEMA
from models.base import EstadoRegistro, Rol
from models.capacitacion import (
    BibliotecaManual, BibliotecaVersion, CapacitacionAlertasConfig, CategoriaManual, ContenidoServicio,
    CursoCatalogo, TecnicoCurso, TipoCurso,
)
from models.catalogos import Habilidad, OrigenHabilidad, Tecnico, TecnicoHabilidad, TipoEquipo
from models.contratos import Contrato
from models.organizaciones import Prestador, Tenant
from models.usuarios import Usuario
from services import capacitacion_service
from services.almacenamiento import dueno_de, obtener_almacenamiento

HOY = date.today()

# (nombre, tipo, proveedor, horas, vigencia_meses, habilidad, norma, global)
CURSOS = [
    ("Seguridad e higiene en el trabajo", "curso", "STPS", Decimal("8"), 12, None, "NOM-STPS / DC-3", True),
    ("Primeros auxilios", "curso", "Cruz Roja Mexicana", Decimal("12"), 24, None, None, True),
    ("Trabajo en alturas", "certificacion", "Instituto de Seguridad Industrial", Decimal("16"), 24, None,
     "NOM-009-STPS", True),
    ("Manejo de refrigerantes R-410A", "certificacion", "Instituto Nacional de Refrigeración", Decimal("16"), 24,
     "refrigeracion", "NOM-STPS / DC-3", False),
    ("Instalaciones eléctricas de baja tensión", "certificacion", "Cámara de la Industria Eléctrica",
     Decimal("24"), 36, "electricidad", "NOM-001-SEDE", False),
    ("Sistemas HVAC: diagnóstico y balanceo", "certificacion", "Asociación Mexicana de HVAC", Decimal("20"), 18,
     "hvac", None, False),
    ("Iluminación LED y eficiencia energética", "curso", "Capacitación interna", Decimal("6"), None, "iluminacion",
     None, False),
    ("Atención al cliente en sitio", "curso", "Capacitación interna", Decimal("4"), None, None, None, False),
]

# (titulo, tipo de equipo, categoria, descripcion, versiones)
MANUALES = [
    ("Ficha técnica · Refrigerador vertical", "Refrigerador vertical", CategoriaManual.ficha_tecnica,
     "Características eléctricas, capacidad y refrigerante del equipo.", 2),
    ("Procedimiento de mantenimiento preventivo · Refrigerador vertical", "Refrigerador vertical",
     CategoriaManual.procedimiento, "Rutina trimestral: condensador, empaques, termostato y drenaje.", 1),
    ("Listado de refacciones · Refrigerador vertical", "Refrigerador vertical", CategoriaManual.refacciones,
     "Números de parte de compresor, termostato, empaques y ventilador.", 1),
    ("Diagrama eléctrico · Minisplit", "Minisplit", CategoriaManual.diagrama,
     "Conexiones de la unidad interior y exterior, y protecciones.", 2),
    ("Procedimiento de limpieza de serpentines · Minisplit", "Minisplit", CategoriaManual.procedimiento,
     "Limpieza de serpentines, filtros y drenaje, con producto autorizado.", 1),
    ("Ficha técnica · Lámpara LED de techo", "Lámpara LED de techo", CategoriaManual.ficha_tecnica,
     "Potencia, flujo luminoso, temperatura de color y vida útil.", 1),
]

# Contenido de servicio del cliente demo: los puntos que el cliente exige en cada visita (§6.10.4).
CONTENIDO = [
    ("Refrigerador vertical", "Rutina contractual de refrigeración comercial", "mensual", [
        ("temperatura", "Verificar temperatura de cámara y registrarla", True),
        ("condensador", "Limpieza de condensador y verificación de ventiladores", True),
        ("empaques", "Revisión de empaques de puerta y sellado", True),
        ("drenaje", "Destape y limpieza de drenaje", True),
        ("refrigerante", "Medición de presiones y carga de refrigerante", False),
        ("foto", "Fotografía del equipo antes y después", True),
    ]),
    ("Minisplit", "Rutina contractual de climatización", "bimestral", [
        ("filtros", "Lavado de filtros de la unidad interior", True),
        ("serpentin", "Limpieza de serpentín evaporador y condensador", True),
        ("drenaje", "Verificación de drenaje y pendiente", True),
        ("electrico", "Revisión de conexiones eléctricas y apriete", True),
        ("temperatura", "Medición de delta de temperatura", False),
    ]),
]


def _pdf_demo(titulo: str, version: int) -> bytes:
    """PDF mínimo válido: sirve para probar el visor y la descarga sin arrastrar binarios al repositorio."""
    texto = f"{titulo} (version {version})"
    contenido = (f"BT /F1 14 Tf 60 760 Td ({texto}) Tj ET").encode("latin-1", "replace")
    objetos = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> "
        b"/Contents 4 0 R >>",
        b"<< /Length " + str(len(contenido)).encode() + b" >>\nstream\n" + contenido + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    salida = bytearray(b"%PDF-1.4\n")
    posiciones = []
    for i, cuerpo in enumerate(objetos, 1):
        posiciones.append(len(salida))
        salida += f"{i} 0 obj\n".encode() + cuerpo + b"\nendobj\n"
    inicio_xref = len(salida)
    salida += f"xref\n0 {len(objetos) + 1}\n".encode() + b"0000000000 65535 f \n"
    for pos in posiciones:
        salida += f"{pos:010d} 00000 n \n".encode()
    salida += (f"trailer\n<< /Size {len(objetos) + 1} /Root 1 0 R >>\nstartxref\n{inicio_xref}\n%%EOF\n").encode()
    return bytes(salida)


async def sembrar_capacitacion(db) -> bool:
    prestador = (await db.execute(select(Prestador).where(Prestador.rfc == "PDE200101AB1"))).scalar_one_or_none()
    tenant = (await db.execute(select(Tenant).where(Tenant.rfc == "CDE200101XY2"))).scalar_one_or_none()
    if prestador is None or tenant is None:
        return False
    ya = (await db.execute(select(CursoCatalogo).where(CursoCatalogo.prestador_id == prestador.id))).first()
    if ya is not None:
        return False

    superadmin = (await db.execute(select(Usuario).where(Usuario.rol == Rol.superadmin))).scalars().first()
    admin_prestador = (await db.execute(select(Usuario).where(
        Usuario.rol == Rol.admin_prestador, Usuario.prestador_id == prestador.id))).scalars().first()
    admin_empresa = (await db.execute(select(Usuario).where(
        Usuario.rol == Rol.admin_empresa, Usuario.tenant_id == tenant.id))).scalars().first()
    habilidades = {h.clave: h for h in (await db.execute(select(Habilidad).where(
        Habilidad.prestador_id == prestador.id))).scalars()}
    tipos = {t.nombre: t for t in (await db.execute(select(TipoEquipo))).scalars()}
    # Los cuatro tecnicos del demo, por correo y no por posicion: en la base de desarrollo conviven con los 50
    # tecnicos de las pruebas de carga, y por orden alfabetico el historial caia en esos, no en los del demo.
    por_email = {u.email: (t, u) for t, u in (await db.execute(
        select(Tecnico, Usuario).join(Usuario, Usuario.id == Tecnico.usuario_id)
        .where(Tecnico.prestador_id == prestador.id).order_by(Usuario.email))).all()}
    tecnicos = [por_email[e] for e in (f"tecnico{i}@acma.dev" for i in (1, 2, 3, 4)) if e in por_email]
    if not tecnicos:
        tecnicos = list(por_email.values())

    # ---------------------------------------------------------------- catálogo de cursos
    cursos: dict[str, CursoCatalogo] = {}
    for nombre, tipo, proveedor, horas, vigencia, clave_hab, norma, es_global in CURSOS:
        curso = CursoCatalogo(
            prestador_id=None if es_global else prestador.id, nombre=nombre, tipo=TipoCurso(tipo),
            proveedor=proveedor, duracion_horas=horas, vigencia_meses=vigencia,
            habilidad_id=habilidades[clave_hab].id if clave_hab and clave_hab in habilidades else None,
            norma_referencia=norma, descripcion="")
        db.add(curso)
        cursos[nombre] = curso
    await db.flush()

    # ---------------------------------------------------------------- configuración de alertas
    db.add(CapacitacionAlertasConfig(prestador_id=prestador.id, dias_anticipacion=30, notificar_cliente=True,
                                     activa=True))
    await db.flush()

    # ---------------------------------------------------------------- historial por técnico
    # Tres situaciones que la pantalla debe mostrar distinto: vigente, por vencer en 10 días y vencida.
    # El cuarto técnico tiene un curso sin vigencia (no caduca) para ver el caso «sin_vigencia».
    plan = [
        # (indice de técnico, curso, fecha_fin, vigente_hasta, aprobado, calificacion, constancia)
        (0, "Manejo de refrigerantes R-410A", HOY - timedelta(days=200), None, True, Decimal("95"), "DC3-2026-0101"),
        (0, "Seguridad e higiene en el trabajo", HOY - timedelta(days=60), None, True, Decimal("88"), "DC3-2026-0102"),
        # Por vencer en 10 días: la alerta CERTIFICACION_VENCIDA debe disparar con el umbral de 30.
        (1, "Sistemas HVAC: diagnóstico y balanceo", HOY - timedelta(days=540), HOY + timedelta(days=10), True,
         Decimal("90"), "HVAC-2025-0210"),
        (1, "Primeros auxilios", HOY - timedelta(days=30), None, True, Decimal("100"), None),
        # Vencida: la tarea diaria debe retirar la habilidad de electricidad de este técnico.
        (2, "Instalaciones eléctricas de baja tensión", HOY - timedelta(days=1200), HOY - timedelta(days=15), True,
         Decimal("85"), "SEDE-2023-0455"),
        # Sin vigencia: el curso no caduca.
        (3, "Iluminación LED y eficiencia energética", HOY - timedelta(days=90), None, True, Decimal("93"), None),
        (3, "Atención al cliente en sitio", HOY - timedelta(days=15), None, True, None, None),
        # Reprobado: no certifica nada (lo comprueba la prueba del servicio).
        (3, "Trabajo en alturas", HOY - timedelta(days=45), None, False, Decimal("55"), None),
    ]
    almacen = obtener_almacenamiento()
    for indice, nombre_curso, fecha_fin, vigencia_manual, aprobado, calificacion, constancia in plan:
        if indice >= len(tecnicos):
            continue
        tecnico, usuario = tecnicos[indice]
        curso = cursos[nombre_curso]
        vigente = vigencia_manual or capacitacion_service.vigencia_de(fecha_fin, curso.vigencia_meses)
        registro = TecnicoCurso(
            prestador_id=prestador.id, tecnico_id=tecnico.id, curso_id=curso.id,
            fecha_inicio=fecha_fin - timedelta(days=2), fecha_fin=fecha_fin, calificacion=calificacion,
            aprobado=aprobado, folio_constancia=constancia, vigente_hasta=vigente,
            vigencia_editada=vigencia_manual is not None,
            razon_vigencia="Vigencia del documento original" if vigencia_manual is not None else "",
            estado=capacitacion_service.estado_de(vigente, 30),
            registrado_por=admin_prestador.id if admin_prestador else None)
        db.add(registro)
        await db.flush()
        if aprobado:
            clave = f"capacitacion/{prestador.id}/{tecnico.id}/{registro.id}.pdf"
            almacen.guardar(clave, _pdf_demo(f"Constancia: {nombre_curso} · {usuario.nombre}", 1),
                            "application/pdf", dueno=dueno_de(None, prestador.id))
            registro.certificado_key = clave
            registro.certificado_nombre = f"constancia-{curso.id.hex[:8]}.pdf"
            registro.certificado_mime = "application/pdf"
        # La vinculación con la habilidad usa la misma regla que el registro por pantalla.
        if aprobado and curso.habilidad_id:
            fila = (await db.execute(select(TecnicoHabilidad).where(
                TecnicoHabilidad.tecnico_id == tecnico.id,
                TecnicoHabilidad.habilidad_id == curso.habilidad_id))).scalar_one_or_none()
            if fila is None:
                fila = TecnicoHabilidad(prestador_id=prestador.id, tecnico_id=tecnico.id,
                                        habilidad_id=curso.habilidad_id)
                db.add(fila)
            fila.certificada = True
            fila.origen = OrigenHabilidad.curso
            fila.fecha_certificacion = fecha_fin
            fila.vigencia_hasta = vigente
            registro.habilidad_otorgada_id = curso.habilidad_id
    await db.flush()

    # ---------------------------------------------------------------- biblioteca de manuales
    for titulo, nombre_tipo, categoria, descripcion, versiones in MANUALES:
        tipo = tipos.get(nombre_tipo)
        if tipo is None:
            continue
        datos = _pdf_demo(titulo, 1)
        manual = BibliotecaManual(
            prestador_id=prestador.id, tipo_equipo_id=tipo.id, titulo=titulo, categoria=categoria,
            descripcion=descripcion, version=1, archivo_key="", nombre_original=f"{titulo[:40]}.pdf",
            mime="application/pdf", bytes=len(datos), hash_sha256=hashlib.sha256(datos).hexdigest(),
            subido_por=admin_prestador.id if admin_prestador else None)
        db.add(manual)
        await db.flush()
        manual.archivo_key = f"biblioteca/{prestador.id}/{manual.id}/v1.pdf"
        almacen.guardar(manual.archivo_key, datos, "application/pdf", dueno=dueno_de(None, prestador.id))
        if versiones > 1:
            # Segunda versión: la primera queda en el historial, como pide §6.10.4.
            nuevos = _pdf_demo(titulo, 2)
            db.add(BibliotecaVersion(
                prestador_id=prestador.id, manual_id=manual.id, version_anterior=1,
                archivo_key_anterior=manual.archivo_key, nombre_original_anterior=manual.nombre_original,
                bytes_anterior=manual.bytes, hash_sha256_anterior=manual.hash_sha256,
                reemplazado_por=admin_prestador.id if admin_prestador else None,
                notas_version="Actualización del fabricante"))
            manual.version = 2
            manual.archivo_key = f"biblioteca/{prestador.id}/{manual.id}/v2.pdf"
            manual.bytes, manual.hash_sha256 = len(nuevos), hashlib.sha256(nuevos).hexdigest()
            almacen.guardar(manual.archivo_key, nuevos, "application/pdf", dueno=dueno_de(None, prestador.id))
    await db.flush()

    # ---------------------------------------------------------------- contenido de servicio del cliente
    contrato = (await db.execute(select(Contrato).where(
        Contrato.tenant_id == tenant.id, Contrato.prestador_id == prestador.id,
        Contrato.estado == EstadoRegistro.activo).order_by(Contrato.fecha_inicio.desc()))).scalars().first()
    if contrato is not None:
        for nombre_tipo, titulo, periodicidad, puntos in CONTENIDO:
            tipo = tipos.get(nombre_tipo)
            if tipo is None:
                continue
            db.add(ContenidoServicio(
                tenant_id=tenant.id, prestador_id=prestador.id, tipo_equipo_id=tipo.id, contrato_id=contrato.id,
                titulo=titulo, periodicidad=periodicidad,
                puntos_revision_json=[{"orden": i, "clave": c, "descripcion": d, "obligatorio": o}
                                      for i, (c, d, o) in enumerate(puntos, 1)],
                # Coherente con la iguala de P10: se copian los valores del contrato.
                correctivos_iguala=contrato.folios_correctivos_iguala,
                preventivos_iguala_json=contrato.preventivos_iguala_json or {},
                subido_por=admin_empresa.id if admin_empresa else None))
    await db.flush()
    return True


async def main() -> None:
    from core.db import nueva_sesion

    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        ok = await sembrar_capacitacion(db)
        await db.commit()
    print("Cursos, historial de técnicos, manuales y contenido de servicio demo creados." if ok
          else "Ya existían (o falta el seed base).")


if __name__ == "__main__":
    asyncio.run(main())
