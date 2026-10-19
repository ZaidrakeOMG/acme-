#!/bin/bash
# Crea los roles de aplicación y las bases de datos (dev y pruebas).
#  - acma_owner: dueño del esquema; solo lo usa Alembic para migrar.
#  - acma_api:   rol de la aplicación. NOSUPERUSER, NOBYPASSRLS, no es dueño de tablas.
#  - acma_auth:  NOLOGIN con BYPASSRLS. Solo es dueño de las funciones SECURITY DEFINER de arranque de
#                sesión (buscar usuario por correo, sesión por hash, intentos fallidos).
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
  CREATE ROLE acma_owner LOGIN PASSWORD '${ACMA_OWNER_PASSWORD}' NOSUPERUSER NOBYPASSRLS NOCREATEROLE;
  CREATE ROLE acma_api   LOGIN PASSWORD '${ACMA_API_PASSWORD}'   NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOCREATEDB;
  CREATE ROLE acma_auth  NOLOGIN NOSUPERUSER BYPASSRLS;
  GRANT acma_auth TO acma_owner;
  CREATE DATABASE acma_test OWNER acma_owner;
  ALTER DATABASE acma OWNER TO acma_owner;
EOSQL

for db in acma acma_test; do
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$db" <<-EOSQL
    CREATE EXTENSION IF NOT EXISTS postgis;
    CREATE EXTENSION IF NOT EXISTS pgcrypto;
    ALTER SCHEMA public OWNER TO acma_owner;
    REVOKE ALL ON SCHEMA public FROM PUBLIC;
    GRANT USAGE ON SCHEMA public TO acma_api, acma_auth;
EOSQL
done
