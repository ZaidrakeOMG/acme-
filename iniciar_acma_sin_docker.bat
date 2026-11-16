@echo off
setlocal
REM Un lanzador, una URL: React + FastAPI + Celery Worker/Beat sin Docker.
REM Infraestructura remota EXISTENTE; no crea ni modifica ninguna base de datos.
cd /d "%~dp0"
if not exist ".env" (
  echo ERROR: falta .env privado de ACMA.
  echo Consulta docs\supabase_pasos_acma.md
  exit /b 1
)
findstr /r /i /c:"^DATABASE_URL=.*localhost" /c:"^DATABASE_URL=.*127\.0\.0\.1" ".env" >nul
if not errorlevel 1 (
  echo ERROR: .env apunta a PostgreSQL local. Sin Docker requiere PostgreSQL remoto.
  exit /b 1
)
REM En modo COMPLETO se exige que todas las URLs de Redis estén definidas:
REM con valores ausentes config.py usaría los defaults localhost, perdiendo jobs.
for %%V in (REDIS_URL CELERY_BROKER_URL CELERY_RESULT_BACKEND) do (
  findstr /B /I /C:"%%V=rediss://" ".env" >nul
  if errorlevel 1 (
    echo ERROR: falta %%V=rediss://... en .env.
    echo El modo completo necesita Redis REMOTO con TLS para Celery y chat.
    echo Para probar solo la web usa PROBAR_ACMA_WEB.bat.
    exit /b 1
  )
)
if not exist "backend\.venv\Scripts\python.exe" (
  echo ERROR: falta Python 3.12 y el entorno backend\.venv.
  exit /b 1
)
REM Validar esquema y privilegios con la conexion PRIVADA de Supabase.
pushd backend
".venv\Scripts\python.exe" -m scripts.preflight_supabase
if errorlevel 1 (
  popd
  echo ERROR: no se iniciara ACMA con una BD incorrecta.
  exit /b 1
)
popd

where npm >nul 2>nul
if errorlevel 1 (
  echo ERROR: necesitas Node.js 22+ y npm.
  exit /b 1
)
if not exist "frontend\node_modules" (
  pushd frontend
  call npm ci
  if errorlevel 1 (
    popd
    exit /b 1
  )
  popd
)
pushd frontend
echo [1/4] Compilando React original...
call npm run build
if errorlevel 1 (
  popd
  echo ERROR: compilacion fallida; no se inicia la aplicacion.
  exit /b 1
)
popd
pushd backend
echo [2/4] Iniciando Celery Worker...
start "ACMA - Worker" cmd /k ".venv\Scripts\python.exe -m celery -A workers.celery_app worker --pool=solo -l info"
echo [3/4] Iniciando Celery Beat...
start "ACMA - Beat" cmd /k ".venv\Scripts\python.exe -m celery -A workers.celery_app beat -l info"
echo [4/4] Iniciando FastAPI con React integrado...
start "ACMA - API y React" cmd /k ".venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000"
popd
echo.
echo Abre http://localhost:8000
echo Conserva abiertas las ventanas de API, Worker y Beat.
echo Se necesita acceso a PostgreSQL/Supabase y Redis externos.
echo Para Android y iPhone publica ACMA en un dominio HTTPS.
start "" "http://localhost:8000"
exit /b 0
