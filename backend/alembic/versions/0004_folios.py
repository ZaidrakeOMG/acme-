"""0004 — Folios (§4.1, §6.8.6, §6.8.7): ciclo de vida con 11 estados, validaciones automáticas en captura,
flujo de aprobación multinivel con decisiones inmutables y timeouts.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-27
"""
from alembic import op

from core.sql_migracion import ex, rls, versionar

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

# Orden de creación (las FKs apuntan hacia atrás).
TABLAS = [
    "folio_politicas_tenant", "folio_keywords_alerta", "aprobacion_reglas", "aprobacion_niveles_config",
    "folios", "folio_estados_historial", "folio_formulario_captura", "folio_formulario_atencion", "folio_evidencias",
    "folio_refacciones", "folio_sla", "folio_encuesta", "revision_manual_triggers",
    "aprobacion_flujos", "aprobacion_decisiones", "aprobacion_alertas_timeout",
]
APPEND_ONLY = ["folio_estados_historial", "aprobacion_decisiones"]
ALERTAS = [
    ("APROBACION_PENDIENTE_VENCIDA", "Aprobación de folio sin respuesta al vencer el tiempo límite del nivel (más de X horas de retraso).",
     0, 0, 720, "horas", '["admin_empresa","admin_un","despachador"]'),
    ("APROBACION_BLOQUEADA", "Flujo de aprobación bloqueado por timeout: requiere decisión humana (más de X folios bloqueados).",
     0, 0, 1000, "cantidad", '["admin_empresa","admin_un","despachador"]'),
    ("FOLIO_EN_REVISION_SIN_ATENDER", "Folio en revisión (excepción de captura) sin atender por el despachador por más de X horas.",
     4, 1, 720, "horas", '["despachador","admin_prestador"]'),
]

base = """
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      version_hash VARCHAR(64)"""

# Filas con tenant y prestador: las lee el tenant dueño y el prestador que atiende el folio; escriben ambos.
LECTURA_FOLIO = "(acma_tenant_visible(tenant_id) AND acma_prestador_visible(prestador_id))"
ESCRITURA_FOLIO = "(acma_es_plataforma() OR tenant_id = acma_ctx_tenant() OR prestador_id = acma_ctx_prestador())"


def _politicas_folio(t: str, lectura: str = LECTURA_FOLIO) -> tuple[str, str]:
    return (
        f"CREATE POLICY {t}_lectura ON {t} FOR SELECT USING ({lectura});",
        f"CREATE POLICY {t}_escritura ON {t} FOR ALL USING ({ESCRITURA_FOLIO}) WITH CHECK ({ESCRITURA_FOLIO});",
    )


def upgrade() -> None:
    ex("SELECT set_config('app.rol', 'sistema', true);")
    ex("""
    CREATE TYPE tipo_folio AS ENUM ('correctivo','preventivo','especial');
    CREATE TYPE estado_folio AS ENUM ('capturado','en_revision','pendiente_informacion','autorizado','asignado','reasignado',
                                      'en_camino','en_ejecucion','pendiente_refaccion','cerrado','cancelado');
    CREATE TYPE severidad_origen AS ENUM ('automatica_matriz','override_admin');
    CREATE TYPE tipo_evidencia_folio AS ENUM ('antes','durante','despues','firma','factura','otro');
    CREATE TYPE origen_refaccion AS ENUM ('almacen','oc','caja_chica');
    CREATE TYPE trigger_revision AS ENUM ('sin_contrato','garantia','tipo_falla_flag','fuera_horario','keyword_alerta',
                                          'severidad_no_configurada','confirmacion_un_faltante');
    CREATE TYPE criterio_aprobacion AS ENUM ('monto','criticidad','tipo_trabajo');
    CREATE TYPE estado_flujo_aprobacion AS ENUM ('activo','aprobado','rechazado','bloqueado');
    CREATE TYPE comportamiento_timeout AS ENUM ('escalar','bloquear_alertar','autorizar_automatico','depende_criticidad');
    CREATE TYPE decision_aprobacion AS ENUM ('aprobado','rechazado','auto_aprobado','escalado','bloqueado');
    CREATE TYPE razon_rechazo AS ENUM ('por_presupuesto','requiere_cotizacion','seguimiento_interno','reprogramar');
    CREATE TYPE modulo_destino AS ENUM ('por_presupuesto','cotizaciones','seguimiento_interno','reprogramacion');
    CREATE TYPE canal_aprobacion AS ENUM ('push','app','minuta','sistema');
    CREATE TYPE criticidad_activo AS ENUM ('A','B','C','D');
    """)

    # ------------------------------------------------ cambios en tablas previas
    ex("""
    -- Días y horas de servicio del contrato: {"lunes": [["08:00","18:00"]], ...}; NULL = 24/7 (§6.8.6 "fuera de horario").
    ALTER TABLE contratos ADD COLUMN horario_servicio_json JSONB;
    -- Criticidad del activo capturada a mano por Admin empresa en Fase 1 (el cálculo automático de §6.9.3 es Fase 2).
    ALTER TABLE equipos ADD COLUMN criticidad criticidad_activo;
    -- Habilidad requerida para atender equipos de la familia (clave de `habilidades`); NULL = se compara por nombre.
    ALTER TABLE familias_equipo ADD COLUMN habilidad_clave VARCHAR(60);
    """)

    # --------------------------------------------------- configuración por tenant
    ex(f"""
    CREATE TABLE folio_politicas_tenant ({base},
      tenant_id UUID NOT NULL UNIQUE REFERENCES tenants(id),
      bloqueo_total_duplicados BOOLEAN NOT NULL DEFAULT false,
      revision_obligatoria_garantia BOOLEAN NOT NULL DEFAULT false,
      autorizacion_automatica_criticos BOOLEAN NOT NULL DEFAULT false,
      aprobacion_secuencial BOOLEAN NOT NULL DEFAULT false,
      prefijo_folio VARCHAR(10) NOT NULL DEFAULT 'F',
      ultimo_numero INTEGER NOT NULL DEFAULT 0,
      CONSTRAINT ck_folio_politicas_prefijo CHECK (prefijo_folio ~ '^[A-Z0-9]{{1,10}}$')
    );
    CREATE TABLE folio_keywords_alerta ({base},
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      tenant_id UUID REFERENCES tenants(id),
      palabra VARCHAR(80) NOT NULL,
      activa BOOLEAN NOT NULL DEFAULT true
    );
    CREATE UNIQUE INDEX ux_folio_keywords ON folio_keywords_alerta (prestador_id, COALESCE(tenant_id, '00000000-0000-0000-0000-000000000000'::uuid), lower(palabra));
    CREATE TABLE aprobacion_reglas ({base},
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      nivel SMALLINT NOT NULL CHECK (nivel BETWEEN 1 AND 3),
      criterio criterio_aprobacion NOT NULL,
      operador VARCHAR(12) NOT NULL,
      valor_json JSONB NOT NULL DEFAULT '{{}}'::jsonb,
      activa BOOLEAN NOT NULL DEFAULT true
    );
    CREATE INDEX ix_aprobacion_reglas_tenant ON aprobacion_reglas (tenant_id);
    CREATE TABLE aprobacion_niveles_config ({base},
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      nivel SMALLINT NOT NULL CHECK (nivel BETWEEN 1 AND 3),
      rol_aprobador rol_usuario NOT NULL,
      tiempo_limite_horas INTEGER NOT NULL CHECK (tiempo_limite_horas > 0),
      comportamiento_timeout comportamiento_timeout NOT NULL DEFAULT 'bloquear_alertar',
      notificar_por_json JSONB NOT NULL DEFAULT '["push","app"]'::jsonb,
      UNIQUE (tenant_id, nivel),
      -- §6.8.7: el Nivel 3 nunca escala ni autoriza automáticamente (no hay nivel superior).
      CONSTRAINT ck_aprobacion_nivel3 CHECK (nivel < 3 OR comportamiento_timeout IN ('bloquear_alertar','depende_criticidad'))
    );
    """)

    # --------------------------------------------------------------- folios
    ex(f"""
    CREATE TABLE folios ({base},
      numero_folio VARCHAR(30) NOT NULL,
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      un_id UUID NOT NULL REFERENCES unidades_negocio(id),
      equipo_id UUID NOT NULL REFERENCES equipos(id),
      tipo_falla_id UUID REFERENCES tipos_falla(id),
      tipo_folio tipo_folio NOT NULL DEFAULT 'correctivo',
      estado estado_folio NOT NULL DEFAULT 'capturado',
      prioridad SMALLINT NOT NULL DEFAULT 0,
      descripcion TEXT NOT NULL DEFAULT '',
      tecnico_id UUID REFERENCES usuarios(id),
      orden_en_ruta INTEGER,
      ventana_inicio TIMESTAMPTZ,
      ventana_fin TIMESTAMPTZ,
      severidad_id UUID REFERENCES niveles_severidad(id),
      severidad_origen severidad_origen NOT NULL DEFAULT 'automatica_matriz',
      confirmacion_un BOOLEAN NOT NULL DEFAULT false,
      confirmacion_un_timestamp TIMESTAMPTZ,
      confirmacion_un_geolat DOUBLE PRECISION,
      confirmacion_un_geolng DOUBLE PRECISION,
      folio_duplicado_justificacion TEXT,
      folio_duplicado_ref_id UUID REFERENCES folios(id),
      monto_estimado NUMERIC(14,2) CHECK (monto_estimado IS NULL OR monto_estimado >= 0),
      capturado_por UUID NOT NULL REFERENCES usuarios(id),
      capturado_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      geolat_captura DOUBLE PRECISION,
      geolng_captura DOUBLE PRECISION,
      fecha_falla TIMESTAMPTZ NOT NULL DEFAULT now(),
      fecha_inicio_atencion TIMESTAMPTZ,
      fecha_cierre TIMESTAMPTZ,
      razon_cancelacion TEXT,
      cancelado_por UUID REFERENCES usuarios(id),
      UNIQUE (tenant_id, numero_folio)
    );
    CREATE INDEX ix_folios_tenant_estado ON folios (tenant_id, estado);
    CREATE INDEX ix_folios_prestador_estado ON folios (prestador_id, estado);
    CREATE INDEX ix_folios_equipo ON folios (equipo_id);
    CREATE INDEX ix_folios_tecnico ON folios (tecnico_id);
    CREATE INDEX ix_folios_un ON folios (un_id);

    CREATE TABLE folio_estados_historial (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      folio_id UUID NOT NULL REFERENCES folios(id),
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      evento VARCHAR(60) NOT NULL DEFAULT 'transicion',
      estado_anterior estado_folio,
      estado_nuevo estado_folio NOT NULL,
      actor_id UUID REFERENCES usuarios(id),
      actor_rol VARCHAR(40) NOT NULL,
      timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
      notas TEXT NOT NULL DEFAULT '',
      datos_contexto_json JSONB NOT NULL DEFAULT '{{}}'::jsonb
    );
    CREATE INDEX ix_folio_historial_folio ON folio_estados_historial (folio_id, timestamp);

    CREATE TABLE folio_formulario_captura ({base},
      folio_id UUID NOT NULL UNIQUE REFERENCES folios(id),
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      respuesta_id UUID NOT NULL REFERENCES formulario_respuestas(id),
      formulario_id UUID NOT NULL REFERENCES formularios(id),
      version_formulario INTEGER NOT NULL,
      timestamp TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE TABLE folio_formulario_atencion ({base},
      folio_id UUID NOT NULL UNIQUE REFERENCES folios(id),
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      respuesta_id UUID NOT NULL REFERENCES formulario_respuestas(id),
      formulario_id UUID NOT NULL REFERENCES formularios(id),
      version_formulario INTEGER NOT NULL,
      timestamp TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE TABLE folio_evidencias ({base},
      folio_id UUID NOT NULL REFERENCES folios(id),
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      evidencia_id UUID REFERENCES formulario_evidencias(id),
      tipo tipo_evidencia_folio NOT NULL,
      archivo_key VARCHAR(300) NOT NULL,
      geolat DOUBLE PRECISION,
      geolng DOUBLE PRECISION,
      timestamp_captura TIMESTAMPTZ NOT NULL DEFAULT now(),
      subido_por UUID REFERENCES usuarios(id)
    );
    CREATE INDEX ix_folio_evidencias_folio ON folio_evidencias (folio_id);
    -- articulo_id sin FK: el catálogo de artículos de inventario llega en P09.
    CREATE TABLE folio_refacciones ({base},
      folio_id UUID NOT NULL REFERENCES folios(id),
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      articulo_id UUID,
      descripcion VARCHAR(200) NOT NULL,
      cantidad NUMERIC(12,2) NOT NULL CHECK (cantidad > 0),
      origen origen_refaccion NOT NULL DEFAULT 'almacen',
      costo_unitario NUMERIC(14,2) NOT NULL DEFAULT 0,
      gasto_caja_chica_id UUID
    );
    CREATE INDEX ix_folio_refacciones_folio ON folio_refacciones (folio_id);
    CREATE TABLE folio_sla ({base},
      folio_id UUID NOT NULL UNIQUE REFERENCES folios(id),
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      nivel_severidad_id UUID REFERENCES niveles_severidad(id),
      tiempo_respuesta_prometido_horas INTEGER NOT NULL,
      tiempo_resolucion_prometido_horas INTEGER NOT NULL,
      tiempo_respuesta_real_min INTEGER,
      tiempo_resolucion_real_min INTEGER,
      cumplimiento_respuesta BOOLEAN,
      cumplimiento_resolucion BOOLEAN
    );
    CREATE TABLE folio_encuesta ({base},
      folio_id UUID NOT NULL UNIQUE REFERENCES folios(id),
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      operador_id UUID NOT NULL REFERENCES usuarios(id),
      nps_score SMALLINT NOT NULL CHECK (nps_score BETWEEN 0 AND 10),
      respuesta_id UUID REFERENCES formulario_respuestas(id),
      timestamp TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE TABLE revision_manual_triggers ({base},
      folio_id UUID NOT NULL REFERENCES folios(id),
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      trigger_tipo trigger_revision NOT NULL,
      descripcion TEXT NOT NULL DEFAULT '',
      timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
      resuelto BOOLEAN NOT NULL DEFAULT false
    );
    CREATE INDEX ix_revision_triggers_folio ON revision_manual_triggers (folio_id);
    """)

    # ----------------------------------------------------- aprobación multinivel
    ex(f"""
    CREATE TABLE aprobacion_flujos ({base},
      folio_id UUID NOT NULL REFERENCES folios(id),
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      nivel_actual SMALLINT NOT NULL CHECK (nivel_actual BETWEEN 1 AND 3),
      nivel_maximo_requerido SMALLINT NOT NULL CHECK (nivel_maximo_requerido BETWEEN 1 AND 3),
      estado estado_flujo_aprobacion NOT NULL DEFAULT 'activo',
      iniciado_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      resuelto_at TIMESTAMPTZ
    );
    CREATE INDEX ix_aprobacion_flujos_folio ON aprobacion_flujos (folio_id);
    CREATE TABLE aprobacion_decisiones (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      flujo_id UUID NOT NULL REFERENCES aprobacion_flujos(id),
      folio_id UUID NOT NULL REFERENCES folios(id),
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      nivel SMALLINT NOT NULL,
      actor_id UUID REFERENCES usuarios(id),
      decision decision_aprobacion NOT NULL,
      razon_rechazo razon_rechazo,
      modulo_destino modulo_destino,
      modulo_destino_id UUID,
      canal canal_aprobacion NOT NULL,
      timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
      notas TEXT NOT NULL DEFAULT ''
    );
    CREATE INDEX ix_aprobacion_decisiones_flujo ON aprobacion_decisiones (flujo_id, timestamp);
    CREATE TABLE aprobacion_alertas_timeout ({base},
      flujo_id UUID NOT NULL REFERENCES aprobacion_flujos(id),
      folio_id UUID NOT NULL REFERENCES folios(id),
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      nivel SMALLINT NOT NULL,
      vence_at TIMESTAMPTZ NOT NULL,
      procesado BOOLEAN NOT NULL DEFAULT false,
      accion_ejecutada VARCHAR(40),
      procesado_at TIMESTAMPTZ
    );
    CREATE INDEX ix_aprobacion_timeout_pendientes ON aprobacion_alertas_timeout (vence_at) WHERE NOT procesado;
    """)

    versionar(*[t for t in TABLAS if t not in APPEND_ONLY])

    # ---------------------------------------------------- triggers y funciones
    ex("""
    -- Append-only como audit_log: ni UPDATE ni DELETE ni TRUNCATE, para ningún rol (incluido el dueño del esquema).
    CREATE TRIGGER trg_folio_estados_historial_inmutable BEFORE UPDATE OR DELETE ON folio_estados_historial
      FOR EACH ROW EXECUTE FUNCTION acma_auditoria_inmutable();
    CREATE TRIGGER trg_folio_estados_historial_truncate BEFORE TRUNCATE ON folio_estados_historial
      FOR EACH STATEMENT EXECUTE FUNCTION acma_auditoria_inmutable();
    CREATE TRIGGER trg_aprobacion_decisiones_inmutable BEFORE UPDATE OR DELETE ON aprobacion_decisiones
      FOR EACH ROW EXECUTE FUNCTION acma_auditoria_inmutable();
    CREATE TRIGGER trg_aprobacion_decisiones_truncate BEFORE TRUNCATE ON aprobacion_decisiones
      FOR EACH STATEMENT EXECUTE FUNCTION acma_auditoria_inmutable();

    -- §6.8.6 inmutabilidad: un folio cerrado o cancelado no cambia (solo updated_at/version_hash, que calcula acma_version()).
    CREATE FUNCTION acma_folio_inmutable() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF OLD.estado IN ('cerrado', 'cancelado')
         AND (to_jsonb(NEW) - 'updated_at' - 'version_hash') <> (to_jsonb(OLD) - 'updated_at' - 'version_hash') THEN
        RAISE EXCEPTION 'El folio % está % y es inmutable; solo se admiten comentarios en el historial', OLD.numero_folio, OLD.estado
          USING ERRCODE = 'insufficient_privilege';
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER trg_folios_inmutable BEFORE UPDATE ON folios FOR EACH ROW EXECUTE FUNCTION acma_folio_inmutable();
    CREATE TRIGGER trg_folios_sin_borrado BEFORE DELETE ON folios FOR EACH ROW EXECUTE FUNCTION acma_auditoria_inmutable();

    -- Correlativo por tenant con prefijo configurable (p. ej. CD-000123). Bloquea la fila de políticas del tenant.
    -- Pertenece a acma_auth (BYPASSRLS) porque un usuario del prestador también captura folios del tenant.
    CREATE FUNCTION acma_siguiente_numero_folio(p_tenant UUID) RETURNS TEXT
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
    DECLARE v_prefijo TEXT; v_numero INTEGER;
    BEGIN
      INSERT INTO folio_politicas_tenant (tenant_id) VALUES (p_tenant) ON CONFLICT (tenant_id) DO NOTHING;
      UPDATE folio_politicas_tenant SET ultimo_numero = ultimo_numero + 1 WHERE tenant_id = p_tenant
        RETURNING prefijo_folio, ultimo_numero INTO v_prefijo, v_numero;
      RETURN v_prefijo || '-' || lpad(v_numero::text, 6, '0');
    END $$;
    GRANT SELECT, INSERT, UPDATE ON folio_politicas_tenant TO acma_auth;
    GRANT CREATE ON SCHEMA public TO acma_auth;
    ALTER FUNCTION acma_siguiente_numero_folio(UUID) OWNER TO acma_auth;
    REVOKE CREATE ON SCHEMA public FROM acma_auth;
    GRANT EXECUTE ON FUNCTION acma_siguiente_numero_folio(UUID) TO acma_api;
    """)

    # ------------------------------------------------------------------ RLS
    for t in ("folio_politicas_tenant", "aprobacion_reglas", "aprobacion_niveles_config"):
        # Configuración del tenant: la lee también el prestador que lo atiende (necesita políticas y reglas al capturar).
        rls(t, f"CREATE POLICY {t}_lectura ON {t} FOR SELECT USING (acma_tenant_visible(tenant_id));",
            f"CREATE POLICY {t}_escritura ON {t} FOR ALL USING (acma_es_plataforma() OR tenant_id = acma_ctx_tenant()"
            f" OR (acma_ctx_prestador() IS NOT NULL AND acma_tenant_visible(tenant_id)))"
            f" WITH CHECK (acma_es_plataforma() OR tenant_id = acma_ctx_tenant()"
            f" OR (acma_ctx_prestador() IS NOT NULL AND acma_tenant_visible(tenant_id)));")
    rls("folio_keywords_alerta",
        "CREATE POLICY folio_keywords_alerta_lectura ON folio_keywords_alerta FOR SELECT USING (acma_prestador_visible(prestador_id));",
        "CREATE POLICY folio_keywords_alerta_escritura ON folio_keywords_alerta FOR ALL"
        " USING (acma_es_plataforma() OR prestador_id = acma_ctx_prestador())"
        " WITH CHECK (acma_es_plataforma() OR prestador_id = acma_ctx_prestador());")
    # Folios: además del tenant/prestador, el técnico solo ve los suyos (asignados o capturados por él).
    rls("folios", *_politicas_folio("folios", f"{LECTURA_FOLIO} AND (acma_ctx_rol() <> 'tecnico'"
                                               " OR tecnico_id = acma_ctx_usuario() OR capturado_por = acma_ctx_usuario())"))
    for t in TABLAS:
        if t in ("folio_politicas_tenant", "aprobacion_reglas", "aprobacion_niveles_config", "folio_keywords_alerta", "folios"):
            continue
        rls(t, *_politicas_folio(t))

    ex(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {', '.join(TABLAS)} TO acma_api;")
    ex("REVOKE UPDATE, DELETE, TRUNCATE ON folio_estados_historial, aprobacion_decisiones FROM acma_api;")
    ex("REVOKE DELETE ON folios FROM acma_api;")

    # --------------------------------------------------------------- alertas
    for clave, desc, d, mn, mx, tipo, dest in ALERTAS:
        ex(f"""
        INSERT INTO alertas_catalogo (clave, descripcion, umbral_default, umbral_min, umbral_max, tipo_umbral,
                                      modulo_origen, prompt_origen, destinatarios_default)
        VALUES ('{clave}', '{desc.replace("'", "''")}', {d}, {mn}, {mx}, '{tipo}', 'folios', 'P04', '{dest}'::jsonb);
        """)


def downgrade() -> None:
    ex("SELECT set_config('app.rol', 'sistema', true);")
    claves = ", ".join(f"'{a[0]}'" for a in ALERTAS)
    for t in ("alertas_historial", "alertas_configuracion", "alertas_supresiones"):
        ex(f"DELETE FROM {t} WHERE clave_alerta IN ({claves});")
    ex(f"DELETE FROM alertas_catalogo WHERE clave IN ({claves});")
    ex("DROP FUNCTION IF EXISTS acma_siguiente_numero_folio(UUID);")
    for t in reversed(TABLAS):
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE;")
    ex("""
    DROP FUNCTION IF EXISTS acma_folio_inmutable() CASCADE;
    ALTER TABLE equipos DROP COLUMN IF EXISTS criticidad;
    ALTER TABLE familias_equipo DROP COLUMN IF EXISTS habilidad_clave;
    ALTER TABLE contratos DROP COLUMN IF EXISTS horario_servicio_json;
    DROP TYPE IF EXISTS criticidad_activo;
    DROP TYPE IF EXISTS canal_aprobacion;
    DROP TYPE IF EXISTS modulo_destino;
    DROP TYPE IF EXISTS razon_rechazo;
    DROP TYPE IF EXISTS decision_aprobacion;
    DROP TYPE IF EXISTS comportamiento_timeout;
    DROP TYPE IF EXISTS estado_flujo_aprobacion;
    DROP TYPE IF EXISTS criterio_aprobacion;
    DROP TYPE IF EXISTS trigger_revision;
    DROP TYPE IF EXISTS origen_refaccion;
    DROP TYPE IF EXISTS tipo_evidencia_folio;
    DROP TYPE IF EXISTS severidad_origen;
    DROP TYPE IF EXISTS estado_folio;
    DROP TYPE IF EXISTS tipo_folio;
    """)
