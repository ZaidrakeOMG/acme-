"""0014 — Notificaciones por WhatsApp y SMS (§6.1, §7.5, §6.9.6). F2-02.

Teléfono móvil verificado y consentimiento por canal en `usuarios` (el número se guarda cifrado con el mecanismo de
P11a y en bitácoras solo aparece su hash o su máscara), catálogo de plantillas aprobables por Meta, bitácora de
envíos con estado de entrega y costo estimado, configuración por prestador/tenant y mensajes entrantes («BAJA»,
«ALTA» y botones). Activa las dos alertas de mensajería.

El contenido de las plantillas NO se escribe aquí: vive en `services/mensajeria/plantillas.py` y los seeds lo
sincronizan con `sembrar_plantillas()`, para no tener el mismo texto en dos lugares.

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-09
"""
import json

from core.sql_migracion import ex, lit, rls, versionar

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

TABLAS = ["mensajeria_plantillas", "mensajeria_configuracion", "mensajeria_envios", "mensajeria_respuestas"]

base = """
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      version_hash VARCHAR(64)"""

# Las plantillas base son de la plataforma (prestador_id NULL) y cada prestador puede tener la suya, igual que el
# catálogo de cursos de F2-01: el nombre de la plantilla en Meta y su estado de aprobación son de cada cuenta.
LECTURA_PLANTILLA = "((prestador_id IS NULL AND acma_hay_contexto()) OR acma_prestador_visible(prestador_id))"
ESCRITURA_PLANTILLA = "(acma_es_plataforma() OR (prestador_id IS NOT NULL AND prestador_id = acma_ctx_prestador()))"

# Igual que `notificaciones` (P07): quien genera el evento —el tenant o el prestador del evento, o el sistema—
# registra el envío y actualiza su estado en la misma transacción; el destinatario ve el suyo.
DUENIO_ENVIO = ("acma_es_plataforma() OR usuario_id = acma_ctx_usuario() OR tenant_id = acma_ctx_tenant()"
                " OR prestador_id = acma_ctx_prestador()")

ALERTAS_NUEVAS = [
    # clave, descripcion, umbral, tipo, min, max, destinatarios
    ("MENSAJERIA_CONSUMO_ALTO",
     "El consumo de mensajes de WhatsApp o SMS del mes llegó al porcentaje configurado del tope.",
     80, "porcentaje", 50, 100, ["admin_prestador", "mesa_control"]),
    ("MENSAJERIA_PLANTILLA_RECHAZADA",
     "El proveedor rechazó o pausó una plantilla de WhatsApp: el canal cae al siguiente hasta corregirla.",
     0, "cantidad", 0, 10, ["admin_prestador"]),
]


def upgrade() -> None:
    ex("SELECT set_config('app.rol', 'sistema', true);")

    # ------------------------------------------------------------------ teléfono y consentimiento del usuario
    # `telefono_movil_e164` guarda el número **cifrado** (envelope AES-256-GCM de P11a, igual que `mfa_secreto_cifrado`):
    # el formato E.164 se valida en el servicio antes de cifrar. El hash sirve para resolver un mensaje entrante del
    # proveedor sin descifrar a nadie, y la máscara (+52 871 ••• ••34) es lo único que se muestra en bitácoras.
    ex("""
    ALTER TABLE usuarios
      ADD COLUMN telefono_movil_e164 TEXT,
      ADD COLUMN telefono_movil_hash VARCHAR(64),
      ADD COLUMN telefono_movil_mascara VARCHAR(40),
      ADD COLUMN telefono_verificado_at TIMESTAMPTZ,
      ADD COLUMN telefono_codigo_hash VARCHAR(64),
      ADD COLUMN telefono_codigo_expira_at TIMESTAMPTZ,
      ADD COLUMN telefono_codigo_intentos SMALLINT NOT NULL DEFAULT 0,
      ADD COLUMN whatsapp_consentimiento_at TIMESTAMPTZ,
      ADD COLUMN whatsapp_baja_at TIMESTAMPTZ,
      ADD COLUMN sms_consentimiento_at TIMESTAMPTZ,
      ADD COLUMN sms_baja_at TIMESTAMPTZ;
    CREATE INDEX ix_usuarios_telefono_hash ON usuarios (telefono_movil_hash) WHERE telefono_movil_hash IS NOT NULL;
    GRANT UPDATE (telefono_movil_e164, telefono_movil_hash, telefono_movil_mascara, telefono_verificado_at,
                  telefono_codigo_hash, telefono_codigo_expira_at, telefono_codigo_intentos,
                  whatsapp_consentimiento_at, whatsapp_baja_at, sms_consentimiento_at, sms_baja_at) ON usuarios TO acma_api;
    """)

    ex("""
    CREATE TYPE canal_mensajeria AS ENUM ('whatsapp','sms');
    CREATE TYPE categoria_plantilla AS ENUM ('utility','authentication','marketing');
    CREATE TYPE estado_aprobacion_plantilla AS ENUM ('borrador','enviada','aprobada','rechazada','pausada');
    CREATE TYPE proveedor_mensajeria AS ENUM ('stub','meta_cloud','twilio');
    CREATE TYPE estado_envio_mensajeria AS ENUM
      ('en_cola','enviado','entregado','leido','fallido','rechazado_por_proveedor');
    """)

    # ------------------------------------------------------------------ plantillas
    ex(f"""
    CREATE TABLE mensajeria_plantillas ({base},
      prestador_id UUID REFERENCES prestadores(id),
      clave VARCHAR(60) NOT NULL,
      canal canal_mensajeria NOT NULL,
      idioma VARCHAR(10) NOT NULL DEFAULT 'es_MX',
      nombre_proveedor VARCHAR(120) NOT NULL DEFAULT '',
      categoria categoria_plantilla NOT NULL DEFAULT 'utility',
      encabezado VARCHAR(120) NOT NULL DEFAULT '',
      cuerpo TEXT NOT NULL,
      pie VARCHAR(120) NOT NULL DEFAULT '',
      botones_json JSONB NOT NULL DEFAULT '[]'::jsonb,
      variables_json JSONB NOT NULL DEFAULT '[]'::jsonb,
      ejemplo_json JSONB NOT NULL DEFAULT '{{}}'::jsonb,
      estado_aprobacion estado_aprobacion_plantilla NOT NULL DEFAULT 'borrador',
      motivo_rechazo TEXT NOT NULL DEFAULT '',
      version SMALLINT NOT NULL DEFAULT 1,
      activa BOOLEAN NOT NULL DEFAULT true,
      -- Una plantilla rechazada o pausada tiene que decir por qué (§6.9.6: el admin necesita saber qué corregir).
      CONSTRAINT ck_mensajeria_plantillas_motivo CHECK (
        estado_aprobacion NOT IN ('rechazada','pausada') OR length(btrim(motivo_rechazo)) > 0),
      CONSTRAINT ck_mensajeria_plantillas_cuerpo CHECK (length(btrim(cuerpo)) > 0)
    );
    CREATE UNIQUE INDEX uq_mensajeria_plantillas ON mensajeria_plantillas
      (COALESCE(prestador_id, '00000000-0000-0000-0000-000000000000'::uuid), clave, canal, idioma);
    CREATE INDEX ix_mensajeria_plantillas_clave ON mensajeria_plantillas (clave, canal) WHERE activa;
    """)
    rls("mensajeria_plantillas",
        f"CREATE POLICY mensajeria_plantillas_lectura ON mensajeria_plantillas FOR SELECT USING ({LECTURA_PLANTILLA});",
        f"CREATE POLICY mensajeria_plantillas_escritura ON mensajeria_plantillas FOR ALL USING ({ESCRITURA_PLANTILLA})"
        f" WITH CHECK ({ESCRITURA_PLANTILLA});")

    # ------------------------------------------------------------------ configuración
    # Una fila por prestador (tenant_id NULL) y, si el prestador lo quiere afinar, una por tenant que atiende.
    # `eventos_*_json` vacío significa «todos los eventos del catálogo»; con lista, solo esos.
    ex(f"""
    CREATE TABLE mensajeria_configuracion ({base},
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      tenant_id UUID REFERENCES tenants(id),
      whatsapp_activo BOOLEAN NOT NULL DEFAULT false,
      sms_activo BOOLEAN NOT NULL DEFAULT false,
      eventos_whatsapp_json JSONB NOT NULL DEFAULT '[]'::jsonb,
      eventos_sms_json JSONB NOT NULL DEFAULT '[]'::jsonb,
      horario_silencio_json JSONB NOT NULL
        DEFAULT '{{"inicio": "22:00", "fin": "07:00", "zona": "America/Mexico_City"}}'::jsonb,
      tope_mensual_mensajes INTEGER NOT NULL DEFAULT 1000,
      alerta_consumo_pct SMALLINT NOT NULL DEFAULT 80,
      remitente_whatsapp VARCHAR(60) NOT NULL DEFAULT '',
      remitente_sms VARCHAR(30) NOT NULL DEFAULT '',
      tarifa_whatsapp NUMERIC(10,4) NOT NULL DEFAULT 0.4000,
      tarifa_sms NUMERIC(10,4) NOT NULL DEFAULT 0.6000,
      moneda CHAR(3) NOT NULL DEFAULT 'MXN',
      ventana_respuesta_horas SMALLINT NOT NULL DEFAULT 24,
      CONSTRAINT ck_mensajeria_config_pct CHECK (alerta_consumo_pct BETWEEN 50 AND 100),
      CONSTRAINT ck_mensajeria_config_tope CHECK (tope_mensual_mensajes >= 0),
      CONSTRAINT ck_mensajeria_config_ventana CHECK (ventana_respuesta_horas BETWEEN 1 AND 24)
    );
    CREATE UNIQUE INDEX uq_mensajeria_configuracion ON mensajeria_configuracion
      (prestador_id, COALESCE(tenant_id, '00000000-0000-0000-0000-000000000000'::uuid));
    """)
    rls("mensajeria_configuracion",
        "CREATE POLICY mensajeria_configuracion_lectura ON mensajeria_configuracion FOR SELECT USING "
        "(acma_es_plataforma() OR prestador_id = acma_ctx_prestador() OR tenant_id = acma_ctx_tenant());",
        "CREATE POLICY mensajeria_configuracion_escritura ON mensajeria_configuracion FOR ALL USING "
        "(acma_es_plataforma() OR prestador_id = acma_ctx_prestador() OR tenant_id = acma_ctx_tenant()) WITH CHECK "
        "(acma_es_plataforma() OR prestador_id = acma_ctx_prestador() OR tenant_id = acma_ctx_tenant());")

    # ------------------------------------------------------------------ envíos
    # `telefono_destino_hash` y `telefono_mascara`: el número en claro nunca se guarda aquí (§6.9.5).
    # `codigo_enlace` es el enlace corto propio de ACMA (`/l/{codigo}`), sin servicio externo: en un SMS de 160
    # caracteres el enlace largo no cabe, y el clic queda registrado en `abierto_at`.
    ex(f"""
    CREATE TABLE mensajeria_envios ({base},
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      tenant_id UUID REFERENCES tenants(id),
      usuario_id UUID REFERENCES usuarios(id),
      notificacion_id UUID REFERENCES notificaciones(id) ON DELETE SET NULL,
      evento VARCHAR(80) NOT NULL DEFAULT '',
      canal canal_mensajeria NOT NULL,
      proveedor proveedor_mensajeria NOT NULL DEFAULT 'stub',
      telefono_destino_hash VARCHAR(64) NOT NULL,
      telefono_mascara VARCHAR(40) NOT NULL DEFAULT '',
      plantilla_id UUID REFERENCES mensajeria_plantillas(id),
      plantilla_clave VARCHAR(60) NOT NULL DEFAULT '',
      variables_json JSONB NOT NULL DEFAULT '[]'::jsonb,
      cuerpo_renderizado TEXT NOT NULL DEFAULT '',
      mensaje_id_proveedor VARCHAR(120),
      estado estado_envio_mensajeria NOT NULL DEFAULT 'en_cola',
      codigo_error VARCHAR(60) NOT NULL DEFAULT '',
      detalle_error TEXT NOT NULL DEFAULT '',
      costo_estimado NUMERIC(10,4) NOT NULL DEFAULT 0,
      moneda CHAR(3) NOT NULL DEFAULT 'MXN',
      segmentos_sms SMALLINT NOT NULL DEFAULT 0,
      intentos SMALLINT NOT NULL DEFAULT 0,
      proximo_intento_at TIMESTAMPTZ,
      critico BOOLEAN NOT NULL DEFAULT false,
      codigo_enlace VARCHAR(16),
      enlace_destino VARCHAR(400) NOT NULL DEFAULT '',
      abierto_at TIMESTAMPTZ,
      vista_previa_key VARCHAR(300),
      enviado_at TIMESTAMPTZ,
      entregado_at TIMESTAMPTZ,
      leido_at TIMESTAMPTZ,
      CONSTRAINT ck_mensajeria_envios_intentos CHECK (intentos >= 0 AND intentos <= 20)
    );
    CREATE UNIQUE INDEX uq_mensajeria_envios_codigo ON mensajeria_envios (codigo_enlace)
      WHERE codigo_enlace IS NOT NULL;
    CREATE UNIQUE INDEX uq_mensajeria_envios_proveedor ON mensajeria_envios (proveedor, mensaje_id_proveedor)
      WHERE mensaje_id_proveedor IS NOT NULL;
    CREATE INDEX ix_mensajeria_envios_consumo ON mensajeria_envios (prestador_id, canal, created_at);
    CREATE INDEX ix_mensajeria_envios_tenant ON mensajeria_envios (tenant_id, created_at DESC);
    CREATE INDEX ix_mensajeria_envios_usuario ON mensajeria_envios (usuario_id, created_at DESC);
    CREATE INDEX ix_mensajeria_envios_notificacion ON mensajeria_envios (notificacion_id);
    CREATE INDEX ix_mensajeria_envios_pendientes ON mensajeria_envios (proximo_intento_at)
      WHERE estado = 'en_cola';
    """)
    rls("mensajeria_envios",
        f"CREATE POLICY mensajeria_envios_lectura ON mensajeria_envios FOR SELECT USING ({DUENIO_ENVIO});",
        f"CREATE POLICY mensajeria_envios_insercion ON mensajeria_envios FOR INSERT WITH CHECK ({DUENIO_ENVIO});",
        f"CREATE POLICY mensajeria_envios_actualizacion ON mensajeria_envios FOR UPDATE USING ({DUENIO_ENVIO})"
        f" WITH CHECK ({DUENIO_ENVIO});")

    # ------------------------------------------------------------------ mensajes entrantes
    # Un mensaje entrante puede llegar de un número que no está en la plataforma: `usuario_id`, `prestador_id` y
    # `tenant_id` quedan en NULL y solo la plataforma lo ve (no se le puede atribuir dueño sin inventarlo).
    ex(f"""
    CREATE TABLE mensajeria_respuestas ({base},
      prestador_id UUID REFERENCES prestadores(id),
      tenant_id UUID REFERENCES tenants(id),
      usuario_id UUID REFERENCES usuarios(id),
      canal canal_mensajeria NOT NULL,
      proveedor proveedor_mensajeria NOT NULL DEFAULT 'stub',
      telefono_hash VARCHAR(64) NOT NULL,
      telefono_mascara VARCHAR(40) NOT NULL DEFAULT '',
      texto TEXT NOT NULL DEFAULT '',
      boton VARCHAR(60) NOT NULL DEFAULT '',
      envio_id UUID REFERENCES mensajeria_envios(id) ON DELETE SET NULL,
      mensaje_id_proveedor VARCHAR(120),
      accion_ejecutada VARCHAR(60) NOT NULL DEFAULT '',
      timestamp TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE INDEX ix_mensajeria_respuestas_usuario ON mensajeria_respuestas (usuario_id, timestamp DESC);
    CREATE INDEX ix_mensajeria_respuestas_telefono ON mensajeria_respuestas (telefono_hash, timestamp DESC);
    """)
    rls("mensajeria_respuestas",
        "CREATE POLICY mensajeria_respuestas_lectura ON mensajeria_respuestas FOR SELECT USING "
        "(acma_es_plataforma() OR usuario_id = acma_ctx_usuario() OR prestador_id = acma_ctx_prestador() "
        "OR tenant_id = acma_ctx_tenant());",
        "CREATE POLICY mensajeria_respuestas_escritura ON mensajeria_respuestas FOR ALL USING "
        "(acma_es_plataforma() OR prestador_id = acma_ctx_prestador() OR tenant_id = acma_ctx_tenant()) WITH CHECK "
        "(acma_es_plataforma() OR prestador_id = acma_ctx_prestador() OR tenant_id = acma_ctx_tenant());")

    versionar(*TABLAS)
    for t in TABLAS:
        ex(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {t} TO acma_api;")

    # ------------------------------------------------------------------ alertas
    for clave, desc, umbral, tipo, mn, mx, dest in ALERTAS_NUEVAS:
        ex(f"""
        INSERT INTO alertas_catalogo (clave, descripcion, umbral_default, umbral_min, umbral_max, tipo_umbral,
                                      modulo_origen, prompt_origen, destinatarios_default, canales_default, fase)
        VALUES ({lit(clave)}, {lit(desc)}, {umbral}, {mn}, {mx}, {lit(tipo)}, 'notificaciones', 'F2-02',
                {lit(json.dumps(dest))}::jsonb, '["app", "push", "email"]'::jsonb, 1)
        ON CONFLICT (clave) DO NOTHING;
        """)


def downgrade() -> None:
    ex("SELECT set_config('app.rol', 'sistema', true);")
    for clave, *_ in ALERTAS_NUEVAS:
        ex(f"DELETE FROM alertas_historial WHERE clave_alerta = {lit(clave)};")
        ex(f"DELETE FROM alertas_configuracion WHERE clave_alerta = {lit(clave)};")
        ex(f"DELETE FROM alertas_catalogo WHERE clave = {lit(clave)};")
    for t in reversed(TABLAS):
        ex(f"DROP TABLE IF EXISTS {t} CASCADE;")
    ex("""
    DROP TYPE IF EXISTS estado_envio_mensajeria;
    DROP TYPE IF EXISTS proveedor_mensajeria;
    DROP TYPE IF EXISTS estado_aprobacion_plantilla;
    DROP TYPE IF EXISTS categoria_plantilla;
    DROP TYPE IF EXISTS canal_mensajeria;
    """)
    ex("""
    DROP INDEX IF EXISTS ix_usuarios_telefono_hash;
    ALTER TABLE usuarios
      DROP COLUMN IF EXISTS telefono_movil_e164,
      DROP COLUMN IF EXISTS telefono_movil_hash,
      DROP COLUMN IF EXISTS telefono_movil_mascara,
      DROP COLUMN IF EXISTS telefono_verificado_at,
      DROP COLUMN IF EXISTS telefono_codigo_hash,
      DROP COLUMN IF EXISTS telefono_codigo_expira_at,
      DROP COLUMN IF EXISTS telefono_codigo_intentos,
      DROP COLUMN IF EXISTS whatsapp_consentimiento_at,
      DROP COLUMN IF EXISTS whatsapp_baja_at,
      DROP COLUMN IF EXISTS sms_consentimiento_at,
      DROP COLUMN IF EXISTS sms_baja_at;
    """)
