# WhatsApp y SMS en ACMA — guía de operación (F2-02)

Esta guía es para ti, Liliana: explica cómo quedó el canal, qué puedes probar **sin contratar nada** y qué hay que
hacer el día que quieras mandar mensajes de verdad. ACMA **no** crea cuentas ni pide contraseñas: tú creas la
cuenta, copias dos o tres valores al archivo `.env` y reinicias la API.

---

## 1. Los tres modos

Cada canal tiene su propio modo, igual que el correo en P07:

| Variable | Valores | Qué hace |
|---|---|---|
| `WHATSAPP_MODO` | `stub` (por defecto) · `prueba` · `real` | De dónde sale el WhatsApp |
| `SMS_MODO` | `stub` (por defecto) · `prueba` · `real` | De dónde sale el SMS |

* **`stub`** — nada sale de la máquina. El mensaje se renderiza, se guarda en la bitácora de envíos y queda como
  archivo de vista previa en el almacenamiento (`mensajeria/AAAA/MM/DD/…txt`). Lo ves en
  **Mensajería → Bitácora de envíos** y en `GET /api/mensajeria/simulados`. Es el modo con el que se desarrolló y se
  probó todo: el seed deja las plantillas como `aprobada` porque no hay nada que aprobar.
* **`prueba`** — usa las cuentas **gratuitas** de Meta o de Twilio. Entregan solo a números que tú verifiques en su
  panel (Meta: hasta 5; Twilio: los que confirmes con un código). Sirve para ver el mensaje en tu propio celular.
* **`real`** — cuenta de pago, número de negocio verificado y plantillas aprobadas. Es el paso final del proyecto.

Si el modo es `prueba` o `real` y falta una credencial, ACMA **no se queda sin canal**: usa el simulado, lo escribe
en el log y la bitácora dice `proveedor: stub`. Así una variable mal escrita nunca deja a nadie sin aviso.

---

## 2. WhatsApp con la cuenta de prueba de Meta (gratis)

Lo que Meta te va a pedir: una cuenta de Facebook y aceptar sus términos de desarrollador. No hay que dar tarjeta.

1. Entra a <https://developers.facebook.com/> → **Mis aplicaciones** → **Crear aplicación** → tipo **Empresa**.
2. En la aplicación, agrega el producto **WhatsApp**. Meta te regala un **número de prueba** y un
   **token temporal de 24 horas**.
3. En *WhatsApp → Primeros pasos* copia:
   * **Identificador del número de teléfono** (`Phone number ID`) → `WHATSAPP_NUMERO_ID`
   * **Token de acceso temporal** → `WHATSAPP_TOKEN`
4. En la misma pantalla, en «Para», **agrega tu celular como destinatario de prueba** y confirma el código que te
   llega por WhatsApp. El número de prueba de Meta **solo entrega a esos destinatarios** (máximo 5).
5. En *Configuración de la aplicación → Básica* copia la **clave secreta de la aplicación** →
   `WHATSAPP_APP_SECRET` (con eso ACMA valida la firma `X-Hub-Signature-256` de los webhooks).
6. Inventa un texto cualquiera para `WHATSAPP_VERIFY_TOKEN` (el mismo que escribirás en el webhook de Meta).

En `.env`:

```dotenv
WHATSAPP_MODO=prueba
WHATSAPP_PROVEEDOR=meta_cloud
WHATSAPP_NUMERO_ID=123456789012345
WHATSAPP_TOKEN=EAAG...   # el temporal vence en 24 h; para algo permanente hay que generar uno de sistema
WHATSAPP_APP_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
WHATSAPP_VERIFY_TOKEN=lo-que-tu-quieras-aqui
```

**Límites de la cuenta de prueba que conviene tener en mente**

* El token temporal **vence en 24 horas**: para pruebas más largas hay que crear un usuario del sistema y un token
  permanente (Meta → *Configuración empresarial → Usuarios del sistema*).
* Solo entrega a los destinatarios verificados.
* Con el número de prueba Meta **permite enviar las plantillas de muestra** y las que tú crees y apruebe; una
  plantilla nueva tarda de minutos a horas en aprobarse.
* Fuera de la ventana de 24 h posterior a un mensaje del usuario, **solo se puede mandar plantilla**, no texto
  libre. ACMA ya lo respeta: los avisos salen como plantilla y el acuse de «BAJA»/«ALTA» como texto libre, que
  siempre ocurre justo después de que el usuario escribió.

---

## 3. SMS con la cuenta de prueba de Twilio (saldo de regalo)

1. Regístrate en <https://www.twilio.com/try-twilio> (te dan saldo de prueba; no hace falta contratar).
2. En la consola copia **Account SID** y **Auth Token**.
3. En *Phone Numbers → Verified Caller IDs* **verifica tu celular**: la cuenta de prueba solo entrega a números
   verificados y antepone un aviso al texto del mensaje.
4. Toma el número que Twilio te asignó (o el **Messaging Service SID**, que empieza con `MG`).

```dotenv
SMS_MODO=prueba
SMS_PROVEEDOR=twilio
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_REMITENTE_SMS=+15005550006
# Opcional: WhatsApp por Twilio en lugar de Meta (el «sandbox» de Twilio).
TWILIO_REMITENTE_WHATSAPP=whatsapp:+14155238886
```

Twilio también puede entregar WhatsApp (su *sandbox*): pon `WHATSAPP_PROVEEDOR=twilio` y únete al sandbox desde tu
celular con la palabra que te indique su consola.

---

## 4. Después de llenar el `.env`

1. Reinicia la API (`uvicorn`) y el worker de Celery: las variables se leen al arrancar.
2. Entra como **Admin prestador** a **Mensajería → Canales y consumo** y revisa que arriba diga
   `WhatsApp: modo prueba (meta_cloud)`.
3. En tu perfil (**Notificaciones → Mi celular**) registra tu celular, pide el código y verifícalo. En modo `prueba`
   el código llega de verdad a tu teléfono.
4. Usa **Prueba de envío** (en «Para usarlo de verdad») con tu propio número verificado.

Si algo no llega, la bitácora de envíos dice el código de error del proveedor y su texto: ahí se ve si el número no
estaba verificado, si la plantilla no estaba aprobada o si el token venció.

---

## 5. Webhooks (estados de entrega y respuestas del usuario)

Los estados «entregado» y «leído», y los mensajes que el usuario te escriba («BAJA», «ALTA», los botones), llegan
por webhook. **En tu máquina local el proveedor no puede llamar a ACMA**: no hay URL pública.

* Mientras desarrollas: usa **Bitácora de envíos → Ver → Simular entrega**, o
  `POST /api/mensajeria/webhook/simular` (solo administradores y nunca en producción).
* Cuando ACMA esté publicado en un dominio con HTTPS, configura:
  * **Meta** → *WhatsApp → Configuración → Webhooks*: URL `https://TU-DOMINIO/api/mensajeria/webhook/meta`,
    token de verificación = `WHATSAPP_VERIFY_TOKEN`, y suscríbete al campo **messages**.
  * **Twilio** → en el número o el Messaging Service, *A message comes in* y *Status callback URL*:
    `https://TU-DOMINIO/api/mensajeria/webhook/twilio`.
* ACMA valida la firma de los dos proveedores y responde 403 si no cuadra. Sin `WHATSAPP_APP_SECRET` o sin
  `TWILIO_AUTH_TOKEN`, el webhook queda cerrado a propósito.
* Si quieres probar los webhooks de verdad sin publicar nada, un túnel como `cloudflared tunnel --url
  http://localhost:8000` da una URL temporal; es opcional y no hace falta para el piloto.

---

## 6. Plantillas: cómo se aprueban en Meta

WhatsApp no deja mandar lo que quieras: cada aviso viaja en una **plantilla aprobada** de categoría *utility*.

1. **Mensajería → Plantillas** lista las de ACMA con su estado. Las de la plataforma son la base; cuando editas
   una, ACMA guarda **una copia tuya** en borrador y deja intacta la base.
2. Abre la plantilla, revisa la vista previa (se ve como en WhatsApp, con sus botones) y presiona
   **Exportar para Meta**: te da el JSON con `name`, `language`, `category` y `components`.
3. En Meta (*WhatsApp Manager → Plantillas de mensajes → Crear*) pega ese contenido y sométela. Meta responde en
   minutos u horas.
4. Cuando la aprueben, cambia el estado de la plantilla en ACMA a **Aprobada**. Si la rechazan o la pausan, pon el
   motivo: ACMA levanta la alerta `MENSAJERIA_PLANTILLA_RECHAZADA`, deja de usar esa plantilla y los avisos caen al
   siguiente canal hasta que la corrijas.

Reglas que las plantillas de ACMA ya cumplen y que conviene no romper al editarlas:

* **Nada sensible en el mensaje**: ni montos, ni datos de terceros, ni evidencias. Solo folio, sucursal, estado y
  el enlace. Una prueba automática revisa el catálogo completo.
* Los botones **no ejecutan nada**: «Aprobar» y «Rechazar» contestan con el enlace a la pantalla de aprobación,
  donde el usuario entra con su sesión y su doble factor si aplica.
* Los **SMS se escriben sin acentos**: así caben 160 caracteres en un segmento (con acentos el mensaje pasa a UCS-2
  y se queda en 70, y cuesta el doble). La vista previa te lo avisa.

---

## 7. Lo que decide cuándo sale un mensaje

En este orden, y el motivo del «no» queda escrito en la notificación y en la bitácora:

1. **Preferencia del usuario** por evento (Notificaciones → Preferencias).
2. **Canal activo** en la configuración del prestador o del tenant.
3. **Lista de eventos** del canal, si la llenaste (vacía = todos).
4. **Teléfono verificado y consentimiento vigente** del destinatario.
5. **Horario de silencio**, salvo los eventos críticos (aprobación pendiente o bloqueada, SLA en riesgo o
   incumplido, severidad crítica, trabajo especial de urgencia).
6. **Tope mensual** de mensajes: al alcanzarlo solo salen los críticos.

Cuando no puede salir, el aviso **cae al siguiente canal** (push, correo o bandeja). Nadie se queda sin enterarse
por un problema de mensajería.

---

## 8. Costo

ACMA **no consulta precios** del proveedor: estima con las tarifas que pongas en *Canales y consumo*
(`tarifa_whatsapp`, `tarifa_sms` y la moneda). El contador del mes es por prestador y por tenant, con alerta
`MENSAJERIA_CONSUMO_ALTO` al llegar al porcentaje configurado (80 % por defecto) y bloqueo de los no críticos al
llegar al tope. Un SMS de dos segmentos cuesta el doble, y lo que no salió no se cobra.

---

## 9. Palabras que el usuario puede escribir

| Palabra | Efecto |
|---|---|
| `BAJA` | Da de baja ese canal **de inmediato** y manda un acuse por el mismo canal. |
| `ALTA` | Vuelve a activarlo. |

Funciona en mayúsculas o minúsculas, con o sin acentos, por WhatsApp o por SMS. La baja también se puede hacer
desde **Notificaciones → Mi celular**, y queda con su fecha en la bitácora de auditoría.

---

## 10. Pendientes para producción

- [ ] Plantillas aprobadas por Meta (categoría *utility*).
- [ ] Número de negocio verificado en WhatsApp Business (y token permanente, no el de 24 h).
- [ ] URL pública con HTTPS y webhooks configurados en Meta y en Twilio.
- [ ] Tarifas reales del proveedor en la configuración, y tope mensual acordado con Dirección.
- [ ] Revisión del área legal del aviso de privacidad del teléfono (pregunta 31 de
      `docs/decisiones_para_validar.md`).
