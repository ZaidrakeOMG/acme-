"""Capacitación y certificación de técnicos (§6.10.3). F2-01.

Reglas elegidas (anotadas en CONTEXTO.md):
- **Un curso aprobado con `habilidad_id` certifica la habilidad**: crea o actualiza `tecnico_habilidades` con
  `origen = curso`, `fecha_certificacion = fecha_fin` y la vigencia del curso.
- **La habilidad declarada a mano gana.** Si el técnico ya tenía la habilidad con `origen = manual`, el curso queda
  registrado como respaldo y no la toca: alguien del prestador la afirmó y el sistema no le discute.
- **Al vencer, el sistema retira la certificación** que él mismo otorgó (`origen = curso`). A partir de ese día la
  restricción dura de asignación de P04/P06 bloquea a ese técnico para esa familia de equipos, salvo el permiso
  `asignar_tecnico_sin_habilidad` con razón. Cada retiro queda en `audit_log`.
- **Vista del cliente:** técnicos habilitados para su tenant o que atendieron un folio suyo en los últimos 90 días,
  y solo sus certificaciones vigentes. La RLS lo restringe igual (política `tecnico_cursos_lectura_cliente`).
"""
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import Request
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.dependencias import Actor
from core.errors import ErrorAPI, no_encontrado, prohibido
from models.base import Rol
from models.capacitacion import (
    CapacitacionAlertasConfig, CursoCatalogo, EstadoCursoTecnico, TecnicoCurso, TipoCurso,
)
from models.catalogos import Habilidad, OrigenHabilidad, Tecnico, TecnicoHabilidad, TecnicoTenantHabilitado
from models.folios import Folio
from models.usuarios import Usuario
from services import alertas_service, auditoria, notificaciones_service
from services.almacenamiento import dueno_de, obtener_almacenamiento

# §6.10.3: el catálogo interno lo gestiona el Admin prestador; el global, el Superadmin.
GESTIONAN = {Rol.superadmin, Rol.admin_prestador}
# Mesa de control consulta y el despachador necesita ver vigencias para asignar.
CONSULTAN_PRESTADOR = GESTIONAN | {Rol.mesa_control, Rol.despachador, Rol.direccion_prestador, Rol.supervisor_prestador}
CONSULTAN_CLIENTE = {Rol.superadmin, Rol.admin_empresa, Rol.admin_un}
DIAS_FOLIO_RECIENTE = 90          # ventana de «técnico que atendió mis unidades»
MAX_CERTIFICADO_BYTES = 10_000_000  # 10 MB: una constancia escaneada no pesa más
MIMES_CERTIFICADO = {"application/pdf", "image/jpeg", "image/png", "image/webp"}


# --------------------------------------------------------------------------- vigencia

def vigencia_de(fecha_fin: date, vigencia_meses: int | None) -> date | None:
    """`fecha_fin + vigencia_meses` (§6.10.3). Sin vigencia configurada, el curso no caduca."""
    if not vigencia_meses:
        return None
    mes = fecha_fin.month - 1 + vigencia_meses
    anio, mes = fecha_fin.year + mes // 12, mes % 12 + 1
    dia = min(fecha_fin.day, [31, 29 if anio % 4 == 0 and (anio % 100 != 0 or anio % 400 == 0) else 28,
                              31, 30, 31, 30, 31, 31, 30, 31, 30, 31][mes - 1])
    return date(anio, mes, dia)


def estado_de(vigente_hasta: date | None, dias_anticipacion: int, hoy: date | None = None) -> EstadoCursoTecnico:
    hoy = hoy or date.today()
    if vigente_hasta is None:
        return EstadoCursoTecnico.sin_vigencia
    if vigente_hasta < hoy:
        return EstadoCursoTecnico.vencido
    if (vigente_hasta - hoy).days <= dias_anticipacion:
        return EstadoCursoTecnico.por_vencer
    return EstadoCursoTecnico.vigente


async def configuracion(db: AsyncSession, prestador_id: UUID) -> CapacitacionAlertasConfig:
    """Configuración de alertas del prestador; se crea con los valores por defecto la primera vez."""
    cfg = (await db.execute(select(CapacitacionAlertasConfig).where(
        CapacitacionAlertasConfig.prestador_id == prestador_id))).scalar_one_or_none()
    if cfg is None:
        cfg = CapacitacionAlertasConfig(prestador_id=prestador_id)
        db.add(cfg)
        await db.flush()
    return cfg


async def guardar_configuracion(db: AsyncSession, actor: Actor, request: Request | None, *,
                                dias_anticipacion: int | None, notificar_cliente: bool | None,
                                activa: bool | None) -> CapacitacionAlertasConfig:
    _exigir(actor, GESTIONAN, "Configurar las alertas de capacitación")
    cfg = await configuracion(db, _prestador(actor))
    antes = auditoria.instantanea(cfg)
    if dias_anticipacion is not None:
        if not 1 <= dias_anticipacion <= 180:
            raise ErrorAPI(422, "DIAS_FUERA_DE_RANGO", "Los días de anticipación van de 1 a 180")
        cfg.dias_anticipacion = dias_anticipacion
    if notificar_cliente is not None:
        cfg.notificar_cliente = notificar_cliente
    if activa is not None:
        cfg.activa = activa
    await db.flush()
    await auditoria.registrar_actor(db, actor, "capacitacion.configuracion", request, recurso_tipo="prestador",
                                    recurso_id=cfg.prestador_id, antes=antes, despues=auditoria.instantanea(cfg))
    return cfg


# --------------------------------------------------------------------------- catálogo

def _exigir(actor: Actor, roles: set[Rol], accion: str) -> None:
    if actor.rol not in roles:
        raise prohibido(f"{accion}: tu rol no tiene permiso")


def _prestador(actor: Actor) -> UUID:
    if actor.prestador_id is None:
        raise ErrorAPI(422, "PRESTADOR_REQUERIDO", "Indica el prestador: tu usuario no pertenece a uno")
    return actor.prestador_id


async def listar_cursos(db: AsyncSession, actor: Actor, *, solo_activos: bool = False,
                        q: str | None = None) -> list[CursoCatalogo]:
    _exigir(actor, CONSULTAN_PRESTADOR, "Consultar el catálogo de cursos")
    consulta = select(CursoCatalogo).order_by(CursoCatalogo.nombre)
    if solo_activos:
        consulta = consulta.where(CursoCatalogo.activo.is_(True))
    if q:
        patron = f"%{q.lower()}%"
        consulta = consulta.where(or_(func.lower(CursoCatalogo.nombre).like(patron),
                                      func.lower(func.coalesce(CursoCatalogo.proveedor, "")).like(patron)))
    return list((await db.execute(consulta)).scalars())


async def crear_curso(db: AsyncSession, actor: Actor, request: Request | None, datos: dict[str, Any]) -> CursoCatalogo:
    """El Superadmin crea cursos globales (`global = true`); el Admin prestador, los de su prestador."""
    _exigir(actor, GESTIONAN, "Crear cursos")
    es_global = bool(datos.pop("global", False))
    if es_global and actor.rol != Rol.superadmin:
        raise prohibido("Solo el Superadmin crea cursos del catálogo global")
    prestador_id = None if es_global else _prestador(actor)
    if datos.get("habilidad_id"):
        if prestador_id is None:
            raise ErrorAPI(422, "HABILIDAD_EN_CURSO_GLOBAL",
                           "Un curso global no puede certificar una habilidad: las habilidades son de cada prestador")
        await _habilidad_del_prestador(db, datos["habilidad_id"], prestador_id)
    curso = CursoCatalogo(prestador_id=prestador_id, **datos)
    db.add(curso)
    await db.flush()
    await auditoria.registrar_actor(db, actor, "capacitacion.curso_creado", request, recurso_tipo="curso",
                                    recurso_id=curso.id, despues=auditoria.instantanea(curso))
    return curso


async def editar_curso(db: AsyncSession, actor: Actor, request: Request | None, curso_id: UUID,
                       cambios: dict[str, Any]) -> CursoCatalogo:
    _exigir(actor, GESTIONAN, "Editar cursos")
    curso = await obtener_curso(db, curso_id)
    if curso.prestador_id is None and actor.rol != Rol.superadmin:
        raise prohibido("El catálogo global solo lo edita el Superadmin")
    if curso.prestador_id is not None and actor.rol != Rol.superadmin and curso.prestador_id != actor.prestador_id:
        raise prohibido("Ese curso es de otro prestador")
    antes = auditoria.instantanea(curso)
    if cambios.get("habilidad_id"):
        await _habilidad_del_prestador(db, cambios["habilidad_id"], curso.prestador_id)
    for campo, valor in cambios.items():
        if valor is not None:
            setattr(curso, campo, valor)
    await db.flush()
    await auditoria.registrar_actor(db, actor, "capacitacion.curso_editado", request, recurso_tipo="curso",
                                    recurso_id=curso.id, antes=antes, despues=auditoria.instantanea(curso))
    return curso


async def obtener_curso(db: AsyncSession, curso_id: UUID) -> CursoCatalogo:
    curso = (await db.execute(select(CursoCatalogo).where(CursoCatalogo.id == curso_id))).scalar_one_or_none()
    if curso is None:
        raise no_encontrado("Curso")
    return curso


async def _habilidad_del_prestador(db: AsyncSession, habilidad_id: UUID, prestador_id: UUID | None) -> Habilidad:
    h = (await db.execute(select(Habilidad).where(Habilidad.id == habilidad_id))).scalar_one_or_none()
    if h is None or (prestador_id is not None and h.prestador_id != prestador_id):
        raise ErrorAPI(422, "HABILIDAD_INVALIDA", "La habilidad no existe o es de otro prestador")
    return h


# --------------------------------------------------------------------------- cursos por técnico

async def _tecnico(db: AsyncSession, tecnico_id: UUID, prestador_id: UUID) -> Tecnico:
    t = (await db.execute(select(Tecnico).where(Tecnico.id == tecnico_id))).scalar_one_or_none()
    if t is None or t.prestador_id != prestador_id:   # multitenancy en el servicio, además de la RLS
        raise no_encontrado("Técnico")
    return t


async def registrar_curso(db: AsyncSession, actor: Actor, request: Request | None, *, tecnico_id: UUID,
                          curso_id: UUID, fecha_fin: date, fecha_inicio: date | None = None,
                          calificacion: Decimal | None = None, aprobado: bool = True,
                          folio_constancia: str | None = None, vigente_hasta: date | None = None,
                          razon_vigencia: str = "", notas: str = "",
                          certificado: tuple[bytes, str, str] | None = None) -> TecnicoCurso:
    """Registra un curso del técnico y, si procede, certifica su habilidad."""
    _exigir(actor, GESTIONAN, "Registrar cursos de técnicos")
    prestador_id = _prestador(actor)
    tecnico = await _tecnico(db, tecnico_id, prestador_id)
    curso = await obtener_curso(db, curso_id)
    if curso.prestador_id is not None and curso.prestador_id != prestador_id:
        raise ErrorAPI(422, "CURSO_DE_OTRO_PRESTADOR", "Ese curso pertenece a otro prestador")
    if fecha_fin > date.today():
        raise ErrorAPI(422, "FECHA_FUTURA", "La fecha de término del curso no puede estar en el futuro")
    if fecha_inicio and fecha_inicio > fecha_fin:
        raise ErrorAPI(422, "FECHAS_INVALIDAS", "La fecha de inicio es posterior a la de término")

    calculada = vigencia_de(fecha_fin, curso.vigencia_meses)
    editada = vigente_hasta is not None and vigente_hasta != calculada
    if editada and not razon_vigencia.strip():
        raise ErrorAPI(422, "RAZON_REQUERIDA", "Cambiar la vigencia calculada exige una razón")
    final = vigente_hasta or calculada
    if final is not None and final < fecha_fin:
        raise ErrorAPI(422, "VIGENCIA_INVALIDA", "La vigencia no puede terminar antes que el curso")

    registro = TecnicoCurso(
        prestador_id=prestador_id, tecnico_id=tecnico_id, curso_id=curso_id, fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin, calificacion=calificacion, aprobado=aprobado, folio_constancia=folio_constancia,
        vigente_hasta=final, vigencia_editada=editada, razon_vigencia=razon_vigencia.strip() if editada else "",
        notas=notas, registrado_por=actor.id)
    cfg = await configuracion(db, prestador_id)
    registro.estado = estado_de(final, cfg.dias_anticipacion)
    db.add(registro)
    await db.flush()

    if certificado is not None:
        registro.certificado_key = await _guardar_certificado(registro, prestador_id, certificado)
        registro.certificado_nombre, registro.certificado_mime = certificado[1][:255], certificado[2][:120]
        await db.flush()

    habilidad = await _certificar_habilidad(db, actor, request, registro, curso, tecnico)
    await auditoria.registrar_actor(db, actor, "capacitacion.curso_registrado", request, recurso_tipo="tecnico_curso",
                                    recurso_id=registro.id, despues={
                                        "tecnico_id": str(tecnico_id), "curso": curso.nombre, "aprobado": aprobado,
                                        "vigente_hasta": str(final) if final else None,
                                        "habilidad_certificada": str(habilidad) if habilidad else None})
    return registro


async def _guardar_certificado(registro: TecnicoCurso, prestador_id: UUID,
                               certificado: tuple[bytes, str, str]) -> str:
    datos, nombre, mime = certificado
    if not datos:
        raise ErrorAPI(422, "ARCHIVO_VACIO", "El certificado está vacío")
    if len(datos) > MAX_CERTIFICADO_BYTES:
        raise ErrorAPI(413, "ARCHIVO_DEMASIADO_GRANDE",
                       f"El certificado no puede exceder {MAX_CERTIFICADO_BYTES // 1_000_000} MB")
    if mime not in MIMES_CERTIFICADO:
        raise ErrorAPI(422, "TIPO_ARCHIVO_INVALIDO", "El certificado debe ser PDF, JPG, PNG o WebP")
    extension = {"application/pdf": "pdf", "image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}[mime]
    clave = f"capacitacion/{prestador_id}/{registro.tecnico_id}/{registro.id}.{extension}"
    # El cifrado por dueño de P11a: la llave se deriva del prestador.
    obtener_almacenamiento().guardar(clave, datos, mime, dueno=dueno_de(None, prestador_id))
    return clave


async def _certificar_habilidad(db: AsyncSession, actor: Actor, request: Request | None, registro: TecnicoCurso,
                                curso: CursoCatalogo, tecnico: Tecnico) -> UUID | None:
    """§6.10.3: el curso aprobado vincula la habilidad. La declarada a mano no se toca."""
    if not registro.aprobado or curso.habilidad_id is None:
        return None
    fila = (await db.execute(select(TecnicoHabilidad).where(
        TecnicoHabilidad.tecnico_id == tecnico.id, TecnicoHabilidad.habilidad_id == curso.habilidad_id))).scalar_one_or_none()
    if fila is not None and fila.origen == OrigenHabilidad.manual and fila.certificada:
        # El curso queda como respaldo documental; la afirmación del prestador manda.
        return None
    if fila is None:
        fila = TecnicoHabilidad(prestador_id=tecnico.prestador_id, tecnico_id=tecnico.id,
                                habilidad_id=curso.habilidad_id)
        db.add(fila)
    # Solo se adelanta la vigencia: un curso viejo no debe pisar una certificación más fresca.
    if fila.vigencia_hasta and registro.vigente_hasta and registro.vigente_hasta < fila.vigencia_hasta:
        return None
    fila.certificada = True
    fila.origen = OrigenHabilidad.curso
    fila.fecha_certificacion = registro.fecha_fin
    fila.vigencia_hasta = registro.vigente_hasta
    registro.habilidad_otorgada_id = curso.habilidad_id
    await db.flush()
    await auditoria.registrar_actor(db, actor, "capacitacion.habilidad_certificada", request,
                                    recurso_tipo="tecnico_habilidad", recurso_id=fila.id,
                                    despues={"tecnico_id": str(tecnico.id), "habilidad_id": str(curso.habilidad_id),
                                             "origen": "curso", "vigencia_hasta": str(registro.vigente_hasta)
                                             if registro.vigente_hasta else None, "curso": curso.nombre})
    return curso.habilidad_id


async def listar_cursos_de_tecnico(db: AsyncSession, actor: Actor, tecnico_id: UUID) -> list[TecnicoCurso]:
    _exigir(actor, CONSULTAN_PRESTADOR, "Consultar el expediente del técnico")
    await _tecnico(db, tecnico_id, _prestador(actor))
    return list((await db.execute(select(TecnicoCurso).where(TecnicoCurso.tecnico_id == tecnico_id)
                                  .order_by(TecnicoCurso.fecha_fin.desc()))).scalars())


async def expediente(db: AsyncSession, actor: Actor, tecnico_id: UUID) -> dict[str, Any]:
    """Cursos, certificaciones, habilidades derivadas y próximos vencimientos del técnico."""
    _exigir(actor, CONSULTAN_PRESTADOR, "Consultar el expediente del técnico")
    prestador_id = _prestador(actor)
    tecnico = await _tecnico(db, tecnico_id, prestador_id)
    usuario = await db.get(Usuario, tecnico.usuario_id)
    cursos = await listar_cursos_de_tecnico(db, actor, tecnico_id)
    # Sin cursos no se consulta el catalogo: un IN vacio aqui generaba SQL invalido y el expediente de un tecnico
    # recien dado de alta devolvia 500.
    catalogo: dict[UUID, CursoCatalogo] = {}
    if cursos:
        catalogo = {c.id: c for c in (await db.execute(select(CursoCatalogo).where(
            CursoCatalogo.id.in_({c.curso_id for c in cursos})))).scalars()}
    habilidades = {h.id: h for h in (await db.execute(select(Habilidad).where(
        Habilidad.prestador_id == prestador_id))).scalars()}
    filas = list((await db.execute(select(TecnicoHabilidad).where(
        TecnicoHabilidad.tecnico_id == tecnico_id))).scalars())
    cfg = await configuracion(db, prestador_id)
    hoy = date.today()
    return {
        "tecnico_id": tecnico_id,
        "tecnico_nombre": usuario.nombre if usuario else "",
        "numero_empleado": tecnico.numero_empleado,
        "dias_anticipacion": cfg.dias_anticipacion,
        "cursos": [{
            "id": c.id, "curso_id": c.curso_id, "curso": catalogo[c.curso_id].nombre if c.curso_id in catalogo else "",
            "tipo": catalogo[c.curso_id].tipo.value if c.curso_id in catalogo else None,
            "proveedor": catalogo[c.curso_id].proveedor if c.curso_id in catalogo else None,
            "norma_referencia": catalogo[c.curso_id].norma_referencia if c.curso_id in catalogo else None,
            "fecha_inicio": c.fecha_inicio, "fecha_fin": c.fecha_fin, "calificacion": c.calificacion,
            "aprobado": c.aprobado, "folio_constancia": c.folio_constancia, "vigente_hasta": c.vigente_hasta,
            "estado": estado_de(c.vigente_hasta, cfg.dias_anticipacion, hoy).value,
            "dias_para_vencer": (c.vigente_hasta - hoy).days if c.vigente_hasta else None,
            "tiene_certificado": bool(c.certificado_key), "notas": c.notas,
            "habilidad": habilidades[c.habilidad_otorgada_id].nombre
            if c.habilidad_otorgada_id in habilidades else None,
        } for c in cursos],
        "habilidades": [{
            "habilidad_id": f.habilidad_id,
            "habilidad": habilidades[f.habilidad_id].nombre if f.habilidad_id in habilidades else "",
            "clave": habilidades[f.habilidad_id].clave if f.habilidad_id in habilidades else "",
            "certificada": f.certificada, "origen": f.origen.value,
            "fecha_certificacion": f.fecha_certificacion, "vigencia_hasta": f.vigencia_hasta,
            "estado": estado_de(f.vigencia_hasta, cfg.dias_anticipacion, hoy).value if f.certificada else "vencido",
        } for f in filas],
    }


async def proximos_vencimientos(db: AsyncSession, actor: Actor, dias: int | None = None) -> list[dict[str, Any]]:
    """Certificaciones que vencen dentro de la ventana configurada, para el tablero del Admin prestador."""
    _exigir(actor, CONSULTAN_PRESTADOR, "Consultar vencimientos")
    prestador_id = _prestador(actor)
    cfg = await configuracion(db, prestador_id)
    ventana = dias if dias is not None else cfg.dias_anticipacion
    hoy = date.today()
    limite = hoy + timedelta(days=ventana)
    filas = (await db.execute(
        select(TecnicoCurso, CursoCatalogo, Usuario)
        .join(CursoCatalogo, CursoCatalogo.id == TecnicoCurso.curso_id)
        .join(Tecnico, Tecnico.id == TecnicoCurso.tecnico_id)
        .join(Usuario, Usuario.id == Tecnico.usuario_id)
        .where(TecnicoCurso.aprobado.is_(True), TecnicoCurso.vigente_hasta.is_not(None),
               TecnicoCurso.vigente_hasta <= limite)
        .order_by(TecnicoCurso.vigente_hasta))).all()
    return [{
        "tecnico_curso_id": tc.id, "tecnico_id": tc.tecnico_id, "tecnico_nombre": u.nombre,
        "curso": c.nombre, "tipo": c.tipo.value, "norma_referencia": c.norma_referencia,
        "vigente_hasta": tc.vigente_hasta, "dias": (tc.vigente_hasta - hoy).days,
        "estado": estado_de(tc.vigente_hasta, cfg.dias_anticipacion, hoy).value,
        "habilidad_id": tc.habilidad_otorgada_id,
    } for tc, c, u in filas]


# --------------------------------------------------------------------------- vista del cliente

async def tecnicos_de_mis_unidades(db: AsyncSession, actor: Actor) -> list[dict[str, Any]]:
    """§6.10.3: el cliente ve las certificaciones **vigentes** de los técnicos que atienden sus unidades.

    No devuelve calificaciones, cursos no aprobados, certificados adjuntos ni nada interno del prestador.
    """
    _exigir(actor, CONSULTAN_CLIENTE, "Consultar las certificaciones de los técnicos")
    if actor.tenant_id is None and actor.rol != Rol.superadmin:
        raise ErrorAPI(422, "TENANT_REQUERIDO", "Tu usuario no pertenece a un cliente")
    hoy = date.today()
    desde = datetime.now(UTC) - timedelta(days=DIAS_FOLIO_RECIENTE)
    habilitados = select(TecnicoTenantHabilitado.tecnico_id).where(
        TecnicoTenantHabilitado.tenant_id == actor.tenant_id)
    # §5: el Admin UN solo ve lo de sus unidades; el folio reciente ya está acotado por la RLS de folios.
    recientes = (select(Tecnico.id).join(Usuario, Usuario.id == Tecnico.usuario_id)
                 .join(Folio, Folio.tecnico_id == Usuario.id)
                 .where(Folio.capturado_at >= desde))
    filas = (await db.execute(
        select(TecnicoCurso, CursoCatalogo, Usuario)
        .join(CursoCatalogo, CursoCatalogo.id == TecnicoCurso.curso_id)
        .join(Tecnico, Tecnico.id == TecnicoCurso.tecnico_id)
        .join(Usuario, Usuario.id == Tecnico.usuario_id)
        .where(TecnicoCurso.aprobado.is_(True),
               or_(TecnicoCurso.vigente_hasta.is_(None), TecnicoCurso.vigente_hasta >= hoy),
               or_(TecnicoCurso.tecnico_id.in_(habilitados), TecnicoCurso.tecnico_id.in_(recientes)))
        .order_by(Usuario.nombre, CursoCatalogo.nombre))).all()
    por_tecnico: dict[UUID, dict[str, Any]] = {}
    for tc, curso, usuario in filas:
        entrada = por_tecnico.setdefault(tc.tecnico_id, {
            "tecnico_id": tc.tecnico_id, "nombre": usuario.nombre, "certificaciones": []})
        entrada["certificaciones"].append({
            "nombre": curso.nombre, "tipo": curso.tipo.value, "norma_referencia": curso.norma_referencia,
            "proveedor": curso.proveedor, "vigente_hasta": tc.vigente_hasta,
            # Texto listo para mostrarle al cliente: la pantalla no vuelve a formatear la fecha (es un DATE, y
            # pasarlo por un formateador de fecha y hora lo corria un dia hacia atras).
            "vigencia": ("permanente" if tc.vigente_hasta is None
                         else f"vigente hasta el {tc.vigente_hasta.strftime('%d/%m/%Y')}"),
        })
    return list(por_tecnico.values())


# --------------------------------------------------------------------------- vencimiento (tarea diaria)

async def recalcular_estados(db: AsyncSession, hoy: date | None = None) -> dict[str, int]:
    """Tarea diaria: recalcula `estado` y **retira las habilidades que el sistema certificó y ya vencieron**.

    Corre con el rol `sistema`: recorre todos los prestadores.
    """
    hoy = hoy or date.today()
    resumen = {"revisados": 0, "vencidos": 0, "habilidades_retiradas": 0}
    configs = {c.prestador_id: c.dias_anticipacion for c in (await db.execute(
        select(CapacitacionAlertasConfig))).scalars()}
    cursos = list((await db.execute(select(TecnicoCurso).where(TecnicoCurso.aprobado.is_(True)))).scalars())
    for tc in cursos:
        resumen["revisados"] += 1
        nuevo = estado_de(tc.vigente_hasta, configs.get(tc.prestador_id, 30), hoy)
        if nuevo != tc.estado:
            tc.estado = nuevo
        if nuevo == EstadoCursoTecnico.vencido:
            resumen["vencidos"] += 1
            if await _retirar_habilidad(db, tc, hoy):
                resumen["habilidades_retiradas"] += 1
    await db.flush()
    return resumen


async def _retirar_habilidad(db: AsyncSession, tc: TecnicoCurso, hoy: date) -> bool:
    """Quita la certificación que otorgó este curso, si nada más la respalda."""
    if tc.habilidad_otorgada_id is None:
        return False
    fila = (await db.execute(select(TecnicoHabilidad).where(
        TecnicoHabilidad.tecnico_id == tc.tecnico_id,
        TecnicoHabilidad.habilidad_id == tc.habilidad_otorgada_id))).scalar_one_or_none()
    if fila is None or not fila.certificada or fila.origen != OrigenHabilidad.curso:
        return False      # ya no está certificada, o la afirmó el prestador a mano
    # ¿Hay otro curso aprobado y vigente de la misma habilidad? Entonces esa certificación sigue respaldada.
    otro = (await db.execute(select(TecnicoCurso.id).join(CursoCatalogo, CursoCatalogo.id == TecnicoCurso.curso_id)
                             .where(TecnicoCurso.tecnico_id == tc.tecnico_id, TecnicoCurso.aprobado.is_(True),
                                    TecnicoCurso.id != tc.id,
                                    CursoCatalogo.habilidad_id == tc.habilidad_otorgada_id,
                                    or_(TecnicoCurso.vigente_hasta.is_(None),
                                        TecnicoCurso.vigente_hasta >= hoy)))).first()
    if otro is not None:
        return False
    fila.certificada = False
    fila.vigencia_hasta = tc.vigente_hasta
    await db.flush()
    await auditoria.registrar(
        db, "capacitacion.habilidad_retirada_por_vencimiento", actor_rol="sistema",
        prestador_id=tc.prestador_id, recurso_tipo="tecnico_habilidad", recurso_id=fila.id,
        antes={"certificada": True}, despues={"certificada": False, "vigencia_hasta": str(tc.vigente_hasta),
                                              "tecnico_id": str(tc.tecnico_id),
                                              "habilidad_id": str(tc.habilidad_otorgada_id)})
    await alertas_service.disparar(
        db, "CERTIFICACION_VENCIDA_HABILIDAD_RETIRADA", tenant_id=None, prestador_id=tc.prestador_id,
        entidad_tipo="tecnico_habilidad", entidad_id=fila.id,
        datos={"tecnico_id": str(tc.tecnico_id), "habilidad_id": str(tc.habilidad_otorgada_id),
               "vencio_el": str(tc.vigente_hasta)})
    await _avisar(db, tc, retirada=True)
    return True


async def _avisar(db: AsyncSession, tc: TecnicoCurso, *, retirada: bool) -> None:
    """Notifica al Admin prestador siempre, y al cliente solo si `notificar_cliente` está activo (§6.10.3)."""
    cfg = await configuracion(db, tc.prestador_id)
    if not cfg.activa:
        return
    tecnico = await db.get(Tecnico, tc.tecnico_id)
    usuario = await db.get(Usuario, tecnico.usuario_id) if tecnico else None
    curso = await db.get(CursoCatalogo, tc.curso_id)
    nombre = usuario.nombre if usuario else "un técnico"
    evento = "capacitacion.habilidad_retirada" if retirada else "capacitacion.certificacion_por_vencer"
    asunto = (f"Certificación vencida: {nombre}" if retirada
              else f"Certificación por vencer: {nombre}")
    cuerpo = (f"La certificación «{curso.nombre if curso else ''}» de {nombre} venció el {tc.vigente_hasta} y el "
              f"sistema retiró la habilidad que respaldaba: desde hoy no se le puede asignar trabajo que la exija."
              if retirada else
              f"La certificación «{curso.nombre if curso else ''}» de {nombre} vence el {tc.vigente_hasta}.")
    destinos = await notificaciones_service.destinatarios_por_rol(db, [Rol.admin_prestador],
                                                                  prestador_id=tc.prestador_id)
    if cfg.notificar_cliente and tecnico is not None:
        tenants = [t.tenant_id for t in (await db.execute(select(TecnicoTenantHabilitado).where(
            TecnicoTenantHabilitado.tecnico_id == tecnico.id))).scalars()]
        for tenant_id in tenants:
            destinos += await notificaciones_service.destinatarios_por_rol(
                db, [Rol.admin_empresa, Rol.admin_un], tenant_id=tenant_id)
    if not destinos:
        return
    await notificaciones_service.notificar(
        db, evento, list(dict.fromkeys(destinos)),
        {"tecnico_curso_id": str(tc.id), "tecnico_id": str(tc.tecnico_id)},
        asunto=asunto, cuerpo=cuerpo, url=f"/capacitacion?tecnico={tc.tecnico_id}",
        prestador_id=tc.prestador_id, canales=["app", "email"])
