# F2-03 — Pantalla de operaciones en tiempo real (segunda etapa, prioridad 2 de Dirección)

## Contexto

Este prompt se ejecuta **después de cerrar F2-02** (WhatsApp y SMS). Lee antes de empezar `CONTEXTO.md` completo (reglas de la segunda etapa, notas de entorno y la sección de F2-02), `BITACORA.md`, `docs/piloto/ACMA_Segunda_Etapa.xlsx` (hoja «Bloques Fase 2», bloque «Pantalla de operaciones en tiempo real») y en `ACMA_Documento_Diseno_v2.5.docx`: §6.8.4 completo (arquitectura de actualización GPS, elementos de la pantalla, detección de tiempo muerto, desvío y sin señal), §6.8.6 (el estado «En camino» lo puede marcar el sistema por posición GPS), §6.9.6 (alertas `TECNICO_TIEMPO_MUERTO`, `TECNICO_DESVIO_RUTA`, `TECNICO_SIN_SEÑAL`), §6.9.5 (privacidad y auditoría), §4.1 (módulo Pantalla de operaciones) y ACT-3.2 del §8.

**Alcance decidido por Dirección:** se desarrolla la pantalla completa **excepto la alerta de desvío de ruta**, porque necesita la ruta planeada que calcula el bloque «Optimización de rutas y reasignación automática», que se hará después. La alerta `TECNICO_DESVIO_RUTA` permanece como Fase 2 y su espacio en la pantalla queda preparado. Tampoco se calcula ETA por tráfico (también es del bloque de rutas).

Lo que ya existe y debe usarse sin duplicar: la tabla `tecnicos` (P02), `unidades_negocio.ubicacion` con PostGIS (P01), los estados del folio y `transicionar()` (P04), el canal WebSocket con Redis pub/sub y respaldo SSE del chat (P05), la barra de «Indicadores globales de jornada» del despachador (P10), el contador de SLA y la alerta de SLA en riesgo (P10), las reasignaciones (P06), `notificar()` con push, WhatsApp y SMS (P07 y F2-02), la configuración central de alertas con sus rangos (P10) y la auditoría y el cifrado de P11a.

**Regla de esta etapa:** no se contrata nada. El mapa usa **OpenStreetMap con Leaflet** (gratuito, sin cuenta) detrás de una interfaz de proveedor de mapas; Google Maps se podrá activar en el paso final cambiando la configuración.

## Objetivo

Que el despachador y el Admin prestador vean durante la jornada, en un solo tablero que se actualiza solo, dónde está cada técnico, qué está haciendo, qué folios están en riesgo de incumplir el SLA y qué alertas requieren acción, y que el sistema detecte automáticamente al técnico detenido fuera de su destino y al técnico sin señal.

## Entregables

### 1. Migración `0015_operaciones_tiempo_real.py`

Con los helpers de `core/sql_migracion.py`, RLS forzada en toda tabla con `tenant_id`/`prestador_id`.

| Tabla / cambio | Campos clave |
|---|---|
| `tecnicos` | agregar `ultima_posicion GEOGRAPHY(Point)`, `ultima_posicion_at`, `ultima_precision_m`, `ultima_bateria_pct`, `estatus_operativo` ENUM(`fuera_de_jornada` / `en_ruta` / `en_servicio` / `pausa` / `sin_senal`) (§6.8.4) |
| `jornadas_tecnico` | tecnico_id, prestador_id, inicio, fin, estado ENUM(`activa` / `pausa` / `cerrada`), dispositivo_id, cerrada_por (técnico / sistema por inactividad / despachador) |
| `jornada_pausas` | jornada_id, inicio, fin, motivo (comida, trámite, otro) |
| `tecnico_posiciones` | tecnico_id, prestador_id, jornada_id, posicion GEOGRAPHY(Point), precision_m, velocidad_mps, rumbo, bateria_pct, capturada_at (hora del dispositivo), recibida_at, tardia (bool: llegó después por falta de señal) — **particionada por día**, con índice espacial y por técnico/fecha |
| `alertas_operacion_seguimiento` | alerta_historial_id, tipo, tecnico_id, folio_id nullable, push_al_tecnico_at, respuesta_tecnico (`estoy_bien` / `necesito_apoyo` / null), respondida_at, escalada_at |

Retención de `tecnico_posiciones`: 90 días por defecto con `DETACH` + `DROP` de particiones (mismo mecanismo de P11a); conservar solo la posición de llegada y de cierre de cada folio en el historial del folio de forma permanente. Anotar la retención como decisión para validar (privacidad).

### 2. Envío de posición desde la app del técnico (§6.8.4 «Arquitectura de actualización GPS»)

- Inicio y fin de jornada y pausas desde la app del técnico (botones visibles en «Mis folios»). Sin jornada activa **no se envía ninguna posición** (anotar como regla de privacidad).
- `navigator.geolocation.watchPosition` con las frecuencias literales del diseño: cada 30 s en jornada activa, cada 5 min en pausa, cada 2 min si la batería baja del 20 % (Battery Status API donde exista; si no, usar el intervalo normal y anotarlo). No envía cuando la app se cierra o se bloquea el teléfono (§6.8.4).
- Envío por `POST /api/operacion/posiciones` en lotes pequeños; sin señal, las posiciones se guardan en IndexedDB (nueva tabla Dexie `posiciones_pendientes`) y se envían al reconectar marcadas como `tardia`, sin generar movimientos falsos en el mapa.
- El servidor actualiza `tecnicos.ultima_posicion` y `ultima_posicion_at`, guarda la posición actual en Redis con TTL de 2 minutos y publica un evento por WebSocket al tablero del prestador correspondiente (solo al prestador del técnico; nunca a otro prestador ni a usuarios del cliente).
- Aviso al técnico la primera vez que inicia jornada: qué se registra, cuándo y para qué, con aceptación registrada; texto en `docs/decisiones_para_validar.md` para revisión legal (datos de geolocalización de empleados).

### 3. Estados automáticos

- `estatus_operativo` se calcula: `en_servicio` si tiene un folio en `en_ejecucion`; `en_ruta` si tiene folio en `en_camino` o se está moviendo con folios pendientes; `pausa` si la jornada está en pausa; `sin_senal` si `ultima_posicion_at` supera el umbral; `fuera_de_jornada` si no hay jornada activa.
- Llegada sugerida por geocerca: cuando la posición del técnico entra en el radio de la UN de su folio en `en_camino` (radio configurable, default 150 m), la app le propone «Confirmar llegada» con un toque. **No transicionar sola a `en_ejecucion`**: la confirmación sigue siendo del técnico (§6.8.6). Registrar la hora de entrada a la geocerca en el folio como dato adicional para el SLA de respuesta (solo informativo; no cambia la regla de P10; anotar).

### 4. Detección automática (§6.8.4)

Evaluadores registrados con `@registrar_evaluador`, cada minuto, con umbrales de la configuración central (P10). Cambiar `fase` a 1 en el catálogo para las dos alertas que se activan:

- **`TECNICO_TIEMPO_MUERTO`** (default 20 min): técnico en jornada activa sin moverse (todas las posiciones del periodo dentro de un radio de 50 m, configurable) en un punto que **no** es la UN destino de su folio en curso. Acción literal: alerta en el panel del despachador y push al técnico preguntando si necesita asistencia con dos respuestas («Estoy bien» / «Necesito apoyo»); si pasan otros 10 minutos sin respuesta, escala al Admin prestador. «Necesito apoyo» genera alerta de prioridad alta inmediata al despachador. No se dispara durante pausas ni dentro de la geocerca de una UN.
- **`TECNICO_SIN_SENAL`** (default 15 min): sin posición recibida en jornada activa. Marcador gris con la etiqueta «Sin señal desde HH:MM» y alerta al despachador. **No se genera alerta de emergencia automáticamente: el despachador decide** (§6.8.4).
- **`TECNICO_DESVIO_RUTA`**: permanece con `fase = 2`, inactiva, con la nota «requiere el bloque de optimización de rutas».
- Cierre automático de jornada: si el técnico no la cierra y no hay posiciones ni actividad en X horas (default 2 h) después de su último folio, cerrarla con `cerrada_por = sistema` (anotar).

### 5. Tablero de operaciones (§6.8.4 «Elementos de la pantalla»)

Página `pages/operaciones/Operaciones.tsx`, módulo nuevo `operaciones` en `src/config/modulos.ts` (grupo Operación) para Despachador, Admin prestador, Mesa de control (solo lectura) y Superadmin; el Despachador ve solo los técnicos y folios de su mercado (misma regla de alcance de P04).

- **Mapa en vivo:** Leaflet con mapas de OpenStreetMap detrás de una interfaz `ProveedorMapa` (`osm` por defecto; `google` preparado para el paso final, sin llave). Un marcador por técnico en jornada con nombre, estatus (color + texto) y número de folios pendientes del día; clic → panel con el detalle del técnico, sus folios y su recorrido de las últimas 2 horas. Marcadores de las UN con folios activos. El mapa actualiza solo el marcador que cambió (sin redibujar todo). Controles para centrar en un técnico, en una UN o en todo el mercado.
- **Panel de técnicos:** lista ordenable por estatus, folios pendientes y tiempo en el estatus actual; fila en rojo con alerta activa; el amarillo de desvío queda reservado para el bloque de rutas.
- **Panel de folios activos del día:** estatus, técnico, UN, tiempo restante antes de vencer el SLA (contador regresivo con el contador de P10); folios con SLA en riesgo en rojo; ordenable por urgencia.
- **Panel de alertas:** feed cronológico con tiempo muerto, sin señal, SLA en riesgo, reasignaciones recientes y folios autorizados sin técnico asignado; cada alerta con su botón de acción directa (llamar o mandar mensaje al técnico desde el chat del folio, abrir el folio, reasignar con el flujo de P06, marcar atendida).
- **Indicadores globales de jornada:** reutilizar la barra de P10 y actualizarla en vivo.
- Tiempo real por el WebSocket existente (canal por prestador y mercado) con respaldo SSE; reconexión automática e indicador de «datos en vivo / reconectando».
- Diseño pensado para pantalla grande de oficina y usable en laptop; colores accesibles y estatus siempre también en texto.

### 6. Privacidad y seguridad

- Las posiciones son visibles solo para el prestador del técnico (Despachador de su mercado, Mesa de control, Admin prestador, Superadmin). El cliente **no** ve posiciones de técnicos (anotar; el «ETA al operador» es del bloque de rutas).
- El técnico puede consultar su propio historial de posiciones del día.
- Auditoría de acceso a datos sensibles (P11a) al consultar el recorrido de un técnico.
- Pruebas de carga: medir la recepción de posiciones con 50 técnicos enviando cada 30 s (100 posiciones por minuto) junto con el uso normal, con los scripts de Locust de P11a, y anotar el resultado.

### 7. Seed y pruebas

- Seed: jornadas activas para los 4 técnicos demo con recorridos simulados de la última hora entre las 3 UN (un técnico en servicio, uno en ruta, uno detenido 25 min fuera de destino y uno sin señal desde hace 20 min), y un script `scripts/simular_jornada.py` que envía posiciones en vivo cada pocos segundos para demostrar la pantalla sin salir a la calle.
- Backend (`tests/test_operacion_posiciones.py`, `tests/test_operacion_estatus.py`, `tests/test_alertas_operacion.py`, `tests/test_operacion_tablero.py`): sin jornada no se aceptan posiciones; frecuencias no se validan en el servidor pero sí el lote y la precisión; posiciones tardías no alteran la última posición si son más viejas; Redis con TTL; evento WebSocket solo al prestador correcto; estatus calculado en cada caso; geocerca propone llegada sin transicionar; tiempo muerto dispara, no dispara en pausa ni en la UN destino, push al técnico, escalación a los 10 min y «Necesito apoyo»; sin señal no genera emergencia; desvío sigue inactivo como Fase 2; cierre automático de jornada; retención por partición; el cliente no puede consultar posiciones (RLS y HTTP); aislamiento entre prestadores; RLS forzada en las tablas nuevas.
- Frontend: inicio/fin de jornada y pausa; cola de posiciones sin señal (con `fake-indexeddb` y geolocalización simulada); tablero que mueve un marcador al recibir un evento; panel de alertas con acción.
- `pytest`, `vitest`, `tsc --noEmit` y `npm run build` en verde, con los servidores de desarrollo apagados durante la suite completa.

## Reglas (vigentes)

1. Seguir el Documento de Diseño v2.5; lo no definido se anota en `CONTEXTO.md` como decisión pendiente de validación.
2. Multitenancy validado en servicio además de RLS.
3. Sin contratar proveedores: OpenStreetMap/Leaflet en desarrollo; Google Maps queda preparado sin llave.
4. Identificadores en español sin acentos.
5. Cerrar con `CONTEXTO.md` (avance F2-03 ✅; sección «Operaciones en tiempo real (F2-03)» con las frecuencias, los umbrales, la retención de posiciones, lo que queda para el bloque de rutas —desvío y ETA— y lo necesario para producción) y `BITACORA.md` actualizados.
6. No cambiar el stack (Leaflet y su envoltorio para React son librerías del frontend; anotar versiones).
7. No correr la suite completa con los servidores de desarrollo encendidos.
8. Commits solo locales; si el trabajo es largo, «F2-03 (1/2) backend» y «F2-03 (2/2) frontend».

## Al terminar

Resumen en español con: tablas de la migración 0015, endpoints y eventos de tiempo real, reglas de estatus y de alertas con sus umbrales, retención de posiciones, resultado de la prueba de carga de posiciones, cómo ver la demostración con `simular_jornada.py`, decisiones pendientes nuevas y conteo de pruebas.
