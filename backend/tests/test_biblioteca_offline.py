"""Descarga de la biblioteca para uso sin señal (§6.2 capa 3, ACT-5.3): paquete incremental con bajas lógicas y
registro de lo que el técnico guarda o borra en su dispositivo. F2-01."""
from datetime import UTC, datetime, timedelta

from tests.capacitacion_utiles import pdf_falso, subir_manual, tipo_equipo_id
from tests.folios_utiles import AE, AP, DES, OP, TEC, TEC2, accion, autorizar_sin_flujo, nuevo_equipo, tecnico_con_habilidades
from tests.sla_utiles import contrato_demo


async def _paquete(cliente, auth, email=TEC, desde: str | None = None) -> dict:
    params = {"dispositivo_id": "prueba-offline"}
    if desde:
        params["desde"] = desde
    r = await cliente.get("/api/sync/catalogos", headers=await auth(email), params=params)
    assert r.status_code == 200, r.text
    return r.json()


async def test_el_paquete_del_tecnico_trae_los_metadatos_de_la_biblioteca(cliente, auth, datos):
    """La clave `biblioteca` del paquete deja de venir vacía: metadatos, no archivos."""
    tipo = await tipo_equipo_id(cliente, auth)
    manual = await subir_manual(cliente, auth, tipo, "Manual sincronizable")
    paquete = await _paquete(cliente, auth)
    biblioteca = paquete["biblioteca"]
    assert biblioteca, "la biblioteca del técnico ya no puede venir vacía"
    fila = next(b for b in biblioteca if b["id"] == manual["id"])
    assert fila["clase"] == "manual" and fila["version"] == 1 and fila["activo"] is True
    assert fila["bytes"] > 0 and len(fila["hash_sha256"]) == 64
    # Metadatos, no contenido: el archivo se descarga aparte con su enlace firmado.
    assert "archivo" not in fila and "contenido" not in fila


async def test_el_paquete_es_incremental_y_trae_las_bajas(cliente, auth, datos):
    tipo = await tipo_equipo_id(cliente, auth, "Minisplit")
    marca = datetime.now(UTC).isoformat()
    nuevo = await subir_manual(cliente, auth, tipo, "Manual posterior a la marca")

    incremental = await _paquete(cliente, auth, desde=marca)
    ids = {b["id"] for b in incremental["biblioteca"]}
    assert nuevo["id"] in ids, "lo nuevo debe venir en el incremental"
    assert len(ids) < 50, "y no debe traer todo el catálogo otra vez"

    # Una baja lógica viaja con `activo: false` para que el dispositivo la retire (§6.2 capa 3).
    await cliente.delete(f"/api/biblioteca/manuales/{nuevo['id']}", headers=await auth(AP))
    tras_baja = await _paquete(cliente, auth, desde=marca)
    fila = next(b for b in tras_baja["biblioteca"] if b["id"] == nuevo["id"])
    assert fila["activo"] is False


async def test_el_paquete_marca_lo_que_es_de_sus_folios(cliente, auth, datos):
    """El dispositivo decide qué guardar; el paquete le dice qué corresponde a su trabajo del día."""
    equipo = await nuevo_equipo(cliente, auth, datos, familia="Refrigeración")
    manual = await subir_manual(cliente, auth, equipo["tipo_equipo_id"], "Manual del equipo del folio")
    folio = await autorizar_sin_flujo(cliente, auth, datos, OP, equipo=equipo)
    tec = await tecnico_con_habilidades(cliente, auth, TEC, ["refrigeracion", "electricidad"])
    await accion(cliente, auth, DES, folio["id"], "asignar", {"tecnico_id": tec})

    paquete = await _paquete(cliente, auth)
    fila = next(b for b in paquete["biblioteca"] if b["id"] == manual["id"])
    assert fila["de_mis_folios"] is True

    # Para otro técnico, el mismo manual está disponible pero no marcado como de sus folios.
    otro = await _paquete(cliente, auth, email=TEC2)
    fila_otro = next((b for b in otro["biblioteca"] if b["id"] == manual["id"]), None)
    assert fila_otro is not None and fila_otro["de_mis_folios"] is False


async def test_el_contenido_de_servicio_solo_viaja_si_es_de_sus_folios(cliente, auth, datos):
    """§6.10.4: el contenido del cliente es confidencial; solo baja el de los folios asignados."""
    contrato = await contrato_demo(cliente, auth)
    equipo = await nuevo_equipo(cliente, auth, datos, familia="Climatización")
    r = await cliente.post("/api/biblioteca/contenido", headers=await auth(AE),
                           json={"tipo_equipo_id": equipo["tipo_equipo_id"], "contrato_id": contrato["id"],
                                 "titulo": "Puntos para sincronizar", "periodicidad": "mensual",
                                 "puntos_revision": [{"descripcion": "Revisar filtros", "obligatorio": True}]})
    assert r.status_code == 201, r.text
    contenido_id = r.json()["contenido"]["id"]

    # Antes de asignarle el folio, no baja.
    antes = await _paquete(cliente, auth, email=TEC2)
    assert contenido_id not in {b["id"] for b in antes["biblioteca"]}

    # El tipo de falla tiene que ser de la familia del equipo (§6.8.6).
    folio = await autorizar_sin_flujo(cliente, auth, datos, OP, equipo=equipo, familia="Climatización",
                                      falla="No enfría")
    tec2 = await tecnico_con_habilidades(cliente, auth, TEC2, ["hvac", "electricidad"])
    await accion(cliente, auth, DES, folio["id"], "asignar", {"tecnico_id": tec2})

    despues = await _paquete(cliente, auth, email=TEC2)
    fila = next(b for b in despues["biblioteca"] if b["id"] == contenido_id)
    assert fila["clase"] == "contenido_servicio"
    assert [p["descripcion"] for p in fila["puntos_revision"]] == ["Revisar filtros"]


async def test_registro_de_lo_descargado_y_del_borrado(cliente, auth, datos):
    tipo = await tipo_equipo_id(cliente, auth)
    manual = await subir_manual(cliente, auth, tipo, "Manual que se guarda en el celular")

    r = await cliente.post("/api/biblioteca/offline", headers=await auth(TEC),
                           json={"manual_id": manual["id"], "version": 1, "dispositivo_id": "celular-tec1"})
    assert r.status_code == 201, r.text
    guardados = (await cliente.get("/api/biblioteca/offline", headers=await auth(TEC))).json()
    fila = next(g for g in guardados if g["id"] == manual["id"])
    assert fila["version_descargada"] == 1 and fila["desactualizado"] is False

    # Una versión nueva marca lo del dispositivo como desactualizado (§6.10.4: avisar y ofrecer actualizar).
    await cliente.post(f"/api/biblioteca/manuales/{manual['id']}/versiones", headers=await auth(AP),
                       files={"archivo": ("v2.pdf", pdf_falso("v2"), "application/pdf")})
    guardados = (await cliente.get("/api/biblioteca/offline", headers=await auth(TEC))).json()
    fila = next(g for g in guardados if g["id"] == manual["id"])
    assert fila["desactualizado"] is True and fila["version_vigente"] == 2

    # Borrarlo del dispositivo lo saca de la lista, sin perder el registro.
    r = await cliente.post("/api/biblioteca/offline", headers=await auth(TEC),
                           json={"manual_id": manual["id"], "version": 2, "dispositivo_id": "celular-tec1",
                                 "en_dispositivo": False})
    assert r.status_code == 201
    guardados = (await cliente.get("/api/biblioteca/offline", headers=await auth(TEC))).json()
    assert manual["id"] not in {g["id"] for g in guardados}


async def test_solo_un_tecnico_registra_descargas_y_no_las_de_otro(cliente, auth, datos):
    tipo = await tipo_equipo_id(cliente, auth)
    manual = await subir_manual(cliente, auth, tipo, "Manual de permisos offline")
    # El Admin prestador no tiene dispositivo: no registra descargas.
    r = await cliente.post("/api/biblioteca/offline", headers=await auth(AP),
                           json={"manual_id": manual["id"], "version": 1})
    assert r.status_code == 403
    # Y la lista de cada técnico es la suya.
    await cliente.post("/api/biblioteca/offline", headers=await auth(TEC),
                       json={"manual_id": manual["id"], "version": 1, "dispositivo_id": "celular-tec1"})
    de_otro = (await cliente.get("/api/biblioteca/offline", headers=await auth(TEC2))).json()
    assert manual["id"] not in {g["id"] for g in de_otro}


async def test_pedir_dos_recursos_a_la_vez_se_rechaza(cliente, auth, datos):
    tipo = await tipo_equipo_id(cliente, auth)
    manual = await subir_manual(cliente, auth, tipo, "Manual validacion offline")
    contrato = await contrato_demo(cliente, auth)
    contenido = (await cliente.post("/api/biblioteca/contenido", headers=await auth(AE),
                                    json={"tipo_equipo_id": tipo, "contrato_id": contrato["id"],
                                          "titulo": "Para validar", "puntos_revision": [
                                              {"descripcion": "Punto único"}]})).json()["contenido"]
    r = await cliente.post("/api/biblioteca/offline", headers=await auth(TEC),
                           json={"manual_id": manual["id"], "contenido_id": contenido["id"], "version": 1})
    assert r.status_code == 422
    r = await cliente.post("/api/biblioteca/offline", headers=await auth(TEC), json={"version": 1})
    assert r.status_code == 422
