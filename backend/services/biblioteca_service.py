"""Biblioteca de manuales técnicos y contenido de servicio contractual (§6.10.4). F2-01.

Dos contenidos con dueños distintos:
- **Manual técnico** del tipo de equipo, que sube el Admin prestador. Cada versión nueva reemplaza a la vigente y
  deja la anterior en `biblioteca_versiones`, que es append-only.
- **Contenido de servicio contractual**, que sube el Admin empresa: los puntos exactos a revisar en cada visita, la
  periodicidad y lo incluido en la iguala. Es confidencial de su tenant y ningún otro tenant lo ve.

Reglas elegidas (anotadas en CONTEXTO.md):
- Tamaño máximo por archivo: 50 MB, y solo PDF, imágenes y video corto.
- El técnico ve todos los manuales de su prestador (con el permiso `acceder_manuales`), pero el contenido de
  servicio **solo del tenant y tipo de equipo de los folios que tiene asignados**.
- La descarga va por un enlace firmado de 5 minutos: los archivos están cifrados con la llave del dueño (P11a), así
  que no se pueden servir desde el almacenamiento directamente, pero el visor del navegador necesita una URL.
- Si el contenido de servicio no coincide con la iguala del contrato (P10), se avisa y **no se bloquea**.
"""
import hashlib
from datetime import date, datetime
from typing import Any
from uuid import UUID

import jwt
from fastapi import Request
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ErrorAPI, no_encontrado, prohibido
from core.security import crear_jwt, decodificar_jwt
from models.base import Dominio, EstadoRegistro, Rol
from models.capacitacion import (
    BibliotecaManual, BibliotecaVersion, CategoriaManual, ContenidoServicio, TecnicoDescargaOffline,
)
from models.catalogos import Equipo, Tecnico, TipoEquipo
from models.contratos import Contrato
from models.folios import EstadoFolio, Folio
from services import auditoria, permisos_service
from services.almacenamiento import dueno_de, obtener_almacenamiento

GESTIONAN_MANUALES = {Rol.superadmin, Rol.admin_prestador}
GESTIONAN_CONTENIDO = {Rol.superadmin, Rol.admin_empresa}
CONSULTAN_MANUALES = GESTIONAN_MANUALES | {Rol.mesa_control, Rol.despachador, Rol.tecnico,
                                           Rol.direccion_prestador, Rol.supervisor_prestador}
CONSULTAN_CONTENIDO = GESTIONAN_CONTENIDO | {Rol.admin_un, Rol.admin_prestador, Rol.mesa_control,
                                             Rol.despachador, Rol.tecnico}

MAX_BYTES = 50_000_000      # 50 MB por archivo
MIMES = {
    "application/pdf": "pdf",
    "image/jpeg": "jpg", "image/png": "png", "image/webp": "webp",
    "video/mp4": "mp4", "video/webm": "webm",
}
TIPO_DESCARGA = "descarga_biblioteca"
MINUTOS_DESCARGA = 5
# Estados en los que un folio asignado sigue siendo «trabajo del técnico» para efectos de consulta.
ABIERTOS = [e for e in EstadoFolio if e not in (EstadoFolio.cerrado, EstadoFolio.cancelado)]


def _exigir(actor, roles: set[Rol], accion: str) -> None:
    if actor.rol not in roles:
        raise prohibido(f"{accion}: tu rol no tiene permiso")


def _prestador(actor) -> UUID:
    if actor.prestador_id is None:
        raise ErrorAPI(422, "PRESTADOR_REQUERIDO", "Tu usuario no pertenece a un prestador")
    return actor.prestador_id


def _tenant(actor) -> UUID:
    if actor.tenant_id is None:
        raise ErrorAPI(422, "TENANT_REQUERIDO", "Tu usuario no pertenece a un cliente")
    return actor.tenant_id


def _validar_archivo(datos: bytes, mime: str) -> str:
    if not datos:
        raise ErrorAPI(422, "ARCHIVO_VACIO", "El archivo está vacío")
    if len(datos) > MAX_BYTES:
        raise ErrorAPI(413, "ARCHIVO_DEMASIADO_GRANDE",
                       f"El archivo no puede exceder {MAX_BYTES // 1_000_000} MB")
    if mime not in MIMES:
        raise ErrorAPI(422, "TIPO_ARCHIVO_INVALIDO",
                       "Se admiten PDF, imágenes (JPG, PNG, WebP) y video corto (MP4, WebM)")
    return MIMES[mime]


# --------------------------------------------------------------------------- manuales

async def _tipo_equipo(db: AsyncSession, tipo_equipo_id: UUID) -> TipoEquipo:
    t = (await db.execute(select(TipoEquipo).where(TipoEquipo.id == tipo_equipo_id))).scalar_one_or_none()
    if t is None:
        raise no_encontrado("Tipo de equipo")
    return t


async def subir_manual(db: AsyncSession, actor, request: Request | None, *, tipo_equipo_id: UUID, titulo: str,
                       categoria: CategoriaManual, descripcion: str, archivo: tuple[bytes, str, str]) -> BibliotecaManual:
    _exigir(actor, GESTIONAN_MANUALES, "Subir manuales")
    prestador_id = _prestador(actor)
    await _tipo_equipo(db, tipo_equipo_id)
    datos, nombre, mime = archivo
    extension = _validar_archivo(datos, mime)
    manual = BibliotecaManual(prestador_id=prestador_id, tipo_equipo_id=tipo_equipo_id, titulo=titulo,
                              categoria=categoria, descripcion=descripcion, version=1, archivo_key="",
                              nombre_original=nombre[:255], mime=mime, bytes=len(datos),
                              hash_sha256=hashlib.sha256(datos).hexdigest(), subido_por=actor.id)
    db.add(manual)
    await db.flush()
    manual.archivo_key = f"biblioteca/{prestador_id}/{manual.id}/v1.{extension}"
    obtener_almacenamiento().guardar(manual.archivo_key, datos, mime, dueno=dueno_de(None, prestador_id))
    await db.flush()
    await auditoria.registrar_actor(db, actor, "biblioteca.manual_subido", request, recurso_tipo="manual",
                                    recurso_id=manual.id, despues={"titulo": titulo, "version": 1,
                                                                   "tipo_equipo_id": str(tipo_equipo_id),
                                                                   "bytes": len(datos)})
    return manual


async def nueva_version(db: AsyncSession, actor, request: Request | None, manual_id: UUID, *,
                        archivo: tuple[bytes, str, str], notas: str = "") -> BibliotecaManual:
    """§6.10.4: la versión nueva reemplaza a la vigente y la anterior queda en el historial."""
    _exigir(actor, GESTIONAN_MANUALES, "Subir una versión nueva")
    manual = await obtener_manual(db, actor, manual_id)
    if manual.prestador_id != _prestador(actor) and actor.rol != Rol.superadmin:
        raise prohibido("Ese manual es de otro prestador")
    datos, nombre, mime = archivo
    extension = _validar_archivo(datos, mime)
    db.add(BibliotecaVersion(
        prestador_id=manual.prestador_id, manual_id=manual.id, version_anterior=manual.version,
        archivo_key_anterior=manual.archivo_key, nombre_original_anterior=manual.nombre_original,
        bytes_anterior=manual.bytes, hash_sha256_anterior=manual.hash_sha256,
        reemplazado_por=actor.id, notas_version=notas))
    manual.version += 1
    manual.archivo_key = f"biblioteca/{manual.prestador_id}/{manual.id}/v{manual.version}.{extension}"
    manual.nombre_original, manual.mime, manual.bytes = nombre[:255], mime, len(datos)
    manual.hash_sha256 = hashlib.sha256(datos).hexdigest()
    manual.fecha_subida = datetime.now(tz=None).astimezone()
    manual.subido_por = actor.id
    obtener_almacenamiento().guardar(manual.archivo_key, datos, mime, dueno=dueno_de(None, manual.prestador_id))
    await db.flush()
    await auditoria.registrar_actor(db, actor, "biblioteca.manual_nueva_version", request, recurso_tipo="manual",
                                    recurso_id=manual.id, despues={"version": manual.version, "notas": notas})
    return manual


async def obtener_manual(db: AsyncSession, actor, manual_id: UUID) -> BibliotecaManual:
    m = (await db.execute(select(BibliotecaManual).where(BibliotecaManual.id == manual_id))).scalar_one_or_none()
    if m is None:
        raise no_encontrado("Manual")
    return m


async def desactivar_manual(db: AsyncSession, actor, request: Request | None, manual_id: UUID) -> BibliotecaManual:
    _exigir(actor, GESTIONAN_MANUALES, "Desactivar manuales")
    manual = await obtener_manual(db, actor, manual_id)
    manual.activo = False
    await db.flush()
    await auditoria.registrar_actor(db, actor, "biblioteca.manual_desactivado", request, recurso_tipo="manual",
                                    recurso_id=manual.id, despues={"activo": False})
    return manual


async def versiones(db: AsyncSession, actor, manual_id: UUID) -> list[BibliotecaVersion]:
    """Historial de versiones: solo el Admin prestador (y el Superadmin) ven y descargan las anteriores."""
    _exigir(actor, GESTIONAN_MANUALES, "Consultar el historial de versiones")
    await obtener_manual(db, actor, manual_id)
    return list((await db.execute(select(BibliotecaVersion).where(BibliotecaVersion.manual_id == manual_id)
                                  .order_by(BibliotecaVersion.version_anterior.desc()))).scalars())


async def _tipos_de_sus_folios(db: AsyncSession, actor) -> set[UUID]:
    """Tipos de equipo de los folios abiertos asignados al técnico."""
    filas = (await db.execute(select(Equipo.tipo_equipo_id).join(Folio, Folio.equipo_id == Equipo.id)
                              .where(Folio.tecnico_id == actor.id, Folio.estado.in_(ABIERTOS)))).scalars()
    return set(filas)


async def listar_manuales(db: AsyncSession, actor, *, tipo_equipo_id: UUID | None = None, q: str | None = None,
                          solo_mis_folios: bool = False) -> list[dict[str, Any]]:
    _exigir(actor, CONSULTAN_MANUALES, "Consultar la biblioteca")
    if actor.rol == Rol.tecnico:
        await _exigir_permiso_manuales(db, actor)
    consulta = select(BibliotecaManual, TipoEquipo.nombre).join(
        TipoEquipo, TipoEquipo.id == BibliotecaManual.tipo_equipo_id).where(
        BibliotecaManual.activo.is_(True)).order_by(TipoEquipo.nombre, BibliotecaManual.titulo)
    if tipo_equipo_id:
        consulta = consulta.where(BibliotecaManual.tipo_equipo_id == tipo_equipo_id)
    if q:
        patron = f"%{q.lower()}%"
        consulta = consulta.where(or_(func.lower(BibliotecaManual.titulo).like(patron),
                                      func.lower(BibliotecaManual.descripcion).like(patron)))
    if solo_mis_folios:
        tipos = await _tipos_de_sus_folios(db, actor)
        if not tipos:
            return []
        consulta = consulta.where(BibliotecaManual.tipo_equipo_id.in_(tipos))
    return [{
        "id": m.id, "tipo_equipo_id": m.tipo_equipo_id, "tipo_equipo": tipo, "titulo": m.titulo,
        "categoria": m.categoria.value, "descripcion": m.descripcion, "version": m.version,
        "fecha_subida": m.fecha_subida, "nombre_original": m.nombre_original, "mime": m.mime,
        "bytes": m.bytes, "hash_sha256": m.hash_sha256, "updated_at": m.updated_at,
    } for m, tipo in (await db.execute(consulta)).all()]


async def fila_de_manual(db: AsyncSession, manual_id: UUID) -> dict[str, Any]:
    """La misma forma que `listar_manuales`, para una sola fila (respuesta de subir y de versionar)."""
    fila = (await db.execute(select(BibliotecaManual, TipoEquipo.nombre)
                             .join(TipoEquipo, TipoEquipo.id == BibliotecaManual.tipo_equipo_id)
                             .where(BibliotecaManual.id == manual_id))).first()
    if fila is None:
        raise no_encontrado("Manual")
    m, tipo = fila
    return {"id": m.id, "tipo_equipo_id": m.tipo_equipo_id, "tipo_equipo": tipo, "titulo": m.titulo,
            "categoria": m.categoria.value, "descripcion": m.descripcion, "version": m.version,
            "fecha_subida": m.fecha_subida, "nombre_original": m.nombre_original, "mime": m.mime,
            "bytes": m.bytes, "hash_sha256": m.hash_sha256, "updated_at": m.updated_at}


async def _exigir_permiso_manuales(db: AsyncSession, actor) -> None:
    """§6.8.3: el permiso `acceder_manuales` resuelto como en P02 (override > grupo > prestador > catálogo)."""
    permisos = await permisos_service.efectivos_de_tecnico(db, _prestador(actor), actor.id)
    if not any(p["clave"] == "acceder_manuales" and p["habilitado"] for p in permisos):
        raise prohibido("Tu prestador no te habilitó la consulta de manuales")


# --------------------------------------------------------------------------- contenido de servicio

async def _contrato_del_tenant(db: AsyncSession, contrato_id: UUID, tenant_id: UUID) -> Contrato:
    c = (await db.execute(select(Contrato).where(Contrato.id == contrato_id))).scalar_one_or_none()
    if c is None or c.tenant_id != tenant_id:
        raise no_encontrado("Contrato")
    return c


def _avisos_de_coherencia(contenido: dict[str, Any], contrato: Contrato) -> list[str]:
    """Compara lo declarado con la iguala del contrato (P10). Avisa, no bloquea."""
    avisos = []
    correctivos = contenido.get("correctivos_iguala")
    if correctivos is not None and contrato.folios_correctivos_iguala is not None \
            and int(correctivos) != int(contrato.folios_correctivos_iguala):
        avisos.append(f"El contrato incluye {contrato.folios_correctivos_iguala} correctivos en la iguala y aquí "
                      f"dice {correctivos}")
    preventivos = contenido.get("preventivos_iguala_json") or {}
    del_contrato = contrato.preventivos_iguala_json or {}
    if preventivos and del_contrato and preventivos != del_contrato:
        avisos.append("Los preventivos incluidos no coinciden con los del contrato")
    return avisos


def _validar_puntos(puntos: Any) -> list[dict[str, Any]]:
    if not isinstance(puntos, list):
        raise ErrorAPI(422, "PUNTOS_INVALIDOS", "Los puntos de revisión deben ser una lista ordenada")
    limpios = []
    for i, p in enumerate(puntos, 1):
        if not isinstance(p, dict) or not str(p.get("descripcion", "")).strip():
            raise ErrorAPI(422, "PUNTO_SIN_DESCRIPCION", f"El punto {i} no tiene descripción")
        limpios.append({"orden": i, "clave": str(p.get("clave") or f"punto_{i}")[:60],
                        "descripcion": str(p["descripcion"]).strip()[:500],
                        "obligatorio": bool(p.get("obligatorio", True))})
    return limpios


async def guardar_contenido(db: AsyncSession, actor, request: Request | None, *, tipo_equipo_id: UUID,
                            contrato_id: UUID, titulo: str, puntos_revision: list[dict[str, Any]],
                            periodicidad: str | None, correctivos_iguala: int | None,
                            preventivos_iguala: dict[str, Any] | None,
                            archivo: tuple[bytes, str, str] | None = None) -> tuple[ContenidoServicio, list[str]]:
    """Crea el contenido de servicio del tipo de equipo, o lo reemplaza con una versión nueva si ya existía."""
    _exigir(actor, GESTIONAN_CONTENIDO, "Definir el contenido de servicio")
    tenant_id = _tenant(actor)
    contrato = await _contrato_del_tenant(db, contrato_id, tenant_id)
    await _tipo_equipo(db, tipo_equipo_id)
    puntos = _validar_puntos(puntos_revision)
    datos_nuevos = {"correctivos_iguala": correctivos_iguala, "preventivos_iguala_json": preventivos_iguala or {}}
    avisos = _avisos_de_coherencia(datos_nuevos, contrato)

    vigente = (await db.execute(select(ContenidoServicio).where(
        ContenidoServicio.tenant_id == tenant_id, ContenidoServicio.contrato_id == contrato_id,
        ContenidoServicio.tipo_equipo_id == tipo_equipo_id, ContenidoServicio.activo.is_(True)))).scalar_one_or_none()
    version = 1
    if vigente is not None:
        vigente.activo = False          # la versión anterior queda inactiva, consultable por su id
        version = vigente.version + 1
        await db.flush()

    contenido = ContenidoServicio(
        tenant_id=tenant_id, prestador_id=contrato.prestador_id, tipo_equipo_id=tipo_equipo_id,
        contrato_id=contrato_id, titulo=titulo, puntos_revision_json=puntos, periodicidad=periodicidad,
        correctivos_iguala=correctivos_iguala, preventivos_iguala_json=preventivos_iguala or {},
        version=version, subido_por=actor.id)
    db.add(contenido)
    await db.flush()
    if archivo is not None:
        datos, nombre, mime = archivo
        extension = _validar_archivo(datos, mime)
        contenido.archivo_key = f"contenido_servicio/{tenant_id}/{contenido.id}/v{version}.{extension}"
        contenido.nombre_original, contenido.mime, contenido.bytes = nombre[:255], mime, len(datos)
        obtener_almacenamiento().guardar(contenido.archivo_key, datos, mime, dueno=dueno_de(tenant_id, None))
        await db.flush()
    await auditoria.registrar_actor(db, actor, "biblioteca.contenido_servicio_guardado", request,
                                    recurso_tipo="contenido_servicio", recurso_id=contenido.id,
                                    despues={"version": version, "puntos": len(puntos), "avisos": avisos})
    return contenido, avisos


async def listar_contenido(db: AsyncSession, actor, *, tipo_equipo_id: UUID | None = None,
                           incluir_inactivos: bool = False) -> list[dict[str, Any]]:
    """El cliente ve su contenido; el técnico, solo el de los folios que tiene asignados."""
    _exigir(actor, CONSULTAN_CONTENIDO, "Consultar el contenido de servicio")
    consulta = select(ContenidoServicio, TipoEquipo.nombre).join(
        TipoEquipo, TipoEquipo.id == ContenidoServicio.tipo_equipo_id).order_by(
        TipoEquipo.nombre, ContenidoServicio.version.desc())
    if not incluir_inactivos:
        consulta = consulta.where(ContenidoServicio.activo.is_(True))
    if tipo_equipo_id:
        consulta = consulta.where(ContenidoServicio.tipo_equipo_id == tipo_equipo_id)
    if actor.rol == Rol.tecnico:
        await _exigir_permiso_manuales(db, actor)
        pares = await _pares_de_sus_folios(db, actor)
        if not pares:
            return []
        consulta = consulta.where(or_(*[
            (ContenidoServicio.tenant_id == t) & (ContenidoServicio.tipo_equipo_id == te) for t, te in pares]))
    return [{
        "id": c.id, "tenant_id": c.tenant_id, "tipo_equipo_id": c.tipo_equipo_id, "tipo_equipo": tipo,
        "contrato_id": c.contrato_id, "titulo": c.titulo, "puntos_revision": c.puntos_revision_json,
        "periodicidad": c.periodicidad, "correctivos_iguala": c.correctivos_iguala,
        "preventivos_iguala": c.preventivos_iguala_json, "version": c.version, "activo": c.activo,
        "tiene_archivo": bool(c.archivo_key), "updated_at": c.updated_at,
    } for c, tipo in (await db.execute(consulta)).all()]


async def _pares_de_sus_folios(db: AsyncSession, actor) -> set[tuple[UUID, UUID]]:
    """(tenant, tipo de equipo) de los folios abiertos asignados al técnico."""
    filas = (await db.execute(select(Folio.tenant_id, Equipo.tipo_equipo_id)
                              .join(Equipo, Equipo.id == Folio.equipo_id)
                              .where(Folio.tecnico_id == actor.id, Folio.estado.in_(ABIERTOS)))).all()
    return {(t, te) for t, te in filas}


async def contenido_de_folio(db: AsyncSession, actor, folio: Folio) -> dict[str, Any] | None:
    """Puntos de revisión aplicables a un folio: su tenant y el tipo de equipo del equipo del folio."""
    equipo = await db.get(Equipo, folio.equipo_id)
    if equipo is None:
        return None
    c = (await db.execute(select(ContenidoServicio).where(
        ContenidoServicio.tenant_id == folio.tenant_id,
        ContenidoServicio.tipo_equipo_id == equipo.tipo_equipo_id,
        ContenidoServicio.activo.is_(True)))).scalar_one_or_none()
    if c is None:
        return None
    return {"id": c.id, "titulo": c.titulo, "puntos_revision": c.puntos_revision_json,
            "periodicidad": c.periodicidad, "version": c.version}


async def apoyo_de_folio(db: AsyncSession, actor, folio_id: UUID) -> dict[str, Any]:
    """
    Lo que hace falta a la mano durante la atención (§6.10.4): los puntos de revisión del contrato y los manuales del
    tipo de equipo del folio. Se resuelve en una sola llamada porque la app del técnico la hace al abrir el folio.

    Lo que el actor no tenga permiso de ver sale vacío en lugar de tumbar la pantalla completa: un técnico sin el
    permiso `acceder_manuales` sigue necesitando los puntos de revisión.
    """
    folio = await db.get(Folio, folio_id)       # la RLS deja invisible el folio de otro dueño
    if folio is None:
        raise no_encontrado("Folio")
    equipo = await db.get(Equipo, folio.equipo_id)
    if equipo is None:
        raise no_encontrado("Equipo del folio")
    manuales: list[dict[str, Any]] = []
    if actor.rol in CONSULTAN_MANUALES:
        try:
            manuales = await listar_manuales(db, actor, tipo_equipo_id=equipo.tipo_equipo_id)
        except ErrorAPI:
            manuales = []
    contenido = await contenido_de_folio(db, actor, folio) if actor.rol in CONSULTAN_CONTENIDO else None
    return {"folio_id": folio.id, "tipo_equipo_id": equipo.tipo_equipo_id,
            "contenido": contenido, "manuales": manuales}


# --------------------------------------------------------------------------- descarga firmada

def firmar_descarga(*, clase: str, recurso_id: UUID, usuario_id: UUID, version: int) -> str:
    """Enlace de corta duración para el visor del navegador (los archivos están cifrados: los sirve la API)."""
    return crear_jwt({"clase": clase, "rid": str(recurso_id), "sub": str(usuario_id), "ver": version},
                     TIPO_DESCARGA, MINUTOS_DESCARGA)


def leer_firma(token: str) -> dict[str, Any]:
    try:
        return decodificar_jwt(token, TIPO_DESCARGA)
    except jwt.PyJWTError:
        raise prohibido("El enlace de descarga venció o no es válido")


async def archivo_firmado(token: str) -> tuple[bytes, str, str]:
    """Sirve el archivo de un enlace firmado **con la visibilidad del usuario que lo pidió**.

    El endpoint no lleva cabecera de autorización (el visor del navegador no la manda), así que la sesión de la
    petición no tiene contexto RLS y no vería nada: aquí se abre una sesión con el contexto del usuario del token,
    que es quien firmó. Si ese usuario perdió el acceso, el enlace deja de servir aunque no haya vencido.
    """
    from core.db import nueva_sesion
    from core.rls import CONTEXTO_SISTEMA, ContextoRLS
    from models.usuarios import Usuario

    carga = leer_firma(token)
    usuario_id = UUID(carga["sub"])
    async with nueva_sesion(CONTEXTO_SISTEMA) as sistema:
        usuario = await sistema.get(Usuario, usuario_id)
        if usuario is None or usuario.estado != EstadoRegistro.activo:
            raise prohibido("El enlace de descarga ya no es válido")
        contexto = ContextoRLS(usuario_id=usuario.id, tenant_id=usuario.tenant_id,
                               prestador_id=usuario.prestador_id, rol=usuario.rol.value)
    async with nueva_sesion(contexto) as db:
        if carga["clase"] == "manual":
            return await bytes_de_manual(db, UUID(carga["rid"]), carga.get("ver"))
        return await bytes_de_contenido(db, UUID(carga["rid"]))


async def bytes_de_manual(db: AsyncSession, manual_id: UUID, version: int | None = None) -> tuple[bytes, str, str]:
    m = (await db.execute(select(BibliotecaManual).where(BibliotecaManual.id == manual_id))).scalar_one_or_none()
    if m is None:
        raise no_encontrado("Manual")
    clave, nombre, mime = m.archivo_key, m.nombre_original, m.mime
    if version is not None and version != m.version:
        v = (await db.execute(select(BibliotecaVersion).where(
            BibliotecaVersion.manual_id == manual_id, BibliotecaVersion.version_anterior == version))).scalar_one_or_none()
        if v is None:
            raise no_encontrado("Versión del manual")
        clave, nombre = v.archivo_key_anterior, v.nombre_original_anterior or m.nombre_original
    try:
        return obtener_almacenamiento().leer(clave), nombre, mime
    except Exception:
        raise no_encontrado("Archivo")


async def bytes_de_contenido(db: AsyncSession, contenido_id: UUID) -> tuple[bytes, str, str]:
    c = (await db.execute(select(ContenidoServicio).where(
        ContenidoServicio.id == contenido_id))).scalar_one_or_none()
    if c is None or not c.archivo_key:
        raise no_encontrado("Documento del contenido de servicio")
    try:
        return obtener_almacenamiento().leer(c.archivo_key), c.nombre_original or "contenido.pdf", c.mime or "application/pdf"
    except Exception:
        raise no_encontrado("Archivo")


# --------------------------------------------------------------------------- descargas offline

async def registrar_descarga(db: AsyncSession, actor, *, manual_id: UUID | None = None,
                             contenido_id: UUID | None = None, version: int, dispositivo_id: str | None,
                             en_dispositivo: bool = True) -> TecnicoDescargaOffline:
    """Lo llama el técnico (o la cola offline de P05) al guardar o borrar un archivo en su dispositivo."""
    if (manual_id is None) == (contenido_id is None):
        raise ErrorAPI(422, "RECURSO_REQUERIDO", "Indica un manual o un contenido de servicio, no los dos")
    tecnico = (await db.execute(select(Tecnico).where(Tecnico.usuario_id == actor.id))).scalar_one_or_none()
    if tecnico is None:
        raise prohibido("Solo un técnico registra descargas para uso sin señal")
    fila = (await db.execute(select(TecnicoDescargaOffline).where(
        TecnicoDescargaOffline.tecnico_id == tecnico.id,
        TecnicoDescargaOffline.manual_id == manual_id,
        TecnicoDescargaOffline.contenido_id == contenido_id,
        TecnicoDescargaOffline.dispositivo_id == dispositivo_id))).scalar_one_or_none()
    if fila is None:
        fila = TecnicoDescargaOffline(prestador_id=tecnico.prestador_id, tecnico_id=tecnico.id, manual_id=manual_id,
                                      contenido_id=contenido_id, version_descargada=version,
                                      dispositivo_id=dispositivo_id, en_dispositivo=en_dispositivo)
        db.add(fila)
    else:
        fila.version_descargada = version
        fila.en_dispositivo = en_dispositivo
        fila.fecha_descarga = datetime.now(tz=None).astimezone()
    await db.flush()
    return fila


async def mis_descargas(db: AsyncSession, actor) -> list[dict[str, Any]]:
    """Lo que el técnico tiene guardado, con aviso de versión nueva."""
    tecnico = (await db.execute(select(Tecnico).where(Tecnico.usuario_id == actor.id))).scalar_one_or_none()
    if tecnico is None:
        return []
    filas = (await db.execute(select(TecnicoDescargaOffline).where(
        TecnicoDescargaOffline.tecnico_id == tecnico.id, TecnicoDescargaOffline.en_dispositivo.is_(True)))).scalars()
    salida = []
    for f in filas:
        if f.manual_id:
            m = await db.get(BibliotecaManual, f.manual_id)
            if m is None:
                continue
            salida.append({"tipo": "manual", "id": m.id, "titulo": m.titulo, "bytes": m.bytes,
                           "version_descargada": f.version_descargada, "version_vigente": m.version,
                           "desactualizado": f.version_descargada < m.version, "activo": m.activo,
                           "fecha_descarga": f.fecha_descarga, "dispositivo_id": f.dispositivo_id})
        else:
            c = await db.get(ContenidoServicio, f.contenido_id)
            if c is None:
                continue
            salida.append({"tipo": "contenido_servicio", "id": c.id, "titulo": c.titulo, "bytes": c.bytes,
                           "version_descargada": f.version_descargada, "version_vigente": c.version,
                           "desactualizado": f.version_descargada < c.version, "activo": c.activo,
                           "fecha_descarga": f.fecha_descarga, "dispositivo_id": f.dispositivo_id})
    return salida


# --------------------------------------------------------------------------- paquete de sincronización

async def paquete_del_tecnico(db: AsyncSession, actor, desde: datetime | None) -> list[dict[str, Any]]:
    """Metadatos (no los archivos) de manuales y contenido aplicables al técnico, incrementales con bajas lógicas."""
    tipos = await _tipos_de_sus_folios(db, actor)
    pares = await _pares_de_sus_folios(db, actor)
    salida: list[dict[str, Any]] = []
    consulta = select(BibliotecaManual)
    if desde:
        consulta = consulta.where(BibliotecaManual.updated_at > desde)
    for m in (await db.execute(consulta)).scalars():
        salida.append({
            "clase": "manual", "id": str(m.id), "tipo_equipo_id": str(m.tipo_equipo_id), "titulo": m.titulo,
            "categoria": m.categoria.value, "version": m.version, "mime": m.mime, "bytes": m.bytes,
            "hash_sha256": m.hash_sha256, "nombre_original": m.nombre_original,
            "updated_at": m.updated_at.isoformat() if m.updated_at else None,
            # `activo` es la baja lógica que el dispositivo usa para retirar lo que ya no aplica (§6.2 capa 3).
            "activo": m.activo, "de_mis_folios": m.tipo_equipo_id in tipos,
        })
    consulta = select(ContenidoServicio)
    if desde:
        consulta = consulta.where(ContenidoServicio.updated_at > desde)
    for c in (await db.execute(consulta)).scalars():
        if (c.tenant_id, c.tipo_equipo_id) not in pares:
            continue
        salida.append({
            "clase": "contenido_servicio", "id": str(c.id), "tipo_equipo_id": str(c.tipo_equipo_id),
            "titulo": c.titulo, "version": c.version, "puntos_revision": c.puntos_revision_json,
            "periodicidad": c.periodicidad, "tiene_archivo": bool(c.archivo_key), "mime": c.mime,
            "bytes": c.bytes, "updated_at": c.updated_at.isoformat() if c.updated_at else None,
            "activo": c.activo, "de_mis_folios": True,
        })
    return salida
