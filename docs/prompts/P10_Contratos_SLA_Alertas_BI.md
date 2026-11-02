# P10 — Contratos y SLA, configuración central de alertas, dashboards y reportes ejecutivos (Fase 1, prompt 10 de 11)

## Contexto

P09 está cerrado. Lee antes de empezar `CONTEXTO.md` (todas las secciones de arquitectura, en particular "Folios (P04)" con `folio_sla` y los eventos para P10, "Minuta y seguimiento (P07)" con `excluir_sla_por_cliente` y el inicio del SLA al autorizar un folio no crítico, "Inventario, costos y activos (P09)" con el costo del folio, los consumos de presupuesto y los ganchos para P10, y todas las decisiones pendientes), `BITACORA.md`, y en `ACMA_Documento_Diseno_v2.5.docx`: §6.10.1 completo (estructura del contrato, niveles de severidad, reglas del contador de SLA, penalización y sus 5 tablas), §6.9.6 completo (catálogo de alertas, 4 tablas y principio de configuración), §6.8.4 solo los "Indicadores globales de jornada", §6.8.5 (jerarquía Tenant → Grupo → UN en reportes), §5.1 y §5.2 (qué ve cada rol: Supervisor de operadores, Supervisor del prestador, Dirección del prestador, Mesa de control), §7.5 (Dashboard ACMA), §4.1 (módulos Contratos y SLAs, Configuración central de alertas, Inteligencia de negocio), el glosario (MTBF y MTTR) y las actividades ACT-8.1, ACT-8.4 y ACT-8.5 del §8. En `ACMA_Alcance_Fases_v1.0.docx`: el mapa en vivo, GPS, desvíos de ruta, productividad y venta por técnico, medidores, certificaciones y criticidad automática son Fase 2.

Este prompt cierra el desarrollo funcional de Fase 1. P11 es solo endurecimiento y publicación.

## Objetivo

Que cada contrato mida su cumplimiento: el SLA de cada folio corre con pausas y exclusiones aprobadas, se calcula la penalización y se consolida por mes; que todas las alertas del sistema se configuren desde una sola pantalla dentro de los rangos que fija el Superadmin, con escalación a la Dirección del prestador; y que cada rol tenga su dashboard y sus reportes ejecutivos comparativos exportables y programables.

## Entregables

### 1. Migración `0010_sla_alertas_bi.py`

Con los helpers de `core/sql_migracion.py`, RLS forzada en toda tabla con `tenant_id`/`prestador_id`.

**Contratos y SLA (§6.10.1):**
- `contratos`: completar con `modalidad` ENUM(`evento` / `iguala`), `folios_correctivos_iguala`, `preventivos_iguala_json` (cantidad, periodicidad y referencia a puntos a revisar), `tarifa_iguala_mensual`, `moneda`, `activo` (lo que ya exista de P01–P04 se conserva).
- `contrato_sla`: completar con `tiempo_respuesta`, `tiempo_resolucion`, `unidad` ENUM(`horas` / `dias` / `semanas` / `meses`) con validación de 1 a 4,320 horas equivalentes, `penalizacion_tipo` ENUM(`monto` / `porcentaje`), `penalizacion_valor`, por cada uno de los 5 niveles de severidad.
- `folio_sla`: completar con los campos literales de §6.10.1 (`tiempo_inicio`, `tiempo_fin`, `tiempo_pausado_min`, `tiempo_exclusion_min`, `tiempo_efectivo_min`, `limite_sla_min`, `cumplimiento`, `penalizacion_calculada`) conservando los de P04 (respuesta y resolución prometida/real, cumplimiento de respuesta y de resolución) y la bandera `excluir_sla_por_cliente` de P07.
- `folio_sla_pausas` (folio_id, motivo ENUM(`reasignacion` / `otro`), inicio, fin) y `folio_sla_exclusiones` (folio_id, causa ENUM(`cliente_sin_acceso` / `fuerza_mayor` / `refaccion_no_disponible_mercado` / `otra`), descripcion, registrado_por, timestamp_inicio, timestamp_fin, aprobado_por, aprobada (nullable = pendiente), decidida_at, razon_decision).
- `penalizaciones_periodo` (contrato_id, periodo, total_folios, folios_incumplidos, monto_penalizacion, estado ENUM(`borrador` / `revisado` / `cerrado`), revisado_por, incluido_en_factura_id nullable — lo llenará el CFDI de Fase 2) y `iguala_consumo_periodo` (contrato_id, periodo, correctivos_incluidos, correctivos_atendidos, correctivos_adicionales, preventivos_incluidos, preventivos_ejecutados).

**Alertas (§6.9.6):** verificar que `alertas_catalogo`, `alertas_configuracion`, `alertas_historial` y `alertas_supresiones` tengan los campos literales de §6.9.6 y agregar los que falten: en el catálogo `umbral_default`, `tipo_umbral`, `modulo_origen`, `activa_por_defecto`, `umbral_minimo`, `umbral_maximo`, `destinatarios_roles_default_json`, `fase` (`1` / `2`) y `escalacion_de` (nullable, clave de la alerta que la origina); en el historial `umbral_en_momento`, `datos_contexto_json`, `timestamp_disparo`, `timestamp_vista`, `vista_por`, `atendida_at`, `atendida_por`, `escalada` (bool).

**Dashboards y reportes:** `reportes_programados` (tenant_id o prestador_id, tipo_reporte, filtros_json, formato ENUM(`pdf` / `excel`), periodicidad ENUM(`diaria` / `semanal` / `mensual`), dia_hora, destinatarios_json, activo, ultimo_envio_at, created_by) y `reportes_generados` (programado_id nullable, tipo_reporte, filtros_json, archivo_key, generado_por, generado_at).

### 2. Contador de SLA y penalizaciones (`services/sla_service.py`)

- Al crear el folio (P04) fijar `tiempo_inicio` en la captura (§6.10.1); para folios no críticos clasificados por el Admin UN (P07) el inicio es el momento de autorización, como ya quedó decidido; respetar `excluir_sla_por_cliente` de P07.
- Al autorizar, fijar los límites desde `contrato_sla` del contrato vigente y la severidad del folio (respuesta y resolución, convertidos a minutos).
- Pausa por reasignación (§6.10.1): abrir la pausa al entrar a `reasignado` y cerrarla al volver a `asignado` con el nuevo técnico. Como en Fase 1 la reasignación forzada es inmediata, la pausa será de segundos; anotar que el documento dice "reanuda cuando el nuevo técnico acepta" y que la aceptación explícita del técnico no existe en Fase 1. Registrar también como pausa el tiempo en `pendiente_informacion` (espera de datos del operador) y anotarlo como decisión pendiente.
- Exclusiones: el prestador (Despachador, Mesa de control, Admin prestador) registra causa, periodo y descripción; el Admin empresa aprueba o rechaza con razón (§6.10.1: "Admin prestador registro — Admin empresa aprobación"); solo los periodos aprobados se descuentan.
- Respuesta = de `tiempo_inicio` a `asignado` (o a `en_camino`, elegir y anotar); resolución = de `tiempo_inicio` a `cerrado`; `tiempo_efectivo_min = total − pausas − exclusiones aprobadas`; cumplimiento por cada uno; penalización solo si incumple la resolución (§6.10.1), por monto fijo o porcentaje sobre `folio_costos.costo_total` (P09).
- Todo el cálculo pasa por un gancho en `transicionar()` de P04 y se recalcula si se aprueba una exclusión después del cierre (el folio cerrado es inmutable, pero `folio_sla` no es parte del registro principal; confirmar contra el trigger de inmutabilidad de P04 y anotarlo).
- Penalizaciones del periodo: tarea beat mensual (y `POST /api/contratos/{id}/penalizaciones/calcular?periodo=`) que consolida `penalizaciones_periodo` por contrato, con detalle de folios; el Admin prestador lo revisa antes del cierre (`borrador` → `revisado` → `cerrado`). El descuento en la factura CFDI es Fase 2: dejar `incluido_en_factura_id` nulo y el resumen exportable en PDF y Excel.
- Iguala: consumo mensual de correctivos y preventivos incluidos contra los atendidos, con correctivos adicionales identificados; alerta `IGUALA_LIMITE_ALCANZADO`.
- Alertas: `SLA_RESPUESTA_EN_RIESGO` y `SLA_RESOLUCION_EN_RIESGO` (80 % consumido por defecto), `SLA_INCUMPLIDO`, `EXCLUSION_SLA_PENDIENTE` (al Admin empresa), `CONTRATO_POR_VENCER` (30 días antes, §6.10.1).

### 3. Configuración central de alertas (§6.9.6)

- Conciliar el catálogo completo: todas las claves registradas en P01–P09 más las de §6.9.6 con sus nombres literales. Donde un prompt anterior creó una clave equivalente con otro nombre (por ejemplo, `PRESUPUESTO_UMBRAL_ALCANZADO` de P09 frente a `PRESUPUESTO_ALERTA_1/2/3`, o `SEGUIMIENTO_INTERNO_SIN_ACTUALIZAR` frente a `SEGUIMIENTO_SIN_UPDATE`), dejar la clave literal del documento como canónica, migrar configuración e historial y conservar la anterior como alias en el evaluador; listar las conciliaciones en `CONTEXTO.md`.
- Alertas cuya fuente es Fase 2 (`TECNICO_TIEMPO_MUERTO`, `TECNICO_DESVIO_RUTA`, `TECNICO_SIN_SENAL`, `MEDIDOR_PROXIMO_PM`, `CERTIFICACION_VENCIDA`): en el catálogo con `fase = 2`, inactivas y visibles con la etiqueta "Fase 2".
- Principio literal de §6.9.6: el Superadmin define umbral por defecto y rango mínimo/máximo; tenants y prestadores ajustan su umbral, canales y roles destinatarios dentro del rango; sin configuración propia se usa el default. Validación en servidor con 422 fuera de rango.
- Escalación a la Dirección del prestador: `COTIZACION_ESCALADA_DIRECCION` medida desde el disparo de `COTIZACION_SIN_RESPUESTA` (no desde el envío), con umbral independiente (7 días por defecto); generalizar el mecanismo con `escalacion_de` para que el Admin prestador pueda configurar escalaciones a Dirección de otras alertas críticas (`SLA_INCUMPLIDO`, `PRESUPUESTO_ALERTA_3`, `REPROGRAMACION_ESCALADA_EMPRESA`) y anotarlo.
- `PREVENTIVO_DESVIO` (5 días) con `desvio_dias` de P06 y `FOLIO_SIN_CLASIFICAR` (24 h) con P07, si aún no existen con ese nombre.
- Panel de alertas para cada usuario: feed de alertas activas de sus destinatarios con marcar como vista, atender (con nota) y suprimir temporalmente (con razón, desde y hasta, solo roles administradores); historial filtrable.

### 4. Dashboards por rol (`services/bi_service.py`)

Todos con filtros por período y la jerarquía Tenant → Grupo de UNs → UN de §6.8.5, cálculos en el servidor y caché en Redis con TTL corto (anotar el valor). Cada indicador con su definición escrita en `docs/bi/indicadores.md` (fórmula, fuente, filtros), que es el entregable ACT-8.1.

- **Admin empresa:** gasto contra presupuesto (P09); cumplimiento de SLA de respuesta y resolución por severidad; MTTR (tiempo medio de reparación: de la captura al cierre de correctivos) y MTBF (tiempo medio entre fallas por equipo, a partir del historial de correctivos), según el glosario; folios por estado y por severidad; cumplimiento de preventivos y desvío promedio (P06); hallazgos y su conversión a cotización (P07); trabajos especiales y urgencias (P08); top 10 equipos por costo y por número de fallas; comparativo entre UNs, entre grupos y entre períodos.
- **Admin UN:** lo mismo limitado a sus UNs, más su calificación del período (P07).
- **Supervisor de operadores** (§5.1, literal): dashboard consolidado de sus grupos de UNs con conteo de folios por estado, alertas de SLA en riesgo y distribución por severidad, **sin acceso al detalle de cada folio, sin información financiera ni historial de folios cerrados**.
- **Admin prestador y Mesa de control:** folios por cliente y estado; cumplimiento de SLA por cliente y penalizaciones del periodo; consumo de iguala; cotizaciones (conversión y monto); carga de trabajo por técnico (folios asignados y cerrados en el periodo, sin productividad ni venta por técnico, que son Fase 2); preventivos y desvío; caja chica e inventario (resumen de P09).
- **Despachador:** barra de "Indicadores globales de jornada" de §6.8.4 sin mapa: folios completados / total del día, técnicos con folios activos, alertas abiertas y tiempo promedio de atención del día; integrada arriba del listado de folios de P04.
- **Supervisor del prestador** (§5.2): solo lectura de los dashboards del prestador y el reporte de cierre de jornada por correo (tarea beat diaria con `notificar()` de P07).
- **Dirección del prestador** (§5.2): dashboard ejecutivo de solo lectura (indicadores principales del prestador) e histórico de alertas de escalación.

### 5. Reportes ejecutivos exportables y programados (ACT-8.4)

- Plantillas por destinatario: Admin empresa (gasto, SLA, preventivos, hallazgos, comparativos multi-período), Admin prestador (clientes, SLA y penalizaciones, iguala, cotizaciones), Supervisor del prestador (cierre de jornada). Generación en servidor: PDF con el generador de P07 (WeasyPrint en Linux, respaldo en Windows) y Excel con openpyxl, con logo y colores del prestador.
- `POST /api/reportes/generar` (descarga inmediata) y CRUD de `reportes_programados` con tarea beat que genera y envía por correo según periodicidad; historial en `reportes_generados`.
- Comparativos multi-período: período actual contra anterior y contra el mismo período del año anterior cuando haya datos; volumen de prueba de 1,000+ folios (ACT-8.4) medido y anotado.

### 6. Frontend

- Módulo `contratos` (P01) ampliado: modalidad e iguala, SLA por severidad con unidad y penalización, vista de cumplimiento del contrato, penalizaciones del período con revisión y exportación, consumo de iguala, y bandeja de exclusiones (registro por el prestador, aprobación por Admin empresa). En `FolioDetalle.tsx`, sección SLA con contador (tiempo efectivo, límite, pausas, exclusiones y cumplimiento) y botón "Registrar exclusión".
- Módulo `alertas` (P01) rehecho como configuración central: tabla del catálogo agrupada por módulo con umbral por defecto, rango, umbral propio, canales y roles; columna "Fase 2" deshabilitada; configuración de escalaciones a Dirección; supresiones; historial. Panel de alertas del usuario accesible desde la campana de la cabecera junto a notificaciones (P07).
- Módulo `bi` (`src/config/modulos.ts`): `pages/bi/Dashboard.tsx` que muestra el tablero según el rol, con selector de período y de nivel (tenant, grupo, UN); gráficas con una librería de código abierto ya compatible con React 19 (Recharts u otra; elegir y anotar), colores accesibles y cada valor también en texto; tarjetas KPI con variación contra el período anterior; tablas de detalle con descarga Excel.
- `pages/bi/Reportes.tsx`: generar ahora y programados.
- Dashboards específicos de §5: Supervisor de operadores sin enlaces al detalle de folios ni montos; Dirección con su histórico de escalaciones.

### 7. Seed y pruebas

- Seed: contrato demo en modalidad iguala con 20 correctivos y 8 preventivos mensuales, SLA y penalización por las 5 severidades; `folio_sla` calculado para todos los folios del seed con al menos 3 incumplidos, 1 con pausa por reasignación, 2 exclusiones (una aprobada, una pendiente); penalizaciones de los últimos 3 meses; 12 meses de historial sintético (al menos 1,000 folios cerrados entre las 3 UNs, con costos y preventivos) generado por un script aparte `scripts/seed_historico.py` para no hacer lento el seed normal; configuraciones de alerta por tenant con una supresión activa y 2 escalaciones a Dirección en el historial; 2 reportes programados.
- Backend (`tests/test_sla.py`, `tests/test_penalizaciones.py`, `tests/test_alertas_config.py`, `tests/test_escalacion.py`, `tests/test_bi.py`, `tests/test_reportes.py`): contador con pausa, con exclusión aprobada y rechazada, cumplimiento de respuesta y resolución por severidad y unidad; penalización por monto y por porcentaje; recalculo tras exclusión aprobada después del cierre sin violar la inmutabilidad del folio; consolidado mensual e iguala; alertas de SLA en riesgo al 80 %; conciliación de claves con alias; umbral fuera de rango rechazado; default cuando no hay configuración; supresión; escalación medida desde la alerta origen; cada indicador del dashboard contra un cálculo manual en datos controlados (MTTR, MTBF, cumplimiento, gasto); el Supervisor de operadores no recibe montos ni detalle; PDF y Excel generados; reporte programado enviado por el modo stub de correo; tiempos con 1,000+ folios; aislamiento entre tenants y prestadores; RLS forzada en todas las tablas nuevas.
- Frontend: configuración de SLA del contrato, aprobación de exclusión, edición de umbral con validación de rango, dashboard por rol (Admin empresa y Supervisor de operadores), generación de reporte.
- `pytest`, `vitest`, `tsc --noEmit` y `npm run build` en verde.

## Reglas (vigentes)

1. Seguir el Documento de Diseño v2.5; lo no definido se anota en `CONTEXTO.md` como decisión pendiente de validación.
2. Multitenancy validado en servicio además de RLS.
3. Sin proveedores externos de pago.
4. Identificadores en español sin acentos.
5. Cerrar con `CONTEXTO.md` (avance P10 ✅; sección "SLA, alertas y BI (P10)" con las reglas del contador, la conciliación de claves de alerta, la lista de indicadores y lo que P11 debe revisar en rendimiento) y `BITACORA.md` actualizados.
6. No cambiar el stack.
7. No correr la suite completa de pytest con los servidores de desarrollo encendidos.
8. Si el trabajo es demasiado para una sola sesión, cerrar primero el backend con sus pruebas y un commit parcial "P10 (1/2)", y después el frontend con el commit "P10 (2/2)".

## Al terminar

Resumen en español con: tablas y campos de la migración 0010, endpoints, reglas del contador de SLA elegidas, conciliación de claves de alerta, lista de indicadores por rol, tareas Celery nuevas, decisiones pendientes nuevas, tiempos medidos con 1,000+ folios y conteo de pruebas.
