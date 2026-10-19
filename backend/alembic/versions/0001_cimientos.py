"""0001 — Cimientos: tenants, prestadores, usuarios, UNs, contratos, alertas, auditoría, RLS.

Revision ID: 0001
Revises:
Create Date: 2026-10-19
"""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

ROLES = [
    # clave, nombre, dominio, mfa_obligatorio, descripcion (§5)
    ("superadmin", "Superadmin", "plataforma", True, "Acceso total. Gestiona tenants, prestadores, planes y configuración global."),
    ("admin_prestador", "Admin prestador", "prestador", True, "Administra técnicos, vehículos, inventario, contratos, formularios y catálogos."),
    ("direccion_prestador", "Dirección del prestador", "prestador", True, "Nivel directivo de solo lectura; recibe alertas de escalación."),
    ("mesa_control", "Mesa de control", "prestador", False, "Relación con el cliente: cotizaciones, consultas, monitoreo y estadísticas."),
    ("despachador", "Despachador", "prestador", False, "Operador logístico: rutas, técnicos, preventivos, minuta y reasignaciones."),
    ("supervisor_prestador", "Supervisor (prestador)", "prestador", False, "Solo lectura de dashboards de KPIs y reporte de cierre de jornada."),
    ("tecnico", "Técnico", "prestador", False, "Técnico en campo: ruta, formularios de atención, evidencias y firma."),
    ("admin_empresa", "Admin empresa", "tenant", True, "Administrador del tenant: UNs, presupuestos, usuarios, reportes y aprobaciones."),
    ("admin_un", "Admin unidad de negocio", "tenant", False, "Administra sus UNs asignadas y responde la minuta del día."),
    ("supervisor_operadores", "Supervisor de operadores", "tenant", False, "Dashboard consolidado de los grupos de UNs asignados."),
    ("operador", "Operador", "tenant", False, "Captura folios desde la app móvil de su UN."),
]

PERMISOS = [
    # clave, aplica_a, valor_default, descripcion (§6.8.3 y §6.8.3b)
    ("ejecutar_correctivos", "tecnico", True, "Puede recibir y cerrar folios de mantenimiento correctivo."),
    ("ejecutar_preventivos", "tecnico", True, "Puede recibir y ejecutar mantenimientos preventivos programados."),
    ("ejecutar_trabajos_especiales", "tecnico", False, "Puede recibir y ejecutar trabajos especiales autorizados."),
    ("capturar_hallazgos", "tecnico", True, "Puede registrar hallazgos en el formulario de atención."),
    ("generar_cotizacion_campo", "tecnico", False, "Puede iniciar una cotización desde el campo durante una visita."),
    ("ver_costo_refacciones", "tecnico", False, "Puede ver el costo unitario de las refacciones en su inventario."),
    ("usar_caja_chica", "tecnico", True, "Puede realizar compras con la tarjeta de caja chica y capturar facturas."),
    ("acceder_manuales", "tecnico", True, "Puede consultar la biblioteca de manuales técnicos."),
    ("ver_historial_equipo", "tecnico", True, "Puede ver el historial completo del equipo al que atiende."),
    ("modificar_folio_en_campo", "tecnico", False, "Puede editar la descripción del folio una vez asignado."),
    ("crear_folio_en_campo", "tecnico", False, "Puede levantar un folio nuevo desde su app durante una visita."),
    ("crear_folios", "despachador", True, "Puede capturar folios directamente desde el portal del despachador."),
    ("forzar_severidad", "despachador", False, "Puede modificar la severidad asignada por la matriz antes de autorizar."),
    ("cancelar_folios_autorizados", "despachador", False, "Puede cancelar folios en estado Autorizado o posterior."),
    ("asignar_tecnico_sin_habilidad", "despachador", False, "Puede asignar un técnico sin la habilidad certificada, con razón obligatoria."),
    ("ver_costos_folio", "despachador", True, "Puede ver el desglose de costos de cada folio."),
]

ALERTAS = [
    # clave, descripcion, umbral_default, tipo_umbral, min, max, parametros_extra, modulo, prompt, destinatarios
    ("SLA_RESPUESTA_EN_RIESGO", "Folio sin asignar cuando se ha consumido X% del tiempo de respuesta del SLA.", 80, "porcentaje", 50, 100, None, "contratos_sla", "P10", ["despachador", "admin_prestador"]),
    ("SLA_RESOLUCION_EN_RIESGO", "Folio asignado cuando se ha consumido X% del tiempo de resolución del SLA.", 80, "porcentaje", 50, 100, None, "contratos_sla", "P10", ["despachador", "admin_prestador"]),
    ("TECNICO_TIEMPO_MUERTO", "Técnico sin movimiento GPS por más de X minutos en jornada activa.", 20, "minutos", 5, 240, None, "operaciones", "Fase 2", ["despachador"]),
    ("TECNICO_DESVIO_RUTA", "Técnico a más de X metros de la ruta calculada por más de Y minutos.", 500, "metros", 100, 10000, '{"minutos": 5}', "operaciones", "Fase 2", ["despachador"]),
    ("TECNICO_SIN_SENAL", "Sin posición del técnico por más de X minutos en jornada.", 15, "minutos", 5, 240, None, "operaciones", "Fase 2", ["despachador"]),
    ("PRESUPUESTO_ALERTA_1", "Gasto de la UN alcanzó X% del presupuesto del período.", 70, "porcentaje", 10, 100, None, "presupuestos", "P09", ["admin_empresa", "admin_un"]),
    ("PRESUPUESTO_ALERTA_2", "Gasto de la UN alcanzó X% del presupuesto.", 90, "porcentaje", 10, 100, None, "presupuestos", "P09", ["admin_empresa", "admin_un", "admin_prestador"]),
    ("PRESUPUESTO_ALERTA_3", "Gasto de la UN superó el X% del presupuesto.", 100, "porcentaje", 50, 200, None, "presupuestos", "P09", ["admin_empresa", "admin_un", "admin_prestador"]),
    ("COTIZACION_SIN_RESPUESTA", "Cotización enviada sin respuesta del cliente por más de X días.", 7, "dias", 1, 60, None, "seguimiento", "P07", ["admin_prestador", "despachador"]),
    ("COTIZACION_SIN_PREPARAR", "Cotización solicitada por el cliente sin preparar por más de X días.", 3, "dias", 1, 60, None, "seguimiento", "P07", ["admin_prestador", "despachador"]),
    ("SEGUIMIENTO_SIN_UPDATE", "Hallazgo en seguimiento interno sin actualización por más de X días.", 15, "dias", 1, 90, None, "seguimiento", "P07", ["despachador", "admin_un"]),
    ("REPROGRAMACION_FECHA_VENCIDA", "Fecha acordada de reprogramación vencida sin cambio de estado (X días de tolerancia).", 0, "dias", 0, 30, None, "seguimiento", "P07", ["despachador", "admin_un"]),
    ("STOCK_MINIMO", "Artículo de inventario con stock igual o menor al mínimo configurado.", 0, "cantidad", 0, 1000, None, "inventario", "P09", ["admin_prestador"]),
    ("FONDO_CAJA_CHICA_BAJO", "Saldo del fondo cayó por debajo de X% del monto inicial.", 20, "porcentaje", 5, 90, None, "caja_chica", "P09", ["admin_prestador"]),
    ("ACTIVO_REEMPLAZO", "TCO del activo supera X% de su valor de reposición.", 70, "porcentaje", 10, 200, None, "activos", "P09", ["admin_empresa", "admin_un"]),
    ("MEDIDOR_PROXIMO_PM", "Medidor alcanzará el umbral del plan en menos de X% del intervalo.", 10, "porcentaje", 1, 50, None, "medidores", "Fase 2", ["despachador"]),
    ("CERTIFICACION_VENCIDA", "Certificación de un técnico vence en menos de X días.", 30, "dias", 1, 180, None, "capacitacion", "Fase 2", ["admin_prestador"]),
    ("FOLIO_SIN_CLASIFICAR", "Folio no crítico sin autorización ni clasificación por más de X horas.", 24, "horas", 1, 720, None, "folios", "P07", ["admin_empresa", "admin_un"]),
    ("PREVENTIVO_DESVIO", "Preventivo ejecutado con más de X días de desvío respecto a la fecha programada.", 5, "dias", 0, 60, None, "preventivos", "P06", ["admin_empresa", "admin_prestador"]),
    ("COTIZACION_ESCALADA_DIRECCION", "Cotización que ya disparó COTIZACION_SIN_RESPUESTA y sigue sin resolverse X días después.", 7, "dias", 1, 60, None, "seguimiento", "P07", ["direccion_prestador"]),
]

# Tablas con id/created_at/updated_at/version_hash (§6.2 capa 1).
TABLAS_VERSIONADAS = [
    "tenants", "prestadores", "tenant_prestador", "usuarios", "roles", "permisos_catalogo",
    "permisos_tecnico", "grupos_tecnicos", "grupo_tecnico_permisos", "tecnico_grupo",
    "tecnico_permisos_override", "permisos_despachador", "grupos_un", "unidades_negocio",
    "grupo_un_miembros", "usuario_grupos", "usuario_un", "contratos", "contrato_sla",
    "alertas_catalogo", "alertas_configuracion", "alertas_supresiones",
    "configuracion_tenant", "configuracion_prestador",
]


def _lit(v) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    return "'" + str(v).replace("'", "''") + "'"


def _sentencias(sql: str) -> list[str]:
    """Divide un bloque SQL en sentencias respetando cadenas, cuerpos $$...$$ y comentarios (asyncpg ejecuta una a la vez)."""
    partes, actual, i, en_comillas, en_dolar = [], [], 0, False, False
    while i < len(sql):
        if not en_comillas and sql.startswith("$$", i):
            en_dolar = not en_dolar
            actual.append("$$")
            i += 2
            continue
        c = sql[i]
        if c == "-" and sql.startswith("--", i) and not en_comillas and not en_dolar:
            fin = sql.find("\n", i)
            i = len(sql) if fin == -1 else fin
            continue
        if c == "'" and not en_dolar:
            en_comillas = not en_comillas
        if c == ";" and not en_comillas and not en_dolar:
            partes.append("".join(actual).strip())
            actual = []
        else:
            actual.append(c)
        i += 1
    partes.append("".join(actual).strip())
    return [p for p in partes if p]


def ex(sql: str) -> None:
    for sentencia in _sentencias(sql):
        op.execute(sentencia)


def upgrade() -> None:

    # ------------------------------------------------------------------ tipos
    ex("""
    CREATE TYPE rol_usuario AS ENUM ('superadmin','admin_prestador','direccion_prestador','mesa_control',
        'despachador','supervisor_prestador','tecnico','admin_empresa','admin_un','supervisor_operadores','operador');
    CREATE TYPE dominio_usuario AS ENUM ('tenant','prestador','plataforma');
    CREATE TYPE estado_registro AS ENUM ('activo','inactivo','suspendido');
    CREATE TYPE nivel_severidad AS ENUM ('muy_baja','baja','media','alta','critica');
    CREATE TYPE modalidad_contrato AS ENUM ('evento','iguala');
    CREATE TYPE unidad_tiempo AS ENUM ('horas','dias','semanas','meses');
    CREATE TYPE tipo_penalizacion AS ENUM ('monto','porcentaje');
    CREATE TYPE tipo_umbral AS ENUM ('porcentaje','minutos','horas','dias','metros','cantidad');
    CREATE TYPE aplica_permiso AS ENUM ('tecnico','despachador');
    CREATE TYPE estado_alerta AS ENUM ('disparada','vista','resuelta');
    """)

    # ------------------------------------------------- funciones genéricas
    ex("""
    CREATE FUNCTION acma_version() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP = 'UPDATE' THEN
        NEW.created_at := OLD.created_at;
      END IF;
      NEW.updated_at := now();
      NEW.version_hash := encode(sha256(convert_to((to_jsonb(NEW) - 'version_hash' - 'updated_at')::text, 'UTF8')), 'hex');
      RETURN NEW;
    END $$;

    CREATE FUNCTION acma_auditoria_inmutable() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      RAISE EXCEPTION 'La tabla % es de solo inserción (append-only): % no permitido', TG_TABLE_NAME, TG_OP
        USING ERRCODE = 'insufficient_privilege';
    END $$;
    """)

    base = """
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      version_hash VARCHAR(64)"""

    # ---------------------------------------------------------------- tablas
    ex(f"""
    CREATE TABLE roles ({base},
      clave rol_usuario NOT NULL UNIQUE,
      nombre VARCHAR(80) NOT NULL,
      dominio dominio_usuario NOT NULL,
      mfa_obligatorio BOOLEAN NOT NULL DEFAULT false,
      descripcion TEXT NOT NULL DEFAULT ''
    );

    CREATE TABLE tenants ({base},
      razon_social VARCHAR(200) NOT NULL,
      rfc VARCHAR(20) NOT NULL,
      pais CHAR(2) NOT NULL DEFAULT 'MX',
      moneda CHAR(3) NOT NULL DEFAULT 'MXN',
      zona_horaria VARCHAR(64) NOT NULL DEFAULT 'America/Mexico_City',
      estado estado_registro NOT NULL DEFAULT 'activo',
      CONSTRAINT uq_tenants_rfc_pais UNIQUE (rfc, pais)
    );

    CREATE TABLE prestadores ({base},
      razon_social VARCHAR(200) NOT NULL,
      rfc VARCHAR(20) NOT NULL,
      pais CHAR(2) NOT NULL DEFAULT 'MX',
      datos_fiscales_cifrados TEXT,
      logo_key VARCHAR(300),
      color_primario VARCHAR(7) NOT NULL DEFAULT '#1C3D8F',
      color_acento VARCHAR(7) NOT NULL DEFAULT '#A2C62B',
      estado estado_registro NOT NULL DEFAULT 'activo',
      CONSTRAINT uq_prestadores_rfc_pais UNIQUE (rfc, pais)
    );

    CREATE TABLE tenant_prestador ({base},
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      vigencia_inicio DATE NOT NULL DEFAULT current_date,
      vigencia_fin DATE,
      estado estado_registro NOT NULL DEFAULT 'activo',
      CONSTRAINT ck_tenant_prestador_vigencia CHECK (vigencia_fin IS NULL OR vigencia_fin >= vigencia_inicio),
      CONSTRAINT uq_tenant_prestador UNIQUE (tenant_id, prestador_id, vigencia_inicio)
    );

    CREATE TABLE usuarios ({base},
      email VARCHAR(254) NOT NULL,
      password_hash VARCHAR(255) NOT NULL,
      nombre VARCHAR(160) NOT NULL,
      telefono VARCHAR(30),
      rol rol_usuario NOT NULL,
      dominio dominio_usuario NOT NULL,
      tenant_id UUID REFERENCES tenants(id),
      prestador_id UUID REFERENCES prestadores(id),
      estado estado_registro NOT NULL DEFAULT 'activo',
      mfa_secreto_cifrado TEXT,
      mfa_habilitado BOOLEAN NOT NULL DEFAULT false,
      mfa_codigos_recuperacion JSONB NOT NULL DEFAULT '[]'::jsonb,
      intentos_fallidos INTEGER NOT NULL DEFAULT 0,
      bloqueado_hasta TIMESTAMPTZ,
      password_actualizado_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      ultimo_acceso_at TIMESTAMPTZ,
      CONSTRAINT ck_usuarios_dominio CHECK (
        (dominio = 'plataforma' AND tenant_id IS NULL AND prestador_id IS NULL AND rol = 'superadmin')
        OR (dominio = 'tenant' AND tenant_id IS NOT NULL AND prestador_id IS NULL
            AND rol IN ('admin_empresa','admin_un','supervisor_operadores','operador'))
        OR (dominio = 'prestador' AND prestador_id IS NOT NULL AND tenant_id IS NULL
            AND rol IN ('admin_prestador','direccion_prestador','mesa_control','despachador','supervisor_prestador','tecnico'))
      )
    );
    CREATE UNIQUE INDEX uq_usuarios_email ON usuarios (lower(email));
    CREATE INDEX ix_usuarios_tenant ON usuarios (tenant_id);
    CREATE INDEX ix_usuarios_prestador ON usuarios (prestador_id);

    CREATE TABLE historial_contrasenas (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      usuario_id UUID NOT NULL REFERENCES usuarios(id),
      password_hash VARCHAR(255) NOT NULL,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE INDEX ix_historial_contrasenas_usuario ON historial_contrasenas (usuario_id, created_at DESC);

    CREATE TABLE permisos_catalogo ({base},
      clave VARCHAR(60) NOT NULL UNIQUE,
      aplica_a aplica_permiso NOT NULL,
      valor_default BOOLEAN NOT NULL,
      descripcion TEXT NOT NULL
    );

    -- §6.8.3 valores del prestador (nivel base), grupos y overrides individuales.
    CREATE TABLE permisos_tecnico ({base},
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      permiso_clave VARCHAR(60) NOT NULL REFERENCES permisos_catalogo(clave),
      habilitado BOOLEAN NOT NULL,
      CONSTRAINT uq_permisos_tecnico UNIQUE (prestador_id, permiso_clave)
    );
    CREATE TABLE grupos_tecnicos ({base},
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      nombre VARCHAR(80) NOT NULL,
      descripcion TEXT NOT NULL DEFAULT '',
      CONSTRAINT uq_grupos_tecnicos UNIQUE (prestador_id, nombre)
    );
    CREATE TABLE grupo_tecnico_permisos ({base},
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      grupo_id UUID NOT NULL REFERENCES grupos_tecnicos(id) ON DELETE CASCADE,
      permiso_clave VARCHAR(60) NOT NULL REFERENCES permisos_catalogo(clave),
      habilitado BOOLEAN NOT NULL,
      CONSTRAINT uq_grupo_tecnico_permisos UNIQUE (grupo_id, permiso_clave)
    );
    CREATE TABLE tecnico_grupo ({base},
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      tecnico_id UUID NOT NULL REFERENCES usuarios(id),
      grupo_id UUID NOT NULL REFERENCES grupos_tecnicos(id) ON DELETE CASCADE,
      fecha_asignacion DATE NOT NULL DEFAULT current_date,
      CONSTRAINT uq_tecnico_grupo UNIQUE (tecnico_id)
    );
    CREATE TABLE tecnico_permisos_override ({base},
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      tecnico_id UUID NOT NULL REFERENCES usuarios(id),
      permiso_clave VARCHAR(60) NOT NULL REFERENCES permisos_catalogo(clave),
      habilitado BOOLEAN NOT NULL,
      razon TEXT NOT NULL DEFAULT '',
      modificado_por UUID REFERENCES usuarios(id),
      CONSTRAINT uq_tecnico_permisos_override UNIQUE (tecnico_id, permiso_clave)
    );

    -- §6.8.3b: fila con despachador_id y tenant_id nulos = valor base del prestador.
    CREATE TABLE permisos_despachador ({base},
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      despachador_id UUID REFERENCES usuarios(id),
      tenant_id UUID REFERENCES tenants(id),
      permiso_clave VARCHAR(60) NOT NULL REFERENCES permisos_catalogo(clave),
      habilitado BOOLEAN NOT NULL,
      configurado_por UUID REFERENCES usuarios(id),
      CONSTRAINT ck_permisos_despachador_alcance CHECK ((despachador_id IS NULL) = (tenant_id IS NULL))
    );
    CREATE UNIQUE INDEX uq_permisos_despachador ON permisos_despachador
      (prestador_id, COALESCE(despachador_id, '00000000-0000-0000-0000-000000000000'::uuid),
       COALESCE(tenant_id, '00000000-0000-0000-0000-000000000000'::uuid), permiso_clave);
    CREATE TABLE permisos_despachador_log (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      despachador_id UUID REFERENCES usuarios(id),
      tenant_id UUID REFERENCES tenants(id),
      permiso_clave VARCHAR(60) NOT NULL,
      valor_anterior BOOLEAN,
      valor_nuevo BOOLEAN NOT NULL,
      modificado_por UUID REFERENCES usuarios(id),
      created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );

    CREATE TABLE grupos_un ({base},
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      nombre VARCHAR(120) NOT NULL,
      descripcion TEXT NOT NULL DEFAULT '',
      responsable_id UUID REFERENCES usuarios(id),
      estado estado_registro NOT NULL DEFAULT 'activo',
      CONSTRAINT uq_grupos_un UNIQUE (tenant_id, nombre)
    );

    CREATE TABLE unidades_negocio ({base},
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      nombre VARCHAR(160) NOT NULL,
      codigo VARCHAR(40) NOT NULL,
      direccion TEXT NOT NULL DEFAULT '',
      ubicacion GEOGRAPHY(Point, 4326),
      zona_horaria VARCHAR(64) NOT NULL DEFAULT 'America/Mexico_City',
      estado estado_registro NOT NULL DEFAULT 'activo',
      grupo_id UUID REFERENCES grupos_un(id),
      CONSTRAINT uq_unidades_negocio_codigo UNIQUE (tenant_id, codigo)
    );
    CREATE INDEX ix_unidades_negocio_tenant ON unidades_negocio (tenant_id);
    CREATE INDEX ix_unidades_negocio_ubicacion ON unidades_negocio USING GIST (ubicacion);

    -- §6.8.5: una UN puede pertenecer a varios grupos. unidades_negocio.grupo_id es el grupo principal.
    CREATE TABLE grupo_un_miembros ({base},
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      grupo_id UUID NOT NULL REFERENCES grupos_un(id) ON DELETE CASCADE,
      unidad_id UUID NOT NULL REFERENCES unidades_negocio(id) ON DELETE CASCADE,
      fecha_ingreso DATE NOT NULL DEFAULT current_date,
      CONSTRAINT uq_grupo_un_miembros UNIQUE (grupo_id, unidad_id)
    );
    CREATE TABLE usuario_grupos ({base},
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      usuario_id UUID NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
      grupo_id UUID NOT NULL REFERENCES grupos_un(id) ON DELETE CASCADE,
      rol_en_grupo VARCHAR(40) NOT NULL DEFAULT 'supervisor',
      CONSTRAINT uq_usuario_grupos UNIQUE (usuario_id, grupo_id)
    );
    CREATE TABLE usuario_un ({base},
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      usuario_id UUID NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
      unidad_id UUID NOT NULL REFERENCES unidades_negocio(id) ON DELETE CASCADE,
      CONSTRAINT uq_usuario_un UNIQUE (usuario_id, unidad_id)
    );

    CREATE TABLE contratos ({base},
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      nombre VARCHAR(160) NOT NULL,
      modalidad modalidad_contrato NOT NULL DEFAULT 'evento',
      fecha_inicio DATE NOT NULL,
      fecha_fin DATE NOT NULL,
      folios_correctivos_iguala INTEGER CHECK (folios_correctivos_iguala IS NULL OR folios_correctivos_iguala >= 0),
      preventivos_iguala_json JSONB NOT NULL DEFAULT '{{}}'::jsonb,
      penalizacion_tope_porcentaje NUMERIC(5,2) CHECK (penalizacion_tope_porcentaje IS NULL OR penalizacion_tope_porcentaje BETWEEN 0 AND 100),
      calificacion_json JSONB NOT NULL DEFAULT '{{}}'::jsonb,
      estado estado_registro NOT NULL DEFAULT 'activo',
      CONSTRAINT ck_contratos_vigencia CHECK (fecha_fin >= fecha_inicio)
    );
    CREATE INDEX ix_contratos_tenant ON contratos (tenant_id);
    CREATE INDEX ix_contratos_prestador ON contratos (prestador_id);

    CREATE TABLE contrato_sla ({base},
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      contrato_id UUID NOT NULL REFERENCES contratos(id) ON DELETE CASCADE,
      nivel_severidad nivel_severidad NOT NULL,
      tiempo_respuesta_horas INTEGER NOT NULL CHECK (tiempo_respuesta_horas BETWEEN 1 AND 4320),
      tiempo_resolucion_horas INTEGER NOT NULL CHECK (tiempo_resolucion_horas BETWEEN 1 AND 4320),
      unidad_expresion unidad_tiempo NOT NULL DEFAULT 'horas',
      penalizacion_tipo tipo_penalizacion NOT NULL DEFAULT 'porcentaje',
      penalizacion_valor NUMERIC(12,2) NOT NULL DEFAULT 0 CHECK (penalizacion_valor >= 0),
      CONSTRAINT uq_contrato_sla UNIQUE (contrato_id, nivel_severidad)
    );

    CREATE TABLE alertas_catalogo ({base},
      clave VARCHAR(60) NOT NULL UNIQUE,
      descripcion TEXT NOT NULL,
      umbral_default NUMERIC(12,2) NOT NULL,
      umbral_min NUMERIC(12,2) NOT NULL,
      umbral_max NUMERIC(12,2) NOT NULL,
      tipo_umbral tipo_umbral NOT NULL,
      parametros_default JSONB NOT NULL DEFAULT '{{}}'::jsonb,
      modulo_origen VARCHAR(40) NOT NULL,
      prompt_origen VARCHAR(10) NOT NULL,
      destinatarios_default JSONB NOT NULL DEFAULT '[]'::jsonb,
      canales_default JSONB NOT NULL DEFAULT '["push","email"]'::jsonb,
      activa_por_defecto BOOLEAN NOT NULL DEFAULT true,
      CONSTRAINT ck_alertas_catalogo_rango CHECK (umbral_min <= umbral_default AND umbral_default <= umbral_max)
    );

    CREATE TABLE alertas_configuracion ({base},
      clave_alerta VARCHAR(60) NOT NULL REFERENCES alertas_catalogo(clave),
      tenant_id UUID REFERENCES tenants(id),
      prestador_id UUID REFERENCES prestadores(id),
      umbral_valor NUMERIC(12,2) NOT NULL,
      parametros JSONB NOT NULL DEFAULT '{{}}'::jsonb,
      canales_json JSONB NOT NULL DEFAULT '["push","email"]'::jsonb,
      destinatarios_roles_json JSONB NOT NULL DEFAULT '[]'::jsonb,
      activa BOOLEAN NOT NULL DEFAULT true,
      CONSTRAINT ck_alertas_configuracion_duenio CHECK ((tenant_id IS NULL) <> (prestador_id IS NULL))
    );
    CREATE UNIQUE INDEX uq_alertas_configuracion ON alertas_configuracion
      (clave_alerta, COALESCE(tenant_id, '00000000-0000-0000-0000-000000000000'::uuid),
       COALESCE(prestador_id, '00000000-0000-0000-0000-000000000000'::uuid));

    CREATE TABLE alertas_historial (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      clave_alerta VARCHAR(60) NOT NULL REFERENCES alertas_catalogo(clave),
      tenant_id UUID REFERENCES tenants(id),
      prestador_id UUID REFERENCES prestadores(id),
      entidad_tipo VARCHAR(60),
      entidad_id UUID,
      umbral_en_momento NUMERIC(12,2),
      datos_contexto_json JSONB NOT NULL DEFAULT '{{}}'::jsonb,
      estado estado_alerta NOT NULL DEFAULT 'disparada',
      timestamp_disparo TIMESTAMPTZ NOT NULL DEFAULT now(),
      timestamp_vista TIMESTAMPTZ,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE INDEX ix_alertas_historial_disparo ON alertas_historial (timestamp_disparo DESC);
    CREATE INDEX ix_alertas_historial_updated ON alertas_historial (updated_at);

    CREATE TABLE alertas_supresiones ({base},
      clave_alerta VARCHAR(60) NOT NULL REFERENCES alertas_catalogo(clave),
      tenant_id UUID REFERENCES tenants(id),
      prestador_id UUID REFERENCES prestadores(id),
      entidad_id UUID,
      suprimida_por UUID REFERENCES usuarios(id),
      razon TEXT NOT NULL,
      desde TIMESTAMPTZ NOT NULL DEFAULT now(),
      hasta TIMESTAMPTZ NOT NULL,
      activa BOOLEAN NOT NULL DEFAULT true,
      CONSTRAINT ck_alertas_supresiones_duenio CHECK ((tenant_id IS NULL) <> (prestador_id IS NULL)),
      CONSTRAINT ck_alertas_supresiones_rango CHECK (hasta > desde)
    );

    CREATE TABLE configuracion_tenant ({base},
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      clave VARCHAR(80) NOT NULL,
      valor JSONB NOT NULL,
      CONSTRAINT uq_configuracion_tenant UNIQUE (tenant_id, clave)
    );
    CREATE TABLE configuracion_prestador ({base},
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      clave VARCHAR(80) NOT NULL,
      valor JSONB NOT NULL,
      CONSTRAINT uq_configuracion_prestador UNIQUE (prestador_id, clave)
    );

    CREATE TABLE sesiones (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      usuario_id UUID NOT NULL REFERENCES usuarios(id),
      familia_id UUID NOT NULL,
      padre_id UUID REFERENCES sesiones(id) ON DELETE SET NULL,
      token_hash VARCHAR(64) NOT NULL UNIQUE,
      dispositivo VARCHAR(200),
      user_agent TEXT,
      ip_origen VARCHAR(64),
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      ultimo_acceso_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      expira_at TIMESTAMPTZ NOT NULL,
      rotada_at TIMESTAMPTZ,
      revocada_at TIMESTAMPTZ,
      motivo_revocacion VARCHAR(60)
    );
    CREATE INDEX ix_sesiones_usuario ON sesiones (usuario_id);
    CREATE INDEX ix_sesiones_familia ON sesiones (familia_id);

    CREATE TABLE intentos_fallidos (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      ip_origen VARCHAR(64) NOT NULL,
      email VARCHAR(254),
      usuario_id UUID,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE INDEX ix_intentos_fallidos_ip ON intentos_fallidos (ip_origen, created_at DESC);
    """)

    for t in TABLAS_VERSIONADAS:
        ex(f"CREATE INDEX ix_{t}_updated_at ON {t} (updated_at);")
        ex(f"CREATE TRIGGER trg_{t}_version BEFORE INSERT OR UPDATE ON {t} FOR EACH ROW EXECUTE FUNCTION acma_version();")

    # ----------------------------------------- auditoría particionada (§6.9.5)
    ex("""
    CREATE TABLE audit_log (
      id UUID NOT NULL DEFAULT gen_random_uuid(),
      evento_tipo VARCHAR(80) NOT NULL,
      actor_id UUID,
      actor_rol VARCHAR(40),
      tenant_id UUID,
      prestador_id UUID,
      recurso_tipo VARCHAR(80),
      recurso_id VARCHAR(80),
      valor_anterior_json JSONB,
      valor_nuevo_json JSONB,
      ip_origen VARCHAR(64),
      user_agent TEXT,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      PRIMARY KEY (id, created_at)
    ) PARTITION BY RANGE (created_at);
    CREATE INDEX ix_audit_log_created ON audit_log (created_at DESC);
    CREATE INDEX ix_audit_log_tenant ON audit_log (tenant_id, created_at DESC);
    CREATE INDEX ix_audit_log_evento ON audit_log (evento_tipo, created_at DESC);

    CREATE TABLE audit_accesos_api (
      id UUID NOT NULL DEFAULT gen_random_uuid(),
      metodo VARCHAR(10) NOT NULL,
      ruta VARCHAR(300) NOT NULL,
      codigo_respuesta SMALLINT NOT NULL,
      duracion_ms INTEGER NOT NULL,
      usuario_id UUID,
      tenant_id UUID,
      prestador_id UUID,
      ip_origen VARCHAR(64),
      user_agent TEXT,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      PRIMARY KEY (id, created_at)
    ) PARTITION BY RANGE (created_at);
    CREATE INDEX ix_audit_accesos_api_created ON audit_accesos_api (created_at DESC);

    CREATE TABLE audit_log_default PARTITION OF audit_log DEFAULT;
    CREATE TABLE audit_accesos_api_default PARTITION OF audit_accesos_api DEFAULT;

    -- Crea particiones mensuales desde el mes actual hasta N meses adelante (beat mensual).
    CREATE FUNCTION acma_crear_particiones_auditoria(meses_adelante INTEGER DEFAULT 3) RETURNS INTEGER
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
    DECLARE
      base_tabla TEXT;
      inicio DATE;
      fin DATE;
      nombre TEXT;
      creadas INTEGER := 0;
    BEGIN
      FOREACH base_tabla IN ARRAY ARRAY['audit_log','audit_accesos_api'] LOOP
        FOR i IN 0..meses_adelante LOOP
          inicio := (date_trunc('month', now()) + make_interval(months => i))::date;
          fin := (inicio + interval '1 month')::date;
          nombre := format('%s_%s', base_tabla, to_char(inicio, 'YYYY_MM'));
          IF to_regclass(nombre) IS NULL THEN
            EXECUTE format('CREATE TABLE %I PARTITION OF %I FOR VALUES FROM (%L) TO (%L)', nombre, base_tabla, inicio, fin);
            creadas := creadas + 1;
          END IF;
        END LOOP;
      END LOOP;
      RETURN creadas;
    END $$;
    SELECT acma_crear_particiones_auditoria(3);

    CREATE TRIGGER trg_audit_log_inmutable BEFORE UPDATE OR DELETE ON audit_log
      FOR EACH ROW EXECUTE FUNCTION acma_auditoria_inmutable();
    CREATE TRIGGER trg_audit_log_truncate BEFORE TRUNCATE ON audit_log
      FOR EACH STATEMENT EXECUTE FUNCTION acma_auditoria_inmutable();
    CREATE TRIGGER trg_audit_accesos_api_inmutable BEFORE UPDATE OR DELETE ON audit_accesos_api
      FOR EACH ROW EXECUTE FUNCTION acma_auditoria_inmutable();
    """)

    # ------------------------------------------------------ datos semilla
    for clave, nombre, dominio, mfa, desc in ROLES:
        ex(f"INSERT INTO roles (clave, nombre, dominio, mfa_obligatorio, descripcion) VALUES "
           f"({_lit(clave)}, {_lit(nombre)}, {_lit(dominio)}, {_lit(mfa)}, {_lit(desc)});")
    for clave, aplica, default, desc in PERMISOS:
        ex(f"INSERT INTO permisos_catalogo (clave, aplica_a, valor_default, descripcion) VALUES "
           f"({_lit(clave)}, {_lit(aplica)}, {_lit(default)}, {_lit(desc)});")
    for clave, desc, umbral, tipo, mn, mx, params, modulo, prompt, dest in ALERTAS:
        dest_json = "[" + ",".join(f'"{d}"' for d in dest) + "]"
        ex(
            "INSERT INTO alertas_catalogo (clave, descripcion, umbral_default, umbral_min, umbral_max, tipo_umbral,"
            " parametros_default, modulo_origen, prompt_origen, destinatarios_default) VALUES "
            f"({_lit(clave)}, {_lit(desc)}, {umbral}, {mn}, {mx}, {_lit(tipo)}, {_lit(params or '{}')}::jsonb,"
            f" {_lit(modulo)}, {_lit(prompt)}, {_lit(dest_json)}::jsonb);"
        )

    # -------------------------------------------- contexto RLS (§3 de P01)
    ex("""
    CREATE FUNCTION acma_ctx_usuario() RETURNS UUID LANGUAGE sql STABLE AS
      $$ SELECT NULLIF(current_setting('app.usuario_id', true), '')::uuid $$;
    CREATE FUNCTION acma_ctx_tenant() RETURNS UUID LANGUAGE sql STABLE AS
      $$ SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid $$;
    CREATE FUNCTION acma_ctx_prestador() RETURNS UUID LANGUAGE sql STABLE AS
      $$ SELECT NULLIF(current_setting('app.prestador_id', true), '')::uuid $$;
    CREATE FUNCTION acma_ctx_rol() RETURNS TEXT LANGUAGE sql STABLE AS
      $$ SELECT COALESCE(current_setting('app.rol', true), '') $$;

    -- Política específica por rol: superadmin (y el rol técnico 'sistema' de Celery/scripts).
    CREATE FUNCTION acma_es_plataforma() RETURNS BOOLEAN LANGUAGE sql STABLE AS
      $$ SELECT acma_ctx_rol() IN ('superadmin', 'sistema') $$;
    -- Hay contexto autenticado (cualquier rol). Sin contexto: false.
    CREATE FUNCTION acma_hay_contexto() RETURNS BOOLEAN LANGUAGE sql STABLE AS
      $$ SELECT acma_ctx_rol() <> '' $$;

    -- Relaciones tenant↔prestador vigentes. SECURITY DEFINER para no depender de la RLS de tenant_prestador.
    CREATE FUNCTION acma_tenants_del_prestador() RETURNS UUID[]
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
      SELECT COALESCE(array_agg(tenant_id), '{}') FROM tenant_prestador
       WHERE prestador_id = acma_ctx_prestador() AND estado = 'activo'
         AND vigencia_inicio <= current_date AND (vigencia_fin IS NULL OR vigencia_fin >= current_date)
    $$;
    CREATE FUNCTION acma_prestadores_del_tenant() RETURNS UUID[]
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
      SELECT COALESCE(array_agg(prestador_id), '{}') FROM tenant_prestador
       WHERE tenant_id = acma_ctx_tenant() AND estado = 'activo'
         AND vigencia_inicio <= current_date AND (vigencia_fin IS NULL OR vigencia_fin >= current_date)
    $$;
    CREATE FUNCTION acma_tenant_visible(t UUID) RETURNS BOOLEAN LANGUAGE sql STABLE AS $$
      SELECT acma_es_plataforma() OR t = acma_ctx_tenant()
          OR (acma_ctx_prestador() IS NOT NULL AND t = ANY (acma_tenants_del_prestador()))
    $$;
    CREATE FUNCTION acma_prestador_visible(p UUID) RETURNS BOOLEAN LANGUAGE sql STABLE AS $$
      SELECT acma_es_plataforma() OR p = acma_ctx_prestador()
          OR (acma_ctx_tenant() IS NOT NULL AND p = ANY (acma_prestadores_del_tenant()))
    $$;

    -- Bootstrap de autenticación: búsquedas mínimas antes de que exista contexto. La RLS forzada aplica también al
    -- dueño del esquema, por eso estas funciones pertenecen a acma_auth (NOLOGIN, BYPASSRLS, ver docker/postgres).
    CREATE FUNCTION auth_identidad_por_email(p_email TEXT)
    RETURNS TABLE (id UUID, rol rol_usuario, tenant_id UUID, prestador_id UUID)
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
      SELECT u.id, u.rol, u.tenant_id, u.prestador_id FROM usuarios u WHERE lower(u.email) = lower(p_email)
    $$;
    CREATE FUNCTION auth_identidad_por_id(p_id UUID)
    RETURNS TABLE (id UUID, rol rol_usuario, tenant_id UUID, prestador_id UUID)
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
      SELECT u.id, u.rol, u.tenant_id, u.prestador_id FROM usuarios u WHERE u.id = p_id
    $$;
    CREATE FUNCTION auth_usuario_de_sesion(p_token_hash TEXT) RETURNS UUID
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
      SELECT s.usuario_id FROM sesiones s WHERE s.token_hash = p_token_hash
    $$;
    CREATE FUNCTION auth_registrar_intento_fallido(p_ip TEXT, p_email TEXT, p_usuario UUID) RETURNS VOID
    LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path = public, pg_temp AS $$
      INSERT INTO intentos_fallidos (ip_origen, email, usuario_id) VALUES (p_ip, p_email, p_usuario)
    $$;
    CREATE FUNCTION auth_fallos_recientes_ip(p_ip TEXT, p_minutos INTEGER) RETURNS INTEGER
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
      SELECT count(*)::int FROM intentos_fallidos
       WHERE ip_origen = p_ip AND created_at > now() - make_interval(mins => p_minutos)
    $$;
    """)

    ex("""
    GRANT SELECT ON usuarios, sesiones TO acma_auth;
    GRANT SELECT, INSERT ON intentos_fallidos TO acma_auth;
    GRANT CREATE ON SCHEMA public TO acma_auth;
    ALTER FUNCTION auth_identidad_por_email(TEXT) OWNER TO acma_auth;
    ALTER FUNCTION auth_identidad_por_id(UUID) OWNER TO acma_auth;
    ALTER FUNCTION auth_usuario_de_sesion(TEXT) OWNER TO acma_auth;
    ALTER FUNCTION auth_registrar_intento_fallido(TEXT, TEXT, UUID) OWNER TO acma_auth;
    ALTER FUNCTION auth_fallos_recientes_ip(TEXT, INTEGER) OWNER TO acma_auth;
    REVOKE CREATE ON SCHEMA public FROM acma_auth;
    """)

    # ------------------------------------------------- políticas RLS
    def rls(tabla: str, *politicas: str) -> None:
        ex(f"ALTER TABLE {tabla} ENABLE ROW LEVEL SECURITY; ALTER TABLE {tabla} FORCE ROW LEVEL SECURITY;")
        for p in politicas:
            ex(p)

    # Catálogos globales: lectura con cualquier contexto autenticado; escritura solo plataforma.
    for t in ("roles", "permisos_catalogo", "alertas_catalogo"):
        rls(
            t,
            f"CREATE POLICY {t}_lectura ON {t} FOR SELECT USING (acma_hay_contexto());",
            f"CREATE POLICY {t}_plataforma ON {t} FOR ALL USING (acma_es_plataforma()) WITH CHECK (acma_es_plataforma());",
        )

    rls(
        "tenants",
        "CREATE POLICY tenants_lectura ON tenants FOR SELECT USING (acma_tenant_visible(id));",
        "CREATE POLICY tenants_escritura ON tenants FOR UPDATE USING (acma_es_plataforma() OR id = acma_ctx_tenant())"
        " WITH CHECK (acma_es_plataforma() OR id = acma_ctx_tenant());",
        "CREATE POLICY tenants_plataforma ON tenants FOR ALL USING (acma_es_plataforma()) WITH CHECK (acma_es_plataforma());",
    )
    rls(
        "prestadores",
        "CREATE POLICY prestadores_lectura ON prestadores FOR SELECT USING (acma_prestador_visible(id));",
        "CREATE POLICY prestadores_escritura ON prestadores FOR UPDATE USING (acma_es_plataforma() OR id = acma_ctx_prestador())"
        " WITH CHECK (acma_es_plataforma() OR id = acma_ctx_prestador());",
        "CREATE POLICY prestadores_plataforma ON prestadores FOR ALL USING (acma_es_plataforma()) WITH CHECK (acma_es_plataforma());",
    )
    rls(
        "tenant_prestador",
        "CREATE POLICY tenant_prestador_lectura ON tenant_prestador FOR SELECT USING (acma_es_plataforma()"
        " OR tenant_id = acma_ctx_tenant() OR prestador_id = acma_ctx_prestador());",
        "CREATE POLICY tenant_prestador_plataforma ON tenant_prestador FOR ALL USING (acma_es_plataforma())"
        " WITH CHECK (acma_es_plataforma());",
    )
    rls(
        "usuarios",
        "CREATE POLICY usuarios_lectura ON usuarios FOR SELECT USING (acma_es_plataforma() OR id = acma_ctx_usuario()"
        " OR (tenant_id IS NOT NULL AND acma_tenant_visible(tenant_id))"
        " OR (prestador_id IS NOT NULL AND acma_prestador_visible(prestador_id)));",
        "CREATE POLICY usuarios_escritura ON usuarios FOR ALL USING (acma_es_plataforma() OR id = acma_ctx_usuario()"
        " OR tenant_id = acma_ctx_tenant() OR prestador_id = acma_ctx_prestador())"
        " WITH CHECK (acma_es_plataforma() OR id = acma_ctx_usuario()"
        " OR tenant_id = acma_ctx_tenant() OR prestador_id = acma_ctx_prestador());",
    )
    rls(
        "historial_contrasenas",
        "CREATE POLICY historial_contrasenas_propio ON historial_contrasenas FOR ALL"
        " USING (acma_es_plataforma() OR usuario_id = acma_ctx_usuario())"
        " WITH CHECK (acma_es_plataforma() OR usuario_id = acma_ctx_usuario());",
    )

    # Tablas del tenant: lectura para el tenant y sus prestadores vigentes; escritura solo el tenant.
    for t in ("grupos_un", "unidades_negocio", "grupo_un_miembros", "usuario_grupos", "usuario_un", "configuracion_tenant"):
        rls(
            t,
            f"CREATE POLICY {t}_lectura ON {t} FOR SELECT USING (acma_tenant_visible(tenant_id));",
            f"CREATE POLICY {t}_escritura ON {t} FOR ALL USING (acma_es_plataforma() OR tenant_id = acma_ctx_tenant())"
            f" WITH CHECK (acma_es_plataforma() OR tenant_id = acma_ctx_tenant());",
        )

    # Tablas del prestador: lectura y escritura solo del propio prestador.
    for t in ("permisos_tecnico", "grupos_tecnicos", "grupo_tecnico_permisos", "tecnico_grupo",
              "tecnico_permisos_override", "permisos_despachador", "permisos_despachador_log", "configuracion_prestador"):
        rls(
            t,
            f"CREATE POLICY {t}_prestador ON {t} FOR ALL USING (acma_es_plataforma() OR prestador_id = acma_ctx_prestador())"
            f" WITH CHECK (acma_es_plataforma() OR prestador_id = acma_ctx_prestador());",
        )

    # Contratos: los administra el prestador; el tenant los lee.
    for t in ("contratos", "contrato_sla"):
        rls(
            t,
            f"CREATE POLICY {t}_lectura ON {t} FOR SELECT USING (acma_es_plataforma()"
            f" OR tenant_id = acma_ctx_tenant() OR prestador_id = acma_ctx_prestador());",
            f"CREATE POLICY {t}_escritura ON {t} FOR ALL USING (acma_es_plataforma() OR prestador_id = acma_ctx_prestador())"
            f" WITH CHECK (acma_es_plataforma() OR prestador_id = acma_ctx_prestador());",
        )

    # Alertas por dueño (tenant o prestador).
    for t in ("alertas_configuracion", "alertas_historial", "alertas_supresiones"):
        rls(
            t,
            f"CREATE POLICY {t}_duenio ON {t} FOR ALL USING (acma_es_plataforma()"
            f" OR tenant_id = acma_ctx_tenant() OR prestador_id = acma_ctx_prestador())"
            f" WITH CHECK (acma_es_plataforma() OR tenant_id = acma_ctx_tenant() OR prestador_id = acma_ctx_prestador());",
        )

    # Sesiones: solo las propias. La búsqueda por hash usa auth_usuario_de_sesion().
    rls(
        "sesiones",
        "CREATE POLICY sesiones_propias ON sesiones FOR ALL USING (acma_es_plataforma() OR usuario_id = acma_ctx_usuario())"
        " WITH CHECK (acma_es_plataforma() OR usuario_id = acma_ctx_usuario());",
    )
    # Intentos fallidos: solo vía funciones SECURITY DEFINER o plataforma.
    rls(
        "intentos_fallidos",
        "CREATE POLICY intentos_fallidos_plataforma ON intentos_fallidos FOR ALL USING (acma_es_plataforma())"
        " WITH CHECK (acma_es_plataforma());",
    )

    # Auditoría: se puede insertar siempre (incluso un login fallido sin contexto); solo plataforma lee.
    for t in ("audit_log", "audit_accesos_api"):
        rls(
            t,
            f"CREATE POLICY {t}_insercion ON {t} FOR INSERT WITH CHECK (true);",
            f"CREATE POLICY {t}_lectura ON {t} FOR SELECT USING (acma_es_plataforma());",
            # Sin estas políticas un UPDATE/DELETE de plataforma afectaría 0 filas en silencio; con ellas
            # las filas llegan al trigger acma_auditoria_inmutable(), que lanza la excepción.
            f"CREATE POLICY {t}_bloqueo_update ON {t} FOR UPDATE USING (acma_es_plataforma());",
            f"CREATE POLICY {t}_bloqueo_delete ON {t} FOR DELETE USING (acma_es_plataforma());",
        )

    # ------------------------------------------------------------ permisos
    ex("""
    GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO acma_api;
    REVOKE UPDATE, DELETE, TRUNCATE ON audit_log, audit_accesos_api FROM acma_api;
    REVOKE UPDATE, DELETE, TRUNCATE ON permisos_despachador_log FROM acma_api;
    ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO acma_api;
    ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT EXECUTE ON FUNCTIONS TO acma_api;
    GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO acma_api;
    """)
    # Particiones: acceso solo a través de la tabla padre (que aplica RLS).
    ex("""
    DO $$ DECLARE r RECORD; BEGIN
      FOR r IN SELECT c.relname FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid
               JOIN pg_class p ON p.oid = i.inhparent WHERE p.relname IN ('audit_log','audit_accesos_api') LOOP
        EXECUTE format('REVOKE ALL ON %I FROM acma_api', r.relname);
      END LOOP;
    END $$;
    """)


def downgrade() -> None:
    tablas = [
        "audit_accesos_api", "audit_log", "intentos_fallidos", "sesiones", "configuracion_prestador",
        "configuracion_tenant", "alertas_supresiones", "alertas_historial", "alertas_configuracion",
        "alertas_catalogo", "contrato_sla", "contratos", "usuario_un", "usuario_grupos", "grupo_un_miembros",
        "unidades_negocio", "grupos_un", "permisos_despachador_log", "permisos_despachador",
        "tecnico_permisos_override", "tecnico_grupo", "grupo_tecnico_permisos", "grupos_tecnicos",
        "permisos_tecnico", "permisos_catalogo", "historial_contrasenas", "usuarios", "tenant_prestador",
        "prestadores", "tenants", "roles",
    ]
    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM acma_auth;")
    for t in tablas:
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE;")
    for f in (
        "auth_fallos_recientes_ip(TEXT, INTEGER)", "auth_registrar_intento_fallido(TEXT, TEXT, UUID)",
        "auth_usuario_de_sesion(TEXT)", "auth_identidad_por_id(UUID)", "auth_identidad_por_email(TEXT)",
        "acma_prestador_visible(UUID)", "acma_tenant_visible(UUID)", "acma_prestadores_del_tenant()",
        "acma_tenants_del_prestador()", "acma_hay_contexto()", "acma_es_plataforma()", "acma_ctx_rol()",
        "acma_ctx_prestador()", "acma_ctx_tenant()", "acma_ctx_usuario()",
        "acma_crear_particiones_auditoria(INTEGER)", "acma_auditoria_inmutable()", "acma_version()",
    ):
        op.execute(f"DROP FUNCTION IF EXISTS {f} CASCADE;")
    for tipo in ("estado_alerta", "aplica_permiso", "tipo_umbral", "tipo_penalizacion", "unidad_tiempo",
                 "modalidad_contrato", "nivel_severidad", "estado_registro", "dominio_usuario", "rol_usuario"):
        op.execute(f"DROP TYPE IF EXISTS {tipo};")
