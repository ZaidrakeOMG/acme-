#!/usr/bin/env bash
# ACMA: único comando de instalación en un VPS IONOS con Docker Compose ya instalado.
# NO cambia DNS, no modifica BD Supabase y no crea usuarios ni ejecuta migraciones.
set -euo pipefail

cd "$(dirname "$0")/../.."
COMPOSE=(docker compose --env-file .env -f deploy/ionos/compose.yml)

if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
  echo "[ERROR] Falta Docker Engine con el plugin docker compose."
  exit 1
fi
if [[ ! -f .env ]]; then
  echo "[ERROR] Falta el archivo privado /opt/acma/.env."
  echo "Copialo desde el entorno ACMA que ya funciona, con SCP/SFTP cifrado."
  echo "Nunca lo subas a GitHub."
  exit 1
fi
if [[ -z "${ACMA_DOMINIO:-}" ]]; then
  # Compose lee .env sin ejecutar el archivo como código Shell.
  if ! "${COMPOSE[@]}" config --quiet; then
    echo "[ERROR] Falta ACMA_DOMINIO o hay valores mal formados en .env."
    echo "Define ACMA_DOMINIO=acma.dominio-del-cliente.com en .env."
    exit 1
  fi
fi
if ! "${COMPOSE[@]}" config --quiet; then
  echo "[ERROR] Docker Compose no pudo validar la configuracion."
  exit 1
fi
echo "[OK] Configuracion de contenedores validada."
if [[ "${1:-}" == "--completo" ]]; then
  echo "[INFO] Activando Redis, Celery Worker y Celery Beat."
  echo "[INFO] Para chat entre procesos, define TIEMPO_REAL_MODO=redis en .env."
  docker compose --profile completo --env-file .env -f deploy/ionos/compose.yml up -d --build
else
  echo "[INFO] Modo inicial: Web + FastAPI + HTTPS. Redis y Celery desactivados."
  "${COMPOSE[@]}" up -d --build
fi
echo
"${COMPOSE[@]}" ps
echo
echo "Revisa https://TU-DOMINIO/api/salud tras apuntar DNS A al VPS."
echo "Revisa: docker compose --env-file .env -f deploy/ionos/compose.yml logs --tail=80 api"
