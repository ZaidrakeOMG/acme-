# CONTEXTO — Estado del proyecto ACMA (desarrollo nuevo)

> Se actualiza al cierre de cada prompt. Última actualización: **2026-10-27 · P04 Folios**.

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
| P05 | Apps PWA operador/técnico, offline y chat | Pendiente |
| P06 | Preventivos y reasignación forzada | Pendiente |
| P07 | Minuta y seguimiento | Pendiente |
| P08 | Trabajos especiales y OC | Pendiente |
| P09 | Inventario, caja chica manual, presupuestos y activos | Pendiente |
| P10 | Contratos/SLA (contador), alertas por módulo y BI | Pendiente |
| P11 | Endurecimiento y despliegue | Pendiente |

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

## Notas de entorno (esta máquina)

- Python 3.12 instalado con `py install 3.12`; el venv vive en `backend/.venv`.
- asyncpg fijado en 0.31.0: la 0.32 la bloquea el Control de aplicaciones de Windows.
- Node 25 trae un `localStorage` experimental que tapa el de jsdom; `frontend/tests/setup.ts` instala uno en memoria.
- 2026-10-19: Docker Desktop no arrancaba por sockets huérfanos; se renombraron `%LOCALAPPDATA%\Docker\run` y
  `%LOCALAPPDATA%\docker-secrets-engine` (copias `*.viejo-20261019`, se pueden borrar).
- 2026-10-27: mismo problema (`dockerInference`); copias `*.huerfano-20261027-*`, se pueden borrar.
- Zona horaria del horario de servicio: `zoneinfo` + paquete `tzdata` (ya en el venv) porque Windows no trae la base IANA.
