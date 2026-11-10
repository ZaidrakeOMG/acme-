"""Datos demo de F2-02: plantillas base, configuración del prestador y del cliente demo con WhatsApp y SMS activos,
teléfonos ficticios verificados con consentimiento para cuatro usuarios, preferencias que incluyen los canales
nuevos y 30 envíos de ejemplo con estados variados.

Los teléfonos son del rango de prueba (`+52155501…`): aunque alguien active un proveedor real con los datos demo,
no le llega el mensaje a nadie.

Idempotente: si ya existe la configuración del prestador demo, no hace nada.

Ejecutar desde backend/:  .venv/Scripts/python -m scripts.seed_mensajeria
"""
import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from core.rls import CONTEXTO_SISTEMA
from models.mensajeria import (
    CanalMensajeria, EstadoEnvioMensajeria, MensajeriaConfiguracion, MensajeriaEnvio, MensajeriaPlantilla,
    ProveedorMensajeria,
)
from models.minutas import NotificacionPreferencia
from models.organizaciones import Prestador, Tenant
from models.usuarios import Usuario
from services.mensajeria import telefonos
from services.mensajeria.plantillas import sembrar_plantillas

# (correo, teléfono de prueba, canales que el usuario pidió en sus preferencias)
TELEFONOS = [
    ("admin.empresa@acma.dev", "+521555010001", ["app", "push", "email", "whatsapp"]),
    ("admin.un@acma.dev", "+521555010002", ["app", "push", "email", "whatsapp"]),
    ("despachador@acma.dev", "+521555010003", ["app", "push", "whatsapp", "sms"]),
    ("tecnico1@acma.dev", "+521555010004", ["app", "push", "sms"]),
]
# Solo la minuta trae la preferencia ya puesta, y solo para quien la recibe: es lo que §7.5 pide ver funcionando.
# Los demás eventos se activan desde la pantalla de Notificaciones, usuario por usuario; ponerlos aquí llenaría de
# mensajes la base demo y cambiaría lo que afirman las pruebas de otros prompts.
EVENTOS_CON_MENSAJERIA = ["minuta.enviada"]
CON_PREFERENCIA_DE_MINUTA = {"admin.empresa@acma.dev", "admin.un@acma.dev"}

# (evento, plantilla, canal, estado, días de antigüedad)
EJEMPLOS = [
    ("folio.estado", "folio_asignado", "whatsapp", "leido", 0),
    ("folio.estado", "folio_en_camino", "whatsapp", "entregado", 0),
    ("aprobacion.pendiente", "aprobacion_pendiente", "whatsapp", "leido", 0),
    ("minuta.enviada", "minuta_disponible", "whatsapp", "entregado", 1),
    ("folio.estado", "folio_cerrado", "sms", "entregado", 1),
    ("alerta", "sla_en_riesgo", "whatsapp", "enviado", 1),
    ("folio.estado", "folio_creado", "whatsapp", "entregado", 2),
    ("cotizacion.enviada", "cotizacion_enviada", "whatsapp", "leido", 2),
    ("folio.estado", "folio_asignado", "sms", "fallido", 2),
    ("minuta.enviada", "minuta_disponible", "whatsapp", "leido", 3),
    ("alerta", "certificacion_por_vencer", "whatsapp", "entregado", 3),
    ("folio.estado", "folio_autorizado", "whatsapp", "entregado", 4),
    ("trabajo_especial.enviado", "trabajo_especial_por_validar", "whatsapp", "enviado", 4),
    ("folio.estado", "folio_en_camino", "sms", "entregado", 5),
    ("minuta.enviada", "minuta_disponible", "whatsapp", "entregado", 5),
    ("aprobacion.bloqueada", "aprobacion_bloqueada", "whatsapp", "leido", 6),
    ("folio.estado", "folio_rechazado", "whatsapp", "entregado", 6),
    ("alerta", "sla_incumplido", "whatsapp", "leido", 7),
    ("folio.estado", "folio_cerrado", "whatsapp", "entregado", 7),
    ("folio.estado", "folio_asignado", "whatsapp", "rechazado_por_proveedor", 8),
    ("minuta.enviada", "minuta_disponible", "whatsapp", "entregado", 8),
    ("alerta", "cotizacion_por_vencer", "whatsapp", "entregado", 9),
    ("folio.estado", "folio_creado", "sms", "entregado", 9),
    ("folio.estado", "folio_en_camino", "whatsapp", "leido", 10),
    ("seguimiento.cambio_estado", "preventivo_por_reprogramar", "whatsapp", "entregado", 10),
    ("minuta.enviada", "minuta_disponible", "whatsapp", "entregado", 11),
    ("folio.estado", "folio_cerrado", "whatsapp", "entregado", 11),
    ("telefono.verificacion", "codigo_verificacion", "sms", "entregado", 12),
    ("folio.estado", "folio_autorizado", "whatsapp", "entregado", 12),
    ("alerta", "alerta_generica", "whatsapp", "enviado", 13),
]

CUERPOS_DEMO = {
    "folio_creado": "Se levantó el folio F-2026-0001{n} en SUC-001 Sucursal Centro (media).",
    "folio_autorizado": "El folio F-2026-0001{n} de SUC-001 Sucursal Centro quedó autorizado y pasa a asignación.",
    "folio_asignado": "El folio F-2026-0001{n} de SUC-001 Sucursal Centro quedó asignado a Tomás Técnico.",
    "folio_en_camino": "Tomás Técnico va en camino a SUC-002 Sucursal Polanco por el folio F-2026-0001{n}.",
    "folio_cerrado": "El folio F-2026-0001{n} de SUC-001 Sucursal Centro se cerró.",
    "folio_rechazado": "El folio F-2026-0001{n} de SUC-003 Sucursal Coyoacán fue rechazado. Razón: fuera de cobertura.",
    "aprobacion_pendiente": "Tienes el folio F-2026-0001{n} de SUC-001 Sucursal Centro esperando tu autorización.",
    "aprobacion_bloqueada": "Se venció el tiempo para autorizar el folio F-2026-0001{n} y quedó bloqueado.",
    "minuta_disponible": "Minuta del día de SUC-001 Sucursal Centro. Lo más crítico de hoy: 2 hallazgo(s) de "
                         "urgencia alta · 1 preventivo con retraso.",
    "cotizacion_enviada": "Se envió la cotización del folio F-2026-0001{n} de SUC-002 Sucursal Polanco.",
    "cotizacion_por_vencer": "La cotización del folio F-2026-0001{n} lleva 7 día(s) sin respuesta.",
    "trabajo_especial_por_validar": "El trabajo especial TE-2026-000{n} de SUC-001 está esperando tu validación.",
    "preventivo_por_reprogramar": "El folio F-2026-0001{n} de SUC-003 necesita reprogramarse.",
    "sla_incumplido": "Se incumplió el SLA del folio F-2026-0001{n} de SUC-002 Sucursal Polanco.",
    "sla_en_riesgo": "El folio F-2026-0001{n} de SUC-001 está por incumplir su SLA de respuesta.",
    "certificacion_por_vencer": "La certificación «Sistemas HVAC» de Teresa Técnica vence en 7 día(s).",
    "alerta_generica": "Alerta de ACMA: stock mínimo. 3 artículo(s) bajo el mínimo.",
    "codigo_verificacion": "ACMA: tu codigo de verificacion es 482913 (vence en 10 min).",
}


async def sembrar_mensajeria(db) -> bool:
    prestador = (await db.execute(select(Prestador).where(Prestador.rfc == "PDE200101AB1"))).scalar_one_or_none()
    tenant = (await db.execute(select(Tenant).where(Tenant.rfc == "CDE200101XY2"))).scalar_one_or_none()
    if prestador is None or tenant is None:
        print("Sin prestador/tenant demo: corre primero scripts.seed_dev")
        return False
    if (await db.execute(select(MensajeriaConfiguracion).where(
            MensajeriaConfiguracion.prestador_id == prestador.id))).scalar_one_or_none():
        return False

    creadas = await sembrar_plantillas(db)
    print(f"Plantillas base sincronizadas ({creadas} nuevas)")

    # El prestador activa los dos canales; el cliente demo ajusta su propio horario de silencio y su tope.
    db.add(MensajeriaConfiguracion(
        prestador_id=prestador.id, tenant_id=None, whatsapp_activo=True, sms_activo=True,
        horario_silencio_json={"inicio": "22:00", "fin": "07:00", "zona": "America/Mexico_City"},
        tope_mensual_mensajes=1000, alerta_consumo_pct=80, remitente_whatsapp="demo-numero-whatsapp",
        remitente_sms="+520000000000", tarifa_whatsapp=Decimal("0.4000"), tarifa_sms=Decimal("0.6000")))
    db.add(MensajeriaConfiguracion(
        prestador_id=prestador.id, tenant_id=tenant.id, whatsapp_activo=True, sms_activo=True,
        horario_silencio_json={"inicio": "21:30", "fin": "06:30", "zona": "America/Mexico_City"},
        tope_mensual_mensajes=400, alerta_consumo_pct=75, remitente_whatsapp="demo-numero-whatsapp",
        remitente_sms="+520000000000", tarifa_whatsapp=Decimal("0.4000"), tarifa_sms=Decimal("0.6000")))
    await db.flush()

    ahora = datetime.now(UTC)
    usuarios: dict[str, Usuario] = {}
    for correo, numero, canales in TELEFONOS:
        usuario = (await db.execute(select(Usuario).where(Usuario.email == correo))).scalar_one_or_none()
        if usuario is None:
            continue
        telefonos.guardar(usuario, numero)
        usuario.telefono_verificado_at = ahora - timedelta(days=20)
        for canal in ("whatsapp", "sms"):
            if canal in canales:
                telefonos.fijar_consentimiento(usuario, canal, True)
        usuarios[correo] = usuario
        if correo not in CON_PREFERENCIA_DE_MINUTA:
            continue
        for evento in EVENTOS_CON_MENSAJERIA:
            fila = (await db.execute(select(NotificacionPreferencia).where(
                NotificacionPreferencia.usuario_id == usuario.id,
                NotificacionPreferencia.evento == evento))).scalar_one_or_none()
            if fila is None:
                fila = NotificacionPreferencia(usuario_id=usuario.id, tenant_id=usuario.tenant_id,
                                               prestador_id=usuario.prestador_id, evento=evento)
                db.add(fila)
            fila.canales_json = list(canales)
    await db.flush()
    print(f"Teléfonos verificados con consentimiento: {len(usuarios)}")

    plantillas = {(p.clave, p.canal): p for p in (await db.execute(select(MensajeriaPlantilla))).scalars()}
    correos = list(usuarios)
    for i, (evento, clave, canal_txt, estado_txt, dias) in enumerate(EJEMPLOS):
        if not correos:
            break
        usuario = usuarios[correos[i % len(correos)]]
        canal = CanalMensajeria(canal_txt)
        estado = EstadoEnvioMensajeria(estado_txt)
        cuando = ahora - timedelta(days=dias, minutes=17 * i % 600)
        cuerpo = CUERPOS_DEMO.get(clave, "Aviso de ACMA.").replace("{n}", f"{20 + i:02d}")
        plantilla = plantillas.get((clave, canal))
        envio = MensajeriaEnvio(
            id=uuid.uuid4(), prestador_id=prestador.id,
            tenant_id=tenant.id if usuario.tenant_id else None, usuario_id=usuario.id, evento=evento, canal=canal,
            proveedor=ProveedorMensajeria.stub,
            telefono_destino_hash=usuario.telefono_movil_hash, telefono_mascara=usuario.telefono_movil_mascara,
            plantilla_id=plantilla.id if plantilla else None, plantilla_clave=clave,
            cuerpo_renderizado=cuerpo, mensaje_id_proveedor=f"stub-demo-{i:04d}",
            estado=estado, segmentos_sms=1 if canal == CanalMensajeria.sms else 0,
            costo_estimado=(Decimal("0.4000") if canal == CanalMensajeria.whatsapp else Decimal("0.6000"))
            if estado in (EstadoEnvioMensajeria.enviado, EstadoEnvioMensajeria.entregado, EstadoEnvioMensajeria.leido)
            else Decimal("0"),
            moneda="MXN", intentos=1 if estado != EstadoEnvioMensajeria.fallido else 3,
            critico=clave in ("aprobacion_pendiente", "aprobacion_bloqueada", "sla_incumplido", "sla_en_riesgo",
                              "folio_rechazado", "codigo_verificacion"),
            codigo_enlace=f"demo{i:04d}", enlace_destino="/folios",
            codigo_error="" if estado not in (EstadoEnvioMensajeria.fallido,
                                              EstadoEnvioMensajeria.rechazado_por_proveedor) else "131026",
            detalle_error="" if estado not in (EstadoEnvioMensajeria.fallido,
                                               EstadoEnvioMensajeria.rechazado_por_proveedor)
            else "El destinatario no tiene WhatsApp o no acepta mensajes de este número",
            created_at=cuando, updated_at=cuando,
            enviado_at=cuando if estado != EstadoEnvioMensajeria.fallido else None,
            entregado_at=cuando + timedelta(seconds=40) if estado in (EstadoEnvioMensajeria.entregado,
                                                                      EstadoEnvioMensajeria.leido) else None,
            leido_at=cuando + timedelta(minutes=3) if estado == EstadoEnvioMensajeria.leido else None,
            proximo_intento_at=ahora + timedelta(minutes=4) if estado == EstadoEnvioMensajeria.fallido else None)
        db.add(envio)
    await db.flush()
    print(f"Envíos de ejemplo: {len(EJEMPLOS)}")
    return True


async def main() -> None:
    from core.db import nueva_sesion

    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        if await sembrar_mensajeria(db):
            await db.commit()
            print("Listo: datos demo de mensajería sembrados")
        else:
            print("La mensajería demo ya estaba sembrada")


if __name__ == "__main__":
    asyncio.run(main())
