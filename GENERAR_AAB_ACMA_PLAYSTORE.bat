@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title ACMA - ANDROID APP BUNDLE GOOGLE PLAY
echo.
echo ================================================================
echo  ACMA - AAB ANDROID FIRMADO PARA GOOGLE PLAY (API 36)
echo ================================================================
echo  Compila Android para Google Play, no crea cuentas ni firma por ti.
echo  NO modifica Supabase ni coloca contrasenas dentro de la app.
echo.
set "ACMA_URL=%~1"
if not defined ACMA_URL set "ACMA_URL=https://acme-production-ee493e67.up.railway.app"
set "ACMA_APPLICATION_ID=%~2"
if not defined ACMA_APPLICATION_ID set "ACMA_APPLICATION_ID=com.zaidrakeomg.acma"
echo Dominio: %ACMA_URL%
echo Application ID propuesto: %ACMA_APPLICATION_ID%
echo IMPORTANTE: este ID no se debe cambiar despues de la primera subida a Play.
echo.
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
    echo [ERROR] No se encontro Python.
    goto :final
  )
  set "ACMA_PYTHON=python"
)
if not exist "mobile_flutter\android\app\build.gradle.kts" (
  echo [1/6] Creando proyecto Android...
  pushd mobile_flutter
  call flutter create --platforms=android --project-name acma_mobile .
  if errorlevel 1 (
    popd
    echo [ERROR] Fallo flutter create.
    goto :final
  )
  popd
)
echo [2/6] Preparando permisos para Android por HTTPS...
"%ACMA_PYTHON%" scripts\preparar_flutter_release_acma.py "%ACMA_URL%"
if errorlevel 1 goto :final
echo [3/6] Verificando firma y ajustando Gradle para Play Store...
"%ACMA_PYTHON%" scripts\preparar_android_play.py --application-id "%ACMA_APPLICATION_ID%" --verificar-firma
if errorlevel 1 (
  echo.
  echo [AYUDA] Falta la firma privada para Google Play.
  echo Consulta docs\despliegue\PLAYSTORE_ANDROID.md
  goto :final
)
pushd mobile_flutter
echo [4/6] Instalando dependencias Flutter...
call flutter pub get
if errorlevel 1 (
  popd
  echo [ERROR] Fallo flutter pub get.
  goto :final
)
echo [5/6] Creando icono ACMA para Android, sin iOS...
call dart run flutter_launcher_icons
if errorlevel 1 (
  popd
  echo [ERROR] Fallaron los iconos Android.
  goto :final
)
echo [6/6] Generando Android App Bundle (release firmado)...
call flutter build appbundle --release "--dart-define=ACMA_BASE_URL=%ACMA_URL%"
if errorlevel 1 (
  popd
  echo [ERROR] Fallo la compilacion del AAB. No se puede publicar aun.
  goto :final
)
popd
echo.
echo ================================================================
echo  ARCHIVO AAB GENERADO PARA PRUEBAS EN GOOGLE PLAY:
echo  mobile_flutter\build\app\outputs\bundle\release\app-release.aab
echo ================================================================
echo  Comprueba la firma real y prueba en pista Internal Testing de Play.
echo  AAB generado NO significa que Google Play lo apruebe automaticamente.
echo  Realiza pruebas MFA, archivos, GPS, PDF, pantalla y red en equipos.
:final
echo.
pause
endlocal
