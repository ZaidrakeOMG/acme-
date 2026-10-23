# P03 — Motor de formularios dinámicos (Fase 1, prompt 3 de 11)

## Contexto

P02 está cerrado (commit `f6846b6`; 96 pytest y 27 vitest en verde). Lee antes de empezar `CONTEXTO.md` (secciones "Arquitectura vigente" y "Catálogos maestros (P02)"), `BITACORA.md`, y en `ACMA_Documento_Diseno_v2.5.docx` las secciones §4.3 (los 22 tipos de campo, con sus dos principios: rol destino configurable y valor por defecto configurable) y §6.8.3c (roles de diseño, repositorio de plantillas, campos enlazados a catálogos, cascada, formularios por cliente, control de calidad de fotografías e inmutabilidad).

Este prompt construye el motor completo: modelo, constructor visual, renderizador y validación de respuestas. No construye folios (P04); el folio será el primer consumidor del motor, así que todo lo que aquí se entregue debe poder invocarse desde P04 sin modificaciones.

## Objetivo

Que el Superadmin y el Admin prestador puedan diseñar, versionar, asignar y publicar formularios sin programar, con los 22 tipos de campo de §4.3, y que cualquier rol destino pueda llenarlos desde la PWA con validación idéntica en cliente y servidor.

## Entregables

### 1. Migración `0003_formularios.py`

Con los helpers de `core/sql_migracion.py` (`ex`, `rls`, `versionar`, `politicas_tenant`…), igual que 0002.

| Tabla | Propietario | Campos clave |
|---|---|---|
| `formularios` | Prestador (o plataforma si `prestador_id` NULL) | prestador_id (nullable), tenant_id (nullable = alcance global del prestador), nombre, descripcion, tipo (`captura_operador` / `atencion_tecnico` / `preventivo` / `trabajo_especial` / `encuesta` / `libre`), rol_destino (array de roles, §4.3), estado (`borrador` / `publicado` / `archivado`), version_publicada_id, es_plantilla_base (bool, solo plataforma), clonado_de_id (nullable) |
| `formulario_versiones` | Igual que su formulario | formulario_id, numero_version, esquema_json (definición completa de campos, orden, secciones, lógica condicional y cascada), publicada_at, publicada_por, notas_version |
| `formulario_asignaciones` | Prestador | formulario_id, tenant_id (nullable), tipo_folio (nullable), tipo_equipo_id (nullable), familia_equipo_id (nullable), plan_mantenimiento_id (nullable, FK diferida: la tabla llega en P06, dejar sin constraint y anotarlo), prioridad (específico de tenant > global, §6.8.3c), activa |
| `formulario_permisos_mesa` | Prestador | formulario_id, usuario_id (mesa_control), puede_editar_publicado (§6.8.3c) |
| `catalogos_personalizados` y `catalogo_personalizado_opciones` | Prestador, por tenant opcional | prestador_id, tenant_id (nullable), nombre, clave; opciones con valor, etiqueta, orden, activa, padre_opcion_id (para cascada propia) |
| `formulario_respuestas` | Tenant | formulario_id, version_id, tenant_id, un_id (nullable), origen (`folio_captura` / `folio_atencion` / `independiente` …), referencia_id (nullable; P04 guardará aquí el folio_id), respuestas_json, respondido_por, iniciado_at, enviado_at, estado (`en_progreso` / `enviado`), dispositivo_json, inmutable (bool) |
| `formulario_evidencias` | Tenant | respuesta_id, campo_clave, tipo (`foto` / `firma` / `dibujo` / `archivo` / `audio`), archivo_key (MinIO), nombre_original, mime, bytes, ancho_px, alto_px, geolat, geolng, exif_timestamp, anotaciones_json, orden, etiqueta (p. ej. Antes / Detalle / Después), hash_sha256 |
| `calidad_foto_defaults` | Plataforma | tamano_minimo_kb, resolucion_minima_ancho, resolucion_minima_alto, compresion_maxima_pct (defaults globales de Superadmin, §6.8.3c) |

Reglas:
- Una versión publicada no se edita: cualquier cambio sobre un formulario publicado crea `numero_version + 1` en borrador; publicar la nueva versión no afecta respuestas ya enviadas, que conservan `version_id`.
- `formulario_respuestas` con `estado = enviado` es inmutable: trigger `BEFORE UPDATE` que solo permite cambiar `estado` de `en_progreso` a `enviado` y rechaza cualquier UPDATE posterior; `formulario_evidencias` de una respuesta enviada rechaza UPDATE y DELETE (§4.3 y §6.8.3c: la evidencia adicional posterior va por el chat del folio, P05).
- Las respuestas se guardan contra el `esquema_json` de la versión; agregar los `version_id` a `TABLAS_VERSIONADAS` según convención.

### 2. Esquema JSON de formulario (contrato compartido backend/frontend)

Definir en `backend/schemas/formularios.py` (Pydantic) y en `frontend/src/types/formularios.ts` (TypeScript, generado o escrito a mano pero idéntico) el contrato:

- `secciones[]` → `campos[]`. Cada campo: `clave` (única en el formulario, sin acentos), `tipo` (uno de los 22 identificadores de abajo), `etiqueta`, `ayuda`, `obligatorio`, `valor_defecto` (solo en los tipos que §4.3 lo permite), `config` (objeto específico por tipo), `condiciones[]` y `fuente_opciones` (fija o catálogo).
- `condiciones[]`: `{ campo_origen, operador, valor, accion }` con operadores `igual`, `distinto`, `contiene`, `vacio`, `no_vacio`, `en_rango`, `opcion_seleccionada`; acción `mostrar` u `ocultar`. Se evalúan en cadena y en el mismo orden en cliente y servidor.
- `fuente_opciones`: `{ origen: "fija", opciones[] }` o `{ origen: "catalogo", catalogo, filtro_contexto, campo_padre }` donde `catalogo` es uno de: `equipos_tenant`, `unidades_negocio`, `tecnicos_prestador`, `tipos_falla`, `tipos_equipo`, `familias_equipo`, `materiales` (sin datos hasta P09: devolver lista vacía con aviso), `proveedores_externos` (igual, P08), `catalogo_personalizado`. Los catálogos se consultan con los endpoints de P02 y el `filtro_contexto` usa el contexto del folio activo (`un_id`, `tenant_id`, `equipo_id`) que P04 pasará al renderizador; `campo_padre` implementa la cascada de §6.8.3c.

Identificadores de los 22 tipos, en el orden de §4.3: `si_no`, `opcion_multiple`, `texto`, `texto_amplio`, `fotografia`, `firma`, `dibujo`, `radio`, `boton_grupo`, `lista_desplegable`, `seleccion_multiple`, `concatenacion`, `archivo`, `escaner`, `etiqueta_info`, `audio`, `fecha_hora`, `sello_fecha_hora`, `matematicas_tiempo`, `slider`, `encuesta_satisfaccion`, `geolocalizacion`.

Para cada tipo, `config` debe contemplar exactamente los parámetros que §4.3 enumera (etiquetas de botones y modo de valor por defecto en `si_no`; mínimo/máximo de selecciones, fuente fija o catálogo y lógica por opción en `opcion_multiple` y `seleccion_multiple`; longitud, restricción de formato y regex en `texto`/`texto_amplio`; origen cámara/galería, calidad mínima, cantidad y etiquetas en secuencia, anotación y vista previa en `fotografia`; lienzo obligatorio y pantalla completa en `firma`; imagen de referencia (incluida una foto previa del mismo formulario) en `dibujo`; 2 a 5 opciones con color libre en `boton_grupo`; búsqueda, selección única/múltiple y disponibilidad offline en `lista_desplegable`; contador por opción, grupos colapsables y plantillas de combinaciones en `seleccion_multiple`; partes de texto fijo y campos origen en `concatenacion`; tipos y tamaño en `archivo`; QR/EAN/Code128/DataMatrix y precarga de contexto de equipo en `escaner`; formato enriquecido y enlace en `etiqueta_info`; duración máxima en `audio`; modos fecha/hora/ambos, rangos, "hoy + N" e instancias inicio/fin en `fecha_hora`; trigger en `sello_fecha_hora`; fuentes usuario/sistema y unidad del resultado en `matematicas_tiempo`; mínimo, máximo, incremento, etiquetas y modo rango en `slider`; estrellas/numérica/emojis, obligatoriedad y disparo por rango bajo en `encuesta_satisfaccion`; radio de ajuste manual, registro dual y geofencing por UN en `geolocalizacion`).

Documentar el contrato completo en `docs/formularios/tipos_de_campo.md` (equivale a ACT-4.1): por cada tipo, comportamiento, parámetros de `config`, validaciones, qué guarda en `respuestas_json` y casos límite.

### 3. Backend — servicios y endpoints (prefijo `/api/formularios`)

- CRUD de formularios y versiones: crear, editar borrador, publicar, archivar, clonar (de plantilla base o de otro formulario propio), listar con filtros por tipo, alcance y estado. Permisos de §6.8.3c: Superadmin todo; Admin prestador los suyos; Mesa de control solo los formularios publicados donde `formulario_permisos_mesa.puede_editar_publicado` sea verdadero (su edición crea versión nueva); Admin empresa y Admin UN solo lectura de resultados.
- Asignaciones: CRUD y `GET /api/formularios/resolver?tipo=&tenant_id=&tipo_equipo_id=&familia_equipo_id=&plan_id=` que devuelve el formulario publicado aplicable con la prioridad de §6.8.3c (específico de tenant sobre global; coincidencia más específica primero). P04 lo usará.
- Catálogos personalizados: CRUD por prestador y tenant.
- Respuestas: `POST /api/formularios/{id}/respuestas` (crea en progreso), `PUT .../{respuesta_id}` (guarda parcial; permite reanudar), `POST .../{respuesta_id}/enviar` (valida contra el esquema de la versión y marca inmutable), `GET` por rol destino, origen y referencia. Validación en servidor con el mismo motor de reglas que el cliente: obligatorios, longitudes, regex, mínimos/máximos, cantidad de fotos, condiciones (un campo oculto por condición no es obligatorio ni se valida), concatenaciones y matemáticas recalculadas en servidor (el valor del cliente se descarta), sello de fecha y hora fijado por el servidor según el trigger.
- Evidencias: `POST /api/formularios/respuestas/{id}/evidencias` con validación de calidad de foto (tamaño mínimo, resolución mínima, compresión máxima con los defaults de `calidad_foto_defaults` o los del campo), extracción de EXIF y GPS con Pillow, `hash_sha256`, guardado en MinIO con `obtener_almacenamiento()`; anotaciones (flechas, círculos, trazos) guardadas como `anotaciones_json` y como imagen compuesta aparte, nunca sobre el original.
- Transcripción de audio (§4.3 `audio`): dejar la interfaz `services/transcripcion.py` con implementación `stub` que registra "transcripción pendiente" (regla 3: sin proveedores de pago en Fase 1). Anotar en `CONTEXTO.md` como pendiente de Fase 2.
- Geofencing (§4.3 `geolocalizacion`): calcular con PostGIS la distancia entre la coordenada capturada y `unidades_negocio.ubicacion`; si supera el radio configurado del campo, disparar la alerta `GEOLOCALIZACION_FUERA_DE_UN` (nueva clave en `alertas_catalogo`, evaluador en `workers/evaluadores.py`) y registrar `geolocalizacion_ajustada` en `audit_log` cuando el usuario ajustó la coordenada.
- Auditoría con `auditoria.registrar_actor` en publicar, archivar, clonar y enviar respuesta.

### 4. Frontend

- Módulo `formularios` (`src/config/modulos.ts`, P03): agregar `ruta` y página en `PAGINAS`; roles Superadmin y Admin prestador; Mesa de control ve la lista y edita solo los que tenga permitidos.
- **Constructor** (`pages/formularios/Constructor.tsx`): paleta con los 22 tipos; lienzo con secciones y campos ordenables por arrastre; panel de propiedades por tipo (todos los parámetros de `config`); editor visual de condiciones (campo origen → operador → valor → mostrar/ocultar); arrastre de un catálogo del sistema sobre un campo para enlazarlo como fuente (§6.8.3c) y configuración de cascada eligiendo el campo padre; vista previa en vivo con el renderizador real; publicar con notas de versión; comparación simple entre versiones (campos agregados, quitados, modificados).
- **Repositorio de plantillas** (`pages/formularios/Plantillas.tsx`): lista de plantillas base, clonar con un clic. Sembrar 4 plantillas base de §6.8.3c: cierre de correctivo, inspección preventiva, instalación de equipo y trabajo especial, usando entre todas los 22 tipos de campo.
- **Renderizador** (`components/formularios/Renderizador.tsx` y un componente por tipo en `components/formularios/campos/`): recibe `esquema_json`, contexto (`tenant_id`, `un_id`, `equipo_id`, rol) y respuestas; evalúa condiciones y cascadas en tiempo real; valida en cliente con las mismas reglas del servidor (compartir la lógica en `src/services/formularios/validacion.ts`); soporta guardar parcial y reanudar. Cámara con `mediaDevices` y `facingMode` cuando el origen es solo cámara; comprobación de calidad de foto antes de aceptar (indicador verde/rojo); lienzo de firma y de dibujo con `canvas`; escáner con una librería de código abierto (por ejemplo `@zxing/browser`); audio con `MediaRecorder`; geolocalización con `navigator.geolocation` y mapa simple para el ajuste dentro del radio; selector de fecha nativo. Las evidencias se suben al terminar cada campo, no al enviar.
- **Pantalla "Mis formularios"** (`pages/formularios/MisFormularios.tsx`) para cualquier rol destino: formularios publicados asignados a su rol con `origen = independiente`, en progreso y enviados (solo lectura al enviarse).
- Preparar el renderizador para offline: no implementar la cola todavía (P05), pero toda escritura debe pasar por una única función `guardarRespuesta()` en `src/services/formularios/respuestas.ts` que P05 pueda interceptar.

### 5. Seed y pruebas

- Seed: las 4 plantillas base, un catálogo personalizado "Causa raíz" con 6 opciones para el tenant demo, un formulario de captura y uno de atención publicados para el prestador demo y asignados a la familia "Refrigeración", y uno específico del tenant demo para el mismo caso (para probar la prioridad).
- Backend (`tests/test_formularios.py`, `tests/test_formularios_validacion.py`, `tests/test_formularios_evidencias.py`): permisos por rol de §6.8.3c; versionado (editar publicado crea versión nueva; respuestas conservan versión); `resolver` con prioridad específico > global; validación de cada uno de los 22 tipos con un caso válido y uno inválido; condiciones que ocultan campos obligatorios; cascada con tipos de falla por familia; concatenación y matemáticas de tiempo recalculadas en servidor; sello de fecha fijado por servidor; inmutabilidad de respuesta enviada y de sus evidencias; rechazo de foto por tamaño, resolución y compresión; geofencing que dispara la alerta; aislamiento entre tenants y prestadores; RLS forzada en todas las tablas nuevas.
- Frontend (vitest): constructor agrega y configura un campo de cada tipo; editor de condiciones oculta y muestra campos en la vista previa; renderizador bloquea el envío con obligatorios vacíos y con fotos por debajo del mínimo; cascada familia → tipo de falla.
- `pytest`, `vitest`, `tsc --noEmit` y `npm run build` en verde.

## Reglas (vigentes de P01 y P02)

1. Seguir el Documento de Diseño v2.5; lo no definido se anota en `CONTEXTO.md` como decisión pendiente de validación.
2. Multitenancy validado en servicio además de RLS.
3. Sin proveedores externos de pago (transcripción en `stub`).
4. Identificadores en español sin acentos.
5. Cerrar con `CONTEXTO.md` (avance P03 ✅; sección "Motor de formularios (P03)" con el contrato del esquema, `resolver`, `guardarRespuesta()` y lo que P04 y P05 deben reutilizar) y `BITACORA.md` actualizados.
6. No cambiar el stack.

## Al terminar

Resumen en español con: tablas de la migración 0003, endpoints, lista de los 22 tipos con su identificador, plantillas sembradas, pendientes de Fase 2 detectados y conteo de pruebas.
