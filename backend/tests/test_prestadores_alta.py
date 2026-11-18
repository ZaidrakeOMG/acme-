"""Regresión: alta de prestadores informa claramente si el RFC ya existe."""


async def test_alta_prestador_rfc_duplicado_error_legible(cliente, auth, datos):
    cabeceras = await auth("superadmin@acma.dev")
    r = await cliente.get("/api/prestadores", headers=cabeceras)
    assert r.status_code == 200, r.text
    prestador = next(p for p in r.json() if p["id"] == str(datos["prestador"]))

    respuesta = await cliente.post("/api/prestadores", headers=cabeceras, json={
        "razon_social": "Prestador duplicado de prueba",
        "rfc": prestador["rfc"],
        "pais": prestador["pais"],
    })
    assert respuesta.status_code == 409, respuesta.text
    assert respuesta.json()["codigo"] == "RFC_PRESTADOR_DUPLICADO"
    assert "Ya existe un prestador" in respuesta.json()["mensaje"]
    assert sum(p["rfc"] == prestador["rfc"] for p in
               (await cliente.get("/api/prestadores", headers=cabeceras)).json()) == 1
