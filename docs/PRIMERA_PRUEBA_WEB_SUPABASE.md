# ACMA — Primera prueba web REAL contra Supabase

Se conserva React + FastAPI ORIGINAL (mismas pantallas y API). Esta guía es solo para probar web y autenticación. No sustituye Redis/Celery ni prueba Flutter.

## Estado inicial

La auditoría del usuario confirma Alembic 0018, 201 tablas y particiones, 2.520 columnas, 337 índices, 187 triggers, 33 funciones, 412 políticas, 114 ENUM con 431 etiquetas, 126 restricciones nombradas, PostGIS y cero usuarios. Falta el bucket privado de Storage. No reinstalar el esquema ni ejecutar V1/V2/V3 otra vez.

## 1. Bucket de archivos

Supabase → SQL Editor: ejecutar el archivo **docs/01_CREAR_BUCKET_PRIVADO_ACMA.sql** de ESTA RAMA. Debe quedar id=acma, name=acma, public=false. No crear políticas de acceso público.

## 2. Obtener cambios de GitHub

Desde CMD/PowerShell en la carpeta del repositorio ACMA:

    git status
    git fetch origin
    git switch main
    git pull --ff-only

Si la rama local ya existe:

    git switch main
    git pull --ff-only origin main

Si hay cambios locales sin guardar, revisarlos antes de actualizar, sin descartarlos.

## 3. Doble clic en PROBAR_ACMA_WEB.bat

Requiere Windows, Python 3.12, Node.js 22+ e internet. El lanzador crea el virtualenv, instala todas las dependencias originales y ejecuta npm ci y npm run build sin tocar el diseño.

La primera ejecución presenta un asistente. Los datos se introducen **SOLO en la consola local**:
1. URL pública del proyecto ACMA ya está preconfigurada como https://mrtmwmqzueqamzfveyev.supabase.co (NO agregar /rest/v1).
2. Nueva Supabase Secret API Key (oculta, NUNCA pegada a GitHub ni escrita en la web). Revoca la clave anterior compartida en el chat desde el panel de API Keys antes de usar la nueva.
3. Conexión PostgreSQL con usuario postgres desde Supabase → Connect → Session pooler puerto 5432 en Windows/IPv4. Copiar la cadena COMPLETA de Connect incluso si contiene [YOUR-PASSWORD]: el asistente pedirá la contraseña PostgreSQL por separado, oculta. Copiar host EXACTO y usuario postgres.PROJECT_REF. Si dispone de IPv6, puede usar Direct connection con postgres.
4. Confirmar CONFIGURAR. El instalador verifica esquema Alembic 0018 y bucket privado, genera aleatoriamente una contraseña de DB para el rol acma_api (sin BYPASSRLS) y crea el archivo .env, EXCLUIDO DE GIT. No persiste la credencial de postgres.
5. Escribir correo REAL y nombre del primer superadmin.

El sistema reutiliza **backend/scripts/seed_produccion.py** del proyecto original: crea el superadmin + las cuatro plantillas iniciales de formularios y las plantillas de mensajería sin usuarios ni datos DEMO. Muestra la contraseña temporal aleatoria UNA vez. Guardarla inmediatamente. Exige MFA y cambio de contraseña. No ejecutar seed_dev.py.

Si ya tienes un .env viejo de Docker, el lanzador lo guarda AUTOMÁTICAMENTE como .env.respaldo_anterior, sin borrar su contenido, y abre el asistente Supabase. No te pedirá escribir RESPALDAR. Guarda la copia local en un lugar seguro y no la subas a GitHub. Si el asistente creó .env pero no completó la cuenta, ejecutar **CREAR_ADMIN_ACMA.bat**: retoma solo la parte del administrador sin sobrescribir secretos.

## 4. Entrar al sitio

Abrir http://localhost:8000 — todo React original, no el servidor Vite por separado.
Verificar http://localhost:8000/api/salud (JSON estado=ok).
Iniciar sesión con el correo y contraseña temporal impresos. Configurar el autenticador MFA y respaldar códigos de recuperación; cambiar contraseña temporal.
Probar módulos de formularios, contratos, activos, reportes y navegación tras crear la empresa/prestador correspondiente desde la aplicación. Ver errores API en la consola del servidor.

AVISO: /api/salud/detalle puede devolver degradado porque este modo NO inicia Redis/Celery. Las alertas programadas, chat multiinstancia, minutas, envíos en cola y todas las tareas necesitan los procesos reales. Este launcher es exclusivamente la primera prueba WEB, NO la aplicación final.

## 5. Después: todos los procesos

Configurar Redis externo con TLS y arrancar FastAPI y Celery Worker/Beat siguiendo **docs/operacion/despliegue.md**, configurar HTTPS, notificaciones, copias de seguridad y pruebas de roles RLS entre tenants. Flutter debe probarse en dispositivos y usar la URL HTTPS del backend ACMA, no la URL pública de la base.

## Seguridad

- Nunca subir .env, JWT, clave AES, cadena postgres, sb_secret o service_role.
- La app se conecta como acma_api en el esquema privado acma; anon/authenticated no pueden consultarlo.
- No correr pytest completo sobre la base alojada: las fixtures originales DROP/CREATE la DB de prueba.
- No exponer el puerto 8000 local directamente a internet.
