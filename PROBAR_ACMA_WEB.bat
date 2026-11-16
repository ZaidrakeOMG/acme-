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

where py >nul 2>nul
if errorlevel 1 (
  echo [ERROR 01] No se encontro el lanzador de Python "py".
  echo Instala Python 3.12. Prueba desde CMD: py -3.12 --version
  goto :error
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
if not exist ".env" (
  echo.
  echo [3/5] Configurando Supabase y primer administrador...
  echo Si se cancela el asistente, NO borres ni la BD ni carpetas.
  "backend\.venv\Scripts\python.exe" scripts\configurar_acma_supabase.py
  if errorlevel 1 (
    echo [ERROR 05] Fallo el asistente de Supabase.
    echo Comprueba que se creo el bucket privado acma y las credenciales.
    echo Si el archivo .env ya existe, ejecuta CREAR_ADMIN_ACMA.bat.
    goto :error
  )
)
if not exist ".env" (
  echo [ERROR 06] Falta .env en la raiz. No se inicia ACMA.
  goto :error
)
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
