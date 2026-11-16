@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title ACMA - Crear superadmin adicional Zaid

echo.
echo ============================================================
echo   ACMA - ALTA DE SUPERADMIN ZAID (SUPABASE)
echo ============================================================
echo   Correo: zaidfarjat@gmail.com
echo   El password se escribe oculto y se guarda solo como hash.
echo   ACMA requiere por lo menos un simbolo en el password.
echo.
if not exist ".env" (
  echo [ERROR] No existe .env de ACMA, configura primero PROBAR_ACMA_WEB.bat.
  goto :final
)
if not exist "backend\.venv\Scripts\python.exe" (
  echo [ERROR] Falta Python. Ejecuta primero PROBAR_ACMA_WEB.bat.
  goto :final
)
pushd backend
".venv\Scripts\python.exe" -m scripts.crear_superadmin_zaid
set "ACMA_ADMIN_EXIT=%ERRORLEVEL%"
popd
echo.
if "%ACMA_ADMIN_EXIT%"=="0" (
  echo Operacion terminada. Si se creo, prueba el login en ACMA Web.
) else (
  echo [ERROR] No se pudo completar. Copia solo el error, nunca secretos.
)
:final
echo.
pause
endlocal
