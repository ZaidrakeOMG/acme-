# BITÁCORA — ACMA (desarrollo nuevo)

Registro por fecha de lo realizado en cada prompt.

## 2026-10-28 · P05 — Apps PWA del operador y del técnico, modo offline y chat

**Base de datos (migración 0005)**
- 9 tablas: chats, chat_participantes, chat_mensajes (id_cliente UNIQUE por chat, doble timestamp, leído), chat_archivos,
  chat_eventos_sistema, sincronizacion_dispositivos, sincronizacion_conflictos, sincronizacion_mutaciones (bitácora
  idempotente) y suscripciones_push; `plazo_encuesta_horas` en las políticas del tenant. Trigger de inmutabilidad de
  mensajes en folio cerrado; RLS de mensajes/archivos limitada a participantes (políticas de escritura por comando, misma
  corrección aplicada a `folios`).

**Backend**
- Sincronización: paquete incremental de catálogos por rol con bajas lógicas, lote de mutaciones en orden e idempotente
  (7 tipos) con las reglas de §6.2 (server-wins, client-wins con hora real, merge con alerta como gancho para P09),
  evidencias en dos pasos y registro de conflictos. `transicionar()` y `enviar()` aceptan `momento`.
- Chat: tres chats automáticos por folio (gancho `folio.creado`), participantes fijos y permisos literales de §6.8.1,
  eventos de sistema por transición, evidencia posterior al cierre, archivado de cancelados sin asignar, WebSocket por chat
  con Redis pub/sub y fallback SSE.
- Cierre en campo: firma del operador/Admin UN, encuesta NPS con formulario resuelto por P03 y plazo configurable, evento
  `encuesta.pendiente` al cerrar. Push PWA con web-push (VAPID) y suscripciones por dispositivo; `mis-permisos`.
- Seed: encuesta publicada, chats y mensajes demo (incluido el folio cerrado) y suscripción push de prueba.

**Frontend**
- Dexie v2, `syncEngine` (cola FIFO, reintento exponencial, «requiere atención», reanudación tras recarga, refresco de
  catálogos, ids locales), transporte híbrido de formularios, `useConexion` + indicador global, pantalla «Pendientes de
  sincronizar», service worker con `NetworkFirst` para la API y manejador de push.
- App del operador (inicio por UN, captura táctil offline con confirmación de UN, detalle con chat, firma a pantalla
  completa y encuesta), app del técnico (mis folios hoy/próximos, atención con acciones, formulario de P03, refacciones y
  chat) y `ChatFolio` con pestañas por canal, tiempo real, adjuntos, leído y participantes, integrado en el detalle.

**Pruebas:** 203 pytest y 45 vitest en verde; `tsc --noEmit` limpio; `npm run build` verde.

**Incidencias resueltas:** una política RLS `FOR ALL` concede SELECT (se separó por comando); `INSERT … RETURNING` exige
pasar la política de lectura (ids generados en el cliente para mensajes de sistema); el envío push debe correr en sesión
de sistema; parches con `replace` fallaban por archivos con CRLF (script tolerante a finales de línea).

## 2026-10-27 · P04 — Folios: ciclo de vida, validaciones y aprobación multinivel

**Base de datos (migración 0004)**
- 16 tablas: folios (numero correlativo por tenant con prefijo, 11 estados, severidad y origen, confirmación de UN,
  duplicado con justificación, monto estimado), folio_estados_historial y aprobacion_decisiones (append-only, también
  para superadmin), folio_formulario_captura/atencion, folio_evidencias, folio_refacciones, folio_sla, folio_encuesta,
  revision_manual_triggers, folio_keywords_alerta, folio_politicas_tenant, aprobacion_reglas, aprobacion_flujos,
  aprobacion_niveles_config (CHECK del Nivel 3) y aprobacion_alertas_timeout. Trigger de inmutabilidad del folio
  cerrado/cancelado; función `acma_siguiente_numero_folio()` (acma_auth); `contratos.horario_servicio_json`,
  `equipos.criticidad`, `familias_equipo.habilidad_clave`; 3 alertas nuevas (25 en el catálogo).

**Backend**
- Motor de estados `folio_estados.py` con la tabla literal de §6.8.6 y `transicionar()` como única puerta de cambio de estado
  (409 `TRANSICION_NO_PERMITIDA` / `CIERRE_INCOMPLETO`, historial, auditoría, fechas, suscriptores para P05/P06/P07/P10).
- Captura `folios_captura_service.py` con las 8 validaciones en orden, duplicado con bloqueo total o confirmación fuerte,
  severidad automática y override, permisos configurables de técnico y despachador, alcance por rol y archivo completo.
- Aprobación `aprobacion_service.py`: nivel de entrada (monto, criticidad, tipo de trabajo; la más restrictiva gana),
  auto-aprobación de críticos, bandeja por nivel, aprobación en cadena, rechazo con 4 razones → módulo destino y evento
  `folio.derivado_a_modulo`, timeouts con las cuatro opciones (Celery cada minuto). Evaluador `FOLIO_EN_REVISION_SIN_ATENDER`.
- 32 endpoints bajo `/api/folios`; stub `services/notificaciones.py`.
- Seed: políticas y prefijo `CD`, 6 reglas, 3 niveles, criticidad en 12 equipos, 4 palabras clave, horario de servicio y 15
  folios (uno por trigger, flujo en Nivel 1 y 2, pendiente de información, autorizado, asignado, en ejecución, cerrado
  con atención y firma, cancelado por rechazo).

**Frontend**
- Módulo Folios: listado con filtros y Kanban, detalle con todas las secciones del archivo, línea de tiempo, acciones
  según la tabla de transiciones del servidor y panel de aprobación; captura con selector de UN, equipos con contrato,
  falla por familia, formulario dinámico de P03, tarjeta de duplicado con justificación y confirmación obligatoria de UN
  («Sí, es esta unidad» / «No, quiero cambiarla»); bandeja de aprobación con rechazo en dos pasos y configuración del
  flujo para Admin empresa; `services/notificaciones.ts` (stub en consola).

**Pruebas:** 185 pytest y 39 vitest en verde; `tsc --noEmit` limpio; `npm run build` verde.

**Incidencias resueltas:** Docker Desktop otra vez con sockets huérfanos (mismo remedio); `ALTER FUNCTION … OWNER TO
acma_auth` requiere `GRANT CREATE ON SCHEMA` temporal y privilegios de tabla para la función SECURITY DEFINER; el
`now()` de PostgreSQL empataba el orden del historial (timestamps explícitos); las pruebas de catálogos cambian las
habilidades del técnico demo (las pruebas de folios las fijan); el evaluador de matriz ignoraba alertas por folio.

## 2026-10-23 · P03 — Motor de formularios dinámicos

**Base de datos (migración 0003)**
- 9 tablas: formularios, formulario_versiones, formulario_asignaciones, formulario_permisos_mesa, catalogos_personalizados,
  catalogo_personalizado_opciones, formulario_respuestas (inmutable al enviar), formulario_evidencias (inmutables con la
  respuesta; sin altas tras el envío) y calidad_foto_defaults. Alerta `GEOLOCALIZACION_FUERA_DE_UN`.

**Backend**
- Contrato Pydantic de los 22 tipos de campo con `config` validada por tipo, condiciones, fuentes fijas/catálogo y cascada.
- Motor de reglas (`validacion.py`): visibilidad en cadena, validación por tipo, concatenación/matemáticas/sellos en servidor.
- 26 endpoints bajo `/api/formularios`: CRUD con versionado, publicar, archivar, clonar, diff; asignaciones y `resolver`
  con prioridad §6.8.3c; permisos de mesa; catálogos personalizados; `opciones` de catálogos del sistema; respuestas
  (crear, parcial, enviar, listar) y evidencias (subir con control de calidad, EXIF/GPS, hash; descargar; eliminar).
- Geofencing con PostGIS al enviar + evaluador de respaldo; auditoría de ajustes manuales; transcripción stub.
- Seed: 4 plantillas base (22 tipos), catálogo «Causa raíz» (6 opciones), formulario de captura y de atención publicados y
  asignados a Refrigeración, y uno específico del tenant demo.

**Frontend**
- Tipos espejo y motor de validación espejo; `respuestas.ts` como única puerta de escritura (interceptable en P05).
- Renderizador con un componente por tipo: cámara (`mediaDevices`) con indicador verde/rojo y anotación, firma y dibujo en
  `canvas`, escáner con `@zxing/browser`, audio con `MediaRecorder`, geolocalización con ajuste dentro del radio, cascada.
- Constructor visual: paleta de 22 tipos, lienzo con secciones y arrastre, panel con todos los parámetros de `config`,
  editor de condiciones, enlace de catálogos por arrastre, vista previa real, publicar con notas y comparación de versiones.
- Repositorio de plantillas, lista de formularios y «Mis formularios» (iniciar, reanudar, consultar enviados); página de
  llenado con guardado parcial automático.
- Documentación `docs/formularios/tipos_de_campo.md`.

**Pruebas:** 131 pytest y 33 vitest en verde; `tsc --noEmit` limpio; `npm run build` verde.

**Incidencias resueltas:** rutas literales (`/respuestas`, `/catalogos-personalizados`) declaradas después de
`/{formulario_id}`; EXIF GPS de prueba con `IFDRational`; caché de opciones compartida entre pruebas de vitest.

## 2026-10-23 · P02 — Catálogos maestros

**Base de datos (migración 0002)**
- 11 tablas nuevas: habilidades, tecnicos, tecnico_habilidades, tecnico_tenants_habilitados, niveles_severidad (5 por
  prestador, sembrados también al crear un prestador), familias_equipo y tipos_equipo (globales o del tenant), equipos,
  tipos_falla (flag `requiere_revision_manual` protegido además por trigger), tipo_falla_severidad e importaciones_catalogo.
- `contratos.cobertura`, `contrato_sla.nivel_severidad_id` (con backfill) y la alerta `MATRIZ_SEVERIDAD_INCOMPLETA`.
- Función `acma_equipo_con_contrato_activo(equipo_id)` y helpers reutilizables de migración en `core/sql_migracion.py`.

**Backend**
- 30 endpoints nuevos bajo `/api/catalogos`: habilidades, técnicos (ficha, habilidades, tenants §6.10.8, grupo, overrides y
  permisos efectivos), grupos de técnicos, severidades, familias y tipos de equipo (cascada), equipos (filtro por UN, texto y
  contrato activo), tipos de falla, matriz de severidad (celda, masiva y `resolver`) e importador (catálogos, plantilla,
  vista previa, confirmar, cancelar).
- Importador CSV/Excel para 8 catálogos con validación por fila, duplicados y límite de 10,000 filas; archivos en MinIO.
- Evaluador de alertas `MATRIZ_SEVERIDAD_INCOMPLETA` registrado en Celery (no se repite mientras haya una sin atender).
- Seed: 5 habilidades, 4 técnicos (2 nuevos: tecnico3 y tecnico4), 3 familias globales con 2 tipos cada una, 12 equipos
  (2 sin contrato activo, 1 en garantía), 8 tipos de falla y matriz completa (16 celdas) para el tenant demo.

**Frontend**
- Módulo Catálogos con pestañas por rol: Técnicos, Severidades, Familias y tipos, Equipos, Tipos de falla, Matriz de
  severidad (cuadrícula con color) e Importar (plantilla → vista previa → confirmar). Buscador reutilizable y
  `SelectorBusqueda` para P04.

**Pruebas:** 96 pytest y 27 vitest en verde; `tsc --noEmit` limpio; `npm run build` verde.

**Incidencias resueltas:** Docker Desktop otra vez con sockets huérfanos (mismo remedio); las semillas de una migración
chocan con la RLS forzada (se fija `app.rol = sistema` al inicio de la migración).

## 2026-10-19 · P01 — Cimientos

**Infraestructura**
- Repositorio nuevo en `Desktop\acma`, separado de `acma-proyecto` (que no se modificó).
- Docker Compose con PostgreSQL 16 + PostGIS, Redis 7 y MinIO en puertos propios; script de init con los roles
  `acma_owner`, `acma_api` y `acma_auth` y las bases `acma` y `acma_test`.
- Python 3.12 instalado; venv del backend; dependencias del frontend (React 19, Vite 8, TypeScript 7, Tailwind 4, vite-plugin-pwa 2).

**Base de datos (migración 0001)**
- 31 tablas: tenants, prestadores, tenant_prestador, usuarios, historial_contrasenas, roles (11, ENUM), permisos_catalogo,
  permisos_tecnico, grupos_tecnicos, grupo_tecnico_permisos, tecnico_grupo, tecnico_permisos_override, permisos_despachador,
  permisos_despachador_log, grupos_un, unidades_negocio (PostGIS), grupo_un_miembros, usuario_grupos, usuario_un, contratos,
  contrato_sla, alertas_catalogo (20 alertas semilla), alertas_configuracion, alertas_historial, alertas_supresiones,
  configuracion_tenant, configuracion_prestador, sesiones, intentos_fallidos, audit_log y audit_accesos_api (particionadas).
- RLS habilitada y forzada en todas las tablas con dueño; políticas fail-closed por tenant, prestador y rol.
- Auditoría append-only con triggers que rechazan UPDATE/DELETE/TRUNCATE, incluso al dueño del esquema.
- `version_hash` y `updated_at` mantenidos por trigger.

**Backend**
- FastAPI con 43 rutas en 10 routers: auth, usuarios, tenants, prestadores, unidades_negocio, grupos_un, contratos, alertas,
  configuracion, auditoria. OpenAPI con descripciones en español.
- Login en dos pasos con MFA TOTP (enrolamiento con QR, verificación, códigos de recuperación, deshabilitar, regenerar);
  JWT de 15 min y refresh rotativo de 7 días con detección de reúso que revoca la familia.
- Límite de 5 intentos fallidos por IP en 10 min, bloqueo temporal por usuario, política de contraseñas con historial de 10.
- Cabeceras de seguridad, CORS por entorno, bitácora de cada llamada a la API, cifrado AES-256-GCM de secreto MFA y datos fiscales.
- Celery con worker, beat y tareas `evaluar_alertas` (60 s), particiones de auditoría y purga de sesiones.
- `seed_dev.py`: Prestador Demo, Cliente Demo, 3 UNs, 1 grupo, 1 contrato con 5 SLAs y 12 usuarios (11 roles).

**Frontend**
- PWA instalable (manifest, íconos, service worker con precache del shell).
- Login con MFA y códigos de recuperación, AppShell con barra lateral y cabecera, RoleHub por rol con módulos futuros
  marcados "Disponible en el prompt Pxx".
- Pantallas: usuarios, clientes, prestadores (con logo y colores), UNs y grupos, contratos con SLAs, configuración de
  alertas, auditoría y "Mi seguridad".

**Pruebas:** 76 pytest y 19 vitest en verde; `tsc --noEmit` limpio; `npm run build` verde.

**Incidencias resueltas:** Docker Desktop bloqueado por sockets huérfanos; asyncpg 0.32 bloqueado por el Control de
aplicaciones de Windows (se fijó 0.31.0); `localStorage` de Node 25 en vitest; funciones SECURITY DEFINER sujetas a la RLS
forzada (se movieron a `acma_auth`).
