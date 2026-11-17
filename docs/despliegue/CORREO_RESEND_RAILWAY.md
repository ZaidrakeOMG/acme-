# ACMA — correos de restablecimiento con Resend y Railway

## ¿Por qué no llegan?

- El backend ACMA tiene un emisor SMTP, pero sin proveedor configurado opera
  en **modo simulación (stub)**: guarda el correo como archivo; no lo entrega.
- Railway Free, Trial y Hobby **bloquean salida SMTP**. Conectar Gmail,
  Outlook, IONOS o SMTP de Resend por puerto 587/465 no funciona en esos planes.
- El despliegue sencillo de ACMA no tiene Redis ni Celery. Anteriormente la
  solicitud de restablecimiento quedaba pendiente de una tarea que no corría.
- Esta integración añade la API **HTTPS** de Resend, compatible con Railway
  Free, y envía las recuperaciones **durante la solicitud**. Otros envíos
  programados siguen necesitando worker/beat (o `NOTIFICACIONES_ENVIO_INLINE`
  si se decide activar envíos de otros módulos).

## Pasos en Resend

1. Crea cuenta en https://resend.com y entra a **Domains → Add Domain**.
2. Verifica un dominio que controles (por ejemplo,
   `notificaciones.dominio-del-cliente.com`). En el proveedor DNS, que
   puede ser IONOS, agrega **exactamente** los registros SPF/DKIM que
   proporcione Resend; los nombres y valores dependen de esa cuenta.
   No borres los registros MX actuales ni modifiques el correo corporativo.
3. Una vez que el estado del dominio sea **Verified**, abre
   **API Keys → Create API Key** (permiso de envío) y copia la clave
   en un gestor seguro. **Nunca la envíes por chat ni la subas a GitHub.**
4. Elige un remitente de ese dominio verificado, por ejemplo
   `ACMA <no-reply@notificaciones.dominio-del-cliente.com>`.

## Configuración en Railway

En **Proyecto → servicio acme- → Variables**, agrega:

```dotenv
RESEND_API_KEY=LA_CLAVE_REAL_PRIVADA_DE_RESEND
RESEND_FROM=ACMA <no-reply@notificaciones.dominio-del-cliente.com>
```

Reemplaza ambos valores por los reales de tu cuenta Resend. No añadas
comillas alrededor del valor del remitente en Railway. **No es necesario
configurar SMTP_HOST, SMTP_PORT, SMTP_USER ni SMTP_PASSWORD** para Resend API.
Se mantiene la configuración PostgreSQL, Supabase, JWT y cifrado existente.
Guarda y aplica los cambios pendientes con **Deploy**.

En el flujo de recuperación de contraseña, `/api/auth/restablecer/solicitar`
usa el remitente `RESEND_FROM` y la URL que Railway establece por
`RAILWAY_PUBLIC_DOMAIN`: el enlace debe comenzar con
`https://acme-production-ee493e67.up.railway.app/restablecer?token=...`.

No se generan ni se exponen nuevos usuarios, contraseñas o claves de
Supabase. El token solo sirve una vez y expira a los **30 minutos**.

## Prueba real

1. Verifica que Railway muestre el despliegue nuevo como **Active**.
2. En ACMA pulsa **¿Olvidaste tu contraseña?** y escribe un correo de
   un usuario activo que controles.
3. Revisa bandeja principal y spam. Consulta en Resend **Emails / Logs**
   si se aceptó el mensaje o hubo error.
4. Revisa **Railway → Deploy Logs**. Si ves
   `resend:http_403`, revisa dominio/remitente/credencial;
   `resend:http_429` indica límite de tasa;
   `resend:red_ConnectError` indica problema de conexión HTTPS.
   Los mensajes de error no muestran contraseñas ni tokens.
5. Pulsa el enlace dentro del correo y establece una contraseña
   nueva que cumpla la política de seguridad; inicia sesión y MFA.

**La respuesta de ACMA es intencionalmente genérica**, tanto si el
correo existe como si no, para evitar enumeración de usuarios. La API
de Resend puede aceptar un envío sin que el correo termine en bandeja:
para verificar entrega, revisa el panel de Resend.

## Importante para otros correos

Esta corrección soluciona el canal HTTP y el envío inmediato de
**restablecimientos** sin cola. El resto de notificaciones que actualmente
usan Celery seguirán pendientes mientras no existan Redis/worker/beat.
Para activarlos es necesario configurar servicios Railway separados,
colas y pruebas.

## Documentación pública

- Railway: https://docs.railway.com/networking/outbound-networking
- Resend: https://resend.com/docs/api-reference/emails/send-email
- Dominios Resend: https://resend.com/docs/dashboard/domains/introduction
- Precios: https://resend.com/pricing
