# ACMA móvil — Android / iPhone (Flutter)

## Qué conserva exactamente

Esta primera versión **no rehace las pantallas**: incrusta la interfaz React existente en una WebView de Flutter. Así se conservan por diseño los componentes, tipografías, colores, navegación y flujos actuales; no se introducen emojis ni menús sustitutos. Los estados de carga y conexión añadidos por Flutter usan Material Icons.

Es un **cliente de transición** y NO equivale a una reimplementación nativa de las 80 pantallas. La equivalencia funcional total depende de que ACMA esté publicado con FastAPI, PostgreSQL, Storage y workers disponibles. GPS, cámara, firmas, descargas PDF, push, WebSockets y modo sin conexión requieren pruebas explícitas en Android y iPhone; no se consideran verificados por el mero hecho de mostrar la web.

**Nunca conectar a Supabase directamente desde la WebView con una clave secreta.** La sesión y las reglas de negocio permanecen en FastAPI.

## Preparar el proyecto (Flutter 3.38+ / Dart 3.10+)

1. Instalar Flutter SDK, Android Studio y las herramientas de compilación. Para iOS, además, macOS + Xcode.
2. Desde este directorio, ejecutar:

```powershell
flutter create --platforms=android,ios --project-name acma_mobile .
flutter pub get
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
