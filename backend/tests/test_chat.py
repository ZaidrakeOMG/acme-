"""Chat archivado por folio (§6.8.1): tres chats automáticos con participantes fijos, permisos para agregar, lectura solo de
participantes (RLS), inmutabilidad en folio cerrado con evidencia posterior, eventos de sistema, WebSocket y SSE."""
import json
import uuid

import pytest
from sqlalchemy import text

from core.db import nueva_sesion
from core.rls import CONTEXTO_SISTEMA, ContextoRLS
from tests.conftest import _TOKENS
from tests.folios_utiles import (
    AE, AP, AUN, DES, MC, OP, OTRO_AE, SA, SUPO, TEC, TEC2, accion, autorizar_sin_flujo, capturar, detalle, tecnico_con_habilidades,
)

SUPP = "supervisor.prestador@acma.dev"


async def chats_de(cliente, auth, folio_id, email):
    r = await cliente.get(f"/api/folios/{folio_id}/chats", headers=await auth(email))
    assert r.status_code == 200, r.text
    return {c["canal"]: c for c in r.json()}


async def enviar(cliente, auth, email, chat_id, texto="hola", esperado=201, **extra):
    r = await cliente.post(f"/api/chats/{chat_id}/mensajes", headers=await auth(email), json={"id_cliente": str(uuid.uuid4()), "contenido_texto": texto, **extra})
    assert r.status_code == esperado, r.text
    return r.json()


async def test_tres_chats_con_participantes_fijos_y_eventos(cliente, auth, datos):
    f = await autorizar_sin_flujo(cliente, auth, datos, OP)
    chats = await chats_de(cliente, auth, f["id"], OP)
    assert set(chats) == {"campo", "operativo", "interno"}
    campo, operativo, interno = chats["campo"], chats["operativo"], chats["interno"]
    assert campo["es_participante"] and {p["rol"] for p in campo["participantes"]} == {"operador"} and all(p["fijo"] for p in campo["participantes"])
    assert not operativo["es_participante"] and {p["rol"] for p in operativo["participantes"]} == {"admin_un"}
    assert {p["rol"] for p in interno["participantes"]} == {"admin_prestador"}
    # El operador no lee el canal operativo; sí el de campo (con el evento de captura).
    assert (await cliente.get(f"/api/chats/{operativo['id']}/mensajes", headers=await auth(OP))).status_code == 403
    msgs = (await cliente.get(f"/api/chats/{campo['id']}/mensajes", headers=await auth(OP))).json()
    assert [m["tipo"] for m in msgs] == ["sistema"] and "capturado" in msgs[0]["contenido_texto"]
    # Asignar: el técnico entra al canal campo y el despachador a operativo/interno; evento en campo y operativo.
    tec = await tecnico_con_habilidades(cliente, auth, TEC, ["refrigeracion", "electricidad"])
    await accion(cliente, auth, DES, f["id"], "asignar", {"tecnico_id": tec})
    chats = await chats_de(cliente, auth, f["id"], DES)
    assert {p["rol"] for p in chats["campo"]["participantes"]} == {"operador", "tecnico"}
    assert chats["operativo"]["es_participante"] and chats["interno"]["es_participante"]
    msgs = (await cliente.get(f"/api/chats/{chats['campo']['id']}/mensajes", headers=await auth(TEC))).json()
    assert any(m["tipo"] == "sistema" and "asignado" in m["contenido_texto"] and "Tomás" in m["contenido_texto"] for m in msgs)
    assert any(m["datos_json"].get("tipo_evento") == "folio.asignado" for m in (await cliente.get(f"/api/chats/{chats['operativo']['id']}/mensajes", headers=await auth(DES))).json())
    await accion(cliente, auth, TEC, f["id"], "en-camino")
    await accion(cliente, auth, TEC, f["id"], "confirmar-llegada")
    eventos = [m["datos_json"]["tipo_evento"] for m in (await cliente.get(f"/api/chats/{chats['campo']['id']}/mensajes", headers=await auth(OP))).json() if m["tipo"] == "sistema"]
    assert eventos == ["folio.capturado", "folio.asignado", "folio.en_camino", "folio.en_ejecucion"]
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        n = (await db.execute(text("SELECT count(*) FROM chat_eventos_sistema e JOIN chats c ON c.id = e.chat_id WHERE c.folio_id = :f"), {"f": f["id"]})).scalar()
    assert n >= 7


async def test_mensajes_doble_timestamp_idempotencia_y_leido(cliente, auth, datos):
    f = await capturar(cliente, auth, datos, OP)
    campo = (await chats_de(cliente, auth, f["id"], OP))["campo"]
    idc = str(uuid.uuid4())
    m = await enviar(cliente, auth, OP, campo["id"], "Enviado sin señal", id_cliente=idc, timestamp_dispositivo="2026-10-27T08:00:00Z")
    assert m["timestamp_dispositivo"].startswith("2026-10-27T08:00:00") and m["timestamp_servidor"] > m["timestamp_dispositivo"] and m["duplicado"] is False
    rep = await enviar(cliente, auth, OP, campo["id"], "Enviado sin señal", id_cliente=idc, timestamp_dispositivo="2026-10-27T08:00:00Z")
    assert rep["id"] == m["id"] and rep["duplicado"] is True
    assert (await cliente.post(f"/api/chats/{campo['id']}/mensajes", headers=await auth(OP), json={"id_cliente": str(uuid.uuid4()), "contenido_texto": "  "})).status_code == 422
    # Admin UN agrega a otro operador de la misma UN; este lee y marca leído.
    otro = (await cliente.post("/api/usuarios", headers=await auth(AE), json={"email": f"op2-{uuid.uuid4().hex[:5]}@acma.dev", "nombre": "Otro Operador", "rol": "operador",
                                                                           "contrasena": datos["contrasena"]}))
    assert otro.status_code == 201, otro.text
    uid = otro.json()["id"]
    assert (await cliente.post(f"/api/chats/{campo['id']}/participantes", headers=await auth(AUN), json={"usuario_id": uid})).status_code == 422  # sin UN asignada
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:  # se asigna a SUC-001 sin tocar las asignaciones existentes
        await db.execute(text("INSERT INTO usuario_un (tenant_id, usuario_id, unidad_id) VALUES (:t, :u, :un)"), {"t": datos["tenant"], "u": uid, "un": datos["unidades"][0]})
        await db.commit()
    r = await cliente.post(f"/api/chats/{campo['id']}/participantes", headers=await auth(AUN), json={"usuario_id": uid})
    assert r.status_code == 201 and any(p["usuario_id"] == uid and not p["fijo"] for p in r.json()["participantes"])
    n = await cliente.post(f"/api/chats/{campo['id']}/leido", headers=await auth(OP), json={})
    assert n.status_code == 200
    msgs = (await cliente.get(f"/api/chats/{campo['id']}/mensajes", headers=await auth(OP))).json()
    assert all(str(datos["tenant"]) or True for _ in msgs) and all(m["leido_por_json"] for m in msgs if m["tipo"] != "sistema")
    assert (await cliente.delete(f"/api/chats/{campo['id']}/participantes/{uid}", headers=await auth(AUN))).status_code == 200
    assert (await cliente.delete(f"/api/chats/{campo['id']}/participantes/{f['capturado_por']}", headers=await auth(AUN))).json()["codigo"] == "PARTICIPANTE_FIJO"


async def test_permisos_para_agregar_por_canal(cliente, auth, datos):
    f = await capturar(cliente, auth, datos, OP)
    chats = await chats_de(cliente, auth, f["id"], AP)
    usuarios = {u["rol"]: u for u in (await cliente.get("/api/usuarios", headers=await auth(SA), params={"limite": 500})).json() if u["email"].endswith("@acma.dev") and "otro" not in u["email"]}
    async def agregar(email, canal, rol, esperado):
        r = await cliente.post(f"/api/chats/{chats[canal]['id']}/participantes", headers=await auth(email), json={"usuario_id": usuarios[rol]["id"]})
        assert r.status_code == esperado, (email, canal, rol, r.text)
    # Campo: admin prestador/despachador agregan técnicos; admin UN operadores; nadie agrega admin_empresa.
    await agregar(DES, "campo", "tecnico", 201)
    await agregar(OP, "campo", "tecnico", 403)
    await agregar(AP, "campo", "admin_empresa", 403)
    await agregar(AUN, "campo", "tecnico", 403)
    # Operativo: solo admin prestador, cualquier rol del tenant o del prestador.
    await agregar(AP, "operativo", "supervisor_operadores", 201)
    await agregar(AP, "operativo", "mesa_control", 201)
    await agregar(DES, "operativo", "admin_empresa", 403)
    # Interno: admin prestador agrega al supervisor del prestador; nunca roles del tenant.
    await agregar(AP, "interno", "supervisor_prestador", 201)
    await agregar(AP, "interno", "admin_un", 403)
    # El otro prestador no puede tocar chats ajenos.
    r = await cliente.post(f"/api/chats/{chats['interno']['id']}/participantes", headers=await auth("admin.otroprestador@acma.dev"), json={"usuario_id": usuarios["tecnico"]["id"]})
    assert r.status_code in (403, 404)


async def test_lectura_limitada_a_participantes_por_rls(cliente, auth, datos):
    f = await capturar(cliente, auth, datos, OP)
    chats = await chats_de(cliente, auth, f["id"], OP)
    await enviar(cliente, auth, OP, chats["campo"]["id"], "solo para el campo")
    async def ver(ctx: ContextoRLS) -> int:
        async with nueva_sesion(ctx) as db:
            return (await db.execute(text("SELECT count(*) FROM chat_mensajes WHERE chat_id = :c"), {"c": chats["campo"]["id"]})).scalar()
    usuarios = {u["email"]: u["id"] for u in (await cliente.get("/api/usuarios", headers=await auth(SA), params={"limite": 500})).json()}
    assert await ver(ContextoRLS(usuario_id=usuarios[OP], tenant_id=datos["tenant"], rol="operador")) >= 2
    assert await ver(ContextoRLS(usuario_id=usuarios[AE], tenant_id=datos["tenant"], rol="admin_empresa")) == 0   # mismo tenant, no participante
    assert await ver(ContextoRLS(usuario_id=usuarios[DES], prestador_id=datos["prestador"], rol="despachador")) == 0
    assert await ver(ContextoRLS(rol="superadmin")) >= 2
    # Por API: 403 para no participantes y 404 para otro tenant.
    assert (await cliente.get(f"/api/chats/{chats['campo']['id']}/mensajes", headers=await auth(AE))).status_code == 403
    assert (await cliente.get(f"/api/folios/{f['id']}/chats", headers=await auth(OTRO_AE))).status_code == 404


async def test_inmutabilidad_en_folio_cerrado_y_evidencia_posterior(cliente, auth, datos):
    from tests.test_folio_estados import _respuesta_atencion_con_firma
    from tests.test_formularios_evidencias import png

    f = await autorizar_sin_flujo(cliente, auth, datos, OP)
    tec = await tecnico_con_habilidades(cliente, auth, TEC, ["refrigeracion", "electricidad"])
    await accion(cliente, auth, DES, f["id"], "asignar", {"tecnico_id": tec})
    await accion(cliente, auth, TEC, f["id"], "en-camino")
    await accion(cliente, auth, TEC, f["id"], "confirmar-llegada")
    campo = (await chats_de(cliente, auth, f["id"], TEC))["campo"]
    m = await enviar(cliente, auth, TEC, campo["id"], "Trabajo terminado")
    rid = await _respuesta_atencion_con_firma(cliente, auth, datos, f)
    await cliente.post(f"/api/folios/{f['id']}/atencion", headers=await auth(TEC), json={"respuesta_id": rid})
    await accion(cliente, auth, TEC, f["id"], "cerrar")
    # Texto rechazado; imagen aceptada como evidencia posterior; el mensaje viejo no se edita ni borra (ni como sistema).
    assert (await enviar(cliente, auth, OP, campo["id"], "¿Sigue ahí?", esperado=409))["codigo"] == "CHAT_CERRADO"
    r = await cliente.post(f"/api/chats/{campo['id']}/mensajes/archivo", headers=await auth(OP), data={"id_cliente": str(uuid.uuid4()), "tipo": "imagen", "contenido_texto": "Foto del equipo al día siguiente"},
                           files={"archivo": ("despues.png", png(), "image/png")})
    assert r.status_code == 201 and r.json()["datos_json"]["evidencia_posterior"] is True and r.json()["archivos"][0]["tipo_mime"] == "image/png"
    arch = await cliente.get(f"/api/chats/{campo['id']}/archivos/{r.json()['archivos'][0]['id']}", headers=await auth(TEC))
    assert arch.status_code == 200 and arch.headers["content-type"] == "image/png"
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        with pytest.raises(Exception, match="inmutables"):
            await db.execute(text("UPDATE chat_mensajes SET contenido_texto = 'editado' WHERE id = :i"), {"i": m["id"]})
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        with pytest.raises(Exception, match="inmutables"):
            await db.execute(text("DELETE FROM chat_mensajes WHERE id = :i"), {"i": m["id"]})
    assert (await cliente.post(f"/api/chats/{campo['id']}/leido", headers=await auth(OP), json={})).status_code == 200  # solo leído sí


async def test_chat_archivado_si_se_cancela_antes_de_asignar(cliente, auth, datos):
    f = await capturar(cliente, auth, datos, OP)
    campo = (await chats_de(cliente, auth, f["id"], OP))["campo"]
    await enviar(cliente, auth, OP, campo["id"], "se va a cancelar")
    await accion(cliente, auth, DES, f["id"], "cancelar", {"razon": "Capturado por error"})
    chats = await chats_de(cliente, auth, f["id"], OP)
    assert all(c["estado"] == "archivado" for c in chats.values())
    assert (await cliente.get(f"/api/chats/{campo['id']}/mensajes", headers=await auth(OP))).json() == []
    assert (await enviar(cliente, auth, OP, campo["id"], "hola", esperado=409))["codigo"] == "CHAT_ARCHIVADO"
    assert len((await cliente.get(f"/api/chats/{campo['id']}/mensajes", headers=await auth(SA))).json()) >= 2  # superadmin audita


async def test_websocket_dos_clientes_y_sse(cliente, auth, datos):
    from starlette.testclient import TestClient

    from main import app

    f = await capturar(cliente, auth, datos, OP)
    campo = (await chats_de(cliente, auth, f["id"], OP))["campo"]
    tok_op = _TOKENS[OP]["access_token"]
    await auth(AE)
    tok_ae = _TOKENS[AE]["access_token"]
    with TestClient(app) as c:
        # No participante → cierre 4403.
        with pytest.raises(Exception):
            with c.websocket_connect(f"/ws/chats/{campo['id']}?token={tok_ae}") as ws:
                ws.receive_text()
        with c.websocket_connect(f"/ws/chats/{campo['id']}?token={tok_op}") as ws1, c.websocket_connect(f"/ws/chats/{campo['id']}?token={tok_op}") as ws2:
            assert json.loads(ws1.receive_text())["evento"] == "conectado" and json.loads(ws2.receive_text())["evento"] == "conectado"
            ws1.send_text("ping")
            assert json.loads(ws1.receive_text())["evento"] == "pong"
            r = c.post(f"/api/chats/{campo['id']}/mensajes", headers={"Authorization": f"Bearer {tok_op}"},
                       json={"id_cliente": str(uuid.uuid4()), "contenido_texto": "en vivo"})
            assert r.status_code == 201, r.text
            for ws in (ws1, ws2):
                ev = json.loads(ws.receive_text())
                assert ev["evento"] == "mensaje" and ev["mensaje"]["contenido_texto"] == "en vivo" and ev["mensaje"]["usuario_nombre"] == "Olga Operadora"
            c.post(f"/api/chats/{campo['id']}/leido", headers={"Authorization": f"Bearer {tok_op}"}, json={})
        # SSE: recibe el evento de conexión; el envío sigue siendo HTTP POST.
        with c.stream("GET", f"/api/chats/{campo['id']}/stream?token={tok_op}") as r:
            assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
            primera = next(r.iter_lines())
            assert "conectado" in primera
