"""0002 — Catálogos maestros: técnicos y habilidades, severidades, familias/tipos de equipo, equipos,
tipos de falla, matriz de severidad e importaciones (§4.1, §6.3, §6.8.3, §6.8.6, §6.10.8).

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-23
"""
from alembic import op

from core.sql_migracion import ex, lit, politicas_prestador, politicas_tenant, rls, versionar

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

# clave, nombre, orden, color, respuesta h, resolución h (§6.10.1: 5 niveles)
NIVELES = [
    ("muy_baja", "Muy baja", 1, "#1976D2", 72, 720),
    ("baja", "Baja", 2, "#388E3C", 24, 168),
    ("media", "Media", 3, "#FBC02D", 8, 72),
    ("alta", "Alta", 4, "#F57C00", 4, 24),
    ("critica", "Crítica", 5, "#D32F2F", 2, 8),
]

TABLAS = [
    "habilidades", "tecnicos", "tecnico_habilidades", "tecnico_tenants_habilitados", "niveles_severidad",
    "familias_equipo", "tipos_equipo", "equipos", "tipos_falla", "tipo_falla_severidad", "importaciones_catalogo",
]

base = """
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      version_hash VARCHAR(64)"""

CERO = "'00000000-0000-0000-0000-000000000000'::uuid"


def upgrade() -> None:
    # Las filas que inserta esta migración (backfill) necesitan contexto: la RLS forzada aplica también al dueño.
    ex("SELECT set_config('app.rol', 'sistema', true);")

    ex("""
    CREATE TYPE estado_activo AS ENUM ('activo','inactivo','baja');
    CREATE TYPE origen_habilidad AS ENUM ('manual','curso');
    CREATE TYPE cobertura_contrato AS ENUM ('todas_las_un','equipos_especificos');
    CREATE TYPE estado_importacion AS ENUM ('vista_previa','confirmada','cancelada');
    """)

    ex(f"""
    ALTER TABLE contratos ADD COLUMN cobertura cobertura_contrato NOT NULL DEFAULT 'todas_las_un';

    CREATE TABLE habilidades ({base},
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      clave VARCHAR(60) NOT NULL,
      nombre VARCHAR(120) NOT NULL,
      descripcion TEXT NOT NULL DEFAULT '',
      activa BOOLEAN NOT NULL DEFAULT true,
      CONSTRAINT uq_habilidades UNIQUE (prestador_id, clave)
    );

    CREATE TABLE tecnicos ({base},
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      usuario_id UUID NOT NULL UNIQUE REFERENCES usuarios(id),
      numero_empleado VARCHAR(40),
      telefono VARCHAR(30),
      vehiculo_placas VARCHAR(20),
      estado estado_activo NOT NULL DEFAULT 'activo',
      fecha_ingreso DATE
    );
    CREATE UNIQUE INDEX uq_tecnicos_numero_empleado ON tecnicos (prestador_id, numero_empleado) WHERE numero_empleado IS NOT NULL;

    CREATE TABLE tecnico_habilidades ({base},
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      tecnico_id UUID NOT NULL REFERENCES tecnicos(id) ON DELETE CASCADE,
      habilidad_id UUID NOT NULL REFERENCES habilidades(id),
      certificada BOOLEAN NOT NULL DEFAULT false,
      fecha_certificacion DATE,
      vigencia_hasta DATE,
      origen origen_habilidad NOT NULL DEFAULT 'manual',
      CONSTRAINT uq_tecnico_habilidades UNIQUE (tecnico_id, habilidad_id),
      CONSTRAINT ck_tecnico_habilidades_vigencia CHECK (vigencia_hasta IS NULL OR fecha_certificacion IS NULL
                                                        OR vigencia_hasta >= fecha_certificacion)
    );

    -- §6.10.8: tenants adicionales que puede atender un técnico.
    CREATE TABLE tecnico_tenants_habilitados ({base},
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      tecnico_id UUID NOT NULL REFERENCES tecnicos(id) ON DELETE CASCADE,
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      habilitado_por UUID REFERENCES usuarios(id),
      fecha_habilitacion DATE NOT NULL DEFAULT current_date,
      activo BOOLEAN NOT NULL DEFAULT true,
      CONSTRAINT uq_tecnico_tenants UNIQUE (tecnico_id, tenant_id)
    );

    CREATE TABLE niveles_severidad ({base},
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      clave VARCHAR(40) NOT NULL,
      nombre VARCHAR(60) NOT NULL,
      orden SMALLINT NOT NULL CHECK (orden BETWEEN 1 AND 5),
      color_hex VARCHAR(7) NOT NULL CHECK (color_hex ~ '^#[0-9A-Fa-f]{{6}}$'),
      tiempo_respuesta_horas INTEGER NOT NULL CHECK (tiempo_respuesta_horas BETWEEN 1 AND 4320),
      tiempo_resolucion_horas INTEGER NOT NULL CHECK (tiempo_resolucion_horas BETWEEN 1 AND 4320),
      activo BOOLEAN NOT NULL DEFAULT true,
      CONSTRAINT uq_niveles_clave UNIQUE (prestador_id, clave),
      CONSTRAINT uq_niveles_orden UNIQUE (prestador_id, orden)
    );

    ALTER TABLE contrato_sla ADD COLUMN nivel_severidad_id UUID REFERENCES niveles_severidad(id);

    -- tenant_id NULL = catálogo global de plataforma (solo superadmin lo edita).
    CREATE TABLE familias_equipo ({base},
      tenant_id UUID REFERENCES tenants(id),
      nombre VARCHAR(120) NOT NULL,
      descripcion TEXT NOT NULL DEFAULT '',
      activa BOOLEAN NOT NULL DEFAULT true
    );
    CREATE UNIQUE INDEX uq_familias_equipo ON familias_equipo (COALESCE(tenant_id, {CERO}), lower(nombre));

    CREATE TABLE tipos_equipo ({base},
      familia_id UUID NOT NULL REFERENCES familias_equipo(id),
      tenant_id UUID REFERENCES tenants(id),
      nombre VARCHAR(120) NOT NULL,
      descripcion TEXT NOT NULL DEFAULT '',
      activa BOOLEAN NOT NULL DEFAULT true
    );
    CREATE UNIQUE INDEX uq_tipos_equipo ON tipos_equipo (familia_id, COALESCE(tenant_id, {CERO}), lower(nombre));
    CREATE INDEX ix_tipos_equipo_familia ON tipos_equipo (familia_id);

    CREATE TABLE equipos ({base},
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      un_id UUID NOT NULL REFERENCES unidades_negocio(id),
      tipo_equipo_id UUID NOT NULL REFERENCES tipos_equipo(id),
      codigo VARCHAR(60) NOT NULL,
      nombre VARCHAR(160) NOT NULL,
      marca VARCHAR(80),
      modelo VARCHAR(80),
      numero_serie VARCHAR(80),
      fecha_instalacion DATE,
      valor_reposicion NUMERIC(14,2) CHECK (valor_reposicion IS NULL OR valor_reposicion >= 0),
      estado estado_activo NOT NULL DEFAULT 'activo',
      garantia_vigente_hasta DATE,
      contrato_id UUID REFERENCES contratos(id),
      notas TEXT NOT NULL DEFAULT '',
      CONSTRAINT uq_equipos_codigo UNIQUE (tenant_id, codigo)
    );
    CREATE INDEX ix_equipos_un ON equipos (un_id);
    CREATE INDEX ix_equipos_tipo ON equipos (tipo_equipo_id);
    CREATE INDEX ix_equipos_busqueda ON equipos (tenant_id, lower(nombre));

    CREATE TABLE tipos_falla ({base},
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      descripcion VARCHAR(200) NOT NULL,
      familia_equipo_id UUID NOT NULL REFERENCES familias_equipo(id),
      requiere_revision_manual BOOLEAN NOT NULL DEFAULT false,
      activa BOOLEAN NOT NULL DEFAULT true
    );
    CREATE UNIQUE INDEX uq_tipos_falla ON tipos_falla (prestador_id, familia_equipo_id, lower(descripcion));

    CREATE TABLE tipo_falla_severidad ({base},
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      tipo_falla_id UUID NOT NULL REFERENCES tipos_falla(id),
      tipo_equipo_id UUID NOT NULL REFERENCES tipos_equipo(id),
      nivel_severidad_id UUID NOT NULL REFERENCES niveles_severidad(id),
      configurado_por UUID REFERENCES usuarios(id),
      activa BOOLEAN NOT NULL DEFAULT true,
      CONSTRAINT uq_tipo_falla_severidad UNIQUE (tenant_id, tipo_falla_id, tipo_equipo_id)
    );

    CREATE TABLE importaciones_catalogo ({base},
      tenant_id UUID REFERENCES tenants(id),
      prestador_id UUID REFERENCES prestadores(id),
      catalogo VARCHAR(40) NOT NULL,
      archivo_nombre VARCHAR(255) NOT NULL,
      archivo_key VARCHAR(300) NOT NULL,
      total_filas INTEGER NOT NULL DEFAULT 0,
      filas_ok INTEGER NOT NULL DEFAULT 0,
      filas_error INTEGER NOT NULL DEFAULT 0,
      errores_json JSONB NOT NULL DEFAULT '[]'::jsonb,
      duplicados_json JSONB NOT NULL DEFAULT '[]'::jsonb,
      filas_validas_json JSONB NOT NULL DEFAULT '[]'::jsonb,
      estado estado_importacion NOT NULL DEFAULT 'vista_previa',
      ejecutada_por UUID REFERENCES usuarios(id),
      confirmada_at TIMESTAMPTZ,
      CONSTRAINT ck_importaciones_duenio CHECK ((tenant_id IS NULL) <> (prestador_id IS NULL))
    );
    """)

    versionar(*TABLAS)

    # requiere_revision_manual es un flag global que solo cambia el superadmin (§6.8.6). Defensa en BD además del servicio.
    ex("""
    CREATE FUNCTION acma_tipos_falla_flag() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NOT acma_es_plataforma() THEN
        IF TG_OP = 'INSERT' AND NEW.requiere_revision_manual THEN
          RAISE EXCEPTION 'Solo el superadmin activa requiere_revision_manual' USING ERRCODE = 'insufficient_privilege';
        ELSIF TG_OP = 'UPDATE' AND NEW.requiere_revision_manual IS DISTINCT FROM OLD.requiere_revision_manual THEN
          RAISE EXCEPTION 'Solo el superadmin cambia requiere_revision_manual' USING ERRCODE = 'insufficient_privilege';
        END IF;
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER trg_tipos_falla_flag BEFORE INSERT OR UPDATE ON tipos_falla
      FOR EACH ROW EXECUTE FUNCTION acma_tipos_falla_flag();

    -- Un equipo tiene contrato activo si su contrato_id apunta a un contrato vigente de su tenant, o si no tiene
    -- contrato_id y existe un contrato vigente del tenant con cobertura de todas las UN. Respeta la RLS del llamador.
    CREATE FUNCTION acma_equipo_con_contrato_activo(p_equipo UUID) RETURNS BOOLEAN LANGUAGE sql STABLE AS $$
      SELECT EXISTS (
        SELECT 1 FROM equipos e
          JOIN contratos c ON c.tenant_id = e.tenant_id
         WHERE e.id = p_equipo
           AND c.estado = 'activo'
           AND current_date BETWEEN c.fecha_inicio AND c.fecha_fin
           AND ((e.contrato_id IS NOT NULL AND c.id = e.contrato_id)
                OR (e.contrato_id IS NULL AND c.cobertura = 'todas_las_un'))
      )
    $$;
    GRANT EXECUTE ON FUNCTION acma_equipo_con_contrato_activo(UUID) TO acma_api;
    """)

    # ------------------------------------------------------------- RLS
    for t in ("habilidades", "tecnicos", "tecnico_habilidades", "tecnico_tenants_habilitados"):
        rls(t, *politicas_prestador(t))
    # Severidades y tipos de falla: los leen los tenants atendidos (matriz de severidad, captura de folios).
    for t in ("niveles_severidad", "tipos_falla"):
        rls(t, *politicas_prestador(t, lectura_tenants=True))
    for t in ("equipos", "tipo_falla_severidad"):
        rls(t, *politicas_tenant(t))
    # Familias y tipos de equipo: globales (tenant_id NULL) visibles con cualquier contexto; los del tenant, por tenant.
    for t in ("familias_equipo", "tipos_equipo"):
        rls(
            t,
            f"CREATE POLICY {t}_lectura ON {t} FOR SELECT USING (acma_hay_contexto()"
            f" AND (tenant_id IS NULL OR acma_tenant_visible(tenant_id)));",
            f"CREATE POLICY {t}_escritura ON {t} FOR ALL"
            f" USING (acma_es_plataforma() OR (tenant_id IS NOT NULL AND tenant_id = acma_ctx_tenant()))"
            f" WITH CHECK (acma_es_plataforma() OR (tenant_id IS NOT NULL AND tenant_id = acma_ctx_tenant()));",
        )
    rls(
        "importaciones_catalogo",
        "CREATE POLICY importaciones_catalogo_duenio ON importaciones_catalogo FOR ALL USING (acma_es_plataforma()"
        " OR tenant_id = acma_ctx_tenant() OR prestador_id = acma_ctx_prestador())"
        " WITH CHECK (acma_es_plataforma() OR tenant_id = acma_ctx_tenant() OR prestador_id = acma_ctx_prestador());",
    )

    ex("""
    GRANT SELECT, INSERT, UPDATE, DELETE ON habilidades, tecnicos, tecnico_habilidades, tecnico_tenants_habilitados,
      niveles_severidad, familias_equipo, tipos_equipo, equipos, tipos_falla, tipo_falla_severidad, importaciones_catalogo
      TO acma_api;
    """)

    # ------------------------------------------- datos y backfill
    valores = ", ".join(f"({lit(c)}, {lit(n)}, {o}, {lit(col)}, {r}, {s})" for c, n, o, col, r, s in NIVELES)
    ex(f"""
    INSERT INTO niveles_severidad (prestador_id, clave, nombre, orden, color_hex, tiempo_respuesta_horas, tiempo_resolucion_horas)
    SELECT p.id, v.clave, v.nombre, v.orden, v.color, v.resp, v.resol
      FROM prestadores p CROSS JOIN (VALUES {valores}) AS v(clave, nombre, orden, color, resp, resol);

    UPDATE contrato_sla cs SET nivel_severidad_id = ns.id
      FROM niveles_severidad ns
     WHERE ns.prestador_id = cs.prestador_id AND ns.clave = cs.nivel_severidad::text;

    INSERT INTO alertas_catalogo (clave, descripcion, umbral_default, umbral_min, umbral_max, tipo_umbral,
                                  modulo_origen, prompt_origen, destinatarios_default)
    VALUES ('MATRIZ_SEVERIDAD_INCOMPLETA',
            'Combinaciones tipo de falla × tipo de equipo en uso por el tenant sin severidad configurada (dispara si hay más de X).',
            0, 0, 1000, 'cantidad', 'catalogos', 'P02', '["admin_empresa"]'::jsonb);
    """)


def downgrade() -> None:
    ex("SELECT set_config('app.rol', 'sistema', true);")
    ex("DELETE FROM alertas_historial WHERE clave_alerta = 'MATRIZ_SEVERIDAD_INCOMPLETA';")
    ex("DELETE FROM alertas_configuracion WHERE clave_alerta = 'MATRIZ_SEVERIDAD_INCOMPLETA';")
    ex("DELETE FROM alertas_catalogo WHERE clave = 'MATRIZ_SEVERIDAD_INCOMPLETA';")
    ex("ALTER TABLE contrato_sla DROP COLUMN IF EXISTS nivel_severidad_id;")
    for t in reversed(TABLAS):
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE;")
    ex("""
    DROP FUNCTION IF EXISTS acma_equipo_con_contrato_activo(UUID);
    DROP FUNCTION IF EXISTS acma_tipos_falla_flag() CASCADE;
    ALTER TABLE contratos DROP COLUMN IF EXISTS cobertura;
    DROP TYPE IF EXISTS estado_importacion;
    DROP TYPE IF EXISTS cobertura_contrato;
    DROP TYPE IF EXISTS origen_habilidad;
    DROP TYPE IF EXISTS estado_activo;
    """)
