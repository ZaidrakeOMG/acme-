# ACMA — Sistema Integral de Gestión de Mantenimiento

Plataforma SaaS multitenant que conecta empresas con múltiples unidades de negocio (tenants) con sus prestadores
de servicio de mantenimiento. Referencia obligatoria: `ACMA_Documento_Diseno_v2.5.docx`. Alcance por fases:
`ACMA_Alcance_Fases_v1.0.docx`. Estado del proyecto: [`CONTEXTO.md`](CONTEXTO.md). Registro de trabajo: [`BITACORA.md`](BITACORA.md).

| Capa | Tecnología |
|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2.0 async + asyncpg, Pydantic v2, Alembic, Celery + Redis, pyotp |
| Base de datos | PostgreSQL 16 + PostGIS, RLS multitenant fail-closed |
| Frontend | React 19 + TypeScript estricto + Vite, PWA (vite-plugin-pwa), Tailwind 4, react-router, react-hook-form + zod, Dexie |
| Archivos | MinIO (S3-compatible) en desarrollo |
| Pruebas | pytest + pytest-asyncio + httpx · vitest + testing-library |

## Requisitos en Windows

- Docker Desktop (motor Linux/WSL2).
- Python 3.12 — `py install 3.12` (Python install manager) o el instalador de python.org.
- Node.js 22 o superior (probado con 25.8) y npm.

Los puertos de este proyecto **no chocan con acma-proyecto**: PostgreSQL `5442`, Redis `6389`, MinIO `9010` (consola `9011`),
API `8000`, frontend `5173`.

## Puesta en marcha (PowerShell, desde la carpeta del repo)

### 1. Variables de entorno y servicios Docker

```powershell
cd $env:USERPROFILE\Desktop\acma
Copy-Item .env.example .env        # solo la primera vez; ajusta contraseñas si quieres
docker compose up -d
docker compose ps                  # postgres y redis deben aparecer "healthy"
```

La primera vez, `docker/postgres/01_roles.sh` crea los roles `acma_owner` (dueño del esquema, migraciones),
`acma_api` (aplicación, sin BYPASSRLS), `acma_auth` (NOLOGIN, dueño de las funciones de arranque de sesión) y las bases
`acma` y `acma_test`.

### 2. Backend (una sola vez: entorno virtual, migración y datos demo)

```powershell
cd $env:USERPROFILE\Desktop\acma\backend
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m alembic upgrade head
.\.venv\Scripts\python -m scripts.seed_dev
```

### 3. Levantar cada proceso (una terminal por proceso)

```powershell
# API  →  http://localhost:8000/docs
cd $env:USERPROFILE\Desktop\acma\backend
.\.venv\Scripts\python -m uvicorn main:app --port 8000
```

```powershell
# Worker de Celery (en Windows siempre --pool=solo)
cd $env:USERPROFILE\Desktop\acma\backend
.\.venv\Scripts\celery -A workers.celery_app worker --pool=solo -l info
```

```powershell
# Beat de Celery (evaluar_alertas cada 60 s, particiones de auditoría diarias, purga de sesiones)
cd $env:USERPROFILE\Desktop\acma\backend
.\.venv\Scripts\celery -A workers.celery_app beat -l info
```

```powershell
# Frontend  →  http://localhost:5173  (redirige /api al puerto 8000)
cd $env:USERPROFILE\Desktop\acma\frontend
npm install        # solo la primera vez
npm run dev
```

En Windows uvicorn se ejecuta **sin `--reload`** (convención heredada de acma-proyecto); reinícialo tras cambiar código.

## Usuarios de prueba

Contraseña de todos: `Demo#Acma2026`. En desarrollo `MFA_OBLIGATORIO=false`, así que los roles críticos entran sin MFA;
con `MFA_OBLIGATORIO=true` (pruebas y producción) el primer login pide enrolar la app autenticadora.

| Rol | Correo |
|---|---|
| superadmin | superadmin@acma.dev |
| admin_prestador | admin.prestador@acma.dev |
| direccion_prestador | direccion@acma.dev |
| mesa_control | mesa.control@acma.dev |
| despachador | despachador@acma.dev |
| supervisor_prestador | supervisor.prestador@acma.dev |
| tecnico | tecnico1@acma.dev, tecnico2@acma.dev |
| admin_empresa | admin.empresa@acma.dev |
| admin_un | admin.un@acma.dev (Sucursal Centro y Polanco) |
| supervisor_operadores | supervisor.operadores@acma.dev (grupo Zona Metropolitana) |
| operador | operador@acma.dev (Sucursal Centro) |

## Pruebas y verificaciones

```powershell
cd $env:USERPROFILE\Desktop\acma\backend
.\.venv\Scripts\python -m pytest            # recrea la base acma_test con Alembic en cada corrida
```

```powershell
cd $env:USERPROFILE\Desktop\acma\frontend
npm run typecheck                           # tsc --noEmit
npm test                                    # vitest
npm run build                               # tsc + vite build + service worker
```

## Estructura

```
acma/
  README.md, CONTEXTO.md, BITACORA.md, docker-compose.yml, .env.example
  docker/postgres/01_roles.sh       roles y bases (init de PostgreSQL)
  docs/prompts/                     prompts de desarrollo (P01…P11)
  backend/
    main.py                         app FastAPI
    core/                           config, db, rls, security, errors, middleware, dependencias
    models/  schemas/  routers/  services/
    workers/                        celery_app.py y tareas.py
    alembic/versions/0001_cimientos.py
    scripts/                        seed_dev.py, generar_secretos.py
    tests/
  frontend/
    src/ (components, pages, hooks, services, contexts, types, config)
    public/  tests/
```

## Problemas conocidos en Windows

- **Docker Desktop no arranca** y el log menciona `remove …\dockerInference` o `…\engine.sock`: quedaron sockets huérfanos.
  Cierra Docker Desktop, renombra `%LOCALAPPDATA%\Docker\run` (y `%LOCALAPPDATA%\docker-secrets-engine` si aparece) y vuelve
  a abrirlo. No uses "Reset to factory defaults": borra los volúmenes de todos los proyectos.
- **`DLL load failed … Control de aplicaciones`** al importar asyncpg: el Control de aplicaciones de Windows bloquea asyncpg
  0.32. `requirements.txt` fija la 0.31.0.
