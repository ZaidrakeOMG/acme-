"""0016 — Medidores de activos (§6.9.2), los cuatro triggers de plan que faltaban (§6.9.1), depreciación por unidades
de producción (§6.9.4, ACT-8.3) y la alerta MEDIDOR_PROXIMO_PM (§6.9.6). F2-04.

Lo que agrega:
- Las cuatro tablas literales de §6.9.2 (`tipos_medidor`, `equipo_medidores`, `medidor_lecturas`,
  `medidor_estimaciones`) más `medidor_cambios`, que es lo que permite que el acumulado no retroceda cuando el
  marcador se reinicia o se reemplaza el medidor.
- `eventos_trigger_catalogo`: catálogo **cerrado** de eventos que pueden disparar un plan. Se siembra aquí, como las
  razones de reasignación de P06, porque no es algo que el usuario invente: cada clave tiene código que la escucha.
- `llaves_api_tenant`: llave por cliente para que su SCADA o su ERP mande lecturas sin usuario humano. Solo sirve
  para registrar lecturas (`permisos_json`), se guarda **hasheada** y se revoca sin borrarla, para que la auditoría
  siga apuntando a algo.
- `plan_triggers.clave`: identidad estable de cada trigger dentro del plan. Antes una edición borraba y recreaba los
  triggers, así que sus id cambiaban; el trigger `combinado` apunta a otros triggers y no podía apoyarse en ellos.
- Columnas de uso en `plan_ejecuciones`, `preventivos_calendario` (origen `medidor` / `evento`) y
  `activo_depreciacion.equipo_medidor_id` (el medidor que mide el desgaste del activo).

**`medidor_lecturas` es append-only con una excepción**: la medición (valor, método, quién y cuándo) no se puede
cambiar nunca, pero las lecturas anómalas quedan `en_revision` y alguien las aprueba o las rechaza, así que el
trigger deja cambiar solo `estado`, `motivo`, `valor_acumulado`, `revisada_por` y `revisada_at`. Es el mismo patrón
de `acma_chat_mensaje_inmutable()` en P05, que deja cambiar solo `leido_por_json`.

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-11
"""
import json

from core.sql_migracion import ex, lit, politicas_tenant, rls, versionar

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None

TABLAS = ["tipos_medidor", "equipo_medidores", "medidor_lecturas", "medidor_estimaciones", "medidor_cambios",
          "llaves_api_tenant"]
ENUMS = ["categoria_medidor", "metodo_actualizacion_medidor", "estado_lectura_medidor", "tipo_cambio_medidor"]

base = """
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      version_hash VARCHAR(64)"""

# Los tipos de medidor son catálogo: el global (sin dueño) lo mantiene el Superadmin y lo ve cualquiera con contexto;
# el prestador y el cliente pueden tener los suyos. Igual que `familias_equipo` (P02) y las plantillas de F2-02.
LECTURA_TIPO = ("((prestador_id IS NULL AND tenant_id IS NULL AND acma_hay_contexto())"
                " OR acma_prestador_visible(prestador_id) OR acma_tenant_visible(tenant_id))")
ESCRITURA_TIPO = ("(acma_es_plataforma() OR (prestador_id IS NOT NULL AND prestador_id = acma_ctx_prestador())"
                  " OR (tenant_id IS NOT NULL AND tenant_id = acma_ctx_tenant()))")

# El medidor cuelga de un equipo, que es del cliente, pero lo lee y lo registra el prestador que lo atiende: la
# escritura va por `acma_tenant_visible` como en las tablas de activos de P09, no por el tenant del contexto.
ESCRITURA_TENANT_VISIBLE = "(acma_es_plataforma() OR acma_tenant_visible(tenant_id))"


def _politicas_tenant_visible(t: str) -> tuple[str, ...]:
    return (
        f"CREATE POLICY {t}_lectura ON {t} FOR SELECT USING (acma_tenant_visible(tenant_id));",
        f"CREATE POLICY {t}_insercion ON {t} FOR INSERT WITH CHECK ({ESCRITURA_TENANT_VISIBLE});",
        f"CREATE POLICY {t}_actualizacion ON {t} FOR UPDATE USING ({ESCRITURA_TENANT_VISIBLE}) WITH CHECK ({ESCRITURA_TENANT_VISIBLE});",
        f"CREATE POLICY {t}_borrado ON {t} FOR DELETE USING ({ESCRITURA_TENANT_VISIBLE});",
    )


def _append_only_tenant_visible(t: str) -> tuple[str, ...]:
    """Sin DELETE: lo que se puede cambiar lo limita el trigger de inmutabilidad, no la política."""
    return (
        f"CREATE POLICY {t}_lectura ON {t} FOR SELECT USING (acma_tenant_visible(tenant_id));",
        f"CREATE POLICY {t}_insercion ON {t} FOR INSERT WITH CHECK ({ESCRITURA_TENANT_VISIBLE});",
        f"CREATE POLICY {t}_actualizacion ON {t} FOR UPDATE USING ({ESCRITURA_TENANT_VISIBLE}) WITH CHECK ({ESCRITURA_TENANT_VISIBLE});",
    )


# §6.9.1 «Por evento»: catálogo cerrado. Cada clave tiene un gancho en el código que la escucha, así que no se
# inventan desde la interfaz; lo configurable son sus parámetros.
EVENTOS = [
    ("falla_correctiva_grave",
     "Se cerró un folio correctivo del equipo con severidad alta o crítica.",
     {"severidades": {"tipo": "lista_severidades", "default": ["alta", "critica"],
                      "etiqueta": "Severidades que cuentan como falla grave"}}),
    ("fallas_repetidas",
     "El equipo acumuló N folios correctivos cerrados en los últimos X días.",
     {"cantidad": {"tipo": "entero", "min": 2, "max": 20, "default": 3, "etiqueta": "Cuántas fallas"},
      "dias": {"tipo": "entero", "min": 1, "max": 365, "default": 30, "etiqueta": "En cuántos días"}}),
    ("equipo_instalado",
     "Se dio de alta el equipo por instalación de activo (§6.10.7).",
     {"dias_despues": {"tipo": "entero", "min": 0, "max": 365, "default": 30,
                       "etiqueta": "Días después de la instalación"}}),
    ("reemplazo_componente",
     "Se consumió en un folio del equipo una refacción de la categoría configurada.",
     {"categorias": {"tipo": "lista_texto", "default": [], "etiqueta": "Categorías de refacción que disparan el plan"}}),
    ("cambio_medidor",
     "Se reemplazó el medidor del equipo (no un reinicio del marcador).",
     {"tipo_medidor_id": {"tipo": "uuid_tipo_medidor", "default": None,
                          "etiqueta": "Tipo de medidor (vacío = cualquiera)"}}),
]

ALERTAS_NUEVAS = [
    # clave, descripcion, umbral, tipo, min, max, destinatarios
    ("MEDIDOR_LECTURA_ANOMALA",
     "Una lectura de medidor quedó en revisión: retrocedió o saltó más de lo esperado. Hasta que alguien la apruebe "
     "no dispara planes de mantenimiento.",
     0, "cantidad", 0, 100, ["despachador", "admin_prestador"]),
    ("MEDIDOR_SIN_LECTURA",
     "Un medidor que no se estima llevaba más de X días sin lectura, así que los planes por uso de ese equipo están "
     "ciegos.",
     30, "dias", 1, 365, ["despachador", "admin_prestador"]),
]


def upgrade() -> None:
    ex("SELECT set_config('app.rol', 'sistema', true);")

    ex("""
    CREATE TYPE categoria_medidor AS ENUM ('horas','ciclos','distancia','energia','unidades','personalizado');
    CREATE TYPE metodo_actualizacion_medidor AS ENUM ('tecnico','operador','importacion','estimado');
    CREATE TYPE estado_lectura_medidor AS ENUM ('valida','rechazada','en_revision');
    CREATE TYPE tipo_cambio_medidor AS ENUM ('reinicio','reemplazo_medidor');
    """)

    # ------------------------------------------------------------------ catálogo de tipos de medidor (§6.9.2)
    ex(f"""
    CREATE TABLE tipos_medidor ({base},
      prestador_id UUID REFERENCES prestadores(id),
      tenant_id UUID REFERENCES tenants(id),
      nombre VARCHAR(120) NOT NULL,
      unidad VARCHAR(30) NOT NULL,
      categoria categoria_medidor NOT NULL DEFAULT 'personalizado',
      descripcion TEXT NOT NULL DEFAULT '',
      permite_estimacion BOOLEAN NOT NULL DEFAULT true,
      decimales SMALLINT NOT NULL DEFAULT 0,
      requiere_foto BOOLEAN NOT NULL DEFAULT false,
      -- Detección de saltos: N veces el incremento diario esperado por los días transcurridos (default 3).
      factor_salto_maximo NUMERIC(6,2) NOT NULL DEFAULT 3,
      activo BOOLEAN NOT NULL DEFAULT true,
      CONSTRAINT ck_tipos_medidor_duenio CHECK (prestador_id IS NULL OR tenant_id IS NULL),
      CONSTRAINT ck_tipos_medidor_decimales CHECK (decimales BETWEEN 0 AND 4),
      CONSTRAINT ck_tipos_medidor_salto CHECK (factor_salto_maximo >= 1)
    );
    CREATE UNIQUE INDEX uq_tipos_medidor ON tipos_medidor (
      COALESCE(prestador_id, '00000000-0000-0000-0000-000000000000'::uuid),
      COALESCE(tenant_id, '00000000-0000-0000-0000-000000000000'::uuid), lower(nombre));
    """)
    rls("tipos_medidor",
        f"CREATE POLICY tipos_medidor_lectura ON tipos_medidor FOR SELECT USING ({LECTURA_TIPO});",
        f"CREATE POLICY tipos_medidor_escritura ON tipos_medidor FOR ALL USING ({ESCRITURA_TIPO})"
        f" WITH CHECK ({ESCRITURA_TIPO});")

    # ------------------------------------------------------------------ medidores por equipo
    # `acumulado_offset` y `ciclo_inicio` son la memoria de los reinicios: el acumulado de una lectura es
    # `acumulado_offset + (valor - ciclo_inicio)`, así que un marcador que vuelve a 0 no hace retroceder el total.
    ex(f"""
    CREATE TABLE equipo_medidores ({base},
      equipo_id UUID NOT NULL REFERENCES equipos(id),
      tipo_medidor_id UUID NOT NULL REFERENCES tipos_medidor(id),
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      valor_actual NUMERIC(16,2) NOT NULL DEFAULT 0,
      valor_acumulado NUMERIC(16,2) NOT NULL DEFAULT 0,
      valor_ultimo_pm NUMERIC(16,2) NOT NULL DEFAULT 0,
      acumulado_offset NUMERIC(16,2) NOT NULL DEFAULT 0,
      ciclo_inicio NUMERIC(16,2) NOT NULL DEFAULT 0,
      fecha_ultima_lectura TIMESTAMPTZ,
      metodo_actualizacion metodo_actualizacion_medidor NOT NULL DEFAULT 'tecnico',
      valor_maximo NUMERIC(16,2),
      numero_serie_medidor VARCHAR(80),
      instalado_en DATE,
      activo BOOLEAN NOT NULL DEFAULT true,
      CONSTRAINT ck_equipo_medidores_maximo CHECK (valor_maximo IS NULL OR valor_maximo > 0)
    );
    CREATE UNIQUE INDEX uq_equipo_medidores ON equipo_medidores (equipo_id, tipo_medidor_id) WHERE activo;
    CREATE INDEX ix_equipo_medidores_equipo ON equipo_medidores (equipo_id);
    CREATE INDEX ix_equipo_medidores_sin_lectura ON equipo_medidores (tenant_id, fecha_ultima_lectura)
      WHERE activo AND metodo_actualizacion <> 'estimado';
    """)
    rls("equipo_medidores", *_politicas_tenant_visible("equipo_medidores"))

    # ------------------------------------------------------------------ lecturas (append-only con revisión)
    ex(f"""
    CREATE TABLE medidor_lecturas ({base},
      equipo_medidor_id UUID NOT NULL REFERENCES equipo_medidores(id),
      equipo_id UUID NOT NULL REFERENCES equipos(id),
      tipo_medidor_id UUID NOT NULL REFERENCES tipos_medidor(id),
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      prestador_id UUID REFERENCES prestadores(id),
      valor NUMERIC(16,2) NOT NULL,
      valor_acumulado NUMERIC(16,2) NOT NULL,
      metodo metodo_actualizacion_medidor NOT NULL,
      registrado_por UUID REFERENCES usuarios(id),
      folio_id UUID REFERENCES folios(id),
      respuesta_id UUID REFERENCES formulario_respuestas(id),
      evidencia_id UUID REFERENCES formulario_evidencias(id),
      llave_api_id UUID,
      timestamp_dispositivo TIMESTAMPTZ,
      timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
      estado estado_lectura_medidor NOT NULL DEFAULT 'valida',
      motivo TEXT NOT NULL DEFAULT '',
      revisada_por UUID REFERENCES usuarios(id),
      revisada_at TIMESTAMPTZ,
      CONSTRAINT ck_medidor_lecturas_valor CHECK (valor >= 0),
      -- Una lectura rechazada o en revisión tiene que decir por qué: es lo que lee quien la resuelve.
      CONSTRAINT ck_medidor_lecturas_motivo CHECK (
        estado = 'valida' OR length(btrim(motivo)) > 0)
    );
    CREATE INDEX ix_medidor_lecturas_medidor ON medidor_lecturas (equipo_medidor_id, timestamp DESC);
    CREATE INDEX ix_medidor_lecturas_equipo ON medidor_lecturas (equipo_id, timestamp DESC);
    CREATE INDEX ix_medidor_lecturas_revision ON medidor_lecturas (tenant_id, timestamp DESC)
      WHERE estado = 'en_revision';
    CREATE INDEX ix_medidor_lecturas_folio ON medidor_lecturas (folio_id) WHERE folio_id IS NOT NULL;
    -- Idempotencia de la importación y de la cola sin señal: la misma medición del mismo instante no entra dos veces.
    CREATE UNIQUE INDEX uq_medidor_lecturas_instante ON medidor_lecturas (equipo_medidor_id, timestamp_dispositivo, valor)
      WHERE timestamp_dispositivo IS NOT NULL;
    """)
    # La medición es inmutable; la revisión no. Sin esta excepción no habría forma de aprobar una lectura anómala.
    ex("""
    CREATE FUNCTION acma_medidor_lectura_inmutable() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP IN ('DELETE', 'TRUNCATE') THEN
        RAISE EXCEPTION 'Las lecturas de medidor no se borran (§6.9.2: el historial es la evidencia del uso)'
          USING ERRCODE = 'insufficient_privilege';
      END IF;
      IF (to_jsonb(NEW) - 'estado' - 'motivo' - 'valor_acumulado' - 'revisada_por' - 'revisada_at'
          - 'updated_at' - 'version_hash')
         <> (to_jsonb(OLD) - 'estado' - 'motivo' - 'valor_acumulado' - 'revisada_por' - 'revisada_at'
             - 'updated_at' - 'version_hash') THEN
        RAISE EXCEPTION 'Una lectura registrada no se modifica: solo se aprueba o se rechaza'
          USING ERRCODE = 'insufficient_privilege';
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER trg_medidor_lecturas_inmutable BEFORE UPDATE OR DELETE ON medidor_lecturas
      FOR EACH ROW EXECUTE FUNCTION acma_medidor_lectura_inmutable();
    CREATE TRIGGER trg_medidor_lecturas_sin_truncate BEFORE TRUNCATE ON medidor_lecturas
      FOR EACH STATEMENT EXECUTE FUNCTION acma_auditoria_inmutable();
    """)
    rls("medidor_lecturas", *_append_only_tenant_visible("medidor_lecturas"))

    # ------------------------------------------------------------------ estimación (§6.9.2 «Cálculo estimado»)
    ex(f"""
    CREATE TABLE medidor_estimaciones ({base},
      equipo_medidor_id UUID NOT NULL REFERENCES equipo_medidores(id),
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      incremento_por_dia NUMERIC(14,4) NOT NULL DEFAULT 0,
      incremento_real_promedio NUMERIC(14,4),
      horario_operacion_json JSONB NOT NULL DEFAULT '{{}}'::jsonb,
      activa BOOLEAN NOT NULL DEFAULT true,
      desde DATE NOT NULL DEFAULT CURRENT_DATE,
      ultima_estimacion_at TIMESTAMPTZ,
      CONSTRAINT ck_medidor_estimaciones_incremento CHECK (incremento_por_dia >= 0)
    );
    CREATE UNIQUE INDEX uq_medidor_estimaciones ON medidor_estimaciones (equipo_medidor_id);
    """)
    rls("medidor_estimaciones", *_politicas_tenant_visible("medidor_estimaciones"))

    # ------------------------------------------------------------------ reinicios y reemplazos de medidor
    ex(f"""
    CREATE TABLE medidor_cambios ({base},
      equipo_medidor_id UUID NOT NULL REFERENCES equipo_medidores(id),
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      tipo tipo_cambio_medidor NOT NULL,
      valor_anterior NUMERIC(16,2) NOT NULL DEFAULT 0,
      valor_nuevo NUMERIC(16,2) NOT NULL DEFAULT 0,
      acumulado_al_cambio NUMERIC(16,2) NOT NULL DEFAULT 0,
      numero_serie_anterior VARCHAR(80),
      numero_serie_nuevo VARCHAR(80),
      motivo TEXT NOT NULL,
      registrado_por UUID REFERENCES usuarios(id),
      timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
      CONSTRAINT ck_medidor_cambios_motivo CHECK (length(btrim(motivo)) > 0)
    );
    CREATE INDEX ix_medidor_cambios_medidor ON medidor_cambios (equipo_medidor_id, timestamp DESC);
    """)
    rls("medidor_cambios", *_politicas_tenant_visible("medidor_cambios"))

    # ------------------------------------------------------------------ llaves de API para lecturas
    # La llave se guarda hasheada (SHA-256 con la pimienta de P11a) y solo se muestra completa al crearla. `prefijo`
    # es lo único legible después: sirve para que el Admin empresa sepa cuál revocar.
    ex(f"""
    CREATE TABLE llaves_api_tenant ({base},
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      nombre VARCHAR(120) NOT NULL,
      prefijo VARCHAR(16) NOT NULL,
      llave_hash VARCHAR(64) NOT NULL,
      permisos_json JSONB NOT NULL DEFAULT '["medidores.lecturas"]'::jsonb,
      activa BOOLEAN NOT NULL DEFAULT true,
      creada_por UUID REFERENCES usuarios(id),
      revocada_at TIMESTAMPTZ,
      revocada_por UUID REFERENCES usuarios(id),
      ultimo_uso_at TIMESTAMPTZ,
      usos INTEGER NOT NULL DEFAULT 0,
      CONSTRAINT ck_llaves_api_revocacion CHECK (activa OR revocada_at IS NOT NULL)
    );
    CREATE UNIQUE INDEX uq_llaves_api_hash ON llaves_api_tenant (llave_hash);
    CREATE INDEX ix_llaves_api_tenant ON llaves_api_tenant (tenant_id) WHERE activa;
    """)
    rls("llaves_api_tenant", *politicas_tenant("llaves_api_tenant"))

    # ------------------------------------------------------------------ catálogo cerrado de eventos
    # Sin tenant ni prestador: es de la plataforma, como `alertas_catalogo`. Solo lectura para la app.
    ex(f"""
    CREATE TABLE eventos_trigger_catalogo ({base},
      clave VARCHAR(60) NOT NULL UNIQUE,
      descripcion TEXT NOT NULL,
      parametros_schema_json JSONB NOT NULL DEFAULT '{{}}'::jsonb,
      activo BOOLEAN NOT NULL DEFAULT true
    );
    """)
    for clave, descripcion, esquema in EVENTOS:
        ex(f"""
        INSERT INTO eventos_trigger_catalogo (clave, descripcion, parametros_schema_json)
        VALUES ({lit(clave)}, {lit(descripcion)}, {lit(json.dumps(esquema))}::jsonb)
        ON CONFLICT (clave) DO NOTHING;
        """)
    ex("CREATE TRIGGER trg_eventos_trigger_catalogo_version BEFORE INSERT OR UPDATE ON eventos_trigger_catalogo"
       " FOR EACH ROW EXECUTE FUNCTION acma_version();")
    ex("GRANT SELECT ON eventos_trigger_catalogo TO acma_api;")

    versionar(*TABLAS)
    for t in TABLAS:
        ex(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {t} TO acma_api;")
    # Append-only de verdad: el rol de la app no borra lecturas aunque la política lo dejara pasar.
    ex("REVOKE DELETE ON medidor_lecturas FROM acma_api;")

    # ------------------------------------------------------------------ triggers de plan: identidad estable
    ex("""
    ALTER TABLE plan_triggers ADD COLUMN clave VARCHAR(40) NOT NULL DEFAULT '';
    UPDATE plan_triggers t SET clave = 't' || x.n
      FROM (SELECT id, row_number() OVER (PARTITION BY plan_id ORDER BY created_at, id) AS n
              FROM plan_triggers) x
     WHERE x.id = t.id;
    CREATE UNIQUE INDEX uq_plan_triggers_clave ON plan_triggers (plan_id, clave) WHERE clave <> '';
    """)

    # ------------------------------------------------------------------ de qué trigger salió cada ejecución
    ex("""
    ALTER TABLE plan_ejecuciones
      ADD COLUMN plan_trigger_id UUID REFERENCES plan_triggers(id) ON DELETE SET NULL,
      ADD COLUMN valor_medidor NUMERIC(16,2);
    ALTER TABLE preventivos_calendario
      ADD COLUMN plan_trigger_id UUID REFERENCES plan_triggers(id) ON DELETE SET NULL,
      ADD COLUMN valor_medidor NUMERIC(16,2);
    ALTER TYPE origen_preventivo ADD VALUE IF NOT EXISTS 'medidor';
    ALTER TYPE origen_preventivo ADD VALUE IF NOT EXISTS 'evento';
    """)

    # ------------------------------------------------------------------ depreciación por unidades (§6.9.4, ACT-8.3)
    ex("""
    ALTER TABLE activo_depreciacion
      ADD COLUMN equipo_medidor_id UUID REFERENCES equipo_medidores(id),
      ADD COLUMN unidades_al_inicio NUMERIC(16,2);
    ALTER TABLE activo_depreciacion_historial
      ADD COLUMN unidades_periodo NUMERIC(16,2),
      ADD COLUMN unidades_acumuladas NUMERIC(16,2);
    """)

    # ------------------------------------------------------------------ alertas (§6.9.6)
    # MEDIDOR_PROXIMO_PM existe desde P01 esperando este bloque: ya tiene de dónde salir.
    ex("UPDATE alertas_catalogo SET fase = 1, activa_por_defecto = true, prompt_origen = 'F2-04' "
       "WHERE clave = 'MEDIDOR_PROXIMO_PM';")
    ex("UPDATE alertas_configuracion SET activa = true WHERE clave_alerta = 'MEDIDOR_PROXIMO_PM';")
    for clave, desc, umbral, tipo, mn, mx, dest in ALERTAS_NUEVAS:
        ex(f"""
        INSERT INTO alertas_catalogo (clave, descripcion, umbral_default, umbral_min, umbral_max, tipo_umbral,
                                      modulo_origen, prompt_origen, destinatarios_default, canales_default, fase)
        VALUES ({lit(clave)}, {lit(desc)}, {umbral}, {mn}, {mx}, {lit(tipo)}, 'medidores', 'F2-04',
                {lit(json.dumps(dest))}::jsonb, '["app", "push", "email"]'::jsonb, 1)
        ON CONFLICT (clave) DO NOTHING;
        """)


def downgrade() -> None:
    ex("SELECT set_config('app.rol', 'sistema', true);")
    for clave, *_ in ALERTAS_NUEVAS:
        ex(f"DELETE FROM alertas_historial WHERE clave_alerta = {lit(clave)};")
        ex(f"DELETE FROM alertas_configuracion WHERE clave_alerta = {lit(clave)};")
        ex(f"DELETE FROM alertas_catalogo WHERE clave = {lit(clave)};")
    ex("DELETE FROM alertas_historial WHERE clave_alerta = 'MEDIDOR_PROXIMO_PM';")
    ex("UPDATE alertas_catalogo SET fase = 2, activa_por_defecto = false, prompt_origen = 'P01' "
       "WHERE clave = 'MEDIDOR_PROXIMO_PM';")
    ex("UPDATE alertas_configuracion SET activa = false WHERE clave_alerta = 'MEDIDOR_PROXIMO_PM';")

    ex("""
    ALTER TABLE activo_depreciacion_historial
      DROP COLUMN IF EXISTS unidades_periodo,
      DROP COLUMN IF EXISTS unidades_acumuladas;
    ALTER TABLE activo_depreciacion
      DROP COLUMN IF EXISTS equipo_medidor_id,
      DROP COLUMN IF EXISTS unidades_al_inicio;
    """)

    # Un ENUM no suelta valores: se recrea sin `medidor` ni `evento` (las filas que los usaran vuelven a `plan`).
    ex("""
    UPDATE preventivos_calendario SET origen = 'plan' WHERE origen::text IN ('medidor','evento');
    ALTER TABLE preventivos_calendario
      DROP COLUMN IF EXISTS plan_trigger_id,
      DROP COLUMN IF EXISTS valor_medidor;
    ALTER TABLE plan_ejecuciones
      DROP COLUMN IF EXISTS plan_trigger_id,
      DROP COLUMN IF EXISTS valor_medidor;
    ALTER TABLE preventivos_calendario ALTER COLUMN origen DROP DEFAULT;
    ALTER TYPE origen_preventivo RENAME TO origen_preventivo_viejo;
    CREATE TYPE origen_preventivo AS ENUM ('manual','plan');
    ALTER TABLE preventivos_calendario ALTER COLUMN origen TYPE origen_preventivo
      USING origen::text::origen_preventivo;
    ALTER TABLE preventivos_calendario ALTER COLUMN origen SET DEFAULT 'manual';
    DROP TYPE origen_preventivo_viejo;
    """)

    ex("""
    DROP INDEX IF EXISTS uq_plan_triggers_clave;
    ALTER TABLE plan_triggers DROP COLUMN IF EXISTS clave;
    """)

    ex("DROP TABLE IF EXISTS eventos_trigger_catalogo CASCADE;")
    for t in reversed(TABLAS):
        ex(f"DROP TABLE IF EXISTS {t} CASCADE;")
    ex("DROP FUNCTION IF EXISTS acma_medidor_lectura_inmutable();")
    for e in reversed(ENUMS):
        ex(f"DROP TYPE IF EXISTS {e};")
