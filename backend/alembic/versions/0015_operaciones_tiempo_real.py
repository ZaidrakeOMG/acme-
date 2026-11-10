"""0015 — Pantalla de operaciones en tiempo real (§6.8.4, §6.8.6, §6.9.6). F2-03.

Jornada del técnico con sus pausas, historial de posiciones GPS **particionado por día** (90 días de retención con
DETACH + DROP, el mismo mecanismo de la auditoría de P11a), el estatus operativo del técnico en su ficha y el
seguimiento de las alertas de operación (push al técnico, su respuesta y la escalación).

Activa `TECNICO_TIEMPO_MUERTO` y `TECNICO_SIN_SENAL`. `TECNICO_DESVIO_RUTA` **sigue en Fase 2**: necesita la ruta
planeada que calcula el bloque de optimización de rutas.

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-10
"""
from core.sql_migracion import ex, lit, rls, versionar

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None

# `tecnico_posiciones` no lleva las columnas de versión de §6.2 capa 1 ni su trigger: es un flujo de solo inserción,
# como la auditoría de P01, y 100 posiciones por minuto no deben pagar un trigger de hash en cada fila.
TABLAS = ["jornadas_tecnico", "jornada_pausas", "alertas_operacion_seguimiento"]

base = """
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      version_hash VARCHAR(64)"""

# Las posiciones son del prestador del técnico y nadie más: el cliente no ve dónde anda nadie (§6.9.5). El propio
# técnico ve las suyas.
LECTURA_OPERACION = ("acma_es_plataforma() OR prestador_id = acma_ctx_prestador()"
                     " OR EXISTS (SELECT 1 FROM tecnicos t WHERE t.id = %s AND t.usuario_id = acma_ctx_usuario())")
ESCRITURA_PRESTADOR = "(acma_es_plataforma() OR prestador_id = acma_ctx_prestador())"


def upgrade() -> None:
    ex("SELECT set_config('app.rol', 'sistema', true);")

    ex("""
    CREATE TYPE estatus_operativo_tecnico AS ENUM
      ('fuera_de_jornada','en_ruta','en_servicio','pausa','sin_senal');
    CREATE TYPE estado_jornada AS ENUM ('activa','pausa','cerrada');
    CREATE TYPE cerrada_por_jornada AS ENUM ('tecnico','sistema','despachador');
    CREATE TYPE motivo_pausa_jornada AS ENUM ('comida','tramite','otro');
    CREATE TYPE respuesta_alerta_tecnico AS ENUM ('estoy_bien','necesito_apoyo');
    """)

    # ------------------------------------------------------------------ ficha del técnico (§6.8.4)
    ex("""
    ALTER TABLE tecnicos
      ADD COLUMN ultima_posicion GEOGRAPHY(Point, 4326),
      ADD COLUMN ultima_posicion_at TIMESTAMPTZ,
      ADD COLUMN ultima_precision_m NUMERIC(7,1),
      ADD COLUMN ultima_bateria_pct SMALLINT,
      ADD COLUMN estatus_operativo estatus_operativo_tecnico NOT NULL DEFAULT 'fuera_de_jornada',
      -- §6.8.4 pide ordenar por «tiempo en el estatus actual»: hace falta saber desde cuándo lleva ese estatus.
      ADD COLUMN estatus_operativo_desde TIMESTAMPTZ,
      ADD CONSTRAINT ck_tecnicos_bateria CHECK (ultima_bateria_pct IS NULL OR ultima_bateria_pct BETWEEN 0 AND 100);
    CREATE INDEX ix_tecnicos_ultima_posicion ON tecnicos USING GIST (ultima_posicion);
    CREATE INDEX ix_tecnicos_estatus ON tecnicos (prestador_id, estatus_operativo);
    GRANT UPDATE (ultima_posicion, ultima_posicion_at, ultima_precision_m, ultima_bateria_pct, estatus_operativo,
                  estatus_operativo_desde) ON tecnicos TO acma_api;
    """)

    # ------------------------------------------------------------------ jornada y pausas
    ex(f"""
    CREATE TABLE jornadas_tecnico ({base},
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      tecnico_id UUID NOT NULL REFERENCES tecnicos(id),
      inicio TIMESTAMPTZ NOT NULL DEFAULT now(),
      fin TIMESTAMPTZ,
      estado estado_jornada NOT NULL DEFAULT 'activa',
      dispositivo_id VARCHAR(80) NOT NULL DEFAULT '',
      cerrada_por cerrada_por_jornada,
      aviso_aceptado_at TIMESTAMPTZ,
      posiciones INTEGER NOT NULL DEFAULT 0,
      CONSTRAINT ck_jornadas_fin CHECK (fin IS NULL OR fin >= inicio),
      CONSTRAINT ck_jornadas_cerrada CHECK (estado <> 'cerrada' OR (fin IS NOT NULL AND cerrada_por IS NOT NULL))
    );
    -- Una sola jornada abierta por técnico: el índice lo impide, no solo el servicio.
    CREATE UNIQUE INDEX uq_jornadas_tecnico_abierta ON jornadas_tecnico (tecnico_id)
      WHERE estado <> 'cerrada';
    CREATE INDEX ix_jornadas_tecnico_prestador ON jornadas_tecnico (prestador_id, inicio DESC);
    """)
    rls("jornadas_tecnico",
        f"CREATE POLICY jornadas_tecnico_lectura ON jornadas_tecnico FOR SELECT USING "
        f"({LECTURA_OPERACION % 'jornadas_tecnico.tecnico_id'});",
        f"CREATE POLICY jornadas_tecnico_escritura ON jornadas_tecnico FOR ALL USING {ESCRITURA_PRESTADOR}"
        f" WITH CHECK {ESCRITURA_PRESTADOR};")

    ex(f"""
    CREATE TABLE jornada_pausas ({base},
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      jornada_id UUID NOT NULL REFERENCES jornadas_tecnico(id) ON DELETE CASCADE,
      inicio TIMESTAMPTZ NOT NULL DEFAULT now(),
      fin TIMESTAMPTZ,
      motivo motivo_pausa_jornada NOT NULL DEFAULT 'otro',
      nota VARCHAR(200) NOT NULL DEFAULT '',
      CONSTRAINT ck_jornada_pausas_fin CHECK (fin IS NULL OR fin >= inicio)
    );
    CREATE UNIQUE INDEX uq_jornada_pausas_abierta ON jornada_pausas (jornada_id) WHERE fin IS NULL;
    CREATE INDEX ix_jornada_pausas_jornada ON jornada_pausas (jornada_id, inicio DESC);
    """)
    rls("jornada_pausas",
        "CREATE POLICY jornada_pausas_lectura ON jornada_pausas FOR SELECT USING "
        "(acma_es_plataforma() OR prestador_id = acma_ctx_prestador() OR EXISTS "
        "(SELECT 1 FROM jornadas_tecnico j JOIN tecnicos t ON t.id = j.tecnico_id "
        "WHERE j.id = jornada_pausas.jornada_id AND t.usuario_id = acma_ctx_usuario()));",
        f"CREATE POLICY jornada_pausas_escritura ON jornada_pausas FOR ALL USING {ESCRITURA_PRESTADOR}"
        f" WITH CHECK {ESCRITURA_PRESTADOR};")

    # ------------------------------------------------------------------ posiciones (particionadas por día)
    ex("""
    CREATE TABLE tecnico_posiciones (
      id UUID NOT NULL DEFAULT gen_random_uuid(),
      prestador_id UUID NOT NULL,
      tecnico_id UUID NOT NULL,
      jornada_id UUID NOT NULL,
      posicion GEOGRAPHY(Point, 4326) NOT NULL,
      precision_m NUMERIC(7,1),
      velocidad_mps NUMERIC(6,2),
      rumbo NUMERIC(5,1),
      bateria_pct SMALLINT,
      capturada_at TIMESTAMPTZ NOT NULL,
      recibida_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      tardia BOOLEAN NOT NULL DEFAULT false,
      PRIMARY KEY (id, capturada_at),
      CONSTRAINT ck_tecnico_posiciones_precision CHECK (precision_m IS NULL OR precision_m >= 0),
      CONSTRAINT ck_tecnico_posiciones_bateria CHECK (bateria_pct IS NULL OR bateria_pct BETWEEN 0 AND 100),
      CONSTRAINT ck_tecnico_posiciones_rumbo CHECK (rumbo IS NULL OR rumbo BETWEEN 0 AND 360)
    ) PARTITION BY RANGE (capturada_at);
    CREATE TABLE tecnico_posiciones_default PARTITION OF tecnico_posiciones DEFAULT;
    CREATE INDEX ix_tecnico_posiciones_tecnico ON tecnico_posiciones (tecnico_id, capturada_at DESC);
    CREATE INDEX ix_tecnico_posiciones_jornada ON tecnico_posiciones (jornada_id, capturada_at);
    CREATE INDEX ix_tecnico_posiciones_espacial ON tecnico_posiciones USING GIST (posicion);
    """)
    rls("tecnico_posiciones",
        "CREATE POLICY tecnico_posiciones_lectura ON tecnico_posiciones FOR SELECT USING "
        "(acma_es_plataforma() OR prestador_id = acma_ctx_prestador() OR EXISTS "
        "(SELECT 1 FROM tecnicos t WHERE t.id = tecnico_posiciones.tecnico_id "
        "AND t.usuario_id = acma_ctx_usuario()));",
        f"CREATE POLICY tecnico_posiciones_insercion ON tecnico_posiciones FOR INSERT WITH CHECK "
        f"{ESCRITURA_PRESTADOR};")

    # Particiones diarias: la tarea del beat las crea con días de adelanto (como las de auditoría, pero por día).
    ex("""
    CREATE FUNCTION acma_crear_particiones_posiciones(dias_adelante INTEGER DEFAULT 7) RETURNS INTEGER
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
    DECLARE
      inicio DATE;
      nombre TEXT;
      creadas INTEGER := 0;
    BEGIN
      FOR i IN -1..dias_adelante LOOP
        inicio := (CURRENT_DATE + i);
        nombre := format('tecnico_posiciones_%s', to_char(inicio, 'YYYY_MM_DD'));
        IF to_regclass(nombre) IS NULL THEN
          EXECUTE format('CREATE TABLE %I PARTITION OF tecnico_posiciones FOR VALUES FROM (%L) TO (%L)',
                         nombre, inicio, inicio + 1);
          creadas := creadas + 1;
        END IF;
      END LOOP;
      RETURN creadas;
    END $$;
    SELECT acma_crear_particiones_posiciones(7);
    """)

    # Retención: 90 días. La posición de llegada y la de cierre de cada folio viven en su historial (P04), así que
    # soltar la partición no borra el dato que el folio necesita conservar (decisión anotada en CONTEXTO).
    ex("""
    CREATE FUNCTION acma_purgar_posiciones(dias INTEGER DEFAULT 90)
    RETURNS TABLE (particion TEXT, accion TEXT, filas BIGINT)
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
    DECLARE
      r RECORD;
      limite DATE := CURRENT_DATE - dias;
      cuantas BIGINT;
    BEGIN
      FOR r IN
        SELECT c.relname AS nombre,
               to_date(right(c.relname, 10), 'YYYY_MM_DD') AS dia
          FROM pg_class c
          JOIN pg_inherits i ON i.inhrelid = c.oid
          JOIN pg_class padre ON padre.oid = i.inhparent
         WHERE padre.relname = 'tecnico_posiciones'
           AND c.relname ~ '_[0-9]{4}_[0-9]{2}_[0-9]{2}$'
      LOOP
        IF r.dia IS NULL OR r.dia >= limite THEN
          CONTINUE;
        END IF;
        EXECUTE format('SELECT count(*) FROM %I', r.nombre) INTO cuantas;
        EXECUTE format('ALTER TABLE tecnico_posiciones DETACH PARTITION %I', r.nombre);
        EXECUTE format('DROP TABLE %I', r.nombre);
        particion := r.nombre;
        accion := 'soltada';
        filas := cuantas;
        RETURN NEXT;
      END LOOP;
    END $$;
    """)
    ex("REVOKE ALL ON FUNCTION acma_crear_particiones_posiciones(INTEGER) FROM PUBLIC;")
    ex("REVOKE ALL ON FUNCTION acma_purgar_posiciones(INTEGER) FROM PUBLIC;")
    ex("GRANT EXECUTE ON FUNCTION acma_crear_particiones_posiciones(INTEGER) TO acma_owner, acma_api;")
    ex("GRANT EXECUTE ON FUNCTION acma_purgar_posiciones(INTEGER) TO acma_owner;")
    ex("GRANT SELECT, INSERT ON tecnico_posiciones TO acma_api;")

    # ------------------------------------------------------------------ seguimiento de las alertas de operación
    ex(f"""
    CREATE TABLE alertas_operacion_seguimiento ({base},
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      alerta_historial_id UUID REFERENCES alertas_historial(id) ON DELETE SET NULL,
      tipo VARCHAR(60) NOT NULL,
      tecnico_id UUID NOT NULL REFERENCES tecnicos(id),
      folio_id UUID REFERENCES folios(id),
      jornada_id UUID REFERENCES jornadas_tecnico(id) ON DELETE SET NULL,
      push_al_tecnico_at TIMESTAMPTZ,
      respuesta_tecnico respuesta_alerta_tecnico,
      respondida_at TIMESTAMPTZ,
      escalada_at TIMESTAMPTZ,
      datos_json JSONB NOT NULL DEFAULT '{{}}'::jsonb,
      CONSTRAINT ck_alertas_operacion_respuesta CHECK (
        (respuesta_tecnico IS NULL) = (respondida_at IS NULL))
    );
    CREATE INDEX ix_alertas_operacion_tecnico ON alertas_operacion_seguimiento (tecnico_id, created_at DESC);
    CREATE INDEX ix_alertas_operacion_pendientes ON alertas_operacion_seguimiento (prestador_id, created_at DESC)
      WHERE respondida_at IS NULL;
    CREATE UNIQUE INDEX uq_alertas_operacion_historial ON alertas_operacion_seguimiento (alerta_historial_id)
      WHERE alerta_historial_id IS NOT NULL;
    """)
    rls("alertas_operacion_seguimiento",
        f"CREATE POLICY alertas_operacion_seguimiento_lectura ON alertas_operacion_seguimiento FOR SELECT USING "
        f"({LECTURA_OPERACION % 'alertas_operacion_seguimiento.tecnico_id'});",
        "CREATE POLICY alertas_operacion_seguimiento_respuesta ON alertas_operacion_seguimiento FOR UPDATE USING "
        "(EXISTS (SELECT 1 FROM tecnicos t WHERE t.id = alertas_operacion_seguimiento.tecnico_id "
        "AND t.usuario_id = acma_ctx_usuario())) WITH CHECK "
        "(EXISTS (SELECT 1 FROM tecnicos t WHERE t.id = alertas_operacion_seguimiento.tecnico_id "
        "AND t.usuario_id = acma_ctx_usuario()));",
        f"CREATE POLICY alertas_operacion_seguimiento_escritura ON alertas_operacion_seguimiento FOR ALL USING "
        f"{ESCRITURA_PRESTADOR} WITH CHECK {ESCRITURA_PRESTADOR};")

    versionar(*TABLAS)
    for t in TABLAS:
        ex(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {t} TO acma_api;")

    # ------------------------------------------------------------------ alertas (§6.9.6)
    # Las dos que ya tienen de dónde salir dejan de ser de Fase 2; el desvío de ruta sigue esperando su bloque.
    for clave, parametros in (("TECNICO_TIEMPO_MUERTO", '{"radio_m": 50, "escalacion_min": 10}'),
                              ("TECNICO_SIN_SENAL", '{}')):
        ex(f"UPDATE alertas_catalogo SET fase = 1, activa_por_defecto = true, prompt_origen = 'F2-03', "
           f"parametros_default = {lit(parametros)}::jsonb WHERE clave = {lit(clave)};")
        ex(f"UPDATE alertas_configuracion SET activa = true WHERE clave_alerta = {lit(clave)};")
    ex("UPDATE alertas_catalogo SET descripcion = descripcion || ' Requiere el bloque de optimización de rutas: "
       "sin la ruta planeada no hay desvío que medir.' WHERE clave = 'TECNICO_DESVIO_RUTA' "
       "AND descripcion NOT LIKE '%optimización de rutas%';")


def downgrade() -> None:
    ex("SELECT set_config('app.rol', 'sistema', true);")
    for clave in ("TECNICO_TIEMPO_MUERTO", "TECNICO_SIN_SENAL"):
        ex(f"DELETE FROM alertas_historial WHERE clave_alerta = {lit(clave)};")
        ex(f"UPDATE alertas_catalogo SET fase = 2, activa_por_defecto = false, prompt_origen = 'P01', "
           f"parametros_default = '{{}}'::jsonb WHERE clave = {lit(clave)};")
        ex(f"UPDATE alertas_configuracion SET activa = false WHERE clave_alerta = {lit(clave)};")
    ex("UPDATE alertas_catalogo SET descripcion = replace(descripcion, ' Requiere el bloque de optimización de "
       "rutas: sin la ruta planeada no hay desvío que medir.', '') WHERE clave = 'TECNICO_DESVIO_RUTA';")
    ex("DROP TABLE IF EXISTS alertas_operacion_seguimiento CASCADE;")
    ex("DROP FUNCTION IF EXISTS acma_purgar_posiciones(INTEGER);")
    ex("DROP FUNCTION IF EXISTS acma_crear_particiones_posiciones(INTEGER);")
    ex("DROP TABLE IF EXISTS tecnico_posiciones CASCADE;")
    ex("DROP TABLE IF EXISTS jornada_pausas CASCADE;")
    ex("DROP TABLE IF EXISTS jornadas_tecnico CASCADE;")
    ex("""
    DROP INDEX IF EXISTS ix_tecnicos_estatus;
    DROP INDEX IF EXISTS ix_tecnicos_ultima_posicion;
    ALTER TABLE tecnicos
      DROP CONSTRAINT IF EXISTS ck_tecnicos_bateria,
      DROP COLUMN IF EXISTS ultima_posicion,
      DROP COLUMN IF EXISTS ultima_posicion_at,
      DROP COLUMN IF EXISTS ultima_precision_m,
      DROP COLUMN IF EXISTS ultima_bateria_pct,
      DROP COLUMN IF EXISTS estatus_operativo,
      DROP COLUMN IF EXISTS estatus_operativo_desde;
    """)
    ex("""
    DROP TYPE IF EXISTS respuesta_alerta_tecnico;
    DROP TYPE IF EXISTS motivo_pausa_jornada;
    DROP TYPE IF EXISTS cerrada_por_jornada;
    DROP TYPE IF EXISTS estado_jornada;
    DROP TYPE IF EXISTS estatus_operativo_tecnico;
    """)
