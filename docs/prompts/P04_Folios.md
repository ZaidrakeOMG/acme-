# P04 — Folios: ciclo de vida, validaciones y aprobación multinivel (Fase 1, prompt 4 de 11)

## Contexto

P03 está cerrado (commit `524465b`; 131 pytest y 33 vitest en verde). Lee antes de empezar `CONTEXTO.md` (secciones "Arquitectura vigente", "Catálogos maestros (P02)" y "Motor de formularios (P03)", y las decisiones pendientes 1–26), `BITACORA.md`, y en `ACMA_Documento_Diseno_v2.5.docx`: §4.1 (módulo Gestión de folios), §6.8.6 completo (11 estados, validaciones automáticas en captura, modelo de datos del ciclo de vida, estructura del archivo del folio, inmutabilidad), §6.8.7 completo (flujo de aprobación multinivel, 5 tablas), §6.10.1 (SLA por severidad) y la entrada 2.3 del control de versiones (quién puede crear folios).

Este prompt construye el folio como entidad central y su motor de estados. La app móvil del operador y del técnico, el modo offline, las evidencias en campo, la firma, la encuesta y el chat llegan en P05 sobre lo que aquí se entregue; la reasignación forzada en P06; los cuatro módulos de seguimiento en P07.

## Objetivo

Que un folio pueda capturarse con las validaciones automáticas de §6.8.6, recorrer sus 11 estados con las transiciones y actores permitidos, pasar por el flujo de aprobación multinivel de §6.8.7 con decisiones inmutables y timeouts, y quedar archivado con historial completo.

## Entregables

### 1. Migración `0004_folios.py`

Con los helpers de `core/sql_migracion.py`, RLS forzada y políticas en toda tabla con `tenant_id`/`prestador_id`, `acma_version()` donde corresponda.

**Ciclo de vida (§6.8.6):**

| Tabla | Campos clave |
|---|---|
| `folios` | id, numero_folio (correlativo por tenant con prefijo configurable en `configuracion_tenant`, p. ej. `CD-000123`), tenant_id, prestador_id, un_id, equipo_id, tipo_folio ENUM(`correctivo` / `preventivo` / `especial`), estado ENUM con los 11 estados (`capturado`, `en_revision`, `pendiente_informacion`, `autorizado`, `asignado`, `reasignado`, `en_camino`, `en_ejecucion`, `pendiente_refaccion`, `cerrado`, `cancelado`), prioridad, descripcion, tecnico_id (nullable), orden_en_ruta (nullable, Fase 2), ventana_inicio / ventana_fin (nullable, Fase 2), severidad_id, severidad_origen ENUM(`automatica_matriz` / `override_admin`), confirmacion_un (bool), confirmacion_un_timestamp, confirmacion_un_geolat, confirmacion_un_geolng, folio_duplicado_justificacion (nullable), folio_duplicado_ref_id (nullable, FK folios), monto_estimado (nullable), capturado_por, capturado_at, geolat_captura, geolng_captura, fecha_falla, fecha_inicio_atencion (nullable), fecha_cierre (nullable), razon_cancelacion (nullable), cancelado_por (nullable), created_at, updated_at, version_hash |
| `folio_estados_historial` | folio_id, estado_anterior, estado_nuevo, actor_id, actor_rol, timestamp, notas, datos_contexto_json — **append-only** (triggers como `audit_log`) |
| `folio_formulario_captura` | folio_id, respuesta_id (FK `formulario_respuestas`), formulario_id, version_formulario, timestamp |
| `folio_formulario_atencion` | folio_id, respuesta_id, formulario_id, version_formulario, timestamp |
| `folio_evidencias` | folio_id, evidencia_id (FK `formulario_evidencias`, nullable), tipo ENUM(`antes` / `durante` / `despues` / `firma` / `factura` / `otro`), archivo_key, geolat, geolng, timestamp_captura, subido_por |
| `folio_refacciones` | folio_id, articulo_id (sin FK hasta P09; anotarlo), descripcion, cantidad, origen ENUM(`almacen` / `oc` / `caja_chica`), costo_unitario, gasto_caja_chica_id (nullable, P09) |
| `folio_sla` | folio_id, nivel_severidad_id, tiempo_respuesta_prometido_horas, tiempo_resolucion_prometido_horas, tiempo_respuesta_real_min (nullable), tiempo_resolucion_real_min (nullable), cumplimiento_respuesta (nullable), cumplimiento_resolucion (nullable) — se llena el prometido al autorizar con `contrato_sla`; el real y las pausas los calcula P10 |
| `folio_encuesta` | folio_id, operador_id, nps_score, respuesta_id (FK `formulario_respuestas`), timestamp |
| `revision_manual_triggers` | folio_id, trigger_tipo ENUM(`sin_contrato` / `garantia` / `tipo_falla_flag` / `fuera_horario` / `keyword_alerta` / `severidad_no_configurada` / `confirmacion_un_faltante`), descripcion, timestamp |
| `folio_keywords_alerta` | prestador_id, tenant_id (nullable), palabra, activa — lista de palabras en la descripción libre que fuerzan En revisión (§6.8.6 "keyword de alerta detectada") |
| `folio_politicas_tenant` | tenant_id, bloqueo_total_duplicados (bool, §6.8.6), revision_obligatoria_garantia (bool, configurado por prestador: ponerlo en `configuracion_prestador` si prefieres), autorizacion_automatica_criticos (bool, §6.8.7), prefijo_folio |

**Aprobación multinivel (§6.8.7, las 5 tablas):** `aprobacion_reglas` (tenant_id, nivel 1-3, criterio ENUM(`monto` / `criticidad` / `tipo_trabajo`), operador, valor_json, activa), `aprobacion_flujos` (folio_id, nivel_actual, nivel_maximo_requerido, estado ENUM(`activo` / `aprobado` / `rechazado` / `bloqueado`), iniciado_at, resuelto_at), `aprobacion_niveles_config` (tenant_id, nivel, rol_aprobador, tiempo_limite_horas, comportamiento_timeout ENUM(`escalar` / `bloquear_alertar` / `autorizar_automatico` / `depende_criticidad`), notificar_por_json), `aprobacion_decisiones` (flujo_id, nivel, actor_id nullable, decision ENUM(`aprobado` / `rechazado` / `auto_aprobado` / `escalado` / `bloqueado`), razon_rechazo ENUM(`por_presupuesto` / `requiere_cotizacion` / `seguimiento_interno` / `reprogramar`) nullable, modulo_destino ENUM(`por_presupuesto` / `cotizaciones` / `seguimiento_interno` / `reprogramacion`) nullable, modulo_destino_id nullable (P07 lo llenará), canal ENUM(`push` / `app` / `minuta` / `sistema`), timestamp) — **append-only, ningún rol puede modificarla, incluido Superadmin** — y `aprobacion_alertas_timeout` (flujo_id, nivel, vence_at, procesado, accion_ejecutada).

**Contratos:** agregar a `contratos` los campos `horario_servicio_json` (días y horas por día, nullable = 24/7) y, si no existe, la relación con `contrato_sla` por severidad ya creada en P02.

**Equipos:** agregar `equipos.criticidad` ENUM(`A` / `B` / `C` / `D`) nullable, capturada manualmente por Admin empresa en Fase 1 (el cálculo automático de §6.9.3 es Fase 2). Anotar la decisión.

### 2. Motor de estados (`services/folio_estados.py`)

- Tabla de transiciones en código, literal de §6.8.6: estado origen → estados destino permitidos → roles que pueden ejecutarla (incluido el actor `sistema`). Cualquier transición fuera de la tabla devuelve 409 `TRANSICION_NO_PERMITIDA` con el detalle.
- Una única función `transicionar(db, folio, nuevo_estado, actor, notas, contexto)` que valida la transición, actualiza el folio, inserta en `folio_estados_historial`, registra auditoría con `auditoria.registrar_actor`, fija `fecha_inicio_atencion` al entrar a `en_ejecucion` y `fecha_cierre` al entrar a `cerrado`, y dispara los eventos de alerta correspondientes. Todas las rutas y los prompts posteriores (P05, P06, P10) deben usar esta función; ninguna escritura directa al campo `estado`.
- Inmutabilidad de §6.8.6: trigger en `folios` que rechaza UPDATE cuando el estado es `cerrado`, salvo que el único cambio sea `updated_at`/`version_hash`; en `cancelado` solo se permiten comentarios en el historial.
- Requisitos de entrada a `cerrado`: formulario de atención enviado (`folio_formulario_atencion` presente) y evidencia de tipo `firma` presente; si falta alguno, 409 `CIERRE_INCOMPLETO`. P05 provee la interfaz para cumplirlos; P04 provee los endpoints.

### 3. Captura y validaciones automáticas (`services/folios_captura_service.py`)

`POST /api/folios` recibe: un_id, equipo_id, tipo_falla_id, descripcion, confirmación de UN (bool + timestamp + geolocalización), geolocalización de captura, `respuesta_id` del formulario de captura (resuelto con `GET /api/formularios/resolver?tipo=captura_operador…`, P03) y, si aplica, `folio_duplicado_justificacion` o `folio_duplicado_ref_id`.

Quién puede crear (entrada 2.3 del control de versiones): Operador, Admin UN, Admin empresa, Supervisor de operadores y Mesa de control siempre; Técnico y Despachador solo si su permiso configurable `crear_folio_en_campo` / equivalente de despachador está habilitado para ese cliente (`permisos_service` de P02).

Mecanismos preventivos expuestos para el formulario: `GET /api/catalogos/equipos?un_id=&con_contrato=true` (P02) y `GET /api/folios/verificar-duplicado?equipo_id=` que devuelve, si existe folio abierto para el equipo, la tarjeta enriquecida de §6.8.6 (estado, técnico asignado y ETA si aplica).

Validaciones al enviar, en este orden y con este resultado literal de §6.8.6:
1. `confirmacion_un` verdadero; si no, el folio queda en `capturado` con trigger `confirmacion_un_faltante` y notificación al operador.
2. Equipo con contrato activo (`catalogos_service.equipo_con_contrato_activo`); si no → `en_revision` + trigger `sin_contrato` + alerta al despachador con el contrato vencido.
3. Duplicado abierto: si existe y el tenant tiene `bloqueo_total_duplicados`, 409 `FOLIO_DUPLICADO_BLOQUEADO`; si no lo tiene, exigir `folio_duplicado_justificacion` no vacía (confirmación fuerte) y guardar `folio_duplicado_ref_id`.
4. Severidad: `catalogos_service.resolver_severidad(tipo_falla, tipo_equipo del equipo)`; `severidad_origen = automatica_matriz`; si 404 → `en_revision` + trigger `severidad_no_configurada` + alerta `MATRIZ_SEVERIDAD_INCOMPLETA` (P02).
5. Garantía vigente y `revision_obligatoria_garantia` → `en_revision` + trigger `garantia`.
6. `tipos_falla.requiere_revision_manual` → `en_revision` + trigger `tipo_falla_flag`.
7. Fuera de `horario_servicio_json` del contrato → `en_revision` + trigger `fuera_horario` + alerta al despachador.
8. Palabra de `folio_keywords_alerta` en la descripción → `en_revision` + trigger `keyword_alerta`.

Si todas pasan, el folio entra directamente al punto de decisión del flujo multinivel (sección 4). Un folio puede acumular varios triggers; todos se registran en `revision_manual_triggers`.

Override de severidad: Despachador o Admin prestador pueden cambiarla en `en_revision` con razón obligatoria; `severidad_origen = override_admin` y auditoría.

### 4. Flujo de aprobación multinivel (`services/aprobacion_service.py`)

- Evaluación al terminar las validaciones: reglas de `aprobacion_reglas` por monto estimado (umbrales A y B del tenant), criticidad del activo (`equipos.criticidad`; A/B mínimo Nivel 2) y tipo de trabajo (preventivo → 1, correctivo → por monto, especial → mínimo 2). **La regla más restrictiva gana.** Si el tenant no tiene reglas configuradas, el folio no entra a flujo y pasa a `autorizado` (anotar como decisión pendiente). Si `autorizacion_automatica_criticos` está activa y el activo es A/B, pasa directo a `autorizado` registrando una decisión `auto_aprobado` con canal `sistema`.
- Mientras el flujo está activo el folio permanece en `en_revision` (§6.8.7: sub-proceso interno), con `aprobacion_flujos.nivel_actual` visible en el detalle.
- Actores por nivel según `aprobacion_niveles_config`: Nivel 1 Admin UN de la UN del folio; Nivel 2 rol `supervisor_operadores` con la UN asignada en `usuario_un` (el documento lo llama "Supervisor regional"; anotar la equivalencia como decisión pendiente); Nivel 3 Admin empresa.
- `POST /api/folios/{id}/aprobacion/aprobar` y `.../rechazar` con `canal` (`push` / `app` / `minuta`): aprobar en el último nivel requerido → `autorizado`; aprobar en un nivel intermedio → sube de nivel y notifica; rechazar exige `razon_rechazo` y deriva al `modulo_destino` de la tabla de §6.8.7, transiciona el folio a `cancelado` con razón documentada y deja `modulo_destino_id` nulo para que P07 lo complete al crear el registro en el módulo (dejar un evento `folio.derivado_a_modulo` en el historial con el destino, para que P07 lo procese).
- Timeouts: worker Celery `evaluar_timeouts_aprobacion` cada minuto sobre `aprobacion_alertas_timeout`; aplica literalmente las cuatro opciones de §6.8.7 y la restricción de que el Nivel 3 solo admite `bloquear_alertar` o `depende_criticidad` (validar al configurar). Alertas nuevas en `alertas_catalogo`: `APROBACION_PENDIENTE_VENCIDA`, `APROBACION_BLOQUEADA`, `FOLIO_EN_REVISION_SIN_ATENDER`.
- Pantalla de configuración para Admin empresa: umbrales A/B, reglas por criterio, actor y timeout por nivel.

### 5. Endpoints (prefijo `/api/folios`)

- Listado con filtros (tenant, UN, grupo de UNs, estado, severidad, técnico, fechas, tipo) y alcance por rol: Operador solo sus UNs; Admin UN sus UNs; Supervisor de operadores sus UNs; Admin empresa todo su tenant; Despachador, Mesa de control y Admin prestador los tenants que atiende su prestador; Técnico solo folios asignados a él (cerrar la decisión pendiente n.º 3 de P01 en ese sentido y anotarlo).
- Detalle completo con la estructura del archivo de §6.8.6: captura, formulario de captura, asignación, historial de estados, evidencias, formulario de atención, refacciones, SLA, encuesta, decisiones de aprobación. Las secciones todavía vacías (chat P05, reasignaciones P06, datos financieros P09) se devuelven vacías, no se omiten.
- Transiciones: `POST /{id}/transicion` genérica (usa el motor) y atajos semánticos: `autorizar`, `pedir-informacion`, `responder-informacion`, `asignar` (técnico con habilidad requerida: restricción dura salvo permiso `asignar_tecnico_sin_habilidad` del despachador con razón obligatoria), `en-camino`, `confirmar-llegada`, `pendiente-refaccion`, `reanudar`, `cerrar`, `cancelar` (razón obligatoria).
- `GET /{id}/historial`, `GET /pendientes-aprobacion` (para el aprobador), `GET /verificar-duplicado`.
- Mesa de control, Despachador y Admin prestador pueden fijar `monto_estimado` en `capturado` o `en_revision` (necesario para la regla por monto; anotar como decisión).

### 6. Frontend

- Módulo `folios` (`src/config/modulos.ts`, P04): ruta y página; roles: todos los que listan en §5.
- `pages/folios/Folios.tsx`: listado con filtros y columnas estado, severidad (color del nivel), UN, equipo, técnico, antigüedad; vista Kanban por estado opcional.
- `pages/folios/FolioDetalle.tsx`: todas las secciones del archivo del folio, línea de tiempo del historial, acciones disponibles según rol y estado (botones que solo aparecen si la transición es válida, consultando la misma tabla de transiciones expuesta por `GET /api/folios/transiciones`), triggers de revisión visibles, panel de aprobación con nivel actual.
- `pages/folios/CapturaFolio.tsx`: captura desde escritorio/PWA para Operador, Admin UN, Admin empresa, Supervisor y Mesa de control: selector de UN (`SelectorBusqueda` de P02), equipos con contrato activo, tipo de falla filtrado por familia del equipo, descripción, formulario dinámico resuelto por P03 con el `Renderizador`, verificación de duplicado con la tarjeta enriquecida y confirmación fuerte, y el paso final obligatorio de confirmación de UN con los dos botones literales de §6.8.6 («Sí, es esta unidad» / «No, quiero cambiarla»). P05 reutiliza esta pantalla en la app del operador con offline.
- `pages/folios/Aprobaciones.tsx`: bandeja del aprobador con los dos únicos botones Aprobar / Rechazar y el segundo paso obligatorio con las cuatro razones; configuración del flujo para Admin empresa.
- Notificaciones push de aprobación: dejar la llamada a `services/notificaciones` con implementación en consola/registro (el canal real llega en P07).

### 7. Seed y pruebas

- Seed: políticas y prefijo para el tenant demo, reglas de aprobación (umbral A 5,000, umbral B 20,000, preventivo → 1, especial → 2, A/B → 2), configuración de los tres niveles con timeouts distintos, criticidad en los 12 equipos, 4 palabras clave de alerta, horario de servicio en el contrato demo, y 15 folios en distintos estados (incluidos uno en revisión por cada trigger, uno con flujo en Nivel 2, uno cerrado y uno cancelado por rechazo).
- Backend (`tests/test_folios_captura.py`, `tests/test_folio_estados.py`, `tests/test_aprobacion.py`): cada validación con su resultado; duplicado con y sin bloqueo total; severidad automática y override; cada transición permitida por su rol y las no permitidas (409); inmutabilidad de folio cerrado y de `folio_estados_historial` y `aprobacion_decisiones` (incluido Superadmin); cierre incompleto; flujo: nivel de entrada por cada criterio y regla más restrictiva, aprobación en cadena, rechazo con cada razón y su destino, autorización automática de críticos, las cuatro opciones de timeout y la restricción del Nivel 3; alcance de listado por rol; aislamiento entre tenants; RLS forzada en todas las tablas nuevas.
- Frontend: captura completa con confirmación de UN, botones de acción según estado, bandeja de aprobación con rechazo en dos pasos.
- `pytest`, `vitest`, `tsc --noEmit` y `npm run build` en verde.

## Reglas (vigentes)

1. Seguir el Documento de Diseño v2.5; lo no definido se anota en `CONTEXTO.md` como decisión pendiente de validación.
2. Multitenancy validado en servicio además de RLS.
3. Sin proveedores externos de pago.
4. Identificadores en español sin acentos.
5. Cerrar con `CONTEXTO.md` (avance P04 ✅; sección "Folios (P04)" con la tabla de transiciones, `transicionar()`, el orden de validaciones y los eventos que P05, P06, P07 y P10 deben consumir) y `BITACORA.md` actualizados.
6. No cambiar el stack.

## Al terminar

Resumen en español con: tablas de la migración 0004, endpoints, tabla de transiciones estado → estado → roles, lista de triggers de revisión, decisiones pendientes nuevas y conteo de pruebas.
