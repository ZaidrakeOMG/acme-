@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title ACMA - PROBAR FLUTTER ANDROID (SIN DOCKER)
echo.
echo =========================================================
echo  ACMA - ABRIR ANDROID EN EMULADOR CON UN DOBLE CLIC
echo =========================================================
echo  1. En Android Studio abre un emulador desde Device Manager.
echo  2. Ejecuta este .bat: se abrira ACMA en el emulador.
echo  3. Usa la web publicada en Railway sin iniciar servidor local.
echo.
echo  Si prefieres probar backend local, ejecuta:
echo  PROBAR_ACMA_FLUTTER_ANDROID.bat --local
echo.
set "ACMA_MODO=--railway"
if /I "%~1"=="--local" set "ACMA_MODO="
rem Usar primero el Python que YA instalamos para ACMA Web.
rem El launcher "py" no es requisito de Flutter ni de Android Studio.
if exist "backend\.venv\Scripts\python.exe" goto :python_venv
where python >nul 2>nul
if not errorlevel 1 goto :python_path
where py >nul 2>nul
if not errorlevel 1 goto :python_launcher
echo [ERROR] No se encontro Python en el equipo.
echo Instala Python 3.12 o configura Python en PATH,
echo o comprueba desde CMD: python --version
goto :final

:python_venv
echo [OK] Usando Python del entorno de ACMA Web.
"backend\.venv\Scripts\python.exe" scripts\iniciar_flutter_acma.py %ACMA_MODO%
goto :resultado

:python_path
echo [OK] Usando Python disponible en PATH.
python scripts\iniciar_flutter_acma.py %ACMA_MODO%
goto :resultado

:python_launcher
echo [OK] Usando lanzador alternativo py -3.12.
py -3.12 scripts\iniciar_flutter_acma.py %ACMA_MODO%
goto :resultado

:resultado
set "RESULTADO_FLUTTER=%ERRORLEVEL%"
if not "%RESULTADO_FLUTTER%"=="0" (
  echo.
  echo [ERROR] Flutter termino con codigo %RESULTADO_FLUTTER%.
  echo Copia el ultimo mensaje de error, pero NO envies secretos ni .env.
) else (
  echo.
  echo Flutter termino correctamente.
)
:final
echo.
echo La ventana queda abierta para que puedas leer el resultado.
pause
endlocal
