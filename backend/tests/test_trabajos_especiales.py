"""Trabajos especiales (§6.10.6): creación por rol, validación del cliente por botón (rechazo con comentario y reenvío con versión),
programación con permiso del técnico, folio operativo sincronizado en ambas direcciones, cierre bloqueado sin formulario/evidencia/firma,
conversión desde cotización, cancelación, aislamiento, alertas y reporte."""
from datetime import UTC, date, datetime, timedelta

from tests.folios_utiles import AP, DES, MC, OP, OTRO_AE, OTRO_AP, SUPO, TEC, TEC2, accion, detalle
from tests.seguimiento_utiles import alertas_disparadas, bandeja, cambiar_estado, crear_registro, detalle_registro, retroceder
from tests.te_utiles import AE, AUN, accion_te, cerrar_te_completo, crear_te, detalle_te, formulario_te, habilitar_te, manana, respuesta_te, te_programado


async def test_creacion_por_rol_y_validacion_del_cliente(cliente, auth, datos):
    await formulario_te(cliente, auth)
    assert (await crear_te(cliente, auth, datos, OP, esperado=403))["codigo"] == "PROHIBIDO"
    assert (await crear_te(cliente, auth, datos, AUN, esperado=403))["codigo"] == "PROHIBIDO"  # el cliente solo crea TE de urgencia
    te = await crear_te(cliente, auth, datos, MC, descripcion="Reubicación del anuncio luminoso (solicitud del cliente)")
    assert te["numero"].startswith("TE-") and te["estado"] == "creado" and te["version_enviada"] == 0 and te["formulario_id"] and te["creado_por_rol"] == "mesa_control"
    assert te["destinos"] == ["enviado_cliente", "cancelado"]
    # El cliente no acepta algo que no se le ha enviado; el prestador no acepta nunca.
    assert (await accion_te(cliente, auth, AE, te["id"], "aceptar", {"canal": "app"}, 409))["codigo"] == "TRANSICION_NO_PERMITIDA"
    d = await accion_te(cliente, auth, DES, te["id"], "enviar", {"notas": "Versión inicial"})
    assert d["estado"] == "enviado_cliente" and d["version_enviada"] == 1 and d["enviado_at"]
    assert (await accion_te(cliente, auth, DES, te["id"], "aceptar", {"canal": "app"}, 409))["detalles"][0]["roles_permitidos"] == ["admin_empresa", "admin_un", "superadmin"]
    assert any(n["evento"] == "trabajo_especial.enviado" and n["datos"]["trabajo_especial_id"] == te["id"] for n in await bandeja(cliente, auth, AUN, solo_no_leidas=True))
    # Bandeja «por validar» del cliente.
    por_validar = (await cliente.get("/api/trabajos-especiales", headers=await auth(AE), params={"por_validar": True})).json()
    assert any(x["id"] == te["id"] for x in por_validar)
    # Rechazo sin comentario → 422; con comentario → rechazado y respuesta append-only.
    assert (await accion_te(cliente, auth, AE, te["id"], "rechazar", {"canal": "email", "comentario": ""}, 422))["codigo"] == "COMENTARIO_REQUERIDO"
    d = await accion_te(cliente, auth, AE, te["id"], "rechazar", {"canal": "email", "comentario": "El monto excede lo acordado"})
    assert d["estado"] == "rechazado" and d["respuestas_cliente"][0] == {**d["respuestas_cliente"][0], "decision": "rechazado", "version_enviada": 1, "canal": "email"}
    assert d["destinos"] == [] and sorted((await detalle_te(cliente, auth, te["id"]))["destinos"]) == ["cancelado", "enviado_cliente"]  # destinos por actor
    # Modificar y reenviar: versión 2 con el monto ajustado; el Admin UN acepta.
    d = await accion_te(cliente, auth, DES, te["id"], "enviar", {"monto": "5400.00", "notas": "Se ajustó la mano de obra"})
    assert d["estado"] == "enviado_cliente" and d["version_enviada"] == 2 and d["monto"] == "5400.00"
    d = await accion_te(cliente, auth, AUN, te["id"], "aceptar", {"canal": "app", "comentario": "Adelante"})
    assert d["estado"] == "aceptado" and d["aceptado_at"] and [r["decision"] for r in d["respuestas_cliente"]] == ["rechazado", "aceptado"]
    assert [h["estado_nuevo"] for h in d["historial"]] == ["creado", "enviado_cliente", "rechazado", "enviado_cliente", "aceptado"]
    assert any(n["evento"] == "trabajo_especial.aceptado" and n["datos"]["numero"] == te["numero"] for n in await bandeja(cliente, auth, DES))
    # Programar exige fecha y técnicos con el permiso ejecutar_trabajos_especiales.
    tid2 = await habilitar_te(cliente, auth, TEC2, False)
    r = await accion_te(cliente, auth, DES, te["id"], "programar", {"fecha_programada": manana(), "tecnico_ids": [tid2]}, 409)
    assert r["codigo"] == "TECNICO_SIN_PERMISO"
    assert (await accion_te(cliente, auth, AE, te["id"], "programar", {"fecha_programada": manana(), "tecnico_ids": [tid2]}, 409))["codigo"] == "TRANSICION_NO_PERMITIDA"
    tid = await habilitar_te(cliente, auth, TEC, True)
    await habilitar_te(cliente, auth, TEC2, True)
    d = await accion_te(cliente, auth, DES, te["id"], "programar", {"fecha_programada": manana(), "tecnico_ids": [tid, tid2], "tecnico_responsable_id": tid, "notas": "Cuadrilla"})
    assert d["estado"] == "programado" and d["fecha_programada"] == manana() and d["tecnico_responsable_id"] == tid and len(d["tecnicos"]) == 2
    # Folio operativo tipo especial, autorizado y asignado al responsable, visible con el bloque del TE.
    f = await detalle(cliente, auth, d["folio_id"])
    assert f["folio"]["tipo_folio"] == "especial" and f["folio"]["estado"] == "asignado" and f["folio"]["tecnico_id"] == tid and f["folio"]["trabajo_especial_id"] == te["id"]
    assert f["trabajo_especial"]["numero"] == te["numero"] and f["trabajo_especial"]["estado"] == "programado"
    assert [h["estado_nuevo"] for h in f["historial"] if h["evento"] == "transicion"] == ["capturado", "autorizado", "asignado"]
    assert any(n["evento"] == "trabajo_especial.programado" for n in await bandeja(cliente, auth, AUN))
    assert any(n["evento"] == "trabajo_especial.programado" for n in await bandeja(cliente, auth, TEC))


async def test_ejecucion_cierre_y_sincronizacion_con_el_folio(cliente, auth, datos):
    d, tid = await te_programado(cliente, auth, datos)
    # Solo el responsable inicia; el técnico lo ve en su listado.
    assert any(x["id"] == d["id"] for x in (await cliente.get("/api/trabajos-especiales", headers=await auth(TEC))).json())
    assert (await accion_te(cliente, auth, TEC2, d["id"], "iniciar", {}, 404))["codigo"] == "NO_ENCONTRADO"  # no está asignado: fuera de su alcance
    e = await accion_te(cliente, auth, TEC, d["id"], "iniciar", {"notas": "Llegué"})
    assert e["estado"] == "en_ejecucion" and e["fecha_inicio"] and e["estado_folio"] == "en_ejecucion"
    # Cierre bloqueado sin formulario, evidencia ni firma: desde el TE y desde el folio.
    r = await accion_te(cliente, auth, TEC, d["id"], "cerrar", {}, 409)
    assert r["codigo"] == "CIERRE_TE_INCOMPLETO" and set(r["detalles"]) == {"formulario_te", "firma", "evidencia_cierre"}
    assert (await accion(cliente, auth, TEC, d["folio_id"], "cerrar", esperado=409))["codigo"] in ("CIERRE_TE_INCOMPLETO", "CIERRE_INCOMPLETO")
    rid = await respuesta_te(cliente, auth, datos, d["folio_id"], con_foto=False)
    await accion(cliente, auth, TEC, d["folio_id"], "atencion", {"respuesta_id": rid}, esperado=201)
    r = await accion_te(cliente, auth, TEC, d["id"], "cerrar", {}, 409)
    assert set(r["detalles"]) == {"firma", "evidencia_cierre"}
    # Evidencia de cierre por el endpoint del TE (foto en base64) y firma del operador.
    import base64

    from tests.test_cierre_folio import firmar
    from tests.test_formularios_evidencias import jpeg

    ev = await cliente.post(f"/api/trabajos-especiales/{d['id']}/evidencias", headers=await auth(TEC),
                            json={"tipo": "cierre", "contenido_base64": base64.b64encode(jpeg(640, 480)).decode(), "nombre": "cierre.jpg", "mime": "image/jpeg"})
    assert ev.status_code == 201 and ev.json()["tipo"] == "cierre" and ev.json()["archivo_key"].startswith("trabajos_especiales/")
    assert (await accion_te(cliente, auth, TEC, d["id"], "cerrar", {}, 409))["detalles"] == ["firma"]
    await firmar(cliente, auth, OP, d["folio_id"])
    c = await accion_te(cliente, auth, TEC, d["id"], "cerrar", {"notas": "Terminado"})
    assert c["estado"] == "cerrado" and c["fecha_cierre"] and c["estado_folio"] == "cerrado" and c["respuesta_formulario_id"] == rid and c["destinos"] == []
    f = await detalle(cliente, auth, d["folio_id"])
    assert f["folio"]["estado"] == "cerrado" and f["folio"]["fecha_cierre"]
    assert (await accion_te(cliente, auth, AP, d["id"], "cancelar", {"notas": "Ya no aplica"}, 409))["codigo"] == "TRANSICION_NO_PERMITIDA"
    assert any(n["evento"] == "trabajo_especial.cerrado" for n in await bandeja(cliente, auth, AUN))


async def test_cierre_desde_el_folio_del_tecnico_sincroniza_el_te(cliente, auth, datos):
    """El técnico opera desde la app de P05: en-camino / llegada / atención / cerrar en el folio mueven el TE."""
    from tests.test_cierre_folio import firmar

    d, tid = await te_programado(cliente, auth, datos)
    await accion(cliente, auth, TEC, d["folio_id"], "en-camino")
    await accion(cliente, auth, TEC, d["folio_id"], "confirmar-llegada")
    assert (await detalle_te(cliente, auth, d["id"]))["estado"] == "en_ejecucion"
    rid = await respuesta_te(cliente, auth, datos, d["folio_id"])  # con foto de cierre → evidencia «después» del folio
    await accion(cliente, auth, TEC, d["folio_id"], "atencion", {"respuesta_id": rid}, esperado=201)
    await firmar(cliente, auth, OP, d["folio_id"])
    await accion(cliente, auth, TEC, d["folio_id"], "cerrar")
    t = await detalle_te(cliente, auth, d["id"])
    assert t["estado"] == "cerrado" and t["estado_folio"] == "cerrado" and t["requisitos_cierre_faltantes"] == []
    assert any(h["notas"] == "Sincronizado desde el folio operativo" for h in t["historial"])


async def test_cancelacion_en_cualquiera_cancela_al_otro(cliente, auth, datos):
    d, _ = await te_programado(cliente, auth, datos)
    assert (await accion_te(cliente, auth, MC, d["id"], "cancelar", {"notas": "x"}, 422))["codigo"] == "JUSTIFICACION_REQUERIDA"
    assert (await accion_te(cliente, auth, AE, d["id"], "cancelar", {"notas": "Ya no lo queremos"}, 409))["codigo"] == "TRANSICION_NO_PERMITIDA"  # solo urgencias propias
    c = await accion_te(cliente, auth, MC, d["id"], "cancelar", {"notas": "El cliente contrató a otro proveedor"})
    assert c["estado"] == "cancelado" and c["razon_cancelacion"] == "El cliente contrató a otro proveedor" and c["estado_folio"] == "cancelado"
    f = await detalle(cliente, auth, d["folio_id"])
    assert f["folio"]["estado"] == "cancelado" and "El cliente contrató a otro proveedor" in f["folio"]["razon_cancelacion"]
    # Sentido inverso: cancelar el folio operativo cancela el TE.
    d2, _ = await te_programado(cliente, auth, datos)
    await accion(cliente, auth, DES, d2["folio_id"], "cancelar", {"razon": "Se canceló la visita", "notas": "Se canceló la visita"})
    t = await detalle_te(cliente, auth, d2["id"])
    assert t["estado"] == "cancelado" and "Se canceló la visita" in t["razon_cancelacion"]


async def test_conversion_desde_cotizacion_autorizada(cliente, auth, datos):
    await formulario_te(cliente, auth)
    c = await crear_registro(cliente, auth, "cotizaciones", datos, AUN, descripcion="Reemplazo del evaporador (prueba)")
    assert (await cliente.post(f"/api/seguimiento/cotizaciones/{c['id']}/convertir", headers=await auth(DES))).status_code == 409  # solicitada → no
    await cambiar_estado(cliente, auth, "cotizaciones", c["id"], "enviada", DES, monto="18400.00", descripcion="Reemplazo del evaporador")
    await cambiar_estado(cliente, auth, "cotizaciones", c["id"], "autorizada", AE, notas="Autorizada")
    assert (await cliente.post(f"/api/seguimiento/cotizaciones/{c['id']}/convertir", headers=await auth(AUN))).status_code == 403
    r = await cliente.post(f"/api/seguimiento/cotizaciones/{c['id']}/convertir", headers=await auth(DES))
    assert r.status_code == 200, r.text
    cot, te = r.json(), r.json()["trabajo_especial"]
    assert cot["estado"] == "convertida" and cot["trabajo_especial_id"] == te["id"] and cot["estado_trabajo_especial"] == "creado"
    assert te["monto"] == "18400.00" and te["un_id"] == str(datos["unidades"][0]) and te["descripcion"] == "Reemplazo del evaporador" and te["cotizacion_numero"] == c["numero"]
    assert te["detalle_json"]["cotizacion_numero"] == c["numero"]
    assert (await cliente.post(f"/api/seguimiento/cotizaciones/{c['id']}/convertir", headers=await auth(DES))).status_code == 409
    # La columna «Estado del trabajo especial» del listado y el detalle de la cotización muestran el estado del TE.
    assert (await detalle_registro(cliente, auth, "cotizaciones", c["id"], DES))["estado_trabajo_especial"] == "creado"
    await accion_te(cliente, auth, DES, te["id"], "enviar", {})
    lista = (await cliente.get("/api/seguimiento/cotizaciones", headers=await auth(AE))).json()
    assert next(x for x in lista if x["id"] == c["id"])["estado_trabajo_especial"] == "enviado_cliente"
    # Kanban de cotizaciones: autorizada → convertida por el cambio genérico de estado.
    c2 = await crear_registro(cliente, auth, "cotizaciones", datos, AUN, descripcion="Otra cotización para el Kanban")
    await cambiar_estado(cliente, auth, "cotizaciones", c2["id"], "enviada", DES, monto="900.00")
    await cambiar_estado(cliente, auth, "cotizaciones", c2["id"], "autorizada", AE)
    k = await cambiar_estado(cliente, auth, "cotizaciones", c2["id"], "convertida", DES)
    assert k["estado"] == "convertida" and k["trabajo_especial_id"]


async def test_kanban_generico_aislamiento_y_reporte(cliente, auth, datos):
    await formulario_te(cliente, auth)
    te = await crear_te(cliente, auth, datos, AP)
    g = await accion_te(cliente, auth, AP, te["id"], "estado", {"estado": "enviado_cliente", "notas": "Kanban"})
    assert g["estado"] == "enviado_cliente"
    assert (await accion_te(cliente, auth, AP, te["id"], "estado", {"estado": "cerrado"}, 409))["codigo"] == "TRANSICION_NO_PERMITIDA"
    # Aislamiento entre tenants y prestadores.
    assert (await cliente.get(f"/api/trabajos-especiales/{te['id']}", headers=await auth(OTRO_AE))).status_code == 404
    assert (await cliente.get(f"/api/trabajos-especiales/{te['id']}", headers=await auth(OTRO_AP))).status_code == 404
    assert all(x["id"] != te["id"] for x in (await cliente.get("/api/trabajos-especiales", headers=await auth(OTRO_AE))).json())
    assert (await cliente.post(f"/api/trabajos-especiales/{te['id']}/aceptar", headers=await auth(OTRO_AE), json={"canal": "app"})).status_code == 404
    assert any(x["id"] == te["id"] for x in (await cliente.get("/api/trabajos-especiales", headers=await auth(SUPO))).json())
    # Reporte: conteo por estado, etapas, % urgencias, monto total; exportable.
    r = (await cliente.get("/api/trabajos-especiales/reporte", headers=await auth(AP))).json()
    assert r["total"] >= 1 and r["por_estado"]["enviado_cliente"] >= 1 and set(r["tiempo_promedio_etapas_dias"]) == {"creado_a_enviado", "enviado_a_respuesta", "aceptado_a_programado", "programado_a_cierre"}
    assert 0 <= r["porcentaje_urgencias"] <= 100 and float(r["monto_total"]) >= 6200
    x = await cliente.get("/api/trabajos-especiales/reporte.xlsx", headers=await auth(AE))
    assert x.status_code == 200 and x.headers["content-type"].startswith("application/vnd.openxmlformats")
    p = await cliente.get("/api/trabajos-especiales/reporte.pdf", headers=await auth(DES), params={"desde": date.today().isoformat()})
    assert p.status_code == 200 and p.content[:4] == b"%PDF"
    assert (await cliente.get("/api/trabajos-especiales/reporte", headers=await auth(TEC))).status_code == 403


async def test_alertas_de_trabajos_especiales(cliente, auth, datos):
    from models.trabajos_especiales import TrabajoEspecial
    from workers import tareas

    await formulario_te(cliente, auth)
    hace = datetime.now(UTC) - timedelta(days=10)
    enviado = await crear_te(cliente, auth, datos, DES, descripcion="TE enviado sin respuesta del cliente")
    await accion_te(cliente, auth, DES, enviado["id"], "enviar", {})
    await retroceder(TrabajoEspecial, enviado["id"], enviado_at=hace, estado_desde=hace)
    aceptado = await crear_te(cliente, auth, datos, DES, descripcion="TE aceptado sin programar")
    await accion_te(cliente, auth, DES, aceptado["id"], "enviar", {})
    await accion_te(cliente, auth, AE, aceptado["id"], "aceptar", {"canal": "app"})
    await retroceder(TrabajoEspecial, aceptado["id"], aceptado_at=hace, estado_desde=hace)
    vencido, _ = await te_programado(cliente, auth, datos, descripcion="TE programado y vencido")
    await retroceder(TrabajoEspecial, vencido["id"], fecha_programada=date.today() - timedelta(days=5))
    await tareas.evaluar_alertas_async()
    assert await alertas_disparadas("TE_SIN_RESPUESTA_CLIENTE", enviado["id"])
    assert await alertas_disparadas("TE_ACEPTADO_SIN_PROGRAMAR", aceptado["id"])
    assert await alertas_disparadas("TE_PROGRAMADO_VENCIDO", vencido["id"])
    d = await detalle_te(cliente, auth, vencido["id"])
    assert "TE_PROGRAMADO_VENCIDO" in d["alertas_activas"]
