# P08 — Trabajos especiales, conversión de cotizaciones y seguimiento de OC de activos (Fase 1, prompt 8 de 11)

## Contexto

P07 está cerrado (commit `73e273b`; 259 pytest y 62 vitest en verde). Lee antes de empezar `CONTEXTO.md` (secciones "Folios (P04)", "Campo, offline y chat (P05)", "Minuta y seguimiento (P07)" — en particular el gancho `cotizaciones.convertir_en_trabajo_especial()` que responde 501 `DISPONIBLE_EN_P08`, la columna `trabajo_especial_id`, la sección "trabajos especiales" de la minuta con nota P08 y la columna "Estado del trabajo especial" del listado de cotizaciones — y todas las decisiones pendientes), `BITACORA.md`, y en `ACMA_Documento_Diseno_v2.5.docx`: §6.10.6 completo (ciclo de vida, formulario configurable, modelo de datos, TE de urgencia), §6.10.7 completo (flujo de OC de activos, estatus y tabla), §6.10.2 (capacidades de Mesa de control), §7.3 (sección Trabajos especiales de la minuta), §7.7 Módulo 1 (estados Autorizada y Convertida) y §6.8.3 (permiso `ejecutar_trabajos_especiales` del técnico).

Este prompt cierra el capítulo de seguimiento: los trabajos especiales con su validación por botón del cliente, la conversión automática de cotizaciones y el seguimiento del trámite de OC en el ERP del cliente para folios de instalación de activos. No construye inventario ni costos (P09): el alta automática del equipo al cerrar un folio de activo se hace aquí contra el catálogo `equipos` de P02.

## Objetivo

Que el prestador cree trabajos especiales (desde una cotización autorizada o de forma independiente), que el cliente los acepte o rechace con un botón, que se programen, ejecuten con formulario propio y cierren con evidencia y firma, apareciendo en la minuta; que Admin empresa y Admin UN puedan crear TE de urgencia; y que los folios de instalación de activo esperen la OC del cliente con los cinco estatus de §6.10.7 antes de asignarse, dando de alta el equipo al cerrar.

## Entregables

### 1. Migración `0008_trabajos_especiales_oc.py`

Con los helpers de `core/sql_migracion.py`, RLS forzada en toda tabla con `tenant_id`/`prestador_id`.

| Tabla | Campos clave |
|---|---|
| `trabajos_especiales` (§6.10.6 y §7.9) | numero (correlativo por prestador, p. ej. `TE-000045`), tenant_id, prestador_id, un_id, cotizacion_id (nullable; completar aquí la FK `cotizaciones.trabajo_especial_id → trabajos_especiales.id`), descripcion, estado ENUM(`creado` / `enviado_cliente` / `aceptado` / `rechazado` / `programado` / `en_ejecucion` / `cerrado` / `cancelado`), urgencia bool default false, creado_por_id, creado_por_rol, formulario_id (formulario de tipo `trabajo_especial` de P03), respuesta_formulario_id (nullable), monto (nullable; heredado de la cotización; vacío en urgencia hasta cotización retroactiva), cotizacion_retroactiva_id (nullable), fecha_programada, fecha_inicio, fecha_cierre, tecnico_ids_json, tecnico_responsable_id (jefe de cuadrilla), razon_cancelacion, version_enviada (entero: se incrementa en cada reenvío tras rechazo) |
| `te_respuesta_cliente` | trabajo_especial_id, version_enviada, respondido_por, decision ENUM(`aceptado` / `rechazado`), comentario (obligatorio en rechazo), canal, timestamp — **append-only** |
| `te_evidencias` | trabajo_especial_id, tipo ENUM(`avance` / `cierre` / `firma` / `documento`), evidencia_id (FK `formulario_evidencias`, nullable), archivo_key, geolat, geolng, timestamp, subido_por |
| `te_historial` | trabajo_especial_id, estado_anterior, estado_nuevo, actor_id, actor_rol, timestamp, notas — **append-only** (o reutilizar `modulo_historial` de P07 con `modulo = trabajos_especiales`; elegir una y anotarlo) |
| `folio_activo_autorizacion` (§6.10.7) | folio_id, estatus_multinivel ENUM(`pendiente_iniciar_tramite` / `oc_en_tramite` / `oc_autorizada` / `listo_para_asignar` / `oc_rechazada`), numero_oc_provisional, numero_oc_definitivo, fecha_autorizacion_erp, registrado_por, notas, decision_rechazo ENUM(`cancelar` / `reprogramar_periodo`) nullable, periodo_presupuestal_destino nullable |
| `folio_activo_historial` | folio_id, estatus_anterior, estatus_nuevo, actor_id, timestamp, notas — **append-only** |

Cambios en tablas existentes: `folios.es_instalacion_activo` bool default false y `folios.equipo_instalado_id` (nullable, FK `equipos`); `folios.trabajo_especial_id` (nullable) para el folio operativo que un TE genera al programarse (ver sección 2); en el esquema de formularios de P03, bandera `clasifica_instalacion_activo` en un campo `si_no` o `radio` del formulario de captura para que el operador o el técnico clasifiquen el folio como instalación de activo (§6.10.7 "se clasifica en el formulario"), con mapeo opcional de campos a `equipos` (marca, modelo, serie, tipo de equipo) para el alta automática.

### 2. Trabajos especiales (`services/trabajos_especiales_service.py`)

- Tabla de transiciones literal de §6.10.6 con actores: `creado` → `enviado_cliente` (creador); `enviado_cliente` → `aceptado` / `rechazado` (Admin empresa o Admin UN de la UN, con comentario obligatorio al rechazar); `rechazado` → `enviado_cliente` (modificar y reenviar, `version_enviada + 1`) o `cancelado`; `aceptado` → `programado` (Despachador asigna fecha y técnicos; el cliente recibe confirmación de la fecha); `programado` → `en_ejecucion` (técnico responsable); `en_ejecucion` → `cerrado` (técnico, con formulario del TE enviado, evidencia fotográfica de cierre y firma del cliente: operador o Admin UN); cualquier estado no final → `cancelado` con razón documentada (Admin prestador, Mesa de control, Despachador; Admin empresa y Admin UN solo en sus TE de urgencia antes de `programado`). Función única `cambiar_estado_te()` con historial, auditoría, `notificar()` de P07 y eventos de chat.
- Creación: Admin prestador (sin restricciones), Mesa de control y Despachador (§6.10.6); desde cotización autorizada hereda tenant, UN, equipo, descripción, monto y el contexto del hallazgo original, y ejecuta la transición `convertida` de la cotización (implementar aquí `convertir_en_trabajo_especial()` reemplazando el 501); de forma independiente con formulario resuelto por P03 (`tipo = trabajo_especial`).
- TE de urgencia (§6.10.6): creado por Admin empresa o Admin UN con `urgencia = true`, sin monto, sin límite ni escalación; el prestador puede llevarlo de `creado` directamente a `programado` sin validación del cliente; cotización retroactiva opcional desde el módulo de Cotizaciones de P07 (`POST /api/trabajos-especiales/{id}/cotizacion-retroactiva` crea la cotización vinculada en ambas direcciones) que no bloquea el cierre; bandera visible en listado, reportes y minuta.
- Ejecución en campo: al pasar a `programado` el TE se vuelve operable en la app del técnico de P05: crear un folio con `tipo_folio = especial` vinculado (`folios.trabajo_especial_id`) para reutilizar la asignación, el ciclo de estados, el formulario de atención del TE, las evidencias, la firma y el chat sin duplicar lógica; el TE y su folio se sincronizan (`en_ejecucion` ↔ `en_ejecucion`, `cerrado` ↔ `cerrado`, cancelación en cualquiera cancela al otro). Anotar esta decisión. El técnico requiere el permiso `ejecutar_trabajos_especiales` (P02); si el TE tiene varios técnicos, el responsable es quien ejecuta las transiciones y los demás aparecen en el folio.
- Validación del cliente por botón (§6.10.6): `POST /api/trabajos-especiales/{id}/aceptar` y `.../rechazar` con `canal` (`app` / `email` / `push`); notificación al cliente al enviar con enlace directo; al aceptar, notificación a quien lo creó y al Despachador.
- Minuta (§7.3): completar la sección "Trabajos especiales" de P07 con nuevos solicitados en el día, en proceso y terminados en el día con evidencia fotográfica de cierre, y la etiqueta de urgencia.
- Cotizaciones (§7.7 y §7.8): la alerta `COTIZACION_AUTORIZADA_SIN_CONVERTIR` sigue vigente; la columna "Estado del trabajo especial" del listado muestra ahora el estado del TE vinculado.
- Alertas nuevas: `TE_SIN_RESPUESTA_CLIENTE` (días configurables), `TE_ACEPTADO_SIN_PROGRAMAR`, `TE_PROGRAMADO_VENCIDO` (fecha programada pasada sin iniciar), `TE_URGENCIA_SIN_COTIZACION_RETROACTIVA` (informativa, opcional por tenant).
- Reporte: `GET /api/trabajos-especiales/reporte?desde=&hasta=&tenant_id=` con conteo por estado, tiempo promedio por etapa, porcentaje de urgencias y monto total; exportable a PDF y Excel con los generadores de P07.

### 3. Seguimiento de OC de activos (`services/oc_activos_service.py`)

- Al capturar un folio (P04) o al enviarse un formulario de atención (P03) con la bandera `clasifica_instalacion_activo` afirmativa, marcar `folios.es_instalacion_activo = true`, crear `folio_activo_autorizacion` en `pendiente_iniciar_tramite` y mantener el folio en `en_revision` con trigger `pendiente_oc_cliente` (nuevo valor del ENUM de `revision_manual_triggers`) hasta que la OC esté autorizada; el flujo multinivel de §6.8.7 no se evalúa mientras el folio espera OC (anotar la decisión).
- Transiciones literales de §6.10.7, todas por Admin empresa salvo la automática: `pendiente_iniciar_tramite` → `oc_en_tramite` (número provisional opcional) → `oc_autorizada` (número definitivo y fecha obligatorios) → `listo_para_asignar` (sistema: `transicionar(autorizado)` del folio) ; `oc_en_tramite` / `pendiente_iniciar_tramite` → `oc_rechazada` con `decision_rechazo`: `cancelar` (folio a `cancelado` con razón) o `reprogramar_periodo` (registro en Por presupuesto de P07 con el período destino). ACMA no genera la OC en el ERP del cliente.
- Vista "folios de activos pendientes de autorización" para Admin UN y Admin empresa: `GET /api/oc-activos/pendientes`.
- Alta automática del equipo al cerrar el folio (§6.10.7): al llegar a `cerrado` un folio con `es_instalacion_activo`, crear el registro en `equipos` (P02) con los datos mapeados del formulario (tipo de equipo, marca, modelo, serie, fecha de instalación = fecha de cierre, UN del folio, `contrato_id` del contrato vigente, `valor_reposicion` si se capturó) y guardar `folios.equipo_instalado_id`; si falta el tipo de equipo, crear el equipo en estado `inactivo` con alerta `ACTIVO_INSTALADO_INCOMPLETO` para que Admin empresa complete la ficha.
- Alertas nuevas: `OC_ACTIVO_SIN_TRAMITE` (días configurables sin iniciar), `OC_ACTIVO_EN_TRAMITE_PROLONGADO`.

### 4. Frontend

- Módulo `trabajos_especiales` (`src/config/modulos.ts`, P08): `pages/trabajos_especiales/TrabajosEspeciales.tsx` con listado filtrable (tenant, UN, estado, urgencia, período), Kanban por estado para Admin prestador, Mesa de control y Despachador, y detalle con línea de tiempo, versiones enviadas y respuestas del cliente, cotización vinculada, folio operativo vinculado, evidencias y acciones por rol y estado; creación desde cotización autorizada (botón "Convertir en Trabajo Especial" en el detalle de cotización de P07) o independiente con el formulario resuelto; programación con fecha y técnicos; cancelación con razón.
- Portal del cliente: en el mismo módulo, para Admin empresa y Admin UN, bandeja "Trabajos especiales por validar" con el botón de aceptación y el de rechazo con comentario, confirmación de fecha programada y creación de TE de urgencia con formulario reducido y aviso de que no lleva monto.
- App del técnico (P05): los folios de tipo `especial` aparecen con etiqueta "Trabajo especial" (y "Urgencia" cuando aplica), con el formulario del TE y los puntos de verificación al cierre.
- Módulo `oc_activos` (agregarlo a `modulos.ts`, grupo Seguimiento, prompt P08): `pages/oc_activos/OcActivos.tsx` con la vista de pendientes, el registro de número de OC y estatus por folio, el historial del trámite y las dos decisiones ante rechazo; indicador "Esperando OC del cliente" en `FolioDetalle.tsx` y en el listado de folios de P04.
- Minuta (P07): sección de trabajos especiales con contenido real y etiqueta de urgencia.

### 5. Seed y pruebas

- Seed: formulario publicado de tipo `trabajo_especial` para el prestador demo; 7 trabajos especiales (uno por estado no final más un cerrado y un cancelado), de los cuales uno proviene de la cotización autorizada del seed de P07, uno es de urgencia creado por el Admin UN y uno tiene dos versiones enviadas con un rechazo; 3 folios de instalación de activo en `pendiente_iniciar_tramite`, `oc_en_tramite` y `oc_autorizada`, y uno cerrado con equipo dado de alta.
- Backend (`tests/test_trabajos_especiales.py`, `tests/test_te_urgencia.py`, `tests/test_oc_activos.py`): cada transición por rol y las no permitidas; rechazo con comentario obligatorio y reenvío con versión; conversión desde cotización con herencia de datos y estado `convertida`; folio operativo sincronizado en ambas direcciones; cierre bloqueado sin formulario, evidencia o firma; permiso `ejecutar_trabajos_especiales`; urgencia: creación por Admin UN, salto a `programado`, cotización retroactiva opcional, bandera en minuta; alertas de TE; OC: cada estatus y su actor, folio retenido en revisión hasta `oc_autorizada`, `listo_para_asignar` automático, rechazo con cancelación y con reprogramación a período, alta automática del equipo con datos mapeados y con datos incompletos; minuta con la sección de TE; columna de estado del TE en cotizaciones; aislamiento entre tenants y prestadores; RLS forzada en todas las tablas nuevas.
- Frontend: bandeja del cliente con aceptar / rechazar, conversión desde cotización, registro de OC, Kanban de TE.
- `pytest`, `vitest`, `tsc --noEmit` y `npm run build` en verde.

## Reglas (vigentes)

1. Seguir el Documento de Diseño v2.5; lo no definido se anota en `CONTEXTO.md` como decisión pendiente de validación.
2. Multitenancy validado en servicio además de RLS.
3. Sin proveedores externos de pago.
4. Identificadores en español sin acentos.
5. Cerrar con `CONTEXTO.md` (avance P08 ✅; sección "Trabajos especiales y OC (P08)" con `cambiar_estado_te()`, la relación TE ↔ folio operativo, el alta automática de equipos y los ganchos de costo para P09) y `BITACORA.md` actualizados.
6. No cambiar el stack.

## Al terminar

Resumen en español con: tablas de la migración 0008, endpoints, tabla de transiciones del TE, alertas nuevas, decisiones pendientes nuevas y conteo de pruebas.
