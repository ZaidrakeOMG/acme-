"""Sincronización con los dispositivos (§6.2 capa 3): paquete incremental de catálogos por rol y cola de mutaciones
capturadas offline, aplicadas en orden e idempotentes por `id_cliente`, con las reglas de conflicto literales:
catálogos → server-wins; capturas en campo → client-wins (se conserva `timestamp_dispositivo` como hora real);
movimientos de inventario → merge con alerta (gancho para P09)."""
import base64
import hashlib
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi import Request
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.dependencias import Actor
from core.errors import ErrorAPI, no_encontrado, prohibido
from models.base import Dominio, EstadoRegistro, Rol
from models.catalogos import Equipo, EstadoActivo, FamiliaEquipo, NivelSeveridadCatalogo, TipoEquipo, TipoFalla
from models.chat import ReglaConflicto, ResultadoMutacion, SincronizacionConflicto, SincronizacionDispositivo, SincronizacionMutacion, TipoMensaje
from models.folios import EstadoFolio, Folio, FolioRefaccion, TipoFolio
from models.formularios import EstadoRespuesta, FormularioEvidencia, FormularioRespuesta
from models.unidades import GrupoUNMiembro, UnidadNegocio, UsuarioGrupo, UsuarioUN
from schemas.folios import FolioEntrada
from schemas.formularios import RespuestaEntrada
from services import auditoria, catalogos_service, chat_service, folio_estados
from services import folios_captura_service as captura
from services.formularios import servicio as formularios

TIPOS_MUTACION = ("crear_folio", "transicion", "guardar_respuesta", "enviar_respuesta", "subir_evidencia", "agregar_refaccion", "mensaje_chat")
ROLES_OPERADOR = {Rol.operador, Rol.admin_un, Rol.admin_empresa, Rol.supervisor_operadores, Rol.mesa_control}


def _fila(obj, campos: tuple[str, ...]) -> dict[str, Any]:
    return {k: auditoria.a_json(getattr(obj, k)) for k in campos}


# ------------------------------------------------------------- catálogos

async def _unidades_visibles(db: AsyncSession, actor: Actor) -> list[UnidadNegocio]:
    consulta = select(UnidadNegocio).order_by(UnidadNegocio.codigo)
    if actor.rol in (Rol.admin_un, Rol.operador):
        consulta = consulta.where(UnidadNegocio.id.in_(select(UsuarioUN.unidad_id).where(UsuarioUN.usuario_id == actor.id)))
    elif actor.rol == Rol.supervisor_operadores:
        por_grupo = select(GrupoUNMiembro.unidad_id).join(UsuarioGrupo, UsuarioGrupo.grupo_id == GrupoUNMiembro.grupo_id).where(UsuarioGrupo.usuario_id == actor.id)
        directas = select(UsuarioUN.unidad_id).where(UsuarioUN.usuario_id == actor.id)
        consulta = consulta.where(or_(UnidadNegocio.id.in_(por_grupo), UnidadNegocio.id.in_(directas)))
    elif actor.dominio == Dominio.tenant:
        consulta = consulta.where(UnidadNegocio.tenant_id == actor.tenant_id)
    return list((await db.execute(consulta)).scalars())


def _desde(consulta, modelo, desde: datetime | None):
    return consulta.where(modelo.updated_at > desde) if desde else consulta


async def _registrar_dispositivo(db: AsyncSession, actor: Actor, dispositivo_id: str | None, version_app: str | None, plataforma: str | None) -> None:
    if not dispositivo_id:
        return
    d = (await db.execute(select(SincronizacionDispositivo).where(
        SincronizacionDispositivo.usuario_id == actor.id, SincronizacionDispositivo.dispositivo_id == dispositivo_id))).scalar_one_or_none()
    if d is None:
        d = SincronizacionDispositivo(usuario_id=actor.id, tenant_id=actor.tenant_id, prestador_id=actor.prestador_id, dispositivo_id=dispositivo_id)
        db.add(d)
    d.ultimo_sync_at = datetime.now(UTC)
    if version_app:
        d.version_app = version_app
    if plataforma:
        d.plataforma = plataforma
    await db.flush()


async def catalogos(db: AsyncSession, actor: Actor, desde: datetime | None, dispositivo_id: str | None, version_app: str | None = None,
                    plataforma: str | None = None) -> dict[str, Any]:
    """Solo registros con updated_at > desde. Incluye bajas lógicas (activo/estado) para que el dispositivo las retire."""
    ahora = datetime.now(UTC)
    salida: dict[str, Any] = {"servidor_at": ahora.isoformat(), "desde": desde.isoformat() if desde else None, "rol": actor.rol.value}
    unidades = await _unidades_visibles(db, actor)
    ids_un = [u.id for u in unidades]
    if actor.rol in ROLES_OPERADOR or actor.es_superadmin:
        salida["unidades"] = [{**_fila(u, ("id", "tenant_id", "codigo", "nombre", "direccion", "zona_horaria", "estado", "grupo_id", "updated_at", "version_hash")),
                               "activo": u.estado == EstadoRegistro.activo}
                              for u in unidades if not desde or u.updated_at > desde]
        equipos = (await db.execute(_desde(select(Equipo, TipoEquipo.familia_id, catalogos_service.CON_CONTRATO)
                                           .join(TipoEquipo, TipoEquipo.id == Equipo.tipo_equipo_id)
                                           .where(Equipo.un_id.in_(ids_un)), Equipo, desde))).all()
        salida["equipos"] = [{**_fila(e, ("id", "tenant_id", "un_id", "tipo_equipo_id", "codigo", "nombre", "marca", "modelo", "numero_serie", "estado",
                                          "garantia_vigente_hasta", "criticidad", "updated_at", "version_hash")),
                              "familia_id": fam, "con_contrato_activo": bool(cc), "activo": e.estado == EstadoActivo.activo} for e, fam, cc in equipos]
        tenant_id = actor.tenant_id or (unidades[0].tenant_id if unidades else None)
        prestadores = await catalogos_service.prestadores_del_tenant(db, tenant_id) if tenant_id else []
        familias = (await db.execute(_desde(select(FamiliaEquipo).where(or_(FamiliaEquipo.tenant_id.is_(None), FamiliaEquipo.tenant_id == tenant_id)), FamiliaEquipo, desde))).scalars().all()
        salida["familias_equipo"] = [{**_fila(f, ("id", "tenant_id", "nombre", "habilidad_clave", "updated_at", "version_hash")), "activo": f.activa} for f in familias]
        tipos = (await db.execute(_desde(select(TipoEquipo).where(or_(TipoEquipo.tenant_id.is_(None), TipoEquipo.tenant_id == tenant_id)), TipoEquipo, desde))).scalars().all()
        salida["tipos_equipo"] = [{**_fila(t, ("id", "familia_id", "tenant_id", "nombre", "updated_at", "version_hash")), "activo": t.activa} for t in tipos]
        fallas = (await db.execute(_desde(select(TipoFalla).where(TipoFalla.prestador_id.in_(prestadores)), TipoFalla, desde))).scalars().all()
        salida["tipos_falla"] = [{**_fila(t, ("id", "prestador_id", "descripcion", "familia_equipo_id", "requiere_revision_manual", "updated_at", "version_hash")), "activo": t.activa} for t in fallas]
        niveles = (await db.execute(_desde(select(NivelSeveridadCatalogo).where(NivelSeveridadCatalogo.prestador_id.in_(prestadores)), NivelSeveridadCatalogo, desde))).scalars().all()
        salida["niveles_severidad"] = [{**_fila(n, ("id", "prestador_id", "clave", "nombre", "orden", "color_hex", "tiempo_respuesta_horas", "tiempo_resolucion_horas", "updated_at", "version_hash")), "activo": n.activo} for n in niveles]
        formularios_captura = await formularios.listar(db, actor, "captura_operador", None, "publicado", None, None)
        salida["formularios"] = [await formularios.salida(db, actor, f) for f in formularios_captura if not desde or f.updated_at > desde]
        salida["formularios_ids"] = [str(f.id) for f in formularios_captura]
    if actor.rol == Rol.tecnico or actor.es_superadmin:
        folios = await captura.listar(db, actor, tenant_id=None, un_id=None, grupo_id=None, estado=[e for e in EstadoFolio if e not in (EstadoFolio.cerrado, EstadoFolio.cancelado)],
                                      severidad_id=None, tecnico_id=actor.id if actor.rol == Rol.tecnico else None, desde=None, hasta=None, tipo_folio=None, q=None, limite=500)
        resumen = await captura.resumen(db, folios)
        salida["folios"] = [auditoria.a_json(r) for r in resumen if not desde or any(f.id == r["id"] and f.updated_at > desde for f in folios)]
        salida["folios_ids"] = [str(f.id) for f in folios]
        atencion: dict[str, Any] = {}
        for f in folios:
            equipo = await db.get(Equipo, f.equipo_id)
            tipo = await db.get(TipoEquipo, equipo.tipo_equipo_id) if equipo else None
            tipo_formulario = {TipoFolio.preventivo: "preventivo", TipoFolio.especial: "trabajo_especial"}.get(f.tipo_folio, "atencion_tecnico")
            resultado = await formularios.resolver(db, actor, tipo_formulario, f.tenant_id, equipo.tipo_equipo_id if equipo else None,
                                                   tipo.familia_id if tipo else None, f.plan_id, actor.prestador_id, f.tipo_folio.value)
            if resultado:
                formulario = resultado[0]
                if str(formulario.id) not in atencion:
                    atencion[str(formulario.id)] = await formularios.salida(db, actor, formulario)
                salida.setdefault("formulario_por_folio", {})[str(f.id)] = str(formulario.id)
        preventivos = await formularios.listar(db, actor, "preventivo", None, "publicado", None, None)
        for f in preventivos:
            atencion.setdefault(str(f.id), await formularios.salida(db, actor, f))
        salida["formularios"] = [v for v in atencion.values() if not desde or datetime.fromisoformat(str(v["updated_at"])) > desde]
        salida["formularios_ids"] = list(atencion)
        salida["refacciones"] = []       # catálogo de inventario: P09
        salida["biblioteca"] = []        # manuales técnicos: Fase 2
    await _registrar_dispositivo(db, actor, dispositivo_id, version_app, plataforma)
    return salida


# ------------------------------------------------------------- mutaciones

class _Rechazo(Exception):
    def __init__(self, codigo: str, mensaje: str):
        super().__init__(mensaje)
        self.codigo, self.mensaje = codigo, mensaje


async def _ledger(db: AsyncSession, actor: Actor, id_cliente: uuid.UUID) -> SincronizacionMutacion | None:
    return (await db.execute(select(SincronizacionMutacion).where(
        SincronizacionMutacion.usuario_id == actor.id, SincronizacionMutacion.id_cliente == id_cliente))).scalar_one_or_none()


async def _resolver_id(db: AsyncSession, actor: Actor, mapa: dict[str, uuid.UUID], valor: Any) -> uuid.UUID | None:
    """Un id puede ser del servidor o el `id_cliente` de una operación previa (misma tanda o ya aplicada)."""
    if not valor:
        return None
    texto = str(valor)
    if texto in mapa:
        return mapa[texto]
    try:
        uid = uuid.UUID(texto)
    except ValueError:
        raise _Rechazo("ID_INVALIDO", f"Identificador inválido: {texto}")
    previa = await _ledger(db, actor, uid)
    if previa is not None and previa.entidad_id:
        return previa.entidad_id
    return uid


async def _conflicto(db: AsyncSession, actor: Actor, dispositivo_id: str | None, entidad: str, entidad_id: uuid.UUID | None,
                     regla: ReglaConflicto, cliente: dict, servidor: dict) -> None:
    db.add(SincronizacionConflicto(usuario_id=actor.id, tenant_id=actor.tenant_id, prestador_id=actor.prestador_id, dispositivo_id=dispositivo_id,
                                   entidad=entidad, entidad_id=entidad_id, regla_aplicada=regla, datos_cliente_json=auditoria.a_json(cliente),
                                   datos_servidor_json=auditoria.a_json(servidor), resuelto_at=datetime.now(UTC)))
    await db.flush()


async def _aplicar_una(db: AsyncSession, actor: Actor, m, mapa: dict[str, uuid.UUID], dispositivo_id: str | None, request: Request | None,
                       publicar: list) -> tuple[uuid.UUID | None, bool]:
    """Devuelve (entidad_id, ya_existia)."""
    p = dict(m.payload or {})
    ts = m.timestamp_dispositivo
    if m.tipo == "crear_folio":
        if p.get("respuesta_id"):
            p["respuesta_id"] = await _resolver_id(db, actor, mapa, p["respuesta_id"])
        datos = FolioEntrada(**{k: v for k, v in p.items() if k in FolioEntrada.model_fields})
        folio = await captura.crear(db, actor, datos, request, ahora=ts)
        return folio.id, False
    if m.tipo == "transicion":
        folio = await captura.obtener(db, actor, await _resolver_id(db, actor, mapa, p.get("folio_id")))
        estado = EstadoFolio(p["estado"])
        contexto = dict(p.get("contexto") or {})
        if ts and folio.updated_at and folio.updated_at > ts:
            await _conflicto(db, actor, dispositivo_id, "folio", folio.id, ReglaConflicto.client_wins,
                             {"estado": estado.value, "timestamp_dispositivo": ts.isoformat()}, {"estado": folio.estado.value, "updated_at": folio.updated_at.isoformat()})
        if estado == EstadoFolio.asignado and contexto.get("tecnico_id"):
            await captura.asignar(db, actor, folio, uuid.UUID(str(contexto["tecnico_id"])), contexto.get("razon"), p.get("notas", ""), request)
        elif estado == EstadoFolio.autorizado and folio.estado == EstadoFolio.en_revision and not actor.es_superadmin:
            await captura.autorizar_manual(db, actor, folio, p.get("notas", ""), request)
        else:
            await folio_estados.transicionar(db, folio, estado, actor, p.get("notas", ""), contexto, request, momento=ts)
        return folio.id, False
    if m.tipo == "guardar_respuesta":
        rid = await _resolver_id(db, actor, mapa, p.get("respuesta_id"))
        r = await db.get(FormularioRespuesta, rid) if rid else None
        if r is None:
            crear = p.get("crear") or {}
            if not crear.get("formulario_id"):
                raise _Rechazo("RESPUESTA_INVALIDA", "La respuesta no existe y no se indicó cómo crearla")
            contexto = dict(crear.get("contexto") or {})
            if crear.get("referencia_id"):
                crear["referencia_id"] = await _resolver_id(db, actor, mapa, crear["referencia_id"])
            entrada = RespuestaEntrada(origen=crear.get("origen", "independiente"), referencia_id=crear.get("referencia_id"), contexto=contexto,
                                       dispositivo={"dispositivo_id": dispositivo_id, "timestamp_dispositivo": ts.isoformat() if ts else None})
            r = await formularios.crear_respuesta(db, actor, uuid.UUID(str(crear["formulario_id"])), entrada, request)
            if p.get("respuesta_id"):
                mapa[str(p["respuesta_id"])] = r.id
        elif p.get("version_hash") and r.version_hash and p["version_hash"] != r.version_hash:
            await _conflicto(db, actor, dispositivo_id, "formulario_respuesta", r.id, ReglaConflicto.client_wins,
                             {"respuestas": p.get("respuestas"), "version_hash": p["version_hash"]}, {"respuestas": r.respuestas_json, "version_hash": r.version_hash})
        if r.estado == EstadoRespuesta.enviado:
            return r.id, True
        await formularios.guardar_parcial(db, actor, r, p.get("respuestas") or {}, {"dispositivo_id": dispositivo_id, "timestamp_dispositivo": ts.isoformat() if ts else None})
        return r.id, False
    if m.tipo == "enviar_respuesta":
        rid = await _resolver_id(db, actor, mapa, p.get("respuesta_id"))
        r = await formularios.obtener_respuesta(db, actor, rid)
        if r.estado == EstadoRespuesta.enviado:
            return r.id, True
        if p.get("respuestas"):
            await formularios.guardar_parcial(db, actor, r, p["respuestas"], None)
        await formularios.enviar(db, actor, r, request, momento=ts)
        return r.id, False
    if m.tipo == "subir_evidencia":
        rid = await _resolver_id(db, actor, mapa, p.get("respuesta_id"))
        r = await formularios.obtener_respuesta(db, actor, rid)
        contenido = base64.b64decode(p.get("contenido_base64") or "")
        if not contenido:
            raise _Rechazo("ARCHIVO_VACIO", "La evidencia no trae contenido")
        hash_ = hashlib.sha256(contenido).hexdigest()
        if p.get("hash_sha256") and p["hash_sha256"] != hash_:
            raise _Rechazo("HASH_INVALIDO", "El contenido no coincide con el hash declarado")
        existente = (await db.execute(select(FormularioEvidencia).where(FormularioEvidencia.respuesta_id == r.id, FormularioEvidencia.hash_sha256 == hash_))).scalars().first()
        if existente is not None:
            return existente.id, True
        e, _calidad = await formularios.subir_evidencia(db, actor, r, p["campo_clave"], contenido, p.get("nombre") or "evidencia", p.get("mime") or "image/jpeg",
                                                        p.get("etiqueta"), p.get("orden"), p.get("anotaciones"), None, p.get("geolat"), p.get("geolng"), request)
        return e.id, False
    if m.tipo == "agregar_refaccion":
        folio = await captura.obtener(db, actor, await _resolver_id(db, actor, mapa, p.get("folio_id")))
        if folio.estado in (EstadoFolio.cerrado, EstadoFolio.cancelado):
            raise _Rechazo("FOLIO_INMUTABLE", "El folio está cerrado o cancelado")
        if actor.rol == Rol.tecnico and folio.tecnico_id != actor.id:
            raise _Rechazo("PROHIBIDO", "El folio no está asignado a ti")
        ref = FolioRefaccion(folio_id=folio.id, tenant_id=folio.tenant_id, prestador_id=folio.prestador_id, descripcion=str(p.get("descripcion", ""))[:200],
                             cantidad=Decimal(str(p.get("cantidad", 1))), origen=p.get("origen", "almacen"), costo_unitario=Decimal(str(p.get("costo_unitario", 0))),
                             articulo_id=uuid.UUID(str(p["articulo_id"])) if p.get("articulo_id") else None)
        db.add(ref)
        await db.flush()
        await aplicar_movimiento_inventario(db, actor, ref, dispositivo_id, ts)
        return ref.id, False
    if m.tipo == "mensaje_chat":
        chat = await chat_service.obtener_chat(db, uuid.UUID(str(p["chat_id"])))
        archivo = None
        if p.get("contenido_base64"):
            archivo = (base64.b64decode(p["contenido_base64"]), p.get("nombre") or "adjunto", p.get("mime") or "application/octet-stream")
        mensaje, dup = await chat_service.enviar_mensaje(db, actor, chat, contenido=p.get("contenido_texto") or "", tipo=TipoMensaje(p.get("tipo", "texto")),
                                                        id_cliente=m.id_cliente, timestamp_dispositivo=ts, archivo=archivo, datos=p.get("datos"), request=request)
        if not dup:
            publicar.append((mensaje, actor.nombre))
        return mensaje.id, dup
    raise _Rechazo("TIPO_DESCONOCIDO", f"Tipo de mutación no soportado: {m.tipo}")


async def aplicar_movimiento_inventario(db: AsyncSession, actor: Actor, refaccion: FolioRefaccion, dispositivo_id: str | None, ts: datetime | None) -> None:
    """Gancho §6.2 "merge con alerta": P09 descuenta el stock y, si queda negativo, registra el conflicto y alerta al despachador."""
    return None


async def aplicar_mutaciones(db: AsyncSession, actor: Actor, lote, request: Request | None) -> tuple[list[dict[str, Any]], list]:
    resultados: list[dict[str, Any]] = []
    publicar: list = []
    mapa: dict[str, uuid.UUID] = {}
    for m in lote.mutaciones:
        previa = await _ledger(db, actor, m.id_cliente)
        if previa is not None:
            if previa.entidad_id:
                mapa[str(m.id_cliente)] = previa.entidad_id
            resultados.append({"id_cliente": m.id_cliente, "tipo": m.tipo, "resultado": "duplicada", "entidad_id": previa.entidad_id,
                               "codigo": previa.codigo, "mensaje": "Ya se había aplicado"})
            continue
        resultado, entidad_id, codigo, mensaje = ResultadoMutacion.aplicada, None, None, ""
        punto = await db.begin_nested()
        try:
            entidad_id, existia = await _aplicar_una(db, actor, m, mapa, lote.dispositivo_id, request, publicar)
            await punto.commit()
            if existia:
                resultado, mensaje = ResultadoMutacion.duplicada, "Ya existía en el servidor"
        except _Rechazo as e:
            await punto.rollback()
            resultado, codigo, mensaje = ResultadoMutacion.rechazada, e.codigo, e.mensaje
        except ErrorAPI as e:
            await punto.rollback()
            resultado, codigo, mensaje = ResultadoMutacion.rechazada, e.codigo, e.mensaje
        except Exception as e:  # noqa: BLE001 — una operación fallida no detiene a las siguientes
            await punto.rollback()
            resultado, codigo, mensaje = ResultadoMutacion.rechazada, "ERROR_INTERNO", str(e)[:300]
        if entidad_id:
            mapa[str(m.id_cliente)] = entidad_id
        db.add(SincronizacionMutacion(usuario_id=actor.id, tenant_id=actor.tenant_id, prestador_id=actor.prestador_id, dispositivo_id=lote.dispositivo_id,
                                      id_cliente=m.id_cliente, tipo=m.tipo, resultado=resultado, entidad_id=entidad_id, codigo=codigo, mensaje=mensaje,
                                      timestamp_dispositivo=m.timestamp_dispositivo))
        await db.flush()
        resultados.append({"id_cliente": m.id_cliente, "tipo": m.tipo, "resultado": resultado.value, "entidad_id": entidad_id, "codigo": codigo, "mensaje": mensaje})
    await _registrar_dispositivo(db, actor, lote.dispositivo_id, lote.version_app, lote.plataforma)
    return resultados, publicar


# ------------------------------------------------------- evidencias en dos pasos

async def iniciar_evidencia(db: AsyncSession, actor: Actor, datos) -> dict[str, Any]:
    previa = await _ledger(db, actor, datos.id_cliente)
    if previa is not None:
        return {"estado": "duplicada", "evidencia_id": previa.entidad_id, "subir_a": None}
    rid = await _resolver_id(db, actor, {}, datos.respuesta_id)
    r = await formularios.obtener_respuesta(db, actor, rid)
    existente = (await db.execute(select(FormularioEvidencia).where(
        FormularioEvidencia.respuesta_id == r.id, FormularioEvidencia.hash_sha256 == datos.hash_sha256))).scalars().first()
    if existente is not None:
        db.add(SincronizacionMutacion(usuario_id=actor.id, tenant_id=actor.tenant_id, prestador_id=actor.prestador_id, id_cliente=datos.id_cliente,
                                      tipo="subir_evidencia", resultado=ResultadoMutacion.duplicada, entidad_id=existente.id, mensaje="Hash ya registrado"))
        await db.flush()
        return {"estado": "existente", "evidencia_id": existente.id, "subir_a": None}
    return {"estado": "pendiente", "evidencia_id": None, "subir_a": f"/api/sync/evidencias/{datos.id_cliente}/archivo"}


async def subir_evidencia(db: AsyncSession, actor: Actor, id_cliente: uuid.UUID, respuesta_id: str, campo_clave: str, contenido: bytes, nombre: str, mime: str,
                          hash_sha256: str | None, etiqueta: str | None, geolat: float | None, geolng: float | None, dispositivo_id: str | None,
                          timestamp_dispositivo: datetime | None, request: Request | None) -> tuple[FormularioEvidencia, str]:
    previa = await _ledger(db, actor, id_cliente)
    if previa is not None and previa.entidad_id:
        e = await db.get(FormularioEvidencia, previa.entidad_id)
        if e is not None:
            return e, "duplicada"
    hash_ = hashlib.sha256(contenido).hexdigest()
    if hash_sha256 and hash_sha256 != hash_:
        raise ErrorAPI(422, "HASH_INVALIDO", "El contenido no coincide con el hash declarado")
    rid = await _resolver_id(db, actor, {}, respuesta_id)
    r = await formularios.obtener_respuesta(db, actor, rid)
    existente = (await db.execute(select(FormularioEvidencia).where(FormularioEvidencia.respuesta_id == r.id, FormularioEvidencia.hash_sha256 == hash_))).scalars().first()
    if existente is not None:
        e, resultado = existente, "duplicada"
    else:
        e, _ = await formularios.subir_evidencia(db, actor, r, campo_clave, contenido, nombre, mime, etiqueta, None, None, None, geolat, geolng, request)
        resultado = "aplicada"
    if previa is None:
        db.add(SincronizacionMutacion(usuario_id=actor.id, tenant_id=actor.tenant_id, prestador_id=actor.prestador_id, dispositivo_id=dispositivo_id,
                                      id_cliente=id_cliente, tipo="subir_evidencia", resultado=ResultadoMutacion(resultado), entidad_id=e.id,
                                      timestamp_dispositivo=timestamp_dispositivo))
        await db.flush()
    return e, resultado


async def conflictos_de(db: AsyncSession, actor: Actor, limite: int = 100) -> list[SincronizacionConflicto]:
    consulta = select(SincronizacionConflicto).order_by(SincronizacionConflicto.created_at.desc()).limit(limite)
    if not actor.es_superadmin and actor.rol not in (Rol.admin_prestador, Rol.admin_empresa, Rol.despachador, Rol.mesa_control):
        consulta = consulta.where(SincronizacionConflicto.usuario_id == actor.id)
    return list((await db.execute(consulta)).scalars())
