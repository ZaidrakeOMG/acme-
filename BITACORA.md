# BITÁCORA — ACMA (desarrollo nuevo)

Registro por fecha de lo realizado en cada prompt.

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
