# ACMA · rastreo de USUARIOS (PC, Android e iPhone)

Este módulo **no rastrea folios**. Un usuario autenticado puede activar
voluntariamente el envío de su última ubicación desde cualquier navegador
con geolocalización disponible en Windows/macOS, Android o iPhone.

- Menú o perfil de ACMA → **Mi ubicación** → **Activar mi ubicación**.
- Los perfiles de Operaciones autorizados ven **Rastrear usuarios en tiempo real**
  y eligen a una persona por nombre, independientemente de sus folios.
- El mapa dibuja marcadores verdes para los usuarios que consienten compartir.
  Se consulta cada 10 segundos; los dispositivos envían lectura aprox. cada 15 s.
- **Dejar de compartir** elimina la ubicación actual de la sesión activa.
- Si no llega un punto válido, deja de ser visible a los 90 segundos.
- Se guarda solo la última ubicación por usuario, NO el historial del recorrido.
- Seguridad: el servidor toma la identidad del JWT del usuario, nunca un
  usuario_id suministrado por el cliente. RLS permite lectura al propio
  usuario y a administradores autorizados dentro de su organización.

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
