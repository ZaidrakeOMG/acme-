@echo off
setlocal EnableExtensions
REM ACMA: primera prueba REAL de React + FastAPI + Supabase, sin Docker.
REM Este modo NO inicia Celery/Beat y no equivale a produccion.
cd /d "%~dp0"
echo.
echo ===== ACMA - PRUEBA WEB CON SUPABASE =====
echo.
where py >nul 2>nul
if errorlevel 1 (
  echo ERROR: instala Python 3.12 y selecciona "Add Python to PATH".
  exit /b 1
)
where npm >nul 2>nul
if errorlevel 1 (
  echo ERROR: instala Node.js 22 o superior.
  exit /b 1
)
if not exist "backend\.venv\Scripts\python.exe" (
  echo [1/5] Preparando Python 3.12...
  py -3.12 -m venv backend\.venv
  if errorlevel 1 exit /b 1
)
if not exist "backend\.venv\.dependencias_web_acma_ok" (
  echo [2/5] Instalando dependencias del proyecto original...
  "backend\.venv\Scripts\python.exe" -m pip install -r backend\requirements.txt
  if errorlevel 1 (
    echo ERROR: no se pudieron instalar las dependencias. No se iniciara la web.
    exit /b 1
  )
  echo ok>"backend\.venv\.dependencias_web_acma_ok"
)
if not exist ".env" (
  echo [3/5] Configurando Supabase y primer usuario admin en esta computadora...
  "backend\.venv\Scripts\python.exe" scripts\configurar_acma_supabase.py
  if errorlevel 1 (
    echo ERROR: configuracion incompleta. Revisa el mensaje anterior.
    exit /b 1
  )
)
if not exist ".env" (
  echo ERROR: no existe el archivo .env privado.
  exit /b 1
)
pushd backend
".venv\Scripts\python.exe" -m scripts.preflight_supabase
if errorlevel 1 (
  popd
  echo ERROR: no se puede usar PostgreSQL como acma_api.
  exit /b 1
)
popd
echo [4/5] Compilando la interfaz React ORIGINAL...
pushd frontend
if not exist node_modules (
  call npm ci
  if errorlevel 1 (
    popd
    exit /b 1
  )
)
call npm run build
if errorlevel 1 (
  popd
  echo ERROR: la web no compila. La API no se iniciara.
  exit /b 1
)
popd
echo.
echo [5/5] Iniciando ACMA WEB en http://localhost:8000
echo En otra pestana abre http://localhost:8000
echo Para cerrar el servidor usa CTRL+C.
echo Nota: las tareas automaticas necesitan Redis/Celery remoto; NO se prueban aqui.
echo.
pushd backend
".venv\Scripts\python.exe" -m uvicorn main:app --host 127.0.0.1 --port 8000
set "CODIGO=%ERRORLEVEL%"
popd
exit /b %CODIGO%
