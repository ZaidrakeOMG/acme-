# F2-02 — Notificaciones por WhatsApp y SMS (segunda etapa, prioridad 1 de Dirección)

## Contexto

F2-01 está cerrado (último commit `b994401`). Por indicación de Dirección, los bloques prioritarios de la segunda etapa son **WhatsApp/SMS (este prompt)** y **pantalla de operaciones en tiempo real (F2-03)**. Lee antes de empezar `CONTEXTO.md` completo (reglas de la segunda etapa y notas de entorno), `BITACORA.md`, `docs/piloto/ACMA_Segunda_Etapa.xlsx` (hoja «Bloques Fase 2», bloque «Notificaciones por WhatsApp y SMS») y en `ACMA_Documento_Diseno_v2.5.docx`: §6.1 (stack de notificaciones: «Twilio / WhatsApp Business API + Push PWA + Email»), §4.1 (Minuta del día multicanal), §7.5 (canal WhatsApp de la minuta: «resumen ejecutivo en texto, máx. 5 bullets, + enlace al PDF completo», para Admin empresa y Admin UN, «solo los puntos más críticos del día»), §6.9.6 (canales de alertas), §6.9.5 (auditoría y datos personales) y ACT-6.2 y ACT-7.1 del §8.

Lo que ya existe y este prompt debe usar sin duplicar: `notificar()` en `services/notificaciones_service.py` con la tabla `notificaciones`, las preferencias por usuario y evento, el envío en Celery y los canales `whatsapp` y `sms` registrados hoy como `omitida — canal Fase 2` (`FASE_2 = {whatsapp, sms}`); el correo SMTP con modo stub (P07); el push PWA (P05); la generación de la minuta y su PDF con hash (P07); las alertas con canales configurables (P10); y el cifrado y la auditoría de P11a.

**Regla de esta etapa:** no se contrata nada. Se desarrolla con modo simulado y con las cuentas de prueba gratuitas de los proveedores; las credenciales reales se cargan en el paso final.

## Objetivo

Que cualquier evento que hoy se notifica por correo, push o bandeja pueda enviarse también por WhatsApp o SMS según la preferencia del usuario y la configuración del tenant, con plantillas aprobables por Meta, consentimiento del destinatario, control de costo y bitácora completa; y que la minuta del día llegue por WhatsApp como resumen de máximo 5 puntos con enlace al PDF.

## Entregables

### 1. Migración `0014_whatsapp_sms.py`

Con los helpers de `core/sql_migracion.py`, RLS forzada en toda tabla con `tenant_id`/`prestador_id`.

| Tabla / cambio | Campos clave |
|---|---|
| `usuarios` | agregar `telefono_movil_e164` (validado en formato E.164, p. ej. `+528711234567`), `telefono_verificado_at`, `whatsapp_consentimiento_at`, `whatsapp_baja_at`, `sms_consentimiento_at`, `sms_baja_at` (el teléfono se guarda cifrado con el mecanismo de P11a; anotar) |
| `mensajeria_plantillas` | clave (p. ej. `folio_asignado`), canal ENUM(`whatsapp` / `sms`), idioma (`es_MX`), nombre_proveedor (nombre de la plantilla en Meta), categoria ENUM(`utility` / `authentication` / `marketing`), cuerpo con variables `{{1}}`…, botones_json, estado_aprobacion ENUM(`borrador` / `enviada` / `aprobada` / `rechazada` / `pausada`), motivo_rechazo, version, activa |
| `mensajeria_envios` | notificacion_id (FK `notificaciones`), canal, proveedor ENUM(`stub` / `meta_cloud` / `twilio`), telefono_destino_hash (no el número en claro), plantilla_id, variables_json, mensaje_id_proveedor, estado ENUM(`en_cola` / `enviado` / `entregado` / `leido` / `fallido` / `rechazado_por_proveedor`), codigo_error, detalle_error, costo_estimado, moneda, segmentos_sms, intentos, enviado_at, entregado_at, leido_at |
| `mensajeria_configuracion` | prestador_id, tenant_id nullable, whatsapp_activo, sms_activo, eventos_whatsapp_json, eventos_sms_json, horario_silencio_json (no enviar fuera de horario salvo críticos), tope_mensual_mensajes, alerta_consumo_pct (default 80), remitente_whatsapp (id de número de Meta), remitente_sms |
| `mensajeria_respuestas` | mensaje entrante del usuario (texto o botón), telefono_hash, usuario_id resuelto, contexto (mensaje original), accion_ejecutada, timestamp — para «BAJA», «ALTA» y respuestas rápidas |

### 2. Capa de proveedores (`services/mensajeria/`)

- Interfaz `ProveedorMensajeria` con `enviar_plantilla()`, `enviar_texto()` (solo dentro de la ventana de 24 h que permite WhatsApp tras un mensaje del usuario), `estado()` y `validar_webhook()`.
- Implementaciones: `stub` (por defecto; guarda el mensaje renderizado en la bitácora y en un archivo de vista previa, simula estados entregado/leído y errores configurables para pruebas), `meta_cloud` (WhatsApp Cloud API de Meta, por HTTPS con el token y el id del número en variables de entorno) y `twilio` (SMS y, opcionalmente, WhatsApp por Twilio). Selección por variables `WHATSAPP_MODO` y `SMS_MODO` (`stub` / `prueba` / `real`), igual que `SMTP` en P07.
- Modo `prueba`: usa las cuentas gratuitas de los proveedores sin contratar nada: el **número de prueba de WhatsApp Cloud API** de Meta (envía solo a números destinatarios verificados en el panel de Meta, máximo 5) y la **cuenta de prueba de Twilio** (envía solo a números verificados). Documentar en `docs/operacion/mensajeria.md` paso a paso cómo la usuaria crea esas cuentas de prueba, qué variables llenar en `.env` y sus limitaciones. Claude Code **no** crea cuentas ni pide contraseñas: deja la guía y espera a que la usuaria cargue las variables.
- Webhooks: `POST /api/mensajeria/webhook/meta` (con verificación del `hub.verify_token` y de la firma `X-Hub-Signature-256`) y `POST /api/mensajeria/webhook/twilio` (con validación de firma de Twilio): actualizan estados de entrega/lectura y registran mensajes entrantes. En desarrollo local los webhooks no son alcanzables desde internet: dejar un endpoint de simulación de webhook para pruebas y documentar que en producción se configuran con la URL pública (paso final).
- Reintentos con espera exponencial en Celery; errores permanentes (número inválido, plantilla rechazada, usuario dado de baja) no se reintentan y hacen caer al siguiente canal de la preferencia (por ejemplo, WhatsApp falla → correo).
- Límite de tasa por proveedor y por tenant.

### 3. Integración con `notificar()`

- Quitar `whatsapp` y `sms` de `FASE_2`. `notificar()` decide el canal con este orden: preferencia del usuario por evento → configuración del tenant/prestador (`mensajeria_configuracion`) → consentimiento y teléfono verificado → horario de silencio (salvo eventos críticos: `SLA_INCUMPLIDO`, alertas de severidad crítica, aprobación por vencer) → tope mensual. Si no puede usar WhatsApp/SMS, cae al siguiente canal y lo registra con su motivo.
- Plantillas por evento para todos los eventos que hoy usan `notificar()` (folio creado/autorizado/asignado/en camino/cerrado, aprobación pendiente, rechazo, minuta disponible, cotización enviada/por vencer, trabajo especial por validar, preventivo por reprogramar, alertas, certificación por vencer, restablecimiento de contraseña solo por correo). Las de WhatsApp se redactan en español, categoría `utility`, con variables y botón de enlace a la pantalla exacta de ACMA (folio, minuta, aprobación). Las de SMS, en un solo segmento cuando sea posible (160 caracteres GSM-7; avisar si lleva acentos y pasa a UCS-2 con 70 caracteres) y con enlace corto propio de ACMA (`/l/{codigo}` que redirige a la pantalla, sin servicio externo).
- **Minuta por WhatsApp (§7.5):** resumen de máximo 5 puntos con los más críticos del día (contadores en rojo, hallazgos de urgencia alta/crítica, preventivos con retraso, cotizaciones por vencer) y botón al PDF completo con enlace firmado de corta duración. Si no hay nada crítico, un mensaje breve de «sin pendientes críticos» con el enlace.
- Respuestas rápidas en WhatsApp (dentro de la ventana de 24 h): botones «Ver folio» y, para aprobaciones, «Aprobar» / «Rechazar» que **no ejecutan la acción directamente**: abren ACMA en la pantalla de aprobación con sesión normal y doble factor si aplica (anotar como decisión de seguridad: ninguna acción crítica se ejecuta solo con un mensaje).

### 4. Consentimiento, privacidad y costo

- Alta de teléfono por el propio usuario en su perfil, con verificación por código de un solo uso enviado por el mismo canal (en modo stub el código aparece en la bitácora). Consentimiento explícito por canal, con fecha; palabra «BAJA» en WhatsApp o SMS da de baja el canal de inmediato y «ALTA» lo reactiva (anotar el texto exacto).
- Aviso de privacidad: agregar el texto de uso del teléfono para notificaciones operativas en la pantalla de perfil (texto marcado para revisión del área legal en `docs/decisiones_para_validar.md`).
- Ningún dato sensible en el cuerpo del mensaje: sin montos, sin datos personales de terceros, sin evidencias; solo identificador del folio, sucursal, estado y enlace. Validar en pruebas que las plantillas no incluyen campos financieros.
- Auditoría (P11a): registrar envío, entrega, lectura, baja y alta; el teléfono en bitácoras siempre como hash o enmascarado (`+52 871 ••• ••34`).
- Costo: `costo_estimado` por mensaje con tarifas configurables en `mensajeria_configuracion` (sin consultar precios del proveedor), contador mensual por tenant, alerta `MENSAJERIA_CONSUMO_ALTO` al llegar al porcentaje configurado y bloqueo de no críticos al llegar al tope (anotar).
- Alerta `MENSAJERIA_PLANTILLA_RECHAZADA` cuando el proveedor rechace o pause una plantilla.

### 5. Endpoints

`/api/mensajeria`: configuración por tenant/prestador, plantillas (CRUD, vista previa con datos de ejemplo, exportación en el formato que pide Meta para someterlas a aprobación), envíos con filtros y estado, consumo del mes, prueba de envío a un número verificado (solo administradores), webhooks y simulación de webhook. En `/api/usuarios/me`: teléfono, verificación, consentimientos y bajas.

### 6. Frontend

- Perfil del usuario: teléfono móvil con verificación, consentimiento por canal y aviso de privacidad; preferencias por evento (P07) con WhatsApp y SMS ya habilitados.
- Nueva sección «Mensajería» en Configuración (Superadmin, Admin prestador y Admin empresa para su tenant): canales activos, eventos por canal, horario de silencio, tope mensual y consumo con barra y texto; plantillas con estado de aprobación y vista previa tal como se verá en WhatsApp; bitácora de envíos con estado (en cola, enviado, entregado, leído, fallido) y motivo del cambio de canal.
- Quitar las leyendas «canal Fase 2» de WhatsApp y SMS.
- Detalle del folio y de la minuta: indicar por qué canales se notificó y su estado de entrega.

### 7. Seed y pruebas

- Seed: teléfonos ficticios verificados para Admin UN, Admin empresa, Despachador y Técnico demo (números con formato válido pero de rango de prueba), consentimientos, configuración con WhatsApp y SMS activos para el tenant demo, todas las plantillas en estado `aprobada` en modo stub, y 30 envíos de ejemplo con estados variados.
- Backend (`tests/test_mensajeria_proveedores.py`, `tests/test_mensajeria_notificar.py`, `tests/test_mensajeria_minuta.py`, `tests/test_mensajeria_consentimiento.py`, `tests/test_mensajeria_webhooks.py`): selección de canal con cada regla (preferencia, consentimiento, teléfono no verificado, horario de silencio, crítico que ignora el silencio, tope); caída al siguiente canal con motivo; reintentos solo en errores temporales; plantillas sin datos financieros; minuta con máximo 5 puntos y enlace firmado; SMS de un segmento y cálculo de segmentos con acentos; «BAJA» y «ALTA»; verificación de firma de webhooks de Meta y Twilio (válida e inválida); estados entregado/leído; botón de aprobación que no ejecuta la acción; teléfono cifrado y enmascarado en bitácoras; aislamiento entre tenants; RLS forzada en las tablas nuevas. Ninguna prueba llama a Meta ni a Twilio de verdad.
- Frontend: verificación del teléfono, preferencias con WhatsApp, vista previa de plantilla, bitácora de envíos.
- `pytest`, `vitest`, `tsc --noEmit` y `npm run build` en verde, con los servidores de desarrollo apagados durante la suite completa.

## Reglas (vigentes)

1. Seguir el Documento de Diseño v2.5; lo no definido se anota en `CONTEXTO.md` como decisión pendiente de validación.
2. Multitenancy validado en servicio además de RLS.
3. Sin contratar proveedores: modo `stub` por defecto y modo `prueba` con cuentas gratuitas que configura la usuaria; nunca pedir contraseñas ni tokens por chat.
4. Identificadores en español sin acentos.
5. Cerrar con `CONTEXTO.md` (avance F2-02 ✅; sección «WhatsApp y SMS (F2-02)» con la regla de selección de canal, las plantillas y lo que falta para producción: aprobación de plantillas por Meta, número de negocio verificado, URL pública de webhooks) y `BITACORA.md` actualizados.
6. No cambiar el stack.
7. No correr la suite completa con los servidores de desarrollo encendidos.
8. Commits solo locales; si el trabajo es largo, «F2-02 (1/2) backend» y «F2-02 (2/2) frontend».

## Al terminar

Resumen en español con: tablas de la migración 0014, endpoints, lista de plantillas por evento con su texto, regla de selección de canal, qué debe hacer la usuaria para probar con las cuentas gratuitas, pendientes para producción, decisiones pendientes nuevas y conteo de pruebas.
