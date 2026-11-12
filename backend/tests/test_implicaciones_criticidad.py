"""Las implicaciones de §6.9.3 por nivel: ACMA las aplica como alerta por defecto y como restricción solo si el
cliente lo decide. Una prueba por implicación, en los dos modos. F2-05."""
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import text

from tests.criticidad_utiles import (
    activar_implicacion, equipo_con_historia, evaluar, restaurar_configuracion, sembrar_fallas,
)
from tests.folios_utiles import AE, AP, DES, OP, SA, autorizar_sin_flujo, tecnico_usuario_id

TEC3 = "tecnico3@acma.dev"   # el único técnico del demo sin la habilidad de refrigeración certificada
from tests.operacion_utiles import alertas_de, evaluar as correr_evaluador
from tests.preventivos_utiles import nuevo_plan

CRITICO = (5, 4, 4, 4)       # con probabilidad 5 da 86.00: nivel A


async def _critico(cliente, auth, datos, **extra):
    """Un activo que el cálculo deja en A: doce fallas en doce meses e impacto alto."""
    equipo = await equipo_con_historia(cliente, auth, datos, fallas=12, **extra)
    fila = await evaluar(cliente, auth, equipo["id"], *CRITICO)
    assert fila["nivel"] == "A", fila
    return equipo


async def _mias(clave, equipo_id):
    return [a for a in await alertas_de(clave) if a["datos"].get("equipo_id") == str(equipo_id)]


async def test_pm_obligatorio_como_alerta_y_apagado(cliente, auth, datos):
    """§6.9.3 nivel A: «PM obligatorio con plan definido». Sin plan activo, se avisa."""
    equipo = await _critico(cliente, auth, datos)
    try:
        await activar_implicacion(cliente, auth, "pm_obligatorio", alerta=False)
        await correr_evaluador("ACTIVO_CRITICO_SIN_PLAN")
        assert await _mias("ACTIVO_CRITICO_SIN_PLAN", equipo["id"]) == [], "apagada no debe avisar"

        await activar_implicacion(cliente, auth, "pm_obligatorio", alerta=True)
        await correr_evaluador("ACTIVO_CRITICO_SIN_PLAN")
        avisos = await _mias("ACTIVO_CRITICO_SIN_PLAN", equipo["id"])
        assert len(avisos) == 1, avisos
        assert avisos[0]["datos"]["nivel"] == "A" and equipo["codigo"] in avisos[0]["datos"]["etiqueta"]
        # Y no se repite mientras siga sin plan.
        await correr_evaluador("ACTIVO_CRITICO_SIN_PLAN")
        assert len(await _mias("ACTIVO_CRITICO_SIN_PLAN", equipo["id"])) == 1
    finally:
        await restaurar_configuracion(cliente, auth)


async def test_un_activo_critico_con_plan_no_dispara_la_alerta(cliente, auth, datos):
    plan = await nuevo_plan(cliente, auth)       # los planes nacen activos
    equipo = await _critico(cliente, auth, datos)
    r = await cliente.post(f"/api/planes/{plan['id']}/equipos", headers=await auth(AP),
                           json={"equipo_id": equipo["id"]})
    assert r.status_code == 201, r.text
    await correr_evaluador("ACTIVO_CRITICO_SIN_PLAN")
    assert await _mias("ACTIVO_CRITICO_SIN_PLAN", equipo["id"]) == []


async def test_respuesta_maxima_por_criticidad(cliente, auth, datos):
    """§6.9.3: 4 h en activos A y 8 h en B, aunque el SLA del contrato prometa más. El umbral es el % consumido."""
    from core.db import nueva_sesion
    from core.rls import CONTEXTO_SISTEMA
    import uuid

    equipo = await _critico(cliente, auth, datos)
    folio = await autorizar_sin_flujo(cliente, auth, datos, OP, equipo=equipo)
    # El folio se captura recién: 3.5 h de las 4 son el 87 %, pasado el 80 % del default.
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        await db.execute(text("UPDATE folios SET capturado_at = :t WHERE id = :id"),
                         {"t": datetime.now(UTC) - timedelta(hours=3, minutes=30), "id": uuid.UUID(folio["id"])})
        await db.commit()
    try:
        await activar_implicacion(cliente, auth, "respuesta_maxima", alerta=False)
        await correr_evaluador("RESPUESTA_CRITICIDAD_EN_RIESGO")
        assert [a for a in await alertas_de("RESPUESTA_CRITICIDAD_EN_RIESGO")
                if a["datos"].get("folio_id") == folio["id"]] == []

        await activar_implicacion(cliente, auth, "respuesta_maxima", alerta=True)
        await correr_evaluador("RESPUESTA_CRITICIDAD_EN_RIESGO")
        avisos = [a for a in await alertas_de("RESPUESTA_CRITICIDAD_EN_RIESGO")
                  if a["datos"].get("folio_id") == folio["id"]]
        assert len(avisos) == 1, avisos
        assert avisos[0]["datos"]["horas_limite"] == 4 and avisos[0]["datos"]["nivel"] == "A"
        assert float(avisos[0]["datos"]["horas_transcurridas"]) >= 3.4
    finally:
        await restaurar_configuracion(cliente, auth)


async def test_la_respuesta_por_criticidad_no_toca_el_sla_del_contrato(cliente, auth, datos):
    """Es un aviso paralelo: el contrato puede prometer 24 h en un equipo que por su criticidad debería atenderse
    en 4. Correr el evaluador no mueve ni una columna del `folio_sla` que mide el cumplimiento (P10)."""
    from core.db import nueva_sesion
    from core.rls import CONTEXTO_SISTEMA
    from models.folios import FolioSLA
    import uuid

    equipo = await _critico(cliente, auth, datos)
    folio = await autorizar_sin_flujo(cliente, auth, datos, OP, equipo=equipo)
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        await db.execute(text("UPDATE folios SET capturado_at = :t WHERE id = :id"),
                         {"t": datetime.now(UTC) - timedelta(hours=3, minutes=45), "id": uuid.UUID(folio["id"])})
        await db.commit()

    async def _sla():
        async with nueva_sesion(CONTEXTO_SISTEMA) as db:
            fila = (await db.execute(select_sla(uuid.UUID(folio["id"])))).scalar_one_or_none()
            if fila is None:
                return None
            return {"respuesta_horas": fila.tiempo_respuesta_prometido_horas,
                    "cumplimiento_respuesta": fila.cumplimiento_respuesta,
                    "respuesta_real_min": fila.tiempo_respuesta_real_min}

    def select_sla(folio_id):
        from sqlalchemy import select

        return select(FolioSLA).where(FolioSLA.folio_id == folio_id)

    antes = await _sla()
    await activar_implicacion(cliente, auth, "respuesta_maxima", alerta=True)
    try:
        await correr_evaluador("RESPUESTA_CRITICIDAD_EN_RIESGO")
        assert [a for a in await alertas_de("RESPUESTA_CRITICIDAD_EN_RIESGO")
                if a["datos"].get("folio_id") == folio["id"]], "la alerta de criticidad sí debe dispararse"
        assert await _sla() == antes, "el aviso de §6.9.3 no mide el SLA del contrato"
        if antes is not None:
            assert antes["cumplimiento_respuesta"] is None and antes["respuesta_real_min"] is None
    finally:
        await restaurar_configuracion(cliente, auth)


async def test_tecnico_certificado_como_advertencia(cliente, auth, datos):
    """Por defecto queda como advertencia: el despachador la ve y queda en el historial del folio."""
    from core.db import nueva_sesion
    from core.rls import CONTEXTO_SISTEMA
    from models.folios import Folio
    from services import folios_captura_service
    import uuid

    equipo = await _critico(cliente, auth, datos, familia="Refrigeración")
    folio = await autorizar_sin_flujo(cliente, auth, datos, OP, equipo=equipo)
    try:
        await activar_implicacion(cliente, auth, "tecnico_certificado", alerta=True, restriccion=False)
        async with nueva_sesion(CONTEXTO_SISTEMA) as db:
            f = await db.get(Folio, uuid.UUID(folio["id"]))
            aviso = await folios_captura_service.advertencia_por_criticidad(db, f, tiene_habilidad=False)
            assert aviso is not None and aviso["nivel"] == "A" and aviso["restriccion"] is False
            assert "especialista" in aviso["mensaje"]
            # Con la habilidad certificada no hay nada que advertir.
            assert await folios_captura_service.advertencia_por_criticidad(db, f, tiene_habilidad=True) is None

        # Apagadas las dos (alerta y restricción), la implicación desaparece.
        await activar_implicacion(cliente, auth, "tecnico_certificado", alerta=False, restriccion=False)
        async with nueva_sesion(CONTEXTO_SISTEMA) as db:
            f = await db.get(Folio, uuid.UUID(folio["id"]))
            assert await folios_captura_service.advertencia_por_criticidad(db, f, tiene_habilidad=False) is None
    finally:
        await restaurar_configuracion(cliente, auth)


async def test_tecnico_certificado_como_restriccion(cliente, auth, datos):
    """Activada como restricción, asignar un técnico sin la certificación a un activo A se bloquea, y el permiso
    `asignar_tecnico_sin_habilidad` no la levanta: ese permiso dispensa la habilidad, no la certificación."""
    equipo = await _critico(cliente, auth, datos, familia="Refrigeración")
    folio = await autorizar_sin_flujo(cliente, auth, datos, OP, equipo=equipo)
    sin_certificacion = await tecnico_usuario_id(cliente, auth, TEC3)   # tecnico3 no tiene refrigeración
    h = await auth(AP)
    desp = (await cliente.get("/api/usuarios", headers=h, params={"rol": "despachador"})).json()[0]
    permiso = {"despachador_id": desp["id"], "tenant_id": str(datos["tenant"])}
    try:
        await activar_implicacion(cliente, auth, "tecnico_certificado", alerta=True, restriccion=True)
        # Sin el permiso de habilidad ni llega a la criticidad: lo frena la regla de F2-01.
        r = await cliente.post(f"/api/folios/{folio['id']}/asignar", headers=await auth(DES),
                               json={"tecnico_id": sin_certificacion})
        assert r.status_code == 409 and r.json()["codigo"] == "TECNICO_SIN_HABILIDAD", r.text
        assert (await cliente.put("/api/configuracion/permisos-despachador", headers=h,
                                  json={"valores": {"asignar_tecnico_sin_habilidad": True},
                                        **permiso})).status_code == 200
        r = await cliente.post(f"/api/folios/{folio['id']}/asignar", headers=await auth(DES),
                               json={"tecnico_id": sin_certificacion, "razon": "Es el único disponible"})
        assert r.status_code == 409 and r.json()["codigo"] == "CRITICIDAD_EXIGE_CERTIFICACION", r.text
        assert r.json()["detalles"][0]["nivel"] == "A"

        # Como advertencia (no restricción) sí asigna, y el aviso queda en el historial del folio.
        await activar_implicacion(cliente, auth, "tecnico_certificado", alerta=True, restriccion=False)
        r = await cliente.post(f"/api/folios/{folio['id']}/asignar", headers=await auth(DES),
                               json={"tecnico_id": sin_certificacion, "razon": "Es el único disponible"})
        assert r.status_code == 200, r.text
        historial = (await cliente.get(f"/api/folios/{folio['id']}/historial", headers=await auth(DES))).json()
        contextos = [e.get("datos_contexto_json") or {} for e in historial]
        assert any(c.get("criticidad") == "A" and "especialista" in (c.get("aviso_criticidad") or "")
                   for c in contextos), contextos
    finally:
        await cliente.put("/api/configuracion/permisos-despachador", headers=h,
                          json={"valores": {"asignar_tecnico_sin_habilidad": False}, **permiso})
        await restaurar_configuracion(cliente, auth)


async def test_refaccion_critica_sin_stock(cliente, auth, datos):
    """§6.9.3 nivel A: «refacciones siempre en inventario». Se mira el material del plan contra la existencia."""
    from tests.inventario_utiles import articulo

    equipo = await _critico(cliente, auth, datos)
    # Artículo con mínimo 5 y sin una sola entrada: existencia 0 contra mínimo 5.
    art = await articulo(cliente, auth, minimo="5")
    plan = await nuevo_plan(cliente, auth, materiales=[
        {"descripcion": "Refacción crítica de la prueba", "articulo_id": art["id"],
         "cantidad_estandar": "1", "unidad": "pieza"}])
    assert (await cliente.post(f"/api/planes/{plan['id']}/equipos", headers=await auth(AP),
                               json={"equipo_id": equipo["id"]})).status_code == 201
    try:
        await activar_implicacion(cliente, auth, "refaccion_en_inventario", alerta=False)
        await correr_evaluador("REFACCION_CRITICA_SIN_STOCK")
        assert [a for a in await alertas_de("REFACCION_CRITICA_SIN_STOCK")
                if a["datos"].get("articulo_id") == art["id"]] == []

        await activar_implicacion(cliente, auth, "refaccion_en_inventario", alerta=True)
        await correr_evaluador("REFACCION_CRITICA_SIN_STOCK")
        avisos = [a for a in await alertas_de("REFACCION_CRITICA_SIN_STOCK")
                  if a["datos"].get("articulo_id") == art["id"]]
        assert len(avisos) == 1, avisos
        assert avisos[0]["datos"]["equipo_codigo"] == equipo["codigo"]
    finally:
        await restaurar_configuracion(cliente, auth)


async def test_las_implicaciones_son_del_cliente(cliente, auth, datos):
    """Las activa el Admin empresa; el prestador las ve pero no las cambia."""
    try:
        cfg = await activar_implicacion(cliente, auth, "pm_obligatorio", alerta=True, restriccion=True)
        assert cfg["implicaciones_activas_json"]["pm_obligatorio"]["restriccion"] is True
        r = await cliente.put("/api/criticidad/configuracion", headers=await auth(AP),
                              params={"tenant_id": str(datos["tenant"])},
                              json={"implicaciones_activas_json": {"pm_obligatorio": {"alerta": False}}})
        assert r.status_code == 403, r.text
        # Y cada cliente tiene las suyas: lo que apague el demo no afecta al otro.
        ajena = (await cliente.get("/api/criticidad/configuracion", headers=await auth(SA),
                                   params={"tenant_id": str(datos["otro_tenant"])})).json()
        assert ajena["implicaciones_activas_json"]["pm_obligatorio"]["restriccion"] is False
    finally:
        await restaurar_configuracion(cliente, auth)


async def test_la_guia_del_formulario_trae_las_implicaciones_por_nivel(cliente, auth):
    """Lo que la pantalla necesita para explicar qué significa cada nivel, con el texto literal de §6.9.3."""
    g = (await cliente.get("/api/criticidad/guia", headers=await auth(AE))).json()
    assert set(g["dimensiones"]) == {"operacional", "seguridad", "economico", "imagen"}
    assert g["dimensiones"]["operacional"]["niveles"]["5"] == "Cierre total"
    assert set(g["niveles"]) == {"A", "B", "C", "D"} and g["niveles"]["A"] == "Crítico"
    assert g["implicaciones"]["A"].startswith("PM obligatorio")
    assert "4 horas" in g["implicaciones"]["A"] and "8 horas" in g["implicaciones"]["B"]
    assert "reactivo" in g["implicaciones"]["D"]
