"""Compartir ubicacion de un usuario para un folio: consentimiento, visibilidad, fin y aislamiento."""
from tests.folios_utiles import (AE, DES, OP, OTRO_AP, capturar, nuevo_equipo)


async def test_un_usuario_comparte_solo_su_gps_y_lo_puede_detener(cliente, auth, datos):
    equipo = await nuevo_equipo(cliente, auth, datos)
    folio = await capturar(cliente, auth, datos, email=OP, equipo=equipo)
    ruta = f"/api/folios/{folio['id']}"

    previo = await cliente.get(ruta + "/mi-rastreo", headers=await auth(OP))
    assert previo.status_code == 200, previo.text
    assert previo.json()["compartiendo"] is False

    sin_consentimiento = await cliente.post(
        ruta + "/compartir-ubicacion", headers=await auth(OP), json={"acepto": False}
    )
    assert sin_consentimiento.status_code == 422
    # El despachador puede VER el rastreo voluntario, pero no encender el GPS de otro usuario.
    ajeno = await cliente.post(
        ruta + "/compartir-ubicacion", headers=await auth(DES), json={"acepto": True}
    )
    assert ajeno.status_code == 403

    inicio = await cliente.post(ruta + "/compartir-ubicacion", headers=await auth(OP),
                                json={"acepto": True})
    assert inicio.status_code == 200, inicio.text
    assert inicio.json()["compartiendo"] is True

    invalido = await cliente.put(ruta + "/compartir-ubicacion", headers=await auth(OP),
                                 json={"lat": 91, "lng": -103})
    assert invalido.status_code == 422

    actualizado = await cliente.put(ruta + "/compartir-ubicacion", headers=await auth(OP),
                                    json={"lat": 25.54, "lng": -103.42, "precision_m": 12})
    assert actualizado.status_code == 200, actualizado.text

    visible = await cliente.get("/api/operacion/usuarios-compartiendo", headers=await auth(DES))
    assert visible.status_code == 200, visible.text
    assert any(f["folio_id"] == folio["id"] and f["lat"] == 25.54 for f in visible.json())

    # Un cliente y otro prestador no pueden consultar la geolocalizacion.
    denegado = await cliente.get("/api/operacion/usuarios-compartiendo", headers=await auth(AE))
    assert denegado.status_code == 403
    otro = await cliente.get("/api/operacion/usuarios-compartiendo", headers=await auth(OTRO_AP))
    assert otro.status_code == 200
    assert all(f["folio_id"] != folio["id"] for f in otro.json())

    fin = await cliente.post(ruta + "/detener-ubicacion", headers=await auth(OP))
    assert fin.status_code == 200 and fin.json()["compartiendo"] is False
    despues = await cliente.get("/api/operacion/usuarios-compartiendo", headers=await auth(DES))
    assert all(f["folio_id"] != folio["id"] for f in despues.json())
