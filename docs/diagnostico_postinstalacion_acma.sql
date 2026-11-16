-- ACMA | Auditoría NO destructiva posterior a Alembic 0018.
-- No crea usuarios, no modifica contraseñas, no hace GRANT/REVOKE.
-- Ejecutar en SQL Editor del proyecto NUEVO/exclusivo de ACMA.

-- A. Objetos precargados por las migraciones originales
SELECT 'roles_de_aplicacion' AS elemento, count(*) AS cantidad FROM acma.roles
UNION ALL
SELECT 'permisos_catalogo', count(*) FROM acma.permisos_catalogo
UNION ALL
SELECT 'alertas_catalogo', count(*) FROM acma.alertas_catalogo
UNION ALL
SELECT 'eventos_trigger_catalogo', count(*) FROM acma.eventos_trigger_catalogo
UNION ALL
SELECT 'usuarios', count(*) FROM acma.usuarios;

-- B. Funciones de autenticación y funciones privilegiadas:
-- Revisar especialmente si search_path apunta a public en lugar de acma.
SELECT p.proname AS funcion,
       pg_get_function_identity_arguments(p.oid) AS argumentos,
       pg_get_userbyid(p.proowner) AS propietario,
       p.prosecdef AS security_definer,
       array_to_string(p.proconfig, ', ') AS configuracion
FROM pg_proc p
JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname = 'acma'
  AND (p.proname LIKE 'auth_%' OR p.prosecdef)
ORDER BY p.proname;

-- C. Grupos RLS y permisos:
SELECT rolname, rolcanlogin, rolbypassrls
FROM pg_roles WHERE rolname IN ('acma_api', 'acma_owner', 'acma_auth')
ORDER BY rolname;

-- D. Esquema y tabla de versiones (consulta la fila más reciente).
SELECT version_num FROM acma.alembic_version;
