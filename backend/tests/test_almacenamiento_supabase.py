import httpx
import pytest

from services.almacenamiento_supabase import AlmacenamientoSupabase


def test_guardar_y_leer_misma_clave_sin_exponerla_en_url():
    peticiones = []

    def responder(peticion: httpx.Request) -> httpx.Response:
        peticiones.append(peticion)
        if peticion.method == "POST":
            return httpx.Response(200, json={"Key": "folio/1.pdf"})
        if peticion.url.path.startswith("/storage/v1/bucket/"):
            return httpx.Response(200, json={"id": "acma", "name": "acma", "public": False})
        return httpx.Response(200, content=b"cifrado")

    cliente = AlmacenamientoSupabase(
        url="https://acma-prueba.supabase.co", key="secreto-servidor",
        bucket="acma", transport=httpx.MockTransport(responder),
    )
    cliente.guardar("folio/1.pdf", b"cifrado", "application/pdf")
    assert cliente.leer("folio/1.pdf") == b"cifrado"
    cliente.comprobar()

    assert peticiones[0].headers["x-upsert"] == "true"
    assert peticiones[0].content == b"cifrado"
    assert peticiones[0].url.path.endswith("/storage/v1/object/acma/folio/1.pdf")
    assert peticiones[1].url.path.endswith("/storage/v1/object/authenticated/acma/folio/1.pdf")
    assert all("secreto-servidor" not in str(p.url) for p in peticiones)


def test_rechaza_claves_fuera_del_bucket():
    cliente = AlmacenamientoSupabase(url="https://prueba.supabase.co", key="test", bucket="acma")
    with pytest.raises(ValueError):
        cliente.leer("../fuera")
    with pytest.raises(ValueError):
        cliente.leer("/etc/passwd")
    with pytest.raises(ValueError):
        cliente.leer("x\\y")
    with pytest.raises(ValueError):
        AlmacenamientoSupabase(url="http://inseguro", key="test", bucket="acma")
