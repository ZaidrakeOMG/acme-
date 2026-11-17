# ACMA en Android Studio

La app móvil es **Flutter + WebView**: abre el mismo frontend React y backend FastAPI de la plataforma web. Los cambios visuales publicados en Railway se reflejan dentro de la app sin copiar frontend ni configurar secretos en Android.

## 1. Actualizar el repositorio

Desde CMD en la carpeta raíz:

```bat
git status
git switch main
git pull --ff-only origin main
```

## 2. Abrir en Android Studio

- Instala el SDK de Flutter y los plugins Flutter/Dart en Android Studio.
- Abre **File → Open** y selecciona `mobile_flutter`, no la carpeta `frontend`.
- Inicia un emulador desde **Tools → Device Manager** o conecta un celular Android con **Depuración USB**.
- Abre la terminal integrada y verifica que estés en `mobile_flutter`.

```powershell
flutter doctor
flutter create --platforms=android --project-name acma_mobile .
flutter pub get
dart run flutter_launcher_icons
flutter devices
flutter run --dart-define=ACMA_BASE_URL=https://acme-production-ee493e67.up.railway.app
```

Si deseas utilizar el botón **Run** del IDE, elige el dispositivo en la barra superior y crea una configuración Flutter con **Additional run args**:

```text
--dart-define=ACMA_BASE_URL=https://acme-production-ee493e67.up.railway.app
```

El punto de entrada es `lib/main.dart`. La app requiere conectividad a Railway para cargar la web; por eso debes comprobar antes `/api/salud` en el mismo dominio.

## 3. Probar con el servidor local (opcional)

Primero inicia `PROBAR_ACMA_WEB.bat` desde la raíz y confirma `http://127.0.0.1:8000/api/salud`. Después usa `PROBAR_ACMA_FLUTTER_ANDROID.bat`; el lanzador hace `adb reverse` y usa `localhost` para la WebView. No habilites HTTP en una APK de producción.

## 4. Generar APK o App Bundle

Desde la raíz en Windows:

```bat
GENERAR_APK_ACMA_RAILWAY.bat https://acme-production-ee493e67.up.railway.app
```

Resultado: `mobile_flutter/build/app/outputs/flutter-apk/app-release.apk`.

Para Google Play, configura primero la llave privada de firma de tu cuenta. Después utiliza `GENERAR_AAB_ACMA_PLAYSTORE.bat`. El artefacto de CI es **solo de prueba**, no incluye la llave definitiva de la tienda.

## Consideraciones

- No guardar `SUPABASE_SECRET_KEY`, JWT ni `DATABASE_URL` dentro de la aplicación.
- La identidad Android se genera desde `frontend/public/icono-512.png` mediante `dart run flutter_launcher_icons`.
- El módulo voluntario de ubicación de personal todavía no forma parte de `main`: necesita migración SQL, permisos de backend y nueva APK antes de usarlo.
- Probar acceso, MFA, formularios, navegación, PDFs y permisos físicos en un Android real antes de publicar.
