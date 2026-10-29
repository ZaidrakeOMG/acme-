"""0008 — Trabajos especiales con validación del cliente (§6.10.6), conversión de cotizaciones (§7.7 M1) y seguimiento de OC
para instalación de activos (§6.10.7). P08.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-29
"""
from alembic import op

from core.sql_migracion import ex, rls, versionar

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

TABLAS = ["trabajos_especiales", "te_respuesta_cliente", "te_evidencias", "te_historial", "folio_activo_autorizacion", "folio_activo_historial"]
ENUMS = ["estado_trabajo_especial", "decision_te_cliente", "tipo_evidencia_te", "estatus_oc_activo", "decision_oc_rechazo"]
ALERTAS = [
    ("TE_SIN_RESPUESTA_CLIENTE", "Trabajo especial enviado al cliente sin aceptación ni rechazo por más de X días.", 3, 1, 30, "dias", "trabajos_especiales", '["despachador","mesa_control","admin_prestador"]'),
    ("TE_ACEPTADO_SIN_PROGRAMAR", "Trabajo especial aceptado por el cliente sin fecha ni técnicos por más de X días.", 3, 1, 30, "dias", "trabajos_especiales", '["despachador","admin_prestador"]'),
    ("TE_PROGRAMADO_VENCIDO", "Trabajo especial con fecha programada vencida sin iniciar (X días de tolerancia).", 0, 0, 15, "dias", "trabajos_especiales", '["despachador","admin_prestador","admin_un"]'),
    ("TE_URGENCIA_SIN_COTIZACION_RETROACTIVA", "Trabajo especial de urgencia cerrado hace más de X días sin cotización retroactiva (informativa).", 7, 1, 90, "dias", "trabajos_especiales", '["admin_prestador","mesa_control"]'),
    ("OC_ACTIVO_SIN_TRAMITE", "Folio de instalación de activo sin iniciar el trámite de OC por más de X días.", 5, 1, 60, "dias", "oc_activos", '["admin_empresa","admin_un","mesa_control"]'),
    ("OC_ACTIVO_EN_TRAMITE_PROLONGADO", "Trámite de OC en el ERP del cliente sin resolución por más de X días.", 15, 1, 120, "dias", "oc_activos", '["admin_empresa","mesa_control"]'),
    ("ACTIVO_INSTALADO_INCOMPLETO", "Equipo dado de alta al cerrar un folio de activo con ficha incompleta (X días sin completarla).", 0, 0, 30, "dias", "oc_activos", '["admin_empresa","admin_un"]'),
]

base = """
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      version_hash VARCHAR(64)"""

LECTURA = "(acma_tenant_visible(tenant_id) AND acma_prestador_visible(prestador_id))"
ESCRITURA = "(acma_es_plataforma() OR tenant_id = acma_ctx_tenant() OR prestador_id = acma_ctx_prestador())"


def _politicas(t: str, solo_insercion: bool = False) -> tuple[str, ...]:
    politicas = (
        f"CREATE POLICY {t}_lectura ON {t} FOR SELECT USING ({LECTURA});",
        f"CREATE POLICY {t}_insercion ON {t} FOR INSERT WITH CHECK ({ESCRITURA});",
    )
    if solo_insercion:
        return politicas
    return politicas + (
        f"CREATE POLICY {t}_actualizacion ON {t} FOR UPDATE USING ({ESCRITURA}) WITH CHECK ({ESCRITURA});",
        f"CREATE POLICY {t}_borrado ON {t} FOR DELETE USING ({ESCRITURA});",
    )


def upgrade() -> None:
    ex("SELECT set_config('app.rol', 'sistema', true);")
    ex("""
    CREATE TYPE estado_trabajo_especial AS ENUM ('creado','enviado_cliente','aceptado','rechazado','programado','en_ejecucion','cerrado','cancelado');
    CREATE TYPE decision_te_cliente AS ENUM ('aceptado','rechazado');
    CREATE TYPE tipo_evidencia_te AS ENUM ('avance','cierre','firma','documento');
    CREATE TYPE estatus_oc_activo AS ENUM ('pendiente_iniciar_tramite','oc_en_tramite','oc_autorizada','listo_para_asignar','oc_rechazada');
    CREATE TYPE decision_oc_rechazo AS ENUM ('cancelar','reprogramar_periodo');
    """)

    # ------------------------------------------------ trabajos especiales (§6.10.6, §7.9)
    ex(f"""
    CREATE TABLE trabajos_especiales ({base},
      numero VARCHAR(20) NOT NULL,
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      un_id UUID NOT NULL REFERENCES unidades_negocio(id),
      equipo_id UUID REFERENCES equipos(id),
      cotizacion_id UUID REFERENCES cotizaciones(id),
      hallazgo_id UUID REFERENCES hallazgos(id),
      descripcion TEXT NOT NULL DEFAULT '',
      detalle_json JSONB NOT NULL DEFAULT '{{}}'::jsonb,
      estado estado_trabajo_especial NOT NULL DEFAULT 'creado',
      estado_desde TIMESTAMPTZ NOT NULL DEFAULT now(),
      urgencia BOOLEAN NOT NULL DEFAULT false,
      creado_por_id UUID REFERENCES usuarios(id),
      creado_por_rol VARCHAR(40) NOT NULL DEFAULT 'sistema',
      formulario_id UUID REFERENCES formularios(id),
      respuesta_formulario_id UUID REFERENCES formulario_respuestas(id),
      monto NUMERIC(14,2),
      moneda VARCHAR(3) NOT NULL DEFAULT 'MXN',
      cotizacion_retroactiva_id UUID REFERENCES cotizaciones(id),
      fecha_programada DATE,
      fecha_inicio TIMESTAMPTZ,
      fecha_cierre TIMESTAMPTZ,
      tecnico_ids_json JSONB NOT NULL DEFAULT '[]'::jsonb,
      tecnico_responsable_id UUID REFERENCES usuarios(id),
      folio_id UUID REFERENCES folios(id),
      razon_cancelacion TEXT,
      version_enviada INTEGER NOT NULL DEFAULT 0,
      enviado_at TIMESTAMPTZ,
      aceptado_at TIMESTAMPTZ,
      programado_at TIMESTAMPTZ,
      UNIQUE (prestador_id, numero)
    );
    CREATE INDEX ix_trabajos_especiales_tenant_estado ON trabajos_especiales (tenant_id, estado);
    CREATE INDEX ix_trabajos_especiales_folio ON trabajos_especiales (folio_id);
    CREATE TABLE te_respuesta_cliente (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      trabajo_especial_id UUID NOT NULL REFERENCES trabajos_especiales(id),
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      version_enviada INTEGER NOT NULL DEFAULT 1,
      respondido_por UUID REFERENCES usuarios(id),
      decision decision_te_cliente NOT NULL,
      comentario TEXT NOT NULL DEFAULT '',
      canal VARCHAR(20) NOT NULL DEFAULT 'app',
      timestamp TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE INDEX ix_te_respuesta_cliente_te ON te_respuesta_cliente (trabajo_especial_id, timestamp);
    CREATE TRIGGER trg_te_respuesta_cliente_inmutable BEFORE UPDATE OR DELETE OR TRUNCATE ON te_respuesta_cliente
      FOR EACH STATEMENT EXECUTE FUNCTION acma_auditoria_inmutable();
    CREATE TABLE te_evidencias ({base},
      trabajo_especial_id UUID NOT NULL REFERENCES trabajos_especiales(id),
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      tipo tipo_evidencia_te NOT NULL DEFAULT 'avance',
      evidencia_id UUID REFERENCES formulario_evidencias(id),
      archivo_key VARCHAR(300) NOT NULL DEFAULT '',
      geolat DOUBLE PRECISION,
      geolng DOUBLE PRECISION,
      timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
      subido_por UUID REFERENCES usuarios(id)
    );
    CREATE INDEX ix_te_evidencias_te ON te_evidencias (trabajo_especial_id, timestamp);
    CREATE TABLE te_historial (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      trabajo_especial_id UUID NOT NULL REFERENCES trabajos_especiales(id),
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      estado_anterior VARCHAR(40),
      estado_nuevo VARCHAR(40) NOT NULL,
      actor_id UUID REFERENCES usuarios(id),
      actor_rol VARCHAR(40) NOT NULL DEFAULT 'sistema',
      timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
      notas TEXT NOT NULL DEFAULT '',
      datos_json JSONB NOT NULL DEFAULT '{{}}'::jsonb
    );
    CREATE INDEX ix_te_historial_te ON te_historial (trabajo_especial_id, timestamp);
    CREATE TRIGGER trg_te_historial_inmutable BEFORE UPDATE OR DELETE OR TRUNCATE ON te_historial
      FOR EACH STATEMENT EXECUTE FUNCTION acma_auditoria_inmutable();
    """)

    # ------------------------------------------------ OC de activos (§6.10.7)
    ex(f"""
    CREATE TABLE folio_activo_autorizacion ({base},
      folio_id UUID NOT NULL UNIQUE REFERENCES folios(id),
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      un_id UUID NOT NULL REFERENCES unidades_negocio(id),
      estatus_multinivel estatus_oc_activo NOT NULL DEFAULT 'pendiente_iniciar_tramite',
      estatus_desde TIMESTAMPTZ NOT NULL DEFAULT now(),
      numero_oc_provisional VARCHAR(60),
      numero_oc_definitivo VARCHAR(60),
      fecha_autorizacion_erp DATE,
      registrado_por UUID REFERENCES usuarios(id),
      notas TEXT NOT NULL DEFAULT '',
      decision_rechazo decision_oc_rechazo,
      periodo_presupuestal_destino VARCHAR(40),
      origen VARCHAR(30) NOT NULL DEFAULT 'captura',
      respuesta_id UUID REFERENCES formulario_respuestas(id),
      datos_equipo_json JSONB NOT NULL DEFAULT '{{}}'::jsonb,
      hallazgo_presupuesto_id UUID REFERENCES hallazgos_presupuesto(id)
    );
    CREATE INDEX ix_folio_activo_autorizacion_tenant_estatus ON folio_activo_autorizacion (tenant_id, estatus_multinivel);
    CREATE TABLE folio_activo_historial (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      folio_id UUID NOT NULL REFERENCES folios(id),
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      estatus_anterior VARCHAR(40),
      estatus_nuevo VARCHAR(40) NOT NULL,
      actor_id UUID REFERENCES usuarios(id),
      actor_rol VARCHAR(40) NOT NULL DEFAULT 'sistema',
      timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
      notas TEXT NOT NULL DEFAULT ''
    );
    CREATE INDEX ix_folio_activo_historial_folio ON folio_activo_historial (folio_id, timestamp);
    CREATE TRIGGER trg_folio_activo_historial_inmutable BEFORE UPDATE OR DELETE OR TRUNCATE ON folio_activo_historial
      FOR EACH STATEMENT EXECUTE FUNCTION acma_auditoria_inmutable();
    """)

    # ------------------------------------------------ tablas existentes
    ex("""
    ALTER TABLE cotizaciones ADD CONSTRAINT fk_cotizaciones_trabajo_especial FOREIGN KEY (trabajo_especial_id) REFERENCES trabajos_especiales(id);
    ALTER TABLE folios ADD COLUMN es_instalacion_activo BOOLEAN NOT NULL DEFAULT false;
    ALTER TABLE folios ADD COLUMN equipo_instalado_id UUID REFERENCES equipos(id);
    ALTER TABLE folios ADD COLUMN trabajo_especial_id UUID REFERENCES trabajos_especiales(id);
    CREATE INDEX ix_folios_trabajo_especial ON folios (trabajo_especial_id);
    """)
    # El folio de instalación de activo espera la OC del cliente como un trigger más de revisión (§6.10.7, decisión pendiente).
    ex("ALTER TYPE trigger_revision ADD VALUE IF NOT EXISTS 'pendiente_oc_cliente';")

    versionar("trabajos_especiales", "te_evidencias", "folio_activo_autorizacion")

    # ------------------------------------------------------------------ RLS
    for t in ("trabajos_especiales", "te_evidencias", "folio_activo_autorizacion"):
        rls(t, *_politicas(t))
    for t in ("te_respuesta_cliente", "te_historial", "folio_activo_historial"):
        rls(t, *_politicas(t, solo_insercion=True))
    ex(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {', '.join(TABLAS)} TO acma_api;")

    # ------------------------------------------------------------- semillas
    for clave, desc, d, mn, mx, tipo, modulo, dest in ALERTAS:
        ex(f"""
        INSERT INTO alertas_catalogo (clave, descripcion, umbral_default, umbral_min, umbral_max, tipo_umbral, modulo_origen, prompt_origen, destinatarios_default)
        VALUES ('{clave}', '{desc.replace("'", "''")}', {d}, {mn}, {mx}, '{tipo}', '{modulo}', 'P08', '{dest}'::jsonb);
        """)


def downgrade() -> None:
    ex("SELECT set_config('app.rol', 'sistema', true);")
    claves = ", ".join(f"'{a[0]}'" for a in ALERTAS)
    for t in ("alertas_historial", "alertas_configuracion", "alertas_supresiones"):
        ex(f"DELETE FROM {t} WHERE clave_alerta IN ({claves});")
    ex(f"DELETE FROM alertas_catalogo WHERE clave IN ({claves});")
    ex("""
    ALTER TABLE cotizaciones DROP CONSTRAINT IF EXISTS fk_cotizaciones_trabajo_especial;
    UPDATE cotizaciones SET trabajo_especial_id = NULL WHERE trabajo_especial_id IS NOT NULL;
    ALTER TABLE folios DROP COLUMN IF EXISTS trabajo_especial_id;
    ALTER TABLE folios DROP COLUMN IF EXISTS equipo_instalado_id;
    ALTER TABLE folios DROP COLUMN IF EXISTS es_instalacion_activo;
    """)
    for t in reversed(TABLAS):
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE;")
    for e in reversed(ENUMS):
        op.execute(f"DROP TYPE IF EXISTS {e};")
    # El valor 'pendiente_oc_cliente' de trigger_revision no se puede quitar de un ENUM; se elimina al bajar 0004.
