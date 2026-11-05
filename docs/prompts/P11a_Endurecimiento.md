# P11a — Endurecimiento: seguridad, rendimiento, respaldos y paquete de producción (Fase 1, prompt 11, parte 1 de 2)

## Contexto

P10 está cerrado (commit `0915942`; 365 pytest y 104 vitest en verde; los 27 módulos de Fase 1 tienen pantalla). Lee antes de empezar `CONTEXTO.md` completo, en particular **todas las decisiones pendientes** y las notas de entorno, `BITACORA.md`, y en `ACMA_Documento_Diseno_v2.5.docx`: §6.9.5 completo (eventos auditados, requisitos ISO 27001, tablas y su retención), §6.7 (restricciones del negocio: 50 técnicos simultáneos escalable a 500+, evidencia inmutable 5 años, saldo de caja chica nunca negativo, campos de sello y geolocalización no editables), §6.2 (capas de datos y réplicas) y ACT-1.6 y ACT-10.1 del §8.

Este prompt **no agrega funcionalidad** ni publica nada en internet. Deja ACMA listo para producción en cualquier servidor Linux: cierra los pendientes de seguridad, mide rendimiento, automatiza respaldos y empaqueta el despliegue. La publicación en `acma.unai.com.mx` con el servidor definitivo y los datos reales de UNAI es P11b.

## Entregables

### 1. Pendientes de seguridad (§6.9.5)

Cierra cada uno o justifica por escrito en `CONTEXTO.md` por qué queda para después:

- **Sesiones (§6.9.5 Gestión de sesiones):** reemplazar el refresh token en `localStorage` (decisión pendiente n.º 7) por cookie `httpOnly`, `Secure` en producción, `SameSite=Strict`, con ruta limitada a `/api/auth`, y protección CSRF para el endpoint de refresh (doble envío o cabecera personalizada). Conservar el token de acceso en memoria. Ajustar el cliente de `src/services/api.ts`, el modo offline de P05 (que no debe perder la sesión al recargar sin red; documentar el comportamiento) y las pruebas. Expiración: aplicar la de §6.9.5 (8 h, 2 h para roles administrativos) como vida máxima de la sesión con cierre por inactividad configurable, conservando el access token corto; resolver así la decisión pendiente n.º 1 y anotarlo.
- **Contraseñas (§6.9.5):** mínimo 10 caracteres con complejidad, historial de las 10 anteriores (tabla `historial_contrasenas` de P01), vencimiento a 90 días para roles administrativos con cambio obligatorio al iniciar sesión, y pantalla de cambio de contraseña. Comprobar que el restablecimiento de contraseña existe; si no, implementarlo con token de un solo uso por correo (`notificar()` de P07).
- **MFA:** impedir la reutilización del mismo código TOTP dentro de su ventana (registrar el último paso usado por usuario).
- **Intentos fallidos:** confirmar el bloqueo tras 5 intentos en 10 minutos por IP y agregar la notificación al administrador con `notificar()` (pendiente de P01).
- **Auditoría:** revisar que se registren todas las categorías de la tabla de §6.9.5, incluido el **acceso a datos sensibles** (consulta de datos financieros de P09/P10, descarga de reportes, acceso a historial de folio cerrado) con tabla, ID y cantidad de registros; geolocalización aproximada del login con una base local gratuita (GeoLite2 si la licencia lo permite, o dejarlo como interfaz `stub` y anotarlo).
- **Retención de `audit_accesos_api` (§6.9.5):** 90 días para llamadas normales y 1 año para errores 4xx/5xx, con particiones diarias si el volumen lo justifica (decisión pendiente n.º 6), purgando solo con `DETACH` + `DROP` de particiones; tarea beat diaria.
- **Cifrado en reposo:** revisar la cobertura de columnas sensibles; para archivos en MinIO, activar cifrado del lado del servidor (SSE) y documentar la estrategia de llaves por tenant de §6.9.5 (implementarla si MinIO lo permite sin servicio externo; si no, anotarla para Fase 2).
- **RLS:** confirmar fail-closed en todas las tablas con `tenant_id`/`prestador_id` (la prueba automática ya existe), revisar que ninguna política permita lectura sin contexto, y agregar pruebas de intento de acceso cruzado por HTTP con un usuario de cada rol contra recursos de otro tenant en todos los routers (ACT-1.6), generadas a partir de la lista de rutas de la app.
- **Cabeceras y CORS:** CSP sin `unsafe-inline` en producción, HSTS, `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy` (cámara, micrófono y geolocalización solo para el propio origen), CORS restringido al dominio de producción.
- **Dependencias:** `pip-audit` y `npm audit` con resultado documentado; actualizar lo crítico sin cambiar versiones mayores del stack; fijar la imagen de MinIO por versión o digest (decisión pendiente n.º 12) y todas las imágenes de Docker por versión exacta.
- **Secretos:** ningún secreto en el repositorio; `.env.production.example` con todas las variables y su descripción; `scripts/generar_secretos.py` para producción; rotación de los secretos de demo; verificación al arrancar en producción que rechace valores de ejemplo (`cambiar_*`, claves demo).
- **Restricciones de §6.7:** pruebas explícitas de que el saldo de caja chica no puede quedar negativo, de que sello de fecha y geolocalización no son editables por el usuario, y de que la evidencia de folios cerrados no se puede borrar (política de retención de 5 años documentada para MinIO y la base de datos).

Entrega `docs/seguridad/checklist_iso27001.md`: cada requisito de §6.9.5 con su implementación, la prueba que lo verifica y su estado.

### 2. Rendimiento y carga (ACT-1.6, §6.7)

- Scripts de carga con Locust en `backend/pruebas_carga/` sobre datos del seed histórico de P10: 50 técnicos simultáneos sincronizando y atendiendo folios, 20 usuarios de oficina navegando listados, detalle, minuta y dashboards, y la captura de folios del operador. Medir percentiles p50/p95/p99, errores y uso de memoria de la API, PostgreSQL y Redis.
- Corregir lo que la medición muestre: índices faltantes (revisar `EXPLAIN ANALYZE` de las consultas más lentas de listados, dashboards y sincronización), N+1 en el ORM, tamaño del pool de conexiones, caché de catálogos.
- Documentar en `docs/rendimiento/resultados.md` los resultados antes y después, y una estimación del servidor necesario para 50 y para 500 técnicos.
- Ejecutar las pruebas de carga con los servidores de desarrollo y la suite de pytest apagados (la máquina tiene poca memoria).

### 3. Respaldos y recuperación (§6.9.5, ACT-10.1)

- `scripts/respaldo.sh`: `pg_dump` en formato custom de la base completa, más los objetos de MinIO, con nombre por fecha, compresión, verificación (`pg_restore --list` y conteos cruzados como en los procedimientos de auditoría de P01) y rotación (diarios 14 días, semanales 8 semanas, mensuales 12 meses; configurable). Destino configurable: carpeta local y, opcionalmente, un bucket S3 compatible en otra región (§6.9.5 "respaldo diario a región diferente"), sin proveedor de pago obligatorio.
- `scripts/restaurar.sh` y un procedimiento probado de restauración en una base vacía, con medición del tiempo real (objetivo RTO < 4 h y RPO < 1 h; si el RPO de 1 h exige respaldo continuo con WAL, documentar la opción y su costo y dejar el respaldo diario funcionando).
- `docs/operacion/recuperacion_desastres.md` con el procedimiento paso a paso y la plantilla de la prueba trimestral.

### 4. Paquete de producción

- `Dockerfile` del backend (multietapa, usuario no root, WeasyPrint con sus dependencias de sistema para que el PDF use el diseño completo en Linux), imagen del frontend compilado servido como estático, y `docker-compose.prod.yml` con: proxy inverso con HTTPS automático (Caddy, por simplicidad de certificados), API con varios workers de uvicorn (o gunicorn con workers uvicorn), worker y beat de Celery, PostgreSQL 16 + PostGIS con el script de roles de P01, Redis con contraseña, MinIO, y volúmenes persistentes; límites de memoria por servicio; healthchecks en todos; reinicio automático.
- Migraciones al desplegar (`alembic upgrade head` en un servicio de una sola ejecución) y un `seed_produccion.py` que crea solo la plataforma, el superadmin inicial (contraseña forzada a cambiar en el primer acceso) y los catálogos globales; **nada de datos demo**.
- PWA en producción: `APP_URL_PUBLICA`, service worker con la versión correcta, claves VAPID reales, manifest con nombre y colores de ACMA.
- Correo: plantilla de variables `SMTP_*` lista para el correo corporativo (sin credenciales).
- Observabilidad mínima sin servicios de pago: logs en JSON con rotación, endpoint `/api/salud` (base de datos, Redis, MinIO, Celery) y `docs/operacion/monitoreo.md` con qué revisar diariamente.
- Probar el paquete completo localmente: `docker compose -f docker-compose.prod.yml up` con un dominio de prueba en `localhost`, recorrido básico con el navegador, y apagarlo.
- `docs/operacion/despliegue.md`: requisitos del servidor (según la medición de la sección 2), pasos para un servidor Linux nuevo (Docker, firewall, usuario, DNS de `acma.unai.com.mx`, primer arranque, restauración de respaldo), actualización a una nueva versión y reversión.

### 5. Limpieza y documentación

- Resolver o clasificar todas las decisiones pendientes de `CONTEXTO.md` en tres grupos: **resueltas en P11a**, **requieren validación del negocio** (con la pregunta concreta a responder) y **Fase 2**. Generar `docs/decisiones_para_validar.md` con solo el segundo grupo, redactado para una persona no técnica, una pregunta por decisión, con la opción que eligió el sistema y su efecto.
- `README.md` final: qué es, cómo levantar desarrollo, cómo desplegar, dónde está cada documento.
- Revisar que no queden textos internos visibles al usuario final ("vacía hasta P09", "Disponible en el prompt Pxx", etc.) salvo las etiquetas "Fase 2" acordadas.

### 6. Pruebas

- Todas las pruebas nuevas de seguridad (sesión por cookie, CSRF, contraseñas, TOTP reutilizado, notificación de bloqueo, auditoría de datos sensibles, acceso cruzado por ruta y rol, retención de auditoría, restricciones de §6.7) y la prueba del script de restauración en la base de pruebas.
- `pytest`, `vitest`, `tsc --noEmit` y `npm run build` en verde, con la suite completa corrida con los servidores de desarrollo apagados.

## Reglas (vigentes)

1. Seguir el Documento de Diseño v2.5; lo no definido se anota en `CONTEXTO.md`.
2. Multitenancy validado en servicio además de RLS.
3. Sin proveedores externos de pago.
4. Identificadores en español sin acentos.
5. Cerrar con `CONTEXTO.md` (avance P11a ✅) y `BITACORA.md` actualizados.
6. No cambiar el stack.
7. No correr la suite completa ni las pruebas de carga con los servidores de desarrollo encendidos.
8. Si el trabajo es demasiado para una sesión, hacer commits parciales por sección ("P11a (1/3) seguridad", "(2/3) rendimiento y respaldos", "(3/3) paquete de producción y documentación").

## Al terminar

Resumen en español con: pendientes de seguridad cerrados y los que quedan con su razón, resultados de carga (p95 y errores con 50 técnicos), tiempo medido de restauración, tamaño de servidor recomendado, lista de archivos de despliegue, número de decisiones para validar y conteo de pruebas.
