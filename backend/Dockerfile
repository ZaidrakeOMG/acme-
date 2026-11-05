# ACMA · imagen del backend (API y workers de Celery). P11a.
#
# Dos etapas: la primera instala las dependencias en un entorno virtual, la segunda solo lleva ese entorno y el
# código. Así la imagen final no carga compiladores y pesa mucho menos.
#
# Construir desde la raíz del repositorio:
#   docker build -f backend/Dockerfile -t acma-api:0.1.0 backend

FROM python:3.12.10-slim-bookworm AS dependencias

# Algunas ruedas se compilan si el índice no tiene binario para esta plataforma.
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential libffi-dev \
    && rm -rf /var/lib/apt/lists/*

ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
# Las herramientas locales (pip-audit, locust, pytest) no van en la imagen de producción.
RUN grep -viE '^(pip-audit|locust|pytest|pytest-asyncio|aiosmtpd)' requirements.txt > requirements.prod.txt \
    && pip install -r requirements.prod.txt \
    && pip install "gunicorn>=23.0"


FROM python:3.12.10-slim-bookworm

# WeasyPrint necesita Pango, Cairo y GDK-Pixbuf para generar los PDF con el diseño completo (en Windows no cargan y
# el código cae a un generador mínimo; aquí sí están). `fonts-dejavu-core` da tipografías con acentos y símbolos.
RUN apt-get update && apt-get install -y --no-install-recommends \
      libpango-1.0-0 libpangoft2-1.0-0 libcairo2 libgdk-pixbuf-2.0-0 \
      libharfbuzz0b libfribidi0 shared-mime-info fonts-dejavu-core \
      curl tzdata \
    && rm -rf /var/lib/apt/lists/*

# Usuario sin privilegios: nada en el contenedor corre como root.
RUN useradd --create-home --uid 10001 acma
# El calendario de Celery beat vive aqui, en un volumen. El directorio se crea en la imagen y con dueno `acma`
# porque Docker copia el dueno del directorio de la imagen al inicializar un volumen vacio; si no existiera, el
# volumen quedaria de root y beat (que no es root) no podria escribir su calendario.
RUN mkdir -p /var/lib/acma && chown acma:acma /var/lib/acma
COPY --from=dependencias /opt/venv /opt/venv

WORKDIR /app
COPY --chown=acma:acma . /app
# Lo que no debe viajar en la imagen.
RUN rm -rf /app/.venv /app/tests /app/pruebas_carga /app/__pycache__ \
    && find /app -name '__pycache__' -prune -exec rm -rf {} + \
    && chown -R acma:acma /app

USER acma
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=America/Mexico_City \
    UVICORN_WORKERS=4

EXPOSE 8000

# El healthcheck pega al mismo endpoint que vigila el monitoreo (§ observabilidad de P11a).
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8000/api/salud || exit 1

# gunicorn con workers uvicorn: reinicia el worker que muera y reparte la carga entre núcleos.
# El número de workers se ajusta por entorno; ver docs/rendimiento/resultados.md para el cálculo con el pool.
CMD ["sh", "-c", "exec gunicorn main:app \
      --worker-class uvicorn.workers.UvicornWorker \
      --workers ${UVICORN_WORKERS} \
      --bind 0.0.0.0:8000 \
      --timeout 120 --graceful-timeout 30 --keep-alive 5 \
      --max-requests 2000 --max-requests-jitter 200 \
      --access-logfile - --error-logfile - --log-level info"]
