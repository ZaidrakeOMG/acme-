"""0003 — Motor de formularios dinámicos (§4.3, §6.8.3c): formularios versionados, asignaciones, permisos de mesa,
catálogos personalizados, respuestas inmutables, evidencias y defaults de calidad de foto.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-23
"""
from alembic import op

from core.sql_migracion import ex, rls, versionar

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

TABLAS = [
    "formularios", "formulario_versiones", "formulario_asignaciones", "formulario_permisos_mesa",
    "catalogos_personalizados", "catalogo_personalizado_opciones", "formulario_respuestas", "formulario_evidencias",
    "calidad_foto_defaults",
]

base = """
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      version_hash VARCHAR(64)"""

# Visible si es de plataforma (prestador_id NULL) o del prestador/sus clientes, y respeta el alcance por tenant.
LECTURA_FORMULARIO = ("((prestador_id IS NULL AND acma_hay_contexto()) OR acma_prestador_visible(prestador_id))"
                      " AND (tenant_id IS NULL OR acma_tenant_visible(tenant_id))")
ESCRITURA_PRESTADOR = "(acma_es_plataforma() OR (prestador_id IS NOT NULL AND prestador_id = acma_ctx_prestador()))"
# Respuestas y evidencias: el tenant dueño y los prestadores que lo atienden; sin tenant, solo el prestador del autor.
DUENIO_RESPUESTA = ("(acma_es_plataforma() OR (tenant_id IS NOT NULL AND acma_tenant_visible(tenant_id))"
                    " OR (tenant_id IS NULL AND prestador_id IS NOT NULL AND prestador_id = acma_ctx_prestador()))")


def upgrade() -> None:
    ex("SELECT set_config('app.rol', 'sistema', true);")
    ex("""
    CREATE TYPE tipo_formulario AS ENUM ('captura_operador','atencion_tecnico','preventivo','trabajo_especial','encuesta','libre');
    CREATE TYPE estado_formulario AS ENUM ('borrador','publicado','archivado');
    CREATE TYPE origen_respuesta AS ENUM ('folio_captura','folio_atencion','preventivo','trabajo_especial','encuesta','independiente');
    CREATE TYPE estado_respuesta AS ENUM ('en_progreso','enviado');
    CREATE TYPE tipo_evidencia AS ENUM ('foto','firma','dibujo','archivo','audio');
    """)

    ex(f"""
    CREATE TABLE formularios ({base},
      prestador_id UUID REFERENCES prestadores(id),
      tenant_id UUID REFERENCES tenants(id),
      nombre VARCHAR(160) NOT NULL,
      descripcion TEXT NOT NULL DEFAULT '',
      tipo tipo_formulario NOT NULL DEFAULT 'libre',
      rol_destino JSONB NOT NULL DEFAULT '[]'::jsonb,
      estado estado_formulario NOT NULL DEFAULT 'borrador',
      version_publicada_id UUID,
      es_plantilla_base BOOLEAN NOT NULL DEFAULT false,
      clonado_de_id UUID,
      CONSTRAINT ck_formularios_plantilla CHECK (NOT es_plantilla_base OR prestador_id IS NULL),
      CONSTRAINT ck_formularios_tenant_requiere_prestador CHECK (tenant_id IS NULL OR prestador_id IS NOT NULL)
    );
    CREATE INDEX ix_formularios_prestador ON formularios (prestador_id, estado);
    CREATE INDEX ix_formularios_tenant ON formularios (tenant_id);

    CREATE TABLE formulario_versiones ({base},
      formulario_id UUID NOT NULL REFERENCES formularios(id) ON DELETE CASCADE,
      prestador_id UUID REFERENCES prestadores(id),
      tenant_id UUID REFERENCES tenants(id),
      numero_version INTEGER NOT NULL CHECK (numero_version >= 1),
      esquema_json JSONB NOT NULL,
      publicada_at TIMESTAMPTZ,
      publicada_por UUID REFERENCES usuarios(id),
      notas_version TEXT NOT NULL DEFAULT '',
      CONSTRAINT uq_formulario_versiones UNIQUE (formulario_id, numero_version)
    );
    ALTER TABLE formularios ADD CONSTRAINT fk_formularios_version_publicada
      FOREIGN KEY (version_publicada_id) REFERENCES formulario_versiones(id) DEFERRABLE INITIALLY DEFERRED;

    -- plan_mantenimiento_id sin FK: la tabla planes_mantenimiento llega en P06 (agregar la constraint allí).
    CREATE TABLE formulario_asignaciones ({base},
      formulario_id UUID NOT NULL REFERENCES formularios(id) ON DELETE CASCADE,
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      tenant_id UUID REFERENCES tenants(id),
      tipo_folio VARCHAR(40),
      tipo_equipo_id UUID REFERENCES tipos_equipo(id),
      familia_equipo_id UUID REFERENCES familias_equipo(id),
      plan_mantenimiento_id UUID,
      prioridad INTEGER NOT NULL DEFAULT 0,
      activa BOOLEAN NOT NULL DEFAULT true
    );
    CREATE INDEX ix_formulario_asignaciones_busqueda ON formulario_asignaciones (prestador_id, activa, tenant_id, tipo_folio);

    CREATE TABLE formulario_permisos_mesa ({base},
      formulario_id UUID NOT NULL REFERENCES formularios(id) ON DELETE CASCADE,
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      usuario_id UUID NOT NULL REFERENCES usuarios(id),
      puede_editar_publicado BOOLEAN NOT NULL DEFAULT true,
      CONSTRAINT uq_formulario_permisos_mesa UNIQUE (formulario_id, usuario_id)
    );

    CREATE TABLE catalogos_personalizados ({base},
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      tenant_id UUID REFERENCES tenants(id),
      nombre VARCHAR(120) NOT NULL,
      clave VARCHAR(60) NOT NULL,
      activo BOOLEAN NOT NULL DEFAULT true
    );
    CREATE UNIQUE INDEX uq_catalogos_personalizados ON catalogos_personalizados
      (prestador_id, COALESCE(tenant_id, '00000000-0000-0000-0000-000000000000'::uuid), clave);

    CREATE TABLE catalogo_personalizado_opciones ({base},
      catalogo_id UUID NOT NULL REFERENCES catalogos_personalizados(id) ON DELETE CASCADE,
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      tenant_id UUID REFERENCES tenants(id),
      valor VARCHAR(120) NOT NULL,
      etiqueta VARCHAR(200) NOT NULL,
      orden INTEGER NOT NULL DEFAULT 0,
      activa BOOLEAN NOT NULL DEFAULT true,
      padre_opcion_id UUID REFERENCES catalogo_personalizado_opciones(id) ON DELETE SET NULL,
      CONSTRAINT uq_catalogo_personalizado_opciones UNIQUE (catalogo_id, valor)
    );

    CREATE TABLE formulario_respuestas ({base},
      formulario_id UUID NOT NULL REFERENCES formularios(id),
      version_id UUID NOT NULL REFERENCES formulario_versiones(id),
      tenant_id UUID REFERENCES tenants(id),
      prestador_id UUID REFERENCES prestadores(id),
      un_id UUID REFERENCES unidades_negocio(id),
      equipo_id UUID REFERENCES equipos(id),
      origen origen_respuesta NOT NULL DEFAULT 'independiente',
      referencia_id UUID,
      respuestas_json JSONB NOT NULL DEFAULT '{{}}'::jsonb,
      contexto_json JSONB NOT NULL DEFAULT '{{}}'::jsonb,
      respondido_por UUID NOT NULL REFERENCES usuarios(id),
      iniciado_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      enviado_at TIMESTAMPTZ,
      estado estado_respuesta NOT NULL DEFAULT 'en_progreso',
      dispositivo_json JSONB NOT NULL DEFAULT '{{}}'::jsonb,
      inmutable BOOLEAN NOT NULL DEFAULT false,
      CONSTRAINT ck_formulario_respuestas_duenio CHECK (tenant_id IS NOT NULL OR prestador_id IS NOT NULL),
      CONSTRAINT ck_formulario_respuestas_enviado CHECK ((estado = 'enviado') = (enviado_at IS NOT NULL))
    );
    CREATE INDEX ix_formulario_respuestas_formulario ON formulario_respuestas (formulario_id, estado);
    CREATE INDEX ix_formulario_respuestas_referencia ON formulario_respuestas (origen, referencia_id);
    CREATE INDEX ix_formulario_respuestas_autor ON formulario_respuestas (respondido_por, estado);

    CREATE TABLE formulario_evidencias ({base},
      respuesta_id UUID NOT NULL REFERENCES formulario_respuestas(id) ON DELETE CASCADE,
      tenant_id UUID REFERENCES tenants(id),
      prestador_id UUID REFERENCES prestadores(id),
      campo_clave VARCHAR(60) NOT NULL,
      tipo tipo_evidencia NOT NULL,
      archivo_key VARCHAR(300) NOT NULL,
      archivo_anotado_key VARCHAR(300),
      nombre_original VARCHAR(255) NOT NULL,
      mime VARCHAR(120) NOT NULL,
      bytes INTEGER NOT NULL CHECK (bytes >= 0),
      ancho_px INTEGER,
      alto_px INTEGER,
      geolat DOUBLE PRECISION,
      geolng DOUBLE PRECISION,
      exif_timestamp TIMESTAMPTZ,
      anotaciones_json JSONB NOT NULL DEFAULT '{{}}'::jsonb,
      orden INTEGER NOT NULL DEFAULT 0,
      etiqueta VARCHAR(80),
      hash_sha256 VARCHAR(64) NOT NULL,
      inmutable BOOLEAN NOT NULL DEFAULT false
    );
    CREATE INDEX ix_formulario_evidencias_respuesta ON formulario_evidencias (respuesta_id, campo_clave, orden);

    CREATE TABLE calidad_foto_defaults ({base},
      clave VARCHAR(20) NOT NULL DEFAULT 'global' UNIQUE,
      tamano_minimo_kb INTEGER NOT NULL DEFAULT 150 CHECK (tamano_minimo_kb >= 0),
      resolucion_minima_ancho INTEGER NOT NULL DEFAULT 800 CHECK (resolucion_minima_ancho >= 1),
      resolucion_minima_alto INTEGER NOT NULL DEFAULT 600 CHECK (resolucion_minima_alto >= 1),
      compresion_maxima_pct INTEGER NOT NULL DEFAULT 70 CHECK (compresion_maxima_pct BETWEEN 0 AND 100)
    );
    INSERT INTO calidad_foto_defaults (clave) VALUES ('global');
    """)

    versionar(*TABLAS)

    # Inmutabilidad (§4.3, §6.8.3c): una respuesta enviada no cambia; sus evidencias no se modifican ni se borran.
    ex("""
    CREATE FUNCTION acma_respuesta_inmutable() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF OLD.estado = 'enviado' THEN
        RAISE EXCEPTION 'La respuesta % ya fue enviada y es inmutable', OLD.id USING ERRCODE = 'insufficient_privilege';
      END IF;
      IF NEW.estado = 'enviado' THEN
        NEW.inmutable := true;
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER trg_formulario_respuestas_inmutable BEFORE UPDATE ON formulario_respuestas
      FOR EACH ROW EXECUTE FUNCTION acma_respuesta_inmutable();

    CREATE FUNCTION acma_respuesta_sellar_evidencias() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NEW.estado = 'enviado' AND OLD.estado <> 'enviado' THEN
        UPDATE formulario_evidencias SET inmutable = true WHERE respuesta_id = NEW.id AND NOT inmutable;
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER trg_formulario_respuestas_sellar AFTER UPDATE ON formulario_respuestas
      FOR EACH ROW EXECUTE FUNCTION acma_respuesta_sellar_evidencias();

    CREATE FUNCTION acma_evidencia_inmutable() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP = 'INSERT' THEN
        IF EXISTS (SELECT 1 FROM formulario_respuestas r WHERE r.id = NEW.respuesta_id AND r.estado = 'enviado') THEN
          RAISE EXCEPTION 'No se pueden agregar evidencias a una respuesta enviada' USING ERRCODE = 'insufficient_privilege';
        END IF;
        RETURN NEW;
      END IF;
      IF OLD.inmutable THEN
        RAISE EXCEPTION 'La evidencia % pertenece a una respuesta enviada y es inmutable', OLD.id USING ERRCODE = 'insufficient_privilege';
      END IF;
      RETURN COALESCE(NEW, OLD);
    END $$;
    CREATE TRIGGER trg_formulario_evidencias_inmutable BEFORE INSERT OR UPDATE OR DELETE ON formulario_evidencias
      FOR EACH ROW EXECUTE FUNCTION acma_evidencia_inmutable();
    """)

    # ------------------------------------------------------------- RLS
    for t in ("formularios", "formulario_versiones"):
        rls(t,
            f"CREATE POLICY {t}_lectura ON {t} FOR SELECT USING ({LECTURA_FORMULARIO});",
            f"CREATE POLICY {t}_escritura ON {t} FOR ALL USING ({ESCRITURA_PRESTADOR}) WITH CHECK ({ESCRITURA_PRESTADOR});")
    rls("formulario_asignaciones",
        f"CREATE POLICY formulario_asignaciones_lectura ON formulario_asignaciones FOR SELECT USING "
        f"(acma_prestador_visible(prestador_id) AND (tenant_id IS NULL OR acma_tenant_visible(tenant_id)));",
        f"CREATE POLICY formulario_asignaciones_escritura ON formulario_asignaciones FOR ALL USING ({ESCRITURA_PRESTADOR})"
        f" WITH CHECK ({ESCRITURA_PRESTADOR});")
    rls("formulario_permisos_mesa",
        "CREATE POLICY formulario_permisos_mesa_prestador ON formulario_permisos_mesa FOR ALL"
        " USING (acma_es_plataforma() OR prestador_id = acma_ctx_prestador())"
        " WITH CHECK (acma_es_plataforma() OR prestador_id = acma_ctx_prestador());")
    for t in ("catalogos_personalizados", "catalogo_personalizado_opciones"):
        rls(t,
            f"CREATE POLICY {t}_lectura ON {t} FOR SELECT USING "
            f"(acma_prestador_visible(prestador_id) AND (tenant_id IS NULL OR acma_tenant_visible(tenant_id)));",
            f"CREATE POLICY {t}_escritura ON {t} FOR ALL USING ({ESCRITURA_PRESTADOR}) WITH CHECK ({ESCRITURA_PRESTADOR});")
    for t in ("formulario_respuestas", "formulario_evidencias"):
        rls(t, f"CREATE POLICY {t}_duenio ON {t} FOR ALL USING ({DUENIO_RESPUESTA}) WITH CHECK ({DUENIO_RESPUESTA});")
    rls("calidad_foto_defaults",
        "CREATE POLICY calidad_foto_defaults_lectura ON calidad_foto_defaults FOR SELECT USING (acma_hay_contexto());",
        "CREATE POLICY calidad_foto_defaults_plataforma ON calidad_foto_defaults FOR ALL USING (acma_es_plataforma())"
        " WITH CHECK (acma_es_plataforma());")

    ex(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {', '.join(TABLAS)} TO acma_api;")

    ex("""
    INSERT INTO alertas_catalogo (clave, descripcion, umbral_default, umbral_min, umbral_max, tipo_umbral,
                                  modulo_origen, prompt_origen, destinatarios_default)
    VALUES ('GEOLOCALIZACION_FUERA_DE_UN',
            'Ubicación capturada en un formulario a más de X metros del perímetro configurado de la UN (geofencing §4.3).',
            0, 0, 5000, 'metros', 'formularios', 'P03', '["despachador","admin_prestador"]'::jsonb);
    """)


def downgrade() -> None:
    ex("SELECT set_config('app.rol', 'sistema', true);")
    for t in ("alertas_historial", "alertas_configuracion", "alertas_supresiones"):
        ex(f"DELETE FROM {t} WHERE clave_alerta = 'GEOLOCALIZACION_FUERA_DE_UN';")
    ex("DELETE FROM alertas_catalogo WHERE clave = 'GEOLOCALIZACION_FUERA_DE_UN';")
    ex("ALTER TABLE formularios DROP CONSTRAINT IF EXISTS fk_formularios_version_publicada;")
    for t in reversed(TABLAS):
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE;")
    ex("""
    DROP FUNCTION IF EXISTS acma_evidencia_inmutable() CASCADE;
    DROP FUNCTION IF EXISTS acma_respuesta_sellar_evidencias() CASCADE;
    DROP FUNCTION IF EXISTS acma_respuesta_inmutable() CASCADE;
    DROP TYPE IF EXISTS tipo_evidencia;
    DROP TYPE IF EXISTS estado_respuesta;
    DROP TYPE IF EXISTS origen_respuesta;
    DROP TYPE IF EXISTS estado_formulario;
    DROP TYPE IF EXISTS tipo_formulario;
    """)
