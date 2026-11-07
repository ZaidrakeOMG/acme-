"""0013 — Capacitación y certificación de técnicos (§6.10.3) y biblioteca de manuales con contenido de servicio
contractual (§6.10.4). Activa la alerta CERTIFICACION_VENCIDA y agrega la de habilidad retirada. F2-01.

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-06
"""
from core.sql_migracion import ex, lit, politicas_tenant, rls, versionar

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

TABLAS = [
    "cursos_catalogo", "tecnico_cursos", "capacitacion_alertas_config",
    "biblioteca_manuales", "biblioteca_versiones", "contenido_servicio", "tecnico_descargas_offline",
]

base = """
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      version_hash VARCHAR(64)"""

# El catálogo de cursos es como las plantillas base de formularios: lo global (prestador_id NULL) lo ve cualquiera
# con contexto y solo lo escribe la plataforma; lo propio, su prestador.
LECTURA_CURSO = "((prestador_id IS NULL AND acma_hay_contexto()) OR acma_prestador_visible(prestador_id))"
ESCRITURA_CURSO = "(acma_es_plataforma() OR (prestador_id IS NOT NULL AND prestador_id = acma_ctx_prestador()))"

# §6.10.3 «Vista del cliente»: el cliente ve las certificaciones VIGENTES de los técnicos que atienden sus unidades.
# La restricción vive en la política, no solo en el servicio: un técnico habilitado para su tenant, o que atendió un
# folio suyo en los últimos 90 días, y únicamente cursos aprobados y sin vencer.
LECTURA_CLIENTE_CURSOS = """(
      aprobado AND (vigente_hasta IS NULL OR vigente_hasta >= CURRENT_DATE) AND acma_ctx_tenant() IS NOT NULL
      AND (EXISTS (SELECT 1 FROM tecnico_tenants_habilitados h
                    WHERE h.tecnico_id = tecnico_cursos.tecnico_id AND h.tenant_id = acma_ctx_tenant())
           OR EXISTS (SELECT 1 FROM folios f JOIN tecnicos tc ON tc.usuario_id = f.tecnico_id
                       WHERE tc.id = tecnico_cursos.tecnico_id AND f.tenant_id = acma_ctx_tenant()
                         AND f.capturado_at >= now() - INTERVAL '90 days'))
    )"""

ALERTAS_NUEVAS = [
    # clave, descripcion, umbral, tipo, min, max, modulo, destinatarios
    ("CERTIFICACION_VENCIDA_HABILIDAD_RETIRADA",
     "El sistema retiró una habilidad certificada porque venció la certificación que la respaldaba.",
     0, "dias", 0, 30, "capacitacion", ["admin_prestador", "despachador"]),
]


def upgrade() -> None:
    ex("SELECT set_config('app.rol', 'sistema', true);")

    # ------------------------------------------------------------------ capacitación (§6.10.3)
    ex("""
    CREATE TYPE tipo_curso AS ENUM ('curso','certificacion');
    CREATE TYPE estado_curso_tecnico AS ENUM ('vigente','por_vencer','vencido','sin_vigencia');
    """)

    ex(f"""
    CREATE TABLE cursos_catalogo ({base},
      prestador_id UUID REFERENCES prestadores(id),
      nombre VARCHAR(200) NOT NULL,
      proveedor VARCHAR(200),
      duracion_horas NUMERIC(6,2),
      vigencia_meses SMALLINT,
      habilidad_id UUID REFERENCES habilidades(id),
      tipo tipo_curso NOT NULL DEFAULT 'curso',
      norma_referencia VARCHAR(160),
      descripcion TEXT NOT NULL DEFAULT '',
      activo BOOLEAN NOT NULL DEFAULT true,
      CONSTRAINT ck_cursos_catalogo_vigencia CHECK (vigencia_meses IS NULL OR vigencia_meses BETWEEN 1 AND 600),
      CONSTRAINT ck_cursos_catalogo_duracion CHECK (duracion_horas IS NULL OR duracion_horas > 0),
      -- Una habilidad solo se puede respaldar con cursos del mismo prestador que la definió.
      CONSTRAINT ck_cursos_catalogo_habilidad_propia CHECK (habilidad_id IS NULL OR prestador_id IS NOT NULL)
    );
    CREATE UNIQUE INDEX uq_cursos_catalogo_nombre ON cursos_catalogo (COALESCE(prestador_id, '00000000-0000-0000-0000-000000000000'::uuid), lower(nombre));
    CREATE INDEX ix_cursos_catalogo_habilidad ON cursos_catalogo (habilidad_id);
    """)
    rls("cursos_catalogo",
        f"CREATE POLICY cursos_catalogo_lectura ON cursos_catalogo FOR SELECT USING ({LECTURA_CURSO});",
        f"CREATE POLICY cursos_catalogo_escritura ON cursos_catalogo FOR ALL USING ({ESCRITURA_CURSO})"
        f" WITH CHECK ({ESCRITURA_CURSO});")

    ex(f"""
    CREATE TABLE tecnico_cursos ({base},
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      tecnico_id UUID NOT NULL REFERENCES tecnicos(id),
      curso_id UUID NOT NULL REFERENCES cursos_catalogo(id),
      fecha_inicio DATE,
      fecha_fin DATE NOT NULL,
      calificacion NUMERIC(5,2),
      aprobado BOOLEAN NOT NULL DEFAULT true,
      certificado_key VARCHAR(300),
      certificado_nombre VARCHAR(255),
      certificado_mime VARCHAR(120),
      folio_constancia VARCHAR(80),
      vigente_hasta DATE,
      vigencia_editada BOOLEAN NOT NULL DEFAULT false,
      razon_vigencia TEXT NOT NULL DEFAULT '',
      estado estado_curso_tecnico NOT NULL DEFAULT 'sin_vigencia',
      habilidad_otorgada_id UUID REFERENCES habilidades(id),
      registrado_por UUID REFERENCES usuarios(id),
      notas TEXT NOT NULL DEFAULT '',
      CONSTRAINT ck_tecnico_cursos_fechas CHECK (fecha_inicio IS NULL OR fecha_inicio <= fecha_fin),
      CONSTRAINT ck_tecnico_cursos_vigencia CHECK (vigente_hasta IS NULL OR vigente_hasta >= fecha_fin),
      CONSTRAINT ck_tecnico_cursos_calificacion CHECK (calificacion IS NULL OR calificacion BETWEEN 0 AND 100),
      -- Editar la vigencia calculada exige razón (§6.10.3: el dato sale de fecha_fin + vigencia_meses).
      CONSTRAINT ck_tecnico_cursos_razon CHECK (NOT vigencia_editada OR length(btrim(razon_vigencia)) > 0)
    );
    CREATE INDEX ix_tecnico_cursos_tecnico ON tecnico_cursos (tecnico_id, fecha_fin DESC);
    CREATE INDEX ix_tecnico_cursos_vigencia ON tecnico_cursos (vigente_hasta) WHERE aprobado;
    CREATE INDEX ix_tecnico_cursos_curso ON tecnico_cursos (curso_id);
    """)
    rls("tecnico_cursos",
        "CREATE POLICY tecnico_cursos_lectura ON tecnico_cursos FOR SELECT USING "
        "(acma_es_plataforma() OR prestador_id = acma_ctx_prestador());",
        f"CREATE POLICY tecnico_cursos_lectura_cliente ON tecnico_cursos FOR SELECT USING ({LECTURA_CLIENTE_CURSOS});",
        "CREATE POLICY tecnico_cursos_escritura ON tecnico_cursos FOR ALL USING "
        "(acma_es_plataforma() OR prestador_id = acma_ctx_prestador()) WITH CHECK "
        "(acma_es_plataforma() OR prestador_id = acma_ctx_prestador());")

    ex(f"""
    CREATE TABLE capacitacion_alertas_config ({base},
      prestador_id UUID NOT NULL UNIQUE REFERENCES prestadores(id),
      dias_anticipacion SMALLINT NOT NULL DEFAULT 30,
      notificar_cliente BOOLEAN NOT NULL DEFAULT false,
      activa BOOLEAN NOT NULL DEFAULT true,
      CONSTRAINT ck_capacitacion_alertas_dias CHECK (dias_anticipacion BETWEEN 1 AND 180)
    );
    """)
    rls("capacitacion_alertas_config",
        "CREATE POLICY capacitacion_alertas_config_lectura ON capacitacion_alertas_config FOR SELECT USING "
        "(acma_prestador_visible(prestador_id));",
        "CREATE POLICY capacitacion_alertas_config_escritura ON capacitacion_alertas_config FOR ALL USING "
        "(acma_es_plataforma() OR prestador_id = acma_ctx_prestador()) WITH CHECK "
        "(acma_es_plataforma() OR prestador_id = acma_ctx_prestador());")

    # ------------------------------------------------------------------ biblioteca (§6.10.4)
    ex("""
    CREATE TYPE categoria_manual AS ENUM ('ficha_tecnica','procedimiento','diagrama','refacciones','otro');
    """)

    ex(f"""
    CREATE TABLE biblioteca_manuales ({base},
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      tipo_equipo_id UUID NOT NULL REFERENCES tipos_equipo(id),
      titulo VARCHAR(200) NOT NULL,
      categoria categoria_manual NOT NULL DEFAULT 'otro',
      descripcion TEXT NOT NULL DEFAULT '',
      version INTEGER NOT NULL DEFAULT 1,
      fecha_subida TIMESTAMPTZ NOT NULL DEFAULT now(),
      archivo_key VARCHAR(300) NOT NULL,
      nombre_original VARCHAR(255) NOT NULL,
      mime VARCHAR(120) NOT NULL,
      bytes INTEGER NOT NULL,
      hash_sha256 VARCHAR(64) NOT NULL,
      activo BOOLEAN NOT NULL DEFAULT true,
      subido_por UUID REFERENCES usuarios(id),
      CONSTRAINT ck_biblioteca_manuales_version CHECK (version >= 1),
      CONSTRAINT ck_biblioteca_manuales_bytes CHECK (bytes > 0)
    );
    CREATE INDEX ix_biblioteca_manuales_tipo ON biblioteca_manuales (tipo_equipo_id, activo);
    CREATE INDEX ix_biblioteca_manuales_prestador ON biblioteca_manuales (prestador_id, activo);
    """)
    # Los manuales son documentación técnica del prestador: la lee su propia gente (técnicos incluidos), no el cliente.
    rls("biblioteca_manuales",
        "CREATE POLICY biblioteca_manuales_lectura ON biblioteca_manuales FOR SELECT USING "
        "(acma_es_plataforma() OR prestador_id = acma_ctx_prestador());",
        "CREATE POLICY biblioteca_manuales_escritura ON biblioteca_manuales FOR ALL USING "
        "(acma_es_plataforma() OR prestador_id = acma_ctx_prestador()) WITH CHECK "
        "(acma_es_plataforma() OR prestador_id = acma_ctx_prestador());")

    # §6.10.4: «cada nueva versión reemplaza la anterior pero conserva el historial». Append-only: el historial de
    # versiones no se corrige ni se borra, igual que la auditoría.
    ex(f"""
    CREATE TABLE biblioteca_versiones ({base},
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      manual_id UUID NOT NULL REFERENCES biblioteca_manuales(id) ON DELETE CASCADE,
      version_anterior INTEGER NOT NULL,
      archivo_key_anterior VARCHAR(300) NOT NULL,
      nombre_original_anterior VARCHAR(255),
      bytes_anterior INTEGER,
      hash_sha256_anterior VARCHAR(64),
      reemplazado_en TIMESTAMPTZ NOT NULL DEFAULT now(),
      reemplazado_por UUID REFERENCES usuarios(id),
      notas_version TEXT NOT NULL DEFAULT '',
      CONSTRAINT uq_biblioteca_versiones UNIQUE (manual_id, version_anterior)
    );
    CREATE INDEX ix_biblioteca_versiones_manual ON biblioteca_versiones (manual_id, version_anterior DESC);
    """)
    rls("biblioteca_versiones",
        "CREATE POLICY biblioteca_versiones_lectura ON biblioteca_versiones FOR SELECT USING "
        "(acma_es_plataforma() OR prestador_id = acma_ctx_prestador());",
        "CREATE POLICY biblioteca_versiones_insercion ON biblioteca_versiones FOR INSERT WITH CHECK "
        "(acma_es_plataforma() OR prestador_id = acma_ctx_prestador());")
    ex("""
    CREATE TRIGGER trg_biblioteca_versiones_inmutable
      BEFORE UPDATE OR DELETE OR TRUNCATE ON biblioteca_versiones
      FOR EACH STATEMENT EXECUTE FUNCTION acma_auditoria_inmutable();
    """)

    # §6.10.4: el contenido de servicio es confidencial del tenant. `acma_tenant_visible` lo deja ver al propio
    # tenant y a los prestadores que lo atienden, y a ningún otro tenant del mismo prestador.
    ex(f"""
    CREATE TABLE contenido_servicio ({base},
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      tipo_equipo_id UUID NOT NULL REFERENCES tipos_equipo(id),
      contrato_id UUID NOT NULL REFERENCES contratos(id),
      titulo VARCHAR(200) NOT NULL,
      puntos_revision_json JSONB NOT NULL DEFAULT '[]'::jsonb,
      periodicidad VARCHAR(80),
      correctivos_iguala INTEGER,
      preventivos_iguala_json JSONB NOT NULL DEFAULT '{{}}'::jsonb,
      archivo_key VARCHAR(300),
      nombre_original VARCHAR(255),
      mime VARCHAR(120),
      bytes INTEGER,
      version INTEGER NOT NULL DEFAULT 1,
      activo BOOLEAN NOT NULL DEFAULT true,
      subido_por UUID REFERENCES usuarios(id),
      CONSTRAINT ck_contenido_servicio_version CHECK (version >= 1),
      CONSTRAINT ck_contenido_servicio_puntos CHECK (jsonb_typeof(puntos_revision_json) = 'array'),
      CONSTRAINT ck_contenido_servicio_correctivos CHECK (correctivos_iguala IS NULL OR correctivos_iguala >= 0)
    );
    CREATE UNIQUE INDEX uq_contenido_servicio_vigente ON contenido_servicio (tenant_id, contrato_id, tipo_equipo_id)
      WHERE activo;
    CREATE INDEX ix_contenido_servicio_tipo ON contenido_servicio (tipo_equipo_id, activo);
    """)
    rls("contenido_servicio", *politicas_tenant("contenido_servicio"))

    ex(f"""
    CREATE TABLE tecnico_descargas_offline ({base},
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      tecnico_id UUID NOT NULL REFERENCES tecnicos(id),
      manual_id UUID REFERENCES biblioteca_manuales(id) ON DELETE CASCADE,
      contenido_id UUID REFERENCES contenido_servicio(id) ON DELETE CASCADE,
      fecha_descarga TIMESTAMPTZ NOT NULL DEFAULT now(),
      version_descargada INTEGER NOT NULL,
      en_dispositivo BOOLEAN NOT NULL DEFAULT true,
      dispositivo_id VARCHAR(120),
      CONSTRAINT ck_tecnico_descargas_uno CHECK ((manual_id IS NOT NULL) <> (contenido_id IS NOT NULL))
    );
    CREATE INDEX ix_tecnico_descargas_tecnico ON tecnico_descargas_offline (tecnico_id, fecha_descarga DESC);
    CREATE UNIQUE INDEX uq_tecnico_descargas_manual ON tecnico_descargas_offline (tecnico_id, manual_id, dispositivo_id)
      WHERE manual_id IS NOT NULL;
    CREATE UNIQUE INDEX uq_tecnico_descargas_contenido ON tecnico_descargas_offline (tecnico_id, contenido_id, dispositivo_id)
      WHERE contenido_id IS NOT NULL;
    """)
    rls("tecnico_descargas_offline",
        "CREATE POLICY tecnico_descargas_offline_lectura ON tecnico_descargas_offline FOR SELECT USING "
        "(acma_es_plataforma() OR prestador_id = acma_ctx_prestador());",
        "CREATE POLICY tecnico_descargas_offline_escritura ON tecnico_descargas_offline FOR ALL USING "
        "(acma_es_plataforma() OR prestador_id = acma_ctx_prestador()) WITH CHECK "
        "(acma_es_plataforma() OR prestador_id = acma_ctx_prestador());")

    # §6.10.3 «Vista del cliente»: para ver las certificaciones de los tecnicos que atienden sus unidades, el cliente
    # necesita leer la ficha del tecnico y su vinculo. P02 las dejo solo para el prestador, y una politica que consulta
    # esas tablas (como `tecnico_cursos_lectura_cliente`) tambien queda a ciegas, porque la RLS se aplica dentro de la
    # subconsulta. Se abre lo minimo: la ficha de los tecnicos habilitados para ese cliente o que atendieron un folio
    # suyo en los ultimos 90 dias. El nombre ya era visible (`usuarios_lectura` lo permite desde P01) y los endpoints
    # del catalogo de tecnicos siguen cerrados a los roles del cliente.
    ex("""
    CREATE POLICY tecnico_tenants_habilitados_lectura_cliente ON tecnico_tenants_habilitados FOR SELECT
      USING (acma_ctx_tenant() IS NOT NULL AND tenant_id = acma_ctx_tenant());
    CREATE POLICY tecnicos_lectura_cliente ON tecnicos FOR SELECT USING (
      acma_ctx_tenant() IS NOT NULL AND (
        EXISTS (SELECT 1 FROM tecnico_tenants_habilitados h
                 WHERE h.tecnico_id = tecnicos.id AND h.tenant_id = acma_ctx_tenant())
        OR EXISTS (SELECT 1 FROM folios f
                    WHERE f.tecnico_id = tecnicos.usuario_id AND f.tenant_id = acma_ctx_tenant()
                      AND f.capturado_at >= now() - INTERVAL '90 days')));
    """)

    versionar(*TABLAS)
    for t in TABLAS:
        ex(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {t} TO acma_api;")

    # ------------------------------------------------------------------ alertas
    # CERTIFICACION_VENCIDA dejaba de ser Fase 2: su fuente de datos ya existe (tecnico_cursos).
    ex("UPDATE alertas_catalogo SET fase = 1, activa_por_defecto = true, prompt_origen = 'F2-01' "
       "WHERE clave = 'CERTIFICACION_VENCIDA';")
    ex("UPDATE alertas_configuracion SET activa = true WHERE clave_alerta = 'CERTIFICACION_VENCIDA';")
    for clave, desc, umbral, tipo, mn, mx, modulo, dest in ALERTAS_NUEVAS:
        ex(f"""
        INSERT INTO alertas_catalogo (clave, descripcion, umbral_default, umbral_min, umbral_max, tipo_umbral,
                                      modulo_origen, prompt_origen, destinatarios_default, fase)
        VALUES ({lit(clave)}, {lit(desc)}, {umbral}, {mn}, {mx}, {lit(tipo)}, {lit(modulo)}, 'F2-01',
                {lit(__import__("json").dumps(dest))}::jsonb, 1)
        ON CONFLICT (clave) DO NOTHING;
        """)


def downgrade() -> None:
    ex("SELECT set_config('app.rol', 'sistema', true);")
    for clave, *_ in ALERTAS_NUEVAS:
        ex(f"DELETE FROM alertas_historial WHERE clave_alerta = {lit(clave)};")
        ex(f"DELETE FROM alertas_configuracion WHERE clave_alerta = {lit(clave)};")
        ex(f"DELETE FROM alertas_catalogo WHERE clave = {lit(clave)};")
    ex("UPDATE alertas_catalogo SET fase = 2, activa_por_defecto = false, prompt_origen = 'P10' "
       "WHERE clave = 'CERTIFICACION_VENCIDA';")
    ex("UPDATE alertas_configuracion SET activa = false WHERE clave_alerta = 'CERTIFICACION_VENCIDA';")
    ex("DROP POLICY IF EXISTS tecnicos_lectura_cliente ON tecnicos;")
    ex("DROP POLICY IF EXISTS tecnico_tenants_habilitados_lectura_cliente ON tecnico_tenants_habilitados;")
    ex("DROP TRIGGER IF EXISTS trg_biblioteca_versiones_inmutable ON biblioteca_versiones;")
    for t in reversed(TABLAS):
        ex(f"DROP TABLE IF EXISTS {t} CASCADE;")
    ex("DROP TYPE IF EXISTS categoria_manual; DROP TYPE IF EXISTS estado_curso_tecnico; DROP TYPE IF EXISTS tipo_curso;")
