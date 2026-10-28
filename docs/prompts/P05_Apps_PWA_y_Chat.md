# P05 — Apps PWA del operador y del técnico, modo offline y chat (Fase 1, prompt 5 de 11)

## Contexto

P04 está cerrado (commit `9decb77`; 185 pytest y 39 vitest en verde). Lee antes de empezar `CONTEXTO.md` (secciones "Arquitectura vigente", "Motor de formularios (P03)", "Folios (P04)" con `transicionar()`, los requisitos de cierre y los eventos que P05 debe consumir, y las decisiones pendientes 1–39), `BITACORA.md`, y en `ACMA_Documento_Diseno_v2.5.docx`: §5.1 (Operador) y §5.2 (Técnico), §6.2 completo (capa 3 IndexedDB, resolución de conflictos y principio de diseño), §6.8.1 completo (chat: canales, permisos, modelo de datos, inmutabilidad, comportamiento offline), §6.8.6 (estructura del archivo del folio: datos de ejecución y de cierre) y §4.3 (campos `fotografia`, `firma`, `geolocalizacion`, `encuesta_satisfaccion`, `sello_fecha_hora`).

Este prompt construye las dos experiencias de campo sobre el motor de estados de P04 y el renderizador de P03. No construye rutas ni ETA (Fase 2), ni reasignación forzada (P06), ni notificaciones por correo o WhatsApp (P07): donde el documento las menciona, se deja el evento emitido y la interfaz preparada.

## Objetivo

Que un operador capture folios y firme el cierre desde su celular, que un técnico atienda su lista de folios con formularios, fotos y refacciones aunque no tenga señal, que ninguna captura en campo se pierda por conectividad, y que técnico, operador, despachador y administradores conversen en los tres canales del chat archivado del folio.

## Entregables

### 1. Migración `0005_chat_offline.py`

Con los helpers de `core/sql_migracion.py`, RLS forzada en toda tabla con `tenant_id`/`prestador_id`.

**Chat (§6.8.1, las 5 tablas):**

| Tabla | Campos clave |
|---|---|
| `chats` | folio_id, tenant_id, prestador_id, canal ENUM(`campo` / `operativo` / `interno`), estado ENUM(`activo` / `archivado`), created_at; UNIQUE(folio_id, canal) |
| `chat_participantes` | chat_id, usuario_id, rol, agregado_por, fecha_ingreso, activo |
| `chat_mensajes` | chat_id, usuario_id (nullable en mensajes de sistema), contenido_texto, tipo ENUM(`texto` / `imagen` / `audio` / `sistema`), timestamp_servidor, timestamp_dispositivo, leido_por_json, id_cliente (UUID generado en el dispositivo, UNIQUE por chat, para idempotencia de la cola offline) |
| `chat_archivos` | mensaje_id, archivo_key, tipo_mime, tamano_bytes, thumbnail_key |
| `chat_eventos_sistema` | chat_id, tipo_evento, datos_json, timestamp |

Reglas: los mensajes de un folio `cerrado` son inmutables (trigger que rechaza UPDATE salvo `leido_por_json`, y DELETE); el borrado lógico (`estado = archivado` y mensajes ocultos) solo aplica a chats de folios cancelados antes de `asignado`. La política RLS de `chat_mensajes` debe limitar la lectura a participantes activos del chat, además del tenant/prestador.

**Sincronización (§6.2):**

| Tabla | Campos clave |
|---|---|
| `sincronizacion_dispositivos` | usuario_id, dispositivo_id, ultimo_sync_at, version_app, plataforma |
| `sincronizacion_conflictos` | dispositivo_id, entidad, entidad_id, regla_aplicada ENUM(`server_wins` / `client_wins` / `merge_alerta`), datos_cliente_json, datos_servidor_json, resuelto_at |

`folios`, `folio_evidencias` y `formulario_respuestas` ya llevan `version_hash` y `updated_at`; verificar que `unidades_negocio`, `equipos`, `tipos_falla`, `niveles_severidad`, `formulario_versiones` y `usuario_un` también, y agregarlos a `TABLAS_VERSIONADAS` si falta alguno (§6.2 capa 1: los catálogos que se cachean deben poder sincronizarse por `updated_at`).

### 2. Backend — sincronización (`routers/sync.py`, `services/sync_service.py`)

- `GET /api/sync/catalogos?desde=<timestamp>&dispositivo_id=`: devuelve solo registros con `updated_at > desde` de los catálogos que cada app cachea según §6.2 capa 3: para el operador, UNs asignadas, equipos de esas UNs (con bandera de contrato activo), tipos de falla por familia, niveles de severidad y formularios de captura publicados aplicables; para el técnico, folios asignados con su formulario de atención resuelto (P03 `resolver`), formularios de preventivo, catálogos de refacciones (vacío hasta P09) y, cuando exista, biblioteca (Fase 2). Incluye bajas lógicas (`activo = false`) para que el dispositivo las retire.
- `POST /api/sync/mutaciones`: recibe un lote ordenado de operaciones capturadas offline, cada una con `id_cliente` (UUID), `tipo` (`crear_folio`, `transicion`, `guardar_respuesta`, `enviar_respuesta`, `subir_evidencia`, `agregar_refaccion`, `mensaje_chat`), `timestamp_dispositivo` y payload. El servidor las aplica en orden, de forma idempotente por `id_cliente`, con las reglas literales de §6.2: catálogos → server-wins; capturas en campo (folio, formulario, fotos, firma, mensajes) → client-wins conservando `timestamp_dispositivo` como hora real del evento (p. ej. hora real de cierre); movimientos de inventario → merge con alerta (dejar el gancho; P09 implementa el stock). Cada conflicto se registra en `sincronizacion_conflictos`. La respuesta indica por operación: aplicada, duplicada (ya existía), rechazada (con código y motivo) — una rechazada no detiene a las siguientes.
- Las transiciones aplicadas desde la cola pasan por `transicionar()` con el `timestamp_dispositivo` en `datos_contexto_json` y en `fecha_inicio_atencion` / `fecha_cierre` cuando corresponda (§6.2: "queda registrado con la hora real de cierre").
- Evidencias offline: subida en dos pasos, `POST /api/sync/evidencias/iniciar` (metadatos + hash) y subida del binario con reintento; una evidencia con el mismo `hash_sha256` y `id_cliente` no se duplica.

### 3. Backend — chat (`routers/chat.py`, `services/chat_service.py`, `services/ws_manager.py`)

- Creación automática de los tres chats al crear el folio (gancho en P04: evento `folio.creado`) con participantes fijos de §6.8.1: canal `campo` con el operador que capturó y, al asignarse, el técnico; canal `operativo` con el despachador que autoriza/asigna y el Admin UN de la UN; canal `interno` con Admin prestador y Despachador. Participantes adicionales y quién puede agregarlos, literal de la tabla de §6.8.1.
- `GET /api/folios/{id}/chats`, `GET /api/chats/{id}/mensajes?desde=`, `POST /api/chats/{id}/mensajes` (texto o con archivo; `id_cliente` obligatorio; el servidor fija `timestamp_servidor` y conserva `timestamp_dispositivo`), `POST .../leido`, `POST /api/chats/{id}/participantes` y `DELETE`.
- WebSocket `/ws/chats/{chat_id}` autenticado con el JWT, un canal por chat; `ws_manager` publica por Redis pub/sub para que funcione con más de un proceso de API. Fallback SSE `GET /api/chats/{id}/stream` para recepción cuando el WebSocket no se sostiene; el envío siempre es HTTP POST (§6.8.1).
- Eventos de sistema en el chat (§6.8.1 `chat_eventos_sistema`): consumir los eventos del historial de estados de P04 y escribir en el canal correspondiente: folio asignado (campo y operativo), técnico en camino, llegada confirmada, pendiente de refacción, cerrado, cancelado, reasignado (P06 lo emitirá).
- El chat del folio es el único canal abierto para evidencia posterior al cierre (§6.8.3c): permitir `tipo = imagen` en folios cerrados con el mensaje marcado como `evidencia_posterior` en `datos_json`.

### 4. Backend — cierre del folio

- `POST /api/folios/{id}/firma`: evidencia de tipo `firma` con imagen del trazo, geolocalización y timestamp del dispositivo; solo el operador de la UN (o Admin UN) puede firmar; registra en `folio_evidencias`.
- `POST /api/folios/{id}/encuesta`: usa el formulario de tipo `encuesta` resuelto por P03 (sembrar uno con un campo `encuesta_satisfaccion` NPS 0–10 y un texto obligatorio si la calificación es baja); guarda en `folio_encuesta` con `nps_score`.
- Secuencia literal de §6.8.6 y §6.9.1: técnico envía formulario de atención → operador firma → sistema genera la encuesta → `cerrar` transiciona a `cerrado` (la encuesta puede responderse después del cierre dentro de un plazo configurable, decisión pendiente: proponer 48 h).

### 5. Frontend — PWA offline (§6.2 capa 3)

- Ampliar `src/services/db.ts` (Dexie) con una versión nueva del esquema: `catalogos_cache` (por entidad, con `updated_at`), `folios_cache`, `formularios_cache`, `respuestas_borrador`, `evidencias_pendientes` (blob + metadatos), `mutaciones_pendientes` (cola FIFO con `id_cliente`, intentos, último error), `chat_mensajes_cache`, `chat_pendientes`.
- `src/services/syncEngine.ts`: cola con reintento exponencial (1 s, 4 s, 16 s, 64 s, 256 s, máximo 5 intentos y después "requiere atención" visible al usuario), envío en orden, idempotencia por `id_cliente`, refresco de catálogos al volver en línea y registro local de conflictos devueltos por el servidor. Interceptar `guardarRespuesta()` de P03 y las llamadas de transición, evidencias, refacciones y chat para que, sin red, escriban en la cola.
- Hook `useConexion` e `IndicadorConectividad` global (en línea / sin conexión / sincronizando N pendientes / N con error), y pantalla "Pendientes de sincronizar" con reintento manual.
- Service Worker: precache del shell y de los módulos de campo; `NetworkFirst` para la API con respaldo a caché solo en lecturas; descarga en segundo plano del paquete de catálogos al iniciar sesión.
- Regla de §6.2: "ningún dato crítico de operación puede perderse por un problema de conectividad". Probar con throttling de red y corte en mitad de una subida.

### 6. Frontend — app del operador (`pages/campo/operador/`)

Pensada para celular, en el mismo bundle PWA, con navegación simplificada para el rol `operador` (y disponible para Admin UN):

- Inicio: folios abiertos de su UN asignada (de cualquier operador de esa UN, §5.1), con estado, técnico asignado y el espacio para ETA (vacío hasta Fase 2); sin acceso a otras UNs.
- Captura: reutilizar `CapturaFolio.tsx` de P04 adaptada a pantalla táctil, con guía por preguntas e imágenes (§2.3), cámara directa, y funcionando offline con catálogos cacheados; la confirmación de UN literal de §6.8.6 se mantiene.
- Detalle del folio con línea de tiempo y chat `campo`.
- Cierre: pantalla de firma (lienzo a pantalla completa, componente `firma` de P03) seguida de la encuesta.
- Notificaciones push PWA de cambio de estado: registrar suscripción (`PushManager`) y guardarla en `usuarios` o tabla nueva `suscripciones_push`; el envío real por `web-push` desde el backend es gratuito y entra aquí para los eventos de estado del folio; el resto de canales (correo, WhatsApp) es P07.

### 7. Frontend — app del técnico (`pages/campo/tecnico/`)

- "Mis folios": asignados para hoy y próximos, con estado y acciones del ciclo de vida permitidas al técnico (en camino, confirmar llegada, pendiente de refacción, reanudar, cerrar) usando la tabla de transiciones de P04.
- Atención: formulario de atención resuelto por P03 con fotos antes/durante/después (control de calidad y GPS de P03), captura de refacciones consumidas con origen (almacén / OC / caja chica manual) y costo si tiene el permiso `ver_costo_refacciones`, sello de llegada, y entrega del dispositivo al operador para la firma.
- Crear folio en campo solo si `crear_folio_en_campo` está habilitado (P02 permisos efectivos).
- Chat `campo` con el operador e indicador de mensajes pendientes de envío con doble timestamp (escritura / entrega) según §6.8.1.
- Todo operable offline: lista, formularios, fotos y chat se encolan.

### 8. Frontend — chat para los demás roles

Componente `components/chat/ChatFolio.tsx` con pestañas por canal visibles según permisos, mensajes en tiempo real por WebSocket con fallback SSE, adjuntos, eventos de sistema diferenciados, marcado de leído y gestión de participantes; integrado en `FolioDetalle.tsx` de P04 (sección de chat que estaba vacía).

### 9. Seed y pruebas

- Seed: suscripción push de prueba, chats y mensajes para los 15 folios demo (incluido un folio cerrado con mensajes inmutables), un formulario de encuesta publicado, y un escenario de cola offline en los fixtures de frontend.
- Backend (`tests/test_sync.py`, `tests/test_chat.py`, `tests/test_cierre_folio.py`): `sync/catalogos` incremental con bajas; lote de mutaciones con operaciones aplicadas, duplicadas y rechazadas; client-wins conservando hora real de cierre; server-wins en catálogo; registro de conflictos; idempotencia por `id_cliente` y por hash de evidencia; creación automática de los tres chats y participantes fijos; permisos de agregar participantes por canal; lectura limitada a participantes (RLS); inmutabilidad de mensajes en folio cerrado y evidencia posterior permitida; eventos de sistema por transición; WebSocket con dos clientes y SSE; firma solo por operador/Admin UN; encuesta con NPS; cierre bloqueado sin formulario o sin firma; aislamiento entre tenants.
- Frontend (vitest con `fake-indexeddb`): cola FIFO con reintentos y reanudación tras recarga; captura de folio sin red y envío al reconectar; formulario de atención guardado parcial offline; mensaje de chat encolado con doble timestamp; indicador de conectividad; app del operador sin acceso a otras UNs.
- `pytest`, `vitest`, `tsc --noEmit` y `npm run build` en verde.

## Reglas (vigentes)

1. Seguir el Documento de Diseño v2.5; lo no definido se anota en `CONTEXTO.md` como decisión pendiente de validación.
2. Multitenancy validado en servicio además de RLS.
3. Sin proveedores externos de pago (push PWA con `web-push` es gratuito y sí entra; ETA, Google Maps, WhatsApp y SMS no).
4. Identificadores en español sin acentos.
5. Cerrar con `CONTEXTO.md` (avance P05 ✅; sección "Campo, offline y chat (P05)" con el contrato de `sync/mutaciones`, la cola, los eventos de chat y lo que P06, P07 y P09 deben enganchar) y `BITACORA.md` actualizados.
6. No cambiar el stack.

## Al terminar

Resumen en español con: tablas de la migración 0005, endpoints y canales en tiempo real, tipos de mutación soportados por la cola y sus reglas de conflicto, pantallas de operador y técnico, decisiones pendientes nuevas y conteo de pruebas.
