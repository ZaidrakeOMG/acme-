# ACMA: despliegue unificado React + FastAPI para IONOS VPS / otras plataformas Docker.
# Contexto de compilacion: RAIZ del repositorio (no backend/).
# No contiene secretos, ni crea bases de datos, ni ejecuta migraciones.
#
# La SPA compilada se sirve desde FastAPI (core.frontend_integrado).
# El APK Flutter de produccion usa la misma URL HTTPS.

FROM node:22-alpine AS web
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim-bookworm AS python-deps
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libffi-dev \
    && rm -rf /var/lib/apt/lists/*
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY backend/requirements.txt /tmp/requirements.txt
# No incluir pruebas de carga ni herramientas de desarrollo en produccion.
RUN grep -viE '^(pip-audit|locust|pytest|pytest-asyncio|aiosmtpd)' \
        /tmp/requirements.txt > /tmp/requirements.prod.txt \
    && pip install -r /tmp/requirements.prod.txt

FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpango-1.0-0 libpangoft2-1.0-0 libcairo2 \
        libgdk-pixbuf-2.0-0 libharfbuzz0b libfribidi0 \
        shared-mime-info fonts-dejavu-core tzdata \
    && rm -rf /var/lib/apt/lists/*
RUN useradd --create-home --uid 10001 acma \
    && mkdir -p /app/backend /app/frontend/dist /var/lib/acma \
    && chown -R acma:acma /app /var/lib/acma
COPY --from=python-deps /opt/venv /opt/venv
COPY --chown=acma:acma backend/ /app/backend/
COPY --from=web --chown=acma:acma /build/frontend/dist/ /app/frontend/dist/
WORKDIR /app/backend
USER acma
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=America/Mexico_City
EXPOSE 8000
# Railway entrega PORT y RAILWAY_PUBLIC_DOMAIN; en un VPS Compose entrega PORT y el dominio HTTPS.
# El lanzador configura origen, MFA y pool antes de que FastAPI importe la configuracion.
# Nunca se incluyen JWT_SECRETO, CLAVE_CIFRADO ni SUPABASE_SECRET_KEY en la imagen.
CMD ["python", "railway_start.py"]
