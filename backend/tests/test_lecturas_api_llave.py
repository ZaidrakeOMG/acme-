"""Llaves de API por cliente y lecturas en lote (§6.9.2 «Importación desde ERP o SCADA»). F2-04.

La llave: se muestra una sola vez, se guarda hasheada, sirve **solo** para registrar lecturas, alcanza solo a los
equipos de su cliente, se revoca sin borrarse y deja huella en la auditoría. El lote: cada fila se resuelve aparte,
con los mismos estados que la captura manual (aplicada, duplicada, en revisión, rechazada).
"""
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select, text

from core.db import nueva_sesion
from core.rls import CONTEXTO_SISTEMA
from tests.folios_utiles import AE, AP, AUN, DES, OP, OTRO_AE, SA, TEC
from tests.medidores_utiles import (
    alta_medidor, crear_llave, equipo_con_medidor, estado_medidor, incremento_esperado, nuevo_tipo_medidor,
)

RUTA = "/api/medidores/lecturas/lote"


def _fila(equipo, tipo, valor, *, horas_atras=1):
    return {"equipo_codigo": equipo["codigo"], "tipo_medidor": tipo["nombre"], "valor": str(valor),
            "timestamp": (datetime.now(UTC) - timedelta(hours=horas_atras)).isoformat()}


async def test_crear_ver_una_vez_y_revocar(cliente, auth, datos):
    creada = await crear_llave(cliente, auth, nombre="SCADA planta Torreón")
    secreto = creada["secreto"]
    assert secreto.startswith("acma_") and len(secreto) > 40
    assert creada["llave"]["prefijo"] == secreto[:8] and creada["llave"]["permisos_json"] == ["medidores.lecturas"]
    # El listado no vuelve a mostrar la llave: solo su prefijo y su uso.
    listado = (await cliente.get("/api/medidores/llaves", headers=await auth(AE))).json()
    fila = next(x for x in listado if x["id"] == creada["llave"]["id"])
    assert "secreto" not in fila and fila["prefijo"] == secreto[:8] and fila["activa"] is True and fila["usos"] == 0
    # Y en la base solo vive su hash.
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        guardado = (await db.execute(text("SELECT llave_hash FROM llaves_api_tenant WHERE id = :i"),
                                     {"i": creada["llave"]["id"]})).scalar()
        assert guardado and secreto not in guardado and len(guardado) == 64
    r = await cliente.delete(f"/api/medidores/llaves/{creada['llave']['id']}", headers=await auth(AE))
    assert r.status_code == 200
    listado = (await cliente.get("/api/medidores/llaves", headers=await auth(AE))).json()
    fila = next(x for x in listado if x["id"] == creada["llave"]["id"])
    assert fila["activa"] is False and fila["revocada_at"] is not None


async def test_solo_el_admin_empresa_y_el_superadmin_administran_llaves(cliente, auth, datos):
    for email in (AP, DES, AUN, OP, TEC):
        r = await cliente.post("/api/medidores/llaves", headers=await auth(email), json={"nombre": "Intento"})
        assert r.status_code in (403, 404), (email, r.text)
        assert (await cliente.get("/api/medidores/llaves", headers=await auth(email))).status_code == 403
    # El Superadmin la crea para el cliente que indique.
    r = await cliente.post("/api/medidores/llaves", headers=await auth(SA),
                           json={"nombre": "SCADA del superadmin", "tenant_id": str(datos["tenant"])})
    assert r.status_code == 201 and r.json()["llave"]["tenant_id"] == str(datos["tenant"])


async def test_lote_con_llave_valida(cliente, auth, datos):
    equipo, medidor, tipo = await equipo_con_medidor(cliente, auth, datos, metodo_actualizacion="importacion",
                                                     factor_salto="100")
    await incremento_esperado(cliente, auth, medidor, 100)
    llave = await crear_llave(cliente, auth)
    cabecera = {"X-ACMA-Llave": llave["secreto"]}
    lote = {"lecturas": [_fila(equipo, tipo, 150, horas_atras=3)]}
    r = await cliente.post(RUTA, headers=cabecera, json=lote)
    assert r.status_code == 200, r.text
    assert r.json()["aplicadas"] == 1 and r.json()["resultados"][0]["estado"] == "aplicada"
    assert Decimal((await estado_medidor(cliente, auth, equipo["id"]))[0]["valor_actual"]) == 150
    # Idempotente: el mismo lote otra vez no duplica (es lo que hace un SCADA al reintentar).
    r = await cliente.post(RUTA, headers=cabecera, json=lote)
    assert r.json()["duplicadas"] == 1 and r.json()["aplicadas"] == 0
    # El uso queda contado y en la auditoría.
    fila = next(x for x in (await cliente.get("/api/medidores/llaves", headers=await auth(AE))).json()
                if x["id"] == llave["llave"]["id"])
    assert fila["usos"] == 2 and fila["ultimo_uso_at"] is not None
    r = await cliente.get("/api/auditoria/eventos", headers=await auth(SA),
                          params={"evento_tipo": "medidores.lote_por_llave"})
    assert r.status_code == 200, r.text
    assert any(str(e["recurso_id"]) == llave["llave"]["id"] for e in r.json()), r.json()[:3]


async def test_lote_resuelve_fila_por_fila(cliente, auth, datos):
    equipo, medidor, tipo = await equipo_con_medidor(cliente, auth, datos, metodo_actualizacion="importacion")
    await incremento_esperado(cliente, auth, medidor, 10)
    llave = await crear_llave(cliente, auth)
    cabecera = {"X-ACMA-Llave": llave["secreto"]}
    # Una buena, una de un equipo que no existe, una de un medidor que el equipo no tiene y una con salto absurdo.
    lecturas = [
        _fila(equipo, tipo, 100, horas_atras=10),
        {"equipo_codigo": "NO-EXISTE", "tipo_medidor": tipo["nombre"], "valor": "5"},
        {"equipo_codigo": equipo["codigo"], "tipo_medidor": "Medidor inexistente", "valor": "5"},
        _fila(equipo, tipo, 99999, horas_atras=1),
    ]
    r = await cliente.post(RUTA, headers=cabecera, json={"lecturas": lecturas})
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    estados = [x["estado"] for x in cuerpo["resultados"]]
    assert estados == ["aplicada", "rechazada", "rechazada", "en_revision"], cuerpo
    assert cuerpo["aplicadas"] == 1 and cuerpo["rechazadas"] == 2 and cuerpo["en_revision"] == 1
    assert "NO-EXISTE" in cuerpo["resultados"][1]["motivo"].upper() or "no existe" in cuerpo["resultados"][1]["motivo"]
    assert "Medidor inexistente" in cuerpo["resultados"][2]["motivo"]
    # La anómala está en la bandeja del despachador, no en el medidor.
    assert Decimal((await estado_medidor(cliente, auth, equipo["id"]))[0]["valor_actual"]) == 100
    bandeja = (await cliente.get("/api/medidores/lecturas/por-revisar", headers=await auth(DES))).json()
    assert any(x["equipo_codigo"] == equipo["codigo"] for x in bandeja)


async def test_llave_revocada_invalida_y_de_otro_cliente(cliente, auth, datos):
    equipo, _medidor, tipo = await equipo_con_medidor(cliente, auth, datos, metodo_actualizacion="importacion")
    # Sin llave y con una sesión sin permiso.
    r = await cliente.post(RUTA, json={"lecturas": [_fila(equipo, tipo, 10)]})
    assert r.status_code == 401, r.text
    r = await cliente.post(RUTA, headers={"X-ACMA-Llave": "acma_inventada"}, json={"lecturas": [_fila(equipo, tipo, 10)]})
    assert r.status_code == 401 and r.json()["codigo"] == "LLAVE_INVALIDA"
    # Revocada.
    llave = await crear_llave(cliente, auth)
    await cliente.delete(f"/api/medidores/llaves/{llave['llave']['id']}", headers=await auth(AE))
    r = await cliente.post(RUTA, headers={"X-ACMA-Llave": llave["secreto"]}, json={"lecturas": [_fila(equipo, tipo, 10)]})
    assert r.status_code == 401 and r.json()["codigo"] == "LLAVE_REVOCADA"
    # La llave del otro cliente no alcanza este equipo: la fila se rechaza (no existe en su universo).
    ajena = await crear_llave(cliente, auth, email=OTRO_AE)
    r = await cliente.post(RUTA, headers={"X-ACMA-Llave": ajena["secreto"]}, json={"lecturas": [_fila(equipo, tipo, 10)]})
    assert r.status_code == 200 and r.json()["rechazadas"] == 1, r.text
    assert r.json()["aplicadas"] == 0


async def test_llave_sin_permiso_para_otra_cosa(cliente, auth, datos):
    """La llave solo registra lecturas: con otro permiso exigido no pasa, y no abre ninguna otra ruta."""
    from services import medidores_service

    llave = await crear_llave(cliente, auth)
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        from core.errors import ErrorAPI

        resuelta = await medidores_service.resolver_llave(db, llave["secreto"])
        assert resuelta.permisos_json == ["medidores.lecturas"]
        try:
            await medidores_service.resolver_llave(db, llave["secreto"], permiso="folios.crear")
            fallo = False
        except ErrorAPI as e:
            fallo = e.codigo == "LLAVE_SIN_PERMISO" and e.estado == 403
        assert fallo
        await db.rollback()
    # Y la cabecera no autentica ninguna otra ruta de la API.
    for ruta in ("/api/medidores/tipos", "/api/folios", "/api/medidores/llaves"):
        r = await cliente.get(ruta, headers={"X-ACMA-Llave": llave["secreto"]})
        assert r.status_code == 401, (ruta, r.status_code)


async def test_lote_con_sesion_normal(cliente, auth, datos):
    """El mismo endpoint sirve con sesión: es lo que usa la importación por archivo del cliente."""
    equipo, _medidor, tipo = await equipo_con_medidor(cliente, auth, datos, metodo_actualizacion="importacion")
    r = await cliente.post(RUTA, headers=await auth(AE), json={"lecturas": [_fila(equipo, tipo, 42)]})
    assert r.status_code == 200 and r.json()["aplicadas"] == 1, r.text
    # El operador no registra lotes.
    r = await cliente.post(RUTA, headers=await auth(OP), json={"lecturas": [_fila(equipo, tipo, 50)]})
    assert r.status_code == 403, r.text
