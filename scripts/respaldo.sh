#!/usr/bin/env bash
# ACMA · respaldo diario (§6.9.5 «respaldo diario a región diferente», ACT-10.1).
#
# Respalda la base completa y los archivos del Object Storage, verifica lo que acaba de escribir, rota lo viejo y,
# si se configura un destino remoto, lo copia fuera del servidor. No usa ningún servicio de pago: el destino remoto
# es cualquier almacenamiento compatible con S3 (otro MinIO, Backblaze B2, Wasabi, S3) o una carpeta montada.
#
# Uso:
#   ./scripts/respaldo.sh                 # respaldo completo (base + archivos)
#   ./scripts/respaldo.sh --solo-base     # únicamente PostgreSQL
#   ./scripts/respaldo.sh --verificar-solo <archivo.dump>
#
# Variables (se leen del .env del despliegue si existe):
#   RESPALDO_DIR          carpeta destino (default /var/backups/acma)
#   RESPALDO_DIARIOS      cuántos diarios conservar (default 14)
#   RESPALDO_SEMANALES    cuántos semanales conservar (default 8)
#   RESPALDO_MENSUALES    cuántos mensuales conservar (default 12)
#   RESPALDO_REMOTO       alias/bucket mc para la copia fuera del servidor, p.ej. "remoto/acma-respaldos"
#   RESPALDO_REMOTO_URL   endpoint del destino remoto (si hay que configurar el alias)
#   RESPALDO_REMOTO_KEY   / RESPALDO_REMOTO_SECRET   credenciales del destino remoto
#   COMPOSE_FILE          compose del despliegue (default docker-compose.prod.yml, o docker-compose.yml si no existe)
#   PG_SERVICIO           servicio de PostgreSQL en el compose (default postgres)
#   MINIO_SERVICIO        servicio de MinIO (default minio)
#
# Cron sugerido (diario a la 01:30, antes de la purga de auditoría de las 03:50):
#   30 1 * * *  cd /opt/acma && ./scripts/respaldo.sh >> /var/log/acma-respaldo.log 2>&1

set -euo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$RAIZ"

# shellcheck disable=SC1091
[ -f .env ] && set -a && . ./.env && set +a

RESPALDO_DIR="${RESPALDO_DIR:-/var/backups/acma}"
RESPALDO_DIARIOS="${RESPALDO_DIARIOS:-14}"
RESPALDO_SEMANALES="${RESPALDO_SEMANALES:-8}"
RESPALDO_MENSUALES="${RESPALDO_MENSUALES:-12}"
PG_SERVICIO="${PG_SERVICIO:-postgres}"
MINIO_SERVICIO="${MINIO_SERVICIO:-minio}"
if [ -z "${COMPOSE_FILE:-}" ]; then
  COMPOSE_FILE="docker-compose.prod.yml"
  [ -f "$COMPOSE_FILE" ] || COMPOSE_FILE="docker-compose.yml"
fi
BASE_DATOS="${POSTGRES_DB:-acma}"
USUARIO_PG="${POSTGRES_SUPERUSER:-acma_super}"
MINIO_BUCKET="${MINIO_BUCKET:-acma}"

FECHA="$(date +%Y-%m-%d_%H%M)"
DIA_SEMANA="$(date +%u)"   # 7 = domingo
DIA_MES="$(date +%d)"
if [ "$DIA_MES" = "01" ]; then CLASE=mensual
elif [ "$DIA_SEMANA" = "7" ]; then CLASE=semanal
else CLASE=diario
fi
DESTINO="$RESPALDO_DIR/$CLASE"
DUMP="$DESTINO/acma_${FECHA}.dump"
ARCHIVOS="$DESTINO/archivos_${FECHA}"
REGISTRO="$DESTINO/acma_${FECHA}.txt"

compose() { docker compose -f "$COMPOSE_FILE" "$@"; }
log() { printf '%s  %s\n' "$(date +%H:%M:%S)" "$*"; }
morir() { log "ERROR: $*"; exit 1; }

# --------------------------------------------------------------- verificación

# Tablas cuyo conteo se compara con la base viva: las que el procedimiento de auditoría de P01 considera críticas.
TABLAS_CRITICAS="folios folio_evidencias audit_log usuarios tenants prestadores contratos minutas gastos_caja_chica"

conteos_vivos() {
  compose exec -T "$PG_SERVICIO" psql -U "$USUARIO_PG" -d "$BASE_DATOS" -t -A -F, -c "
    SET app.rol='sistema';
    $(for t in $TABLAS_CRITICAS; do printf "SELECT '%s', count(*) FROM %s UNION ALL " "$t" "$t"; done | sed 's/ UNION ALL $/;/')"     | grep ','   # psql tambien imprime la linea "SET" del set_config: solo interesan los pares tabla,conteo
}

verificar_dump() {
  local dump="$1"
  log "Verificando $dump"
  [ -s "$dump" ] || morir "el respaldo está vacío"
  # 1. El archivo es un dump válido y legible de principio a fin.
  compose exec -T "$PG_SERVICIO" pg_restore --list < "$dump" > "$dump.indice" \
    || morir "pg_restore --list falló: el respaldo no se puede leer"
  local objetos
  objetos="$(grep -c ';' "$dump.indice" || true)"
  [ "$objetos" -gt 50 ] || morir "el índice del respaldo tiene solo $objetos entradas: algo quedó incompleto"
  # 2. Todas las tablas criticas aparecen en el dump. Se busca la definicion y no "TABLE DATA" porque las tablas
  #    particionadas (audit_log, audit_accesos_api) no tienen datos en la tabla padre, sino en sus particiones.
  for t in $TABLAS_CRITICAS; do
    grep -qE "TABLE public $t( |$)" "$dump.indice" || morir "falta la tabla $t en el respaldo"
  done
  log "  dump válido: $objetos objetos, $(du -h "$dump" | cut -f1)"
}

if [ "${1:-}" = "--verificar-solo" ]; then
  [ -n "${2:-}" ] || morir "indica el archivo a verificar"
  verificar_dump "$2"
  exit 0
fi

SOLO_BASE=false
[ "${1:-}" = "--solo-base" ] && SOLO_BASE=true

mkdir -p "$DESTINO"
INICIO=$(date +%s)
log "Respaldo $CLASE de ACMA · base «$BASE_DATOS» · destino $DESTINO"

# ------------------------------------------------------------------ PostgreSQL

log "Volcando la base (formato custom, compresión 9)…"
compose exec -T "$PG_SERVICIO" pg_dump -U "$USUARIO_PG" -d "$BASE_DATOS" --format=custom --compress=9 \
  --no-password > "$DUMP" || morir "pg_dump falló"
verificar_dump "$DUMP"

log "Guardando los conteos de las tablas críticas para el cotejo de la restauración…"
conteos_vivos > "$REGISTRO" || morir "no se pudieron leer los conteos"
log "  $(tr '\n' ' ' < "$REGISTRO")"

# ------------------------------------------------------------------- archivos

if [ "$SOLO_BASE" = false ]; then
  log "Copiando los objetos de MinIO (bucket $MINIO_BUCKET)…"
  # `mc` ya viene en la imagen de MinIO y corre dentro de la red del compose: no hace falta instalar nada en el
  # servidor. Se copia a un directorio temporal del contenedor y de ahi al host con `docker compose cp`, porque la
  # imagen de MinIO no trae `tar` y los bind mounts no apuntan al mismo lugar en Linux y en Windows.
  # Requiere espacio libre dentro del contenedor equivalente al tamano del bucket.
  TEMP_CONTENEDOR="/tmp/respaldo_acma_$FECHA"
  compose exec -T "$MINIO_SERVICIO" sh -c "
    mc --quiet alias set local http://127.0.0.1:9000 \"\$MINIO_ROOT_USER\" \"\$MINIO_ROOT_PASSWORD\" >/dev/null &&
    mc --quiet mirror --overwrite local/${MINIO_BUCKET} ${TEMP_CONTENEDOR} >/dev/null"     || morir "mc mirror falló"
  compose cp "${MINIO_SERVICIO}:${TEMP_CONTENEDOR}" "$ARCHIVOS" > /dev/null || morir "no se pudo traer la copia al host"
  compose exec -T "$MINIO_SERVICIO" rm -rf "$TEMP_CONTENEDOR" || true
  OBJETOS=$(find "$ARCHIVOS" -type f | wc -l)
  log "  $OBJETOS objetos, $(du -sh "$ARCHIVOS" | cut -f1)"
  echo "objetos_minio,$OBJETOS" >> "$REGISTRO"
  log "Comprimiendo los archivos…"
  tar -czf "$ARCHIVOS.tar.gz" -C "$(dirname "$ARCHIVOS")" "$(basename "$ARCHIVOS")" || morir "no se pudo comprimir"
  tar -tzf "$ARCHIVOS.tar.gz" > /dev/null || morir "el tar de archivos quedó corrupto"
  rm -rf "$ARCHIVOS"
fi

# -------------------------------------------------------------------- rotación

rotar() {
  local carpeta="$1" conservar="$2"
  [ -d "$carpeta" ] || return 0
  # Se cuentan los .dump: cada respaldo tiene uno, y sus acompañantes llevan la misma fecha en el nombre.
  local sobran
  sobran="$(ls -1t "$carpeta"/acma_*.dump 2>/dev/null | tail -n "+$((conservar + 1))" || true)"
  for viejo in $sobran; do
    local marca
    marca="$(basename "$viejo" .dump | sed 's/^acma_//')"
    log "  rotando $marca de $(basename "$carpeta")"
    rm -f "$carpeta"/acma_"$marca".dump "$carpeta"/acma_"$marca".dump.indice "$carpeta"/acma_"$marca".txt \
          "$carpeta"/archivos_"$marca".tar.gz
  done
}

log "Rotando: $RESPALDO_DIARIOS diarios, $RESPALDO_SEMANALES semanales, $RESPALDO_MENSUALES mensuales"
rotar "$RESPALDO_DIR/diario" "$RESPALDO_DIARIOS"
rotar "$RESPALDO_DIR/semanal" "$RESPALDO_SEMANALES"
rotar "$RESPALDO_DIR/mensual" "$RESPALDO_MENSUALES"

# ---------------------------------------------------------- copia fuera del servidor

if [ -n "${RESPALDO_REMOTO:-}" ]; then
  log "Copiando a $RESPALDO_REMOTO (otra región)…"
  if [ -n "${RESPALDO_REMOTO_URL:-}" ]; then
    docker run --rm -v "$RESPALDO_DIR:/datos" --entrypoint sh minio/mc -c "
      mc alias set remoto '$RESPALDO_REMOTO_URL' '$RESPALDO_REMOTO_KEY' '$RESPALDO_REMOTO_SECRET' >/dev/null &&
      mc mirror --overwrite --remove /datos '$RESPALDO_REMOTO'" || morir "la copia remota falló"
  else
    # Destino montado en el servidor (NFS, disco externo, carpeta sincronizada).
    mkdir -p "$RESPALDO_REMOTO"
    rsync -a --delete "$RESPALDO_DIR/" "$RESPALDO_REMOTO/" || morir "el rsync al destino remoto falló"
  fi
  log "  copia remota al día"
else
  log "AVISO: sin RESPALDO_REMOTO el respaldo vive solo en este servidor; §6.9.5 pide una copia en otra región."
fi

log "Listo en $(( $(date +%s) - INICIO )) s · $DUMP"
