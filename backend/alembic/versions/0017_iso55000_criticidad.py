"""0017 — Análisis de criticidad y gestión de riesgo por activo (ISO 55000, §6.9.3). F2-05.

Lo que agrega:
- `criticidad_configuracion`: los pesos de las cuatro dimensiones, los rangos del impacto económico, la escala de
  probabilidad, los rangos de nivel, los meses de revisión y qué implicaciones están activas. Todo por cliente, con
  los valores literales del diseño como default, y un CHECK que exige que los pesos sumen 100.
- `activo_criticidad` + `criticidad_evaluaciones` (**append-only**): la clasificación vigente de cada equipo y la
  traza de cómo llegó ahí, que es lo que pide una auditoría ISO 55000.
- `activo_modos_falla` + `activo_riesgo_mitigacion`: el FMEA simplificado. Un modo de falla cuelga **del equipo o
  del tipo de equipo** (uno de los dos, con CHECK): los genéricos del tipo sirven para sembrar los de todos sus
  equipos sin repetir el trabajo.

`equipos.criticidad` (P04) **no se duplica**: sigue siendo el campo que leen la aprobación multinivel y el resto del
sistema, y `criticidad_service` lo sincroniza desde `activo_criticidad.nivel`. Por eso el ENUM del nivel es el mismo
`criticidad_activo` que ya existía, no uno nuevo.

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-11
"""
import json

from core.sql_migracion import ex, lit, rls, versionar

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None

TABLAS = ["criticidad_configuracion", "activo_criticidad", "criticidad_evaluaciones", "activo_modos_falla",
          "activo_riesgo_mitigacion"]
ENUMS = ["origen_criticidad", "motivo_evaluacion_criticidad", "origen_modo_falla", "tipo_mitigacion",
         "estado_mitigacion"]

base = """
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      version_hash VARCHAR(64)"""

# Las tablas de criticidad son del cliente, pero las escribe también el prestador que lo atiende (el Admin
# prestador registra modos de falla y mitigaciones), así que la escritura va por `acma_tenant_visible` como las de
# activos de P09, no por el tenant del contexto.
ESCRITURA = "(acma_es_plataforma() OR acma_tenant_visible(tenant_id))"


def _politicas(t: str) -> tuple[str, ...]:
    return (
        f"CREATE POLICY {t}_lectura ON {t} FOR SELECT USING (acma_tenant_visible(tenant_id));",
        f"CREATE POLICY {t}_insercion ON {t} FOR INSERT WITH CHECK {ESCRITURA};",
        f"CREATE POLICY {t}_actualizacion ON {t} FOR UPDATE USING {ESCRITURA} WITH CHECK {ESCRITURA};",
        f"CREATE POLICY {t}_borrado ON {t} FOR DELETE USING {ESCRITURA};",
    )


def _append_only(t: str) -> tuple[str, ...]:
    return (
        f"CREATE POLICY {t}_lectura ON {t} FOR SELECT USING (acma_tenant_visible(tenant_id));",
        f"CREATE POLICY {t}_insercion ON {t} FOR INSERT WITH CHECK {ESCRITURA};",
    )


# ------------------------------------------------------------------ valores literales de §6.9.3
PESOS = {"operacional": 30, "seguridad": 35, "economico": 25, "imagen": 10}

# Impacto económico: §6.9.3 fija los dos extremos (1 = menos de $5,000; 5 = más de $500,000). Los intermedios los
# elige ACMA y son configurables por cliente (decisión pendiente).
RANGOS_ECONOMICO = [
    {"nivel": 1, "hasta": 5000, "texto": "Menor a $5,000"},
    {"nivel": 2, "hasta": 25000, "texto": "De $5,000 a $25,000"},
    {"nivel": 3, "hasta": 100000, "texto": "De $25,000 a $100,000"},
    {"nivel": 4, "hasta": 500000, "texto": "De $100,000 a $500,000"},
    {"nivel": 5, "hasta": None, "texto": "Mayor a $500,000"},
]

# Probabilidad de falla 1–5 desde el historial de ACMA. El diseño pide «historial de fallas» sin fijar la escala:
# esta es la de ACMA y es configurable (decisión pendiente). `por_mtbf` viene vacío a propósito: con él configurado
# y suficientes fallas, el cálculo usa el MTBF del equipo en lugar del conteo.
ESCALA_PROBABILIDAD = {
    "meses": 12,
    "minimo_meses_historia": 6,
    "por_fallas": [
        {"nivel": 1, "hasta": 0, "texto": "Sin fallas en 12 meses"},
        {"nivel": 2, "hasta": 2, "texto": "1 o 2 fallas en 12 meses"},
        {"nivel": 3, "hasta": 5, "texto": "De 3 a 5 fallas en 12 meses"},
        {"nivel": 4, "hasta": 11, "texto": "De 6 a 11 fallas en 12 meses"},
        {"nivel": 5, "hasta": None, "texto": "12 fallas o más en 12 meses"},
    ],
    "por_mtbf": [],
    "minimo_fallas_para_mtbf": 3,
}

RANGOS_NIVEL = [
    {"nivel": "A", "desde": 80, "hasta": 100, "etiqueta": "Crítico"},
    {"nivel": "B", "desde": 50, "hasta": 79, "etiqueta": "Importante"},
    {"nivel": "C", "desde": 20, "hasta": 49, "etiqueta": "Estándar"},
    {"nivel": "D", "desde": 0, "hasta": 19, "etiqueta": "No crítico"},
]

# Las implicaciones literales de §6.9.3. `alerta` avisa; `restriccion` además bloquea, y eso lo decide el cliente.
IMPLICACIONES = {
    "pm_obligatorio": {"alerta": True, "restriccion": False},
    "respuesta_maxima": {"alerta": True, "restriccion": False, "horas_a": 4, "horas_b": 8, "aviso_pct": 80},
    "tecnico_certificado": {"alerta": True, "restriccion": False},
    "refaccion_en_inventario": {"alerta": True, "restriccion": False},
}

ALERTAS = [
    # clave, descripcion, umbral, tipo, min, max, destinatarios
    ("CRITICIDAD_REVISION_PENDIENTE",
     "La criticidad de un activo lleva más de X días vencida su fecha de revisión (ISO 55000 pide revisarla "
     "periódicamente).",
     0, "dias", 0, 365, ["admin_empresa", "admin_un"]),
    ("ACTIVO_CRITICO_SIN_PLAN",
     "Un activo de criticidad A no tiene plan de mantenimiento preventivo activo (§6.9.3: PM obligatorio).",
     0, "cantidad", 0, 100, ["admin_empresa", "admin_prestador", "despachador"]),
    ("RESPUESTA_CRITICIDAD_EN_RIESGO",
     "Un correctivo de un activo A o B se acerca al tiempo de respuesta que exige su criticidad (4 h y 8 h de "
     "§6.9.3), aunque el SLA del contrato sea más largo. No cambia el SLA ni la penalización.",
     80, "porcentaje", 50, 100, ["despachador", "admin_prestador"]),
    ("REFACCION_CRITICA_SIN_STOCK",
     "Una refacción de los planes de activos A está por debajo de su stock mínimo (§6.9.3: refacciones siempre en "
     "inventario).",
     0, "cantidad", 0, 100, ["admin_prestador", "despachador", "admin_empresa"]),
    ("MITIGACION_VENCIDA",
     "Una acción de mitigación de riesgo pasó su fecha compromiso sin implementarse.",
     0, "dias", 0, 180, ["admin_empresa", "admin_prestador"]),
]


def upgrade() -> None:
    ex("SELECT set_config('app.rol', 'sistema', true);")

    ex("""
    CREATE TYPE origen_criticidad AS ENUM ('calculado','manual');
    CREATE TYPE motivo_evaluacion_criticidad AS ENUM
      ('evaluacion_inicial','revision_periodica','recalculo_por_historial','ajuste_manual','cambio_configuracion');
    CREATE TYPE origen_modo_falla AS ENUM ('sugerido','manual');
    CREATE TYPE tipo_mitigacion AS ENUM
      ('plan_preventivo','capacitacion','refaccion_en_inventario','rediseno','otro');
    CREATE TYPE estado_mitigacion AS ENUM ('propuesta','en_proceso','implementada','descartada');
    """)

    # ------------------------------------------------------------------ configuración por cliente
    ex(f"""
    CREATE TABLE criticidad_configuracion ({base},
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      pesos_json JSONB NOT NULL DEFAULT {lit(json.dumps(PESOS))}::jsonb,
      rangos_economico_json JSONB NOT NULL DEFAULT {lit(json.dumps(RANGOS_ECONOMICO))}::jsonb,
      escala_probabilidad_json JSONB NOT NULL DEFAULT {lit(json.dumps(ESCALA_PROBABILIDAD))}::jsonb,
      rangos_nivel_json JSONB NOT NULL DEFAULT {lit(json.dumps(RANGOS_NIVEL))}::jsonb,
      meses_revision SMALLINT NOT NULL DEFAULT 12,
      implicaciones_activas_json JSONB NOT NULL DEFAULT {lit(json.dumps(IMPLICACIONES))}::jsonb,
      configurado_por UUID REFERENCES usuarios(id),
      -- §6.9.3: los pesos son configurables, pero tienen que sumar 100 % o el índice deja de significar nada.
      CONSTRAINT ck_criticidad_pesos CHECK (
        (COALESCE((pesos_json->>'operacional')::numeric, 0) + COALESCE((pesos_json->>'seguridad')::numeric, 0)
         + COALESCE((pesos_json->>'economico')::numeric, 0) + COALESCE((pesos_json->>'imagen')::numeric, 0)) = 100),
      CONSTRAINT ck_criticidad_meses CHECK (meses_revision BETWEEN 1 AND 60)
    );
    CREATE UNIQUE INDEX uq_criticidad_configuracion ON criticidad_configuracion (tenant_id);
    """)
    rls("criticidad_configuracion", *_politicas("criticidad_configuracion"))

    # ------------------------------------------------------------------ clasificación vigente
    ex(f"""
    CREATE TABLE activo_criticidad ({base},
      equipo_id UUID NOT NULL REFERENCES equipos(id),
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      indice_criticidad NUMERIC(6,2) NOT NULL DEFAULT 0,
      nivel criticidad_activo NOT NULL,
      probabilidad NUMERIC(4,2) NOT NULL DEFAULT 1,
      probabilidad_estimada BOOLEAN NOT NULL DEFAULT false,
      probabilidad_origen VARCHAR(40) NOT NULL DEFAULT 'historial_equipo',
      impacto_ponderado NUMERIC(4,2) NOT NULL DEFAULT 1,
      dimensiones_json JSONB NOT NULL DEFAULT '{{}}'::jsonb,
      origen origen_criticidad NOT NULL DEFAULT 'calculado',
      razon_manual TEXT NOT NULL DEFAULT '',
      evaluado_por UUID REFERENCES usuarios(id),
      fecha_evaluacion DATE NOT NULL DEFAULT CURRENT_DATE,
      proxima_revision DATE,
      CONSTRAINT ck_activo_criticidad_indice CHECK (indice_criticidad BETWEEN 0 AND 100),
      CONSTRAINT ck_activo_criticidad_escalas CHECK (
        probabilidad BETWEEN 1 AND 5 AND impacto_ponderado BETWEEN 1 AND 5),
      -- Un ajuste manual tiene que decir por qué: es lo que lee la auditoría cuando el nivel no sale del cálculo.
      CONSTRAINT ck_activo_criticidad_razon CHECK (
        origen <> 'manual' OR length(btrim(razon_manual)) > 0)
    );
    CREATE UNIQUE INDEX uq_activo_criticidad ON activo_criticidad (equipo_id);
    CREATE INDEX ix_activo_criticidad_nivel ON activo_criticidad (tenant_id, nivel);
    CREATE INDEX ix_activo_criticidad_revision ON activo_criticidad (proxima_revision)
      WHERE proxima_revision IS NOT NULL;
    """)
    rls("activo_criticidad", *_politicas("activo_criticidad"))

    # ------------------------------------------------------------------ historial de evaluaciones (append-only)
    ex(f"""
    CREATE TABLE criticidad_evaluaciones ({base},
      equipo_id UUID NOT NULL REFERENCES equipos(id),
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      indice_anterior NUMERIC(6,2),
      indice_nuevo NUMERIC(6,2) NOT NULL,
      nivel_anterior criticidad_activo,
      nivel_nuevo criticidad_activo NOT NULL,
      dimensiones_json JSONB NOT NULL DEFAULT '{{}}'::jsonb,
      probabilidad NUMERIC(4,2) NOT NULL DEFAULT 1,
      impacto_ponderado NUMERIC(4,2) NOT NULL DEFAULT 1,
      motivo motivo_evaluacion_criticidad NOT NULL,
      razon TEXT NOT NULL DEFAULT '',
      evaluado_por UUID REFERENCES usuarios(id),
      timestamp TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE INDEX ix_criticidad_evaluaciones_equipo ON criticidad_evaluaciones (equipo_id, timestamp DESC);
    CREATE TRIGGER trg_criticidad_evaluaciones_inmutable BEFORE UPDATE OR DELETE ON criticidad_evaluaciones
      FOR EACH ROW EXECUTE FUNCTION acma_auditoria_inmutable();
    CREATE TRIGGER trg_criticidad_evaluaciones_truncate BEFORE TRUNCATE ON criticidad_evaluaciones
      FOR EACH STATEMENT EXECUTE FUNCTION acma_auditoria_inmutable();
    """)
    rls("criticidad_evaluaciones", *_append_only("criticidad_evaluaciones"))

    # ------------------------------------------------------------------ modos de falla (FMEA simplificado)
    # `deteccion` es opcional: con ella el riesgo es severidad × frecuencia × detección (RPN clásico del FMEA);
    # sin ella, severidad × frecuencia, que es lo que pide §6.9.3. El servicio guarda `nivel_riesgo` ya calculado
    # para poder ordenar y filtrar sin recalcular en cada consulta.
    ex(f"""
    CREATE TABLE activo_modos_falla ({base},
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      equipo_id UUID REFERENCES equipos(id),
      tipo_equipo_id UUID REFERENCES tipos_equipo(id),
      descripcion_falla VARCHAR(300) NOT NULL,
      tipo_falla_id UUID REFERENCES tipos_falla(id),
      causa_probable TEXT NOT NULL DEFAULT '',
      efecto_operacional TEXT NOT NULL DEFAULT '',
      severidad SMALLINT NOT NULL DEFAULT 3,
      frecuencia_historica SMALLINT NOT NULL DEFAULT 1,
      fallas_12m SMALLINT NOT NULL DEFAULT 0,
      deteccion SMALLINT,
      nivel_riesgo SMALLINT NOT NULL DEFAULT 3,
      origen origen_modo_falla NOT NULL DEFAULT 'manual',
      activo BOOLEAN NOT NULL DEFAULT true,
      registrado_por UUID REFERENCES usuarios(id),
      -- Un modo de falla es de un equipo **o** genérico de un tipo de equipo, nunca de los dos ni de ninguno.
      CONSTRAINT ck_modos_falla_dueno CHECK ((equipo_id IS NULL) <> (tipo_equipo_id IS NULL)),
      CONSTRAINT ck_modos_falla_escalas CHECK (
        severidad BETWEEN 1 AND 5 AND frecuencia_historica BETWEEN 1 AND 5
        AND (deteccion IS NULL OR deteccion BETWEEN 1 AND 5))
    );
    CREATE INDEX ix_modos_falla_equipo ON activo_modos_falla (equipo_id) WHERE equipo_id IS NOT NULL;
    CREATE INDEX ix_modos_falla_tipo ON activo_modos_falla (tipo_equipo_id) WHERE tipo_equipo_id IS NOT NULL;
    CREATE INDEX ix_modos_falla_riesgo ON activo_modos_falla (tenant_id, nivel_riesgo DESC) WHERE activo;
    """)
    rls("activo_modos_falla", *_politicas("activo_modos_falla"))

    # ------------------------------------------------------------------ acciones de mitigación
    ex(f"""
    CREATE TABLE activo_riesgo_mitigacion ({base},
      modo_falla_id UUID NOT NULL REFERENCES activo_modos_falla(id) ON DELETE CASCADE,
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      accion_mitigacion TEXT NOT NULL,
      tipo tipo_mitigacion NOT NULL DEFAULT 'otro',
      plan_mantenimiento_id UUID REFERENCES planes_mantenimiento(id),
      curso_id UUID REFERENCES cursos_catalogo(id),
      articulo_id UUID REFERENCES articulos(id),
      responsable_id UUID REFERENCES usuarios(id),
      fecha_compromiso DATE,
      fecha_implementacion DATE,
      estado estado_mitigacion NOT NULL DEFAULT 'propuesta',
      efectividad_json JSONB NOT NULL DEFAULT '{{}}'::jsonb,
      evidencia_key VARCHAR(400),
      razon_descarte TEXT NOT NULL DEFAULT '',
      registrado_por UUID REFERENCES usuarios(id),
      CONSTRAINT ck_mitigacion_accion CHECK (length(btrim(accion_mitigacion)) > 0),
      -- Una acción implementada tiene fecha; una descartada, razón.
      CONSTRAINT ck_mitigacion_implementada CHECK (
        estado <> 'implementada' OR fecha_implementacion IS NOT NULL),
      CONSTRAINT ck_mitigacion_descartada CHECK (
        estado <> 'descartada' OR length(btrim(razon_descarte)) > 0)
    );
    CREATE INDEX ix_mitigacion_modo ON activo_riesgo_mitigacion (modo_falla_id);
    CREATE INDEX ix_mitigacion_vencidas ON activo_riesgo_mitigacion (tenant_id, fecha_compromiso)
      WHERE estado IN ('propuesta','en_proceso') AND fecha_compromiso IS NOT NULL;
    """)
    rls("activo_riesgo_mitigacion", *_politicas("activo_riesgo_mitigacion"))

    versionar(*TABLAS)
    for t in TABLAS:
        ex(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {t} TO acma_api;")
    # El historial de evaluaciones es la traza de la auditoría ISO: la app no lo borra ni con la política abierta.
    ex("REVOKE DELETE ON criticidad_evaluaciones FROM acma_api;")

    # ------------------------------------------------------------------ alertas (§6.9.6)
    for clave, desc, umbral, tipo, mn, mx, dest in ALERTAS:
        ex(f"""
        INSERT INTO alertas_catalogo (clave, descripcion, umbral_default, umbral_min, umbral_max, tipo_umbral,
                                      modulo_origen, prompt_origen, destinatarios_default, canales_default, fase)
        VALUES ({lit(clave)}, {lit(desc)}, {umbral}, {mn}, {mx}, {lit(tipo)}, 'criticidad', 'F2-05',
                {lit(json.dumps(dest))}::jsonb, '["app", "push", "email"]'::jsonb, 1)
        ON CONFLICT (clave) DO NOTHING;
        """)


def downgrade() -> None:
    ex("SELECT set_config('app.rol', 'sistema', true);")
    for clave, *_ in ALERTAS:
        ex(f"DELETE FROM alertas_historial WHERE clave_alerta = {lit(clave)};")
        ex(f"DELETE FROM alertas_configuracion WHERE clave_alerta = {lit(clave)};")
        ex(f"DELETE FROM alertas_catalogo WHERE clave = {lit(clave)};")
    for t in reversed(TABLAS):
        ex(f"DROP TABLE IF EXISTS {t} CASCADE;")
    for e in reversed(ENUMS):
        ex(f"DROP TYPE IF EXISTS {e};")
