# ACMA en Android Studio

La app móvil es **Flutter + WebView**: abre el mismo frontend React y backend FastAPI de la plataforma web. Los cambios visuales publicados en Railway se reflejan dentro de la app sin copiar frontend ni configurar secretos en Android.

## 1. Actualizar el repositorio

Desde CMD en la carpeta raíz:

```bat
git status
git switch main
git pull --ff-only origin main
```

## 2. Abrir ACMA en el emulador con un doble clic

1. En **Android Studio → Tools → Device Manager**, inicia tu emulador Android.
2. Desde el Explorador de Windows, entra a la carpeta **raiz del repositorio ACMA**.
3. Haz doble clic en **PROBAR_ACMA_FLUTTER_ANDROID.bat**.

El lanzador utiliza el emulador encendido, prepara Flutter y abre la WebView conectada al dominio HTTPS configurado de **ACMA**. No hace falta abrir PROBAR_ACMA_WEB.bat.

Para desarrollo con servidor **local**, abre PROBAR_ACMA_WEB.bat y ejecuta:

```bat
PROBAR_ACMA_FLUTTER_ANDROID.bat --local
```

Si deseas usar el boton **Run** de Android Studio, abre la carpeta `mobile_flutter`, elige el emulador y configura los argumentos de Flutter:

```text
--dart-define=ACMA_BASE_URL=https://grupoacma.com
```

## 3. Probar con el servidor local (opcional)

Primero inicia `PROBAR_ACMA_WEB.bat` desde la raíz y confirma `http://127.0.0.1:8000/api/salud`. Después usa `PROBAR_ACMA_FLUTTER_ANDROID.bat`; el lanzador hace `adb reverse` y usa `localhost` para la WebView. No habilites HTTP en una APK de producción.

## 4. Generar APK o App Bundle

Desde la raíz en Windows:

```bat
GENERAR_APK_ACMA_RAILWAY.bat https://grupoacma.com
```

Resultado: `mobile_flutter/build/app/outputs/flutter-apk/app-release.apk`.

La app muestra un botón de **servidor** (arriba a la derecha). Si Railway cambia la URL, usa ese botón y escribe el dominio HTTPS de ACMA; la elección se guarda en el dispositivo. Esto evita tener que recompilar el APK por cada cambio de dominio.

Para Google Play, configura primero la llave privada de firma de tu cuenta. Después utiliza `GENERAR_AAB_ACMA_PLAYSTORE.bat`. El artefacto de CI es **solo de prueba**, no incluye la llave definitiva de la tienda.

## Consideraciones

- No guardar `SUPABASE_SECRET_KEY`, JWT ni `DATABASE_URL` dentro de la aplicación.
- La identidad Android se genera desde `frontend/public/icono-512.png` mediante `dart run flutter_launcher_icons`.
- El módulo voluntario de ubicación de personal todavía no forma parte de `main`: necesita migración SQL, permisos de backend y nueva APK antes de usarlo.
- Probar acceso, MFA, formularios, navegación, PDFs y permisos físicos en un Android real antes de publicar.
