"""0006 — Planes de mantenimiento con triggers (§6.9.1), calendario de preventivos (§7.6), autorizaciones de
reprogramación/cancelación y reasignaciones forzadas (§6.8.2). P06.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-28
"""
from alembic import op

from core.sql_migracion import ex, politicas_prestador, rls, versionar

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

TABLAS = [
    "planes_mantenimiento", "plan_triggers", "plan_tareas", "plan_materiales", "preventivos_calendario", "plan_ejecuciones",
    "equipo_planes", "calendario_publicaciones", "autorizaciones_preventivo", "razones_reasignacion", "reasignaciones",
    "reasignacion_validaciones",
]
ALERTAS = [
    ("PREVENTIVO_VENCIDO_SIN_EJECUTAR", "Preventivo con fecha programada (más la ventana del plan) superada por más de X días sin cierre.",
     0, 0, 90, "dias", '["despachador","admin_prestador","admin_un"]'),
    ("AUTORIZACION_PREVENTIVO_PENDIENTE", "Solicitud de reprogramación o cancelación de un preventivo sin respuesta tras X horas.",
     24, 1, 720, "horas", '["admin_un","admin_empresa","despachador"]'),
    ("CALENDARIO_MES_SIN_PUBLICAR", "Llegó el día X del mes y el calendario de preventivos del mes siguiente no se ha publicado.",
     25, 1, 31, "dias", '["despachador","admin_prestador"]'),
]
RAZONES = [
    ("Incidencia del técnico", "Accidente, descompostura de vehículo, enfermedad u otra causa que impide al técnico continuar."),
    ("Prioridad de cliente", "El cliente solicita atención inmediata que requiere reubicar recursos."),
    ("Optimización de ruta", "El despachador detecta una oportunidad de mejora que el algoritmo no capturó."),
    ("Falta de habilidad no detectada", "Se descubrió en campo que el folio requiere una habilidad distinta a la registrada."),
    ("Falta de refacción", "El técnico no tiene la refacción y no puede abastecerse a tiempo."),
    ("Solicitud del técnico", "El técnico reporta que no puede atender el folio por razones justificadas."),
    ("Corrección de asignación inicial", "Error en la asignación automática detectado por el despachador."),
]

base = """
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      version_hash VARCHAR(64)"""

LECTURA_FOLIO = "(acma_tenant_visible(tenant_id) AND acma_prestador_visible(prestador_id))"
ESCRITURA_FOLIO = "(acma_es_plataforma() OR tenant_id = acma_ctx_tenant() OR prestador_id = acma_ctx_prestador())"


def _politicas_folio(t: str) -> tuple[str, ...]:
    return (
        f"CREATE POLICY {t}_lectura ON {t} FOR SELECT USING ({LECTURA_FOLIO});",
        f"CREATE POLICY {t}_insercion ON {t} FOR INSERT WITH CHECK ({ESCRITURA_FOLIO});",
        f"CREATE POLICY {t}_actualizacion ON {t} FOR UPDATE USING ({ESCRITURA_FOLIO}) WITH CHECK ({ESCRITURA_FOLIO});",
        f"CREATE POLICY {t}_borrado ON {t} FOR DELETE USING ({ESCRITURA_FOLIO});",
    )


def upgrade() -> None:
    ex("SELECT set_config('app.rol', 'sistema', true);")
    ex("""
    CREATE TYPE tipo_trigger_plan AS ENUM ('tiempo_fijo','calendario','medidor_umbral','medidor_intervalo','evento','combinado');
    CREATE TYPE estado_plan AS ENUM ('activo','inactivo');
    CREATE TYPE estado_ejecucion_plan AS ENUM ('programada','generada','ejecutada','cancelada');
    CREATE TYPE estado_preventivo AS ENUM ('programado','generado','reprogramado','cancelado','ejecutado');
    CREATE TYPE origen_preventivo AS ENUM ('manual','plan');
    CREATE TYPE tipo_autorizacion_preventivo AS ENUM ('reprogramacion','cancelacion');
    CREATE TYPE estado_autorizacion AS ENUM ('pendiente','autorizada','rechazada');
    CREATE TYPE tipo_reasignacion AS ENUM ('automatica','forzada');
    """)

    # ------------------------------------------------------- planes (§6.9.1)
    ex(f"""
    CREATE TABLE planes_mantenimiento ({base},
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      tenant_id UUID REFERENCES tenants(id),
      tipo_equipo_id UUID NOT NULL REFERENCES tipos_equipo(id),
      nombre VARCHAR(160) NOT NULL,
      descripcion TEXT NOT NULL DEFAULT '',
      version INTEGER NOT NULL DEFAULT 1,
      estado estado_plan NOT NULL DEFAULT 'activo',
      tiempo_ventana_dias INTEGER NOT NULL DEFAULT 7 CHECK (tiempo_ventana_dias >= 0),
      formulario_id UUID REFERENCES formularios(id),
      nivel_severidad_id UUID REFERENCES niveles_severidad(id),
      created_by UUID REFERENCES usuarios(id)
    );
    CREATE INDEX ix_planes_prestador ON planes_mantenimiento (prestador_id, estado);
    CREATE TABLE plan_triggers ({base},
      plan_id UUID NOT NULL REFERENCES planes_mantenimiento(id) ON DELETE CASCADE,
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      tipo_trigger tipo_trigger_plan NOT NULL,
      parametros_json JSONB NOT NULL DEFAULT '{{}}'::jsonb,
      logica_combinacion VARCHAR(10)
    );
    CREATE TABLE plan_tareas ({base},
      plan_id UUID NOT NULL REFERENCES planes_mantenimiento(id) ON DELETE CASCADE,
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      orden INTEGER NOT NULL DEFAULT 1,
      descripcion VARCHAR(300) NOT NULL,
      tiempo_estimado_min INTEGER NOT NULL DEFAULT 0,
      habilidad_requerida_id UUID REFERENCES habilidades(id)
    );
    -- articulo_id sin FK: el catálogo de artículos de inventario llega en P09.
    CREATE TABLE plan_materiales ({base},
      plan_id UUID NOT NULL REFERENCES planes_mantenimiento(id) ON DELETE CASCADE,
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      articulo_id UUID,
      descripcion VARCHAR(200) NOT NULL,
      cantidad_estandar NUMERIC(12,2) NOT NULL DEFAULT 1,
      unidad VARCHAR(30) NOT NULL DEFAULT 'pieza'
    );
    -- Unificación de calendarios_preventivos (§6.9.1) y preventivos_calendario (§7.6).
    CREATE TABLE preventivos_calendario ({base},
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      un_id UUID NOT NULL REFERENCES unidades_negocio(id),
      equipo_id UUID REFERENCES equipos(id),
      plan_id UUID REFERENCES planes_mantenimiento(id),
      tecnico_id UUID REFERENCES usuarios(id),
      fecha_programada DATE NOT NULL,
      fecha_programada_original DATE,
      fecha_real DATE,
      desvio_dias INTEGER,
      estado estado_preventivo NOT NULL DEFAULT 'programado',
      folio_id UUID REFERENCES folios(id),
      formulario_id UUID REFERENCES formularios(id),
      origen origen_preventivo NOT NULL DEFAULT 'manual',
      descripcion TEXT NOT NULL DEFAULT '',
      cargado_por UUID REFERENCES usuarios(id),
      reprogramado_desde_id UUID REFERENCES preventivos_calendario(id)
    );
    CREATE INDEX ix_preventivos_calendario_fecha ON preventivos_calendario (tenant_id, fecha_programada);
    CREATE INDEX ix_preventivos_calendario_folio ON preventivos_calendario (folio_id);
    CREATE TABLE plan_ejecuciones ({base},
      plan_id UUID NOT NULL REFERENCES planes_mantenimiento(id),
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      equipo_id UUID NOT NULL REFERENCES equipos(id),
      folio_id UUID REFERENCES folios(id),
      calendario_id UUID REFERENCES preventivos_calendario(id),
      formulario_id UUID REFERENCES formularios(id),
      fecha_programada DATE NOT NULL,
      fecha_real DATE,
      desvio_dias INTEGER,
      estado estado_ejecucion_plan NOT NULL DEFAULT 'programada'
    );
    CREATE INDEX ix_plan_ejecuciones_plan ON plan_ejecuciones (plan_id, fecha_programada);
    CREATE TABLE equipo_planes ({base},
      equipo_id UUID NOT NULL REFERENCES equipos(id),
      plan_id UUID NOT NULL REFERENCES planes_mantenimiento(id),
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      activo BOOLEAN NOT NULL DEFAULT true,
      fecha_proxima_ejecucion DATE,
      ultimo_valor_medidor NUMERIC(14,2),
      fecha_ultima_ejecucion DATE,
      fecha_alta DATE NOT NULL DEFAULT current_date,
      UNIQUE (equipo_id, plan_id)
    );
    CREATE TABLE calendario_publicaciones ({base},
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      mes DATE NOT NULL,
      publicado_por UUID REFERENCES usuarios(id),
      publicado_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      total_preventivos INTEGER NOT NULL DEFAULT 0,
      UNIQUE (prestador_id, tenant_id, mes)
    );
    CREATE TABLE autorizaciones_preventivo ({base},
      folio_id UUID NOT NULL REFERENCES folios(id),
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      calendario_id UUID REFERENCES preventivos_calendario(id),
      tipo tipo_autorizacion_preventivo NOT NULL,
      solicitado_por UUID NOT NULL REFERENCES usuarios(id),
      autorizado_por UUID REFERENCES usuarios(id),
      fecha_solicitud TIMESTAMPTZ NOT NULL DEFAULT now(),
      fecha_autorizacion TIMESTAMPTZ,
      razon TEXT NOT NULL,
      fecha_nueva DATE,
      estado estado_autorizacion NOT NULL DEFAULT 'pendiente',
      canal canal_aprobacion NOT NULL DEFAULT 'app',
      notas_respuesta TEXT NOT NULL DEFAULT ''
    );
    CREATE INDEX ix_autorizaciones_preventivo_folio ON autorizaciones_preventivo (folio_id, estado);
    -- FK diferida de P03 y vínculo del folio con su plan/calendario.
    ALTER TABLE formulario_asignaciones ADD CONSTRAINT fk_formulario_asignaciones_plan
      FOREIGN KEY (plan_mantenimiento_id) REFERENCES planes_mantenimiento(id);
    ALTER TABLE folios ADD COLUMN plan_id UUID REFERENCES planes_mantenimiento(id);
    ALTER TABLE folios ADD COLUMN calendario_id UUID REFERENCES preventivos_calendario(id);
    """)

    # ------------------------------------------------ reasignaciones (§6.8.2)
    ex(f"""
    CREATE TABLE razones_reasignacion ({base},
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      descripcion VARCHAR(160) NOT NULL,
      detalle TEXT NOT NULL DEFAULT '',
      activa BOOLEAN NOT NULL DEFAULT true,
      orden_display INTEGER NOT NULL DEFAULT 0,
      UNIQUE (prestador_id, descripcion)
    );
    CREATE TABLE reasignaciones ({base},
      folio_id UUID NOT NULL REFERENCES folios(id),
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      tecnico_origen_id UUID REFERENCES usuarios(id),
      tecnico_destino_id UUID NOT NULL REFERENCES usuarios(id),
      tipo tipo_reasignacion NOT NULL DEFAULT 'forzada',
      razon_id UUID REFERENCES razones_reasignacion(id),
      comentario TEXT NOT NULL DEFAULT '',
      despachador_id UUID REFERENCES usuarios(id),
      timestamp TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE INDEX ix_reasignaciones_folio ON reasignaciones (folio_id, timestamp);
    CREATE TABLE reasignacion_validaciones ({base},
      reasignacion_id UUID NOT NULL REFERENCES reasignaciones(id),
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      habilidad_ok BOOLEAN NOT NULL DEFAULT true,
      refaccion_ok BOOLEAN,
      advertencias_json JSONB NOT NULL DEFAULT '[]'::jsonb
    );
    """)

    versionar(*TABLAS)

    # ------------------------------------------------------------------ RLS
    for t in ("planes_mantenimiento", "plan_triggers", "plan_tareas", "plan_materiales", "razones_reasignacion"):
        rls(t, *politicas_prestador(t, lectura_tenants=True))
    for t in ("preventivos_calendario", "plan_ejecuciones", "equipo_planes", "calendario_publicaciones", "autorizaciones_preventivo",
              "reasignaciones", "reasignacion_validaciones"):
        rls(t, *_politicas_folio(t))
    ex(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {', '.join(TABLAS)} TO acma_api;")

    # ------------------------------------------------------------- semillas
    for clave, desc, d, mn, mx, tipo, dest in ALERTAS:
        ex(f"""
        INSERT INTO alertas_catalogo (clave, descripcion, umbral_default, umbral_min, umbral_max, tipo_umbral, modulo_origen, prompt_origen, destinatarios_default)
        VALUES ('{clave}', '{desc.replace("'", "''")}', {d}, {mn}, {mx}, '{tipo}', 'preventivos', 'P06', '{dest}'::jsonb);
        """)
    # Catálogo literal de razones para los prestadores existentes (los nuevos lo reciben al crearse).
    for i, (desc, detalle) in enumerate(RAZONES, start=1):
        ex(f"""
        INSERT INTO razones_reasignacion (prestador_id, descripcion, detalle, orden_display)
        SELECT id, '{desc.replace("'", "''")}', '{detalle.replace("'", "''")}', {i} FROM prestadores;
        """)


def downgrade() -> None:
    ex("SELECT set_config('app.rol', 'sistema', true);")
    claves = ", ".join(f"'{a[0]}'" for a in ALERTAS)
    for t in ("alertas_historial", "alertas_configuracion", "alertas_supresiones"):
        ex(f"DELETE FROM {t} WHERE clave_alerta IN ({claves});")
    ex(f"DELETE FROM alertas_catalogo WHERE clave IN ({claves});")
    ex("ALTER TABLE folios DROP COLUMN IF EXISTS calendario_id; ALTER TABLE folios DROP COLUMN IF EXISTS plan_id;")
    ex("ALTER TABLE formulario_asignaciones DROP CONSTRAINT IF EXISTS fk_formulario_asignaciones_plan;")
    for t in reversed(TABLAS):
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE;")
    ex("""
    DROP TYPE IF EXISTS tipo_reasignacion; DROP TYPE IF EXISTS estado_autorizacion; DROP TYPE IF EXISTS tipo_autorizacion_preventivo;
    DROP TYPE IF EXISTS origen_preventivo; DROP TYPE IF EXISTS estado_preventivo; DROP TYPE IF EXISTS estado_ejecucion_plan;
    DROP TYPE IF EXISTS estado_plan; DROP TYPE IF EXISTS tipo_trigger_plan;
    """)
