"""Ayudas compartidas por las pruebas de F2-04 (medidores de activos y planes por uso)."""
import uuid
from datetime import UTC, datetime, timedelta

from tests.folios_utiles import AE, AP, nuevo_equipo


async def nuevo_tipo_medidor(cliente, auth, *, email=AP, esperado=201, **extra) -> dict:
    """Tipo del prestador (o del cliente, según el usuario). Por defecto no exige foto y tolera 3× el salto."""
    cuerpo = {"nombre": f"Horómetro {uuid.uuid4().hex[:6]}", "unidad": "h", "categoria": "horas", "decimales": 1,
              "permite_estimacion": True, "requiere_foto": False, "factor_salto_maximo": "3", **extra}
    r = await cliente.post("/api/medidores/tipos", headers=await auth(email), json=cuerpo)
    assert r.status_code == esperado, r.text
    return r.json()


async def tipo_global(cliente, auth, nombre="Horas de operación", email=AP) -> dict:
    r = await cliente.get("/api/medidores/tipos", headers=await auth(email))
    assert r.status_code == 200, r.text
    return next(t for t in r.json() if t["nombre"] == nombre)


async def alta_medidor(cliente, auth, equipo: dict, tipo: dict, *, email=AP, esperado=201, **extra) -> dict:
    cuerpo = {"tipo_medidor_id": tipo["id"], "valor_inicial": "0", "metodo_actualizacion": "operador", **extra}
    r = await cliente.post(f"/api/medidores/equipos/{equipo['id']}", headers=await auth(email), json=cuerpo)
    assert r.status_code == esperado, r.text
    return r.json()


async def equipo_con_medidor(cliente, auth, datos, *, familia="Refrigeración", tipo=None, email=AP,
                             valor_inicial="0", factor_salto="3", **extra) -> tuple[dict, dict, dict]:
    """(equipo, medidor, tipo de medidor) listos para usar. El equipo es nuevo, así que no choca con el seed.

    `factor_salto` alto (p. ej. "1000") desactiva en la práctica la detección de saltos: lo usan las pruebas de
    triggers, que mueven el marcador a propósito. La detección tiene sus propias pruebas en
    `test_medidor_lecturas.py`, con el factor por defecto."""
    equipo = await nuevo_equipo(cliente, auth, datos, familia=familia)
    tipo = tipo or await nuevo_tipo_medidor(cliente, auth, factor_salto_maximo=factor_salto)
    medidor = await alta_medidor(cliente, auth, equipo, tipo, email=email, valor_inicial=valor_inicial, **extra)
    return equipo, medidor, tipo


async def lectura(cliente, auth, medidor: dict, valor, *, email=AP, esperado=201, dias_atras: float | None = None,
                  **extra) -> dict:
    """Registra una lectura. `dias_atras` fija la hora del dispositivo, que es la que vale para los saltos."""
    cuerpo = {"equipo_medidor_id": medidor["id"], "valor": str(valor), **extra}
    if dias_atras is not None:
        cuerpo["timestamp_dispositivo"] = (datetime.now(UTC) - timedelta(days=dias_atras)).isoformat()
    r = await cliente.post("/api/medidores/lecturas", headers=await auth(email), json=cuerpo)
    assert r.status_code == esperado, r.text
    return r.json()


async def historia(cliente, auth, medidor: dict, valores: list, *, desde_dias: int = 30, email=AP) -> list[dict]:
    """Varias lecturas en días consecutivos hacia atrás, en orden cronológico."""
    salida = []
    total = len(valores)
    for i, v in enumerate(valores):
        salida.append(await lectura(cliente, auth, medidor, v, email=email, dias_atras=desde_dias - i * (desde_dias / total)))
    return salida


async def incremento_esperado(cliente, auth, medidor: dict, por_dia, *, email=AP, activa=False) -> dict:
    """Fija el incremento diario esperado del medidor. Es lo que usan la detección de saltos y la proyección, así
    que las pruebas que mueven el marcador a propósito lo declaran para no chocar con la alerta de anomalía."""
    r = await cliente.put(f"/api/medidores/{medidor['id']}/estimacion", headers=await auth(email),
                          json={"incremento_por_dia": str(por_dia), "activa": activa})
    assert r.status_code == 200, r.text
    return r.json()


async def estado_medidor(cliente, auth, equipo_id: str, *, email=AP) -> list[dict]:
    r = await cliente.get(f"/api/medidores/equipos/{equipo_id}", headers=await auth(email))
    assert r.status_code == 200, r.text
    return r.json()


async def plan_por_medidor(cliente, auth, equipo: dict, tipo_medidor: dict, *, tipo="medidor_umbral", valor=500,
                           familia="Refrigeración", indice=0, email=AP) -> dict:
    """Plan con un solo trigger por medidor, ya asignado al equipo."""
    from tests.preventivos_utiles import nuevo_plan

    campo = "umbral" if tipo == "medidor_umbral" else "intervalo"
    plan = await nuevo_plan(cliente, auth, familia=familia, indice=indice, email=email, trigger={
        "tipo_trigger": tipo, "parametros_json": {"tipo_medidor_id": tipo_medidor["id"], campo: valor}})
    r = await cliente.post(f"/api/planes/{plan['id']}/equipos", headers=await auth(AP), json={"equipo_id": equipo["id"]})
    assert r.status_code == 201, r.text
    return plan


async def correctivo_cerrado(cliente, auth, datos, equipo: dict, *, falla="No enciende", familia="Refrigeración") -> dict:
    """Folio correctivo de ese equipo llevado hasta `cerrado`. Lo usan las pruebas del trigger por evento, que
    escucha el cierre de un correctivo (§6.9.1)."""
    from tests.folios_utiles import DES, TEC, accion, autorizar_sin_flujo, detalle, tecnico_con_habilidades
    from tests.test_folio_estados import _respuesta_atencion_con_firma

    f = await autorizar_sin_flujo(cliente, auth, datos, equipo=equipo, familia=familia, falla=falla)
    tec = await tecnico_con_habilidades(cliente, auth, TEC, ["refrigeracion", "electricidad"])
    await accion(cliente, auth, DES, f["id"], "asignar", {"tecnico_id": tec})
    await accion(cliente, auth, TEC, f["id"], "en-camino", {"geolat": 19.43, "geolng": -99.13})
    await accion(cliente, auth, TEC, f["id"], "confirmar-llegada", {"geolat": 19.43, "geolng": -99.13})
    folio = (await detalle(cliente, auth, f["id"]))["folio"]
    rid = await _respuesta_atencion_con_firma(cliente, auth, datos, folio)
    assert (await cliente.post(f"/api/folios/{f['id']}/atencion", headers=await auth(TEC),
                               json={"respuesta_id": rid})).status_code == 201
    cerrado = await accion(cliente, auth, TEC, f["id"], "cerrar", {"notas": "Correctivo atendido"})
    assert cerrado["estado"] == "cerrado"
    return {**folio, **cerrado}


async def crear_llave(cliente, auth, *, nombre=None, email=AE, esperado=201) -> dict:
    cuerpo = {"nombre": nombre or f"SCADA {uuid.uuid4().hex[:6]}"}
    r = await cliente.post("/api/medidores/llaves", headers=await auth(email), json=cuerpo)
    assert r.status_code == esperado, r.text
    return r.json()
