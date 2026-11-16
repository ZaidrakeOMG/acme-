# ACMA + Supabase — acceso seguro antes de migrar

## 1. Proyecto aislado para ACMA
Usar un proyecto Supabase nuevo **exclusivo para ACMA**, no Party-book u otras apps. La base de datos y sus archivos no se deben alterar hasta verificar las 18 migraciones de Alembic y la compatibilidad de roles, extensiones PostGIS y RLS.

## 2. Consulta SQL sin riesgos
Ejecutar el contenido de `docs/consulta_supabase_acma.sql` en SQL Editor → New query → Run.
Esta consulta solo obtiene versión PostgreSQL, número de tablas public, RLS, extensiones y roles ACMA; no devuelve credenciales, no crea ni destruye datos.

## 3. Qué información es seguro entregar
- URL de proyecto: `https://PROJECT_REF.supabase.co`.
- Identificador del proyecto (project ref), presente en esa URL.
- Clave publicable `sb_publishable_...` si es necesario configurar clientes con el SDK público. En la arquitectura actual, React y Flutter consumen FastAPI, así que **ni siquiera hace falta pasar esa clave**.
- Resultado SQL de diagnóstico (no secretos).
- Decidir si el backend se desplegará en una VM Linux con IPv6 o en una red IPv4: cambia cómo se conecta PostgreSQL.

**No compartir** contraseña de base de datos, `service_role`, `sb_secret_...`, credenciales SMTP, tokens de WhatsApp, ni llaves AES. No pegar secretos en issues, commits, PR, chat ni screenshots. La conexión de base desde FastAPI requiere una contraseña por usuario/rol de aplicación en un `.env` solo del servidor, o un almacén de secretos en el hosting.

Supabase → botón **Connect** → Direct connection (hosting IPv6) o **Session pooler** (hosting IPv4) para la cadena Postgres. **No confundir** esta cadena con la URL del proyecto. Los campos DB deben configurarse con el driver `postgresql+asyncpg://`. No usar pooler en modo Transaction para la RLS de ACMA sin pruebas: usa estado de sesión dentro de transacciones y necesita afinidad temporal de conexión.

Supabase → **Project Settings → API Keys** para claves `sb_publishable_` y `sb_secret_`. Nunca incrustar secret en React ni Flutter.

## 4. Por qué no ejecutar simplemente las 18 migraciones
ACMA utiliza `acma_owner`, `acma_api`, `acma_auth`, funciones privilegiadas, `SET LOCAL`, `FORCE ROW LEVEL SECURITY`, particiones de auditoría y PostGIS. Supabase trae roles y esquemas propios. Configurar la aplicación para operar como `postgres` o `service_role` puede evadir RLS y exponer datos entre empresas.

Se requiere primero auditoría completa y migración en un proyecto de prueba vacío. El SQL de diagnóstico **no es** un script de instalación del esquema. Los scripts destructivos o migraciones sin respaldo no se ejecutan por defecto.

## 5. Arquitectura sin Docker preservando todas las funciones
El frontend React se compila y se sirve desde FastAPI por un mismo host. Flutter accede a ese sitio mientras se validan capacidades nativas. Postgres y archivos se alojan en Supabase; para **no perder las tareas existentes**, Celery sigue operando con un Redis externo administrado y su proceso worker + beat, iniciados por un solo lanzador. Si a futuro se sustituyen por Supabase Cron y Queues, la sustitución se hará tarea por tarea con tests de paridad.

Esto elimina Docker de la máquina donde se ejecute ACMA, pero **no elimina la necesidad de procesos de backend/worker ni una URL accesible desde los celulares**. Para producción se recomienda una VM Linux y ejecución controlada de la API/worker/scheduler.

## 6. Condiciones de entrega
- Compatibilidad de 18 migraciones y roles, tablas, índices, funciones, triggers, PostGIS, RLS.
- Mismos datos/archivos, cifrado y descifrado, políticas y usuarios.
- React: igual CSS, UI, rutas y funciones.
- Celery: mismas tareas, frecuencia y reintentos. Redis externo, no local Docker.
- Flutter: comparar 80 páginas y cámara, GPS, descargas, push, offline, QR, web sockets, MFA en Android/iOS reales.
- No fusionar a `main` hasta que CI y pruebas reales estén completas.

## Documentación oficial
- https://supabase.com/docs/guides/getting-started/api-keys
- https://supabase.com/docs/guides/database/connecting-to-postgres
- https://supabase.com/docs/guides/database/postgres/row-level-security
