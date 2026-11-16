#!/usr/bin/env bash
# ACMA para VPS IONOS Linux. Sin migraciones ni altas/bajas en Supabase.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."
OPCION="${1:---basico}"
case "$OPCION" in
  --basico|--completo|--verificar) ;;
  *) echo "Uso: bash deploy/ionos/desplegar.sh [--basico|--completo|--verificar]"; exit 2 ;;
esac

echo "=================================================="
echo " ACMA - Instalacion en VPS IONOS"
echo "=================================================="
if [[ ! -f .env ]]; then
  echo "[ERROR] Falta .env en la raiz del repositorio."
  echo "Copia deploy/ionos/variables.template y rellena SOLO en el VPS."
  exit 1
fi
# No hacer 'source .env': un archivo con secretos no debe ejecutarse como shell.
for clave in ACMA_DOMINIO DATABASE_URL SUPABASE_URL SUPABASE_SECRET_KEY JWT_SECRETO CLAVE_CIFRADO; do
  if ! grep -qE "^${clave}=.+" .env; then
    echo "[ERROR] Falta ${clave} en .env o esta vacio."
    exit 1
  fi
done
dominio="$(grep '^ACMA_DOMINIO=' .env | tail -n 1 | cut -d= -f2- | tr -d '\r')"
if [[ ! "$dominio" =~ ^[a-zA-Z0-9][a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$ ]] || [[ "$dominio" == *"tu-dominio"* || "$dominio" == *"example"* ]]; then
  echo "[ERROR] ACMA_DOMINIO debe ser un subdominio REAL, solo hostname sin https://."
  exit 1
fi
if grep -qE '^(DATABASE_URL|SUPABASE_URL|SUPABASE_SECRET_KEY|JWT_SECRETO|CLAVE_CIFRADO)=.*(REEMPLAZAR|TU_PROYECTO|HOST_POOLER|CONTRASENA|USUARIO_ACMA_API)' .env; then
  echo "[ERROR] .env aun tiene valores de ejemplo. No pongas secretos en GitHub."
  exit 1
fi
if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
  echo "[ERROR] Instala Docker Engine y Docker Compose plugin en el VPS."
  exit 1
fi
if ! docker info >/dev/null 2>&1; then
  echo "[ERROR] Sin permisos para ejecutar Docker. Usa una cuenta autorizada."
  exit 1
fi

COMPOSE=(docker compose --env-file .env -f deploy/ionos/compose.yml)
if [[ "$OPCION" == --completo ]]; then
  # Exportar solo la modalidad; los secretos siguen protegidos dentro de .env.
  export TIEMPO_REAL_MODO=redis
  echo "[INFO] Modo completo: React + API + HTTPS + Redis + Celery + Beat."
else
  export TIEMPO_REAL_MODO=local
  echo "[INFO] Modo basico: React + API + HTTPS, sin tareas programadas."
fi

"${COMPOSE[@]}" config --quiet
if [[ "$OPCION" == --completo ]]; then
  docker compose --profile completo --env-file .env -f deploy/ionos/compose.yml config --quiet
  memoria_kb="$(awk '/^MemTotal:/ {print $2}' /proc/meminfo || true)"
  if [[ "${memoria_kb:-0}" -lt 6000000 ]]; then
    echo "[AVISO] Menos de 6 GB RAM. Para modo completo se recomienda VPS de 8 GB o mas."
  fi
fi
if command -v df >/dev/null 2>&1; then
  libre_kb="$(df -Pk . | awk 'END {print $4}')"
  if [[ "${libre_kb:-0}" -lt 8000000 ]]; then
    echo "[AVISO] Menos de 8 GB libres. El build Docker puede quedarse sin espacio."
  fi
fi
if command -v getent >/dev/null 2>&1 && ! getent ahostsv4 "$dominio" >/dev/null; then
  echo "[AVISO] El subdominio no resuelve todavia por IPv4. Configura su registro DNS A."
fi

echo "[OK] Docker Compose validado sin mostrar secretos."
if [[ "$OPCION" == --verificar ]]; then
  echo "[OK] Solo verificacion: no se cambiaron ni encendieron contenedores."
  exit 0
fi
if [[ "$OPCION" == --completo ]]; then
  docker compose --profile completo --env-file .env -f deploy/ionos/compose.yml up -d --build
else
  "${COMPOSE[@]}" up -d --build
fi

echo
"${COMPOSE[@]}" ps
echo
echo "=================================================="
echo " ACMA Web: https://${dominio}"
echo " API salud: https://${dominio}/api/salud"
echo "=================================================="
echo "Revisa logs con: docker compose --env-file .env -f deploy/ionos/compose.yml logs --tail=80 api"
echo "Si falla HTTPS, revisa DNS, puertos 80/443, y logs del contenedor caddy."
