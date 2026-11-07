# F2-01 — Capacitación y certificación de técnicos, biblioteca de manuales y contenido de servicio (segunda etapa, bloque 1 de 9)

## Contexto

La Fase 1 está cerrada y el paso 0 aplicado (último commit `8c52e52`). Lee antes de empezar `CONTEXTO.md` completo (incluidas las reglas de la segunda etapa del paso 0 y las notas de entorno), `BITACORA.md`, `docs/piloto/ACMA_Segunda_Etapa.xlsx` (hoja «Bloques Fase 2», fila 1) y en `ACMA_Documento_Diseno_v2.5.docx`: §6.10.3 completo (capacitación y certificación, 3 tablas), §6.10.4 completo (biblioteca y contenido de servicio, 4 tablas), §4.1 (módulos Capacitación de técnicos y Biblioteca de manuales), §5.2 (Técnico: «accede a biblioteca de manuales»), §6.8.3 (permiso `acceder_manuales`), §6.9.6 (alerta `CERTIFICACION_VENCIDA`), §6.10.1 (preventivos de iguala «con su periodicidad y puntos a revisar definidos en la biblioteca de manuales»), §6.2 capa 3 (offline) y ACT-5.3 del §8.

Este bloque no requiere ningún proveedor externo. Lo que la Fase 1 dejó listo y este prompt debe usar sin duplicar: `habilidades` y `tecnico_habilidades` con `certificada`, `fecha_certificacion`, `vigencia_hasta` y `origen` (`manual` / `curso`) de P02; la restricción dura de asignación por habilidad certificada (P04/P06); el permiso `acceder_manuales` (P01); la clave `biblioteca` del paquete de sincronización del técnico, hoy vacía (`services/sync_service.py`); la alerta `CERTIFICACION_VENCIDA` registrada como Fase 2 e inactiva (P10); `contratos.preventivos_iguala_json` (P10); el almacenamiento con cifrado por dueño (P11a); y el importador de P02.

## Objetivo

Que el Admin prestador lleve el historial de cursos y certificaciones de cada técnico con sus vencimientos, que una certificación vigente habilite automáticamente la habilidad correspondiente (y su vencimiento la retire), que el cliente consulte las certificaciones de los técnicos que atienden sus UNs, y que el técnico consulte y descargue para uso sin señal los manuales del tipo de equipo que atiende y los puntos de revisión que el cliente fijó en su contenido de servicio.

## Entregables

### 1. Migración `0013_capacitacion_biblioteca.py`

Con los helpers de `core/sql_migracion.py`, RLS forzada en toda tabla con `tenant_id`/`prestador_id`, `acma_version()` donde corresponda.

**Capacitación (§6.10.3, las 3 tablas literales más lo necesario):**

| Tabla | Campos clave |
|---|---|
| `cursos_catalogo` | prestador_id (nullable = catálogo global del Superadmin), nombre, proveedor, duracion_horas, vigencia_meses (nullable = no vence), habilidad_id (nullable), tipo ENUM(`curso` / `certificacion`), norma_referencia (texto libre, p. ej. «NOM-STPS / DC-3»), activo |
| `tecnico_cursos` | tecnico_id, curso_id, fecha_inicio, fecha_fin, calificacion, aprobado (bool), certificado_key (archivo en almacenamiento, PDF o imagen), vigente_hasta (calculado de `fecha_fin + vigencia_meses`, editable con razón), folio_constancia (texto), registrado_por, estado ENUM(`vigente` / `por_vencer` / `vencido` / `sin_vigencia`) calculado |
| `capacitacion_alertas_config` | prestador_id, dias_anticipacion (default 30), notificar_cliente (bool), activa |

**Biblioteca (§6.10.4, las 4 tablas literales):**

| Tabla | Campos clave |
|---|---|
| `biblioteca_manuales` | tipo_equipo_id, prestador_id, titulo, categoria ENUM(`ficha_tecnica` / `procedimiento` / `diagrama` / `refacciones` / `otro`), version (entero), fecha_subida, archivo_key, nombre_original, mime, bytes, hash_sha256, activo, subido_por |
| `biblioteca_versiones` | manual_id, version_anterior, archivo_key_anterior, reemplazado_en, reemplazado_por, notas_version — **append-only** |
| `contenido_servicio` | tenant_id, tipo_equipo_id, contrato_id, titulo, puntos_revision_json (lista ordenada de puntos con descripción y si es obligatorio), periodicidad, correctivos_iguala, preventivos_iguala_json, archivo_key (nullable, documento adjunto), version, activo, subido_por |
| `tecnico_descargas_offline` | tecnico_id, manual_id (nullable), contenido_id (nullable), fecha_descarga, version_descargada, en_dispositivo (bool), dispositivo_id |

`contenido_servicio` es confidencial del tenant: su política RLS solo lo deja ver al propio tenant y al prestador que lo atiende con ese contrato (y a ningún otro tenant del mismo prestador).

### 2. Capacitación (`services/capacitacion_service.py`)

- Catálogo: CRUD por Admin prestador (propio) y Superadmin (global, `prestador_id` NULL). Importación de cursos y del historial de cursos por técnico con el importador de P02 (nuevos catálogos `cursos` y `tecnico_cursos`, con plantilla Excel).
- Registro de cursos por técnico con certificado adjunto (PDF o imagen, guardado con `obtener_almacenamiento()` y el cifrado por dueño de P11a).
- **Vinculación automática con habilidades (§6.10.3):** al registrar un curso aprobado cuyo `curso_id` tenga `habilidad_id`, crear o actualizar `tecnico_habilidades` con `certificada = true`, `origen = curso`, `fecha_certificacion = fecha_fin` y `vigencia_hasta` del curso. Si el técnico ya tenía la habilidad con `origen = manual`, conservarla y registrar el curso como respaldo (anotar la regla).
- **Vencimiento:** tarea beat diaria que recalcula `estado` y, cuando `vigencia_hasta` pasa, marca la habilidad derivada como no certificada. Consecuencia que debe quedar probada: a partir de ese día la restricción dura de asignación de P04/P06 impide asignar ese técnico a folios que requieren la habilidad (salvo el permiso `asignar_tecnico_sin_habilidad` con razón). Registrar en `audit_log` cada habilidad retirada por vencimiento.
- **Alerta `CERTIFICACION_VENCIDA`:** activarla (cambiar `fase` a 1 en el catálogo de alertas, con su umbral por defecto de 30 días dentro del rango que fije el Superadmin) y escribir su evaluador: al Admin prestador siempre; al Admin empresa y Admin UN de los tenants donde el técnico está habilitado (`tecnico_tenants_habilitados` de P02) solo si `notificar_cliente` está activo. Agregar `CERTIFICACION_VENCIDA_HABILIDAD_RETIRADA` para el día en que efectivamente se retira la habilidad.
- **Vista del cliente (§6.10.3):** `GET /api/capacitacion/tecnicos-de-mis-unidades` para Admin empresa y Admin UN: técnicos habilitados para su tenant, o que atendieron folios en sus UNs en los últimos 90 días (anotar la regla), con sus certificaciones **vigentes** (nombre, norma, vigencia). No muestra calificaciones, cursos no aprobados, certificados adjuntos ni datos internos del prestador.
- Expediente del técnico para Admin prestador: cursos, certificaciones, habilidades derivadas y próximos vencimientos; exportable a Excel y PDF (generadores de P07/P10).

### 3. Biblioteca (`services/biblioteca_service.py`)

- **Manuales técnicos (Admin prestador):** subir por tipo de equipo; subir una nueva versión reemplaza la vigente y escribe `biblioteca_versiones` (§6.10.4: «cada nueva versión reemplaza la anterior pero conserva el historial»); desactivar; historial de versiones con descarga de anteriores solo para Admin prestador. Tipos permitidos: PDF, imágenes y video corto (definir límite de tamaño y anotarlo; sugerencia 50 MB).
- **Contenido de servicio contractual (Admin empresa):** por tipo de equipo y contrato; puntos de revisión estructurados (lista ordenada editable, no solo un archivo), periodicidad, correctivos y preventivos de la iguala; versiones. Validar coherencia con `contratos.folios_correctivos_iguala` y `preventivos_iguala_json` de P10 y mostrar advertencia si difieren (no bloquear; anotar).
- **Consulta por el técnico:** con el permiso `acceder_manuales`, el técnico ve los manuales vigentes de los tipos de equipo de sus folios asignados y de todo el catálogo de su prestador (filtro por tipo de equipo y búsqueda por título), y el contenido de servicio del tenant y tipo de equipo **solo de los folios que tiene asignados**.
- **En la atención del folio (P05):** botón «Manual del equipo» y sección «Puntos de revisión del cliente» con los `puntos_revision_json` del contenido de servicio aplicable; en preventivos (P06), mostrarlos junto a las tareas del plan. No se convierten en campos obligatorios del formulario en este prompt (anotar como mejora posible).

### 4. Descarga para uso sin señal (§6.2 capa 3, ACT-5.3)

- Llenar la clave `biblioteca` del paquete de `GET /api/sync/catalogos` con los metadatos (no los archivos) de los manuales y contenidos aplicables al técnico, incrementales por `updated_at` con bajas lógicas.
- En la PWA: nueva tabla Dexie `biblioteca_offline` (blob + metadatos + versión) en una versión nueva del esquema; descarga **selectiva** (el técnico elige qué guardar) y descarga automática de los manuales del tipo de equipo de sus folios del día si está en Wi-Fi (configurable). Pantalla «Mis manuales sin conexión» con tamaño ocupado, versión, aviso de «hay versión nueva» y botón para borrar; límite de almacenamiento configurable con la API de cuota del navegador (`navigator.storage.estimate()`), avisando antes de superarlo.
- Registrar cada descarga y cada borrado en `tecnico_descargas_offline` (por la cola de mutaciones de P05 cuando ocurre sin señal).
- Cuando hay versión nueva de un manual descargado, marcar el anterior como desactualizado en el dispositivo y ofrecer actualizar.

### 5. Endpoints

`/api/capacitacion` (catálogo, cursos por técnico, expediente, vista del cliente, configuración de alertas, exportación) y `/api/biblioteca` (manuales, versiones, contenido de servicio, consulta del técnico, descarga con URL firmada de corta duración). Validación de multitenancy en servicio además de RLS; auditoría con `registrar_actor` en altas, nuevas versiones, desactivaciones y descargas de certificados; registro de «acceso a datos sensibles» (P11a) al descargar certificados de técnicos.

### 6. Frontend

- Agregar los módulos `capacitacion` y `biblioteca` a `src/config/modulos.ts` (grupo Operación o Recursos; elegir y anotar) con sus roles: Capacitación → Superadmin, Admin prestador, Mesa de control (lectura), Despachador (lectura de vigencias), Admin empresa y Admin UN (solo la vista del cliente); Biblioteca → Superadmin, Admin prestador, Mesa de control, Despachador, Técnico (con permiso), Admin empresa y Admin UN (su contenido de servicio).
- `pages/capacitacion/Capacitacion.tsx`: catálogo, registro de cursos con carga del certificado, expediente por técnico con semáforo de vigencias (texto además del color), próximos vencimientos y configuración de alertas; vista del cliente separada y sin datos internos.
- `pages/biblioteca/Biblioteca.tsx`: manuales por tipo de equipo con versiones; contenido de servicio del cliente con editor de puntos de revisión; visor de PDF en el navegador.
- App del técnico (P05): acceso a la biblioteca, «Mis manuales sin conexión», y en la atención del folio el botón del manual y los puntos de revisión.
- En la asignación y reasignación de técnicos (P04/P06), mostrar junto a cada candidato si su certificación de la habilidad requerida está vigente o próxima a vencer.
- Quitar las etiquetas «Fase 2» de la alerta `CERTIFICACION_VENCIDA` y de la biblioteca del técnico; actualizar la hoja «Dónde se ve en el sistema» si menciona este bloque (no editar el Excel: anotar en `CONTEXTO.md` qué filas quedan obsoletas).

### 7. Seed y pruebas

- Seed: 8 cursos (3 globales, 5 del prestador demo; al menos 4 ligados a habilidades, uno tipo DC-3), historial para los 4 técnicos con certificados de ejemplo, una certificación vencida, una por vencer en 10 días y una sin vigencia; configuración de alertas con `notificar_cliente` activo; 6 manuales (2 con dos versiones) para 3 tipos de equipo; contenido de servicio del tenant demo para 2 tipos de equipo con puntos de revisión coherentes con el contrato de iguala de P10.
- Backend (`tests/test_capacitacion.py`, `tests/test_certificacion_habilidades.py`, `tests/test_biblioteca.py`, `tests/test_contenido_servicio.py`, `tests/test_biblioteca_offline.py`): catálogo global y propio por rol; curso aprobado crea la habilidad certificada y uno reprobado no; vencimiento retira la habilidad y **la asignación queda bloqueada** salvo el permiso con razón; alerta por vencer al prestador y al cliente solo con `notificar_cliente`; vista del cliente sin datos internos y limitada a sus técnicos; nueva versión de manual conserva historial e inmutabilidad de `biblioteca_versiones`; contenido de servicio invisible para otro tenant del mismo prestador (RLS y HTTP); técnico solo ve contenido de servicio de sus folios; permiso `acceder_manuales` desactivado bloquea; paquete de sincronización incremental con bajas; registro de descargas por la cola offline; aislamiento entre tenants y prestadores; RLS forzada en todas las tablas nuevas.
- Frontend: registro de curso con certificado, semáforo de vigencias, visor del manual, descarga y borrado sin conexión (con `fake-indexeddb`), puntos de revisión en la atención.
- `pytest`, `vitest`, `tsc --noEmit` y `npm run build` en verde, con los servidores de desarrollo apagados durante la suite completa.

## Reglas (vigentes)

1. Seguir el Documento de Diseño v2.5; lo no definido se anota en `CONTEXTO.md` como decisión pendiente de validación.
2. Multitenancy validado en servicio además de RLS.
3. Sin proveedores externos de pago (este bloque no necesita ninguno).
4. Identificadores en español sin acentos.
5. Cerrar con `CONTEXTO.md` (avance F2-01 ✅; sección «Capacitación y biblioteca (F2-01)») y `BITACORA.md` actualizados.
6. No cambiar el stack.
7. No correr la suite completa con los servidores de desarrollo encendidos.
8. Commits solo locales (sin remoto, por decisión de la usuaria); si el trabajo es largo, commits parciales «F2-01 (1/2) backend» y «F2-01 (2/2) frontend».

## Al terminar

Resumen en español con: tablas de la migración 0013, endpoints, reglas elegidas (habilidad manual frente a curso, técnicos visibles para el cliente, límite de tamaño de archivos, descarga automática), alertas activadas, decisiones pendientes nuevas y conteo de pruebas.
