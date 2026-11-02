"""0010 — Contrato con modalidad e iguala, contador de SLA con pausas y exclusiones (§6.10.1), penalizaciones por período,
conciliación del catálogo central de alertas (§6.9.6) y reportes ejecutivos programados (ACT-8.4). P10.

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-02
"""
from alembic import op

from core.sql_migracion import ex, politicas_prestador, politicas_tenant, rls, versionar

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

TABLAS = [
    "folio_sla_pausas", "folio_sla_exclusiones", "penalizaciones_periodo", "iguala_consumo_periodo",
    "reportes_programados", "reportes_generados",
]
ENUMS = [
    "motivo_pausa_sla", "causa_exclusion_sla", "estado_penalizacion", "formato_reporte", "periodicidad_reporte",
]

# Alertas nuevas de P10 (§6.10.1) y las dos escalaciones a Dirección. Las 20 claves de §6.9.6 ya vienen del catálogo
# de P01 con su nombre literal (PRESUPUESTO_ALERTA_1/2/3 incluidas): aquí solo se concilian las que P09 duplicó.
ALERTAS = [
    ("SLA_INCUMPLIDO", "Folio cerrado fuera del tiempo de resolución del SLA de su severidad; genera penalización.", 0, 0, 1,
     "cantidad", "sla", '["admin_prestador","mesa_control","admin_empresa"]', 1, None),
    ("EXCLUSION_SLA_PENDIENTE", "Exclusión de SLA registrada por el prestador sin decisión del Admin empresa por más de X días.", 2, 1, 30,
     "dias", "sla", '["admin_empresa","admin_un"]', 1, None),
    ("CONTRATO_POR_VENCER", "El contrato vence en menos de X días (§6.10.1).", 30, 1, 180,
     "dias", "contratos", '["admin_prestador","admin_empresa","direccion_prestador"]', 1, None),
    ("IGUALA_LIMITE_ALCANZADO", "Los folios correctivos del período alcanzaron el X% de los incluidos en la iguala.", 90, 50, 150,
     "porcentaje", "contratos", '["admin_prestador","mesa_control","admin_empresa"]', 1, None),
    ("SLA_INCUMPLIDO_ESCALADO_DIRECCION", "Folio con SLA incumplido sin atender por la operación; escala a Dirección del prestador.", 3, 1, 60,
     "dias", "sla", '["direccion_prestador"]', 1, "SLA_INCUMPLIDO"),
    ("PRESUPUESTO_ESCALADO_DIRECCION", "Presupuesto excedido sin resolución de la operación; escala a Dirección del prestador.", 7, 1, 60,
     "dias", "presupuestos", '["direccion_prestador"]', 1, "PRESUPUESTO_ALERTA_3"),
]
# Conciliación de claves: la clave de P09 queda como alias del evaluador y su configuración e historial se migran.
CONCILIACION = [("PRESUPUESTO_UMBRAL_ALCANZADO", "PRESUPUESTO_ALERTA_1"), ("PRESUPUESTO_EXCEDIDO", "PRESUPUESTO_ALERTA_3")]
# Alertas cuya fuente de datos es Fase 2 (GPS, medidores, certificaciones): visibles con la etiqueta, inactivas.
FASE_2 = ["TECNICO_TIEMPO_MUERTO", "TECNICO_DESVIO_RUTA", "TECNICO_SIN_SENAL", "MEDIDOR_PROXIMO_PM", "CERTIFICACION_VENCIDA"]

base = """
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      version_hash VARCHAR(64)"""

LECTURA_FOLIO = "(acma_tenant_visible(tenant_id) AND acma_prestador_visible(prestador_id))"
ESCRITURA_FOLIO = "(acma_es_plataforma() OR tenant_id = acma_ctx_tenant() OR prestador_id = acma_ctx_prestador())"


def _politicas_folio(t: str) -> tuple[str, ...]:
    """El prestador registra y el cliente aprueba: ambos escriben la misma fila (§6.10.1)."""
    return (
        f"CREATE POLICY {t}_lectura ON {t} FOR SELECT USING ({LECTURA_FOLIO});",
        f"CREATE POLICY {t}_insercion ON {t} FOR INSERT WITH CHECK ({ESCRITURA_FOLIO});",
        f"CREATE POLICY {t}_actualizacion ON {t} FOR UPDATE USING ({ESCRITURA_FOLIO}) WITH CHECK ({ESCRITURA_FOLIO});",
        f"CREATE POLICY {t}_borrado ON {t} FOR DELETE USING ({ESCRITURA_FOLIO});",
    )


def _politicas_reporte(t: str) -> tuple[str, ...]:
    """Reportes del tenant o del prestador: cada dominio ve y escribe los suyos."""
    visible = (f"(acma_es_plataforma() OR (tenant_id IS NOT NULL AND acma_tenant_visible(tenant_id))"
               f" OR (prestador_id IS NOT NULL AND acma_prestador_visible(prestador_id)))")
    escritura = (f"(acma_es_plataforma() OR (tenant_id IS NOT NULL AND tenant_id = acma_ctx_tenant())"
                 f" OR (prestador_id IS NOT NULL AND prestador_id = acma_ctx_prestador()))")
    return (
        f"CREATE POLICY {t}_lectura ON {t} FOR SELECT USING ({visible});",
        f"CREATE POLICY {t}_escritura ON {t} FOR ALL USING ({escritura}) WITH CHECK ({escritura});",
    )


def upgrade() -> None:
    ex("SELECT set_config('app.rol', 'sistema', true);")
    ex("""
    CREATE TYPE motivo_pausa_sla AS ENUM ('reasignacion','pendiente_informacion','otro');
    CREATE TYPE causa_exclusion_sla AS ENUM ('cliente_sin_acceso','fuerza_mayor','refaccion_no_disponible_mercado','otra');
    CREATE TYPE estado_penalizacion AS ENUM ('borrador','revisado','cerrado');
    CREATE TYPE formato_reporte AS ENUM ('pdf','excel');
    CREATE TYPE periodicidad_reporte AS ENUM ('diaria','semanal','mensual');
    """)

    # ------------------------------------------------- contrato: iguala (§6.10.1)
    # `estado` (estado_registro) ya cumple la función de `activo` de §6.10.1; no se duplica la bandera.
    ex("""
    ALTER TABLE contratos ADD COLUMN tarifa_iguala_mensual NUMERIC(14,2);
    ALTER TABLE contratos ADD COLUMN moneda VARCHAR(3) NOT NULL DEFAULT 'MXN';
    ALTER TABLE contratos ADD CONSTRAINT ck_contratos_iguala
      CHECK (modalidad <> 'iguala' OR (tarifa_iguala_mensual IS NOT NULL AND folios_correctivos_iguala IS NOT NULL));
    """)
    # El contrato guarda el tiempo en la unidad que el cliente firmó y su equivalente en horas (1 a 4,320).
    ex("""
    ALTER TABLE contrato_sla ADD COLUMN tiempo_respuesta INTEGER;
    ALTER TABLE contrato_sla ADD COLUMN tiempo_resolucion INTEGER;
    UPDATE contrato_sla SET tiempo_respuesta = tiempo_respuesta_horas, tiempo_resolucion = tiempo_resolucion_horas;
    ALTER TABLE contrato_sla ALTER COLUMN tiempo_respuesta SET NOT NULL;
    ALTER TABLE contrato_sla ALTER COLUMN tiempo_resolucion SET NOT NULL;
    ALTER TABLE contrato_sla ADD CONSTRAINT ck_contrato_sla_rango
      CHECK (tiempo_respuesta_horas BETWEEN 1 AND 4320 AND tiempo_resolucion_horas BETWEEN 1 AND 4320);
    """)

    # ------------------------------------------- contador del folio (§6.10.1)
    ex("""
    ALTER TABLE folio_sla ADD COLUMN tiempo_inicio TIMESTAMPTZ;
    ALTER TABLE folio_sla ADD COLUMN tiempo_respuesta_at TIMESTAMPTZ;
    ALTER TABLE folio_sla ADD COLUMN tiempo_fin TIMESTAMPTZ;
    ALTER TABLE folio_sla ADD COLUMN tiempo_pausado_min INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE folio_sla ADD COLUMN tiempo_exclusion_min INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE folio_sla ADD COLUMN tiempo_efectivo_min INTEGER;
    ALTER TABLE folio_sla ADD COLUMN tiempo_respuesta_efectivo_min INTEGER;
    ALTER TABLE folio_sla ADD COLUMN limite_respuesta_min INTEGER;
    ALTER TABLE folio_sla ADD COLUMN limite_sla_min INTEGER;
    ALTER TABLE folio_sla ADD COLUMN cumplimiento BOOLEAN;
    ALTER TABLE folio_sla ADD COLUMN penalizacion_calculada NUMERIC(12,2) NOT NULL DEFAULT 0;
    ALTER TABLE folio_sla ADD COLUMN penalizacion_detalle_json JSONB NOT NULL DEFAULT '{}'::jsonb;
    ALTER TABLE folio_sla ADD COLUMN contrato_sla_id UUID REFERENCES contrato_sla(id);
    ALTER TABLE folio_sla ADD COLUMN riesgo_respuesta_avisado BOOLEAN NOT NULL DEFAULT false;
    ALTER TABLE folio_sla ADD COLUMN riesgo_resolucion_avisado BOOLEAN NOT NULL DEFAULT false;
    CREATE INDEX ix_folio_sla_cumplimiento ON folio_sla (tenant_id, cumplimiento);
    CREATE INDEX ix_folio_sla_fin ON folio_sla (prestador_id, tiempo_fin);
    """)

    ex(f"""
    CREATE TABLE folio_sla_pausas ({base},
      folio_id UUID NOT NULL REFERENCES folios(id),
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      motivo motivo_pausa_sla NOT NULL,
      inicio TIMESTAMPTZ NOT NULL DEFAULT now(),
      fin TIMESTAMPTZ,
      minutos INTEGER,
      notas TEXT NOT NULL DEFAULT '',
      CONSTRAINT ck_folio_sla_pausas_rango CHECK (fin IS NULL OR fin >= inicio)
    );
    CREATE INDEX ix_folio_sla_pausas_folio ON folio_sla_pausas (folio_id);
    CREATE UNIQUE INDEX ux_folio_sla_pausa_abierta ON folio_sla_pausas (folio_id) WHERE fin IS NULL;
    """)

    ex(f"""
    CREATE TABLE folio_sla_exclusiones ({base},
      folio_id UUID NOT NULL REFERENCES folios(id),
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      causa causa_exclusion_sla NOT NULL,
      descripcion TEXT NOT NULL,
      registrado_por UUID REFERENCES usuarios(id),
      timestamp_inicio TIMESTAMPTZ NOT NULL,
      timestamp_fin TIMESTAMPTZ NOT NULL,
      minutos INTEGER NOT NULL,
      aprobado_por UUID REFERENCES usuarios(id),
      aprobada BOOLEAN,
      decidida_at TIMESTAMPTZ,
      razon_decision TEXT NOT NULL DEFAULT '',
      CONSTRAINT ck_folio_sla_exclusiones_rango CHECK (timestamp_fin > timestamp_inicio)
    );
    CREATE INDEX ix_folio_sla_exclusiones_folio ON folio_sla_exclusiones (folio_id);
    CREATE INDEX ix_folio_sla_exclusiones_pendientes ON folio_sla_exclusiones (tenant_id) WHERE aprobada IS NULL;
    """)

    # ------------------------------------- penalizaciones e iguala por período
    ex(f"""
    CREATE TABLE penalizaciones_periodo ({base},
      contrato_id UUID NOT NULL REFERENCES contratos(id),
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      periodo VARCHAR(7) NOT NULL,
      total_folios INTEGER NOT NULL DEFAULT 0,
      folios_incumplidos INTEGER NOT NULL DEFAULT 0,
      monto_penalizacion NUMERIC(14,2) NOT NULL DEFAULT 0,
      moneda VARCHAR(3) NOT NULL DEFAULT 'MXN',
      estado estado_penalizacion NOT NULL DEFAULT 'borrador',
      detalle_json JSONB NOT NULL DEFAULT '[]'::jsonb,
      revisado_por UUID REFERENCES usuarios(id),
      revisado_at TIMESTAMPTZ,
      cerrado_at TIMESTAMPTZ,
      incluido_en_factura_id UUID,
      CONSTRAINT ux_penalizaciones_periodo UNIQUE (contrato_id, periodo)
    );
    """)
    ex(f"""
    CREATE TABLE iguala_consumo_periodo ({base},
      contrato_id UUID NOT NULL REFERENCES contratos(id),
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      periodo VARCHAR(7) NOT NULL,
      correctivos_incluidos INTEGER NOT NULL DEFAULT 0,
      correctivos_atendidos INTEGER NOT NULL DEFAULT 0,
      correctivos_adicionales INTEGER NOT NULL DEFAULT 0,
      preventivos_incluidos INTEGER NOT NULL DEFAULT 0,
      preventivos_ejecutados INTEGER NOT NULL DEFAULT 0,
      tarifa_mensual NUMERIC(14,2) NOT NULL DEFAULT 0,
      folios_adicionales_json JSONB NOT NULL DEFAULT '[]'::jsonb,
      CONSTRAINT ux_iguala_consumo_periodo UNIQUE (contrato_id, periodo)
    );
    """)

    # ------------------------------------------- reportes programados (ACT-8.4)
    ex(f"""
    CREATE TABLE reportes_programados ({base},
      tenant_id UUID REFERENCES tenants(id),
      prestador_id UUID REFERENCES prestadores(id),
      nombre VARCHAR(160) NOT NULL,
      tipo_reporte VARCHAR(40) NOT NULL,
      filtros_json JSONB NOT NULL DEFAULT '{{}}'::jsonb,
      formato formato_reporte NOT NULL DEFAULT 'pdf',
      periodicidad periodicidad_reporte NOT NULL DEFAULT 'mensual',
      dia_hora VARCHAR(16) NOT NULL DEFAULT '08:00',
      destinatarios_json JSONB NOT NULL DEFAULT '[]'::jsonb,
      activo BOOLEAN NOT NULL DEFAULT true,
      ultimo_envio_at TIMESTAMPTZ,
      created_by UUID REFERENCES usuarios(id),
      CONSTRAINT ck_reportes_programados_dueno CHECK (tenant_id IS NOT NULL OR prestador_id IS NOT NULL)
    );
    CREATE INDEX ix_reportes_programados_activos ON reportes_programados (periodicidad) WHERE activo;
    """)
    ex(f"""
    CREATE TABLE reportes_generados ({base},
      programado_id UUID REFERENCES reportes_programados(id),
      tenant_id UUID REFERENCES tenants(id),
      prestador_id UUID REFERENCES prestadores(id),
      tipo_reporte VARCHAR(40) NOT NULL,
      filtros_json JSONB NOT NULL DEFAULT '{{}}'::jsonb,
      formato formato_reporte NOT NULL DEFAULT 'pdf',
      archivo_key VARCHAR(300) NOT NULL,
      filas INTEGER NOT NULL DEFAULT 0,
      ms_generacion INTEGER,
      generado_por UUID REFERENCES usuarios(id),
      generado_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      CONSTRAINT ck_reportes_generados_dueno CHECK (tenant_id IS NOT NULL OR prestador_id IS NOT NULL)
    );
    CREATE INDEX ix_reportes_generados_tipo ON reportes_generados (tipo_reporte, generado_at);
    """)

    # ------------------------------------- catálogo central de alertas (§6.9.6)
    ex("""
    ALTER TABLE alertas_catalogo ADD COLUMN fase SMALLINT NOT NULL DEFAULT 1;
    ALTER TABLE alertas_catalogo ADD COLUMN escalacion_de VARCHAR(60) REFERENCES alertas_catalogo(clave);
    ALTER TABLE alertas_catalogo ADD CONSTRAINT ck_alertas_catalogo_fase CHECK (fase IN (1, 2));
    ALTER TABLE alertas_historial ADD COLUMN vista_por UUID REFERENCES usuarios(id);
    ALTER TABLE alertas_historial ADD COLUMN atendida_at TIMESTAMPTZ;
    ALTER TABLE alertas_historial ADD COLUMN atendida_por UUID REFERENCES usuarios(id);
    ALTER TABLE alertas_historial ADD COLUMN nota_atencion TEXT NOT NULL DEFAULT '';
    ALTER TABLE alertas_historial ADD COLUMN escalada BOOLEAN NOT NULL DEFAULT false;
    CREATE INDEX ix_alertas_historial_clave_disparo ON alertas_historial (clave_alerta, timestamp_disparo);
    """)

    versionar(*TABLAS)
    for t in ("folio_sla_pausas", "folio_sla_exclusiones", "penalizaciones_periodo", "iguala_consumo_periodo"):
        rls(t, *_politicas_folio(t))
    for t in ("reportes_programados", "reportes_generados"):
        rls(t, *_politicas_reporte(t))
    ex(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {', '.join(TABLAS)} TO acma_api;")

    # ------------------------------------------------------------- semillas
    for clave, desc, d, mn, mx, tipo, modulo, dest, fase, escala in ALERTAS:
        ex(f"""
        INSERT INTO alertas_catalogo (clave, descripcion, umbral_default, umbral_min, umbral_max, tipo_umbral, modulo_origen,
                                      prompt_origen, destinatarios_default, fase, escalacion_de)
        VALUES ('{clave}', '{desc.replace("'", "''")}', {d}, {mn}, {mx}, '{tipo}', '{modulo}', 'P10', '{dest}'::jsonb, {fase},
                {"NULL" if escala is None else "'" + escala + "'"});
        """)
    # La escalación de cotizaciones de P01 se mide desde su alerta origen (§6.9.6).
    ex("UPDATE alertas_catalogo SET escalacion_de = 'COTIZACION_SIN_RESPUESTA' WHERE clave = 'COTIZACION_ESCALADA_DIRECCION';")
    claves_fase2 = ", ".join(f"'{c}'" for c in FASE_2)
    ex(f"UPDATE alertas_catalogo SET fase = 2, activa_por_defecto = false WHERE clave IN ({claves_fase2});")
    ex(f"UPDATE alertas_configuracion SET activa = false WHERE clave_alerta IN ({claves_fase2});")

    # Conciliación: la configuración y el historial de P09 pasan a la clave literal del documento.
    for vieja, nueva in CONCILIACION:
        ex(f"""
        UPDATE alertas_configuracion SET clave_alerta = '{nueva}' WHERE clave_alerta = '{vieja}'
          AND NOT EXISTS (SELECT 1 FROM alertas_configuracion c2 WHERE c2.clave_alerta = '{nueva}'
                          AND c2.tenant_id IS NOT DISTINCT FROM alertas_configuracion.tenant_id
                          AND c2.prestador_id IS NOT DISTINCT FROM alertas_configuracion.prestador_id);
        DELETE FROM alertas_configuracion WHERE clave_alerta = '{vieja}';
        UPDATE alertas_historial SET clave_alerta = '{nueva}' WHERE clave_alerta = '{vieja}';
        UPDATE alertas_supresiones SET clave_alerta = '{nueva}' WHERE clave_alerta = '{vieja}';
        DELETE FROM alertas_catalogo WHERE clave = '{vieja}';
        """)


def downgrade() -> None:
    ex("SELECT set_config('app.rol', 'sistema', true);")
    # Regresa las claves de P09 y devuelve su configuración e historial.
    ex("""
    INSERT INTO alertas_catalogo (clave, descripcion, umbral_default, umbral_min, umbral_max, tipo_umbral, modulo_origen,
                                  prompt_origen, destinatarios_default)
    VALUES ('PRESUPUESTO_UMBRAL_ALCANZADO', 'El consumo del presupuesto alcanzó uno de los umbrales configurados (umbrales_alerta_json).',
            80, 10, 100, 'porcentaje', 'presupuestos', 'P09', '["admin_empresa","admin_un"]'::jsonb),
           ('PRESUPUESTO_EXCEDIDO', 'El consumo del presupuesto superó el 100% del monto asignado.',
            100, 100, 200, 'porcentaje', 'presupuestos', 'P09', '["admin_empresa","admin_un","admin_prestador"]'::jsonb);
    """)
    for vieja, nueva in CONCILIACION:
        ex(f"""
        UPDATE alertas_historial SET clave_alerta = '{vieja}' WHERE clave_alerta = '{nueva}';
        UPDATE alertas_supresiones SET clave_alerta = '{vieja}' WHERE clave_alerta = '{nueva}';
        UPDATE alertas_configuracion SET clave_alerta = '{vieja}' WHERE clave_alerta = '{nueva}';
        """)
    claves = ", ".join(f"'{a[0]}'" for a in ALERTAS)
    for t in ("alertas_historial", "alertas_configuracion", "alertas_supresiones"):
        ex(f"DELETE FROM {t} WHERE clave_alerta IN ({claves});")
    ex(f"DELETE FROM alertas_catalogo WHERE clave IN ({claves});")
    claves_fase2 = ", ".join(f"'{c}'" for c in FASE_2)
    ex(f"UPDATE alertas_catalogo SET fase = 1, activa_por_defecto = true WHERE clave IN ({claves_fase2});")
    ex("""
    DROP INDEX IF EXISTS ix_alertas_historial_clave_disparo;
    ALTER TABLE alertas_historial DROP COLUMN IF EXISTS escalada;
    ALTER TABLE alertas_historial DROP COLUMN IF EXISTS nota_atencion;
    ALTER TABLE alertas_historial DROP COLUMN IF EXISTS atendida_por;
    ALTER TABLE alertas_historial DROP COLUMN IF EXISTS atendida_at;
    ALTER TABLE alertas_historial DROP COLUMN IF EXISTS vista_por;
    ALTER TABLE alertas_catalogo DROP CONSTRAINT IF EXISTS ck_alertas_catalogo_fase;
    ALTER TABLE alertas_catalogo DROP COLUMN IF EXISTS escalacion_de;
    ALTER TABLE alertas_catalogo DROP COLUMN IF EXISTS fase;
    """)
    ex("""
    DROP INDEX IF EXISTS ix_folio_sla_fin;
    DROP INDEX IF EXISTS ix_folio_sla_cumplimiento;
    ALTER TABLE folio_sla DROP COLUMN IF EXISTS riesgo_resolucion_avisado;
    ALTER TABLE folio_sla DROP COLUMN IF EXISTS riesgo_respuesta_avisado;
    ALTER TABLE folio_sla DROP COLUMN IF EXISTS contrato_sla_id;
    ALTER TABLE folio_sla DROP COLUMN IF EXISTS penalizacion_detalle_json;
    ALTER TABLE folio_sla DROP COLUMN IF EXISTS penalizacion_calculada;
    ALTER TABLE folio_sla DROP COLUMN IF EXISTS cumplimiento;
    ALTER TABLE folio_sla DROP COLUMN IF EXISTS limite_sla_min;
    ALTER TABLE folio_sla DROP COLUMN IF EXISTS limite_respuesta_min;
    ALTER TABLE folio_sla DROP COLUMN IF EXISTS tiempo_respuesta_efectivo_min;
    ALTER TABLE folio_sla DROP COLUMN IF EXISTS tiempo_efectivo_min;
    ALTER TABLE folio_sla DROP COLUMN IF EXISTS tiempo_exclusion_min;
    ALTER TABLE folio_sla DROP COLUMN IF EXISTS tiempo_pausado_min;
    ALTER TABLE folio_sla DROP COLUMN IF EXISTS tiempo_fin;
    ALTER TABLE folio_sla DROP COLUMN IF EXISTS tiempo_respuesta_at;
    ALTER TABLE folio_sla DROP COLUMN IF EXISTS tiempo_inicio;
    ALTER TABLE contrato_sla DROP CONSTRAINT IF EXISTS ck_contrato_sla_rango;
    ALTER TABLE contrato_sla DROP COLUMN IF EXISTS tiempo_resolucion;
    ALTER TABLE contrato_sla DROP COLUMN IF EXISTS tiempo_respuesta;
    ALTER TABLE contratos DROP CONSTRAINT IF EXISTS ck_contratos_iguala;
    ALTER TABLE contratos DROP COLUMN IF EXISTS moneda;
    ALTER TABLE contratos DROP COLUMN IF EXISTS tarifa_iguala_mensual;
    """)
    for t in reversed(TABLAS):
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE;")
    for e in reversed(ENUMS):
        op.execute(f"DROP TYPE IF EXISTS {e};")
