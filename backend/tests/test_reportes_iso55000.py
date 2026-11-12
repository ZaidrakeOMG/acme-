"""Los cinco reportes que respaldan una certificación ISO 55000 (§6.9.3): PDF y Excel por el generador de P10,
secciones con contenido real, permisos por rol y aislamiento entre clientes. F2-05."""
from services.reportes_iso55000 import PLANTILLAS
from tests.criticidad_utiles import equipo_con_historia, evaluar, mitigacion, modo_falla
from tests.folios_utiles import AE, AP, AUN, DES, MC, OP, OTRO_AE, SA, TEC

FIRMAS = {"pdf": b"%PDF", "excel": b"PK"}


async def _descargar(cliente, auth, email, tipo, formato="pdf", esperado=200, **params):
    r = await cliente.get(f"/api/reportes/iso55000/{tipo}", headers=await auth(email),
                          params={"formato": formato, **params})
    assert r.status_code == esperado, r.text
    return r


async def _parque_evaluado(cliente, auth, datos):
    """Un activo A con su modo de falla y su acción de mitigación: lo que los cinco reportes tienen que mostrar."""
    equipo = await equipo_con_historia(cliente, auth, datos, fallas=12)
    await evaluar(cliente, auth, equipo["id"], 5, 4, 4, 4, razon="Evaluación para el reporte de certificación")
    modo = await modo_falla(cliente, auth, equipo["id"], severidad=5, frecuencia_historica=4)
    await mitigacion(cliente, auth, modo["id"], accion_mitigacion="Acción para el reporte de certificación")
    return equipo


async def test_los_cinco_reportes_de_certificacion_estan_listados(cliente, auth):
    lista = (await cliente.get("/api/reportes/iso55000", headers=await auth(AE))).json()
    assert {x["tipo"] for x in lista} == set(PLANTILLAS)
    assert len(lista) == 5 and all(x["nombre"].startswith("ISO 55000") for x in lista)


async def test_cada_reporte_sale_en_pdf_y_en_excel(cliente, auth, datos):
    await _parque_evaluado(cliente, auth, datos)
    for tipo in PLANTILLAS:
        for formato in ("pdf", "excel"):
            r = await _descargar(cliente, auth, AE, tipo, formato)
            assert r.content.startswith(FIRMAS[formato]), (tipo, formato, r.content[:8])
            assert len(r.content) > 500, (tipo, formato, len(r.content))
            assert "attachment" in r.headers["content-disposition"]
            assert tipo in r.headers["content-disposition"]


async def test_el_reporte_queda_registrado_como_los_de_p10(cliente, auth, datos):
    """Mismo generador: se anota en `reportes_generados` con su tiempo y su archivo, y se puede volver a bajar."""
    await _parque_evaluado(cliente, auth, datos)
    r = await _descargar(cliente, auth, AE, "iso_registro", "pdf")
    reporte_id = r.headers["x-reporte-id"]
    assert int(r.headers["x-reporte-ms"]) >= 0
    lista = (await cliente.get("/api/bi/reportes/generados", headers=await auth(AE))).json()
    mio = next((x for x in lista if x["id"] == reporte_id), None)
    assert mio is not None and mio["tipo_reporte"] == "iso_registro" and mio["filas"] >= 1
    assert mio["archivo_key"].startswith("reportes/") and mio["ms_generacion"] is not None
    de_nuevo = await cliente.get(f"/api/bi/reportes/generados/{reporte_id}/archivo", headers=await auth(AE))
    assert de_nuevo.status_code == 200 and de_nuevo.content.startswith(b"%PDF")


async def test_las_secciones_traen_lo_que_un_auditor_pregunta(cliente, auth, datos):
    """Se revisan las secciones que arma el servicio, no el PDF: es lo que después pinta cualquiera de los dos
    formatos."""
    from core.db import nueva_sesion
    from core.rls import CONTEXTO_SISTEMA
    from models.usuarios import Usuario
    from services import bi_service, reportes_service
    from sqlalchemy import select

    equipo = await _parque_evaluado(cliente, auth, datos)
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        usuario = (await db.execute(select(Usuario).where(Usuario.email == AE))).scalar_one()
        from scripts.seed_folios import actor_de

        actor = actor_de(usuario)
        f = await bi_service.filtro_de(db, actor, None, None, None, None)
        por_tipo = {t: await reportes_service.secciones(db, actor, t, f) for t in PLANTILLAS}

    # Registro: una fila por activo evaluado, con nivel, índice y próxima revisión.
    registro = por_tipo["iso_registro"]
    tabla = next(s for s in registro if s["tipo"] == "tabla")
    assert any("Nivel" in c for c in tabla["columnas"]) and any("ndice" in c for c in tabla["columnas"])
    assert any(equipo["codigo"] in str(fila) for fila in tabla["filas"])
    assert any(s["tipo"] == "kpi" for s in registro)        # distribución por nivel

    # Matriz: probabilidad × impacto con los activos ubicados.
    matriz = por_tipo["iso_matriz"]
    assert any(equipo["codigo"] in str(s["filas"]) for s in matriz if s["tipo"] == "tabla")

    # Modos de falla: el modo con su nivel de riesgo y su acción de mitigación con responsable.
    modos = por_tipo["iso_modos_falla"]
    texto_modos = str([s["filas"] for s in modos])
    assert "Acción para el reporte de certificación" in texto_modos

    # Historial: cada cambio de criticidad con su motivo y su razón.
    historial = por_tipo["iso_historial"]
    texto_historial = str([s["filas"] for s in historial])
    assert "Evaluación para el reporte de certificación" in texto_historial

    # Mejora continua: MTBF, MTTR y cobertura de preventivos por nivel.
    mejora = por_tipo["iso_mejora_continua"]
    assert mejora and any(s["tipo"] in ("kpi", "tabla") for s in mejora)
    for tipo, secciones in por_tipo.items():
        assert secciones, tipo
        for s in secciones:
            assert s["titulo"] and s["tipo"] in ("kpi", "tabla"), (tipo, s)
            if s["tipo"] == "tabla":
                assert s["columnas"] and all(len(f) == len(s["columnas"]) for f in s["filas"]), (tipo, s["titulo"])


async def test_permisos_de_los_reportes_de_certificacion(cliente, auth, datos):
    """Los saca quien responde por la gestión de activos: el cliente y la dirección del prestador. No el técnico
    ni el operador."""
    await _parque_evaluado(cliente, auth, datos)
    for email in (AE, AUN, AP, MC, SA):
        await _descargar(cliente, auth, email, "iso_registro", "pdf",
                         **({"tenant_id": str(datos["tenant"])} if email in (AP, MC, SA) else {}))
    for email in (OP, TEC, DES):
        await _descargar(cliente, auth, email, "iso_registro", esperado=403)
    assert (await cliente.get("/api/reportes/iso55000", headers=await auth(TEC))).status_code == 403
    # Una plantilla inexistente se rechaza con el listado de las que hay.
    r = await _descargar(cliente, auth, AE, "iso_inventado", esperado=422)
    assert r.json()["codigo"] == "TIPO_DESCONOCIDO" and "iso_registro" in r.json()["mensaje"]
    # Un formato que no existe lo frena el patrón de la ruta.
    await _descargar(cliente, auth, AE, "iso_registro", "word", esperado=422)


async def test_el_reporte_de_un_cliente_no_trae_activos_de_otro(cliente, auth, datos):
    """§6.9.5: el reporte de certificación es del cliente. El otro tenant no aparece ni se lo puede pedir."""
    from core.db import nueva_sesion
    from core.rls import CONTEXTO_SISTEMA
    from models.usuarios import Usuario
    from services import bi_service, reportes_service
    from sqlalchemy import select

    equipo = await _parque_evaluado(cliente, auth, datos)
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        from scripts.seed_folios import actor_de

        ajeno = actor_de((await db.execute(select(Usuario).where(Usuario.email == OTRO_AE))).scalar_one())
        f = await bi_service.filtro_de(db, ajeno, None, None, None, None)
        secciones = await reportes_service.secciones(db, ajeno, "iso_registro", f)
    assert equipo["codigo"] not in str([s["filas"] for s in secciones])
    # Y el Admin empresa del otro cliente no puede pedir el del demo.
    r = await cliente.get("/api/reportes/iso55000/iso_registro", headers=await auth(OTRO_AE),
                          params={"formato": "pdf", "tenant_id": str(datos["tenant"])})
    assert r.status_code == 200, r.text        # se le ignora el tenant ajeno y sale el suyo
    # El reporte que acaba de generar es el suyo, y el del demo no aparece en su historial.
    lista = (await cliente.get("/api/bi/reportes/generados", headers=await auth(OTRO_AE))).json()
    assert r.headers["x-reporte-id"] in {x["id"] for x in lista}
    propios = (await cliente.get("/api/bi/reportes/generados", headers=await auth(AE))).json()
    assert r.headers["x-reporte-id"] not in {x["id"] for x in propios}
