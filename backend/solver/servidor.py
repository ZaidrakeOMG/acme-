"""Servicio del optimizador de rutas (F2-06).

Existe por una razón concreta: en Windows el **Control de aplicaciones inteligente** bloquea el binario nativo de
OR-Tools, así que la API no puede cargarlo en proceso. En Linux (producción) sí carga y este contenedor no hace
falta. Para que el modelo no se bifurque, el contenedor **no tiene su propia copia**: usa el mismo
`services/rutas/modelo_ortools.py` que la API, montado en la imagen.

No habla con la base, no sabe de clientes ni de folios y **no se publica**: escucha solo en la red interna de
Docker. Recibe el problema ya armado (matrices, ventanas, pesos) y devuelve rutas. Si algún día la API corre donde
OR-Tools carga, se apaga el contenedor y nada más cambia.
"""
import logging
import os

from fastapi import FastAPI
from pydantic import BaseModel, Field

from modelo_ortools import ortools_disponible, resolver

logging.basicConfig(level=os.environ.get("LOG_NIVEL", "INFO"))
log = logging.getLogger("acma.solver")

app = FastAPI(title="ACMA · optimizador de rutas", docs_url=None, redoc_url=None, openapi_url=None)


class Problema(BaseModel):
    tecnicos: list[dict] = Field(default_factory=list)
    paradas: list[dict] = Field(default_factory=list)
    segundos: list[list[int]] = Field(default_factory=list)
    metros: list[list[int]] = Field(default_factory=list)
    pesos: dict = Field(default_factory=dict)
    limite_s: int = 30


@app.get("/salud")
def salud() -> dict:
    return {"estado": "ok" if ortools_disponible() else "sin_ortools", "motor": "ortools"}


@app.post("/resolver")
def resolver_ruta(problema: Problema) -> dict:
    datos = problema.model_dump()
    log.info("resolver: %s técnicos, %s paradas, límite %ss",
             len(datos["tecnicos"]), len(datos["paradas"]), datos["limite_s"])
    resultado = resolver(datos)
    log.info("resuelto en %sms: %s rutas, %s sin asignar",
             resultado.get("ms"), len(resultado.get("rutas", [])), len(resultado.get("sin_asignar", [])))
    return resultado
