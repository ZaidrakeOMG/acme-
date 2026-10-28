# P06 — Calendario de preventivos, planes con triggers y reasignación forzada (Fase 1, prompt 6 de 11)

## Contexto

P05 está cerrado (commit `4ad78d8`; 203 pytest y 45 vitest en verde). Lee antes de empezar `CONTEXTO.md` (secciones "Folios (P04)" con `transicionar()` y la tabla de transiciones, "Campo, offline y chat (P05)" con los eventos de chat, y las decisiones pendientes 1–48), `BITACORA.md`, y en `ACMA_Documento_Diseno_v2.5.docx`: §4.1 (módulos Planes de mantenimiento, Calendario de preventivos y Gestión de reasignaciones), §6.9.1 completo (tipos de trigger, estructura del plan, modelo de datos, ciclo de vida del preventivo, chat del preventivo, modelo complementario), §7.6 (calendario mensual y desvío en días), §6.8.2 solo en su parte de reasignación forzada (restricciones, catálogo de razones y modelo de datos) y §6.8.3b (permiso `asignar_tecnico_sin_habilidad`), y en `ACMA_Alcance_Fases_v1.0.docx` la sección 5.1 (alcance reducido de los triggers en Fase 1).

Este prompt construye los preventivos y la reasignación manual. La reasignación automática, el recálculo VRPTW, los triggers por medidor, por evento y combinado, y los medidores son Fase 2: sus tablas y campos se crean completos aquí, su lógica no.

## Objetivo

Que el prestador programe preventivos de dos maneras, calendario mensual manual (como hoy) y planes con triggers por tiempo fijo y por calendario que generan folios solos, que cada preventivo siga el ciclo de vida de §6.9.1 con reprogramación y cancelación autorizadas formalmente, que el desvío entre fecha programada y real quede medido, y que el despachador pueda reasignar folios con las restricciones y razones de §6.8.2.

## Entregables

### 1. Migración `0006_preventivos_reasignaciones.py`

Con los helpers de `core/sql_migracion.py`, RLS forzada en toda tabla con `tenant_id`/`prestador_id`.

**Planes de mantenimiento (§6.9.1, las 6 tablas, completas aunque Fase 1 use dos triggers):**

| Tabla | Campos clave |
|---|---|
| `planes_mantenimiento` | prestador_id, tenant_id (nullable = aplica a todos los clientes), tipo_equipo_id, nombre, descripcion, version, estado (`activo` / `inactivo`), tiempo_ventana_dias, formulario_id (formulario de tipo `preventivo` de P03), created_by |
| `plan_triggers` | plan_id, tipo_trigger ENUM(`tiempo_fijo` / `calendario` / `medidor_umbral` / `medidor_intervalo` / `evento` / `combinado`), parametros_json, logica_combinacion (nullable); en Fase 1 el servicio solo acepta crear `tiempo_fijo` (`{"cada_dias": N}` o `{"cada": N, "unidad": "dias|semanas|meses"}`) y `calendario` (`{"mes": M, "dia": D}` o lista de fechas); los otros cuatro responden 403 `TRIGGER_FASE_2` |
| `plan_tareas` | plan_id, orden, descripcion, tiempo_estimado_min, habilidad_requerida_id |
| `plan_materiales` | plan_id, articulo_id (sin FK hasta P09), descripcion, cantidad_estandar, unidad |
| `plan_ejecuciones` | plan_id, equipo_id, folio_id, fecha_programada, fecha_real (nullable), desvio_dias (nullable), estado |
| `equipo_planes` | equipo_id, plan_id, activo, fecha_proxima_ejecucion, ultimo_valor_medidor (nullable, Fase 2), fecha_ultima_ejecucion |

Completar la FK diferida de P03: `formulario_asignaciones.plan_mantenimiento_id → planes_mantenimiento.id`.

**Calendario y ciclo de vida del preventivo (§6.9.1 y §7.6):** el documento define dos tablas de calendario (`calendarios_preventivos` en §6.9.1 y `preventivos_calendario` en §7.6) con el mismo propósito; unificarlas en una sola, `preventivos_calendario`, con la unión de campos: prestador_id, tenant_id, un_id, equipo_id (nullable: preventivo de instalación o de UN completa), plan_id (nullable: NULL = programación manual), tecnico_id (nullable), fecha_programada, fecha_real (nullable), desvio_dias (nullable), estado ENUM(`programado` / `generado` / `reprogramado` / `cancelado` / `ejecutado`), folio_id (nullable), origen ENUM(`manual` / `plan`), cargado_por, created_at. Anotar la unificación como decisión pendiente.

`autorizaciones_preventivo`: folio_id, tipo ENUM(`reprogramacion` / `cancelacion`), solicitado_por, autorizado_por (nullable), fecha_solicitud, fecha_autorizacion (nullable), razon, fecha_nueva (nullable, para reprogramación), estado ENUM(`pendiente` / `autorizada` / `rechazada`), canal.

**Reasignaciones (§6.8.2, las 3 tablas):** `razones_reasignacion` (prestador_id, descripcion, activa, orden_display; sembrar las 7 razones del catálogo literal de §6.8.2 al crear un prestador), `reasignaciones` (folio_id, tecnico_origen_id, tecnico_destino_id, tipo ENUM(`automatica` / `forzada`), razon_id, comentario, despachador_id, timestamp) y `reasignacion_validaciones` (reasignacion_id, habilidad_ok, refaccion_ok, advertencias_json).

### 2. Planes y generación automática (`services/planes_service.py`, `workers/tareas/preventivos.py`)

- CRUD de planes, triggers, tareas, materiales y asignación de planes a equipos (`equipo_planes`) para Admin prestador y Despachador; consulta para Admin empresa y Admin UN. Al asignar un plan a un equipo se calcula `fecha_proxima_ejecucion` según el trigger (tiempo fijo desde la última ejecución o desde la fecha de alta; calendario: la próxima fecha fija).
- Tarea Celery beat nocturna `generar_preventivos_programados` (y manual con `POST /api/preventivos/generar` para pruebas): para cada `equipo_planes` activo cuya `fecha_proxima_ejecucion` esté dentro del horizonte configurable (default 7 días) y no tenga folio generado, crea la fila en `preventivos_calendario` con `origen = plan`, crea el folio con `tipo_folio = preventivo` mediante el servicio de captura de P04 en modo sistema (sin validaciones de operador; severidad del nivel configurado para preventivos en el plan o la más baja), lo transiciona directo a `autorizado` (§6.9.1: "ya fue aprobado al configurar el plan"), vincula `folio_formulario_atencion` al formulario del plan resuelto por P03, registra `plan_ejecuciones` y recalcula `fecha_proxima_ejecucion`. El folio preventivo abre sus chats por el gancho de P05.
- Evaluación de triggers con el contexto `CONTEXTO_SISTEMA`; sesión propia por tarea.

### 3. Calendario mensual manual (§7.6)

- `POST /api/preventivos/calendario` (una fila o lote) y carga por archivo con el importador de P02 (nuevo catálogo `calendario_preventivos` en el registro `CATALOGOS`: columnas UN, equipo opcional, fecha, técnico opcional). Despachador, Mesa de control y Admin prestador cargan; Admin UN y Admin empresa consultan su calendario completo.
- `GET /api/preventivos/calendario?mes=&tenant_id=&un_id=&estado=` con vista mensual y lista.
- Al cerrar el mes (acción `POST /api/preventivos/calendario/publicar?mes=`), emitir el evento `calendario.publicado` con los destinatarios Admin empresa y Admin UN (§7.6: "ACMA envía el calendario"); el envío real lo hace P07, aquí se registra la notificación push PWA de P05 y el log.
- Los preventivos manuales generan su folio en la fecha programada con la misma tarea nocturna (origen `manual`, sin plan; formulario de preventivo resuelto por P03 por tipo de equipo o el genérico sembrado en P03).

### 4. Ciclo de vida del preventivo (§6.9.1)

- Asignación por Despachador con la restricción de habilidad: si el plan tiene `plan_tareas.habilidad_requerida_id`, el técnico debe tenerlas todas certificadas (P02), salvo permiso `asignar_tecnico_sin_habilidad` con razón obligatoria.
- Reprogramación: `POST /api/preventivos/{folio_id}/solicitar-reprogramacion` (Despachador, con fecha nueva y razón) crea la autorización pendiente, notifica a Admin UN y Admin empresa y escribe un evento de sistema en el chat `operativo`; `POST .../autorizaciones/{id}/autorizar|rechazar` (Admin UN de la UN o Admin empresa). Solo con autorización el sistema mueve `fecha_programada`, marca el registro anterior como `reprogramado` y conserva el histórico. Sin autorización, 409 `REQUIERE_AUTORIZACION`.
- Cancelación: mismo mecanismo con tipo `cancelacion`; al autorizarse, `transicionar(cancelado)` con la razón documentada. Esta reprogramación de preventivos es distinta del Módulo Reprogramación de hallazgos (§7.7, P07); anotarlo.
- Cierre: al llegar a `cerrado` por el flujo de P05 (formulario del plan + firma + encuesta), fijar `fecha_real`, calcular `desvio_dias = fecha_real − fecha_programada` en `preventivos_calendario` y `plan_ejecuciones`, y dejar el texto literal de §7.6 disponible para la minuta ("realizado N días antes de lo programado" / "realizado con N días de retraso") en un helper `texto_desvio()`.
- Alertas nuevas en `alertas_catalogo`: `PREVENTIVO_VENCIDO_SIN_EJECUTAR` (fecha programada + ventana superada sin cierre), `AUTORIZACION_PREVENTIVO_PENDIENTE` (solicitud sin respuesta tras N horas), `CALENDARIO_MES_SIN_PUBLICAR` (día configurable del mes sin calendario del siguiente).

### 5. Reasignación forzada (§6.8.2, parte forzada)

- `GET /api/folios/{id}/reasignacion/candidatos`: técnicos del prestador con indicador de habilidad requerida (restricción dura), carga del día (folios asignados), y advertencia de refacción (gancho para P09: hoy siempre `refaccion_ok = null`).
- `POST /api/folios/{id}/reasignar` (Despachador; Admin prestador también): valida las restricciones literales de §6.8.2: no reasignar en `en_ejecucion`; no a técnico sin la habilidad certificada (403, salvo permiso `asignar_tecnico_sin_habilidad` con razón); refacción faltante solo advierte y exige confirmación explícita; razón de `razones_reasignacion` obligatoria y comentario opcional. Ejecuta `transicionar(reasignado)` y de inmediato `transicionar(asignado)` al nuevo técnico (estado transitorio de §6.8.6), registra `reasignaciones` y `reasignacion_validaciones`, emite el evento de chat "reasignado" de P05 en canales `campo` y `operativo` (el técnico origen sale del canal `campo` y entra el destino), y notifica por push a ambos técnicos.
- `GET /api/reasignaciones/reporte?desde=&hasta=&tenant_id=`: principales causas por período (conteo y porcentaje por razón, por técnico origen/destino) — §4.1 Gestión de reasignaciones.
- CRUD de `razones_reasignacion` para Admin prestador.

### 6. Frontend

- Módulo `calendario` (`src/config/modulos.ts`): página `pages/preventivos/Calendario.tsx` con vista mensual (celdas por día con conteo y chips por UN), lista filtrable, carga manual individual y por archivo, botón "Publicar mes", y en cada preventivo su estado, técnico, fecha real y desvío con el texto de §7.6. Roles: Despachador, Mesa de control, Admin prestador (edición); Admin UN y Admin empresa (consulta); Supervisor de operadores (consulta de sus UNs).
- Nuevo módulo `planes` (agregarlo a `modulos.ts`, grupo Operación, prompt P06): `pages/preventivos/Planes.tsx` con lista, editor del plan (encabezado, triggers con solo las dos opciones de Fase 1 habilitadas y las otras cuatro visibles pero deshabilitadas con la etiqueta "Fase 2", tareas ordenables con habilidad, materiales, formulario del plan, ventana ±días) y asignación de planes a equipos con fecha próxima.
- Bandeja de autorizaciones de preventivos para Admin UN y Admin empresa (`pages/preventivos/Autorizaciones.tsx`): reprogramación y cancelación con fecha nueva y razón visibles; integrar también como sección en `FolioDetalle.tsx`.
- Módulo `reasignacion` (`modulos.ts`): acción "Reasignar" en `FolioDetalle.tsx` y en el listado del despachador: selector de candidatos con indicadores de habilidad, carga y refacción, razón obligatoria, confirmación explícita cuando hay advertencia; `pages/reasignaciones/Reporte.tsx` con las causas por período.
- App del técnico (P05): los folios preventivos aparecen con etiqueta "Preventivo", el plan con sus tareas como lista de verificación dentro de la atención, y los materiales estándar precargados en refacciones.

### 7. Seed y pruebas

- Seed: 3 planes (uno con trigger `tiempo_fijo` cada 30 días, uno `calendario` el 15 de enero, uno con ambos) con tareas, materiales y formulario; 6 `equipo_planes`; calendario manual del mes actual con 8 preventivos (2 ejecutados con desvío positivo y negativo, 1 reprogramado autorizado, 1 cancelado, resto programados); las 7 razones de reasignación; 3 reasignaciones históricas.
- Backend (`tests/test_planes.py`, `tests/test_preventivos_calendario.py`, `tests/test_preventivos_ciclo.py`, `tests/test_reasignaciones.py`): triggers `tiempo_fijo` y `calendario` calculan la próxima fecha correctamente (incluidos meses de distinta longitud); los otros cuatro responden `TRIGGER_FASE_2`; la tarea nocturna genera folios en `autorizado`, no duplica si se ejecuta dos veces y respeta el horizonte; importación del calendario; publicación del mes y evento; reprogramación y cancelación bloqueadas sin autorización y aplicadas con ella; `desvio_dias` y `texto_desvio()` en cierre; alertas de vencido y de autorización pendiente; reasignación: cada restricción de §6.8.2, permiso `asignar_tecnico_sin_habilidad`, transición `reasignado → asignado`, cambio de participantes del chat `campo`, reporte de causas; aislamiento entre prestadores y tenants; RLS forzada en todas las tablas nuevas.
- Frontend: calendario mensual con carga y publicación; editor de plan con los triggers de Fase 2 deshabilitados; flujo de reasignación con advertencia y confirmación.
- `pytest`, `vitest`, `tsc --noEmit` y `npm run build` en verde.

## Reglas (vigentes)

1. Seguir el Documento de Diseño v2.5; lo no definido se anota en `CONTEXTO.md` como decisión pendiente de validación.
2. Multitenancy validado en servicio además de RLS.
3. Sin proveedores externos de pago.
4. Identificadores en español sin acentos.
5. Cerrar con `CONTEXTO.md` (avance P06 ✅; sección "Preventivos y reasignaciones (P06)" con la tarea nocturna, `texto_desvio()`, los eventos `calendario.publicado` y de autorizaciones que P07 debe entregar por correo, y el gancho de refacciones para P09) y `BITACORA.md` actualizados.
6. No cambiar el stack.

## Al terminar

Resumen en español con: tablas de la migración 0006, endpoints, tareas Celery nuevas, alertas nuevas, decisiones pendientes nuevas y conteo de pruebas.
