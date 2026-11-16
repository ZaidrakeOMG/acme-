# ACMA Web + Android con Railway (instalación sencilla)

**Objetivo:** una única URL HTTPS de Railway para la **web React**, el **backend FastAPI** y el **APK Flutter WebView Android**. Los datos continúan en el Supabase actual de ACMA: **no se migran ni se borran tablas, usuarios, MFA ni archivos**.

El código de la rama `migracion-supabase-segura-20261115` ya contiene:

- `Dockerfile` en la raíz: construye React y FastAPI en un contenedor.
- `backend/railway_start.py`: detecta `RAILWAY_PUBLIC_DOMAIN` y establece el origen HTTPS correcto para cookies y CORS. **No debe incluir claves secretas en el APK.**
- `.railway/railway.ts`: configuración IaC opcional para Railway CLI. **No se activa automáticamente por estar en GitHub.**
- `GENERAR_APK_ACMA_RAILWAY.bat`: compilación del APK en Windows con la dirección pública.

## 1. Publicar ACMA desde el panel Railway

1. Entra a https://railway.com/dashboard con tu nueva cuenta y conecta GitHub.
2. Haz clic en **New Project → Deploy from GitHub Repo**.
3. Autoriza el repositorio **`ZaidrakeOMG/acme-`** si Railway aún no puede verlo.
4. Selecciona el repositorio; al crear el servicio, usa la rama
   **`migracion-supabase-segura-20261115`**, NO la rama main.
   Si Railway comienza a desplegar main automáticamente, entra en
   **servicio → Settings → Source → Branch** y cámbiala ANTES de publicar.
5. Deja **Root Directory** vacía (raíz del repo). Railway detectará el
   `Dockerfile` de la raíz; no uses `frontend/`, `backend/` ni `mobile_flutter/`.
6. Abre el servicio → **Settings → Networking → Public Networking → Generate Domain**.
   Railway dará una dirección similar a `https://acma-web.up.railway.app`.
   **Copia tu dirección real.** Generar el dominio es obligatorio para
   que `backend/railway_start.py` configure la URL segura automáticamente.
7. Abre **Variables** del mismo servicio y captura solo las **cinco variables
   privadas** indicadas abajo. Las demás usan los valores seguros fijados por
   el lanzador, salvo que un ajuste de tu instalación requiera lo contrario.
8. Verifica en **Settings** que el healthcheck sea `/api/salud` y que exista
   **una réplica**. Si aún no se ha activado IaC, pon el healthcheck desde el
   panel. El Dockerfile arranca FastAPI y escucha en el `PORT` de Railway.
9. Despliega los cambios pendientes y revisa **Deployments → Logs**.
   Se debe ver `[ACMA] Arrancando FastAPI + React` y no errores de configuración.

### Variables privadas (Railway → servicio → Variables)

| Clave | Valor a proporcionar |
| --- | --- |
| `DATABASE_URL` | URL PostgreSQL **actual** de ACMA en Supabase con usuario API (`acma_api`), formato `postgresql+asyncpg://...` |
| `SUPABASE_URL` | URL HTTPS del proyecto Supabase **ACMA** |
| `SUPABASE_SECRET_KEY` | Clave **secreta del backend** vigente, solo dentro de Railway (nunca en Flutter ni frontend) |
| `JWT_SECRETO` | **Exactamente la misma** clave JWT válida que está en el ACMA funcional |
| `CLAVE_CIFRADO` | **Exactamente la misma** clave AES-256 base64 que usa el ACMA funcional |

**Crítico:** no subas ni pegues el `.env` a GitHub, ChatGPT o el APK. Tampoco uses contraseñas de PostgreSQL `postgres`/owner, credenciales de migración, ni claves de otros proyectos. Cambiar `CLAVE_CIFRADO` puede impedir descifrar MFA y archivos históricos; cambiar JWT invalida sesiones.

El lanzador establece automáticamente en el contenedor los valores
`ACMA_ENTORNO=produccion`, `DB_SCHEMA=acma`, `MFA_OBLIGATORIO=true`,
`ALMACENAMIENTO_MODO=supabase`, `SUPABASE_BUCKET=acma`,
`UVICORN_WORKERS=1`, `DB_POOL_SIZE=3`, `DB_POOL_OVERFLOW=2`,
`TIEMPO_REAL_MODO=local` y `NOTIFICACIONES_ENVIO_INLINE=false`.
Si `RAILWAY_PUBLIC_DOMAIN` está presente, también establece
`APP_URL_PUBLICA=https://<dominio>` y `CORS_ORIGENES=https://<dominio>`.

Si ya configuraste valores explícitos para el dominio, tienen prioridad;
comprueba que coincidan exactamente con el dominio HTTPS actual de Railway.
Si aparece `[ACMA CONFIG]` en los logs, corrige el dato nombrado y vuelve
a desplegar. No se publica ninguna contraseña en el mensaje.

**Supabase no se mueve:** el contenedor solo se conecta a la base y al
bucket privado originales. No ejecutar seeds, scripts de migración ni alta
de superadmin durante el despliegue.

## 2. Verificar la web ANTES de generar el APK

Abre estas direcciones usando tu dominio real:

- `https://TU-DOMINIO.up.railway.app/api/salud`: devuelve JSON con `estado: ok`.
- `https://TU-DOMINIO.up.railway.app/`: abre el login React.
- Inicia sesión y completa MFA. Prueba un módulo con lectura y guardado
  autorizado, luego carga y descarga un archivo de Supabase Storage.

**Importante:** `/api/salud` solo indica que el servidor responde.
No garantiza que Supabase, Storage, Redis ni Celery estén bien. Si falla
login o archivos, revisar logs y variables en Railway sin publicarlas.

## 3. Generar el APK Android en Windows

Cuando web + login + MFA funcionen desde Internet, abre CMD:

```bat
cd /d C:\Users\camil\Downloads\acme-
git pull --ff-only origin migracion-supabase-segura-20261115
GENERAR_APK_ACMA_RAILWAY.bat
```

El archivo `.bat` solicitará **la URL HTTPS real de Railway**, por ejemplo
`https://acma-web.up.railway.app`. No escribas `localhost` ni una URL HTTP.

El generador comprueba la URL, prepara permisos Android seguros en release,
instala dependencias Flutter, aplica el logo original de ACMA y compila:

`mobile_flutter\build\app\outputs\flutter-apk\app-release.apk`

El APK corre en un **Android real** mediante Internet, sin `adb reverse` ni
servidor local Windows. Es una WebView Flutter sobre el React original, no
una aplicación nativa reconstruida pantalla por pantalla. Para Play Store
se necesita identificador de paquete propio, keystore de firma permanente,
versionado y pruebas de permisos/cámara/archivos/GPS en Android real.

El **APK no se aloja como backend en Railway**: se instala en el teléfono.
Solo requiere que ACMA Web/API permanezca accesible en el dominio HTTPS de Railway.

## 4. Modo completo (etapa posterior)

El arranque ligero de un servicio deja chat en modo local y no enciende tareas
Celery programadas (preventivos, notificaciones en segundo plano, reportes).
**No declarar ACMA completamente operativo solo con la API funcionando.**

Para activar esas funciones se necesita:
1. Redis como servicio privado;
2. Celery Worker como servicio privado;
3. Celery Beat (un solo programador activo), y Redis/Celery configurados en
   todos los procesos implicados;
4. pruebas de cada tarea, cuotas y costes de Railway.

En la etapa inicial no se crean esos servicios para no gastar créditos de
prueba sin necesidad. Se pueden activar después sin cambiar la URL del APK.

## 5. Si el cliente quiere usar su dominio IONOS

No requiere VPS. Una vez que Railway funcione, puedes conectar un subdominio
como `acma.dominio-cliente.com` desde **Railway → Settings → Networking → Custom Domain**,
y añadir en el panel DNS de IONOS los registros que Railway indique.
Railway gestiona HTTPS. Evita cambiar el dominio principal, correo y MX.

Si el APK se compila con la URL `*.up.railway.app` y después decides cambiar
al dominio de IONOS, seguirá funcionando mientras conserve ese dominio de
Railway. Para entregar un APK que use el dominio del cliente, recompílalo con
el dominio HTTPS definitivo.

**Estado actual:** el proyecto está preparado en GitHub, pero no hay una cuenta
Railway conectada a esta conversación ni un despliegue público verificado.
Revisar los logs reales antes de afirmar que está publicado.
