from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.frontend_integrado import instalar_frontend


def test_spa_sirve_app_y_no_interfiere_con_api(tmp_path: Path):
    (tmp_path / "index.html").write_text("<h1>ACMA SPA</h1>", encoding="utf-8")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("console.log('ok')", encoding="utf-8")

    app = FastAPI()

    @app.get("/api/salud")
    def salud():
        return {"estado": "ok"}

    assert instalar_frontend(app, tmp_path) is True
    client = TestClient(app)
    assert client.get("/").status_code == 200
    assert client.get("/folios/42").status_code == 200
    assert "console.log" in client.get("/assets/app.js").text
    assert client.get("/api/salud").json() == {"estado": "ok"}
    assert client.get("/api/inexistente").status_code == 404
    assert client.get("/assets/noexiste.js").status_code == 404


def test_sin_build_no_monta_nada(tmp_path: Path):
    app = FastAPI()
    assert instalar_frontend(app, tmp_path) is False
    assert len(app.routes) == 4
