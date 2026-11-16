# ACMA listo para VPS IONOS: Web + Android por HTTPS, Supabase sin mover

**Estado del repositorio:** preparados `Dockerfile`, `deploy/ionos/compose.yml`,
`deploy/ionos/Caddyfile`, `deploy/ionos/desplegar.sh` y
`GENERAR_APK_ACMA_IONOS.bat`. La imagen React + FastAPI y el archivo Compose
se validan en GitHub Actions.

**Estado del hosting:** todavía NO se ha desplegado: desconocemos si el cliente
tiene **IONOS Hosting compartido** o **VPS/Cloud Linux**. Esa distinción es
decisiva; no se puede ejecutar FastAPI/Redis/Celery persistente en un hosting
que solo admite subir archivos web estáticos/PHP.

## 1. Qué producto comprobar en IONOS

Entrar al panel IONOS del cliente → **Mis productos / Contratos**.

| Producto | Para ACMA |
| --- | --- |
| Solo dominio | Usarlo como subdominio para un VPS o hosting con backend |
| Hosting Web / WordPress / FTP | No es suficiente para ejecutar FastAPI y tareas en contenedores |
| VPS Linux / Servidor Cloud con SSH (root/sudo) | **Sí**: permite desplegar la Web, API, proxy HTTPS, Redis y Celery |

Recomendación: conservar el sitio actual del cliente en el dominio principal
y usar un subdominio dedicado, por ejemplo `acma.dominio-cliente.com`.
Modificar solo el DNS de ese subdominio (A → IP pública del VPS), sin cambiar
registros de correo MX ni del dominio principal. Si hay registros AAAA,
solo añadirlos si el VPS admite esa IPv6 y está configurada correctamente.

## 2. Arquitectura

```text
PC, Chrome, iPhone navegador       APK Android Flutter
                  \               /
                   HTTPS: acma.dominio-cliente.com
                          |
                  Caddy (IONOS VPS)
                          |
           FastAPI + React original (Docker)
                          |
             PostgreSQL y Storage SUPABASE
```

**La aplicación móvil y la web usan el mismo origen HTTPS.** No hay que abrir
el puerto 8000 al exterior ni usar `adb reverse` en el APK final.
El bucket privado y los usuarios con MFA se conservan.

## 3. Requisitos previos del VPS

- Ubuntu/Debian Linux con Docker Engine + Docker Compose plugin instalados;
  SSH con sudo/root para configuración inicial.
- Recursos suficientes para Python/OR-Tools, React y Docker. Para perfiles
  con Redis/Celery se requieren más RAM/CPU; verificar plan antes de activar.
- Puertos entrantes **80 y 443** disponibles; no abrir `8000`, `6379`
  ni puertos de base de datos.
- DNS `A` del subdominio de ACMA apuntando a la IPv4 pública del VPS.
  Comprobar que no hay otro servidor (Apache/Nginx/Plesk) ocupando 80/443.
- Conexión saliente desde VPS a Supabase PostgreSQL y Storage.
- La URL de Supabase, usuario `acma_api`, esquema `acma` y contraseñas
  existentes deben permanecer iguales salvo rotación planificada.

**Importante:** si el VPS ya hospeda otras webs, no usar directamente
los puertos 80/443 sin revisar el proxy/reverse proxy existente. En ese caso,
el Compose preparado debe integrarse al proxy que ya existe; no detener sitios.

## 4. Instalación inicial en VPS IONOS

Con SSH y el repositorio disponible:

```bash
git clone --branch migracion-supabase-segura-20261115 https://github.com/ZaidrakeOMG/acme-.git /opt/acma
cd /opt/acma
```

Si el repo es privado, configurar Deploy Key SSH en GitHub; nunca poner un
token GitHub en una URL que pudiera quedar en el historial de comandos.

Subir el `.env` vigente de ACMA desde Windows al VPS **por SCP/SFTP cifrado**,
en `/opt/acma/.env`. Comprobar que el archivo tenga solo los secretos de ACMA,
sin los de otros proyectos y sin credenciales de migraciones/owner si no hacen falta.
Por seguridad, `chmod 600 /opt/acma/.env`, y restringir acceso al usuario
que ejecuta Docker; el servicio Docker tendrá sus variables mediante
`env_file`. No pegar el contenido en GitHub ni en este chat.

Agregar en `.env` (solo ejemplos de variables públicas):

```dotenv
ACMA_DOMINIO=acma.dominio-cliente.com
```

Debe contener además los **valores reales existentes** de
`DATABASE_URL` (usuario ACMA API), `SUPABASE_URL`,
`SUPABASE_SECRET_KEY`, `JWT_SECRETO` y `CLAVE_CIFRADO`.
No inventar ni regenerar esas claves: el MFA, archivos cifrados y
sesiones dependen de su continuidad.
Si la clave `SUPABASE_SECRET_KEY` se expuso, rotarla coordinadamente.

El Compose fuerza: `ACMA_ENTORNO=produccion`, MFA obligatorio,
`DB_SCHEMA=acma`, Storage Supabase privado, URL pública HTTPS y CORS
del subdominio. No hace migraciones de BD ni crea administradores.

**Instalación básica:**

```bash
cd /opt/acma
bash deploy/ionos/desplegar.sh
```

El script valida con `docker compose config --quiet` y construye
Web React + FastAPI. Enciende **solo** API + Caddy HTTPS;
Redis y los procesos de tareas quedan desactivados.

Diagnóstico:

```bash
docker compose --env-file .env -f deploy/ionos/compose.yml ps
docker compose --env-file .env -f deploy/ionos/compose.yml logs --tail=80 api
docker compose --env-file .env -f deploy/ionos/compose.yml logs --tail=80 caddy
```

No ejecutar `docker compose config` sin `--quiet` ni publicar
capturas de los logs si incluyen datos sensibles.

## 5. Verificar la web publicada

1. `https://acma.dominio-cliente.com/api/salud` → JSON con `estado: ok`.
2. `https://acma.dominio-cliente.com/` → login React, estilos y navegación.
3. Login real, MFA, sesiones y cookies HTTPS (sin HTTP).
4. Lectura y escritura autorizada en Supabase, sin errores de RLS.
5. Archivos, PDF, formularios, cámara/GPS, y aislamiento por empresa.
6. `/api/salud/detalle` mostrará dependencias que estén apagadas; en
   modo mínimo Redis y Celery no estarán listos. **No es prueba de operación completa**.

El servidor del cliente puede requerir ajustes de red/puertos/DNS que no
pueden completarse solo con GitHub.

## 6. Perfil opcional: ACMA completo con Redis y Celery en el mismo VPS

ACMA incluye chat multiinstancia, notificaciones, preventivos, cálculos
programados y otras tareas. El modo básico no enciende esos procesos.
**Cuando el VPS tenga recursos suficientes**:

1. En `.env`, definir `TIEMPO_REAL_MODO=redis`.
2. Ejecutar:
   ```bash
   cd /opt/acma
   bash deploy/ionos/desplegar.sh --completo
   ```
3. Docker Compose enciende adicionalmente `redis`, `celery-worker`,
   `celery-beat`; el servicio API usa Redis local de la red interna.
4. Redis conserva su volumen; Beat conserva su calendario en volumen.
   Mantener **solo una** réplica de Beat. Verificar logs, tareas y
   permisos de base antes de considerarlo apto para producción.

No es otro hosting: corre en el mismo VPS, pero consume más memoria y CPU.
Verificar tamaño del plan y backups antes de activar tareas.

## 7. Generar APK Android con dominio IONOS

Una vez que **Web + API + MFA** funcionen mediante HTTPS, en tu PC Windows:

```bat
cd /d C:\Users\camil\Downloads\acme-
git pull --ff-only origin migracion-supabase-segura-20261115
GENERAR_APK_ACMA_IONOS.bat https://acma.dominio-cliente.com
```

Este lanzador:
- Comprueba URL HTTPS para no compilar el APK apuntando a localhost.
- Prepara el AndroidManifest RELEASE generado localmente por Flutter
  con permisos de Internet, cámara y ubicación; no habilita HTTP en release.
- Ejecuta `flutter pub get` y `flutter build apk --release`.
- Deja el APK en
  `mobile_flutter\build\app\outputs\flutter-apk\app-release.apk`.

**El APK es una primera versión instalable para pruebas**, no una publicación
en Play Store: revisar firma propia, ID del paquete, icono, permisos y
funcionamiento real en dispositivos. Si el servidor está caído, ambos
clientes —Web y Android— fallarán; la base permanece en Supabase.

## 8. Qué falta para ponerlo en Internet

- Confirmar el tipo de contrato IONOS del cliente (VPS vs Hosting).
- Si tiene VPS: conocer la IP pública y el subdominio elegido; configurar
  SSH, Docker, DNS y firewall sin cambiar las webs existentes.
- Transferir `.env` de ACMA de forma privada.
- Ejecutar el script, revisar logs y completar pruebas funcionales.

Nada de esto toca la base de datos actual, ni hace un deploy real sin
acceso al servidor del cliente.
