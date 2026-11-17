# ACMA Android — Ubicación de personal (uso voluntario)

## Qué hace

- Solo funciona dentro de la **aplicación Android ACMA**, no en una pestaña web normal.
- Cada persona tiene que pulsar **Comenzar a compartir** y autorizar la ubicación en Android.
- Solo se actualiza mientras la pantalla **Ubicación de personal** está abierta y visible. No solicita `ACCESS_BACKGROUND_LOCATION` ni ejecuta un servicio GPS permanente.
- Solo se guarda la **última posición**, no un historial ni recorridos; la señal enviada se actualiza aproximadamente cada 30 segundos. Si no hay nueva señal en 5 minutos, el mapa la oculta.
- **Detener y borrar ubicación** elimina la última posición de la base. Al cerrar la pantalla se detiene el GPS e intenta avisar al servidor mediante una solicitud corta; Android puede terminar el proceso abruptamente, por lo que el mapa expira igualmente las señales viejas.
- Un usuario con permiso de **visor** ve únicamente personas de su empresa/organización y que aceptaron compartir. El Superadmin ve el mapa y puede habilitar/revocar permiso por persona.
- Los permisos de lectura no autorizan compartir la ubicación de otra persona ni abrir rutas ajenas.
- El mapa utiliza **Leaflet y OpenStreetMap**, con opción **Abrir en Google Maps** sobre la posición seleccionada.

## Antes de habilitar en producción

**No fusionar este PR antes de aplicar la migración 0019 al proyecto correcto de Supabase y comprobar RLS.** La cuenta Supabase que se encuentra conectada al entorno de desarrollo puede no ser la misma base de datos ACMA. No ejecutar SQL sobre otra base.

1. Identificar el proyecto correcto de Supabase de ACMA y hacer un respaldo verificado.
2. Utilizar las mismas variables de DB que ACMA ya tiene. Para migrar se requiere `DATABASE_MIGRATIONS_URL` con rol **propietario** del esquema; el rol `acma_api` no debe poder alterar tablas.
3. Aplicar Alembic desde un entorno privado con `backend/` como directorio de trabajo:
   `python -m alembic upgrade head`
4. Verificar que `alembic_version` sea `0019`, que existan `ubicaciones_movil` y `ubicacion_movil_visores`, y que **FORCE ROW LEVEL SECURITY** esté activado para ambas. Confirmar que el rol de la API tenga permisos y las claves de Supabase `anon` y `authenticated` no puedan consultarlas.
5. Probar con cuentas ficticias de **dos organizaciones distintas**:
   - Sin consentimiento no se acepta GPS.
   - Sin permiso de visor el mapa devuelve 403.
   - Con permiso el visor solo ve gente de la misma organización.
   - Al revocar permiso se pierde el acceso inmediatamente.
   - Al detener se borra la última posición.
   - Una posición con más de cinco minutos no aparece.
6. Solo después fusionar y desplegar el PR desde `main`. Generar e instalar **nueva APK**: la WebView Android anterior no anuncia el módulo mediante `acma-android-ready`.
7. Validar permisos GPS y mapa en un teléfono Android real. No asumir soporte por pasar pruebas unitarias.

## Limitaciones explícitas

Esto **no** es rastreo continuo con la aplicación cerrada ni una solución antirrobo. El usuario controla el consentimiento y Android puede pausar o cortar la señal. La geolocalización es un dato personal sensible: comunicar propósito, quién puede verla, periodo de retención y derechos aplicables a los usuarios antes de comenzar.

No guardar claves de Supabase, claves JWT ni secretos de Mailjet en Android ni en GitHub.
