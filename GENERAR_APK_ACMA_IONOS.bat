@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title ACMA - APK IONOS HTTPS
echo.
echo =======================================================
echo  ACMA - GENERAR APK ANDROID PARA IONOS / HTTPS
echo =======================================================
echo  No modifica Supabase, no publica secretos, no usa ADB.
echo.
if "%~1"=="" (
  echo [FALTA] Indica el dominio HTTPS de ACMA.
  echo Ejemplo:
  echo   GENERAR_APK_ACMA_IONOS.bat https://acma.dominio-cliente.com
  goto :final
)
set "ACMA_URL=%~1"
where flutter >nul 2>nul
if errorlevel 1 (
  echo [ERROR] No se encontro Flutter SDK en PATH.
  goto :final
)
if exist "backend\.venv\Scripts\python.exe" (
  set "ACMA_PYTHON=backend\.venv\Scripts\python.exe"
) else (
  where python >nul 2>nul
  if errorlevel 1 (
    echo [ERROR] No se encontro Python para preparar AndroidManifest.
    goto :final
  )
  set "ACMA_PYTHON=python"
)
if not exist "mobile_flutter\android\app\src\main\AndroidManifest.xml" (
  echo [1/5] Generando estructura Android que falta...
  pushd mobile_flutter
  call flutter create --platforms=android --project-name acma_mobile .
  if errorlevel 1 (
    popd
    echo [ERROR] No se pudo generar el proyecto Android.
    goto :final
  )
  popd
)
echo [2/5] Verificando dominio HTTPS y permisos Android de produccion...
"%ACMA_PYTHON%" scripts\preparar_flutter_release_acma.py "%ACMA_URL%"
if errorlevel 1 goto :final
echo [3/5] Instalando dependencias Flutter...
pushd mobile_flutter
call flutter pub get
if errorlevel 1 (
  popd
  echo [ERROR] Fallo flutter pub get.
  goto :final
)
echo [4/5] Aplicando el icono original de ACMA al APK...
call dart run flutter_launcher_icons
if errorlevel 1 (
  popd
  echo [ERROR] No se pudo generar el icono original de ACMA.
  goto :final
)
echo [5/5] Compilando APK RELEASE para el dominio indicado...
call flutter build apk --release "--dart-define=ACMA_BASE_URL=%ACMA_URL%"
if errorlevel 1 (
  popd
  echo [ERROR] Fallo flutter build apk.
  goto :final
)
popd
echo.
echo =======================================================
echo  APK generado:
echo  mobile_flutter\build\app\outputs\flutter-apk\app-release.apk
echo =======================================================
echo  IMPORTANTE: verificar firma propia antes de publicar en Play Store.
echo  Este APK necesita que la URL HTTPS de ACMA este publicada.
:final
echo.
pause
endlocal
