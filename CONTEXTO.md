# CONTEXTO — Estado del proyecto ACMA (desarrollo nuevo)

> Se actualiza al cierre de cada prompt. Última actualización: **2026-10-19 · P01 Cimientos**.

## Ubicación y relación con acma-proyecto

- Este repositorio (`C:\Users\lilia\Desktop\acma`) es el **desarrollo nuevo desde cero** definido en
  `ACMA_Alcance_Fases_v1.0.docx` (11 prompts de Fase 1).
- `C:\Users\lilia\Desktop\acma-proyecto` es la implementación anterior. **No se toca.** Ambos conviven: este proyecto usa
  puertos y contenedores distintos (`acma_nuevo_*`, PostgreSQL 5442, Redis 6389, MinIO 9010/9011).

## Avance por prompt

| Prompt | Contenido | Estado |
|---|---|---|
| P01 | Cimientos: repo, Docker, modelo base, RLS, auth + MFA, API base, PWA con login y hub | ✅ 2026-10-19 |
| P02 | Catálogos maestros (técnicos y habilidades, equipos, fallas, severidades, importador) | Pendiente |
| P03 | Motor de formularios | Pendiente |
| P04 | Folios | Pendiente |
| P05 | Apps PWA operador/técnico, offline y chat | Pendiente |
| P06 | Preventivos y reasignación forzada | Pendiente |
| P07 | Minuta y seguimiento | Pendiente |
| P08 | Trabajos especiales y OC | Pendiente |
| P09 | Inventario, caja chica manual, presupuestos y activos | Pendiente |
| P10 | Contratos/SLA (contador), alertas por módulo y BI | Pendiente |
| P11 | Endurecimiento y despliegue | Pendiente |

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

## Notas de entorno (esta máquina)

- Python 3.12 instalado con `py install 3.12`; el venv vive en `backend/.venv`.
- asyncpg fijado en 0.31.0: la 0.32 la bloquea el Control de aplicaciones de Windows.
- Node 25 trae un `localStorage` experimental que tapa el de jsdom; `frontend/tests/setup.ts` instala uno en memoria.
- 2026-10-19: Docker Desktop no arrancaba por sockets huérfanos; se renombraron `%LOCALAPPDATA%\Docker\run` y
  `%LOCALAPPDATA%\docker-secrets-engine` (copias `*.viejo-20261019`, se pueden borrar).
