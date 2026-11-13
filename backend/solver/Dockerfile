# Optimizador de rutas (F2-06). Imagen mínima: OR-Tools, FastAPI y el modelo que comparte con la API.
# El modelo NO se copia a mano: se monta desde `backend/services/rutas/modelo_ortools.py` (ver docker-compose.yml),
# para que el contenedor y la API usen exactamente el mismo archivo y no se puedan desincronizar.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY servidor.py /app/servidor.py

# Sin root: el contenedor no necesita privilegios para resolver un modelo matemático.
RUN useradd --create-home --uid 10001 solver
USER solver

EXPOSE 8099

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if 'ok' in urllib.request.urlopen('http://127.0.0.1:8099/salud', timeout=4).read().decode() else 1)"

CMD ["uvicorn", "servidor:app", "--host", "0.0.0.0", "--port", "8099"]
