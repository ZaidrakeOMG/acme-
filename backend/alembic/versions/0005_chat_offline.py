"""0005 — Apps de campo, modo offline y chat (§5.1, §5.2, §6.2, §6.8.1): chat archivado por folio (5 tablas),
sincronización de dispositivos (dispositivos, conflictos, bitácora idempotente de mutaciones) y suscripciones push.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-28
"""
from alembic import op

from core.sql_migracion import ex, rls, versionar

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

TABLAS = [
    "chats", "chat_participantes", "chat_mensajes", "chat_archivos", "chat_eventos_sistema",
    "sincronizacion_dispositivos", "sincronizacion_conflictos", "sincronizacion_mutaciones", "suscripciones_push",
]

base = """
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      version_hash VARCHAR(64)"""

LECTURA_FOLIO = "(acma_tenant_visible(tenant_id) AND acma_prestador_visible(prestador_id))"
ESCRITURA_FOLIO = "(acma_es_plataforma() OR tenant_id = acma_ctx_tenant() OR prestador_id = acma_ctx_prestador())"
# Mensajes y archivos: además del tenant/prestador, solo participantes activos del chat (§6.8.1).
PARTICIPANTE = ("EXISTS (SELECT 1 FROM chat_participantes p WHERE p.chat_id = {col} AND p.usuario_id = acma_ctx_usuario() AND p.activo)")


def upgrade() -> None:
    ex("SELECT set_config('app.rol', 'sistema', true);")
    ex("""
    CREATE TYPE canal_chat AS ENUM ('campo','operativo','interno');
    CREATE TYPE estado_chat AS ENUM ('activo','archivado');
    CREATE TYPE tipo_mensaje_chat AS ENUM ('texto','imagen','audio','sistema');
    CREATE TYPE regla_conflicto AS ENUM ('server_wins','client_wins','merge_alerta');
    CREATE TYPE resultado_mutacion AS ENUM ('aplicada','duplicada','rechazada');
    ALTER TABLE folio_politicas_tenant ADD COLUMN plazo_encuesta_horas INTEGER NOT NULL DEFAULT 48;
    """)

    # ------------------------------------------------------------------ chat
    ex(f"""
    CREATE TABLE chats ({base},
      folio_id UUID NOT NULL REFERENCES folios(id),
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      canal canal_chat NOT NULL,
      estado estado_chat NOT NULL DEFAULT 'activo',
      UNIQUE (folio_id, canal)
    );
    CREATE TABLE chat_participantes ({base},
      chat_id UUID NOT NULL REFERENCES chats(id),
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      usuario_id UUID NOT NULL REFERENCES usuarios(id),
      rol rol_usuario NOT NULL,
      agregado_por UUID REFERENCES usuarios(id),
      fecha_ingreso TIMESTAMPTZ NOT NULL DEFAULT now(),
      activo BOOLEAN NOT NULL DEFAULT true,
      UNIQUE (chat_id, usuario_id)
    );
    CREATE TABLE chat_mensajes ({base},
      chat_id UUID NOT NULL REFERENCES chats(id),
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      usuario_id UUID REFERENCES usuarios(id),
      contenido_texto TEXT NOT NULL DEFAULT '',
      tipo tipo_mensaje_chat NOT NULL DEFAULT 'texto',
      timestamp_servidor TIMESTAMPTZ NOT NULL DEFAULT now(),
      timestamp_dispositivo TIMESTAMPTZ,
      leido_por_json JSONB NOT NULL DEFAULT '{{}}'::jsonb,
      datos_json JSONB NOT NULL DEFAULT '{{}}'::jsonb,
      id_cliente UUID NOT NULL DEFAULT gen_random_uuid(),
      oculto BOOLEAN NOT NULL DEFAULT false,
      UNIQUE (chat_id, id_cliente)
    );
    CREATE INDEX ix_chat_mensajes_chat ON chat_mensajes (chat_id, timestamp_servidor);
    CREATE TABLE chat_archivos ({base},
      mensaje_id UUID NOT NULL REFERENCES chat_mensajes(id),
      chat_id UUID NOT NULL REFERENCES chats(id),
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      archivo_key VARCHAR(300) NOT NULL,
      nombre_original VARCHAR(255) NOT NULL DEFAULT '',
      tipo_mime VARCHAR(120) NOT NULL,
      tamano_bytes INTEGER NOT NULL,
      thumbnail_key VARCHAR(300)
    );
    CREATE TABLE chat_eventos_sistema ({base},
      chat_id UUID NOT NULL REFERENCES chats(id),
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      tipo_evento VARCHAR(60) NOT NULL,
      datos_json JSONB NOT NULL DEFAULT '{{}}'::jsonb,
      timestamp TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE INDEX ix_chat_eventos_chat ON chat_eventos_sistema (chat_id, timestamp);

    -- §6.8.1: en un folio cerrado los mensajes son inmutables (solo cambia leido_por_json) y no se borran.
    CREATE FUNCTION acma_chat_mensaje_inmutable() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE v_estado estado_folio;
    BEGIN
      SELECT f.estado INTO v_estado FROM chats c JOIN folios f ON f.id = c.folio_id WHERE c.id = OLD.chat_id;
      IF v_estado = 'cerrado' THEN
        IF TG_OP = 'DELETE' THEN
          RAISE EXCEPTION 'Los mensajes de un folio cerrado son inmutables' USING ERRCODE = 'insufficient_privilege';
        END IF;
        IF (to_jsonb(NEW) - 'leido_por_json' - 'updated_at' - 'version_hash') <> (to_jsonb(OLD) - 'leido_por_json' - 'updated_at' - 'version_hash') THEN
          RAISE EXCEPTION 'Los mensajes de un folio cerrado son inmutables (solo se marcan como leídos)' USING ERRCODE = 'insufficient_privilege';
        END IF;
      END IF;
      RETURN COALESCE(NEW, OLD);
    END $$;
    CREATE TRIGGER trg_chat_mensajes_inmutable BEFORE UPDATE OR DELETE ON chat_mensajes
      FOR EACH ROW EXECUTE FUNCTION acma_chat_mensaje_inmutable();
    """)

    # --------------------------------------------------------- sincronización
    ex(f"""
    CREATE TABLE sincronizacion_dispositivos ({base},
      usuario_id UUID NOT NULL REFERENCES usuarios(id),
      tenant_id UUID REFERENCES tenants(id),
      prestador_id UUID REFERENCES prestadores(id),
      dispositivo_id VARCHAR(120) NOT NULL,
      ultimo_sync_at TIMESTAMPTZ,
      version_app VARCHAR(40),
      plataforma VARCHAR(60),
      UNIQUE (usuario_id, dispositivo_id)
    );
    CREATE TABLE sincronizacion_conflictos ({base},
      usuario_id UUID NOT NULL REFERENCES usuarios(id),
      tenant_id UUID REFERENCES tenants(id),
      prestador_id UUID REFERENCES prestadores(id),
      dispositivo_id VARCHAR(120),
      entidad VARCHAR(60) NOT NULL,
      entidad_id UUID,
      regla_aplicada regla_conflicto NOT NULL,
      datos_cliente_json JSONB NOT NULL DEFAULT '{{}}'::jsonb,
      datos_servidor_json JSONB NOT NULL DEFAULT '{{}}'::jsonb,
      resuelto_at TIMESTAMPTZ
    );
    -- Bitácora idempotente de la cola offline: una operación por (usuario, id_cliente).
    CREATE TABLE sincronizacion_mutaciones ({base},
      usuario_id UUID NOT NULL REFERENCES usuarios(id),
      tenant_id UUID REFERENCES tenants(id),
      prestador_id UUID REFERENCES prestadores(id),
      dispositivo_id VARCHAR(120),
      id_cliente UUID NOT NULL,
      tipo VARCHAR(40) NOT NULL,
      resultado resultado_mutacion NOT NULL,
      entidad_id UUID,
      codigo VARCHAR(60),
      mensaje TEXT NOT NULL DEFAULT '',
      timestamp_dispositivo TIMESTAMPTZ,
      UNIQUE (usuario_id, id_cliente)
    );
    CREATE TABLE suscripciones_push ({base},
      usuario_id UUID NOT NULL REFERENCES usuarios(id),
      tenant_id UUID REFERENCES tenants(id),
      prestador_id UUID REFERENCES prestadores(id),
      dispositivo_id VARCHAR(120),
      endpoint TEXT NOT NULL,
      claves_json JSONB NOT NULL DEFAULT '{{}}'::jsonb,
      user_agent VARCHAR(300),
      activa BOOLEAN NOT NULL DEFAULT true,
      ultimo_envio_at TIMESTAMPTZ,
      UNIQUE (usuario_id, endpoint)
    );
    """)

    versionar(*TABLAS)

    # ------------------------------------------------------------------ RLS
    for t in ("chats", "chat_participantes", "chat_eventos_sistema"):
        rls(t, f"CREATE POLICY {t}_lectura ON {t} FOR SELECT USING ({LECTURA_FOLIO});",
            f"CREATE POLICY {t}_escritura ON {t} FOR ALL USING ({ESCRITURA_FOLIO}) WITH CHECK ({ESCRITURA_FOLIO});")
    # Las políticas de escritura van por comando (no FOR ALL): una política FOR ALL también concede SELECT y anularía la
    # restricción de lectura a participantes.
    for t, col in (("chat_mensajes", "chat_mensajes.chat_id"), ("chat_archivos", "chat_archivos.chat_id")):
        rls(t, f"CREATE POLICY {t}_lectura ON {t} FOR SELECT USING ({LECTURA_FOLIO} AND (acma_es_plataforma() OR {PARTICIPANTE.format(col=col)}));",
            f"CREATE POLICY {t}_insercion ON {t} FOR INSERT WITH CHECK ({ESCRITURA_FOLIO});",
            f"CREATE POLICY {t}_actualizacion ON {t} FOR UPDATE USING ({ESCRITURA_FOLIO}) WITH CHECK ({ESCRITURA_FOLIO});",
            f"CREATE POLICY {t}_borrado ON {t} FOR DELETE USING ({ESCRITURA_FOLIO});")
    # Misma corrección en `folios` (P04): la política FOR ALL del prestador dejaba leer al técnico folios ajenos por RLS.
    ex(f"""
    DROP POLICY IF EXISTS folios_escritura ON folios;
    CREATE POLICY folios_insercion ON folios FOR INSERT WITH CHECK ({ESCRITURA_FOLIO});
    CREATE POLICY folios_actualizacion ON folios FOR UPDATE USING ({ESCRITURA_FOLIO}) WITH CHECK ({ESCRITURA_FOLIO});
    CREATE POLICY folios_borrado ON folios FOR DELETE USING ({ESCRITURA_FOLIO});
    """)
    # Datos del propio usuario (dispositivos, conflictos, mutaciones, suscripciones); plataforma ve todo.
    for t in ("sincronizacion_dispositivos", "sincronizacion_conflictos", "sincronizacion_mutaciones", "suscripciones_push"):
        rls(t, f"CREATE POLICY {t}_propio ON {t} FOR ALL USING (acma_es_plataforma() OR usuario_id = acma_ctx_usuario())"
               f" WITH CHECK (acma_es_plataforma() OR usuario_id = acma_ctx_usuario());")
    # Los administradores del tenant/prestador consultan conflictos y suscripciones de su ámbito (lectura).
    ex("CREATE POLICY sincronizacion_conflictos_ambito ON sincronizacion_conflictos FOR SELECT USING "
       "((tenant_id IS NOT NULL AND tenant_id = acma_ctx_tenant()) OR (prestador_id IS NOT NULL AND prestador_id = acma_ctx_prestador()));")
    ex("CREATE POLICY suscripciones_push_ambito ON suscripciones_push FOR SELECT USING "
       "((tenant_id IS NOT NULL AND acma_tenant_visible(tenant_id)) OR (prestador_id IS NOT NULL AND acma_prestador_visible(prestador_id)));")

    ex(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {', '.join(TABLAS)} TO acma_api;")


def downgrade() -> None:
    ex("SELECT set_config('app.rol', 'sistema', true);")
    ex(f"""
    DROP POLICY IF EXISTS folios_insercion ON folios; DROP POLICY IF EXISTS folios_actualizacion ON folios; DROP POLICY IF EXISTS folios_borrado ON folios;
    DROP POLICY IF EXISTS folios_escritura ON folios;
    CREATE POLICY folios_escritura ON folios FOR ALL USING ({ESCRITURA_FOLIO}) WITH CHECK ({ESCRITURA_FOLIO});
    """)
    for t in reversed(TABLAS):
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE;")
    ex("""
    DROP FUNCTION IF EXISTS acma_chat_mensaje_inmutable() CASCADE;
    ALTER TABLE folio_politicas_tenant DROP COLUMN IF EXISTS plazo_encuesta_horas;
    DROP TYPE IF EXISTS resultado_mutacion;
    DROP TYPE IF EXISTS regla_conflicto;
    DROP TYPE IF EXISTS tipo_mensaje_chat;
    DROP TYPE IF EXISTS estado_chat;
    DROP TYPE IF EXISTS canal_chat;
    """)
