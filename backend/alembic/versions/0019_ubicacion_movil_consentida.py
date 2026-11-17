"""0019 — Compartir ubicación de usuarios en Android con consentimiento y visores autorizados.

No hay historial de rutas: se conserva únicamente la última ubicación, que se
elimina al detener el uso compartido. Nadie comparte ubicación automáticamente.
La visibilidad del mapa exige concesión individual por superadmin y el RLS
impide ver usuarios de otra organización.
"""
from core.sql_migracion import ex, rls

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    ex("""
    CREATE TABLE ubicacion_movil_visores (
        usuario_id UUID PRIMARY KEY REFERENCES usuarios(id) ON DELETE CASCADE,
        habilitado BOOLEAN NOT NULL DEFAULT false,
        otorgado_por UUID REFERENCES usuarios(id) ON DELETE SET NULL,
        actualizado_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE TABLE ubicaciones_movil (
        usuario_id UUID PRIMARY KEY REFERENCES usuarios(id) ON DELETE CASCADE,
        tenant_id UUID REFERENCES tenants(id),
        prestador_id UUID REFERENCES prestadores(id),
        activa BOOLEAN NOT NULL DEFAULT false,
        consentimiento_at TIMESTAMPTZ,
        lat DOUBLE PRECISION,
        lng DOUBLE PRECISION,
        precision_m DOUBLE PRECISION,
        ultima_ubicacion_at TIMESTAMPTZ,
        actualizado_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT ck_ubicacion_lat CHECK (lat IS NULL OR lat BETWEEN -90 AND 90),
        CONSTRAINT ck_ubicacion_lng CHECK (lng IS NULL OR lng BETWEEN -180 AND 180),
        CONSTRAINT ck_ubicacion_precision CHECK (precision_m IS NULL OR precision_m BETWEEN 0 AND 100000),
        CONSTRAINT ck_ubicacion_coordenadas CHECK ((lat IS NULL) = (lng IS NULL)),
        CONSTRAINT ck_ubicacion_ubicacion_consentida CHECK
            (lat IS NULL OR (activa AND consentimiento_at IS NOT NULL))
    );
    CREATE INDEX ix_ubicaciones_movil_recientes
       ON ubicaciones_movil (ultima_ubicacion_at DESC) WHERE activa;
    CREATE INDEX ix_ubicaciones_movil_tenant
       ON ubicaciones_movil (tenant_id, ultima_ubicacion_at DESC) WHERE activa;
    CREATE INDEX ix_ubicaciones_movil_prestador
       ON ubicaciones_movil (prestador_id, ultima_ubicacion_at DESC) WHERE activa;
    """)
    # Privilegios de sesión solo para la API de ACMA: no exponer ubicación a
    # las claves anon/publishable de Supabase.
    ex("""
    REVOKE ALL ON ubicacion_movil_visores, ubicaciones_movil FROM PUBLIC;
    GRANT SELECT, INSERT, UPDATE, DELETE
       ON ubicacion_movil_visores, ubicaciones_movil TO acma_api;
    DO $$
    BEGIN
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        REVOKE ALL ON ubicacion_movil_visores, ubicaciones_movil FROM anon;
      END IF;
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        REVOKE ALL ON ubicacion_movil_visores, ubicaciones_movil FROM authenticated;
      END IF;
    END
    $$;
    """)
    rls("ubicacion_movil_visores",
        """CREATE POLICY visores_leer_propios ON ubicacion_movil_visores FOR SELECT
           USING (acma_es_plataforma() OR usuario_id = acma_ctx_usuario());""",
        """CREATE POLICY visores_gestion_plataforma ON ubicacion_movil_visores FOR ALL
           USING (acma_es_plataforma()) WITH CHECK (acma_es_plataforma());""")
    rls("ubicaciones_movil",
        """CREATE POLICY ubicacion_leer_propias ON ubicaciones_movil FOR SELECT
           USING (usuario_id = acma_ctx_usuario());""",
        """CREATE POLICY ubicacion_actualizar_propias ON ubicaciones_movil FOR ALL
           USING (usuario_id = acma_ctx_usuario() OR acma_es_plataforma())
           WITH CHECK (usuario_id = acma_ctx_usuario() OR acma_es_plataforma());""",
        """CREATE POLICY ubicacion_visores_autorizados ON ubicaciones_movil FOR SELECT
           USING (acma_es_plataforma() OR (
             activa AND ((tenant_id IS NOT NULL AND tenant_id = acma_ctx_tenant())
                OR (prestador_id IS NOT NULL AND prestador_id = acma_ctx_prestador()))
             AND EXISTS (
               SELECT 1 FROM ubicacion_movil_visores v
               WHERE v.usuario_id = acma_ctx_usuario() AND v.habilitado = true
             )
           ));""")


def downgrade() -> None:
    ex("DROP TABLE IF EXISTS ubicaciones_movil; DROP TABLE IF EXISTS ubicacion_movil_visores;")
