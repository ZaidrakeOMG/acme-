"""Módulo 1 — Cotizaciones (§7.7 M1): solicitada → en preparación → enviada → autorizada | rechazada → convertida (P08).
PDF literal de §7.7 y reenvío por correo a destinatarios externos sin cambiar el estado."""
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import config
from core.dependencias import Actor
from core.errors import ErrorAPI
from models.base import Rol
from models.catalogos import Equipo
from models.folios import Folio, ModuloDestino
from models.minutas import EstadoNotificacion, Hallazgo
from models.organizaciones import Prestador
from models.seguimiento import Cotizacion, CotizacionEnvioExterno, EstadoCotizacion, EstadoPresupuesto, HallazgoPresupuesto
from models.unidades import UnidadNegocio
from models.usuarios import Usuario
from services import auditoria, correo, notificaciones_service, pdf
from services.almacenamiento import obtener_almacenamiento
from services.folio_estados import ACTOR_SISTEMA, ActorFolio
from services.seguimiento import base

MODULO = ModuloDestino.cotizaciones
# §7.7 M1: estado → (destinos, roles responsables)
TRANSICIONES: dict[EstadoCotizacion, dict[EstadoCotizacion, set[Rol]]] = {
    EstadoCotizacion.solicitada: {EstadoCotizacion.en_preparacion: base.PRESTADOR, EstadoCotizacion.enviada: base.PRESTADOR},
    EstadoCotizacion.en_preparacion: {EstadoCotizacion.enviada: base.PRESTADOR},
    EstadoCotizacion.enviada: {EstadoCotizacion.autorizada: base.CLIENTE, EstadoCotizacion.rechazada: base.CLIENTE},
    EstadoCotizacion.autorizada: {EstadoCotizacion.convertida: {Rol.superadmin, Rol.despachador, Rol.admin_prestador}},
    EstadoCotizacion.rechazada: {},
    EstadoCotizacion.convertida: {},
}


def exigir(actor: ActorFolio, c: Cotizacion, destino: EstadoCotizacion) -> None:
    permitidos = TRANSICIONES[c.estado]
    if destino not in permitidos:
        raise ErrorAPI(409, "TRANSICION_NO_PERMITIDA", f"Una cotización {c.estado.value} no pasa a {destino.value}",
                       [{"destinos_posibles": [d.value for d in permitidos]}])
    base.exigir_rol(actor, permitidos[destino], f"Pasar a {destino.value}")


async def siguiente_numero(db: AsyncSession, prestador_id: UUID) -> str:
    n = (await db.execute(select(func.count()).select_from(Cotizacion).where(Cotizacion.prestador_id == prestador_id))).scalar() or 0
    return f"COT-{n + 1:05d}"


async def crear(db: AsyncSession, actor: ActorFolio, *, tenant_id: UUID, prestador_id: UUID, un_id: UUID, equipo_id: UUID | None, descripcion: str,
                hallazgo_id: UUID | None = None, folio_id: UUID | None = None, origen: str = "minuta", solicitado_por: UUID | None = None,
                request: Request | None = None) -> Cotizacion:
    c = Cotizacion(hallazgo_id=hallazgo_id, folio_id=folio_id, tenant_id=tenant_id, prestador_id=prestador_id, un_id=un_id, equipo_id=equipo_id,
                   numero=await siguiente_numero(db, prestador_id), descripcion=descripcion, origen=origen, solicitado_por=solicitado_por or getattr(actor, "id", None),
                   fecha_solicitud=datetime.now(UTC), estado_desde=datetime.now(UTC))
    db.add(c)
    await db.flush()
    await base.historial(db, MODULO, c, None, c.estado.value, actor, f"Solicitada ({origen})", {"hallazgo_id": str(hallazgo_id) if hallazgo_id else None, "folio_id": str(folio_id) if folio_id else None})
    await auditoria.registrar(db, "cotizaciones.solicitada", actor_rol=base.rol_de(actor), actor_id=getattr(actor, "id", None), tenant_id=tenant_id, prestador_id=prestador_id,
                              recurso_tipo="cotizacion", recurso_id=c.id, despues={"numero": c.numero, "origen": origen})
    # §7.4 / §6.10.5: el prestador (Mesa de control, Despachador y Admin prestador) recibe la solicitud simultáneamente.
    un = await db.get(UnidadNegocio, un_id)
    destinatarios = await notificaciones_service.destinatarios_por_rol(db, [Rol.mesa_control, Rol.despachador, Rol.admin_prestador], prestador_id=prestador_id)
    await notificaciones_service.notificar(db, "cotizacion.solicitada", destinatarios, {"cotizacion_id": str(c.id), "numero": c.numero},
                                           asunto=f"Cotización {c.numero} solicitada por el cliente ({un.codigo if un else ''})",
                                           cuerpo=descripcion[:300], url=f"/seguimiento/cotizaciones/{c.id}", tenant_id=tenant_id, prestador_id=prestador_id)
    return c


async def preparar(db: AsyncSession, actor: Actor, c: Cotizacion, *, descripcion: str | None, monto: Decimal | None, detalle: dict[str, Any] | None,
                   request: Request | None) -> Cotizacion:
    base.exigir_rol(actor, base.PRESTADOR, "Preparar la cotización")
    if c.estado not in (EstadoCotizacion.solicitada, EstadoCotizacion.en_preparacion):
        raise ErrorAPI(409, "TRANSICION_NO_PERMITIDA", f"Una cotización {c.estado.value} ya no se edita")
    antes = auditoria.instantanea(c)
    if descripcion is not None:
        c.descripcion = descripcion
    if monto is not None:
        c.monto = monto
    if detalle is not None:
        c.detalle_json = detalle
    c.preparado_por = actor.id
    if c.estado == EstadoCotizacion.solicitada:
        exigir(actor, c, EstadoCotizacion.en_preparacion)
        anterior = base.transicionar(c, EstadoCotizacion.en_preparacion)
        c.fecha_preparacion = datetime.now(UTC)
        await base.historial(db, MODULO, c, anterior, c.estado.value, actor, "En preparación")
    c.pdf_key = c.hash_pdf = None  # el PDF se regenera con los datos nuevos
    await db.flush()
    await auditoria.registrar_actor(db, actor, "cotizaciones.preparada", request, tenant_id=c.tenant_id, prestador_id=c.prestador_id, recurso_tipo="cotizacion",
                                    recurso_id=c.id, antes=antes, despues=auditoria.instantanea(c))
    return c


async def enviar_cliente(db: AsyncSession, actor: Actor, c: Cotizacion, request: Request | None) -> Cotizacion:
    exigir(actor, c, EstadoCotizacion.enviada)
    if not c.descripcion.strip() or c.monto is None or c.monto <= 0:
        raise ErrorAPI(422, "COTIZACION_INCOMPLETA", "Para enviar la cotización indica descripción y monto")
    anterior = base.transicionar(c, EstadoCotizacion.enviada)
    c.fecha_envio = datetime.now(UTC)
    if c.preparado_por is None:
        c.preparado_por = actor.id
    await db.flush()
    await generar_pdf(db, c)
    await base.historial(db, MODULO, c, anterior, c.estado.value, actor, "Enviada al cliente", {"monto": str(c.monto)})
    await auditoria.registrar_actor(db, actor, "cotizaciones.enviada", request, tenant_id=c.tenant_id, prestador_id=c.prestador_id, recurso_tipo="cotizacion",
                                    recurso_id=c.id, despues={"numero": c.numero, "monto": str(c.monto)})
    un = await db.get(UnidadNegocio, c.un_id)
    destinatarios = await notificaciones_service.destinatarios_por_rol(db, [Rol.admin_un, Rol.admin_empresa], tenant_id=c.tenant_id, un_id=c.un_id)
    await notificaciones_service.notificar(db, "cotizacion.enviada", destinatarios, {"cotizacion_id": str(c.id), "numero": c.numero, "monto": str(c.monto),
                                                                                       "html_valores": await _valores_correo(db, c, un, "")},
                                           asunto=f"Cotización {c.numero} por ${c.monto:,.2f} {c.moneda} — {un.codigo if un else ''}", cuerpo=c.descripcion[:300],
                                           url=f"/seguimiento/cotizaciones/{c.id}", tenant_id=c.tenant_id, prestador_id=c.prestador_id, plantilla="cotizacion",
                                           adjuntos=[{"nombre": f"{c.numero}.pdf", "clave": c.pdf_key, "mime": "application/pdf"}])
    return c


async def responder(db: AsyncSession, actor: Actor, c: Cotizacion, autorizar: bool, notas: str, pasar_a_presupuesto: bool | None, request: Request | None) -> Cotizacion:
    destino = EstadoCotizacion.autorizada if autorizar else EstadoCotizacion.rechazada
    exigir(actor, c, destino)
    if actor.dominio.value == "tenant" and c.tenant_id != actor.tenant_id:
        raise ErrorAPI(404, "NO_ENCONTRADO", "Cotización no encontrada")
    anterior = base.transicionar(c, destino)
    c.fecha_respuesta, c.respondido_por, c.notas_respuesta = datetime.now(UTC), actor.id, notas or ""
    if pasar_a_presupuesto is not None:
        c.pasar_a_presupuesto_si_rechaza = pasar_a_presupuesto
    await db.flush()
    await base.historial(db, MODULO, c, anterior, c.estado.value, actor, notas or ("Autorizada" if autorizar else "Rechazada"))
    await auditoria.registrar_actor(db, actor, f"cotizaciones.{destino.value}", request, tenant_id=c.tenant_id, prestador_id=c.prestador_id, recurso_tipo="cotizacion",
                                    recurso_id=c.id, despues={"numero": c.numero, "notas": notas})
    registro_presupuesto = None
    if not autorizar and c.pasar_a_presupuesto_si_rechaza:
        from services.seguimiento import presupuesto

        registro_presupuesto = await presupuesto.crear(db, actor, tenant_id=c.tenant_id, prestador_id=c.prestador_id, un_id=c.un_id, equipo_id=c.equipo_id,
                                                       descripcion=c.descripcion, hallazgo_id=c.hallazgo_id, folio_id=c.folio_id, origen="cotizacion_rechazada",
                                                       monto_estimado=c.monto)
    destinatarios = await notificaciones_service.destinatarios_por_rol(db, [Rol.mesa_control, Rol.despachador, Rol.admin_prestador], prestador_id=c.prestador_id)
    await notificaciones_service.notificar(db, "cotizacion.respondida", destinatarios, {"cotizacion_id": str(c.id), "numero": c.numero, "estado": c.estado.value},
                                           asunto=f"Cotización {c.numero} {'autorizada' if autorizar else 'rechazada'} por el cliente", cuerpo=notas or "",
                                           url=f"/seguimiento/cotizaciones/{c.id}", tenant_id=c.tenant_id, prestador_id=c.prestador_id)
    if registro_presupuesto is not None:
        c.detalle_json = {**c.detalle_json, "hallazgo_presupuesto_id": str(registro_presupuesto.id)}
        await db.flush()
    return c


async def convertir_en_trabajo_especial(db: AsyncSession, actor: Actor, c: Cotizacion) -> None:
    """Gancho para P08: la conversión crea el Trabajo Especial con todo el contexto de la cotización."""
    exigir(actor, c, EstadoCotizacion.convertida)
    raise ErrorAPI(501, "DISPONIBLE_EN_P08", "La conversión en Trabajo Especial se construye en P08")


async def cambiar_estado(db: AsyncSession, actor: Actor, c: Cotizacion, nuevo: EstadoCotizacion, notas: str, request: Request | None, **campos: Any) -> Cotizacion:
    """Entrada genérica (Kanban): traduce el destino a la operación del módulo."""
    if nuevo == EstadoCotizacion.en_preparacion:
        return await preparar(db, actor, c, descripcion=campos.get("descripcion"), monto=campos.get("monto"), detalle=campos.get("detalle"), request=request)
    if nuevo == EstadoCotizacion.enviada:
        if campos.get("monto") is not None or campos.get("descripcion") is not None:
            await preparar(db, actor, c, descripcion=campos.get("descripcion"), monto=campos.get("monto"), detalle=campos.get("detalle"), request=request)
        return await enviar_cliente(db, actor, c, request)
    if nuevo in (EstadoCotizacion.autorizada, EstadoCotizacion.rechazada):
        return await responder(db, actor, c, nuevo == EstadoCotizacion.autorizada, notas, campos.get("pasar_a_presupuesto"), request)
    if nuevo == EstadoCotizacion.convertida:
        await convertir_en_trabajo_especial(db, actor, c)
    raise ErrorAPI(409, "TRANSICION_NO_PERMITIDA", f"Destino {nuevo.value} no válido")


# -------------------------------------------------------------------- PDF

async def _valores_correo(db: AsyncSession, c: Cotizacion, un: UnidadNegocio | None, comentario: str) -> dict[str, Any]:
    equipo = await db.get(Equipo, c.equipo_id) if c.equipo_id else None
    prestador = await db.get(Prestador, c.prestador_id)
    return {"saludo": "Estimado cliente,", "numero": c.numero, "monto": f"${c.monto:,.2f} {c.moneda}" if c.monto is not None else "por definir",
            "un": f"{un.codigo} · {un.nombre}" if un else "", "descripcion": c.descripcion, "equipo": f"{equipo.codigo} · {equipo.nombre}" if equipo else "—",
            "prestador": prestador.razon_social if prestador else "", "hash_pdf": c.hash_pdf or "",
            "comentario_html": f"<p><em>{correo.html.escape(comentario)}</em></p>" if comentario else ""}


async def html_cotizacion(db: AsyncSession, c: Cotizacion) -> str:
    """Datos literales de §7.7: descripción del trabajo, equipos, monto, UN, prestador y contexto del hallazgo original."""
    un = await db.get(UnidadNegocio, c.un_id)
    equipo = await db.get(Equipo, c.equipo_id) if c.equipo_id else None
    prestador = await db.get(Prestador, c.prestador_id)
    hallazgo = await db.get(Hallazgo, c.hallazgo_id) if c.hallazgo_id else None
    folio = await db.get(Folio, c.folio_id) if c.folio_id else None
    e = correo.html.escape
    partidas = c.detalle_json.get("partidas") or []
    filas = "".join(f"<tr><td>{e(str(p.get('descripcion', '')))}</td><td>{e(str(p.get('cantidad', '')))}</td><td>{e(str(p.get('importe', '')))}</td></tr>" for p in partidas)
    return f"""<html><head><meta charset="utf-8"><style>body{{font-family:Arial;font-size:12px;color:#1f2937}} h1{{color:{prestador.color_primario if prestador else '#1C3D8F'}}}
    table{{border-collapse:collapse;width:100%}} td,th{{border-bottom:1px solid #ddd;padding:6px;text-align:left}}</style></head><body>
    <h1>Cotización {e(c.numero)}</h1>
    <p>{e(prestador.razon_social if prestador else '')} · RFC {e(prestador.rfc if prestador else '')} · {c.fecha_envio.strftime('%d/%m/%Y') if c.fecha_envio else datetime.now(UTC).strftime('%d/%m/%Y')}</p>
    <h2>Unidad de negocio</h2><p>{e(un.codigo if un else '')} · {e(un.nombre if un else '')} · {e(un.direccion if un else '')}</p>
    <h2>Equipo involucrado</h2><p>{e(f"{equipo.codigo} · {equipo.nombre}" if equipo else 'Sin equipo específico')}</p>
    <h2>Descripción del trabajo</h2><p>{e(c.descripcion)}</p>
    {f'<h2>Partidas</h2><table><tr><th>Concepto</th><th>Cantidad</th><th>Importe</th></tr>{filas}</table>' if filas else ''}
    <h2>Monto</h2><p><strong>${c.monto:,.2f} {e(c.moneda)}</strong></p>
    <h2>Contexto del hallazgo original</h2><p>{e(hallazgo.descripcion if hallazgo else (folio.descripcion if folio else 'Solicitud directa del cliente'))}
    {f'· urgencia {e(hallazgo.nivel_urgencia.value)}' if hallazgo else ''}{f' · folio {e(folio.numero_folio)}' if folio else ''}</p>
    <p>Estado: {e(c.estado.value)}. Generado por ACMA.</p></body></html>"""


async def generar_pdf(db: AsyncSession, c: Cotizacion) -> bytes:
    datos = pdf.html_a_pdf(await html_cotizacion(db, c))
    c.pdf_key = f"cotizaciones/{c.tenant_id}/{c.numero}.pdf"
    c.hash_pdf = pdf.sha256(datos)
    obtener_almacenamiento().guardar(c.pdf_key, datos, "application/pdf")
    await db.flush()
    return datos


async def pdf_de(db: AsyncSession, c: Cotizacion) -> bytes:
    if c.pdf_key:
        try:
            return obtener_almacenamiento().leer(c.pdf_key)
        except Exception:  # noqa: BLE001 — se regenera si el objeto no está
            pass
    return await generar_pdf(db, c)


async def enviar_externo(db: AsyncSession, actor: Actor, c: Cotizacion, destinatarios: list[str], comentario: str, request: Request | None) -> CotizacionEnvioExterno:
    """§7.7: el Admin UN (o Admin empresa) envía el PDF a terceros (p. ej. compras) sin cambiar el estado."""
    base.exigir_rol(actor, base.CLIENTE | base.PRESTADOR, "Enviar la cotización por correo")
    if c.estado not in (EstadoCotizacion.enviada, EstadoCotizacion.autorizada, EstadoCotizacion.rechazada, EstadoCotizacion.convertida):
        raise ErrorAPI(409, "COTIZACION_NO_ENVIADA", "La cotización aún no se ha enviado al cliente")
    if not destinatarios:
        raise ErrorAPI(422, "DESTINATARIOS_REQUERIDOS", "Indica al menos un correo")
    un = await db.get(UnidadNegocio, c.un_id)
    estado_antes = c.estado
    datos = await pdf_de(db, c)
    asunto = f"Cotización {c.numero} — ${c.monto:,.2f} {c.moneda} — {un.codigo if un else ''} {un.nombre if un else ''}".strip()
    prestador = await db.get(Prestador, c.prestador_id)
    html = correo.plantilla("cotizacion", titulo=asunto, color_primario=prestador.color_primario if prestador else "#1C3D8F",
                            color_acento=prestador.color_acento if prestador else "#A2C62B", **await _valores_correo(db, c, un, comentario))
    estado, detalle = await correo.enviar(correo.Correo(destinatarios=destinatarios, asunto=asunto, html=html,
                                                        adjuntos=[correo.Adjunto(nombre=f"{c.numero}.pdf", contenido=datos)]))
    envio = CotizacionEnvioExterno(cotizacion_id=c.id, tenant_id=c.tenant_id, prestador_id=c.prestador_id, destinatarios_json=destinatarios, comentario=comentario,
                                   asunto=asunto, enviado_por=actor.id, timestamp=datetime.now(UTC), estado_entrega=EstadoNotificacion(estado))
    db.add(envio)
    await db.flush()
    await base.historial(db, MODULO, c, c.estado.value, c.estado.value, actor, f"PDF enviado a {', '.join(destinatarios)}", {"envio_externo_id": str(envio.id), "comentario": comentario})
    await auditoria.registrar_actor(db, actor, "cotizaciones.envio_externo", request, tenant_id=c.tenant_id, prestador_id=c.prestador_id, recurso_tipo="cotizacion",
                                    recurso_id=c.id, despues={"destinatarios": destinatarios, "estado_entrega": estado, "detalle": detalle})
    assert c.estado == estado_antes
    return envio


async def envios_externos(db: AsyncSession, c: Cotizacion) -> list[CotizacionEnvioExterno]:
    return list((await db.execute(select(CotizacionEnvioExterno).where(CotizacionEnvioExterno.cotizacion_id == c.id).order_by(CotizacionEnvioExterno.timestamp))).scalars())


async def listar(db: AsyncSession, actor: Actor, filtros: dict[str, Any]) -> list[Cotizacion]:
    base.exigir_rol(actor, base.CONSULTAN, "Consultar cotizaciones")
    consulta = await base.alcance(db, actor, select(Cotizacion).order_by(Cotizacion.fecha_solicitud.desc()), Cotizacion)
    consulta = _filtrar(consulta, Cotizacion, filtros)
    return list((await db.execute(consulta)).scalars())


def _filtrar(consulta, modelo, filtros: dict[str, Any]):
    if filtros.get("tenant_id"):
        consulta = consulta.where(modelo.tenant_id == filtros["tenant_id"])
    if filtros.get("un_id"):
        consulta = consulta.where(modelo.un_id == filtros["un_id"])
    if filtros.get("estado"):
        consulta = consulta.where(modelo.estado == filtros["estado"])
    if filtros.get("desde"):
        consulta = consulta.where(modelo.created_at >= filtros["desde"])
    if filtros.get("hasta"):
        consulta = consulta.where(modelo.created_at <= filtros["hasta"])
    return consulta


async def nombres_usuarios(db: AsyncSession, ids: set[UUID | None]) -> dict[UUID, str]:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    return {u.id: u.nombre for u in (await db.execute(select(Usuario).where(Usuario.id.in_(ids)))).scalars()}


def url_publica(ruta: str) -> str:
    return f"{config.app_url_publica.rstrip('/')}{ruta}"
