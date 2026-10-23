"""Validación de respuestas: los 22 tipos (válido/inválido), condiciones, cascada, cálculos en servidor e inmutabilidad."""
from datetime import datetime

import pytest
from sqlalchemy import text

from core.db import nueva_sesion
from core.rls import CONTEXTO_SISTEMA
from schemas.formularios import TIPOS_CAMPO, EsquemaFormulario
from services.formularios.validacion import Contexto, validar, visibilidad

AP, TEC, OP = "admin.prestador@acma.dev", "tecnico1@acma.dev", "operador@acma.dev"
FIJA = {"origen": "fija", "opciones": [{"valor": "a", "etiqueta": "A", "color": "#111111"}, {"valor": "b", "etiqueta": "B", "color": "#222222"}, {"valor": "c", "etiqueta": "C", "color": "#333333"}]}

# Por tipo: (config, fuente, respuesta válida, respuesta inválida, evidencias válidas)
CASOS = {
    "si_no": ({}, None, True, "tal vez", None),
    "opcion_multiple": ({"min_selecciones": 1, "max_selecciones": 2}, FIJA, ["a", "b"], ["a", "b", "c"], None),
    "texto": ({"longitud_min": 2, "longitud_max": 5, "formato": "numeros"}, None, "123", "abc", None),
    "texto_amplio": ({"longitud_min": 5, "longitud_max": 50, "formato": "letras"}, None, "hola mundo", "hola 1", None),
    "fotografia": ({"cantidad_min": 1, "cantidad_max": 2}, None, None, None, {"c": [{"tipo": "foto"}]}),
    "firma": ({}, None, {"timestamp": "2026-10-23T10:00"}, None, {"c": [{"tipo": "firma"}]}),
    "dibujo": ({}, None, None, None, {"c": [{"tipo": "dibujo"}]}),
    "radio": ({}, FIJA, "a", "z", None),
    "boton_grupo": ({}, FIJA, "b", ["a", "b"], None),
    "lista_desplegable": ({"seleccion": "multiple"}, FIJA, ["a", "c"], ["z"], None),
    "seleccion_multiple": ({"min_selecciones": 1, "contador_por_opcion": True, "contador_min": 1, "contador_max": 3}, FIJA, [{"valor": "a", "cantidad": 2}], [{"valor": "a", "cantidad": 9}], None),
    "archivo": ({"cantidad_max": 1}, None, None, None, {"c": [{"tipo": "archivo"}]}),
    "escaner": ({}, None, "QR-123", "", None),
    "audio": ({}, None, None, None, {"c": [{"tipo": "audio"}]}),
    "fecha_hora": ({"modo": "fecha", "fecha_minima": "2026-01-01", "fecha_maxima": "2026-12-31"}, None, "2026-06-15", "2027-01-01", None),
    "slider": ({"minimo": 0, "maximo": 10, "incremento": 2}, None, 4, 5, None),
    "encuesta_satisfaccion": ({"modalidad": "numerica", "escala_max": 10}, None, 7, 11, None),
    "geolocalizacion": ({"radio_ajuste_m": 50}, None, {"lat": 19.4, "lng": -99.1}, {"lat": 95, "lng": 0}, None),
}
CALCULADOS = {"concatenacion", "matematicas_tiempo", "sello_fecha_hora", "etiqueta_info"}


def _esquema(tipo, config, fuente, extra=None):
    campo = {"clave": "c", "tipo": tipo, "etiqueta": "Campo", "obligatorio": True, "config": config}
    if fuente:
        campo["fuente_opciones"] = fuente
    return EsquemaFormulario.model_validate({"secciones": [{"clave": "s", "titulo": "S", "campos": [campo, *(extra or [])]}]})


@pytest.mark.parametrize("tipo", [t for t in TIPOS_CAMPO if t not in CALCULADOS])
def test_cada_tipo_valido_e_invalido(tipo):
    config, fuente, valido, invalido, evidencias = CASOS[tipo]
    esquema = _esquema(tipo, config, fuente)
    ctx = Contexto(evidencias=evidencias or {}, enviado_at=datetime(2026, 10, 23, 12, 0))
    _, errores = validar(esquema, {"c": valido} if valido is not None else {}, ctx)
    assert errores == [], (tipo, errores)
    if invalido is not None:
        _, errores = validar(esquema, {"c": invalido}, ctx)
        assert errores and errores[0]["campo"] == "c", (tipo, errores)
    # Vacío: obligatorio → error (los de evidencia sin evidencias también).
    _, errores = validar(esquema, {}, Contexto(enviado_at=datetime(2026, 10, 23)))
    assert errores and errores[0]["campo"] == "c", tipo


def test_tipos_calculados_en_servidor():
    esquema = EsquemaFormulario.model_validate({"secciones": [{"clave": "s", "titulo": "S", "campos": [
        {"clave": "modelo", "tipo": "texto", "etiqueta": "Modelo"},
        {"clave": "fase", "tipo": "radio", "etiqueta": "Fase", "fuente_opciones": FIJA},
        {"clave": "codigo", "tipo": "concatenacion", "etiqueta": "Código", "config": {"partes": [{"tipo": "texto", "valor": "EQ"}, {"tipo": "campo", "valor": "modelo"}, {"tipo": "campo", "valor": "fase"}], "separador": "-", "mayusculas": True}},
        {"clave": "ini", "tipo": "fecha_hora", "etiqueta": "Ini", "config": {"modo": "ambos"}},
        {"clave": "fin", "tipo": "fecha_hora", "etiqueta": "Fin", "config": {"modo": "ambos", "vinculo": {"rol": "fin", "campo_par": "ini"}}},
        {"clave": "dur", "tipo": "matematicas_tiempo", "etiqueta": "Dur", "config": {"inicio": {"origen": "campo", "valor": "ini"}, "fin": {"origen": "campo", "valor": "fin"}, "unidad": "compuesto"}},
        {"clave": "desde_captura", "tipo": "matematicas_tiempo", "etiqueta": "Desde captura", "config": {"inicio": {"origen": "sistema", "valor": "captura_folio"}, "fin": {"origen": "sistema", "valor": "ahora"}, "unidad": "horas"}},
        {"clave": "sello_abrir", "tipo": "sello_fecha_hora", "etiqueta": "Abrir", "config": {"trigger": "al_abrir"}},
        {"clave": "sello_enviar", "tipo": "sello_fecha_hora", "etiqueta": "Enviar", "config": {"trigger": "al_enviar"}},
        {"clave": "sello_seccion", "tipo": "sello_fecha_hora", "etiqueta": "Sección", "config": {"trigger": "al_llegar_seccion"}},
        {"clave": "info", "tipo": "etiqueta_info", "etiqueta": "Info", "config": {"contenido": "Hola"}},
    ]}]})
    ctx = Contexto(sistema={"captura_folio": "2026-10-23T08:00"}, sellos={"sello_seccion": "2026-10-23T09:30:00"},
                   iniciado_at=datetime(2026, 10, 23, 9, 0), enviado_at=datetime(2026, 10, 23, 12, 0))
    r, errores = validar(esquema, {"modelo": "rv-32", "fase": "b", "codigo": "FALSO", "ini": "2026-10-23T09:00", "fin": "2026-10-24T10:30",
                                   "dur": {"minutos": 1}, "sello_enviar": "1999-01-01T00:00", "info": "no debe guardarse"}, ctx)
    assert errores == []
    assert r["codigo"] == "EQ-RV-32-B"  # el valor del cliente se descarta; la etiqueta de la opción se usa en la concatenación
    assert r["dur"] == {"minutos": 1530, "unidad": "compuesto", "texto": "1d 1h 30min"}
    assert r["desde_captura"]["texto"] == "4.00 h"
    assert r["sello_abrir"] == "2026-10-23T09:00:00" and r["sello_enviar"] == "2026-10-23T12:00:00" and r["sello_seccion"] == "2026-10-23T09:30:00"
    assert "info" not in r


def test_condiciones_ocultan_obligatorios_y_cadena():
    esquema = EsquemaFormulario.model_validate({"secciones": [{"clave": "s", "titulo": "S", "campos": [
        {"clave": "enciende", "tipo": "si_no", "etiqueta": "¿Enciende?", "obligatorio": True},
        {"clave": "detalle", "tipo": "texto", "etiqueta": "Detalle", "obligatorio": True, "condiciones": [{"campo_origen": "enciende", "operador": "igual", "valor": False, "accion": "mostrar"}]},
        {"clave": "nivel", "tipo": "slider", "etiqueta": "Nivel", "config": {"minimo": 0, "maximo": 10, "incremento": 1}, "condiciones": [{"campo_origen": "detalle", "operador": "contiene", "valor": "grave", "accion": "mostrar"}]},
        {"clave": "aviso", "tipo": "etiqueta_info", "etiqueta": "Aviso", "config": {"contenido": "x"}, "condiciones": [{"campo_origen": "nivel", "operador": "en_rango", "valor": [8, 10], "accion": "mostrar"}]},
        {"clave": "siempre", "tipo": "texto", "etiqueta": "Siempre", "condiciones": [{"campo_origen": "enciende", "operador": "igual", "valor": True, "accion": "ocultar"}]},
    ]}]})
    # Encendido: detalle oculto (no obligatorio), nivel oculto porque su origen está oculto, 'siempre' oculto por 'ocultar'.
    assert visibilidad(esquema, {"enciende": True, "detalle": "grave", "nivel": 9}) == {"enciende"}
    _, errores = validar(esquema, {"enciende": True}, Contexto())
    assert errores == []
    # Apagado: detalle obligatorio; con 'grave' aparece nivel; con nivel 9 aparece el aviso.
    _, errores = validar(esquema, {"enciende": False}, Contexto())
    assert [e["campo"] for e in errores] == ["detalle"]
    assert visibilidad(esquema, {"enciende": False, "detalle": "falla grave", "nivel": 9}) == {"enciende", "detalle", "nivel", "aviso", "siempre"}
    r, errores = validar(esquema, {"enciende": False, "detalle": "falla grave", "nivel": 9, "siempre": "ok"}, Contexto())
    assert errores == [] and r == {"enciende": False, "detalle": "falla grave", "nivel": 9, "siempre": "ok"}
    # Valor de un campo oculto se descarta de la respuesta normalizada.
    r, _ = validar(esquema, {"enciende": True, "detalle": "basura", "siempre": "no"}, Contexto())
    assert r == {"enciende": True}


def test_valores_por_defecto_y_opciones_catalogo_sin_resolutor():
    esquema = EsquemaFormulario.model_validate({"secciones": [{"clave": "s", "titulo": "S", "campos": [
        {"clave": "ok", "tipo": "si_no", "etiqueta": "OK", "obligatorio": True, "valor_defecto": True, "config": {"modo_defecto": "con_defecto"}},
        {"clave": "falla", "tipo": "lista_desplegable", "etiqueta": "Falla", "obligatorio": True, "fuente_opciones": {"origen": "catalogo", "catalogo": "tipos_falla", "campo_padre": "familia"}},
        {"clave": "familia", "tipo": "radio", "etiqueta": "Familia", "fuente_opciones": {"origen": "catalogo", "catalogo": "familias_equipo"}},
    ]}]})
    r, errores = validar(esquema, {"falla": "cualquier-id", "familia": "f"}, Contexto())
    assert errores == [] and r["ok"] is True  # default aplicado; catálogo sin resolutor no se verifica
    r, errores = validar(esquema, {"falla": "x"}, Contexto(resolutor=lambda campo: [] if campo.clave == "falla" else None))
    assert errores and errores[0]["campo"] == "falla"


# ---------------------------------------------------------------- vía API

ESQUEMA_API = {"secciones": [{"clave": "s", "titulo": "S", "campos": [
    {"clave": "familia", "tipo": "radio", "etiqueta": "Familia", "obligatorio": True, "fuente_opciones": {"origen": "catalogo", "catalogo": "familias_equipo", "filtro_contexto": False}},
    {"clave": "falla", "tipo": "lista_desplegable", "etiqueta": "Falla", "obligatorio": True, "fuente_opciones": {"origen": "catalogo", "catalogo": "tipos_falla", "campo_padre": "familia"}},
    {"clave": "grave", "tipo": "si_no", "etiqueta": "¿Grave?", "obligatorio": True},
    {"clave": "detalle", "tipo": "texto", "etiqueta": "Detalle", "obligatorio": True, "config": {"longitud_min": 5}, "condiciones": [{"campo_origen": "grave", "operador": "igual", "valor": True, "accion": "mostrar"}]},
    {"clave": "ref", "tipo": "concatenacion", "etiqueta": "Ref", "config": {"partes": [{"tipo": "texto", "valor": "R"}, {"tipo": "campo", "valor": "grave"}], "separador": "-"}},
    {"clave": "sello", "tipo": "sello_fecha_hora", "etiqueta": "Sello", "config": {"trigger": "al_enviar"}},
    {"clave": "llegada", "tipo": "sello_fecha_hora", "etiqueta": "Llegada", "config": {"trigger": "al_llegar_seccion"}},
]}]}


async def _formulario_api(cliente, auth, nombre="Validación API"):
    r = await cliente.post("/api/formularios", headers=await auth(AP), json={"nombre": nombre, "rol_destino": ["tecnico"], "esquema": ESQUEMA_API})
    assert r.status_code == 201, r.text
    await cliente.post(f"/api/formularios/{r.json()['id']}/publicar", headers=await auth(AP), json={"notas_version": "v1"})
    return r.json()["id"]


async def test_respuesta_parcial_envio_cascada_y_calculos(cliente, auth, datos):
    fid = await _formulario_api(cliente, auth)
    h = await auth(TEC)
    familias = {f["nombre"]: f for f in (await cliente.get("/api/catalogos/familias-equipo", headers=h)).json()}
    refri, ilum = familias["Refrigeración"]["id"], familias["Iluminación"]["id"]
    fallas_refri = (await cliente.get("/api/formularios/opciones", headers=h, params={"catalogo": "tipos_falla", "padre": refri})).json()["opciones"]
    fallas_ilum = (await cliente.get("/api/formularios/opciones", headers=h, params={"catalogo": "tipos_falla", "padre": ilum})).json()["opciones"]
    no_enciende_refri = next(o["valor"] for o in fallas_refri if o["etiqueta"] == "No enciende")
    parpadea = next(o["valor"] for o in fallas_ilum if o["etiqueta"] == "Parpadea")

    r = await cliente.post(f"/api/formularios/{fid}/respuestas", headers=h, json={"contexto": {"tenant_id": str(datos["tenant"]), "un_id": str(datos["unidades"][0])}, "respuestas": {"familia": refri}})
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    assert r.json()["estado"] == "en_progreso" and r.json()["tenant_id"] == str(datos["tenant"])
    # Parcial inválido se guarda (reanudable) y reporta errores pendientes; sello de sección fijado por el servidor.
    p = await cliente.put(f"/api/formularios/respuestas/{rid}", headers=h, json={"respuestas": {"familia": refri, "falla": parpadea, "grave": True, "detalle": "ab", "llegada": "cliente"}})
    assert p.status_code == 200, p.text
    assert {e["campo"] for e in p.json()["errores"]} == {"falla", "detalle"}  # cascada: 'Parpadea' no es de Refrigeración
    assert p.json()["respuestas_json"]["detalle"] == "ab"
    env = await cliente.post(f"/api/formularios/respuestas/{rid}/enviar", headers=h)
    assert env.status_code == 422 and env.json()["codigo"] == "RESPUESTA_INVALIDA" and {d["campo"] for d in env.json()["detalles"]} == {"falla", "detalle"}
    # Corrige; el cliente manda ref y sello falsos que el servidor recalcula.
    await cliente.put(f"/api/formularios/respuestas/{rid}", headers=h, json={"respuestas": {"familia": refri, "falla": no_enciende_refri, "grave": True, "detalle": "Se quemó el compresor", "ref": "FALSO", "sello": "1999-01-01T00:00", "llegada": "x"}})
    env = await cliente.post(f"/api/formularios/respuestas/{rid}/enviar", headers=h)
    assert env.status_code == 200, env.text
    rj = env.json()["respuestas_json"]
    assert rj["ref"] == "R-true" and rj["sello"].startswith("2026") and rj["sello"] != "1999-01-01T00:00"
    assert rj["llegada"].startswith("2026") and rj["llegada"] <= rj["sello"]
    assert env.json()["estado"] == "enviado" and env.json()["inmutable"]
    # Inmutable: servicio y base de datos.
    assert (await cliente.put(f"/api/formularios/respuestas/{rid}", headers=h, json={"respuestas": {}})).json()["codigo"] == "RESPUESTA_INMUTABLE"
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        with pytest.raises(Exception, match="inmutable"):
            await db.execute(text("UPDATE formulario_respuestas SET respuestas_json = '{}' WHERE id = :i"), {"i": rid})
    # Otro técnico no ve la respuesta; el admin empresa del tenant sí (resultados).
    assert (await cliente.get(f"/api/formularios/respuestas/{rid}", headers=await auth("tecnico2@acma.dev"))).status_code == 404
    assert (await cliente.get(f"/api/formularios/respuestas/{rid}", headers=await auth("admin.empresa@acma.dev"))).status_code == 200
    assert (await cliente.get(f"/api/formularios/respuestas/{rid}", headers=await auth("admin.otro@acma.dev"))).status_code == 404
    mias = (await cliente.get("/api/formularios/respuestas", headers=h, params={"formulario_id": fid})).json()
    assert [m["id"] for m in mias] == [rid]


async def test_rol_destino_y_contexto(cliente, auth, datos):
    fid = await _formulario_api(cliente, auth, "Solo técnicos")
    assert (await cliente.post(f"/api/formularios/{fid}/respuestas", headers=await auth(OP), json={})).status_code == 403
    malo = await cliente.post(f"/api/formularios/{fid}/respuestas", headers=await auth(TEC), json={"contexto": {"tenant_id": str(datos["tenant"]), "un_id": str(datos["un_otro"])}})
    assert malo.json()["codigo"] == "UNIDAD_INVALIDA"
    assert (await cliente.post(f"/api/formularios/{fid}/respuestas", headers=await auth(TEC), json={"contexto": {"tenant_id": str(datos["otro_tenant"])}})).json()["codigo"] == "TENANT_NO_VINCULADO"
