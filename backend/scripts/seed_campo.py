"""Datos demo de P05: formulario de encuesta publicado y asignado, mensajes en los chats de los folios demo (incluido el
cerrado, cuyos mensajes son inmutables) y una suscripción push de prueba. Idempotente. Los chats en sí los crea el
gancho `folio.creado` al sembrar los folios (P04)."""
import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from core.rls import CONTEXTO_SISTEMA
from models.base import Rol
from models.chat import CanalChat, Chat, ChatMensaje, SuscripcionPush, TipoMensaje
from models.folios import EstadoFolio, Folio
from models.formularios import Formulario, FormularioAsignacion
from models.organizaciones import Prestador, Tenant
from models.usuarios import Usuario
from services import chat_service, folio_cierre_service, push_service  # noqa: F401 — registran suscriptores

ENCUESTA_SATISFACCION: dict[str, Any] = {"secciones": [
    {"clave": "encuesta", "titulo": "Encuesta de satisfacción", "campos": [
        {"clave": "calificacion", "tipo": "encuesta_satisfaccion", "etiqueta": "¿Qué tan probable es que recomiendes el servicio? (0–10)", "obligatorio": True,
         "config": {"modalidad": "numerica", "escala_max": 10, "etiqueta_min": "Nada probable", "etiqueta_max": "Muy probable", "umbral_bajo": 6}},
        {"clave": "comentario", "tipo": "texto_amplio", "etiqueta": "Cuéntanos qué pasó", "obligatorio": True,
         "config": {"lineas_visibles": 3, "longitud_min": 5, "longitud_max": 1000},
         "condiciones": [{"campo_origen": "calificacion", "operador": "en_rango", "valor": [0, 6], "accion": "mostrar"}]},
        {"clave": "sugerencia", "tipo": "texto_amplio", "etiqueta": "¿Algo que podamos mejorar?", "obligatorio": False,
         "config": {"lineas_visibles": 2, "longitud_min": 0, "longitud_max": 1000}},
    ]},
]}


async def sembrar_campo(db) -> bool:
    prestador = (await db.execute(select(Prestador).where(Prestador.rfc == "PDE200101AB1"))).scalar_one_or_none()
    tenant = (await db.execute(select(Tenant).where(Tenant.rfc == "CDE200101XY2"))).scalar_one_or_none()
    if prestador is None or tenant is None:
        return False
    from scripts.seed_dev import _formulario

    creado = False
    usuarios = {u.email: u for u in (await db.execute(select(Usuario))).scalars()}
    if not (await db.execute(select(Formulario.id).where(Formulario.nombre == "Encuesta de satisfacción (operador)"))).first():
        encuesta = await _formulario(db, prestador_id=prestador.id, tenant_id=None, nombre="Encuesta de satisfacción (operador)", tipo="encuesta",
                                     roles=["operador", "admin_un"], esquema=ENCUESTA_SATISFACCION,
                                     descripcion="NPS 0–10 al cierre del folio; con calificación baja el comentario es obligatorio",
                                     publicado_por=usuarios["admin.prestador@acma.dev"].id)
        db.add(FormularioAsignacion(formulario_id=encuesta.id, prestador_id=prestador.id, tenant_id=None, prioridad=1))
        await db.flush()
        creado = True

    folios = {f.numero_folio: f for f in (await db.execute(select(Folio).where(Folio.tenant_id == tenant.id))).scalars()}
    # Chats para folios sembrados antes de P05 (el gancho folio.creado los crea en los nuevos).
    from services.folio_estados import ACTOR_SISTEMA
    con_chat = set((await db.execute(select(Chat.folio_id))).scalars())
    for f in folios.values():
        if f.id not in con_chat:
            nuevos = await chat_service.crear_chats(db, f, ACTOR_SISTEMA)
            if f.tecnico_id:
                tecnico = await db.get(Usuario, f.tecnico_id)
                if tecnico:
                    await chat_service._agregar(db, nuevos[CanalChat.campo], tecnico)
            creado = True
    await db.flush()
    chats = {(c.folio_id, c.canal): c for c in (await db.execute(select(Chat))).scalars()}
    if (await db.execute(select(ChatMensaje.id).where(ChatMensaje.usuario_id.is_not(None)))).first():
        return creado

    def mensaje(chat: Chat, autor: Usuario | None, texto: str, minutos: int, tipo=TipoMensaje.texto, retraso: int = 0, **datos) -> None:
        base = datetime(2026, 10, 26, 16, 0, tzinfo=UTC) + timedelta(minutes=minutos)
        db.add(ChatMensaje(chat_id=chat.id, tenant_id=chat.tenant_id, prestador_id=chat.prestador_id, usuario_id=autor.id if autor else None,
                           contenido_texto=texto, tipo=tipo, timestamp_servidor=base + timedelta(minutes=retraso),
                           timestamp_dispositivo=base if retraso else None, datos_json=datos,
                           leido_por_json={str(autor.id): base.isoformat()} if autor else {}))

    op, tec1, tec2, desp, aun = (usuarios[e] for e in ("operador@acma.dev", "tecnico1@acma.dev", "tecnico2@acma.dev", "despachador@acma.dev", "admin.un@acma.dev"))
    # Folio en ejecución (CD-000015): conversación de campo con un mensaje enviado con retraso (doble timestamp).
    f15 = folios.get("CD-000015")
    if f15 and (f15.id, CanalChat.campo) in chats:
        c = chats[(f15.id, CanalChat.campo)]
        mensaje(c, tec2, "Voy llegando en 10 minutos, ¿el equipo sigue sin encender?", 5)
        mensaje(c, aun, "Sí, lo apagamos del interruptor por seguridad.", 8)
        mensaje(c, tec2, "Ya estoy en sitio. Necesito acceso al cuarto de máquinas.", 40, retraso=25)
    # Folio cerrado (CD-000001): mensajes históricos inmutables en los tres canales.
    f1 = folios.get("CD-000001")
    if f1 and f1.estado == EstadoFolio.cerrado:
        if (f1.id, CanalChat.campo) in chats:
            c = chats[(f1.id, CanalChat.campo)]
            mensaje(c, tec1, "Llegué a la sucursal, ¿me reciben en el andén?", -9000)
            mensaje(c, op, "Claro, te abro ahora.", -8995)
            mensaje(c, tec1, "Listo: se recargó refrigerante y se selló la fuga. ¿Firmamos?", -8900)
        if (f1.id, CanalChat.operativo) in chats:
            mensaje(chats[(f1.id, CanalChat.operativo)], desp, "Técnico asignado para hoy a primera hora.", -9100)
        if (f1.id, CanalChat.interno) in chats:
            mensaje(chats[(f1.id, CanalChat.interno)], desp, "Pendiente revisar costo del refrigerante con el proveedor.", -8800)
    # Folio asignado (CD-000014): mensaje operativo del despachador.
    f14 = folios.get("CD-000014")
    if f14 and (f14.id, CanalChat.operativo) in chats:
        mensaje(chats[(f14.id, CanalChat.operativo)], desp, "Tania pasa mañana entre 9 y 11.", 60)
    await db.flush()

    if not (await db.execute(select(SuscripcionPush.id).where(SuscripcionPush.usuario_id == op.id))).first():
        db.add(SuscripcionPush(usuario_id=op.id, tenant_id=tenant.id, prestador_id=None, dispositivo_id="demo-operador-android",
                               endpoint="https://push.example.invalid/acma/demo-operador", claves_json={"p256dh": "demo", "auth": "demo"},
                               user_agent="ACMA demo (Android)"))
    await db.flush()
    return True


async def main() -> None:
    from core.db import nueva_sesion

    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        creado = await sembrar_campo(db)
        await db.commit()
    print("Datos de campo (P05) creados." if creado else "Ya había datos de campo; no se modificó nada.")


if __name__ == "__main__":
    asyncio.run(main())
