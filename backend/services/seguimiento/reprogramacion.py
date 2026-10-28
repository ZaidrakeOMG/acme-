"""Módulo 4 — Reprogramación (§7.7 M4): tercero con fecha acordada vigilada por ACMA, contador de 3 fechas vencidas con escalado
al Admin empresa, trabajo coordinado con variantes A (tercero habilita → técnico ejecuta) y B (técnico ejecuta → tercero certifica)."""
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.dependencias import Actor
from core.errors import ErrorAPI
from models.base import Rol
from models.folios import ModuloDestino
from models.seguimiento import EstadoReprogramacion as E, Reprogramacion, VarianteCoordinado
from services import alertas_service, auditoria, notificaciones_service
from services.folio_estados import ACTOR_SISTEMA, ActorFolio
from services.seguimiento import base

MODULO = ModuloDestino.reprogramacion
CLIENTE = {Rol.superadmin, Rol.admin_un, Rol.admin_empresa}
CON_DESPACHADOR = CLIENTE | {Rol.despachador}
TRANSICIONES: dict[E, dict[E, set[Rol]]] = {
    E.pendiente_fecha: {E.fecha_asignada: CON_DESPACHADOR, E.cancelado: CLIENTE},
    E.fecha_asignada: {E.fecha_asignada: CON_DESPACHADOR, E.tercero_confirmado: CON_DESPACHADOR, E.en_ejecucion: CON_DESPACHADOR, E.cancelado: CLIENTE},
    E.tercero_confirmado: {E.fecha_asignada: CON_DESPACHADOR, E.tercero_confirmado: CON_DESPACHADOR, E.en_ejecucion: CON_DESPACHADOR, E.cancelado: CLIENTE},
    E.en_ejecucion: {E.resuelto: CON_DESPACHADOR, E.cancelado: CLIENTE},
    E.resuelto: {},
    E.cancelado: {},
}
FINALES = {E.resuelto, E.cancelado}
MAX_FECHAS_VENCIDAS = 3


async def crear(db: AsyncSession, actor: ActorFolio, *, tenant_id: UUID, prestador_id: UUID, un_id: UUID, equipo_id: UUID | None, descripcion: str,
                hallazgo_id: UUID | None = None, folio_id: UUID | None = None, origen: str = "minuta", motivo: str = "", fecha_tentativa: date | None = None,
                trabajo_coordinado: bool = False, variante: VarianteCoordinado | None = None, proveedor: str | None = None) -> Reprogramacion:
    if trabajo_coordinado and variante is None:
        raise ErrorAPI(422, "VARIANTE_REQUERIDA", "El trabajo coordinado requiere variante A o B")
    ahora = datetime.now(UTC)
    r = Reprogramacion(hallazgo_id=hallazgo_id, folio_id=folio_id, tenant_id=tenant_id, prestador_id=prestador_id, un_id=un_id, equipo_id=equipo_id, descripcion=descripcion,
                       origen=origen, motivo=motivo or "", fecha_tentativa=fecha_tentativa, trabajo_coordinado=trabajo_coordinado, variante=variante, estado_desde=ahora,
                       proveedor_tercero=proveedor)
    if fecha_tentativa:
        # §6.10.5 opción 2: la fecha tentativa crea el recordatorio; el registro ya nace con fecha asignada.
        r.estado, r.fecha_acordada = E.fecha_asignada, fecha_tentativa
    db.add(r)
    await db.flush()
    await base.historial(db, MODULO, r, None, r.estado.value, actor, f"Creada ({origen})" + (f" · fecha tentativa {fecha_tentativa.isoformat()}" if fecha_tentativa else ""),
                         {"trabajo_coordinado": trabajo_coordinado, "variante": variante.value if variante else None})
    await auditoria.registrar(db, "reprogramacion.creada", actor_rol=base.rol_de(actor), actor_id=getattr(actor, "id", None), tenant_id=tenant_id, prestador_id=prestador_id,
                              recurso_tipo="reprogramacion", recurso_id=r.id, despues={"origen": origen, "fecha_tentativa": fecha_tentativa})
    return r


async def cambiar_estado(db: AsyncSession, actor: ActorFolio, r: Reprogramacion, nuevo: E, notas: str, request: Request | None, *, proveedor: str | None = None,
                         fecha_acordada: date | None = None, referencia_tercero: str | None = None, **_: Any) -> Reprogramacion:
    permitidos = TRANSICIONES[r.estado]
    if nuevo not in permitidos:
        raise ErrorAPI(409, "TRANSICION_NO_PERMITIDA", f"Una reprogramación {r.estado.value} no pasa a {nuevo.value}", [{"destinos_posibles": [d.value for d in permitidos]}])
    base.exigir_rol(actor, permitidos[nuevo], f"Pasar a {nuevo.value}")
    datos: dict[str, Any] = {}
    if nuevo in (E.fecha_asignada, E.tercero_confirmado):
        proveedor = (proveedor or r.proveedor_tercero or "").strip()
        fecha = fecha_acordada or (r.fecha_acordada if nuevo == E.tercero_confirmado else None)
        if not proveedor or fecha is None:
            raise ErrorAPI(422, "FECHA_REQUERIDA", "Indica el nombre del tercero y la fecha acordada (la referencia es opcional)")
        r.proveedor_tercero, r.fecha_acordada = proveedor, fecha
        if referencia_tercero is not None:
            r.referencia_tercero = referencia_tercero.strip() or None
        datos = {"proveedor": proveedor, "fecha_acordada": fecha.isoformat(), "referencia_tercero": r.referencia_tercero}
    if nuevo == E.en_ejecucion and r.trabajo_coordinado and r.variante == VarianteCoordinado.A and not r.tercero_completo:
        raise ErrorAPI(409, "TERCERO_PENDIENTE", "Variante A: confirma primero que el tercero completó su parte (habilitación) antes de que entre el técnico")
    if nuevo in FINALES:
        notas = base.exigir_justificacion(notas, "Resolver" if nuevo == E.resuelto else "Cancelar")
        r.justificacion_cierre, r.cerrado_por, r.fecha_resolucion = notas, getattr(actor, "id", None), datetime.now(UTC)
    anterior = base.transicionar(r, nuevo)
    await db.flush()
    await base.historial(db, MODULO, r, anterior, nuevo.value, actor, notas, datos)
    await auditoria.registrar(db, f"reprogramacion.{nuevo.value}", actor_rol=base.rol_de(actor), actor_id=getattr(actor, "id", None), tenant_id=r.tenant_id,
                              prestador_id=r.prestador_id, recurso_tipo="reprogramacion", recurso_id=r.id, despues={"notas": notas, **datos})
    destinatarios = await notificaciones_service.destinatarios_por_rol(db, [Rol.despachador, Rol.admin_prestador], prestador_id=r.prestador_id)
    destinatarios += await notificaciones_service.destinatarios_por_rol(db, [Rol.admin_un], tenant_id=r.tenant_id, un_id=r.un_id)
    await notificaciones_service.notificar(db, "seguimiento.cambio_estado", [d for d in destinatarios if d != getattr(actor, "id", None)],
                                           {"modulo": MODULO.value, "registro_id": str(r.id), "estado": nuevo.value}, asunto=f"Reprogramación: {nuevo.value}",
                                           cuerpo=r.descripcion[:200], url=f"/seguimiento/reprogramacion/{r.id}", tenant_id=r.tenant_id, prestador_id=r.prestador_id, canales=["app"])
    return r


async def confirmar_tercero(db: AsyncSession, actor: Actor, r: Reprogramacion, notas: str, request: Request | None):
    """Variante A: el Admin UN o el Despachador confirman que el tercero completó la habilitación; se crea el folio correctivo
    para el técnico del prestador. Variante B no requiere confirmación (el tercero certifica en el acto)."""
    base.exigir_rol(actor, {Rol.superadmin, Rol.admin_un, Rol.admin_empresa, Rol.despachador}, "Confirmar el paso del tercero")
    if not r.trabajo_coordinado or r.variante != VarianteCoordinado.A:
        raise ErrorAPI(409, "NO_APLICA", "Solo el trabajo coordinado variante A requiere confirmar el paso del tercero")
    if r.estado in FINALES or r.tercero_completo:
        raise ErrorAPI(409, "TERCERO_YA_CONFIRMADO" if r.tercero_completo else "ESTADO_FINAL", "Ya está confirmado o el registro está cerrado")
    from services.seguimiento import entradas

    folio = await entradas.folio_directo(db, actor, tenant_id=r.tenant_id, prestador_id=r.prestador_id, un_id=r.un_id, equipo_id=r.equipo_id,
                                         descripcion=f"Trabajo coordinado (variante A) tras habilitación de {r.proveedor_tercero or 'tercero'}: {r.descripcion}",
                                         contexto={"reprogramacion_id": str(r.id), "origen": "trabajo_coordinado_A"}, folio_origen_id=r.folio_id, request=request)
    r.tercero_completo, r.folio_coordinado_id = True, folio.id
    if r.estado != E.en_ejecucion:
        anterior = base.transicionar(r, E.en_ejecucion)
        await base.historial(db, MODULO, r, anterior, r.estado.value, actor, notas or "Tercero completó su parte; técnico del prestador programado", {"folio_id": str(folio.id)})
    else:
        await base.historial(db, MODULO, r, r.estado.value, r.estado.value, actor, notas or "Tercero completó su parte", {"folio_id": str(folio.id)})
    await db.flush()
    return r, folio


async def registrar_fecha_vencida(db: AsyncSession, r: Reprogramacion, hoy: date) -> bool:
    """Lo llama el evaluador de alertas: suma una fecha vencida (entre fecha_asignada y tercero_confirmado) y escala al llegar a 3."""
    if r.estado not in (E.fecha_asignada, E.tercero_confirmado) or r.fecha_acordada is None or r.fecha_acordada >= hoy:
        return False
    r.fechas_vencidas_count += 1
    vencida = r.fecha_acordada
    r.fecha_acordada = None  # se exige nueva fecha; el estado se conserva
    await base.historial(db, MODULO, r, r.estado.value, r.estado.value, ACTOR_SISTEMA, f"Fecha acordada {vencida.isoformat()} vencida ({r.fechas_vencidas_count} de {MAX_FECHAS_VENCIDAS})",
                         {"fecha_vencida": vencida.isoformat(), "fechas_vencidas_count": r.fechas_vencidas_count})
    await alertas_service.disparar(db, "REPROGRAMACION_FECHA_VENCIDA", tenant_id=r.tenant_id, prestador_id=r.prestador_id, entidad_tipo="reprogramacion", entidad_id=r.id,
                                   datos={"fecha_vencida": vencida.isoformat(), "fechas_vencidas_count": r.fechas_vencidas_count})
    if r.fechas_vencidas_count >= MAX_FECHAS_VENCIDAS and not r.escalada_empresa:
        r.escalada_empresa = True
        await alertas_service.disparar(db, "REPROGRAMACION_ESCALADA_EMPRESA", tenant_id=r.tenant_id, prestador_id=r.prestador_id, entidad_tipo="reprogramacion",
                                       entidad_id=r.id, datos={"fechas_vencidas_count": r.fechas_vencidas_count})
        destinatarios = await notificaciones_service.destinatarios_por_rol(db, [Rol.admin_empresa], tenant_id=r.tenant_id)
        await notificaciones_service.notificar(db, "seguimiento.escalada", destinatarios, {"registro_id": str(r.id)}, asunto="Reprogramación escalada: 3 fechas vencidas",
                                               cuerpo=f"{r.descripcion[:200]} — asigna una nueva fecha o cancela.", url=f"/seguimiento/reprogramacion/{r.id}",
                                               tenant_id=r.tenant_id, prestador_id=r.prestador_id)
    await db.flush()
    return True


async def listar(db: AsyncSession, actor: Actor, filtros: dict[str, Any]) -> list[Reprogramacion]:
    from services.seguimiento.cotizaciones import _filtrar

    base.exigir_rol(actor, base.CONSULTAN, "Consultar reprogramaciones")
    consulta = await base.alcance(db, actor, select(Reprogramacion).order_by(Reprogramacion.created_at.desc()), Reprogramacion)
    return list((await db.execute(_filtrar(consulta, Reprogramacion, filtros))).scalars())
