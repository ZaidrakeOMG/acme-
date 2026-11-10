"""Ayudas compartidas por las pruebas de mensajería (F2-02)."""
import re

from sqlalchemy import select

from core.db import nueva_sesion
from core.rls import CONTEXTO_SISTEMA
from tests.folios_utiles import AP

# Usuarios con teléfono verificado y consentimiento en el seed demo (scripts/seed_mensajeria.py).
CON_WHATSAPP = "admin.empresa@acma.dev"
CON_AMBOS = "despachador@acma.dev"
CON_SMS = "tecnico1@acma.dev"
# Sin teléfono en el seed: las pruebas que dan de alta o de baja un número usan estos.
SIN_TELEFONO = "mesa.control@acma.dev"
SIN_TELEFONO_2 = "supervisor.prestador@acma.dev"

TELEFONO_PRUEBA = "+521555019001"
TELEFONO_PRUEBA_2 = "+521555019002"


async def configurar(cliente, auth, email=AP, **cambios) -> dict:
    r = await cliente.put("/api/mensajeria/configuracion", headers=await auth(email), json=cambios)
    assert r.status_code == 200, r.text
    return r.json()


async def configuracion(cliente, auth, email=AP) -> dict:
    r = await cliente.get("/api/mensajeria/configuracion", headers=await auth(email))
    assert r.status_code == 200, r.text
    return r.json()


async def envios(cliente, auth, email=AP, **filtros) -> list[dict]:
    r = await cliente.get("/api/mensajeria/envios", headers=await auth(email), params=filtros)
    assert r.status_code == 200, r.text
    return r.json()


async def plantillas(cliente, auth, email=AP, **filtros) -> list[dict]:
    r = await cliente.get("/api/mensajeria/plantillas", headers=await auth(email), params=filtros)
    assert r.status_code == 200, r.text
    return r.json()


async def plantilla(cliente, auth, clave: str, canal: str = "whatsapp", email=AP) -> dict:
    lista = await plantillas(cliente, auth, email, canal=canal)
    return next(p for p in lista if p["clave"] == clave)


async def mi_telefono(cliente, auth, email) -> dict:
    r = await cliente.get("/api/usuarios/me/telefono", headers=await auth(email))
    assert r.status_code == 200, r.text
    return r.json()


def codigo_del_stub() -> str:
    """El código de verificación que el proveedor simulado «envió» (en modo stub nada sale de la máquina)."""
    from services.mensajeria.stub import ENVIADOS

    for registro in reversed(ENVIADOS):
        if registro["plantilla"] == "codigo_verificacion":
            encontrado = re.search(r"\b(\d{6})\b", registro["cuerpo"])
            if encontrado:
                return encontrado.group(1)
    raise AssertionError("el stub no registró ningún código de verificación")


async def alta_y_verificacion(cliente, auth, email, numero=TELEFONO_PRUEBA, canal="sms", consentir=("sms",)) -> dict:
    """Alta del teléfono, código por el canal simulado, verificación y consentimientos."""
    h = await auth(email)
    r = await cliente.put("/api/usuarios/me/telefono", headers=h, json={"telefono": numero})
    assert r.status_code == 200, r.text
    assert r.json()["verificado"] is False
    r = await cliente.post(f"/api/usuarios/me/telefono/codigo?canal={canal}", headers=h)
    assert r.status_code == 200, r.text
    r = await cliente.post("/api/usuarios/me/telefono/verificar", headers=h, json={"codigo": codigo_del_stub()})
    assert r.status_code == 200, r.text
    for c in consentir:
        r = await cliente.put("/api/usuarios/me/consentimiento", headers=h, json={"canal": c, "acepta": True})
        assert r.status_code == 200, r.text
    return r.json()


async def quitar_telefono(cliente, auth, email) -> None:
    r = await cliente.delete("/api/usuarios/me/telefono", headers=await auth(email))
    assert r.status_code == 200, r.text


async def preferencia(cliente, auth, email, evento: str, canales: list[str]) -> dict:
    r = await cliente.put("/api/notificaciones/preferencias", headers=await auth(email),
                          json={"evento": evento, "canales": canales})
    assert r.status_code == 200, r.text
    return r.json()


async def notificaciones_de(email: str, evento: str) -> list:
    """Notificaciones del usuario para ese evento, directo de la base (incluye las omitidas y su motivo)."""
    from models.minutas import Notificacion
    from models.usuarios import Usuario

    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        uid = (await db.execute(select(Usuario.id).where(Usuario.email == email))).scalar_one()
        filas = (await db.execute(select(Notificacion).where(
            Notificacion.usuario_id == uid, Notificacion.evento == evento
        ).order_by(Notificacion.timestamp.desc()))).scalars().all()
        return [{"canal": n.canal.value, "estado": n.estado.value, "respuesta": n.proveedor_respuesta,
                 "datos": (n.cuerpo_json or {}).get("datos", {}), "timestamp": n.timestamp} for n in filas]


async def notificar_de_prueba(evento: str, email: str, datos: dict | None = None, *, asunto="Aviso de prueba",
                              url="/folios", canales: list[str] | None = ("whatsapp",)) -> list:
    """Dispara `notificar()` como lo haría un módulo, con el contexto del sistema.

    `canales` fuerza la lista (como hace la minuta) para no tocar las preferencias del usuario, que son datos
    compartidos por toda la sesión de pruebas. Las reglas de canal se evalúan igual.
    """
    from models.usuarios import Usuario
    from services import notificaciones_service

    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        usuario = (await db.execute(select(Usuario).where(Usuario.email == email))).scalar_one()
        creadas = await notificaciones_service.notificar(
            db, evento, [usuario.id], datos or {}, asunto=asunto, cuerpo="Detalle de la prueba", url=url,
            tenant_id=usuario.tenant_id, prestador_id=usuario.prestador_id or await _prestador_del_tenant(db, usuario),
            canales=list(canales) if canales else None, enviar_ahora=True)
        salida = [{"canal": n.canal.value, "estado": n.estado.value, "respuesta": n.proveedor_respuesta,
                   "id": n.id} for n in creadas]
        await db.commit()
        return salida


async def _prestador_del_tenant(db, usuario):
    from models.organizaciones import TenantPrestador

    return (await db.execute(select(TenantPrestador.prestador_id).where(
        TenantPrestador.tenant_id == usuario.tenant_id).limit(1))).scalar()


async def ultimo_envio(email: str | None = None, canal: str | None = None):
    from models.mensajeria import CanalMensajeria, MensajeriaEnvio
    from models.usuarios import Usuario

    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        consulta = select(MensajeriaEnvio).order_by(MensajeriaEnvio.created_at.desc(), MensajeriaEnvio.id)
        if email:
            uid = (await db.execute(select(Usuario.id).where(Usuario.email == email))).scalar_one()
            consulta = consulta.where(MensajeriaEnvio.usuario_id == uid)
        if canal:
            consulta = consulta.where(MensajeriaEnvio.canal == CanalMensajeria(canal))
        e = (await db.execute(consulta.limit(1))).scalar_one_or_none()
        if e is None:
            return None
        return {"id": e.id, "canal": e.canal.value, "estado": e.estado.value, "cuerpo": e.cuerpo_renderizado,
                "plantilla": e.plantilla_clave, "mascara": e.telefono_mascara, "hash": e.telefono_destino_hash,
                "codigo_enlace": e.codigo_enlace, "destino": e.enlace_destino, "mensaje_id": e.mensaje_id_proveedor,
                "costo": str(e.costo_estimado), "segmentos": e.segmentos_sms, "intentos": e.intentos,
                "critico": e.critico, "error": e.codigo_error, "evento": e.evento}


async def telefono_en_claro(email: str) -> str | None:
    """Solo para las pruebas: descifra el número para programar fallas del proveedor simulado por destinatario."""
    from models.usuarios import Usuario
    from services.mensajeria import telefonos

    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        usuario = (await db.execute(select(Usuario).where(Usuario.email == email))).scalar_one()
        return telefonos.en_claro(usuario)


async def columna_cifrada(email: str) -> str | None:
    """Lo que de verdad está guardado en `usuarios.telefono_movil_e164` (debe ser ilegible)."""
    from models.usuarios import Usuario

    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        return (await db.execute(select(Usuario.telefono_movil_e164).where(Usuario.email == email))).scalar()


def limpiar_stub() -> None:
    from services.mensajeria.proveedores import limpiar_cubetas
    from services.mensajeria.stub import limpiar

    limpiar()
    limpiar_cubetas()
