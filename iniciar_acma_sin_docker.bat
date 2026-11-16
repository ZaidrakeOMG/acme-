@echo off
setlocal
REM Modo sin Docker: requiere Supabase/Postgres remoto ya migrado, no crea ninguna tabla.
cd /d "%~dp0"
if not exist ".env" (
  echo Falta .env. Configura uno para ACMA exclusivamente.
  exit /b 1
)
findstr /i /c:"localhost:5442" ".env" >nul
if not errorlevel 1 (
  echo ERROR: .env sigue conectado a PostgreSQL Docker local.
  echo No se inicia hasta configurar y validar la base remota de ACMA.
  exit /b 1
)
if not exist "backend\.venv\Scripts\python.exe" (
  echo ERROR: crea el entorno Python en backend\.venv antes de iniciar.
  exit /b 1
)
where npm >nul 2>nul
if errorlevel 1 (
  echo ERROR: necesitas Node.js y npm.
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
call npm run build
if errorlevel 1 (
  echo ERROR: no se pudo compilar React. No se inicia la API.
  popd
  exit /b 1
)
popd
echo Iniciando React + FastAPI en http://localhost:8000
pushd backend
".venv\Scripts\python.exe" -m uvicorn main:app --host 127.0.0.1 --port 8000
set "EXIT_CODE=%ERRORLEVEL%"
popd
exit /b %EXIT_CODE%
