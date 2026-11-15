# CONTEXTO — Estado del proyecto ACMA (desarrollo nuevo)

> Se actualiza al cierre de cada prompt. Última actualización: **2026-11-13 · F2-06 Rutas del día y reasignación automática**.

## Ubicación y relación con acma-proyecto

- Este repositorio (`C:\Users\lilia\Desktop\acma`) es el **desarrollo nuevo desde cero** definido en
  `ACMA_Alcance_Fases_v1.0.docx` (11 prompts de Fase 1).
- `C:\Users\lilia\Desktop\acma-proyecto` es la implementación anterior. **No se toca.** Ambos conviven: este proyecto usa
  puertos y contenedores distintos (`acma_nuevo_*`, PostgreSQL 5442, Redis 6389, MinIO 9010/9011).

## Avance por prompt

| Prompt | Contenido | Estado |
|---|---|---|
| P01 | Cimientos: repo, Docker, modelo base, RLS, auth + MFA, API base, PWA con login y hub | ✅ 2026-10-19 |
| P02 | Catálogos maestros (técnicos y habilidades, equipos, fallas, severidades, matriz, importador) | ✅ 2026-10-23 |
| P03 | Motor de formularios: 22 tipos de campo, constructor, versiones, asignaciones, respuestas y evidencias | ✅ 2026-10-23 |
| P04 | Folios: ciclo de vida de 11 estados, validaciones automáticas en captura y aprobación multinivel | ✅ 2026-10-27 |
| P05 | Apps PWA del operador y del técnico, modo offline (cola idempotente) y chat archivado con tiempo real | ✅ 2026-10-28 |
| P06 | Calendario de preventivos, planes con triggers de Fase 1, autorizaciones y reasignación forzada | ✅ 2026-10-28 |
| P07 | Minuta del día por UN y global, notificaciones multicanal (correo SMTP), cuatro módulos de seguimiento y clasificación de no críticos | ✅ 2026-10-29 |
| P08 | Trabajos especiales con validación del cliente, conversión de cotizaciones y seguimiento de OC de activos | ✅ 2026-10-29 |
| P09 | Inventario con los tres orígenes de refacción, caja chica manual, costo del folio, presupuestos, capa ERP y activos con TCO | ✅ 2026-11-02 |
| P10 | Contratos con iguala y contador de SLA, penalizaciones, configuración central de alertas, tableros por rol y reportes ejecutivos | ✅ 2026-11-02 |
| P11a | Endurecimiento: seguridad de §6.9.5, pruebas de carga, respaldos con restauración medida y paquete de producción | ✅ 2026-11-05 |
| P11b | Publicación en `acma.unai.com.mx` con el servidor definitivo y los datos reales de UNAI | Pendiente |
| F2-01 | Capacitación y certificaciones del personal, biblioteca de manuales con versiones y contenido de servicio contractual, con descarga para uso sin señal | ✅ 2026-11-07 |
| F2-02 | Notificaciones por WhatsApp y SMS: plantillas aprobables por Meta, consentimiento del destinatario, horario de silencio, tope de gasto, enlace corto propio y minuta por WhatsApp | ✅ 2026-11-10 |
| F2-03 | Pantalla de operaciones en tiempo real: jornada del técnico con GPS, mapa en vivo con OpenStreetMap, estatus automático, geocerca de llegada, tiempo muerto y sin señal | ✅ 2026-11-10 |
| F2-04 | Medidores de activos y planes de mantenimiento por uso: los seis tipos de medidor, lecturas por los cuatro métodos, los cuatro triggers que faltaban, depreciación por unidades producidas y llaves de API para recibir lecturas | ✅ 2026-11-11 |
| F2-05 | ISO 55000: criticidad A/B/C/D calculada como probabilidad × impacto, FMEA simplificado con mitigaciones y su efectividad medida, implicaciones por nivel como alerta o restricción y cinco reportes de certificación | ✅ 2026-11-11 |
| F2-06 | Rutas del día con VRPTW en OR-Tools (habilidades, ventanas, SLA, criticidad, jornada y refacciones), recálculo parcial con propuestas que vencen, reasignación automática en dos modos, ETA para el cliente, alerta de desvío de ruta y navegación gratuita en la app del técnico | ✅ 2026-11-13 |

## Verificación al cierre de F2-05

- Migración `0017_iso55000_criticidad.py` aplicada (subida, bajada y subida), con `criticidad_configuracion`,
  `activo_criticidad`, `criticidad_evaluaciones` (**append-only**), `activo_modos_falla` y
  `activo_riesgo_mitigacion`; RLS forzada en las cinco, `criticidad_evaluaciones` sin privilegio DELETE para
  `acma_api` y con políticas solo de SELECT e INSERT (así un UPDATE no encuentra ni una fila), más el trigger
  `acma_auditoria_inmutable()` como tercer cerco.
- **665 pytest** en verde **con los servidores de desarrollo apagados** (37:28). 77 pruebas nuevas
  de F2-05 en `test_criticidad_calculo.py`, `test_criticidad_revision.py`, `test_modos_falla.py`,
  `test_mitigacion.py`, `test_implicaciones_criticidad.py` y `test_reportes_iso55000.py`.
- **150 vitest** (13 nuevos en `criticidad.test.tsx`), `tsc --noEmit` y `npm run build` en verde.
- Las dos pruebas guardián de P11a volvieron a hacer su trabajo: `test_acceso_cruzado` pidió declarar de dónde
  sacar un `modo_id` y un `mitigacion_id` reales, y `test_permisos_roles` acusó el catálogo de alertas de 64 a 69.
- Pruebas de otros prompts que cambiaron porque F2-05 cambia lo que afirmaban: el importador pasó de 12 a 13
  catálogos, la ficha del activo dejó de etiquetar la criticidad y el FMEA como «Fase 2» (ahora dice de dónde salió
  el nivel: cálculo o ajuste manual), y `test_formularios` ya no afirma que el catálogo de equipos del segundo
  cliente esté **vacío**, sino que no trae equipos del demo: la prueba de la probabilidad anónima por tipo de equipo
  necesita darle de alta uno, y lo que esa afirmación cuida es el aislamiento, no que el catálogo esté vacío.
- La primera corrida completa marcó 14 fallas; dos eran reales (la afirmación de «Fase 2» en la ficha y la
  contaminación del catálogo del segundo cliente) y están corregidas. Las otras doce no se reprodujeron ni juntas ni
  por archivo, así que quedan como ruido de esa corrida: la segunda corrida completa salió limpia.
- **Dos defectos propios que encontraron las pruebas**, los dos corregidos y con su prueba:
  - `_meses_de_historia` medía la observación desde el primer folio del equipo, así que un activo instalado en 2024
    con una sola falla reciente parecía nuevo y su probabilidad salía prestada del tipo de equipo en lugar de su
    propio historial. Ahora un activo **sin un solo folio** sigue dando 0 (no se ha observado nada), pero con
    folios la observación se cuenta desde lo más antiguo que ACMA sabe de él.
  - La implicación «técnico certificado» activada como **restricción** no restringía nada: la levantaba la razón del
    permiso `asignar_tecnico_sin_habilidad`, y sin esa razón la asignación ya se había frenado antes. Ahora solo el
    Superadmin la pasa.
- **Reparación de la base de desarrollo (autorizada por la usuaria).** El demo mostraba A, B y C pero no D, y no
  era la fórmula: `scripts/seed_historico` se había corrido cuando el cliente demo tenía doce equipos, así que sus
  1,200 folios sintéticos quedaron apilados en esos doce (52 a 81 fallas al año cada uno) y con esa densidad la
  probabilidad sale 5 para todos y el índice mínimo alcanzable es 20.00, justo la frontera de C. Se repartieron esos
  folios entre los 419 equipos de sus tres UNs conservando número, costo, SLA, fechas y UN —lo único que cambió es a
  qué activo de esa misma UN pertenece cada uno, así que los totales del tablero no se movieron—, y después se
  completó el historial de los doce hasta su banda y se reevaluaron. **El folio cerrado es inmutable por diseño**:
  se desactivó solo `trg_folios_inmutable`, en una transacción, y quedó activo otra vez al terminar; el mapeo previo
  se respaldó antes. Hoy el demo muestra **2 A (EQ-0001 con plan y EQ-0002 sin plan), 2 B, 4 C y 4 D**, con 10 modos
  de falla, 6 mitigaciones y las alertas `ACTIVO_CRITICO_SIN_PLAN` y `MITIGACION_VENCIDA` disparadas. La lección
  quedó escrita en el encabezado de `seed_historico`: ese seed se corre **al final**, con el parque ya cargado.

- El seed demo deja los doce equipos con **los cuatro niveles saliendo del cálculo** (2 A, 2 B, 4 C y 4 D), y
  completa el historial de fallas de cada uno hasta la banda de probabilidad que le toca contando lo que ya le
  dejaron los otros seeds: así la demo no depende de cuántos folios haya generado antes el seed base.

## Verificación al cierre de F2-04

- Migración `0016_medidores_planes_uso.py` aplicada (subida, bajada y subida), con las cuatro tablas literales de
  §6.9.2 más `medidor_cambios`, `eventos_trigger_catalogo` y `llaves_api_tenant`; RLS forzada en las seis que
  tienen dueño y `medidor_lecturas` sin privilegio DELETE para `acma_api`.
- **588 pytest** en verde **con los servidores de desarrollo apagados** (28:45), más 1 saltado a propósito. 45
  pruebas nuevas de F2-04 en `test_medidores.py`, `test_medidor_lecturas.py`, `test_triggers_medidor.py`,
  `test_trigger_evento.py`, `test_trigger_combinado.py`, `test_depreciacion_unidades.py`,
  `test_lecturas_api_llave.py` y una del importador.
- Las dos pruebas guardián de P11a hicieron su trabajo: `test_acceso_cruzado` pidió declarar de dónde sacar un
  `medidor_id` real (y ahora barre `GET /api/medidores/{medidor_id}/cambios` con usuarios de otro cliente y de otro
  prestador) y `test_permisos_roles` acusó el catálogo de alertas de 62 a 64.
- **137 vitest** (6 nuevos en `medidores.test.tsx`), `tsc --noEmit` y `npm run build` en verde.
- Pruebas de otros prompts que cambiaron porque F2-04 cambia lo que afirmaban: los cuatro triggers ya no responden
  403 `TRIGGER_FASE_2` (ahora se validan sus parámetros), `MEDIDOR_PROXIMO_PM` salió de la lista de alertas de Fase 2
  (solo queda `TECNICO_DESVIO_RUTA`), el método «unidades de producción» dejó de avisar `REQUIERE_MEDIDORES_FASE_2`
  y calcula, el importador pasó de 11 a 12 catálogos, el catálogo de alertas creció de 62 a 64 claves, el seed
  agregó una familia global («Equipos industriales») y seis equipos en la primera UN, y el editor de planes dejó de
  tener triggers deshabilitados.
- **Tres cambios de comportamiento de P06** que salieron de este bloque, los tres documentados arriba: la
  generación nocturna ahora respeta el candado «no hay folio abierto de este plan en este equipo», pinta el origen
  real del folio (`medidor` / `evento`) y recalcula la próxima fecha con la proyección del uso cuando el plan tiene
  triggers por medidor.

## Verificación al cierre de F2-03

- Migración `0015_operaciones_tiempo_real.py` aplicada (subida, bajada y subida), con `jornadas_tecnico`,
  `jornada_pausas`, `tecnico_posiciones` (**particionada por día**), `alertas_operacion_seguimiento` y las columnas
  de posición y estatus en `tecnicos`; RLS forzada en las cuatro tablas nuevas.
- **531 pytest** en verde **con los servidores de desarrollo apagados**, más 1 saltado a propósito.
  39 pruebas nuevas de F2-03 en `test_operacion_posiciones.py`, `test_operacion_estatus.py`,
  `test_alertas_operacion.py` y `test_operacion_tablero.py`.
- **131 vitest** (8 nuevos en `operaciones.test.tsx`), `tsc --noEmit` y
  `npm run build` en verde.
- **Prueba de carga de posiciones** (ACT-1.6 con el perfil de §6.8.4): 71 usuarios durante 90 s con 3 workers: **222 posiciones por minuto sin una sola falla** (el doble del requisito de §6.8.4), con mediana de 960 ms. El detalle y lo que se puede y no se puede afirmar de los percentiles están en [`docs/rendimiento/resultados.md`](docs/rendimiento/resultados.md).
- Las dos pantallas nuevas se recorrieron además en la app real con la base de desarrollo (Admin prestador,
  Despachador y técnico): seis correcciones salieron de ahí, entre ellas la columna `estatus_operativo_desde` (el
  «tiempo en el estatus» medía la jornada) y el «Sin configurar» de Mensajería, cuyo botón habría apagado los
  canales de un prestador ya configurado. El detalle está en `BITACORA.md`.
- Pruebas de otros prompts que cambiaron porque F2-03 cambia lo que afirmaban: `TECNICO_TIEMPO_MUERTO` y
  `TECNICO_SIN_SENAL` dejaron de ser alertas de Fase 2 (la de Fase 2 que queda como ejemplo es
  `TECNICO_DESVIO_RUTA`), el catálogo de alertas no cambió de tamaño pero sí de fase, y el aviso de la barra de
  indicadores de jornada ya no habla del mapa, que ahora existe.

## Verificación al cierre de F2-02

- Migración `0014_whatsapp_sms.py` aplicada (subida, bajada y subida), con las cuatro tablas nuevas
  (`mensajeria_plantillas`, `mensajeria_configuracion`, `mensajeria_envios`, `mensajeria_respuestas`) y la RLS
  forzada en todas, más las columnas de teléfono y consentimiento en `usuarios`.
- **531 pytest** en verde **con los servidores de desarrollo apagados**, más 1 saltado a propósito
  (`tests/test_respaldo.py`). 58 pruebas nuevas de F2-02 en `test_mensajeria_proveedores.py`,
  `test_mensajeria_notificar.py`, `test_mensajeria_minuta.py`, `test_mensajeria_consentimiento.py` y
  `test_mensajeria_webhooks.py`. Ninguna llama a Meta ni a Twilio: el proveedor simulado es el que responde, y las
  firmas de los webhooks se arman en la prueba con el mismo algoritmo del proveedor.
- **131 vitest** (7 nuevos en `mensajeria.test.tsx`), `tsc --noEmit` y `npm run build` en verde.
- `conftest` también desactiva el **horario de silencio** en la base de pruebas (`inicio == fin`), por la misma razón
  por la que abre los contratos: con el horario del demo (22:00–07:00) el resultado de las pruebas dependía de la
  hora a la que se corrieran. La regla del silencio tiene su propia prueba, que fija su ventana y la restaura.

## Verificación al cierre de F2-01

- Migración `0013_capacitacion_biblioteca.py` aplicada (subida, bajada y subida), con las siete tablas y la RLS
  forzada en todas.
- **434 pytest** en verde **con los servidores de desarrollo apagados**, más 1 saltado a propósito
  (`tests/test_respaldo.py`, que levanta y borra bases: se activa con `ACMA_PRUEBA_RESPALDO=1`). 41 pruebas nuevas
  de F2-01 repartidas en `test_capacitacion.py`,
  `test_certificacion_habilidades.py`, `test_biblioteca.py`, `test_contenido_servicio.py` y
  `test_biblioteca_offline.py`.
- **116 vitest** (7 nuevos en `capacitacion.test.tsx` y `biblioteca.test.tsx`, con `fake-indexeddb`),
  `tsc --noEmit` y `npm run build` en verde.
- Cinco pruebas de prompts anteriores cambiaron porque F2-01 cambia lo que afirmaban: el catálogo de alertas pasó de
  59 a 60 claves, el importador de 9 a 11 catálogos, la clave `biblioteca` del paquete de sincronización dejó de
  venir vacía, el seed deja a un técnico con una certificación vencida (su habilidad ya no es vigente) y
  `CERTIFICACION_VENCIDA` salió de la lista de alertas de Fase 2.
- Las pantallas nuevas se recorrieron además en la app real con la base de desarrollo (Admin prestador, técnico y
  Admin empresa): seis fallas encontradas ahí y corregidas, incluida la del visor contra `frame-ancestors 'none'`
  (decisión 147) y el 500 del expediente de un técnico sin cursos.

## Verificación al cierre de P11a

- Migraciones `0011_endurecimiento.py` y `0012_indices_rendimiento.py` aplicadas (subida, bajada y subida).
- **394 pytest** en verde con los servidores de desarrollo apagados, más 1 saltado a propósito
  (`tests/test_respaldo.py`, que levanta y borra bases; se activa con `ACMA_PRUEBA_RESPALDO=1` y se corrió aparte).
- **109 vitest**, `tsc --noEmit` y `npm run build` en verde.
- Pruebas de carga con 71 usuarios (50 técnicos, 20 de oficina, 1 operador): de **17.7 % de errores y mediana de
  29 s** a **0.02–0.6 % y mediana de 1–2 s**. Resultados y cálculo del servidor en `docs/rendimiento/resultados.md`.
- Respaldo (21 s) y **restauración medida (47 s)** con cotejo de las nueve tablas críticas: 9/9 coincidieron y el
  esquema restaurado fue `0012`.
- **`docker-compose.prod.yml` probado completo en local** con `ACMA_DOMINIO=localhost`: los siete servicios en
  `healthy`, migraciones en un servicio de una sola ejecución, `seed_produccion.py`, login con MFA obligatorio,
  `/api/salud/detalle` con las cuatro dependencias en verde, PWA servida por Caddy con HTTPS y redirección desde
  HTTP, y logs en JSON. Cuatro fallas reales encontradas y corregidas en ese ensayo (ver decisiones 128 a 131).

## Verificación al cierre de P10

- Migración `0010_sla_alertas_bi.py` aplicada (subida, bajada y subida) y seeds `seed_sla.py` (en la cadena de `seed_dev`) y
  `seed_historico.py` (aparte, 1,200 folios en 12 meses) cargados.
- `pytest`: **365 pruebas en verde** (incluye `test_sla.py`, `test_penalizaciones.py`, `test_alertas_config.py`,
  `test_escalacion.py`, `test_bi.py` y `test_reportes.py`; cambiaron las de P01/P04/P07/P09 por la conciliación de claves
  de alerta, el catálogo de 59 y los 51 evaluadores).
- `vitest`: **104 pruebas en verde** (SLA por severidad con unidad y penalización, iguala del contrato, aprobación de la
  exclusión, umbral con validación de rango, alertas de Fase 2 no activables, escalaciones, panel de la campana, tablero
  del Admin empresa y del Supervisor de operadores, barra de jornada, tablero de Dirección y generación y programación de
  reportes). `tsc --noEmit` y `npm run build` en verde.
- Tiempos medidos con 1,000+ folios cerrados (ACT-8.4): reporte ejecutivo del cliente sobre 12 meses en **906 ms (PDF)** y
  **1,250 ms (Excel)**; el seed del histórico tarda ~1 min.
- Suite completa de `pytest` corrida con los servidores de desarrollo apagados (regla 7).

## Verificación al cierre de P09

- Migración `0009_inventario_costos_activos.py` aplicada (subida, bajada y subida) y seed `seed_inventario.py` cargado.
- `pytest`: **307 pruebas en verde** (incluye `test_inventario.py`, `test_ordenes_compra.py`, `test_caja_chica.py`,
  `test_folio_costos.py`, `test_presupuestos.py`, `test_erp_exportacion.py` y `test_activos_tco.py`; cambiaron las de P04/P07 por
  el catálogo de 55 alertas y los 41 evaluadores).
- `vitest`: **87 pruebas en verde** (traspaso almacén → vehículo, ciclo de la OC, aprobación del gasto en un toque y captura del
  técnico desde el folio, tablero de presupuestos con semáforo, ficha del equipo con TCO y decisión de reemplazo, sección
  financiera del folio y bandeja del ERP). `tsc --noEmit` y `npm run build` en verde.
- Suite completa de `pytest` corrida con los servidores de desarrollo apagados (regla 7 de P09): la máquina de 7 GB se queda sin
  memoria si coinciden Docker, pytest y Vite.

## Verificación al cierre de P08

- Migración `0008_trabajos_especiales_oc.py` aplicada (subida, bajada y subida) y seed `seed_trabajos_especiales.py` cargado.
- `pytest`: **277 pruebas en verde** (incluye `test_trabajos_especiales.py`, `test_te_urgencia.py` y `test_oc_activos.py`; las de
  P04/P07 que cambiaron: catálogo de 49 alertas, sección de trabajos especiales de la minuta con contenido real).
- `vitest`: **68 pruebas en verde** (bandeja del cliente con aceptar/rechazar, Kanban y programación del TE, conversión desde la
  cotización, registro de OC y decisión ante rechazo). `tsc --noEmit` y `npm run build` en verde.
- Sin revisión visual en el navegador esta vez: la máquina (7 GB) se quedó sin memoria con Docker, pytest y los servidores de
  desarrollo a la vez; las pantallas se cubren con las pruebas de vitest y los datos demo del seed.

## Verificación al cierre de P07

- `pytest`: **259 pruebas en verde** (226 anteriores + las de P07: preferencias/canales Fase 2/bandeja, correo stub con `.eml`
  y adjunto, correo por SMTP contra `aiosmtpd`, plantilla del prestador; configuración, generación UN y global con secciones y
  entrega, modo con validación y ventana vencida, las seis respuestas con su efecto, vencimiento y alerta, recordatorio por
  período, hallazgos desde formulario y chat; cotizaciones por rol con PDF, rechazo → presupuesto y envío externo, Kanban,
  historial inmutable, alertas por días, reporte JSON/Excel/PDF; presupuesto reactivar/descartar/revisar, alerta y monto
  potencial, períodos, derivación §6.8.7; interno transiciones/campos/justificación y alertas; reprogramación con 3 fechas
  vencidas y escalado, alertas y variantes A/B; clasificación con las cinco opciones, tardía, alertas y calificación). La
  suite completa supera los 15 minutos: `conftest.auth` vuelve a iniciar sesión a los 10 min.
- `vitest`: **62 pruebas en verde** (+ responder la minuta con las seis opciones y validación del despachador, Kanban que
  cambia estado, listado y reporte, clasificación con fecha tentativa, calificación, bandeja y preferencias).
- `tsc --noEmit` limpio; `npm run build` verde. Datos demo regenerados con `seed_minuta` sobre la base existente.

## Verificación al cierre de P06

- `pytest`: **226 pruebas en verde** (203 anteriores + 23: próxima fecha y validación de triggers, plan completo, 403 de
  Fase 2, asignación a equipos con recálculo, edición con versión y aislamiento; texto literal de desvío, carga/consulta/
  edición por rol, publicación con notificación, importador `calendario_preventivos`, generación desde calendario
  manual; generación nocturna idempotente, habilidades del plan + tareas y paquete del técnico, cancelación con
  autorización, reprogramación autorizada y rechazada, cierre con desvío y recálculo, las tres alertas; catálogo de
  razones, candidatos y restricciones con confirmación, sin habilidad con permiso, estados no reasignables y roles,
  reporte de causas). La prueba de reasignación de P04 usa ahora la reasignación forzada real.
- `vitest`: **54 pruebas en verde** (45 anteriores + 9: calendario con desvío y publicación, editor de planes con Fase 2
  deshabilitada, técnico con tareas y materiales, solicitud de reprogramación desde el folio, bandeja de
  autorizaciones; modal de reasignación con 409 y confirmación, razón sin habilidad, sin botón para el operador,
  reporte con porcentajes).
- `tsc --noEmit` limpio; `npm run build` verde. Datos demo regenerados con `seed_preventivos` sobre la base existente.

## Verificación al cierre de P05

- `pytest`: **203 pruebas en verde** (185 anteriores + 18: sincronización incremental con bajas, lote aplicadas/duplicadas/
  rechazadas, cierre offline con hora real y conflicto, respuesta y evidencia idempotentes, dos pasos con reintento,
  refacción/mensaje offline y aislamiento; tres chats y eventos, doble timestamp e idempotencia, permisos por canal, RLS
  de participantes, inmutabilidad y evidencia posterior, chat archivado, WebSocket con dos clientes y SSE; firma, secuencia
  atención→firma→encuesta→cierre, plazo de la encuesta, push).
- `vitest`: **45 pruebas en verde** (39 anteriores + 6: cola FIFO con reintentos y reanudación, atención parcial offline,
  mensaje encolado con doble timestamp, indicador de conectividad, captura sin red y envío al reconectar, inicio del
  operador sin acceso a otras UNs).
- `tsc --noEmit` limpio; `npm run build` verde.

## Verificación al cierre de P04

- `pytest`: **185 pruebas en verde** (131 anteriores + 54 de folios: 8 validaciones de captura, duplicados con y sin bloqueo,
  severidad automática y override, transiciones por rol y 409, cierre incompleto, inmutabilidad de cerrado/cancelado,
  historial y decisiones append-only incluso superadmin, alcance por rol, aislamiento, RLS en tablas nuevas, nivel de
  entrada por criterio, cadena, 4 razones de rechazo, auto-aprobación de críticos, 4 timeouts y restricción del Nivel 3).
- `vitest`: **39 pruebas en verde** (33 anteriores + 6: captura con confirmación de UN, tarjeta de duplicado con justificación,
  botones por rol/estado en el detalle, bandeja con rechazo en dos pasos, listado y Kanban).
- `tsc --noEmit` limpio; `npm run build` verde.

## Verificación al cierre de P03

- `pytest`: **131 pruebas en verde** (96 anteriores + 35 de formularios: permisos, versionado, resolver, 22 tipos, condiciones,
  cascada, cálculos en servidor, inmutabilidad, calidad de foto, EXIF/GPS, geofencing).
- `vitest`: **33 pruebas en verde** (27 anteriores + 6: constructor con los 22 tipos, editor de condiciones, guardar/publicar,
  renderizador bloquea envío, cascada familia → tipo de falla, motor espejo).
- `tsc --noEmit` limpio; `npm run build` verde.

## Verificación al cierre de P02

- `pytest`: **96 pruebas en verde** (76 de P01 + 20 de catálogos, matriz e importador).
- `vitest`: **27 pruebas en verde** (19 de P01 + 8 de catálogos: pestañas por rol, celda de matriz, importación).
- `tsc --noEmit` limpio; `npm run build` verde.
- Verificado a mano en el navegador: pestañas de catálogos, matriz editable, importación con vista previa.

## Verificación al cierre de P01

- `pytest`: **76 pruebas en verde** (auth/MFA/refresh/reúso, aislamiento RLS, audit append-only, matriz de permisos por rol).
- `vitest`: **19 pruebas en verde** (login, enrolamiento MFA, hub por rol, refresh single-flight).
- `tsc --noEmit` limpio; `npm run build` verde (service worker con precache del shell).
- Verificado a mano: API real con datos demo, worker + beat de Celery ejecutando `evaluar_alertas`, interfaz (login, hub,
  UNs, edición de contrato) sin errores de consola.

## Arquitectura vigente (lo que deben respetar los prompts siguientes)

### Base de datos y RLS
- Esquema definido en SQL explícito en `backend/alembic/versions/0001_cimientos.py`; los modelos ORM lo reflejan.
  Las migraciones nuevas se escriben igual (SQL explícito con `ex()`, que divide sentencias para asyncpg).
- Roles: `acma_owner` migra; `acma_api` es la app (sin BYPASSRLS ni propiedad de tablas); `acma_auth` (NOLOGIN, BYPASSRLS)
  es dueño **solo** de las funciones `auth_*` de arranque de sesión.
- Contexto RLS: `app.usuario_id`, `app.tenant_id`, `app.prestador_id`, `app.rol`. Se aplica con `set_config(…, true)` en el
  evento `after_begin` de la sesión (`core/rls.py`), así que **cada transacción** lleva contexto aunque haya commits intermedios.
  Para cambiarlo dentro de una sesión: `fijar_contexto(sesion, ContextoRLS(...))`.
- Funciones de política: `acma_es_plataforma()` (superadmin o `sistema`), `acma_tenant_visible(t)` (tenant propio o
  atendido por el prestador del contexto), `acma_prestador_visible(p)`. Sin contexto, todas devuelven falso (fail-closed).
- Toda tabla nueva con `tenant_id` o `prestador_id` debe llevar `ENABLE` + `FORCE ROW LEVEL SECURITY` y políticas;
  `tests/test_rls.py::test_toda_tabla_con_tenant_o_prestador_tiene_rls_forzada` lo verifica automáticamente.
- Tablas críticas: `id`, `created_at`, `updated_at` (índice) y `version_hash`, calculados por el trigger `acma_version()`.
  Agregar la tabla a la lista `TABLAS_VERSIONADAS` (o crear el trigger equivalente) en su migración.
- `audit_log` y `audit_accesos_api`: particionadas por mes, append-only (triggers BEFORE UPDATE/DELETE/TRUNCATE + sin
  privilegios UPDATE/DELETE para `acma_api`). Insertar siempre con `services.auditoria.registrar(...)` (sin RETURNING).
- Celery y scripts usan el contexto `CONTEXTO_SISTEMA` (rol `sistema`) de forma explícita.

### Backend
- Dependencias: `usuario_actual` (`ActorActual`), `requiere_rol(*roles)`, `requiere_dominio(...)`, y en servicios
  `validar_tenant` / `validar_prestador` (regla 2: validar multitenancy además de la RLS).
- Errores: lanzar `core.errors.ErrorAPI(estado, codigo, mensaje, detalles)`; todo error sale como `{codigo, mensaje, detalles}`.
- Auditoría de cambios críticos: `auditoria.registrar_actor(db, actor, "modulo.evento", request, antes=..., despues=...)`.
- Alertas: cada módulo registra su evaluador con `@workers.tareas.registrar_evaluador("CLAVE")` y dispara con
  `services.alertas_service.disparar(...)` (respeta umbral efectivo, estado activo y supresiones).
- Almacenamiento: `services.almacenamiento.obtener_almacenamiento()` (MinIO o memoria en pruebas).
- `DATABASE_READ_URL` opcional → `core.db.engine_lectura` (igual al principal si está vacía).
- **Sesiones dentro del worker**: cada tarea de Celery corre en su propio event loop (`asyncio.run`), así que
  `celeryd_init` llama a `core.db.reconstruir_sin_pool()` y en el worker las sesiones van sin pool. Lo que
  notifica desde background (`push_service.enviar_a_usuarios` y todo lo que use `nueva_sesion`) depende de eso;
  con pool compartido la segunda tarea de la corrida fallaba con «Event loop is closed». La API conserva su pool
  (P11a). Pendiente: la suite fija `DB_POOL_NULO=true`, así que no hay prueba automática del camino con pool.

### Catálogos maestros (P02)
- Migración `0002_catalogos.py` usa los helpers de `core/sql_migracion.py` (`ex`, `rls`, `versionar`, `politicas_tenant`,
  `politicas_prestador`). Una migración que inserte o actualice filas debe empezar con
  `SELECT set_config('app.rol','sistema',true)`: la RLS forzada aplica también al dueño del esquema.
- Tablas: `habilidades`, `tecnicos`, `tecnico_habilidades`, `tecnico_tenants_habilitados` (§6.10.8), `niveles_severidad`,
  `familias_equipo` y `tipos_equipo` (`tenant_id` NULL = global de plataforma), `equipos`, `tipos_falla`,
  `tipo_falla_severidad`, `importaciones_catalogo`. Nuevos: `contratos.cobertura` y `contrato_sla.nivel_severidad_id`.
- **Contrato activo de un equipo**: función SQL `acma_equipo_con_contrato_activo(equipo_id)` (respeta la RLS del llamador) y
  `services.catalogos_service.equipo_con_contrato_activo`. `GET /api/catalogos/equipos?con_contrato=true` la aplica; P04 la
  usa en el selector filtrado y en la validación de captura.
- **Severidad automática**: `catalogos_service.resolver_severidad(db, tenant, tipo_falla, tipo_equipo)` y
  `GET /api/catalogos/matriz-severidad/resolver` (404 `SEVERIDAD_NO_CONFIGURADA` → el folio va a En revisión en P04).
  Devuelve también `requiere_revision_manual` del tipo de falla.
- **Permisos efectivos del técnico**: `permisos_service.efectivos_de_tecnico` (override > grupo > prestador > catálogo);
  `GET /api/catalogos/tecnicos/{id}/permisos-efectivos`.
- **Importador** (`services/importador_service.py`): registro `CATALOGOS` con columnas, validación por fila y aplicación;
  flujo `POST /api/catalogos/importar/{catalogo}` → `…/{id}/confirmar | cancelar`; plantillas en `…/{catalogo}/plantilla`.
  Para agregar un catálogo: entrada en `CATALOGOS` y ramas en `Contexto.cargar`, `_validar_fila` y `aplicar`.
- **Evaluadores de alertas** viven en `workers/evaluadores.py` (importado por `workers/tareas.py`). Un evaluador no debe
  repetir una alerta mientras exista una `disparada` sin atender para la misma entidad (patrón de `matriz_incompleta`).
- Frontend: `src/components/Buscador.tsx` (`Buscador` con retardo y `SelectorBusqueda` tipo combobox para P04),
  `pages/catalogos/Catalogos.tsx` con `useAmbito()` (tenant/prestador del usuario o los que elige el superadmin) y una
  pestaña por catálogo en `pages/catalogos/pestanas/`.

### Motor de formularios (P03)
- **Contrato del esquema**: `backend/schemas/formularios.py` ↔ `frontend/src/types/formularios.ts`; documentación completa de
  los 22 tipos en `docs/formularios/tipos_de_campo.md`. `secciones[] → campos[]` con `clave`, `tipo`, `config` validada por
  tipo, `condiciones[]` y `fuente_opciones` (fija o catálogo con `campo_padre` para cascada).
- **Motor de reglas** idéntico en `backend/services/formularios/validacion.py` y
  `frontend/src/services/formularios/validacion.ts` (`visibilidad`, `validar`, cálculos). Cualquier regla nueva se cambia
  en ambos y se prueba en `test_formularios_validacion.py` y `tests/formularios.test.tsx`.
- **Tablas (0003)**: `formularios`, `formulario_versiones` (una publicada no se edita: editar crea `numero_version + 1`),
  `formulario_asignaciones` (`plan_mantenimiento_id` sin FK hasta P06), `formulario_permisos_mesa`,
  `catalogos_personalizados` + opciones, `formulario_respuestas` (inmutables al enviar, trigger), `formulario_evidencias`
  (inmutables con la respuesta, trigger), `calidad_foto_defaults`. Alerta nueva `GEOLOCALIZACION_FUERA_DE_UN`.
- **Para P04 (folios)**:
  - `GET /api/formularios/resolver?tipo=&tipo_folio=&tenant_id=&tipo_equipo_id=&familia_equipo_id=&plan_id=` → formulario
    publicado aplicable (específico de tenant > global; coincidencia más específica) con su `esquema_json`.
  - `POST /api/formularios/{id}/respuestas` con `origen` (`folio_captura` | `folio_atencion` | …), `referencia_id` (el
    folio) y `contexto` {`tenant_id`, `un_id`, `equipo_id`, `sistema` {captura_folio, asignacion, autorizacion,
    fecha_programada: ISO}}; `PUT …/respuestas/{id}` parcial; `POST …/enviar` valida en servidor (422
    `RESPUESTA_INVALIDA` con `detalles`), recalcula concatenaciones/matemáticas/sellos y aplica geofencing.
  - `GET /api/formularios/respuestas?origen=&referencia_id=` para listar las respuestas de un folio.
  - `GET /api/formularios/opciones?catalogo=…&padre=…&un_id=…` resuelve los catálogos del sistema para el renderizador;
    `tipos_falla` devuelve `extra.requiere_revision_manual`.
  - Frontend: `<Renderizador esquema respuestas onChange contexto respuestaId evidencias onEvidencias />` y la página
    `pages/formularios/Llenar.tsx` (ruta `/formularios/llenar/:id?origen=&referencia=&un_id=&equipo_id=&tenant_id=`).
- **Para P05 (offline)**: toda escritura pasa por `frontend/src/services/formularios/respuestas.ts`
  (`crearRespuesta`, `guardarRespuesta`, `enviarRespuesta`, `subirEvidencia`, `eliminarEvidencia`); la cola sustituye el
  transporte con `usarTransporte(...)`. `lista_desplegable.config.disponible_offline` marca los catálogos a descargar.
- **Evidencias**: `services/formularios/evidencias.py` (Pillow: dimensiones, EXIF, GPS, calidad JPEG estimada por tabla
  de cuantización). Las anotaciones van en `anotaciones_json` y la imagen compuesta en `archivo_anotado_key`.
- **Transcripción de audio**: `services/transcripcion.py` con `TranscriptorStub` (Fase 2 sustituye la implementación).
- **Seed**: 4 plantillas base (cubren los 22 tipos), catálogo «Causa raíz», «Captura de folio (operador)» y
  «Cierre de correctivo (global)» publicados y asignados a Refrigeración, y «Cierre de correctivo · Cliente Demo»
  específico del tenant (gana en `resolver`).

### Folios (P04)
- **Tablas (0004)**: `folios` (número correlativo `PREFIJO-000001` por tenant vía `acma_siguiente_numero_folio()`, 11 estados,
  severidad + origen, confirmación de UN con timestamp/geo, duplicado con justificación y referencia, monto estimado,
  fechas de atención/cierre, cancelación), `folio_estados_historial` (**append-only**, con `evento`: `transicion`,
  `comentario`, `aprobacion.*`, `revision.resuelta`, `severidad.override`, `atencion.vinculada`, `confirmacion_un`,
  `folio.derivado_a_modulo`), `folio_formulario_captura`, `folio_formulario_atencion`, `folio_evidencias`,
  `folio_refacciones` (`articulo_id` sin FK hasta P09), `folio_sla` (prometido al autorizar; real y pausas en P10),
  `folio_encuesta`, `revision_manual_triggers` (con `resuelto`), `folio_keywords_alerta`, `folio_politicas_tenant`
  (bloqueo de duplicados, revisión por garantía, auto-autorización de críticos, `aprobacion_secuencial`, prefijo y
  contador) y las 5 de aprobación: `aprobacion_reglas`, `aprobacion_flujos`, `aprobacion_niveles_config` (CHECK Nivel 3),
  `aprobacion_decisiones` (**append-only, también para superadmin**), `aprobacion_alertas_timeout`. Además
  `contratos.horario_servicio_json`, `equipos.criticidad` (A/B/C/D) y `familias_equipo.habilidad_clave`. Alertas nuevas:
  `APROBACION_PENDIENTE_VENCIDA`, `APROBACION_BLOQUEADA`, `FOLIO_EN_REVISION_SIN_ATENDER` (evaluador en Celery).
- **Trigger `acma_folio_inmutable()`**: un folio `cerrado` o `cancelado` rechaza cualquier UPDATE (salvo
  `updated_at`/`version_hash`); `DELETE` prohibido siempre. Solo se admiten comentarios en el historial.
- **Motor de estados** `services/folio_estados.py`: tabla `TRANSICIONES` literal de §6.8.6 (origen → destino → roles,
  con el actor `sistema`); `transicionar(db, folio, nuevo_estado, actor, notas, contexto, request)` es la **única** forma de
  cambiar `folios.estado` (409 `TRANSICION_NO_PERMITIDA` con `roles_permitidos` y `destinos_posibles`; 409
  `CIERRE_INCOMPLETO` si faltan formulario de atención o firma; fija `fecha_inicio_atencion` y `fecha_cierre`; escribe
  historial + auditoría `folio.transicion.<estado>`). `ACTOR_SISTEMA` para transiciones automáticas; `comentar()` para
  eventos sin cambio de estado; `suscribir(fn)` registra consumidores en proceso (P05 chat/offline, P06 rutas y
  reasignación, P07 seguimiento, P10 SLA) con firma `async fn(db, folio, anterior, nuevo, actor, contexto)`.

  | Origen | Destinos → roles |
  |---|---|
  | capturado | en_revision → sistema · autorizado → sistema · cancelado → despachador, admin_prestador, admin_empresa, sistema |
  | en_revision | autorizado → despachador, admin_prestador, sistema · pendiente_informacion → despachador, admin_prestador · cancelado → despachador, admin_prestador, admin_empresa, sistema |
  | pendiente_informacion | en_revision → operador, admin_un, supervisor_operadores, admin_empresa, mesa_control · cancelado → despachador, admin_prestador, admin_empresa |
  | autorizado | asignado → despachador, sistema · cancelado → despachador, admin_prestador, admin_empresa |
  | asignado | en_camino → sistema, tecnico · reasignado → despachador, sistema · cancelado → (los tres) |
  | reasignado | asignado → sistema, despachador |
  | en_camino | en_ejecucion → sistema, tecnico · cancelado → (los tres) |
  | en_ejecucion | cerrado → tecnico, sistema · pendiente_refaccion → tecnico |
  | pendiente_refaccion | en_ejecucion → admin_prestador, despachador · reasignado → despachador, admin_prestador · cancelado → (los tres) |
  | cerrado / cancelado | — (finales; superadmin puede ejecutar cualquier transición existente en la tabla) |

- **Captura** `services/folios_captura_service.py` (`POST /api/folios`): roles que capturan siempre (operador, admin UN,
  admin empresa, supervisor de operadores, mesa de control); técnico con `crear_folio_en_campo` y despachador con
  `crear_folios` del cliente. Orden literal de validaciones: 1 confirmación de UN (si falta, queda `capturado` con
  trigger `confirmacion_un_faltante` y notificación; se completa con `POST /{id}/confirmar-un`) · 2 contrato activo
  (`sin_contrato`) · 3 duplicado abierto (409 `FOLIO_DUPLICADO_BLOQUEADO` con auditoría, o 422 `JUSTIFICACION_REQUERIDA`
  hasta enviar `folio_duplicado_justificacion`) · 4 severidad por matriz (`severidad_no_configurada` + alerta
  `MATRIZ_SEVERIDAD_INCOMPLETA`) · 5 garantía con `revision_obligatoria_garantia` (`garantia`) · 6 flag del tipo de
  falla (`tipo_falla_flag`) · 7 horario del contrato en la zona horaria de la UN (`fuera_horario`) · 8 palabras clave
  (`keyword_alerta`). Varios triggers se acumulan; con alguno el folio pasa a `en_revision` (sistema); si todas pasan,
  entra al punto de decisión D_MULTI. `respuesta_id` del formulario de captura es opcional (sin formulario resuelto se
  captura igual). Override de severidad: `PUT /{id}/severidad` (despachador/admin prestador, en revisión, razón).
- **Aprobación** `services/aprobacion_service.py`: `nivel_entrada(reglas, monto, criticidad, tipo_folio)` → la regla más
  restrictiva gana; reglas por `monto` (`<`, `<=`, `>`, `>=`, `entre`), `criticidad` (`en`) y `tipo_trabajo` (`igual`,
  `en`). Sin reglas aplicables → `autorizado` directo. Críticos A/B con `autorizacion_automatica_criticos` → `autorizado`
  con decisión `auto_aprobado` (canal `sistema`). El flujo vive dentro de `en_revision`: `aprobacion_flujos.nivel_actual`
  y `vence_at` en el detalle. Aprobadores: Nivel 1 `admin_un` (UN del folio en `usuario_un`), Nivel 2
  `supervisor_operadores` (UN directa o por grupo), Nivel 3 `admin_empresa`. `aprobar` en el último nivel → `autorizado`
  (y SLA prometido); nivel intermedio (solo con `aprobacion_secuencial` o tras escalado) → sube y notifica. `rechazar`
  exige `razon_rechazo` → `modulo_destino`, folio `cancelado` y evento `folio.derivado_a_modulo` en el historial con
  `{modulo_destino, razon_rechazo, decision_id, modulo_destino_id: null, procesado_por_p07: false}`.
- **Timeouts**: `aprobacion_alertas_timeout.vence_at` = momento real de programación + `tiempo_limite_horas`; Celery
  `acma.evaluar_timeouts_aprobacion` cada 60 s (`aprobacion_service.evaluar_timeouts`) aplica `escalar`,
  `bloquear_alertar` (flujo `bloqueado`, el aprobador aún decide), `autorizar_automatico` y `depende_criticidad`
  (A/B autoriza, C/D bloquea); el Nivel 3 solo admite las dos últimas (422 en API, CHECK en BD).
- **Endpoints** `/api/folios`: listado con alcance por rol y filtros; `verificar-duplicado`; `pendientes-aprobacion`;
  `politicas`; `keywords`; `aprobacion/configuracion|reglas|niveles`; `POST` captura; `GET /{id}` (archivo completo con
  secciones vacías `chat`, `reasignaciones`, `financiero`, más `acciones` válidas para el actor y `puede_aprobar`);
  `historial`; `transicion` genérica y atajos (`autorizar`, `pedir-informacion`, `responder-informacion`, `asignar`,
  `reasignar`, `en-camino`, `confirmar-llegada`, `pendiente-refaccion`, `reanudar`, `cerrar`, `cancelar`,
  `confirmar-un`, `comentario`); `monto-estimado`; `severidad`; `atencion` (vincula la respuesta enviada del técnico y
  registra sus evidencias; la firma cuenta para el cierre); `evidencias`; `refacciones`; `aprobacion/aprobar|rechazar`.
- **Eventos a consumir en prompts siguientes**: P05 — `POST /{id}/atencion`, `POST /{id}/evidencias` y las transiciones
  `en-camino`/`confirmar-llegada`/`cerrar` desde la app del técnico; `confirmar-un` desde la del operador; `capturarFolio`
  en `frontend/src/services/folios.ts` es la puerta a interceptar con la cola offline. P06 — `reasignado → asignado` con
  razón (hoy `reasignar` + `asignar`), asignación automática con `ACTOR_SISTEMA`, `orden_en_ruta`/`ventana_*`. P07 —
  historial `folio.derivado_a_modulo` (crear el registro del módulo y llenar `aprobacion_decisiones.modulo_destino_id`),
  canales `push`/`minuta` reales (`services/notificaciones.py` es un stub en log). P10 — `folio_sla` real y pausas a
  partir de `fecha_inicio_atencion`/`fecha_cierre` y del historial.
- **Frontend**: `types/folios.ts`, `services/folios.ts` (incluye `ACCIONES` destino → ruta y la tabla de transiciones
  cacheada), `pages/folios/{Folios,FolioDetalle,CapturaFolio,Aprobaciones}.tsx`, `services/notificaciones.ts` (stub).
- **Seed** (`scripts/seed_folios.py`): políticas (`CD-`), 6 reglas (A 5,000 / B 20,000, A/B → N2, preventivo → N1,
  especial → N2), 3 niveles (4 h escalar · 12 h depende_criticidad · 24 h bloquear), criticidad en los 12 equipos,
  4 palabras clave, horario L–V 08–20 / S 09–14 y 15 folios (CD-000001 cerrado … CD-000015 en ejecución).

### Campo, offline y chat (P05)
- **Tablas (0005)**: chat (`chats` UNIQUE(folio, canal), `chat_participantes`, `chat_mensajes` con `id_cliente` UNIQUE por chat,
  `timestamp_dispositivo`, `leido_por_json`, `datos_json`, `oculto`; `chat_archivos`; `chat_eventos_sistema`), sincronización
  (`sincronizacion_dispositivos`, `sincronizacion_conflictos`, `sincronizacion_mutaciones` = bitácora idempotente por
  (usuario, id_cliente)), `suscripciones_push` y `folio_politicas_tenant.plazo_encuesta_horas` (48). Trigger
  `acma_chat_mensaje_inmutable()`: en folio cerrado solo cambia `leido_por_json`; sin DELETE. RLS de `chat_mensajes` y
  `chat_archivos`: lectura solo para participantes activos (y plataforma); **las políticas de escritura van por comando**
  (INSERT/UPDATE/DELETE), porque una `FOR ALL` también concede SELECT — misma corrección aplicada a `folios` (el técnico ya
  no lee folios ajenos ni por RLS). Inserciones de mensajes/eventos sin `RETURNING` (ids generados en el cliente) porque
  quien transiciona puede no ser participante.
- **Sincronización** (`services/sync_service.py`, `/api/sync`): `GET /catalogos?desde=&dispositivo_id=` → paquete por rol
  (operador/admin UN/supervisor/admin empresa/mesa: `unidades`, `equipos` con `con_contrato_activo`, `familias_equipo`,
  `tipos_equipo`, `tipos_falla`, `niveles_severidad`, `formularios` de captura + `formularios_ids`; técnico: `folios`
  abiertos asignados + `folios_ids`, `formularios` de atención/preventivo, `formulario_por_folio`, `refacciones` [] (P09),
  `biblioteca` [] (Fase 2)); todo con `activo` para bajas lógicas y `servidor_at` como siguiente `desde`.
  `POST /mutaciones` {dispositivo_id, version_app, plataforma, mutaciones[{id_cliente, tipo, timestamp_dispositivo,
  payload}]} → por operación `aplicada | duplicada | rechazada {codigo, mensaje}` con `entidad_id`; se aplican en orden
  dentro de savepoints (una rechazada no detiene), idempotentes por la bitácora, y los ids del payload pueden ser
  `id_cliente` de operaciones previas (`folio_id`, `respuesta_id`, `referencia_id`). Tipos: `crear_folio` (payload =
  `FolioEntrada`; `capturado_at` = hora del dispositivo), `transicion` {folio_id, estado, notas, contexto} (→
  `transicionar(..., momento=timestamp_dispositivo)`: `fecha_inicio_atencion`/`fecha_cierre` reales y
  `datos_contexto_json.timestamp_dispositivo`; `asignado` con `contexto.tecnico_id` usa `asignar`; `autorizado` en
  revisión usa `autorizar_manual`), `guardar_respuesta` {respuesta_id | crear{formulario_id, origen, referencia_id,
  contexto}, respuestas, version_hash?}, `enviar_respuesta` {respuesta_id, respuestas?} (→ `enviar(..., momento)`),
  `subir_evidencia` {respuesta_id, campo_clave, nombre, mime, hash_sha256, contenido_base64}, `agregar_refaccion`
  {folio_id, descripcion, cantidad, origen, costo_unitario, articulo_id} y `mensaje_chat` {chat_id, contenido_texto,
  tipo, contenido_base64?}. Reglas §6.2: catálogos server-wins (el paquete manda); capturas client-wins (se aplican y, si el
  servidor cambió después de la hora del dispositivo o el `version_hash` difiere, queda un `sincronizacion_conflictos`
  con `client_wins`); inventario merge con alerta = gancho `aplicar_movimiento_inventario()` que P09 implementa.
  Evidencias en dos pasos: `POST /evidencias/iniciar` (hash + id_cliente → pendiente | existente | duplicada) y
  `PUT /evidencias/{id_cliente}/archivo` (multipart reintentable; mismo hash no se duplica). `GET /conflictos`.
- **Chat** (`services/chat_service.py`, `services/ws_manager.py`, `routers/chat.py`): los tres chats se crean con el
  evento `folio.creado` (`folio_estados.suscribir_creacion`) con participantes fijos §6.8.1 (campo: quien capturó;
  operativo: Admin UN de la UN; interno: Admin prestador); el técnico entra a `campo` al asignarse y el despachador a
  `operativo`/`interno` al actuar. `PUEDE_AGREGAR` literal de la tabla. Eventos de sistema por transición (mensaje
  `tipo=sistema` + `chat_eventos_sistema`): capturado (campo), asignado/reasignado/en_camino/en_ejecucion/
  pendiente_refaccion (campo y operativo), autorizado (operativo e interno), cerrado y cancelado (los tres). Folio
  cerrado: solo `imagen` con `datos_json.evidencia_posterior=true` (§6.8.3c); cancelado antes de asignar: chats
  `archivado` y mensajes `oculto` (solo superadmin los lee). Endpoints `GET /api/folios/{id}/chats`,
  `GET/POST /api/chats/{id}/mensajes`, `POST …/mensajes/archivo`, `GET …/archivos/{id}`, `POST …/leido`,
  `POST/DELETE …/participantes`. Tiempo real: `WS /ws/chats/{chat_id}?token=` (eventos `conectado`, `mensaje`, `leido`,
  `pong`) y fallback `GET /api/chats/{id}/stream?token=` (SSE, latido cada 15 s); el envío siempre es HTTP POST.
  `ws_manager.gestor` reparte en el proceso y publica por Redis pub/sub (`TIEMPO_REAL_MODO=redis|local`).
- **Cierre en campo** (`services/folio_cierre_service.py`): `POST /api/folios/{id}/firma` (multipart; solo operador/Admin
  UN de la UN con el folio en ejecución; `FolioEvidencia` tipo firma + evento `firma` + push «responde la encuesta»),
  `GET …/encuesta/disponible` y `POST …/encuesta` {nps_score 0–10, comentario, respuestas, timestamp_dispositivo}
  (formulario tipo `encuesta` resuelto por P03 → respuesta `origen=encuesta` enviada; comentario obligatorio si
  nps ≤ 6; disponible tras la firma, antes o después del cierre dentro de `plazo_encuesta_horas`). Al cerrar sin
  encuesta queda el evento `encuesta.pendiente`. La firma también puede venir del campo `firma` del formulario de
  atención del técnico (P04 la mapea), que es la «entrega del dispositivo al operador».
- **Push** (`services/push_service.py`, `/api/push`): `GET /clave-publica`, `POST/DELETE /suscripcion`; envío con
  `pywebpush` si hay `VAPID_CLAVE_PUBLICA/PRIVADA` (`scripts/generar_vapid.py`), si no solo log; suscriptor de
  transiciones notifica al operador (todos los cambios) y al técnico (asignación, autorización, cancelación) en una
  sesión de sistema. `public/sw-push.js` muestra la notificación y abre `datos.url`.
- **Frontend offline**: `services/db.ts` v2 (`catalogos_cache`, `folios_cache`, `formularios_cache`,
  `respuestas_borrador`, `evidencias_pendientes`, `mutaciones_pendientes`, `chat_mensajes_cache`, `chat_pendientes`;
  `usarBaseLocal()` para pruebas), `services/syncEngine.ts` (`encolar`, `encolarEvidencia`, `procesar` serializado,
  reintentos 1/4/16/64/256 s y `atencion` al 5.º, `reintentar`, `descartar`, `refrescarCatalogos`, `catalogo`,
  `resolverId`, `conRespaldoOffline`, `simularSinConexion` para pruebas), `services/offline/transporteRespuestas.ts`
  (transporte híbrido instalado en `main.tsx` con `usarTransporte`), `services/campo.ts` (folios/transiciones/refacciones
  con respaldo, firma, encuesta, catálogos cacheados, `registrarPush`), `services/chat.ts` (`conectarTiempoReal` WS→SSE),
  `useConexion` + `IndicadorConectividad` (cabecera), página `/sincronizacion`. Service worker: precache del shell,
  `NetworkFirst` para `GET /api/*` (no `/stream`), `importScripts('sw-push.js')`. `AuthContext` descarga el paquete de
  catálogos y registra push al iniciar sesión de operador, técnico y Admin UN.
- **Pantallas**: `/campo` (`pages/campo/Campo.tsx` por rol) → operador/Admin UN: `InicioOperador` (folios de su UN,
  técnico, ETA «Fase 2»), `/campo/nuevo` (`CapturaFolio modoCampo`: táctil, guía por paso, catálogos cacheados,
  captura sin red), `/campo/folio/:id` (`DetalleOperador`: línea de tiempo, chat campo, firma/encuesta),
  `/campo/folio/:id/cierre` (`CierreOperador`: lienzo a pantalla completa + NPS); técnico: `MisFolios` (hoy/próximos,
  «Nuevo folio» si `crear_folio_en_campo`), `/campo/folio/:id` (`AtencionTecnico`: acciones por la tabla de P04,
  formulario de atención resuelto por P03 o desde caché, refacciones con costo si `ver_costo_refacciones`, chat).
  `components/chat/ChatFolio.tsx` integrado en `FolioDetalle` (todos los roles). `GET /api/configuracion/mis-permisos`
  da los permisos efectivos del técnico/despachador.
- **Para P06**: reasignación → `transicionar(reasignado)` emite el evento de chat `folio.reasignado` y `asignar` vuelve a
  agregar al técnico; rutas/ETA sustituyen el «Fase 2» de las tarjetas. **Para P07**: canales reales de notificación
  (hoy `notificaciones.py` log + push web); la minuta puede usar `chat_eventos_sistema`. **Para P09**:
  `sync_service.aplicar_movimiento_inventario()` (merge con alerta de stock negativo) y `refacciones` del paquete.
  **Para P10**: `fecha_inicio_atencion`/`fecha_cierre` ya traen la hora real del dispositivo.
- **Seed** (`scripts/seed_campo.py`): formulario «Encuesta de satisfacción (operador)» publicado y asignado, chats de los
  15 folios (creados por el gancho o rellenados), mensajes en CD-000015 (uno con retraso), CD-000001 (cerrado, inmutables)
  y CD-000014, y una suscripción push demo del operador.

### Preventivos y reasignaciones (P06)
- **Tablas (0006)**: `planes_mantenimiento` (prestador, tenant opcional = todos los clientes, tipo de equipo, versión,
  estado, `tiempo_ventana_dias`, formulario y severidad opcionales), `plan_triggers` (ENUM `tipo_trigger_plan`: Fase 1
  `tiempo_fijo` {cada_dias} | {cada, unidad} y `calendario` {mes, dia} | {fechas}; `medidor_umbral`, `medidor_intervalo`,
  `evento`, `combinado` existen en el ENUM pero responden **403 TRIGGER_FASE_2**), `plan_tareas` (orden, minutos,
  `habilidad_requerida_id`), `plan_materiales` (`articulo_id` sin FK hasta P09), `plan_ejecuciones` (dedupe por plan +
  equipo + fecha), `equipo_planes` (UNIQUE equipo-plan; `fecha_proxima_ejecucion`, `fecha_ultima_ejecucion`,
  `ultimo_valor_medidor` para Fase 2), **`preventivos_calendario`** (una sola tabla para §6.9.1 y §7.6: UN obligatoria,
  equipo/plan/técnico opcionales, `fecha_programada`, `fecha_programada_original`, `fecha_real`, `desvio_dias`, estado
  `programado|generado|ejecutado|reprogramado|cancelado`, `folio_id`, `origen manual|plan`, `reprogramado_desde_id`),
  `calendario_publicaciones` (UNIQUE prestador-tenant-mes), `autorizaciones_preventivo` (tipo reprogramación/cancelación,
  solicitante, autorizador, canal `canal_aprobacion`, `fecha_nueva`, estado), `razones_reasignacion` (UNIQUE
  prestador-descripción; 7 literales de §6.8.2 sembradas por la migración y por `POST /api/prestadores`),
  `reasignaciones` (origen, destino, tipo `forzada|automatica`, razón, comentario, despachador) y
  `reasignacion_validaciones` (`habilidad_ok`, `refaccion_ok` NULL hasta P09, advertencias). `folios.plan_id` y
  `folios.calendario_id`; FK real de `formulario_asignaciones.plan_mantenimiento_id`. Tres alertas nuevas:
  `PREVENTIVO_VENCIDO_SIN_EJECUTAR` (umbral días tras fecha + ventana), `AUTORIZACION_PREVENTIVO_PENDIENTE` (24 h) y
  `CALENDARIO_MES_SIN_PUBLICAR` (día 25). RLS: tablas del prestador con `politicas_prestador(lectura_tenants=True)`; las
  ligadas al folio con políticas por comando como en P05.
- **Planes** (`services/planes_service.py`, `/api/planes`): `validar_trigger`, `proxima_fecha_trigger(tipo, parametros,
  desde, hoy)` (tiempo fijo = última ejecución + intervalo, con recorte de fin de mes; calendario = siguiente fecha
  fija posterior a hoy), `crear/editar` (editar reemplaza triggers/tareas/materiales, sube `version` una vez y recalcula
  la próxima fecha de los equipos), `asignar_equipo(plan, equipo, fecha_base)` (valida tipo de equipo y cliente
  vinculado) y `desactivar_equipo`. Admin prestador y Despachador editan; Admin empresa/Admin UN consultan.
- **Calendario** (`services/preventivos_service.py`): `GET/POST /api/preventivos/calendario` (filas con `un_id`,
  `equipo_id?`, `plan_id?`, `tecnico_id?`, `fecha_programada`), `PATCH …/calendario/{id}` (la fecha solo sin folio:
  409 `REQUIERE_AUTORIZACION`), `POST …/calendario/publicar?mes=AAAA-MM&tenant_id` (409 `MES_VACIO`; emite
  `calendario.publicado` → `notificaciones.enviar` roles admin_empresa/admin_un canales push+email y push web; **P07
  conecta el correo**), `GET …/publicaciones`, catálogo importable **`calendario_preventivos`** (cliente por RFC o razón
  social, UN, fecha, equipo/plan/técnico opcionales; duplicado por tenant+UN+equipo+fecha). `texto_desvio(desvio)` es el
  literal de §7.6: «realizado en la fecha programada», «realizado N día(s) antes de lo programado», «realizado con N
  día(s) de retraso», «pendiente de ejecución»; se expone en cada fila y en `GET /api/preventivos/texto-desvio`.
- **Generación nocturna**: tarea Celery `acma.generar_preventivos_programados` (beat 02:00, `workers/tareas/preventivos.py`)
  = `generar_programados(db, hoy, horizonte_dias=7)`: equipos con `fecha_proxima_ejecucion ≤ hoy+horizonte` → fila de
  calendario `origen=plan` + `generar_folio_preventivo` (folio `tipo_folio=preventivo` capturado por el sistema con
  confirmación de UN, severidad del plan o la más baja del prestador, formulario del plan o resuelto por P03 con
  `plan_id`, historial `capturado → autorizado` por `sistema` sin flujo de aprobación) + `plan_ejecuciones` + próxima
  fecha recalculada; después las filas manuales con equipo dentro del horizonte. Idempotente; cada equipo en su savepoint.
  `POST /api/preventivos/generar?hoy=&horizonte_dias=` ejecuta lo mismo a demanda (pruebas y operación).
- **Ciclo**: asignación con `tecnico_con_habilidad` ampliado (habilidad de la familia **y** las de `plan_tareas`: mensaje
  «refrigeracion + plan: plomeria»); `GET /api/preventivos/{folio_id}/plan` da tareas y materiales al técnico y el
  paquete offline resuelve el formulario tipo `preventivo` por folio. Reprogramación y cancelación: `POST
  /api/preventivos/{folio_id}/solicitar-reprogramacion|solicitar-cancelacion` (Despachador/Mesa/Admin prestador; una
  pendiente por folio: 409 `SOLICITUD_PENDIENTE`; 409 `NO_ES_PREVENTIVO`, `FOLIO_FINAL`; 422 `FECHA_REQUERIDA`) →
  `autorizaciones_preventivo` + evento `preventivo.solicitud_*` en historial y chat operativo + notificación
  `autorizacion.solicitada` (push + email P07) a los Admin UN de la UN y Admin empresa; `GET /api/preventivos/autorizaciones`
  (bandeja con `puede_resolver`), `POST …/{id}/autorizar|rechazar` {notas, canal app|push|minuta}. Autorizada:
  reprogramación = nueva fila del calendario con `reprogramado_desde_id` (la original queda `reprogramado` y conserva la
  fecha original), `folio.calendario_id` y `fecha_falla` actualizados, evento `preventivo.reprogramado`; cancelación =
  `transicionar(cancelado)` ejecutada por el solicitante con `autorizacion_id` en el contexto. Validador
  `folio_estados.suscribir_validacion`: un preventivo **no** se cancela desde los roles del prestador sin
  `contexto.autorizacion_id` (409 `REQUIERE_AUTORIZACION`); Admin empresa sí puede directamente. Al cerrar
  (`_al_cerrar_preventivo`): `fecha_real`, `desvio_dias`, estado `ejecutado`, `plan_ejecuciones` y
  `equipo_planes.fecha_ultima/proxima`.
- **Reasignación forzada** (`services/reasignacion_service.py`): `GET /api/folios/{id}/reasignacion/candidatos` (técnicos
  activos del prestador con `habilidad_ok`, `habilidad_requerida`, `carga_dia`, `refaccion_ok` NULL, `es_actual`,
  advertencias), `POST /api/folios/{id}/reasignar` {tecnico_destino_id, razon_id, comentario, confirmar_advertencias,
  razon_sin_habilidad}: 409 `REASIGNACION_NO_PERMITIDA` en ejecución («el técnico ya está en la unidad»), en camino o
  estados no reasignables (válidos: asignado, pendiente_refaccion); 422 `MISMO_TECNICO`, `RAZON_INVALIDA`
  (catálogo del prestador, activa), `RAZON_REQUERIDA`; 403 `TECNICO_SIN_HABILIDAD` salvo Admin prestador o despachador
  con `asignar_tecnico_sin_habilidad` (y razón); 409 `CONFIRMACION_REQUERIDA` con la lista de advertencias (hoy siempre
  «Refacción no verificada» hasta P09) si no se confirma. Ejecuta `reasignado → asignado` (misma operación, historial
  de P04 con `sin_habilidad`/`razon`), guarda `reasignaciones` + `reasignacion_validaciones`, saca al técnico anterior
  del chat de campo y mete al nuevo, evento `folio.reasignado` en campo y operativo, push a ambos técnicos.
  `GET /api/folios/{id}/reasignaciones` (también en `GET /api/folios/{id}` → `reasignaciones`),
  `GET /api/reasignaciones/reporte?desde&hasta&tenant_id` (total y % por razón, técnico origen/destino y tipo),
  `GET/POST/PATCH /api/reasignaciones/razones`. La ruta transitoria `POST /api/folios/{id}/reasignar` de P04 (solo
  marcar `reasignado`) se sustituyó por esta.
- **Frontend**: `types/preventivos.ts`, `services/preventivos.ts`; módulos `preventivos` (`/preventivos/calendario`,
  `pages/preventivos/Calendario.tsx`: mes, cliente, estados, carga por filas, edición, publicar, «Generar folios ahora»,
  desvío literal por fila), `/preventivos/planes` (`Planes.tsx`: lista, editor con los 6 triggers del ENUM y los de Fase
  2 deshabilitados, tareas con habilidad, materiales, equipos con fecha base), `/preventivos/autorizaciones`
  (`Autorizaciones.tsx`), `reasignaciones` (`/reasignaciones/reporte`, `pages/reasignaciones/Reporte.tsx` con catálogo
  de razones). `FolioDetalle`: botón **Reasignar** (`pages/folios/Reasignar.tsx`: candidatos con insignias, razón del
  catálogo, advertencias con casilla de confirmación ante 409, razón sin habilidad) y `PanelPreventivo` (solicitar
  reprogramación/cancelación, autorizar/rechazar, histórico). App del técnico: insignia **Preventivo** + plan, lista de
  verificación de tareas (`PlanDelTecnico.tsx`, marcas en IndexedDB, operable sin red) y materiales «Usar como refacción».
- **Seed** (`scripts/seed_preventivos.py`): formulario «Inspección preventiva · Prestador Demo» asignado a `preventivo`,
  3 planes (trimestral de refrigeradores cada 3 meses, semestral de minisplits cada 180 días, anual de iluminación el
  15/01) con 9 tareas y 6 materiales, 6 equipo_planes, generación simulada del 05 y 20 de octubre, calendario con 8 filas
  (2 ejecutados con desvío +2/−3, 1 reprogramado + su nueva fecha, 1 cancelado, 3 programados de noviembre: uno de UN
  completa), noviembre publicado, 7 razones y 3 reasignaciones (una sin habilidad por el Admin prestador).
- **Para P07**: eventos `calendario.publicado` y `autorizacion.solicitada`/`*_autorizada` ya pasan por `notificaciones.enviar`
  con canal `email`; la minuta puede leer `preventivos_calendario` y `texto_desvio`. **Para P09**: `plan_materiales.articulo_id`,
  `reasignacion_validaciones.refaccion_ok` y la advertencia «Refacción no verificada» se resuelven con el inventario del
  vehículo. **Para P10**: `plan_ejecuciones.desvio_dias` y la alerta de preventivo vencido alimentan los KPIs.

### Minuta y seguimiento (P07)
- **Tablas (0007)**: `hallazgos` (folio opcional, UN, equipo, descripción, `nivel_urgencia`, `foto_evidencia_id`, tipo preventivo/
  correctivo, origen `formulario_atencion|chat|manual`, `respuesta_id`, `mensaje_id`, estado de respuesta, opción §7.4, módulo y
  registro destino), `peticiones_cliente`; minuta: `minuta_configuracion` (por prestador-tenant: modo, `hora_envio`, ventana 30
  min, plazo 24 h y los umbrales de los contadores), `minutas` (UNIQUE tenant-prestador-fecha-tipo-UN; estados `borrador →
  pendiente_validacion → enviada → respondida | vencida`, `enviada_sin_validacion`, `vence_respuesta_at`, `pdf_key`, `hash_pdf`,
  `urgente`), `minutas_secciones` (una fila por sección con `contenido_json`), `minutas_respuestas` (opción, canal
  app/email/push, módulo y registro o folio generado), `minutas_destinatarios`; notificaciones: `notificaciones` (por usuario y
  canal, estado `pendiente|enviada|fallida|omitida`, `leida_at`, `url`; sin RETURNING como el chat) y `notificacion_preferencias`
  (`canales_json` por evento, `*` = todos); módulos: `periodos_presupuestales`, `cotizaciones` (`numero` COT-00001 por prestador,
  `detalle_json.partidas`, `estado_desde`, `trabajo_especial_id` sin FK hasta P08, `pdf_key`/`hash_pdf`,
  `pasar_a_presupuesto_si_rechaza`), `cotizacion_envios_externos`, `hallazgos_presupuesto` (`ultima_revision`,
  `historial_revisiones_json`, `reactivado_como`), `seguimientos_internos` (proveedor, fecha acordada, referencia,
  `ultima_actualizacion`, `justificacion_cierre`), `reprogramaciones` (`fecha_tentativa`, `trabajo_coordinado` + `variante`,
  `tercero_completo`, `folio_coordinado_id`, `fechas_vencidas_count`, `escalada_empresa`), `modulo_historial` (**append-only**,
  trigger `acma_auditoria_inmutable`); clasificación: `clasificacion_configuracion` (severidades no críticas, plazo, umbral,
  `admin_empresa_puede_clasificar`, `puntos_json`), `folio_clasificaciones`, `admin_un_calificacion`. Además
  `trigger_revision` gana `pendiente_clasificacion`, `folio_sla` gana `autorizado_en` y `excluir_sla_por_cliente` (P10), y
  `aprobacion_decisiones` acepta **una sola** actualización NULL → id de `modulo_destino_id` (trigger `acma_decision_solo_modulo`).
  18 alertas evaluadas (14 nuevas + 5 del catálogo base: `COTIZACION_SIN_PREPARAR`, `COTIZACION_SIN_RESPUESTA`,
  `SEGUIMIENTO_SIN_UPDATE`, `REPROGRAMACION_FECHA_VENCIDA`, `FOLIO_SIN_CLASIFICAR`). RLS: tablas con tenant+prestador con las
  políticas por comando de P05/P06; `notificaciones` las lee/actualiza su dueño o el tenant/prestador del evento (la bandeja
  filtra por usuario en el servicio); `notificacion_preferencias` las lee quien notifica (tenant o prestador vinculados).
- **Notificaciones** (`services/notificaciones_service.py`): `notificar(db, evento, destinatarios, datos, asunto=, cuerpo=, url=,
  tenant_id=, prestador_id=, canales=, adjuntos=, plantilla=)` resuelve canales por preferencia del usuario (`canales_de`:
  preferencia del evento → preferencia `*` → `CANALES_POR_EVENTO` → `app, push, email`), inserta una fila por canal y envía:
  `app` inmediata (bandeja), `push` (web-push de P05) y `email` (`services/correo.py`) desde `procesar()`, en línea si
  `NOTIFICACIONES_ENVIO_INLINE=true` (pruebas, sin Celery) o en la tarea `acma.enviar_notificaciones` (+ barrido
  `acma.enviar_notificaciones_pendientes` cada 2 min). `whatsapp` y `sms` quedan `omitida` «canal Fase 2». La bitácora
  `notificaciones.ENVIADAS` de P04–P06 se conserva; los stubs de aprobaciones (`aprobacion.pendiente`, `aprobacion.bloqueada`),
  captura (`folio.espera`, `folio.revision`) y preventivos (`calendario.publicado`, `autorizacion.solicitada`) ya pasan por
  `notificar()`. `destinatarios_por_rol(db, roles, tenant_id=, prestador_id=, un_id=)` (Admin UN solo los de la UN). Catálogo de
  eventos `EVENTOS`; API `/api/notificaciones` (bandeja, `no-leidas`, `leidas`, `eventos`, `preferencias`, `procesar`).
  Correo: SMTP genérico con `aiosmtplib` (`SMTP_HOST/PORT/USER/PASSWORD/FROM/TLS`); sin `SMTP_HOST` modo **stub** que guarda
  el `.eml` en el almacenamiento (`correo/AAAA/MM/DD/<id>.eml`) y registra en `correo.ENVIADOS`. Plantillas en
  `backend/plantillas/correo/` (`base.html` con logo/colores del prestador, `generico`, `minuta`, `cotizacion`), rellenadas con
  `correo.plantilla()` (escapa todo salvo claves `*_html`). PDF: `services/pdf.py` usa WeasyPrint cuando carga; si faltan sus
  librerías nativas (GTK/Pango en Windows) usa un generador PDF mínimo propio; `sha256()` = `hash_pdf`.
- **Hallazgos y peticiones** (`services/hallazgos_service.py`): el esquema de formularios (P03) admite `genera_hallazgo` por campo
  (`HallazgoMapeo`: `campo_descripcion`, `campo_urgencia` texto o slider 1–10, `urgencia_fija`, `campo_foto`, `condicion_campo` /
  `condicion_valor`); al enviar una respuesta `folio_atencion` `desde_respuesta()` crea los hallazgos. Un mensaje de chat con
  texto se marca con `POST /api/chats/{chat}/mensajes/{id}/marcar` {como: hallazgo|peticion} (técnico, operador, Admin UN,
  Despachador; `datos_json.marcado_como` evita duplicar). Captura manual `POST /api/hallazgos`. `GET /api/hallazgos`,
  `GET /api/peticiones`.
- **Minuta** (`services/minuta_service.py`): `generar(db, prestador, tenant, fecha)` → una minuta por UN con actividad
  (`unidades_con_actividad`: eventos de folio, hallazgos, peticiones o preventivos ejecutados ese día en la zona horaria del
  tenant) y una global; idempotente por la UNIQUE. **`minutas_secciones`** (`seccion`, `orden`, `contenido_json`):
  `contadores` {cotizaciones{total, pendientes_enviar, pendientes_autorizar, color, umbral}, por_presupuesto, seguimiento_interno,
  reprogramacion} con los colores/umbrales literales de §7.3 (rojo/amarillo según `minuta_configuracion`), `preventivos`
  {items: [{un, equipo, tecnico, hora, fecha_programada, fecha_real, desvio_dias, texto_desvio}]} con `texto_desvio()` de P06,
  `hallazgos` {items: [{hallazgo_id, descripcion, equipo, urgencia, foto_url, estado_respuesta, opcion_respuesta,
  pendiente_de_dias_anteriores}]}, `cotizaciones` {pendientes_enviar, pendientes_autorizar}, `trabajos_especiales` {nota P08},
  `peticiones` {items}, `pendientes_autorizacion` {items} (§6.8.7 canal minuta) y, solo en la global de la primera minuta del mes o
  del inicio del período presupuestal, `recordatorio_presupuesto` {items}. Modo `automatica` → `enviar()` al generar; modo
  `con_validacion` → `pendiente_validacion` + aviso al despachador; `validar(actor, notas)` o `vencer_validaciones()` (tras
  `ventana_validacion_min`, marca `enviada_sin_validacion`). `enviar()`: PDF + `hash_pdf`, `notificar("minuta.enviada", …,
  canales=[app, push, email], plantilla="minuta", adjuntos=[PDF])` a los Admin UN de la UN (minuta UN) o al Admin empresa
  (global), `minutas_destinatarios`, `vence_respuesta_at` solo si hay hallazgos pendientes. `responder(actor, minuta,
  hallazgo, opcion, canal, fecha_tentativa, proveedor, trabajo_coordinado, variante)` ejecuta el efecto literal de §7.4 vía
  `seguimiento.entradas.desde_hallazgo` y refleja la respuesta en las secciones de la minuta UN y global del día; al responder
  todos → `respondida`. `vencer_respuestas()` → `vencida` + `MINUTA_SIN_RESPUESTA`. Tarea `acma.generar_minutas` (cada 10 min:
  genera a la `hora_envio` local de cada tenant, vence ventanas y plazos) y `POST /api/minutas/generar|procesar-pendientes`.
  Endpoints `/api/minutas` (config GET/PUT, lista, detalle con secciones/hallazgos/respuestas/destinatarios, `pdf`, `validar`,
  `hallazgos/{id}/responder`).
- **Módulos de seguimiento** (`services/seguimiento/`): `base.py` (alcance por rol, `historial()` append-only, `exigir_rol`,
  `exigir_justificacion`, `dias_en_estado`, `alertas_activas`, `transicionar` con `estado_desde`), y un módulo por tabla con
  `TRANSICIONES` literal de §7.7 y **`cambiar_estado(db, actor, registro, nuevo, notas, request, **campos)`**: valida destino y
  rol, exige campos (`con_proveedor`/`fecha_asignada`/`tercero_confirmado`: proveedor + fecha, referencia opcional) y
  justificación escrita (`resuelto`, `cancelado`, `descartado`), escribe `modulo_historial`, audita y notifica (bandeja).
  Cotizaciones: `crear` (COT-n, aviso simultáneo a Mesa, Despachador y Admin prestador), `preparar`, `enviar_cliente` (PDF +
  correo con adjunto a Admin UN/empresa), `responder` (autorizar/rechazar; rechazo con `pasar_a_presupuesto_si_rechaza` →
  diferido), `enviar_externo` (PDF por correo a terceros, registrado, sin cambiar estado), `convertir_en_trabajo_especial` →
  **501 `DISPONIBLE_EN_P08`**. Presupuesto: `revisar`, `reactivar(como=folio|cotizacion)`, `descartar(razón)`, `monto_potencial`,
  `periodo_actual()` / `inicio_de_periodo()` (mensual, trimestral, semestral, anual o fechas). Interno: `actualizar` (novedad).
  Reprogramación: `registrar_fecha_vencida()` (contador acumulado entre `fecha_asignada` y `tercero_confirmado`; al llegar a 3
  `escalada_empresa` + `REPROGRAMACION_ESCALADA_EMPRESA` + aviso al Admin empresa), `confirmar_tercero()` (variante A → crea el
  folio correctivo del técnico con `entradas.folio_directo`). `entradas.py`: `desde_hallazgo` (§7.4), `desde_clasificacion`
  (§6.10.5), `desde_derivacion` (§6.8.7: el rechazo del flujo crea el registro y llena `aprobacion_decisiones.modulo_destino_id`;
  `procesar_derivaciones_pendientes()` migró los folios demo) y `folio_directo` (correctivo del sistema directo a Autorizado, sin
  flujo multinivel). API `/api/seguimiento/{cotizaciones|presupuesto|interno|reprogramacion}` (listado con filtros tenant/UN/
  período/estado/urgencia, alta directa, detalle con historial, `estado` para el Kanban), acciones propias
  (`preparar`, `enviar`, `responder`, `convertir`, `pdf`, `enviar-externo`, `reactivar`, `descartar`, `revisar`,
  `monto-potencial`, `actualizar`, `confirmar-tercero`), `por-un/{un_id}`, `periodos-presupuestales`, `reporte/ejecutivo`
  (JSON, `.xlsx`, `.pdf`: tiempo promedio por módulo, tasa de conversión, hallazgos recurrentes por tipo de equipo, monto
  potencial).
- **Clasificación** (`services/clasificacion_service.py`): en la captura (P04), si el tenant tiene `clasificacion_configuracion`
  activa y la severidad es no crítica, el folio queda `en_revision` con el trigger `pendiente_clasificacion` (sin flujo) y se
  avisa al Admin UN; `pendientes()` (sus UNs; Admin empresa si está habilitado) con plazo restante; `clasificar(opcion,
  fecha_tentativa, notas)`: `autorizado` → `transicionar(autorizado)` + `folio_sla.autorizado_en`; las otras cuatro crean el
  registro del módulo y cancelan el folio con razón (queda enlazado por `derivaciones`). Tardía → `dentro_de_plazo=False`,
  `horas_retraso`, `excluir_sla_por_cliente`. `calificar(tenant, periodo)` por Admin UN: base − retraso proporcional (tope) −
  pendientes vencidos − minutas sin respuesta/tardías → `admin_un_calificacion` con `eventos_json`; bajo el umbral dispara
  `ADMIN_UN_BAJO_DESEMPENO` y avisa al Admin empresa. Tarea `acma.calificar_admin_un` (06:30: calificación del período y
  recordatorios de inicio de período presupuestal). API `/api/clasificacion` (config, pendientes, `{folio_id}`,
  calificaciones, `calificaciones/calcular`).
- **Frontend**: `types/minutas.ts`, `services/minutas.ts`; módulos con ruta `minuta` (`/minutas`, `pages/minutas/Minutas.tsx`
  con bandeja de validación y configuración por cliente; `/minutas/:id` `ResponderMinuta.tsx`: dos bloques, PDF, validación y
  respuesta por hallazgo con las seis opciones y captura de fecha/tercero/variante), `seguimiento` (`/seguimiento`,
  `pages/seguimiento/Seguimiento.tsx`: cuatro pestañas, listado con días en estado y próxima alerta, columna «Estado del trabajo
  especial» vacía hasta P08, Kanban con arrastre/«Mover a…» para Admin prestador y Despachador, vista por UN, reporte
  ejecutivo con exportación, detalle con acciones por rol), `clasificacion` (`/clasificacion`, pantalla §6.10.5 + calificación +
  configuración), `notificaciones` (`/notificaciones`, bandeja y preferencias; campana `CampanaNotificaciones` en la cabecera).
  `FolioDetalle` muestra hallazgos, derivaciones y clasificación; `ChatFolio` permite marcar un mensaje como hallazgo o petición.
- **Seed** (`scripts/seed_minuta.py`): configuración de minuta, período trimestral, severidades no críticas, 6 hallazgos en 6
  folios, 2 peticiones, minutas de los últimos 3 días (UN respondida y vencida, hoy pendiente de validación), 3 cotizaciones
  (enviada con PDF, autorizada con envío externo, solicitada), 2 diferidos (uno migrado del rechazo de P04), 2 seguimientos
  internos (uno con proveedor), 2 reprogramaciones (una coordinada A con 2 fechas vencidas), 4 folios no críticos pendientes
  de clasificar y la calificación del período.
- **Para P08**: `cotizaciones.convertir_en_trabajo_especial()` (501) y la columna `trabajo_especial_id`; la sección
  `trabajos_especiales` de la minuta recibe nuevos/en proceso/terminados; la columna «Estado del trabajo especial» del listado.
  **Para P09**: `periodos_presupuestales` rige el recordatorio y debe ligarse al presupuesto; `hallazgos_presupuesto.monto_estimado`
  y `monto_potencial`. **Para P10**: `folio_sla.autorizado_en` (inicio del SLA) y `excluir_sla_por_cliente`; `modulo_historial`
  y `admin_un_calificacion` alimentan KPIs. **Fase 2**: canales `whatsapp`/`sms` (hoy `omitida`).

### Trabajos especiales y OC de activos (P08)
- **Tablas (0008)**: `trabajos_especiales` (`numero` TE-000001 por prestador, tenant/prestador/UN, `equipo_id`, `cotizacion_id`,
  `hallazgo_id`, `descripcion`, `detalle_json`, 8 estados, `estado_desde`, `urgencia`, `creado_por_id/rol`, `formulario_id`,
  `respuesta_formulario_id`, `monto`, `cotizacion_retroactiva_id`, `fecha_programada/inicio/cierre`, `tecnico_ids_json`,
  `tecnico_responsable_id`, `folio_id` (folio operativo), `razon_cancelacion`, `version_enviada`, `enviado_at/aceptado_at/programado_at`),
  `te_respuesta_cliente` (**append-only**: decisión por versión enviada, comentario, canal), `te_evidencias` (avance/cierre/firma/documento,
  `evidencia_id` del formulario o `archivo_key` propio), `te_historial` (**append-only**, tabla propia del TE), `folio_activo_autorizacion`
  (uno por folio: 5 estatus §6.10.7, `numero_oc_provisional/definitivo`, `fecha_autorizacion_erp`, `decision_rechazo`,
  `periodo_presupuestal_destino`, `origen` captura/atencion, `datos_equipo_json` mapeado del formulario, `hallazgo_presupuesto_id`) y
  `folio_activo_historial` (**append-only**). Además `cotizaciones.trabajo_especial_id` ya es FK, `folios.es_instalacion_activo`,
  `folios.equipo_instalado_id` (FK `equipos`) y `folios.trabajo_especial_id`, y `trigger_revision` gana `pendiente_oc_cliente`. 7 alertas
  nuevas (`TE_SIN_RESPUESTA_CLIENTE`, `TE_ACEPTADO_SIN_PROGRAMAR`, `TE_PROGRAMADO_VENCIDO`, `TE_URGENCIA_SIN_COTIZACION_RETROACTIVA`,
  `OC_ACTIVO_SIN_TRAMITE`, `OC_ACTIVO_EN_TRAMITE_PROLONGADO`, `ACTIVO_INSTALADO_INCOMPLETO`) con evaluadores en
  `workers/evaluadores_te.py` (32 evaluadores en total). RLS por tenant+prestador con políticas por comando (solo SELECT/INSERT en las append-only).
- **`services/trabajos_especiales_service.py`**: `TRANSICIONES` literal de §6.10.6 (creado → enviado_cliente [prestador] · creado →
  programado solo urgencia · enviado_cliente → aceptado | rechazado [Admin empresa / Admin UN de la UN, comentario obligatorio al rechazar] ·
  rechazado → enviado_cliente (`version_enviada + 1`, admite nuevo monto/descripción) | cancelado · aceptado → programado [despachador,
  admin prestador: fecha + técnicos con `ejecutar_trabajos_especiales`, responsable = jefe de cuadrilla] · programado → en_ejecucion y
  en_ejecucion → cerrado [técnico responsable o sistema] · no final → cancelado [admin prestador, mesa, despachador; el cliente solo sus
  TE de urgencia antes de programar]). **`cambiar_estado_te(db, actor, te, nuevo, notas, request, **campos)`** es la única entrada: valida
  rol y campos, escribe `te_historial`, audita, notifica con `notificar()` (eventos `trabajo_especial.*`) y sincroniza el folio operativo.
  `crear()` (prestador u urgencia del cliente, resuelve el formulario `trabajo_especial` con P03), `desde_cotizacion()` (§7.7 M1
  autorizada → convertida; sustituye el 501 de `cotizaciones.convertir_en_trabajo_especial`), `requisitos_cierre()` (formulario del TE,
  evidencia fotográfica de cierre y firma del cliente → 409 `CIERRE_TE_INCOMPLETO`), `agregar_evidencia()`, `cotizacion_retroactiva()`,
  `seccion_minuta()` (§7.3 nuevos / en proceso / terminados con evidencia y etiqueta de urgencia), `reporte()` y `serializar()/detalle()`.
- **Relación TE ↔ folio operativo**: al pasar a `programado` se crea un folio `tipo_folio = especial` vinculado por
  `folios.trabajo_especial_id` (capturado por el sistema, confirmado, directo a Autorizado y Asignado al responsable; los demás técnicos van
  en el contexto del historial); la app del técnico (P05) lo atiende con el formulario del TE (`sync_service` y `AtencionTecnico` resuelven
  `trabajo_especial` para `especial`). Sincronización en ambos sentidos: TE `en_ejecucion` ↔ folio `en_ejecucion` (en_camino + llegada),
  `cerrado` ↔ `cerrado` y la cancelación de cualquiera cancela al otro (`_sincronizar_folio` y el suscriptor `_al_transicionar_folio`);
  el validador `_validar_cierre_te` bloquea el cierre del folio si al TE le faltan requisitos.
- **`services/oc_activos_service.py`** (§6.10.7): `detectar()` lee el campo con `clasifica_instalacion_activo` (`ActivoMapeo` en
  `schemas/formularios.py`: `valor_afirmativo` y mapeo de tipo de equipo, marca, modelo, serie, valor de reposición y nombre);
  `desde_respuesta()` se engancha en la captura (P04, formulario de captura) y en el envío del formulario de atención (P03). `marcar()` pone
  `es_instalacion_activo`, crea la autorización, historial, evento `activo.clasificado` y avisa a Admin UN/empresa. En la captura el folio
  queda `en_revision` con el trigger `pendiente_oc_cliente` (sin flujo multinivel ni clasificación). `cambiar_estatus()` (Admin empresa):
  pendiente → oc_en_tramite (provisional opcional) → oc_autorizada (definitivo + fecha obligatorios) → `listo_para_asignar` automático
  (resuelve el trigger y `transicionar(autorizado)` si no quedan otros triggers; si quedan, avisa al despachador) ·
  pendiente/en_tramite → oc_rechazada con `cancelar` (folio cancelado) o `reprogramar_periodo` (registro en Por presupuesto con el período
  destino + folio cancelado). `alta_equipo()` corre en el validador previo al cierre (`suscribir_validacion`, porque el folio cerrado es
  inmutable): `ACT-<folio>`, tipo por id o nombre, marca/modelo/serie/valor, `fecha_instalacion` = cierre, contrato vigente, y si falta el
  tipo → `inactivo` + `ACTIVO_INSTALADO_INCOMPLETO` + aviso al Admin empresa. `pendientes()` (Admin UN sus UNs, Admin empresa, prestador).
- **Endpoints**: `/api/trabajos-especiales` (listado con filtros tenant/UN/estado/urgencia/período/`por_validar`, `POST` crear,
  `/{id}`, `enviar`, `aceptar`, `rechazar`, `programar`, `iniciar`, `cerrar`, `cancelar`, `estado` (Kanban), `evidencias`,
  `cotizacion-retroactiva`, `reporte` + `.xlsx` + `.pdf`) y `/api/oc-activos` (`pendientes`, `/{folio_id}`, `/{folio_id}/estatus`).
  `POST /api/seguimiento/cotizaciones/{id}/convertir` devuelve la cotización convertida con el TE; el listado y detalle de cotizaciones
  traen `estado_trabajo_especial` y `trabajo_especial_numero`. El detalle del folio incluye `oc_activo` y `trabajo_especial`; el resumen,
  `es_instalacion_activo`, `equipo_instalado_id` y `trabajo_especial_id`.
- **Frontend**: módulos `trabajos_especiales` (`/trabajos-especiales`, `pages/trabajos_especiales/TrabajosEspeciales.tsx`: listado,
  Kanban del prestador, bandeja «Por validar» del cliente con aceptar/rechazar, creación ordinaria y de urgencia, detalle con línea de
  tiempo, versiones, respuestas del cliente, cotización y folio vinculados, programación con técnicos, iniciar/cerrar, cotización
  retroactiva y cancelación, reporte exportable) y `oc_activos` (`/oc-activos`, `pages/oc_activos/OcActivos.tsx`: pendientes, registro
  de estatus/OC, decisión ante rechazo, historial, equipo dado de alta). `FolioDetalle` y `Folios` muestran «Esperando OC del cliente» y el
  TE vinculado; la app del técnico etiqueta «Trabajo especial» / «Urgencia» y resuelve el formulario del TE; la minuta muestra la sección real.
- **Seed** (`scripts/seed_trabajos_especiales.py`): formulario «Trabajo especial (global)» asignado a `especial`, formulario de captura
  «instalación de activo», permiso TE para Tomás y Tania (overrides), 8 TE (TE-000001 creado … TE-000008 cancelado; TE-000002 con dos
  versiones y un rechazo; TE-000005 desde COT-00002; TE-000006 de urgencia del Admin UN en ejecución; TE-000007 cerrado con evidencia y
  firma) y 4 folios de activo (CD-000038 pendiente, CD-000039 en trámite, CD-000040 OC autorizada pero retenido por el trigger de
  contrato vencido, CD-000041 cerrado con el equipo `ACT-CD-000041` inactivo por ficha incompleta).
- **Para P09**: `trabajos_especiales.monto`, `cotizacion_retroactiva_id` y `folios.monto_estimado` del folio operativo son los ganchos de
  costo; `equipos` creados por `alta_equipo()` alimentan activos y depreciación (`valor_reposicion`, `fecha_instalacion`, `contrato_id`).
  **Para P10**: `te_historial` y `folio_activo_historial` dan tiempos por etapa; `TE_PROGRAMADO_VENCIDO` y `OC_ACTIVO_*` entran al tablero.

### Inventario, costos y activos (P09)
- **Tablas (0009)**: `articulos`, `ubicaciones_inventario` (almacén o vehículo con `tecnico_id` y placas), `existencias`
  (`cantidad`, `stock_minimo`, `costo_promedio` por ubicación+artículo), `movimientos_inventario` (**append-only**: entrada,
  salida, traspaso, ajuste, consumo_folio con `origen` almacen/oc/caja_chica, folio, razón y referencia), `ordenes_compra` +
  `orden_compra_partidas` (borrador → aprobada → enviada_erp → recibida | cancelada, `recibido` por partida),
  `fondos_caja_chica`, `gastos_caja_chica` (factura con foto en MinIO, RFC, UUID, subtotal/IVA/total, estado y `estado_cfdi`),
  `polizas_exportacion`, `validaciones_cfdi`, `folio_costos` (refacciones + mano de obra + otros + ajuste, horas y tarifa,
  `origen_horas`, centro de costos, validación y `documento_erp_ref`), `tarifas_mano_obra`, `presupuestos` (UN **o** grupo con
  CHECK excluyente, tipo de actividad, período, monto y `umbrales_alerta_json`), `presupuesto_consumos` (**append-only**),
  `erp_eventos_pendientes`, `erp_configuracion`, `erp_exportaciones`, `activo_depreciacion`, `activo_depreciacion_historial`
  (**append-only**), `activo_tco_snapshot` y `activo_reemplazo_alertas`. 13 ENUM nuevos; `tipos_equipo` y `equipos` ganan los
  campos económicos (`costo_adquisicion`, `fecha_adquisicion`, `costo_hora_inactividad`, `numero_activo_fijo_erp`). 6 alertas
  nuevas (`STOCK_NEGATIVO`, `OC_SIN_APROBAR`, `OC_SIN_RECIBIR`, `GASTO_CAJA_CHICA_SIN_APROBAR`, `PRESUPUESTO_UMBRAL_ALCANZADO`,
  `PRESUPUESTO_EXCEDIDO`) y 9 evaluadores en `workers/evaluadores_inventario.py` (41 en total). RLS forzada en todas; las tablas
  que el prestador escribe en contexto de tenant usan `acma_tenant_visible()` también en el WITH CHECK de escritura.
- **`services/inventario_service.py`**: `_mover()` es el único escritor de existencias y movimientos; la entrada recalcula el
  **costo promedio ponderado** y la salida no lo altera. `entrada` / `traspaso` (almacén → vehículo del técnico) / `ajuste`
  (admite negativos, razón obligatoria), `consumir_en_folio()` (§6.4 Tipo A: en línea bloquea con 409 `STOCK_INSUFICIENTE`),
  `aplicar_consumo_offline()` (§6.2: aplica los dos consumos, deja `SincronizacionConflicto` con `merge_alerta` y dispara
  `STOCK_NEGATIVO`), ciclo de la OC (`crear_oc` / `aprobar_oc` → evento ERP `generar_oc` / `recibir_oc` → entrada al almacén /
  `cancelar_oc`) y `tiene_materiales()` para el `refaccion_ok` de P06.
- **`services/caja_chica_service.py`** (§6.4 Tipo C y §6.5): `capturar_gasto()` (el técnico sube la foto y captura a mano; OCR y
  validación del CFDI son stubs de Fase 1), `aprobar_gasto()` resuelve en una sola transacción el alta de la refacción del folio,
  el movimiento de inventario y el cargo al fondo (409 `SALDO_INSUFICIENTE` si el fondo no alcanza), `rechazar_gasto()` con razón,
  `generar_poliza()` / `generar_polizas_del_dia()` con las 12 columnas literales de §6.5 en Excel más el XML de póliza.
- **`services/costos_service.py`** (§6.8.6): `calcular()` corre suscrito al cierre del folio (`folio_estados.suscribir`) y suma
  refacciones consumidas + mano de obra (horas × tarifa vigente) + otros + ajuste; `validar()` (Mesa de control, Admin prestador,
  superadmin) cierra el costo, genera el evento ERP `registrar_gasto` y registra el consumo en los presupuestos aplicables;
  `detalle_financiero()` respeta la visibilidad de costos del rol; `tarifa_vigente()` resuelve la tarifa más específica.
- **`services/presupuestos_service.py`** (§6.8.5): `aplicables()` (la UN y sus grupos × tipo de actividad y período),
  `registrar_consumo()`, `comprometido()` (folios autorizados sin cerrar con monto estimado), `_revisar_umbrales()` (dispara
  `PRESUPUESTO_UMBRAL_ALCANZADO` / `PRESUPUESTO_EXCEDIDO` una sola vez por umbral, deduplicando contra `alertas_historial`),
  `resumen()`, `consolidado()` (Tenant → Grupo → UN con semáforo verde/amarillo/rojo) y `disponible_para_folio()`.
- **`services/activos_service.py`** (§6.9.4): `valor_en_libros()` con los 4 métodos (línea recta, doble saldo decreciente,
  unidades de producción → `REQUIERE_MEDIDORES_FASE_2`, manual), `componentes_tco()` y `calcular_tco()` (adquisición +
  preventivos + correctivos + inactividad − valor residual, con las refacciones como desglose), `_revisar_reemplazo()` (alerta
  `ACTIVO_REEMPLAZO` al superar el umbral del valor de reposición), `decidir_reemplazo()` (aceptar genera el trabajo especial de
  reemplazo de P08; posponer exige razón), `ficha()` y `calcular_mes()` para la tarea mensual.
- **Capa ERP desacoplada** (§6.6, `services/erp/`): ACMA nunca habla con el ERP; `eventos.py` genera los 4 eventos internos
  (`generar_oc`, `registrar_gasto`, `crear_activo_fijo`, `poliza_caja_chica`), `base.py` registra los adaptadores (CONTPAQi y
  Microsip quedan como **stub** `omitido` de Fase 2) y `exportacion.py` produce la exportación universal (XML de pólizas y Excel
  con columnas configurables) que en Fase 1 sustituye a los adaptadores.
- **Endpoints**: `/api/inventario` (artículos, ubicaciones, existencias, movimientos entrada/traspaso/ajuste, órdenes de compra
  con aprobar/recibir/cancelar), `/api/caja-chica` (fondos y reposición, ocr, gastos con imagen/aprobar/rechazar, pólizas y
  archivo), `/api/presupuestos` (listado, consolidado, alta/edición, consumos, tarifas), `/api/erp` (configuración, eventos y
  procesar, exportaciones y archivo), `/api/activos` (listado, ficha, datos-economicos, depreciacion, calcular, alertas-reemplazo,
  decidir, umbral-reemplazo) y `GET/POST /api/folios/{id}/costos[/validar]`.
- **Tareas Celery**: `acma.generar_polizas_caja_chica` (23:00), `acma.calcular_depreciacion_tco` (día 1, 03:30) y
  `acma.exportar_erp_periodo` (día 1, 04:00).
- **Frontend**: módulos `inventario` (`/inventario`), `caja_chica` (`/caja-chica`), `presupuestos` (`/presupuestos`), `activos`
  (`/activos` y la ficha `/activos/:equipoId`) y `erp` (`/erp`); `pages/folios/Financiero.tsx` es la sección «Datos financieros»
  del folio y `pages/campo/tecnico/GastoCajaChica.tsx` la captura del gasto desde la atención del técnico; el folio en
  `pendiente_refaccion` ofrece generar la orden de compra.
- **Seed** (`scripts/seed_inventario.py`): 25 artículos en 4 categorías, almacén central y un vehículo por técnico (2 artículos
  bajo mínimo), 3 OC en distintos estados, 2 fondos con 5 gastos y 1 póliza, tarifas de mano de obra, costos calculados y
  validados, presupuestos calibrados al 85 % y al 125 %, configuración ERP con los 4 tipos de evento y 6 activos con 12 meses de
  snapshots y 1 alerta de reemplazo.
- **Para P10**: `folio_costos.costo_total` es la base de la penalización por SLA; `presupuesto_consumos` y `presupuestos`
  alimentan el gasto contra presupuesto del tablero; `activo_tco_snapshot` da el TCO histórico para el top de equipos por costo;
  `erp_eventos_pendientes` y `erp_exportaciones` son la fuente del resumen exportable de penalizaciones; las 6 alertas nuevas
  entran a la configuración central y `PRESUPUESTO_UMBRAL_ALCANZADO` debe conciliarse con `PRESUPUESTO_ALERTA_1/2/3`.

### SLA, alertas y BI (P10)
- **Tablas (0010)**: `folio_sla_pausas` (motivo reasignacion/pendiente_informacion/otro, inicio, fin, minutos; índice único
  de una sola pausa abierta por folio), `folio_sla_exclusiones` (causa literal de §6.10.1, descripción, período, minutos,
  `aprobada` NULL = pendiente, `aprobado_por`, `decidida_at`, `razon_decision`), `penalizaciones_periodo` (contrato +
  período únicos, total de folios, incumplidos, monto, moneda, estado borrador → revisado → cerrado, `detalle_json` con el
  folio a folio, `incluido_en_factura_id` que llenará el CFDI de Fase 2), `iguala_consumo_periodo` (correctivos incluidos /
  atendidos / adicionales, preventivos incluidos / ejecutados, tarifa y los folios adicionales identificados),
  `reportes_programados` (tenant **o** prestador, tipo, filtros, formato pdf/excel, periodicidad diaria/semanal/mensual,
  `dia_hora`, destinatarios, `ultimo_envio_at`) y `reportes_generados` (archivo, filas y `ms_generacion`). 5 ENUM nuevos.
  **Columnas**: `contratos` gana `tarifa_iguala_mensual` y `moneda` (con CHECK de que la iguala traiga tarifa y folios);
  `contrato_sla` gana `tiempo_respuesta` / `tiempo_resolucion` en la unidad firmada y un CHECK de 1 a 4,320 horas
  equivalentes; `folio_sla` gana `tiempo_inicio`, `tiempo_respuesta_at`, `tiempo_fin`, `tiempo_pausado_min`,
  `tiempo_exclusion_min`, `tiempo_efectivo_min`, `tiempo_respuesta_efectivo_min`, `limite_respuesta_min`, `limite_sla_min`,
  `cumplimiento`, `penalizacion_calculada`, `penalizacion_detalle_json`, `contrato_sla_id` y las dos banderas de aviso de
  riesgo; `alertas_catalogo` gana `fase` (1/2) y `escalacion_de`; `alertas_historial` gana `vista_por`, `atendida_at`,
  `atendida_por`, `nota_atencion` y `escalada`. RLS forzada en las 6 tablas nuevas (política de folio: leen el tenant y el
  prestador, escriben ambos, porque el prestador registra y el cliente aprueba).
- **`services/sla_service.py`** (el contador, §6.10.1): `fijar_limites()` al autorizar (crea la fila si falta, fija
  `tiempo_inicio` y los límites en minutos desde `contrato_sla` del contrato vigente por severidad); `abrir_pausa()` /
  `cerrar_pausa()`; `minutos_pausados()` y `minutos_excluidos()` (solo lo aprobado); `recalcular()`
  (`tiempo_efectivo = total − pausas − exclusiones`, cumplimiento de respuesta y de resolución, penalización);
  `en_riesgo()` (80 % por defecto, una sola vez por folio); `registrar_exclusion()` / `decidir_exclusion()` (y el
  recálculo cuando se aprueba después del cierre); `consolidar_penalizaciones()` y `revisar_penalizacion()`;
  `consumo_iguala()` con la alerta `IGUALA_LIMITE_ALCANZADO`; `contratos_por_vencer()`; y el gancho
  `@folio_estados.suscribir` que hace todo lo anterior en las transiciones.
- **`services/alertas_service.py`** (ampliado, §6.9.6): `canonica()` con el diccionario `ALIAS` de las claves que P01–P09
  nombraron de otra forma; `efectiva()` resuelve también `fase` y `escalacion_de`; `umbral()` y `destinatarios()` (roles
  efectivos → usuarios del tenant y del prestador); `panel()` (feed del usuario filtrado por los roles destinatarios),
  `marcar_vista()`, `atender()`, `suprimir()`; `escalaciones()`, `configurar_escalacion()`, `cadena_de()` y `por_escalar()`
  (el umbral corre **desde el disparo de la alerta origen**).
- **`services/bi_service.py`**: `Filtro` (período + tenant/prestador/grupo/UN, con `anterior()` y `anio_anterior()`),
  `filtro_de()` (encierra al actor en su dominio y al Admin UN en sus UNs), y los indicadores `folios_por_estado`,
  `folios_por_severidad`, `cumplimiento_sla`, `mttr`, `mtbf`, `gasto_vs_presupuesto`, `costo_total`, `top_equipos`,
  `preventivos`, `hallazgos`, `cotizaciones`, `trabajos_especiales`, `carga_por_tecnico`, `penalizaciones`, `iguala`,
  `inventario_y_caja`, `alertas_abiertas`, `jornada` (§6.8.4 sin mapa) y `comparativo_jerarquia` (§6.8.5). `tablero()` arma
  el tablero del rol (`cliente`, `supervision`, `prestador`, `direccion`, `jornada`) y lo guarda en Redis con **TTL de
  120 s**; sin Redis se recalcula. Cada indicador está documentado en `docs/bi/indicadores.md` (entregable ACT-8.1).
- **`services/reportes_service.py`** (ACT-8.4): `secciones()` por plantilla (`cliente`, `prestador`, `jornada`),
  `a_html()` y `a_excel()` con el logo y los colores del prestador, `generar()` (deja el registro con `ms_generacion` y
  `filas`), `crear_programado()`, `toca_hoy()` y `periodo_de()`.
- **Endpoints**: `/api/sla` (contador del folio, exclusiones y su decisión, cumplimiento del contrato, penalizaciones con
  cálculo, cambio de estado y archivo PDF/Excel, iguala), `/api/bi` (tablero, jornada, indicador suelto, generar reporte,
  generados y su archivo, CRUD de programados) y en `/api/alertas` el panel del usuario, atender, escalaciones y su
  configuración. El detalle del folio trae `sla_contador` con pausas, exclusiones y cumplimiento.
- **Conciliación de claves de alerta (§6.9.6)**: el catálogo de P01 ya traía los 20 nombres literales del documento, así que
  P10 **eliminó las dos claves que P09 había duplicado** y migró su configuración, historial y supresiones:
  `PRESUPUESTO_UMBRAL_ALCANZADO` → `PRESUPUESTO_ALERTA_1` y `PRESUPUESTO_EXCEDIDO` → `PRESUPUESTO_ALERTA_3` (con
  `PRESUPUESTO_ALERTA_2` al 90 % ya en el catálogo). Las claves viejas siguen aceptándose como **alias** en
  `alertas_service.canonica()`, junto con `SEGUIMIENTO_INTERNO_SIN_ACTUALIZAR` → `SEGUIMIENTO_SIN_UPDATE` y
  `TECNICO_SIN_SEÑAL` → `TECNICO_SIN_SENAL`. Alertas nuevas: `SLA_INCUMPLIDO`, `EXCLUSION_SLA_PENDIENTE`,
  `CONTRATO_POR_VENCER`, `IGUALA_LIMITE_ALCANZADO`, `SLA_INCUMPLIDO_ESCALADO_DIRECCION` y
  `PRESUPUESTO_ESCALADO_DIRECCION` → **59 alertas y 51 evaluadores**. Las 5 de Fase 2 (`TECNICO_TIEMPO_MUERTO`,
  `TECNICO_DESVIO_RUTA`, `TECNICO_SIN_SENAL`, `MEDIDOR_PROXIMO_PM`, `CERTIFICACION_VENCIDA`) quedan con `fase = 2`,
  inactivas y con 422 `ALERTA_FASE_2` si se intentan activar.
- **Tareas Celery**: `acma.consolidar_penalizaciones` (día 1, 05:00: penalizaciones e iguala del mes cerrado),
  `acma.enviar_reportes_programados` (08:00 diario, filtra por periodicidad) y `acma.reporte_cierre_jornada` (22:30).
- **Frontend**: módulo `contratos` con las pestañas Contratos / Cumplimiento y penalizaciones / Exclusiones (iguala, SLA por
  severidad con unidad y tipo de penalización, revisión borrador → revisado → cerrado y exportación PDF/Excel); módulo
  `alertas` rehecho como configuración central (catálogo agrupado por módulo con default, rango, umbral propio, canales,
  roles y columna «Fase 2», escalaciones, supresiones e historial) y `components/PanelAlertas.tsx` colgado de la cabecera;
  módulo `bi` (`pages/bi/Dashboard.tsx` con el tablero del rol y `pages/bi/Reportes.tsx`); `pages/folios/SeccionSLA.tsx` con
  el contador y el botón «Registrar exclusión». Gráficas con **Recharts 3.10.1** (código abierto, compatible con React 19),
  paleta accesible y **cada valor también en texto**. Con P10 los 27 módulos de Fase 1 tienen ruta: no queda ninguno
  «Disponible en el prompt Pxx».
- **Seed**: `scripts/seed_sla.py` convierte el contrato demo a modalidad iguala (20 correctivos y 8 preventivos al mes,
  tarifa de $48,000, SLA y penalización por las 5 severidades), calcula `folio_sla` de todos los folios del seed con 3
  incumplidos, 1 pausa por reasignación y 2 exclusiones (una aprobada y una pendiente), consolida las penalizaciones de 3
  meses (una cerrada, una revisada y una en borrador), configura alertas por tenant con una supresión activa y 2
  escalaciones en el historial, y deja 2 reportes programados. `scripts/seed_historico.py` genera el histórico sintético
  (por defecto 1,200 folios cerrados en 12 meses con costo y `folio_sla`) y va **aparte** para no hacer lento el seed normal.
- **Para P11 (endurecimiento y rendimiento)**: el bundle pasa de 500 kB por Recharts (conviene `import()` dinámico del
  tablero); `comparativo_jerarquia()` recorre grupo por grupo y UN por UN (una consulta por nivel) y `consumo_iguala()`
  recalcula al leer el tablero del prestador, así que con muchos clientes conviene materializarlos o alargar el TTL;
  `seed_historico` tarda ~1 min por 1,000 folios; el reporte del cliente sobre 12 meses tarda ~0.9 s en PDF y ~1.3 s en
  Excel; y el panel de alertas resuelve los roles destinatarios clave por clave (cachear el catálogo).

### Capacitación y biblioteca (F2-01)
- **Tablas (0013)**: `cursos_catalogo` (prestador_id **nullable**: NULL = curso global de la plataforma; nombre, proveedor,
  duración, `vigencia_meses` NULL = no caduca, `habilidad_id` que certifica, tipo curso/certificación,
  `norma_referencia`), `tecnico_cursos` (técnico + curso, fechas, calificación, `aprobado`, folio de constancia,
  `vigente_hasta` con su `razon_vigencia` cuando se fija a mano, `certificado_key` del archivo cifrado),
  `capacitacion_alertas_config` (por prestador: `dias_anticipacion`, `notificar_cliente`, `activa`),
  `biblioteca_manuales` (prestador + tipo de equipo, título, categoría, versión vigente, archivo, hash, bytes),
  `biblioteca_versiones` (**append-only** con `acma_auditoria_inmutable()`: versión anterior, su archivo, quién la
  reemplazó y las notas), `contenido_servicio` (tenant + tipo de equipo + contrato, `puntos_revision_json` ordenados,
  periodicidad, correctivos y preventivos de la iguala, versión) y `tecnico_descargas_offline` (manual **o** contenido,
  versión descargada, dispositivo, `en_dispositivo`). 3 ENUM nuevos. RLS forzada en las siete.
- **Políticas que no son las de siempre**: el curso global (`prestador_id IS NULL`) lo lee cualquiera con contexto;
  el cliente lee `tecnico_cursos` solo de certificaciones **aprobadas y vigentes** de quien está habilitado en sus
  unidades o atendió un folio suyo en los últimos 90 días. Para que ese EXISTS funcione se agregaron políticas de
  lectura de cliente en `tecnicos` y `tecnico_tenants_habilitados`: **la subconsulta de una política también pasa por
  la RLS de la tabla que lee**, así que sin ellas la vista del cliente salía vacía.
- **`services/capacitacion_service.py`**: `vigencia_de()` (suma meses respetando fin de mes), `estado_de()`
  (vigente / por_vencer / vencido / sin_vigencia con los días de anticipación del prestador), catálogo (`listar_cursos`,
  `crear_curso`, `editar_curso`), `registrar_curso()` con la constancia (PDF/JPG/PNG/WebP, 10 MB, cifrada con el sobre
  de P11a), `_certificar_habilidad()` (un curso **aprobado** con habilidad la certifica; la declarada a mano gana y
  nunca se le recorta la vigencia), `expediente()`, `proximos_vencimientos()`, `tecnicos_de_mis_unidades()` (vista del
  cliente), `recalcular_estados()` (la tarea diaria que retira la habilidad vencida y avisa) y la exportación del
  expediente en Excel y PDF.
- **`services/biblioteca_service.py`**: manuales (`subir_manual`, `nueva_version` que conserva el historial,
  `desactivar_manual`, `listar_manuales` con `solo_mis_folios`), contenido de servicio (`guardar_contenido` con
  `_avisos_de_coherencia` contra la iguala del contrato de P10 —avisa, no bloquea—, `listar_contenido`),
  `apoyo_de_folio()` (puntos de revisión + manuales del tipo de equipo del folio, en una sola llamada para la app del
  técnico), descarga firmada (`firmar_descarga` / `archivo_firmado`, JWT de 5 minutos que **reconstruye el contexto RLS
  desde su `sub`** porque el visor del navegador no manda cabecera de autorización), `registrar_descarga`,
  `mis_descargas` y `paquete_del_tecnico()` para la sincronización.
- **Habilidad certificada como restricción dura**: `folios_captura_service.tecnico_con_habilidad()` ahora exige
  `tecnico_habilidades.certificada`, no solo que la fila exista. `estado_certificacion()` distingue «no declaró la
  habilidad» de «la tiene pero su certificación venció», y la reasignación (P06) lo muestra candidato por candidato.
- **Alertas**: `CERTIFICACION_VENCIDA` deja de ser de Fase 2 (fase 1, activa por defecto, evaluador en
  `workers/evaluadores_capacitacion.py` con el umbral = min(configuración del prestador, catálogo)) y se agrega
  `CERTIFICACION_VENCIDA_HABILIDAD_RETIRADA` (informativa, sin evaluador: la dispara la tarea al retirar la habilidad).
  Tarea `acma.recalcular_capacitacion` en el beat a las 05:10.
- **Sincronización (§6.2 capa 3)**: la clave `biblioteca` de `GET /api/sync/catalogos` ya no viene vacía: metadatos
  (no archivos) incrementales por `updated_at`, con `activo: false` para las bajas y `de_mis_folios` para que el
  dispositivo sepa qué le toca. El contenido de servicio solo viaja si es de un folio asignado.
- **PWA**: Dexie **versión 3** con `biblioteca_offline` (blob + metadatos + versión + `desactualizado`).
  `services/bibliotecaOffline.ts` concilia el paquete (marca lo desactualizado, retira las bajas y descarga sola los
  manuales de los folios del día **solo con Wi-Fi**, configurable), respeta un tope propio en MB y la cuota del
  navegador (`navigator.storage.estimate()`, avisando antes de pasarse), y registra cada guardado y cada borrado en el
  servidor (sin señal queda local y se registra al volver la red).
- **Endpoints**: `/api/capacitacion` (cursos: listar, crear, editar; `tecnicos/{id}/cursos` multipart,
  `tecnicos/{id}/expediente`, `tecnicos/{id}/certificado/{tc}`, `tecnicos/{id}/expediente.xlsx|.pdf`, `vencimientos`,
  `tecnicos-de-mis-unidades`, `alertas/configuracion` GET/PUT) y `/api/biblioteca` (`manuales` listar/subir,
  `manuales/{id}/versiones` GET/POST, `manuales/{id}` DELETE, `manuales/{id}/enlace`, `contenido/{id}/enlace`,
  `archivo?token=`, `contenido` listar/guardar, `contenido/{id}/documento`, `folios/{id}/apoyo`, `offline` GET/POST).
- **Frontend**: módulos `capacitacion` (grupo **Administración**: es expediente de personal, vive junto a usuarios y
  catálogos) y `biblioteca` (grupo **Operación**: se consulta mientras se atiende). `pages/capacitacion/Capacitacion.tsx`
  (expedientes con semáforo en texto y color, catálogo, vencimientos, alertas, y vista separada del cliente),
  `pages/biblioteca/Biblioteca.tsx` (manuales con versiones y visor en el navegador, editor de puntos de revisión
  ordenados), y en la app del técnico `ApoyoDelFolio` (puntos de revisión y manual dentro de la atención, con lo
  descargado cuando no hay señal) y `MisManuales` («Mis manuales sin conexión»: espacio usado, versión, aviso de
  versión nueva, actualizar y borrar).
- **Hoja «Dónde se ve en el sistema» (Excel, no se edita)**: quedan obsoletas las filas que marcan como «Fase 2» o
  «sin pantalla» la **capacitación / certificaciones del personal**, la **biblioteca de manuales**, el **contenido de
  servicio contractual** y la alerta **CERTIFICACION_VENCIDA**: los cuatro ya tienen pantalla y están activos. Sigue
  vigente lo que la hoja diga de GPS, medidores, OCR y adaptadores de ERP.

### WhatsApp y SMS (F2-02)

**Regla de selección de canal.** `notificar()` sigue siendo el único punto de entrada; para `whatsapp` y `sms`
pregunta a `mensajeria_service.evaluar()`, que aplica en este orden y deja escrito el motivo del «no»:

1. preferencia del usuario por evento (`notificacion_preferencias`, P07);
2. canal activo en `mensajeria_configuracion` (fila del tenant si existe, si no la del prestador);
3. lista blanca de eventos del canal, si está llena (vacía = todos);
4. teléfono registrado **y verificado**, y consentimiento vigente de ese canal;
5. horario de silencio, salvo eventos críticos;
6. tope mensual de mensajes, salvo eventos críticos.

Cuando no puede salir, la notificación queda `omitida` con el motivo y **el aviso cae al siguiente canal** (`push`,
`email`, `app`, el primero que el usuario no tuviera ya). Lo mismo pasa con un error permanente del proveedor
(número inválido, plantilla rechazada, usuario dado de baja): no se reintenta y cae al siguiente canal. Los errores
temporales se reintentan con espera exponencial (2, 4, 8… minutos, hasta 5 intentos) desde
`acma.reintentar_mensajeria`, cada 5 minutos en el beat.

**Eventos críticos** (ignoran el silencio y el tope): `aprobacion.pendiente`, `aprobacion.bloqueada`,
`trahabajo_especial.urgencia`, la verificación del teléfono, las alertas de SLA
(`SLA_INCUMPLIDO`, `SLA_RESPUESTA_EN_RIESGO`, `SLA_RESOLUCION_EN_RIESGO`, su escalación a dirección y
`TECNICO_SIN_SENAL`), el folio rechazado y cualquier evento con severidad o urgencia crítica.

**Capa de proveedores** (`services/mensajeria/`): la interfaz `ProveedorMensajeria` (`enviar_plantilla`,
`enviar_texto`, `estado`, `validar_webhook`) con tres implementaciones —`stub` (por defecto; guarda el mensaje
renderizado en la bitácora y un archivo de vista previa en el almacenamiento, simula entrega y lectura y acepta
fallas programadas por número para las pruebas), `meta_cloud` (WhatsApp Cloud API) y `twilio` (SMS y,
opcionalmente, WhatsApp)—. El modo se elige con `WHATSAPP_MODO` y `SMS_MODO` (`stub` / `prueba` / `real`), igual que
`SMTP` en P07; si el modo pide un proveedor real y falta su credencial, se usa el simulado y queda en el log, para
que una variable mal escrita no deje a nadie sin aviso. Límite de tasa por proveedor y por tenant
(`MENSAJERIA_MAX_POR_MINUTO`, cubeta por minuto en el proceso).

**Plantillas.** El texto vive en `services/mensajeria/plantillas.py` (una sola fuente) y `sembrar_plantillas()` lo
sincroniza con `mensajeria_plantillas`, que es lo que el Admin prestador edita y somete a Meta: 22 plantillas por
canal, en español, categoría `utility`, con variables posicionales `{{1}}…` y botón de enlace a la pantalla exacta.
La base es de la plataforma (`prestador_id` nulo); cuando el Admin prestador la edita, ACMA **clona** la plantilla
para su prestador en borrador y deja la base intacta. En modo `stub` nacen `aprobada` (no hay nada que someter);
con cuenta real nacen en borrador. `GET /plantillas/{id}/exportar` entrega el JSON que pide Meta.
Ninguna plantilla lleva datos financieros ni personales de terceros: una prueba revisa el catálogo completo con
`datos_sensibles()`, y los SMS se escriben **sin acentos** para caber en un segmento GSM-7 de 160 caracteres.

**Minuta por WhatsApp (§7.5).** `minuta_service.enviar()` manda, además de los tres canales de Fase 1, una
notificación por WhatsApp o SMS a quien lo haya pedido en sus preferencias: resumen de **máximo 5 puntos** con lo
más crítico del día (indicadores en rojo, hallazgos de urgencia alta o crítica, preventivos con retraso,
cotizaciones por vencer, hallazgos sin responder) y botón al **PDF completo** con un enlace firmado de 60 minutos
(`/api/mensajeria/minutas/{token}.pdf`, que reconstruye el contexto RLS del usuario del token, como el visor de
F2-01). Sin nada crítico, el mensaje dice «sin pendientes críticos» con el mismo enlace.

**Enlace corto propio.** Cada envío lleva un `codigo_enlace` de 8 caracteres; el mensaje enseña
`APP_URL_PUBLICA/l/{codigo}` y la pantalla `/l/:codigo` resuelve el destino con
`GET /api/mensajeria/enlaces/{codigo}` (público a propósito: lo abre quien recibió el mensaje, que no tiene sesión en
ese navegador; solo devuelve una ruta y registra el clic en `abierto_at`). Sin servicio externo de acortamiento.

**Teléfono y consentimiento (§6.9.5).** El número vive **cifrado** en `usuarios.telefono_movil_e164` (el mismo
envelope AES-256-GCM de P11a) con su `hash` —para reconocer al remitente de un mensaje entrante sin descifrar a
nadie— y su máscara `+52 871 ••• ••34`, que es lo único que se muestra y lo único que se guarda en bitácoras. El
alta la hace el propio usuario en *Notificaciones → Mi celular*, con verificación por código de un solo uso de 6
dígitos (10 minutos, 5 intentos) enviado por el mismo canal; cambiar el número obliga a verificarlo otra vez.
Consentimiento explícito por canal con fecha; «BAJA» por WhatsApp o SMS da de baja el canal de inmediato y «ALTA» lo
reactiva, con acuse por el mismo canal dentro de la ventana de 24 h.

**Ninguna acción crítica se ejecuta desde un mensaje.** Los botones «Aprobar» y «Rechazar» del WhatsApp de una
aprobación son respuestas rápidas: al llegar, ACMA contesta con el enlace a la pantalla de aprobación y registra
`accion_ejecutada = enlace_enviado`. La decisión se toma en ACMA, con sesión y doble factor si el rol lo exige.

**Costo.** `costo_estimado` por mensaje con las tarifas de `mensajeria_configuracion` (sin consultar precios del
proveedor), contador del mes por prestador y por tenant, alerta `MENSAJERIA_CONSUMO_ALTO` al llegar al porcentaje
configurado (una vez por mes y dueño) y bloqueo de los no críticos al llegar al tope. Un SMS de dos segmentos cuesta
el doble; lo que no salió no se cobra. `MENSAJERIA_PLANTILLA_RECHAZADA` se dispara cuando el proveedor rechaza o
pausa una plantilla.

**Webhooks.** `POST /api/mensajeria/webhook/meta` (firma `X-Hub-Signature-256` con el secreto de la app;
`GET` responde el `hub.challenge` con `WHATSAPP_VERIFY_TOKEN`) y `POST /api/mensajeria/webhook/twilio` (firma
HMAC-SHA1 de la URL más los parámetros). Sin secreto configurado los dos quedan cerrados. En una máquina local el
proveedor no alcanza a ACMA: `POST /api/mensajeria/webhook/simular` hace su papel (solo administradores, nunca en
producción).

**Lo que falta para producción:** plantillas aprobadas por Meta, número de negocio verificado (y token permanente,
no el temporal de 24 h), URL pública con HTTPS y los webhooks configurados en Meta y en Twilio, tarifas reales y
revisión legal del aviso de privacidad. El paso a paso de las cuentas gratuitas está en
[`docs/operacion/mensajeria.md`](docs/operacion/mensajeria.md).

- **Hoja «Dónde se ve en el sistema» (Excel, no se edita)**: quedan obsoletas las filas que marcan como «Fase 2» los
  canales **WhatsApp** y **SMS** de notificaciones y alertas: los dos están activos, con pantalla propia
  (*Mensajería*) y con su configuración por cliente.

### Operaciones en tiempo real (F2-03)

**La jornada manda.** `jornadas_tecnico` (una abierta por técnico, garantizado por índice único) con sus pausas en
`jornada_pausas`. **Sin jornada activa el servidor no acepta ninguna posición**, y la primera vez el técnico acepta
un aviso de qué se registra y para qué (`aviso_aceptado_at`), cuyo texto está en
`operacion_service.AVISO_GEOLOCALIZACION` y en `docs/decisiones_para_validar.md` para revisión legal. La app deja de
reportar cuando se cierra la jornada, cuando la app se cierra y cuando el teléfono se bloquea, porque
`watchPosition` deja de emitir: no hace falta nada más para cumplir §6.8.4.

**Frecuencias** (literales del diseño, las publica `GET /api/operacion/parametros` para que app y pantalla hablen del
mismo número): 30 s en jornada activa, 5 min en pausa y 2 min con batería bajo el 20 % (Battery Status API donde
exista; sin ella se usa el intervalo normal). El servidor no valida frecuencias —manda la app— pero sí el tamaño del
lote (60 posiciones) y la calidad del dato: se descartan las de precisión peor que 500 m, las del futuro y las de
hace más de dos días, cada una con su motivo en la respuesta.

**Posiciones.** `tecnico_posiciones` está **particionada por día** (`acma_crear_particiones_posiciones`, cada
madrugada, con 7 días de adelanto) y vive **90 días**: `acma_purgar_posiciones` suelta las particiones viejas con
DETACH + DROP, el mismo mecanismo de la auditoría de P11a. Es una tabla de solo inserción: no lleva las columnas de
versión de §6.2 capa 1 ni su trigger, porque 50 técnicos a 30 s son 100 filas por minuto. La **hora de llegada y la
de cierre** de cada folio quedan en el historial del folio, que es permanente, así que soltar una partición no borra
lo que el folio necesita.

Al recibir un lote, el servicio actualiza `tecnicos.ultima_posicion`, guarda la posición actual en **Redis con TTL de
2 minutos** y publica un evento por WebSocket. Lo que llegó tarde (guardado sin señal en IndexedDB y enviado al
reconectar) entra al historial marcado como `tardia` y **no mueve** la última posición si es más vieja que la que ya
está: el mapa no da saltos falsos.

**Estatus operativo** (`tecnicos.estatus_operativo`), en este orden: `fuera_de_jornada` sin jornada, `pausa` si la
jornada está en pausa, `sin_senal` si la última posición pasó el umbral de `TECNICO_SIN_SENAL`, `en_servicio` con un
folio en ejecución y `en_ruta` en los demás casos. Lo recalcula cada lote de posiciones y, cada minuto, la tarea
`acma.seguimiento_operacion`, para que el mapa no muestre «en ruta» a quien lleva media hora sin reportar.

**Geocerca de llegada (§6.8.6).** Cuando la posición entra al radio de la UN del folio en camino (150 m, configurable
en `configuracion_prestador` con la clave `operacion.geocerca_radio_m`), la respuesta trae una **sugerencia**: la app
le propone «Confirmar llegada» y la transición la sigue haciendo el técnico. La entrada al radio queda en el
historial del folio como evento `entrada_geocerca`, **informativo** para el SLA de respuesta: no cambia la regla de
P10.

**Detección automática** (evaluadores de P10, cada minuto):
* `TECNICO_TIEMPO_MUERTO` (20 min, radio 50 m): todas las posiciones del periodo dentro del radio, en un punto que
  no es la UN destino de su folio, y no en pausa. Dispara la alerta al despachador, crea un
  `alertas_operacion_seguimiento` y manda **push al técnico** con dos respuestas («Estoy bien» / «Necesito apoyo»).
  A los 10 minutos sin respuesta, `acma.seguimiento_operacion` **escala al Admin prestador**. «Necesito apoyo»
  levanta de inmediato una alerta de prioridad alta al despachador.
* `TECNICO_SIN_SENAL` (15 min): marcador gris con «Sin señal desde HH:MM» y aviso al despachador. **No genera
  emergencia**: el despachador decide.
* `TECNICO_DESVIO_RUTA` sigue en **fase 2 y sin evaluador**, con la nota de que necesita la ruta planeada del bloque
  de optimización de rutas. Su espacio en la pantalla queda preparado (el amarillo del panel de técnicos).
* **Cierre automático de jornada** (`acma.cerrar_jornadas_inactivas`, cada 15 min): jornada sin posiciones ni folios
  en curso en 2 h (configurable) se cierra con `cerrada_por = sistema`.

**Tiempo real.** El gestor de P05 se generalizó: el canal es `chat:{id}` o `operacion:{prestador}`, y
`publicar_canal` / `suscribir_canal` sirven a los dos. Hay **un canal por prestador**, así que las posiciones de un
prestador no llegan al tablero de otro (§6.9.5). `WS /api/operacion/ws` con respaldo `GET /api/operacion/stream`
(SSE), los dos autenticados con `?token=`, reconexión con espera exponencial y el indicador «datos en vivo /
reconectando» en la pantalla.

**Privacidad (§6.9.5).** Las posiciones son del prestador del técnico: el cliente no las ve ni por endpoint ni por
RLS (una prueba lo verifica con el contexto de un Admin UN). El técnico ve su propio recorrido, y consultar el de
alguien queda registrado como acceso a datos sensibles (P11a).

**Mapa.** Leaflet 1.9.4 con react-leaflet 5.0.0 y teselas de **OpenStreetMap** (gratis, sin cuenta) detrás de la
interfaz `ProveedorMapa` de `src/services/mapas.ts`: con `VITE_MAPA_PROVEEDOR=google` y `VITE_MAPA_LLAVE` se cambia
sin tocar la pantalla, y sin llave se queda en OSM para que el mapa nunca aparezca en blanco. El mapa **mueve solo
el marcador que cambió** (los marcadores se guardan por técnico), y si Leaflet falla, un límite de error deja los
paneles funcionando.

- **Hoja «Dónde se ve en el sistema» (Excel, no se edita)**: quedan obsoletas las filas que marcan como «Fase 2» la
  **pantalla de operaciones**, el **mapa en vivo**, el **GPS del técnico** y las alertas **TECNICO_TIEMPO_MUERTO** y
  **TECNICO_SIN_SEÑAL**. Siguen vigentes las de **desvío de ruta**, **ETA por tráfico** y **optimización de rutas**.

### Medidores y planes por uso (F2-04)

**El acumulado es la cifra que manda.** `equipo_medidores` guarda dos números: `valor_actual` es lo que dice el
marcador y `valor_acumulado` es lo que el equipo lleva de verdad. El acumulado se calcula
`acumulado_offset + (valor - ciclo_inicio)`, y un `medidor_cambios` (reinicio del marcador o reemplazo del medidor)
mueve esas dos columnas, así que **el acumulado nunca retrocede**. Los planes por uso miran siempre el acumulado,
nunca el marcador; `medidores_service.acumulado_de()` es la única fuente de esa cuenta.

- **Tablas (0016)**: `tipos_medidor` (catálogo; sin dueño = global del Superadmin, con `requiere_foto` y
  `factor_salto_maximo` por tipo), `equipo_medidores`, `medidor_lecturas`, `medidor_estimaciones`,
  `medidor_cambios`, `eventos_trigger_catalogo` (catálogo **cerrado**, sembrado en la migración, solo lectura para
  la app) y `llaves_api_tenant`. Columnas nuevas: `plan_triggers.clave`, `plan_ejecuciones` y
  `preventivos_calendario` con `plan_trigger_id` y `valor_medidor`, `activo_depreciacion.equipo_medidor_id` y
  `unidades_al_inicio`, `activo_depreciacion_historial` con las unidades del período. El ENUM `origen_preventivo`
  gana `medidor` y `evento`.
- **`medidor_lecturas` es append-only con una excepción**: la medición (valor, método, quién y cuándo) no cambia
  nunca, pero las anómalas quedan `en_revision` y alguien las resuelve, así que el trigger
  `acma_medidor_lectura_inmutable()` deja cambiar solo `estado`, `motivo`, `valor_acumulado`, `revisada_por` y
  `revisada_at` — el patrón de `acma_chat_mensaje_inmutable()` de P05. `acma_api` tampoco tiene privilegio DELETE.
- **`plan_triggers.clave`** (`t1`, `t2`, …) es la identidad estable de cada condición dentro del plan. Antes una
  edición borraba y recreaba los triggers y sus id cambiaban; el `combinado` apunta a otros triggers, así que ahora
  `planes_service._guardar_triggers` hace **upsert por clave** y el id sobrevive. Por dentro se guardan claves
  (`triggers_claves`); la API acepta y devuelve además `triggers_ids`, que es con lo que trabaja la interfaz.
- **`services/triggers_service.py`** resuelve los cuatro tipos nuevos con **un solo predicado**, `cumple()`: todos se
  leen como «desde la última ejecución del plan en este equipo pasó X». Por eso la **evaluación inmediata** (al
  registrar una lectura válida o al ocurrir un evento) y la **nocturna** dan el mismo resultado y no se duplican:
  las dos pasan por el mismo candado, `_folio_abierto()`. `medidor_umbral` es un **hito** (no se repite si
  `equipo_planes.ultimo_valor_medidor` ya lo alcanzó); `medidor_intervalo` se cuenta desde ahí. Una condición que es
  hija de un `combinado` **no dispara por sí sola** (`claves_hijas()`).
- **El folio lo crea el sistema**: `_generar()` fija el contexto RLS de sistema dentro de la misma transacción y lo
  restaura, porque ni el operador que capturó la lectura ni el técnico que cerró el folio pueden escribir `folios`
  del cliente (RLS de P04). Es el patrón del alta de equipos de P08.
- **Reinicio del combinado (§6.9.1)**: sale gratis. Al cerrarse el preventivo, P06 mueve `fecha_ultima_ejecucion` y
  `triggers_service.al_cerrar` mueve `equipo_medidores.valor_ultimo_pm` y `equipo_planes.ultimo_valor_medidor`, que
  son la referencia de **todos** los triggers del plan.
- **Validación de lecturas**: menor que la anterior o salto mayor a N× el incremento diario (N por tipo de medidor,
  default 3) → `en_revision` + `MEDIDOR_LECTURA_ANOMALA`; fecha futura → 422; duplicada (mismo medidor, mismo
  instante del dispositivo y mismo valor) → se devuelve la que ya existía, que es lo que necesitan la cola sin señal
  y la importación para reintentar. El incremento diario con el que se proyecta y se miden los saltos sale, en este
  orden, del promedio **real** medido, de la estimación configurada o del historial (`incremento_diario()`).
- **Estimación**: `acma.ciclo_medidores` (beat 01:30, antes de la generación de las 02:00) escribe una lectura
  `estimado` por día de operación; una lectura real posterior marca las estimadas como `rechazada` («corregida
  por…», no se borran) y recalcula `incremento_real_promedio`, que es el «estimado vs. real» que muestra la ficha.
- **Entradas de lectura**: el técnico por la bandera `lectura_medidor` del motor de formularios (campo `texto`
  numérico o `slider`, con foto opcional u obligatoria del marcador; el gancho está en
  `formularios/servicio.enviar`), el operador por `/api/medidores/operador/equipos` y la cola `registrar_lectura` de
  P05 (los medidores viajan en el paquete de catálogos), la importación por el catálogo `lecturas_medidor` del
  importador de P02 y `POST /api/medidores/lecturas/lote` con **llave de API por cliente** (hasheada, revocable, con
  permiso solo `medidores.lecturas`; la búsqueda de la llave va con contexto de sistema y de ahí en adelante la
  sesión queda en el contexto del cliente). Formato en
  [`docs/integracion/lecturas_medidor.md`](docs/integracion/lecturas_medidor.md).
- **Depreciación por unidades (§6.9.4, ACT-8.3)**: `activos_service.libros_con_unidades` lee del medidor configurado
  las unidades desde `fecha_inicio` y las del período. Sin medidor elegido avisa `MEDIDOR_NO_CONFIGURADO` y usa el
  campo manual de P09; sin vida útil en unidades, `SIN_VIDA_UTIL_EN_UNIDADES`.
- **Alertas**: `MEDIDOR_PROXIMO_PM` pasó a fase 1 con su 10 % literal (se mide contra el intervalo del propio
  trigger, así que «10 %» significa lo mismo en un plan de 500 h que en uno de 10,000 ciclos) y lleva la fecha
  estimada; nuevas `MEDIDOR_LECTURA_ANOMALA` y `MEDIDOR_SIN_LECTURA` (30 días). Las tres se disparan con
  `prestador_id` resuelto por `medidores_service.prestador_responsable`, porque el panel de un usuario del prestador
  solo muestra las de **su** prestador y la lectura la puede capturar el operador del cliente.
- **Endpoints**: `/api/medidores` (tipos, medidores por equipo, lecturas con filtros, registro individual, lote,
  bandeja de revisión, cambios, estimaciones, llaves y la pantalla del operador) y en planes
  `GET /api/planes/eventos-catalogo` y `GET /api/planes/{id}/simulacion`.
- **Frontend**: módulo `medidores` (`/medidores`: bandeja, catálogo, llaves), pestaña «Medidores» de la ficha del
  equipo (`pages/activos/PestanaMedidores.tsx`), `ConstructorTriggers.tsx` (los seis triggers en lenguaje claro, con
  el combinado y la simulación), `/campo/lectura` del operador y la columna de origen del calendario.
- **Seed** (`scripts/seed_medidores.py`): los seis tipos globales de §6.9.2, seis equipos industriales (familia
  «Equipos industriales») con 60 días de lecturas de los cuatro métodos, una anómala en revisión, un reinicio de
  odómetro, cuatro planes nuevos (uno a punto de dispararse) y la línea de producción depreciándose por unidades.
- **A tener presente**: el salto se mide contra el promedio **real** en cuanto hay dos lecturas reales, así que la
  estimación configurada deja de pesar. Es el comportamiento deseado (el uso medido es mejor referencia que el
  supuesto), pero conviene recordarlo al leer una alerta de anomalía. Las decisiones 38 a 42 esperan validación.
- **Hoja «Dónde se ve en el sistema» (Excel, no se edita)**: quedan obsoletas las filas que marcan como «Fase 2» los
  **medidores de activos**, los **planes por medidor, por evento y combinados**, la **depreciación por unidades de
  producción** y la alerta **MEDIDOR_PROXIMO_PM**. Sigue vigente lo que depende de otros bloques: la **criticidad
  automática A/B/C/D**, el **FMEA**, el **MTBF/MTTR** y los **adaptadores de ERP** (la importación de lecturas por
  archivo y por API propia sí existe; lo que no hay es conexión directa a un ERP de terceros).

### ISO 55000 (F2-05)

**La fórmula.** `índice = probabilidad × impacto ÷ 25 × 100`, de 4 a 100. La **probabilidad** es 1–5 y la pone ACMA
con el historial de correctivos cerrados del activo; el **impacto** es 1.00–5.00 y es el promedio ponderado de las
cuatro dimensiones de §6.9.3 que evalúa el cliente. El nivel sale del índice. Un ejemplo completo, el EQ-0001 del
demo: 13 fallas en 12 meses → probabilidad 5; dimensiones 5 operacional, 4 seguridad, 4 económico y 4 imagen con
los pesos 30/35/25/10 → impacto `(150 + 140 + 100 + 40) ÷ 100 = 4.30`; índice `5 × 4.30 ÷ 25 × 100 = 86.00` →
**nivel A**.

**Las escalas elegidas** (todas configuración por cliente, no código):

| Qué | Valor de hoy |
|---|---|
| Pesos de las dimensiones | seguridad 35 %, operacional 30 %, económico 25 %, imagen 10 % (tienen que sumar 100 %, lo garantiza un CHECK) |
| Fronteras de nivel | A ≥ 80, B ≥ 50, C ≥ 20, D debajo de 20 |
| Probabilidad por fallas en 12 meses | 0 → 1 · 1–2 → 2 · 3–5 → 3 · 6–11 → 4 · 12 o más → 5 |
| Impacto económico (propuesta automática) | menos de $5,000 → 1 · hasta $25,000 → 2 · hasta $100,000 → 3 · hasta $500,000 → 4 · más → 5 |
| Historia mínima para usar el historial propio | 6 meses |
| Revisión de la clasificación | cada 12 meses, con aviso a los 30 días de vencida |
| Ventana de efectividad de una mitigación | 6 meses antes contra 6 después, con «sin datos suficientes» antes de 90 días |

**Recalibrar con datos reales.** Estos números son defendibles, pero son un punto de partida, no una verdad: se
eligieron sin historia propia del parque. **La recomendación es revisarlos con seis a doce meses de operación
real**, comparando lo que el cálculo clasificó contra lo que de verdad falló, y ajustando sobre todo la escala de
probabilidad, que es la que más depende del tipo de parque: en equipos de uso intenso doce fallas al año puede ser
lo normal, y entonces la escala quedaría toda en 5, que es como no tener escala. Las ocho preguntas que esto le deja
al negocio están en [`docs/decisiones_para_validar.md`](docs/decisiones_para_validar.md) (43 a 50).

- **Tablas (0017)**: `criticidad_configuracion` (pesos, escalas, rangos e implicaciones activas por cliente),
  `activo_criticidad` (la clasificación vigente, una por equipo, reusando el ENUM `criticidad_activo` de P04),
  `criticidad_evaluaciones` (**append-only**: cada cambio con su motivo, su razón y quién), `activo_modos_falla`
  (del activo **o** genérico del tipo de equipo, nunca de los dos: lo garantiza un CHECK) y
  `activo_riesgo_mitigacion` (la acción, su vínculo según el tipo y su efectividad medida).
- **`equipos.criticidad` sigue siendo el campo que lee el resto del sistema** (la aprobación multinivel de P04, el
  tablero, la ficha). La evaluación lo escribe con contexto de sistema dentro de la misma transacción, como el alta
  de equipos de P08, porque el cliente no puede escribir ese campo por la RLS de P02 y porque la tarea semanal
  evalúa sin usuario. Así la criticidad calculada entra sola a decidir el nivel de aprobación de un folio.
- **El recálculo solo escribe si cambia el nivel.** Si el índice se mueve de 51.60 a 55.00 la fila se actualiza pero
  no se registra una evaluación: ensuciar la traza de auditoría con ruido hace que nadie la lea. Y respeta el nivel
  fijado a mano hasta la próxima revisión.
- **La probabilidad prestada se declara.** Sin historia propia suficiente se usa el promedio del mismo tipo de
  equipo del cliente, después el de toda la plataforma como número anónimo, y si no hay nada, 2.00. En los tres
  casos la fila queda `probabilidad_estimada = true` con su origen, y la pantalla lo dice: un dato prestado que se
  lee como propio es peor que no tenerlo.
- **El FMEA no se escribe en blanco.** `riesgo_service.sugerir()` propone los tipos de falla que el activo ya
  repitió en sus correctivos cerrados, con la causa raíz más frecuente (del catálogo de P03, leída de la respuesta
  del formulario de atención) y la severidad que la operación ya les dio. Quien revisa acepta, edita o descarta, y
  lo aceptado queda marcado `sugerido` para distinguirlo de lo que escribió una persona.
- **Las cuatro implicaciones de §6.9.3 son alerta por defecto y restricción opcional** del cliente
  (`implicaciones_activas_json`). Cinco alertas avisan solas (`CRITICIDAD_REVISION_PENDIENTE`,
  `ACTIVO_CRITICO_SIN_PLAN`, `RESPUESTA_CRITICIDAD_EN_RIESGO` al 80 % del tiempo, `REFACCION_CRITICA_SIN_STOCK` y
  `MITIGACION_VENCIDA`); la del técnico se aplica al asignar. **`RESPUESTA_CRITICIDAD_EN_RIESGO` no toca el SLA ni
  la penalización de P10**: es un reloj paralelo, porque el contrato puede prometer 24 h en un equipo que por su
  criticidad debería atenderse en 4.
- **Cinco reportes de certificación** (`iso_registro`, `iso_matriz`, `iso_modos_falla`, `iso_mejora_continua`,
  `iso_historial`) sin generador nuevo: arman las mismas secciones `{titulo, tipo, columnas, filas}` que ya
  comparten el PDF y el Excel de P10.
- **Hoja «Dónde se ve en el sistema» (Excel, no se edita)**: quedan obsoletas las filas que marcan como «Fase 2» la
  **criticidad automática A/B/C/D**, el **FMEA** y la **matriz de riesgo**. El **MTBF y el MTTR por activo** en la
  ficha siguen pendientes (en el tablero ya están desde P10).

### Rutas y reasignación automática (F2-06)

**Qué resuelve.** Cada mañana hay que decidir quién atiende cada folio y en qué orden, respetando a la vez la
habilidad certificada del técnico, la ventana de horario de la unidad, el SLA del contrato, la criticidad del
activo, la jornada y si el técnico trae la refacción. Es un VRPTW (ruteo de vehículos con ventanas de tiempo) y lo
resuelve **OR-Tools 9.15.6755**, que es una librería de Python: no se contrató ningún proveedor.

**El motor corre en un contenedor, no en el proceso de la API.** `backend/services/rutas/modelo_ortools.py` es
deliberadamente autónomo (solo `ortools` y la librería estándar) para que **el mismo archivo** sirva en proceso y
dentro del contenedor `acma_nuevo_solver` (puerto 8099), que lo monta de solo lectura. El selector
`RUTAS_MOTOR_TRANSPORTE` acepta `auto | en_proceso | sidecar`. En esta máquina queda en `sidecar` por dos razones
concretas, las dos anotadas en el código: **Smart App Control de Windows** bloqueó `_pywrapcp.pyd` al principio
(Code Integrity 3077/3033), y aunque después lo dejó cargar, **OR-Tools revienta con segfault dentro de pytest**,
así que `tests/conftest.py` fija el transporte en `sidecar`. En producción (Linux) `en_proceso` ahorra el salto HTTP.

**La función objetivo, en pesos configurables** (`rutas_configuracion.pesos_json`). Cada peso dice «cuántos minutos
de ruta vale la pena gastar para evitar esto»:

| Peso | Valor de hoy | Qué castiga |
|---|---|---|
| `folio_sin_asignar` | 5,000 | Dejar un folio fuera de la ruta. Es el más alto a propósito: ACMA prefiere una ruta larga a un folio sin atender |
| `sla` | 600 | Entregar un folio con su SLA ya vencido |
| `sin_refaccion` | 400 | Mandar a quien no trae la refacción en su vehículo |
| `criticidad` | 300 | No adelantar un activo crítico (un A pesa el triple que un C) |
| `horas_extra` | 240 | Pasarse de la jornada, por cada hora de más |
| `distancia` | 1 | El costo base, en metros, contra el que compiten los demás |

**Cómo entra cada restricción en el modelo** (lo que no es obvio quedó comentado en el archivo):

- **Habilidad certificada**: `routing.VehicleVar(nodo).SetValues([-1, *permitidos])`. El `-1` va **siempre**,
  porque es el valor que representa «este nodo no se visita»: sin él, un folio que nadie puede atender vuelve
  **todo el modelo** no factible y el plan sale vacío en lugar de salir con ese folio reportado.
- **La dimensión de tiempo está en minutos, no en segundos.** Con segundos, la penalización del SLA competía contra
  la de dejar el folio fuera en otra escala y el plan salía casi vacío.
- **El coeficiente del SLA está acotado**: `tope_sla = max(1, (pesos["folio_sin_asignar"] - 1) // jornada_max)`.
  Sin el tope, un SLA muy vencido costaba más que no visitar el folio y el motor prefería abandonarlo.
- **La criticidad no es una penalización sino una cota**: con factor ≥ 2 (activos A y B) la llegada se acota al
  inicio de su ventana, que es lo que de verdad los adelanta.
- **Las paradas en ejecución son fijas**: entran con `AddDisjunction([indice], penalizacion * 100)`, tan caro que el
  motor nunca las suelta, sin volver el modelo infactible si algo no cuadra.
- **Búsqueda**: `PARALLEL_CHEAPEST_INSERTION` + búsqueda local guiada, con un reintento en `AUTOMATIC` /
  `GREEDY_DESCENT`. `PATH_CHEAPEST_ARC` no encontraba ni una primera solución con muchos nodos opcionales.

**El plan nace en borrador.** Calcular no asigna nada: los técnicos no ven el plan hasta que alguien lo **publica**,
y publicar es lo que escribe la asignación del folio (respetando §6.8.6: primero `reasignado`, después `asignado`).
Mover una parada a mano valida la habilidad igual que al asignar, y la pantalla ofrece **«¿Qué pasa si lo muevo?»**:
una simulación que no escribe nada y contesta en kilómetros y en paradas fuera de ventana.

**Recálculo parcial, no recálculo del día.** Durante la jornada se recalculan solo los folios pendientes del técnico
afectado más los huérfanos, partiendo de dónde está cada uno **ahora**, y nunca lo que ya empezó. Los siete
disparadores de §6.8.2 (`desvio`, `tiempo_muerto`, `sla_en_riesgo`, `incidencia_tecnico`, `folio_nuevo_urgente`,
`reasignacion_forzada`, `manual`) tienen su razón en texto, que es lo que lee el despachador.

**Reasignación automática en dos modos.** Hoy `solo_sugerir`: la propuesta queda pendiente y **nada cambia hasta que
alguien acepta**; vence sola a los 20 minutos porque describe la operación de ese momento. El modo
`aplicar_y_avisar` está implementado y se activa con un selector. Lo aplicado queda en `reasignaciones` con su
`recalculo_id`, así que siempre se puede ver qué movimiento salió de qué recálculo.

**La alerta de desvío (`TECNICO_DESVIO_RUTA`), que quedaba pendiente de F2-03**, queda en fase 1 **y activa por
defecto**: `alertas_service.disparar` respeta la configuración efectiva, así que dejarla inactiva por defecto habría
sido darle evaluador a una alerta que nadie dispara. Con esto **el catálogo se queda sin ninguna alerta de Fase 2**;
el candado que impide activar una alerta sin fuente de datos se quedó en pie (ahora en
`alertas_service.validar_fase`) para la siguiente que se registre. La regla se evalúa de dos maneras según lo
que haya: con el **trazo** del plan publicado se mide la distancia del técnico al corredor de su ruta; sin plan, con
la distancia al **segmento** hacia su siguiente parada. Dispara con más de 500 m fuera del corredor (pasillo de
300 m) durante más de 10 minutos y solo si el tráfico no lo explica. En el tablero pinta la fila **en ámbar y con el
texto «Desvío de ruta»** (no solo color), porque un desvío casi siempre tiene una razón; las demás alertas siguen en
rojo.

**La ETA es para el cliente, y es una hora, no una posición.** `GET /api/operacion/eta` devuelve la hora estimada de
llegada del folio y, si no está en una ruta publicada, lo dice en lugar de inventar una hora. **No expone el GPS del
técnico**: eso se decidió en F2-03 (§6.9.5) y la ETA no lo cambia. Se refresca cada 5 minutos y avisa 15 antes.

**Los tiempos de servicio se miden, no se adivinan**: la **mediana** (`percentile_cont(0.5)`) de los folios cerrados
por tipo de trabajo y tipo de equipo, descartando muestras de más de 8 horas. Con el promedio y sin descarte, un
folio que alguien dejó abierto el fin de semana daba 1,440 minutos y la ruta salía con **una parada por técnico**.
Sin historial, 60 minutos.

**Distancias sin contratar nada.** `ProveedorEstimado` usa la línea recta por un factor de sinuosidad de 1.35 y
velocidades por franja (18 / 28 / 16 / 35 km/h). `ProveedorGoogleRoutes` está escrito y **sin llave devuelve el
estimado diciendo que lo es**. Para activar Google Routes en producción: poner `GOOGLE_ROUTES_API_KEY`, cambiar
`proveedor_distancias` a `google_routes` en la configuración del prestador y fijarle un tope de gasto como el de
WhatsApp de F2-02 (una ruta de 30 paradas pide una matriz grande en cada recálculo). Las medidas se guardan en Redis
y en `distancias_cache`, así que un recálculo no vuelve a pedir lo que ya preguntó.

**Rendimiento (ACT-2.2, medido el 13 de noviembre de 2026).** El tiempo lo fija el presupuesto de cálculo, no el
tamaño del problema: con 50 técnicos y 300 folios coloca **los 300** tanto con 3 segundos (3,610 ms) como con 10
(10,719 ms), y el recálculo parcial termina en **2.5 segundos**. Con 25 técnicos y 150 folios, también los 150. Con
10 técnicos y 50 folios quedan 4 sin asignar, y no es un fallo del motor: nadie del turno tiene certificada esa
habilidad, y el plan lo reporta con ese motivo. El detalle está en
[`docs/rendimiento/resultados.md`](docs/rendimiento/resultados.md).

- **Tablas (0018)**: `mercados` y `mercado_unidades` (la ruta se calcula por mercado), `rutas_configuracion`
  (pesos, jornada, velocidades, umbrales de desvío, modo de reasignación y presupuesto de cálculo),
  `rutas_tiempos_servicio`, `rutas_planes`, `rutas_paradas`, `rutas_trazos`, `rutas_recalculos` y
  `distancias_cache`; más `reasignaciones.recalculo_id`. RLS forzada por `prestador_id` en todas, **y validación de
  multitenancy también en el servicio**, no solo en la base.
- **Los triggers de inmutabilidad no se tocaron en este prompt**, en ninguna forma: ni se desactivaron, ni se
  recrearon, ni se les dio una excepción.
- **Celery**: `calcular-rutas-del-dia` a las 06:00, `refrescar-eta` cada 5 minutos y `expirar-propuestas-ruta` cada
  5 minutos.
- **`scripts/seed_rutas.py` se puede volver a correr** y deja la demostración como el inicio de un día: reusa el
  mercado, refresca las jornadas que llevan más de dos horas abiertas y cierra el plan publicado anterior antes de
  volver a calcular (el servicio no recalcula sobre un plan publicado, y hace bien). En la base de desarrollo hay
  casi cien folios autorizados en las tres UN del mercado, así que el plan coloca lo que cabe en la jornada de los
  técnicos del demo y el resto sale **con su motivo**: eso es lo que hay que leer, no el total.
- Las siete preguntas que esto le deja al negocio están en
  [`docs/decisiones_para_validar.md`](docs/decisiones_para_validar.md) (51 a 57).

### Frontend
- `src/config/modulos.ts` define los 30 módulos con pantalla (27 de Fase 1 + `medidores` de F2-04,
  `iso55000` de F2-05 y `rutas` de F2-06), su prompt y los
  roles que los ven. Desde P10 **todos tienen
  `ruta`**: no queda ninguno con la etiqueta «Disponible en el prompt Pxx».
- Gráficas con Recharts 3.10.1; cada valor va también en texto junto a la gráfica (accesibilidad).
- `src/services/api.ts`: cliente con refresh single-flight y `ErrorAPI`. `useRecurso` para listados.
- Colores del prestador vía variables CSS `--color-primario` / `--color-acento` (`aplicarTema`).
- Dexie (`src/services/db.ts`) solo tiene `metadatos`; P05 agrega tablas offline con nuevas versiones del esquema.

## Clasificación de las decisiones pendientes (P11a, entregable 5)

Las 124 decisiones de la lista siguiente quedaron repartidas en tres grupos.

**1. Resueltas.** La mayoría eran decisiones de implementación que el diseño no definía y que ya están tomadas,
probadas y sin efecto visible para el usuario: no hay nada que preguntar. P11a cerró además estas seis, que sí
estaban abiertas de verdad:

| N.º | Qué estaba abierto | Cómo quedó |
|---|---|---|
| 1 | Vida del JWT: P01 pedía 15 min + 7 días; §6.9.5 pide 8 h (2 h admins) | Las dos cosas: sesión de 8 h (2 h administrativos) con cierre por inactividad a los 30 min, y token de acceso corto que se renueva solo |
| 6 | Retención de `audit_accesos_api` | 90 días las llamadas normales y 1 año los errores 4xx/5xx, purgando con `DETACH`+`DROP` de particiones; tarea diaria a las 03:50 |
| 7 | Refresh token en `localStorage` | Cookie `httpOnly` con ruta `/api/auth`, `SameSite=Strict`, `Secure` en producción y CSRF de doble envío |
| 11 | Pendientes de §6.9.5 sin cubrir | Los cinco cerrados: vencimiento de contraseña a 90 días, aviso al admin por bloqueo de IP, geolocalización en la auditoría de login, llaves de cifrado por dueño para los archivos y TOTP que no se puede reutilizar |
| 12 | Imagen de MinIO en `latest` | Fijada por digest, igual que PostgreSQL; Redis y las bases de las imágenes propias, por versión exacta |
| 74 | WeasyPrint sin librerías nativas en Windows | La imagen de producción las trae, así que en el servidor los PDF salen con el diseño completo; en Windows sigue el generador mínimo |

**2. Requieren validación del negocio: 28 preguntas.** Están en
[`docs/decisiones_para_validar.md`](docs/decisiones_para_validar.md), redactadas para una persona no técnica, con la
opción que eligió el sistema y su efecto. Corresponden a las decisiones **2, 23, 27, 30, 31, 32, 35, 43, 44, 50, 54,
55, 59, 62, 63, 64, 65, 68, 88, 89, 90, 91, 92, 93, 94, 103, 104, 107, 108, 110, 111, 112, 114, 120 y 122** (varias
se agruparon en una sola pregunta), más dos puntos de infraestructura que P11a dejó explícitos: el destino de los
respaldos fuera del servidor y el RPO real.

**3. Fase 2.** Decisiones **26, 36, 46, 72, 95, 101, 102 y 115**: dependen de módulos que el alcance pone en Fase 2
(medidores de activos, OCR y validación del CFDI ante el SAT, adaptadores de ERP, WhatsApp y SMS, criticidad
automática por FMEA, descuento de penalizaciones en el CFDI, ETA y ruta). No hay nada que decidir hasta entonces.

## Reglas de trabajo de la segunda etapa (paso 0)

- La segunda etapa (prompts `F2-xx`) se desarrolla con **todas las integraciones externas en modo simulado o con
  cuentas de prueba gratuitas**: ninguna contratación ni publicación hasta el paso final.
- **Cada prompt cierra con un commit local.** Los trabajos largos se dividen en commits parciales por sección, para
  no perder avance si la sesión se corta.
- **El repositorio remoto queda pendiente hasta que la usuaria lo autorice.** Nada de `git push`, `gh repo create`
  ni configurar remotos; el repositorio vive solo en `C:\Users\lilia\Desktop\acma`. El proyecto anterior
  `Liliana0315/ACMA` no se toca.

## Decisiones pendientes de validación (regla 1)

1. **Vida del JWT:** P01 pide acceso de 15 min + refresh de 7 días; §6.9.5 dice 8 h (2 h admins). Se siguió P01.
2. **MFA obligatorio:** P01 incluye `direccion_prestador` además de los tres roles de §6.9.5. Se siguió P01.
3. **Grupos de UNs:** §6.8.5 define pertenencia N:N (`grupo_un_miembros`) y P01 pide `unidades_negocio.grupo_id`. Se hicieron
   ambos: `grupo_id` es el grupo principal y la tabla N:N la membresía completa.
4. **Permisos de técnico/despachador:** `permisos_tecnico` y `permisos_despachador` guardan el valor base por prestador; se
   crearon además las tablas de grupos y overrides de §6.8.3 (`grupos_tecnicos`, `grupo_tecnico_permisos`, `tecnico_grupo`,
   `tecnico_permisos_override`), sin endpoints hasta P02. `permisos_despachador` admite filas por despachador + cliente (§6.8.3b).
5. **Rangos de umbral de alertas:** el diseño no define mínimos/máximos; se eligieron rangos razonables en la migración.
   `TECNICO_SIN_SEÑAL` se registró como `TECNICO_SIN_SENAL` (sin acentos en identificadores).
6. **`audit_accesos_api`** particionada por mes (el diseño dice por día). Retención 90 días / 1 año pendiente: se hará con
   DROP de particiones (no viola el append-only).
7. **Refresh token en localStorage** (más simple); alternativa más segura: cookie httpOnly + SameSite. Revisar en P11.
8. **Visibilidad de módulos futuros por rol** en el hub: asignación preliminar derivada de §5; se confirma en cada prompt.
9. **Tema para usuarios de tenant:** se usan los colores del primer prestador vigente vinculado al tenant.
10. **Rol `sistema` en RLS** para Celery y scripts, equivalente a superadmin.
11. **Pendientes de §6.9.5 no cubiertos en P01:** vencimiento de contraseña a 90 días para admins (el campo
    `password_actualizado_at` ya existe), notificación al admin por bloqueo de IP (requiere canal de notificaciones, P07),
    geolocalización aproximada en auditoría de login, llaves de cifrado por tenant para Object Storage, protección contra
    repetición del mismo código TOTP dentro de su ventana de 30 s.
12. **Imagen de MinIO** en `latest` (la etiqueta fija elegida no existe en Docker Hub); fijar por digest en P11.
13. **Niveles de severidad: 5, no 3.** §6.3 muestra 3 niveles de ejemplo (Crítico/Urgente/Normal) pero §6.10.1 y §4.1 fijan
    5; se siguen los 5, con clave y orden fijos por prestador (solo nombre, color y tiempos son editables).
14. **`contratos.cobertura`** (`todas_las_un` | `equipos_especificos`, default `todas_las_un`) agregado para la regla de
    contrato activo; el diseño no lo definía.
15. **Tipos de falla solo sobre familias globales**: el prestador define síntomas por familia de plataforma; las familias
    propias de un tenant no admiten tipos de falla del prestador (si hiciera falta, se revisa en P04).
16. **`contrato_sla` conserva el ENUM `nivel_severidad`** además de `nivel_severidad_id`; P10 decide cuál manda.
17. **Importador**: los duplicados contra la base se omiten (no actualizan), salvo `severidades` y `matriz_severidad`, que
    actualizan por clave. Las contraseñas de técnicos importados viajan en el archivo y no se devuelven en la vista previa.
18. **Alerta `MATRIZ_SEVERIDAD_INCOMPLETA`**: umbral 0 (dispara con 1 combinación faltante), destinatario admin_empresa,
    sin repetir mientras haya una sin atender. Solo cuentan tipos de equipo con equipos activos del tenant.
20. **Formularios: `formulario_respuestas` admite `tenant_id` nulo** (respuesta independiente de un usuario del prestador)
    con `prestador_id` del autor; la RLS es «tenant visible o prestador propio». Las evidencias copian ambos dueños.
21. **`resolver`**: `tipo` es el tipo de formulario y `tipo_folio` (correctivo, preventivo…) acota las asignaciones; el
    prompt solo mencionaba `tipo`.
22. **Sellos `al_llegar_seccion` / `por_condicion`**: el servidor fija la hora en que recibe por primera vez un valor del
    cliente para ese campo (guardado parcial), no la hora que manda el cliente.
23. **Compresión máxima de fotos**: se estima la calidad JPEG con la tabla de cuantización (`compresion = 100 − calidad`);
    PNG/WebP no se evalúan. Pendiente validar el umbral default 70 % con fotos reales de los técnicos.
24. **Alerta `GEOLOCALIZACION_FUERA_DE_UN`** pertenece al tenant y al prestador a la vez (la ven despachador, admin
    prestador y el cliente); umbral = metros de exceso sobre el radio del campo (default 0).
25. **Plantillas base con catálogo personalizado**: la plantilla «Cierre de correctivo» referencia un id de catálogo
    ficticio; al clonarla el prestador debe elegir su catálogo «Causa raíz» (el seed ya lo hace en los formularios demo).
26. **Pendientes de Fase 2 detectados**: transcripción de audio real; validación cruzada GPS de fotos vs. formulario
    (§4.3) y mapa del despachador; anotación sobre archivos de imagen cargados (solo fotos por ahora); mesa de control
    no cambia asignaciones; el constructor no reordena secciones por arrastre (solo campos).
19. **Catálogos en lectura para técnico, despachador y mesa de control** (equipos, tipos de falla, familias) para preparar
    P04; el hub muestra el módulo también a admin_un, mesa de control y despachador.

27. **Técnico solo ve sus folios** (cierra la decisión 3 de P01 en ese sentido): asignados a él o capturados por él
    (`crear_folio_en_campo`); también en la RLS de `folios`.
28. **Sin reglas de aprobación (o ninguna aplicable) el folio pasa directo a `autorizado`**; `monto_estimado` nulo se
    evalúa como 0 (Nivel 1 por monto).
29. **Nivel 2 = `supervisor_operadores`** (el documento lo llama "Supervisor regional"); aprueba las UNs de su grupo o
    asignadas en `usuario_un`.
30. **`aprobacion_secuencial`** (política del tenant, default false): §6.8.7 dice que el flujo comienza en el nivel de
    entrada; con la política activa comienza en Nivel 1 y sube hasta el requerido (aprobación en cadena).
31. **Autorizar en revisión con reglas configuradas**: si el despachador/admin prestador resuelve la excepción y el tenant
    tiene reglas aplicables, el folio no pasa a `autorizado` sino que inicia el flujo multinivel (`revision.resuelta`).
32. **Monto estimado** lo fijan Mesa de control, Despachador y Admin prestador en `capturado`/`en_revision`; el documento
    no define quién lo captura.
33. **`folio_duplicado_ref_id` / justificación** solo se guardan cuando hay folio abierto; `respuesta_id` del formulario de
    captura es opcional.
34. **Habilidad requerida al asignar** = `familias_equipo.habilidad_clave` (nuevo campo; si es nulo se compara por nombre de
    familia). El seed mapea Refrigeración → refrigeracion, Climatización → hvac, Iluminación → iluminacion.
35. **`revision_obligatoria_garantia`** vive en `folio_politicas_tenant` y la puede fijar el Admin prestador (el documento
    dice "configurado por el prestador") además del Admin empresa.
36. **`equipos.criticidad`** manual (Fase 1); el cálculo automático de §6.9.3 llega en Fase 2.
37. **Alertas al despachador por `sin_contrato`/`fuera_horario`** se emiten como notificación (stub) y no como alerta del
    catálogo (no existe una clave de diseño para ellas); los triggers quedan en `revision_manual_triggers`.
38. **Comentarios en folios finales**: `folio_estados_historial.evento = comentario` con `estado_anterior = estado_nuevo`.
39. **`folios.tecnico_id` referencia `usuarios.id`** (no `tecnicos.id`), igual que los permisos de técnico; el vehículo se
    copia al historial al asignar porque los usuarios del tenant no leen `tecnicos` (RLS).
40. **`timestamp_dispositivo` como hora real** solo en `transicion`, `enviar_respuesta`, `crear_folio` (`capturado_at`),
    firma y encuesta; la auditoría conserva la hora del servidor. Si el servidor cambió después de esa hora se registra
    un conflicto `client_wins` pero la operación se aplica.
41. **Idempotencia por (usuario, id_cliente)** en `sincronizacion_mutaciones`; para evidencias además por `hash_sha256`
    dentro de la misma respuesta.
42. **Participantes iniciales**: el documento fija «despachador asignado»; como el despachador no existe al capturar,
    entra a operativo/interno con su primera acción (autorizar, asignar, cancelar…). Admin prestador entra a `interno`
    desde el inicio (todos los activos del prestador).
43. **Mensajes de texto en folio cerrado: rechazados** (solo evidencia posterior en imagen, §6.8.3c); el chat de un folio
    cancelado antes de asignar queda archivado y solo superadmin lo audita.
44. **Encuesta**: plazo `plazo_encuesta_horas` = 48 por defecto (configurable por tenant); con NPS ≤ 6 el comentario es
    obligatorio; se puede responder antes del cierre (tras la firma).
45. **Push**: suscripción por `(usuario, endpoint)`; sin claves VAPID el envío solo se registra. El técnico recibe push de
    asignación, autorización y cancelación; el operador de todo cambio de estado.
46. **ETA y ruta** se muestran como «Disponible en Fase 2» en las apps de campo; **biblioteca** y **refacciones** del
    paquete del técnico vienen vacíos hasta Fase 2 / P09.
47. **Caché de API en el service worker**: `NetworkFirst` 8 s para `GET /api/*`; las escrituras nunca se cachean. Las
    lecturas de folios/catálogos para las apps usan además IndexedDB (fuente offline principal).
48. **Política RLS de `folios`** corregida en 0005 (escritura por comando) para que la restricción de lectura del técnico
    aplique también a nivel de BD.
49. **Una sola tabla de calendario** (`preventivos_calendario`) para `calendarios_preventivos` (§6.9.1) y
    `preventivos_calendario` (§7.6): misma información con origen `manual|plan`. `plan_ejecuciones` conserva el histórico
    por plan y equipo.
50. **Preventivos de UN completa** (sin equipo) se programan y publican, pero **no generan folio** hasta asignarles un
    equipo: el folio exige `equipo_id`. La tarea nocturna los reporta como `omitidos`.
51. **Fecha próxima por tiempo fijo** = última ejecución (o fecha base) + intervalo, aunque quede en el pasado: un plan
    atrasado genera su folio en la siguiente corrida y la alerta `PREVENTIVO_VENCIDO_SIN_EJECUTAR` lo marca.
52. **El folio preventivo nace autorizado sin flujo de aprobación** («autorizado al configurar el plan»). La regla de
    aprobación `tipo_trabajo = preventivo` queda para preventivos capturados a mano.
53. **Reprogramación de preventivos ≠ rechazo «reprogramar» de §6.8.7**: aquí el folio no se cancela; se crea una fila
    nueva del calendario ligada a la original y el folio conserva número e historial.
54. **Cancelar un preventivo exige autorización formal** del Admin UN de la UN o del Admin empresa cuando lo pide el
    prestador (validador en el motor de estados); el Admin empresa puede cancelarlo directamente.
55. **Severidad del preventivo**: la del plan si la tiene; si no, el nivel más bajo del prestador (no hay tipo de falla
    para la matriz).
56. **En camino no se reasigna** (la tabla §6.8.6 no tiene `en_camino → reasignado`); solo `asignado` y
    `pendiente_refaccion`. En ejecución está prohibido por diseño.
57. **Reasignación forzada = `reasignado → asignado` en una sola operación** (el estado intermedio queda en el historial);
    la tabla literal se respeta usando al despachador como actor (o `sistema` si actúa el Admin prestador).
58. **Advertencia de refacción siempre presente** hasta P09 («Refacción no verificada»), por lo que toda reasignación
    pide `confirmar_advertencias`. P09 la sustituye por la verificación real del inventario del vehículo.
59. **Umbrales de las alertas nuevas**: vencido 0 días tras fecha + ventana del plan; autorización pendiente 24 h;
    calendario sin publicar desde el día 25 (una vez por mes y vínculo tenant-prestador).
60. **Publicar un mes vacío responde 409** (`MES_VACIO`); volver a publicar actualiza la misma publicación y vuelve a
    notificar.
61. **Origen de los hallazgos**: bandera `genera_hallazgo` por campo del formulario de atención (con condición opcional) y
    marcado de mensajes de chat por técnico/operador/Admin UN/Despachador; también captura manual. El documento no define el
    mecanismo.
62. **Minuta de UN sin actividad no se genera**; la global sí cuando hubo actividad en el tenant; `forzar` la genera vacía.
63. **Ventana de validación vencida → envío automático** marcado `enviada_sin_validacion` (el documento define la ventana, no
    el vencimiento).
64. **«PDF firmado» = SHA-256** guardado en `hash_pdf` y mostrado en el correo, hasta definir firma electrónica.
65. **Minuta sin hallazgos pendientes no vence** (`vence_respuesta_at` NULL); con hallazgos, vence tras `plazo_respuesta_horas`
    y aún admite respuestas tardías (cuentan en la calificación).
66. **Autorizar reparar sin cotización** crea un folio correctivo capturado por el sistema directo a Autorizado, sin flujo
    multinivel: el cliente ya decidió. Lo mismo para «reactivar como folio» y el trabajo coordinado variante A.
67. **Clasificación de no críticos**: el folio queda en `en_revision` con trigger `pendiente_clasificacion` (sin flujo) hasta
    que el Admin UN clasifique; las opciones distintas de «autorizado» cancelan el folio con razón y lo enlazan al módulo
    (como el rechazo de §6.8.7). Solo aplica a folios capturados después de configurar el tenant.
68. **Clasificación tardía**: descuento proporcional a las horas de retraso (`puntos_json.clasificacion_tarde_por_hora`, tope
    `clasificacion_tarde_max`) y bandera `excluir_sla_por_cliente` para P10.
69. **Alertas reutilizadas** del catálogo base (`COTIZACION_SIN_PREPARAR`, `COTIZACION_SIN_RESPUESTA`, `SEGUIMIENTO_SIN_UPDATE`,
    `REPROGRAMACION_FECHA_VENCIDA`, `FOLIO_SIN_CLASIFICAR`) en lugar de duplicarlas con los nombres del prompt.
70. **`aprobacion_decisiones` sigue siendo append-only** salvo por `modulo_destino_id`, que se puede llenar una sola vez.
71. **Reprogramación con fecha tentativa** (clasificación o respuesta de la minuta) nace en `fecha_asignada`; una fecha vencida
    deja `fecha_acordada` NULL y conserva el estado hasta que se registre la nueva.
72. **Fase 2 de notificaciones** (`whatsapp`, `sms`) se registra como `omitida` con motivo, para que la bitácora sea completa.
73. **Notificaciones en línea**: en pruebas y sin Celery se envían en la misma petición (`NOTIFICACIONES_ENVIO_INLINE`); en
    producción las envía Celery.
74. **WeasyPrint** se usa cuando sus librerías nativas están presentes (Linux/contenedor); en esta máquina Windows sin GTK se
    usa el generador PDF mínimo propio (texto y estructura, sin estilos).
75. **Historial del TE en tabla propia** (`te_historial`), no en `modulo_historial`: `modulo_destino` es un ENUM de los cuatro módulos
    de P07 y el TE tiene su propio ciclo.
76. **Folio operativo del TE**: al programar se crea un folio `especial` capturado por el sistema, directo a Autorizado y asignado al
    responsable sin validar la habilidad de familia (el permiso `ejecutar_trabajos_especiales` la sustituye); TE y folio se sincronizan
    en ambos sentidos y la cancelación de uno cancela al otro.
77. **Actor del folio al sincronizar**: si quien mueve el TE no puede ejecutar la transición del folio según §6.8.6 (p. ej. Mesa de
    control cancela un folio asignado), el folio se cancela con un actor del prestador que conserva el id real del usuario; la ejecución
    y el cierre sincronizados usan el actor `sistema`.
78. **Requisitos de cierre del TE**: formulario del TE enviado (vinculado como atención del folio operativo), evidencia fotográfica de
    cierre (`te_evidencias` tipo `cierre` o fotos «después/durante» del folio) y firma del cliente (del folio o del TE).
79. **Cotización retroactiva** disponible para cualquier TE sin cotización vinculada (no solo urgencias); nace `en_preparacion` con el
    monto y queda enlazada en ambas direcciones.
80. **El cliente cancela solo sus TE de urgencia** y solo antes de programarlos; después cancela el prestador con razón.
81. **El TE ordinario no salta de creado a programado**; el de urgencia sí, por el despachador o el Admin prestador, y queda registrado
    `sin_validacion_cliente` en el historial.
82. **Clasificación como instalación de activo** con la bandera `clasifica_instalacion_activo` en campos `si_no`/`radio` del formulario
    de captura o de atención. Desde la atención (el técnico lo identifica en la visita) el folio ya en ejecución continúa y la OC se sigue
    en paralelo; solo el folio capturado se retiene en revisión.
83. **El folio de activo espera la OC como trigger `pendiente_oc_cliente`**: no se evalúa el flujo multinivel ni la clasificación de no
    críticos; con la OC autorizada pasa directo a Autorizado si no quedan otros triggers y, si quedan (p. ej. sin contrato), sigue en
    revisión y se avisa al despachador.
84. **OC rechazada**: `cancelar` cancela el folio con razón; `reprogramar_periodo` crea el registro en Por presupuesto con el período
    destino y cancela el folio (queda enlazado por `derivaciones`).
85. **Alta automática del equipo**: código `ACT-<folio>`, nombre tipo + marca + modelo, contrato vigente del equipo del folio, tipo de
    equipo por id o por nombre; si falta el tipo se usa el del equipo del folio y el activo queda `inactivo` con alerta. Se ejecuta en el
    validador previo al cierre porque el folio cerrado es inmutable.
86. **Roles del TE**: crean Admin prestador, Mesa de control y Despachador; programan Despachador y Admin prestador; cancelan los tres del
    prestador; consultan además supervisores, dirección y los técnicos asignados. En la OC registra solo el Admin empresa; consultan Admin
    UN (sus UNs) y los roles de gestión del prestador.
87. **`TE_URGENCIA_SIN_COTIZACION_RETROACTIVA` es informativa**: umbral en días por tenant y se silencia con la supresión de alertas de P01.
88. **Costo promedio ponderado** para el inventario: cada entrada promedia por cantidad y la salida no altera el costo; el
    consumo del folio se valúa al costo promedio de la ubicación de origen.
89. **Horas de mano de obra**: se toman del formulario de atención si traen `horas_mano_obra` / `horas_trabajadas` /
    `tiempo_horas` / `horas`; si no, se calculan entre `fecha_inicio_atencion` y `fecha_cierre`, con mínimo de 0.5 h. El origen
    queda en `folio_costos.origen_horas` (formulario | calculadas | minimo).
90. **Tarifa de mano de obra**: gana la más específica (tenant + tipo de folio > tenant > tipo de folio > general) y, a igual
    especificidad, la de `vigente_desde` más reciente.
91. **Costo de inactividad del TCO**: horas entre `fecha_falla` y `fecha_cierre` de los folios correctivos y especiales por el
    costo/hora del equipo; si el equipo no lo tiene, el default de su tipo de equipo.
92. **Comprometido del presupuesto**: folios autorizados y sin cerrar con `monto_estimado` capturado dentro del período; no se
    suma al consumido, se muestra aparte y resta del disponible.
93. **TCO** = adquisición + preventivos + correctivos + inactividad − valor residual. Las refacciones se muestran como desglose
    porque ya están dentro de los costos de los folios: sumarlas las contaría dos veces.
94. **Valor residual** = valor en libros del método de depreciación configurado; sin método configurado se usa el costo de
    adquisición.
95. **Unidades de producción** devuelve `REQUIERE_MEDIDORES_FASE_2` y conserva el último valor en libros capturado a mano,
    porque los medidores de activos son Fase 2.
96. **Consumo offline con existencia negativa** (§6.2): se aplican los dos consumos, se registra `SincronizacionConflicto` con
    regla `merge_alerta` y se dispara `STOCK_NEGATIVO`; en línea el consumo se bloquea con 409 `STOCK_INSUFICIENTE`.
97. **El fondo de caja chica nunca queda negativo**: la aprobación del gasto se bloquea con 409 `SALDO_INSUFICIENTE` y el Admin
    prestador debe reponer el fondo primero.
98. **Una sola tabla `presupuestos`** con `un_id` XOR `grupo_id` (CHECK) en lugar de la `presupuestos_grupo` separada de §6.8.5.
99. **Umbrales de presupuesto deduplicados contra `alertas_historial`** (`datos_contexto_json['umbral']`) en vez de una columna
    de control en `presupuestos`: la fila del presupuesto no se actualiza al validar un costo y se evita el choque con la RLS del
    prestador.
100. **`POST /api/activos/{id}/calcular` solo Admin empresa y superadmin**: el recálculo escribe tablas del tenant y el contexto
    del prestador no las puede escribir; la tarea mensual lo hace con el rol sistema.
101. **OCR de facturas y validación del CFDI ante el SAT son stubs de Fase 1**: devuelven `disponible: false` con el motivo y el
    técnico captura los datos a mano; el modelo de datos (`validaciones_cfdi`, `estado_cfdi`) ya existe.
102. **Adaptadores de ERP CONTPAQi y Microsip son Fase 2**: seleccionarlos deja los eventos en `omitido` con su motivo; en Fase 1
    el contador descarga la exportación universal en XML o Excel.
103. **Póliza de reposición de caja chica**: una por fondo y por día, con las 12 columnas literales de §6.5; si no hay gastos
    aprobados sin consolidar, la generación devuelve vacío en lugar de repetir la póliza.
104. **Un solo contrato activo por relación cliente–prestador** (§6.10.1 «contrato único»): el alta y la edición
    rechazan con 409 `CONTRATO_TRASLAPADO` un segundo contrato activo cuyo período se traslape con otro del mismo cliente
    y prestador, porque dejaría indefinido qué SLA y qué horario de servicio aplican. Si por datos heredados hubiera dos,
    `contrato_vigente()` toma el de vigencia más reciente. El seed de P10 convierte el contrato demo a modalidad iguala en
    lugar de agregar uno nuevo.
105. **El SLA se firma en la unidad que elige el cliente** y ACMA guarda además su equivalente en horas: `tiempo_respuesta`
    y `tiempo_resolucion` en la unidad, `*_horas` normalizado, con validación de 1 a 4,320 horas en el esquema y CHECK en
    la tabla.
106. **`contratos.estado` cumple la función del `activo` de §6.10.1**: no se duplicó la bandera.
107. **El contador arranca en la captura del folio**; para los no críticos que el Admin UN clasificó (P07) arranca en la
    autorización, que es la decisión ya tomada en ese prompt.
108. **Respuesta = de `tiempo_inicio` a `asignado`** (§6.10.1 habla de «folio sin asignar»), no a `en_camino`.
109. **La pausa por reasignación** se abre al entrar a `reasignado` y se cierra al volver a `asignado`. El documento dice
    «reanuda cuando el nuevo técnico acepta», pero la aceptación explícita del técnico no existe en Fase 1 y la
    reasignación forzada es inmediata: la pausa dura segundos.
110. **`pendiente_informacion` también pausa el contador** (el folio espera datos del operador, no del prestador). No está
    en la tabla de §6.10.1: queda como decisión pendiente de validación.
111. **La penalización solo mira la resolución** (§6.10.1): monto fijo, o porcentaje sobre `folio_costos.costo_total` de
    P09. Si el costo aún no está calculado, la base es 0 y queda el detalle del cálculo en `penalizacion_detalle_json`.
112. **Un folio con `excluir_sla_por_cliente`** (P07, clasificación tardía del cliente) cuenta como cumplido y no genera
    penalización, con el motivo escrito en el detalle.
113. **El recálculo tras aprobar una exclusión no viola la inmutabilidad del folio**: el trigger de P04 protege `folios`,
    y `folio_sla` no es parte del registro principal del folio cerrado.
114. **Un período de penalizaciones `cerrado` no se recalcula**, aunque después se cierren más folios de ese mes.
115. **El descuento en la factura CFDI es Fase 2**: `penalizaciones_periodo.incluido_en_factura_id` queda nulo y el
    resumen se entrega en PDF y Excel.
116. **La escalación por dueño vive en `alertas_configuracion.parametros.escalacion_de`**, no en el catálogo: el catálogo
    es de la plataforma (§6.9.6) y la RLS impide que el prestador lo escriba. El Superadmin cambia el default del catálogo
    y el Admin prestador la cadena de su prestador.
117. **`REPROGRAMACION_ESCALADA_EMPRESA` no usa `escalacion_de`**: su regla de P07 es «tres reprogramaciones del mismo
    registro», no un tiempo desde otra alerta.
118. **`TECNICO_SIN_SENAL` conserva el nombre sin «ñ»** (regla 4 de identificadores sin acentos) aunque §6.9.6 la escribe
    `TECNICO_SIN_SEÑAL`; el nombre del documento queda como alias.
119. **`app` se agregó como canal** de la configuración de alertas: existe desde P07 en notificaciones y es el canal del
    panel de alertas.
120. **TTL del caché de BI: 120 segundos.** Los tableros se consultan en ráfagas y un minuto de desfase es aceptable para
    indicadores operativos; sin Redis el cálculo simplemente se repite.
121. **Recharts 3.10.1** como librería de gráficas (código abierto, compatible con React 19, la que sugiere ACT-8.1), con
    paleta accesible y **cada valor también en texto** junto a la gráfica.
122. **El Supervisor de operadores** recibe `sin_finanzas: true`, un tablero con solo conteos y SLA en riesgo, y **403** si
    pide un indicador financiero suelto (§5.1 literal).
123. **MTTR** = promedio de horas de la captura al cierre de los correctivos cerrados del período; **MTBF** = promedio de
    horas entre capturas correctivas consecutivas **del mismo equipo** (con menos de dos fallas devuelve 0 con aviso).
124. **Reportes**: tres plantillas (`cliente`, `prestador`, `jornada`); `dia_hora` admite «08:00», «lunes 08:00» y
    «1 08:00», y el día del mes se limita a 28 para que todos los meses tengan envío.

125. **La contraseña se compara fuera del event loop.** argon2 cuesta ~110 ms de CPU por verificación con 4 hilos;
    llamarlo de forma síncrona dentro de una función `async` congelaba todas las peticiones del proceso. Ahora va en
    un hilo y con tope de concurrencia (`HASH_CONCURRENCIA`, 2 por proceso) para que una tanda de inicios de sesión
    no se coma la CPU. **Los parámetros de argon2 no se bajaron**: siguen en el default de argon2-cffi (t=3,
    m=64 MiB, p=4), más fuertes que el mínimo de OWASP.
126. **El pool de conexiones es configurable** (`DB_POOL_SIZE` 15, `DB_POOL_OVERFLOW` 10, `DB_POOL_TIMEOUT` 10 s).
    La regla: `workers × (size + overflow) ≤ max_connections − margen`; `docker-compose.prod.yml` levanta PostgreSQL
    con `max_connections=200` para 4 workers.
127. **El listado de folios sigue leyendo todos los folios del cliente con RLS activa.** La migración 0012 agrega los
    índices por `capturado_at DESC` y sin RLS la consulta baja de 3.4 ms a 0.74 ms, pero con las políticas puestas el
    planeador estima 1 fila donde hay 1,433 y prefiere el `Seq Scan`. Con cientos de miles de folios habrá que
    acotar el listado por ventana de tiempo (queda como decisión a validar, porque cambia lo que ve el usuario).
128. **Las rutas de la API van en su propio bloque `handle` del Caddyfile.** Caddy ejecuta `try_files` antes de
    `reverse_proxy`, así que con un matcher suelto `/api/*` terminaba sirviendo el `index.html` de la PWA. Lo
    encontró el ensayo del paquete de producción.
129. **El directorio del calendario de Celery beat se crea en la imagen con dueño `acma`.** Docker copia el dueño del
    directorio de la imagen al inicializar un volumen vacío; sin eso el volumen quedaba de root y beat no arrancaba
    (`Permission denied`). Si se cambia esa línea del `Dockerfile` hay que borrar el volumen.
130. **El healthcheck del worker usa `CMD-SHELL`.** En la forma exec no hay shell, `$HOSTNAME` llegaba literal y el
    worker salía siempre `unhealthy` aunque estuviera trabajando. Beat tiene el suyo propio (la frescura de su
    calendario), porque el de la imagen pega a `/api/salud` y beat no atiende HTTP.
131. **`seed_produccion.py` valida el correo con las mismas reglas que el login.** Un dominio reservado (`.local`,
    `.test`) creaba un superadmin que nunca podía entrar y el error aparecía hasta el primer día de uso.
132. **`/api/salud` es ligera a propósito** (la usa el healthcheck del contenedor: si Redis se cae, no hay que
    reiniciar la API) y el estado de las dependencias vive en `/api/salud/detalle`, que responde 503 si alguna falla.
    Crear el cliente de MinIO hace E/S de red **síncrona**, así que esa comprobación va en un hilo: en el event loop
    bloqueaba varios segundos y tumbaba por tiempo de espera las otras tres.
133. **El cifrado de archivos se hizo en la aplicación, no con SSE de MinIO.** El sobre AES-256-GCM lleva la llave
    derivada por HKDF para cada dueño y la ruta del objeto firmada, así que un archivo no se puede mover al
    expediente de otro cliente. MinIO SSE-C exige TLS hacia MinIO y SSE-S3 exige el servicio KES: ninguno se puede
    probar sin montar infraestructura extra, y el sobre cumple lo que pide el diseño («llaves por tenant») hoy. Lo
    escrito antes de P11a sigue legible porque el sobre se detecta por su marca.
134. **HSTS solo en producción.** Un HSTS cacheado desde un `localhost` sin TLS deja al navegador exigiendo https en
    todo `localhost` y rompe el desarrollo de cualquier proyecto en esa máquina.
135. **La geolocalización del login es aproximada y opcional.** No se incluye la base GeoLite2 (su licencia exige
    registro y aceptar sus términos): con `GEOIP_BASE` vacío la auditoría anota `geo: null`, y las IP privadas se
    marcan como `red_local`. `services/geoip.py` es la interfaz lista para conectar la base cuando el cliente la
    descargue.
136. **Las seis vulnerabilidades moderadas que quedan en el frontend son de la cadena de construcción**
    (`vite-plugin-pwa` → `workbox-build` → `glob`, `minimatch`, `deepmerge`) y no viajan en el paquete que recibe el
    navegador. El arreglo que propone `npm audit` es *bajar* `vite-plugin-pwa` de 2.x a 1.1.0, un retroceso de
    versión que cambiaría el generador del service worker: no se aplica.
137. **La prueba del ciclo de respaldo y restauración no corre en la suite normal.** Levanta y borra bases y necesita
    `docker compose`: se activa con `ACMA_PRUEBA_RESPALDO=1` y es, en un comando, el ensayo trimestral que pide
    §6.9.5.

138. **Grupo de los módulos nuevos en el menú (F2-01 pedía elegir y anotar):** `capacitacion` queda en
    **Administración** (es expediente del personal, junto a usuarios y catálogos) y `biblioteca` en **Operación**
    (se consulta mientras se atiende el folio). No se creó un grupo «Recursos» para no mover los 27 módulos ya
    acomodados.
139. **La habilidad declarada a mano le gana al curso.** Si el Admin prestador afirmó la habilidad, un curso no se la
    quita ni le recorta la vigencia; si la certificó un curso, al vencer la certificación la habilidad se retira sola.
    El diseño no dice qué pasa cuando las dos fuentes se contradicen.
140. **Qué personal ve el cliente:** los técnicos habilitados en sus unidades y los que atendieron un folio suyo en los
    **últimos 90 días**, con sus certificaciones **aprobadas y vigentes** (nombre, tipo, norma, proveedor y vigencia);
    sin teléfono, sin número de empleado, sin calificaciones y sin constancias. Los 90 días son una elección.
141. **La certificación vencida bloquea la asignación.** `tecnico_habilidades.certificada` pasó a ser requisito duro en
    la captura y en la reasignación: hasta P11a bastaba con que la habilidad estuviera declarada. Se puede asignar
    igual por la vía que ya existía en §6.8.2 (reasignación con razón registrada), y el candidato muestra si lo que
    falta es la habilidad o solo su certificación.
142. **Límites de archivo:** 10 MB la constancia del curso (PDF, JPG, PNG o WebP) y 50 MB el manual (lo anterior más
    MP4 y WebM). El diseño no fija tamaños; estos caben en el sobre cifrado de P11a sin tocar la memoria del servidor.
143. **Un solo contenido de servicio activo por cliente y tipo de equipo.** Si el contrato cambia, se guarda otra
    versión del mismo registro (sube `version`), no un segundo contenido en paralelo.
144. **Descarga automática de manuales: solo con Wi-Fi**, tope de 200 MB por dispositivo y aviso al 80 %. Cuando el
    navegador no dice el tipo de conexión se asume que sí se puede descargar (la alternativa, no descargar nunca, deja
    al técnico sin manuales en sitio); con `saveData` o 2G/3G no descarga.
145. **El enlace del visor dura 5 minutos y reconstruye el contexto RLS desde su token.** Los archivos están cifrados,
    así que los sirve la API y no MinIO; el visor del navegador no manda cabecera de autorización, de ahí el enlace
    firmado.
146. **La suite dependía de la hora del reloj.** El contrato del demo tiene horario de servicio (L-V 08:00-20:00,
    sábado 09:00-14:00, domingo cerrado) y la causa 7 de §6.8.6 lo evalúa con la hora real del servidor: corrida fuera
    de esa ventana, media suite fallaba porque cada folio capturado se iba a `en_revision`. En la base de pruebas
    `conftest` deja los contratos abiertos los siete días; la causa 7 conserva su prueba, que estrecha la ventana y la
    restaura.

147. **El visor de manuales recibe el archivo como `blob:`, no el enlace firmado.** La API manda
    `frame-ancestors 'none'` desde P11a, así que el navegador bloquea cualquier `iframe` apuntado a
    `/api/biblioteca/archivo`. Relajar la cabecera habría deshecho una protección de P11a por una pantalla; el
    enlace firmado se conserva para abrir el manual en otra pestaña, donde no hay marco que valga.

148. **El número de teléfono se guarda cifrado y en claro no aparece en ningún lado.** La columna
    `usuarios.telefono_movil_e164` lleva el envelope de P11a; para reconocer un mensaje entrante se usa un hash con
    el secreto de la instalación, y en pantallas y bitácoras solo se ve la máscara. El diseño pedía «cifrado»: lo
    que es decisión es guardar además el hash (sin él, un «BAJA» obligaría a descifrar a todos los usuarios para
    saber quién escribió).
149. **El consentimiento es por canal y lo da el propio usuario**, no el administrador: nadie activa un número que
    no es suyo. Y exige el teléfono verificado antes, con un código de un solo uso de 6 dígitos (10 minutos, 5
    intentos). El diseño no fijaba el método de verificación.
150. **Las palabras exactas son «BAJA» y «ALTA»** (en mayúsculas o minúsculas, con o sin acentos, por WhatsApp o por
    SMS), con acuse por el mismo canal. El diseño no las nombraba.
151. **El resumen de la minuta por WhatsApp va en un solo parámetro, con los puntos separados por « · ».** Meta no
    acepta saltos de línea dentro de un parámetro de plantilla, así que los cinco puntos no pueden ir en líneas
    separadas sin partir la plantilla en cinco variables (que además Meta no deja mandar vacías). Si al someter la
    plantilla Meta lo rechaza, el cambio es solo del texto de la plantilla.
152. **El enlace del PDF de la minuta dura 60 minutos**, contra los 5 del visor de manuales de F2-01: el manual se
    abre en el momento, la minuta se lee cuando el Admin UN tiene tiempo. Es una elección.
153. **El enlace corto `/l/{codigo}` se resuelve sin sesión.** Son 8 caracteres aleatorios y la respuesta es solo
    una ruta de ACMA; el destino sí exige sesión, salvo el PDF de la minuta, que viaja con su propio enlace firmado.
    La alternativa (pedir sesión para resolverlo) rompía el único caso que importa: abrir el aviso desde el teléfono.
154. **El tope mensual bloquea los avisos no críticos, no todos.** Al llegar al tope se siguen mandando las
    aprobaciones pendientes, el SLA y lo crítico: un tope de gasto no puede dejar sin avisar de algo que cuesta una
    penalización. El diseño pedía «bloqueo al llegar al tope» sin decir si admitía excepciones.
155. **Las plantillas de SMS se escriben sin acentos.** Con acentos el mensaje pasa de GSM-7 (160 caracteres por
    segmento) a UCS-2 (70), y un aviso de dos segmentos cuesta el doble. La vista previa avisa cuando un texto
    editado cruza esa línea.
156. **La plantilla base es de la plataforma y el prestador edita una copia.** Quien edita una plantilla global
    recibe su propia versión en borrador; la base no se toca. Así el prestador puede ajustar el texto para su número
    de Meta sin cambiárselo a los demás, y la plataforma puede corregir la base sin pisar lo que ya aprobaron.
157. **El restablecimiento de contraseña sigue siendo solo por correo.** No hay plantilla de WhatsApp ni de SMS para
    ese evento, a propósito: el canal de recuperación de una cuenta no debe depender de un teléfono que puede estar
    en manos de otra persona.

158. **Las posiciones se guardan 90 días y se sueltan por partición.** El diseño no fija retención para el
    GPS; 90 días es lo mismo que la bitácora de accesos de P11a y alcanza para aclarar un reclamo de servicio. Lo
    permanente es la hora de llegada y de cierre de cada folio, que vive en el historial del folio. **Es una
    decisión de privacidad: conviene que la valide quien lleva el tema de datos personales de empleados.**
159. **Sin jornada abierta no se guarda ni una posición**, y la jornada la abre y la cierra el técnico. El diseño
    pedía que el GPS funcionara «en jornada activa»; la decisión es que el interruptor sea del técnico y no del
    despachador, y que la app no reporte nunca con la jornada cerrada.
160. **La geocerca propone, no decide.** Entrar al radio de 150 m de la unidad no transiciona el folio: le propone
    al técnico confirmar su llegada (§6.8.6 lo pide así). La entrada al radio se guarda como dato informativo del
    SLA de respuesta, sin cambiar la regla de P10, para que después se pueda comparar «entró» contra «confirmó».
161. **El radio de la geocerca (150 m) y el cierre automático de jornada (2 h) viven en `configuracion_prestador`**
    (`operacion.geocerca_radio_m`, `operacion.jornada_cierre_horas`), no en el catálogo de alertas: no son umbrales
    de alerta. Los umbrales de tiempo muerto y sin señal sí salen de la configuración central de P10.
162. **El tiempo muerto exige posiciones del periodo completo.** Si el técnico no reportó, el caso lo cuenta
    `TECNICO_SIN_SENAL`, no el tiempo muerto: sin datos no se puede afirmar que esté detenido. Además pide al menos
    dos posiciones y que la más vieja cubra el 80 % del periodo.
163. **«Sin señal» no genera emergencia** (§6.8.4 lo dice explícito) y tampoco push al técnico: si no tiene red, el
    push no llega, y si lo tiene, el problema es otro. Solo se avisa al despachador, que decide si llama.
164. **Un canal de tiempo real por prestador.** Se consideró un canal por mercado (el despachador ve su mercado),
    pero el filtro por mercado ya lo hace el alcance de P04 al armar el tablero, y un canal por prestador mantiene
    simple la suscripción. Lo que nunca pasa es que un prestador reciba eventos de otro.
165. **El marcador del técnico se mueve, el mapa no se redibuja.** Con 50 técnicos a 30 segundos, volver a dibujar
    todo haría parpadear la pantalla de la oficina; los marcadores se guardan por técnico y solo se mueve el que
    cambió. Si Leaflet falla, los paneles siguen: el tablero sirve sin mapa, pero no sin paneles.
166. **La batería se lee con la Battery Status API donde exista.** Firefox y Safari no la tienen: ahí se usa el
    intervalo normal de 30 s y la columna `bateria_pct` queda vacía. El diseño pedía «donde exista».

167. **El tiempo en el estatus se guarda, no se deduce.** `tecnicos.estatus_operativo_desde` se actualiza en cada
    cambio de estatus. Deducirlo de la jornada o de la última posición daba números que no eran lo que §6.8.4 pide
    ordenar («tiempo en el estatus actual»), y la pantalla mentía con un número creíble, que es lo peor que puede
    hacer.
168. **El WebSocket del tablero vive en `/ws/operacion`, fuera de `/api`.** El proxy del servidor de desarrollo
    solo levanta la conexión en `/ws` (como el chat de P05), así que dejarlo dentro de `/api` lo habría empujado
    siempre al respaldo SSE sin que se notara.
169. **Los planes por uso miran el acumulado, no el marcador.** `valor_acumulado` corrige reinicios y reemplazos con
    `acumulado_offset` y `ciclo_inicio`; el marcador se guarda solo para que la persona reconozca lo que ve en el
    equipo. Sin esto, un odómetro que vuelve a cero borraría la vida del equipo y el intervalo se recalcularía mal.
170. **Una lectura anómala va a revisión, no se rechaza** (decisión 38), y mientras esté en revisión **no mueve el
    medidor ni dispara planes**. La de fecha futura sí se rechaza con 422: no es una duda, es un dato mal capturado.
171. **La lectura duplicada se devuelve, no se vuelve a escribir.** Clave: (medidor, instante del dispositivo,
    valor). Es lo que necesitan la cola sin señal de P05 y un SCADA que reintenta un lote.
172. **`medidor_umbral` es un hito; `medidor_intervalo` es un ciclo** (decisión 40). «A las 500 h» se atiende una vez
    y no vuelve; «cada 10,000 ciclos» se cuenta desde `equipo_planes.ultimo_valor_medidor`.
173. **Una condición hija de un combinado no dispara por sí sola.** Es la diferencia entre «dos reglas» y «una regla
    con dos condiciones»; `triggers_service.claves_hijas()` las excluye de la generación y de la próxima fecha, y la
    pantalla lo dice.
174. **El último PM sin lectura en el folio usa la última válida** (decisión 41), y si no hay ninguna no se mueve
    nada: el plan sigue esperando la primera lectura.
175. **El incremento diario para proyectar y para medir saltos sale primero del promedio real medido**, después de la
    estimación configurada y al final del historial. El uso medido es mejor referencia que el supuesto, pero eso
    hace que la estimación configurada deje de pesar en cuanto hay dos lecturas reales.
176. **La llave de API del cliente solo registra lecturas** (decisión 42): un permiso (`medidores.lecturas`), atada a
    un cliente, hasheada, revocable sin borrarse y con cada uso en la auditoría. Nunca da contexto de plataforma.
177. **El medidor de la depreciación por unidades se elige explícitamente** (`activo_depreciacion.equipo_medidor_id`)
    y tiene que ser del propio equipo. Sin medidor el método calcula igual, con el campo manual de P09, y lo avisa.

## Notas de entorno (esta máquina)

- Python 3.12 instalado con `py install 3.12`; el venv vive en `backend/.venv`.
- asyncpg fijado en 0.31.0: la 0.32 la bloquea el Control de aplicaciones de Windows.
- Node 25 trae un `localStorage` experimental que tapa el de jsdom; `frontend/tests/setup.ts` instala uno en memoria.
- 2026-10-19: Docker Desktop no arrancaba por sockets huérfanos; se renombraron `%LOCALAPPDATA%\Docker\run` y
  `%LOCALAPPDATA%\docker-secrets-engine` (copias `*.viejo-20261019`, se pueden borrar).
- 2026-10-27: mismo problema (`dockerInference`); copias `*.huerfano-20261027-*`, se pueden borrar.
- 2026-11-02: tras reiniciar la maquina, Docker Desktop volvio a quedarse en el arranque del motor; misma correccion (cerrar Docker, `wsl --shutdown`, renombrar las carpetas); copias `*.huerfano-20261102-*`, se pueden borrar.
- 2026-11-06: cuarta vez, al reiniciar Docker para aplicar el `.wslconfig`. El error exacto fue
  `initializing Secrets Engine: ... rename engine.sock engine.sock.stale: The file cannot be accessed by the
  system`, y Docker Desktop se queda en un cuadro de error esperando a una persona (solo ofrece «Quit» y «Reset
  to factory defaults»: **no usar el reset**, borra los volumenes de todos los proyectos). Misma correccion;
  copias `*.huerfano-20261106`, se pueden borrar. El error vive en
  `%LOCALAPPDATA%\Docker\log\host\com.docker.backend.exe.log`, en la linea `GET /error`.
- **2026-11-06 · limites de WSL (paso 0).** Docker se caia porque WSL2 tomaba toda la memoria con los
  contenedores, pytest y los servidores de desarrollo a la vez. `%USERPROFILE%\.wslconfig` fija ahora
  `memory=4GB`, `swap=4GB`, `processors=4` y `autoMemoryReclaim=gradual`. La maquina tiene 7.24 GB y 8 nucleos
  logicos: la mitad de la RAM serian 3 GB, por debajo del minimo de 4 GB, asi que quedan ~3.2 GB para Windows,
  Node y los compiladores del frontend. Comprobado: la VM de WSL ve 3.92 GiB y 4 nucleos (`docker info`).
  Cambiar ese archivo exige cerrar Docker Desktop, `wsl --shutdown` y volver a abrirlo.
- 2026-10-29: con pytest corriendo, `tsc` (typescript-go) se queda sin memoria en esta máquina (7 GB): cerrar los servidores de
  desarrollo viejos y correr `tsc`/vitest cuando pytest termina.
- Zona horaria del horario de servicio: `zoneinfo` + paquete `tzdata` (ya en el venv) porque Windows no trae la base IANA.
- `pywebpush` instalado en el venv (P05); `fake-indexeddb` como devDependency del frontend para probar Dexie en vitest.
- Las pruebas de vitest y pytest se corren por separado: en paralelo con el build, vitest falla por tiempos de espera.
- Las **pruebas de carga** y la suite de pytest no pueden correr a la vez: el generador de carga, la API, PostgreSQL y
  MinIO ya se pelean por los 8 núcleos de esta máquina, y los percentiles salen inservibles. Entre dos corridas
  idénticas el p95 va de 6.1 a 8.3 s: el número a comprometer se mide en el servidor, con el generador en otra máquina.
- Los guiones `.sh` se prueban en Git Bash con `MSYS2_ARG_CONV_EXCL="/tmp"`: sin eso, MSYS convierte las rutas del
  CONTENEDOR (`/tmp/...`) a rutas de Windows y `docker cp` falla. En Linux no hace falta.
- `pip-audit` y `locust` quedaron en `requirements.txt` marcados como herramientas locales; el `Dockerfile` de
  producción los excluye al instalar.
- P07: `aiosmtplib`, `aiosmtpd` y `weasyprint` en el venv. WeasyPrint no carga en esta máquina (faltan GTK/Pango: «cannot load
  library libgobject-2.0-0»); `services/pdf.py` cae al generador mínimo. Para PDF con estilos instalar el runtime GTK3 o
  ejecutar en Linux. vitest corre los archivos en serie (`fileParallelism: false`, 30 s por prueba).
