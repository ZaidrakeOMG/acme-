# ACMA — Gestión de mantenimiento

Proyecto de gestión de mantenimiento con **React + FastAPI + PostgreSQL/Supabase** y aplicación Android mediante **Flutter WebView**.

El repositorio contiene el código de la plataforma, sus migraciones, pruebas, los scripts necesarios para desarrollo y las instrucciones de despliegue. Los datos de producción permanecen en Supabase.

## Actualizar ACMA desde GitHub

En CMD o PowerShell, dentro de la carpeta de ACMA:

```bat
git status
git switch main
git pull --ff-only origin main
```

Si Git detecta cambios locales, revísalos antes de actualizar: no los descartes ni uses `git reset --hard` sobre información que quieras conservar.

## Web publicada

**Railway:** https://acme-production-ee493e67.up.railway.app/

**Salud de la API:** https://acme-production-ee493e67.up.railway.app/api/salud

Railway compila automáticamente los cambios de la rama `main` cuando está habilitado el despliegue desde GitHub. Las credenciales pertenecen a las variables privadas de Railway. Nunca subas `.env`, passwords, tokens JWT ni claves de Supabase a GitHub.

## Android Studio (emulador o celular)

1. Instala Android Studio, Android SDK y el SDK de Flutter con sus plugins **Flutter** y **Dart**.
2. Abre Android Studio → **Open** → selecciona la carpeta `mobile_flutter`.
3. Desde **Device Manager**, inicia un emulador o conecta un teléfono Android con depuración USB.
4. En la terminal de Android Studio, dentro de `mobile_flutter`, ejecuta:

```powershell
flutter doctor
flutter create --platforms=android --project-name acma_mobile .
flutter pub get
dart run flutter_launcher_icons
flutter run --dart-define=ACMA_BASE_URL=https://acme-production-ee493e67.up.railway.app
```

La WebView carga el sitio publicado en Railway. Los cambios visuales del frontend React aparecen al desplegar la web; para cambiar el **icono del launcher** o el código Flutter nativo hay que reconstruir/reinstalar la app.

Para crear el APK de pruebas desde Windows se conserva `GENERAR_APK_ACMA_RAILWAY.bat`; para generar el AAB firmado de Google Play se conserva `GENERAR_AAB_ACMA_PLAYSTORE.bat`. Ver [instrucciones de Android](mobile_flutter/README.md) y [despliegue de Android](docs/despliegue/RAILWAY_ANDROID.md).

## Scripts de Windows conservados

| Archivo | Uso |
|---|---|
| `PROBAR_ACMA_WEB.bat` | Iniciar y probar web + API local contra la configuración privada existente. |
| `PROBAR_ACMA_FLUTTER_ANDROID.bat` | Probar Android local con `adb reverse` y backend local. |
| `GENERAR_APK_ACMA_RAILWAY.bat` | Crear APK de prueba para Railway. |
| `GENERAR_AAB_ACMA_PLAYSTORE.bat` | Compilar AAB con firma de publicación configurada. |
| `CREAR_ADMIN_ACMA.bat` | Configuración inicial de administrador, solo si hace falta. |

Los scripts de Docker, despliegue e infraestructura siguen en `deploy/` y las migraciones en `backend/alembic/`. No ejecutes migraciones de producción sin respaldo.

## Documentación técnica

- [Configuración Supabase](docs/supabase_pasos_acma.md)
- [Despliegue Railway Android](docs/despliegue/RAILWAY_ANDROID.md)
- [Google Play](docs/despliegue/PLAYSTORE_ANDROID.md)
- [Procedimientos de operación](docs/operacion/despliegue.md)
- [Seguridad](docs/seguridad/checklist_iso27001.md)

La función opcional de GPS de personal está en desarrollo separado; no queda habilitada por clonar o actualizar la rama `main`.
