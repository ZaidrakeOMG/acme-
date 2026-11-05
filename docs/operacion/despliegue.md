# Despliegue en un servidor Linux

Todo ACMA se levanta con un `docker-compose.prod.yml`: proxy con HTTPS automático que sirve la PWA, la API, los
trabajos de fondo, PostgreSQL, Redis y el almacenamiento de archivos. No hay nada que instalar fuera de Docker.

Los pasos de abajo se probaron completos en local el 5 de noviembre de 2026 (con `ACMA_DOMINIO=localhost`), así que
son los pasos reales, no una guía escrita de memoria.

---

## 1. Qué servidor hace falta

Medido con 50 técnicos simultáneos (detalle y cálculo en [`../rendimiento/resultados.md`](../rendimiento/resultados.md)):

| | Para 50 técnicos | Para 500 técnicos |
|---|---|---|
| CPU | **8 vCPU** | 2–3 servidores de API de 16 vCPU + base dedicada de 16 vCPU |
| RAM | **16 GB** | 32 GB por servidor de API + 64 GB la base |
| Disco | **200 GB SSD NVMe** | según evidencia (≈2 MB por folio cerrado) |
| Sistema | Debian 12 o Ubuntu 22.04/24.04 | igual |

Un solo servidor de 8 vCPU y 16 GB cubre el requisito de §6.7 con margen. Para 500 técnicos hay que separar la base
y agregar una réplica de lectura: el sistema ya está preparado (`DATABASE_READ_URL`).

**Antes de empezar, en el DNS:** un registro `A` de `acma.unai.com.mx` apuntando a la IP del servidor. Caddy no puede
emitir el certificado sin eso.

## 2. Preparar el servidor

```bash
sudo apt update && sudo apt install -y docker.io docker-compose-v2 git
```

Un usuario sin privilegios para operar ACMA (no se trabaja como root):

```bash
sudo adduser --disabled-password --gecos "" acma && sudo usermod -aG docker acma
```

Firewall: solo 22 (SSH), 80 y 443 abiertos. **El 80 es obligatorio**: Let's Encrypt lo usa para validar el dominio.

```bash
sudo ufw allow 22/tcp && sudo ufw allow 80/tcp && sudo ufw allow 443/tcp && sudo ufw --force enable
```

Nada más se publica: PostgreSQL, Redis y MinIO solo hablan dentro de la red de Docker, y la consola de MinIO queda
atada a `127.0.0.1` (se alcanza por un túnel SSH, no desde internet).

## 3. Traer el código y generar los secretos

```bash
sudo -iu acma && git clone <url-del-repositorio> /opt/acma && cd /opt/acma
```

```bash
cp .env.production.example .env
```

Los secretos se generan en el servidor y **no se guardan en el repositorio**:

```bash
docker run --rm -v /opt/acma:/app -w /app/backend python:3.12.10-slim-bookworm python -m scripts.generar_secretos --compose
```

Copie la salida al `.env` y complete el resto: `ACMA_DOMINIO`, `ACMA_CORREO_TLS`, `APP_URL_PUBLICA`,
`CORS_ORIGENES` y los datos de `SMTP_*`. Guarde una copia de todo en el gestor de secretos del cliente.

> **`CLAVE_CIFRADO` es insustituible.** Con ella se cifran los secretos de MFA y todos los archivos del Object
> Storage. Si se pierde, esos datos quedan ilegibles para siempre, respaldos incluidos. Confirme que existe **fuera
> del servidor** antes de seguir.

Claves de notificaciones push (opcional, pero sin ellas los avisos al celular no llegan):

```bash
docker run --rm -v /opt/acma:/app -w /app/backend python:3.12.10-slim-bookworm sh -c "pip install -q cryptography && python -m scripts.generar_vapid"
```

(Los dos guiones corren en una imagen de Python a secas porque el `.env` todavía no está completo y `docker compose`
exige todas sus variables antes de hacer nada, incluso para construir.)

El backend **se niega a arrancar** si algún secreto conserva un valor de ejemplo, si `CORS_ORIGENES` está vacío, si
`APP_URL_PUBLICA` no empieza con `https://` o si `MFA_OBLIGATORIO` no es `true`. Es a propósito: evita publicar con
las llaves de la demo.

## 4. Primer arranque

```bash
cd /opt/acma && docker compose -f docker-compose.prod.yml up -d --build
```

La primera vez tarda unos minutos: compila la imagen de la API (149 MB) y la de la PWA (19 MB). El orden lo maneja el compose:
PostgreSQL arranca, el servicio `migraciones` corre `alembic upgrade head` y termina, y **la API no arranca hasta
que las migraciones salen bien**. Después suben el worker, el beat y el proxy.

Comprobar que todo quedó sano:

```bash
docker compose -f docker-compose.prod.yml ps
```

Los siete servicios deben decir `healthy` (`migraciones` aparece como `exited (0)`: terminó su trabajo).

```bash
curl -s https://acma.unai.com.mx/api/salud/detalle | jq
```

Las cuatro dependencias en `true`. Si el certificado todavía no está listo, espere un minuto: Caddy lo pide al
primer acceso.

## 5. Crear el primer usuario

```bash
docker compose -f docker-compose.prod.yml run --rm api python -m scripts.seed_produccion --email admin@unai.com.mx --nombre "Nombre Apellido"
```

Crea **solo** el superadmin y las cuatro plantillas base de formularios. **Ningún dato demo.**

La contraseña temporal se imprime **una sola vez** y no queda en ningún archivo ni en el log. Entréguela por un canal
distinto al del usuario. Al entrar, ACMA pide dos cosas antes de dejar pasar a cualquier módulo:

1. **Activar la verificación en dos pasos** (el rol superadmin la tiene obligatoria en producción): se escanea el QR
   con Google Authenticator o Microsoft Authenticator y se guardan los diez códigos de recuperación.
2. **Cambiar la contraseña temporal**, porque nace vencida a propósito.

A partir de ahí, ese usuario crea el prestador, los clientes, las unidades y los demás usuarios desde la propia
aplicación.

## 6. Dejar los respaldos andando

Sin esto, el despliegue no está terminado:

```bash
crontab -e
```

```bash
30 1 * * *  cd /opt/acma && ./scripts/respaldo.sh >> /var/log/acma-respaldo.log 2>&1
```

Y **el destino fuera del servidor** (`RESPALDO_REMOTO` en el `.env`): mientras no se configure, el guion lo avisa en
cada corrida, porque un respaldo que vive en el mismo servidor no protege contra la pérdida del servidor. El detalle
está en [`recuperacion_desastres.md`](recuperacion_desastres.md).

Verifique a la mañana siguiente que el respaldo existe y que se puede restaurar.

## 7. Actualizar a una versión nueva

```bash
cd /opt/acma && git fetch && git log --oneline HEAD..origin/main
```

Lea los commits antes de actualizar: si traen migración (`backend/alembic/versions/`), **tome un respaldo primero**.

```bash
./scripts/respaldo.sh
```

```bash
git pull && docker compose -f docker-compose.prod.yml up -d --build
```

El compose reconstruye lo que cambió, corre las migraciones pendientes y reemplaza los contenedores. Hay unos
segundos de corte mientras la API se reinicia; los técnicos en campo no pierden nada porque la app guarda su cola
offline y la sincroniza al volver.

Después:

```bash
curl -s https://acma.unai.com.mx/api/salud/detalle | jq && docker compose -f docker-compose.prod.yml ps
```

### Si algo sale mal: volver atrás

**Si la actualización no traía migración**, basta regresar el código:

```bash
cd /opt/acma && git checkout <commit-anterior> && docker compose -f docker-compose.prod.yml up -d --build
```

**Si traía migración**, revertirla a ciegas puede perder datos. El camino seguro es:

```bash
docker compose -f docker-compose.prod.yml run --rm migraciones python -m alembic downgrade -1
```

```bash
git checkout <commit-anterior> && docker compose -f docker-compose.prod.yml up -d --build
```

Todas las migraciones de ACMA traen su `downgrade`, pero una que borra columnas **pierde lo que había en ellas**. Si
el `downgrade` falla o no está claro qué se pierde, la opción correcta es restaurar el respaldo anterior
([`recuperacion_desastres.md`](recuperacion_desastres.md)) y no insistir con el downgrade.

## 8. Cosas que ya pasaron al probar esto

Las siguientes no son hipótesis: salieron al probar el paquete completo en local y ya están corregidas en el
repositorio. Se dejan anotadas porque si alguien edita esos archivos, vuelven.

- **`/api/*` servía el `index.html` de la PWA.** Caddy ejecuta `try_files` antes de `reverse_proxy`, así que un
  matcher suelto no alcanza: las rutas de la API tienen que ir en su propio bloque `handle` (ya es así en
  `docker/Caddyfile`).
- **El beat de Celery no arrancaba:** `Permission denied` al escribir su calendario. El contenedor corre sin
  privilegios y el volumen se creaba con dueño root. El `Dockerfile` crea `/var/lib/acma` con dueño `acma` para que
  el volumen herede el dueño correcto; si cambia esa línea, hay que borrar el volumen (`docker volume rm
  acma-prod_beat_datos`) para que se vuelva a inicializar.
- **Un correo con dominio reservado** (`.local`, `.test`) creaba un superadmin que nunca podía entrar, porque el
  login valida el correo y el guion no. Ahora `seed_produccion.py` lo valida igual que la API.
- **El healthcheck del worker lo marcaba `unhealthy` aunque estuviera trabajando.** En la forma exec de un
  healthcheck no hay shell, así que `$HOSTNAME` llegaba literal y Celery preguntaba por un nodo inexistente. Ahora
  usa `CMD-SHELL`. Beat tiene el suyo propio (la frescura de su calendario): el de la imagen pega a `/api/salud` y
  beat no atiende HTTP.
- **El puerto 9001** suele estar ocupado si la máquina ya corre otro MinIO: la consola es configurable con
  `MINIO_CONSOLE_PORT`.

## 9. Cómo verificar el disco cifrado

§6.9.5 pide cifrado en reposo. ACMA cifra por su cuenta las columnas sensibles y **todos** los archivos del Object
Storage, pero el disco del servidor es responsabilidad de la infraestructura. Para confirmar que lo está:

```bash
lsblk -o NAME,FSTYPE,MOUNTPOINT | grep -i crypt
```

Si no aparece nada, el disco **no** está cifrado: hay que pedírselo al proveedor (casi todos lo ofrecen sin costo en
sus volúmenes) o montar los volúmenes de Docker sobre LUKS. Queda anotado en
[`../seguridad/checklist_iso27001.md`](../seguridad/checklist_iso27001.md) como pendiente del cliente.

## 10. Lo que este despliegue no incluye

- **Alta disponibilidad.** Es un servidor: si se cae, ACMA deja de estar disponible hasta que vuelva. La
  recuperación está resuelta (respaldo y restauración medida); la continuidad sin interrupción no.
- **Métricas históricas de servidor.** Hay logs en JSON y dos endpoints de salud; CPU y memoria en el tiempo
  (Prometheus y Grafana, ambos libres) quedan para Fase 2. Qué revisar cada día: [`monitoreo.md`](monitoreo.md).
- **La publicación real en `acma.unai.com.mx`** con los datos de UNAI, que es el prompt siguiente (P11b).
