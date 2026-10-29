@echo off
REM ACMA - Cierra las ventanas de servicios y apaga los contenedores de Docker.
cd /d "%~dp0"
for %%T in ("ACMA - API" "ACMA - Worker" "ACMA - Beat" "ACMA - Frontend") do taskkill /FI "WINDOWTITLE eq %%~T*" /T /F >nul 2>&1
docker compose stop
echo ACMA detenido.
pause
