"""0018 — Optimización de rutas (VRPTW), reasignación automática, ETA y desvío de ruta (§6.8.2, §6.8.4). F2-06.

Lo que agrega:
- `mercados` + `mercado_unidades`: el área de operación del prestador. El diseño habla de «mercado» (velocidad
  promedio por mercado, ruta por mercado y fecha) pero no define la entidad, así que ACMA la modela como un
  catálogo **del prestador** que agrupa las UNs de sus clientes que se atienden juntas. Queda anotada como decisión
  pendiente: una UN pertenece a un mercado por prestador, no a uno global.
- `rutas_configuracion` + `rutas_tiempos_servicio`: los pesos de la función objetivo (ACT-2.1), la jornada, las
  velocidades por franja horaria, el factor de sinuosidad, los umbrales de desvío y qué proveedor de distancias y
  qué modo de reasignación automática usa el prestador.
- `rutas_planes` + `rutas_paradas` + `rutas_trazos`: el plan del día, cada parada con su hora estimada y si cumple
  ventana y SLA, y el trazo para dibujarlo y para medir el desvío.
- `rutas_recalculos`: cada recálculo parcial con su disparador, lo que propuso y qué se decidió. Es la traza de las
  reasignaciones automáticas.
- `distancias_cache`: la distancia y el tiempo entre dos puntos por franja y proveedor, además de Redis, para no
  volver a pedirla (y para no gastar llamadas cuando el proveedor sea Google).
- `reasignaciones.recalculo_id`: liga una reasignación automática al recálculo que la propuso.
- `TECNICO_DESVIO_RUTA` pasa a fase 1 **y activa por defecto** (como el tiempo muerto y «sin señal» en F2-03:
  una alerta inactiva por defecto no la dispara nadie, porque `alertas_service.disparar` respeta la
  configuración efectiva), con sus defaults literales de §6.8.4 (500 m por 5 min). El umbral de la tabla
  de alertas son los **metros**; los minutos viven en `rutas_configuracion.umbral_desvio_min`, porque una alerta
  tiene un solo umbral configurable.

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-13
"""
import json

from core.sql_migracion import ex, lit, politicas_prestador, rls, versionar

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None

TABLAS = ["mercados", "mercado_unidades", "rutas_configuracion", "rutas_tiempos_servicio", "rutas_planes",
          "rutas_paradas", "rutas_trazos", "rutas_recalculos", "distancias_cache"]
ENUMS = ["modo_reasignacion_automatica", "proveedor_distancias", "estado_plan_ruta", "disparador_recalculo",
         "estado_recalculo"]

base = """
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      version_hash VARCHAR(64)"""

# ------------------------------------------------------------------ valores literales de ACT-2.1 y §6.8.4
# Pesos de la función objetivo. La distancia y el tiempo son el costo base; los demás son penalizaciones que
# compiten contra él. Están en la misma unidad (el solver trabaja en segundos de costo equivalente) para que un
# número más alto siempre signifique «esto importa más».
PESOS = {
    "distancia": 1,            # costo base por kilómetro recorrido
    "sla": 600,                # por cada folio que se entrega con el SLA ya vencido
    "criticidad": 300,         # por nivel de criticidad, A pesa 3 veces lo que C
    "folio_sin_asignar": 5000, # dejar un folio fuera de la ruta es lo más caro
    "horas_extra": 240,        # por cada hora que la ruta pasa de la jornada
    "sin_refaccion": 400,      # asignar a quien no trae la refacción en el vehículo
}
# Velocidad promedio por franja horaria, en km/h. Son estimaciones urbanas de la Ciudad de México y **se
# recalibran con datos reales**: en cuanto haya historial de traslados se comparan contra los tiempos medidos.
VELOCIDADES = {
    "00:00-06:00": 45,
    "06:00-09:00": 20,   # hora pico de la mañana
    "09:00-13:00": 30,
    "13:00-16:00": 28,
    "16:00-20:00": 20,   # hora pico de la tarde
    "20:00-24:00": 38,
}
TIEMPOS_SERVICIO = [
    # (tipo_folio, minutos). El seed los refina con el promedio real del historial de cada prestador.
    ("correctivo", 60),
    ("preventivo", 90),
]


def upgrade() -> None:
    ex("""
    CREATE TYPE modo_reasignacion_automatica AS ENUM ('solo_sugerir', 'aplicar_y_avisar');
    CREATE TYPE proveedor_distancias AS ENUM ('estimado', 'google_routes');
    CREATE TYPE estado_plan_ruta AS ENUM ('borrador', 'publicado', 'en_curso', 'cerrado');
    CREATE TYPE disparador_recalculo AS ENUM ('desvio', 'tiempo_muerto', 'sla_en_riesgo', 'incidencia_tecnico',
                                              'folio_nuevo_urgente', 'reasignacion_forzada', 'manual');
    CREATE TYPE estado_recalculo AS ENUM ('propuesta', 'aplicada', 'rechazada', 'expirada');
    """)

    # ------------------------------------------------------------------ mercados
    ex(f"""
    CREATE TABLE mercados ({base},
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      codigo VARCHAR(40) NOT NULL,
      nombre VARCHAR(160) NOT NULL,
      zona_horaria VARCHAR(64) NOT NULL DEFAULT 'America/Mexico_City',
      centro GEOGRAPHY(POINT, 4326),
      activo BOOLEAN NOT NULL DEFAULT true,
      CONSTRAINT uq_mercado_codigo UNIQUE (prestador_id, codigo)
    );
    CREATE INDEX ix_mercados_prestador ON mercados (prestador_id) WHERE activo;
    """)
    rls("mercados", *politicas_prestador("mercados", lectura_tenants=True))

    # Una UN pertenece a un mercado **por prestador**: dos prestadores pueden agrupar la misma sucursal distinto.
    ex(f"""
    CREATE TABLE mercado_unidades ({base},
      mercado_id UUID NOT NULL REFERENCES mercados(id) ON DELETE CASCADE,
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      un_id UUID NOT NULL REFERENCES unidades_negocio(id),
      CONSTRAINT uq_mercado_un UNIQUE (prestador_id, un_id)
    );
    CREATE INDEX ix_mercado_unidades_mercado ON mercado_unidades (mercado_id);
    """)
    rls("mercado_unidades", *politicas_prestador("mercado_unidades", lectura_tenants=True))

    # ------------------------------------------------------------------ configuración del optimizador
    ex(f"""
    CREATE TABLE rutas_configuracion ({base},
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      mercado_id UUID REFERENCES mercados(id) ON DELETE CASCADE,
      pesos_json JSONB NOT NULL DEFAULT {lit(json.dumps(PESOS))}::jsonb,
      hora_inicio_jornada TIME NOT NULL DEFAULT '08:00',
      duracion_jornada_min INTEGER NOT NULL DEFAULT 480,
      tiempo_servicio_default_min INTEGER NOT NULL DEFAULT 60,
      factor_sinuosidad NUMERIC(4,2) NOT NULL DEFAULT 1.40,
      velocidades_json JSONB NOT NULL DEFAULT {lit(json.dumps(VELOCIDADES))}::jsonb,
      modo_reasignacion_automatica modo_reasignacion_automatica NOT NULL DEFAULT 'solo_sugerir',
      minutos_vigencia_propuesta INTEGER NOT NULL DEFAULT 20,
      umbral_desvio_m INTEGER NOT NULL DEFAULT 500,
      umbral_desvio_min INTEGER NOT NULL DEFAULT 5,
      corredor_desvio_m INTEGER NOT NULL DEFAULT 2000,
      proveedor_distancias proveedor_distancias NOT NULL DEFAULT 'estimado',
      segundos_limite_calculo INTEGER NOT NULL DEFAULT 30,
      hora_calculo_automatico TIME NOT NULL DEFAULT '06:30',
      configurado_por UUID REFERENCES usuarios(id),
      -- Una configuración general por prestador (mercado_id NULL) y una por mercado como override.
      CONSTRAINT uq_rutas_configuracion UNIQUE NULLS NOT DISTINCT (prestador_id, mercado_id),
      CONSTRAINT ck_rutas_jornada CHECK (duracion_jornada_min BETWEEN 60 AND 1440),
      CONSTRAINT ck_rutas_sinuosidad CHECK (factor_sinuosidad BETWEEN 1 AND 3),
      CONSTRAINT ck_rutas_desvio CHECK (umbral_desvio_m BETWEEN 100 AND 10000 AND umbral_desvio_min BETWEEN 1 AND 120),
      CONSTRAINT ck_rutas_limite CHECK (segundos_limite_calculo BETWEEN 1 AND 600),
      CONSTRAINT ck_rutas_vigencia CHECK (minutos_vigencia_propuesta BETWEEN 1 AND 240)
    );
    """)
    rls("rutas_configuracion", *politicas_prestador("rutas_configuracion", lectura_tenants=True))

    # Cuánto dura atender un folio, por tipo y opcionalmente por tipo de equipo. Es el dato que más mueve la
    # calidad de la ruta, y el único que ACMA puede medir solo: el promedio real de atención del historial.
    ex(f"""
    CREATE TABLE rutas_tiempos_servicio ({base},
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      tipo_folio tipo_folio NOT NULL,
      tipo_equipo_id UUID REFERENCES tipos_equipo(id),
      minutos_estimados INTEGER NOT NULL,
      origen VARCHAR(30) NOT NULL DEFAULT 'configurado',
      muestras INTEGER NOT NULL DEFAULT 0,
      CONSTRAINT uq_tiempo_servicio UNIQUE NULLS NOT DISTINCT (prestador_id, tipo_folio, tipo_equipo_id),
      CONSTRAINT ck_tiempo_servicio CHECK (minutos_estimados BETWEEN 1 AND 1440)
    );
    """)
    rls("rutas_tiempos_servicio", *politicas_prestador("rutas_tiempos_servicio", lectura_tenants=True))

    # ------------------------------------------------------------------ plan del día
    ex(f"""
    CREATE TABLE rutas_planes ({base},
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      mercado_id UUID NOT NULL REFERENCES mercados(id) ON DELETE CASCADE,
      fecha DATE NOT NULL,
      estado estado_plan_ruta NOT NULL DEFAULT 'borrador',
      costo_objetivo NUMERIC(14,2) NOT NULL DEFAULT 0,
      distancia_total_km NUMERIC(10,2) NOT NULL DEFAULT 0,
      folios_asignados INTEGER NOT NULL DEFAULT 0,
      folios_sin_asignar INTEGER NOT NULL DEFAULT 0,
      sin_asignar_json JSONB NOT NULL DEFAULT '[]'::jsonb,
      tiempo_calculo_ms INTEGER NOT NULL DEFAULT 0,
      motor VARCHAR(40) NOT NULL DEFAULT 'ortools',
      calculado_por UUID REFERENCES usuarios(id),
      publicado_por UUID REFERENCES usuarios(id),
      publicado_at TIMESTAMPTZ,
      version INTEGER NOT NULL DEFAULT 1,
      -- Un solo plan vigente por mercado y día: los borradores anteriores se reemplazan al recalcular.
      CONSTRAINT uq_rutas_plan UNIQUE (mercado_id, fecha, version)
    );
    CREATE INDEX ix_rutas_planes_fecha ON rutas_planes (prestador_id, fecha DESC);
    """)
    rls("rutas_planes", *politicas_prestador("rutas_planes", lectura_tenants=True))

    ex(f"""
    CREATE TABLE rutas_paradas ({base},
      plan_id UUID NOT NULL REFERENCES rutas_planes(id) ON DELETE CASCADE,
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      tecnico_id UUID NOT NULL REFERENCES usuarios(id),
      folio_id UUID NOT NULL REFERENCES folios(id),
      orden INTEGER NOT NULL,
      llegada_estimada TIMESTAMPTZ,
      inicio_servicio_estimado TIMESTAMPTZ,
      fin_estimado TIMESTAMPTZ,
      distancia_desde_anterior_km NUMERIC(10,2) NOT NULL DEFAULT 0,
      minutos_desde_anterior INTEGER NOT NULL DEFAULT 0,
      minutos_servicio INTEGER NOT NULL DEFAULT 0,
      ventana_ok BOOLEAN NOT NULL DEFAULT true,
      sla_ok BOOLEAN NOT NULL DEFAULT true,
      holgura_sla_min INTEGER,
      fijo BOOLEAN NOT NULL DEFAULT false,
      CONSTRAINT uq_rutas_parada_folio UNIQUE (plan_id, folio_id),
      CONSTRAINT uq_rutas_parada_orden UNIQUE (plan_id, tecnico_id, orden)
    );
    CREATE INDEX ix_rutas_paradas_tecnico ON rutas_paradas (plan_id, tecnico_id, orden);
    CREATE INDEX ix_rutas_paradas_folio ON rutas_paradas (folio_id);
    """)
    rls("rutas_paradas", *politicas_prestador("rutas_paradas", lectura_tenants=True))

    ex(f"""
    CREATE TABLE rutas_trazos ({base},
      plan_id UUID NOT NULL REFERENCES rutas_planes(id) ON DELETE CASCADE,
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      tecnico_id UUID NOT NULL REFERENCES usuarios(id),
      geometria GEOGRAPHY(LINESTRING, 4326) NOT NULL,
      proveedor proveedor_distancias NOT NULL DEFAULT 'estimado',
      version INTEGER NOT NULL DEFAULT 1,
      CONSTRAINT uq_rutas_trazo UNIQUE (plan_id, tecnico_id, version)
    );
    CREATE INDEX ix_rutas_trazos_plan ON rutas_trazos (plan_id, tecnico_id);
    """)
    rls("rutas_trazos", *politicas_prestador("rutas_trazos", lectura_tenants=True))

    # ------------------------------------------------------------------ recálculos y propuestas
    ex(f"""
    CREATE TABLE rutas_recalculos ({base},
      plan_id UUID NOT NULL REFERENCES rutas_planes(id) ON DELETE CASCADE,
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      disparador disparador_recalculo NOT NULL,
      disparado_por_folio_id UUID REFERENCES folios(id),
      disparado_por_tecnico_id UUID REFERENCES usuarios(id),
      tecnicos_afectados JSONB NOT NULL DEFAULT '[]'::jsonb,
      folios_movidos_json JSONB NOT NULL DEFAULT '[]'::jsonb,
      propuesta_json JSONB NOT NULL DEFAULT '{{}}'::jsonb,
      motivo TEXT NOT NULL DEFAULT '',
      estado estado_recalculo NOT NULL DEFAULT 'propuesta',
      vence_at TIMESTAMPTZ,
      decidido_por UUID REFERENCES usuarios(id),
      decidido_at TIMESTAMPTZ,
      tiempo_calculo_ms INTEGER NOT NULL DEFAULT 0,
      timestamp TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE INDEX ix_rutas_recalculos_plan ON rutas_recalculos (plan_id, timestamp DESC);
    CREATE INDEX ix_rutas_recalculos_pendientes ON rutas_recalculos (prestador_id, estado)
      WHERE estado = 'propuesta';
    """)
    rls("rutas_recalculos", *politicas_prestador("rutas_recalculos", lectura_tenants=True))

    # ------------------------------------------------------------------ caché de distancias
    # No lleva dueño: es geografía, no dato de nadie. Por eso no tiene RLS ni columna de prestador; la llave es el
    # par de puntos redondeados, la franja y el proveedor.
    ex(f"""
    CREATE TABLE distancias_cache ({base},
      origen_hash VARCHAR(64) NOT NULL,
      destino_hash VARCHAR(64) NOT NULL,
      franja VARCHAR(20) NOT NULL,
      proveedor proveedor_distancias NOT NULL,
      metros INTEGER NOT NULL,
      segundos INTEGER NOT NULL,
      calculado_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      CONSTRAINT uq_distancias_cache UNIQUE (origen_hash, destino_hash, franja, proveedor)
    );
    CREATE INDEX ix_distancias_cache_fecha ON distancias_cache (calculado_at);
    """)
    ex("ALTER TABLE distancias_cache ENABLE ROW LEVEL SECURITY;")
    ex("CREATE POLICY distancias_cache_todos ON distancias_cache FOR ALL USING (true) WITH CHECK (true);")

    # ------------------------------------------------------------------ liga con la reasignación de P06
    ex("""
    ALTER TABLE reasignaciones ADD COLUMN recalculo_id UUID REFERENCES rutas_recalculos(id);
    CREATE INDEX ix_reasignaciones_recalculo ON reasignaciones (recalculo_id)
      WHERE recalculo_id IS NOT NULL;
    """)

    versionar(*TABLAS)
    for t in TABLAS:
        ex(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {t} TO acma_api;")

    # ------------------------------------------------------------------ desvío de ruta (§6.8.4): sale de Fase 2
    # `alertas_catalogo` tiene RLS forzada desde 0001 y su política de escritura exige contexto de plataforma, que
    # aplica incluso al dueño del esquema: sin contexto el UPDATE afecta **cero filas y no avisa**. Se fija el rol
    # de sistema para la transacción, que es el mismo contexto con el que la app hace su trabajo de sistema.
    ex("SET LOCAL app.rol = 'sistema';")
    ex("""
    UPDATE alertas_catalogo
       SET fase = 1, activa_por_defecto = true, umbral_default = 500, umbral_min = 100,
           umbral_max = 10000, tipo_umbral = 'metros', prompt_origen = 'F2-06',
           descripcion = 'Técnico a más de X metros de su ruta calculada por más de los minutos configurados'
     WHERE clave = 'TECNICO_DESVIO_RUTA';
    """)

    # Tiempos de servicio por tipo de folio para los prestadores que ya existen.
    for tipo, minutos in TIEMPOS_SERVICIO:
        ex(f"""
        INSERT INTO rutas_tiempos_servicio (prestador_id, tipo_folio, tipo_equipo_id, minutos_estimados, origen)
        SELECT id, {lit(tipo)}::tipo_folio, NULL, {minutos}, 'default' FROM prestadores
        ON CONFLICT DO NOTHING;
        """)


def downgrade() -> None:
    ex("SET LOCAL app.rol = 'sistema';")
    ex("""
    UPDATE alertas_catalogo
       SET fase = 2, activa_por_defecto = false, prompt_origen = 'P10',
           descripcion = 'Técnico fuera de la ruta planeada más de los metros configurados'
     WHERE clave = 'TECNICO_DESVIO_RUTA';
    """)
    ex("DROP INDEX IF EXISTS ix_reasignaciones_recalculo;")
    ex("ALTER TABLE reasignaciones DROP COLUMN IF EXISTS recalculo_id;")
    for t in reversed(TABLAS):
        ex(f"DROP TABLE IF EXISTS {t} CASCADE;")
    for e in reversed(ENUMS):
        ex(f"DROP TYPE IF EXISTS {e};")
