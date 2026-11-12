"""Utilidades de las pruebas de criticidad y riesgo (ISO 55000, §6.9.3). F2-05.

El historial de fallas se escribe directo con el contexto del sistema, como lo hace el seed: capturar y cerrar
cuarenta correctivos por la API tardaría minutos y lo que se prueba es la fórmula, no la captura (eso ya lo cubre
`test_folios_captura.py`).
"""
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from tests.folios_utiles import AE, nuevo_equipo

PREFIJO = "PR-"   # historial escrito por las pruebas


async def equipo_con_historia(cliente, auth, datos, *, fallas: int = 0, familia="Refrigeración", indice=0,
                              un_index=0, **extra) -> dict:
    """Equipo nuevo con `fallas` correctivos cerrados en los últimos doce meses y antigüedad suficiente para que la
    probabilidad salga de su propio historial (no estimada del tipo de equipo)."""
    equipo = await nuevo_equipo(cliente, auth, datos, familia=familia, indice=indice, un_index=un_index,
                               fecha_instalacion=str(date.today() - timedelta(days=900)), **extra)
    if fallas:
        await sembrar_fallas(equipo["id"], fallas)
    else:
        # Cero fallas en los ultimos doce meses, pero observado: un correctivo cerrado fuera de la ventana. Un
        # equipo sin ningun folio no tiene historia y su probabilidad se estimaria del tipo de equipo.
        await sembrar_fallas(equipo["id"], 1, desde_dias=400, hasta_dias=400)
    return equipo


async def sembrar_fallas(equipo_id, cuantos: int, *, desde_dias: int = 300, hasta_dias: int = 20) -> int:
    """Correctivos cerrados repartidos entre `desde_dias` y `hasta_dias` atrás."""
    from core.db import nueva_sesion
    from core.rls import CONTEXTO_SISTEMA
    from models.catalogos import Equipo, NivelSeveridadCatalogo, TipoFalla
    from models.folios import EstadoFolio, Folio, SeveridadOrigen, TipoFolio
    from models.usuarios import Usuario

    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        equipo = await db.get(Equipo, uuid.UUID(str(equipo_id)))
        capturo = (await db.execute(select(Usuario.id).where(Usuario.email == "operador@acma.dev"))).scalar_one()
        prestador_id = (await db.execute(select(TipoFalla.prestador_id).limit(1))).scalar_one()
        falla = (await db.execute(select(TipoFalla).where(TipoFalla.prestador_id == prestador_id)
                                  .limit(1))).scalar_one()
        severidad = (await db.execute(select(NivelSeveridadCatalogo)
                                      .where(NivelSeveridadCatalogo.prestador_id == prestador_id)
                                      .order_by(NivelSeveridadCatalogo.orden).limit(1))).scalar_one_or_none()
        paso = (desde_dias - hasta_dias) / max(1, cuantos - 1) if cuantos > 1 else 0
        for i in range(cuantos):
            capturado = datetime.now(UTC) - timedelta(days=desde_dias - int(paso * i))
            db.add(Folio(
                tenant_id=equipo.tenant_id, prestador_id=prestador_id, un_id=equipo.un_id, equipo_id=equipo.id,
                numero_folio=f"{PREFIJO}{uuid.uuid4().hex[:10].upper()}", tipo_folio=TipoFolio.correctivo,
                tipo_falla_id=falla.id, estado=EstadoFolio.cerrado,
                descripcion=f"Falla {i + 1} del historial de pruebas",
                severidad_id=severidad.id if severidad else None,
                severidad_origen=SeveridadOrigen.automatica_matriz, confirmacion_un=True,
                capturado_por=capturo, capturado_at=capturado,
                fecha_falla=capturado - timedelta(minutes=30),
                fecha_inicio_atencion=capturado + timedelta(hours=1),
                fecha_cierre=capturado + timedelta(hours=5)))
        await db.commit()
    return cuantos


async def evaluar(cliente, auth, equipo_id, operacional=3, seguridad=3, economico=3, imagen=3, email=AE,
                  esperado=200, **extra) -> dict:
    r = await cliente.post(f"/api/criticidad/equipos/{equipo_id}", headers=await auth(email),
                           json={"dimensiones": {"operacional": operacional, "seguridad": seguridad,
                                                 "economico": economico, "imagen": imagen}, **extra})
    assert r.status_code == esperado, r.text
    return r.json()


async def detalle(cliente, auth, equipo_id, email=AE) -> dict:
    r = await cliente.get(f"/api/criticidad/equipos/{equipo_id}", headers=await auth(email))
    assert r.status_code == 200, r.text
    return r.json()


async def configuracion(cliente, auth, email=AE, **params) -> dict:
    r = await cliente.get("/api/criticidad/configuracion", headers=await auth(email), params=params)
    assert r.status_code == 200, r.text
    return r.json()


async def poner_configuracion(cliente, auth, cambios: dict, email=AE, esperado=200) -> dict:
    r = await cliente.put("/api/criticidad/configuracion", headers=await auth(email), json=cambios)
    assert r.status_code == esperado, r.text
    return r.json()


async def restaurar_configuracion(cliente, auth) -> None:
    """Deja la configuración del tenant demo como la dejó el seed: los literales de §6.9.3."""
    from models.criticidad import (
        ESCALA_PROBABILIDAD_DEFAULT, IMPLICACIONES_DEFAULT, MESES_REVISION_DEFAULT, PESOS_DEFAULT,
        RANGOS_ECONOMICO_DEFAULT, RANGOS_NIVEL_DEFAULT,
    )

    await poner_configuracion(cliente, auth, {
        "pesos_json": PESOS_DEFAULT, "rangos_economico_json": RANGOS_ECONOMICO_DEFAULT,
        "escala_probabilidad_json": ESCALA_PROBABILIDAD_DEFAULT, "rangos_nivel_json": RANGOS_NIVEL_DEFAULT,
        "meses_revision": MESES_REVISION_DEFAULT, "implicaciones_activas_json": IMPLICACIONES_DEFAULT})


async def activar_implicacion(cliente, auth, clave: str, *, alerta=True, restriccion=False, **extra) -> dict:
    """Cambia una sola implicación y deja las otras tres como están."""
    from models.criticidad import IMPLICACIONES_DEFAULT

    actual = (await configuracion(cliente, auth))["implicaciones_activas_json"] or {}
    mezcla = {**IMPLICACIONES_DEFAULT, **actual}
    mezcla[clave] = {**mezcla.get(clave, {}), "alerta": alerta, "restriccion": restriccion, **extra}
    return await poner_configuracion(cliente, auth, {"implicaciones_activas_json": mezcla})


async def modo_falla(cliente, auth, equipo_id=None, email=None, esperado=201, **extra) -> dict:
    from tests.folios_utiles import AP

    cuerpo = {"descripcion_falla": f"Modo de prueba {uuid.uuid4().hex[:8]}", "causa_probable": "Causa de prueba",
              "efecto_operacional": "Efecto de prueba", "severidad": 4, "frecuencia_historica": 3, **extra}
    if equipo_id:
        cuerpo["equipo_id"] = str(equipo_id)
    r = await cliente.post("/api/modos-falla", headers=await auth(email or AP), json=cuerpo)
    assert r.status_code == esperado, r.text
    return r.json()


async def mitigacion(cliente, auth, modo_id, email=None, esperado=201, **extra) -> dict:
    from tests.folios_utiles import AP

    cuerpo = {"modo_falla_id": str(modo_id), "accion_mitigacion": "Acción de prueba", **extra}
    r = await cliente.post("/api/mitigaciones", headers=await auth(email or AP), json=cuerpo)
    assert r.status_code == esperado, r.text
    return r.json()


def indice(fila) -> Decimal:
    return Decimal(str(fila["indice_criticidad"]))
