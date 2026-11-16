-- ACMA | diagnóstico de proyecto Supabase (solo lectura).
-- Seguro: no escribe, no crea roles, no crea tablas, no cambia RLS.
-- Ejecutar en SQL Editor del proyecto EXCLUSIVO de ACMA.
-- Compartir solo los resultados, NO contraseñas ni claves privadas.
SELECT
    current_database() AS base_datos,
    current_setting('server_version') AS version_postgresql,
    current_user AS usuario_actual,
    (
      SELECT COUNT(*)
      FROM information_schema.tables
      WHERE table_schema = 'public'
        AND table_type = 'BASE TABLE'
    ) AS tablas_publicas,
    (
      SELECT COUNT(*)
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
      WHERE n.nspname = 'public'
        AND c.relkind IN ('r', 'p')
        AND c.relrowsecurity
    ) AS tablas_con_rls,
    (
      SELECT COALESCE(jsonb_agg(extname), '[]'::jsonb)
      FROM pg_extension
      WHERE extname IN ('postgis', 'pgcrypto', 'pg_cron', 'pgmq', 'pg_net')
    ) AS extensiones_instaladas,
    (
      SELECT COALESCE(jsonb_agg(rolname), '[]'::jsonb)
      FROM pg_roles
      WHERE rolname IN ('acma_owner', 'acma_api', 'acma_auth')
    ) AS roles_acma;
