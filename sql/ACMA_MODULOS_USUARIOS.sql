-- ACMA / Supabase SQL Editor (PostgreSQL). Ejecutar antes del backend nuevo.
-- Este archivo NO contiene contraseñas. El alta de Liliana se entrega en un script privado.
-- La autenticación propia de ACMA usa Argon2; NO usar crypt()/gen_salt().
BEGIN;
ALTER TABLE acma.usuarios ADD COLUMN IF NOT EXISTS modulos_habilitados JSONB;
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'acma.usuarios'::regclass AND conname = 'ck_usuarios_modulos_json'
  ) THEN
    ALTER TABLE acma.usuarios ADD CONSTRAINT ck_usuarios_modulos_json
    CHECK (modulos_habilitados IS NULL OR jsonb_typeof(modulos_habilitados) = 'array');
  END IF;
END $$;
COMMIT;
