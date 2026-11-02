"""0009 — Inventario con los tres orígenes de refacciones (§6.4), fondo fijo de caja chica (§6.5), costo del folio,
presupuestos por UN y grupo (§6.8.5), capa desacoplada de ERP (§6.6) y ficha de activos con depreciación y TCO (§6.9.4). P09.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-30
"""
from alembic import op

from core.sql_migracion import ex, politicas_prestador, politicas_tenant, rls, versionar

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

TABLAS = [
    "articulos", "ubicaciones_inventario", "existencias", "movimientos_inventario", "ordenes_compra", "orden_compra_partidas",
    "fondos_caja_chica", "gastos_caja_chica", "polizas_exportacion", "validaciones_cfdi",
    "folio_costos", "tarifas_mano_obra", "presupuestos", "presupuesto_consumos",
    "erp_eventos_pendientes", "erp_configuracion", "erp_exportaciones",
    "activo_depreciacion", "activo_depreciacion_historial", "activo_tco_snapshot", "activo_reemplazo_alertas",
]
ENUMS = [
    "tipo_ubicacion_inventario", "tipo_movimiento_inventario", "estado_orden_compra", "estado_gasto_caja_chica", "estado_cfdi",
    "formato_poliza", "estado_poliza", "tipo_actividad_presupuesto", "operacion_erp", "estado_evento_erp", "adaptador_erp",
    "metodo_depreciacion", "decision_reemplazo",
]
# Alertas nuevas. Del catálogo base de P01 se reutilizan STOCK_MINIMO, FONDO_CAJA_CHICA_BAJO y ACTIVO_REEMPLAZO (reciben evaluador aquí).
ALERTAS = [
    ("STOCK_NEGATIVO", "La existencia de un artículo quedó negativa al aplicar consumos offline (merge con alerta, §6.2).", 0, 0, 1000, "cantidad", "inventario", '["despachador","admin_prestador"]'),
    ("OC_SIN_APROBAR", "Orden de compra en borrador sin aprobar por más de X días.", 2, 1, 30, "dias", "inventario", '["admin_prestador","despachador"]'),
    ("OC_SIN_RECIBIR", "Orden de compra aprobada sin recibir por más de X días.", 7, 1, 90, "dias", "inventario", '["admin_prestador","despachador","mesa_control"]'),
    ("GASTO_CAJA_CHICA_SIN_APROBAR", "Gasto de caja chica capturado sin aprobar por más de X horas.", 24, 1, 168, "horas", "caja_chica", '["admin_prestador"]'),
    ("PRESUPUESTO_UMBRAL_ALCANZADO", "El consumo del presupuesto alcanzó uno de los umbrales configurados (umbrales_alerta_json).", 80, 10, 100, "porcentaje", "presupuestos", '["admin_empresa","admin_un"]'),
    ("PRESUPUESTO_EXCEDIDO", "El consumo del presupuesto superó el 100% del monto asignado.", 100, 100, 200, "porcentaje", "presupuestos", '["admin_empresa","admin_un","admin_prestador"]'),
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


def _append_only_prestador(t: str) -> tuple[str, ...]:
    return (
        f"CREATE POLICY {t}_lectura ON {t} FOR SELECT USING (acma_prestador_visible(prestador_id));",
        f"CREATE POLICY {t}_insercion ON {t} FOR INSERT WITH CHECK (acma_es_plataforma() OR prestador_id = acma_ctx_prestador());",
    )


# Tablas del cliente que el prestador que lo atiende también escribe (costo validado por Mesa de control, TCO recalculado
# por el Admin prestador): la escritura usa `acma_tenant_visible`, no solo el tenant del contexto.
ESCRITURA_TENANT_VISIBLE = "(acma_es_plataforma() OR acma_tenant_visible(tenant_id))"


def _append_only_tenant(t: str) -> tuple[str, ...]:
    return (
        f"CREATE POLICY {t}_lectura ON {t} FOR SELECT USING (acma_tenant_visible(tenant_id));",
        f"CREATE POLICY {t}_insercion ON {t} FOR INSERT WITH CHECK ({ESCRITURA_TENANT_VISIBLE});",
    )


def _politicas_tenant_visible(t: str) -> tuple[str, ...]:
    return (
        f"CREATE POLICY {t}_lectura ON {t} FOR SELECT USING (acma_tenant_visible(tenant_id));",
        f"CREATE POLICY {t}_insercion ON {t} FOR INSERT WITH CHECK ({ESCRITURA_TENANT_VISIBLE});",
        f"CREATE POLICY {t}_actualizacion ON {t} FOR UPDATE USING ({ESCRITURA_TENANT_VISIBLE}) WITH CHECK ({ESCRITURA_TENANT_VISIBLE});",
        f"CREATE POLICY {t}_borrado ON {t} FOR DELETE USING ({ESCRITURA_TENANT_VISIBLE});",
    )


def upgrade() -> None:
    ex("SELECT set_config('app.rol', 'sistema', true);")
    ex("""
    CREATE TYPE tipo_ubicacion_inventario AS ENUM ('almacen','vehiculo');
    CREATE TYPE tipo_movimiento_inventario AS ENUM ('entrada','salida','traspaso','ajuste','consumo_folio');
    CREATE TYPE estado_orden_compra AS ENUM ('borrador','aprobada','enviada_erp','recibida','cancelada');
    CREATE TYPE estado_gasto_caja_chica AS ENUM ('capturado','aprobado','rechazado');
    CREATE TYPE estado_cfdi AS ENUM ('no_validado','vigente','cancelado','no_encontrado');
    CREATE TYPE formato_poliza AS ENUM ('excel','xml','api');
    CREATE TYPE estado_poliza AS ENUM ('pendiente','enviado','contabilizado');
    CREATE TYPE tipo_actividad_presupuesto AS ENUM ('correctivo','preventivo','especial','todos');
    CREATE TYPE operacion_erp AS ENUM ('generar_oc','registrar_gasto','crear_activo_fijo','poliza_caja_chica');
    CREATE TYPE estado_evento_erp AS ENUM ('pendiente','procesado','error','omitido');
    CREATE TYPE adaptador_erp AS ENUM ('ninguno','contpaqi','microsip');
    CREATE TYPE metodo_depreciacion AS ENUM ('linea_recta','doble_saldo_decreciente','unidades_produccion','manual');
    CREATE TYPE decision_reemplazo AS ENUM ('aceptado','pospuesto');
    """)

    # --------------------------------------------------------- inventario (§6.4)
    ex(f"""
    CREATE TABLE articulos ({base},
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      codigo VARCHAR(60) NOT NULL,
      numero_parte VARCHAR(80),
      descripcion VARCHAR(200) NOT NULL,
      unidad VARCHAR(30) NOT NULL DEFAULT 'pieza',
      categoria VARCHAR(80) NOT NULL DEFAULT '',
      costo_unitario_vigente NUMERIC(14,2) NOT NULL DEFAULT 0,
      stock_minimo_default NUMERIC(12,2) NOT NULL DEFAULT 0,
      activo BOOLEAN NOT NULL DEFAULT true,
      UNIQUE (prestador_id, codigo)
    );
    CREATE INDEX ix_articulos_prestador_categoria ON articulos (prestador_id, categoria);
    CREATE TABLE ubicaciones_inventario ({base},
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      tipo tipo_ubicacion_inventario NOT NULL DEFAULT 'almacen',
      nombre VARCHAR(120) NOT NULL,
      tecnico_id UUID REFERENCES usuarios(id),
      placas VARCHAR(20),
      activo BOOLEAN NOT NULL DEFAULT true
    );
    CREATE INDEX ix_ubicaciones_inventario_prestador ON ubicaciones_inventario (prestador_id, tipo);
    CREATE UNIQUE INDEX ux_ubicaciones_vehiculo_tecnico ON ubicaciones_inventario (tecnico_id) WHERE tipo = 'vehiculo' AND tecnico_id IS NOT NULL;
    CREATE TABLE existencias ({base},
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      ubicacion_id UUID NOT NULL REFERENCES ubicaciones_inventario(id),
      articulo_id UUID NOT NULL REFERENCES articulos(id),
      cantidad NUMERIC(14,2) NOT NULL DEFAULT 0,
      stock_minimo NUMERIC(12,2),
      costo_promedio NUMERIC(14,2) NOT NULL DEFAULT 0,
      UNIQUE (ubicacion_id, articulo_id)
    );
    CREATE INDEX ix_existencias_articulo ON existencias (articulo_id);
    CREATE TABLE movimientos_inventario (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      tenant_id UUID REFERENCES tenants(id),
      articulo_id UUID NOT NULL REFERENCES articulos(id),
      ubicacion_origen_id UUID REFERENCES ubicaciones_inventario(id),
      ubicacion_destino_id UUID REFERENCES ubicaciones_inventario(id),
      tipo tipo_movimiento_inventario NOT NULL,
      cantidad NUMERIC(14,2) NOT NULL,
      costo_unitario NUMERIC(14,2) NOT NULL DEFAULT 0,
      origen origen_refaccion NOT NULL DEFAULT 'almacen',
      folio_id UUID REFERENCES folios(id),
      oc_id UUID,
      gasto_caja_chica_id UUID,
      refaccion_id UUID REFERENCES folio_refacciones(id),
      referencia_externa VARCHAR(120),
      razon TEXT NOT NULL DEFAULT '',
      registrado_por UUID REFERENCES usuarios(id),
      timestamp_dispositivo TIMESTAMPTZ,
      timestamp TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE INDEX ix_movimientos_inventario_articulo ON movimientos_inventario (articulo_id, timestamp);
    CREATE INDEX ix_movimientos_inventario_folio ON movimientos_inventario (folio_id);
    CREATE TRIGGER trg_movimientos_inventario_inmutable BEFORE UPDATE OR DELETE OR TRUNCATE ON movimientos_inventario
      FOR EACH STATEMENT EXECUTE FUNCTION acma_auditoria_inmutable();
    CREATE TABLE ordenes_compra ({base},
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      tenant_id UUID REFERENCES tenants(id),
      numero VARCHAR(20) NOT NULL,
      folio_id UUID REFERENCES folios(id),
      proveedor VARCHAR(200) NOT NULL DEFAULT '',
      estado estado_orden_compra NOT NULL DEFAULT 'borrador',
      estado_desde TIMESTAMPTZ NOT NULL DEFAULT now(),
      total NUMERIC(14,2) NOT NULL DEFAULT 0,
      moneda VARCHAR(3) NOT NULL DEFAULT 'MXN',
      ubicacion_destino_id UUID REFERENCES ubicaciones_inventario(id),
      notas TEXT NOT NULL DEFAULT '',
      aprobada_por UUID REFERENCES usuarios(id),
      aprobada_at TIMESTAMPTZ,
      recibida_at TIMESTAMPTZ,
      razon_cancelacion TEXT,
      numero_oc_erp VARCHAR(60),
      created_by UUID REFERENCES usuarios(id),
      UNIQUE (prestador_id, numero)
    );
    CREATE INDEX ix_ordenes_compra_estado ON ordenes_compra (prestador_id, estado);
    CREATE TABLE orden_compra_partidas ({base},
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      oc_id UUID NOT NULL REFERENCES ordenes_compra(id),
      articulo_id UUID NOT NULL REFERENCES articulos(id),
      cantidad NUMERIC(14,2) NOT NULL DEFAULT 1,
      costo_unitario NUMERIC(14,2) NOT NULL DEFAULT 0,
      recibido NUMERIC(14,2) NOT NULL DEFAULT 0
    );
    CREATE INDEX ix_orden_compra_partidas_oc ON orden_compra_partidas (oc_id);
    ALTER TABLE movimientos_inventario ADD CONSTRAINT fk_movimientos_oc FOREIGN KEY (oc_id) REFERENCES ordenes_compra(id);
    """)

    # ------------------------------------------------------- caja chica (§6.5)
    ex(f"""
    CREATE TABLE fondos_caja_chica ({base},
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      tecnico_id UUID NOT NULL REFERENCES usuarios(id),
      monto_inicial NUMERIC(14,2) NOT NULL DEFAULT 0,
      saldo_actual NUMERIC(14,2) NOT NULL DEFAULT 0,
      moneda VARCHAR(3) NOT NULL DEFAULT 'MXN',
      umbral_alerta_pct NUMERIC(5,2) NOT NULL DEFAULT 20,
      fecha_ultima_reposicion DATE,
      activo BOOLEAN NOT NULL DEFAULT true,
      UNIQUE (prestador_id, tecnico_id)
    );
    CREATE TABLE gastos_caja_chica ({base},
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      tenant_id UUID REFERENCES tenants(id),
      fondo_id UUID NOT NULL REFERENCES fondos_caja_chica(id),
      folio_id UUID REFERENCES folios(id),
      tecnico_id UUID NOT NULL REFERENCES usuarios(id),
      proveedor VARCHAR(200) NOT NULL DEFAULT '',
      rfc_proveedor VARCHAR(20),
      uuid_cfdi VARCHAR(40),
      descripcion VARCHAR(300) NOT NULL DEFAULT '',
      numero_parte VARCHAR(80),
      articulo_id UUID REFERENCES articulos(id),
      cantidad NUMERIC(12,2) NOT NULL DEFAULT 1,
      subtotal NUMERIC(14,2) NOT NULL DEFAULT 0,
      iva NUMERIC(14,2) NOT NULL DEFAULT 0,
      monto NUMERIC(14,2) NOT NULL DEFAULT 0,
      estado estado_gasto_caja_chica NOT NULL DEFAULT 'capturado',
      estado_cfdi estado_cfdi NOT NULL DEFAULT 'no_validado',
      imagen_key VARCHAR(300),
      evidencia_id UUID REFERENCES formulario_evidencias(id),
      aprobado_por UUID REFERENCES usuarios(id),
      aprobado_at TIMESTAMPTZ,
      razon_rechazo TEXT,
      centro_costos VARCHAR(80) NOT NULL DEFAULT '',
      cuenta_contable VARCHAR(40) NOT NULL DEFAULT '',
      poliza_id UUID,
      timestamp_dispositivo TIMESTAMPTZ,
      timestamp TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE INDEX ix_gastos_caja_chica_estado ON gastos_caja_chica (prestador_id, estado);
    CREATE INDEX ix_gastos_caja_chica_folio ON gastos_caja_chica (folio_id);
    CREATE TABLE polizas_exportacion ({base},
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      fondo_id UUID REFERENCES fondos_caja_chica(id),
      fecha DATE NOT NULL,
      total NUMERIC(14,2) NOT NULL DEFAULT 0,
      gastos INTEGER NOT NULL DEFAULT 0,
      formato formato_poliza NOT NULL DEFAULT 'excel',
      archivo_key VARCHAR(300),
      archivo_xml_key VARCHAR(300),
      estado estado_poliza NOT NULL DEFAULT 'pendiente',
      generado_por UUID REFERENCES usuarios(id),
      UNIQUE (prestador_id, fondo_id, fecha)
    );
    CREATE TABLE validaciones_cfdi ({base},
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      gasto_id UUID REFERENCES gastos_caja_chica(id),
      uuid_cfdi VARCHAR(40) NOT NULL,
      rfc_emisor VARCHAR(20),
      rfc_receptor VARCHAR(20),
      total NUMERIC(14,2),
      estado_fiscal estado_cfdi NOT NULL DEFAULT 'no_validado',
      detalle TEXT NOT NULL DEFAULT '',
      timestamp_validacion TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    ALTER TABLE gastos_caja_chica ADD CONSTRAINT fk_gastos_poliza FOREIGN KEY (poliza_id) REFERENCES polizas_exportacion(id);
    ALTER TABLE movimientos_inventario ADD CONSTRAINT fk_movimientos_gasto FOREIGN KEY (gasto_caja_chica_id) REFERENCES gastos_caja_chica(id);
    """)

    # ------------------------------------------------- costos del folio y tarifas
    ex(f"""
    CREATE TABLE folio_costos ({base},
      folio_id UUID NOT NULL UNIQUE REFERENCES folios(id),
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      costo_refacciones NUMERIC(14,2) NOT NULL DEFAULT 0,
      costo_mano_obra NUMERIC(14,2) NOT NULL DEFAULT 0,
      costo_otros NUMERIC(14,2) NOT NULL DEFAULT 0,
      costo_total NUMERIC(14,2) NOT NULL DEFAULT 0,
      moneda VARCHAR(3) NOT NULL DEFAULT 'MXN',
      centro_costos VARCHAR(80) NOT NULL DEFAULT '',
      horas_mano_obra NUMERIC(8,2) NOT NULL DEFAULT 0,
      tarifa_hora NUMERIC(14,2) NOT NULL DEFAULT 0,
      origen_horas VARCHAR(30) NOT NULL DEFAULT 'calculadas',
      ajuste NUMERIC(14,2) NOT NULL DEFAULT 0,
      razon_ajuste TEXT NOT NULL DEFAULT '',
      validado_por UUID REFERENCES usuarios(id),
      validado_at TIMESTAMPTZ,
      documento_erp_ref VARCHAR(80),
      detalle_json JSONB NOT NULL DEFAULT '{{}}'::jsonb
    );
    CREATE TABLE tarifas_mano_obra ({base},
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      tenant_id UUID REFERENCES tenants(id),
      tipo_folio tipo_folio,
      tarifa_hora NUMERIC(14,2) NOT NULL DEFAULT 0,
      moneda VARCHAR(3) NOT NULL DEFAULT 'MXN',
      vigente_desde DATE NOT NULL DEFAULT CURRENT_DATE,
      activa BOOLEAN NOT NULL DEFAULT true
    );
    CREATE INDEX ix_tarifas_mano_obra_prestador ON tarifas_mano_obra (prestador_id, vigente_desde);
    """)

    # ------------------------------------------------- presupuestos (§6.8.5)
    ex(f"""
    CREATE TABLE presupuestos ({base},
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      un_id UUID REFERENCES unidades_negocio(id),
      grupo_id UUID REFERENCES grupos_un(id),
      nombre VARCHAR(160) NOT NULL DEFAULT '',
      tipo_actividad tipo_actividad_presupuesto NOT NULL DEFAULT 'todos',
      periodo_inicio DATE NOT NULL,
      periodo_fin DATE NOT NULL,
      monto NUMERIC(14,2) NOT NULL DEFAULT 0,
      moneda VARCHAR(3) NOT NULL DEFAULT 'MXN',
      umbrales_alerta_json JSONB NOT NULL DEFAULT '[50,80,100]'::jsonb,
      activo BOOLEAN NOT NULL DEFAULT true,
      created_by UUID REFERENCES usuarios(id),
      CONSTRAINT ck_presupuesto_alcance CHECK ((un_id IS NOT NULL AND grupo_id IS NULL) OR (un_id IS NULL AND grupo_id IS NOT NULL)),
      CONSTRAINT ck_presupuesto_periodo CHECK (periodo_fin >= periodo_inicio)
    );
    CREATE INDEX ix_presupuestos_tenant_periodo ON presupuestos (tenant_id, periodo_inicio, periodo_fin);
    CREATE TABLE presupuesto_consumos (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      presupuesto_id UUID NOT NULL REFERENCES presupuestos(id),
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      folio_id UUID REFERENCES folios(id),
      un_id UUID REFERENCES unidades_negocio(id),
      monto NUMERIC(14,2) NOT NULL DEFAULT 0,
      fecha DATE NOT NULL DEFAULT CURRENT_DATE,
      tipo tipo_actividad_presupuesto NOT NULL DEFAULT 'todos',
      notas TEXT NOT NULL DEFAULT '',
      registrado_por UUID REFERENCES usuarios(id),
      UNIQUE (presupuesto_id, folio_id)
    );
    CREATE INDEX ix_presupuesto_consumos_presupuesto ON presupuesto_consumos (presupuesto_id, fecha);
    CREATE TRIGGER trg_presupuesto_consumos_inmutable BEFORE UPDATE OR DELETE OR TRUNCATE ON presupuesto_consumos
      FOR EACH STATEMENT EXECUTE FUNCTION acma_auditoria_inmutable();
    """)

    # ------------------------------------------------------------- ERP (§6.6)
    ex(f"""
    CREATE TABLE erp_eventos_pendientes (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      version_hash VARCHAR(64),
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      tenant_id UUID REFERENCES tenants(id),
      operacion operacion_erp NOT NULL,
      entidad VARCHAR(60) NOT NULL,
      entidad_id UUID,
      payload_json JSONB NOT NULL DEFAULT '{{}}'::jsonb,
      estado estado_evento_erp NOT NULL DEFAULT 'pendiente',
      intentos INTEGER NOT NULL DEFAULT 0,
      ultimo_error TEXT,
      adaptador adaptador_erp,
      respuesta_json JSONB NOT NULL DEFAULT '{{}}'::jsonb,
      exportacion_id UUID,
      procesado_at TIMESTAMPTZ
    );
    CREATE INDEX ix_erp_eventos_estado ON erp_eventos_pendientes (prestador_id, estado, created_at);
    CREATE TABLE erp_configuracion ({base},
      prestador_id UUID NOT NULL UNIQUE REFERENCES prestadores(id),
      adaptador adaptador_erp NOT NULL DEFAULT 'ninguno',
      columnas_excel_json JSONB NOT NULL DEFAULT '[]'::jsonb,
      cuentas_contables_json JSONB NOT NULL DEFAULT '{{}}'::jsonb,
      centros_costos_json JSONB NOT NULL DEFAULT '{{}}'::jsonb,
      exportacion_automatica BOOLEAN NOT NULL DEFAULT false
    );
    CREATE TABLE erp_exportaciones ({base},
      prestador_id UUID NOT NULL REFERENCES prestadores(id),
      periodo_inicio DATE NOT NULL,
      periodo_fin DATE NOT NULL,
      formato formato_poliza NOT NULL DEFAULT 'excel',
      archivo_key VARCHAR(300),
      archivo_xml_key VARCHAR(300),
      eventos_incluidos INTEGER NOT NULL DEFAULT 0,
      total NUMERIC(14,2) NOT NULL DEFAULT 0,
      generado_por UUID REFERENCES usuarios(id)
    );
    ALTER TABLE erp_eventos_pendientes ADD CONSTRAINT fk_erp_eventos_exportacion FOREIGN KEY (exportacion_id) REFERENCES erp_exportaciones(id);
    """)

    # ------------------------------------------------------- activos (§6.9.4)
    ex(f"""
    ALTER TABLE equipos ADD COLUMN costo_adquisicion NUMERIC(14,2);
    ALTER TABLE equipos ADD COLUMN fecha_adquisicion DATE;
    ALTER TABLE equipos ADD COLUMN costo_hora_inactividad NUMERIC(14,2);
    ALTER TABLE equipos ADD COLUMN numero_activo_fijo_erp VARCHAR(60);
    ALTER TABLE tipos_equipo ADD COLUMN costo_hora_inactividad_default NUMERIC(14,2);
    CREATE TABLE activo_depreciacion ({base},
      equipo_id UUID NOT NULL UNIQUE REFERENCES equipos(id),
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      metodo metodo_depreciacion NOT NULL DEFAULT 'linea_recta',
      vida_util_anios INTEGER NOT NULL DEFAULT 10,
      valor_salvamento NUMERIC(14,2) NOT NULL DEFAULT 0,
      valor_reposicion NUMERIC(14,2),
      unidades_vida_util NUMERIC(14,2),
      unidades_acumuladas NUMERIC(14,2) NOT NULL DEFAULT 0,
      valor_en_libros_manual NUMERIC(14,2),
      fecha_inicio DATE NOT NULL DEFAULT CURRENT_DATE,
      configurado_por UUID REFERENCES usuarios(id)
    );
    CREATE TABLE activo_depreciacion_historial (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      equipo_id UUID NOT NULL REFERENCES equipos(id),
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      periodo VARCHAR(10) NOT NULL,
      valor_en_libros NUMERIC(14,2) NOT NULL DEFAULT 0,
      depreciacion_periodo NUMERIC(14,2) NOT NULL DEFAULT 0,
      depreciacion_acumulada NUMERIC(14,2) NOT NULL DEFAULT 0,
      metodo_aplicado metodo_depreciacion NOT NULL DEFAULT 'linea_recta',
      calculado_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      UNIQUE (equipo_id, periodo)
    );
    CREATE TABLE activo_tco_snapshot ({base},
      equipo_id UUID NOT NULL REFERENCES equipos(id),
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      un_id UUID REFERENCES unidades_negocio(id),
      periodo VARCHAR(10) NOT NULL,
      costo_adquisicion NUMERIC(14,2) NOT NULL DEFAULT 0,
      costo_preventivos NUMERIC(14,2) NOT NULL DEFAULT 0,
      costo_correctivos NUMERIC(14,2) NOT NULL DEFAULT 0,
      costo_refacciones NUMERIC(14,2) NOT NULL DEFAULT 0,
      costo_downtime NUMERIC(14,2) NOT NULL DEFAULT 0,
      horas_downtime NUMERIC(12,2) NOT NULL DEFAULT 0,
      valor_residual NUMERIC(14,2) NOT NULL DEFAULT 0,
      tco_total NUMERIC(14,2) NOT NULL DEFAULT 0,
      valor_reposicion NUMERIC(14,2),
      porcentaje_vs_reposicion NUMERIC(7,2) NOT NULL DEFAULT 0,
      UNIQUE (equipo_id, periodo)
    );
    CREATE INDEX ix_activo_tco_tenant_periodo ON activo_tco_snapshot (tenant_id, periodo);
    CREATE TABLE activo_reemplazo_alertas ({base},
      equipo_id UUID NOT NULL REFERENCES equipos(id),
      tenant_id UUID NOT NULL REFERENCES tenants(id),
      fecha_alerta DATE NOT NULL DEFAULT CURRENT_DATE,
      tco_al_momento NUMERIC(14,2) NOT NULL DEFAULT 0,
      valor_reposicion NUMERIC(14,2) NOT NULL DEFAULT 0,
      porcentaje_umbral NUMERIC(7,2) NOT NULL DEFAULT 0,
      porcentaje_alcanzado NUMERIC(7,2) NOT NULL DEFAULT 0,
      decision decision_reemplazo,
      razon TEXT NOT NULL DEFAULT '',
      decidido_por UUID REFERENCES usuarios(id),
      decidido_at TIMESTAMPTZ,
      trabajo_especial_id UUID REFERENCES trabajos_especiales(id)
    );
    CREATE INDEX ix_activo_reemplazo_tenant ON activo_reemplazo_alertas (tenant_id, decision);
    """)

    # --------------------------------------------- FKs diferidas de P04 y P06
    ex("""
    ALTER TABLE folio_refacciones ADD CONSTRAINT fk_folio_refacciones_articulo FOREIGN KEY (articulo_id) REFERENCES articulos(id);
    ALTER TABLE folio_refacciones ADD CONSTRAINT fk_folio_refacciones_gasto FOREIGN KEY (gasto_caja_chica_id) REFERENCES gastos_caja_chica(id);
    ALTER TABLE plan_materiales ADD CONSTRAINT fk_plan_materiales_articulo FOREIGN KEY (articulo_id) REFERENCES articulos(id);
    ALTER TABLE folio_refacciones ADD COLUMN ubicacion_id UUID REFERENCES ubicaciones_inventario(id);
    """)

    versionar(*[t for t in TABLAS if t not in ("movimientos_inventario", "presupuesto_consumos", "erp_eventos_pendientes", "activo_depreciacion_historial")])
    ex("CREATE INDEX ix_erp_eventos_pendientes_updated_at ON erp_eventos_pendientes (updated_at);"
       " CREATE TRIGGER trg_erp_eventos_pendientes_version BEFORE INSERT OR UPDATE ON erp_eventos_pendientes FOR EACH ROW EXECUTE FUNCTION acma_version();")

    # ------------------------------------------------------------------ RLS
    for t in ("articulos", "ubicaciones_inventario", "existencias", "orden_compra_partidas", "fondos_caja_chica", "gastos_caja_chica",
              "polizas_exportacion", "validaciones_cfdi", "tarifas_mano_obra", "erp_configuracion", "erp_exportaciones", "erp_eventos_pendientes"):
        rls(t, *politicas_prestador(t))
    # Órdenes de compra: el tenant del folio también las consulta (§6.4 Tipo B).
    rls("ordenes_compra",
        "CREATE POLICY ordenes_compra_lectura ON ordenes_compra FOR SELECT USING (acma_prestador_visible(prestador_id) OR (tenant_id IS NOT NULL AND acma_tenant_visible(tenant_id)));",
        *politicas_prestador("ordenes_compra"))
    rls("movimientos_inventario", *_append_only_prestador("movimientos_inventario"))
    rls("folio_costos", *_politicas_folio("folio_costos"))
    for t in ("presupuestos", "activo_depreciacion"):
        rls(t, *politicas_tenant(t))
    for t in ("activo_tco_snapshot", "activo_reemplazo_alertas"):
        rls(t, *_politicas_tenant_visible(t))
    rls("presupuesto_consumos", *_append_only_tenant("presupuesto_consumos"))
    rls("activo_depreciacion_historial", *_append_only_tenant("activo_depreciacion_historial"))
    ex(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {', '.join(TABLAS)} TO acma_api;")

    # ------------------------------------------------------------- semillas
    for clave, desc, d, mn, mx, tipo, modulo, dest in ALERTAS:
        ex(f"""
        INSERT INTO alertas_catalogo (clave, descripcion, umbral_default, umbral_min, umbral_max, tipo_umbral, modulo_origen, prompt_origen, destinatarios_default)
        VALUES ('{clave}', '{desc.replace("'", "''")}', {d}, {mn}, {mx}, '{tipo}', '{modulo}', 'P09', '{dest}'::jsonb);
        """)


def downgrade() -> None:
    ex("SELECT set_config('app.rol', 'sistema', true);")
    claves = ", ".join(f"'{a[0]}'" for a in ALERTAS)
    for t in ("alertas_historial", "alertas_configuracion", "alertas_supresiones"):
        ex(f"DELETE FROM {t} WHERE clave_alerta IN ({claves});")
    ex(f"DELETE FROM alertas_catalogo WHERE clave IN ({claves});")
    ex("""
    ALTER TABLE folio_refacciones DROP CONSTRAINT IF EXISTS fk_folio_refacciones_articulo;
    ALTER TABLE folio_refacciones DROP CONSTRAINT IF EXISTS fk_folio_refacciones_gasto;
    ALTER TABLE plan_materiales DROP CONSTRAINT IF EXISTS fk_plan_materiales_articulo;
    ALTER TABLE folio_refacciones DROP COLUMN IF EXISTS ubicacion_id;
    UPDATE folio_refacciones SET articulo_id = NULL, gasto_caja_chica_id = NULL;
    UPDATE plan_materiales SET articulo_id = NULL;
    ALTER TABLE equipos DROP COLUMN IF EXISTS costo_adquisicion;
    ALTER TABLE equipos DROP COLUMN IF EXISTS fecha_adquisicion;
    ALTER TABLE equipos DROP COLUMN IF EXISTS costo_hora_inactividad;
    ALTER TABLE equipos DROP COLUMN IF EXISTS numero_activo_fijo_erp;
    ALTER TABLE tipos_equipo DROP COLUMN IF EXISTS costo_hora_inactividad_default;
    """)
    for t in reversed(TABLAS):
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE;")
    for e in reversed(ENUMS):
        op.execute(f"DROP TYPE IF EXISTS {e};")
