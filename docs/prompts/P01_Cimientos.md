# P01 — Cimientos del proyecto ACMA (Fase 1, prompt 1 de 11)

## Contexto

Vas a construir desde cero el sistema ACMA, una plataforma SaaS multitenant de gestión de mantenimiento que conecta a empresas con múltiples unidades de negocio (tenants) con sus prestadores de servicio de mantenimiento. La referencia obligatoria es el archivo `ACMA_Documento_Diseno_v2.5.docx` en la raíz del repositorio; léelo completo antes de escribir código. El anexo `ACMA_Alcance_Fases_v1.0.docx` define qué módulos pertenecen a Fase 1 y cuáles a Fase 2; en este prompt solo se construyen los cimientos.

Este es el primero de 11 prompts secuenciales. No construyas módulos funcionales (folios, formularios, catálogos) todavía; construye la base sobre la que todos ellos se montarán.

## Stack (fijo, no se cambia sin discusión)

- Backend: Python 3.12, FastAPI, SQLAlchemy 2.0 async con asyncpg, Pydantic v2, Alembic para migraciones, Celery + Redis para tareas en background, pyotp para MFA.
- Base de datos: PostgreSQL 16 con PostGIS, RLS multitenant.
- Frontend: React 19 + TypeScript estricto + Vite, PWA con vite-plugin-pwa, Tailwind, react-router, react-hook-form + zod, Dexie para IndexedDB.
- Archivos: MinIO (S3-compatible) en desarrollo.
- Infraestructura dev: Docker Compose con PostgreSQL + PostGIS, Redis y MinIO.
- Pruebas: pytest + pytest-asyncio + httpx (backend), vitest + testing-library (frontend).

## Entregables de este prompt

### 1. Estructura del repositorio

```
acma/
  README.md                 (cómo levantar todo en Windows, comandos exactos)
  CONTEXTO.md               (estado del proyecto; se actualiza en cada prompt)
  BITACORA.md               (registro por fecha de lo realizado en cada prompt)
  docker-compose.yml
  .env.example
  backend/
    main.py, core/ (config, security, rls, errors), models/, schemas/, routers/, services/, workers/, alembic/, tests/, scripts/
  frontend/
    src/ (components, pages, hooks, services, contexts, types, config), public/, tests/
```

### 2. Modelo de datos base (Alembic migración 0001)

Crea solo las tablas que todos los módulos necesitan. Cada tabla crítica lleva `id UUID`, `created_at`, `updated_at` (TIMESTAMPTZ con índice) y `version_hash VARCHAR(64)` conforme a §6.2 capa 1.

- `tenants` (empresa cliente): razón social, RFC, país, moneda, zona horaria, estado.
- `prestadores`: razón social, RFC, país, datos fiscales, logo (key en MinIO).
- `tenant_prestador`: relación N:N con vigencia (un tenant puede tener más de un prestador y viceversa).
- `usuarios`: email único, hash de contraseña (argon2), nombre, teléfono, rol, dominio (`tenant` | `prestador` | `plataforma`), `tenant_id` o `prestador_id` según dominio, estado, MFA (secreto cifrado, habilitado, códigos de recuperación hasheados).
- `roles`: los 11 roles de §5 como ENUM: `superadmin`, `admin_prestador`, `direccion_prestador`, `mesa_control`, `despachador`, `supervisor_prestador`, `tecnico`, `admin_empresa`, `admin_un`, `supervisor_operadores`, `operador`.
- `permisos_tecnico` y `permisos_despachador`: permisos configurables de §6.8.3 y §6.8.3b, por prestador, con los valores por defecto del documento.
- `unidades_negocio` (UN): tenant, nombre, código, dirección, `ubicacion GEOGRAPHY(Point)` con PostGIS, zona horaria, estado, `grupo_id`.
- `grupos_un` (§6.8.5): tenant, nombre, descripción.
- `usuario_un`: asignación de operadores y supervisores a UNs.
- `contratos` (§6.10.1): tenant, prestador, vigencia, 5 niveles de severidad con tiempos de respuesta y resolución configurables (1 a 4,320 horas), penalización y calificación. Solo la estructura; la lógica del contador de SLA llega en P10.
- `alertas_catalogo` y `alertas_historial` (§6.9.6): tipo, umbral por tenant y por prestador, canal, estado, supresiones temporales. Cargar los 20 tipos de alerta del documento como catálogo semilla aunque su lógica se implemente en los prompts siguientes.
- `audit_log` particionada por mes, append-only mediante triggers `BEFORE UPDATE/DELETE` que lanzan excepción (§6.9.5); `audit_accesos_api` para accesos a la API.
- `sesiones`: refresh tokens rotativos con detección de reúso, dispositivo, IP, expiración.
- `configuracion_tenant` y `configuracion_prestador`: clave-valor JSON para parámetros sin tabla propia.

Campos previstos para Fase 2 que se crean ahora aunque no se usen: `usuarios.habilidades` se resuelve en P02; `unidades_negocio.ubicacion` ya incluida; `DATABASE_READ_URL` como variable de entorno opcional (si está vacía se usa `DATABASE_URL`).

### 3. Seguridad multitenant (RLS fail-closed)

- Toda tabla con `tenant_id` o `prestador_id` tiene RLS habilitado y forzado (`FORCE ROW LEVEL SECURITY`).
- Las políticas leen `current_setting('app.tenant_id', true)`, `current_setting('app.prestador_id', true)` y `current_setting('app.rol', true)`. **Si el contexto está vacío, la política no devuelve filas** (fail-closed). Nunca una política que permita todo por ausencia de contexto.
- La aplicación se conecta con el rol `acma_api`, sin `BYPASSRLS` y sin ser dueño de las tablas. Un middleware fija el contexto en cada request dentro de la transacción (`SET LOCAL`). Las tareas Celery y los scripts de seed fijan el contexto explícitamente.
- `superadmin` accede a todos los tenants mediante una política específica por rol, no por ausencia de contexto.
- Cifrado AES-256 en reposo para columnas sensibles (secreto MFA, datos fiscales) con clave en variable de entorno.

### 4. Autenticación y sesiones

- `POST /api/auth/login` (email + contraseña) → si el rol tiene MFA obligatorio (`superadmin`, `admin_prestador`, `admin_empresa`, `direccion_prestador`) devuelve un token temporal y exige `POST /api/auth/mfa/verify`.
- JWT de acceso de corta vida (15 min) + refresh token rotativo (7 días) con detección de reúso que invalida toda la familia de sesiones.
- Endpoints de MFA: setup (QR TOTP), verify, disable, regenerar códigos de recuperación.
- Rate limiting por IP y por usuario en login; bloqueo temporal tras intentos fallidos; registro en `audit_accesos_api`.
- Cabeceras de seguridad (CSP, HSTS, X-Frame-Options) y CORS por entorno.

### 5. API base

- Prefijo `/api`, versionado por cabecera no necesario en v1.
- Manejo de errores estándar: `{ "codigo": "...", "mensaje": "...", "detalles": [...] }`.
- Dependencias reutilizables: `usuario_actual`, `requiere_rol(*roles)`, `requiere_dominio(...)`.
- Routers de este prompt: `auth`, `usuarios`, `tenants`, `prestadores`, `unidades_negocio`, `grupos_un`, `contratos` (CRUD de estructura), `alertas` (catálogo y configuración de umbrales), `configuracion`, `auditoria` (solo lectura para superadmin).
- OpenAPI con descripción en español por endpoint.

### 6. Frontend base

- Login en dos pasos con MFA y códigos de recuperación; enrolamiento MFA.
- `AppShell` con barra lateral, cabecera con nombre y rol, y `RoleHub`: pantalla de inicio que muestra las tarjetas de los módulos que el rol puede ver según §5. Los módulos aún no construidos muestran "Disponible en el prompt Pxx" (no un error).
- Pantallas de administración de este prompt: usuarios, tenants, prestadores, UNs y grupos, contratos (estructura), configuración de alertas.
- Cliente HTTP con refresh automático de token (single-flight) y manejo del error estándar.
- PWA instalable con Service Worker básico (precache del shell). El modo offline completo llega en P05.
- Identidad visual: diseño limpio, tipografía del sistema, color primario configurable por prestador (default azul marino `#1C3D8F`, acento verde lima `#A2C62B`).

### 7. Tareas en background

- Celery app con Redis como broker y backend; beat configurado; una tarea de ejemplo `evaluar_alertas` que recorre `alertas_catalogo` cada 60 s y registra en `alertas_historial` (la lógica real de cada alerta llega con su módulo).
- Cada tarea abre su propia sesión de base de datos (no compartir el engine global entre tareas concurrentes) y fija el contexto RLS.

### 8. Datos iniciales y pruebas

- `scripts/seed_dev.py`: un prestador ("Prestador Demo"), un tenant ("Cliente Demo"), 3 UNs, 1 grupo, 1 contrato y 12 usuarios que cubran los 11 roles, con contraseñas en el script y MFA deshabilitado para dev.
- Pruebas backend: flujo completo de login + MFA + refresh + reúso detectado; aislamiento RLS (un usuario de un tenant no ve UNs de otro; contexto vacío devuelve cero filas); audit_log rechaza UPDATE y DELETE; permisos por rol en cada router.
- Pruebas frontend: login, enrolamiento MFA, hub por rol.
- `tsc --noEmit` limpio, `npm run build` verde, `pytest` verde.

## Reglas del proyecto (aplican a todos los prompts)

1. Seguir el Documento de Diseño v2.5 al pie de la letra; cuando algo no esté definido, elegir la opción más simple y anotarla en `CONTEXTO.md` como decisión pendiente de validación.
2. Multitenancy validado en cada endpoint y en cada servicio; nunca confiar solo en RLS ni solo en el ORM.
3. Nada de proveedores externos de pago en Fase 1; cualquier integración futura se deja detrás de una interfaz con implementación `stub`.
4. Nombres de tablas, columnas, endpoints y textos de interfaz en español, sin acentos en identificadores de código.
5. Toda tarea termina con pruebas en verde y con `CONTEXTO.md` y `BITACORA.md` actualizados.
6. No cambiar el stack sin discusión.

## Al terminar

Entrega un resumen en español con: estructura creada, tablas de la migración 0001, endpoints disponibles, usuarios de prueba y los comandos exactos para levantar Docker, backend, frontend, worker y beat en Windows.
