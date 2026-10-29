# CONTEXTO — Estado del proyecto ACMA (desarrollo nuevo)

> Se actualiza al cierre de cada prompt. Última actualización: **2026-10-29 · P08 Trabajos especiales, conversión de cotizaciones y OC de activos**.

## Ubicación y relación con acma-proyecto

- Este repositorio (`C:\Users\lilia\Desktop\acma`) es el **desarrollo nuevo desde cero** definido en
  `ACMA_Alcance_Fases_v1.0.docx` (11 prompts de Fase 1).
- `C:\Users\lilia\Desktop\acma-proyecto` es la implementación anterior. **No se toca.** Ambos conviven: este proyecto usa
  puertos y contenedores distintos (`acma_nuevo_*`, PostgreSQL 5442, Redis 6389, MinIO 9010/9011).

## Avance por prompt

| Prompt | Contenido | Estado |
|---|---|---|
| P01 | Cimientos: repo, Docker, modelo base, RLS, auth + MFA, API base, PWA con login y hub | ✅ 2026-10-19 |
| P02 | Catálogos maestros (técnicos y habilidades, equipos, fallas, severidades, matriz, importador) | ✅ 2026-10-23 |
| P03 | Motor de formularios: 22 tipos de campo, constructor, versiones, asignaciones, respuestas y evidencias | ✅ 2026-10-23 |
| P04 | Folios: ciclo de vida de 11 estados, validaciones automáticas en captura y aprobación multinivel | ✅ 2026-10-27 |
| P05 | Apps PWA del operador y del técnico, modo offline (cola idempotente) y chat archivado con tiempo real | ✅ 2026-10-28 |
| P06 | Calendario de preventivos, planes con triggers de Fase 1, autorizaciones y reasignación forzada | ✅ 2026-10-28 |
| P07 | Minuta del día por UN y global, notificaciones multicanal (correo SMTP), cuatro módulos de seguimiento y clasificación de no críticos | ✅ 2026-10-29 |
| P08 | Trabajos especiales con validación del cliente, conversión de cotizaciones y seguimiento de OC de activos | ✅ 2026-10-29 |
| P09 | Inventario, caja chica manual, presupuestos y activos | Pendiente |
| P10 | Contratos/SLA (contador), alertas por módulo y BI | Pendiente |
| P11 | Endurecimiento y despliegue | Pendiente |

## Verificación al cierre de P08

- Migración `0008_trabajos_especiales_oc.py` aplicada (subida, bajada y subida) y seed `seed_trabajos_especiales.py` cargado.
- `pytest`: **277 pruebas en verde** (incluye `test_trabajos_especiales.py`, `test_te_urgencia.py` y `test_oc_activos.py`; las de
  P04/P07 que cambiaron: catálogo de 49 alertas, sección de trabajos especiales de la minuta con contenido real).
- `vitest`: **68 pruebas en verde** (bandeja del cliente con aceptar/rechazar, Kanban y programación del TE, conversión desde la
  cotización, registro de OC y decisión ante rechazo). `tsc --noEmit` y `npm run build` en verde.
- Sin revisión visual en el navegador esta vez: la máquina (7 GB) se quedó sin memoria con Docker, pytest y los servidores de
  desarrollo a la vez; las pantallas se cubren con las pruebas de vitest y los datos demo del seed.

## Verificación al cierre de P07

- `pytest`: **259 pruebas en verde** (226 anteriores + las de P07: preferencias/canales Fase 2/bandeja, correo stub con `.eml`
  y adjunto, correo por SMTP contra `aiosmtpd`, plantilla del prestador; configuración, generación UN y global con secciones y
  entrega, modo con validación y ventana vencida, las seis respuestas con su efecto, vencimiento y alerta, recordatorio por
  período, hallazgos desde formulario y chat; cotizaciones por rol con PDF, rechazo → presupuesto y envío externo, Kanban,
  historial inmutable, alertas por días, reporte JSON/Excel/PDF; presupuesto reactivar/descartar/revisar, alerta y monto
  potencial, períodos, derivación §6.8.7; interno transiciones/campos/justificación y alertas; reprogramación con 3 fechas
  vencidas y escalado, alertas y variantes A/B; clasificación con las cinco opciones, tardía, alertas y calificación). La
  suite completa supera los 15 minutos: `conftest.auth` vuelve a iniciar sesión a los 10 min.
- `vitest`: **62 pruebas en verde** (+ responder la minuta con las seis opciones y validación del despachador, Kanban que
  cambia estado, listado y reporte, clasificación con fecha tentativa, calificación, bandeja y preferencias).
- `tsc --noEmit` limpio; `npm run build` verde. Datos demo regenerados con `seed_minuta` sobre la base existente.

## Verificación al cierre de P06

- `pytest`: **226 pruebas en verde** (203 anteriores + 23: próxima fecha y validación de triggers, plan completo, 403 de
  Fase 2, asignación a equipos con recálculo, edición con versión y aislamiento; texto literal de desvío, carga/consulta/
  edición por rol, publicación con notificación, importador `calendario_preventivos`, generación desde calendario
  manual; generación nocturna idempotente, habilidades del plan + tareas y paquete del técnico, cancelación con
  autorización, reprogramación autorizada y rechazada, cierre con desvío y recálculo, las tres alertas; catálogo de
  razones, candidatos y restricciones con confirmación, sin habilidad con permiso, estados no reasignables y roles,
  reporte de causas). La prueba de reasignación de P04 usa ahora la reasignación forzada real.
- `vitest`: **54 pruebas en verde** (45 anteriores + 9: calendario con desvío y publicación, editor de planes con Fase 2
  deshabilitada, técnico con tareas y materiales, solicitud de reprogramación desde el folio, bandeja de
  autorizaciones; modal de reasignación con 409 y confirmación, razón sin habilidad, sin botón para el operador,
  reporte con porcentajes).
- `tsc --noEmit` limpio; `npm run build` verde. Datos demo regenerados con `seed_preventivos` sobre la base existente.

## Verificación al cierre de P05

- `pytest`: **203 pruebas en verde** (185 anteriores + 18: sincronización incremental con bajas, lote aplicadas/duplicadas/
  rechazadas, cierre offline con hora real y conflicto, respuesta y evidencia idempotentes, dos pasos con reintento,
  refacción/mensaje offline y aislamiento; tres chats y eventos, doble timestamp e idempotencia, permisos por canal, RLS
  de participantes, inmutabilidad y evidencia posterior, chat archivado, WebSocket con dos clientes y SSE; firma, secuencia
  atención→firma→encuesta→cierre, plazo de la encuesta, push).
- `vitest`: **45 pruebas en verde** (39 anteriores + 6: cola FIFO con reintentos y reanudación, atención parcial offline,
  mensaje encolado con doble timestamp, indicador de conectividad, captura sin red y envío al reconectar, inicio del
  operador sin acceso a otras UNs).
- `tsc --noEmit` limpio; `npm run build` verde.

## Verificación al cierre de P04

- `pytest`: **185 pruebas en verde** (131 anteriores + 54 de folios: 8 validaciones de captura, duplicados con y sin bloqueo,
  severidad automática y override, transiciones por rol y 409, cierre incompleto, inmutabilidad de cerrado/cancelado,
  historial y decisiones append-only incluso superadmin, alcance por rol, aislamiento, RLS en tablas nuevas, nivel de
  entrada por criterio, cadena, 4 razones de rechazo, auto-aprobación de críticos, 4 timeouts y restricción del Nivel 3).
- `vitest`: **39 pruebas en verde** (33 anteriores + 6: captura con confirmación de UN, tarjeta de duplicado con justificación,
  botones por rol/estado en el detalle, bandeja con rechazo en dos pasos, listado y Kanban).
- `tsc --noEmit` limpio; `npm run build` verde.

## Verificación al cierre de P03

- `pytest`: **131 pruebas en verde** (96 anteriores + 35 de formularios: permisos, versionado, resolver, 22 tipos, condiciones,
  cascada, cálculos en servidor, inmutabilidad, calidad de foto, EXIF/GPS, geofencing).
- `vitest`: **33 pruebas en verde** (27 anteriores + 6: constructor con los 22 tipos, editor de condiciones, guardar/publicar,
  renderizador bloquea envío, cascada familia → tipo de falla, motor espejo).
- `tsc --noEmit` limpio; `npm run build` verde.

## Verificación al cierre de P02

- `pytest`: **96 pruebas en verde** (76 de P01 + 20 de catálogos, matriz e importador).
- `vitest`: **27 pruebas en verde** (19 de P01 + 8 de catálogos: pestañas por rol, celda de matriz, importación).
- `tsc --noEmit` limpio; `npm run build` verde.
- Verificado a mano en el navegador: pestañas de catálogos, matriz editable, importación con vista previa.

## Verificación al cierre de P01

- `pytest`: **76 pruebas en verde** (auth/MFA/refresh/reúso, aislamiento RLS, audit append-only, matriz de permisos por rol).
- `vitest`: **19 pruebas en verde** (login, enrolamiento MFA, hub por rol, refresh single-flight).
- `tsc --noEmit` limpio; `npm run build` verde (service worker con precache del shell).
- Verificado a mano: API real con datos demo, worker + beat de Celery ejecutando `evaluar_alertas`, interfaz (login, hub,
  UNs, edición de contrato) sin errores de consola.

## Arquitectura vigente (lo que deben respetar los prompts siguientes)

### Base de datos y RLS
- Esquema definido en SQL explícito en `backend/alembic/versions/0001_cimientos.py`; los modelos ORM lo reflejan.
  Las migraciones nuevas se escriben igual (SQL explícito con `ex()`, que divide sentencias para asyncpg).
- Roles: `acma_owner` migra; `acma_api` es la app (sin BYPASSRLS ni propiedad de tablas); `acma_auth` (NOLOGIN, BYPASSRLS)
  es dueño **solo** de las funciones `auth_*` de arranque de sesión.
- Contexto RLS: `app.usuario_id`, `app.tenant_id`, `app.prestador_id`, `app.rol`. Se aplica con `set_config(…, true)` en el
  evento `after_begin` de la sesión (`core/rls.py`), así que **cada transacción** lleva contexto aunque haya commits intermedios.
  Para cambiarlo dentro de una sesión: `fijar_contexto(sesion, ContextoRLS(...))`.
- Funciones de política: `acma_es_plataforma()` (superadmin o `sistema`), `acma_tenant_visible(t)` (tenant propio o
  atendido por el prestador del contexto), `acma_prestador_visible(p)`. Sin contexto, todas devuelven falso (fail-closed).
- Toda tabla nueva con `tenant_id` o `prestador_id` debe llevar `ENABLE` + `FORCE ROW LEVEL SECURITY` y políticas;
  `tests/test_rls.py::test_toda_tabla_con_tenant_o_prestador_tiene_rls_forzada` lo verifica automáticamente.
- Tablas críticas: `id`, `created_at`, `updated_at` (índice) y `version_hash`, calculados por el trigger `acma_version()`.
  Agregar la tabla a la lista `TABLAS_VERSIONADAS` (o crear el trigger equivalente) en su migración.
- `audit_log` y `audit_accesos_api`: particionadas por mes, append-only (triggers BEFORE UPDATE/DELETE/TRUNCATE + sin
  privilegios UPDATE/DELETE para `acma_api`). Insertar siempre con `services.auditoria.registrar(...)` (sin RETURNING).
- Celery y scripts usan el contexto `CONTEXTO_SISTEMA` (rol `sistema`) de forma explícita.

### Backend
- Dependencias: `usuario_actual` (`ActorActual`), `requiere_rol(*roles)`, `requiere_dominio(...)`, y en servicios
  `validar_tenant` / `validar_prestador` (regla 2: validar multitenancy además de la RLS).
- Errores: lanzar `core.errors.ErrorAPI(estado, codigo, mensaje, detalles)`; todo error sale como `{codigo, mensaje, detalles}`.
- Auditoría de cambios críticos: `auditoria.registrar_actor(db, actor, "modulo.evento", request, antes=..., despues=...)`.
- Alertas: cada módulo registra su evaluador con `@workers.tareas.registrar_evaluador("CLAVE")` y dispara con
  `services.alertas_service.disparar(...)` (respeta umbral efectivo, estado activo y supresiones).
- Almacenamiento: `services.almacenamiento.obtener_almacenamiento()` (MinIO o memoria en pruebas).
- `DATABASE_READ_URL` opcional → `core.db.engine_lectura` (igual al principal si está vacía).

### Catálogos maestros (P02)
- Migración `0002_catalogos.py` usa los helpers de `core/sql_migracion.py` (`ex`, `rls`, `versionar`, `politicas_tenant`,
  `politicas_prestador`). Una migración que inserte o actualice filas debe empezar con
  `SELECT set_config('app.rol','sistema',true)`: la RLS forzada aplica también al dueño del esquema.
- Tablas: `habilidades`, `tecnicos`, `tecnico_habilidades`, `tecnico_tenants_habilitados` (§6.10.8), `niveles_severidad`,
  `familias_equipo` y `tipos_equipo` (`tenant_id` NULL = global de plataforma), `equipos`, `tipos_falla`,
  `tipo_falla_severidad`, `importaciones_catalogo`. Nuevos: `contratos.cobertura` y `contrato_sla.nivel_severidad_id`.
- **Contrato activo de un equipo**: función SQL `acma_equipo_con_contrato_activo(equipo_id)` (respeta la RLS del llamador) y
  `services.catalogos_service.equipo_con_contrato_activo`. `GET /api/catalogos/equipos?con_contrato=true` la aplica; P04 la
  usa en el selector filtrado y en la validación de captura.
- **Severidad automática**: `catalogos_service.resolver_severidad(db, tenant, tipo_falla, tipo_equipo)` y
  `GET /api/catalogos/matriz-severidad/resolver` (404 `SEVERIDAD_NO_CONFIGURADA` → el folio va a En revisión en P04).
  Devuelve también `requiere_revision_manual` del tipo de falla.
- **Permisos efectivos del técnico**: `permisos_service.efectivos_de_tecnico` (override > grupo > prestador > catálogo);
  `GET /api/catalogos/tecnicos/{id}/permisos-efectivos`.
- **Importador** (`services/importador_service.py`): registro `CATALOGOS` con columnas, validación por fila y aplicación;
  flujo `POST /api/catalogos/importar/{catalogo}` → `…/{id}/confirmar | cancelar`; plantillas en `…/{catalogo}/plantilla`.
  Para agregar un catálogo: entrada en `CATALOGOS` y ramas en `Contexto.cargar`, `_validar_fila` y `aplicar`.
- **Evaluadores de alertas** viven en `workers/evaluadores.py` (importado por `workers/tareas.py`). Un evaluador no debe
  repetir una alerta mientras exista una `disparada` sin atender para la misma entidad (patrón de `matriz_incompleta`).
- Frontend: `src/components/Buscador.tsx` (`Buscador` con retardo y `SelectorBusqueda` tipo combobox para P04),
  `pages/catalogos/Catalogos.tsx` con `useAmbito()` (tenant/prestador del usuario o los que elige el superadmin) y una
  pestaña por catálogo en `pages/catalogos/pestanas/`.

### Motor de formularios (P03)
- **Contrato del esquema**: `backend/schemas/formularios.py` ↔ `frontend/src/types/formularios.ts`; documentación completa de
  los 22 tipos en `docs/formularios/tipos_de_campo.md`. `secciones[] → campos[]` con `clave`, `tipo`, `config` validada por
  tipo, `condiciones[]` y `fuente_opciones` (fija o catálogo con `campo_padre` para cascada).
- **Motor de reglas** idéntico en `backend/services/formularios/validacion.py` y
  `frontend/src/services/formularios/validacion.ts` (`visibilidad`, `validar`, cálculos). Cualquier regla nueva se cambia
  en ambos y se prueba en `test_formularios_validacion.py` y `tests/formularios.test.tsx`.
- **Tablas (0003)**: `formularios`, `formulario_versiones` (una publicada no se edita: editar crea `numero_version + 1`),
  `formulario_asignaciones` (`plan_mantenimiento_id` sin FK hasta P06), `formulario_permisos_mesa`,
  `catalogos_personalizados` + opciones, `formulario_respuestas` (inmutables al enviar, trigger), `formulario_evidencias`
  (inmutables con la respuesta, trigger), `calidad_foto_defaults`. Alerta nueva `GEOLOCALIZACION_FUERA_DE_UN`.
- **Para P04 (folios)**:
  - `GET /api/formularios/resolver?tipo=&tipo_folio=&tenant_id=&tipo_equipo_id=&familia_equipo_id=&plan_id=` → formulario
    publicado aplicable (específico de tenant > global; coincidencia más específica) con su `esquema_json`.
  - `POST /api/formularios/{id}/respuestas` con `origen` (`folio_captura` | `folio_atencion` | …), `referencia_id` (el
    folio) y `contexto` {`tenant_id`, `un_id`, `equipo_id`, `sistema` {captura_folio, asignacion, autorizacion,
    fecha_programada: ISO}}; `PUT …/respuestas/{id}` parcial; `POST …/enviar` valida en servidor (422
    `RESPUESTA_INVALIDA` con `detalles`), recalcula concatenaciones/matemáticas/sellos y aplica geofencing.
  - `GET /api/formularios/respuestas?origen=&referencia_id=` para listar las respuestas de un folio.
  - `GET /api/formularios/opciones?catalogo=…&padre=…&un_id=…` resuelve los catálogos del sistema para el renderizador;
    `tipos_falla` devuelve `extra.requiere_revision_manual`.
  - Frontend: `<Renderizador esquema respuestas onChange contexto respuestaId evidencias onEvidencias />` y la página
    `pages/formularios/Llenar.tsx` (ruta `/formularios/llenar/:id?origen=&referencia=&un_id=&equipo_id=&tenant_id=`).
- **Para P05 (offline)**: toda escritura pasa por `frontend/src/services/formularios/respuestas.ts`
  (`crearRespuesta`, `guardarRespuesta`, `enviarRespuesta`, `subirEvidencia`, `eliminarEvidencia`); la cola sustituye el
  transporte con `usarTransporte(...)`. `lista_desplegable.config.disponible_offline` marca los catálogos a descargar.
- **Evidencias**: `services/formularios/evidencias.py` (Pillow: dimensiones, EXIF, GPS, calidad JPEG estimada por tabla
  de cuantización). Las anotaciones van en `anotaciones_json` y la imagen compuesta en `archivo_anotado_key`.
- **Transcripción de audio**: `services/transcripcion.py` con `TranscriptorStub` (Fase 2 sustituye la implementación).
- **Seed**: 4 plantillas base (cubren los 22 tipos), catálogo «Causa raíz», «Captura de folio (operador)» y
  «Cierre de correctivo (global)» publicados y asignados a Refrigeración, y «Cierre de correctivo · Cliente Demo»
  específico del tenant (gana en `resolver`).

### Folios (P04)
- **Tablas (0004)**: `folios` (número correlativo `PREFIJO-000001` por tenant vía `acma_siguiente_numero_folio()`, 11 estados,
  severidad + origen, confirmación de UN con timestamp/geo, duplicado con justificación y referencia, monto estimado,
  fechas de atención/cierre, cancelación), `folio_estados_historial` (**append-only**, con `evento`: `transicion`,
  `comentario`, `aprobacion.*`, `revision.resuelta`, `severidad.override`, `atencion.vinculada`, `confirmacion_un`,
  `folio.derivado_a_modulo`), `folio_formulario_captura`, `folio_formulario_atencion`, `folio_evidencias`,
  `folio_refacciones` (`articulo_id` sin FK hasta P09), `folio_sla` (prometido al autorizar; real y pausas en P10),
  `folio_encuesta`, `revision_manual_triggers` (con `resuelto`), `folio_keywords_alerta`, `folio_politicas_tenant`
  (bloqueo de duplicados, revisión por garantía, auto-autorización de críticos, `aprobacion_secuencial`, prefijo y
  contador) y las 5 de aprobación: `aprobacion_reglas`, `aprobacion_flujos`, `aprobacion_niveles_config` (CHECK Nivel 3),
  `aprobacion_decisiones` (**append-only, también para superadmin**), `aprobacion_alertas_timeout`. Además
  `contratos.horario_servicio_json`, `equipos.criticidad` (A/B/C/D) y `familias_equipo.habilidad_clave`. Alertas nuevas:
  `APROBACION_PENDIENTE_VENCIDA`, `APROBACION_BLOQUEADA`, `FOLIO_EN_REVISION_SIN_ATENDER` (evaluador en Celery).
- **Trigger `acma_folio_inmutable()`**: un folio `cerrado` o `cancelado` rechaza cualquier UPDATE (salvo
  `updated_at`/`version_hash`); `DELETE` prohibido siempre. Solo se admiten comentarios en el historial.
- **Motor de estados** `services/folio_estados.py`: tabla `TRANSICIONES` literal de §6.8.6 (origen → destino → roles,
  con el actor `sistema`); `transicionar(db, folio, nuevo_estado, actor, notas, contexto, request)` es la **única** forma de
  cambiar `folios.estado` (409 `TRANSICION_NO_PERMITIDA` con `roles_permitidos` y `destinos_posibles`; 409
  `CIERRE_INCOMPLETO` si faltan formulario de atención o firma; fija `fecha_inicio_atencion` y `fecha_cierre`; escribe
  historial + auditoría `folio.transicion.<estado>`). `ACTOR_SISTEMA` para transiciones automáticas; `comentar()` para
  eventos sin cambio de estado; `suscribir(fn)` registra consumidores en proceso (P05 chat/offline, P06 rutas y
  reasignación, P07 seguimiento, P10 SLA) con firma `async fn(db, folio, anterior, nuevo, actor, contexto)`.

  | Origen | Destinos → roles |
  |---|---|
  | capturado | en_revision → sistema · autorizado → sistema · cancelado → despachador, admin_prestador, admin_empresa, sistema |
  | en_revision | autorizado → despachador, admin_prestador, sistema · pendiente_informacion → despachador, admin_prestador · cancelado → despachador, admin_prestador, admin_empresa, sistema |
  | pendiente_informacion | en_revision → operador, admin_un, supervisor_operadores, admin_empresa, mesa_control · cancelado → despachador, admin_prestador, admin_empresa |
  | autorizado | asignado → despachador, sistema · cancelado → despachador, admin_prestador, admin_empresa |
  | asignado | en_camino → sistema, tecnico · reasignado → despachador, sistema · cancelado → (los tres) |
  | reasignado | asignado → sistema, despachador |
  | en_camino | en_ejecucion → sistema, tecnico · cancelado → (los tres) |
  | en_ejecucion | cerrado → tecnico, sistema · pendiente_refaccion → tecnico |
  | pendiente_refaccion | en_ejecucion → admin_prestador, despachador · reasignado → despachador, admin_prestador · cancelado → (los tres) |
  | cerrado / cancelado | — (finales; superadmin puede ejecutar cualquier transición existente en la tabla) |

- **Captura** `services/folios_captura_service.py` (`POST /api/folios`): roles que capturan siempre (operador, admin UN,
  admin empresa, supervisor de operadores, mesa de control); técnico con `crear_folio_en_campo` y despachador con
  `crear_folios` del cliente. Orden literal de validaciones: 1 confirmación de UN (si falta, queda `capturado` con
  trigger `confirmacion_un_faltante` y notificación; se completa con `POST /{id}/confirmar-un`) · 2 contrato activo
  (`sin_contrato`) · 3 duplicado abierto (409 `FOLIO_DUPLICADO_BLOQUEADO` con auditoría, o 422 `JUSTIFICACION_REQUERIDA`
  hasta enviar `folio_duplicado_justificacion`) · 4 severidad por matriz (`severidad_no_configurada` + alerta
  `MATRIZ_SEVERIDAD_INCOMPLETA`) · 5 garantía con `revision_obligatoria_garantia` (`garantia`) · 6 flag del tipo de
  falla (`tipo_falla_flag`) · 7 horario del contrato en la zona horaria de la UN (`fuera_horario`) · 8 palabras clave
  (`keyword_alerta`). Varios triggers se acumulan; con alguno el folio pasa a `en_revision` (sistema); si todas pasan,
  entra al punto de decisión D_MULTI. `respuesta_id` del formulario de captura es opcional (sin formulario resuelto se
  captura igual). Override de severidad: `PUT /{id}/severidad` (despachador/admin prestador, en revisión, razón).
- **Aprobación** `services/aprobacion_service.py`: `nivel_entrada(reglas, monto, criticidad, tipo_folio)` → la regla más
  restrictiva gana; reglas por `monto` (`<`, `<=`, `>`, `>=`, `entre`), `criticidad` (`en`) y `tipo_trabajo` (`igual`,
  `en`). Sin reglas aplicables → `autorizado` directo. Críticos A/B con `autorizacion_automatica_criticos` → `autorizado`
  con decisión `auto_aprobado` (canal `sistema`). El flujo vive dentro de `en_revision`: `aprobacion_flujos.nivel_actual`
  y `vence_at` en el detalle. Aprobadores: Nivel 1 `admin_un` (UN del folio en `usuario_un`), Nivel 2
  `supervisor_operadores` (UN directa o por grupo), Nivel 3 `admin_empresa`. `aprobar` en el último nivel → `autorizado`
  (y SLA prometido); nivel intermedio (solo con `aprobacion_secuencial` o tras escalado) → sube y notifica. `rechazar`
  exige `razon_rechazo` → `modulo_destino`, folio `cancelado` y evento `folio.derivado_a_modulo` en el historial con
  `{modulo_destino, razon_rechazo, decision_id, modulo_destino_id: null, procesado_por_p07: false}`.
- **Timeouts**: `aprobacion_alertas_timeout.vence_at` = momento real de programación + `tiempo_limite_horas`; Celery
  `acma.evaluar_timeouts_aprobacion` cada 60 s (`aprobacion_service.evaluar_timeouts`) aplica `escalar`,
  `bloquear_alertar` (flujo `bloqueado`, el aprobador aún decide), `autorizar_automatico` y `depende_criticidad`
  (A/B autoriza, C/D bloquea); el Nivel 3 solo admite las dos últimas (422 en API, CHECK en BD).
- **Endpoints** `/api/folios`: listado con alcance por rol y filtros; `verificar-duplicado`; `pendientes-aprobacion`;
  `politicas`; `keywords`; `aprobacion/configuracion|reglas|niveles`; `POST` captura; `GET /{id}` (archivo completo con
  secciones vacías `chat`, `reasignaciones`, `financiero`, más `acciones` válidas para el actor y `puede_aprobar`);
  `historial`; `transicion` genérica y atajos (`autorizar`, `pedir-informacion`, `responder-informacion`, `asignar`,
  `reasignar`, `en-camino`, `confirmar-llegada`, `pendiente-refaccion`, `reanudar`, `cerrar`, `cancelar`,
  `confirmar-un`, `comentario`); `monto-estimado`; `severidad`; `atencion` (vincula la respuesta enviada del técnico y
  registra sus evidencias; la firma cuenta para el cierre); `evidencias`; `refacciones`; `aprobacion/aprobar|rechazar`.
- **Eventos a consumir en prompts siguientes**: P05 — `POST /{id}/atencion`, `POST /{id}/evidencias` y las transiciones
  `en-camino`/`confirmar-llegada`/`cerrar` desde la app del técnico; `confirmar-un` desde la del operador; `capturarFolio`
  en `frontend/src/services/folios.ts` es la puerta a interceptar con la cola offline. P06 — `reasignado → asignado` con
  razón (hoy `reasignar` + `asignar`), asignación automática con `ACTOR_SISTEMA`, `orden_en_ruta`/`ventana_*`. P07 —
  historial `folio.derivado_a_modulo` (crear el registro del módulo y llenar `aprobacion_decisiones.modulo_destino_id`),
  canales `push`/`minuta` reales (`services/notificaciones.py` es un stub en log). P10 — `folio_sla` real y pausas a
  partir de `fecha_inicio_atencion`/`fecha_cierre` y del historial.
- **Frontend**: `types/folios.ts`, `services/folios.ts` (incluye `ACCIONES` destino → ruta y la tabla de transiciones
  cacheada), `pages/folios/{Folios,FolioDetalle,CapturaFolio,Aprobaciones}.tsx`, `services/notificaciones.ts` (stub).
- **Seed** (`scripts/seed_folios.py`): políticas (`CD-`), 6 reglas (A 5,000 / B 20,000, A/B → N2, preventivo → N1,
  especial → N2), 3 niveles (4 h escalar · 12 h depende_criticidad · 24 h bloquear), criticidad en los 12 equipos,
  4 palabras clave, horario L–V 08–20 / S 09–14 y 15 folios (CD-000001 cerrado … CD-000015 en ejecución).

### Campo, offline y chat (P05)
- **Tablas (0005)**: chat (`chats` UNIQUE(folio, canal), `chat_participantes`, `chat_mensajes` con `id_cliente` UNIQUE por chat,
  `timestamp_dispositivo`, `leido_por_json`, `datos_json`, `oculto`; `chat_archivos`; `chat_eventos_sistema`), sincronización
  (`sincronizacion_dispositivos`, `sincronizacion_conflictos`, `sincronizacion_mutaciones` = bitácora idempotente por
  (usuario, id_cliente)), `suscripciones_push` y `folio_politicas_tenant.plazo_encuesta_horas` (48). Trigger
  `acma_chat_mensaje_inmutable()`: en folio cerrado solo cambia `leido_por_json`; sin DELETE. RLS de `chat_mensajes` y
  `chat_archivos`: lectura solo para participantes activos (y plataforma); **las políticas de escritura van por comando**
  (INSERT/UPDATE/DELETE), porque una `FOR ALL` también concede SELECT — misma corrección aplicada a `folios` (el técnico ya
  no lee folios ajenos ni por RLS). Inserciones de mensajes/eventos sin `RETURNING` (ids generados en el cliente) porque
  quien transiciona puede no ser participante.
- **Sincronización** (`services/sync_service.py`, `/api/sync`): `GET /catalogos?desde=&dispositivo_id=` → paquete por rol
  (operador/admin UN/supervisor/admin empresa/mesa: `unidades`, `equipos` con `con_contrato_activo`, `familias_equipo`,
  `tipos_equipo`, `tipos_falla`, `niveles_severidad`, `formularios` de captura + `formularios_ids`; técnico: `folios`
  abiertos asignados + `folios_ids`, `formularios` de atención/preventivo, `formulario_por_folio`, `refacciones` [] (P09),
  `biblioteca` [] (Fase 2)); todo con `activo` para bajas lógicas y `servidor_at` como siguiente `desde`.
  `POST /mutaciones` {dispositivo_id, version_app, plataforma, mutaciones[{id_cliente, tipo, timestamp_dispositivo,
  payload}]} → por operación `aplicada | duplicada | rechazada {codigo, mensaje}` con `entidad_id`; se aplican en orden
  dentro de savepoints (una rechazada no detiene), idempotentes por la bitácora, y los ids del payload pueden ser
  `id_cliente` de operaciones previas (`folio_id`, `respuesta_id`, `referencia_id`). Tipos: `crear_folio` (payload =
  `FolioEntrada`; `capturado_at` = hora del dispositivo), `transicion` {folio_id, estado, notas, contexto} (→
  `transicionar(..., momento=timestamp_dispositivo)`: `fecha_inicio_atencion`/`fecha_cierre` reales y
  `datos_contexto_json.timestamp_dispositivo`; `asignado` con `contexto.tecnico_id` usa `asignar`; `autorizado` en
  revisión usa `autorizar_manual`), `guardar_respuesta` {respuesta_id | crear{formulario_id, origen, referencia_id,
  contexto}, respuestas, version_hash?}, `enviar_respuesta` {respuesta_id, respuestas?} (→ `enviar(..., momento)`),
  `subir_evidencia` {respuesta_id, campo_clave, nombre, mime, hash_sha256, contenido_base64}, `agregar_refaccion`
  {folio_id, descripcion, cantidad, origen, costo_unitario, articulo_id} y `mensaje_chat` {chat_id, contenido_texto,
  tipo, contenido_base64?}. Reglas §6.2: catálogos server-wins (el paquete manda); capturas client-wins (se aplican y, si el
  servidor cambió después de la hora del dispositivo o el `version_hash` difiere, queda un `sincronizacion_conflictos`
  con `client_wins`); inventario merge con alerta = gancho `aplicar_movimiento_inventario()` que P09 implementa.
  Evidencias en dos pasos: `POST /evidencias/iniciar` (hash + id_cliente → pendiente | existente | duplicada) y
  `PUT /evidencias/{id_cliente}/archivo` (multipart reintentable; mismo hash no se duplica). `GET /conflictos`.
- **Chat** (`services/chat_service.py`, `services/ws_manager.py`, `routers/chat.py`): los tres chats se crean con el
  evento `folio.creado` (`folio_estados.suscribir_creacion`) con participantes fijos §6.8.1 (campo: quien capturó;
  operativo: Admin UN de la UN; interno: Admin prestador); el técnico entra a `campo` al asignarse y el despachador a
  `operativo`/`interno` al actuar. `PUEDE_AGREGAR` literal de la tabla. Eventos de sistema por transición (mensaje
  `tipo=sistema` + `chat_eventos_sistema`): capturado (campo), asignado/reasignado/en_camino/en_ejecucion/
  pendiente_refaccion (campo y operativo), autorizado (operativo e interno), cerrado y cancelado (los tres). Folio
  cerrado: solo `imagen` con `datos_json.evidencia_posterior=true` (§6.8.3c); cancelado antes de asignar: chats
  `archivado` y mensajes `oculto` (solo superadmin los lee). Endpoints `GET /api/folios/{id}/chats`,
  `GET/POST /api/chats/{id}/mensajes`, `POST …/mensajes/archivo`, `GET …/archivos/{id}`, `POST …/leido`,
  `POST/DELETE …/participantes`. Tiempo real: `WS /ws/chats/{chat_id}?token=` (eventos `conectado`, `mensaje`, `leido`,
  `pong`) y fallback `GET /api/chats/{id}/stream?token=` (SSE, latido cada 15 s); el envío siempre es HTTP POST.
  `ws_manager.gestor` reparte en el proceso y publica por Redis pub/sub (`TIEMPO_REAL_MODO=redis|local`).
- **Cierre en campo** (`services/folio_cierre_service.py`): `POST /api/folios/{id}/firma` (multipart; solo operador/Admin
  UN de la UN con el folio en ejecución; `FolioEvidencia` tipo firma + evento `firma` + push «responde la encuesta»),
  `GET …/encuesta/disponible` y `POST …/encuesta` {nps_score 0–10, comentario, respuestas, timestamp_dispositivo}
  (formulario tipo `encuesta` resuelto por P03 → respuesta `origen=encuesta` enviada; comentario obligatorio si
  nps ≤ 6; disponible tras la firma, antes o después del cierre dentro de `plazo_encuesta_horas`). Al cerrar sin
  encuesta queda el evento `encuesta.pendiente`. La firma también puede venir del campo `firma` del formulario de
  atención del técnico (P04 la mapea), que es la «entrega del dispositivo al operador».
- **Push** (`services/push_service.py`, `/api/push`): `GET /clave-publica`, `POST/DELETE /suscripcion`; envío con
  `pywebpush` si hay `VAPID_CLAVE_PUBLICA/PRIVADA` (`scripts/generar_vapid.py`), si no solo log; suscriptor de
  transiciones notifica al operador (todos los cambios) y al técnico (asignación, autorización, cancelación) en una
  sesión de sistema. `public/sw-push.js` muestra la notificación y abre `datos.url`.
- **Frontend offline**: `services/db.ts` v2 (`catalogos_cache`, `folios_cache`, `formularios_cache`,
  `respuestas_borrador`, `evidencias_pendientes`, `mutaciones_pendientes`, `chat_mensajes_cache`, `chat_pendientes`;
  `usarBaseLocal()` para pruebas), `services/syncEngine.ts` (`encolar`, `encolarEvidencia`, `procesar` serializado,
  reintentos 1/4/16/64/256 s y `atencion` al 5.º, `reintentar`, `descartar`, `refrescarCatalogos`, `catalogo`,
  `resolverId`, `conRespaldoOffline`, `simularSinConexion` para pruebas), `services/offline/transporteRespuestas.ts`
  (transporte híbrido instalado en `main.tsx` con `usarTransporte`), `services/campo.ts` (folios/transiciones/refacciones
  con respaldo, firma, encuesta, catálogos cacheados, `registrarPush`), `services/chat.ts` (`conectarTiempoReal` WS→SSE),
  `useConexion` + `IndicadorConectividad` (cabecera), página `/sincronizacion`. Service worker: precache del shell,
  `NetworkFirst` para `GET /api/*` (no `/stream`), `importScripts('sw-push.js')`. `AuthContext` descarga el paquete de
  catálogos y registra push al iniciar sesión de operador, técnico y Admin UN.
- **Pantallas**: `/campo` (`pages/campo/Campo.tsx` por rol) → operador/Admin UN: `InicioOperador` (folios de su UN,
  técnico, ETA «Fase 2»), `/campo/nuevo` (`CapturaFolio modoCampo`: táctil, guía por paso, catálogos cacheados,
  captura sin red), `/campo/folio/:id` (`DetalleOperador`: línea de tiempo, chat campo, firma/encuesta),
  `/campo/folio/:id/cierre` (`CierreOperador`: lienzo a pantalla completa + NPS); técnico: `MisFolios` (hoy/próximos,
  «Nuevo folio» si `crear_folio_en_campo`), `/campo/folio/:id` (`AtencionTecnico`: acciones por la tabla de P04,
  formulario de atención resuelto por P03 o desde caché, refacciones con costo si `ver_costo_refacciones`, chat).
  `components/chat/ChatFolio.tsx` integrado en `FolioDetalle` (todos los roles). `GET /api/configuracion/mis-permisos`
  da los permisos efectivos del técnico/despachador.
- **Para P06**: reasignación → `transicionar(reasignado)` emite el evento de chat `folio.reasignado` y `asignar` vuelve a
  agregar al técnico; rutas/ETA sustituyen el «Fase 2» de las tarjetas. **Para P07**: canales reales de notificación
  (hoy `notificaciones.py` log + push web); la minuta puede usar `chat_eventos_sistema`. **Para P09**:
  `sync_service.aplicar_movimiento_inventario()` (merge con alerta de stock negativo) y `refacciones` del paquete.
  **Para P10**: `fecha_inicio_atencion`/`fecha_cierre` ya traen la hora real del dispositivo.
- **Seed** (`scripts/seed_campo.py`): formulario «Encuesta de satisfacción (operador)» publicado y asignado, chats de los
  15 folios (creados por el gancho o rellenados), mensajes en CD-000015 (uno con retraso), CD-000001 (cerrado, inmutables)
  y CD-000014, y una suscripción push demo del operador.

### Preventivos y reasignaciones (P06)
- **Tablas (0006)**: `planes_mantenimiento` (prestador, tenant opcional = todos los clientes, tipo de equipo, versión,
  estado, `tiempo_ventana_dias`, formulario y severidad opcionales), `plan_triggers` (ENUM `tipo_trigger_plan`: Fase 1
  `tiempo_fijo` {cada_dias} | {cada, unidad} y `calendario` {mes, dia} | {fechas}; `medidor_umbral`, `medidor_intervalo`,
  `evento`, `combinado` existen en el ENUM pero responden **403 TRIGGER_FASE_2**), `plan_tareas` (orden, minutos,
  `habilidad_requerida_id`), `plan_materiales` (`articulo_id` sin FK hasta P09), `plan_ejecuciones` (dedupe por plan +
  equipo + fecha), `equipo_planes` (UNIQUE equipo-plan; `fecha_proxima_ejecucion`, `fecha_ultima_ejecucion`,
  `ultimo_valor_medidor` para Fase 2), **`preventivos_calendario`** (una sola tabla para §6.9.1 y §7.6: UN obligatoria,
  equipo/plan/técnico opcionales, `fecha_programada`, `fecha_programada_original`, `fecha_real`, `desvio_dias`, estado
  `programado|generado|ejecutado|reprogramado|cancelado`, `folio_id`, `origen manual|plan`, `reprogramado_desde_id`),
  `calendario_publicaciones` (UNIQUE prestador-tenant-mes), `autorizaciones_preventivo` (tipo reprogramación/cancelación,
  solicitante, autorizador, canal `canal_aprobacion`, `fecha_nueva`, estado), `razones_reasignacion` (UNIQUE
  prestador-descripción; 7 literales de §6.8.2 sembradas por la migración y por `POST /api/prestadores`),
  `reasignaciones` (origen, destino, tipo `forzada|automatica`, razón, comentario, despachador) y
  `reasignacion_validaciones` (`habilidad_ok`, `refaccion_ok` NULL hasta P09, advertencias). `folios.plan_id` y
  `folios.calendario_id`; FK real de `formulario_asignaciones.plan_mantenimiento_id`. Tres alertas nuevas:
  `PREVENTIVO_VENCIDO_SIN_EJECUTAR` (umbral días tras fecha + ventana), `AUTORIZACION_PREVENTIVO_PENDIENTE` (24 h) y
  `CALENDARIO_MES_SIN_PUBLICAR` (día 25). RLS: tablas del prestador con `politicas_prestador(lectura_tenants=True)`; las
  ligadas al folio con políticas por comando como en P05.
- **Planes** (`services/planes_service.py`, `/api/planes`): `validar_trigger`, `proxima_fecha_trigger(tipo, parametros,
  desde, hoy)` (tiempo fijo = última ejecución + intervalo, con recorte de fin de mes; calendario = siguiente fecha
  fija posterior a hoy), `crear/editar` (editar reemplaza triggers/tareas/materiales, sube `version` una vez y recalcula
  la próxima fecha de los equipos), `asignar_equipo(plan, equipo, fecha_base)` (valida tipo de equipo y cliente
  vinculado) y `desactivar_equipo`. Admin prestador y Despachador editan; Admin empresa/Admin UN consultan.
- **Calendario** (`services/preventivos_service.py`): `GET/POST /api/preventivos/calendario` (filas con `un_id`,
  `equipo_id?`, `plan_id?`, `tecnico_id?`, `fecha_programada`), `PATCH …/calendario/{id}` (la fecha solo sin folio:
  409 `REQUIERE_AUTORIZACION`), `POST …/calendario/publicar?mes=AAAA-MM&tenant_id` (409 `MES_VACIO`; emite
  `calendario.publicado` → `notificaciones.enviar` roles admin_empresa/admin_un canales push+email y push web; **P07
  conecta el correo**), `GET …/publicaciones`, catálogo importable **`calendario_preventivos`** (cliente por RFC o razón
  social, UN, fecha, equipo/plan/técnico opcionales; duplicado por tenant+UN+equipo+fecha). `texto_desvio(desvio)` es el
  literal de §7.6: «realizado en la fecha programada», «realizado N día(s) antes de lo programado», «realizado con N
  día(s) de retraso», «pendiente de ejecución»; se expone en cada fila y en `GET /api/preventivos/texto-desvio`.
- **Generación nocturna**: tarea Celery `acma.generar_preventivos_programados` (beat 02:00, `workers/tareas/preventivos.py`)
  = `generar_programados(db, hoy, horizonte_dias=7)`: equipos con `fecha_proxima_ejecucion ≤ hoy+horizonte` → fila de
  calendario `origen=plan` + `generar_folio_preventivo` (folio `tipo_folio=preventivo` capturado por el sistema con
  confirmación de UN, severidad del plan o la más baja del prestador, formulario del plan o resuelto por P03 con
  `plan_id`, historial `capturado → autorizado` por `sistema` sin flujo de aprobación) + `plan_ejecuciones` + próxima
  fecha recalculada; después las filas manuales con equipo dentro del horizonte. Idempotente; cada equipo en su savepoint.
  `POST /api/preventivos/generar?hoy=&horizonte_dias=` ejecuta lo mismo a demanda (pruebas y operación).
- **Ciclo**: asignación con `tecnico_con_habilidad` ampliado (habilidad de la familia **y** las de `plan_tareas`: mensaje
  «refrigeracion + plan: plomeria»); `GET /api/preventivos/{folio_id}/plan` da tareas y materiales al técnico y el
  paquete offline resuelve el formulario tipo `preventivo` por folio. Reprogramación y cancelación: `POST
  /api/preventivos/{folio_id}/solicitar-reprogramacion|solicitar-cancelacion` (Despachador/Mesa/Admin prestador; una
  pendiente por folio: 409 `SOLICITUD_PENDIENTE`; 409 `NO_ES_PREVENTIVO`, `FOLIO_FINAL`; 422 `FECHA_REQUERIDA`) →
  `autorizaciones_preventivo` + evento `preventivo.solicitud_*` en historial y chat operativo + notificación
  `autorizacion.solicitada` (push + email P07) a los Admin UN de la UN y Admin empresa; `GET /api/preventivos/autorizaciones`
  (bandeja con `puede_resolver`), `POST …/{id}/autorizar|rechazar` {notas, canal app|push|minuta}. Autorizada:
  reprogramación = nueva fila del calendario con `reprogramado_desde_id` (la original queda `reprogramado` y conserva la
  fecha original), `folio.calendario_id` y `fecha_falla` actualizados, evento `preventivo.reprogramado`; cancelación =
  `transicionar(cancelado)` ejecutada por el solicitante con `autorizacion_id` en el contexto. Validador
  `folio_estados.suscribir_validacion`: un preventivo **no** se cancela desde los roles del prestador sin
  `contexto.autorizacion_id` (409 `REQUIERE_AUTORIZACION`); Admin empresa sí puede directamente. Al cerrar
  (`_al_cerrar_preventivo`): `fecha_real`, `desvio_dias`, estado `ejecutado`, `plan_ejecuciones` y
  `equipo_planes.fecha_ultima/proxima`.
- **Reasignación forzada** (`services/reasignacion_service.py`): `GET /api/folios/{id}/reasignacion/candidatos` (técnicos
  activos del prestador con `habilidad_ok`, `habilidad_requerida`, `carga_dia`, `refaccion_ok` NULL, `es_actual`,
  advertencias), `POST /api/folios/{id}/reasignar` {tecnico_destino_id, razon_id, comentario, confirmar_advertencias,
  razon_sin_habilidad}: 409 `REASIGNACION_NO_PERMITIDA` en ejecución («el técnico ya está en la unidad»), en camino o
  estados no reasignables (válidos: asignado, pendiente_refaccion); 422 `MISMO_TECNICO`, `RAZON_INVALIDA`
  (catálogo del prestador, activa), `RAZON_REQUERIDA`; 403 `TECNICO_SIN_HABILIDAD` salvo Admin prestador o despachador
  con `asignar_tecnico_sin_habilidad` (y razón); 409 `CONFIRMACION_REQUERIDA` con la lista de advertencias (hoy siempre
  «Refacción no verificada» hasta P09) si no se confirma. Ejecuta `reasignado → asignado` (misma operación, historial
  de P04 con `sin_habilidad`/`razon`), guarda `reasignaciones` + `reasignacion_validaciones`, saca al técnico anterior
  del chat de campo y mete al nuevo, evento `folio.reasignado` en campo y operativo, push a ambos técnicos.
  `GET /api/folios/{id}/reasignaciones` (también en `GET /api/folios/{id}` → `reasignaciones`),
  `GET /api/reasignaciones/reporte?desde&hasta&tenant_id` (total y % por razón, técnico origen/destino y tipo),
  `GET/POST/PATCH /api/reasignaciones/razones`. La ruta transitoria `POST /api/folios/{id}/reasignar` de P04 (solo
  marcar `reasignado`) se sustituyó por esta.
- **Frontend**: `types/preventivos.ts`, `services/preventivos.ts`; módulos `preventivos` (`/preventivos/calendario`,
  `pages/preventivos/Calendario.tsx`: mes, cliente, estados, carga por filas, edición, publicar, «Generar folios ahora»,
  desvío literal por fila), `/preventivos/planes` (`Planes.tsx`: lista, editor con los 6 triggers del ENUM y los de Fase
  2 deshabilitados, tareas con habilidad, materiales, equipos con fecha base), `/preventivos/autorizaciones`
  (`Autorizaciones.tsx`), `reasignaciones` (`/reasignaciones/reporte`, `pages/reasignaciones/Reporte.tsx` con catálogo
  de razones). `FolioDetalle`: botón **Reasignar** (`pages/folios/Reasignar.tsx`: candidatos con insignias, razón del
  catálogo, advertencias con casilla de confirmación ante 409, razón sin habilidad) y `PanelPreventivo` (solicitar
  reprogramación/cancelación, autorizar/rechazar, histórico). App del técnico: insignia **Preventivo** + plan, lista de
  verificación de tareas (`PlanDelTecnico.tsx`, marcas en IndexedDB, operable sin red) y materiales «Usar como refacción».
- **Seed** (`scripts/seed_preventivos.py`): formulario «Inspección preventiva · Prestador Demo» asignado a `preventivo`,
  3 planes (trimestral de refrigeradores cada 3 meses, semestral de minisplits cada 180 días, anual de iluminación el
  15/01) con 9 tareas y 6 materiales, 6 equipo_planes, generación simulada del 05 y 20 de octubre, calendario con 8 filas
  (2 ejecutados con desvío +2/−3, 1 reprogramado + su nueva fecha, 1 cancelado, 3 programados de noviembre: uno de UN
  completa), noviembre publicado, 7 razones y 3 reasignaciones (una sin habilidad por el Admin prestador).
- **Para P07**: eventos `calendario.publicado` y `autorizacion.solicitada`/`*_autorizada` ya pasan por `notificaciones.enviar`
  con canal `email`; la minuta puede leer `preventivos_calendario` y `texto_desvio`. **Para P09**: `plan_materiales.articulo_id`,
  `reasignacion_validaciones.refaccion_ok` y la advertencia «Refacción no verificada» se resuelven con el inventario del
  vehículo. **Para P10**: `plan_ejecuciones.desvio_dias` y la alerta de preventivo vencido alimentan los KPIs.

### Minuta y seguimiento (P07)
- **Tablas (0007)**: `hallazgos` (folio opcional, UN, equipo, descripción, `nivel_urgencia`, `foto_evidencia_id`, tipo preventivo/
  correctivo, origen `formulario_atencion|chat|manual`, `respuesta_id`, `mensaje_id`, estado de respuesta, opción §7.4, módulo y
  registro destino), `peticiones_cliente`; minuta: `minuta_configuracion` (por prestador-tenant: modo, `hora_envio`, ventana 30
  min, plazo 24 h y los umbrales de los contadores), `minutas` (UNIQUE tenant-prestador-fecha-tipo-UN; estados `borrador →
  pendiente_validacion → enviada → respondida | vencida`, `enviada_sin_validacion`, `vence_respuesta_at`, `pdf_key`, `hash_pdf`,
  `urgente`), `minutas_secciones` (una fila por sección con `contenido_json`), `minutas_respuestas` (opción, canal
  app/email/push, módulo y registro o folio generado), `minutas_destinatarios`; notificaciones: `notificaciones` (por usuario y
  canal, estado `pendiente|enviada|fallida|omitida`, `leida_at`, `url`; sin RETURNING como el chat) y `notificacion_preferencias`
  (`canales_json` por evento, `*` = todos); módulos: `periodos_presupuestales`, `cotizaciones` (`numero` COT-00001 por prestador,
  `detalle_json.partidas`, `estado_desde`, `trabajo_especial_id` sin FK hasta P08, `pdf_key`/`hash_pdf`,
  `pasar_a_presupuesto_si_rechaza`), `cotizacion_envios_externos`, `hallazgos_presupuesto` (`ultima_revision`,
  `historial_revisiones_json`, `reactivado_como`), `seguimientos_internos` (proveedor, fecha acordada, referencia,
  `ultima_actualizacion`, `justificacion_cierre`), `reprogramaciones` (`fecha_tentativa`, `trabajo_coordinado` + `variante`,
  `tercero_completo`, `folio_coordinado_id`, `fechas_vencidas_count`, `escalada_empresa`), `modulo_historial` (**append-only**,
  trigger `acma_auditoria_inmutable`); clasificación: `clasificacion_configuracion` (severidades no críticas, plazo, umbral,
  `admin_empresa_puede_clasificar`, `puntos_json`), `folio_clasificaciones`, `admin_un_calificacion`. Además
  `trigger_revision` gana `pendiente_clasificacion`, `folio_sla` gana `autorizado_en` y `excluir_sla_por_cliente` (P10), y
  `aprobacion_decisiones` acepta **una sola** actualización NULL → id de `modulo_destino_id` (trigger `acma_decision_solo_modulo`).
  18 alertas evaluadas (14 nuevas + 5 del catálogo base: `COTIZACION_SIN_PREPARAR`, `COTIZACION_SIN_RESPUESTA`,
  `SEGUIMIENTO_SIN_UPDATE`, `REPROGRAMACION_FECHA_VENCIDA`, `FOLIO_SIN_CLASIFICAR`). RLS: tablas con tenant+prestador con las
  políticas por comando de P05/P06; `notificaciones` las lee/actualiza su dueño o el tenant/prestador del evento (la bandeja
  filtra por usuario en el servicio); `notificacion_preferencias` las lee quien notifica (tenant o prestador vinculados).
- **Notificaciones** (`services/notificaciones_service.py`): `notificar(db, evento, destinatarios, datos, asunto=, cuerpo=, url=,
  tenant_id=, prestador_id=, canales=, adjuntos=, plantilla=)` resuelve canales por preferencia del usuario (`canales_de`:
  preferencia del evento → preferencia `*` → `CANALES_POR_EVENTO` → `app, push, email`), inserta una fila por canal y envía:
  `app` inmediata (bandeja), `push` (web-push de P05) y `email` (`services/correo.py`) desde `procesar()`, en línea si
  `NOTIFICACIONES_ENVIO_INLINE=true` (pruebas, sin Celery) o en la tarea `acma.enviar_notificaciones` (+ barrido
  `acma.enviar_notificaciones_pendientes` cada 2 min). `whatsapp` y `sms` quedan `omitida` «canal Fase 2». La bitácora
  `notificaciones.ENVIADAS` de P04–P06 se conserva; los stubs de aprobaciones (`aprobacion.pendiente`, `aprobacion.bloqueada`),
  captura (`folio.espera`, `folio.revision`) y preventivos (`calendario.publicado`, `autorizacion.solicitada`) ya pasan por
  `notificar()`. `destinatarios_por_rol(db, roles, tenant_id=, prestador_id=, un_id=)` (Admin UN solo los de la UN). Catálogo de
  eventos `EVENTOS`; API `/api/notificaciones` (bandeja, `no-leidas`, `leidas`, `eventos`, `preferencias`, `procesar`).
  Correo: SMTP genérico con `aiosmtplib` (`SMTP_HOST/PORT/USER/PASSWORD/FROM/TLS`); sin `SMTP_HOST` modo **stub** que guarda
  el `.eml` en el almacenamiento (`correo/AAAA/MM/DD/<id>.eml`) y registra en `correo.ENVIADOS`. Plantillas en
  `backend/plantillas/correo/` (`base.html` con logo/colores del prestador, `generico`, `minuta`, `cotizacion`), rellenadas con
  `correo.plantilla()` (escapa todo salvo claves `*_html`). PDF: `services/pdf.py` usa WeasyPrint cuando carga; si faltan sus
  librerías nativas (GTK/Pango en Windows) usa un generador PDF mínimo propio; `sha256()` = `hash_pdf`.
- **Hallazgos y peticiones** (`services/hallazgos_service.py`): el esquema de formularios (P03) admite `genera_hallazgo` por campo
  (`HallazgoMapeo`: `campo_descripcion`, `campo_urgencia` texto o slider 1–10, `urgencia_fija`, `campo_foto`, `condicion_campo` /
  `condicion_valor`); al enviar una respuesta `folio_atencion` `desde_respuesta()` crea los hallazgos. Un mensaje de chat con
  texto se marca con `POST /api/chats/{chat}/mensajes/{id}/marcar` {como: hallazgo|peticion} (técnico, operador, Admin UN,
  Despachador; `datos_json.marcado_como` evita duplicar). Captura manual `POST /api/hallazgos`. `GET /api/hallazgos`,
  `GET /api/peticiones`.
- **Minuta** (`services/minuta_service.py`): `generar(db, prestador, tenant, fecha)` → una minuta por UN con actividad
  (`unidades_con_actividad`: eventos de folio, hallazgos, peticiones o preventivos ejecutados ese día en la zona horaria del
  tenant) y una global; idempotente por la UNIQUE. **`minutas_secciones`** (`seccion`, `orden`, `contenido_json`):
  `contadores` {cotizaciones{total, pendientes_enviar, pendientes_autorizar, color, umbral}, por_presupuesto, seguimiento_interno,
  reprogramacion} con los colores/umbrales literales de §7.3 (rojo/amarillo según `minuta_configuracion`), `preventivos`
  {items: [{un, equipo, tecnico, hora, fecha_programada, fecha_real, desvio_dias, texto_desvio}]} con `texto_desvio()` de P06,
  `hallazgos` {items: [{hallazgo_id, descripcion, equipo, urgencia, foto_url, estado_respuesta, opcion_respuesta,
  pendiente_de_dias_anteriores}]}, `cotizaciones` {pendientes_enviar, pendientes_autorizar}, `trabajos_especiales` {nota P08},
  `peticiones` {items}, `pendientes_autorizacion` {items} (§6.8.7 canal minuta) y, solo en la global de la primera minuta del mes o
  del inicio del período presupuestal, `recordatorio_presupuesto` {items}. Modo `automatica` → `enviar()` al generar; modo
  `con_validacion` → `pendiente_validacion` + aviso al despachador; `validar(actor, notas)` o `vencer_validaciones()` (tras
  `ventana_validacion_min`, marca `enviada_sin_validacion`). `enviar()`: PDF + `hash_pdf`, `notificar("minuta.enviada", …,
  canales=[app, push, email], plantilla="minuta", adjuntos=[PDF])` a los Admin UN de la UN (minuta UN) o al Admin empresa
  (global), `minutas_destinatarios`, `vence_respuesta_at` solo si hay hallazgos pendientes. `responder(actor, minuta,
  hallazgo, opcion, canal, fecha_tentativa, proveedor, trabajo_coordinado, variante)` ejecuta el efecto literal de §7.4 vía
  `seguimiento.entradas.desde_hallazgo` y refleja la respuesta en las secciones de la minuta UN y global del día; al responder
  todos → `respondida`. `vencer_respuestas()` → `vencida` + `MINUTA_SIN_RESPUESTA`. Tarea `acma.generar_minutas` (cada 10 min:
  genera a la `hora_envio` local de cada tenant, vence ventanas y plazos) y `POST /api/minutas/generar|procesar-pendientes`.
  Endpoints `/api/minutas` (config GET/PUT, lista, detalle con secciones/hallazgos/respuestas/destinatarios, `pdf`, `validar`,
  `hallazgos/{id}/responder`).
- **Módulos de seguimiento** (`services/seguimiento/`): `base.py` (alcance por rol, `historial()` append-only, `exigir_rol`,
  `exigir_justificacion`, `dias_en_estado`, `alertas_activas`, `transicionar` con `estado_desde`), y un módulo por tabla con
  `TRANSICIONES` literal de §7.7 y **`cambiar_estado(db, actor, registro, nuevo, notas, request, **campos)`**: valida destino y
  rol, exige campos (`con_proveedor`/`fecha_asignada`/`tercero_confirmado`: proveedor + fecha, referencia opcional) y
  justificación escrita (`resuelto`, `cancelado`, `descartado`), escribe `modulo_historial`, audita y notifica (bandeja).
  Cotizaciones: `crear` (COT-n, aviso simultáneo a Mesa, Despachador y Admin prestador), `preparar`, `enviar_cliente` (PDF +
  correo con adjunto a Admin UN/empresa), `responder` (autorizar/rechazar; rechazo con `pasar_a_presupuesto_si_rechaza` →
  diferido), `enviar_externo` (PDF por correo a terceros, registrado, sin cambiar estado), `convertir_en_trabajo_especial` →
  **501 `DISPONIBLE_EN_P08`**. Presupuesto: `revisar`, `reactivar(como=folio|cotizacion)`, `descartar(razón)`, `monto_potencial`,
  `periodo_actual()` / `inicio_de_periodo()` (mensual, trimestral, semestral, anual o fechas). Interno: `actualizar` (novedad).
  Reprogramación: `registrar_fecha_vencida()` (contador acumulado entre `fecha_asignada` y `tercero_confirmado`; al llegar a 3
  `escalada_empresa` + `REPROGRAMACION_ESCALADA_EMPRESA` + aviso al Admin empresa), `confirmar_tercero()` (variante A → crea el
  folio correctivo del técnico con `entradas.folio_directo`). `entradas.py`: `desde_hallazgo` (§7.4), `desde_clasificacion`
  (§6.10.5), `desde_derivacion` (§6.8.7: el rechazo del flujo crea el registro y llena `aprobacion_decisiones.modulo_destino_id`;
  `procesar_derivaciones_pendientes()` migró los folios demo) y `folio_directo` (correctivo del sistema directo a Autorizado, sin
  flujo multinivel). API `/api/seguimiento/{cotizaciones|presupuesto|interno|reprogramacion}` (listado con filtros tenant/UN/
  período/estado/urgencia, alta directa, detalle con historial, `estado` para el Kanban), acciones propias
  (`preparar`, `enviar`, `responder`, `convertir`, `pdf`, `enviar-externo`, `reactivar`, `descartar`, `revisar`,
  `monto-potencial`, `actualizar`, `confirmar-tercero`), `por-un/{un_id}`, `periodos-presupuestales`, `reporte/ejecutivo`
  (JSON, `.xlsx`, `.pdf`: tiempo promedio por módulo, tasa de conversión, hallazgos recurrentes por tipo de equipo, monto
  potencial).
- **Clasificación** (`services/clasificacion_service.py`): en la captura (P04), si el tenant tiene `clasificacion_configuracion`
  activa y la severidad es no crítica, el folio queda `en_revision` con el trigger `pendiente_clasificacion` (sin flujo) y se
  avisa al Admin UN; `pendientes()` (sus UNs; Admin empresa si está habilitado) con plazo restante; `clasificar(opcion,
  fecha_tentativa, notas)`: `autorizado` → `transicionar(autorizado)` + `folio_sla.autorizado_en`; las otras cuatro crean el
  registro del módulo y cancelan el folio con razón (queda enlazado por `derivaciones`). Tardía → `dentro_de_plazo=False`,
  `horas_retraso`, `excluir_sla_por_cliente`. `calificar(tenant, periodo)` por Admin UN: base − retraso proporcional (tope) −
  pendientes vencidos − minutas sin respuesta/tardías → `admin_un_calificacion` con `eventos_json`; bajo el umbral dispara
  `ADMIN_UN_BAJO_DESEMPENO` y avisa al Admin empresa. Tarea `acma.calificar_admin_un` (06:30: calificación del período y
  recordatorios de inicio de período presupuestal). API `/api/clasificacion` (config, pendientes, `{folio_id}`,
  calificaciones, `calificaciones/calcular`).
- **Frontend**: `types/minutas.ts`, `services/minutas.ts`; módulos con ruta `minuta` (`/minutas`, `pages/minutas/Minutas.tsx`
  con bandeja de validación y configuración por cliente; `/minutas/:id` `ResponderMinuta.tsx`: dos bloques, PDF, validación y
  respuesta por hallazgo con las seis opciones y captura de fecha/tercero/variante), `seguimiento` (`/seguimiento`,
  `pages/seguimiento/Seguimiento.tsx`: cuatro pestañas, listado con días en estado y próxima alerta, columna «Estado del trabajo
  especial» vacía hasta P08, Kanban con arrastre/«Mover a…» para Admin prestador y Despachador, vista por UN, reporte
  ejecutivo con exportación, detalle con acciones por rol), `clasificacion` (`/clasificacion`, pantalla §6.10.5 + calificación +
  configuración), `notificaciones` (`/notificaciones`, bandeja y preferencias; campana `CampanaNotificaciones` en la cabecera).
  `FolioDetalle` muestra hallazgos, derivaciones y clasificación; `ChatFolio` permite marcar un mensaje como hallazgo o petición.
- **Seed** (`scripts/seed_minuta.py`): configuración de minuta, período trimestral, severidades no críticas, 6 hallazgos en 6
  folios, 2 peticiones, minutas de los últimos 3 días (UN respondida y vencida, hoy pendiente de validación), 3 cotizaciones
  (enviada con PDF, autorizada con envío externo, solicitada), 2 diferidos (uno migrado del rechazo de P04), 2 seguimientos
  internos (uno con proveedor), 2 reprogramaciones (una coordinada A con 2 fechas vencidas), 4 folios no críticos pendientes
  de clasificar y la calificación del período.
- **Para P08**: `cotizaciones.convertir_en_trabajo_especial()` (501) y la columna `trabajo_especial_id`; la sección
  `trabajos_especiales` de la minuta recibe nuevos/en proceso/terminados; la columna «Estado del trabajo especial» del listado.
  **Para P09**: `periodos_presupuestales` rige el recordatorio y debe ligarse al presupuesto; `hallazgos_presupuesto.monto_estimado`
  y `monto_potencial`. **Para P10**: `folio_sla.autorizado_en` (inicio del SLA) y `excluir_sla_por_cliente`; `modulo_historial`
  y `admin_un_calificacion` alimentan KPIs. **Fase 2**: canales `whatsapp`/`sms` (hoy `omitida`).

### Trabajos especiales y OC de activos (P08)
- **Tablas (0008)**: `trabajos_especiales` (`numero` TE-000001 por prestador, tenant/prestador/UN, `equipo_id`, `cotizacion_id`,
  `hallazgo_id`, `descripcion`, `detalle_json`, 8 estados, `estado_desde`, `urgencia`, `creado_por_id/rol`, `formulario_id`,
  `respuesta_formulario_id`, `monto`, `cotizacion_retroactiva_id`, `fecha_programada/inicio/cierre`, `tecnico_ids_json`,
  `tecnico_responsable_id`, `folio_id` (folio operativo), `razon_cancelacion`, `version_enviada`, `enviado_at/aceptado_at/programado_at`),
  `te_respuesta_cliente` (**append-only**: decisión por versión enviada, comentario, canal), `te_evidencias` (avance/cierre/firma/documento,
  `evidencia_id` del formulario o `archivo_key` propio), `te_historial` (**append-only**, tabla propia del TE), `folio_activo_autorizacion`
  (uno por folio: 5 estatus §6.10.7, `numero_oc_provisional/definitivo`, `fecha_autorizacion_erp`, `decision_rechazo`,
  `periodo_presupuestal_destino`, `origen` captura/atencion, `datos_equipo_json` mapeado del formulario, `hallazgo_presupuesto_id`) y
  `folio_activo_historial` (**append-only**). Además `cotizaciones.trabajo_especial_id` ya es FK, `folios.es_instalacion_activo`,
  `folios.equipo_instalado_id` (FK `equipos`) y `folios.trabajo_especial_id`, y `trigger_revision` gana `pendiente_oc_cliente`. 7 alertas
  nuevas (`TE_SIN_RESPUESTA_CLIENTE`, `TE_ACEPTADO_SIN_PROGRAMAR`, `TE_PROGRAMADO_VENCIDO`, `TE_URGENCIA_SIN_COTIZACION_RETROACTIVA`,
  `OC_ACTIVO_SIN_TRAMITE`, `OC_ACTIVO_EN_TRAMITE_PROLONGADO`, `ACTIVO_INSTALADO_INCOMPLETO`) con evaluadores en
  `workers/evaluadores_te.py` (32 evaluadores en total). RLS por tenant+prestador con políticas por comando (solo SELECT/INSERT en las append-only).
- **`services/trabajos_especiales_service.py`**: `TRANSICIONES` literal de §6.10.6 (creado → enviado_cliente [prestador] · creado →
  programado solo urgencia · enviado_cliente → aceptado | rechazado [Admin empresa / Admin UN de la UN, comentario obligatorio al rechazar] ·
  rechazado → enviado_cliente (`version_enviada + 1`, admite nuevo monto/descripción) | cancelado · aceptado → programado [despachador,
  admin prestador: fecha + técnicos con `ejecutar_trabajos_especiales`, responsable = jefe de cuadrilla] · programado → en_ejecucion y
  en_ejecucion → cerrado [técnico responsable o sistema] · no final → cancelado [admin prestador, mesa, despachador; el cliente solo sus
  TE de urgencia antes de programar]). **`cambiar_estado_te(db, actor, te, nuevo, notas, request, **campos)`** es la única entrada: valida
  rol y campos, escribe `te_historial`, audita, notifica con `notificar()` (eventos `trabajo_especial.*`) y sincroniza el folio operativo.
  `crear()` (prestador u urgencia del cliente, resuelve el formulario `trabajo_especial` con P03), `desde_cotizacion()` (§7.7 M1
  autorizada → convertida; sustituye el 501 de `cotizaciones.convertir_en_trabajo_especial`), `requisitos_cierre()` (formulario del TE,
  evidencia fotográfica de cierre y firma del cliente → 409 `CIERRE_TE_INCOMPLETO`), `agregar_evidencia()`, `cotizacion_retroactiva()`,
  `seccion_minuta()` (§7.3 nuevos / en proceso / terminados con evidencia y etiqueta de urgencia), `reporte()` y `serializar()/detalle()`.
- **Relación TE ↔ folio operativo**: al pasar a `programado` se crea un folio `tipo_folio = especial` vinculado por
  `folios.trabajo_especial_id` (capturado por el sistema, confirmado, directo a Autorizado y Asignado al responsable; los demás técnicos van
  en el contexto del historial); la app del técnico (P05) lo atiende con el formulario del TE (`sync_service` y `AtencionTecnico` resuelven
  `trabajo_especial` para `especial`). Sincronización en ambos sentidos: TE `en_ejecucion` ↔ folio `en_ejecucion` (en_camino + llegada),
  `cerrado` ↔ `cerrado` y la cancelación de cualquiera cancela al otro (`_sincronizar_folio` y el suscriptor `_al_transicionar_folio`);
  el validador `_validar_cierre_te` bloquea el cierre del folio si al TE le faltan requisitos.
- **`services/oc_activos_service.py`** (§6.10.7): `detectar()` lee el campo con `clasifica_instalacion_activo` (`ActivoMapeo` en
  `schemas/formularios.py`: `valor_afirmativo` y mapeo de tipo de equipo, marca, modelo, serie, valor de reposición y nombre);
  `desde_respuesta()` se engancha en la captura (P04, formulario de captura) y en el envío del formulario de atención (P03). `marcar()` pone
  `es_instalacion_activo`, crea la autorización, historial, evento `activo.clasificado` y avisa a Admin UN/empresa. En la captura el folio
  queda `en_revision` con el trigger `pendiente_oc_cliente` (sin flujo multinivel ni clasificación). `cambiar_estatus()` (Admin empresa):
  pendiente → oc_en_tramite (provisional opcional) → oc_autorizada (definitivo + fecha obligatorios) → `listo_para_asignar` automático
  (resuelve el trigger y `transicionar(autorizado)` si no quedan otros triggers; si quedan, avisa al despachador) ·
  pendiente/en_tramite → oc_rechazada con `cancelar` (folio cancelado) o `reprogramar_periodo` (registro en Por presupuesto con el período
  destino + folio cancelado). `alta_equipo()` corre en el validador previo al cierre (`suscribir_validacion`, porque el folio cerrado es
  inmutable): `ACT-<folio>`, tipo por id o nombre, marca/modelo/serie/valor, `fecha_instalacion` = cierre, contrato vigente, y si falta el
  tipo → `inactivo` + `ACTIVO_INSTALADO_INCOMPLETO` + aviso al Admin empresa. `pendientes()` (Admin UN sus UNs, Admin empresa, prestador).
- **Endpoints**: `/api/trabajos-especiales` (listado con filtros tenant/UN/estado/urgencia/período/`por_validar`, `POST` crear,
  `/{id}`, `enviar`, `aceptar`, `rechazar`, `programar`, `iniciar`, `cerrar`, `cancelar`, `estado` (Kanban), `evidencias`,
  `cotizacion-retroactiva`, `reporte` + `.xlsx` + `.pdf`) y `/api/oc-activos` (`pendientes`, `/{folio_id}`, `/{folio_id}/estatus`).
  `POST /api/seguimiento/cotizaciones/{id}/convertir` devuelve la cotización convertida con el TE; el listado y detalle de cotizaciones
  traen `estado_trabajo_especial` y `trabajo_especial_numero`. El detalle del folio incluye `oc_activo` y `trabajo_especial`; el resumen,
  `es_instalacion_activo`, `equipo_instalado_id` y `trabajo_especial_id`.
- **Frontend**: módulos `trabajos_especiales` (`/trabajos-especiales`, `pages/trabajos_especiales/TrabajosEspeciales.tsx`: listado,
  Kanban del prestador, bandeja «Por validar» del cliente con aceptar/rechazar, creación ordinaria y de urgencia, detalle con línea de
  tiempo, versiones, respuestas del cliente, cotización y folio vinculados, programación con técnicos, iniciar/cerrar, cotización
  retroactiva y cancelación, reporte exportable) y `oc_activos` (`/oc-activos`, `pages/oc_activos/OcActivos.tsx`: pendientes, registro
  de estatus/OC, decisión ante rechazo, historial, equipo dado de alta). `FolioDetalle` y `Folios` muestran «Esperando OC del cliente» y el
  TE vinculado; la app del técnico etiqueta «Trabajo especial» / «Urgencia» y resuelve el formulario del TE; la minuta muestra la sección real.
- **Seed** (`scripts/seed_trabajos_especiales.py`): formulario «Trabajo especial (global)» asignado a `especial`, formulario de captura
  «instalación de activo», permiso TE para Tomás y Tania (overrides), 8 TE (TE-000001 creado … TE-000008 cancelado; TE-000002 con dos
  versiones y un rechazo; TE-000005 desde COT-00002; TE-000006 de urgencia del Admin UN en ejecución; TE-000007 cerrado con evidencia y
  firma) y 4 folios de activo (CD-000038 pendiente, CD-000039 en trámite, CD-000040 OC autorizada pero retenido por el trigger de
  contrato vencido, CD-000041 cerrado con el equipo `ACT-CD-000041` inactivo por ficha incompleta).
- **Para P09**: `trabajos_especiales.monto`, `cotizacion_retroactiva_id` y `folios.monto_estimado` del folio operativo son los ganchos de
  costo; `equipos` creados por `alta_equipo()` alimentan activos y depreciación (`valor_reposicion`, `fecha_instalacion`, `contrato_id`).
  **Para P10**: `te_historial` y `folio_activo_historial` dan tiempos por etapa; `TE_PROGRAMADO_VENCIDO` y `OC_ACTIVO_*` entran al tablero.

### Frontend
- `src/config/modulos.ts` define los 25 módulos de Fase 1, su prompt y los roles que los ven. Al construir un módulo:
  agregar `ruta`, la página en `App.tsx` (`PAGINAS`) y ajustar roles.
- `src/services/api.ts`: cliente con refresh single-flight y `ErrorAPI`. `useRecurso` para listados.
- Colores del prestador vía variables CSS `--color-primario` / `--color-acento` (`aplicarTema`).
- Dexie (`src/services/db.ts`) solo tiene `metadatos`; P05 agrega tablas offline con nuevas versiones del esquema.

## Decisiones pendientes de validación (regla 1)

1. **Vida del JWT:** P01 pide acceso de 15 min + refresh de 7 días; §6.9.5 dice 8 h (2 h admins). Se siguió P01.
2. **MFA obligatorio:** P01 incluye `direccion_prestador` además de los tres roles de §6.9.5. Se siguió P01.
3. **Grupos de UNs:** §6.8.5 define pertenencia N:N (`grupo_un_miembros`) y P01 pide `unidades_negocio.grupo_id`. Se hicieron
   ambos: `grupo_id` es el grupo principal y la tabla N:N la membresía completa.
4. **Permisos de técnico/despachador:** `permisos_tecnico` y `permisos_despachador` guardan el valor base por prestador; se
   crearon además las tablas de grupos y overrides de §6.8.3 (`grupos_tecnicos`, `grupo_tecnico_permisos`, `tecnico_grupo`,
   `tecnico_permisos_override`), sin endpoints hasta P02. `permisos_despachador` admite filas por despachador + cliente (§6.8.3b).
5. **Rangos de umbral de alertas:** el diseño no define mínimos/máximos; se eligieron rangos razonables en la migración.
   `TECNICO_SIN_SEÑAL` se registró como `TECNICO_SIN_SENAL` (sin acentos en identificadores).
6. **`audit_accesos_api`** particionada por mes (el diseño dice por día). Retención 90 días / 1 año pendiente: se hará con
   DROP de particiones (no viola el append-only).
7. **Refresh token en localStorage** (más simple); alternativa más segura: cookie httpOnly + SameSite. Revisar en P11.
8. **Visibilidad de módulos futuros por rol** en el hub: asignación preliminar derivada de §5; se confirma en cada prompt.
9. **Tema para usuarios de tenant:** se usan los colores del primer prestador vigente vinculado al tenant.
10. **Rol `sistema` en RLS** para Celery y scripts, equivalente a superadmin.
11. **Pendientes de §6.9.5 no cubiertos en P01:** vencimiento de contraseña a 90 días para admins (el campo
    `password_actualizado_at` ya existe), notificación al admin por bloqueo de IP (requiere canal de notificaciones, P07),
    geolocalización aproximada en auditoría de login, llaves de cifrado por tenant para Object Storage, protección contra
    repetición del mismo código TOTP dentro de su ventana de 30 s.
12. **Imagen de MinIO** en `latest` (la etiqueta fija elegida no existe en Docker Hub); fijar por digest en P11.
13. **Niveles de severidad: 5, no 3.** §6.3 muestra 3 niveles de ejemplo (Crítico/Urgente/Normal) pero §6.10.1 y §4.1 fijan
    5; se siguen los 5, con clave y orden fijos por prestador (solo nombre, color y tiempos son editables).
14. **`contratos.cobertura`** (`todas_las_un` | `equipos_especificos`, default `todas_las_un`) agregado para la regla de
    contrato activo; el diseño no lo definía.
15. **Tipos de falla solo sobre familias globales**: el prestador define síntomas por familia de plataforma; las familias
    propias de un tenant no admiten tipos de falla del prestador (si hiciera falta, se revisa en P04).
16. **`contrato_sla` conserva el ENUM `nivel_severidad`** además de `nivel_severidad_id`; P10 decide cuál manda.
17. **Importador**: los duplicados contra la base se omiten (no actualizan), salvo `severidades` y `matriz_severidad`, que
    actualizan por clave. Las contraseñas de técnicos importados viajan en el archivo y no se devuelven en la vista previa.
18. **Alerta `MATRIZ_SEVERIDAD_INCOMPLETA`**: umbral 0 (dispara con 1 combinación faltante), destinatario admin_empresa,
    sin repetir mientras haya una sin atender. Solo cuentan tipos de equipo con equipos activos del tenant.
20. **Formularios: `formulario_respuestas` admite `tenant_id` nulo** (respuesta independiente de un usuario del prestador)
    con `prestador_id` del autor; la RLS es «tenant visible o prestador propio». Las evidencias copian ambos dueños.
21. **`resolver`**: `tipo` es el tipo de formulario y `tipo_folio` (correctivo, preventivo…) acota las asignaciones; el
    prompt solo mencionaba `tipo`.
22. **Sellos `al_llegar_seccion` / `por_condicion`**: el servidor fija la hora en que recibe por primera vez un valor del
    cliente para ese campo (guardado parcial), no la hora que manda el cliente.
23. **Compresión máxima de fotos**: se estima la calidad JPEG con la tabla de cuantización (`compresion = 100 − calidad`);
    PNG/WebP no se evalúan. Pendiente validar el umbral default 70 % con fotos reales de los técnicos.
24. **Alerta `GEOLOCALIZACION_FUERA_DE_UN`** pertenece al tenant y al prestador a la vez (la ven despachador, admin
    prestador y el cliente); umbral = metros de exceso sobre el radio del campo (default 0).
25. **Plantillas base con catálogo personalizado**: la plantilla «Cierre de correctivo» referencia un id de catálogo
    ficticio; al clonarla el prestador debe elegir su catálogo «Causa raíz» (el seed ya lo hace en los formularios demo).
26. **Pendientes de Fase 2 detectados**: transcripción de audio real; validación cruzada GPS de fotos vs. formulario
    (§4.3) y mapa del despachador; anotación sobre archivos de imagen cargados (solo fotos por ahora); mesa de control
    no cambia asignaciones; el constructor no reordena secciones por arrastre (solo campos).
19. **Catálogos en lectura para técnico, despachador y mesa de control** (equipos, tipos de falla, familias) para preparar
    P04; el hub muestra el módulo también a admin_un, mesa de control y despachador.

27. **Técnico solo ve sus folios** (cierra la decisión 3 de P01 en ese sentido): asignados a él o capturados por él
    (`crear_folio_en_campo`); también en la RLS de `folios`.
28. **Sin reglas de aprobación (o ninguna aplicable) el folio pasa directo a `autorizado`**; `monto_estimado` nulo se
    evalúa como 0 (Nivel 1 por monto).
29. **Nivel 2 = `supervisor_operadores`** (el documento lo llama "Supervisor regional"); aprueba las UNs de su grupo o
    asignadas en `usuario_un`.
30. **`aprobacion_secuencial`** (política del tenant, default false): §6.8.7 dice que el flujo comienza en el nivel de
    entrada; con la política activa comienza en Nivel 1 y sube hasta el requerido (aprobación en cadena).
31. **Autorizar en revisión con reglas configuradas**: si el despachador/admin prestador resuelve la excepción y el tenant
    tiene reglas aplicables, el folio no pasa a `autorizado` sino que inicia el flujo multinivel (`revision.resuelta`).
32. **Monto estimado** lo fijan Mesa de control, Despachador y Admin prestador en `capturado`/`en_revision`; el documento
    no define quién lo captura.
33. **`folio_duplicado_ref_id` / justificación** solo se guardan cuando hay folio abierto; `respuesta_id` del formulario de
    captura es opcional.
34. **Habilidad requerida al asignar** = `familias_equipo.habilidad_clave` (nuevo campo; si es nulo se compara por nombre de
    familia). El seed mapea Refrigeración → refrigeracion, Climatización → hvac, Iluminación → iluminacion.
35. **`revision_obligatoria_garantia`** vive en `folio_politicas_tenant` y la puede fijar el Admin prestador (el documento
    dice "configurado por el prestador") además del Admin empresa.
36. **`equipos.criticidad`** manual (Fase 1); el cálculo automático de §6.9.3 llega en Fase 2.
37. **Alertas al despachador por `sin_contrato`/`fuera_horario`** se emiten como notificación (stub) y no como alerta del
    catálogo (no existe una clave de diseño para ellas); los triggers quedan en `revision_manual_triggers`.
38. **Comentarios en folios finales**: `folio_estados_historial.evento = comentario` con `estado_anterior = estado_nuevo`.
39. **`folios.tecnico_id` referencia `usuarios.id`** (no `tecnicos.id`), igual que los permisos de técnico; el vehículo se
    copia al historial al asignar porque los usuarios del tenant no leen `tecnicos` (RLS).
40. **`timestamp_dispositivo` como hora real** solo en `transicion`, `enviar_respuesta`, `crear_folio` (`capturado_at`),
    firma y encuesta; la auditoría conserva la hora del servidor. Si el servidor cambió después de esa hora se registra
    un conflicto `client_wins` pero la operación se aplica.
41. **Idempotencia por (usuario, id_cliente)** en `sincronizacion_mutaciones`; para evidencias además por `hash_sha256`
    dentro de la misma respuesta.
42. **Participantes iniciales**: el documento fija «despachador asignado»; como el despachador no existe al capturar,
    entra a operativo/interno con su primera acción (autorizar, asignar, cancelar…). Admin prestador entra a `interno`
    desde el inicio (todos los activos del prestador).
43. **Mensajes de texto en folio cerrado: rechazados** (solo evidencia posterior en imagen, §6.8.3c); el chat de un folio
    cancelado antes de asignar queda archivado y solo superadmin lo audita.
44. **Encuesta**: plazo `plazo_encuesta_horas` = 48 por defecto (configurable por tenant); con NPS ≤ 6 el comentario es
    obligatorio; se puede responder antes del cierre (tras la firma).
45. **Push**: suscripción por `(usuario, endpoint)`; sin claves VAPID el envío solo se registra. El técnico recibe push de
    asignación, autorización y cancelación; el operador de todo cambio de estado.
46. **ETA y ruta** se muestran como «Disponible en Fase 2» en las apps de campo; **biblioteca** y **refacciones** del
    paquete del técnico vienen vacíos hasta Fase 2 / P09.
47. **Caché de API en el service worker**: `NetworkFirst` 8 s para `GET /api/*`; las escrituras nunca se cachean. Las
    lecturas de folios/catálogos para las apps usan además IndexedDB (fuente offline principal).
48. **Política RLS de `folios`** corregida en 0005 (escritura por comando) para que la restricción de lectura del técnico
    aplique también a nivel de BD.
49. **Una sola tabla de calendario** (`preventivos_calendario`) para `calendarios_preventivos` (§6.9.1) y
    `preventivos_calendario` (§7.6): misma información con origen `manual|plan`. `plan_ejecuciones` conserva el histórico
    por plan y equipo.
50. **Preventivos de UN completa** (sin equipo) se programan y publican, pero **no generan folio** hasta asignarles un
    equipo: el folio exige `equipo_id`. La tarea nocturna los reporta como `omitidos`.
51. **Fecha próxima por tiempo fijo** = última ejecución (o fecha base) + intervalo, aunque quede en el pasado: un plan
    atrasado genera su folio en la siguiente corrida y la alerta `PREVENTIVO_VENCIDO_SIN_EJECUTAR` lo marca.
52. **El folio preventivo nace autorizado sin flujo de aprobación** («autorizado al configurar el plan»). La regla de
    aprobación `tipo_trabajo = preventivo` queda para preventivos capturados a mano.
53. **Reprogramación de preventivos ≠ rechazo «reprogramar» de §6.8.7**: aquí el folio no se cancela; se crea una fila
    nueva del calendario ligada a la original y el folio conserva número e historial.
54. **Cancelar un preventivo exige autorización formal** del Admin UN de la UN o del Admin empresa cuando lo pide el
    prestador (validador en el motor de estados); el Admin empresa puede cancelarlo directamente.
55. **Severidad del preventivo**: la del plan si la tiene; si no, el nivel más bajo del prestador (no hay tipo de falla
    para la matriz).
56. **En camino no se reasigna** (la tabla §6.8.6 no tiene `en_camino → reasignado`); solo `asignado` y
    `pendiente_refaccion`. En ejecución está prohibido por diseño.
57. **Reasignación forzada = `reasignado → asignado` en una sola operación** (el estado intermedio queda en el historial);
    la tabla literal se respeta usando al despachador como actor (o `sistema` si actúa el Admin prestador).
58. **Advertencia de refacción siempre presente** hasta P09 («Refacción no verificada»), por lo que toda reasignación
    pide `confirmar_advertencias`. P09 la sustituye por la verificación real del inventario del vehículo.
59. **Umbrales de las alertas nuevas**: vencido 0 días tras fecha + ventana del plan; autorización pendiente 24 h;
    calendario sin publicar desde el día 25 (una vez por mes y vínculo tenant-prestador).
60. **Publicar un mes vacío responde 409** (`MES_VACIO`); volver a publicar actualiza la misma publicación y vuelve a
    notificar.
61. **Origen de los hallazgos**: bandera `genera_hallazgo` por campo del formulario de atención (con condición opcional) y
    marcado de mensajes de chat por técnico/operador/Admin UN/Despachador; también captura manual. El documento no define el
    mecanismo.
62. **Minuta de UN sin actividad no se genera**; la global sí cuando hubo actividad en el tenant; `forzar` la genera vacía.
63. **Ventana de validación vencida → envío automático** marcado `enviada_sin_validacion` (el documento define la ventana, no
    el vencimiento).
64. **«PDF firmado» = SHA-256** guardado en `hash_pdf` y mostrado en el correo, hasta definir firma electrónica.
65. **Minuta sin hallazgos pendientes no vence** (`vence_respuesta_at` NULL); con hallazgos, vence tras `plazo_respuesta_horas`
    y aún admite respuestas tardías (cuentan en la calificación).
66. **Autorizar reparar sin cotización** crea un folio correctivo capturado por el sistema directo a Autorizado, sin flujo
    multinivel: el cliente ya decidió. Lo mismo para «reactivar como folio» y el trabajo coordinado variante A.
67. **Clasificación de no críticos**: el folio queda en `en_revision` con trigger `pendiente_clasificacion` (sin flujo) hasta
    que el Admin UN clasifique; las opciones distintas de «autorizado» cancelan el folio con razón y lo enlazan al módulo
    (como el rechazo de §6.8.7). Solo aplica a folios capturados después de configurar el tenant.
68. **Clasificación tardía**: descuento proporcional a las horas de retraso (`puntos_json.clasificacion_tarde_por_hora`, tope
    `clasificacion_tarde_max`) y bandera `excluir_sla_por_cliente` para P10.
69. **Alertas reutilizadas** del catálogo base (`COTIZACION_SIN_PREPARAR`, `COTIZACION_SIN_RESPUESTA`, `SEGUIMIENTO_SIN_UPDATE`,
    `REPROGRAMACION_FECHA_VENCIDA`, `FOLIO_SIN_CLASIFICAR`) en lugar de duplicarlas con los nombres del prompt.
70. **`aprobacion_decisiones` sigue siendo append-only** salvo por `modulo_destino_id`, que se puede llenar una sola vez.
71. **Reprogramación con fecha tentativa** (clasificación o respuesta de la minuta) nace en `fecha_asignada`; una fecha vencida
    deja `fecha_acordada` NULL y conserva el estado hasta que se registre la nueva.
72. **Fase 2 de notificaciones** (`whatsapp`, `sms`) se registra como `omitida` con motivo, para que la bitácora sea completa.
73. **Notificaciones en línea**: en pruebas y sin Celery se envían en la misma petición (`NOTIFICACIONES_ENVIO_INLINE`); en
    producción las envía Celery.
74. **WeasyPrint** se usa cuando sus librerías nativas están presentes (Linux/contenedor); en esta máquina Windows sin GTK se
    usa el generador PDF mínimo propio (texto y estructura, sin estilos).
75. **Historial del TE en tabla propia** (`te_historial`), no en `modulo_historial`: `modulo_destino` es un ENUM de los cuatro módulos
    de P07 y el TE tiene su propio ciclo.
76. **Folio operativo del TE**: al programar se crea un folio `especial` capturado por el sistema, directo a Autorizado y asignado al
    responsable sin validar la habilidad de familia (el permiso `ejecutar_trabajos_especiales` la sustituye); TE y folio se sincronizan
    en ambos sentidos y la cancelación de uno cancela al otro.
77. **Actor del folio al sincronizar**: si quien mueve el TE no puede ejecutar la transición del folio según §6.8.6 (p. ej. Mesa de
    control cancela un folio asignado), el folio se cancela con un actor del prestador que conserva el id real del usuario; la ejecución
    y el cierre sincronizados usan el actor `sistema`.
78. **Requisitos de cierre del TE**: formulario del TE enviado (vinculado como atención del folio operativo), evidencia fotográfica de
    cierre (`te_evidencias` tipo `cierre` o fotos «después/durante» del folio) y firma del cliente (del folio o del TE).
79. **Cotización retroactiva** disponible para cualquier TE sin cotización vinculada (no solo urgencias); nace `en_preparacion` con el
    monto y queda enlazada en ambas direcciones.
80. **El cliente cancela solo sus TE de urgencia** y solo antes de programarlos; después cancela el prestador con razón.
81. **El TE ordinario no salta de creado a programado**; el de urgencia sí, por el despachador o el Admin prestador, y queda registrado
    `sin_validacion_cliente` en el historial.
82. **Clasificación como instalación de activo** con la bandera `clasifica_instalacion_activo` en campos `si_no`/`radio` del formulario
    de captura o de atención. Desde la atención (el técnico lo identifica en la visita) el folio ya en ejecución continúa y la OC se sigue
    en paralelo; solo el folio capturado se retiene en revisión.
83. **El folio de activo espera la OC como trigger `pendiente_oc_cliente`**: no se evalúa el flujo multinivel ni la clasificación de no
    críticos; con la OC autorizada pasa directo a Autorizado si no quedan otros triggers y, si quedan (p. ej. sin contrato), sigue en
    revisión y se avisa al despachador.
84. **OC rechazada**: `cancelar` cancela el folio con razón; `reprogramar_periodo` crea el registro en Por presupuesto con el período
    destino y cancela el folio (queda enlazado por `derivaciones`).
85. **Alta automática del equipo**: código `ACT-<folio>`, nombre tipo + marca + modelo, contrato vigente del equipo del folio, tipo de
    equipo por id o por nombre; si falta el tipo se usa el del equipo del folio y el activo queda `inactivo` con alerta. Se ejecuta en el
    validador previo al cierre porque el folio cerrado es inmutable.
86. **Roles del TE**: crean Admin prestador, Mesa de control y Despachador; programan Despachador y Admin prestador; cancelan los tres del
    prestador; consultan además supervisores, dirección y los técnicos asignados. En la OC registra solo el Admin empresa; consultan Admin
    UN (sus UNs) y los roles de gestión del prestador.
87. **`TE_URGENCIA_SIN_COTIZACION_RETROACTIVA` es informativa**: umbral en días por tenant y se silencia con la supresión de alertas de P01.

## Notas de entorno (esta máquina)

- Python 3.12 instalado con `py install 3.12`; el venv vive en `backend/.venv`.
- asyncpg fijado en 0.31.0: la 0.32 la bloquea el Control de aplicaciones de Windows.
- Node 25 trae un `localStorage` experimental que tapa el de jsdom; `frontend/tests/setup.ts` instala uno en memoria.
- 2026-10-19: Docker Desktop no arrancaba por sockets huérfanos; se renombraron `%LOCALAPPDATA%\Docker\run` y
  `%LOCALAPPDATA%\docker-secrets-engine` (copias `*.viejo-20261019`, se pueden borrar).
- 2026-10-27: mismo problema (`dockerInference`); copias `*.huerfano-20261027-*`, se pueden borrar.
- 2026-10-29: con pytest corriendo, `tsc` (typescript-go) se queda sin memoria en esta máquina (7 GB): cerrar los servidores de
  desarrollo viejos y correr `tsc`/vitest cuando pytest termina.
- Zona horaria del horario de servicio: `zoneinfo` + paquete `tzdata` (ya en el venv) porque Windows no trae la base IANA.
- `pywebpush` instalado en el venv (P05); `fake-indexeddb` como devDependency del frontend para probar Dexie en vitest.
- Las pruebas de vitest y pytest se corren por separado: en paralelo con el build, vitest falla por tiempos de espera.
- P07: `aiosmtplib`, `aiosmtpd` y `weasyprint` en el venv. WeasyPrint no carga en esta máquina (faltan GTK/Pango: «cannot load
  library libgobject-2.0-0»); `services/pdf.py` cae al generador mínimo. Para PDF con estilos instalar el runtime GTK3 o
  ejecutar en Linux. vitest corre los archivos en serie (`fileParallelism: false`, 30 s por prueba).
