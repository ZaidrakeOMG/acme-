# Instrucción — Bloques prioritarios de Dirección (segunda etapa)

Por indicación de Dirección, los dos bloques marcados como prioritarios en `docs/piloto/ACMA_Segunda_Etapa.xlsx` se desarrollan ahora, en este orden y uno después del otro:

1. `docs/prompts/F2-02_WhatsApp_y_SMS.md` — Notificaciones por WhatsApp y SMS.
2. `docs/prompts/F2-03_Pantalla_Tiempo_Real.md` — Pantalla de operaciones en tiempo real (sin la alerta de desvío de ruta, que queda para el bloque de rutas).

## Cómo ejecutarlos

- Antes de empezar: confirma con `docker compose ps` que `postgres` y `redis` están *healthy* y revisa `git status` y `CONTEXTO.md` para saber si alguno de los dos ya se empezó. Si ya hay avance, **continúa desde donde quedó**; no lo repitas.
- Ejecuta F2-02 completo siguiendo su prompt al pie de la letra. Ciérralo con sus commits, `CONTEXTO.md` y `BITACORA.md`.
- Al cerrar F2-02, sin esperar otra instrucción, ejecuta F2-03 completo de la misma forma.
- Haz commits parciales por backend y frontend en cada bloque para no perder avance si la sesión se corta. Si se corta, la usuaria volverá a pegar esta misma instrucción y debes retomar desde el último commit.
- Apaga los servidores de desarrollo antes de cada corrida completa de pytest (la máquina tiene 7 GB de RAM y WSL está limitado a 4 GB) y vuelve a encenderlos al terminar.
- No contrates, no crees cuentas y no pidas contraseñas ni tokens: todo en modo simulado (`stub`). Si la usuaria quiere probar con las cuentas gratuitas de Meta o Twilio, deja la guía y espera a que ella cargue las variables.
- Commits solo locales; no configures repositorio remoto.

## Al terminar ambos

Entrega un solo resumen en español con dos secciones (F2-02 y F2-03) con lo que pide el apartado «Al terminar» de cada prompt, más:
- Qué puede probar la usuaria con qué usuario de prueba para ver cada bloque funcionando.
- Las decisiones pendientes nuevas que conviene que valide primero.
- Deja ACMA encendido (Docker, API, worker, beat y frontend) para que la usuaria lo revise.
