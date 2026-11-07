"""Sincronización offline (§6.2): catálogos incrementales con bajas, lote de mutaciones (aplicadas, duplicadas, rechazadas),
client-wins con hora real, server-wins en catálogo, conflictos, idempotencia por id_cliente y por hash de evidencia."""
import base64
import hashlib
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from core.db import nueva_sesion
from core.rls import CONTEXTO_SISTEMA
from tests.folios_utiles import AE, AP, AUN, DES, OP, OTRO_OP, SA, TEC, accion, capturar, detalle, nuevo_equipo, reglas, tecnico_con_habilidades, tipo_falla, REGLAS_DEMO
from tests.test_formularios_evidencias import png


async def sync(cliente, auth, email, mutaciones, dispositivo="disp-prueba"):
    r = await cliente.post("/api/sync/mutaciones", headers=await auth(email), json={"dispositivo_id": dispositivo, "version_app": "0.5", "plataforma": "android", "mutaciones": mutaciones})
    assert r.status_code == 200, r.text
    return r.json()


def mut(tipo, payload, ts="2026-10-27T07:30:00Z", idc=None):
    return {"id_cliente": idc or str(uuid.uuid4()), "tipo": tipo, "timestamp_dispositivo": ts, "payload": payload}


async def test_catalogos_del_operador_incrementales_con_bajas(cliente, auth, datos):
    h = await auth(OP)
    r = await cliente.get("/api/sync/catalogos", headers=h, params={"dispositivo_id": "disp-op", "version_app": "0.5", "plataforma": "android"})
    assert r.status_code == 200, r.text
    paquete = r.json()
    assert [u["codigo"] for u in paquete["unidades"]] == ["SUC-001"]  # solo su UN asignada
    assert all(e["un_id"] == paquete["unidades"][0]["id"] for e in paquete["equipos"]) and any(not e["con_contrato_activo"] for e in paquete["equipos"])
    assert {t["descripcion"] for t in paquete["tipos_falla"]} >= {"No enciende", "No enfría"} and len(paquete["niveles_severidad"]) == 5
    assert any(f["tipo"] == "captura_operador" and f["esquema_json"]["secciones"] for f in paquete["formularios"])
    assert "folios" not in paquete
    # Incremental: desde ahora no hay cambios; al dar de baja un equipo, viene con activo = false.
    desde = paquete["servidor_at"]
    vacio = (await cliente.get("/api/sync/catalogos", headers=h, params={"desde": desde})).json()
    assert vacio["equipos"] == [] and vacio["unidades"] == [] and vacio["tipos_falla"] == []
    e = await nuevo_equipo(cliente, auth, datos)
    assert (await cliente.patch(f"/api/catalogos/equipos/{e['id']}", headers=await auth(AE), json={"estado": "baja"})).status_code == 200
    cambios = (await cliente.get("/api/sync/catalogos", headers=h, params={"desde": desde})).json()
    assert [x for x in cambios["equipos"] if x["id"] == e["id"] and x["activo"] is False]
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        d = (await db.execute(text("SELECT ultimo_sync_at, version_app, plataforma FROM sincronizacion_dispositivos WHERE dispositivo_id = 'disp-op'"))).one()
    assert d.ultimo_sync_at and d.version_app == "0.5" and d.plataforma == "android"


async def test_catalogos_del_tecnico_con_formulario_de_atencion(cliente, auth, datos):
    tec = await tecnico_con_habilidades(cliente, auth, TEC, ["refrigeracion", "electricidad"])
    await reglas(cliente, auth, [])
    try:
        f = await capturar(cliente, auth, datos, OP)
    finally:
        await reglas(cliente, auth, REGLAS_DEMO)
    await accion(cliente, auth, DES, f["id"], "asignar", {"tecnico_id": tec})
    paquete = (await cliente.get("/api/sync/catalogos", headers=await auth(TEC), params={"dispositivo_id": "disp-tec"})).json()
    assert f["id"] in paquete["folios_ids"] and all(x["tecnico_id"] == tec for x in paquete["folios"])
    fid = paquete["formulario_por_folio"][f["id"]]
    assert any(x["id"] == fid and x["tipo"] == "atencion_tecnico" and "Cliente Demo" in x["nombre"] for x in paquete["formularios"])  # el específico del tenant gana
    assert paquete["refacciones"] == [] and "unidades" not in paquete
    # F2-01: la biblioteca viaja como metadatos (sin archivos) y marca lo que es del tipo de equipo de sus folios.
    assert paquete["biblioteca"] and all({"clase", "id", "version", "activo", "de_mis_folios"} <= set(b)
                                         for b in paquete["biblioteca"])
    assert all("archivo" not in b and "contenido" not in b for b in paquete["biblioteca"])


async def test_lote_aplicadas_duplicadas_y_rechazadas_en_orden(cliente, auth, datos):
    e = await nuevo_equipo(cliente, auth, datos, criticidad="D")
    tf = await tipo_falla(cliente, auth)
    id_folio = str(uuid.uuid4())
    crear = mut("crear_folio", {"un_id": e["un_id"], "equipo_id": e["id"], "tipo_falla_id": tf["id"], "descripcion": "Capturado sin señal en campo", "confirmacion_un": True,
                                "confirmacion_un_geolat": 19.43, "confirmacion_un_geolng": -99.13}, ts="2026-10-27T06:15:00Z", idc=id_folio)
    mal = mut("transicion", {"folio_id": id_folio, "estado": "cerrado"}, ts="2026-10-27T06:20:00Z")           # no permitido para el operador
    bien = mut("transicion", {"folio_id": str(uuid.uuid4()), "estado": "cancelado"})                            # folio inexistente
    r = await sync(cliente, auth, OP, [crear, mal, bien, crear])
    assert [x["resultado"] for x in r] == ["aplicada", "rechazada", "rechazada", "duplicada"]
    assert r[1]["codigo"] == "TRANSICION_NO_PERMITIDA" and r[2]["codigo"] == "NO_ENCONTRADO" and r[3]["entidad_id"] == r[0]["entidad_id"]
    d = await detalle(cliente, auth, r[0]["entidad_id"])
    assert d["folio"]["capturado_at"].startswith("2026-10-27T06:15") and d["folio"]["estado"] == "en_revision"  # client-wins: hora real de captura
    # Reenviar el mismo lote: todo duplicado, nada se repite.
    r2 = await sync(cliente, auth, OP, [crear, mal])
    assert [x["resultado"] for x in r2] == ["duplicada", "duplicada"] and r2[1]["codigo"] == "TRANSICION_NO_PERMITIDA"
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        n = (await db.execute(text("SELECT count(*) FROM folios WHERE descripcion = 'Capturado sin señal en campo'"))).scalar()
        bit = (await db.execute(text("SELECT resultado, tipo FROM sincronizacion_mutaciones WHERE id_cliente = :i"), {"i": id_folio})).one()
    assert n == 1 and bit.resultado == "aplicada" and bit.tipo == "crear_folio"


async def test_cierre_offline_conserva_hora_real_y_registra_conflicto(cliente, auth, datos):
    from tests.test_folio_estados import _respuesta_atencion_con_firma

    tec = await tecnico_con_habilidades(cliente, auth, TEC, ["refrigeracion", "electricidad"])
    await reglas(cliente, auth, [])
    try:
        f = await capturar(cliente, auth, datos, AE)
    finally:
        await reglas(cliente, auth, REGLAS_DEMO)
    await accion(cliente, auth, DES, f["id"], "asignar", {"tecnico_id": tec})
    # El técnico trabaja sin señal: en camino y llegada con hora real; luego atención (con firma del operador en su
    # dispositivo) y el cierre encolado con la hora real de cierre.
    r = await sync(cliente, auth, TEC, [
        mut("transicion", {"folio_id": f["id"], "estado": "en_camino"}, ts="2026-10-27T09:00:00Z"),
        mut("transicion", {"folio_id": f["id"], "estado": "en_ejecucion", "contexto": {"geolat": 19.43, "geolng": -99.13}}, ts="2026-10-27T09:40:00Z"),
    ])
    assert [x["resultado"] for x in r] == ["aplicada", "aplicada"], r
    rid = await _respuesta_atencion_con_firma(cliente, auth, datos, f)
    assert (await cliente.post(f"/api/folios/{f['id']}/atencion", headers=await auth(TEC), json={"respuesta_id": rid})).status_code == 201
    r = await sync(cliente, auth, TEC, [mut("transicion", {"folio_id": f["id"], "estado": "cerrado", "notas": "Cerrado en sitio"}, ts="2026-10-27T11:05:00Z")])
    assert r[0]["resultado"] == "aplicada", r
    d = await detalle(cliente, auth, f["id"])
    assert d["folio"]["estado"] == "cerrado" and d["folio"]["fecha_inicio_atencion"].startswith("2026-10-27T09:40") and d["folio"]["fecha_cierre"].startswith("2026-10-27T11:05")
    cierre = [h for h in d["historial"] if h["estado_nuevo"] == "cerrado"][0]
    assert cierre["datos_contexto_json"]["timestamp_dispositivo"].startswith("2026-10-27T11:05")
    # El servidor había cambiado después de la hora del dispositivo (asignación, firma) → conflicto client_wins registrado.
    conflictos = (await cliente.get("/api/sync/conflictos", headers=await auth(TEC))).json()
    assert any(c["entidad"] == "folio" and c["entidad_id"] == f["id"] and c["regla_aplicada"] == "client_wins" for c in conflictos)


async def test_respuesta_y_evidencia_offline_idempotentes(cliente, auth, datos):
    from tests.test_formularios import crear_formulario, publicar

    esquema = {"secciones": [{"clave": "s", "titulo": "S", "campos": [
        {"clave": "nota", "tipo": "texto", "etiqueta": "Nota", "obligatorio": True, "config": {"longitud_min": 2, "longitud_max": 200}},
        {"clave": "foto", "tipo": "fotografia", "etiqueta": "Foto", "config": {"cantidad_min": 0, "cantidad_max": 3, "calidad": {"tamano_minimo_kb": 0, "resolucion_minima_ancho": 1, "resolucion_minima_alto": 1}}},
    ]}]}
    form = await crear_formulario(cliente, auth, AP, esquema=esquema, rol_destino=["tecnico"])
    await publicar(cliente, auth, form["id"])
    id_resp = str(uuid.uuid4())
    guardar = mut("guardar_respuesta", {"respuesta_id": id_resp, "crear": {"formulario_id": form["id"], "origen": "independiente", "contexto": {"tenant_id": str(datos["tenant"])}},
                                        "respuestas": {"nota": "borrador offline"}}, ts="2026-10-27T10:00:00Z", idc=id_resp)
    contenido = png(600, 400)
    hash_ = hashlib.sha256(contenido).hexdigest()
    evid = mut("subir_evidencia", {"respuesta_id": id_resp, "campo_clave": "foto", "nombre": "foto.png", "mime": "image/png", "hash_sha256": hash_,
                                   "contenido_base64": base64.b64encode(contenido).decode()})
    guardar2 = mut("guardar_respuesta", {"respuesta_id": id_resp, "respuestas": {"nota": "versión final"}, "version_hash": "hash-viejo"}, ts="2026-10-27T10:20:00Z")
    enviar = mut("enviar_respuesta", {"respuesta_id": id_resp}, ts="2026-10-27T10:30:00Z")
    r = await sync(cliente, auth, TEC, [guardar, evid, guardar2, enviar])
    assert [x["resultado"] for x in r] == ["aplicada", "aplicada", "aplicada", "aplicada"], r
    rid = r[0]["entidad_id"]
    resp = (await cliente.get(f"/api/formularios/respuestas/{rid}", headers=await auth(TEC))).json()
    assert resp["estado"] == "enviado" and resp["respuestas_json"]["nota"] == "versión final" and resp["enviado_at"].startswith("2026-10-27T10:30")
    evidencias = (await cliente.get(f"/api/formularios/respuestas/{rid}/evidencias", headers=await auth(TEC))).json()
    assert len(evidencias) == 1 and evidencias[0]["hash_sha256"] == hash_
    conflictos = (await cliente.get("/api/sync/conflictos", headers=await auth(TEC))).json()
    assert any(c["entidad"] == "formulario_respuesta" and c["entidad_id"] == rid and c["datos_cliente_json"]["version_hash"] == "hash-viejo" for c in conflictos)
    # Mismo lote otra vez: duplicadas; una evidencia con el mismo hash pero otro id_cliente tampoco se repite.
    r2 = await sync(cliente, auth, TEC, [guardar, evid, enviar, mut("subir_evidencia", evid["payload"])])
    assert [x["resultado"] for x in r2] == ["duplicada", "duplicada", "duplicada", "duplicada"]
    assert len((await cliente.get(f"/api/formularios/respuestas/{rid}/evidencias", headers=await auth(TEC))).json()) == 1


async def test_evidencia_en_dos_pasos_con_reintento(cliente, auth, datos):
    from tests.test_formularios import crear_formulario, publicar

    esquema = {"secciones": [{"clave": "s", "titulo": "S", "campos": [{"clave": "foto", "tipo": "fotografia", "etiqueta": "Foto",
                                                                        "config": {"cantidad_min": 0, "cantidad_max": 2, "calidad": {"tamano_minimo_kb": 0, "resolucion_minima_ancho": 1, "resolucion_minima_alto": 1}}}]}]}
    form = await crear_formulario(cliente, auth, AP, esquema=esquema, rol_destino=["tecnico"])
    await publicar(cliente, auth, form["id"])
    h = await auth(TEC)
    rid = (await cliente.post(f"/api/formularios/{form['id']}/respuestas", headers=h, json={"contexto": {"tenant_id": str(datos["tenant"])}})).json()["id"]
    contenido = png(300, 200)
    hash_ = hashlib.sha256(contenido).hexdigest()
    idc = str(uuid.uuid4())
    ini = await cliente.post("/api/sync/evidencias/iniciar", headers=h, json={"id_cliente": idc, "respuesta_id": rid, "campo_clave": "foto", "nombre": "a.png", "mime": "image/png", "bytes": len(contenido), "hash_sha256": hash_})
    assert ini.status_code == 200 and ini.json()["estado"] == "pendiente" and ini.json()["subir_a"] == f"/api/sync/evidencias/{idc}/archivo"
    malo = await cliente.put(ini.json()["subir_a"], headers=h, data={"respuesta_id": rid, "campo_clave": "foto", "hash_sha256": "0" * 64}, files={"archivo": ("a.png", contenido, "image/png")})
    assert malo.status_code == 422 and malo.json()["codigo"] == "HASH_INVALIDO"
    ok = await cliente.put(ini.json()["subir_a"], headers=h, data={"respuesta_id": rid, "campo_clave": "foto", "hash_sha256": hash_, "timestamp_dispositivo": "2026-10-27T12:00:00Z"}, files={"archivo": ("a.png", contenido, "image/png")})
    assert ok.status_code == 200 and ok.json()["hash_sha256"] == hash_ and ok.json()["calidad"]["resultado"] == "aplicada"
    rep = await cliente.put(ini.json()["subir_a"], headers=h, data={"respuesta_id": rid, "campo_clave": "foto", "hash_sha256": hash_}, files={"archivo": ("a.png", contenido, "image/png")})
    assert rep.status_code == 200 and rep.json()["id"] == ok.json()["id"] and rep.json()["calidad"]["resultado"] == "duplicada"
    ini2 = await cliente.post("/api/sync/evidencias/iniciar", headers=h, json={"id_cliente": str(uuid.uuid4()), "respuesta_id": rid, "campo_clave": "foto", "nombre": "a.png", "mime": "image/png", "bytes": len(contenido), "hash_sha256": hash_})
    assert ini2.json()["estado"] == "existente" and ini2.json()["evidencia_id"] == ok.json()["id"]
    assert (await cliente.post("/api/sync/evidencias/iniciar", headers=h, json={"id_cliente": idc, "respuesta_id": rid, "campo_clave": "foto", "nombre": "a.png", "mime": "image/png", "bytes": 1, "hash_sha256": hash_})).json()["estado"] == "duplicada"
    assert len((await cliente.get(f"/api/formularios/respuestas/{rid}/evidencias", headers=h)).json()) == 1


async def test_refaccion_y_mensaje_offline_y_aislamiento(cliente, auth, datos):
    tec = await tecnico_con_habilidades(cliente, auth, TEC, ["refrigeracion", "electricidad"])
    await reglas(cliente, auth, [])
    try:
        f = await capturar(cliente, auth, datos, OP)
    finally:
        await reglas(cliente, auth, REGLAS_DEMO)
    await accion(cliente, auth, DES, f["id"], "asignar", {"tecnico_id": tec})
    chats = {c["canal"]: c for c in (await cliente.get(f"/api/folios/{f['id']}/chats", headers=await auth(TEC))).json()}
    idm = str(uuid.uuid4())
    r = await sync(cliente, auth, TEC, [
        mut("agregar_refaccion", {"folio_id": f["id"], "descripcion": "Capacitor 35 µF", "cantidad": 1, "origen": "caja_chica", "costo_unitario": 180.5}),
        mut("mensaje_chat", {"chat_id": chats["campo"]["id"], "contenido_texto": "Ya cambié el capacitor"}, ts="2026-10-27T13:00:00Z", idc=idm),
        mut("mensaje_chat", {"chat_id": chats["operativo"]["id"], "contenido_texto": "no soy participante"}),
    ])
    assert [x["resultado"] for x in r] == ["aplicada", "aplicada", "rechazada"] and r[2]["codigo"] == "PROHIBIDO"
    d = await detalle(cliente, auth, f["id"])
    assert d["refacciones"][0]["descripcion"] == "Capacitor 35 µF" and d["refacciones"][0]["origen"] == "caja_chica"
    msgs = (await cliente.get(f"/api/chats/{chats['campo']['id']}/mensajes", headers=await auth(OP))).json()
    mio = next(m for m in msgs if m["id_cliente"] == idm)
    assert mio["timestamp_dispositivo"].startswith("2026-10-27T13:00") and mio["timestamp_servidor"] > mio["timestamp_dispositivo"]
    assert (await sync(cliente, auth, TEC, [mut("mensaje_chat", {"chat_id": chats["campo"]["id"], "contenido_texto": "repetido"}, idc=idm)]))[0]["resultado"] == "duplicada"
    # Otro tenant no puede mutar folios ajenos ni ver conflictos de otros usuarios.
    r = await sync(cliente, auth, OTRO_OP, [mut("transicion", {"folio_id": f["id"], "estado": "cancelado", "notas": "x"})])
    assert r[0]["resultado"] == "rechazada" and r[0]["codigo"] == "NO_ENCONTRADO"
    assert (await cliente.get("/api/sync/conflictos", headers=await auth(OTRO_OP))).json() == []
    assert (await cliente.post("/api/sync/mutaciones", headers=await auth(OP), json={"mutaciones": [{"id_cliente": str(uuid.uuid4()), "tipo": "volar", "payload": {}}]})).status_code == 422
