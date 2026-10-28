"""Cierre del folio desde campo (§6.8.6 datos de cierre, §6.9.1): firma del operador, encuesta de satisfacción NPS y
secuencia técnico envía atención → operador firma → sistema genera la encuesta → `cerrar`."""
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.dependencias import Actor
from core.errors import ErrorAPI, prohibido
from models.base import Rol
from models.catalogos import Equipo, TipoEquipo
from models.folios import EstadoFolio, Folio, FolioEncuesta, FolioEvidencia, TipoEvidenciaFolio
from models.unidades import UsuarioUN
from schemas.formularios import RespuestaEntrada
from services import aprobacion_service, auditoria, folio_estados, push_service
from services.almacenamiento import obtener_almacenamiento
from services.folio_estados import ACTOR_SISTEMA
from services.formularios import servicio as formularios

FIRMAN = {Rol.operador, Rol.admin_un}


async def _exigir_operador_de_la_un(db: AsyncSession, actor: Actor, folio: Folio) -> None:
    if actor.es_superadmin:
        return
    if actor.rol not in FIRMAN or actor.tenant_id != folio.tenant_id:
        raise prohibido("Solo el operador o el Admin UN de la unidad firman y contestan la encuesta")
    asignado = (await db.execute(select(UsuarioUN.id).where(UsuarioUN.usuario_id == actor.id, UsuarioUN.unidad_id == folio.un_id))).first()
    if asignado is None:
        raise prohibido("La unidad del folio no está entre tus UNs asignadas")


async def firmar(db: AsyncSession, actor: Actor, folio: Folio, imagen: bytes, mime: str, geolat: float | None, geolng: float | None,
                 timestamp_dispositivo: datetime | None, request: Request | None) -> FolioEvidencia:
    await _exigir_operador_de_la_un(db, actor, folio)
    if folio.estado not in (EstadoFolio.en_ejecucion, EstadoFolio.pendiente_refaccion):
        raise ErrorAPI(409, "FIRMA_NO_APLICA", "La firma se captura con el folio en ejecución")
    if not imagen:
        raise ErrorAPI(422, "ARCHIVO_VACIO", "La firma está vacía")
    existente = (await db.execute(select(FolioEvidencia.id).where(FolioEvidencia.folio_id == folio.id, FolioEvidencia.tipo == TipoEvidenciaFolio.firma))).first()
    if existente is not None:
        raise ErrorAPI(409, "FIRMA_DUPLICADA", "El folio ya tiene la firma del operador")
    clave = f"folios/{folio.id}/firma-{uuid.uuid4().hex[:10]}.png"
    obtener_almacenamiento().guardar(clave, imagen, mime or "image/png")
    momento = timestamp_dispositivo or datetime.now(UTC)
    e = FolioEvidencia(folio_id=folio.id, tenant_id=folio.tenant_id, prestador_id=folio.prestador_id, tipo=TipoEvidenciaFolio.firma, archivo_key=clave,
                       geolat=geolat, geolng=geolng, timestamp_captura=momento, subido_por=actor.id)
    db.add(e)
    await db.flush()
    await folio_estados.comentar(db, folio, actor, "El operador firmó la orden de servicio",
                                 {"evidencia_id": str(e.id), "geolat": geolat, "geolng": geolng, "timestamp_dispositivo": momento.isoformat()}, evento="firma")
    await auditoria.registrar_actor(db, actor, "folio.firma", request, recurso_tipo="folio", recurso_id=folio.id, tenant_id=folio.tenant_id,
                                    prestador_id=folio.prestador_id, despues={"evidencia_id": e.id, "geolat": geolat, "geolng": geolng})
    # §6.8.6/§6.9.1: tras la firma el sistema genera la encuesta (se responde antes o después del cierre, dentro del plazo).
    await push_service.enviar_a_usuarios(db, [folio.capturado_por], f"Folio {folio.numero_folio}: gracias por firmar",
                                         "Responde la encuesta de satisfacción", {"folio_id": str(folio.id), "accion": "encuesta"})
    return e


async def encuesta_disponible(db: AsyncSession, folio: Folio) -> tuple[bool, str | None]:
    """Disponible tras la firma; después del cierre solo dentro de `plazo_encuesta_horas` del tenant."""
    firma = (await db.execute(select(FolioEvidencia.id).where(FolioEvidencia.folio_id == folio.id, FolioEvidencia.tipo == TipoEvidenciaFolio.firma))).first()
    if firma is None:
        return False, "La encuesta se habilita cuando el operador firma"
    if folio.estado == EstadoFolio.cancelado:
        return False, "El folio está cancelado"
    if folio.estado == EstadoFolio.cerrado and folio.fecha_cierre:
        politicas = await aprobacion_service.politicas_de(db, folio.tenant_id)
        if datetime.now(UTC) > folio.fecha_cierre + timedelta(hours=politicas.plazo_encuesta_horas):
            return False, f"El plazo de {politicas.plazo_encuesta_horas} h para la encuesta venció"
    return True, None


async def responder_encuesta(db: AsyncSession, actor: Actor, folio: Folio, nps: int, comentario: str, respuestas: dict, timestamp_dispositivo: datetime | None,
                             request: Request | None) -> FolioEncuesta:
    await _exigir_operador_de_la_un(db, actor, folio)
    disponible, motivo = await encuesta_disponible(db, folio)
    if not disponible:
        raise ErrorAPI(409, "ENCUESTA_NO_DISPONIBLE", motivo or "")
    if (await db.execute(select(FolioEncuesta.id).where(FolioEncuesta.folio_id == folio.id))).first():
        raise ErrorAPI(409, "ENCUESTA_DUPLICADA", "El folio ya tiene encuesta")
    if nps <= 6 and not comentario.strip() and not respuestas.get("comentario"):
        raise ErrorAPI(422, "COMENTARIO_REQUERIDO", "Con calificación baja cuéntanos qué pasó")
    respuesta_id = None
    equipo = await db.get(Equipo, folio.equipo_id)
    tipo = await db.get(TipoEquipo, equipo.tipo_equipo_id) if equipo else None
    resultado = await formularios.resolver(db, actor, "encuesta", folio.tenant_id, equipo.tipo_equipo_id if equipo else None,
                                           tipo.familia_id if tipo else None, None, folio.prestador_id, folio.tipo_folio.value)
    if resultado is not None and actor.rol.value in (resultado[0].rol_destino or []):
        formulario = resultado[0]
        valores = {"calificacion": nps, "comentario": comentario.strip() or respuestas.get("comentario", ""), **{k: v for k, v in respuestas.items() if k not in ("calificacion",)}}
        entrada = RespuestaEntrada(origen="encuesta", referencia_id=folio.id, contexto={"tenant_id": folio.tenant_id, "un_id": folio.un_id, "equipo_id": folio.equipo_id},
                                   respuestas=valores)
        r = await formularios.crear_respuesta(db, actor, formulario.id, entrada, request)
        await formularios.enviar(db, actor, r, request, momento=timestamp_dispositivo)
        respuesta_id = r.id
    enc = FolioEncuesta(folio_id=folio.id, tenant_id=folio.tenant_id, prestador_id=folio.prestador_id, operador_id=actor.id, nps_score=nps,
                        respuesta_id=respuesta_id, timestamp=timestamp_dispositivo or datetime.now(UTC))
    db.add(enc)
    await db.flush()
    await folio_estados.comentar(db, folio, actor, f"Encuesta respondida: NPS {nps}" + (f" — {comentario.strip()}" if comentario.strip() else ""),
                                 {"nps_score": nps, "respuesta_id": str(respuesta_id) if respuesta_id else None}, evento="encuesta")
    await auditoria.registrar_actor(db, actor, "folio.encuesta", request, recurso_tipo="folio", recurso_id=folio.id, tenant_id=folio.tenant_id,
                                    prestador_id=folio.prestador_id, despues={"nps_score": nps, "respuesta_id": respuesta_id})
    return enc


@folio_estados.suscribir
async def _al_cerrar(db: AsyncSession, folio: Folio, _anterior, nuevo: EstadoFolio, actor, contexto) -> None:
    """Al cerrar, el sistema deja constancia de que la encuesta queda pendiente (si aún no se respondió)."""
    if nuevo != EstadoFolio.cerrado:
        return
    if (await db.execute(select(FolioEncuesta.id).where(FolioEncuesta.folio_id == folio.id))).first():
        return
    politicas = await aprobacion_service.politicas_de(db, folio.tenant_id)
    await folio_estados.comentar(db, folio, ACTOR_SISTEMA, f"Encuesta de satisfacción pendiente (plazo {politicas.plazo_encuesta_horas} h)",
                                 {"plazo_horas": politicas.plazo_encuesta_horas}, evento="encuesta.pendiente")
