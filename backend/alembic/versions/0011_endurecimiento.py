"""0011 — Endurecimiento (§6.9.5): paso TOTP usado, retención de `audit_accesos_api` (90 días normales y 1 año para
errores) y tabla de retención de errores. P11a.

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-04
"""
from alembic import op

from core.sql_migracion import ex

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    ex("SELECT set_config('app.rol', 'sistema', true);")

    # §6.9.5: el mismo código TOTP no se acepta dos veces dentro de su ventana de 30 s.
    ex("""
    ALTER TABLE usuarios ADD COLUMN mfa_ultimo_paso BIGINT;
    COMMENT ON COLUMN usuarios.mfa_ultimo_paso IS 'Último paso TOTP de 30 s consumido; impide la reutilización del código (§6.9.5)';
    """)

    # Retención de la bitácora de API: las llamadas normales se conservan 90 días y los errores 4xx/5xx un año.
    # Como `audit_accesos_api` es append-only (ningún rol puede borrar filas), la purga se hace por particiones:
    # antes de soltar una partición vieja, sus errores se copian a esta tabla, que a su vez se purga por particiones.
    ex("""
    CREATE TABLE audit_accesos_api_errores (
      id UUID NOT NULL,
      created_at TIMESTAMPTZ NOT NULL,
      metodo VARCHAR(10) NOT NULL,
      ruta VARCHAR(300) NOT NULL,
      codigo_respuesta SMALLINT NOT NULL,
      duracion_ms INTEGER NOT NULL,
      usuario_id UUID,
      tenant_id UUID,
      prestador_id UUID,
      ip_origen VARCHAR(64),
      user_agent TEXT,
      PRIMARY KEY (id, created_at)
    ) PARTITION BY RANGE (created_at);
    CREATE INDEX ix_audit_accesos_api_errores_created ON audit_accesos_api_errores (created_at);
    CREATE INDEX ix_audit_accesos_api_errores_codigo ON audit_accesos_api_errores (codigo_respuesta, created_at);
    """)
    # Índice que hace barata la copia de los errores de una partición antes de soltarla.
    ex("CREATE INDEX ix_audit_accesos_api_codigo ON audit_accesos_api (codigo_respuesta, created_at);")

    ex("""
    ALTER TABLE audit_accesos_api_errores ENABLE ROW LEVEL SECURITY;
    ALTER TABLE audit_accesos_api_errores FORCE ROW LEVEL SECURITY;
    CREATE POLICY audit_accesos_api_errores_lectura ON audit_accesos_api_errores FOR SELECT USING (acma_es_plataforma());
    CREATE POLICY audit_accesos_api_errores_insercion ON audit_accesos_api_errores FOR INSERT WITH CHECK (true);
    GRANT SELECT, INSERT ON audit_accesos_api_errores TO acma_api;
    """)
    # El trigger de inmutabilidad de P01 también cubre esta tabla: solo INSERT y SELECT.
    ex("""
    CREATE TRIGGER trg_audit_accesos_api_errores_inmutable
      BEFORE UPDATE OR DELETE OR TRUNCATE ON audit_accesos_api_errores
      FOR EACH STATEMENT EXECUTE FUNCTION acma_auditoria_inmutable();
    """)

    # Crea las particiones del mes en curso y los dos siguientes para la tabla de errores.
    ex("""
    CREATE OR REPLACE FUNCTION acma_crear_particiones_errores_api(meses INTEGER DEFAULT 3)
    RETURNS INTEGER LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
    DECLARE
      i INTEGER;
      inicio DATE;
      fin DATE;
      nombre TEXT;
      creadas INTEGER := 0;
    BEGIN
      FOR i IN 0..(meses - 1) LOOP
        inicio := date_trunc('month', CURRENT_DATE)::date + (i || ' month')::interval;
        fin := inicio + INTERVAL '1 month';
        nombre := 'audit_accesos_api_errores_' || to_char(inicio, 'YYYY_MM');
        IF NOT EXISTS (SELECT 1 FROM pg_class WHERE relname = nombre) THEN
          EXECUTE format('CREATE TABLE %I PARTITION OF audit_accesos_api_errores FOR VALUES FROM (%L) TO (%L)',
                         nombre, inicio, fin);
          creadas := creadas + 1;
        END IF;
      END LOOP;
      RETURN creadas;
    END $$;
    """)
    ex("SELECT acma_crear_particiones_errores_api(3);")

    # §6.7: «toda orden de servicio cerrada conserva su evidencia de forma inmutable por al menos 5 años». El folio
    # cerrado ya era inmutable (P04); aquí se protege además su evidencia, que vivía sin trigger propio. P11a.
    ex("""
    CREATE FUNCTION acma_evidencia_folio_inmutable() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
    DECLARE v_estado TEXT; v_numero TEXT;
    BEGIN
      SELECT f.estado::text, f.numero_folio INTO v_estado, v_numero FROM folios f WHERE f.id = OLD.folio_id;
      IF v_estado IN ('cerrado', 'cancelado') THEN
        RAISE EXCEPTION 'La evidencia del folio % está % y es inmutable (§6.7: retención de 5 años)', v_numero, v_estado
          USING ERRCODE = 'insufficient_privilege';
      END IF;
      RETURN OLD;
    END $$;
    CREATE TRIGGER trg_folio_evidencias_inmutable BEFORE UPDATE OR DELETE ON folio_evidencias
      FOR EACH ROW EXECUTE FUNCTION acma_evidencia_folio_inmutable();
    CREATE TRIGGER trg_folio_evidencias_truncate BEFORE TRUNCATE ON folio_evidencias
      FOR EACH STATEMENT EXECUTE FUNCTION acma_auditoria_inmutable();
    """)

    # El enlace de restablecimiento de contraseña lleva un token firmado: la columna de 300 no alcanza. P11a.
    ex("ALTER TABLE notificaciones ALTER COLUMN url TYPE VARCHAR(600);")

    # Purga por retención: copia los errores de las particiones de `audit_accesos_api` más viejas que `dias_normales`
    # y las suelta; suelta también las particiones de errores más viejas que `dias_errores`. Devuelve el detalle.
    ex("""
    CREATE OR REPLACE FUNCTION acma_purgar_accesos_api(dias_normales INTEGER DEFAULT 90,
                                                       dias_errores INTEGER DEFAULT 365)
    RETURNS TABLE (particion TEXT, accion TEXT, errores_conservados BIGINT)
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
    DECLARE
      r RECORD;
      limite_normales DATE := CURRENT_DATE - dias_normales;
      limite_errores DATE := CURRENT_DATE - dias_errores;
      copiados BIGINT;
      fin DATE;
    BEGIN
      FOR r IN
        SELECT c.relname AS nombre,
               (to_date(right(c.relname, 7), 'YYYY_MM') + INTERVAL '1 month')::date AS hasta
          FROM pg_class c
          JOIN pg_inherits i ON i.inhrelid = c.oid
          JOIN pg_class padre ON padre.oid = i.inhparent
         WHERE padre.relname = 'audit_accesos_api'
           AND c.relname ~ '_[0-9]{4}_[0-9]{2}$'
      LOOP
        IF r.hasta IS NULL OR r.hasta > limite_normales THEN
          CONTINUE;
        END IF;
        -- La partición de errores del mismo mes puede no existir (particiones viejas): se crea al momento.
        fin := date_trunc('month', r.hasta - INTERVAL '1 day')::date;
        IF to_regclass('audit_accesos_api_errores_' || to_char(fin, 'YYYY_MM')) IS NULL THEN
          EXECUTE format('CREATE TABLE %I PARTITION OF audit_accesos_api_errores FOR VALUES FROM (%L) TO (%L)',
                         'audit_accesos_api_errores_' || to_char(fin, 'YYYY_MM'), fin, fin + INTERVAL '1 month');
        END IF;
        EXECUTE format('INSERT INTO audit_accesos_api_errores
                          (id, created_at, metodo, ruta, codigo_respuesta, duracion_ms, usuario_id, tenant_id,
                           prestador_id, ip_origen, user_agent)
                          SELECT id, created_at, metodo, ruta, codigo_respuesta, duracion_ms, usuario_id, tenant_id,
                                 prestador_id, ip_origen, user_agent
                            FROM %I WHERE codigo_respuesta >= 400
                          ON CONFLICT DO NOTHING', r.nombre);
        GET DIAGNOSTICS copiados = ROW_COUNT;
        EXECUTE format('ALTER TABLE audit_accesos_api DETACH PARTITION %I', r.nombre);
        EXECUTE format('DROP TABLE %I', r.nombre);
        particion := r.nombre;
        accion := 'errores_copiados_y_soltada';
        errores_conservados := copiados;
        RETURN NEXT;
      END LOOP;

      FOR r IN
        SELECT c.relname AS nombre,
               (to_date(right(c.relname, 7), 'YYYY_MM') + INTERVAL '1 month')::date AS hasta
          FROM pg_class c
          JOIN pg_inherits i ON i.inhrelid = c.oid
          JOIN pg_class padre ON padre.oid = i.inhparent
         WHERE padre.relname = 'audit_accesos_api_errores'
           AND c.relname ~ '_[0-9]{4}_[0-9]{2}$'
      LOOP
        IF r.hasta IS NULL OR r.hasta > limite_errores THEN
          CONTINUE;
        END IF;
        EXECUTE format('ALTER TABLE audit_accesos_api_errores DETACH PARTITION %I', r.nombre);
        EXECUTE format('DROP TABLE %I', r.nombre);
        particion := r.nombre;
        accion := 'errores_vencidos_soltados';
        errores_conservados := 0;
        RETURN NEXT;
      END LOOP;
    END $$;
    """)
    ex("REVOKE ALL ON FUNCTION acma_purgar_accesos_api(INTEGER, INTEGER) FROM PUBLIC;")
    ex("GRANT EXECUTE ON FUNCTION acma_purgar_accesos_api(INTEGER, INTEGER) TO acma_owner;")
    ex("REVOKE ALL ON FUNCTION acma_crear_particiones_errores_api(INTEGER) FROM PUBLIC;")
    ex("GRANT EXECUTE ON FUNCTION acma_crear_particiones_errores_api(INTEGER) TO acma_owner;")


def downgrade() -> None:
    ex("SELECT set_config('app.rol', 'sistema', true);")
    ex("""
    DROP TRIGGER IF EXISTS trg_folio_evidencias_truncate ON folio_evidencias;
    DROP TRIGGER IF EXISTS trg_folio_evidencias_inmutable ON folio_evidencias;
    DROP FUNCTION IF EXISTS acma_evidencia_folio_inmutable();
    -- Los enlaces de restablecimiento ya emitidos no caben en 300: se recortan antes de angostar la columna.
    UPDATE notificaciones SET url = left(url, 300) WHERE url IS NOT NULL AND length(url) > 300;
    ALTER TABLE notificaciones ALTER COLUMN url TYPE VARCHAR(300);
    """)
    ex("DROP FUNCTION IF EXISTS acma_purgar_accesos_api(INTEGER, INTEGER);")
    ex("DROP FUNCTION IF EXISTS acma_crear_particiones_errores_api(INTEGER);")
    ex("DROP INDEX IF EXISTS ix_audit_accesos_api_codigo;")
    op.execute("DROP TABLE IF EXISTS audit_accesos_api_errores CASCADE;")
    ex("ALTER TABLE usuarios DROP COLUMN IF EXISTS mfa_ultimo_paso;")
