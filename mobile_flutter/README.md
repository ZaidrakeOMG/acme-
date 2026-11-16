# ACMA móvil — Android / iPhone (Flutter)

## Qué conserva exactamente

Esta primera versión **no rehace las pantallas**: incrusta la interfaz React existente en una WebView de Flutter. Así se conservan por diseño los componentes, tipografías, colores, navegación y flujos actuales; no se introducen emojis ni menús sustitutos. Los estados de carga y conexión añadidos por Flutter usan Material Icons.

Es un **cliente de transición** y NO equivale a una reimplementación nativa de las 80 pantallas. La equivalencia funcional total depende de que ACMA esté publicado con FastAPI, PostgreSQL, Storage y workers disponibles. GPS, cámara, firmas, descargas PDF, push, WebSockets y modo sin conexión requieren pruebas explícitas en Android y iPhone; no se consideran verificados por el mero hecho de mostrar la web.

**Nunca conectar a Supabase directamente desde la WebView con una clave secreta.** La sesión y las reglas de negocio permanecen en FastAPI.

## Ver ACMA Android en Windows con el backend Supabase ya funcionando

La manera más sencilla es ejecutar el **PROBAR_ACMA_FLUTTER_ANDROID.bat** de la
raíz del repositorio (NO es necesario publicar todavía ACMA en Internet):

1. Tener Flutter SDK 3.38+ y Android Studio con Android SDK Platform-Tools.
   Verificar desde CMD: `flutter doctor`, `flutter devices`.
2. Abrir **PROBAR_ACMA_WEB.bat** en una ventana CMD y **dejarla abierta**:
   debe responder `http://127.0.0.1:8000/api/salud` con `estado: ok`.
3. En Android Studio → Device Manager, encender un emulador Android.
   Alternativamente conectar un teléfono Android por USB con depuración autorizada.
4. En otra ventana CMD, desde la raíz:
   
   ```bat
   git pull --ff-only origin migracion-supabase-segura-20261115
   PROBAR_ACMA_FLUTTER_ANDROID.bat
   ```

El lanzador detecta Android, genera su estructura si aún no existe, instala
paquetes Flutter, configura automáticamente `adb reverse tcp:8000 tcp:8000`
y ejecuta:

```bat
flutter run -d ID_DEL_ANDROID --debug --dart-define=ACMA_BASE_URL=http://localhost:8000 --dart-define=ACMA_ALLOW_HTTP=true
```

**Por qué localhost y no 10.0.2.2**: el reenvío `adb reverse` permite que
WebView trate `localhost` como un origen seguro, requisito para múltiples
funciones web como Service Workers, geolocalización y cámara. El archivo
`android/app/src/debug/AndroidManifest.xml` autoriza HTTP **solo en modo
depuración**, no en release. No guardar secret keys ni passwords en Flutter.
El API de FastAPI continúa conectado a Supabase a través de `.env` local.

La primera versión es una **WebView**, no una reconstrucción Flutter nativa.
Login y MFA deben probarse en un emulador o Android real. Las pruebas de
geolocalización, notificaciones push y offline siguen pendientes en dispositivos.

**Si no existe Flutter**: https://docs.flutter.dev/install y
https://docs.flutter.dev/platform-integration/android/setup. Si no aparece
Android en `flutter devices`, crea e inicia un emulador en Android Studio.
`flutter run -d chrome` no es una vista equivalente: el proyecto móvil
utiliza un WebView nativo diseñado para Android/iOS.

## Preparar el proyecto (Flutter 3.38+ / Dart 3.10+)

1. Instalar Flutter SDK, Android Studio y las herramientas de compilación. Para iOS, además, macOS + Xcode.
2. Desde este directorio, ejecutar:

```powershell
flutter create --platforms=android,ios --project-name acma_mobile .
flutter pub get
dart run flutter_launcher_icons
flutter test
flutter analyze
```

El `flutter create` genera los directorios de plataforma faltantes. Revisar identificadores `applicationId` y `Bundle Identifier` antes de publicar; no usar los de demostración.

3. En `android/app/src/main/AndroidManifest.xml`, añadir (si no existe) **fuera de** `<application>`:

```xml
<uses-permission android:name="android.permission.INTERNET" />
<uses-permission android:name="android.permission.CAMERA" />
<uses-permission android:name="android.permission.ACCESS_FINE_LOCATION" />
<uses-permission android:name="android.permission.ACCESS_COARSE_LOCATION" />
```

En iOS, configurar `ios/Runner/Info.plist` con `NSCameraUsageDescription` y `NSLocationWhenInUseUsageDescription` explicando los usos. Si se usa CocoaPods, revisar las macros de `permission_handler` (CAMERA y LOCATION_WHENINUSE). La app solicita permisos cuando el sitio ACMA pide cámara o GPS. Los permisos deben comprobarse en Android/iPhone reales.

No habilitar `usesCleartextTraffic` en producción. La URL de ACMA debe ser HTTPS. Para permisos de GPS/cámara, agregar permisos y solicitudes de consentimiento solo después de validar los flujos por plataforma.

## Ejecutar en emulador o celular con backend publicado

```powershell
flutter run --dart-define=ACMA_BASE_URL=https://acma.tu-dominio.com
```

La URL **debe** apuntar al servidor ACMA unificado, no a la URL de Supabase ni al puerto de Vite. La URL de Supabase, si existe, solo pertenece a las variables de backend.

## Probar HTTP local (solo depuración)

```powershell
flutter run --dart-define=ACMA_BASE_URL=http://10.0.2.2:8000 --dart-define=ACMA_ALLOW_HTTP=true
```

Este ejemplo apunta a localhost de la máquina anfitriona **desde el emulador Android**; la política de Android puede requerir configuración de tráfico claro SOLO para debug. En iOS simulador generalmente se usa `http://localhost:8000` con una excepción ATS SOLO para debug. Un teléfono real necesita una dirección accesible por Wi-Fi y permisos de red correspondientes. Las compilaciones `release` rechazan HTTP incluso con `ACMA_ALLOW_HTTP=true`.

## Generar los instaladores

```powershell
flutter build appbundle --release --dart-define=ACMA_BASE_URL=https://acma.tu-dominio.com
flutter build apk --release --dart-define=ACMA_BASE_URL=https://acma.tu-dominio.com
```

Para iPhone, desde macOS con Xcode y firma configurada:

```bash
flutter build ipa --release --dart-define=ACMA_BASE_URL=https://acma.tu-dominio.com
```

App Store / Google Play pueden requerir medidas adicionales y una revisión específica sobre el uso de WebView. No asegurar aprobación por el simple hecho de generar un instalador.

## Lista obligatoria antes de publicar

- Comparar en equipo real todas las pantallas con el sitio React original, en retrato y paisaje.
- Validar login, MFA, expiración/renovación, cookies HttpOnly y cambios de rol.
- Confirmar que distintos tenants jamás pueden acceder a datos de otro tenant.
- Probar adjuntos desde cámara, galería y archivos en ambos sistemas; el selector Android se integra mediante `file_picker` y debe validarse con PDFs, imágenes grandes y múltiples documentos.
- Confirmar descargas PDF/Excel, compartir archivos, mapas, links externos y notificaciones.
- Probar reconexión, offline, sincronización y conflictos de datos.
- Confirmar WebSockets, notificaciones y tareas programadas contra backend público.
- Enviar builds a Android e iOS y verificar pruebas manuales antes de distribuir.

## Evolución a Flutter nativo

No borrar `frontend/`. Implementar módulos nativos uno por uno con paridad automatizada, empezando por login, tableros, folios y campo, manteniendo el resto en la WebView. Cada módulo se reemplaza solamente después de aprobar un inventario de UI, funciones y casos de prueba.
