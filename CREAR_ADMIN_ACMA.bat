@echo off
setlocal
cd /d "%~dp0"
if not exist ".env" (
  echo ERROR: configura primero Supabase con PROBAR_ACMA_WEB.bat.
  exit /b 1
)
if not exist "backend\.venv\Scripts\python.exe" (
  echo ERROR: prepara Python con PROBAR_ACMA_WEB.bat.
  exit /b 1
)
echo.
echo ACMA - Crear o completar el primer administrador
echo Utiliza las plantillas ORIGINALES de produccion, sin datos de ejemplo.
echo.
"backend\.venv\Scripts\python.exe" scripts\crear_admin_acma.py
if errorlevel 1 (
  echo ERROR: no se creo el administrador.
  pause
  exit /b 1
)
echo.
echo Guarda la contraseña temporal que aparecio en esta consola.
pause
exit /b 0
