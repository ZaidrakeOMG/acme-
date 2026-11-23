BEGIN;
-- ACMA / rastreo voluntario del usuario que comparte su GPS para un folio.
-- Sin historial de recorridos; solo la ultima coordenada con vencimiento de 90 segundos.
-- Ejecucion desde el esquema ACMA. El SQL Editor debe usar la base de datos de ACMA.
CREATE TABLE IF NOT EXISTS acma.rastreos_usuario_folio (
    folio_id UUID NOT NULL REFERENCES acma.folios(id) ON DELETE CASCADE,
    usuario_id UUID NOT NULL REFERENCES acma.usuarios(id),
    sesion_id UUID NOT NULL REFERENCES acma.sesiones(id),
    prestador_id UUID NOT NULL REFERENCES acma.prestadores(id),
    lat DOUBLE PRECISION,
    lng DOUBLE PRECISION,
    precision_m NUMERIC(8,1),
    aceptado_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ultima_at TIMESTAMPTZ,
    expira_at TIMESTAMPTZ NOT NULL DEFAULT (now() + interval '90 seconds'),
    PRIMARY KEY (folio_id, usuario_id),
    CONSTRAINT ck_rastreo_usuario_coordenadas CHECK (
        (lat IS NULL AND lng IS NULL)
        OR (lat BETWEEN -90 AND 90 AND lng BETWEEN -180 AND 180 AND NOT (lat = 0 AND lng = 0))
    ),
    CONSTRAINT ck_rastreo_usuario_precision CHECK (precision_m IS NULL OR precision_m BETWEEN 0 AND 10000)
);
CREATE INDEX IF NOT EXISTS ix_rastreo_usuario_prestador_vigencia
    ON acma.rastreos_usuario_folio (prestador_id, expira_at);
ALTER TABLE acma.rastreos_usuario_folio ENABLE ROW LEVEL SECURITY;
ALTER TABLE acma.rastreos_usuario_folio FORCE ROW LEVEL SECURITY;

-- Solo el usuario que voluntariamente comparte, y personal de despacho de su prestador.
DROP POLICY IF EXISTS rastreos_usuario_folio_lectura ON acma.rastreos_usuario_folio;
CREATE POLICY rastreos_usuario_folio_lectura ON acma.rastreos_usuario_folio FOR SELECT USING (
    usuario_id = acma.acma_ctx_usuario()
    OR acma.acma_es_plataforma()
    OR (prestador_id = acma.acma_ctx_prestador()
        AND acma.acma_ctx_rol() IN ('admin_prestador', 'despachador', 'mesa_control'))
);
DROP POLICY IF EXISTS rastreos_usuario_folio_insercion ON acma.rastreos_usuario_folio;
CREATE POLICY rastreos_usuario_folio_insercion ON acma.rastreos_usuario_folio FOR INSERT
    WITH CHECK (usuario_id = acma.acma_ctx_usuario());
DROP POLICY IF EXISTS rastreos_usuario_folio_actualizacion ON acma.rastreos_usuario_folio;
CREATE POLICY rastreos_usuario_folio_actualizacion ON acma.rastreos_usuario_folio FOR UPDATE
    USING (usuario_id = acma.acma_ctx_usuario())
    WITH CHECK (usuario_id = acma.acma_ctx_usuario());
DROP POLICY IF EXISTS rastreos_usuario_folio_eliminacion ON acma.rastreos_usuario_folio;
CREATE POLICY rastreos_usuario_folio_eliminacion ON acma.rastreos_usuario_folio FOR DELETE
    USING (usuario_id = acma.acma_ctx_usuario());

REVOKE ALL ON acma.rastreos_usuario_folio FROM PUBLIC;
GRANT SELECT, INSERT, UPDATE, DELETE ON acma.rastreos_usuario_folio TO acma_api;
COMMIT;
