-- ACMA: confirmar que el backend puede iniciar sesión sin elevar privilegios.
-- SOLO LECTURA. No mostrar contraseñas ni claves.
SELECT rolname AS rol,
       rolcanlogin AS puede_conectarse,
       rolbypassrls AS puede_omitir_rls,
       has_schema_privilege(rolname, 'acma', 'USAGE') AS puede_usar_esquema
FROM pg_roles
WHERE rolname IN ('acma_api', 'acma_owner', 'acma_auth')
ORDER BY rolname;

SELECT
    has_table_privilege('acma_api', 'acma.usuarios', 'SELECT') AS api_lee_usuarios,
    has_table_privilege('acma_api', 'acma.usuarios', 'INSERT') AS api_crea_usuarios,
    has_function_privilege('acma_api', 'acma.auth_identidad_por_email(text)', 'EXECUTE')
      AS api_puede_ejecutar_autenticacion,
    has_schema_privilege('anon', 'acma', 'USAGE') AS acceso_anon,
    has_schema_privilege('authenticated', 'acma', 'USAGE') AS acceso_authenticated;
