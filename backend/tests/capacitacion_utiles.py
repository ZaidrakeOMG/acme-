"""Ayudas compartidas por las pruebas de F2-01 (capacitación y biblioteca)."""
from datetime import date, timedelta

from tests.folios_utiles import AP, SA

HOY = date.today()


async def ficha_tecnico(cliente, auth, email: str) -> dict:
    """La ficha de técnico (su `id`, que es lo que lleva el curso) a partir del correo del usuario."""
    lista = (await cliente.get("/api/catalogos/tecnicos", headers=await auth(AP), params={"limite": 500})).json()
    return next(t for t in lista if t["email"] == email)


async def habilidades(cliente, auth) -> dict[str, str]:
    return {h["clave"]: h["id"] for h in (await cliente.get("/api/catalogos/habilidades",
                                                            headers=await auth(AP))).json()}


async def crear_curso(cliente, auth, nombre: str, *, email=AP, esperado=201, **extra) -> dict:
    cuerpo = {"nombre": nombre, **extra}
    r = await cliente.post("/api/capacitacion/cursos", headers=await auth(email), json=cuerpo)
    assert r.status_code == esperado, r.text
    return r.json()


async def registrar(cliente, auth, tecnico_id: str, curso_id: str, *, email=AP, esperado=201,
                    certificado: bytes | None = None, **campos) -> dict:
    """Registra un curso del técnico. `campos` admite fecha_fin, aprobado, calificacion, vigente_hasta…"""
    datos = {"curso_id": curso_id, "fecha_fin": str(campos.pop("fecha_fin", HOY - timedelta(days=5))), **{
        k: ("true" if v is True else "false" if v is False else str(v)) for k, v in campos.items() if v is not None}}
    archivos = {"certificado": ("constancia.pdf", certificado, "application/pdf")} if certificado else None
    r = await cliente.post(f"/api/capacitacion/tecnicos/{tecnico_id}/cursos", headers=await auth(email),
                           data=datos, files=archivos)
    assert r.status_code == esperado, r.text
    return r.json()


async def expediente(cliente, auth, tecnico_id: str, *, email=AP) -> dict:
    r = await cliente.get(f"/api/capacitacion/tecnicos/{tecnico_id}/expediente", headers=await auth(email))
    assert r.status_code == 200, r.text
    return r.json()


async def tipo_equipo_id(cliente, auth, nombre="Refrigerador vertical", *, email=AP) -> str:
    lista = (await cliente.get("/api/catalogos/tipos-equipo", headers=await auth(email))).json()
    return next(t["id"] for t in lista if t["nombre"] == nombre)


def pdf_falso(texto: str = "manual de prueba") -> bytes:
    """Bytes con cabecera de PDF: basta para las validaciones de tipo y tamaño."""
    return b"%PDF-1.4\n% " + texto.encode() + b"\n" + b"0" * 200


async def subir_manual(cliente, auth, tipo_eq: str, titulo: str, *, email=AP, esperado=201,
                       categoria="procedimiento", contenido: bytes | None = None) -> dict:
    r = await cliente.post("/api/biblioteca/manuales", headers=await auth(email),
                           data={"tipo_equipo_id": tipo_eq, "titulo": titulo, "categoria": categoria,
                                 "descripcion": "Prueba"},
                           files={"archivo": ("manual.pdf", contenido or pdf_falso(titulo), "application/pdf")})
    assert r.status_code == esperado, r.text
    return r.json()
