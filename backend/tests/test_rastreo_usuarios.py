"""La ubicación se comparte por USUARIO autenticado, sin ningún folio."""
from tests.folios_utiles import OP, SA, AE, DES, OTRO_AP


async def test_usuario_activa_desde_pc_ve_su_estado_y_lo_detiene(cliente, auth, datos):
    url = "/api/mi-ubicacion"
    h = await auth(OP)
    previo = await cliente.get(url, headers=h)
    assert previo.status_code == 200, previo.text
    assert previo.json()["compartiendo"] is False

    no = await cliente.post(url + "/iniciar", headers=h,
                            json={"acepto": False, "dispositivo": "pc"})
    assert no.status_code == 422

    inicio = await cliente.post(url + "/iniciar", headers=h,
                                json={"acepto": True, "dispositivo": "pc"})
    assert inicio.status_code == 200, inicio.text
    assert inicio.json()["compartiendo"]

    invalida = await cliente.put(url, headers=h,
                                 json={"lat": 91, "lng": -103})
    assert invalida.status_code == 422
    respuesta = await cliente.put(url, headers=h,
                                  json={"lat": 25.54, "lng": -103.42,
                                        "precision_m": 14})
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["ultima_at"]

    propio = await cliente.get(url, headers=h)
    assert propio.json()["compartiendo"]

    vista = await cliente.get("/api/operacion/usuarios-compartiendo",
                              headers=await auth(SA))
    assert vista.status_code == 200, vista.text
    assert any(u["dispositivo"] == "pc" and u["lat"] == 25.54 for u in vista.json())

    # Los otros usuarios no pueden obtener el mapa de vigilancia.
    otro = await cliente.get("/api/operacion/usuarios-compartiendo",
                             headers=await auth(OP))
    assert otro.status_code == 403
    otro_prestador = await cliente.get("/api/operacion/usuarios-compartiendo",
                                       headers=await auth(OTRO_AP))
    assert otro_prestador.status_code == 200, otro_prestador.text
    assert all(not (u["dispositivo"] == "pc" and u["lat"] == 25.54)
               for u in otro_prestador.json())

    parar = await cliente.post(url + "/detener", headers=h)
    assert parar.status_code == 200 and not parar.json()["compartiendo"]
    vista_final = await cliente.get("/api/operacion/usuarios-compartiendo",
                                    headers=await auth(SA))
    assert all(not (u["dispositivo"] == "pc" and u["lat"] == 25.54)
               for u in vista_final.json())


async def test_despachador_no_puede_activar_gps_de_otro_usuario(cliente, auth, datos):
    # No existe endpoint de activar ubicación de un ID ajeno: la ruta es personal.
    # Aunque despachador esté autorizado a VER el mapa de su prestador, nunca
    # puede activar el GPS del operador (o técnico) a distancia.
    h = await auth(DES)
    r = await cliente.post("/api/mi-ubicacion/iniciar", headers=h,
                           json={"acepto": False, "dispositivo": "android"})
    assert r.status_code == 422
