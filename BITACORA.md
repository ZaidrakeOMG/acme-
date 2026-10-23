# BITÁCORA — ACMA (desarrollo nuevo)

Registro por fecha de lo realizado en cada prompt.

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
