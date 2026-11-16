# Publicar ACMA para Web y APK Android con Railway + Supabase

## Arquitectura elegida

El repositorio existente ya tiene FastAPI capaz de servir `frontend/dist` desde `backend/core/frontend_integrado.py`.
El `Dockerfile` de la raíz compila el React original con Node 22 y ejecuta FastAPI con Python 3.12.
Así el mismo dominio HTTPS responde tanto `/` (React) como `/api/*` y `/ws/*` (FastAPI, websockets),
sin CORS entre dos dominios ni dependencia del equipo Windows del desarrollador.

Supabase **no se migra** ni se crea una base nueva: conservamos el esquema privado `acma`,
las credenciales de aplicación, el bucket privado y los usuarios con MFA actuales.
El Dockerfile no hace migraciones ni ejecuta scripts de creación de administradores.

Vercel puede hospedar un frontend estático, pero separar los orígenes implica tratar
cookies HttpOnly, CSRF, PWA, WebSockets y proxy. Este primer despliegue conserva el diseño
de un único origen seguro, que también utilizará Flutter WebView.

## 1. Crear el servicio web

1. Abre https://railway.com/ y conecta tu cuenta GitHub.
2. Crea un proyecto y elige **Deploy from GitHub Repo**:
   `ZaidrakeOMG/acme-`.
3. Selecciona **la rama** `migracion-supabase-segura-20261115` (no desplegar `main` aún).
4. Deja la **Root Directory** como `/` (raíz del repositorio).
5. Railway detectará el `Dockerfile` de la raíz; no el de `backend/` ni `frontend/`.
   La compilación construye React y luego FastAPI en un solo contenedor.
6. En **Settings → Networking → Public Networking → Generate Domain** crea el dominio temporal
   `https://TU_SERVICIO.up.railway.app`. Railway gestiona el certificado TLS.
7. En **Variables** configura los valores de la sección siguiente.
   Configura **Healthcheck Path**: `/api/salud`.
   No modifiques el comando de inicio; el Dockerfile escucha en el `$PORT` de Railway.
8. Despliega y comprueba en el navegador
   `https://TU_SERVICIO.up.railway.app/api/salud` y
   `https://TU_SERVICIO.up.railway.app/`.
   Para diagnóstico de dependencias consulta `/api/salud/detalle`.

Importante: no se ha conectado todavía una cuenta Railway en esta conversación;
este repositorio queda **preparado**, no publicado automáticamente.
No marques el despliegue como validado hasta revisar logs, login, MFA y archivos.

## 2. Variables de entorno privadas (Railway → Variables)

Copiar los **valores reales** desde el `.env` local a Railway;
NO crear un archivo `.env` en GitHub, NO compartir claves por chat,
y NO pegar el `.env` en la configuración pública de Flutter/Vercel.

Variables fundamentales del servicio API:

```text
ACMA_ENTORNO=produccion
DB_SCHEMA=acma
DATABASE_URL=<misma conexion PostgreSQL Supabase de ACMA, usuario acma_api>
ALMACENAMIENTO_MODO=supabase
SUPABASE_URL=<https://proyecto-ACMA.supabase.co>
SUPABASE_SECRET_KEY=<solo en backend; rotar si ya fue expuesta>
SUPABASE_BUCKET=acma
JWT_SECRETO=<secreto actual seguro, de 32 caracteres o mas>
CLAVE_CIFRADO=<exactamente la clave actual AES-256; no cambiar sin migracion>
MFA_OBLIGATORIO=true
APP_URL_PUBLICA=https://TU_SERVICIO.up.railway.app
CORS_ORIGENES=https://TU_SERVICIO.up.railway.app
UVICORN_WORKERS=1
DB_POOL_SIZE=3
DB_POOL_OVERFLOW=2
LOG_JSON=true
TIEMPO_REAL_MODO=redis
```

Notas:
- No pongas el `DATABASE_MIGRATIONS_URL` o credenciales de propietario de tablas en el
  servicio web a menos que una operación administrativa separada realmente las necesite.
  No ejecutar migraciones automáticas ni seeds sobre datos existentes.
- `JWT_SECRETO` y `CLAVE_CIFRADO` deben mantenerse coherentes con la instalación actual
  si se pretende conservar sesiones, TOTP y lectura de archivos. Cambiarlas sin plan
  rompe sesiones y/o información cifrada.
- `ACMA_ENTORNO=produccion` exige HTTPS, CORS explícito, MFA y secretos no ejemplificados.
- `/api/salud` es un healthcheck ligero: que responda 200 **no** prueba la conexión a
  PostgreSQL/Redis/Storage. Validar la app y el estado detallado.
- No subir al repositorio certificados, contraseñas, service_role o claves de Supabase.

## 3. Redis y tareas que ACMA necesita

ACMA contiene chat en tiempo real, notificaciones, preventivos, cálculos diarios,
y tareas programadas Celery. Publicar solamente FastAPI NO pone en marcha todo eso.

Para operación completa agrega **Redis administrado** al mismo proyecto Railway
(o un proveedor Redis externo compatible). Obtén sus URL privadas/TLS del panel del
proveedor y configura estas variables **en la API y en los procesos Celery**:

```text
REDIS_URL=<URL Redis para API/pubsub>
CELERY_BROKER_URL=<URL Redis para broker de tareas>
CELERY_RESULT_BACKEND=<URL Redis para resultados de tareas>
TIEMPO_REAL_MODO=redis
NOTIFICACIONES_ENVIO_INLINE=false
```

Luego crea dos servicios **privados** adicionales desde el mismo repo, rama y
`Dockerfile`, usando estas órdenes de inicio (Settings → Deploy → Custom Start Command):

- **Worker Celery:** `celery -A workers.celery_app worker --loglevel=info --concurrency=1`
- **Planificador Celery Beat:** `celery -A workers.celery_app beat --loglevel=info --schedule=/tmp/celerybeat-schedule`

Ambos comparten configuración privada de DB, cifrado y Redis. No abrir dominios públicos
para Worker, Beat ni Redis. Mantener **una sola** réplica de Beat para evitar programación
duplicada. El archivo temporal de Beat se recrea al reiniciar; para producción revisar
persistencia y comportamiento de reintentos antes de activar tareas críticas.
Activar los workers solo después de validar dependencias/colas y que las tareas tengan
permisos de BD adecuados; la verificación de la API por sí sola no basta.

## 4. Crear APK Android utilizable fuera de tu PC

Una vez que la URL pública HTTPS abra ACMA y permita iniciar sesión con MFA:

```bat
cd /d C:\Users\camil\Downloads\acme-
git pull --ff-only origin migracion-supabase-segura-20261115
cd mobile_flutter
flutter build apk --release --dart-define=ACMA_BASE_URL=https://TU_SERVICIO.up.railway.app
```

El archivo queda en `mobile_flutter\build\app\outputs\flutter-apk\app-release.apk`.
Reemplazar `TU_SERVICIO.up.railway.app` por el dominio real en ambos lugares.
Nunca usar `http://localhost:8000` ni `adb reverse` en el APK de producción.

El APK generado para pruebas se puede instalar manualmente, pero para distribución
formal es necesario revisar identificador de paquete, versión, icono, firma propia
(keystore) y los permisos nativos. Probar en teléfonos reales el login/MFA,
cámara, GPS, archivos y PDFs; no dar por verificadas funciones que aún no se probaron.

## 5. Seguridad antes de abrir a usuarios reales

- Revisar log del primer despliegue; verificar Supabase/Storage y PostgreSQL desde Railway.
- Usar `ACMA_ENTORNO=produccion`, MFA, cookies HTTPS, CORS específico y claves protegidas.
- Rotar cualquier `SUPABASE_SECRET_KEY` que se haya compartido accidentalmente.
- Comprobar `/api/salud/detalle` con Redis/Worker/Storage activos, antes de asumir
  funcionamiento completo de tareas o tiempo real.
- Probar al menos los flujos de usuarios de distintas empresas/tenants; no activar
  cuentas de terceros hasta validar el aislamiento.
- No ejecutar scripts de seed, bootstrap o migración de la base existente automáticamente.
- Si el hosting reinicia, la DB y archivos persisten en Supabase, no en el disco de Railway.

Documento basado en las rutas y configuración de ACMA; debe contrastarse con los
logs del primer despliegue real.
