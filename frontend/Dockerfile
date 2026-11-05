# ACMA · imagen del frontend: compila la PWA y la sirve con Caddy, que además es el proxy inverso con HTTPS
# automático del despliegue. Una sola imagen atiende el navegador y pasa /api y /ws al backend. P11a.
#
# Construir desde la raíz del repositorio:
#   docker build -f frontend/Dockerfile -t acma-web:0.1.0 .

FROM node:22.14.0-alpine AS compilacion

WORKDIR /app
# Primero el manifiesto: si no cambia, la capa de dependencias se reutiliza.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
# `npm run build` incluye `tsc --noEmit`: si los tipos no cuadran, la imagen no se construye.
RUN npm run build


FROM caddy:2.8.4-alpine

# El Caddyfile vive en el repositorio (docker/Caddyfile) para poder revisarlo sin abrir la imagen.
COPY docker/Caddyfile /etc/caddy/Caddyfile
COPY --from=compilacion /app/dist /srv

# Caddy corre como root para poder escuchar en 80/443 y pedir el certificado; su proceso de trabajo no ejecuta
# nada del dominio de ACMA, solo sirve archivos y hace de proxy.
EXPOSE 80 443

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD wget -q --spider http://127.0.0.1:80/salud-proxy || exit 1
