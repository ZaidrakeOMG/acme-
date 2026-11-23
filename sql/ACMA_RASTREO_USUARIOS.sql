BEGIN;
-- ACMA: rastreo voluntario de usuarios en PC, Android y iPhone.
-- SIN dependencias de folios. Solo una ultima posicion por usuario.
CREATE TABLE IF NOT EXISTS acma.rastreo_usuarios (
  usuario_id UUID PRIMARY KEY REFERENCES acma.usuarios(id) ON DELETE CASCADE,
  sesion_id UUID NOT NULL REFERENCES acma.sesiones(id) ON DELETE CASCADE,
  tenant_id UUID,
  prestador_id UUID,
  dispositivo VARCHAR(24) NOT NULL DEFAULT 'navegador',
  lat DOUBLE PRECISION,
  lng DOUBLE PRECISION,
  precision_m NUMERIC(8,1),
  consentido_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  ultima_at TIMESTAMPTZ,
  expira_at TIMESTAMPTZ NOT NULL DEFAULT (now() + interval '90 seconds'),
  CONSTRAINT ck_rastreo_usuarios_coords CHECK
    ((lat IS NULL AND lng IS NULL) OR
      (lat BETWEEN -90 AND 90 AND lng BETWEEN -180 AND 180 AND NOT (lat=0 AND lng=0))),
  CONSTRAINT ck_rastreo_usuarios_precision CHECK
    (precision_m IS NULL OR precision_m BETWEEN 0 AND 1000000)
);
CREATE INDEX IF NOT EXISTS ix_rastreo_usuarios_vigencia
  ON acma.rastreo_usuarios (expira_at);
CREATE INDEX IF NOT EXISTS ix_rastreo_usuarios_tenant
  ON acma.rastreo_usuarios (tenant_id, expira_at);
CREATE INDEX IF NOT EXISTS ix_rastreo_usuarios_prestador
  ON acma.rastreo_usuarios (prestador_id, expira_at);
ALTER TABLE acma.rastreo_usuarios ENABLE ROW LEVEL SECURITY;
ALTER TABLE acma.rastreo_usuarios FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS rastreo_usuarios_lectura ON acma.rastreo_usuarios;
CREATE POLICY rastreo_usuarios_lectura ON acma.rastreo_usuarios FOR SELECT USING (
  usuario_id = acma.acma_ctx_usuario()
  OR acma.acma_es_plataforma()
  OR (acma.acma_ctx_rol() IN ('admin_prestador','despachador','mesa_control')
      AND prestador_id IS NOT NULL AND prestador_id = acma.acma_ctx_prestador())
  OR (acma.acma_ctx_rol() = 'admin_empresa'
      AND tenant_id IS NOT NULL AND tenant_id = acma.acma_ctx_tenant())
);
DROP POLICY IF EXISTS rastreo_usuarios_insert ON acma.rastreo_usuarios;
CREATE POLICY rastreo_usuarios_insert ON acma.rastreo_usuarios FOR INSERT
  WITH CHECK (usuario_id = acma.acma_ctx_usuario());
DROP POLICY IF EXISTS rastreo_usuarios_update ON acma.rastreo_usuarios;
CREATE POLICY rastreo_usuarios_update ON acma.rastreo_usuarios FOR UPDATE
  USING (usuario_id = acma.acma_ctx_usuario())
  WITH CHECK (usuario_id = acma.acma_ctx_usuario());
DROP POLICY IF EXISTS rastreo_usuarios_delete ON acma.rastreo_usuarios;
CREATE POLICY rastreo_usuarios_delete ON acma.rastreo_usuarios FOR DELETE
  USING (usuario_id = acma.acma_ctx_usuario());
REVOKE ALL ON acma.rastreo_usuarios FROM PUBLIC;
GRANT SELECT,INSERT,UPDATE,DELETE ON acma.rastreo_usuarios TO acma_api;
COMMIT;
