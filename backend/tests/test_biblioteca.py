"""Biblioteca de manuales técnicos (§6.10.4): versiones con historial append-only, permiso del técnico,
enlace firmado y aislamiento entre prestadores. F2-01."""
from sqlalchemy import text

from core.db import nueva_sesion
from core.rls import CONTEXTO_SISTEMA
from tests.capacitacion_utiles import pdf_falso, subir_manual, tipo_equipo_id
from tests.folios_utiles import AE, AP, DES, MC, OP, OTRO_AP, SA, TEC


async def test_subir_manual_y_listarlo_por_tipo_de_equipo(cliente, auth, datos):
    tipo = await tipo_equipo_id(cliente, auth)
    manual = await subir_manual(cliente, auth, tipo, "Manual de prueba", categoria="ficha_tecnica")
    assert manual["version"] == 1 and manual["bytes"] > 0 and len(manual["hash_sha256"]) == 64
    assert manual["tipo_equipo"] == "Refrigerador vertical"

    lista = (await cliente.get("/api/biblioteca/manuales", headers=await auth(AP),
                               params={"tipo_equipo_id": tipo})).json()
    assert manual["id"] in {m["id"] for m in lista}
    # Búsqueda por título.
    hallados = (await cliente.get("/api/biblioteca/manuales", headers=await auth(MC),
                                  params={"q": "manual de prueba"})).json()
    assert any(m["id"] == manual["id"] for m in hallados)


async def test_tipos_y_tamanos_no_permitidos(cliente, auth, datos):
    tipo = await tipo_equipo_id(cliente, auth)
    r = await cliente.post("/api/biblioteca/manuales", headers=await auth(AP),
                           data={"tipo_equipo_id": tipo, "titulo": "Hoja de cálculo"},
                           files={"archivo": ("x.xlsx", b"PK\x03\x04datos",
                                              "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code == 422 and r.json()["codigo"] == "TIPO_ARCHIVO_INVALIDO"
    r = await cliente.post("/api/biblioteca/manuales", headers=await auth(AP),
                           data={"tipo_equipo_id": tipo, "titulo": "Vacío"},
                           files={"archivo": ("x.pdf", b"", "application/pdf")})
    assert r.status_code == 422 and r.json()["codigo"] == "ARCHIVO_VACIO"


async def test_la_version_nueva_reemplaza_y_conserva_el_historial(cliente, auth, datos):
    """§6.10.4: «cada nueva versión reemplaza la anterior pero conserva el historial»."""
    tipo = await tipo_equipo_id(cliente, auth, "Minisplit")
    manual = await subir_manual(cliente, auth, tipo, "Manual versionado", contenido=pdf_falso("v1"))

    r = await cliente.post(f"/api/biblioteca/manuales/{manual['id']}/versiones", headers=await auth(AP),
                           data={"notas": "Corrección del fabricante"},
                           files={"archivo": ("v2.pdf", pdf_falso("v2 mas largo que la uno"), "application/pdf")})
    assert r.status_code == 201, r.text
    assert r.json()["version"] == 2 and r.json()["hash_sha256"] != manual["hash_sha256"]

    historial = (await cliente.get(f"/api/biblioteca/manuales/{manual['id']}/versiones",
                                   headers=await auth(AP))).json()
    assert len(historial) == 1 and historial[0]["version_anterior"] == 1
    assert historial[0]["notas_version"] == "Corrección del fabricante"
    # La versión anterior sigue descargable para el Admin prestador.
    enlace = (await cliente.get(f"/api/biblioteca/manuales/{manual['id']}/enlace", headers=await auth(AP),
                                params={"version": 1})).json()
    archivo = await cliente.get(enlace["url"].replace("/api", "/api"))
    assert archivo.status_code == 200 and b"v1" in archivo.content
    # Y la vigente trae la nueva.
    vigente = (await cliente.get(f"/api/biblioteca/manuales/{manual['id']}/enlace", headers=await auth(AP))).json()
    assert b"v2" in (await cliente.get(vigente["url"])).content


async def test_el_historial_de_versiones_es_append_only(cliente, auth, datos):
    """Ni el dueño del esquema puede corregir el historial: es el mismo trigger que la auditoría."""
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        for sentencia in ("UPDATE biblioteca_versiones SET notas_version = 'alterado'",
                          "DELETE FROM biblioteca_versiones"):
            try:
                await db.execute(text(sentencia))
                paso = True
            except Exception:
                paso = False
            await db.rollback()
            assert not paso, f"biblioteca_versiones debe rechazar: {sentencia}"


async def test_el_tecnico_necesita_el_permiso_acceder_manuales(cliente, auth, datos):
    """§6.8.3: con el permiso desactivado, la biblioteca se le cierra."""
    tipo = await tipo_equipo_id(cliente, auth)
    await subir_manual(cliente, auth, tipo, "Manual para el técnico")
    assert (await cliente.get("/api/biblioteca/manuales", headers=await auth(TEC))).status_code == 200

    h = await auth(AP)
    r = await cliente.put("/api/configuracion/permisos-tecnico", headers=h,
                          json={"valores": {"acceder_manuales": False}})
    assert r.status_code == 200, r.text
    try:
        bloqueado = await cliente.get("/api/biblioteca/manuales", headers=await auth(TEC))
        assert bloqueado.status_code == 403 and bloqueado.json()["codigo"] == "PROHIBIDO"
    finally:
        await cliente.put("/api/configuracion/permisos-tecnico", headers=h,
                          json={"valores": {"acceder_manuales": True}})
    assert (await cliente.get("/api/biblioteca/manuales", headers=await auth(TEC))).status_code == 200


async def test_el_cliente_no_entra_a_los_manuales_del_prestador(cliente, auth, datos):
    """Los manuales son documentación técnica del prestador; el cliente tiene su contenido de servicio."""
    for email in (AE, OP):
        r = await cliente.get("/api/biblioteca/manuales", headers=await auth(email))
        assert r.status_code == 403, f"{email}: {r.status_code}"


async def test_el_otro_prestador_no_ve_ni_versiona_mis_manuales(cliente_factory, auth, datos):
    async with cliente_factory() as c:
        tipo = await tipo_equipo_id(c, auth)
        manual = await subir_manual(c, auth, tipo, "Manual privado del prestador")
        lista = (await c.get("/api/biblioteca/manuales", headers=await auth(OTRO_AP))).json()
        assert manual["id"] not in {m["id"] for m in lista}
        r = await c.get(f"/api/biblioteca/manuales/{manual['id']}/versiones", headers=await auth(OTRO_AP))
        assert r.status_code == 404
        r = await c.post(f"/api/biblioteca/manuales/{manual['id']}/versiones", headers=await auth(OTRO_AP),
                         files={"archivo": ("x.pdf", pdf_falso("ajeno"), "application/pdf")})
        assert r.status_code in (403, 404)


async def test_el_enlace_firmado_vence_y_no_sirve_alterado(cliente, auth, datos):
    tipo = await tipo_equipo_id(cliente, auth)
    manual = await subir_manual(cliente, auth, tipo, "Manual con enlace")
    enlace = (await cliente.get(f"/api/biblioteca/manuales/{manual['id']}/enlace",
                                headers=await auth(AP))).json()
    assert enlace["expira_en_segundos"] == 300
    # El archivo se sirve sin cabecera de autorización (lo abre el visor del navegador)…
    ok = await cliente.get(enlace["url"])
    assert ok.status_code == 200 and ok.headers["cache-control"] == "no-store"
    # …pero el token no se puede inventar ni alterar.
    roto = enlace["url"][:-4] + "xxxx"
    assert (await cliente.get(roto)).status_code == 403


async def test_desactivar_un_manual_lo_saca_de_la_lista(cliente, auth, datos):
    tipo = await tipo_equipo_id(cliente, auth)
    manual = await subir_manual(cliente, auth, tipo, "Manual a desactivar")
    r = await cliente.delete(f"/api/biblioteca/manuales/{manual['id']}", headers=await auth(AP))
    assert r.status_code == 200
    lista = (await cliente.get("/api/biblioteca/manuales", headers=await auth(AP))).json()
    assert manual["id"] not in {m["id"] for m in lista}


async def test_apoyo_del_folio_trae_puntos_y_manuales_del_equipo(cliente, auth, datos):
    """La llamada que hace la app del tecnico al abrir el folio: puntos de revision del contrato + manuales.

    Se usa el contenido que ya deja el seed para «Refrigerador vertical» en lugar de crear otro: solo puede haber un
    contenido activo por cliente y tipo de equipo, asi que guardar aqui le subiria la version al de las demas pruebas.
    """
    from tests.folios_utiles import accion, autorizar_sin_flujo, nuevo_equipo, tecnico_con_habilidades

    # indice=1 es «Refrigerador vertical» (el 0 es «Camara de congelacion»), que es el que el seed trae con puntos.
    equipo = await nuevo_equipo(cliente, auth, datos, familia="Refrigeración", indice=1)
    manual = await subir_manual(cliente, auth, equipo["tipo_equipo_id"], "Manual del apoyo del folio")
    folio = await autorizar_sin_flujo(cliente, auth, datos, OP, equipo=equipo)
    tec = await tecnico_con_habilidades(cliente, auth, TEC, ["refrigeracion", "electricidad"])
    await accion(cliente, auth, DES, folio["id"], "asignar", {"tecnico_id": tec})

    apoyo = (await cliente.get(f"/api/biblioteca/folios/{folio['id']}/apoyo", headers=await auth(TEC))).json()
    assert apoyo["tipo_equipo_id"] == equipo["tipo_equipo_id"]
    assert apoyo["contenido"] is not None, "el contenido de servicio del seed debe llegar al folio"
    assert [p["clave"] for p in apoyo["contenido"]["puntos_revision"]][:2] == ["temperatura", "condensador"]
    assert manual["id"] in {m["id"] for m in apoyo["manuales"]}
    # El prestador ajeno no ve el folio, asi que tampoco su apoyo.
    assert (await cliente.get(f"/api/biblioteca/folios/{folio['id']}/apoyo",
                              headers=await auth(OTRO_AP))).status_code == 404
