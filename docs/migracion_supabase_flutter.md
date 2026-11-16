# ACMA — Migración conservadora a Supabase + Flutter

**ESTADO: rama experimental; NO LISTA para fusionar, instalar en producción ni cambiar la base.** La rama `main` es la versión de referencia y no se debe reescribir ni borrar.

## Inventario mínimo del repositorio original (rama main, 15-11-2026)

- 590 archivos fuente y recursos rastreados.
- 80 páginas React/TSX en `frontend/src/pages/`.
- 40 módulos de routers FastAPI.
- 18 migraciones Alembic (`0001` a `0018`).
- 10 módulos de tareas Celery bajo `backend/workers/tareas/`.
- 126 archivos de pruebas localizados por nombre/ruta.

El inventario de conteos **no es un análisis funcional exhaustivo**. Las firmas de API, capacidades por rol, permisos, eventos, datos y pantallas deben compararse antes de sustituir módulos.

## Diseño inalterable durante la migración

- React, sus CSS, imágenes, iconos, rutas, formularios y componentes se conservan.
- FastAPI conserva endpoints, autenticación personalizada, MFA, RLS, bitácora y reglas.
- Se sirve el build `frontend/dist` desde el mismo FastAPI en producción. No modifica la interfaz.
- Flutter comienza con WebView para conservar visualmente la aplicación; reescritura nativa futura por módulo. Nuevos estados Flutter solo usan Material Icons, sin emojis.
- Mantener original y respaldo por separado; no modificar `main` hasta completar tests y paridad.
- La migración de datos y política RLS se ensaya primero en un proyecto Supabase **exclusivo** de ACMA; nunca en Party-book o proyectos preexistentes.
- No se guardan claves `service_role` / `sb_secret_` en `frontend`, Flutter, GitHub ni aplicaciones distribuidas.

## Componentes de infraestructura

| Actual | Objetivo | Estado |
| --- | --- | --- |
| PostgreSQL/PostGIS Docker | Supabase PostgreSQL/PostGIS, con roles específicos | Pendiente: revisar 18 migraciones, RLS y roles antes de ejecutar |
| MinIO (archivos cifrados) | Supabase Storage bucket PRIVADO, preservando cifrado AES-256-GCM | Adaptador opcional añadido; migración real pendiente |
| Redis Pub/Sub / WebSockets | Realtime y/o transporte Python alojado, conservando rutas | Pendiente |
| Celery worker/beat | Cron / Queues + workers Python alojados para tareas pesadas | Pendiente |
| FastAPI Uvicorn | Servidor Python sin Docker en PC o hosting externo | Entrada de frontend integrada; despliegue pendiente |
| React/Vite | React compilado en FastAPI | Integración de rutas añadida; build/validación pendiente |
| Android/iOS | App Flutter híbrida que conserve React y avance a nativo | Base creada; pruebas móviles pendientes |

### Punto delicado: RLS multitenant

El sistema usa `SET LOCAL` / `set_config('app.tenant_id', ..., true)` y roles `acma_owner`, `acma_api`, `acma_auth`. Algunas funciones `SECURITY DEFINER` y permisos de los roles implican elevación de privilegios; no es seguro reutilizar `postgres` ni la clave `service_role` como usuario normal del backend. Las migraciones de la versión actual crean roles y operan sobre el esquema público, que Supabase expone potencialmente por su Data API.

Migrar significa **auditar funciones, esquemas, roles, permisos, RLS, PostGIS, particiones y direct SQL**, y después ejecutar todo en un proyecto de prueba vacío; no basta con apuntar `DATABASE_URL` a Supabase. No ejecutar `alembic upgrade head` contra un proyecto existente sin esta auditoría.

### Trabajos pendientes imprescindibles

1. Crear proyecto Supabase ACMA aislado y confirmar costo y acceso antes de crear nada.
2. Respaldar bases y archivos originales; registrar checksums de objetos y guardar llaves.
3. Preparar migración de roles/seguridad y 18 esquemas Alembic compatibles; ejecutar y auditar en base temporal.
4. Migrar datos, referencias, adjuntos cifrados e historial conservando identificadores UUID; verificar conteos.
5. Migrar tareas, cola, avisos, SQL scheduled, rutas VRPTW, archivos, Push, realtime.
6. Tests React original y tests de API, aislamiento multitenant, 22 tipos de formularios, importación Excel, exportación Excel/PDF, informes, offline y GPS.
7. Compilar Flutter Android/iPhone y comparar todas las pantallas en dispositivo real. No llamar «igual funcional» a una WebView hasta pasar pruebas de hardware.
8. Cortar tráfico solo con aprobación y plan reversible.

## Usar frontend integrado sin cambiar su diseño

```powershell
cd frontend
npm ci
npm run build
cd ../backend
python -m uvicorn main:app --port 8000
```

El frontend compilado se ve en `http://localhost:8000`. **Requiere** backend, PostgreSQL y los demás servicios configurados; esos comandos no reemplazan la infraestructura por sí solos.

## Seguridad

El adaptador `AlmacenamientoSupabase` recibe bytes ya cifrados por `AlmacenamientoCifrado`; el bucket queda privado. No ejecutar cambios en tablas `auth` o `storage` de un proyecto existente. La API de archivos y permisos se mantiene en FastAPI. Conservar `CLAVE_CIFRADO` original para que los datos históricos sigan siendo descifrables.

## Criterio de salida

Solo marcar un módulo «migrado» tras demostrar **misma UI, mismos datos, mismo comportamiento, mismos roles, misma autorización y mismas salidas** en React y Android/iOS. Ninguna de esas garantías se ha validado aún en dispositivos reales.
