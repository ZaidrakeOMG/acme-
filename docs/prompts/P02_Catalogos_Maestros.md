# P02 — Catálogos maestros (Fase 1, prompt 2 de 11)

## Contexto

P01 está cerrado: 76 pruebas pytest y 19 vitest en verde, migración `0001_cimientos.py`, RLS fail-closed, auth con MFA y PWA con hub por rol. Lee antes de empezar `CONTEXTO.md` (sección "Arquitectura vigente" y "Decisiones pendientes"), `BITACORA.md` y las secciones §4.1 (módulo Catálogos maestros), §6.3, §6.8.3, §6.8.6 (validaciones automáticas en captura — modelo de datos), §6.10.8 y §4.3 (campos de catálogo en cascada) de `ACMA_Documento_Diseno_v2.5.docx`.

Este prompt construye los catálogos operativos que usarán formularios (P03) y folios (P04). No construye folios ni formularios.

## Objetivo

Que un Admin prestador y un Admin empresa puedan dejar cargados, desde la interfaz o desde un archivo CSV/Excel, todos los catálogos que un folio necesita para capturarse sin intervención del despachador: técnicos con habilidades, equipos por UN con contrato y garantía, familias y tipos de equipo, tipos de falla, niveles de severidad y la matriz de severidad tipo de falla × tipo de equipo.

## Entregables

### 1. Migración `0002_catalogos.py`

Misma convención que 0001: SQL explícito con `ex()`, `ENABLE` + `FORCE ROW LEVEL SECURITY` y políticas en toda tabla con `tenant_id` o `prestador_id`, trigger `acma_version()` y alta en `TABLAS_VERSIONADAS`. La prueba `test_toda_tabla_con_tenant_o_prestador_tiene_rls_forzada` debe seguir pasando.

Tablas (propietario según §6.3):

| Tabla | Propietario | Campos clave |
|---|---|---|
| `habilidades` | Prestador | prestador_id, clave, nombre, descripcion, activa |
| `tecnicos` | Prestador | usuario_id (FK usuarios, rol `tecnico`, único), prestador_id, numero_empleado, telefono, vehiculo_placas, estado (`activo`/`inactivo`/`baja`), fecha_ingreso |
| `tecnico_habilidades` | Prestador | tecnico_id, habilidad_id, certificada (bool), fecha_certificacion, vigencia_hasta (nullable), origen (`manual`/`curso`) — el origen `curso` lo usará Capacitación en Fase 2 |
| `tecnico_tenants_habilitados` (§6.10.8) | Prestador | tecnico_id, tenant_id, habilitado_por, fecha_habilitacion, activo |
| `niveles_severidad` | Prestador | prestador_id, clave, nombre, orden (1 = muy baja … 5 = crítica), color_hex, tiempo_respuesta_horas, tiempo_resolucion_horas, activo |
| `familias_equipo` | Plataforma (Superadmin) + Tenant | tenant_id (nullable: NULL = global de plataforma), nombre, descripcion, activa |
| `tipos_equipo` | Plataforma + Tenant | familia_id, tenant_id (nullable, misma regla), nombre, descripcion, activa |
| `equipos` | Tenant | tenant_id, un_id, tipo_equipo_id, codigo (único por tenant), nombre, marca, modelo, numero_serie, fecha_instalacion, valor_reposicion (nullable), estado (`activo`/`inactivo`/`baja`), garantia_vigente_hasta (nullable), contrato_id (nullable; cobertura contractual), notas |
| `tipos_falla` (§6.8.6) | Prestador; flag por Superadmin | prestador_id, descripcion, familia_equipo_id, requiere_revision_manual (bool, solo Superadmin lo cambia), activa |
| `tipo_falla_severidad` (§6.8.6) | Tenant | tenant_id, tipo_falla_id, tipo_equipo_id, nivel_severidad_id, configurado_por, activa; UNIQUE(tenant_id, tipo_falla_id, tipo_equipo_id) |
| `importaciones_catalogo` | Tenant o Prestador | catalogo, archivo_nombre, archivo_key (MinIO), total_filas, filas_ok, filas_error, errores_json, estado (`vista_previa`/`confirmada`/`cancelada`), ejecutada_por |

Reglas de datos:
- Un equipo "tiene contrato activo" cuando `equipos.contrato_id` apunta a un contrato vigente entre su tenant y un prestador, o cuando `contrato_id` es NULL y existe un contrato vigente del tenant que cubra todas sus UNs (campo `cobertura` = `todas_las_un`; agrégalo a `contratos` si no existe). Expón esta regla como función SQL `acma_equipo_con_contrato_activo(equipo_id)` y como servicio Python; P04 la usará para el selector filtrado y la validación de captura.
- `niveles_severidad` se siembra con los 5 niveles de §6.10.1 (muy baja, baja, media, alta, crítica) al crear un prestador, y se vincula con `contrato_sla` por `nivel_severidad_id`. Registra en `CONTEXTO.md` la decisión: §6.3 muestra 3 niveles de ejemplo (Crítico/Urgente/Normal), pero §6.10.1 y §4.1 fijan 5; se siguen los 5.
- Familias y tipos de equipo globales (tenant_id NULL) son visibles para todos los tenants y solo los edita Superadmin; un tenant puede agregar los suyos. Política RLS: `tenant_id IS NULL OR acma_tenant_visible(tenant_id)`.

### 2. Servicios y endpoints (prefijo `/api/catalogos`)

Usar `ActorActual`, `requiere_rol`, `validar_tenant` / `validar_prestador`, `ErrorAPI` y `auditoria.registrar_actor` en toda escritura, como en P01.

- `habilidades`, `tecnicos`, `tecnicos/{id}/habilidades`, `tecnicos/{id}/tenants` — Admin prestador (escritura), Mesa de control y Despachador (lectura). Al crear un técnico se crea o vincula su usuario con rol `tecnico`.
- `tecnicos/{id}/grupo` y `tecnicos/{id}/permisos` — endpoints de las tablas `grupos_tecnicos`, `grupo_tecnico_permisos`, `tecnico_grupo` y `tecnico_permisos_override` que P01 dejó sin endpoints. Incluir `GET /tecnicos/{id}/permisos-efectivos` (grupo + override) usando `services/permisos_service.py`.
- `severidades` — Admin prestador.
- `familias-equipo`, `tipos-equipo` — Superadmin (globales) y Admin empresa (propios). `GET /tipos-equipo?familia_id=` para la cascada de §4.3.
- `equipos` — Admin empresa y Admin UN (solo sus UNs); `GET /equipos?un_id=&con_contrato=true` devuelve únicamente equipos con contrato activo (selector filtrado de §6.8.6); Técnico y Despachador lectura.
- `tipos-falla` — Admin prestador; el campo `requiere_revision_manual` solo lo acepta Superadmin (403 en otro caso). `GET /tipos-falla?familia_id=` para la cascada.
- `matriz-severidad` — Admin empresa: GET en forma de matriz (filas tipo de falla, columnas tipo de equipo), PUT por celda y PUT masivo. `GET /matriz-severidad/resolver?tipo_falla_id=&tipo_equipo_id=` devuelve el nivel o 404 `SEVERIDAD_NO_CONFIGURADA`; P04 lo consume.
- Alerta nueva registrada con `@registrar_evaluador("MATRIZ_SEVERIDAD_INCOMPLETA")`: combinaciones tipo de falla × tipo de equipo en uso por el tenant sin severidad configurada. Agregar la clave a `alertas_catalogo` en la migración.

### 3. Importador CSV/Excel (§6.3, ACT-1.3)

Flujo en dos pasos: `POST /api/catalogos/importar/{catalogo}` con el archivo → vista previa con filas válidas, filas con error (número de fila, columna, motivo) y duplicados detectados; `POST /api/catalogos/importar/{id}/confirmar` aplica solo las filas válidas; `POST .../cancelar`. Catálogos soportados: `tecnicos`, `unidades_negocio`, `severidades`, `familias_equipo`, `tipos_equipo`, `tipos_falla`, `equipos`, `matriz_severidad`. Para cada uno, `GET /api/catalogos/importar/{catalogo}/plantilla` descarga una plantilla Excel con las columnas requeridas y una fila de ejemplo. Lectura con openpyxl y csv; límite 10,000 filas; el archivo se guarda en MinIO con `obtener_almacenamiento()`.

### 4. Frontend

- Módulo `catalogos` (ya definido en `src/config/modulos.ts`, prompt P02): agregar `ruta`, la página en `PAGINAS` de `App.tsx` y confirmar roles: Superadmin, Admin prestador, Admin empresa, Admin UN (solo equipos de sus UNs), Mesa de control y Despachador (lectura).
- Página `pages/catalogos/Catalogos.tsx` con pestañas: Técnicos (ficha, habilidades, grupo y permisos efectivos, tenants habilitados), Severidades, Familias y tipos de equipo, Equipos (filtro por UN, indicador de contrato activo y garantía), Tipos de falla, Matriz de severidad (cuadrícula editable con color del nivel), Importar (subir archivo → vista previa con errores → confirmar).
- Cada pestaña se muestra solo a los roles con permiso, usando `useRecurso` para listados y `ui.tsx` para los componentes.
- Buscador por texto en Técnicos y Equipos (§6.3: el operador escribe 3 letras y selecciona); el componente de búsqueda debe ser reutilizable por P04.

### 5. Seed y pruebas

- `scripts/seed_dev.py`: agregar 5 habilidades, 4 técnicos con habilidades (2 de ellos usuarios `tecnico` ya existentes), 5 niveles de severidad para el prestador demo, 3 familias globales con 2 tipos de equipo cada una, 12 equipos repartidos en las 3 UNs (2 sin contrato activo, 1 en garantía), 8 tipos de falla y la matriz de severidad completa para el tenant demo.
- Pruebas backend (`tests/test_catalogos.py`, `tests/test_importador.py`, `tests/test_matriz_severidad.py`): CRUD por rol (403 en roles sin permiso), aislamiento entre tenants y entre prestadores, `requiere_revision_manual` solo Superadmin, `acma_equipo_con_contrato_activo` en los cuatro casos (contrato propio vigente, contrato de cobertura total, contrato vencido, sin contrato), `resolver` de matriz con y sin configuración, importación con filas válidas, con errores y con duplicados, plantillas descargables, permisos efectivos de técnico (grupo + override).
- Pruebas frontend: pestañas visibles por rol, edición de una celda de la matriz, flujo de importación con vista previa.
- `pytest`, `vitest`, `tsc --noEmit` y `npm run build` en verde.

## Reglas (de P01, vigentes)

1. Seguir el Documento de Diseño v2.5; cualquier elección no definida se anota en `CONTEXTO.md` como decisión pendiente de validación.
2. Multitenancy validado en servicio además de RLS.
3. Sin proveedores externos de pago.
4. Identificadores en español sin acentos.
5. Cerrar con `CONTEXTO.md` (avance P02 ✅, arquitectura vigente ampliada con los catálogos y la función de contrato activo) y `BITACORA.md` actualizados.
6. No cambiar el stack.

## Al terminar

Resumen en español con: tablas de la migración 0002, endpoints, catálogos del importador y sus columnas, usuarios/datos nuevos del seed y conteo de pruebas.
