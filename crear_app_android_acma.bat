@echo off
setlocal
cd /d "%~dp0mobile_flutter"
where flutter >nul 2>nul
if errorlevel 1 (
  echo ERROR: Flutter SDK no esta instalado o no figura en PATH.
  echo Instala Flutter y Android Studio desde https://docs.flutter.dev/get-started/install
  exit /b 1
)
if "%ACMA_BASE_URL%"=="" (
  echo ERROR: falta la URL HTTPS de ACMA publicado.
  echo Ejemplo desde CMD: set ACMA_BASE_URL=https://acma.tu-dominio.com
  echo Despues vuelve a ejecutar este .bat.
  exit /b 1
)
echo %ACMA_BASE_URL% | findstr /b /i /c:"https://" >nul
if errorlevel 1 (
  echo ERROR: para publicar una APK usa una URL HTTPS.
  exit /b 1
)
echo [1/5] Generando proyecto Android e iOS Flutter sin tocar React...
call flutter create --platforms=android,ios --project-name acma_mobile .
if errorlevel 1 exit /b 1
echo [2/5] Dependencias Flutter...
call flutter pub get
if errorlevel 1 exit /b 1
echo [3/5] Icono ACMA original...
call dart run flutter_launcher_icons
if errorlevel 1 exit /b 1
echo [4/5] Validando codigo de Flutter...
call flutter analyze
if errorlevel 1 exit /b 1
call flutter test
if errorlevel 1 exit /b 1
echo [5/5] Compilando APK Android...
call flutter build apk --release --dart-define=ACMA_BASE_URL=%ACMA_BASE_URL%
if errorlevel 1 exit /b 1
echo.
echo APK disponible en mobile_flutter\build\app\outputs\flutter-apk\app-release.apk
echo NOTA: iOS requiere macOS/Xcode. Esta APK no valida el backend ni migracion Supabase.
pause
