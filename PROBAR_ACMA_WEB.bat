@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title ACMA - WEB SUPABASE (diagnostico visible)

echo.
echo ===============================================================
echo          ACMA - PRUEBA WEB CON SUPABASE (SIN DOCKER)
echo ===============================================================
echo  Esta ventana NO se cerrara si hay un error.
echo  No compartas tu archivo .env ni claves o contrasenas.
echo.

rem Si el entorno virtual de ACMA ya existe, NO necesita el lanzador py.
if not exist "backend\.venv\Scripts\python.exe" (
  where py >nul 2>nul
  if errorlevel 1 (
    echo [ERROR 01] Falta el entorno Python de ACMA y no existe el lanzador py.
    echo Para crear el entorno desde cero necesitas Python 3.12 con el lanzador py.
    goto :error
  )
)
where npm >nul 2>nul
if errorlevel 1 (
  echo [ERROR 02] No se encontro npm. Instala Node.js 22 o superior.
  goto :error
)
if not exist "backend\.venv\Scripts\python.exe" (
  echo [1/5] Creando entorno Python 3.12...
  py -3.12 -m venv backend\.venv
  if errorlevel 1 (
    echo [ERROR 03] No fue posible crear backend\.venv.
    goto :error
  )
)
if not exist "backend\.venv\.dependencias_web_acma_ok" (
  echo [2/5] Instalando dependencias originales...
  "backend\.venv\Scripts\python.exe" -m pip install -r backend\requirements.txt
  if errorlevel 1 (
    echo [ERROR 04] Fallo pip install; revisa el mensaje anterior.
    goto :error
  )
  echo ok> "backend\.venv\.dependencias_web_acma_ok"
)
rem Credenciales privadas: nunca se descargan del repositorio ni se piden en cada prueba.
rem .env prevalece. Una plantilla LOCAL .env.prueba.local se usa solo si falta .env.
if not exist ".env" if exist ".env.prueba.local" (
  echo [3/5] Preparando .env desde .env.prueba.local...
  copy /Y ".env.prueba.local" ".env" >nul
  if errorlevel 1 (
    echo [ERROR 05] No se pudo copiar .env.prueba.local a .env.
    goto :error
  )
)
if not exist ".env" (
  echo [ERROR 06] No existe .env ni .env.prueba.local en la raiz de ACMA.
  echo Coloca tu configuracion privada en uno de esos archivos.
  echo No se solicitan claves por consola ni se crea una BD automaticamente.
  goto :error
)
echo.
echo [3/5] Revisando configuracion local sin solicitar claves...
"backend\.venv\Scripts\python.exe" scripts\diagnosticar_env_supabase.py --solo-validar
if errorlevel 1 (
  echo [ERROR 06A] La configuracion privada necesita ajustes (ver mensaje anterior).
  echo Se conservo .env sin moverlo, sobrescribirlo ni pedir contrasenas.
  goto :error
)

:comprobar_supabase
echo.
echo [3/5] Verificando Postgres acma_api, esquema acma y Storage...
pushd backend
".venv\Scripts\python.exe" -m scripts.preflight_supabase
if errorlevel 1 (
  popd
  echo [ERROR 07] No paso el preflight de Supabase.
  echo Revisa el error ANTERIOR. No compartas .env.
  echo Si hace falta el administrador, CREAR_ADMIN_ACMA.bat.
  goto :error
)
popd

echo.
echo [4/5] Compilando React ORIGINAL...
pushd frontend
if not exist node_modules (
  call npm ci
  if errorlevel 1 (
    popd
    echo [ERROR 08] Fallo npm ci.
    goto :error
  )
)
call npm run build
if errorlevel 1 (
  popd
  echo [ERROR 09] Fallo React build, mira el mensaje anterior.
  goto :error
)
popd

echo.
echo ===============================================================
echo   [5/5] Iniciando ACMA: http://localhost:8000
echo   Esta consola queda abierta mientras sirves la web.
echo   CTRL+C para detener servidor. El cierre no toca Supabase.
echo   Redis/Celery no se ejecutan en esta prueba WEB.
echo ===============================================================
echo.
pushd backend
".venv\Scripts\python.exe" -m uvicorn main:app --host 127.0.0.1 --port 8000
set "ACMA_EXIT_CODE=%errorlevel%"
popd
echo.
echo [FINALIZADO] Uvicorn termino con codigo %ACMA_EXIT_CODE%.
if not "%ACMA_EXIT_CODE%"=="0" echo Revisa el error del servidor arriba.
goto :pausa

:error
echo.
echo ===============================================================
echo ERROR: ACMA NO se inicio. NO se han borrado datos ni tablas.
echo Para compartir el error, copia SOLO el mensaje sin credenciales.
echo ===============================================================
goto :pausa

:pausa
echo.
echo Presiona una tecla cuando hayas LEIDO o copiado el error.
pause >nul
endlocal
