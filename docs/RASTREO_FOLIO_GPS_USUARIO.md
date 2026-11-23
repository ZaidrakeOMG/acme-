# ACMA · GPS voluntario del usuario por folio (Android y iPhone)

El boton **Rastrear** de Operaciones busca primero una ubicacion que el
usuario del folio haya decidido compartir desde su propio telefono.
No enciende el GPS de terceros, no rastrea usuarios sin consentimiento y no
sustituye el sistema de jornadas de los tecnicos.

## Preparacion de Supabase

**Antes de publicar esta rama**, aplicar la migracion 0020 en la misma BD
PostgreSQL y esquema que usa Railway:

- Si usas Alembic con `DATABASE_MIGRATIONS_URL` y el rol `acma_owner`, ejecuta
  `alembic upgrade head` desde `backend/`. Debes haber aplicado 0019.
- Si solo tienes SQL Editor de Supabase, el archivo
  `sql/ACMA_RASTREO_USUARIO_FOLIO.sql` crea la tabla y las politicas RLS en
  el esquema `acma`. El SQL se ejecuta con una transaccion.
  No ejecutar el SQL manual y luego Alembic 0020 a ciegas: hay que conciliar
  propietario y version de la migracion. Comprueba `SELECT version_num
  FROM acma.alembic_version` y pide ayuda para regularizar.
- Verifica: `SELECT column_name FROM information_schema.columns
  WHERE table_schema='acma' AND table_name='rastreos_usuario_folio'`.

La tabla conserva solo la **ultima posicion** por folio y usuario, no un
historial de trayectos. Un marcador deja de mostrarse si pasan 90 segundos sin
datos. Al pulsar Detener, se elimina el registro vigente. Los registros
caducados dejan de ser visibles, pero necesitan purga operativa si el usuario
cierra el navegador sin poder enviar Detener.

## Flujo funcional

1. El usuario autenticado que capturo el folio, o su tecnico asignado, abre
   el detalle de **su** folio desde Android/iPhone (Safari, Chrome o WebView).
2. Toca **Compartir mi ubicacion ahora** y autoriza el permiso del dispositivo.
3. Mientras mantiene abierta la pantalla, ACMA envia lecturas GPS al servidor
   aproximadamente cada 15 segundos. Si no hay lectura reciente, no reutiliza
   puntos obsoletos como si fueran actuales.
4. En **Operaciones en tiempo real**, el despachador selecciona ese folio:
   marcador **verde** = usuario compartiendo GPS; azul = tecnico en jornada;
   ambar = sucursal fija; rojo = GPS de pruebas de TestBot.
5. Al dejar la pantalla, ocultar la pagina o pulsar **Dejar de compartir**,
   cesan las solicitudes y se solicita borrar el registro. Si el dispositivo
   pierde conexion, el marcador desaparece al caducar.

## Limitaciones

- Requiere HTTPS, permiso de ubicacion y sesion autenticada.
- Los navegadores moviles y la WebView Flutter no garantizan localizacion con
  pantalla bloqueada o con la app en segundo plano. Para rastreo continuo
  verdadero en segundo plano se necesita una implementacion nativa separada,
  con permiso destacado y aceptacion clara del usuario.
- Solo superadmin y personal autorizado del prestador (despachador, mesa
  control o admin prestador) puede visualizar ubicaciones compartidas.
  El usuario puede consultar solo su propio estado de comparticion.
- El acceso queda limitado por folio y RLS; no hay endpoint para activar el
  GPS de otros usuarios.
