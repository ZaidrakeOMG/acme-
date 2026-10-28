"""Ayudas compartidas por las pruebas de P07 (minuta, notificaciones, módulos de seguimiento y clasificación)."""
from datetime import UTC, date, datetime

from sqlalchemy import delete, select, update

from core.db import nueva_sesion
from core.rls import CONTEXTO_SISTEMA
from tests.folios_utiles import AE, AUN, DES, OP, autorizar_sin_flujo


async def limpiar_minutas_hoy(tenant_id) -> None:
    """Las minutas de hoy del tenant demo las crea el seed (pendientes de validación); las pruebas las regeneran."""
    from models.minutas import Minuta, MinutaDestinatario, MinutaRespuesta, MinutaSeccion

    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        ids = list((await db.execute(select(Minuta.id).where(Minuta.tenant_id == tenant_id, Minuta.fecha == date.today()))).scalars())
        if ids:
            await db.execute(delete(MinutaRespuesta).where(MinutaRespuesta.minuta_id.in_(ids)))
            await db.execute(delete(MinutaDestinatario).where(MinutaDestinatario.minuta_id.in_(ids)))
            await db.execute(delete(MinutaSeccion).where(MinutaSeccion.minuta_id.in_(ids)))
            await db.execute(delete(Minuta).where(Minuta.id.in_(ids)))
        await db.commit()


async def hallazgo(cliente, auth, folio_id, descripcion="Hallazgo de prueba en la visita", urgencia="media", email=DES) -> dict:
    r = await cliente.post("/api/hallazgos", headers=await auth(email), json={"folio_id": folio_id, "descripcion": descripcion, "nivel_urgencia": urgencia})
    assert r.status_code == 201, r.text
    return r.json()


async def generar_minuta(cliente, auth, datos, fecha: date | None = None, email=DES, forzar=True) -> list[dict]:
    r = await cliente.post("/api/minutas/generar", headers=await auth(email), params={"tenant_id": str(datos["tenant"]), "fecha": (fecha or date.today()).isoformat(), "forzar": forzar})
    assert r.status_code == 200, r.text
    return r.json()


async def configurar_minuta(cliente, auth, datos, **cambios) -> dict:
    r = await cliente.put("/api/minutas/configuracion", headers=await auth("admin.prestador@acma.dev"), params={"tenant_id": str(datos["tenant"])}, json=cambios)
    assert r.status_code == 200, r.text
    return r.json()


async def minuta_detalle(cliente, auth, minuta_id, email=DES) -> dict:
    r = await cliente.get(f"/api/minutas/{minuta_id}", headers=await auth(email))
    assert r.status_code == 200, r.text
    return r.json()


async def responder(cliente, auth, minuta_id, hallazgo_id, opcion, email=AUN, esperado=201, **extra) -> dict:
    r = await cliente.post(f"/api/minutas/{minuta_id}/hallazgos/{hallazgo_id}/responder", headers=await auth(email), json={"opcion": opcion, **extra})
    assert r.status_code == esperado, r.text
    return r.json()


async def folio_con_hallazgo(cliente, auth, datos, descripcion="Hallazgo de prueba", urgencia="media") -> tuple[dict, dict]:
    f = await autorizar_sin_flujo(cliente, auth, datos, OP)
    return f, await hallazgo(cliente, auth, f["id"], descripcion, urgencia)


async def crear_registro(cliente, auth, modulo, datos, email=AUN, **extra) -> dict:
    cuerpo = {"un_id": str(datos["unidades"][0]), "descripcion": f"Registro de prueba en {modulo}", **extra}
    r = await cliente.post(f"/api/seguimiento/{modulo}", headers=await auth(email), json=cuerpo)
    assert r.status_code == 201, r.text
    return r.json()


async def cambiar_estado(cliente, auth, modulo, registro_id, estado, email=AUN, esperado=200, **extra) -> dict:
    r = await cliente.post(f"/api/seguimiento/{modulo}/{registro_id}/estado", headers=await auth(email), json={"estado": estado, **extra})
    assert r.status_code == esperado, f"{modulo} → {estado}: {r.status_code} {r.text}"
    return r.json()


async def detalle_registro(cliente, auth, modulo, registro_id, email=AUN) -> dict:
    r = await cliente.get(f"/api/seguimiento/{modulo}/{registro_id}", headers=await auth(email))
    assert r.status_code == 200, r.text
    return r.json()


async def retroceder(modelo, registro_id, **valores) -> None:
    """Mueve fechas hacia el pasado con la sesión de sistema (simula el paso del tiempo)."""
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        await db.execute(update(modelo).where(modelo.id == registro_id).values(**valores))
        await db.commit()


async def alertas_disparadas(clave: str, entidad_id=None) -> list:
    from models.alertas import AlertaHistorial

    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        consulta = select(AlertaHistorial).where(AlertaHistorial.clave_alerta == clave)
        if entidad_id is not None:
            consulta = consulta.where(AlertaHistorial.entidad_id == entidad_id)
        return list((await db.execute(consulta)).scalars())


async def bandeja(cliente, auth, email, solo_no_leidas=False) -> list[dict]:
    r = await cliente.get("/api/notificaciones", headers=await auth(email), params={"solo_no_leidas": solo_no_leidas, "limite": 100})
    assert r.status_code == 200, r.text
    return r.json()


def ahora() -> datetime:
    return datetime.now(UTC)


__all__ = ["AE", "AUN", "DES", "OP"]
