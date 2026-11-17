# ACMA Android para Google Play (noviembre 2026)

## Qué se ha solucionado

El error original en Windows ocurre porque `flutter_launcher_icons` trató de
escribir `ios/Runner/Assets.xcassets/...` cuando tu carpeta solo tiene Android.
En `mobile_flutter/pubspec.yaml` dejamos `flutter_launcher_icons.ios=false`.
Puedes ejecutar el generador Android sin crear iOS.

ACMA móvil sigue siendo una **Flutter WebView** que abre la web React/FastAPI
del servidor Railway. Este trabajo no convierte las 80 pantallas a nativas.
**No podemos garantizar 100% de funcionamiento en cualquier Android sin
probar módulos y permisos en equipos reales**. Por ejemplo, pueden requerir
integración adicional descargas, cámara, GPS, chat, firmas, notificaciones,
acceso offline, almacenamiento, WebSocket y apertura de PDF.

## 1. Probar APK Android (instalación directa)

En Windows con Flutter, Java/Android SDK:

```bat
cd /d C:\Users\camil\Downloads\acme-
git checkout main
git pull --ff-only origin main
GENERAR_APK_ACMA_RAILWAY.bat https://acme-production-ee493e67.up.railway.app
```

Archivo de pruebas: `mobile_flutter/build/app/outputs/flutter-apk/app-release.apk`.
Se puede instalar manualmente por Android, NO es el archivo preferido para Play.

## 2. Preparar identidad del paquete Android

El archivo `GENERAR_AAB_ACMA_PLAYSTORE.bat` utiliza como identificador
**provisional** `com.zaidrakeomg.acma`. Es un identificador de ejemplo basado
en el nombre público de GitHub del desarrollador, **no está confirmado como la
identidad legal ni el nombre final del cliente**. El cliente debe aprobar el
identificador, el nombre, la titularidad, el icono y la marca antes de subir a
Google Play. Una vez publicado, no es posible cambiar el ID de una app ya
publicada manteniendo su ficha e instalaciones.

Si ya existe una ficha de ACMA en Play Console, usar exactamente su
`applicationId` anterior.

El instalador ajusta `compileSdk=36` y `targetSdk=36` para cumplir la norma
de Google Play de 2026. No compromete la API mínima: Flutter moderno suele
admitir Android 7.0 o más nuevo; el rango exacto se comprueba en el AAB de
Play Console. No promete compatibilidad con *todos* los Android antiguos.

## 3. Crear la clave PRIVADA de publicación: solo una vez

Google Play requiere un **Android App Bundle (.aab) firmado con una clave de
subida**. Usa Google Play App Signing para la clave de firma que Google
administra en Play. **Nunca publiques la clave de subida ni su contraseña
en GitHub, Railway, Supabase o ChatGPT.**

Desde CMD con JDK/Android Studio, un ejemplo para generar la llave:

```bat
keytool -genkeypair -v -keystore "%USERPROFILE%\acma-upload-keystore.jks" -storetype JKS -keyalg RSA -keysize 3072 -validity 10000 -alias acma-upload
```

El comando solicita contraseña y certificado. GUARDAR el archivo y las
contraseñas en lugar privado y con backup cifrado. Si `keytool` no está en
PATH, busca en Android Studio el `jbr/bin/keytool.exe` de Java.

Crear **localmente** (NUNCA en GitHub) el archivo
`mobile_flutter/android/key.properties` con estos campos:

```properties
storePassword=TU_CONTRASENA_PRIVADA_DEL_ALMACEN
keyPassword=TU_CONTRASENA_PRIVADA_DE_LA_LLAVE
keyAlias=acma-upload
storeFile=C:/Users/TU_USUARIO/acma-upload-keystore.jks
```

Usa diagonales `/` en Windows para evitar problemas de escape en Gradle.
El script `scripts/preparar_android_play.py` comprobará que los cuatro
campos y el archivo JKS existan sin mostrar los secretos. Tanto
`android/key.properties` como `*.jks` están ignorados por Git.

## 4. Generar el AAB para Google Play

```bat
cd /d C:\Users\camil\Downloads\acme-
git pull --ff-only origin main
GENERAR_AAB_ACMA_PLAYSTORE.bat https://acme-production-ee493e67.up.railway.app com.zaidrakeomg.acma
```

**Antes de ejecutar:** confirma el identificador oficial de la empresa. Si
el cliente aprueba otro ID, sustituye `com.zaidrakeomg.acma` por el definitivo.

El comando:
1. crea plataforma Android si falta,
2. verifica HTTPS y permisos Android,
3. prepara Gradle API 36 e ID Android definitivo,
4. **exige** `key.properties` + JKS,
5. genera únicamente iconos Android,
6. compila el Android App Bundle release con firma.

Resultado (solo si el build termina bien):
`mobile_flutter/build/app/outputs/bundle/release/app-release.aab`.

Sube **el AAB**, no el APK, a la pista **Internal testing** de Play Console.
Si Gradle te da errores, copia los logs completos, sin contraseñas,
y corrige antes de distribuir.

Para generar un APK instalable *después* de configurar la firma:
```bat
cd mobile_flutter
flutter build apk --release --dart-define=ACMA_BASE_URL=https://acme-production-ee493e67.up.railway.app
```

## 5. Compatibilidad y pruebas obligatorias en teléfonos reales

Probar, como mínimo, Android 7-9, 10-12, 13-14 y 15-16 cuando dispongas
de dispositivos o emuladores. Probar en Samsung, Motorola, Xiaomi y Pixel
si son parte del público. Verificar versiones modernas y anteriores,
pantallas pequeñas y grandes, vertical/horizontal, gestos, teclado y
botón de regresar. Probar siempre con datos móviles **y Wi-Fi**.

Verificar con usuarios de prueba autorizados:
- arranque HTTPS, login, MFA, expiración/renovación de sesión;
- lectura y escritura Supabase por tenant sin fugas entre empresas;
- cámara, galería, adjuntos grandes, GPS con permiso y sin permiso;
- exportaciones/descarga de PDF/Excel, enlaces externos y regreso;
- chat y actualizaciones en vivo; pruebas sin conexión y reconexión;
- formularios, notificaciones, trabajos programados y modo sin conexión;
- accesibilidad, estados de carga/errores y aplicación en segundo plano.

**Ojo:** nuestra primera configuración Railway activa FastAPI + React con
`TIEMPO_REAL_MODO=local` y **no** inicia Redis ni Celery Worker/Beat. Las
funciones programadas y notificaciones no están completas solo por generar
AAB. Deben desplegarse, configurar colas y probarse por separado.

## 6. Requisitos de Google Play fuera del código

El propietario debe disponer de cuenta de **Google Play Console**, aceptar
**Play App Signing**, disponer de política de privacidad pública y completar
formularios de Datos de Seguridad, Acceso a la App (credenciales de revisión
cuando MFA sea obligatorio), público objetivo, contenido y permisos. También
necesitará ficha, capturas reales, icono, contacto y declarar que posee derechos
sobre ACMA y su web.

Si la cuenta de desarrollador es **personal** y fue creada después del 13 de
noviembre de 2023, Google exige una prueba cerrada con al menos **12 testers
durante 14 días** antes de solicitar acceso a publicación en producción.

Una app WebView puede distribuirse en Play si proporciona utilidad real y
tiene autorización del propietario del contenido, pero la revisión puede
rechazar contenido repetitivo, roto o limitado. No prometemos aprobación
automática.

Fuentes oficiales:
- https://docs.flutter.dev/deployment/android
- https://support.google.com/googleplay/android-developer/answer/11926878
- https://support.google.com/googleplay/android-developer/answer/14151465
- https://support.google.com/googleplay/android-developer/answer/18265346

## Seguridad antes de publicar

Las credenciales privadas de PostgreSQL y Supabase del proyecto fueron
compartidas en la conversación. **Rotar contraseña PostgreSQL de usuario API
y `SUPABASE_SECRET_KEY` coordinadamente con Railway y el `.env` local.**
No volverlas a compartir por chat. La clave `CLAVE_CIFRADO` no se rota sin
una estrategia de re-cifrado, por riesgo de perder acceso a MFA y archivos.
