"""Hallazgos (§7.3) y peticiones especiales del cliente: nacen del formulario de atención (campo/sección con `genera_hallazgo`),
de un mensaje de chat marcado por técnico, operador, Admin UN o Despachador, o de una captura manual. P07."""
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.dependencias import Actor
from core.errors import ErrorAPI, no_encontrado, prohibido
from models.base import Dominio, Rol
from models.catalogos import Equipo
from models.chat import Chat, ChatMensaje
from models.folios import Folio, TipoFolio
from models.formularios import FormularioEvidencia, FormularioRespuesta
from models.minutas import EstadoRespuestaHallazgo, Hallazgo, NivelUrgencia, OrigenHallazgo, OrigenPeticion, PeticionCliente, TipoHallazgo
from models.unidades import UnidadNegocio
from models.usuarios import Usuario
from services import auditoria
from services.folio_estados import ActorFolio
from services.preventivos_service import _unidades_visibles

MARCAN_CHAT = {Rol.superadmin, Rol.tecnico, Rol.operador, Rol.admin_un, Rol.despachador}
CAPTURAN_MANUAL = {Rol.superadmin, Rol.admin_prestador, Rol.despachador, Rol.mesa_control, Rol.tecnico, Rol.admin_un, Rol.admin_empresa}
URGENCIAS = {"baja": NivelUrgencia.baja, "media": NivelUrgencia.media, "alta": NivelUrgencia.alta, "critica": NivelUrgencia.critica, "crítica": NivelUrgencia.critica}


def _urgencia(valor: Any) -> NivelUrgencia:
    if isinstance(valor, (int, float)):  # slider 1–10
        return NivelUrgencia.critica if valor >= 9 else NivelUrgencia.alta if valor >= 7 else NivelUrgencia.media if valor >= 4 else NivelUrgencia.baja
    return URGENCIAS.get(str(valor or "").strip().lower(), NivelUrgencia.media)


async def desde_respuesta(db: AsyncSession, actor: ActorFolio, r: FormularioRespuesta, esquema) -> list[Hallazgo]:
    """Al enviarse un formulario de atención: cada campo con `genera_hallazgo` crea un hallazgo con el mapeo (descripción, urgencia,
    foto) y, opcionalmente, solo cuando `condicion_campo == condicion_valor`."""
    if r.tenant_id is None or r.prestador_id is None or r.un_id is None:
        return []
    creados: list[Hallazgo] = []
    respuestas = r.respuestas_json or {}
    for campo in esquema.campos:
        mapeo = getattr(campo, "genera_hallazgo", None)
        if not mapeo:
            continue
        if mapeo.condicion_campo and str(respuestas.get(mapeo.condicion_campo)) != str(mapeo.condicion_valor):
            continue
        descripcion = str(respuestas.get(mapeo.campo_descripcion or campo.clave) or "").strip()
        if not descripcion:
            continue
        foto_id = None
        if mapeo.campo_foto:
            ev = (await db.execute(select(FormularioEvidencia).where(FormularioEvidencia.respuesta_id == r.id, FormularioEvidencia.campo_clave == mapeo.campo_foto)
                                   .order_by(FormularioEvidencia.orden))).scalars().first()
            foto_id = ev.id if ev else None
        folio = await db.get(Folio, r.referencia_id) if r.referencia_id else None
        h = Hallazgo(folio_id=folio.id if folio else None, tenant_id=r.tenant_id, prestador_id=r.prestador_id, un_id=r.un_id, equipo_id=r.equipo_id or (folio.equipo_id if folio else None),
                     descripcion=descripcion[:4000], nivel_urgencia=_urgencia(respuestas.get(mapeo.campo_urgencia)) if mapeo.campo_urgencia else NivelUrgencia(mapeo.urgencia_fija or "media"),
                     foto_evidencia_id=foto_id, tipo=TipoHallazgo.preventivo if folio and folio.tipo_folio == TipoFolio.preventivo else TipoHallazgo.correctivo,
                     origen=OrigenHallazgo.formulario_atencion, respuesta_id=r.id, capturado_por=r.respondido_por, timestamp=r.enviado_at or datetime.now(UTC))
        db.add(h)
        creados.append(h)
    if creados:
        await db.flush()
        for h in creados:
            await auditoria.registrar(db, "hallazgos.creado", actor_rol=str(getattr(actor, "rol", "sistema")), actor_id=getattr(actor, "id", None), tenant_id=h.tenant_id,
                                      prestador_id=h.prestador_id, recurso_tipo="hallazgo", recurso_id=h.id, despues={"origen": "formulario_atencion", "respuesta_id": r.id})
    return creados


async def desde_mensaje(db: AsyncSession, actor: Actor, chat: Chat, mensaje: ChatMensaje, *, como: str, urgencia: NivelUrgencia | None, request: Request | None):
    """`como` = hallazgo | peticion. El mensaje queda marcado en `datos_json` para no duplicar."""
    if actor.rol not in MARCAN_CHAT:
        raise prohibido("Solo técnico, operador, Admin UN y Despachador marcan mensajes como hallazgo o petición")
    if mensaje.chat_id != chat.id:
        raise no_encontrado("Mensaje")
    if not (mensaje.contenido_texto or "").strip():
        raise ErrorAPI(422, "MENSAJE_SIN_TEXTO", "Solo se marcan mensajes con texto")
    if mensaje.datos_json.get("marcado_como"):
        raise ErrorAPI(409, "MENSAJE_YA_MARCADO", f"El mensaje ya está marcado como {mensaje.datos_json['marcado_como']}")
    folio = await db.get(Folio, chat.folio_id)
    if folio is None:
        raise no_encontrado("Folio")
    if como == "hallazgo":
        registro = Hallazgo(folio_id=folio.id, tenant_id=folio.tenant_id, prestador_id=folio.prestador_id, un_id=folio.un_id, equipo_id=folio.equipo_id,
                            descripcion=mensaje.contenido_texto.strip()[:4000], nivel_urgencia=urgencia or NivelUrgencia.media,
                            tipo=TipoHallazgo.preventivo if folio.tipo_folio == TipoFolio.preventivo else TipoHallazgo.correctivo, origen=OrigenHallazgo.chat,
                            mensaje_id=mensaje.id, capturado_por=actor.id, timestamp=datetime.now(UTC))
    elif como == "peticion":
        registro = PeticionCliente(folio_id=folio.id, tenant_id=folio.tenant_id, prestador_id=folio.prestador_id, un_id=folio.un_id, texto=mensaje.contenido_texto.strip()[:4000],
                                   origen=OrigenPeticion.chat, mensaje_id=mensaje.id, capturado_por=actor.id, timestamp=datetime.now(UTC))
    else:
        raise ErrorAPI(422, "MARCA_INVALIDA", "Marca el mensaje como hallazgo o peticion")
    db.add(registro)
    mensaje.datos_json = {**mensaje.datos_json, "marcado_como": como, "marcado_por": str(actor.id)}
    await db.flush()
    await auditoria.registrar_actor(db, actor, f"{'hallazgos' if como == 'hallazgo' else 'peticiones'}.desde_chat", request, tenant_id=folio.tenant_id,
                                    prestador_id=folio.prestador_id, recurso_tipo=como, recurso_id=registro.id, despues={"mensaje_id": mensaje.id, "folio_id": folio.id})
    return registro


async def crear_manual(db: AsyncSession, actor: Actor, datos: dict[str, Any], request: Request | None) -> Hallazgo:
    if actor.rol not in CAPTURAN_MANUAL:
        raise prohibido("Tu rol no captura hallazgos")
    folio = None
    if datos.get("folio_id"):
        from services import folios_captura_service

        folio = await folios_captura_service.obtener(db, actor, datos["folio_id"])
    un = await db.get(UnidadNegocio, datos["un_id"] if not folio else folio.un_id)
    if un is None:
        raise ErrorAPI(422, "UNIDAD_INVALIDA", "La unidad no existe")
    if actor.dominio == Dominio.tenant and un.tenant_id != actor.tenant_id:
        raise no_encontrado("Unidad")
    prestador_id = folio.prestador_id if folio else (actor.prestador_id or datos.get("prestador_id"))
    if prestador_id is None:
        from models.organizaciones import TenantPrestador

        prestador_id = (await db.execute(select(TenantPrestador.prestador_id).where(TenantPrestador.tenant_id == un.tenant_id))).scalar()
    equipo_id = folio.equipo_id if folio else datos.get("equipo_id")
    if equipo_id and not folio:
        eq = await db.get(Equipo, equipo_id)
        if eq is None or eq.un_id != un.id:
            raise ErrorAPI(422, "EQUIPO_INVALIDO", "El equipo no pertenece a la unidad")
    h = Hallazgo(folio_id=folio.id if folio else None, tenant_id=un.tenant_id, prestador_id=prestador_id, un_id=un.id, equipo_id=equipo_id, descripcion=datos["descripcion"],
                 nivel_urgencia=NivelUrgencia(datos.get("nivel_urgencia") or "media"), tipo=TipoHallazgo(datos.get("tipo") or ("preventivo" if folio and folio.tipo_folio == TipoFolio.preventivo else "correctivo")),
                 origen=OrigenHallazgo.manual, capturado_por=actor.id, timestamp=datetime.now(UTC))
    db.add(h)
    await db.flush()
    await auditoria.registrar_actor(db, actor, "hallazgos.creado", request, tenant_id=h.tenant_id, prestador_id=h.prestador_id, recurso_tipo="hallazgo", recurso_id=h.id,
                                    despues={"origen": "manual", "folio_id": folio.id if folio else None})
    return h


async def alcance(db: AsyncSession, actor: Actor, consulta, modelo):
    if actor.es_superadmin:
        return consulta
    if actor.dominio == Dominio.tenant:
        consulta = consulta.where(modelo.tenant_id == actor.tenant_id)
        unidades = await _unidades_visibles(db, actor)
        if unidades is not None:
            consulta = consulta.where(modelo.un_id.in_(unidades))
        return consulta
    if actor.rol == Rol.tecnico:
        return consulta.where(modelo.capturado_por == actor.id)
    return consulta.where(modelo.prestador_id == actor.prestador_id)


async def listar(db: AsyncSession, actor: Actor, filtros: dict[str, Any]) -> list[Hallazgo]:
    consulta = select(Hallazgo).order_by(Hallazgo.timestamp.desc())
    consulta = await alcance(db, actor, consulta, Hallazgo)
    for k in ("tenant_id", "un_id", "folio_id"):
        if filtros.get(k):
            consulta = consulta.where(getattr(Hallazgo, k) == filtros[k])
    if filtros.get("estado_respuesta"):
        consulta = consulta.where(Hallazgo.estado_respuesta == EstadoRespuestaHallazgo(filtros["estado_respuesta"]))
    if filtros.get("desde"):
        consulta = consulta.where(Hallazgo.timestamp >= filtros["desde"])
    if filtros.get("hasta"):
        consulta = consulta.where(Hallazgo.timestamp <= filtros["hasta"])
    return list((await db.execute(consulta.limit(500))).scalars())


async def obtener(db: AsyncSession, actor: Actor, hallazgo_id: UUID) -> Hallazgo:
    h = (await db.execute(await alcance(db, actor, select(Hallazgo).where(Hallazgo.id == hallazgo_id), Hallazgo))).scalar_one_or_none()
    if h is None:
        raise no_encontrado("Hallazgo")
    return h


async def enriquecer(db: AsyncSession, lista: list[Hallazgo]) -> list[dict[str, Any]]:
    if not lista:
        return []
    equipos = {e.id: e for e in (await db.execute(select(Equipo).where(Equipo.id.in_({h.equipo_id for h in lista if h.equipo_id})))).scalars()} if any(h.equipo_id for h in lista) else {}
    unidades = {u.id: u for u in (await db.execute(select(UnidadNegocio).where(UnidadNegocio.id.in_({h.un_id for h in lista})))).scalars()}
    folios = {f.id: f for f in (await db.execute(select(Folio).where(Folio.id.in_({h.folio_id for h in lista if h.folio_id})))).scalars()} if any(h.folio_id for h in lista) else {}
    ids = {h.capturado_por for h in lista if h.capturado_por} | {h.respondido_por for h in lista if h.respondido_por}
    nombres = {u.id: u.nombre for u in (await db.execute(select(Usuario).where(Usuario.id.in_(ids)))).scalars()} if ids else {}
    salida = []
    for h in lista:
        eq, un, f = equipos.get(h.equipo_id), unidades.get(h.un_id), folios.get(h.folio_id)
        salida.append({**auditoria.instantanea(h), "id": h.id, "folio_id": h.folio_id, "tenant_id": h.tenant_id, "prestador_id": h.prestador_id, "un_id": h.un_id, "equipo_id": h.equipo_id,
                       "foto_evidencia_id": h.foto_evidencia_id, "respuesta_id": h.respuesta_id, "mensaje_id": h.mensaje_id, "capturado_por": h.capturado_por,
                       "respondido_por": h.respondido_por, "modulo_registro_id": h.modulo_registro_id, "timestamp": h.timestamp, "respondido_at": h.respondido_at,
                       "created_at": h.created_at, "updated_at": h.updated_at,
                       "equipo_codigo": eq.codigo if eq else None, "equipo_nombre": eq.nombre if eq else None, "un_codigo": un.codigo if un else None, "un_nombre": un.nombre if un else None,
                       "numero_folio": f.numero_folio if f else None, "capturado_por_nombre": nombres.get(h.capturado_por), "respondido_por_nombre": nombres.get(h.respondido_por),
                       "foto_url": f"/api/formularios/respuestas/{h.respuesta_id}/evidencias/{h.foto_evidencia_id}/archivo" if h.foto_evidencia_id and h.respuesta_id else None})
    return salida


async def peticiones(db: AsyncSession, actor: Actor, filtros: dict[str, Any]) -> list[PeticionCliente]:
    consulta = select(PeticionCliente).order_by(PeticionCliente.timestamp.desc())
    consulta = await alcance(db, actor, consulta, PeticionCliente)
    for k in ("tenant_id", "un_id", "folio_id"):
        if filtros.get(k):
            consulta = consulta.where(getattr(PeticionCliente, k) == filtros[k])
    return list((await db.execute(consulta.limit(500))).scalars())
