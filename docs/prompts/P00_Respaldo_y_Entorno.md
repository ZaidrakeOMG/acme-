# Paso 0 — Estabilidad del entorno (antes de la segunda etapa)

## Contexto

La Fase 1 está cerrada (último commit `92aae09`, P11a). Antes de empezar la segunda etapa hay que estabilizar la máquina de desarrollo. Este paso **no cambia código de la aplicación**.

**Por decisión de la usuaria, en este paso NO se crea repositorio remoto ni se sube el código a GitHub ni a ningún otro servicio.** El repositorio sigue siendo solo local en `C:\Users\lilia\Desktop\acma`. No usar `git push`, `gh repo create` ni configurar remotos. El proyecto anterior `Liliana0315/ACMA` no se toca.

## Tareas

### 1. Registrar lo pendiente

`git status`: hay una carpeta sin registrar, `docs/piloto/` (dos libros de Excel de pruebas piloto y segunda etapa), y el prompt `docs/prompts/P00_Respaldo_y_Entorno.md`. Agregarlos en un commit local `docs: guía de pruebas piloto, segunda etapa y paso 0`.

### 2. Límite de memoria para WSL y Docker

Docker se ha caído varias veces porque WSL ocupa toda la memoria cuando corren a la vez Docker, pytest y los servidores de desarrollo.

1. Medir la RAM total y los núcleos lógicos de la computadora (`Get-CimInstance Win32_ComputerSystem` y `Get-CimInstance Win32_Processor`).
2. Crear o actualizar `%USERPROFILE%\.wslconfig` (respetando lo que ya tenga) con:
   ```
   [wsl2]
   memory=<la mitad de la RAM, redondeada hacia abajo en GB, mínimo 4GB>
   swap=4GB
   processors=<la mitad de los núcleos lógicos, mínimo 2>

   [experimental]
   autoMemoryReclaim=gradual
   ```
3. Avisar a la usuaria que Docker se reiniciará y que no tenga ACMA abierto; cerrar Docker Desktop, ejecutar `wsl --shutdown`, volver a abrir Docker Desktop y esperar «Engine running».
4. Verificar con `docker compose ps` que `postgres` y `redis` quedan *healthy* y que la API arranca y responde en `/api/salud`; después apagar la API.
5. Anotar el cambio y los valores elegidos en `CONTEXTO.md` (notas de entorno) junto al procedimiento de recuperación de Docker ya documentado.

### 3. Regla de trabajo para la segunda etapa

Agregar a `CONTEXTO.md`, en las reglas del proyecto:

- La segunda etapa (prompts `F2-xx`) se desarrolla con todas las integraciones externas en modo simulado o con cuentas de prueba gratuitas; ninguna contratación ni publicación hasta el paso final.
- Cada prompt cierra con un commit local; los trabajos largos se dividen en commits parciales para no perder avance si la sesión se corta.
- El repositorio remoto queda pendiente hasta que la usuaria lo autorice.

## Al terminar

Resumen en español con: commit realizado, valores de `.wslconfig` aplicados y estado de los contenedores.
