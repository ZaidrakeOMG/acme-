@echo off
REM ACMA - Inicia todos los servicios en tu computadora y abre el navegador.
REM Cada servicio abre su propia ventana; no las cierres mientras uses ACMA.
cd /d "%~dp0"
echo [1/5] Base de datos, Redis y MinIO (Docker)...
docker compose up -d
echo [2/5] API...
start "ACMA - API" cmd /k "cd backend && .venv\Scripts\python -m uvicorn main:app --port 8000"
echo [3/5] Worker de tareas...
start "ACMA - Worker" cmd /k "cd backend && .venv\Scripts\celery -A workers.celery_app worker --pool=solo -l info"
echo [4/5] Programador de tareas...
start "ACMA - Beat" cmd /k "cd backend && .venv\Scripts\celery -A workers.celery_app beat -l info"
echo [5/5] Interfaz web (tambien accesible desde el celular en la misma red Wi-Fi)...
start "ACMA - Frontend" cmd /k "cd frontend && npm run dev -- --host"
echo Esperando a que arranque...
timeout /t 10 >nul
start http://localhost:5173
echo.
echo ACMA esta corriendo. Usuarios de prueba: ver README.md (contrasena de todos: Demo#Acma2026)
echo Para apagar todo ejecuta detener_acma.bat
pause
