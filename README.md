# ACMA — Sistema Integral de Gestión de Mantenimiento

> **Nueva rama de pruebas Supabase sin Docker**: para probar primero la **web original React + FastAPI**
> con la base Supabase en el esquema privado acma, leer
> [docs/PRIMERA_PRUEBA_WEB_SUPABASE.md](docs/PRIMERA_PRUEBA_WEB_SUPABASE.md).
> El proceso es: crear el bucket privado con
> [docs/01_CREAR_BUCKET_PRIVADO_ACMA.sql](docs/01_CREAR_BUCKET_PRIVADO_ACMA.sql),
> instalar Python 3.12 + Node.js 22+, ejecutar **PROBAR_ACMA_WEB.bat** desde Windows.
> El asistente local configura PostgreSQL como acma_api, JWT, cifrado, Storage y el primer
> superadmin con contraseña temporal aleatoria. No sube secretos ni datos de demostración.
> Si se interrumpe el alta del usuario, ejecutar **CREAR_ADMIN_ACMA.bat**.
> **Este modo no inicia Redis/Celery**, por lo que no valida tareas automáticas;
> para todo el sistema usar infraestructura remota y el lanzador completo.
> Las instrucciones Docker de abajo son exclusivamente del despliegue ORIGINAL.

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
| Producción | Docker Compose: Caddy (HTTPS automático), gunicorn + uvicorn, Celery, PostgreSQL, Redis, MinIO |

## Dónde está cada cosa

| Si busca… | Lea |
|---|---|
| Qué hay hecho, qué se decidió y por qué | [`CONTEXTO.md`](CONTEXTO.md) |
| Qué se hizo cada día | [`BITACORA.md`](BITACORA.md) |
| **Decisiones que el negocio debe confirmar** | [`docs/decisiones_para_validar.md`](docs/decisiones_para_validar.md) |
| Cómo publicar en un servidor nuevo, actualizar y revertir | [`docs/operacion/despliegue.md`](docs/operacion/despliegue.md) |
| Qué revisar cada día en producción | [`docs/operacion/monitoreo.md`](docs/operacion/monitoreo.md) |
| Respaldos, restauración y qué hacer si se pierde el servidor | [`docs/operacion/recuperacion_desastres.md`](docs/operacion/recuperacion_desastres.md) |
| Estado de cada requisito de seguridad ISO 27001 | [`docs/seguridad/checklist_iso27001.md`](docs/seguridad/checklist_iso27001.md) |
| Cuánta carga aguanta y qué servidor hace falta | [`docs/rendimiento/resultados.md`](docs/rendimiento/resultados.md) |
| Cómo medir la carga otra vez | [`backend/pruebas_carga/README.md`](backend/pruebas_carga/README.md) |
| Contrato de los 22 tipos de campo de formularios | [`docs/formularios/tipos_de_campo.md`](docs/formularios/tipos_de_campo.md) |
| Qué significa cada indicador de BI | [`docs/bi/indicadores.md`](docs/bi/indicadores.md) |

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
# Beat de Celery (evaluar_alertas y evaluar_timeouts_aprobacion cada 60 s, particiones de auditoría diarias, purga de sesiones)
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
| tecnico | tecnico1@acma.dev … tecnico4@acma.dev (con habilidades) |
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
  README.md, CONTEXTO.md, BITACORA.md
  docker-compose.yml                desarrollo (PostgreSQL + PostGIS, Redis, MinIO)
  docker-compose.prod.yml           produccion (Caddy, API, Celery, PostgreSQL, Redis, MinIO)
  .env.example, .env.production.example
  docker/postgres/01_roles.sh       roles y bases (init de PostgreSQL)
  docker/Caddyfile                  proxy inverso, HTTPS y cabeceras de la PWA
  scripts/respaldo.sh               respaldo diario verificado, con rotacion y copia remota
  scripts/restaurar.sh              restauracion con cotejo de conteos
  docs/
    decisiones_para_validar.md      preguntas para el negocio
    operacion/                      despliegue, monitoreo, recuperacion de desastres
    seguridad/checklist_iso27001.md
    rendimiento/resultados.md
    formularios/, bi/, prompts/
  backend/
    Dockerfile                      imagen de la API y de los workers (multietapa, sin root)
    main.py                         app FastAPI
    core/                           config, db, rls, security, cookies, errors, middleware,
                                    dependencias, observabilidad, sql_migracion
    models/  schemas/  routers/  services/
    workers/                        celery_app.py y tareas/
    alembic/versions/               0001_cimientos.py … 0012_indices_rendimiento.py
    scripts/                        seed_dev.py, seed_produccion.py, generar_secretos.py, generar_vapid.py, …
    pruebas_carga/                  Locust: preparar.py, locustfile.py
    tests/
  frontend/
    Dockerfile                      compila la PWA y la sirve con Caddy
    src/ (components, pages, hooks, services, contexts, types, config)
    public/  tests/
```

## Catálogos maestros (P02)

Tarjeta **Catálogos maestros** del hub: técnicos y habilidades, severidades, familias y tipos de equipo, equipos por UN (con
indicador de contrato activo y garantía), tipos de falla, matriz de severidad e **importador CSV/Excel**. Para importar:
descarga la plantilla del catálogo, llénala, súbela, revisa la vista previa (errores por fila y duplicados) y confirma.

## Formularios dinámicos (P03)

Tarjeta **Formularios dinámicos** (superadmin, admin prestador y mesa de control): constructor visual con los 22 tipos de
campo, plantillas base, versiones y asignaciones. Tarjeta **Mis formularios** (cualquier rol): llenar los formularios
dirigidos a tu rol, reanudar en progreso y consultar enviados. Contrato de los tipos: `docs/formularios/tipos_de_campo.md`.

## Folios (P04)

Tarjeta **Folios** (todos los roles operativos): captura con validaciones automáticas de §6.8.6 (UN confirmada, contrato
activo, duplicado, severidad por matriz, garantía, flag del tipo de falla, horario del contrato y palabras clave), ciclo de
vida de 11 estados con acciones según rol, y **Aprobaciones** para Admin UN, Supervisor de operadores y Admin empresa
(Aprobar / Rechazar con razón → módulo de seguimiento). El Admin empresa configura umbrales, reglas y niveles en la misma
pantalla. Los 15 folios demo tienen prefijo `CD-`.

## Apps de campo, offline y chat (P05)

Tarjeta **App de campo y chat** (`/campo`): el operador y el Admin UN ven los folios de su unidad, capturan (también sin
señal), firman la orden de servicio y contestan la encuesta; el técnico atiende sus folios con el formulario de atención,
fotos, refacciones y las acciones del ciclo de vida. Todo lo hecho sin conexión se encola en IndexedDB y se ve en
**Pendientes de sincronizar** (indicador en la cabecera). El chat del folio (tres canales) está en el detalle del folio y
en las apps de campo, con tiempo real por WebSocket (fallback SSE). Para las notificaciones push genera claves VAPID con
`.\.venv\Scripts\python -m scripts.generar_vapid` y pégalas en `.env`; sin ellas el envío solo se registra en el log.

## Preventivos y reasignaciones (P06)

Tarjeta **Preventivos y planes** (`/preventivos/calendario`): el prestador carga el calendario del mes (fila por fila o
importando el catálogo `calendario_preventivos`), lo publica (aviso al Admin empresa y Admin UN) y ve el desvío literal de
cada preventivo («realizado con 2 días de retraso»). En **Planes** define triggers de tiempo fijo o calendario (los de
Fase 2 aparecen deshabilitados), tareas con habilidad requerida, materiales y equipos; la tarea nocturna
(`acma.generar_preventivos_programados`, 02:00) o el botón «Generar folios ahora» crean los folios preventivos directo en
Autorizado. Reprogramar o cancelar un preventivo pasa por **Autorizaciones** (Admin UN / Admin empresa). Tarjeta
**Reasignaciones** (`/reasignaciones/reporte`): causas por período y catálogo de razones; la reasignación forzada se hace
desde el detalle del folio con el botón **Reasignar** (habilidad = restricción dura, advertencias con confirmación).

## Minuta del día, notificaciones y seguimiento (P07)

Tarjeta **Minuta del día** (`/minutas`): al cierre de jornada ACMA genera una minuta por UN y una global (estatus de los cuatro
módulos, preventivos con desvío, hallazgos, cotizaciones, peticiones) y la entrega por correo con PDF, push y la bandeja. El
despachador puede validarla (ventana de 30 minutos) y el Admin UN responde cada hallazgo con una de seis opciones. Tarjeta
**Seguimiento** (`/seguimiento`): Cotizaciones, Por presupuesto, Seguimiento interno y Reprogramación con listado, Kanban, vista
por UN y reporte ejecutivo (Excel/PDF). Tarjeta **Folios no críticos** (`/clasificacion`): el Admin UN clasifica en plazo y el
Admin empresa ve su calificación. **Notificaciones** (campana): bandeja y preferencias de canal por evento.

Correo saliente: deja `SMTP_HOST` vacío para el modo *stub* (los `.eml` quedan en MinIO bajo `correo/`) o configura
`SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` y `SMTP_TLS` (correo corporativo o SendGrid por SMTP).
`APP_URL_PUBLICA` es la base de los enlaces. Para PDF con diseño instala el runtime GTK3 (WeasyPrint); sin él se genera un PDF
mínimo de texto.

## Trabajos especiales y OC de activos (P08)

- `/trabajos-especiales`: el prestador (Admin prestador, Mesa de control, Despachador) crea el TE —o lo convierte desde una cotización
  autorizada en `/seguimiento`—, lo envía al cliente y, aceptado, lo programa con técnicos que tengan `ejecutar_trabajos_especiales`; el
  cliente (Admin empresa / Admin UN) lo acepta o rechaza con comentario desde la bandeja «Por validar» y puede crear TE de urgencia
  sin monto. Al programarse se crea el folio operativo `especial` que el técnico atiende en `/campo` con el formulario del TE; el cierre
  exige formulario, evidencia fotográfica y firma.
- `/oc-activos`: folios clasificados como instalación de activo en el formulario (`clasifica_instalacion_activo`) esperan la OC del
  cliente; el Admin empresa registra el estatus y el número de OC; con la OC autorizada el folio entra al flujo de asignación y al
  cerrarse el equipo se da de alta en el catálogo (`ACT-<folio>`).
- Datos demo: TE-000001 … TE-000008 y folios CD-000038 … CD-000041 (`scripts/seed_trabajos_especiales.py`).

## Inventario, costos y activos (P09)

Los tres orígenes de refacción de §6.4: existencias del almacén y del vehículo de cada técnico con costo promedio ponderado,
orden de compra cuando la refacción no está en inventario y compra directa en refaccionaria pagada con caja chica. El gasto de
caja chica se captura con la foto de la factura desde la atención del folio y el Admin prestador lo aprueba en un toque: eso da
de alta la refacción, mueve el inventario y carga al fondo del técnico. Al cerrar un folio se calcula su costo (refacciones más
horas por la tarifa vigente) y al validarlo se carga a los presupuestos de la UN, de sus grupos y del tipo de actividad, con
tablero consolidado y semáforo. La ficha de cada equipo reúne historial, refacciones, depreciación (cuatro métodos) y costo total
de propiedad, y recomienda el reemplazo cuando el TCO supera el porcentaje configurado de su valor de reposición. La integración
con ERPs es una capa desacoplada: ACMA genera eventos en su formato interno y, en Fase 1, el contador descarga la exportación
universal en XML de pólizas o Excel configurable.

| Módulo | Ruta | Quién entra |
|---|---|---|
| Inventario | `/inventario` | Admin prestador, despachador, mesa de control, técnico (su vehículo) |
| Caja chica | `/caja-chica` | Admin prestador (aprueba), técnico (captura) |
| Presupuestos | `/presupuestos` | Admin empresa (alta), Admin UN y supervisores (lectura) |
| Equipos y activos | `/activos` | Admin empresa, Admin UN, prestador |
| Integración ERP | `/erp` | Admin prestador, dirección, mesa de control |


## Contratos y SLA, alertas y BI (P10)

Cada contrato mide su cumplimiento: el contador de SLA corre desde la captura del folio, se pausa en la reasignación y
mientras se esperan datos del operador, descuenta las exclusiones que el prestador registra y el Admin empresa aprueba, y
al cerrar calcula si se atendió dentro del tiempo pactado y cuánto se penaliza. Las penalizaciones se consolidan por mes
y el Admin prestador las revisa y las cierra antes de facturar (el descuento en el CFDI llega en Fase 2). La modalidad
iguala lleva su propio control: correctivos y preventivos incluidos contra los atendidos, con los adicionales
identificados.

Todas las alertas del sistema se configuran en una sola pantalla: el Superadmin fija el valor por defecto y el rango, y
cada cliente y cada prestador ajustan su umbral, sus canales y sus roles destinatarios dentro de ese rango. Las que
dependen de datos de Fase 2 (GPS, medidores, certificaciones) se ven etiquetadas y no se pueden activar. Las escalaciones
a la Dirección del prestador se miden desde el momento en que se disparó la alerta operativa, no desde el hecho original.

Cada rol tiene su tablero: gasto contra presupuesto, cumplimiento de SLA, MTTR y MTBF y comparativos entre unidades,
grupos y períodos para el cliente; folios por cliente, penalizaciones, iguala, cotizaciones y carga por técnico para el
prestador; conteos y SLA en riesgo —sin montos ni detalle de folios— para el Supervisor de operadores; la barra de
jornada para el despachador; y los indicadores con el histórico de escalaciones para la Dirección. Los reportes
ejecutivos se descargan en PDF o Excel y se pueden programar por correo.

| Módulo | Ruta | Quién entra |
|---|---|---|
| Contratos y SLAs | `/contratos` | Admin prestador (configura), Admin empresa (aprueba exclusiones), mesa de control |
| Contador de SLA | `/contratos?vista=cumplimiento` | Prestador y cliente |
| Configuración de alertas | `/alertas` | Superadmin (defaults y rangos), Admin empresa, Admin prestador |
| Inteligencia de negocio | `/bi` | Todos los roles con tablero |
| Reportes ejecutivos | `/bi/reportes` | Admin empresa, Admin prestador, supervisores |


## Seguridad y sesiones (P11a)

La sesión vive en una cookie `httpOnly` con ruta limitada a `/api/auth` y protección CSRF de doble envío; el token de
acceso solo existe en memoria del navegador, así que recargar sin red **no** cierra la sesión (el modo offline de P05
sigue funcionando). La sesión dura 8 horas — 2 para los roles administrativos — y se cierra a los 30 minutos sin uso.
La contraseña de los roles administrativos vence a los 90 días: al entrar, ACMA exige cambiarla antes de abrir
cualquier módulo. Hay restablecimiento por correo con un enlace de un solo uso que vence en 30 minutos.

Los archivos del Object Storage se guardan **cifrados** (AES-256-GCM) con una llave derivada para cada cliente o
prestador; la ruta del objeto va firmada, así que un archivo no se puede mover al expediente de otro cliente. Las
columnas sensibles (secreto MFA, datos fiscales) ya se cifraban desde P01.

La bitácora de accesos a la API se conserva 90 días y los errores un año; la purga suelta particiones completas, nunca
borra filas, para no tocar la auditoría. El estado de cada requisito está en
[`docs/seguridad/checklist_iso27001.md`](docs/seguridad/checklist_iso27001.md).

## Producción

Todo el despliegue es un `docker-compose.prod.yml`: Caddy con HTTPS automático sirviendo la PWA y haciendo de proxy,
la API con gunicorn y varios workers de uvicorn, el worker y el beat de Celery, PostgreSQL 16 + PostGIS, Redis con
contraseña y MinIO. Las migraciones corren en un servicio de una sola ejecución y la API no arranca hasta que
terminan bien.

```bash
cp .env.production.example .env   # y rellenar cada <...>
```

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

Antes de eso hay que generar los secretos; el backend **se niega a arrancar** si alguno conserva un valor de ejemplo,
si falta el dominio en `CORS_ORIGENES` o si `APP_URL_PUBLICA` no es https:

```bash
cd backend && .venv/Scripts/python -m scripts.generar_secretos --compose
```

Y sembrar el superadmin inicial, que entra con una contraseña temporal y debe cambiarla de inmediato:

```bash
docker compose -f docker-compose.prod.yml run --rm api python -m scripts.seed_produccion --email admin@cliente.com --nombre "Nombre Apellido"
```

Pasos completos para un servidor nuevo, actualización y reversión:
[`docs/operacion/despliegue.md`](docs/operacion/despliegue.md). Respaldo diario y restauración:
`scripts/respaldo.sh` y `scripts/restaurar.sh`, documentados en
[`docs/operacion/recuperacion_desastres.md`](docs/operacion/recuperacion_desastres.md).

## Problemas conocidos en Windows

- **Docker Desktop no arranca** y el log menciona `remove …\dockerInference` o `…\engine.sock`: quedaron sockets huérfanos.
  Cierra Docker Desktop, renombra `%LOCALAPPDATA%\Docker\run` (y `%LOCALAPPDATA%\docker-secrets-engine` si aparece) y vuelve
  a abrirlo. No uses "Reset to factory defaults": borra los volúmenes de todos los proyectos.
- **`DLL load failed … Control de aplicaciones`** al importar asyncpg: el Control de aplicaciones de Windows bloquea asyncpg
  0.32. `requirements.txt` fija la 0.31.0.

## Migración opcional sin Docker y Android/iPhone

Se trabaja **sin reemplazar este sistema** en la rama de desarrollo `migracion-supabase-segura-20261115`. El React original permanece intacto y el build puede ser servido por FastAPI. La base móvil Flutter conserva temporalmente la UI React mediante WebView mientras se verifica paridad pantalla por pantalla; todavía NO es una conversión nativa completa ni un despliegue validado en Supabase.

- [Alcance y reglas de preservación de funciones](docs/migracion_supabase_flutter.md)
- [Proyecto Flutter Android/iOS y manual](mobile_flutter/README.md)
- `iniciar_acma_sin_docker.bat` solo funciona una vez migradas y configuradas las dependencias remotas de ACMA.

**Nunca conectar a la nube usando credenciales de otra aplicación; no subir claves a Git.**
