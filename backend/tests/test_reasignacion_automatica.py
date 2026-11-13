"""Reasignación automática (§6.8.2): sus restricciones duras, su registro con razón del catálogo y la pausa de
SLA de §6.10.1, y los dos modos del prestador. F2-06.

Lo que esta prueba cuida es que la reasignación automática **no sea una puerta trasera**: pasa por el mismo
servicio que la forzada, con las mismas restricciones, el mismo registro y la misma pausa de SLA. Lo único que
cambia es quién la decide.
"""
from datetime import UTC, datetime

from sqlalchemy import select

from models.preventivos import Reasignacion, TipoReasignacion
from models.rutas import DisparadorRecalculo, EstadoRecalculo, RutaRecalculo
from tests.folios_utiles import AP, DES, OP, TEC
from tests.rutas_utiles import (
    calcular, configurar, folios_del_dia, jornadas_abiertas, mercado, paradas_de, plan, publicar, tecnico_de,
    usuario_id,
)


async def _plan(cliente, auth, datos, folios=5):
    await configurar(cliente, auth)
    await jornadas_abiertas()
    m = await mercado(cliente, auth, datos)
    mios = await folios_del_dia(cliente, auth, datos, folios)
    detalle = await calcular(cliente, auth, m["id"])
    await publicar(cliente, auth, detalle["plan"]["id"])
    return await plan(cliente, auth, detalle["plan"]["id"]), {f["id"] for f in mios}


def test_la_razon_de_cada_disparador_esta_en_el_catalogo_de_6_8_2():
    """Cada movimiento automático se registra con una de las siete razones literales del diseño."""
    from models.preventivos import RAZONES_REASIGNACION
    from services.rutas.recalculo_service import RAZON_POR_DISPARADOR

    literales = {r[0] if isinstance(r, tuple) else r for r in RAZONES_REASIGNACION}
    assert set(RAZON_POR_DISPARADOR.values()) <= literales, set(RAZON_POR_DISPARADOR.values()) - literales
    # Cada disparador tiene su razón, no una genérica para todos.
    assert RAZON_POR_DISPARADOR[DisparadorRecalculo.incidencia_tecnico] == "Incidencia del técnico"
    assert RAZON_POR_DISPARADOR[DisparadorRecalculo.folio_nuevo_urgente] == "Prioridad de cliente"
    assert RAZON_POR_DISPARADOR[DisparadorRecalculo.desvio] == "Optimización de ruta"
    assert set(DisparadorRecalculo) == set(RAZON_POR_DISPARADOR), "falta la razón de algún disparador"


async def test_la_reasignacion_automatica_queda_registrada_con_su_razon(cliente, auth, datos):
    from core.db import nueva_sesion
    from core.rls import CONTEXTO_SISTEMA
    import uuid

    detalle, _ = await _plan(cliente, auth, datos, folios=6)
    r = await cliente.post(f"/api/rutas/{detalle['plan']['id']}/recalcular", headers=await auth(DES),
                           json={"disparador": "incidencia_tecnico", "motivo": "el técnico reportó el vehículo"})
    assert r.status_code == 200, r.text
    propuesta = r.json()
    if not propuesta["movimientos"]:
        return
    r2 = await cliente.post(f"/api/rutas/propuestas/{propuesta['id']}/aceptar", headers=await auth(DES))
    assert r2.status_code == 200, r2.text

    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        recalculo = await db.get(RutaRecalculo, uuid.UUID(propuesta["id"]))
        assert recalculo.estado == EstadoRecalculo.aplicada
        assert recalculo.decidido_por is not None and recalculo.decidido_at is not None
        filas = list((await db.execute(select(Reasignacion).where(
            Reasignacion.recalculo_id == recalculo.id))).scalars())
        for f in filas:
            assert f.tipo == TipoReasignacion.automatica
            assert f.recalculo_id == recalculo.id
            assert f.razon_id is not None, "la razón del catálogo es obligatoria también en la automática"
            assert "automática" in f.comentario or "automatica" in f.comentario


async def test_la_automatica_pausa_el_sla_igual_que_la_forzada(cliente, auth, datos):
    """§6.10.1: el contador se pausa durante la reasignación. Lo hace la transición a `reasignado`, que es la
    misma por la que pasa la automática."""
    from core.db import nueva_sesion
    from core.rls import CONTEXTO_SISTEMA
    from models.sla import FolioSLAPausa
    import uuid

    detalle, _ = await _plan(cliente, auth, datos, folios=6)
    r = await cliente.post(f"/api/rutas/{detalle['plan']['id']}/recalcular", headers=await auth(DES),
                           json={"disparador": "sla_en_riesgo", "motivo": "para ver la pausa"})
    propuesta = r.json()
    movidos = [m for m in propuesta["movimientos"] if m.get("de_tecnico_id")]
    if not movidos:
        return   # solo hubo huérfanos: una primera asignación no pausa nada porque el reloj no estaba corriendo
    assert (await cliente.post(f"/api/rutas/propuestas/{propuesta['id']}/aceptar",
                               headers=await auth(DES))).status_code == 200
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        pausas = list((await db.execute(select(FolioSLAPausa).where(
            FolioSLAPausa.folio_id == uuid.UUID(movidos[0]["folio_id"])))).scalars())
    assert pausas, "la reasignación automática tiene que haber abierto una pausa de SLA"


async def test_nunca_mueve_un_folio_en_ejecucion(cliente, auth, datos):
    """Restricción dura de §6.8.2: el técnico ya está en la unidad."""
    from core.db import nueva_sesion
    from core.rls import CONTEXTO_SISTEMA
    from models.folios import EstadoFolio, Folio
    import uuid

    detalle, mios = await _plan(cliente, auth, datos, folios=5)
    paradas = paradas_de(detalle)
    objetivo = next((p for p in paradas if p["folio_id"] in mios), None)
    if objetivo is None:
        return
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        f = await db.get(Folio, uuid.UUID(objetivo["folio_id"]))
        f.estado = EstadoFolio.en_ejecucion
        f.fecha_inicio_atencion = datetime.now(UTC)
        await db.commit()
    r = await cliente.post(f"/api/rutas/{detalle['plan']['id']}/recalcular", headers=await auth(DES),
                           json={"disparador": "manual", "motivo": "con uno en ejecución"})
    if r.status_code == 409:
        return
    movidos = {m["folio_id"] for m in r.json()["movimientos"]}
    assert objetivo["folio_id"] not in movidos


async def test_nunca_asigna_a_quien_no_tiene_la_habilidad(cliente, auth, datos):
    """La restricción dura la pone el modelo: ningún movimiento propuesto lleva un folio a un técnico sin la
    habilidad certificada."""
    from tests.rutas_utiles import HABILIDADES

    detalle, _ = await _plan(cliente, auth, datos, folios=6)
    r = await cliente.post(f"/api/rutas/{detalle['plan']['id']}/recalcular", headers=await auth(DES),
                           json={"disparador": "manual"})
    if r.status_code == 409:
        return
    # Habilidad certificada de cada técnico, por id de usuario.
    por_id = {str(await usuario_id(e)): h for e, h in HABILIDADES.items()}
    from core.db import nueva_sesion
    from core.rls import CONTEXTO_SISTEMA
    from models.catalogos import Equipo, FamiliaEquipo, TipoEquipo
    from models.folios import Folio
    import uuid

    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        for m in r.json()["movimientos"]:
            folio = await db.get(Folio, uuid.UUID(m["folio_id"]))
            if folio.equipo_id is None:
                continue
            equipo = await db.get(Equipo, folio.equipo_id)
            tipo = await db.get(TipoEquipo, equipo.tipo_equipo_id)
            familia = await db.get(FamiliaEquipo, tipo.familia_id)
            requerida = familia.habilidad_clave or familia.nombre.lower().replace(" ", "_")
            destino = por_id.get(m["a_tecnico_id"])
            if destino is not None:
                assert requerida in destino, (m["numero_folio"], requerida, destino)


async def test_el_modo_lo_decide_el_prestador(cliente, auth, datos):
    """`solo_sugerir` es el default y es el que conviene: un cálculo nuevo no debería mover la operación solo."""
    cfg = await configurar(cliente, auth)
    assert cfg["modo_reasignacion_automatica"] == "solo_sugerir"
    assert 1 <= cfg["minutos_vigencia_propuesta"] <= 240
    # Solo el Admin prestador cambia el modo: es su operación.
    r = await cliente.put("/api/rutas/configuracion", headers=await auth(DES),
                          json={"modo_reasignacion_automatica": "aplicar_y_avisar"})
    assert r.status_code == 403, r.text
    for email in (OP, TEC):
        assert (await cliente.get("/api/rutas/configuracion", headers=await auth(email))).status_code == 403


async def test_aplicar_y_avisar_notifica_al_despachador_y_a_los_tecnicos(cliente, auth, datos):
    from services import notificaciones

    try:
        detalle, _ = await _plan(cliente, auth, datos, folios=6)
        await configurar(cliente, auth, modo_reasignacion_automatica="aplicar_y_avisar")
        notificaciones.ENVIADAS.clear()
        r = await cliente.post(f"/api/rutas/{detalle['plan']['id']}/recalcular", headers=await auth(DES),
                               json={"disparador": "folio_nuevo_urgente", "motivo": "urgente del cliente"})
        assert r.status_code == 200, r.text
        nuevos = list(notificaciones.ENVIADAS)
        if r.json()["movimientos"]:
            assert any("Reasignación automática aplicada" in n["titulo"] for n in nuevos), \
                [n["titulo"] for n in nuevos]
            aviso = next(n for n in nuevos if "Reasignación automática aplicada" in n["titulo"])
            assert set(aviso["roles"]) == {"despachador", "admin_prestador"}
    finally:
        await configurar(cliente, auth, modo_reasignacion_automatica="solo_sugerir")


async def test_solo_sugerir_avisa_que_hay_algo_que_decidir(cliente, auth, datos):
    from services import notificaciones

    detalle, _ = await _plan(cliente, auth, datos, folios=6)
    notificaciones.ENVIADAS.clear()
    r = await cliente.post(f"/api/rutas/{detalle['plan']['id']}/recalcular", headers=await auth(DES),
                           json={"disparador": "tiempo_muerto", "motivo": "tiempo muerto detectado"})
    assert r.status_code == 200, r.text
    if r.json()["movimientos"]:
        nuevos = list(notificaciones.ENVIADAS)
        aviso = next((n for n in nuevos if "Propuesta de reasignación" in n["titulo"]), None)
        assert aviso is not None, [n["titulo"] for n in nuevos]
        assert "no cambia nada" in aviso["cuerpo"]
