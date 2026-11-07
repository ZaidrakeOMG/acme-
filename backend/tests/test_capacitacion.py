"""Capacitación y certificación de técnicos (§6.10.3): catálogo por rol, registro con constancia, expediente,
vencimientos, configuración de alertas y la vista del cliente. F2-01."""
from datetime import date, timedelta

from tests.capacitacion_utiles import HOY, crear_curso, expediente, ficha_tecnico, habilidades, registrar
from tests.folios_utiles import AE, AP, AUN, DES, MC, OP, OTRO_AP, SA, TEC, TEC2


async def test_el_catalogo_global_lo_crea_solo_el_superadmin(cliente, auth, datos):
    """El catálogo de plataforma es del Superadmin; el Admin prestador solo crea los suyos (§6.10.3)."""
    propio = await crear_curso(cliente, auth, f"Curso propio {HOY}", proveedor="Interno", duracion_horas="4")
    assert propio["prestador_id"] == str(datos["prestador"])

    global_ = await crear_curso(cliente, auth, f"Curso global {HOY}", email=SA, **{"global": True})
    assert global_["prestador_id"] is None

    # El Admin prestador no puede crear en el catálogo global.
    r = await cliente.post("/api/capacitacion/cursos", headers=await auth(AP),
                           json={"nombre": "Intento global", "global": True})
    assert r.status_code == 403 and r.json()["codigo"] == "PROHIBIDO"
    # Y un curso global no puede certificar una habilidad: las habilidades son de cada prestador.
    habs = await habilidades(cliente, auth)
    r = await cliente.post("/api/capacitacion/cursos", headers=await auth(SA),
                           json={"nombre": "Global con habilidad", "global": True,
                                 "habilidad_id": habs["refrigeracion"]})
    assert r.status_code == 422 and r.json()["codigo"] == "HABILIDAD_EN_CURSO_GLOBAL"


async def test_el_catalogo_del_otro_prestador_no_se_ve_ni_se_edita(cliente_factory, auth, datos):
    """Aislamiento: el catálogo propio es privado y el global es compartido."""
    async with cliente_factory() as c:
        propio = await crear_curso(c, auth, f"Privado {HOY.isoformat()}")
        lista = (await c.get("/api/capacitacion/cursos", headers=await auth(OTRO_AP))).json()
        ids = {x["id"] for x in lista}
        assert propio["id"] not in ids, "el otro prestador no debe ver el catálogo ajeno"
        assert any(x["prestador_id"] is None for x in lista), "pero sí debe ver el catálogo global"
        r = await c.put(f"/api/capacitacion/cursos/{propio['id']}", headers=await auth(OTRO_AP),
                        json={"activo": False})
        assert r.status_code in (403, 404)


async def test_registro_de_curso_con_constancia_y_expediente(cliente, auth, datos):
    """Registrar un curso deja el expediente con su estado y la constancia descargable."""
    habs = await habilidades(cliente, auth)
    curso = await crear_curso(cliente, auth, f"Refrigeración avanzada {HOY}", vigencia_meses=24,
                              habilidad_id=habs["refrigeracion"], norma_referencia="NOM-STPS / DC-3",
                              tipo="certificacion")
    tecnico = await ficha_tecnico(cliente, auth, TEC)
    exp = await registrar(cliente, auth, tecnico["id"], curso["id"], fecha_fin=HOY - timedelta(days=10),
                          calificacion=95, folio_constancia="DC3-PRUEBA-1",
                          certificado=b"%PDF-1.4 constancia de prueba")
    fila = next(c for c in exp["cursos"] if c["curso_id"] == curso["id"])
    assert fila["estado"] == "vigente" and fila["tiene_certificado"] is True
    assert fila["vigente_hasta"] == str(date(HOY.year + 2, HOY.month, HOY.day) - timedelta(days=10)) or \
           fila["dias_para_vencer"] > 600
    assert fila["habilidad"] == "Refrigeración comercial"

    # La constancia se descarga y queda registrada como acceso a datos sensibles (§6.9.5).
    r = await cliente.get(f"/api/capacitacion/tecnicos/{tecnico['id']}/certificado/{fila['id']}",
                          headers=await auth(AP))
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    eventos = (await cliente.get("/api/auditoria/eventos", headers=await auth(SA),
                                 params={"evento_tipo": "acceso.datos_sensibles", "limite": 50})).json()
    assert any(e.get("recurso_tipo") == "tecnico_cursos" for e in eventos)


async def test_la_fecha_futura_y_la_vigencia_sin_razon_se_rechazan(cliente, auth, datos):
    curso = await crear_curso(cliente, auth, f"Curso validaciones {HOY}", vigencia_meses=12)
    tecnico = await ficha_tecnico(cliente, auth, TEC2)
    r = await cliente.post(f"/api/capacitacion/tecnicos/{tecnico['id']}/cursos", headers=await auth(AP),
                           data={"curso_id": curso["id"], "fecha_fin": str(HOY + timedelta(days=1))})
    assert r.status_code == 422 and r.json()["codigo"] == "FECHA_FUTURA"
    # Cambiar la vigencia calculada exige razón.
    r = await cliente.post(f"/api/capacitacion/tecnicos/{tecnico['id']}/cursos", headers=await auth(AP),
                           data={"curso_id": curso["id"], "fecha_fin": str(HOY - timedelta(days=3)),
                                 "vigente_hasta": str(HOY + timedelta(days=900))})
    assert r.status_code == 422 and r.json()["codigo"] == "RAZON_REQUERIDA"
    # Con razón, se acepta y queda marcada como editada.
    ok = await registrar(cliente, auth, tecnico["id"], curso["id"], fecha_fin=HOY - timedelta(days=3),
                         vigente_hasta=HOY + timedelta(days=900),
                         razon_vigencia="El documento original trae esa fecha")
    assert any(c["curso_id"] == curso["id"] for c in ok["cursos"])


async def test_los_vencimientos_y_la_configuracion_de_alertas(cliente, auth, datos):
    """§6.10.3: días de anticipación configurables y aviso opcional al cliente."""
    cfg = (await cliente.get("/api/capacitacion/alertas/configuracion", headers=await auth(AP))).json()
    assert cfg["dias_anticipacion"] == 30 and cfg["notificar_cliente"] is True   # el seed lo deja activo

    r = await cliente.put("/api/capacitacion/alertas/configuracion", headers=await auth(AP),
                          json={"dias_anticipacion": 200})
    assert r.status_code == 422
    r = await cliente.put("/api/capacitacion/alertas/configuracion", headers=await auth(AP),
                          json={"dias_anticipacion": 45, "notificar_cliente": False})
    assert r.status_code == 200 and r.json()["dias_anticipacion"] == 45
    # Se restaura para no alterar las otras pruebas de la suite.
    await cliente.put("/api/capacitacion/alertas/configuracion", headers=await auth(AP),
                      json={"dias_anticipacion": 30, "notificar_cliente": True})

    # El seed deja una certificación por vencer en 10 días y una vencida.
    vencimientos = (await cliente.get("/api/capacitacion/vencimientos", headers=await auth(AP))).json()
    estados = {v["estado"] for v in vencimientos}
    assert "por_vencer" in estados and "vencido" in estados, vencimientos
    assert all(v["dias"] <= 30 for v in vencimientos)
    # El despachador consulta vigencias para asignar; el operador del cliente no.
    assert (await cliente.get("/api/capacitacion/vencimientos", headers=await auth(DES))).status_code == 200
    assert (await cliente.get("/api/capacitacion/vencimientos", headers=await auth(OP))).status_code == 403


async def test_la_vista_del_cliente_no_expone_datos_internos(cliente, auth, datos):
    """§6.10.3: el cliente ve certificaciones vigentes, sin calificaciones ni cursos reprobados."""
    habs = await habilidades(cliente, auth)
    curso = await crear_curso(cliente, auth, f"Certificación visible {HOY}", vigencia_meses=36,
                              habilidad_id=habs["hvac"], tipo="certificacion", norma_referencia="NOM-009-STPS")
    reprobado = await crear_curso(cliente, auth, f"Curso reprobado {HOY}", vigencia_meses=12)
    tecnico = await ficha_tecnico(cliente, auth, TEC)
    await registrar(cliente, auth, tecnico["id"], curso["id"], fecha_fin=HOY - timedelta(days=20),
                    calificacion=99)
    await registrar(cliente, auth, tecnico["id"], reprobado["id"], fecha_fin=HOY - timedelta(days=20),
                    aprobado=False, calificacion=40)

    for email in (AE, AUN):
        lista = (await cliente.get("/api/capacitacion/tecnicos-de-mis-unidades",
                                   headers=await auth(email))).json()
        assert lista, f"{email} debería ver técnicos de sus unidades"
        mio = next((t for t in lista if t["tecnico_id"] == tecnico["id"]), None)
        assert mio is not None
        nombres = {c["nombre"] for c in mio["certificaciones"]}
        assert curso["nombre"] in nombres
        assert reprobado["nombre"] not in nombres, "un curso reprobado no es una certificación"
        plano = str(mio)
        assert "calificacion" not in plano and "certificado" not in plano
        for c in mio["certificaciones"]:
            assert set(c) == {"nombre", "tipo", "norma_referencia", "proveedor", "vigente_hasta", "vigencia"}

    # El prestador no usa esa vista y el cliente no ve el expediente interno.
    assert (await cliente.get("/api/capacitacion/tecnicos-de-mis-unidades",
                              headers=await auth(AP))).status_code == 403
    assert (await cliente.get(f"/api/capacitacion/tecnicos/{tecnico['id']}/expediente",
                              headers=await auth(AE))).status_code == 403


async def test_el_cliente_ajeno_no_ve_los_tecnicos_del_prestador(cliente_factory, auth, datos):
    """El otro cliente del mismo prestador no tiene técnicos habilitados ni folios: no ve nada."""
    async with cliente_factory() as c:
        lista = (await c.get("/api/capacitacion/tecnicos-de-mis-unidades",
                             headers=await auth("admin.otro@acma.dev"))).json()
        assert lista == [], lista


async def test_el_expediente_se_exporta_a_excel_y_pdf(cliente, auth, datos):
    tecnico = await ficha_tecnico(cliente, auth, TEC)
    xlsx = await cliente.get(f"/api/capacitacion/tecnicos/{tecnico['id']}/expediente.xlsx", headers=await auth(AP))
    assert xlsx.status_code == 200 and xlsx.content[:2] == b"PK" and len(xlsx.content) > 4000
    pdf = await cliente.get(f"/api/capacitacion/tecnicos/{tecnico['id']}/expediente.pdf", headers=await auth(MC))
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")


async def test_no_se_registra_un_curso_a_un_tecnico_de_otro_prestador(cliente_factory, auth, datos):
    async with cliente_factory() as c:
        curso = await crear_curso(c, auth, f"Curso aislamiento {HOY}")
        tecnico = await ficha_tecnico(c, auth, TEC)
        # El Admin del otro prestador no puede registrar en la ficha de este técnico.
        r = await c.post(f"/api/capacitacion/tecnicos/{tecnico['id']}/cursos", headers=await auth(OTRO_AP),
                         data={"curso_id": curso["id"], "fecha_fin": str(HOY - timedelta(days=2))})
        assert r.status_code in (403, 404, 422), r.text
