"""Evidencias: calidad de foto (tamaño, resolución, compresión), EXIF, firma, inmutabilidad y geofencing."""
import io
import random

import pytest
from PIL import Image
from PIL.TiffImagePlugin import IFDRational
from sqlalchemy import select, text

from core.db import nueva_sesion
from core.rls import CONTEXTO_SISTEMA
from models import AlertaHistorial
from services.formularios import evidencias as ev

AP, TEC, SA = "admin.prestador@acma.dev", "tecnico1@acma.dev", "superadmin@acma.dev"

ESQUEMA = {"secciones": [{"clave": "s", "titulo": "S", "campos": [
    {"clave": "fotos", "tipo": "fotografia", "etiqueta": "Fotos", "obligatorio": True, "config": {"cantidad_min": 1, "cantidad_max": 2, "etiquetas_secuencia": ["Antes", "Después"]}},
    {"clave": "estricta", "tipo": "fotografia", "etiqueta": "Estricta", "config": {"cantidad_min": 0, "cantidad_max": 1, "calidad": {"resolucion_minima_ancho": 2000, "resolucion_minima_alto": 1500}}},
    {"clave": "firma", "tipo": "firma", "etiqueta": "Firma", "config": {"pantalla_completa": True}},
    {"clave": "doc", "tipo": "archivo", "etiqueta": "Documento", "config": {"tipos_permitidos": ["pdf"], "tamano_maximo_mb": 1, "cantidad_max": 1}},
    {"clave": "voz", "tipo": "audio", "etiqueta": "Voz", "config": {"duracion_maxima_seg": 60}},
    {"clave": "geo", "tipo": "geolocalizacion", "etiqueta": "Geo", "obligatorio": True, "config": {"radio_ajuste_m": 50, "geofencing_radio_m": 300, "alertar_fuera_un": True}},
]}]}


def jpeg(ancho=1024, alto=768, calidad=85, ruido=True, exif_gps=False) -> bytes:
    random.seed(1)
    img = Image.new("RGB", (ancho, alto), (120, 140, 160))
    if ruido:
        pixeles = img.load()
        for y in range(0, alto, 2):
            for x in range(0, ancho, 2):
                pixeles[x, y] = (random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))
    salida = io.BytesIO()
    kw = {}
    if exif_gps:
        exif = Image.Exif()
        exif[0x0132] = "2026:10:23 10:15:00"
        gps = exif.get_ifd(0x8825)
        gps[1], gps[2] = "N", (IFDRational(19, 1), IFDRational(25, 1), IFDRational(5736, 100))
        gps[3], gps[4] = "W", (IFDRational(99, 1), IFDRational(7, 1), IFDRational(5952, 100))
        kw["exif"] = exif.tobytes()
    img.save(salida, format="JPEG", quality=calidad, **kw)
    return salida.getvalue()


def png(ancho=400, alto=200) -> bytes:
    salida = io.BytesIO()
    Image.new("RGBA", (ancho, alto), (0, 0, 0, 0)).save(salida, format="PNG")
    return salida.getvalue()


def test_estimacion_de_calidad_jpeg():
    for q in (30, 60, 90):
        img = Image.open(io.BytesIO(jpeg(200, 150, calidad=q, ruido=False)))
        estimada = ev.estimar_calidad_jpeg(img)
        assert abs(estimada - q) <= 4, (q, estimada)
    analisis = ev.analizar_imagen(jpeg(640, 480, exif_gps=True))
    assert analisis.ancho == 640 and analisis.exif_timestamp.year == 2026
    assert analisis.geolat == pytest.approx(19.4326, abs=1e-3) and analisis.geolng == pytest.approx(-99.1332, abs=1e-3)


async def _respuesta(cliente, auth, datos, un_index=0):
    r = await cliente.post("/api/formularios", headers=await auth(AP), json={"nombre": "Evidencias", "rol_destino": ["tecnico"], "esquema": ESQUEMA})
    assert r.status_code == 201, r.text
    fid = r.json()["id"]
    await cliente.post(f"/api/formularios/{fid}/publicar", headers=await auth(AP), json={"notas_version": ""})
    resp = await cliente.post(f"/api/formularios/{fid}/respuestas", headers=await auth(TEC), json={"contexto": {"tenant_id": str(datos["tenant"]), "un_id": str(datos["unidades"][un_index])}})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _subir(cliente, h, rid, campo, nombre, contenido, mime, **campos):
    return await cliente.post(f"/api/formularios/respuestas/{rid}/evidencias", headers=h, data={"campo_clave": campo, **campos},
                              files={"archivo": (nombre, contenido, mime)})


async def test_calidad_de_foto_rechazos_y_aceptacion(cliente, auth, datos):
    rid = await _respuesta(cliente, auth, datos)
    h = await auth(TEC)
    chica = await _subir(cliente, h, rid, "fotos", "chica.jpg", jpeg(200, 150, ruido=False), "image/jpeg")
    assert chica.status_code == 422 and chica.json()["codigo"] == "FOTO_RECHAZADA"
    assert any("KB" in d for d in chica.json()["detalles"]) and any("Resolución" in d for d in chica.json()["detalles"])
    comprimida = await _subir(cliente, h, rid, "fotos", "comprimida.jpg", jpeg(1024, 768, calidad=20), "image/jpeg")
    assert comprimida.status_code == 422 and any("comprimida" in d for d in comprimida.json()["detalles"])
    ok = await _subir(cliente, h, rid, "fotos", "buena.jpg", jpeg(1024, 768, exif_gps=True), "image/jpeg")
    assert ok.status_code == 201, ok.text
    e = ok.json()
    assert e["etiqueta"] == "Antes" and e["ancho_px"] == 1024 and e["calidad"]["ok"] and len(e["hash_sha256"]) == 64
    assert e["geolat"] == pytest.approx(19.4326, abs=1e-3) and e["exif_timestamp"].startswith("2026-10-23")
    # Mínimos por campo sobre los globales: 1024×768 no alcanza 2000×1500.
    estricta = await _subir(cliente, h, rid, "estricta", "buena.jpg", jpeg(1024, 768), "image/jpeg")
    assert estricta.status_code == 422 and any("2000×1500" in d for d in estricta.json()["detalles"])
    # Segunda foto toma la etiqueta "Después"; la tercera excede cantidad_max.
    segunda = await _subir(cliente, h, rid, "fotos", "b.jpg", jpeg(1024, 768, calidad=90), "image/jpeg", anotaciones='{"trazos": [{"tipo": "flecha", "de": [1, 1], "a": [5, 5]}]}')
    assert segunda.status_code == 201 and segunda.json()["etiqueta"] == "Después" and segunda.json()["anotaciones_json"]["trazos"]
    assert (await _subir(cliente, h, rid, "fotos", "c.jpg", jpeg(1024, 768), "image/jpeg")).json()["codigo"] == "LIMITE_FOTOS"
    assert (await _subir(cliente, h, rid, "fotos", "x.gif", b"GIF89a", "image/gif")).json()["codigo"] == "FORMATO_NO_SOPORTADO"
    # Archivo: tipo y tamaño; audio con transcripción pendiente (stub).
    assert (await _subir(cliente, h, rid, "doc", "doc.txt", b"hola", "text/plain")).json()["codigo"] == "FORMATO_NO_SOPORTADO"
    assert (await _subir(cliente, h, rid, "doc", "grande.pdf", b"%PDF" + b"0" * 1_100_000, "application/pdf")).json()["codigo"] == "ARCHIVO_DEMASIADO_GRANDE"
    assert (await _subir(cliente, h, rid, "doc", "doc.pdf", b"%PDF-1.4 ok", "application/pdf")).status_code == 201
    voz = await _subir(cliente, h, rid, "voz", "nota.webm", b"\x1aE\xdf\xa3audio", "audio/webm")
    assert voz.status_code == 201 and voz.json()["anotaciones_json"]["transcripcion"]["estado"] == "pendiente"
    # Descarga y borrado mientras está en progreso.
    descarga = await cliente.get(f"/api/formularios/respuestas/{rid}/evidencias/{e['id']}/archivo", headers=h)
    assert descarga.status_code == 200 and descarga.headers["content-type"] == "image/jpeg"
    assert (await cliente.delete(f"/api/formularios/respuestas/{rid}/evidencias/{segunda.json()['id']}", headers=h)).status_code == 200
    assert len((await cliente.get(f"/api/formularios/respuestas/{rid}/evidencias", headers=h)).json()) == 3


async def test_firma_envio_e_inmutabilidad_de_evidencias(cliente, auth, datos):
    rid = await _respuesta(cliente, auth, datos)
    h = await auth(TEC)
    assert (await _subir(cliente, h, rid, "fotos", "a.jpg", jpeg(), "image/jpeg")).status_code == 201
    sin_firma = await cliente.put(f"/api/formularios/respuestas/{rid}", headers=h, json={"respuestas": {"geo": {"lat": 19.4326, "lng": -99.1332}}})
    assert [e["campo"] for e in sin_firma.json()["errores"]] == ["firma"]
    firma = await _subir(cliente, h, rid, "firma", "firma.png", png(), "image/png")
    assert firma.status_code == 201 and firma.json()["tipo"] == "firma"
    assert (await _subir(cliente, h, rid, "firma", "firma2.png", png(), "image/png")).json()["codigo"] == "FIRMA_DUPLICADA"
    env = await cliente.post(f"/api/formularios/respuestas/{rid}/enviar", headers=h)
    assert env.status_code == 200, env.text
    assert env.json()["respuestas_json"]["fotos"] == {"evidencias": 1}
    # Tras el envío: ni subir, ni borrar, ni modificar (servicio y triggers de BD).
    assert (await _subir(cliente, h, rid, "fotos", "b.jpg", jpeg(), "image/jpeg")).json()["codigo"] == "RESPUESTA_INMUTABLE"
    assert (await cliente.delete(f"/api/formularios/respuestas/{rid}/evidencias/{firma.json()['id']}", headers=h)).json()["codigo"] == "RESPUESTA_INMUTABLE"
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        with pytest.raises(Exception, match="inmutable"):
            await db.execute(text("DELETE FROM formulario_evidencias WHERE id = :i"), {"i": firma.json()["id"]})
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        with pytest.raises(Exception, match="inmutable"):
            await db.execute(text("UPDATE formulario_evidencias SET etiqueta = 'x' WHERE id = :i"), {"i": firma.json()["id"]})
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        with pytest.raises(Exception, match="respuesta enviada"):
            await db.execute(text("""INSERT INTO formulario_evidencias (respuesta_id, campo_clave, tipo, archivo_key, nombre_original, mime, bytes, hash_sha256)
                                     VALUES (:r, 'fotos', 'foto', 'k', 'n', 'image/jpeg', 1, 'h')"""), {"r": rid})


async def test_geofencing_dispara_alerta_y_ajuste_va_a_auditoria(cliente, auth, datos):
    # Dentro del radio de SUC-001 (19.4326, -99.1332): sin alerta.
    rid = await _respuesta(cliente, auth, datos)
    h = await auth(TEC)
    await _subir(cliente, h, rid, "fotos", "a.jpg", jpeg(), "image/jpeg")
    await _subir(cliente, h, rid, "firma", "f.png", png(), "image/png")
    await cliente.put(f"/api/formularios/respuestas/{rid}", headers=h, json={"respuestas": {"geo": {"lat": 19.4330, "lng": -99.1335}}})
    env = await cliente.post(f"/api/formularios/respuestas/{rid}/enviar", headers=h)
    assert env.status_code == 200, env.text
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        assert (await db.execute(select(AlertaHistorial).where(AlertaHistorial.entidad_id == rid))).first() is None
        geo = (await db.execute(text("SELECT contexto_json->'geofencing'->'geo' FROM formulario_respuestas WHERE id = :i"), {"i": rid})).scalar()
    assert geo["fuera"] is False and geo["distancia_m"] < 300
    # A ~5 km, con ajuste manual dentro de 50 m: alerta GEOLOCALIZACION_FUERA_DE_UN y evento geolocalizacion_ajustada.
    rid2 = await _respuesta(cliente, auth, datos)
    await _subir(cliente, h, rid2, "fotos", "a.jpg", jpeg(), "image/jpeg")
    await _subir(cliente, h, rid2, "firma", "f.png", png(), "image/png")
    lejos = {"lat": 19.4800, "lng": -99.1332, "lat_original": 19.4802, "lng_original": -99.1332, "ajustada": True}
    await cliente.put(f"/api/formularios/respuestas/{rid2}", headers=h, json={"respuestas": {"geo": lejos}})
    env = await cliente.post(f"/api/formularios/respuestas/{rid2}/enviar", headers=h)
    assert env.status_code == 200, env.text
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        alerta = (await db.execute(select(AlertaHistorial).where(AlertaHistorial.entidad_id == rid2))).scalar_one()
        assert alerta.clave_alerta == "GEOLOCALIZACION_FUERA_DE_UN" and alerta.datos_contexto_json["distancia_m"] > 4000
    eventos = (await cliente.get("/api/auditoria/eventos", headers=await auth(SA), params={"evento_tipo": "formularios.geolocalizacion_ajustada"})).json()
    assert any(e["recurso_id"] == rid2 for e in eventos)
    # Ajuste fuera del radio permitido: rechazado al enviar.
    rid3 = await _respuesta(cliente, auth, datos)
    await _subir(cliente, h, rid3, "fotos", "a.jpg", jpeg(), "image/jpeg")
    await _subir(cliente, h, rid3, "firma", "f.png", png(), "image/png")
    await cliente.put(f"/api/formularios/respuestas/{rid3}", headers=h, json={"respuestas": {"geo": {"lat": 19.4326, "lng": -99.1332, "lat_original": 19.4400, "lng_original": -99.1332, "ajustada": True}}})
    env = await cliente.post(f"/api/formularios/respuestas/{rid3}/enviar", headers=h)
    assert env.status_code == 422 and "radio" in env.json()["detalles"][0]["mensaje"]
    # La tarea de alertas no duplica la alerta ya registrada.
    from workers import tareas
    resumen = await tareas.evaluar_alertas_async()
    assert resumen["errores"] == 0
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        assert len((await db.execute(select(AlertaHistorial).where(AlertaHistorial.entidad_id == rid2))).scalars().all()) == 1
