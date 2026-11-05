#!/usr/bin/env bash
# ACMA · restauración de un respaldo (§6.9.5, ACT-10.1: RTO < 4 h, RPO < 1 h).
#
# Restaura la base y, opcionalmente, los archivos del Object Storage. Mide el tiempo real de cada paso y coteja los
# conteos de las tablas críticas contra el registro que dejó `respaldo.sh`, igual que el procedimiento de auditoría.
#
# Uso:
#   ./scripts/restaurar.sh /var/backups/acma/diario/acma_2026-11-05_0130.dump
#   ./scripts/restaurar.sh <dump> --base acma_prueba_restauracion   # ensayo sin tocar producción
#   ./scripts/restaurar.sh <dump> --con-archivos                   # restaura también MinIO
#
# El ensayo trimestral se hace SIEMPRE con --base (una base aparte): así se mide el RTO sin detener el servicio.
# Restaurar sobre la base de producción exige confirmar escribiendo el nombre de la base.

set -euo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$RAIZ"

# shellcheck disable=SC1091
[ -f .env ] && set -a && . ./.env && set +a

PG_SERVICIO="${PG_SERVICIO:-postgres}"
MINIO_SERVICIO="${MINIO_SERVICIO:-minio}"
if [ -z "${COMPOSE_FILE:-}" ]; then
  COMPOSE_FILE="docker-compose.prod.yml"
  [ -f "$COMPOSE_FILE" ] || COMPOSE_FILE="docker-compose.yml"
fi
USUARIO_PG="${POSTGRES_SUPERUSER:-acma_super}"
BASE_PRODUCCION="${POSTGRES_DB:-acma}"
MINIO_BUCKET="${MINIO_BUCKET:-acma}"

compose() { docker compose -f "$COMPOSE_FILE" "$@"; }
log() { printf '%s  %s\n' "$(date +%H:%M:%S)" "$*"; }
morir() { log "ERROR: $*"; exit 1; }

DUMP="${1:-}"
[ -n "$DUMP" ] || morir "indica el archivo .dump a restaurar"
[ -s "$DUMP" ] || morir "no existe o está vacío: $DUMP"
shift

BASE="$BASE_PRODUCCION"
CON_ARCHIVOS=false
while [ $# -gt 0 ]; do
  case "$1" in
    --base) BASE="${2:?falta el nombre de la base}"; shift 2 ;;
    --con-archivos) CON_ARCHIVOS=true; shift ;;
    *) morir "opción desconocida: $1" ;;
  esac
done

if [ "$BASE" = "$BASE_PRODUCCION" ]; then
  log "Vas a SOBRESCRIBIR la base de producción «$BASE». Todo lo que tenga ahora se pierde."
  printf 'Escribe el nombre de la base para confirmar: '
  read -r confirmacion
  [ "$confirmacion" = "$BASE" ] || morir "confirmación incorrecta; no se restauró nada"
fi

INICIO_TOTAL=$(date +%s)
log "Restaurando $DUMP en «$BASE» (compose: $COMPOSE_FILE)"

# 1. El dump se lee completo antes de tocar nada.
log "Verificando el respaldo…"
compose exec -T "$PG_SERVICIO" pg_restore --list < "$DUMP" > /tmp/acma_indice_restauracion.txt \
  || morir "el respaldo no se puede leer: no se restauró nada"
log "  $(grep -c ';' /tmp/acma_indice_restauracion.txt) objetos en el respaldo"

# 2. Base limpia. Los roles (acma_owner, acma_api) viven en el clúster, no en la base: sobreviven al DROP.
log "Recreando la base «$BASE»…"
INICIO_BASE=$(date +%s)
compose exec -T "$PG_SERVICIO" psql -U "$USUARIO_PG" -d postgres -v ON_ERROR_STOP=1 -c \
  "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$BASE' AND pid <> pg_backend_pid();" \
  > /dev/null
compose exec -T "$PG_SERVICIO" psql -U "$USUARIO_PG" -d postgres -v ON_ERROR_STOP=1 \
  -c "DROP DATABASE IF EXISTS $BASE;" -c "CREATE DATABASE $BASE OWNER acma_owner;" > /dev/null \
  || morir "no se pudo recrear la base"
compose exec -T "$PG_SERVICIO" psql -U "$USUARIO_PG" -d "$BASE" -v ON_ERROR_STOP=1 \
  -c "CREATE EXTENSION IF NOT EXISTS postgis;" -c "CREATE EXTENSION IF NOT EXISTS pgcrypto;" > /dev/null

log "Cargando el respaldo…"
# El dump se copia dentro del contenedor porque `pg_restore --jobs` no acepta stdin, y restaurar en paralelo es la
# diferencia entre minutos y horas cuando la base es grande (cuenta para el RTO).
DUMP_EN_CONTENEDOR="/tmp/$(basename "$DUMP")"
compose cp "$DUMP" "${PG_SERVICIO}:${DUMP_EN_CONTENEDOR}" > /dev/null || morir "no se pudo copiar el dump al contenedor"
# Se restaura como superusuario y SIN --no-owner: el dump ya trae a acma_owner como dueno de cada objeto, y eso
# importa porque las tablas llevan FORCE ROW LEVEL SECURITY (las politicas tambien aplican al dueno). Con
# --role=acma_owner fallan los COMMENT ON EXTENSION, que solo puede poner el superusuario.
if ! compose exec -T "$PG_SERVICIO" pg_restore -U "$USUARIO_PG" -d "$BASE" --exit-on-error --jobs=4 "$DUMP_EN_CONTENEDOR"; then
  compose exec -T "$PG_SERVICIO" rm -f "$DUMP_EN_CONTENEDOR" || true
  morir "pg_restore falló"
fi
compose exec -T "$PG_SERVICIO" rm -f "$DUMP_EN_CONTENEDOR" || true
SEGUNDOS_BASE=$(( $(date +%s) - INICIO_BASE ))
log "  base restaurada en ${SEGUNDOS_BASE}s"

# 3. Cotejo con los conteos que dejó el respaldo.
REGISTRO="${DUMP%.dump}.txt"
if [ -f "$REGISTRO" ]; then
  log "Cotejando conteos con $REGISTRO…"
  DIFERENCIAS=0
  # El ciclo lee el registro por stdin y `compose exec` tambien consume stdin: sin `< /dev/null` se come el resto
  # del archivo y solo se coteja la primera tabla.
  while IFS=, read -r tabla esperado; do
    [ -n "$tabla" ] || continue
    [ "$tabla" = "objetos_minio" ] && continue
    # psql imprime tambien la linea "SET" del set_config: se toma el ultimo numero de la salida.
    real="$(compose exec -T "$PG_SERVICIO" psql -U "$USUARIO_PG" -d "$BASE" -t -A -c "SET app.rol='sistema'; SELECT count(*) FROM $tabla;" < /dev/null | grep -oE '[0-9]+' | tail -1)"
    if [ "$real" != "$esperado" ]; then
      log "  DIFERENCIA en $tabla: respaldo $esperado, restaurado $real"
      DIFERENCIAS=$((DIFERENCIAS + 1))
    else
      log "  $tabla: $real ✓"
    fi
  done < "$REGISTRO"
  [ "$DIFERENCIAS" -eq 0 ] || morir "$DIFERENCIAS tablas no coinciden: la restauración NO es buena"
else
  log "AVISO: no hay registro de conteos junto al dump; el cotejo se omite."
fi

# 4. El esquema quedó en la versión que espera la aplicación.
VERSION="$(compose exec -T "$PG_SERVICIO" psql -U "$USUARIO_PG" -d "$BASE" -t -A \
  -c "SELECT version_num FROM alembic_version;" | tr -d '[:space:]')"
log "Versión de esquema restaurada: $VERSION"

# 5. Archivos del Object Storage.
if [ "$CON_ARCHIVOS" = true ]; then
  TAR="$(dirname "$DUMP")/archivos_$(basename "${DUMP%.dump}" | sed 's/^acma_//').tar.gz"
  [ -f "$TAR" ] || morir "no encuentro los archivos del respaldo: $TAR"
  log "Restaurando los objetos de MinIO desde $TAR…"
  INICIO_ARCHIVOS=$(date +%s)
  # El temporal va junto al respaldo, no en /tmp: la extraccion puede ser grande y /tmp suele ser chico.
  TEMPORAL="$(mktemp -d -p "$(dirname "$TAR")")"
  tar -xzf "$TAR" -C "$TEMPORAL"
  ORIGEN="$(find "$TEMPORAL" -maxdepth 1 -type d -name 'archivos_*' | head -1)"
  [ -n "$ORIGEN" ] || ORIGEN="$TEMPORAL"
  # Igual que en el respaldo: los archivos pasan por el contenedor con `compose cp`, no por un bind mount, para que
  # el guion funcione igual en Linux y en Windows.
  DESTINO_CONTENEDOR="/tmp/restaurar_acma_$$"
  compose cp "$ORIGEN" "${MINIO_SERVICIO}:${DESTINO_CONTENEDOR}" > /dev/null || morir "no se pudieron subir los archivos"
  # Se cuentan en el host: la imagen de MinIO no trae `find`.
  OBJETOS_RESTAURADOS=$(find "$ORIGEN" -type f | wc -l | tr -d '[:space:]')
  compose exec -T "$MINIO_SERVICIO" sh -c "
    mc --quiet alias set local http://127.0.0.1:9000 \"\$MINIO_ROOT_USER\" \"\$MINIO_ROOT_PASSWORD\" >/dev/null &&
    mc --quiet mb --ignore-existing local/${MINIO_BUCKET} >/dev/null &&
    mc --quiet mirror --overwrite ${DESTINO_CONTENEDOR} local/${MINIO_BUCKET} >/dev/null" < /dev/null     || morir "la restauración de MinIO falló"
  compose exec -T "$MINIO_SERVICIO" rm -rf "$DESTINO_CONTENEDOR" < /dev/null || true
  rm -rf "$TEMPORAL"
  log "  $OBJETOS_RESTAURADOS objetos restaurados en $(( $(date +%s) - INICIO_ARCHIVOS ))s"
fi

TOTAL=$(( $(date +%s) - INICIO_TOTAL ))
log "Restauración completa en ${TOTAL}s ($(( TOTAL / 60 )) min). Objetivo de §6.9.5: RTO < 4 h."
log "Si fue un ensayo, anota el tiempo en la plantilla de docs/operacion/recuperacion_desastres.md."
