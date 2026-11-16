# ACMA en hosting IONOS: decidir el tipo de plan primero

La meta es alojar **ACMA Web** y el **APK Android** con una única URL HTTPS.
Base de datos y Storage continúan en el proyecto Supabase ACMA existente.
No se crean usuarios, tablas ni migraciones nuevas.

## Importante: distinguir el tipo de producto IONOS

En el panel de IONOS revisa la sección de **Productos / Contratos**:

| Lo contratado | Qué hacer |
|---|---|
| Solo dominio | Vincularlo por DNS al hosting externo (por ejemplo Railway). Un dominio no ejecuta FastAPI. |
| Hosting Web / WordPress / Deploy Now / FTP-SFTP | Publica archivos React estáticos, pero normalmente NO mantiene un proceso FastAPI ASGI, Celery y WebSockets. Para mantener el mismo origen con cookies seguras, apuntar un subdominio a Railway/VPS donde se ejecuten React+FastAPI juntos. |
| VPS (Linux) o servidor Cloud con root SSH | Puede alojar todo ACMA Web + API en el VPS, con Docker, Caddy HTTPS y Supabase. **El VPS puede estar incluido en un contrato ya pagado.** |

No cambiar el dominio ni mover registros DNS hasta identificar el producto concreto.
No compartir contraseñas, claves SSH, .env ni tokens.

## Camino A: IONOS VPS o Cloud Linux, con acceso SSH

Archivos preparados:
- `Dockerfile` (raíz): crea la imagen multietapa React + FastAPI, ya verificada en GitHub Actions.
- `deploy/ionos/compose.yml`: servicio FastAPI y Caddy para HTTPS, con un worker inicial.
- `deploy/ionos/Caddyfile`: reenvía **/**, **/api/** y **/ws/** al mismo FastAPI.
- `.dockerignore`: protege `.env` y archivos locales para que no entren en la imagen.

Requisitos del servidor: Linux reciente, acceso root/sudo, Docker Engine y Docker Compose
instalados, puertos 80 y 443 disponibles. Requiere memoria suficiente para compilar y
ejecutar ACMA; no se asegura que el VPS contratado tenga recursos adecuados sin revisar su
plan. El dominio/subdominio (por ejemplo `acma.dominio-del-cliente.com`) debe apuntar
por registro DNS **A** a la IP pública del VPS y, si hay IPv6, **AAAA** correcto.
Abrir 80/443 en firewall del VPS y del panel IONOS.

Ejemplo de instalación en servidor (comandos orientativos, ejecutar únicamente
después de verificar el contrato/servidor y las rutas existentes):

```bash
git clone --branch migracion-supabase-segura-20261115 https://github.com/ZaidrakeOMG/acme-.git /opt/acma
cd /opt/acma
```

Si el repositorio es privado, usar despliegue SSH/Deploy Key de GitHub;
no incluir un token de GitHub en URLs o en comandos compartidos.

Copiar al VPS por **SCP/SFTP cifrado** el `.env` real de ACMA que ya funciona en
Windows, a `/opt/acma/.env`, fuera de Git. Antes de levantar el servicio:

- Añadir `ACMA_DOMINIO=acma.dominio-del-cliente.com` (solo hostname, sin https).
- Conservar `DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_SECRET_KEY`,
  `JWT_SECRETO`, `CLAVE_CIFRADO` y el bucket **privado** ya configurados.
- Verificar `DATABASE_URL` con `postgresql+asyncpg://...`.
- No cambiar `CLAVE_CIFRADO`: descifra MFA y archivos históricos.
- Revisar que `SUPABASE_SECRET_KEY` esté vigente; si alguna vez se expuso,
  **rotarla** de forma coordinada antes de publicar.

Los archivos del contenedor fuerzan `ACMA_ENTORNO=produccion`,
`MFA_OBLIGATORIO=true`, CORS y APP_URL_PUBLICA HTTPS del dominio configurado.
La IP, SSH y dominio **no** se suben a GitHub.

```bash
cd /opt/acma
docker compose --env-file .env -f deploy/ionos/compose.yml config --quiet
docker compose --env-file .env -f deploy/ionos/compose.yml up -d --build
docker compose --env-file .env -f deploy/ionos/compose.yml ps
docker compose --env-file .env -f deploy/ionos/compose.yml logs --tail=60 api
```

Probar:

- `https://acma.dominio-del-cliente.com/api/salud` debe devolver `estado: ok`;
  **solo confirma que la API responde**, no todas las dependencias.
- `https://acma.dominio-del-cliente.com/` debe mostrar React y el login.
- Validar login, MFA, cookies seguras, lectura y escritura autorizada en Supabase.
- Validar descarga/carga de archivos, sesiones, multiempresa y errores de acceso.
- Verificar `/api/salud/detalle` y el estado de Redis y los workers cuando existan.

No exponer el puerto 8000 a Internet: Caddy lo alcanza en la red privada de Compose.

### Servicios pendientes del entorno completo

Este Compose configura **la prueba funcional de Web+API+APK** con un único proceso.
ACMA también contiene Redis, tareas Celery, Celery Beat, chat y notificaciones
programadas. El ejemplo NO crea Redis ni inicia esos procesos; por tanto no
se debe prometer que las funciones 24/7 funcionen totalmente.
Si el VPS tiene recursos adecuados, Redis y workers pueden añadirse más
adelante, con conexiones privadas y configuración de producción.

## Camino B: el cliente solo tiene alojamiento web compartido IONOS

No intentar subir el backend FastAPI como si fuera HTML/PHP. La web React
estática podría funcionar, pero sin API no se puede completar login ni escribir
en PostgreSQL; no poner la clave secreta de Supabase en React/Flutter.

Usar el dominio existente con un subdominio **DNS** que apunte al servicio Railway
o al VPS que tenga FastAPI. Para esta primera versión, conviene mantener
**React + FastAPI en un mismo dominio** para no romper cookies de sesión/CSRF,
WebSockets ni navegador interno del APK. El resto del sitio del cliente puede
seguir alojado en IONOS sin cambiarse.

## APK Android después de publicar

Una vez que la URL HTTPS permita entrar en la web y MFA:

```bat
cd /d C:\Users\camil\Downloads\acme-
git pull --ff-only origin migracion-supabase-segura-20261115
cd mobile_flutter
flutter build apk --release --dart-define=ACMA_BASE_URL=https://acma.dominio-del-cliente.com
```

El APK estará en `mobile_flutter\build\app\outputs\flutter-apk\app-release.apk`.
Usar el dominio **real** y revisar la firma, identificador de paquete e iconos
antes de distribuirlo a terceros. El APK no requerirá `adb reverse`.

## Estado real

Este repositorio quedó preparado para **un VPS IONOS**, pero no fue
publicado ni configurado en ninguna cuenta IONOS porque aún no sabemos
qué plan tiene contratado el cliente. Lo primero es identificar el servicio
en su panel, sin compartir credenciales.
