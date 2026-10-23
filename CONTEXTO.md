# CONTEXTO — Estado del proyecto ACMA (desarrollo nuevo)

> Se actualiza al cierre de cada prompt. Última actualización: **2026-10-23 · P02 Catálogos maestros**.

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
| P03 | Motor de formularios | Pendiente |
| P04 | Folios | Pendiente |
| P05 | Apps PWA operador/técnico, offline y chat | Pendiente |
| P06 | Preventivos y reasignación forzada | Pendiente |
| P07 | Minuta y seguimiento | Pendiente |
| P08 | Trabajos especiales y OC | Pendiente |
| P09 | Inventario, caja chica manual, presupuestos y activos | Pendiente |
| P10 | Contratos/SLA (contador), alertas por módulo y BI | Pendiente |
| P11 | Endurecimiento y despliegue | Pendiente |

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
19. **Catálogos en lectura para técnico, despachador y mesa de control** (equipos, tipos de falla, familias) para preparar
    P04; el hub muestra el módulo también a admin_un, mesa de control y despachador.

## Notas de entorno (esta máquina)

- Python 3.12 instalado con `py install 3.12`; el venv vive en `backend/.venv`.
- asyncpg fijado en 0.31.0: la 0.32 la bloquea el Control de aplicaciones de Windows.
- Node 25 trae un `localStorage` experimental que tapa el de jsdom; `frontend/tests/setup.ts` instala uno en memoria.
- 2026-10-19: Docker Desktop no arrancaba por sockets huérfanos; se renombraron `%LOCALAPPDATA%\Docker\run` y
  `%LOCALAPPDATA%\docker-secrets-engine` (copias `*.viejo-20261019`, se pueden borrar).
