"""Ayudas compartidas por las pruebas de P08 (trabajos especiales, TE de urgencia y OC de activos)."""
from datetime import date, timedelta

from tests.folios_utiles import AP, DES, OP, TEC, accion, tecnico_usuario_id
from tests.seguimiento_utiles import AE, AUN, bandeja, retroceder  # noqa: F401

_cache: dict = {}

ESQUEMA_TE = {"secciones": [{"clave": "trabajo", "titulo": "Trabajo especial", "campos": [
    {"clave": "descripcion_trabajo", "tipo": "texto", "etiqueta": "Descripción detallada", "obligatorio": True, "config": {"longitud_min": 2, "longitud_max": 500}},
    {"clave": "verificacion", "tipo": "si_no", "etiqueta": "Verificación funcional", "config": {}},
    {"clave": "foto_cierre", "tipo": "fotografia", "etiqueta": "Evidencia de cierre", "config": {"cantidad_min": 0, "cantidad_max": 5}},
]}]}


async def formulario_te(cliente, auth) -> dict:
    """Formulario publicado de tipo trabajo_especial asignado a tipo_folio especial (una vez por sesión de pruebas)."""
    if "form_te" not in _cache:
        from tests.test_formularios import crear_formulario, publicar

        f = await crear_formulario(cliente, auth, AP, tipo="trabajo_especial", rol_destino=["tecnico"], esquema=ESQUEMA_TE)
        a = await cliente.post(f"/api/formularios/{f['id']}/asignaciones", headers=await auth(AP), json={"tipo_folio": "especial"})
        assert a.status_code == 201, a.text
        await publicar(cliente, auth, f["id"])
        _cache["form_te"] = f
    return _cache["form_te"]


async def habilitar_te(cliente, auth, email, habilitado=True) -> str:
    """Override individual del permiso ejecutar_trabajos_especiales (§6.8.3); devuelve el usuario_id del técnico."""
    h = await auth(AP)
    lista = (await cliente.get("/api/catalogos/tecnicos", headers=h)).json()
    t = next(x for x in lista if x["email"] == email)
    r = await cliente.put(f"/api/catalogos/tecnicos/{t['id']}/permisos", headers=h,
                          json={"overrides": [{"permiso_clave": "ejecutar_trabajos_especiales", "habilitado": habilitado, "razon": "Prueba P08"}]})
    assert r.status_code == 200, r.text
    return t["usuario_id"]


async def crear_te(cliente, auth, datos, email=DES, esperado=201, **extra) -> dict:
    cuerpo = {"un_id": str(datos["unidades"][0]), "descripcion": "Instalación de cortina de aire en la entrada (prueba)", "monto": "6200.00", **extra}
    r = await cliente.post("/api/trabajos-especiales", headers=await auth(email), json=cuerpo)
    assert r.status_code == esperado, r.text
    return r.json()


async def accion_te(cliente, auth, email, te_id, ruta, cuerpo=None, esperado=200) -> dict:
    r = await cliente.post(f"/api/trabajos-especiales/{te_id}/{ruta}", headers=await auth(email), json=cuerpo or {})
    assert r.status_code == esperado, f"{ruta}: {r.status_code} {r.text}"
    return r.json()


async def detalle_te(cliente, auth, te_id, email=DES, esperado=200) -> dict:
    r = await cliente.get(f"/api/trabajos-especiales/{te_id}", headers=await auth(email))
    assert r.status_code == esperado, r.text
    return r.json()


async def te_programado(cliente, auth, datos, tecnico=TEC, **extra) -> tuple[dict, str]:
    """TE ordinario aceptado por el cliente y programado para hoy con el técnico habilitado; devuelve (detalle, usuario_id del técnico)."""
    await formulario_te(cliente, auth)
    tid = await habilitar_te(cliente, auth, tecnico, True)
    te = await crear_te(cliente, auth, datos, **extra)
    await accion_te(cliente, auth, DES, te["id"], "enviar", {"notas": "Para su validación"})
    await accion_te(cliente, auth, AE, te["id"], "aceptar", {"canal": "app", "comentario": "Adelante"})
    d = await accion_te(cliente, auth, DES, te["id"], "programar", {"fecha_programada": date.today().isoformat(), "tecnico_ids": [tid], "tecnico_responsable_id": tid})
    assert d["estado"] == "programado" and d["folio_id"] and d["estado_folio"] == "asignado"
    return d, tid


async def respuesta_te(cliente, auth, datos, folio_id, tecnico=TEC, con_foto=True) -> str:
    """Respuesta enviada del formulario del TE (origen folio_atencion) con foto de cierre; sin firma (la pone el operador)."""
    from tests.test_formularios_evidencias import _subir, jpeg

    form = await formulario_te(cliente, auth)
    h = await auth(tecnico)
    r = await cliente.post(f"/api/formularios/{form['id']}/respuestas", headers=h,
                           json={"origen": "folio_atencion", "referencia_id": folio_id, "contexto": {"tenant_id": str(datos["tenant"]), "un_id": str(datos["unidades"][0])},
                                 "respuestas": {"descripcion_trabajo": "Se instaló la cortina de aire", "verificacion": True}})
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    if con_foto:
        foto = await _subir(cliente, h, rid, "foto_cierre", "cierre.jpg", jpeg(1024, 768, exif_gps=True), "image/jpeg")
        assert foto.status_code == 201, foto.text
    env = await cliente.post(f"/api/formularios/respuestas/{rid}/enviar", headers=h)
    assert env.status_code == 200, env.text
    return rid


async def cerrar_te_completo(cliente, auth, datos, d, tid, tecnico=TEC) -> dict:
    """Inicia, llena el formulario del TE con foto, firma del operador y cierra."""
    from tests.test_cierre_folio import firmar

    await accion_te(cliente, auth, tecnico, d["id"], "iniciar", {"notas": "Llegué"})
    rid = await respuesta_te(cliente, auth, datos, d["folio_id"], tecnico)
    await accion(cliente, auth, tecnico, d["folio_id"], "atencion", {"respuesta_id": rid}, esperado=201)
    await firmar(cliente, auth, OP, d["folio_id"])
    return await accion_te(cliente, auth, tecnico, d["id"], "cerrar", {"notas": "Terminado"})


def manana() -> str:
    return (date.today() + timedelta(days=1)).isoformat()


__all__ = ["AE", "AUN", "AP", "DES", "OP", "TEC", "accion", "bandeja", "retroceder", "tecnico_usuario_id"]
