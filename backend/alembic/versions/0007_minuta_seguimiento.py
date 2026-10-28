"""0007 — Hallazgos y peticiones, minuta del día (§7.1–7.5), notificaciones multicanal (§6.1), los cuatro módulos de
seguimiento (§7.7–7.9), clasificación de folios no críticos y calificación del Admin UN (§6.10.5). P07.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-29
"""
from alembic import op

from core.sql_migracion import ex, politicas_tenant, rls, versionar

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

TABLAS = [
    "hallazgos", "peticiones_cliente", "minuta_configuracion", "minutas", "minutas_secciones", "minutas_respuestas", "minutas_destinatarios",
    "notificaciones", "notificacion_preferencias", "periodos_presupuestales", "cotizaciones", "cotizacion_envios_externos",
    "hallazgos_presupuesto", "seguimientos_internos", "reprogramaciones", "modulo_historial", "clasificacion_configuracion",
    "folio_clasificaciones", "admin_un_calificacion",
]
ENUMS = [
    "nivel_urgencia", "tipo_hallazgo", "origen_hallazgo", "estado_respuesta_hallazgo", "opcion_respuesta_minuta", "origen_peticion", "tipo_minuta",
    "estado_minuta", "modo_minuta", "canal_notificacion", "estado_notificacion", "estado_cotizacion", "estado_presupuesto",
    "estado_seguimiento_interno", "estado_reprogramacion", "variante_coordinado", "tipo_periodo_presupuestal", "opcion_clasificacion",
]
# Alertas nuevas (las de COTIZACION_SIN_PREPARAR, COTIZACION_SIN_RESPUESTA, SEGUIMIENTO_SIN_UPDATE, REPROGRAMACION_FECHA_VENCIDA y
# FOLIO_SIN_CLASIFICAR ya existen desde 0001 y reciben evaluador en P07).
ALERTAS = [
    ("MINUTA_SIN_VALIDAR", "Minuta pendiente de validación del despachador que supera la ventana configurada (minutos).", 30, 5, 240, "minutos", "minuta", '["despachador","admin_prestador"]'),
    ("MINUTA_SIN_RESPUESTA", "Minuta enviada sin respuesta del Admin UN tras X horas.", 24, 1, 168, "horas", "minuta", '["admin_un","admin_empresa","despachador"]'),
    ("MINUTA_NO_GENERADA", "Un tenant con actividad no tiene minuta generada X horas después de la hora de envío.", 2, 1, 24, "horas", "minuta", '["despachador","admin_prestador"]'),
    ("COTIZACION_SIN_ENVIAR", "Cotización en preparación sin enviar al cliente por más de X días.", 3, 1, 60, "dias", "seguimiento", '["admin_prestador","despachador","mesa_control"]'),
    ("COTIZACION_AUTORIZADA_SIN_CONVERTIR", "Cotización autorizada sin convertir en Trabajo Especial después de X días.", 3, 1, 30, "dias", "seguimiento", '["despachador","admin_prestador"]'),
    ("PRESUPUESTO_SIN_REVISION", "Hallazgo diferido por presupuesto sin revisión por más de X días.", 30, 1, 365, "dias", "seguimiento", '["admin_un","admin_empresa"]'),
    ("SEGUIMIENTO_INTERNO_FECHA_VENCIDA", "Fecha acordada con el proveedor del seguimiento interno vencida sin cambio de estado (X días de tolerancia).", 0, 0, 30, "dias", "seguimiento", '["admin_un","admin_empresa"]'),
    ("REPROGRAMACION_SIN_FECHA", "Reprogramación pendiente de fecha por más de X días.", 7, 1, 60, "dias", "seguimiento", '["admin_un","admin_empresa","despachador"]'),
    ("REPROGRAMACION_FECHA_PROXIMA", "Fecha acordada de reprogramación a menos de X días sin confirmación del tercero.", 3, 1, 15, "dias", "seguimiento", '["admin_un","despachador"]'),
    ("REPROGRAMACION_SIN_CIERRE", "Reprogramación en ejecución sin cierre por más de X días.", 15, 1, 90, "dias", "seguimiento", '["admin_un","admin_empresa","despachador"]'),
    ("REPROGRAMACION_ESCALADA_EMPRESA", "Reprogramación con X fechas vencidas acumuladas: escala al Admin empresa.", 3, 1, 10, "cantidad", "seguimiento", '["admin_empresa"]'),
    ("ADMIN_UN_INCUMPLIMIENTO_CLASIFICACION", "Folio no crítico que el Admin UN no clasificó dentro del plazo (X horas de tolerancia adicional).", 0, 0, 72, "horas", "clasificacion", '["admin_empresa"]'),
    ("ADMIN_UN_MINUTA_SIN_RESPONDER", "Minuta vencida sin respuesta del Admin UN; informa al Admin empresa (X horas de tolerancia).", 0, 0, 72, "horas", "clasificacion", '["admin_empresa"]'),
    ("ADMIN_UN_BAJO_DESEMPENO", "La calificación del período del Admin UN cayó por debajo de X puntos.", 70, 0, 100, "porcentaje", "clasificacion", '["admin_empresa"]'),
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
    CREATE TYPE nivel_urgencia AS ENUM ('baja','media','alta','critica');
    CREATE TYPE tipo_hallazgo AS ENUM ('preventivo','correctivo');
    CREATE TYPE origen_hallazgo AS ENUM ('formulario_atencion','chat','manual');
    CREATE TYPE estado_respuesta_hallazgo AS ENUM ('pendiente','respondido');
    CREATE TYPE opcion_respuesta_minuta AS ENUM ('enterado','cotizacion','autorizar_reparar','por_presupuesto','seguimiento_interno','reprogramacion');
    CREATE TYPE origen_peticion AS ENUM ('chat','formulario');
    CREATE TYPE tipo_minuta AS ENUM ('un','global');
    CREATE TYPE estado_minuta AS ENUM ('borrador','pendiente_validacion','enviada','respondida','vencida');
    CREATE TYPE modo_minuta AS ENUM ('automatica','con_validacion');
    CREATE TYPE canal_notificacion AS ENUM ('push','email','whatsapp','sms','app');
    CREATE TYPE estado_notificacion AS ENUM ('pendiente','enviada','fallida','omitida');
    CREATE TYPE estado_cotizacion AS ENUM ('solicitada','en_preparacion','enviada','autorizada','rechazada','convertida');
    CREATE TYPE estado_presupuesto AS ENUM ('diferido','reactivado','descartado');
    CREATE TYPE estado_seguimiento_interno AS ENUM ('registrado','en_gestion','con_proveedor','resuelto','cancelado');
    CREATE TYPE estado_reprogramacion AS ENUM ('pendiente_fecha','fecha_asignada','tercero_confirmado','en_ejecucion','resuelto','cancelado');
    CREATE TYPE variante_coordinado AS ENUM ('A','B');
    CREATE TYPE tipo_periodo_presupuestal AS ENUM ('mensual','trimestral','semestral','anual','fechas');
    CREATE TYPE opcion_clasificacion AS ENUM ('presupuesto','reprogramacion','cotizacion','autorizado','seguimiento_interno');
    """)
    # El folio no crítico espera la clasificación del Admin UN como un trigger más de revisión (§6.10.5, decisión pendiente).
    ex("ALTER TYPE trigger_revision ADD VALUE IF NOT EXISTS 'pendiente_clasificacion';")
    # Ganchos para P10 (§6.10.5): el SLA arranca al autorizar y no cuenta contra el prestador si el cliente clasificó tarde.
    ex("""
    ALTER TABLE folio_sla ADD COLUMN autorizado_en TIMESTAMPTZ;
    ALTER TABLE folio_sla ADD COLUMN excluir_sla_por_cliente BOOLEAN NOT NULL DEFAULT false;
    """)

    # ------------------------------------------------------- hallazgos
    ex(f"""
    CREATE TABLE hallazgos ({base},
      folio_id UUID REFERENCES folios(id),
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      un_id UUID NOT NULL REFERENCES unidades_negocio(id),
      equipo_id UUID REFERENCES equipos(id),
      descripcion TEXT NOT NULL,
      nivel_urgencia nivel_urgencia NOT NULL DEFAULT 'media',
      foto_evidencia_id UUID REFERENCES formulario_evidencias(id) ON DELETE SET NULL,
      tipo tipo_hallazgo NOT NULL DEFAULT 'correctivo',
      origen origen_hallazgo NOT NULL DEFAULT 'manual',
      respuesta_id UUID REFERENCES formulario_respuestas(id) ON DELETE SET NULL,
      mensaje_id UUID,
      capturado_por UUID REFERENCES usuarios(id),
      timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
      estado_respuesta estado_respuesta_hallazgo NOT NULL DEFAULT 'pendiente',
      opcion_respuesta opcion_respuesta_minuta,
      respondido_por UUID REFERENCES usuarios(id),
      respondido_at TIMESTAMPTZ,
      modulo_destino modulo_destino,
      modulo_registro_id UUID
    );
    CREATE INDEX ix_hallazgos_un_fecha ON hallazgos (tenant_id, un_id, timestamp);
    CREATE INDEX ix_hallazgos_folio ON hallazgos (folio_id);
    CREATE TABLE peticiones_cliente ({base},
      folio_id UUID REFERENCES folios(id),
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      un_id UUID NOT NULL REFERENCES unidades_negocio(id),
      texto TEXT NOT NULL,
      origen origen_peticion NOT NULL DEFAULT 'chat',
      mensaje_id UUID,
      capturado_por UUID REFERENCES usuarios(id),
      timestamp TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE INDEX ix_peticiones_un_fecha ON peticiones_cliente (tenant_id, un_id, timestamp);
    """)

    # ---------------------------------------------------------- minuta
    ex(f"""
    CREATE TABLE minuta_configuracion ({base},
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      modo modo_minuta NOT NULL DEFAULT 'automatica',
      hora_envio TIME NOT NULL DEFAULT '19:00',
      ventana_validacion_min INTEGER NOT NULL DEFAULT 30,
      plazo_respuesta_horas INTEGER NOT NULL DEFAULT 24,
      dias_sin_respuesta_alerta INTEGER NOT NULL DEFAULT 2,
      dias_cotizacion_sin_respuesta INTEGER NOT NULL DEFAULT 7,
      dias_presupuesto_sin_revision INTEGER NOT NULL DEFAULT 30,
      dias_interno_sin_actualizar INTEGER NOT NULL DEFAULT 15,
      UNIQUE (prestador_id, tenant_id)
    );
    CREATE TABLE minutas ({base},
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      un_id UUID REFERENCES unidades_negocio(id),
      fecha DATE NOT NULL,
      tipo tipo_minuta NOT NULL,
      estado estado_minuta NOT NULL DEFAULT 'borrador',
      modo modo_minuta NOT NULL DEFAULT 'automatica',
      timestamp_generacion TIMESTAMPTZ NOT NULL DEFAULT now(),
      timestamp_envio TIMESTAMPTZ,
      validada_por UUID REFERENCES usuarios(id),
      notas_despachador TEXT NOT NULL DEFAULT '',
      enviada_sin_validacion BOOLEAN NOT NULL DEFAULT false,
      vence_respuesta_at TIMESTAMPTZ,
      respondida_at TIMESTAMPTZ,
      pdf_key VARCHAR(300),
      hash_pdf VARCHAR(64),
      urgente BOOLEAN NOT NULL DEFAULT false,
      UNIQUE (tenant_id, prestador_id, fecha, tipo, un_id)
    );
    CREATE INDEX ix_minutas_fecha ON minutas (tenant_id, fecha);
    CREATE TABLE minutas_secciones ({base},
      minuta_id UUID NOT NULL REFERENCES minutas(id) ON DELETE CASCADE,
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      seccion VARCHAR(40) NOT NULL,
      orden INTEGER NOT NULL DEFAULT 0,
      contenido_json JSONB NOT NULL DEFAULT '{{}}'::jsonb,
      editado_por UUID REFERENCES usuarios(id),
      UNIQUE (minuta_id, seccion)
    );
    CREATE TABLE minutas_respuestas ({base},
      minuta_id UUID NOT NULL REFERENCES minutas(id),
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      hallazgo_id UUID NOT NULL REFERENCES hallazgos(id),
      opcion_elegida opcion_respuesta_minuta NOT NULL,
      usuario_id UUID REFERENCES usuarios(id),
      timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
      notas TEXT NOT NULL DEFAULT '',
      canal canal_notificacion NOT NULL DEFAULT 'app',
      modulo_destino modulo_destino,
      modulo_registro_id UUID,
      folio_generado_id UUID REFERENCES folios(id)
    );
    CREATE TABLE minutas_destinatarios ({base},
      minuta_id UUID NOT NULL REFERENCES minutas(id) ON DELETE CASCADE,
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      usuario_id UUID NOT NULL REFERENCES usuarios(id),
      canal canal_notificacion NOT NULL,
      estado_entrega estado_notificacion NOT NULL DEFAULT 'pendiente',
      timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
      notificacion_id UUID
    );
    """)

    # --------------------------------------------------- notificaciones
    ex(f"""
    CREATE TABLE notificaciones ({base},
      usuario_id UUID NOT NULL REFERENCES usuarios(id),
      tenant_id UUID REFERENCES tenants(id),
      prestador_id UUID REFERENCES prestadores(id),
      evento VARCHAR(80) NOT NULL,
      canal canal_notificacion NOT NULL,
      asunto VARCHAR(300) NOT NULL,
      cuerpo_json JSONB NOT NULL DEFAULT '{{}}'::jsonb,
      estado estado_notificacion NOT NULL DEFAULT 'pendiente',
      proveedor_respuesta TEXT NOT NULL DEFAULT '',
      timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
      enviada_at TIMESTAMPTZ,
      leida_at TIMESTAMPTZ,
      url VARCHAR(300)
    );
    CREATE INDEX ix_notificaciones_usuario ON notificaciones (usuario_id, timestamp DESC);
    CREATE INDEX ix_notificaciones_pendientes ON notificaciones (estado) WHERE estado = 'pendiente';
    CREATE TABLE notificacion_preferencias ({base},
      usuario_id UUID NOT NULL REFERENCES usuarios(id),
      tenant_id UUID REFERENCES tenants(id),
      prestador_id UUID REFERENCES prestadores(id),
      evento VARCHAR(80) NOT NULL,
      canales_json JSONB NOT NULL DEFAULT '["app","push","email"]'::jsonb,
      UNIQUE (usuario_id, evento)
    );
    """)

    # ------------------------------------------------ módulos de seguimiento
    ex(f"""
    CREATE TABLE periodos_presupuestales ({base},
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      tipo tipo_periodo_presupuestal NOT NULL DEFAULT 'trimestral',
      fechas_json JSONB NOT NULL DEFAULT '[]'::jsonb,
      activo BOOLEAN NOT NULL DEFAULT true,
      ultimo_recordatorio DATE
    );
    CREATE TABLE cotizaciones ({base},
      hallazgo_id UUID REFERENCES hallazgos(id),
      folio_id UUID REFERENCES folios(id),
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      un_id UUID NOT NULL REFERENCES unidades_negocio(id),
      equipo_id UUID REFERENCES equipos(id),
      numero VARCHAR(20) NOT NULL,
      descripcion TEXT NOT NULL DEFAULT '',
      detalle_json JSONB NOT NULL DEFAULT '{{}}'::jsonb,
      monto NUMERIC(14,2),
      moneda VARCHAR(3) NOT NULL DEFAULT 'MXN',
      estado estado_cotizacion NOT NULL DEFAULT 'solicitada',
      origen VARCHAR(30) NOT NULL DEFAULT 'minuta',
      fecha_solicitud TIMESTAMPTZ NOT NULL DEFAULT now(),
      fecha_preparacion TIMESTAMPTZ,
      fecha_envio TIMESTAMPTZ,
      fecha_respuesta TIMESTAMPTZ,
      estado_desde TIMESTAMPTZ NOT NULL DEFAULT now(),
      solicitado_por UUID REFERENCES usuarios(id),
      preparado_por UUID REFERENCES usuarios(id),
      respondido_por UUID REFERENCES usuarios(id),
      notas_respuesta TEXT NOT NULL DEFAULT '',
      trabajo_especial_id UUID,
      pdf_key VARCHAR(300),
      hash_pdf VARCHAR(64),
      pasar_a_presupuesto_si_rechaza BOOLEAN NOT NULL DEFAULT false,
      UNIQUE (prestador_id, numero)
    );
    CREATE INDEX ix_cotizaciones_tenant_estado ON cotizaciones (tenant_id, estado);
    CREATE TABLE cotizacion_envios_externos ({base},
      cotizacion_id UUID NOT NULL REFERENCES cotizaciones(id),
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      destinatarios_json JSONB NOT NULL DEFAULT '[]'::jsonb,
      comentario TEXT NOT NULL DEFAULT '',
      asunto VARCHAR(300) NOT NULL DEFAULT '',
      enviado_por UUID REFERENCES usuarios(id),
      timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
      estado_entrega estado_notificacion NOT NULL DEFAULT 'pendiente'
    );
    CREATE TABLE hallazgos_presupuesto ({base},
      hallazgo_id UUID REFERENCES hallazgos(id),
      folio_id UUID REFERENCES folios(id),
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      un_id UUID NOT NULL REFERENCES unidades_negocio(id),
      equipo_id UUID REFERENCES equipos(id),
      descripcion TEXT NOT NULL DEFAULT '',
      periodo_presupuestal VARCHAR(40) NOT NULL DEFAULT '',
      estado estado_presupuesto NOT NULL DEFAULT 'diferido',
      origen VARCHAR(30) NOT NULL DEFAULT 'minuta',
      estado_desde TIMESTAMPTZ NOT NULL DEFAULT now(),
      ultima_revision TIMESTAMPTZ NOT NULL DEFAULT now(),
      razon_descarte TEXT,
      decidido_por UUID REFERENCES usuarios(id),
      decidido_at TIMESTAMPTZ,
      monto_estimado NUMERIC(14,2),
      reactivado_como VARCHAR(20),
      reactivado_registro_id UUID,
      historial_revisiones_json JSONB NOT NULL DEFAULT '[]'::jsonb
    );
    CREATE INDEX ix_presupuesto_tenant_estado ON hallazgos_presupuesto (tenant_id, estado);
    CREATE TABLE seguimientos_internos ({base},
      hallazgo_id UUID REFERENCES hallazgos(id),
      folio_id UUID REFERENCES folios(id),
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      un_id UUID NOT NULL REFERENCES unidades_negocio(id),
      equipo_id UUID REFERENCES equipos(id),
      descripcion TEXT NOT NULL DEFAULT '',
      responsable_un UUID REFERENCES usuarios(id),
      estado estado_seguimiento_interno NOT NULL DEFAULT 'registrado',
      origen VARCHAR(30) NOT NULL DEFAULT 'minuta',
      estado_desde TIMESTAMPTZ NOT NULL DEFAULT now(),
      proveedor VARCHAR(200),
      fecha_acordada DATE,
      referencia_tercero VARCHAR(120),
      ultima_actualizacion TIMESTAMPTZ NOT NULL DEFAULT now(),
      justificacion_cierre TEXT,
      cerrado_por UUID REFERENCES usuarios(id),
      cerrado_at TIMESTAMPTZ
    );
    CREATE INDEX ix_interno_tenant_estado ON seguimientos_internos (tenant_id, estado);
    CREATE TABLE reprogramaciones ({base},
      hallazgo_id UUID REFERENCES hallazgos(id),
      folio_id UUID REFERENCES folios(id),
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      un_id UUID NOT NULL REFERENCES unidades_negocio(id),
      equipo_id UUID REFERENCES equipos(id),
      descripcion TEXT NOT NULL DEFAULT '',
      estado estado_reprogramacion NOT NULL DEFAULT 'pendiente_fecha',
      origen VARCHAR(30) NOT NULL DEFAULT 'minuta',
      estado_desde TIMESTAMPTZ NOT NULL DEFAULT now(),
      motivo TEXT NOT NULL DEFAULT '',
      proveedor_tercero VARCHAR(200),
      fecha_acordada DATE,
      fecha_tentativa DATE,
      referencia_tercero VARCHAR(120),
      trabajo_coordinado BOOLEAN NOT NULL DEFAULT false,
      variante variante_coordinado,
      tercero_completo BOOLEAN NOT NULL DEFAULT false,
      folio_coordinado_id UUID REFERENCES folios(id),
      fechas_vencidas_count INTEGER NOT NULL DEFAULT 0,
      escalada_empresa BOOLEAN NOT NULL DEFAULT false,
      fecha_resolucion TIMESTAMPTZ,
      justificacion_cierre TEXT,
      cerrado_por UUID REFERENCES usuarios(id)
    );
    CREATE INDEX ix_reprogramaciones_tenant_estado ON reprogramaciones (tenant_id, estado);
    CREATE TABLE modulo_historial (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      modulo modulo_destino NOT NULL,
      registro_id UUID NOT NULL,
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      estado_anterior VARCHAR(40),
      estado_nuevo VARCHAR(40) NOT NULL,
      usuario_id UUID REFERENCES usuarios(id),
      actor_rol VARCHAR(40) NOT NULL DEFAULT 'sistema',
      timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
      notas TEXT NOT NULL DEFAULT '',
      datos_json JSONB NOT NULL DEFAULT '{{}}'::jsonb
    );
    CREATE INDEX ix_modulo_historial_registro ON modulo_historial (modulo, registro_id, timestamp);
    CREATE TRIGGER trg_modulo_historial_inmutable BEFORE UPDATE OR DELETE OR TRUNCATE ON modulo_historial
      FOR EACH STATEMENT EXECUTE FUNCTION acma_auditoria_inmutable();
    """)

    # ------------------------------------------------------ clasificación
    ex(f"""
    CREATE TABLE clasificacion_configuracion ({base},
      tenant_id UUID NOT NULL REFERENCES tenants(id) UNIQUE,
      severidades_no_criticas_json JSONB NOT NULL DEFAULT '["muy_baja","baja","media"]'::jsonb,
      plazo_horas INTEGER NOT NULL DEFAULT 24,
      umbral_calificacion INTEGER NOT NULL DEFAULT 70,
      admin_empresa_puede_clasificar BOOLEAN NOT NULL DEFAULT false,
      puntos_json JSONB NOT NULL DEFAULT '{{"base": 100, "clasificacion_tarde_por_hora": 2, "clasificacion_tarde_max": 20, "minuta_sin_respuesta": 10, "minuta_tardia": 5}}'::jsonb,
      activa BOOLEAN NOT NULL DEFAULT true
    );
    CREATE TABLE folio_clasificaciones ({base},
      folio_id UUID NOT NULL REFERENCES folios(id) UNIQUE,
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      un_id UUID NOT NULL REFERENCES unidades_negocio(id),
      admin_un_id UUID NOT NULL REFERENCES usuarios(id),
      opcion_clasificacion opcion_clasificacion NOT NULL,
      timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
      plazo_at TIMESTAMPTZ,
      dentro_de_plazo BOOLEAN NOT NULL DEFAULT true,
      horas_retraso NUMERIC(8,2) NOT NULL DEFAULT 0,
      fecha_tentativa DATE,
      modulo_destino modulo_destino,
      modulo_registro_id UUID,
      notas TEXT NOT NULL DEFAULT ''
    );
    CREATE TABLE admin_un_calificacion ({base},
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      usuario_id UUID NOT NULL REFERENCES usuarios(id),
      un_id UUID REFERENCES unidades_negocio(id),
      periodo VARCHAR(20) NOT NULL,
      puntos_total INTEGER NOT NULL DEFAULT 100,
      folios_clasificados_tiempo INTEGER NOT NULL DEFAULT 0,
      folios_tardios INTEGER NOT NULL DEFAULT 0,
      folios_sin_clasificar INTEGER NOT NULL DEFAULT 0,
      minutas_respondidas INTEGER NOT NULL DEFAULT 0,
      minutas_tardias INTEGER NOT NULL DEFAULT 0,
      calificacion_final NUMERIC(5,2) NOT NULL DEFAULT 100,
      eventos_json JSONB NOT NULL DEFAULT '[]'::jsonb,
      calculada_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      cerrada BOOLEAN NOT NULL DEFAULT false,
      UNIQUE (tenant_id, usuario_id, periodo)
    );
    """)

    versionar(*[t for t in TABLAS if t != "modulo_historial"])

    # §6.8.7: la decisión de rechazo sigue siendo inmutable salvo por `modulo_destino_id`, que P07 completa una sola vez (NULL → id).
    ex("""
    CREATE FUNCTION acma_decision_solo_modulo() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP = 'UPDATE' AND OLD.modulo_destino_id IS NULL AND NEW.modulo_destino_id IS NOT NULL
         AND (to_jsonb(NEW) - 'modulo_destino_id') = (to_jsonb(OLD) - 'modulo_destino_id') THEN
        RETURN NEW;
      END IF;
      RAISE EXCEPTION 'La tabla % es de solo inserción (append-only): % no permitido', TG_TABLE_NAME, TG_OP USING ERRCODE = 'insufficient_privilege';
    END $$;
    DROP TRIGGER IF EXISTS trg_aprobacion_decisiones_inmutable ON aprobacion_decisiones;
    CREATE TRIGGER trg_aprobacion_decisiones_inmutable BEFORE UPDATE OR DELETE ON aprobacion_decisiones
      FOR EACH ROW EXECUTE FUNCTION acma_decision_solo_modulo();
    CREATE POLICY aprobacion_decisiones_modulo_p07 ON aprobacion_decisiones FOR UPDATE
      USING (acma_es_plataforma() OR tenant_id = acma_ctx_tenant() OR prestador_id = acma_ctx_prestador())
      WITH CHECK (acma_es_plataforma() OR tenant_id = acma_ctx_tenant() OR prestador_id = acma_ctx_prestador());
    GRANT UPDATE (modulo_destino_id) ON aprobacion_decisiones TO acma_api;
    """)

    # ------------------------------------------------------------------ RLS
    for t in ("hallazgos", "peticiones_cliente", "minuta_configuracion", "minutas", "minutas_secciones", "minutas_respuestas", "minutas_destinatarios",
              "cotizaciones", "cotizacion_envios_externos", "hallazgos_presupuesto", "seguimientos_internos", "reprogramaciones", "folio_clasificaciones"):
        rls(t, *_politicas_folio(t))
    rls("modulo_historial",
        f"CREATE POLICY modulo_historial_lectura ON modulo_historial FOR SELECT USING ({LECTURA_FOLIO});",
        f"CREATE POLICY modulo_historial_insercion ON modulo_historial FOR INSERT WITH CHECK ({ESCRITURA_FOLIO});")
    for t in ("periodos_presupuestales", "clasificacion_configuracion", "admin_un_calificacion"):
        rls(t, *politicas_tenant(t))
    # Notificaciones: la bandeja filtra por usuario en el servicio; la RLS permite que quien genera el evento (tenant o prestador
    # del evento, o el sistema) las cree, las envíe y marque su estado en la misma transacción. Las preferencias las lee además
    # quien notifica (tenant o prestador vinculados) para resolver los canales.
    DUENIO = "acma_es_plataforma() OR usuario_id = acma_ctx_usuario() OR tenant_id = acma_ctx_tenant() OR prestador_id = acma_ctx_prestador()"
    for t in ("notificaciones", "notificacion_preferencias"):
        lectura = (DUENIO if t == "notificaciones" else
                   "acma_es_plataforma() OR usuario_id = acma_ctx_usuario() OR acma_tenant_visible(tenant_id) OR acma_prestador_visible(prestador_id)")
        escritura = DUENIO if t == "notificaciones" else "acma_es_plataforma() OR usuario_id = acma_ctx_usuario()"
        rls(t,
            f"CREATE POLICY {t}_lectura ON {t} FOR SELECT USING ({lectura});",
            f"CREATE POLICY {t}_insercion ON {t} FOR INSERT WITH CHECK ({DUENIO});",
            f"CREATE POLICY {t}_actualizacion ON {t} FOR UPDATE USING ({escritura}) WITH CHECK ({escritura});",
            f"CREATE POLICY {t}_borrado ON {t} FOR DELETE USING ({escritura});")
    ex(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {', '.join(TABLAS)} TO acma_api;")

    # ------------------------------------------------------------- semillas
    for clave, desc, d, mn, mx, tipo, modulo, dest in ALERTAS:
        ex(f"""
        INSERT INTO alertas_catalogo (clave, descripcion, umbral_default, umbral_min, umbral_max, tipo_umbral, modulo_origen, prompt_origen, destinatarios_default)
        VALUES ('{clave}', '{desc.replace("'", "''")}', {d}, {mn}, {mx}, '{tipo}', '{modulo}', 'P07', '{dest}'::jsonb);
        """)


def downgrade() -> None:
    ex("SELECT set_config('app.rol', 'sistema', true);")
    claves = ", ".join(f"'{a[0]}'" for a in ALERTAS)
    for t in ("alertas_historial", "alertas_configuracion", "alertas_supresiones"):
        ex(f"DELETE FROM {t} WHERE clave_alerta IN ({claves});")
    ex(f"DELETE FROM alertas_catalogo WHERE clave IN ({claves});")
    ex("ALTER TABLE folio_sla DROP COLUMN IF EXISTS autorizado_en; ALTER TABLE folio_sla DROP COLUMN IF EXISTS excluir_sla_por_cliente;")
    ex("""
    REVOKE UPDATE (modulo_destino_id) ON aprobacion_decisiones FROM acma_api;
    DROP POLICY IF EXISTS aprobacion_decisiones_modulo_p07 ON aprobacion_decisiones;
    DROP TRIGGER IF EXISTS trg_aprobacion_decisiones_inmutable ON aprobacion_decisiones;
    CREATE TRIGGER trg_aprobacion_decisiones_inmutable BEFORE UPDATE OR DELETE ON aprobacion_decisiones
      FOR EACH ROW EXECUTE FUNCTION acma_auditoria_inmutable();
    DROP FUNCTION IF EXISTS acma_decision_solo_modulo();
    """)
    for t in reversed(TABLAS):
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE;")
    for e in reversed(ENUMS):
        op.execute(f"DROP TYPE IF EXISTS {e};")
    # El valor 'pendiente_clasificacion' de trigger_revision no se puede quitar de un ENUM; se elimina al bajar 0004.
