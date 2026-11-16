-- ACMA / Supabase Storage: crear bucket privado faltante.
-- Esta consulta modifica ÚNICAMENTE storage.buckets para el bucket "acma".
-- NO borra archivos ni toca el esquema de negocio acma, public ni auth.
-- Ejecutar en SQL Editor del proyecto NUEVO de ACMA.
BEGIN;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM storage.buckets WHERE id = 'acma' AND public) THEN
    RAISE EXCEPTION 'El bucket acma existente es PÚBLICO. Revisar antes de continuar.';
  END IF;
END $$;

INSERT INTO storage.buckets (id, name, public)
VALUES ('acma', 'acma', false)
ON CONFLICT (id) DO NOTHING;

-- No se otorgan permisos al cliente anon ni authenticated: los objetos
-- se suben y descargan únicamente desde FastAPI con clave secreta
-- almacenada en el servidor. ACMA cifra todos los archivos AES-256-GCM.

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM storage.buckets
    WHERE id = 'acma' AND name = 'acma' AND public = false
  ) THEN
    RAISE EXCEPTION 'El bucket acma no quedó en estado privado; revisar.';
  END IF;
END $$;

COMMIT;
SELECT id, name, public FROM storage.buckets WHERE id = 'acma';