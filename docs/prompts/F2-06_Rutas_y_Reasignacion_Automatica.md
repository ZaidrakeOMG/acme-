# F2-06 — Optimización de rutas (VRPTW), reasignación automática, ETA y desvío de ruta (segunda etapa, prioridad 5)

## Contexto

F2-05 (ISO 55000) está cerrado: 665 pytest y 150 vitest en verde. Lee antes de empezar `CONTEXTO.md` completo (reglas de la segunda etapa, notas de entorno, «Preventivos y reasignaciones (P06)», «SLA, alertas y BI (P10)», «Operaciones en tiempo real (F2-03)» — en particular lo que quedó pendiente para este bloque: alerta de desvío y ETA — y las decisiones pendientes), `BITACORA.md`, `docs/piloto/ACMA_Segunda_Etapa.xlsx` (bloque «Optimización de rutas y reasignación automática») y en `ACMA_Documento_Diseno_v2.5.docx`: §6.8.2 completo (reasignación automática y forzada, restricciones, catálogo de razones, tablas), §6.8.4 (desvío de ruta: 500 m por 5 min, verificación de tráfico; ETA), §4.1 (módulo Optimización de rutas), §6.10.1 (pausa del SLA por reasignación), §6.9.3 (prioridad de activos A/B) y ACT-2.1, ACT-2.2 y ACT-3.1 del §8.

Lo que ya existe y debe usarse sin duplicar: folios con `tecnico_id`, `orden_en_ruta`, `ventana_inicio` y `ventana_fin` creados desde P04 y sin uso; ubicación PostGIS de cada UN; habilidades certificadas y su restricción dura (P02, F2-01); reasignación forzada con razones, validaciones y pausa del SLA (P06, P10); existencias por vehículo y `refaccion_ok` (P09); posiciones GPS, jornadas, estatus y Redis con TTL (F2-03); alerta `TECNICO_DESVIO_RUTA` registrada como Fase 2 e inactiva y espacios reservados en el tablero (F2-03); criticidad A/B/C/D (F2-05); contador de SLA y SLA en riesgo (P10); `notificar()` con todos sus canales (P07, F2-02); y Celery con Redis.

**Regla de esta etapa:** no se contrata nada.
- **Optimización:** Google OR-Tools, librería gratuita que corre en el servidor.
- **Distancias y tiempos de traslado:** detrás de una interfaz `ProveedorDistancias` con dos implementaciones:
  - `estimado` (por defecto): distancia en línea recta × factor de sinuosidad, a una velocidad promedio por mercado y franja horaria, ambos configurables.
  - `google_routes`: preparada para Google Maps Routes API con tráfico (`departureTime`, `traffic_model`), sin llave; se activa en el paso final.
- Abrir la navegación en Waze o Google Maps desde la app del técnico se hace con enlaces gratuitos que no requieren API.

## Objetivo

Que al inicio de la jornada el sistema proponga la ruta de cada técnico respetando habilidades, ventanas de horario, SLA, criticidad, capacidad de jornada y refacciones; que durante el día recalcule solo lo afectado cuando algo cambia y proponga (o ejecute, si el prestador lo autoriza) reasignaciones automáticas; que el operador vea la hora estimada de llegada; y que se active la alerta de desvío de ruta que quedó pendiente en F2-03.

## Entregables

### 1. Migración `0018_rutas_vrptw.py`

Con los helpers de `core/sql_migracion.py`, RLS forzada en toda tabla con `tenant_id`/`prestador_id`.

| Tabla / cambio | Campos clave |
|---|---|
| `rutas_configuracion` | prestador_id, mercado_id nullable, pesos_json (distancia, SLA, criticidad, folios no asignados, horas extra — ACT-2.1), hora_inicio_jornada, duracion_jornada_min, tiempo_servicio_default_min (por tipo de folio y tipo de equipo, override en `rutas_tiempos_servicio`), factor_sinuosidad (default 1.4), velocidades_json (por franja horaria; default urbano 30 km/h, hora pico 20 km/h; anotar), modo_reasignacion_automatica ENUM(`solo_sugerir` / `aplicar_y_avisar`) default `solo_sugerir`, umbral_desvio_m (default 500), umbral_desvio_min (default 5), proveedor_distancias ENUM(`estimado` / `google_routes`) |
| `rutas_tiempos_servicio` | prestador_id, tipo_folio, tipo_equipo_id nullable, minutos_estimados (sugerencia inicial: promedio real de `fecha_inicio_atencion`→`fecha_cierre` del historial) |
| `rutas_planes` | prestador_id, mercado_id, fecha, estado ENUM(`borrador` / `publicado` / `en_curso` / `cerrado`), costo_objetivo, distancia_total_km, folios_asignados, folios_sin_asignar, tiempo_calculo_ms, calculado_por (sistema / despachador), version |
| `rutas_paradas` | plan_id, tecnico_id, folio_id, orden, llegada_estimada, inicio_servicio_estimado, fin_estimado, distancia_desde_anterior_km, minutos_desde_anterior, ventana_ok, sla_ok |
| `rutas_trazos` | plan_id, tecnico_id, geometria GEOGRAPHY(LineString) (en modo `estimado`, segmentos rectos entre paradas; en `google_routes`, la polilínea real), version |
| `rutas_recalculos` | plan_id, disparador ENUM(`desvio` / `tiempo_muerto` / `sla_en_riesgo` / `incidencia_tecnico` / `folio_nuevo_urgente` / `reasignacion_forzada` / `manual`), tecnicos_afectados, folios_movidos_json, propuesta_json, estado ENUM(`propuesta` / `aplicada` / `rechazada` / `expirada`), decidido_por, tiempo_calculo_ms, timestamp |
| `distancias_cache` | origen_hash, destino_hash, franja, proveedor, metros, segundos, calculado_at (además de Redis) |
| `reasignaciones` | ya existe (P06): usar `tipo = automatica` y vincular `recalculo_id` (agregar columna) |

### 2. Motor VRPTW (`services/rutas/`)

- Modelo en OR-Tools (Routing con dimensión de tiempo), según los parámetros de ACT-2.1:
  - **Restricciones duras:** habilidad certificada vigente; ventana de horario del folio y de la UN (horario de servicio del contrato, P04); duración de la jornada del técnico; folios ya en ejecución quedan fijos.
  - **Restricciones blandas con penalización configurable:** cumplimiento del SLA (penalización creciente al acercarse al límite); prioridad por criticidad del activo (A > B > C > D); refacciones disponibles en el vehículo (penaliza asignar sin la refacción); folio sin asignar; horas extra.
  - **Función objetivo:** minimizar distancia y tiempo más las penalizaciones.
- **Cálculo inicial:** tarea Celery por mercado a la hora configurada (y botón «Calcular rutas del día»). Genera `rutas_planes` en `borrador`; el despachador la revisa, mueve paradas a mano si quiere y **publica**. Al publicar se asignan los folios con `transicionar()` (P04), se fija `orden_en_ruta`, se notifica a cada técnico su ruta del día y los folios ya asignados a mano se respetan como fijos. Límite de tiempo de cálculo configurable (default 30 s) con la mejor solución encontrada.
- **Recálculo parcial (§6.8.2, literal):** solo los folios **pendientes** del técnico afectado, usando la posición actual de todos los técnicos activos como punto de partida; no toca folios completados ni de otros técnicos, salvo para absorber folios huérfanos. Disparadores: desvío mayor al umbral, tiempo muerto (F2-03), folio con SLA en riesgo (P10), incidencia reportada por el técnico (nuevo botón en su app: vehículo, salud, otro) y folio urgente nuevo autorizado durante el día.
- **Reasignación automática:** con `modo_reasignacion_automatica = solo_sugerir` (default), el recálculo produce una **propuesta** que el despachador acepta o rechaza con un toque en el tablero de operaciones (expira en N minutos; anotar); con `aplicar_y_avisar`, se aplica sola y se notifica a despachador y técnicos. En ambos casos se registra en `reasignaciones` con `tipo = automatica`, la razón «Optimización de ruta» o la del disparador, `reasignacion_validaciones` y la pausa de SLA de P10. Las restricciones de §6.8.2 aplican igual: nunca un folio en ejecución, nunca un técnico sin la habilidad certificada.
- **Reasignación forzada (§6.8.2, literal):** extender la de P06 para que, al reasignar, el folio salga de la ruta del técnico origen y se inserte en la **posición óptima** de la ruta del destino por inserción greedy, sin recalcular toda la ruta del destino, y que se actualicen las ETA de ambos.
- Rendimiento (ACT-2.2): medir el cálculo inicial y el recálculo parcial con escenarios de 10, 25 y 50 técnicos y 50, 150 y 300 folios; anotar los tiempos en `docs/rendimiento/resultados.md`.

### 3. ETA y navegación

- ETA de cada parada recalculada con la posición actual del técnico (F2-03) y el proveedor de distancias; actualización en vivo por el canal WebSocket existente.
- **App del operador:** en la tarjeta del folio, sustituir «Disponible en Fase 2» por «Técnico asignado · llegada estimada HH:MM» (sin mostrar la posición del técnico, como se decidió en F2-03) y aviso cuando el técnico va en camino y cuando la ETA cambia más de 15 minutos (canal según preferencias, F2-02).
- **App del técnico:** ruta del día ordenada con horario estimado por parada, mapa con su recorrido (Leaflet/OSM de F2-03) y botones «Abrir en Waze» / «Abrir en Google Maps» con enlaces de navegación gratuitos hacia la UN.
- **Tablero de operaciones:** ETA y holgura de SLA por parada; propuestas de reasignación automática pendientes con aceptar/rechazar.

### 4. Desvío de ruta (completar F2-03)

- Activar `TECNICO_DESVIO_RUTA` (`fase = 1`) con los defaults literales: más de 500 m del trazo por más de 5 minutos.
- Con proveedor `google_routes`, distancia al trazo real (polilínea). Con proveedor `estimado` no hay trazo de calles, así que comparar contra la línea recta daría falsas alarmas: usar la regla alternativa «la distancia al siguiente destino aumenta de forma sostenida durante el umbral de minutos y el técnico está fuera de un corredor configurable alrededor de la línea recta (default 2 km)»; anotarla como decisión pendiente y dejar ambas reglas probadas.
- Verificación de tráfico (§6.8.4): con `google_routes`, consultar si hay tráfico que justifique el desvío antes de alertar; con `estimado`, no aplica y se indica en la alerta.
- Fila en amarillo en el panel de técnicos (espacio reservado en F2-03) y disparo del recálculo parcial como sugerencia.

### 5. Endpoints

`/api/rutas` (configuración, tiempos de servicio, calcular, ver plan por mercado y fecha, mover parada, publicar, recalcular, propuestas, aceptar/rechazar, trazos, simulación «¿qué pasa si…?» sin aplicar) y ampliación de `/api/operacion` (ETA, incidencias del técnico). Multitenancy validado en servicio además de RLS; auditoría con `registrar_actor` en publicar, aceptar o rechazar propuestas y en reasignaciones automáticas.

### 6. Frontend

- Nuevo módulo `rutas` en `src/config/modulos.ts` (grupo Operación) para Despachador, Admin prestador, Mesa de control (lectura) y Superadmin: `pages/rutas/PlanDelDia.tsx` con mapa por técnico (colores por ruta y texto), lista de paradas con horario, holgura de SLA, criticidad y refacciones; arrastre para mover paradas entre técnicos con validación en vivo; indicadores del plan (km totales, folios sin asignar con su motivo); botones calcular y publicar; configuración de pesos, velocidades y tiempos de servicio (solo Admin prestador) con explicación en lenguaje claro de cada peso.
- Tablero de operaciones (F2-03): ETA por parada, propuestas de reasignación, fila amarilla de desvío y quitar las leyendas «Fase 2» de ETA y desvío.
- Apps del técnico y del operador como en la sección 3; botón «Reportar incidencia» en la app del técnico.

### 7. Seed y pruebas

- Seed: configuración de rutas para el mercado demo con velocidades y tiempos de servicio; 18 folios abiertos del día con ventanas y SLA variados y equipos de distinta criticidad; un plan calculado y publicado; un técnico con desvío simulado por `simular_jornada.py` (ampliarlo) y una propuesta de reasignación automática pendiente.
- Backend (`tests/test_vrptw_restricciones.py`, `tests/test_vrptw_recalculo.py`, `tests/test_reasignacion_automatica.py`, `tests/test_insercion_greedy.py`, `tests/test_eta.py`, `tests/test_desvio_ruta.py`, `tests/test_proveedor_distancias.py`): nunca asigna sin habilidad certificada vigente; respeta ventanas y jornada; prioriza A sobre D y folios cerca de vencer SLA; penaliza la falta de refacción; folio en ejecución fijo; folios asignados a mano respetados; el recálculo parcial no toca a otros técnicos salvo huérfanos; la propuesta en `solo_sugerir` no cambia nada hasta aceptarse y expira; `aplicar_y_avisar` reasigna con pausa de SLA y registro; la inserción greedy coloca el folio en la mejor posición sin recalcular toda la ruta; ETA con posición actual; aviso de cambio de ETA mayor a 15 min; desvío con las dos reglas (trazo y estimada) y sin falsas alarmas en línea recta; caché de distancias; `google_routes` con respuesta simulada (ninguna prueba llama a Google); tiempos de cálculo dentro del límite; aislamiento entre prestadores y mercados; RLS forzada en las tablas nuevas.
- Frontend: plan del día con mover parada y publicar, aceptar propuesta en el tablero, ETA en la app del operador, botones de navegación del técnico.
- `pytest`, `vitest`, `tsc --noEmit` y `npm run build` en verde, con los servidores de desarrollo apagados durante la suite completa.

## Reglas (vigentes)

1. Seguir el Documento de Diseño v2.5; lo no definido se anota en `CONTEXTO.md` como decisión pendiente de validación, y las que deba responder el negocio también en `docs/decisiones_para_validar.md`.
2. Multitenancy validado en servicio además de RLS.
3. Sin contratar proveedores: OR-Tools y distancias estimadas; Google Routes preparado sin llave.
4. Identificadores en español sin acentos.
5. Cerrar con `CONTEXTO.md` (avance F2-06 ✅; sección «Rutas y reasignación automática (F2-06)» con los pesos, la regla de desvío en cada modo, los tiempos medidos y lo necesario para activar Google Routes en producción) y `BITACORA.md` actualizados.
6. No cambiar el stack (OR-Tools es librería de Python; anotar versión).
7. No correr la suite completa con los servidores de desarrollo encendidos; volver a encenderlos al terminar y dejar ACMA encendido para la revisión de la usuaria.
8. Commits solo locales; si el trabajo es largo, «F2-06 (1/2) backend» y «F2-06 (2/2) frontend». Si la sesión se corta, retomar desde el último commit.
9. Los triggers de inmutabilidad no se desactivan bajo ninguna circunstancia en este prompt.

## Al terminar

Resumen en español con: tablas de la migración 0018, endpoints, restricciones y pesos elegidos, regla de desvío en cada modo, tiempos de cálculo medidos (10/25/50 técnicos), cómo ver la demostración (usuario, mercado y técnico con desvío), qué falta para activar Google Routes, decisiones pendientes nuevas y conteo de pruebas.
