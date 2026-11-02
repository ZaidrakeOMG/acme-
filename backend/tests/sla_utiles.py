"""Ayudas compartidas por las pruebas de P10 (contador de SLA, penalizaciones, alertas, BI y reportes)."""
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from core.db import nueva_sesion
from core.rls import CONTEXTO_SISTEMA
from tests.folios_utiles import AE, AP, AUN, DES, MC, OP, SUPO, TEC
from tests.inventario_utiles import cerrar_folio, folio_en_ejecucion

_cache: dict = {}


async def contrato_demo(cliente, auth, email=AP) -> dict:
    """El contrato que hoy aplica a los folios del seed: el mismo criterio que `folios_sla.contrato_vigente()`.

    No se cachea porque las pruebas cambian su modalidad y sus SLA, y otras pruebas crean contratos de otros períodos.
    """
    from datetime import date

    hoy = date.today().isoformat()
    lista = (await cliente.get("/api/contratos", headers=await auth(email))).json()
    vigentes = [c for c in lista if c["estado"] == "activo" and c["fecha_inicio"] <= hoy <= c["fecha_fin"]]
    assert vigentes, "el seed debe dejar un contrato vigente hoy"
    return max(vigentes, key=lambda c: (c["fecha_inicio"], c["fecha_fin"], c["created_at"]))


async def sla_de(cliente, auth, folio_id, email=MC) -> dict:
    r = await cliente.get(f"/api/sla/folios/{folio_id}", headers=await auth(email))
    assert r.status_code == 200, r.text
    return r.json()


async def registrar_exclusion(cliente, auth, folio_id, *, causa="cliente_sin_acceso", horas=4, desde_horas=1,
                              email=MC, esperado=201) -> dict:
    ahora = datetime.now(UTC)
    cuerpo = {"causa": causa,
              "descripcion": "El cliente no dio acceso al cuarto de máquinas durante el turno de la mañana.",
              "timestamp_inicio": (ahora - timedelta(hours=desde_horas + horas)).isoformat(),
              "timestamp_fin": (ahora - timedelta(hours=desde_horas)).isoformat()}
    r = await cliente.post(f"/api/sla/folios/{folio_id}/exclusiones", headers=await auth(email), json=cuerpo)
    assert r.status_code == esperado, r.text
    return r.json()


async def decidir_exclusion(cliente, auth, exclusion_id, *, aprobada=True, razon="", email=AE, esperado=200) -> dict:
    r = await cliente.post(f"/api/sla/exclusiones/{exclusion_id}/decidir", headers=await auth(email),
                           json={"aprobada": aprobada, "razon": razon})
    assert r.status_code == esperado, r.text
    return r.json()


async def folio_cerrado(cliente, auth, datos, *, atras_horas: int | None = None, tecnico=TEC) -> dict:
    """Folio que llega a `cerrado`; con `atras_horas` se envejece el inicio del contador para forzar el incumplimiento."""
    f = await folio_en_ejecucion(cliente, auth, datos, tecnico)
    if atras_horas:
        await envejecer_contador(f["id"], atras_horas)
    await cerrar_folio(cliente, auth, datos, f, tecnico)
    return f


async def envejecer_contador(folio_id, horas: int) -> None:
    """Mueve `tiempo_inicio` del contador hacia atrás (equivale a un folio que lleva horas abierto)."""
    from models.folios import FolioSLA

    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        await db.execute(update(FolioSLA).where(FolioSLA.folio_id == folio_id)
                         .values(tiempo_inicio=datetime.now(UTC) - timedelta(hours=horas)))
        await db.commit()


async def apretar_limite(folio_id, limite_min: int = 30, respuesta_min: int = 10) -> None:
    """Deja el límite del SLA por debajo del tiempo real para provocar el incumplimiento."""
    from models.folios import FolioSLA

    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        await db.execute(update(FolioSLA).where(FolioSLA.folio_id == folio_id)
                         .values(limite_sla_min=limite_min, limite_respuesta_min=respuesta_min))
        await db.commit()


async def fila_sla(folio_id) -> dict:
    from models.folios import FolioSLA

    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        f = (await db.execute(select(FolioSLA).where(FolioSLA.folio_id == folio_id))).scalar_one()
        return {c.key: getattr(f, c.key) for c in f.__table__.columns}


async def recalcular(folio_id) -> dict:
    """Vuelve a correr el contador con el servicio (como lo hace la aprobación tardía de una exclusión)."""
    from models.folios import Folio
    from services import sla_service

    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        folio = await db.get(Folio, folio_id)
        f = await sla_service.recalcular(db, folio)
        salida = {"cumplimiento": f.cumplimiento, "tiempo_efectivo_min": f.tiempo_efectivo_min,
                  "tiempo_exclusion_min": f.tiempo_exclusion_min, "penalizacion": str(f.penalizacion_calculada)}
        await db.commit()
        return salida


async def poner_sla_contrato(cliente, auth, contrato_id, *, tipo="porcentaje", valor="10", email=AP) -> dict:
    """Reescribe los 5 SLA del contrato con la penalización indicada."""
    niveles = ["muy_baja", "baja", "media", "alta", "critica"]
    horas = {"muy_baja": (72, 720), "baja": (24, 168), "media": (8, 72), "alta": (4, 24), "critica": (2, 8)}
    slas = [{"nivel_severidad": n, "tiempo_respuesta_horas": horas[n][0], "tiempo_resolucion_horas": horas[n][1],
             "penalizacion_tipo": tipo, "penalizacion_valor": valor} for n in niveles]
    r = await cliente.patch(f"/api/contratos/{contrato_id}", headers=await auth(email), json={"slas": slas})
    assert r.status_code == 200, r.text
    return r.json()


async def tablero(cliente, auth, email, **params) -> dict:
    r = await cliente.get("/api/bi/tablero", headers=await auth(email), params=params)
    assert r.status_code == 200, r.text
    return r.json()


async def indicador(cliente, auth, email, nombre, esperado=200, **params) -> dict:
    r = await cliente.get(f"/api/bi/indicador/{nombre}", headers=await auth(email), params=params)
    assert r.status_code == esperado, r.text
    return r.json()


async def panel_alertas(cliente, auth, email, **params) -> list[dict]:
    r = await cliente.get("/api/alertas/panel", headers=await auth(email), params=params)
    assert r.status_code == 200, r.text
    return r.json()


async def correr_evaluadores() -> dict:
    from workers.tareas import evaluar_alertas_async

    return await evaluar_alertas_async()
