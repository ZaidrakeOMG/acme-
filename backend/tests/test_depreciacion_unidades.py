"""Depreciación por unidades de producción (§6.9.4, ACT-8.3): el método que P09 dejó pendiente, ahora con las
unidades que leen los medidores. F2-04.

Fórmula literal: depreciación del período = (costo de adquisición − valor residual) × (unidades del período ÷ vida
útil total en unidades).
"""
from datetime import date, timedelta
from decimal import Decimal

from tests.folios_utiles import AE, AP, DES, nuevo_equipo
from tests.inventario_utiles import equipo_con_activo
from tests.medidores_utiles import alta_medidor, incremento_esperado, lectura, nuevo_tipo_medidor


async def _ficha(cliente, auth, equipo_id, email=AE) -> dict:
    r = await cliente.get(f"/api/activos/{equipo_id}", headers=await auth(email))
    assert r.status_code == 200, r.text
    return r.json()


async def test_caso_numerico_con_medidor(cliente, auth, datos):
    """Línea de producción: costo 1,000,000, residual 100,000, vida 100,000 piezas. Con 10,000 piezas producidas
    desde el inicio, la depreciación acumulada es (1,000,000 − 100,000) × 10,000/100,000 = 90,000 y el valor en
    libros queda en 910,000."""
    equipo = await equipo_con_activo(cliente, auth, datos, costo="1000000.00", reposicion="1200000.00")
    tipo = await nuevo_tipo_medidor(cliente, auth, nombre=f"Piezas {equipo['codigo']}", unidad="piezas",
                                    categoria="unidades", decimales=0, factor_salto_maximo="100")
    medidor = await alta_medidor(cliente, auth, equipo, tipo, metodo_actualizacion="importacion")
    await incremento_esperado(cliente, auth, medidor, 500)
    inicio = date.today() - timedelta(days=60)
    await lectura(cliente, auth, medidor, "4000", dias_atras=40)
    await lectura(cliente, auth, medidor, "10000", dias_atras=0)

    r = await cliente.put(f"/api/activos/{equipo['id']}/depreciacion", headers=await auth(AE), json={
        "metodo": "unidades_produccion", "valor_salvamento": "100000.00", "unidades_vida_util": "100000",
        "equipo_medidor_id": medidor["id"], "unidades_al_inicio": "0", "fecha_inicio": inicio.isoformat(),
        "valor_reposicion": "1200000.00"})
    assert r.status_code == 200, r.text
    f = r.json()
    assert f["depreciacion"]["metodo"] == "unidades_produccion" and f["depreciacion"]["aviso"] == ""
    assert f["depreciacion"]["equipo_medidor_id"] == medidor["id"]
    assert Decimal(f["depreciacion"]["unidades_acumuladas"]) == 10000
    assert Decimal(f["tco"]["valor_residual"]) == 910000

    # El historial del período guarda las unidades, para que el cálculo se pueda auditar.
    r = await cliente.post(f"/api/activos/{equipo['id']}/calcular", headers=await auth(AE))
    assert r.status_code == 200, r.text
    h = r.json()["depreciacion_historial"][-1]
    assert h["metodo_aplicado"] == "unidades_produccion"
    assert Decimal(h["valor_en_libros"]) == 910000 and Decimal(h["depreciacion_acumulada"]) == 90000
    assert Decimal(h["unidades_acumuladas"]) == 10000
    # La depreciación del período es proporcional a las unidades de ese mes, no al tiempo.
    unidades_periodo = Decimal(h["unidades_periodo"])
    assert unidades_periodo > 0
    esperada = (Decimal("900000") * unidades_periodo / Decimal("100000")).quantize(Decimal("0.01"))
    assert abs(Decimal(h["depreciacion_periodo"]) - esperada) <= Decimal("0.02"), (h, esperada)


async def test_mas_unidades_deprecian_mas_y_nunca_pasan_del_salvamento(cliente, auth, datos):
    equipo = await equipo_con_activo(cliente, auth, datos, costo="200000.00", reposicion="240000.00")
    tipo = await nuevo_tipo_medidor(cliente, auth, nombre=f"Ciclos {equipo['codigo']}", unidad="ciclos",
                                    categoria="ciclos", decimales=0, factor_salto_maximo="100")
    medidor = await alta_medidor(cliente, auth, equipo, tipo, metodo_actualizacion="importacion")
    await incremento_esperado(cliente, auth, medidor, 1000)
    r = await cliente.put(f"/api/activos/{equipo['id']}/depreciacion", headers=await auth(AE), json={
        "metodo": "unidades_produccion", "valor_salvamento": "20000.00", "unidades_vida_util": "50000",
        "equipo_medidor_id": medidor["id"], "unidades_al_inicio": "0",
        "fecha_inicio": (date.today() - timedelta(days=30)).isoformat()})
    assert r.status_code == 200 and Decimal(r.json()["tco"]["valor_residual"]) == 200000   # sin lecturas, nada usado
    await lectura(cliente, auth, medidor, "25000", dias_atras=10)
    f = await _ficha(cliente, auth, equipo["id"])
    # A la mitad de la vida útil en ciclos: 180,000 × 0.5 = 90,000 de depreciación.
    assert Decimal(f["tco"]["valor_residual"]) == 110000
    # Pasada la vida útil no baja del salvamento.
    await lectura(cliente, auth, medidor, "90000")
    f = await _ficha(cliente, auth, equipo["id"])
    assert Decimal(f["tco"]["valor_residual"]) == 20000


async def test_sin_medidor_usa_el_campo_manual_y_avisa(cliente, auth, datos):
    """Compatibilidad con P09: el método ya calcula, pero sin medidor elegido el aviso lo dice."""
    equipo = await equipo_con_activo(cliente, auth, datos, costo="100000.00", reposicion="120000.00")
    r = await cliente.put(f"/api/activos/{equipo['id']}/depreciacion", headers=await auth(AE), json={
        "metodo": "unidades_produccion", "unidades_vida_util": "10000", "unidades_acumuladas": "2500"})
    assert r.status_code == 200, r.text
    assert r.json()["depreciacion"]["aviso"] == "MEDIDOR_NO_CONFIGURADO"
    assert Decimal(r.json()["tco"]["valor_residual"]) == 75000   # 100,000 − 100,000×(2,500/10,000)
    # Sin vida útil en unidades no hay cómo repartir: el aviso es otro.
    r = await cliente.put(f"/api/activos/{equipo['id']}/depreciacion", headers=await auth(AE), json={
        "metodo": "unidades_produccion", "unidades_vida_util": "0"})
    assert r.status_code == 200 and r.json()["depreciacion"]["aviso"] == "SIN_VIDA_UTIL_EN_UNIDADES"


async def test_el_medidor_debe_ser_del_mismo_equipo(cliente, auth, datos):
    equipo = await equipo_con_activo(cliente, auth, datos, costo="50000.00", reposicion="60000.00")
    otro = await nuevo_equipo(cliente, auth, datos)
    tipo = await nuevo_tipo_medidor(cliente, auth, nombre=f"Horas {otro['codigo']}")
    ajeno = await alta_medidor(cliente, auth, otro, tipo)
    r = await cliente.put(f"/api/activos/{equipo['id']}/depreciacion", headers=await auth(AE), json={
        "metodo": "unidades_produccion", "unidades_vida_util": "1000", "equipo_medidor_id": ajeno["id"]})
    assert r.status_code == 422 and r.json()["codigo"] == "MEDIDOR_INVALIDO"
    # Y solo el Admin empresa configura la depreciación (§6.9.4).
    r = await cliente.put(f"/api/activos/{equipo['id']}/depreciacion", headers=await auth(AP), json={
        "metodo": "unidades_produccion", "unidades_vida_util": "1000"})
    assert r.status_code == 403
