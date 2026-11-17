# ACMA — Mailjet HTTPS para recuperación de contraseña (sin comprar dominio)

Integración opcional que mantiene el código existente de Resend, SMTP, Supabase,
usuarios, MFA y enlaces de restablecimiento. Mailjet se usa **solo** cuando
`CORREO_PROVEEDOR=mailjet` (valor predeterminado: `auto`, que conserva
Resend > SMTP > modo simulación).

## 1. Preparar Mailjet

1. Entra a https://app.mailjet.com/ y crea/confirma tu cuenta.
2. Ve a **Account Settings → Senders & Domains** (o **Add a Sender Domain or Address**).
3. Elige **Add a Sender Address**, por ejemplo `zaidfarjat@gmail.com`.
4. Confirma el enlace que Mailjet manda a esa misma dirección. Debe quedar **Active**.
   No es necesario comprar dominio para verificar **una dirección individual**.
5. En **Account Settings → API Keys** copia la **Public API Key** y la
   **Private/Secret API Key** a un gestor de contraseñas. No las publiques ni
   las pegues en chats, GitHub ni capturas.
6. Verifica que tu cuenta esté habilitada para correo transaccional real.
   La verificación de remitente no garantiza que el proveedor acepte el envío.

**Advertencia:** Mailjet avisa que los remitentes Gmail/Hotmail/Yahoo pueden
tener mala entregabilidad o resultar bloqueados por controles de autenticación.
Sirve como opción sin dominio, pero para producción con uso frecuente se
recomienda un dominio propio con SPF, DKIM y DMARC.

## 2. Variables en Railway (servicio acme- → Variables)

```dotenv
CORREO_PROVEEDOR=mailjet
MAILJET_API_KEY=TU_PUBLIC_API_KEY_DE_MAILJET
MAILJET_SECRET_KEY=TU_PRIVATE_API_KEY_DE_MAILJET
MAILJET_FROM=ACMA <zaidfarjat@gmail.com>
APP_URL_PUBLICA=https://acme-production-ee493e67.up.railway.app
```

Usa el email que realmente hayas validado en Mailjet en `MAILJET_FROM`.
No pongas comillas alrededor del valor en la pantalla de variables de Railway.
Conserva las variables PostgreSQL, Supabase, JWT, cifrado y demás secretos
existentes. No necesitas SMTP_HOST/SMTP_PORT para Mailjet API HTTPS.

**Resend se conserva**. Aunque `RESEND_API_KEY` permanezca configurado,
al seleccionar Mailjet, ACMA usará únicamente Mailjet. Para regresar al
comportamiento anterior elimina `CORREO_PROVEEDOR` o ponlo en `auto`.

Guarda las variables en Railway y aplica el despliegue pendiente.

## 3. Prueba completa (en un usuario activo)

1. Comprueba que Railway tenga un despliegue **Active**.
2. Abre https://acme-production-ee493e67.up.railway.app .
3. Entra a **¿Olvidaste tu contraseña?** y escribe el correo de un
   usuario **activo** de ACMA.
4. Espera el enlace en el destinatario; revisa spam/promociones y el
   historial de envíos/transaccionales de Mailjet.
5. Abre la página `/restablecer?token=...` antes de 30 minutos,
   establece una contraseña distinta a las anteriores y vuelve a iniciar sesión.

La solicitud responde de manera genérica exista o no el correo para no
revelar cuáles usuarios hay registrados. Solo los usuarios activos reciben
enlaces; si Mailjet falla, ACMA registra un diagnóstico resumido sin revelar
claves, correos, HTML ni enlaces.

## 4. Qué buscar si no llega

En **Railway → servicio acme- → Deployments → View Logs**:

- `mailjet:configuracion_incompleta`: falta alguna variable, o el remitente no es válido.
- `mailjet:http_401`: clave pública o secreta incorrecta / cuenta inactiva.
- `mailjet:http_403`: Mailjet prohíbe el envío (cuenta o remitente).
- `mailjet:http_429`: límite de llamadas.
- `mailjet:mensaje_rechazado`: Mailjet contestó HTTP 2xx pero no aceptó todos los mensajes.
- `mailjet:red_ConnectError`: error de red HTTPS.

Un HTTP 200 del endpoint `/api/auth/restablecer/solicitar` **no confirma
entrega**. Consulta el panel de Mailjet para ver los eventos de aceptación,
bloqueo, rebote y entrega. Nunca compartas un enlace de recuperación.

## 5. Verificaciones de código (sin credenciales ni correos reales)

Desde la raíz del repositorio con Python y `httpx` instalado:

```bash
python scripts/test_mailjet_api.py
python scripts/test_resend_api.py
```

Los tests usan `httpx.MockTransport` y no hacen llamadas reales. No hay
migraciones de BD ni cambios en tablas, usuarios, Supabase, UI o MFA.

## Documentación oficial

- https://dev.mailjet.com/docs/email-api/send-api-v31/send-basic-email
- https://dev.mailjet.com/docs/email-api/email-api-overview/authentication
- https://documentation.mailjet.com/hc/en-us/articles/360042759253-How-to-add-a-sender-address
