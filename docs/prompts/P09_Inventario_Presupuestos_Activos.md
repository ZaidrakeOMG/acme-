# P09 — Inventario, caja chica manual, costos del folio, presupuestos, exportación ERP y ficha de activos (Fase 1, prompt 9 de 11)

## Contexto

P08 está cerrado (commit `4eaa5d9`; 277 pytest y 68 vitest en verde). Lee antes de empezar `CONTEXTO.md` (secciones "Folios (P04)", "Campo, offline y chat (P05)" — en particular el gancho de inventario *merge con alerta* de `sync/mutaciones` —, "Preventivos y reasignaciones (P06)" — el gancho de refacción en la reasignación y `plan_materiales.articulo_id` sin FK —, "Minuta y seguimiento (P07)" — períodos presupuestales y monto potencial de Por presupuesto —, "Trabajos especiales y OC (P08)" — ganchos de costo — y todas las decisiones pendientes), `BITACORA.md`, y en `ACMA_Documento_Diseno_v2.5.docx`: §6.4 completo (tres orígenes de refacciones), §6.5 (fondo fijo de caja chica, formatos de reposición y sus 4 tablas), §6.6 (capa desacoplada, operaciones, tabla `erp_eventos_pendientes`, exportación universal), §6.8.5 (presupuestos por grupo), §6.8.6 (`folio_refacciones` y datos financieros del archivo del folio), §6.9.4 completo (TCO, depreciación, alerta de reemplazo y sus 4 tablas), §6.10.8 (inventario del técnico compartido entre tenants), §6.8.3 (permisos `ver_costo_refacciones` y `usar_caja_chica`) y §4.1 (módulos Gestión de inventario, Caja chica, Integración ERP, Presupuesto y control de gasto, Equipos y activos). En `ACMA_Alcance_Fases_v1.0.docx`, sección 3 y 4: el OCR, la validación CFDI ante el SAT, los adaptadores CONTPAQi/Microsip, la facturación CFDI con PAC, la criticidad automática y el FMEA son **Fase 2**.

Este prompt construye la capa económica del sistema: qué se consume, cuánto cuesta cada folio, contra qué presupuesto se carga y cuánto ha costado cada equipo. Lo que dependa de proveedores externos queda detrás de interfaces con implementación `stub` y su tabla creada.

## Objetivo

Que el prestador controle su inventario por almacén y por vehículo con los tres orígenes de §6.4, que cada folio cierre con su costo desglosado, que la caja chica funcione con captura manual y reposición diaria exportable, que el cliente vea su gasto contra presupuesto por UN, grupo y tipo de actividad con alertas, que el contador del prestador reciba la exportación universal para su ERP, y que cada equipo tenga ficha con historial, depreciación, TCO y alerta de reemplazo.

## Entregables

### 1. Migración `0009_inventario_costos_activos.py`

Con los helpers de `core/sql_migracion.py`, RLS forzada en toda tabla con `tenant_id`/`prestador_id`.

**Inventario (§6.4, §4.1):**

| Tabla | Campos clave |
|---|---|
| `articulos` | prestador_id, codigo (único por prestador), numero_parte, descripcion, unidad, categoria, costo_unitario_vigente, stock_minimo_default, activo |
| `ubicaciones_inventario` | prestador_id, tipo ENUM(`almacen` / `vehiculo`), nombre, tecnico_id (nullable: el vehículo pertenece a un técnico), placas, activo |
| `existencias` | ubicacion_id, articulo_id, cantidad, stock_minimo (nullable = default del artículo), costo_promedio, updated_at; UNIQUE(ubicacion_id, articulo_id) |
| `movimientos_inventario` | prestador_id, articulo_id, ubicacion_origen_id (nullable), ubicacion_destino_id (nullable), tipo ENUM(`entrada` / `salida` / `traspaso` / `ajuste` / `consumo_folio`), cantidad, costo_unitario, origen ENUM(`almacen` / `oc` / `caja_chica`), folio_id (nullable), oc_id (nullable), gasto_caja_chica_id (nullable), referencia_externa, registrado_por, timestamp_dispositivo, timestamp — **append-only** |
| `ordenes_compra` | prestador_id, numero (correlativo `OC-000001`), folio_id (nullable), tenant_id (nullable), proveedor, estado ENUM(`borrador` / `aprobada` / `enviada_erp` / `recibida` / `cancelada`), total, aprobada_por, numero_oc_erp (nullable, Fase 2 lo llena el adaptador), created_by |
| `orden_compra_partidas` | oc_id, articulo_id, cantidad, costo_unitario, recibido |

Completar FKs diferidas: `folio_refacciones.articulo_id → articulos.id` (nullable, conservando la descripción libre para registros previos), `plan_materiales.articulo_id → articulos.id`, `folio_refacciones.gasto_caja_chica_id → gastos_caja_chica.id`.

**Caja chica (§6.5, las 4 tablas, más la configuración):** `fondos_caja_chica` (prestador_id, tecnico_id, monto_inicial, saldo_actual, fecha_ultima_reposicion, activo), `gastos_caja_chica` (folio_id, tecnico_id, fondo_id, proveedor, rfc_proveedor, uuid_cfdi (nullable), descripcion, numero_parte, subtotal, iva, monto, estado ENUM(`capturado` / `aprobado` / `rechazado`), estado_cfdi ENUM(`no_validado` / `vigente` / `cancelado` / `no_encontrado`) default `no_validado`, imagen_key, aprobado_por, razon_rechazo, centro_costos, cuenta_contable), `polizas_exportacion` (fecha, prestador_id, fondo_id nullable, total, formato ENUM(`excel` / `xml` / `api`), archivo_key, estado ENUM(`pendiente` / `enviado` / `contabilizado`)), `validaciones_cfdi` (uuid, rfc_emisor, estado_fiscal, timestamp_validacion — creada vacía, la llena Fase 2).

**Costos del folio:** `folio_costos` (folio_id único, costo_refacciones, costo_mano_obra, costo_otros, costo_total, moneda, centro_costos, horas_mano_obra, tarifa_hora, validado_por, validado_at, documento_erp_ref (nullable)); `tarifas_mano_obra` (prestador_id, tenant_id nullable, tipo_folio nullable, tarifa_hora, moneda, vigente_desde).

**Presupuestos (§4.1, §6.8.5):** `presupuestos` (tenant_id, un_id nullable, grupo_id nullable — exactamente uno de los dos —, tipo_actividad ENUM(`correctivo` / `preventivo` / `especial` / `todos`), periodo_inicio, periodo_fin, monto, moneda, umbrales_alerta_json default `[50,80,100]`, created_by) — cubre también `presupuestos_grupo` de §6.8.5 con `grupo_id` (anotar la unificación); `presupuesto_consumos` (presupuesto_id, folio_id, monto, fecha, tipo) — append-only, alimentado al validar el costo del folio.

**ERP (§6.6):** `erp_eventos_pendientes` (prestador_id, tenant_id nullable, operacion ENUM(`generar_oc` / `registrar_gasto` / `crear_activo_fijo` / `poliza_caja_chica`), entidad, entidad_id, payload_json, estado ENUM(`pendiente` / `procesado` / `error` / `omitido`), intentos, ultimo_error, adaptador (nullable), respuesta_json, created_at) — en Fase 1 los eventos se generan y quedan `pendiente`; `erp_configuracion` (prestador_id, adaptador ENUM(`ninguno` / `contpaqi` / `microsip`) default `ninguno`, columnas_excel_json, cuentas_contables_json, centros_costos_json); `erp_exportaciones` (prestador_id, periodo_inicio, periodo_fin, formato, archivo_key, generado_por, eventos_incluidos).

**Activos (§6.9.4):** agregar a `equipos` `costo_adquisicion`, `fecha_adquisicion`, `costo_hora_inactividad` (o por tipo de equipo en `tipos_equipo.costo_hora_inactividad_default` configurado por el tenant; anotar cuál se elige) y `numero_activo_fijo_erp` (nullable); crear `activo_depreciacion`, `activo_depreciacion_historial`, `activo_tco_snapshot` y `activo_reemplazo_alertas` con los campos literales de §6.9.4, más `umbral_reemplazo_pct` en `configuracion_tenant` (default 70, anotar).

### 2. Inventario (`services/inventario_service.py`)

- Catálogo de artículos, almacenes y vehículos (uno por técnico, creado al dar de alta al técnico si el prestador lo configura) — Admin prestador escribe; Despachador y Mesa de control consultan; Técnico ve su vehículo.
- Movimientos: entrada a almacén (manual o importación CSV con el importador de P02, nuevo catálogo `existencias`), traspaso almacén → vehículo (carga de la unidad), ajuste con razón, y consumo en folio. Cada movimiento recalcula `existencias` y `costo_promedio` (promedio ponderado; anotar) en la misma transacción.
- Tipo A almacén (§6.4): en Fase 1 la fuente de verdad es ACMA con carga manual o CSV; la sincronización bidireccional con el ERP del prestador queda como evento `erp_eventos_pendientes` y adaptador `stub` (Fase 2). Anotar.
- Tipo B orden de compra (§6.4): Despachador o Admin prestador crean la OC desde el folio cuando el técnico reporta `pendiente_refaccion` (P04); aprobación por Admin prestador; al aprobarse se genera el evento `generar_oc`; al marcarla `recibida` entra al almacén y queda disponible para asignarse al folio; el folio puede volver a `en_ejecucion` con `transicionar()`.
- Tipo C caja chica: ver sección 3.
- Consumo en folio: `POST /api/folios/{id}/refacciones` (endpoint de P04) ahora acepta `articulo_id` y descuenta del vehículo del técnico (o del almacén si el técnico lo indica); sin `articulo_id` se mantiene la descripción libre con origen y costo (para compras fuera de catálogo). En técnicos compartidos (§6.10.8) se descuenta del inventario del prestador y el costo se imputa al tenant del folio.
- Sincronización offline (P05): implementar el gancho *merge con alerta* de §6.2: ambos consumos offline se aplican; si la existencia queda negativa se registra el conflicto en `sincronizacion_conflictos` y se dispara la alerta `STOCK_NEGATIVO` al Despachador.
- Reasignación (P06): llenar `refaccion_ok` en `reasignacion_validaciones` comparando `plan_materiales` / refacciones previstas del folio contra el vehículo del técnico destino; la advertencia y la confirmación explícita ya existen.
- Alertas nuevas: `STOCK_MINIMO` (por ubicación y artículo), `STOCK_NEGATIVO`, `OC_SIN_APROBAR`, `OC_SIN_RECIBIR` (días configurables).

### 3. Caja chica con captura manual (§6.4 Tipo C y §6.5)

- Fondo fijo por técnico (Admin prestador): monto autorizado y saldo; el técnico requiere el permiso `usar_caja_chica` (P02).
- Flujo de Fase 1 (sin OCR): el técnico, desde la atención del folio en la app de campo (P05, operable offline), toma la foto de la factura (evidencia de tipo `factura`) y captura proveedor, RFC, UUID opcional, descripción, número de parte, subtotal, IVA y total; el admin prestador recibe notificación (`notificar()` de P07) con los datos y la foto y aprueba con un toque o rechaza con razón. Al aprobar, en una sola transacción y literal de §6.4: alta de la refacción vinculada al folio, movimiento de inventario entrada + salida inmediata con origen `caja_chica`, y el gasto que afecta `saldo_actual` del fondo. El folio se desbloquea para cierre.
- La validación del CFDI contra el SAT y la extracción OCR quedan detrás de `services/ocr.py` y `services/sat_validator.py` con implementación `stub` que devuelve `no_validado`; la interfaz muestra "Validación SAT disponible en Fase 2". Anotar.
- Reposición diaria (§6.5): tarea beat al cierre de jornada que consolida los gastos aprobados del día por fondo y genera el documento de reposición en los formatos que no requieren adaptador: Excel con las columnas literales de §6.5 (fecha, proveedor, RFC, folio fiscal, descripción, monto, IVA, total, centro de costos, cuenta contable, técnico, folio de servicio) y XML de póliza estándar; registra `polizas_exportacion` y el evento `poliza_caja_chica`. Reposición del fondo por Admin prestador restableciendo el saldo con registro.
- Alertas nuevas: `GASTO_CAJA_CHICA_SIN_APROBAR`, `FONDO_CAJA_CHICA_BAJO` (porcentaje configurable).

### 4. Costo del folio

- Al cerrar el folio (gancho en `transicionar(cerrado)` de P04), calcular `folio_costos`: refacciones (suma de `folio_refacciones` con su costo), mano de obra (horas entre `fecha_inicio_atencion` y `fecha_cierre`, o capturadas por el técnico si el formulario las trae, × tarifa vigente de `tarifas_mano_obra`; anotar la regla), y otros. Mesa de control o Admin prestador validan el costo (`POST /api/folios/{id}/costos/validar`), con ajuste y razón; al validarse se genera el evento `registrar_gasto` y se registran los consumos de presupuesto.
- Visibilidad por permiso: el técnico ve costos solo con `ver_costo_refacciones`; el cliente ve el costo total y el desglose del folio en su detalle.
- Completar la sección "Datos financieros" del detalle del folio (P04) que hoy dice "vacía hasta P09", y el monto en el detalle del trabajo especial (P08) con el costo real de su folio operativo.

### 5. Presupuestos y control de gasto (§4.1, §6.8.5)

- CRUD de presupuestos por Admin empresa: por UN o por grupo de UNs, por tipo de actividad y período (reutilizar `periodos_presupuestales` de P07 para proponer los períodos).
- Consumo: al validarse el costo de un folio, registrar el consumo en todos los presupuestos aplicables (el de su UN, el de cada grupo al que pertenece la UN, por tipo de actividad y `todos`), dentro del período por fecha de cierre.
- Vista consolidada para Admin empresa (jerarquía Tenant → Grupo → UN de §6.8.5): presupuesto, consumido, comprometido (folios autorizados aún sin cerrar con monto estimado, anotar), disponible, porcentaje y desviación; detalle de folios por presupuesto.
- Alertas configurables por umbral (`umbrales_alerta_json`): `PRESUPUESTO_UMBRAL_ALCANZADO` y `PRESUPUESTO_EXCEDIDO`, a Admin empresa y al Admin UN o responsable del grupo.
- Integrar en P07: el monto potencial de "Por presupuesto" usa ahora costos reales; la regla por monto del flujo multinivel (P04) puede considerar el disponible (no cambiar la regla, solo mostrar el disponible al aprobador).

### 6. Exportación ERP universal (§6.6) y capa desacoplada

- Generación de eventos `erp_eventos_pendientes` en las cuatro operaciones de §6.6 (OC aprobada, costo de folio validado, equipo nuevo instalado de P08, póliza de caja chica), sin adaptador activo.
- Interfaz `services/erp/base.py` con adaptadores `stub` para `contpaqi` y `microsip` (registran y dejan el evento en `omitido` con motivo "adaptador Fase 2").
- Exportación universal por período (`POST /api/erp/exportaciones`, Admin prestador): XML con estructura estándar de pólizas contables y Excel con columnas configurables en `erp_configuracion.columnas_excel_json`; marca los eventos incluidos. Tarea beat opcional al cierre de período.
- Pantalla para Admin prestador: configuración de columnas, cuentas contables y centros de costos; bandeja de eventos con estado; historial de exportaciones con descarga.

### 7. Ficha de activos, depreciación y TCO (§6.9.4)

- Ficha de equipo (`GET /api/activos/{equipo_id}`): datos del equipo, contrato y garantía, criticidad manual (P04), historial completo de folios con tipo de falla, costos y causa, preventivos con desvío, refacciones consumidas, depreciación y TCO.
- Depreciación con los cuatro métodos literales de §6.9.4: línea recta, doble saldo decreciente, unidades de producción (sin medidores en Fase 1: queda configurable pero responde `REQUIERE_MEDIDORES_FASE_2` y el sistema usa el último valor manual; anotar) y manual. Tarea beat mensual que escribe `activo_depreciacion_historial`.
- TCO mensual en `activo_tco_snapshot` con los componentes literales: adquisición, preventivos, correctivos, refacciones, downtime (horas de inactividad = tiempo entre `fecha_falla` y `fecha_cierre` de correctivos, × costo por hora configurado por el tenant; anotar la regla) y valor residual; `porcentaje_vs_reposicion`.
- Alerta de reemplazo: cuando `tco_total` supera `umbral_reemplazo_pct` del `valor_reposicion`, registrar en `activo_reemplazo_alertas` y alertar al Admin empresa (`ACTIVO_REEMPLAZO_RECOMENDADO`); el Admin empresa acepta, lo que genera un trabajo especial de reemplazo (§6.9.4) con el servicio de P08 en estado `creado`, con la UN, el equipo y una descripción precargada para que el prestador lo cotice y envíe (anotar quién figura como creador), o pospone con razón obligatoria.
- Criticidad A/B/C/D automática, FMEA, MTBF y MTTR: Fase 2 (ISO 55000). La ficha muestra la criticidad manual y las etiquetas "Fase 2" donde corresponda.

### 8. Frontend

Agregar `ruta` y página en `PAGINAS` de `App.tsx` para los módulos ya previstos en `src/config/modulos.ts` (`inventario`, `caja_chica`, `presupuestos`, `activos`, `erp`), confirmando roles de §4.1:

- `pages/inventario/Inventario.tsx` (Admin prestador, Despachador, Mesa de control; Técnico solo su vehículo): artículos, existencias por almacén y vehículo con indicador de stock mínimo, movimientos (entrada, traspaso, ajuste), importación CSV, órdenes de compra con aprobación y recepción.
- `pages/caja_chica/CajaChica.tsx`: fondos por técnico con saldo, bandeja de gastos por aprobar con foto y datos y aprobación en un toque, pólizas de reposición con descarga Excel y XML. En la app del técnico (P05): captura de gasto desde la atención del folio, operable sin señal, y saldo de su fondo.
- `pages/presupuestos/Presupuestos.tsx` (Admin empresa; Admin UN solo lectura de sus UNs): alta por UN o grupo, tipo y período; tablero consolidado Tenant → Grupo → UN con barras de consumo y semáforo por umbral (texto además del color); detalle de folios cargados.
- `pages/activos/Activos.tsx` y `pages/activos/FichaEquipo.tsx` (Admin empresa, Admin UN, Admin prestador; Técnico la ficha si tiene `ver_historial_equipo`): listado con TCO y alerta de reemplazo; ficha con historial, depreciación (configuración del método y gráfica de valor en libros) y TCO por componente; decisión de reemplazo.
- `pages/erp/Erp.tsx` (Admin prestador): configuración, eventos y exportaciones; adaptadores visibles como "Fase 2".
- `FolioDetalle.tsx`: sección "Datos financieros" con el desglose y la validación de costo; refacciones con selector de artículo y existencia del vehículo; botón "Generar OC" en `pendiente_refaccion`.

### 9. Seed y pruebas

- Seed: 25 artículos en 4 categorías, 1 almacén y un vehículo por técnico con existencias (2 artículos bajo mínimo), 3 OC (borrador, aprobada, recibida), fondos de caja chica para 2 técnicos con 5 gastos (aprobados, pendiente y rechazado) y una póliza del día anterior, tarifas de mano de obra, costos validados en los folios cerrados del seed, presupuestos trimestrales por UN y por el grupo demo con uno al 85 % y otro excedido, configuración ERP con columnas y eventos generados, depreciación y costo de adquisición en 6 equipos con snapshots de 12 meses y un equipo con alerta de reemplazo.
- Backend (`tests/test_inventario.py`, `tests/test_ordenes_compra.py`, `tests/test_caja_chica.py`, `tests/test_folio_costos.py`, `tests/test_presupuestos.py`, `tests/test_erp_exportacion.py`, `tests/test_activos_tco.py`): existencias y costo promedio por cada tipo de movimiento; inmutabilidad de `movimientos_inventario`; consumo desde vehículo y desde almacén; técnico compartido entre tenants imputa al tenant correcto; merge offline con stock negativo y alerta; `refaccion_ok` en reasignación; OC completa hasta reabrir el folio en ejecución; caja chica: aprobación crea los tres registros en una transacción y descuenta saldo, rechazo no afecta, permiso `usar_caja_chica`, reposición diaria en Excel con las 12 columnas y en XML, reposición del fondo; costo del folio al cierre y validación con ajuste; consumo en presupuestos de UN, grupo y tipo; umbrales y excedido; vista consolidada; eventos ERP en las 4 operaciones y adaptadores stub; exportación universal por período; depreciación con línea recta y doble saldo (casos numéricos), unidades de producción responde `REQUIERE_MEDIDORES_FASE_2`; TCO con sus 6 componentes; alerta de reemplazo y sus dos decisiones; permisos `ver_costo_refacciones`; aislamiento entre tenants y prestadores; RLS forzada en todas las tablas nuevas.
- Frontend: traspaso al vehículo, aprobación de gasto en un toque, tablero de presupuesto con semáforo, ficha de equipo con TCO, sección financiera del folio.
- `pytest`, `vitest`, `tsc --noEmit` y `npm run build` en verde.

## Reglas (vigentes)

1. Seguir el Documento de Diseño v2.5; lo no definido se anota en `CONTEXTO.md` como decisión pendiente de validación.
2. Multitenancy validado en servicio además de RLS.
3. Sin proveedores externos de pago (OCR, SAT, PAC y adaptadores ERP en `stub`).
4. Identificadores en español sin acentos.
5. Cerrar con `CONTEXTO.md` (avance P09 ✅; sección "Inventario, costos y activos (P09)" con el cálculo del costo del folio, el registro de consumos de presupuesto, los eventos ERP y los ganchos que P10 debe usar para SLA, penalizaciones y reportes) y `BITACORA.md` actualizados.
6. No cambiar el stack.
7. No correr la suite completa de pytest con los servidores de desarrollo encendidos (la máquina se queda sin memoria); detenerlos antes.

## Al terminar

Resumen en español con: tablas de la migración 0009, endpoints, tareas Celery y alertas nuevas, reglas de cálculo elegidas (costo promedio, mano de obra, downtime, comprometido), decisiones pendientes nuevas y conteo de pruebas.
