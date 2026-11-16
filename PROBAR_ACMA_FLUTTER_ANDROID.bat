@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title ACMA - PROBAR FLUTTER ANDROID (SIN DOCKER)
echo.
echo =========================================================
echo  ACMA - FLUTTER ANDROID CON SUPABASE
echo =========================================================
echo  1. Mantener PROBAR_ACMA_WEB.bat abierto en otra ventana.
echo  2. Tener Android Studio con un emulador Android ENCENDIDO,
echo     o un celular Android conectado por USB y autorizado.
echo  3. El asistente detectara el equipo y ejecutara Flutter.
echo  No borra la base, no crea usuarios, no pide tu API key.
echo.

rem Usar primero el Python que YA instalamos para ACMA Web.
rem El launcher "py" no es requisito de Flutter ni de Android Studio.
if exist "backend\.venv\Scripts\python.exe" goto :python_venv
where python >nul 2>nul
if not errorlevel 1 goto :python_path
where py >nul 2>nul
if not errorlevel 1 goto :python_launcher
echo [ERROR] No se encontro Python en el equipo.
echo Ejecuta PROBAR_ACMA_WEB.bat para instalar el entorno,
echo o comprueba desde CMD: python --version
goto :final

:python_venv
echo [OK] Usando Python del entorno de ACMA Web.
"backend\.venv\Scripts\python.exe" scripts\iniciar_flutter_acma.py
goto :resultado

:python_path
echo [OK] Usando Python disponible en PATH.
python scripts\iniciar_flutter_acma.py
goto :resultado

:python_launcher
echo [OK] Usando lanzador alternativo py -3.12.
py -3.12 scripts\iniciar_flutter_acma.py
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
