"""Catálogo de plantillas de WhatsApp y SMS por evento (§6.1, §7.5). F2-02.

El texto vive aquí (una sola fuente) y `sembrar_plantillas()` lo sincroniza con `mensajeria_plantillas`, que es lo
que el Admin prestador edita y somete a Meta. Reglas que el catálogo cumple y las pruebas verifican:

* **Nada sensible en el mensaje** (§6.9.5): ni montos, ni datos de terceros, ni evidencias. Solo el identificador
  del folio, la sucursal, el estado y el enlace. `CAMPOS_PROHIBIDOS` lo verifica sobre el cuerpo y las variables.
* **WhatsApp**: español, categoría `utility`, variables posicionales `{{1}}`… y un botón de enlace a la pantalla
  exacta de ACMA. Ninguna acción crítica se ejecuta desde el mensaje: los botones «Aprobar» y «Rechazar» son
  respuestas rápidas que contestan con el enlace a la pantalla de aprobación (sesión normal y MFA si aplica).
* **SMS**: sin acentos para caber en un segmento GSM-7 de 160 caracteres (con acentos el mensaje pasa a UCS-2 y se
  queda en 70), y con el enlace corto propio de ACMA `/l/{codigo}` en el marcador `{enlace}`.
"""
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Palabras que delatan un dato financiero o personal de terceros en el cuerpo o en una variable (§6.9.5).
CAMPOS_PROHIBIDOS = (
    "monto", "total", "importe", "costo", "precio", "subtotal", "iva", "saldo", "presupuesto", "tarifa",
    "factura", "cfdi", "rfc", "cuenta", "tarjeta", "sueldo", "telefono", "correo", "email", "direccion", "evidencia",
)
LONGITUD_MAXIMA_SMS = 320  # dos segmentos GSM-7: más que eso no se envía (el enlace lleva al detalle)


@dataclass(frozen=True)
class Boton:
    tipo: str  # "url" | "respuesta_rapida"
    texto: str
    ruta: str = ""  # ruta de ACMA para los botones de enlace ({folio_id}, {minuta_id}… se sustituyen con los datos)


@dataclass(frozen=True)
class Plantilla:
    clave: str
    nombre: str  # cómo se llama en la pantalla de ACMA
    evento: str  # evento de `notificar()` que la usa
    subtipo: str = ""  # estado del folio o clave de alerta, cuando el evento tiene varias plantillas
    whatsapp: str = ""
    sms: str = ""
    variables: tuple[str, ...] = ()
    botones: tuple[Boton, ...] = ()
    categoria: str = "utility"
    critica: bool = False  # ignora el horario de silencio (§6.1)
    ejemplo: dict[str, Any] = field(default_factory=dict)


# El enlace corto se arma con `codigo_enlace`; en WhatsApp va en el botón y en SMS en el marcador {enlace}.
VER_FOLIO = (Boton("url", "Ver folio", "/folios/{folio_id}"),)
VER_MINUTA = (Boton("url", "Ver minuta", "/minutas/{minuta_id}"),)

CATALOGO: tuple[Plantilla, ...] = (
    # ------------------------------------------------------------------ folios (§6.8)
    Plantilla(
        clave="folio_creado", nombre="Folio creado", evento="folio.estado", subtipo="capturado",
        whatsapp="Se levantó el folio {{1}} en {{2}} ({{3}}). Lo puedes seguir en ACMA con el botón de abajo.",
        sms="ACMA: folio {{1}} creado en {{2}}. Seguimiento: {enlace}",
        variables=("folio", "sucursal", "severidad"), botones=VER_FOLIO,
        ejemplo={"folio": "F-2026-000123", "sucursal": "Sucursal Centro", "severidad": "media"}),
    Plantilla(
        clave="folio_autorizado", nombre="Folio autorizado", evento="folio.estado", subtipo="autorizado",
        whatsapp="El folio {{1}} de {{2}} quedó autorizado y pasa a asignación.",
        sms="ACMA: folio {{1}} autorizado en {{2}}. {enlace}",
        variables=("folio", "sucursal"), botones=VER_FOLIO,
        ejemplo={"folio": "F-2026-000123", "sucursal": "Sucursal Centro"}),
    Plantilla(
        clave="folio_asignado", nombre="Folio asignado a un técnico", evento="folio.estado", subtipo="asignado",
        whatsapp="El folio {{1}} de {{2}} quedó asignado a {{3}}.",
        sms="ACMA: folio {{1}} asignado a {{3}} en {{2}}. {enlace}",
        variables=("folio", "sucursal", "tecnico"), botones=VER_FOLIO,
        ejemplo={"folio": "F-2026-000123", "sucursal": "Sucursal Centro", "tecnico": "Tadeo Tecnico"}),
    Plantilla(
        clave="folio_en_camino", nombre="Técnico en camino", evento="folio.estado", subtipo="en_camino",
        whatsapp="{{3}} va en camino a {{2}} por el folio {{1}}.",
        sms="ACMA: {{3}} va en camino a {{2}} (folio {{1}}). {enlace}",
        variables=("folio", "sucursal", "tecnico"), botones=VER_FOLIO,
        ejemplo={"folio": "F-2026-000123", "sucursal": "Sucursal Centro", "tecnico": "Tadeo Tecnico"}),
    Plantilla(
        clave="folio_cerrado", nombre="Folio cerrado", evento="folio.estado", subtipo="cerrado",
        whatsapp="El folio {{1}} de {{2}} se cerró. Puedes revisar el reporte de atención en ACMA.",
        sms="ACMA: folio {{1}} cerrado en {{2}}. Reporte: {enlace}",
        variables=("folio", "sucursal"), botones=VER_FOLIO,
        ejemplo={"folio": "F-2026-000123", "sucursal": "Sucursal Centro"}),
    Plantilla(
        clave="folio_rechazado", nombre="Folio rechazado", evento="folio.estado", subtipo="rechazado",
        whatsapp="El folio {{1}} de {{2}} fue rechazado. Razón: {{3}}.",
        sms="ACMA: folio {{1}} rechazado en {{2}} ({{3}}). {enlace}",
        variables=("folio", "sucursal", "razon"), botones=VER_FOLIO, critica=True,
        ejemplo={"folio": "F-2026-000123", "sucursal": "Sucursal Centro", "razon": "fuera de cobertura"}),
    Plantilla(
        clave="folio_en_espera", nombre="Folio en espera de confirmación", evento="folio.espera",
        whatsapp="El folio {{1}} de {{2}} está en espera de confirmación.",
        sms="ACMA: folio {{1}} en espera en {{2}}. {enlace}",
        variables=("folio", "sucursal"), botones=VER_FOLIO,
        ejemplo={"folio": "F-2026-000123", "sucursal": "Sucursal Centro"}),

    # ------------------------------------------------------------------ aprobaciones (§6.8.3)
    Plantilla(
        clave="aprobacion_pendiente", nombre="Folio pendiente de tu autorización", evento="aprobacion.pendiente",
        whatsapp="Tienes el folio {{1}} de {{2}} esperando tu autorización (nivel {{3}}). Para autorizar o "
                 "rechazar, abre ACMA: por seguridad la decisión no se toma desde este mensaje.",
        sms="ACMA: folio {{1}} de {{2}} espera tu autorizacion. Abre {enlace}",
        variables=("folio", "sucursal", "nivel"), critica=True,
        botones=(Boton("url", "Abrir aprobación", "/folios/{folio_id}"),
                 Boton("respuesta_rapida", "Aprobar"), Boton("respuesta_rapida", "Rechazar")),
        ejemplo={"folio": "F-2026-000123", "sucursal": "Sucursal Centro", "nivel": "1"}),
    Plantilla(
        clave="aprobacion_bloqueada", nombre="Aprobación bloqueada por tiempo límite",
        evento="aprobacion.bloqueada",
        whatsapp="Se venció el tiempo para autorizar el folio {{1}} de {{2}} y quedó bloqueado. Entra a ACMA para "
                 "resolverlo.",
        sms="ACMA: se vencio el plazo para autorizar el folio {{1}} ({{2}}). {enlace}",
        variables=("folio", "sucursal"), botones=VER_FOLIO, critica=True,
        ejemplo={"folio": "F-2026-000123", "sucursal": "Sucursal Centro"}),

    # ------------------------------------------------------------------ minuta (§7.5)
    Plantilla(
        clave="minuta_disponible", nombre="Minuta del día", evento="minuta.enviada",
        whatsapp="Minuta del {{1}}{{2}}.\nLo más crítico de hoy: {{3}}\nEl PDF completo está en el botón de abajo.",
        sms="ACMA: minuta del {{1}} lista. Lo critico: {{3}}. PDF: {enlace}",
        variables=("fecha", "ambito", "resumen"), botones=VER_MINUTA,
        ejemplo={"fecha": "08/11/2026", "ambito": " de Sucursal Centro",
                 "resumen": "2 hallazgos de urgencia alta · 1 preventivo con retraso"}),
    Plantilla(
        clave="minuta_pendiente_validacion", nombre="Minuta pendiente de validación",
        evento="minuta.pendiente_validacion",
        whatsapp="La minuta del {{1}}{{2}} está lista para que la revises antes de enviarla al cliente.",
        sms="ACMA: minuta del {{1}} lista para validar. {enlace}",
        variables=("fecha", "ambito"), botones=VER_MINUTA,
        ejemplo={"fecha": "08/11/2026", "ambito": " de Sucursal Centro"}),

    # ------------------------------------------------------------------ seguimiento (§7.4)
    Plantilla(
        clave="cotizacion_enviada", nombre="Cotización enviada al cliente", evento="cotizacion.enviada",
        whatsapp="Se envió la cotización del folio {{1}} de {{2}} para tu revisión.",
        sms="ACMA: cotizacion del folio {{1}} ({{2}}) enviada. {enlace}",
        variables=("folio", "sucursal"), botones=VER_FOLIO,
        ejemplo={"folio": "F-2026-000123", "sucursal": "Sucursal Centro"}),
    Plantilla(
        clave="cotizacion_por_vencer", nombre="Cotización por vencer", evento="alerta",
        subtipo="COTIZACION_SIN_RESPUESTA",
        whatsapp="La cotización del folio {{1}} de {{2}} lleva {{3}} día(s) sin respuesta y está por vencer.",
        sms="ACMA: cotizacion del folio {{1}} lleva {{3}} dia(s) sin respuesta. {enlace}",
        variables=("folio", "sucursal", "dias"), botones=VER_FOLIO,
        ejemplo={"folio": "F-2026-000123", "sucursal": "Sucursal Centro", "dias": "7"}),
    Plantilla(
        clave="preventivo_por_reprogramar", nombre="Preventivo por reprogramar",
        evento="seguimiento.cambio_estado", subtipo="reprogramacion",
        whatsapp="El folio {{1}} de {{2}} necesita reprogramarse. Su estado ahora es «{{3}}».",
        sms="ACMA: folio {{1}} de {{2}} por reprogramar ({{3}}). {enlace}",
        variables=("folio", "sucursal", "estado"), botones=VER_FOLIO,
        ejemplo={"folio": "F-2026-000123", "sucursal": "Sucursal Centro", "estado": "pendiente de fecha"}),
    Plantilla(
        clave="trabajo_especial_por_validar", nombre="Trabajo especial por validar",
        evento="trabajo_especial.enviado",
        whatsapp="El trabajo especial {{1}} de {{2}} está esperando tu validación en ACMA.",
        sms="ACMA: trabajo especial {{1}} de {{2}} por validar. {enlace}",
        variables=("consecutivo", "sucursal"),
        botones=(Boton("url", "Abrir trabajo especial", "/trabajos-especiales"),),
        ejemplo={"consecutivo": "TE-2026-0007", "sucursal": "Sucursal Centro"}),

    # ------------------------------------------------------------------ alertas (§6.9.6)
    Plantilla(
        clave="sla_incumplido", nombre="SLA incumplido", evento="alerta", subtipo="SLA_INCUMPLIDO",
        whatsapp="Se incumplió el SLA del folio {{1}} de {{2}}. Revisa el folio en ACMA.",
        sms="ACMA: SLA incumplido en el folio {{1}} ({{2}}). {enlace}",
        variables=("folio", "sucursal"), botones=VER_FOLIO, critica=True,
        ejemplo={"folio": "F-2026-000123", "sucursal": "Sucursal Centro"}),
    Plantilla(
        clave="sla_en_riesgo", nombre="SLA en riesgo", evento="alerta", subtipo="SLA_RESPUESTA_EN_RIESGO",
        whatsapp="El folio {{1}} de {{2}} está por incumplir su SLA de respuesta.",
        sms="ACMA: folio {{1}} ({{2}}) por incumplir el SLA. {enlace}",
        variables=("folio", "sucursal"), botones=VER_FOLIO, critica=True,
        ejemplo={"folio": "F-2026-000123", "sucursal": "Sucursal Centro"}),
    Plantilla(
        clave="certificacion_por_vencer", nombre="Certificación por vencer", evento="alerta",
        subtipo="CERTIFICACION_VENCIDA",
        whatsapp="La certificación «{{2}}» de {{1}} vence en {{3}} día(s).",
        sms="ACMA: la certificacion {{2}} de {{1}} vence en {{3}} dia(s). {enlace}",
        variables=("tecnico", "curso", "dias"),
        botones=(Boton("url", "Ver expediente", "/capacitacion"),),
        ejemplo={"tecnico": "Teresa Tecnica", "curso": "Sistemas HVAC", "dias": "7"}),
    Plantilla(
        clave="alerta_generica", nombre="Alerta del sistema (genérica)", evento="alerta",
        whatsapp="Alerta de ACMA: {{1}}. {{2}}",
        sms="ACMA: {{1}}. {{2}} {enlace}",
        variables=("alerta", "detalle"),
        botones=(Boton("url", "Abrir ACMA", "/alertas"),),
        ejemplo={"alerta": "Stock minimo", "detalle": "3 articulos bajo el minimo"}),

    # ------------------------------------------------------------------ servicio
    Plantilla(
        clave="codigo_verificacion", nombre="Código de verificación del teléfono", evento="telefono.verificacion",
        categoria="authentication", critica=True,
        whatsapp="Tu código para verificar este número en ACMA es {{1}}. Vence en {{2}} minutos. Si no lo pediste, "
                 "ignora este mensaje.",
        sms="ACMA: tu codigo de verificacion es {{1}} (vence en {{2}} min).",
        variables=("codigo", "minutos"), ejemplo={"codigo": "482913", "minutos": "10"}),
    Plantilla(
        clave="notificacion_generica", nombre="Aviso de ACMA (genérico)", evento="*",
        whatsapp="{{1}} {{2}}",
        sms="ACMA: {{1}} {enlace}",
        variables=("asunto", "detalle"),
        botones=(Boton("url", "Abrir ACMA", "/"),),
        ejemplo={"asunto": "Aviso de ACMA", "detalle": "Entra a ACMA para ver el detalle."}),
)

POR_CLAVE: dict[str, Plantilla] = {p.clave: p for p in CATALOGO}
# Eventos cuyos mensajes ignoran el horario de silencio (§6.1: críticos).
CLAVES_CRITICAS = {p.clave for p in CATALOGO if p.critica}


def clave_de_evento(evento: str, datos: dict[str, Any] | None = None) -> str:
    """Plantilla que le toca a un evento. El subtipo sale del estado del folio o de la clave de la alerta."""
    datos = datos or {}
    subtipo = str(datos.get("estado") or datos.get("alerta") or datos.get("clave_alerta") or
                  datos.get("modulo") or "")
    for p in CATALOGO:
        if p.evento == evento and p.subtipo and p.subtipo == subtipo:
            return p.clave
    for p in CATALOGO:
        if p.evento == evento and not p.subtipo:
            return p.clave
    if evento == "alerta":
        return "alerta_generica"
    return "notificacion_generica"


# ----------------------------------------------------------------- validación

def datos_sensibles(p: Plantilla) -> list[str]:
    """Palabras prohibidas (§6.9.5) encontradas en el cuerpo o en los nombres de las variables.

    Se buscan como palabra completa: «iva» o «cuenta» aparecen dentro de palabras inocentes («activa», «cuentan»).
    """
    import re
    import unicodedata

    crudo = f"{p.whatsapp} {p.sms} {' '.join(p.variables)}".lower()
    texto = "".join(c for c in unicodedata.normalize("NFD", crudo) if unicodedata.category(c) != "Mn")
    return [w for w in CAMPOS_PROHIBIDOS if re.search(rf"\b{w}s?\b", texto)]


# ----------------------------------------------------------------- siembra

async def sembrar_plantillas(db: AsyncSession, prestador_id=None) -> int:
    """Crea o actualiza las plantillas base (prestador_id NULL) desde el catálogo. Idempotente.

    En modo `stub` nacen `aprobada`: no hay nada que someter a Meta y así el canal funciona en desarrollo. Con una
    cuenta real, el Admin prestador clona la plantilla para su prestador y la somete (queda `enviada`).
    """
    from models.mensajeria import CanalMensajeria, EstadoAprobacionPlantilla, MensajeriaPlantilla
    from services.mensajeria.proveedores import modo_de_canal

    creadas = 0
    for p in CATALOGO:
        for canal, cuerpo in ((CanalMensajeria.whatsapp, p.whatsapp), (CanalMensajeria.sms, p.sms)):
            if not cuerpo:
                continue
            fila = (await db.execute(select(MensajeriaPlantilla).where(
                MensajeriaPlantilla.prestador_id.is_(None) if prestador_id is None
                else MensajeriaPlantilla.prestador_id == prestador_id,
                MensajeriaPlantilla.clave == p.clave, MensajeriaPlantilla.canal == canal))).scalar_one_or_none()
            aprobada = (EstadoAprobacionPlantilla.aprobada if modo_de_canal(canal.value) == "stub"
                        else EstadoAprobacionPlantilla.borrador)
            if fila is None:
                fila = MensajeriaPlantilla(prestador_id=prestador_id, clave=p.clave, canal=canal, cuerpo=cuerpo,
                                           estado_aprobacion=aprobada)
                db.add(fila)
                creadas += 1
            fila.cuerpo = cuerpo
            fila.categoria = p.categoria
            fila.nombre_proveedor = f"acma_{p.clave}"
            fila.botones_json = [{"tipo": b.tipo, "texto": b.texto, "ruta": b.ruta} for b in p.botones]
            fila.variables_json = list(p.variables)
            fila.ejemplo_json = dict(p.ejemplo)
            fila.activa = True
    await db.flush()
    return creadas
