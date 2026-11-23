# ACMA · rastreo de USUARIOS (PC, Android e iPhone)

Este módulo **no rastrea folios**. Un usuario autenticado puede activar
voluntariamente el envío de su última ubicación desde cualquier navegador
con geolocalización disponible en Windows/macOS, Android o iPhone.

- Al iniciar sesión en ACMA, una ventana pide **Activar mi ubicación**
  o **Ahora no**. El navegador solicita permiso GPS únicamente si acepta;
  nunca se activa a distancia. También puede hacerlo después desde
  menú / perfil → **Mi ubicación**.
- **Operaciones → Rastreo de usuarios en tiempo real** es una pantalla
  exclusiva de personas: no contiene seguimiento de folios, técnicos por
  jornada, indicadores SLA ni alertas de órdenes.
- La lista `GET /api/operacion/usuarios-rastreo` incluye **todas las
  cuentas habilitadas de la organización visible al administrador**,
  aunque no compartan GPS; es distinta de "conectado ahora".
- Cada fila tiene botón **Rastrear usuario**. Si el GPS está activo,
  el marcador verde sigue la última coordenada; de lo contrario muestra
  **Sin GPS** y explica que el usuario debe aceptar desde su dispositivo.
- El administrador ve los usuarios de su propio prestador y el superadmin
  todas las cuentas; no puede iniciar la cámara ni el GPS de terceros.
- La consulta se actualiza aproximadamente cada 10 segundos; los equipos
  envían GPS cada 12–15 segundos mientras ACMA está visible.
- La posición deja de ser visible tras 90 segundos sin nueva lectura.
- Solo se conserva el último punto de cada usuario: no se almacena un
  historial de recorrido.

## Base de datos

**No unir a main ni desplegar antes de aplicar la migración 0020.**
- Alembic: `cd backend && alembic upgrade head` con `DATABASE_MIGRATIONS_URL`
  del dueño del esquema y 0019 ya aplicada.
- En Supabase SQL Editor (esquema acma) está la opción manual
  `sql/ACMA_RASTREO_USUARIOS.sql`. No mezclar ejecución manual con Alembic
  sin reconciliar el historial de revisiones.

El SQL crea `acma.rastreo_usuarios` con RLS y permisos. No altera folios.
La conexión a Supabase disponible en este chat no contiene el proyecto ACMA,
por lo que la migración real no fue aplicada.

## Limitaciones técnicas

Safari iOS, Chrome Android y WebView Flutter pueden interrumpir GPS cuando
la pantalla se apaga o la página deja de estar visible. Desde PC la posición
depende de los servicios de ubicación del sistema y puede ser aproximada.
ACMA mantiene la compartición al navegar por sus pantallas mientras la\npestaña siga visible, con botón Detener GPS siempre disponible.\nNo se ha implementado seguimiento nativo en segundo plano.

Los registros expirados se excluyen del mapa, aunque permanecen físicamente
hasta una limpieza operativa posterior; no contienen historial de puntos.
