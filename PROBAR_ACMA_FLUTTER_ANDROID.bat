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
where py >nul 2>nul
if errorlevel 1 (
  echo [ERROR] No se encontro el lanzador py de Python 3.12.
  echo Ejecuta desde CMD: py -3.12 --version
  goto :final
)
py -3.12 scripts\iniciar_flutter_acma.py
set "RESULTADO_FLUTTER=%ERRORLEVEL%"
if not "%RESULTADO_FLUTTER%"=="0" (
  echo.
  echo [ERROR] Flutter termino con codigo %RESULTADO_FLUTTER%.
  echo Copia el ultimo mensaje de error, pero NO envíes secretos ni .env.
) else (
  echo.
  echo Flutter termino correctamente.
)
:final
echo.
echo La ventana queda abierta para que puedas leer el resultado.
pause
endlocal
