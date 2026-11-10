"""Mensajería por WhatsApp y SMS (§6.1, §7.5, §6.9.5). F2-02.

`notificar()` sigue siendo el único punto de entrada de las notificaciones; este servicio responde dos preguntas:

1. **¿Puede salir por este canal?** `evaluar()` aplica, en este orden: preferencia del usuario por evento (la
   resuelve `notificar()`) → canal activo en `mensajeria_configuracion` del tenant o del prestador → consentimiento
   y teléfono verificado → horario de silencio (salvo eventos críticos) → tope mensual. Cuando no puede, el motivo
   queda escrito en la notificación y el aviso **cae al siguiente canal** (push, correo o bandeja).
2. **¿Cómo sale?** `enviar_notificacion()` arma el mensaje con la plantilla del evento, lo manda por el proveedor
   del canal (stub, Meta Cloud API o Twilio), calcula el costo estimado y deja la bitácora en `mensajeria_envios`.

Reglas de privacidad que el código impone, no solo documenta:
* el número vive cifrado y en bitácoras solo aparece su hash o su máscara (`services/mensajeria/telefonos.py`);
* en el cuerpo del mensaje no va nada sensible: el catálogo de plantillas solo usa folio, sucursal, estado y enlace;
* ninguna acción crítica se ejecuta desde un mensaje: los botones de aprobación contestan con el enlace a ACMA.
"""
import logging
import secrets
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import config
from core.dependencias import Actor, validar_prestador
from core.errors import ErrorAPI, no_encontrado, prohibido
from core.security import crear_jwt, decodificar_jwt
from models.base import EstadoRegistro, Rol
from models.mensajeria import (
    CanalMensajeria, EstadoAprobacionPlantilla, EstadoEnvioMensajeria, MensajeriaConfiguracion, MensajeriaEnvio,
    MensajeriaPlantilla, MensajeriaRespuesta, ProveedorMensajeria,
)
from models.minutas import CanalNotificacion, EstadoNotificacion, Notificacion
from models.usuarios import Usuario
from services import alertas_service, auditoria
from services.mensajeria import base as texto
from services.mensajeria import plantillas as catalogo
from services.mensajeria import proveedores, telefonos

log = logging.getLogger("acma.mensajeria")

CANALES = ("whatsapp", "sms")
# A dónde cae un aviso que no pudo salir por WhatsApp o SMS, en este orden (§6.1).
RESPALDO = ("push", "email", "app")
# Eventos que salen aunque sea de madrugada (§6.1: el silencio no aplica a lo crítico).
EVENTOS_CRITICOS = {"aprobacion.pendiente", "aprobacion.bloqueada", "trabajo_especial.urgencia",
                    "telefono.verificacion"}
ALERTAS_CRITICAS = {"SLA_INCUMPLIDO", "SLA_RESPUESTA_EN_RIESGO", "SLA_RESOLUCION_EN_RIESGO",
                    "SLA_INCUMPLIDO_ESCALADO_DIRECCION", "TECNICO_SIN_SENAL"}
GESTIONAN = (Rol.superadmin, Rol.admin_prestador, Rol.admin_empresa)
TIPO_PDF = "mensajeria_pdf"
MINUTOS_PDF = 60  # enlace firmado de corta duración para el PDF de la minuta (§7.5)
PALABRA_BAJA, PALABRA_ALTA = "BAJA", "ALTA"


# ----------------------------------------------------------------- configuración

async def configuracion(db: AsyncSession, prestador_id: UUID | None, tenant_id: UUID | None,
                        crear: bool = False) -> MensajeriaConfiguracion | None:
    """La fila del tenant si existe, y si no la del prestador (§6.1: el prestador pone el marco, el tenant afina)."""
    if prestador_id is None:
        return None
    filas = list((await db.execute(select(MensajeriaConfiguracion).where(
        MensajeriaConfiguracion.prestador_id == prestador_id))).scalars())
    del_tenant = next((f for f in filas if tenant_id and f.tenant_id == tenant_id), None)
    del_prestador = next((f for f in filas if f.tenant_id is None), None)
    cfg = del_tenant or del_prestador
    if cfg is None and crear:
        cfg = MensajeriaConfiguracion(prestador_id=prestador_id, tenant_id=None,
                                      horario_silencio_json={"inicio": "22:00", "fin": "07:00",
                                                             "zona": "America/Mexico_City"})
        db.add(cfg)
        await db.flush()
    return cfg


async def guardar_configuracion(db: AsyncSession, actor: Actor, prestador_id: UUID, tenant_id: UUID | None,
                                cambios: dict[str, Any], request: Request | None = None) -> MensajeriaConfiguracion:
    if actor.rol not in GESTIONAN:
        raise prohibido("Solo el Superadmin, el Admin prestador y el Admin empresa configuran la mensajería")
    if actor.rol == Rol.admin_prestador:
        validar_prestador(actor, prestador_id)
    if actor.rol == Rol.admin_empresa:
        # El Admin empresa solo configura lo de su propio tenant (regla 2: también en el servicio).
        if tenant_id != actor.tenant_id:
            raise prohibido("Solo puedes configurar la mensajería de tu empresa")
    fila = (await db.execute(select(MensajeriaConfiguracion).where(
        MensajeriaConfiguracion.prestador_id == prestador_id,
        MensajeriaConfiguracion.tenant_id == tenant_id if tenant_id
        else MensajeriaConfiguracion.tenant_id.is_(None)))).scalar_one_or_none()
    antes = {c: getattr(fila, c) for c in ("whatsapp_activo", "sms_activo", "tope_mensual_mensajes")} if fila else None
    if fila is None:
        fila = MensajeriaConfiguracion(prestador_id=prestador_id, tenant_id=tenant_id)
        db.add(fila)
    for campo, valor in cambios.items():
        if valor is not None and hasattr(fila, campo):
            setattr(fila, campo, valor)
    if not isinstance(fila.horario_silencio_json, dict) or not fila.horario_silencio_json:
        fila.horario_silencio_json = {"inicio": "22:00", "fin": "07:00", "zona": "America/Mexico_City"}
    await db.flush()
    await auditoria.registrar_actor(db, actor, "mensajeria.configuracion", request,
                                    recurso_tipo="mensajeria_configuracion", recurso_id=fila.id, antes=antes,
                                    despues={"whatsapp_activo": fila.whatsapp_activo, "sms_activo": fila.sms_activo,
                                             "tope": fila.tope_mensual_mensajes})
    return fila


def en_silencio(cfg: MensajeriaConfiguracion | None, ahora: datetime | None = None) -> bool:
    """Horario de silencio del tenant: fuera de él no se manda nada que no sea crítico (§6.1)."""
    if cfg is None:
        return False
    datos = cfg.horario_silencio_json or {}
    inicio, fin = str(datos.get("inicio") or ""), str(datos.get("fin") or "")
    if not inicio or not fin:
        return False
    try:
        from zoneinfo import ZoneInfo

        zona = ZoneInfo(str(datos.get("zona") or "America/Mexico_City"))
    except Exception:  # noqa: BLE001 — sin base de datos de zonas se evalúa en UTC
        zona = UTC
    momento = (ahora or datetime.now(UTC)).astimezone(zona).time()
    try:
        h_inicio = time.fromisoformat(inicio)
        h_fin = time.fromisoformat(fin)
    except ValueError:
        return False
    if h_inicio <= h_fin:
        return h_inicio <= momento < h_fin
    return momento >= h_inicio or momento < h_fin  # cruza la medianoche (22:00 → 07:00)


def _eventos_permitidos(cfg: MensajeriaConfiguracion | None, canal: str) -> list[str]:
    if cfg is None:
        return []
    return list(cfg.eventos_whatsapp_json if canal == "whatsapp" else cfg.eventos_sms_json)


def es_critico(evento: str, datos: dict[str, Any] | None = None, clave_plantilla: str = "") -> bool:
    datos = datos or {}
    if evento in EVENTOS_CRITICOS or clave_plantilla in catalogo.CLAVES_CRITICAS:
        return True
    alerta = str(datos.get("alerta") or datos.get("clave_alerta") or "")
    if alerta in ALERTAS_CRITICAS:
        return True
    return str(datos.get("severidad") or datos.get("urgencia") or "").lower() in ("critica", "crítica")


# ----------------------------------------------------------------- consumo y costo

def _inicio_del_mes(cuando: datetime | None = None) -> datetime:
    hoy = (cuando or datetime.now(UTC)).astimezone(UTC)
    return datetime(hoy.year, hoy.month, 1, tzinfo=UTC)


async def consumo(db: AsyncSession, prestador_id: UUID, tenant_id: UUID | None = None,
                  cuando: datetime | None = None) -> dict[str, Any]:
    """Mensajes contados y costo estimado del mes en curso, con el tope y el porcentaje usado."""
    cfg = await configuracion(db, prestador_id, tenant_id)
    desde = _inicio_del_mes(cuando)
    consulta = select(MensajeriaEnvio.canal, func.count(), func.coalesce(func.sum(MensajeriaEnvio.costo_estimado), 0)).where(
        MensajeriaEnvio.prestador_id == prestador_id, MensajeriaEnvio.created_at >= desde,
        MensajeriaEnvio.estado.in_((EstadoEnvioMensajeria.enviado, EstadoEnvioMensajeria.entregado,
                                    EstadoEnvioMensajeria.leido)))
    if tenant_id:
        consulta = consulta.where(MensajeriaEnvio.tenant_id == tenant_id)
    filas = (await db.execute(consulta.group_by(MensajeriaEnvio.canal))).all()
    por_canal = {c.value: {"mensajes": 0, "costo": Decimal("0")} for c in CanalMensajeria}
    for canal, cantidad, costo in filas:
        por_canal[canal.value] = {"mensajes": int(cantidad), "costo": Decimal(costo or 0)}
    total = sum(v["mensajes"] for v in por_canal.values())
    tope = cfg.tope_mensual_mensajes if cfg else 0
    return {"mes": desde.date().isoformat(), "mensajes": total, "tope": tope,
            "porcentaje": round(total * 100 / tope, 1) if tope else 0.0,
            "costo_estimado": sum((v["costo"] for v in por_canal.values()), Decimal("0")),
            "moneda": cfg.moneda if cfg else "MXN", "alerta_pct": cfg.alerta_consumo_pct if cfg else 80,
            "por_canal": {k: {"mensajes": v["mensajes"], "costo": str(v["costo"])} for k, v in por_canal.items()}}


def costo_de(cfg: MensajeriaConfiguracion | None, canal: str, segmentos: int) -> tuple[Decimal, str]:
    """Costo estimado con las tarifas configuradas (sin consultar precios del proveedor)."""
    if cfg is None:
        return Decimal("0"), "MXN"
    if canal == "whatsapp":
        return Decimal(cfg.tarifa_whatsapp), cfg.moneda
    return Decimal(cfg.tarifa_sms) * max(1, segmentos), cfg.moneda


async def _avisar_consumo(db: AsyncSession, prestador_id: UUID, tenant_id: UUID | None) -> None:
    """Alerta MENSAJERIA_CONSUMO_ALTO al llegar al porcentaje configurado, una vez por mes y dueño."""
    datos = await consumo(db, prestador_id, tenant_id)
    if not datos["tope"] or datos["porcentaje"] < datos["alerta_pct"]:
        return
    from models.alertas import AlertaHistorial

    ya = (await db.execute(select(AlertaHistorial.id).where(
        AlertaHistorial.clave_alerta == "MENSAJERIA_CONSUMO_ALTO", AlertaHistorial.prestador_id == prestador_id,
        AlertaHistorial.timestamp_disparo >= _inicio_del_mes()))).first()
    if ya:
        return
    await alertas_service.disparar(db, "MENSAJERIA_CONSUMO_ALTO", tenant_id=None, prestador_id=prestador_id,
                                   entidad_tipo="prestador", entidad_id=prestador_id,
                                   datos={"mensajes": datos["mensajes"], "tope": datos["tope"],
                                          "porcentaje": datos["porcentaje"]})


# ----------------------------------------------------------------- decisión de canal

async def evaluar(db: AsyncSession, usuario: Usuario, canal: str, evento: str, *, prestador_id: UUID | None,
                  tenant_id: UUID | None, datos: dict[str, Any] | None = None,
                  ahora: datetime | None = None) -> tuple[bool, str]:
    """(puede, motivo). El motivo se guarda en la notificación cuando no puede: es lo que la pantalla explica."""
    if canal not in CANALES:
        return True, ""
    clave = catalogo.clave_de_evento(evento, datos)
    critico = es_critico(evento, datos, clave)
    prestador = prestador_id or usuario.prestador_id
    if prestador is None:
        return False, "sin prestador para resolver la configuración de mensajería"
    cfg = await configuracion(db, prestador, tenant_id or usuario.tenant_id)
    if cfg is None:
        return False, "el prestador no tiene configurada la mensajería"
    if not (cfg.whatsapp_activo if canal == "whatsapp" else cfg.sms_activo):
        return False, f"canal {canal} no activo para el prestador"
    permitidos = _eventos_permitidos(cfg, canal)
    if permitidos and evento not in permitidos:
        return False, f"el evento {evento} no está habilitado en {canal}"
    if not usuario.telefono_movil_e164:
        return False, "el usuario no tiene teléfono móvil registrado"
    if usuario.telefono_verificado_at is None:
        return False, "teléfono sin verificar"
    if not telefonos.consentido(usuario, canal):
        return False, f"sin consentimiento vigente para {canal}"
    if not critico and en_silencio(cfg, ahora):
        return False, "horario de silencio"
    datos_consumo = await consumo(db, prestador, cfg.tenant_id, ahora)
    if datos_consumo["tope"] and datos_consumo["mensajes"] >= datos_consumo["tope"] and not critico:
        return False, "tope mensual de mensajes alcanzado"
    return True, ""


def canal_de_respaldo(canales_actuales: list[str]) -> str | None:
    """El siguiente canal de Fase 1 que no esté ya en la lista del usuario."""
    for c in RESPALDO:
        if c not in canales_actuales:
            return c
    return None


async def caer_al_siguiente(db: AsyncSession, n: Notificacion, motivo: str) -> Notificacion | None:
    """Crea la misma notificación en el canal de respaldo y deja escrito por qué cambió de canal (§6.1)."""
    cuerpo = dict(n.cuerpo_json or {})
    datos = dict(cuerpo.get("datos") or {})
    if datos.get("respaldo_de"):
        return None  # ya es el respaldo de otro envío: no se encadena
    hermanos = list((await db.execute(select(Notificacion.canal).where(
        Notificacion.usuario_id == n.usuario_id, Notificacion.evento == n.evento,
        Notificacion.timestamp == n.timestamp))).scalars())
    canales = [c.value for c in hermanos]
    destino = canal_de_respaldo(canales)
    if destino is None:
        return None
    datos["respaldo_de"] = n.canal.value
    datos["motivo_respaldo"] = motivo
    nueva = Notificacion(usuario_id=n.usuario_id, tenant_id=n.tenant_id, prestador_id=n.prestador_id,
                         evento=n.evento, canal=CanalNotificacion(destino), asunto=n.asunto,
                         cuerpo_json={**cuerpo, "datos": datos}, url=n.url, timestamp=n.timestamp)
    if destino == "app":
        nueva.estado, nueva.enviada_at = EstadoNotificacion.enviada, datetime.now(UTC)
    db.add(nueva)
    await db.flush()
    return nueva


# ----------------------------------------------------------------- plantillas

async def plantilla_para(db: AsyncSession, clave: str, canal: str,
                         prestador_id: UUID | None) -> MensajeriaPlantilla | None:
    """La del prestador si la tiene (es la que Meta aprobó para su número); si no, la base de la plataforma."""
    filas = list((await db.execute(select(MensajeriaPlantilla).where(
        MensajeriaPlantilla.clave == clave, MensajeriaPlantilla.canal == CanalMensajeria(canal),
        MensajeriaPlantilla.activa.is_(True)))).scalars())
    propias = [f for f in filas if prestador_id and f.prestador_id == prestador_id]
    globales = [f for f in filas if f.prestador_id is None]
    usables = [f for f in propias + globales
               if f.estado_aprobacion in (EstadoAprobacionPlantilla.aprobada, EstadoAprobacionPlantilla.enviada)]
    return (usables or propias or globales or [None])[0]


async def listar_plantillas(db: AsyncSession, actor: Actor, canal: str | None = None) -> list[dict[str, Any]]:
    consulta = select(MensajeriaPlantilla)
    if canal:
        consulta = consulta.where(MensajeriaPlantilla.canal == CanalMensajeria(canal))
    filas = list((await db.execute(consulta.order_by(MensajeriaPlantilla.clave, MensajeriaPlantilla.canal))).scalars())
    salida = []
    for f in filas:
        definicion = catalogo.POR_CLAVE.get(f.clave)
        salida.append({**plantilla_dict(f), "nombre": definicion.nombre if definicion else f.clave,
                       "evento": definicion.evento if definicion else "", "es_global": f.prestador_id is None})
    return salida


def plantilla_dict(f: MensajeriaPlantilla) -> dict[str, Any]:
    return {"id": f.id, "clave": f.clave, "canal": f.canal.value, "idioma": f.idioma,
            "nombre_proveedor": f.nombre_proveedor, "categoria": f.categoria.value, "cuerpo": f.cuerpo,
            "encabezado": f.encabezado, "pie": f.pie, "botones": f.botones_json, "variables": f.variables_json,
            "estado_aprobacion": f.estado_aprobacion.value, "motivo_rechazo": f.motivo_rechazo,
            "version": f.version, "activa": f.activa, "prestador_id": f.prestador_id}


async def editar_plantilla(db: AsyncSession, actor: Actor, plantilla_id: UUID, cambios: dict[str, Any],
                           request: Request | None = None) -> MensajeriaPlantilla:
    """El Admin prestador edita (o clona para su prestador) la plantilla; el Superadmin además la base."""
    if actor.rol not in (Rol.superadmin, Rol.admin_prestador):
        raise prohibido("Solo el Superadmin y el Admin prestador editan plantillas")
    f = await db.get(MensajeriaPlantilla, plantilla_id)
    if f is None:
        raise no_encontrado("Plantilla")
    if f.prestador_id is None and actor.rol == Rol.admin_prestador:
        # No se toca la base de la plataforma: se clona para el prestador y se edita la copia.
        f = MensajeriaPlantilla(prestador_id=actor.prestador_id, clave=f.clave, canal=f.canal, idioma=f.idioma,
                                nombre_proveedor=f.nombre_proveedor, categoria=f.categoria, cuerpo=f.cuerpo,
                                encabezado=f.encabezado, pie=f.pie, botones_json=list(f.botones_json),
                                variables_json=list(f.variables_json), ejemplo_json=dict(f.ejemplo_json),
                                estado_aprobacion=EstadoAprobacionPlantilla.borrador, version=f.version)
        db.add(f)
    antes = {"cuerpo": f.cuerpo, "estado": f.estado_aprobacion.value}
    for campo in ("cuerpo", "encabezado", "pie", "nombre_proveedor", "motivo_rechazo", "activa"):
        if cambios.get(campo) is not None:
            setattr(f, campo, cambios[campo])
    if cambios.get("botones") is not None:
        f.botones_json = cambios["botones"]
    if cambios.get("estado_aprobacion"):
        f.estado_aprobacion = EstadoAprobacionPlantilla(cambios["estado_aprobacion"])
    if cambios.get("cuerpo") is not None:
        f.version = (f.version or 1) + 1
    if f.estado_aprobacion in (EstadoAprobacionPlantilla.rechazada, EstadoAprobacionPlantilla.pausada) \
            and not f.motivo_rechazo.strip():
        f.motivo_rechazo = "Sin motivo informado por el proveedor"
    await db.flush()
    await auditoria.registrar_actor(db, actor, "mensajeria.plantilla", request, recurso_tipo="mensajeria_plantilla",
                                    recurso_id=f.id, antes=antes,
                                    despues={"cuerpo": f.cuerpo, "estado": f.estado_aprobacion.value})
    return f


def vista_previa(f: MensajeriaPlantilla, valores: dict[str, Any] | None = None) -> dict[str, Any]:
    """Cómo se verá el mensaje: cuerpo renderizado, botones y, en SMS, segmentos y codificación."""
    definicion = catalogo.POR_CLAVE.get(f.clave)
    ejemplo = {**(f.ejemplo_json or {}), **(valores or {})}
    variables = [str(ejemplo.get(v, f"{{{v}}}")) for v in (f.variables_json or [])]
    cuerpo = texto.renderizar(f.cuerpo, variables, enlace=f"{config.app_url_publica.rstrip('/')}/l/abc12345")
    segmentos, codificacion = texto.segmentos_sms(cuerpo) if f.canal == CanalMensajeria.sms else (0, "")
    return {"clave": f.clave, "canal": f.canal.value, "cuerpo": cuerpo,
            "botones": [{"texto": b.get("texto", ""), "tipo": b.get("tipo", "url")} for b in (f.botones_json or [])],
            "segmentos": segmentos, "codificacion": codificacion, "caracteres": texto.longitud_sms(cuerpo),
            "critica": bool(definicion and definicion.critica),
            "aviso": ("El texto lleva acentos o emojis: el SMS pasa a UCS-2 y cada segmento baja a 70 caracteres."
                      if f.canal == CanalMensajeria.sms and codificacion == "UCS-2" else "")}


def exportar_para_meta(f: MensajeriaPlantilla) -> dict[str, Any]:
    """Formato que pide Meta para someter la plantilla a aprobación (se pega en el panel o se manda por su API)."""
    componentes: list[dict[str, Any]] = []
    if f.encabezado:
        componentes.append({"type": "HEADER", "format": "TEXT", "text": f.encabezado})
    ejemplos = [str((f.ejemplo_json or {}).get(v, v)) for v in (f.variables_json or [])]
    cuerpo: dict[str, Any] = {"type": "BODY", "text": f.cuerpo}
    if ejemplos:
        cuerpo["example"] = {"body_text": [ejemplos]}
    componentes.append(cuerpo)
    if f.pie:
        componentes.append({"type": "FOOTER", "text": f.pie})
    botones = []
    for b in (f.botones_json or []):
        if b.get("tipo") == "url":
            botones.append({"type": "URL", "text": b.get("texto", "Abrir"),
                            "url": f"{config.app_url_publica.rstrip('/')}/l/{{{{1}}}}", "example": [
                                f"{config.app_url_publica.rstrip('/')}/l/abc12345"]})
        else:
            botones.append({"type": "QUICK_REPLY", "text": b.get("texto", "")})
    if botones:
        componentes.append({"type": "BUTTONS", "buttons": botones})
    return {"name": f.nombre_proveedor or f"acma_{f.clave}", "language": f.idioma,
            "category": f.categoria.value.upper(), "components": componentes}


# ----------------------------------------------------------------- valores del mensaje

async def valores_de(db: AsyncSession, n: Notificacion) -> dict[str, Any]:
    """Datos para las variables de la plantilla. Solo lo que §6.9.5 permite: folio, sucursal, estado y enlace."""
    cuerpo = n.cuerpo_json or {}
    datos = dict(cuerpo.get("datos") or {})
    valores: dict[str, Any] = {"asunto": n.asunto, "detalle": (cuerpo.get("cuerpo") or "")[:200]}
    destino = n.url or "/"
    if datos.get("folio_id"):
        from models.folios import Folio
        from models.unidades import UnidadNegocio

        folio = await db.get(Folio, UUID(str(datos["folio_id"])))
        if folio is not None:
            un = await db.get(UnidadNegocio, folio.un_id)
            tecnico = await db.get(Usuario, folio.tecnico_id) if folio.tecnico_id else None
            valores |= {"folio": folio.numero_folio, "sucursal": f"{un.codigo} {un.nombre}" if un else "su sucursal",
                        "estado": folio.estado.value.replace("_", " "), "tecnico": tecnico.nombre if tecnico else "",
                        "folio_id": str(folio.id)}
            datos.setdefault("estado", folio.estado.value)
            destino = f"/folios/{folio.id}"
    elif datos.get("numero_folio"):
        valores["folio"] = datos["numero_folio"]
    if datos.get("minuta_id"):
        from models.minutas import Minuta

        minuta = await db.get(Minuta, UUID(str(datos["minuta_id"])))
        if minuta is not None:
            puntos = await resumen_minuta(db, minuta)
            valores |= {"fecha": minuta.fecha.strftime("%d/%m/%Y"), "ambito": await _ambito_minuta(db, minuta),
                        "resumen": " · ".join(puntos), "minuta_id": str(minuta.id)}
            destino = enlace_pdf_minuta(minuta.id, n.usuario_id)
    if n.evento == "alerta":
        clave = str(datos.get("alerta") or datos.get("clave_alerta") or "")
        valores |= {"alerta": n.asunto, "clave_alerta": clave}
        valores.setdefault("dias", str(datos.get("dias") or datos.get("horas") or ""))
        valores.setdefault("tecnico", str(datos.get("tecnico") or ""))
        valores.setdefault("curso", str(datos.get("curso") or ""))
    for clave_dato in ("consecutivo", "sucursal", "tecnico", "razon", "severidad", "nivel", "dias", "curso"):
        if datos.get(clave_dato):
            valores[clave_dato] = str(datos[clave_dato])
    valores["_datos"] = datos
    valores["_destino"] = destino
    return valores


async def _ambito_minuta(db: AsyncSession, minuta) -> str:
    from models.unidades import UnidadNegocio

    if minuta.un_id:
        un = await db.get(UnidadNegocio, minuta.un_id)
        return f" de {un.codigo} {un.nombre}" if un else ""
    return " (global)"


async def resumen_minuta(db: AsyncSession, minuta, maximo: int = 5) -> list[str]:
    """§7.5: máximo 5 puntos con lo más crítico del día. Sin nada crítico, un aviso breve."""
    from services import minuta_service

    secciones = await minuta_service.secciones_de(db, minuta.id)
    puntos: list[str] = []
    rojos = [k for k, v in (secciones.get("contadores") or {}).items()
             if isinstance(v, dict) and v.get("color") == "rojo"]
    if rojos:
        puntos.append(f"{len(rojos)} indicador(es) en rojo: {', '.join(rojos[:3])}")
    hallazgos = [h for h in (secciones.get("hallazgos") or []) if h.get("urgencia") in ("alta", "critica")]
    if hallazgos:
        criticos = sum(1 for h in hallazgos if h.get("urgencia") == "critica")
        puntos.append(f"{len(hallazgos)} hallazgo(s) de urgencia alta" + (f", {criticos} crítico(s)" if criticos else ""))
    atrasados = [p for p in (secciones.get("preventivos") or []) if p.get("retraso") or p.get("atrasado")]
    if atrasados:
        puntos.append(f"{len(atrasados)} preventivo(s) con retraso")
    cotizaciones = secciones.get("cotizaciones") or {}
    por_vencer = cotizaciones.get("por_vencer") if isinstance(cotizaciones, dict) else None
    if por_vencer:
        puntos.append(f"{len(por_vencer)} cotización(es) por vencer")
    pendientes = [h for h in (secciones.get("hallazgos") or []) if h.get("estado_respuesta") == "pendiente"]
    if pendientes and len(puntos) < maximo:
        puntos.append(f"{len(pendientes)} hallazgo(s) esperan tu respuesta")
    if not puntos:
        puntos.append("sin pendientes críticos")
    return puntos[:maximo]


# ----------------------------------------------------------------- enlaces

def nuevo_codigo_enlace() -> str:
    return secrets.token_urlsafe(6)[:8]


def enlace_pdf_minuta(minuta_id: UUID, usuario_id: UUID | None) -> str:
    """Ruta firmada de corta duración al PDF de la minuta (§7.5), para abrirlo desde WhatsApp sin sesión."""
    token = crear_jwt({"mid": str(minuta_id), "sub": str(usuario_id or "")}, TIPO_PDF, MINUTOS_PDF)
    return f"/api/mensajeria/minutas/{token}.pdf"


def leer_token_pdf(token: str) -> dict[str, Any]:
    import jwt

    try:
        return decodificar_jwt(token, TIPO_PDF)
    except jwt.PyJWTError:
        raise prohibido("El enlace del PDF venció o no es válido")


def enlace_publico(codigo: str) -> str:
    return f"{config.app_url_publica.rstrip('/')}/l/{codigo}"


async def resolver_enlace(db: AsyncSession, codigo: str, registrar: bool = True) -> dict[str, Any]:
    """Destino de un enlace corto `/l/{codigo}`. Lo consulta el frontend sin sesión; solo devuelve una ruta."""
    envio = (await db.execute(select(MensajeriaEnvio).where(MensajeriaEnvio.codigo_enlace == codigo))).scalar_one_or_none()
    if envio is None or not envio.enlace_destino:
        raise no_encontrado("Enlace")
    if registrar and envio.abierto_at is None:
        envio.abierto_at = datetime.now(UTC)
        await db.flush()
    return {"destino": envio.enlace_destino, "canal": envio.canal.value, "evento": envio.evento}


# ----------------------------------------------------------------- envío

async def enviar_notificacion(db: AsyncSession, n: Notificacion, usuario: Usuario) -> tuple[str, str]:
    """Manda la notificación por WhatsApp o SMS. Devuelve (estado de la notificación, detalle) para `procesar()`.

    Estados posibles: `enviada`, `omitida` (con el motivo) o `fallida` (se reintenta). Cuando el error es
    permanente —número inválido, plantilla rechazada, usuario dado de baja— el aviso cae al siguiente canal.
    """
    canal = n.canal.value
    datos = dict((n.cuerpo_json or {}).get("datos") or {})
    puede, motivo = await evaluar(db, usuario, canal, n.evento, prestador_id=n.prestador_id, tenant_id=n.tenant_id,
                                 datos=datos)
    if not puede:
        await caer_al_siguiente(db, n, motivo)
        return "omitida", motivo
    e164 = telefonos.en_claro(usuario)
    if not e164:
        await caer_al_siguiente(db, n, "teléfono ilegible")
        return "omitida", "teléfono ilegible"
    prestador_id = n.prestador_id or usuario.prestador_id
    cfg = await configuracion(db, prestador_id, n.tenant_id or usuario.tenant_id)
    valores = await valores_de(db, n)
    clave = catalogo.clave_de_evento(n.evento, valores["_datos"])
    plantilla = await plantilla_para(db, clave, canal, prestador_id)
    if plantilla is None:
        await caer_al_siguiente(db, n, f"sin plantilla de {canal} para {clave}")
        return "omitida", f"sin plantilla de {canal} para {clave}"
    if plantilla.estado_aprobacion in (EstadoAprobacionPlantilla.rechazada, EstadoAprobacionPlantilla.pausada):
        await _avisar_plantilla(db, plantilla)
        await caer_al_siguiente(db, n, f"plantilla {clave} {plantilla.estado_aprobacion.value}")
        return "omitida", f"plantilla {clave} {plantilla.estado_aprobacion.value}"
    if not proveedores.permitir(f"{proveedores.nombre_proveedor(canal)}:{n.tenant_id or prestador_id}"):
        return "fallida", "límite de tasa del proveedor alcanzado; se reintenta"

    envio = MensajeriaEnvio(
        prestador_id=prestador_id, tenant_id=n.tenant_id, usuario_id=usuario.id, notificacion_id=n.id,
        evento=n.evento, canal=CanalMensajeria(canal), proveedor=ProveedorMensajeria(proveedores.nombre_proveedor(canal)),
        telefono_destino_hash=usuario.telefono_movil_hash or telefonos.hash_telefono(e164),
        telefono_mascara=usuario.telefono_movil_mascara or telefonos.mascara(e164),
        plantilla_id=plantilla.id, plantilla_clave=clave, critico=es_critico(n.evento, valores["_datos"], clave),
        codigo_enlace=nuevo_codigo_enlace(), enlace_destino=valores["_destino"],
        moneda=cfg.moneda if cfg else "MXN")
    variables = [str(valores.get(v, "")) for v in (plantilla.variables_json or [])]
    envio.variables_json = variables
    mensaje = texto.MensajeSaliente(
        canal=canal, telefono=e164, cuerpo=texto.renderizar(plantilla.cuerpo, variables, enlace_publico(envio.codigo_enlace)),
        plantilla_clave=clave, nombre_proveedor=plantilla.nombre_proveedor, idioma=plantilla.idioma,
        variables=variables, remitente=_remitente(cfg, canal), enlace=enlace_publico(envio.codigo_enlace),
        botones=[{**b, "sufijo": envio.codigo_enlace} for b in (plantilla.botones_json or [])])
    envio.cuerpo_renderizado = mensaje.cuerpo
    if canal == "sms":
        envio.segmentos_sms, _ = texto.segmentos_sms(mensaje.cuerpo)
        if len(mensaje.cuerpo) > catalogo.LONGITUD_MAXIMA_SMS:
            mensaje.cuerpo = mensaje.cuerpo[:catalogo.LONGITUD_MAXIMA_SMS - 1].rstrip() + "…"
    envio.costo_estimado, envio.moneda = costo_de(cfg, canal, envio.segmentos_sms)
    envio.intentos = 1
    db.add(envio)
    await db.flush()

    resultado = await proveedores.obtener(canal).enviar_plantilla(mensaje)
    await _aplicar_resultado(db, envio, resultado)
    await auditoria.registrar(db, f"mensajeria.{canal}", actor_rol="sistema", tenant_id=n.tenant_id,
                              prestador_id=prestador_id, recurso_tipo="mensajeria_envio", recurso_id=envio.id,
                              despues={"evento": n.evento, "plantilla": clave, "estado": envio.estado.value,
                                       "telefono": envio.telefono_mascara, "hash": envio.telefono_destino_hash[:12],
                                       "costo": str(envio.costo_estimado)})
    if resultado.estado == "enviado":
        await _avisar_consumo(db, prestador_id, envio.tenant_id)
        return "enviada", f"{envio.proveedor.value}:{resultado.mensaje_id}"
    if resultado.permanente:
        await caer_al_siguiente(db, n, f"{canal}: {resultado.codigo_error or 'rechazado por el proveedor'}")
        return "omitida", f"{canal} rechazado ({resultado.codigo_error}): {resultado.detalle}"[:400]
    envio.proximo_intento_at = datetime.now(UTC) + timedelta(minutes=2)
    await db.flush()
    return "fallida", f"{resultado.codigo_error}: {resultado.detalle}"[:400]


def _remitente(cfg: MensajeriaConfiguracion | None, canal: str) -> str:
    if cfg is not None:
        propio = cfg.remitente_whatsapp if canal == "whatsapp" else cfg.remitente_sms
        if propio:
            return propio
    return proveedores.remitente_de(canal)


async def _aplicar_resultado(db: AsyncSession, envio: MensajeriaEnvio, resultado: texto.Resultado) -> None:
    ahora = datetime.now(UTC)
    if resultado.estado == "enviado":
        envio.estado, envio.enviado_at = EstadoEnvioMensajeria.enviado, ahora
        envio.mensaje_id_proveedor = resultado.mensaje_id or None
        if resultado.detalle.startswith("stub:"):
            envio.vista_previa_key = resultado.detalle[5:] or None
    else:
        envio.estado = (EstadoEnvioMensajeria.rechazado_por_proveedor if resultado.permanente
                        else EstadoEnvioMensajeria.fallido)
        envio.codigo_error, envio.detalle_error = resultado.codigo_error[:60], resultado.detalle[:1000]
        envio.costo_estimado = Decimal("0")  # lo que no salió no se cobra
    await db.flush()


async def _avisar_plantilla(db: AsyncSession, plantilla: MensajeriaPlantilla) -> None:
    from models.alertas import AlertaHistorial
    from models.base import EstadoAlerta

    ya = (await db.execute(select(AlertaHistorial.id).where(
        AlertaHistorial.clave_alerta == "MENSAJERIA_PLANTILLA_RECHAZADA",
        AlertaHistorial.entidad_id == plantilla.id, AlertaHistorial.estado == EstadoAlerta.disparada))).first()
    if ya:
        return
    await alertas_service.disparar(db, "MENSAJERIA_PLANTILLA_RECHAZADA", tenant_id=None,
                                   prestador_id=plantilla.prestador_id, entidad_tipo="mensajeria_plantilla",
                                   entidad_id=plantilla.id,
                                   datos={"clave": plantilla.clave, "canal": plantilla.canal.value,
                                          "estado": plantilla.estado_aprobacion.value,
                                          "motivo": plantilla.motivo_rechazo})


async def reintentar_pendientes(db: AsyncSession, limite: int = 100) -> dict[str, int]:
    """Reintentos con espera exponencial: 2, 4, 8… minutos, hasta 5 intentos (§6.1)."""
    ahora = datetime.now(UTC)
    filas = list((await db.execute(select(MensajeriaEnvio).where(
        MensajeriaEnvio.estado == EstadoEnvioMensajeria.fallido, MensajeriaEnvio.intentos < 5,
        MensajeriaEnvio.proximo_intento_at.is_not(None),
        MensajeriaEnvio.proximo_intento_at <= ahora).limit(limite))).scalars())
    resumen = {"reintentados": 0, "enviados": 0, "agotados": 0}
    for envio in filas:
        usuario = await db.get(Usuario, envio.usuario_id) if envio.usuario_id else None
        e164 = telefonos.en_claro(usuario) if usuario else None
        if not e164 or usuario.estado != EstadoRegistro.activo:
            envio.estado, envio.codigo_error = EstadoEnvioMensajeria.rechazado_por_proveedor, "SIN_DESTINO"
            resumen["agotados"] += 1
            continue
        cfg = await configuracion(db, envio.prestador_id, envio.tenant_id)
        mensaje = texto.MensajeSaliente(canal=envio.canal.value, telefono=e164, cuerpo=envio.cuerpo_renderizado,
                                        plantilla_clave=envio.plantilla_clave,
                                        variables=[str(v) for v in (envio.variables_json or [])],
                                        remitente=_remitente(cfg, envio.canal.value),
                                        enlace=enlace_publico(envio.codigo_enlace or ""))
        envio.intentos += 1
        resultado = await proveedores.por_nombre(envio.proveedor.value).enviar_plantilla(mensaje)
        await _aplicar_resultado(db, envio, resultado)
        resumen["reintentados"] += 1
        if resultado.estado == "enviado":
            resumen["enviados"] += 1
        elif envio.intentos >= 5:
            resumen["agotados"] += 1
            if envio.notificacion_id:
                n = await db.get(Notificacion, envio.notificacion_id)
                if n is not None:
                    await caer_al_siguiente(db, n, f"{envio.canal.value}: sin entrega después de 5 intentos")
        else:
            envio.proximo_intento_at = ahora + timedelta(minutes=2 ** envio.intentos)
    await db.flush()
    return resumen


# ----------------------------------------------------------------- verificación del teléfono

async def enviar_codigo(db: AsyncSession, usuario: Usuario, canal: str = "sms") -> dict[str, Any]:
    """Código de un solo uso por el mismo canal. En modo stub el código queda en la bitácora y en el log."""
    e164 = telefonos.en_claro(usuario)
    if not e164:
        raise ErrorAPI(409, "SIN_TELEFONO", "Primero guarda tu teléfono móvil")
    if canal not in CANALES:
        canal = "sms"
    codigo = telefonos.nuevo_codigo(usuario)
    await db.flush()
    plantilla = await plantilla_para(db, "codigo_verificacion", canal, usuario.prestador_id)
    cuerpo = texto.renderizar(plantilla.cuerpo if plantilla else "ACMA: tu codigo es {{1}} ({{2}} min).",
                              [codigo, str(telefonos.MINUTOS_CODIGO)])
    mensaje = texto.MensajeSaliente(canal=canal, telefono=e164, cuerpo=cuerpo,
                                    plantilla_clave="codigo_verificacion",
                                    nombre_proveedor=plantilla.nombre_proveedor if plantilla else "",
                                    variables=[codigo, str(telefonos.MINUTOS_CODIGO)],
                                    remitente=proveedores.remitente_de(canal))
    resultado = await proveedores.obtener(canal).enviar_plantilla(mensaje)
    registro = MensajeriaEnvio(
        prestador_id=usuario.prestador_id or await _prestador_de_respaldo(db, usuario), tenant_id=usuario.tenant_id,
        usuario_id=usuario.id, evento="telefono.verificacion", canal=CanalMensajeria(canal),
        proveedor=ProveedorMensajeria(proveedores.nombre_proveedor(canal)),
        telefono_destino_hash=usuario.telefono_movil_hash or telefonos.hash_telefono(e164),
        telefono_mascara=usuario.telefono_movil_mascara or telefonos.mascara(e164),
        plantilla_clave="codigo_verificacion", critico=True, cuerpo_renderizado=cuerpo, intentos=1)
    if registro.prestador_id is not None:
        db.add(registro)
        await db.flush()
        await _aplicar_resultado(db, registro, resultado)
    log.info("Código de verificación enviado a %s por %s (%s)", usuario.telefono_movil_mascara, canal,
             resultado.estado)
    return {"enviado": resultado.estado == "enviado", "canal": canal, "minutos": telefonos.MINUTOS_CODIGO,
            "modo": proveedores.modo_de_canal(canal), "detalle": resultado.detalle}


async def _prestador_de_respaldo(db: AsyncSession, usuario: Usuario) -> UUID | None:
    """Un usuario del dominio del cliente no tiene prestador; para la bitácora se usa el que lo atiende."""
    if usuario.tenant_id is None:
        return None
    from models.organizaciones import TenantPrestador

    return (await db.execute(select(TenantPrestador.prestador_id).where(
        TenantPrestador.tenant_id == usuario.tenant_id, TenantPrestador.estado == EstadoRegistro.activo
    ).limit(1))).scalar()


# ----------------------------------------------------------------- mensajes entrantes

async def actualizar_estado(db: AsyncSession, proveedor: str, mensaje_id: str, estado: str,
                            codigo_error: str = "", detalle: str = "") -> MensajeriaEnvio | None:
    """Estado de entrega o lectura que informa el proveedor por webhook."""
    envio = (await db.execute(select(MensajeriaEnvio).where(
        MensajeriaEnvio.mensaje_id_proveedor == mensaje_id))).scalar_one_or_none()
    if envio is None:
        return None
    ahora = datetime.now(UTC)
    if estado == "entregado" and envio.estado in (EstadoEnvioMensajeria.enviado, EstadoEnvioMensajeria.en_cola):
        envio.estado, envio.entregado_at = EstadoEnvioMensajeria.entregado, ahora
    elif estado == "leido":
        envio.estado, envio.leido_at = EstadoEnvioMensajeria.leido, ahora
        envio.entregado_at = envio.entregado_at or ahora
    elif estado == "fallido":
        envio.estado = EstadoEnvioMensajeria.fallido
        envio.codigo_error, envio.detalle_error = codigo_error[:60], detalle[:1000]
    await db.flush()
    return envio


async def usuario_por_telefono(db: AsyncSession, e164: str) -> Usuario | None:
    return (await db.execute(select(Usuario).where(
        Usuario.telefono_movil_hash == telefonos.hash_telefono(e164),
        Usuario.estado == EstadoRegistro.activo))).scalar_one_or_none()


async def procesar_entrante(db: AsyncSession, *, canal: str, telefono: str, texto_mensaje: str = "",
                            boton: str = "", proveedor: str = "stub",
                            mensaje_id: str = "") -> MensajeriaRespuesta:
    """Mensaje del usuario: «BAJA» da de baja el canal, «ALTA» lo reactiva y un botón contesta con el enlace.

    Ninguna acción crítica se ejecuta aquí (decisión de seguridad): «Aprobar» y «Rechazar» responden con el enlace a
    la pantalla de aprobación, donde el usuario entra con su sesión y su doble factor si aplica.
    """
    e164 = telefonos.normalizar(telefono)
    usuario = await usuario_por_telefono(db, e164)
    palabra = texto.sin_acentos((boton or texto_mensaje or "").strip()).upper()
    ultimo = None
    if usuario is not None:
        ultimo = (await db.execute(select(MensajeriaEnvio).where(
            MensajeriaEnvio.usuario_id == usuario.id, MensajeriaEnvio.canal == CanalMensajeria(canal)
        ).order_by(MensajeriaEnvio.created_at.desc()).limit(1))).scalar_one_or_none()
    accion = ""
    if usuario is not None:
        if palabra == PALABRA_BAJA:
            telefonos.fijar_consentimiento(usuario, canal, False)
            accion = f"baja_{canal}"
        elif palabra == PALABRA_ALTA:
            telefonos.fijar_consentimiento(usuario, canal, True)
            accion = f"alta_{canal}"
        elif palabra in ("APROBAR", "RECHAZAR", "VER FOLIO") and ultimo is not None:
            accion = "enlace_enviado"
    respuesta = MensajeriaRespuesta(
        prestador_id=usuario.prestador_id if usuario else None,
        tenant_id=usuario.tenant_id if usuario else None, usuario_id=usuario.id if usuario else None,
        canal=CanalMensajeria(canal), proveedor=ProveedorMensajeria(proveedor),
        telefono_hash=telefonos.hash_telefono(e164), telefono_mascara=telefonos.mascara(e164),
        texto=(texto_mensaje or "")[:1000], boton=(boton or "")[:60], envio_id=ultimo.id if ultimo else None,
        mensaje_id_proveedor=mensaje_id or None, accion_ejecutada=accion)
    db.add(respuesta)
    await db.flush()
    if accion.startswith(("baja_", "alta_")):
        await auditoria.registrar(db, f"mensajeria.{accion}", actor_rol="sistema",
                                  tenant_id=respuesta.tenant_id, prestador_id=respuesta.prestador_id,
                                  recurso_tipo="usuario", recurso_id=usuario.id if usuario else None,
                                  despues={"canal": canal, "telefono": respuesta.telefono_mascara})
        await _confirmar_por_el_mismo_canal(db, usuario, canal, accion)
    elif accion == "enlace_enviado":
        await _responder_con_enlace(db, usuario, canal, ultimo)
    return respuesta


async def _confirmar_por_el_mismo_canal(db: AsyncSession, usuario: Usuario | None, canal: str, accion: str) -> None:
    """Acuse dentro de la ventana de 24 h (el usuario acaba de escribir, así que el texto libre es válido)."""
    if usuario is None:
        return
    e164 = telefonos.en_claro(usuario)
    if not e164:
        return
    aviso = ("Listo: ya no recibiras avisos de ACMA por este canal. Escribe ALTA para volver a activarlo."
             if accion.startswith("baja_") else "Listo: volveras a recibir los avisos de ACMA por este canal.")
    await proveedores.obtener(canal).enviar_texto(texto.MensajeSaliente(
        canal=canal, telefono=e164, cuerpo=aviso, remitente=proveedores.remitente_de(canal)))


async def _responder_con_enlace(db: AsyncSession, usuario: Usuario | None, canal: str,
                                envio: MensajeriaEnvio | None) -> None:
    if usuario is None or envio is None:
        return
    e164 = telefonos.en_claro(usuario)
    if not e164:
        return
    enlace = enlace_publico(envio.codigo_enlace or "")
    cuerpo = ("Por seguridad la decision no se toma por mensaje: abre ACMA con tu usuario para autorizar o "
              f"rechazar. {enlace}")
    await proveedores.obtener(canal).enviar_texto(texto.MensajeSaliente(
        canal=canal, telefono=e164, cuerpo=cuerpo, enlace=enlace, remitente=proveedores.remitente_de(canal)))


# ----------------------------------------------------------------- webhooks

def _telefono_de_meta(valor: str) -> str:
    return valor if valor.startswith("+") else f"+{valor}"


async def webhook_meta(db: AsyncSession, cuerpo: dict[str, Any]) -> dict[str, int]:
    """Estados de entrega/lectura y mensajes entrantes de WhatsApp Cloud API."""
    resumen = {"estados": 0, "entrantes": 0}
    for entrada in cuerpo.get("entry", []):
        for cambio in entrada.get("changes", []):
            valor = cambio.get("value", {})
            for estado in valor.get("statuses", []):
                mapeo = {"sent": "enviado", "delivered": "entregado", "read": "leido", "failed": "fallido"}
                nuevo = mapeo.get(str(estado.get("status")))
                if not nuevo:
                    continue
                errores = estado.get("errors") or [{}]
                if await actualizar_estado(db, "meta_cloud", str(estado.get("id", "")), nuevo,
                                           str(errores[0].get("code", "")), str(errores[0].get("title", ""))):
                    resumen["estados"] += 1
            for mensaje in valor.get("messages", []):
                boton = ((mensaje.get("button") or {}).get("text")
                         or ((mensaje.get("interactive") or {}).get("button_reply") or {}).get("title") or "")
                await procesar_entrante(db, canal="whatsapp", telefono=_telefono_de_meta(str(mensaje.get("from", ""))),
                                        texto_mensaje=str((mensaje.get("text") or {}).get("body", "")), boton=boton,
                                        proveedor="meta_cloud", mensaje_id=str(mensaje.get("id", "")))
                resumen["entrantes"] += 1
    return resumen


async def webhook_twilio(db: AsyncSession, formulario: dict[str, str]) -> dict[str, int]:
    """Estados y mensajes entrantes de Twilio (SMS o WhatsApp)."""
    from services.mensajeria.twilio import ESTADOS

    resumen = {"estados": 0, "entrantes": 0}
    sid = formulario.get("MessageSid") or formulario.get("SmsSid") or ""
    estado = ESTADOS.get(str(formulario.get("MessageStatus") or formulario.get("SmsStatus") or ""))
    if estado and sid:
        if await actualizar_estado(db, "twilio", sid, estado, str(formulario.get("ErrorCode") or ""),
                                   str(formulario.get("ErrorMessage") or "")):
            resumen["estados"] += 1
    cuerpo_texto = formulario.get("Body")
    if cuerpo_texto is not None and formulario.get("From"):
        origen = str(formulario["From"])
        canal = "whatsapp" if origen.startswith("whatsapp:") else "sms"
        await procesar_entrante(db, canal=canal, telefono=origen.replace("whatsapp:", ""),
                                texto_mensaje=str(cuerpo_texto), proveedor="twilio", mensaje_id=sid)
        resumen["entrantes"] += 1
    return resumen


# ----------------------------------------------------------------- bitácora

async def listar_envios(db: AsyncSession, actor: Actor, *, canal: str | None = None, estado: str | None = None,
                        usuario_id: UUID | None = None, evento: str | None = None, folio_id: UUID | None = None,
                        desde: date | None = None, limite: int = 100) -> list[MensajeriaEnvio]:
    consulta = select(MensajeriaEnvio)
    if actor.rol == Rol.admin_empresa:
        consulta = consulta.where(MensajeriaEnvio.tenant_id == actor.tenant_id)
    elif actor.rol != Rol.superadmin:
        consulta = consulta.where(MensajeriaEnvio.prestador_id == actor.prestador_id)
    if canal:
        consulta = consulta.where(MensajeriaEnvio.canal == CanalMensajeria(canal))
    if estado:
        consulta = consulta.where(MensajeriaEnvio.estado == EstadoEnvioMensajeria(estado))
    if usuario_id:
        consulta = consulta.where(MensajeriaEnvio.usuario_id == usuario_id)
    if evento:
        consulta = consulta.where(MensajeriaEnvio.evento == evento)
    if folio_id:
        # El envio guarda la pantalla a la que lleva su enlace: es el vinculo con el folio sin duplicar la columna.
        consulta = consulta.where(MensajeriaEnvio.enlace_destino == f"/folios/{folio_id}")
    if desde:
        consulta = consulta.where(MensajeriaEnvio.created_at >= datetime.combine(desde, time.min, tzinfo=UTC))
    return list((await db.execute(consulta.order_by(MensajeriaEnvio.created_at.desc()).limit(limite))).scalars())


async def envios_de_notificaciones(db: AsyncSession, ids: list[UUID]) -> dict[UUID, MensajeriaEnvio]:
    """Para el detalle del folio y de la minuta: por qué canal se notificó y en qué estado va la entrega."""
    if not ids:
        return {}
    filas = list((await db.execute(select(MensajeriaEnvio).where(
        MensajeriaEnvio.notificacion_id.in_(ids)))).scalars())
    return {f.notificacion_id: f for f in filas if f.notificacion_id}


def envio_dict(e: MensajeriaEnvio) -> dict[str, Any]:
    return {"id": e.id, "canal": e.canal.value, "estado": e.estado.value, "evento": e.evento,
            "plantilla": e.plantilla_clave, "proveedor": e.proveedor.value, "telefono": e.telefono_mascara,
            "cuerpo": e.cuerpo_renderizado, "costo_estimado": str(e.costo_estimado), "moneda": e.moneda,
            "segmentos_sms": e.segmentos_sms, "intentos": e.intentos, "codigo_error": e.codigo_error,
            "detalle_error": e.detalle_error, "created_at": e.created_at, "enviado_at": e.enviado_at,
            "entregado_at": e.entregado_at, "leido_at": e.leido_at, "abierto_at": e.abierto_at,
            "usuario_id": e.usuario_id, "critico": e.critico, "enlace_destino": e.enlace_destino,
            "mensaje_id_proveedor": e.mensaje_id_proveedor}


async def prueba_de_envio(db: AsyncSession, actor: Actor, canal: str, telefono: str | None = None,
                          clave: str = "notificacion_generica") -> dict[str, Any]:
    """Envío de prueba a un número verificado, solo para administradores (§6.1: para validar la cuenta nueva)."""
    if actor.rol not in GESTIONAN:
        raise prohibido("Solo los administradores pueden mandar un mensaje de prueba")
    usuario = await db.get(Usuario, actor.id)
    destino = telefonos.normalizar(telefono) if telefono else telefonos.en_claro(usuario)
    if not destino:
        raise ErrorAPI(409, "SIN_TELEFONO", "Guarda y verifica tu teléfono, o indica un número verificado")
    if telefono and usuario.telefono_movil_hash != telefonos.hash_telefono(destino) \
            and proveedores.modo_de_canal(canal) != "stub":
        raise prohibido("En modo prueba solo se puede enviar a tu propio número verificado o a uno del panel del "
                        "proveedor; verifícalo allí primero")
    plantilla = await plantilla_para(db, clave, canal, actor.prestador_id)
    if plantilla is None:
        raise no_encontrado("Plantilla")
    previa = vista_previa(plantilla)
    resultado = await proveedores.obtener(canal).enviar_plantilla(texto.MensajeSaliente(
        canal=canal, telefono=destino, cuerpo=previa["cuerpo"], plantilla_clave=clave,
        nombre_proveedor=plantilla.nombre_proveedor, variables=[str(v) for v in (plantilla.variables_json or [])],
        remitente=proveedores.remitente_de(canal)))
    await auditoria.registrar_actor(db, actor, "mensajeria.prueba", None, recurso_tipo="mensajeria_plantilla",
                                    recurso_id=plantilla.id,
                                    despues={"canal": canal, "telefono": telefonos.mascara(destino),
                                             "estado": resultado.estado})
    return {"estado": resultado.estado, "modo": proveedores.modo_de_canal(canal),
            "proveedor": proveedores.nombre_proveedor(canal), "cuerpo": previa["cuerpo"],
            "detalle": resultado.detalle, "codigo_error": resultado.codigo_error}
