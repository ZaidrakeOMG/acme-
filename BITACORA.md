# BITÁCORA — ACMA (desarrollo nuevo)

Registro por fecha de lo realizado en cada prompt.

## 2026-11-11 · F2-05 ISO 55000: criticidad de activos y gestión del riesgo

El bloque que cierra §6.9.3. Hasta hoy la criticidad de un activo era un campo que alguien escribía a mano en la
ficha; ahora **se calcula**, se explica, se revisa y deja evidencia. Migración `0017` con cinco tablas, de las
cuales `criticidad_evaluaciones` es append-only porque es justamente la que lee una auditoría.

**La fórmula, en una línea:** `índice = probabilidad × impacto ÷ 25 × 100`, y el nivel sale del índice (A ≥ 80,
B ≥ 50, C ≥ 20, D debajo). La probabilidad la pone ACMA con el historial de correctivos cerrados del equipo; el
impacto lo evalúa el cliente con las cuatro dimensiones de §6.9.3 y sus pesos (seguridad 35 %, operacional 30 %,
económico 25 %, imagen 10 %). El EQ-0001 del demo: 13 fallas en doce meses → probabilidad 5; dimensiones 5/4/4/4 →
impacto 4.30; índice 86.00 → **A**.

**Por qué el reparto importa.** La probabilidad no la puede capturar una persona: es un hecho que ya está en los
folios, y dejarla a criterio volvería el índice una opinión con decimales. El impacto sí lo tiene que evaluar el
cliente, porque solo él sabe si perder ese equipo le cierra la sucursal. Así el número tiene una mitad medida y una
mitad declarada, y la pantalla dice cuál es cuál: un auditor que pregunta «¿de dónde salió este 86?» ve el desglose
dimensión por dimensión con su peso y su aporte.

**Las escalas son configuración, no código**, y están puestas para moverse: los pesos (con un CHECK que exige que
sumen 100 %, porque si no suman el índice deja de significar lo que dice), las fronteras de nivel, la escala de
fallas y el impacto económico. En `CONTEXTO.md` quedan los valores de hoy y la **recomendación de recalibrarlos con
seis a doce meses de operación real**: se eligieron sin historia del parque, y la escala de probabilidad es la que
más depende del tipo de equipo. Las ocho preguntas que esto le deja al negocio quedaron en
`docs/decisiones_para_validar.md` (43 a 50).

Cuatro decisiones de diseño que salieron de hacerlo:

- **El recálculo solo escribe si cambia el nivel.** La tarea semanal recalcula con el historial nuevo, pero si el
  índice se mueve de 51.60 a 55.00 actualiza la fila y no registra nada: una traza de auditoría llena de ruido no la
  lee nadie. Y respeta el nivel fijado a mano hasta la próxima revisión, que es lo que hace útil al ajuste manual.
- **La probabilidad prestada se declara.** Un activo sin historia suficiente toma el promedio del mismo tipo de
  equipo del cliente, después el de toda la plataforma como número anónimo (nunca se dice de quién salió), y si no
  hay nada, 2.00. En los tres casos la evaluación queda marcada como estimada: un dato prestado que se lee como
  propio es peor que no tenerlo.
- **El FMEA no se escribe en blanco.** ACMA propone los modos de falla que el activo ya repitió, con la causa raíz
  más frecuente que los técnicos registraron en el formulario de cierre (P03) y la severidad que la operación ya les
  dio. Lo aceptado queda marcado `sugerido`, separado de lo que escribió una persona.
- **Las exigencias de cada nivel avisan antes de bloquear.** §6.9.3 dice que un activo A *tiene* plan obligatorio,
  respuesta en 4 horas, técnico especialista y refacción en inventario. ACMA lo aplica como alerta y cada cliente
  puede volver restricción las que quiera: un cálculo nuevo que bloquea la operación el primer día se termina
  apagando entero. Y el aviso de respuesta **no toca el SLA del contrato**: son dos relojes a propósito, porque el
  contrato puede prometer 24 h en un equipo que debería atenderse en 4.

**Dos defectos propios que encontraron las pruebas.** El primero: `_meses_de_historia` medía la observación desde el
primer folio del equipo, así que un activo instalado en 2024 con una sola falla reciente parecía nuevo y tomaba la
probabilidad prestada del tipo de equipo en lugar de su propio historial; ahora un activo sin un solo folio sigue
dando 0 (no se ha observado nada), pero con folios la observación se cuenta desde lo más antiguo que ACMA sabe de
él. El segundo: la implicación «técnico certificado» activada como restricción **no restringía nada**, porque la
levantaba la razón del permiso `asignar_tecnico_sin_habilidad` y sin esa razón la asignación ya se había frenado
antes; ese permiso dispensa la habilidad del tipo de falla, no la certificación que pide la criticidad, así que
ahora solo el Superadmin la pasa.

**El seed demo deja los cuatro niveles saliendo del cálculo** (2 A, 2 B, 4 C y 4 D, con EQ-0001 crítico con plan y
EQ-0002 crítico sin plan, que es el caso que la alerta debe cazar). Para eso completa el historial de fallas de cada
equipo hasta la banda de probabilidad que le toca, **contando lo que ya le dejaron los otros seeds**: con cantidades
fijas la demo cambiaba de resultado según cuántos folios hubiera generado antes el seed base.

**Una reparación de la base de desarrollo que no estaba en el prompt.** Con todo verde, el demo seguía mostrando
solo A, B y C. No era la fórmula: el histórico sintético opcional de P10 se había generado cuando el cliente demo
tenía doce equipos, y hoy tiene 419, así que sus 1,200 folios estaban apilados en esos doce con 52 a 81 fallas al
año cada uno. Con esa densidad la probabilidad de §6.9.3 sale 5 para todos y el nivel D es inalcanzable. Con la
autorización de la usuaria se repartieron entre los equipos de sus tres UNs —conservando número, costo, SLA, fechas
y UN, así que los tableros no se movieron— desactivando solo el trigger de inmutabilidad del folio cerrado dentro de
una transacción y volviéndolo a activar, con el mapeo previo respaldado. Después se completó el historial de los
doce hasta su banda y se reevaluaron: **2 A, 2 B, 4 C y 4 D**. La lección quedó en el encabezado de
`seed_historico`: ese seed va al final, cuando el parque ya está cargado, porque reparte entre los equipos que
existen en ese momento.

Cerró con 665 pytest con los servidores apagados (37:28), 150 vitest, `tsc --noEmit` y
`npm run build` en verde. 77 pruebas nuevas de backend en seis archivos y 13 de frontend.

## 2026-11-11 · F2-04 Medidores de activos y planes de mantenimiento por uso

El bloque que cierra §6.9.1 y §6.9.2: ahora un plan puede dispararse por el **uso real** del equipo y no solo por el
calendario. Migración `0016`, las cuatro tablas literales de §6.9.2 más `medidor_cambios`, el catálogo cerrado de
eventos y las llaves de API del cliente.

**La idea que ordena todo el bloque:** un medidor tiene dos números. `valor_actual` es lo que dice el marcador y
`valor_acumulado` es lo que el equipo lleva de verdad. Cuando el marcador da la vuelta (99,999 → 0) o cuando se
cambia el medidor físico, se registra el cambio y el acumulado **sigue su cuenta**. Los planes miran el acumulado,
nunca el marcador; sin eso, un odómetro que se reinicia borraría media vida del equipo y el mantenimiento por
intervalo se volvería loco.

**Los cuatro triggers que faltaban** (`medidor_umbral`, `medidor_intervalo`, `evento`, `combinado`) se resuelven con
un solo predicado: «desde la última ejecución del plan en este equipo, ¿pasó X?». Los cinco eventos del catálogo
cerrado también se leen así, y por eso la evaluación **inmediata** (al entrar una lectura, al cerrarse un correctivo
grave) y la **nocturna** dan el mismo resultado sin duplicar folios: las dos pasan por el mismo candado, «no hay
folio abierto de este plan en este equipo».

Tres cosas que salieron de hacerlo y no estaban en el prompt:

- **`plan_triggers` necesitaba una `clave`.** El trigger combinado apunta a otros triggers del plan, pero una
  edición los borraba y los recreaba, así que sus id cambiaban: el combinado se quedaba apuntando a nada. Ahora cada
  condición tiene `t1`, `t2`… estable y la edición hace upsert por clave. Por fuera la API sigue hablando de
  `triggers_ids`, que es lo que maneja la interfaz.
- **El folio preventivo lo tiene que crear el sistema.** La lectura la captura el operador del cliente y el cierre
  del correctivo lo hace el técnico del prestador; ninguno de los dos puede escribir `folios` por la RLS de P04. La
  generación fija el contexto de sistema dentro de la misma transacción y lo restaura, como el alta de equipos de
  P08.
- **Las alertas necesitaban dueño.** El panel de un usuario del prestador solo muestra las alertas de **su**
  prestador, y estas las puede disparar una lectura capturada por el cliente. Se resuelve el prestador que atiende a
  ese cliente al disparar; con varios vinculados se usa el primero, porque `alertas_historial` guarda uno solo.

**Reglas que elegí donde el diseño no las fijaba** (las cinco están en `docs/decisiones_para_validar.md`, 38 a 42):
una lectura que retrocede o que salta más de 3× el uso diario va a **revisión**, no se rechaza (el marcador pudo
reiniciarse y eso lo sabe la persona); la de fecha futura sí se rechaza; la duplicada se devuelve tal cual, que es lo
que necesitan la cola sin señal y el SCADA para reintentar; `medidor_umbral` es un **hito** y no se repite tras
atenderse; y si el folio del preventivo no trajo lectura, el último PM se fija con la última válida.

Demo sembrada: seis equipos industriales con 60 días de lecturas de los cuatro métodos, una lectura anómala del
motor esperando revisión, un odómetro que dio la vuelta a los 1,000 km y cuatro planes nuevos con los ejemplos
literales del documento. El del compresor está **a 20 h de dispararse**, así que `MEDIDOR_PROXIMO_PM` ya avisa con
la fecha estimada.

**588 pytest** en verde con los servidores apagados (28:45), 1 saltado a propósito, y **137 vitest** con `tsc` y
`npm run build` limpios. De la primera corrida completa salieron dos fallas, las dos de las pruebas guardián de
P11a y las dos legítimas: `test_acceso_cruzado` exigió declarar de dónde sacar un `medidor_id` real para barrer la
ruta nueva con usuarios ajenos, y `test_permisos_roles` acusó que el catálogo de alertas pasó de 62 a 64. En la
corrida completa de vitest, `biblioteca.test.tsx` falló una vez por tiempo y pasó sola y en la repetición: es la
flaquera de tiempos que ya está anotada en las notas de entorno, no algo que haya tocado este bloque.

## 2026-11-11 · Tres detalles del tablero vistos en el navegador

Revisando `/operaciones` con el despachador demo, contra la base de desarrollo:

- **La hora de las alertas salía en UTC.** El feed decía «Sin señal desde 15:07» mientras el renglón de al lado,
  que la arma el navegador, decía «9:07 a.m.»: seis horas de diferencia en la misma pantalla, y el mismo texto se
  iba en el aviso al despachador (y de ahí al WhatsApp). `operacion_service.hora_local()` formatea en la zona de
  la operación y el evaluador la usa; la prueba de «sin señal» ahora compara contra la hora local esperada.
- **La alerta de tiempo muerto no decía nada debajo del nombre.** El feed pinta `datos.etiqueta` y esa alerta no
  la traía: solo se leía «Técnico detenido · Tadeo Técnico». Ahora lleva «Sin moverse desde las HH:MM».
- **«X min en este estatus» mentía con horas de más** después de resembrar: el seed escribía `estatus_operativo`
  sin tocar `estatus_operativo_desde`, así que se quedaba la marca de la siembra anterior. El producto está bien
  —la marca se fija cuando el estatus cambia—; era el seed. Ahora la fija con el momento del guion.

Verificado en el navegador después de resembrar: Tania «sin señal» hace 21 min, Tomás «en servicio» hace 25 min,
Tadeo «en ruta» con su alerta de detenido, y las dos alertas con la hora de la gente.

## 2026-11-11 · Tablero coherente y una decisión nueva (37)

Al volver a encender todo (la máquina se reinició y se quedaron solo los contenedores) y resembrar la demo, el
técnico «en ruta» aparecía **en servicio** aunque su marcador iba por la avenida: el estatus lo manda el folio
—`en_servicio` con un folio en ejecución— y no la distancia. La regla está así por diseño y es la que documenta
CONTEXTO.md; lo que no cuadraba era el guion del seed, que lo mandaba de Polanco a Coyoacán mientras su folio en
ejecución estaba en la Sucursal Centro, al otro lado de la ciudad.

- `seed_operacion.py`: el guion «ruta» ahora lo lleva **hacia la unidad de su propio folio** y lo deja a ~1.6 km,
  fuera de la geocerca: el mapa y el folio cuentan lo mismo.
- **Decisión 37** en `docs/decisiones_para_validar.md`: ¿«en servicio» debería exigir estar dentro de la geocerca
  de la unidad? Hoy no la exige, y el caso en que se separa es el técnico que termina y se va **sin cerrar el
  folio**: sigue pintado «en servicio» mientras ya va manejando. No lo cambié por mi cuenta porque mueve los
  conteos del tablero y el tiempo atribuido a cada estatus.

Demo verificada después de resembrar: Tomás en servicio a 16 m de su unidad, Teresa en servicio llegando a la suya
a 1.6 km, Tadeo con **TECNICO_TIEMPO_MUERTO** y Tania con **TECNICO_SIN_SENAL**.

## 2026-11-10 · Arreglo a los datos demo de operaciones (`seed_operacion.py`)

Al dejar el tablero listo para la revisión, los cuatro casos que el seed promete no se veían:

- **El técnico detenido salía «sin señal».** Sus posiciones terminaban 26 minutos antes de la hora de la siembra,
  y el evaluador de tiempo muerto mira los últimos 20 minutos: sin datos en esa ventana no hay nada que declarar
  detenido. Ahora los puntos llegan hasta la hora de la siembra, con los 25 minutos quieto completos.
- **El técnico «en servicio» disparaba un tiempo muerto falso.** El seed lo plantaba en la Sucursal Centro, pero
  `seed_dev` le había asignado un folio de la Sucursal Polanco: quieto 25 minutos a 6.5 km de su destino, el
  evaluador tenía razón en alertar. Ahora el seed lo planta en la unidad **de su propio folio en curso** (lo
  consulta en la base) y llega desde la unidad más lejana, así que la exención de la geocerca se ve funcionando.

Las pruebas no lo detectaron porque los tests de F2-03 arman sus propias jornadas y posiciones; esto era solo de
los datos de demostración. Verificado después de resembrar: Tomás **en servicio** a 19 m de su unidad y sin alerta,
Teresa **en ruta** sin alerta, Tadeo con **TECNICO_TIEMPO_MUERTO** y Tania con **TECNICO_SIN_SENAL**.

Para resembrar hay que cerrar primero las jornadas abiertas (el seed es idempotente a propósito).

## 2026-11-10 · Arreglo al encender los servidores (worker de Celery)

Al dejar ACMA encendido para la revisión, el log del worker mostró cinco `Fallo al enviar la notificación` con
`RuntimeError: Event loop is closed`. No era de F2-02 ni de F2-03: el worker corre cada tarea con `asyncio.run`,
o sea un *event loop* nuevo por tarea, y `push_service.enviar_a_usuarios` abre su sesión de sistema con
`core.db.nueva_sesion`, que usa el **engine con pool** de la API. La segunda tarea de la corrida reusaba una
conexión del loop ya cerrado y el envío se caía; lo probé fuera del worker: tarea 1 bien, tarea 2
`AttributeError: 'NoneType' object has no attribute 'send'`, tarea 3 bien otra vez (se perdía más o menos una de
cada dos). Afecta a todo lo que notifica desde background, incluido el push de tiempo muerto de F2-03.

- `core/db.py`: `reconstruir_sin_pool()` rehace el engine, la réplica de lectura y la fábrica de sesiones sin pool.
- `workers/celery_app.py`: se llama desde la señal `celeryd_init`, así que **solo aplica dentro del worker**; la API
  conserva el pool afinado en P11a (10+10 conexiones para 70 usuarios concurrentes).

Verificado: el engine del worker queda en `NullPool` y el de la API en `AsyncAdaptedQueuePool`; tres tareas
seguidas que pasan por `enviar_a_usuarios` terminan bien, y el worker reiniciado lleva 0 errores.
**Sin prueba automática**: `tests/conftest.py` fija `DB_POOL_NULO=true`, así que la suite nunca ejercita el camino
con pool y un test de esto tendría que rehacer el engine global a media corrida. Queda anotado como pendiente.

## 2026-11-10 · F2-03 — Pantalla de operaciones en tiempo real

Segundo bloque prioritario de Dirección, ejecutado enseguida de F2-02. Commits locales por backend y frontend.
**Sin contratar nada:** el mapa usa OpenStreetMap con Leaflet, gratis y sin cuenta, detrás de una interfaz de
proveedor para poder cambiar a Google Maps en el paso final.

### Lo que ahora se ve en vivo

- **Migración `0015_operaciones_tiempo_real.py`**: `jornadas_tecnico` (una abierta por técnico, por índice único),
  `jornada_pausas`, `tecnico_posiciones` **particionada por día** con índice espacial, y
  `alertas_operacion_seguimiento` para el push al técnico, su respuesta y la escalación; más la última posición, la
  precisión, la batería y el `estatus_operativo` en la ficha del técnico. RLS forzada en todas.
- **Jornada del técnico** desde «Mis folios»: iniciar, pausar (comida, trámite, otro), reanudar y cerrar, con el
  aviso de qué se registra la primera vez y su aceptación guardada. **Sin jornada no se registra ninguna posición.**
- **Envío de posición** con las frecuencias del diseño (30 s en jornada, 5 min en pausa, 2 min con batería baja),
  en lotes pequeños; sin señal se guardan en IndexedDB (Dexie v4) y salen al reconectar marcadas como tardías, sin
  mover el mapa hacia atrás. El servidor valida el lote y la calidad del dato, guarda la posición actual en Redis
  con TTL de 2 minutos y publica el evento al tablero del prestador del técnico, nunca a otro.
- **Estatus automático**: en servicio, en ruta, en pausa, sin señal o fuera de jornada, recalculado en cada lote y
  cada minuto por el worker.
- **Geocerca de llegada**: al entrar al radio de 150 m de la unidad del folio en camino, la app propone confirmar
  la llegada —no transiciona sola— y la entrada queda en el historial del folio como dato informativo del SLA.
- **Detección automática**: tiempo muerto (20 min quieto en 50 m fuera de su destino) con alerta al despachador,
  push al técnico con «Estoy bien» / «Necesito apoyo» y escalación al Admin prestador a los 10 minutos sin
  respuesta; sin señal (15 min) con marcador gris y aviso, **sin emergencia automática**. El desvío de ruta sigue
  en Fase 2, sin evaluador, esperando el bloque de optimización de rutas.
- **Cierre automático** de la jornada que el técnico olvidó cerrar (2 h sin posiciones ni folios en curso).
- **Tablero** (`/operaciones`) para Despachador, Admin prestador, Mesa de control (lectura), Dirección y
  Superadmin: mapa en vivo con un marcador por técnico —que se mueve solo él, sin redibujar el mapa— y las unidades
  con folios activos; panel de técnicos ordenable con su estatus en texto; panel de folios del día con el contador
  regresivo del SLA de P10; feed de alertas con acción directa (ver en el mapa, llamar, abrir el folio, reasignar);
  y la barra de indicadores de jornada de P10, en vivo. WebSocket con respaldo SSE e indicador de «datos en vivo /
  reconectando».
- **Privacidad**: las posiciones son del prestador del técnico; el cliente no las ve ni por API ni por RLS. El
  técnico consulta su propio recorrido y mirar el de alguien queda en la bitácora de accesos sensibles.
- **Demostración sin salir a la calle**: `scripts/seed_operacion.py` deja a los cuatro técnicos demo con jornada y
  recorrido de la última hora (uno en servicio, uno en ruta, uno detenido 25 min y uno sin señal) y
  `scripts/simular_jornada.py` los mueve en vivo por el mapa.

**Pruebas:** 531 pytest (39 nuevas de F2-03, con los servidores apagados) y
131 vitest (8 nuevos); `tsc --noEmit` y `npm run build` en verde. Carga de
posiciones: 71 usuarios durante 90 s con 3 workers: **222 posiciones por minuto sin una sola falla** (el doble del requisito de §6.8.4), con mediana de 960 ms. El detalle y lo que se puede y no se puede afirmar de los percentiles están en [`docs/rendimiento/resultados.md`](docs/rendimiento/resultados.md).

### Revisión en el navegador

Las dos pantallas nuevas se recorrieron en la app real contra la base de desarrollo (Admin prestador, Despachador y
técnico). Lo que se encontró ahí y no en las pruebas:

- **«Tiempo en el estatus actual» medía la jornada, no el estatus.** §6.8.4 pide ordenar por ese tiempo y la
  pantalla mostraba «219 min» para un técnico que acababa de quedarse sin señal. Se agregó
  `tecnicos.estatus_operativo_desde`, que el servicio actualiza en cada cambio, y el panel lo lee en horas y
  minutos.
- **El feed de alertas enseñaba la clave cruda** (`SLA_INCUMPLIDO_ESCALADO_DIRECCION`). Ahora el tablero manda el
  nombre del catálogo de alertas y la pantalla lo muestra en palabras.
- **«Marcar atendida» era un enlace a otra pantalla.** §6.8.4 pide acción directa: ahora atiende la alerta ahí
  mismo y refresca el feed.
- **El panel decía «Folios del día»** y traía además los activos de días anteriores, que sí deben salir (un folio
  abierto de ayer es justo lo que el despachador necesita ver). Se renombró a «Folios activos y del día».
- **En Mensajería, un fallo al cargar se veía igual que «sin configurar»**, y el botón de crear la configuración
  habría sobreescrito la que sí existe, dejando los dos canales apagados. Ahora la pantalla distingue «cargando»
  de «no hay configuración».
- El costo del mes se mostraba con cuatro decimales (`9.0000 MXN`); las tarifas por mensaje sí los llevan, el
  total del mes no.

**Incidencias resueltas:** la prueba de P10 que usaba `TECNICO_TIEMPO_MUERTO` como ejemplo de alerta de Fase 2 tuvo
que cambiar de ejemplo, porque ahora está activa; el gestor de tiempo real de P05, escrito solo para el chat, se
generalizó a canales con tema (`chat:` / `operacion:`) sin tocar el chat; el WebSocket del tablero se movió a
`/ws/operacion` porque el proxy del servidor de desarrollo solo levanta la conexión en `/ws`; y las pruebas no
podían limpiar posiciones con DELETE, lo que destapó que `tecnico_posiciones` es append-only incluso para el dueño
del esquema (ahora hay una prueba que lo afirma).

## 2026-11-10 · F2-02 — Notificaciones por WhatsApp y SMS

Segundo bloque de la segunda etapa, primero de los dos prioritarios de Dirección. Commits locales por backend y
frontend. **Nada se contrató:** el canal funciona en modo simulado y la guía para las cuentas gratuitas de Meta y
Twilio quedó escrita para que la usuaria cargue sus credenciales cuando quiera.

### Lo que ahora puede salir por WhatsApp y SMS

- **Migración `0014_whatsapp_sms.py`** con cuatro tablas (`mensajeria_plantillas`, `mensajeria_configuracion`,
  `mensajeria_envios`, `mensajeria_respuestas`), RLS forzada en todas, y las columnas de teléfono, verificación y
  consentimiento en `usuarios`. El número se guarda **cifrado** con el sobre de P11a, con su hash (para reconocer
  un mensaje entrante sin descifrar a nadie) y su máscara `+52 871 ••• ••34`, que es lo único que se ve.
- **Capa de proveedores** (`services/mensajeria/`) detrás de una interfaz: `stub` (el de desarrollo: guarda el
  mensaje renderizado y una vista previa, simula entrega y lectura, y acepta fallas programadas para probar los
  caminos de error), `meta_cloud` (WhatsApp Cloud API) y `twilio` (SMS y, si se prefiere, WhatsApp). El modo se
  elige con `WHATSAPP_MODO` y `SMS_MODO`, igual que el correo en P07; sin credenciales se usa el simulado y queda
  en el log, para que una variable mal escrita no deje a nadie sin aviso.
- **`notificar()` ya no omite nada por «canal Fase 2»**: resuelve el canal con la preferencia del usuario, la
  configuración del tenant o del prestador, el consentimiento y el teléfono verificado, el horario de silencio
  (salvo lo crítico) y el tope mensual. Cuando no puede salir, **el aviso cae al siguiente canal** y el motivo
  queda escrito en la notificación y en la bitácora.
- **22 plantillas por canal** en español, categoría *utility*, con variables posicionales y botón a la pantalla
  exacta de ACMA. El texto vive en el código y los seeds lo sincronizan; la base es de la plataforma y el Admin
  prestador edita una copia propia, que vuelve a borrador porque Meta tiene que aprobarla otra vez. Se exporta en el
  formato que pide Meta con un botón.
- **La minuta del día por WhatsApp (§7.5)**: resumen de máximo 5 puntos con lo más crítico y botón al PDF completo
  con enlace firmado de 60 minutos. Sin nada crítico, dice «sin pendientes críticos».
- **Enlace corto propio** `/l/{codigo}`: en un SMS de 160 caracteres no cabe una URL larga. Se resuelve sin sesión
  (lo abre quien recibió el mensaje, en su teléfono), solo devuelve una ruta y registra el clic.
- **Consentimiento del destinatario**: el propio usuario registra su celular en *Notificaciones → Mi celular*, lo
  verifica con un código de un solo uso de 6 dígitos y acepta canal por canal. «BAJA» por WhatsApp o SMS lo da de
  baja de inmediato y «ALTA» lo reactiva, con acuse por el mismo canal.
- **Ninguna acción crítica se ejecuta desde un mensaje**: los botones «Aprobar» y «Rechazar» contestan con el enlace
  a la pantalla de aprobación, donde se entra con sesión y doble factor si el rol lo exige.
- **Costo y plantillas rechazadas**: costo estimado por mensaje con tarifas configurables, contador del mes por
  prestador y tenant, alerta `MENSAJERIA_CONSUMO_ALTO` al llegar al porcentaje configurado, bloqueo de los no
  críticos al llegar al tope y alerta `MENSAJERIA_PLANTILLA_RECHAZADA` cuando el proveedor rechaza o pausa una
  plantilla.
- **Webhooks** de Meta (con `hub.challenge` y firma `X-Hub-Signature-256`) y de Twilio (firma HMAC-SHA1), más un
  endpoint de **simulación** para desarrollo, porque en una máquina local el proveedor no alcanza a ACMA.
- **Pantallas**: módulo nuevo *Mensajería* (canales y consumo, plantillas con vista previa como se verá en WhatsApp,
  bitácora de envíos con estado de entrega y motivo del cambio de canal), la tarjeta «Mi celular» en Notificaciones
  con el aviso de privacidad, el bloque «Avisos por WhatsApp y SMS» en el detalle del folio y el estado de entrega
  real en los destinatarios de la minuta. Se quitaron las leyendas «canal Fase 2».
- **Guía de operación** en `docs/operacion/mensajeria.md`: paso a paso de las cuentas gratuitas de Meta y de Twilio,
  qué variables llenar, los límites de cada cuenta de prueba y cómo se someten las plantillas.

**Pruebas:** 531 pytest (58 nuevas de F2-02, con los servidores apagados) y
131 vitest (7 nuevos); `tsc --noEmit` y `npm run build` en verde. Ninguna prueba llama a Meta ni a
Twilio: el proveedor simulado responde y las firmas de los webhooks se arman en la prueba.

**Incidencias resueltas:** Docker Desktop volvió a caerse por un socket huérfano
(`AppData\Local\docker-secrets-engine\engine.sock`), la misma falla de P01; `conftest` tuvo que desactivar el
horario de silencio en la base de pruebas, porque con el del demo (22:00–07:00) el resultado de las pruebas
dependía de la hora de la corrida —el mismo problema que el horario de servicio del contrato en F2-01—; y la
pantalla de notificaciones dejó de tener los tres canales fijos en el código, así que una prueba de P07 que mandaba
la lista de canales vacía dejó de encontrar sus casillas.

## 2026-11-07 · F2-01 — Capacitación del personal y biblioteca técnica

Primer bloque de la segunda etapa. Dos commits locales: backend y frontend.

### Capacitación y certificaciones (§6.10.3)

- **Migración `0013_capacitacion_biblioteca.py`** con siete tablas: `cursos_catalogo` (el curso global de la
  plataforma lleva `prestador_id` nulo), `tecnico_cursos`, `capacitacion_alertas_config`, `biblioteca_manuales`,
  `biblioteca_versiones` (append-only), `contenido_servicio` y `tecnico_descargas_offline`; RLS forzada en las siete.
- **Catálogo de cursos y certificaciones** con proveedor, duración, norma de referencia, vigencia en meses
  (vacío = no caduca) y la habilidad que certifica. El Admin prestador mantiene los suyos; los globales son de la
  plataforma.
- **Expediente por técnico**: cursos con fechas, calificación, folio de constancia y el archivo de la constancia
  (PDF o imagen, hasta 10 MB, cifrada con el sobre de P11a), más las habilidades derivadas con su semáforo de
  vigencia. Se descarga en Excel y en PDF, y abrir una constancia queda registrado como acceso a datos sensibles.
- **Un curso aprobado certifica la habilidad**; uno reprobado no. Al vencer la certificación, la tarea diaria
  `acma.recalcular_capacitacion` (05:10) **retira la habilidad**, y desde ese momento el técnico ya no puede recibir
  folios que la exijan: `tecnico_habilidades.certificada` pasó a ser requisito duro en la captura y en la
  reasignación, donde hasta P11a bastaba con que la habilidad estuviera declarada. La habilidad que el Admin
  prestador afirmó a mano no se toca.
- **Alerta `CERTIFICACION_VENCIDA` activada**: deja de ser de Fase 2 (su fuente de datos ya existe), con evaluador
  propio, umbral por prestador y aviso al cliente cuando `notificar_cliente` está activo. Se agregó
  `CERTIFICACION_VENCIDA_HABILIDAD_RETIRADA`, informativa, para el momento en que la habilidad se retira.
- **Vista del cliente**: las certificaciones vigentes de quien está habilitado en sus unidades o atendió un folio
  suyo en los últimos 90 días; nombre del curso, tipo, norma, proveedor y vigencia, sin datos personales ni
  calificaciones.

### Biblioteca técnica y contenido de servicio (§6.10.4)

- **Manuales por tipo de equipo** (ficha, procedimiento, diagrama, refacciones) en PDF, imagen o video corto hasta
  50 MB, con **historial de versiones**: al subir una versión nueva la anterior queda en `biblioteca_versiones`, que
  es inmutable por trigger. El técnico los consulta si su prestador le habilitó el permiso `acceder_manuales`.
- **Visor en el navegador** con enlace firmado de 5 minutos. Los archivos están cifrados, así que los sirve la API y
  el enlace reconstruye el contexto de seguridad desde su propio token: el visor del navegador no manda cabecera de
  autorización.
- **Contenido de servicio contractual**: el cliente define qué incluye el servicio de cada tipo de equipo con sus
  puntos de revisión **ordenados**, y el sistema avisa (no bloquea) cuando lo declarado no cuadra con la iguala del
  contrato de P10. Es contenido confidencial del cliente: el técnico solo ve el de los folios que tiene asignados.
- **`GET /api/biblioteca/folios/{id}/apoyo`**: una sola llamada que la app del técnico hace al abrir el folio y
  devuelve los puntos de revisión del contrato y los manuales del tipo de equipo.

### Uso sin señal (§6.2 capa 3)

- La clave `biblioteca` del paquete de sincronización ya no viene vacía: metadatos (no archivos) incrementales, con
  las bajas lógicas y la marca de lo que corresponde a los folios del técnico.
- **Dexie versión 3** con la tabla `biblioteca_offline` (archivo + metadatos + versión). Descarga **selectiva**, más
  descarga automática de los manuales de los folios del día **solo con Wi-Fi** (configurable). Pantalla «Mis manuales
  sin conexión» con el espacio usado, la versión, el aviso de «hay versión nueva» con su botón de actualizar y el
  botón de borrar; el tope se configura en MB y se cruza con la cuota real del navegador, avisando antes de pasarse.
- Cada guardado y cada borrado se registra en el servidor; sin señal se queda en el dispositivo y se registra al
  volver la red.

### Frontend

- Módulos nuevos: **Capacitación y certificaciones** (grupo Administración) y **Biblioteca técnica** (grupo
  Operación), con los roles que pide el prompt y la vista del cliente separada.
- En la atención del folio, el técnico ve los puntos de revisión y el manual del equipo, y puede guardarlo para
  trabajar sin señal. Al asignar o reasignar, cada candidato muestra si su certificación está vigente o si lo que
  falta es la certificación y no la habilidad.
- Se quitaron las etiquetas «Fase 2» de la alerta de certificaciones y de la biblioteca del técnico.

### Lo que apareció en el camino

- **La vista del cliente salía vacía** aunque los datos existieran: la subconsulta de una política de RLS **también
  pasa por la RLS de la tabla que lee**, así que la política de `tecnico_cursos` no veía `tecnicos` ni
  `tecnico_tenants_habilitados`. Se agregaron políticas de lectura de cliente en esas dos tablas.
- **La suite dependía de la hora del reloj.** El contrato del demo tiene horario de servicio (L-V 08:00-20:00,
  sábado 09:00-14:00, domingo cerrado) y la causa 7 de §6.8.6 lo evalúa con la hora real del servidor: corrida un
  sábado a las 8 de la mañana, 15 pruebas de aprobación fallaban porque cada folio capturado se iba a `en_revision`.
  Ahora `conftest` deja los contratos del tenant de pruebas abiertos los siete días, y la causa 7 conserva su prueba,
  que estrecha la ventana y la restaura.
- En esta versión de FastAPI un `bool = Form(default=True)` llega `False` cuando el campo no viene (la casilla sin
  marcar del navegador): el campo «aprobado» se recibe como texto y se interpreta en el endpoint, donde ausente
  significa aprobado, que es el caso normal.

### Revisión en el navegador (con la base de desarrollo)

Además de las pruebas, se recorrieron las pantallas nuevas con los datos de desarrollo, como Admin prestador,
técnico y Admin empresa. Seis cosas que solo se ven así:

- **El expediente de un técnico sin cursos respondía 500.** Un `IN` vacío generaba SQL inválido; ahora no se
  consulta el catálogo cuando no hay cursos, y hay prueba.
- **El visor de manuales no abría:** la API manda `frame-ancestors 'none'` desde P11a, así que un `iframe` apuntado
  al enlace firmado lo bloquea el navegador. El visor recibe ahora el archivo como `blob:` y el enlace firmado se
  queda para «abrir en otra pestaña».
- **El historial de cursos del seed caía en los técnicos de las pruebas de carga**, no en los cuatro del demo: se
  elegían por posición en una lista ordenada por correo. Ahora se eligen por correo.
- **La vigencia que ve el cliente se corría un día** (una fecha sin hora formateada como fecha y hora): el servidor
  manda el texto ya listo («vigente hasta el 20/04/2028») y la pantalla no lo vuelve a formatear.
- **La lista de técnicos no cabía en la pantalla** con los 54 de la base de desarrollo: se agregó buscador y la
  lista rueda.
- **El técnico solo podía guardar sin señal los manuales de sus folios del día:** ahora puede guardar cualquiera
  que consulte en la biblioteca, que es lo que pide «descarga selectiva».

Probado de punta a punta en la app: guardar un manual deja el archivo en el teléfono y lo registra en
`tecnico_descargas_offline`; borrarlo deja el registro en `en_dispositivo = false`.

Al reasignar el historial en la base de desarrollo salió una séptima: **el seed decía usar la misma regla que la
pantalla para vincular la habilidad, pero la sobreescribía aunque el prestador la hubiera afirmado a mano**. Ahora
aplica la regla de la decisión 139, y la prueba del registro con constancia usa un técnico nuevo (sin habilidades
declaradas) para seguir comprobando que el curso sí certifica cuando no hay nada que respetar.

### Verificado

434 pytest en verde (41 nuevas) con los servidores de desarrollo apagados, más el de respaldo que se corre
aparte; 116 vitest (7 nuevos, con `fake-indexeddb`), `tsc --noEmit` y `npm run build`.

## 2026-11-05 · P11a — Endurecimiento: seguridad, rendimiento, respaldos y paquete de producción

Sin funcionalidad nueva. Tres commits: `129e6e9` seguridad, `2fb5a71` rendimiento y respaldos, y el de documentación
y paquete de producción.

### Seguridad (§6.9.5)

- **Sesión en cookie.** El refresh deja `localStorage` y pasa a la cookie `httpOnly` `acma_refresh` (ruta
  `/api/auth`, `SameSite=Strict`, `Secure` en producción) con doble envío por la cabecera `X-ACMA-CSRF`. El token de
  acceso vive en memoria y en `localStorage` queda solo una marca sin valor, para saber si vale la pena intentar
  renovar al abrir la app: recargar sin red **no** cierra la sesión y el modo offline de P05 sigue funcionando.
- **Vida de la sesión:** 8 h, 2 h para roles administrativos, heredada en cada rotación (renovar no regala otras 8 h)
  y cierre a los 30 min de inactividad.
- **Contraseñas:** vencimiento a 90 días para roles administrativos con un 403 `CONTRASENA_VENCIDA` en todo menos el
  propio perfil, el cambio y el cierre de sesión; restablecimiento por correo con token de un solo uso de 30 min que
  revoca las sesiones abiertas. Pantallas nuevas: cambio obligatorio, «olvidé mi contraseña» y el enlace del correo.
- **MFA:** el mismo código TOTP no se acepta dos veces dentro de su ventana (`usuarios.mfa_ultimo_paso`).
- **Auditoría:** acceso a datos sensibles (costos del folio, descarga de reportes, detalle de folio cerrado) con
  tabla, id y número de registros; ip y geolocalización aproximada en los eventos de login; aviso al superadmin
  cuando una IP queda bloqueada.
- **Retención de `audit_accesos_api`:** 90 días las llamadas normales y 1 año los errores 4xx/5xx, copiados a
  `audit_accesos_api_errores` antes de soltar la partición. Siempre `DETACH`+`DROP`, nunca `DELETE`, para no tocar la
  auditoría. Tarea `acma.purgar_accesos_api` a las 03:50.
- **Cifrado de archivos con llave por dueño** (lo que el diseño §2.5 pide y faltaba): sobre AES-256-GCM con llave
  derivada por HKDF para cada cliente o prestador y la ruta del objeto firmada como datos autenticados, así que un
  archivo no se puede mover al expediente de otro cliente. Lo escrito antes sigue legible.
- **§6.7:** trigger `acma_evidencia_folio_inmutable` para que la evidencia de un folio cerrado no se pueda borrar ni
  desde la base, más pruebas del saldo de caja chica y de que los sellos de fecha y la geolocalización no son
  editables.
- **Cabeceras y secretos:** HSTS solo en producción, COOP y CORP nuevas, CSP estricta forzada por entorno y
  `X-ACMA-CSRF` en CORS; el guardia de producción rechaza valores de ejemplo en diez variables, la clave de cifrado
  del `.env.example`, CORS vacío y `APP_URL_PUBLICA` sin https. `.env.production.example` y
  `generar_secretos.py --compose`.
- **Dependencias:** `pip-audit` sin vulnerabilidades; `npm audit` de 10 avisos a 6, todos de la cadena de
  construcción. Imágenes de Docker fijadas por versión exacta o digest.
- `docs/seguridad/checklist_iso27001.md` con cada requisito, su implementación y la prueba que lo verifica.

**La prueba de acceso cruzado generada desde las rutas de la app (ACT-1.6) encontró dos fallas reales:**
`usuario_actual` reventaba con `AttributeError` en el canal SSE del chat al leer la ruta, y
`GET /api/seguimiento/por-un/{un_id}` respondía 200 con listas vacías para una UN de otro cliente, lo que confirmaba
su existencia. Y `tests/test_seguridad.py` envejecía **todas** las sesiones de la base (la política deja al rol
`sistema` tocar cualquier fila), lo que tumbaba 34 pruebas del final de la suite: ahora usa su propio usuario.

### Rendimiento (ACT-1.6, §6.7)

Pruebas de carga con Locust en `backend/pruebas_carga/`: 50 técnicos sincronizando y atendiendo folios, 20 de oficina
en listados, detalle, minuta, tablero y SLA, y el operador capturando. Cuatro defectos encontrados y corregidos:

1. **El pool de conexiones se agotaba:** 128 de 724 peticiones fallaban (17.7 %) con `QueuePool limit of size 10
   overflow 10`. Ahora es configurable y la espera baja de 30 s a 10 s.
2. **argon2 bloqueaba el event loop:** 110 ms de CPU por verificación, llamados de forma síncrona dentro de
   funciones `async`. Ahora en un hilo, con tope de concurrencia, y el historial de contraseñas corta en la primera
   coincidencia. Los parámetros de argon2 no se tocaron.
3. **Tres cachés que no cacheaban:** `d.setdefault(k, await f())` evalúa el `await` siempre, así que había una
   consulta por elemento del ciclo en tres lugares.
4. **Faltaban índices:** el listado de folios ordena siempre por `capturado_at DESC` y hacía `Seq Scan` +
   `top-N heapsort` sobre los 1,433 folios del cliente para devolver 50 (migración `0012`).

Resultado: de 17.7 % de errores y mediana de 29 s a 0.02–0.6 % de errores y mediana de 1–2 s, con siete veces más
peticiones atendidas. `docs/rendimiento/resultados.md` lleva el antes y después, el costo real de cada endpoint sin
carga, la memoria medida y el servidor recomendado para 50 y para 500 técnicos — y dice sin adornos que los
percentiles de estas corridas no sirven para comprometer un SLA, porque el generador de carga comparte los 8 núcleos
de esta máquina.

### Respaldos (§6.9.5, ACT-10.1)

- `scripts/respaldo.sh`: base completa en formato custom comprimido más los objetos de MinIO, **verificación de lo
  que acaba de escribir** (`pg_restore --list` y presencia de las tablas críticas), registro de conteos para el
  cotejo, rotación 14/8/12 y copia opcional a otra región.
- `scripts/restaurar.sh`: recrea la base, carga con `--jobs=4`, **coteja los conteos de nueve tablas críticas** y
  falla si alguna no cuadra, informa la versión de esquema y repone los archivos. Sobre producción exige escribir el
  nombre de la base.
- Medido: respaldo 21 s, restauración 47 s (20 s la base, 9 s los archivos), 9/9 tablas cotejadas, esquema `0012`.
- `docs/operacion/recuperacion_desastres.md` con el procedimiento, la extrapolación por volumen, la plantilla de la
  prueba trimestral y el aviso de que **el respaldo diario da un RPO de hasta 24 h, no de 1 h**: para cumplirlo hace
  falta archivado continuo de WAL, con sus opciones y su costo documentados.
- `tests/test_respaldo.py` automatiza el ensayo completo; se activa con `ACMA_PRUEBA_RESPALDO=1`.

### Paquete de producción

`Dockerfile` del backend (dos etapas, usuario sin privilegios, WeasyPrint con sus librerías nativas: en el servidor
los PDF salen con el diseño completo), imagen del frontend que compila la PWA y la sirve con Caddy, y
`docker-compose.prod.yml` con proxy, API (gunicorn + uvicorn), worker, beat, PostgreSQL, Redis con contraseña y
MinIO: healthchecks y límites de memoria en todos, migraciones en un servicio de una sola ejecución del que depende
la API. `seed_produccion.py` crea solo el superadmin —con contraseña temporal que nace vencida— y las cuatro
plantillas base: ningún dato demo. Observabilidad: logs de una línea en JSON y `/api/salud/detalle` con base de
datos, Redis, almacenamiento y Celery.

**Probado completo en local** con `ACMA_DOMINIO=localhost`, y el ensayo encontró cuatro fallas reales que ya están
corregidas: `/api/*` servía el `index.html` de la PWA (Caddy ejecuta `try_files` antes de `reverse_proxy`), el beat
de Celery no arrancaba por el dueño del volumen de su calendario, el healthcheck del worker preguntaba por un nodo
inexistente (`$HOSTNAME` sin shell que lo expanda) y `seed_produccion.py` aceptaba un correo que el login rechaza,
con lo que creaba un superadmin incapaz de entrar.

### Documentación y limpieza

- `docs/decisiones_para_validar.md`: 28 preguntas para el negocio, en lenguaje llano, cada una con la opción que
  eligió el sistema y qué cambia si se responde distinto. Las 124 decisiones pendientes quedaron clasificadas en
  CONTEXTO.md (resueltas, requieren validación, Fase 2).
- `docs/operacion/despliegue.md` y `monitoreo.md`; README con índice de documentos, sección de producción y las
  secciones de cada prompt en orden.
- **Textos internos fuera de la interfaz:** 34 referencias al documento de diseño (`§6.9.4`) y a los prompts
  (`(P09)`, «Disponible en el prompt Pxx») que el usuario final veía en pantalla. Se quitó también el campo `prompt`
  del catálogo de módulos y la rama muerta del hub, porque los 27 módulos ya tienen pantalla.

**Pruebas:** 394 pytest (1 saltado a propósito: el ciclo de respaldo), 109 vitest, `tsc --noEmit` y `npm run build`
en verde, con los servidores de desarrollo apagados.

## 2026-11-02 · P10 — Contratos y SLA, configuración central de alertas, tableros y reportes ejecutivos

- Migración `0010`: `folio_sla_pausas`, `folio_sla_exclusiones`, `penalizaciones_periodo`, `iguala_consumo_periodo`,
  `reportes_programados` y `reportes_generados`; iguala en `contratos` (tarifa y moneda), tiempo en la unidad firmada en
  `contrato_sla` con CHECK de 1 a 4,320 horas, los 15 campos del contador en `folio_sla`, `fase` y `escalacion_de` en
  `alertas_catalogo`, y vista/atención/escalada en `alertas_historial`. RLS forzada en todas las tablas nuevas.
- `services/sla_service.py`: contador de §6.10.1 con inicio en la captura (o en la autorización para los no críticos que
  clasificó el Admin UN), límites por severidad del contrato vigente, pausas por reasignación y por espera de información,
  exclusiones que el prestador registra y el Admin empresa aprueba, tiempo efectivo = total − pausas − exclusiones
  aprobadas, cumplimiento de respuesta y de resolución, y penalización por monto o por porcentaje del costo del folio
  (P09). Al aprobar una exclusión después del cierre, el contador se recalcula sin tocar el folio inmutable.
- Penalizaciones por período: consolidado mensual por contrato con el detalle de folios, revisión borrador → revisado →
  cerrado y resumen exportable en PDF y Excel; el descuento en la factura CFDI queda para Fase 2. Consumo de iguala con
  los correctivos adicionales identificados y la alerta `IGUALA_LIMITE_ALCANZADO`.
- Configuración central de alertas (§6.9.6): conciliación de las dos claves que P09 había duplicado
  (`PRESUPUESTO_UMBRAL_ALCANZADO` → `PRESUPUESTO_ALERTA_1`, `PRESUPUESTO_EXCEDIDO` → `PRESUPUESTO_ALERTA_3`) con alias en
  el evaluador, 6 alertas nuevas (59 en total, 51 evaluadores), las 5 de Fase 2 etiquetadas e inactivables (422
  `ALERTA_FASE_2`), escalación genérica medida desde el disparo de la alerta origen y panel de alertas por usuario con
  vista, atención con nota y supresión temporal.
- `services/bi_service.py` y `docs/bi/indicadores.md` (ACT-8.1): 19 indicadores sobre la jerarquía cliente → grupo → UN,
  MTTR y MTBF del glosario, comparativos contra el período anterior y contra el año anterior, barra de jornada de §6.8.4
  sin mapa, y los cinco tableros por rol (incluido el del Supervisor de operadores sin finanzas ni detalle de folios).
  Caché en Redis con TTL de 120 s.
- `services/reportes_service.py` (ACT-8.4): tres plantillas en PDF (WeasyPrint con respaldo) y Excel (openpyxl) con el
  logo y los colores del prestador, historial con el tiempo de generación, y programación diaria, semanal o mensual que
  envía por correo. Tareas Celery de penalizaciones mensuales, reportes programados y cierre de jornada.
- Routers `/api/sla` (11 rutas) y `/api/bi` (8), más el panel y las escalaciones en `/api/alertas`; el detalle del folio
  trae `sla_contador`.
- Frontend: contratos con iguala, cumplimiento, penalizaciones y bandeja de exclusiones; alertas rehecho como
  configuración central con escalaciones, supresiones e historial; panel de alertas en la cabecera; tablero por rol y
  pantalla de reportes con Recharts 3.10.1; sección de SLA en el folio. Con P10 los 27 módulos de Fase 1 tienen ruta.
- Seeds `seed_sla.py` (contrato de iguala, contador de todos los folios, 3 incumplidos, 1 pausa, 2 exclusiones, 3 meses de
  penalizaciones, supresión y escalaciones, 2 reportes programados) y `seed_historico.py` (1,200 folios en 12 meses).
- Pruebas: pytest 365, vitest 104; tiempos con 1,000+ folios: 906 ms en PDF y 1,250 ms en Excel.
- Decisiones pendientes 104–124 en `CONTEXTO.md`.
- Incidencias resueltas: el catálogo de alertas no lo puede escribir el prestador (la RLS lo impide), así que la cadena de
  escalación por dueño se guardó en `alertas_configuracion.parametros`; el seed de P10 creaba un segundo contrato activo
  para el mismo cliente y dejaba indefinido el horario de servicio (ahora convierte el contrato demo a iguala); la
  supresión demo de `FOLIO_SIN_CLASIFICAR` silenciaba las pruebas de P07 (ahora apunta a un folio concreto).

## 2026-11-02 · P09 — Inventario, caja chica, costo del folio, presupuestos, ERP y activos

- Migración `0009`: 21 tablas (`articulos`, `ubicaciones_inventario`, `existencias`, `movimientos_inventario` append-only,
  `ordenes_compra` + partidas, `fondos_caja_chica`, `gastos_caja_chica`, `polizas_exportacion`, `validaciones_cfdi`,
  `folio_costos`, `tarifas_mano_obra`, `presupuestos`, `presupuesto_consumos` append-only, `erp_eventos_pendientes`,
  `erp_configuracion`, `erp_exportaciones`, `activo_depreciacion`, `activo_depreciacion_historial` append-only,
  `activo_tco_snapshot`, `activo_reemplazo_alertas`), 13 ENUM, campos económicos en `tipos_equipo` y `equipos`, y 6 alertas
  nuevas con sus evaluadores (41 en total). RLS forzada en todas.
- `services/inventario_service.py`: los tres orígenes de refacción de §6.4 con costo promedio ponderado, traspaso al vehículo del
  técnico, ajuste con razón, consumo en folio (409 `STOCK_INSUFICIENTE` en línea) y merge con alerta `STOCK_NEGATIVO` para los
  consumos offline de §6.2; ciclo completo de la orden de compra con evento al ERP al aprobar y entrada al almacén al recibir.
- `services/caja_chica_service.py`: fondo por técnico, captura de la factura con foto, aprobación en un toque que da de alta la
  refacción, mueve el inventario y carga al fondo (409 `SALDO_INSUFICIENTE`), y póliza de reposición con las 12 columnas de §6.5
  en Excel y XML. OCR y validación del CFDI quedan como stubs de Fase 1.
- `services/costos_service.py`: el costo del folio se calcula al cerrar (refacciones + horas × tarifa vigente + otros + ajuste) y
  la Mesa de control lo valida, lo que genera el evento `registrar_gasto` del ERP y carga el consumo a los presupuestos.
- `services/presupuestos_service.py`: presupuestos por UN o por grupo y tipo de actividad, comprometido de los folios
  autorizados sin cerrar, umbrales con alerta única por umbral y tablero consolidado Tenant → Grupo → UN con semáforo.
- `services/activos_service.py`: cuatro métodos de depreciación, TCO con inactividad y valor residual, snapshot mensual, alerta
  de reemplazo por umbral del valor de reposición y decisión reemplazar/reparar que genera el trabajo especial de P08.
- `services/erp/`: capa desacoplada de §6.6 con los 4 eventos internos, adaptadores CONTPAQi y Microsip como stub de Fase 2 y
  exportación universal XML/Excel configurable.
- Routers `/api/inventario` (14 rutas), `/api/caja-chica` (10), `/api/presupuestos` (7), `/api/erp` (6) y `/api/activos` (7), más
  `GET/POST /api/folios/{id}/costos[/validar]`. Tareas Celery de pólizas (23:00), depreciación y TCO (día 1) y exportación ERP.
- Frontend: módulos `inventario`, `caja_chica`, `presupuestos`, `activos` (con la ficha del equipo) y `erp`; sección «Datos
  financieros» del folio y captura del gasto de caja chica desde la atención del técnico.
- Seed `seed_inventario.py` con 25 artículos, almacén y vehículos, OC, fondos, gastos, póliza, tarifas, presupuestos al 85 % y
  125 %, configuración ERP y 6 activos con 12 meses de snapshots. Pruebas: pytest 307, vitest 87.
- Decisiones pendientes 88–103 en `CONTEXTO.md`.
- Incidencias resueltas: la cadena de RLS al validar un costo desde el contexto del prestador (`presupuesto_consumos`,
  `alertas_historial` y `notificaciones` necesitaban el `prestador_id` del folio y el WITH CHECK ampliado); el control de
  umbrales se movió de una columna en `presupuestos` a `alertas_historial` para no actualizar la fila del presupuesto;
  `pycryptodome` quedó con su módulo nativo ilegible y bloqueaba MinIO (reinstalación forzada); Docker Desktop volvió a quedarse
  en «Starting the Docker Engine» (misma corrección de sockets huérfanos, copias `*.huerfano-20261102-*`).

## 2026-10-29 · P08 — Trabajos especiales, conversión de cotizaciones y OC de activos

- Migración `0008`: `trabajos_especiales`, `te_respuesta_cliente` y `te_historial` (append-only), `te_evidencias`,
  `folio_activo_autorizacion`, `folio_activo_historial` (append-only); FK de `cotizaciones.trabajo_especial_id`; `folios.es_instalacion_activo`,
  `equipo_instalado_id` y `trabajo_especial_id`; `trigger_revision.pendiente_oc_cliente`; 7 alertas nuevas. RLS forzada en todas.
- `services/trabajos_especiales_service.py`: ciclo de 8 estados con `cambiar_estado_te()`, validación del cliente por botón con
  comentario obligatorio y reenvío por versión, programación con técnicos habilitados (`ejecutar_trabajos_especiales`), folio operativo
  `especial` sincronizado en ambos sentidos, cierre con formulario + evidencia + firma, cancelación con razón, TE de urgencia (sin monto,
  salto a programado, cotización retroactiva opcional), sección de la minuta (§7.3), reporte con exportación. La conversión de
  cotizaciones (§7.7 M1) reemplaza el 501 de P07.
- `services/oc_activos_service.py`: bandera `clasifica_instalacion_activo` en el esquema de formularios (captura y atención), folio
  retenido con `pendiente_oc_cliente`, cinco estatus con `listo_para_asignar` automático, rechazo con cancelación o reprogramación a
  período (Por presupuesto), alta automática del equipo al cerrar (`ACT-<folio>`, inactivo + alerta si falta el tipo).
- Routers `/api/trabajos-especiales` (15 rutas) y `/api/oc-activos` (3); detalle y resumen del folio con los bloques de P08; sync del
  técnico resuelve el formulario `trabajo_especial`.
- Frontend: módulos `trabajos_especiales` y `oc_activos` con sus páginas, botón «Convertir en Trabajo Especial» en cotizaciones, columna
  del TE en el listado, indicadores en folios y en la app del técnico, sección real de la minuta.
- Seed: formulario del TE, formulario de captura de activo, 8 TE y 4 folios de activo. Pruebas: pytest 277, vitest 68.
- Decisiones pendientes 75–87 en `CONTEXTO.md`.

## 2026-10-29 · P07 — Minuta del día, notificaciones por correo y módulos de seguimiento

**Base de datos (migración 0007)**
- 19 tablas: hallazgos, peticiones_cliente, minuta_configuracion, minutas, minutas_secciones, minutas_respuestas,
  minutas_destinatarios, notificaciones, notificacion_preferencias, periodos_presupuestales, cotizaciones,
  cotizacion_envios_externos, hallazgos_presupuesto, seguimientos_internos, reprogramaciones, modulo_historial (append-only),
  clasificacion_configuracion, folio_clasificaciones y admin_un_calificacion; 18 ENUM; `trigger_revision` +
  `pendiente_clasificacion`; `folio_sla.autorizado_en` / `excluir_sla_por_cliente`; `aprobacion_decisiones.modulo_destino_id`
  actualizable una vez. 14 alertas nuevas (minuta, cotizaciones, presupuesto, interno, reprogramación, clasificación).

**Backend**
- `notificaciones_service.notificar()` (canal por preferencia y evento; app, push y correo; WhatsApp/SMS omitidos como Fase 2),
  correo SMTP genérico con modo stub (`.eml` en MinIO) y plantillas con el diseño del prestador, PDF con WeasyPrint o
  generador mínimo; los stubs de P04–P06 ahora pasan por `notificar()`.
- `hallazgos_service` (bandera `genera_hallazgo` en formularios, marcado de mensajes de chat, captura manual),
  `minuta_service` (generación por UN y global con las secciones de §7.3, validación con ventana, entrega por correo+PDF/push/
  bandeja, seis respuestas de §7.4, vencimiento, recordatorio por período), paquete `services/seguimiento` (cotizaciones,
  presupuesto, interno, reprogramación con `cambiar_estado()`, historial inmutable, entradas desde minuta/clasificación/rechazo
  §6.8.7, folio directo), `clasificacion_service` (pendientes, cinco opciones, plazo y calificación del Admin UN).
- Tareas Celery `acma.generar_minutas` (10 min), `acma.enviar_notificaciones` / `_pendientes` (2 min) y
  `acma.calificar_admin_un` (06:30); 25 evaluadores de alertas. 43 rutas nuevas (`/api/minutas`, `/api/hallazgos`,
  `/api/peticiones`, `/api/notificaciones`, `/api/seguimiento`, `/api/clasificacion`, marcado en chat).
- Seed `seed_minuta.py`: configuración, hallazgos, peticiones, minutas de 3 días, cotizaciones, diferidos, seguimientos,
  reprogramaciones, folios pendientes de clasificar y calificación.

**Frontend**
- Páginas Minutas (lista, bandeja de validación, configuración) y ResponderMinuta (dos bloques, PDF, seis opciones),
  Seguimiento (listado, Kanban, vista por UN, reporte ejecutivo exportable, detalle con acciones), Clasificación (pendientes,
  calificación, configuración), Notificaciones (bandeja y preferencias) y campana en la cabecera; detalle del folio con
  hallazgos/derivaciones/clasificación; marcar mensajes del chat.

**Pruebas:** 259 pytest y 62 vitest en verde; `tsc --noEmit` limpio; `npm run build` verde.

**Incidencias resueltas:** WeasyPrint no carga sin GTK en Windows (generador mínimo de respaldo); `aprobacion_decisiones` era
append-only y P07 debe llenar `modulo_destino_id` (trigger que permite esa única actualización); las notificaciones creadas
en la transacción del actor no podían enviarse por la RLS de solo-dueño (política ampliada al tenant/prestador del evento);
la suite completa de pytest supera los 15 minutos del token de acceso (re-login en `conftest.auth`); vitest en paralelo agota
los tiempos (archivos en serie).

## 2026-10-28 · P06 — Calendario de preventivos, planes con triggers y reasignación forzada

**Base de datos (migración 0006)**
- 12 tablas: planes_mantenimiento, plan_triggers, plan_tareas, plan_materiales, plan_ejecuciones, equipo_planes,
  preventivos_calendario (unifica §6.9.1 y §7.6), calendario_publicaciones, autorizaciones_preventivo,
  razones_reasignacion (7 literales sembradas), reasignaciones y reasignacion_validaciones; `folios.plan_id` y
  `folios.calendario_id`; FK de `formulario_asignaciones.plan_mantenimiento_id`. 8 ENUM nuevos. 3 alertas nuevas
  (preventivo vencido, autorización pendiente, calendario sin publicar). RLS por prestador con lectura del tenant y
  políticas por comando en las tablas ligadas al folio.

**Backend**
- `planes_service` (triggers de Fase 1 con 403 para los de Fase 2, próxima fecha, versión, equipos), `preventivos_service`
  (calendario, publicación con evento `calendario.publicado`, generación de folios preventivos directo a Autorizado,
  solicitudes y autorizaciones formales de reprogramación/cancelación, validador en el motor de estados, cierre con
  desvío y `texto_desvio()` literal), `reasignacion_service` (candidatos, restricción dura de habilidad, advertencias con
  confirmación, razón del catálogo, chat y push, historial y reporte), tarea Celery `acma.generar_preventivos_programados`
  (beat 02:00) + `POST /api/preventivos/generar`, catálogo importable `calendario_preventivos`, 22 rutas nuevas en
  `routers/preventivos.py` y `routers/reasignaciones.py`; `tecnico_con_habilidad` considera las habilidades de las tareas
  del plan; el paquete offline del técnico resuelve el formulario `preventivo`; `GET /api/folios/{id}` trae `plan_id`,
  `plan_nombre`, `calendario_id` y las reasignaciones reales. Se retiró la ruta transitoria `reasignar` de P04.
- Seed `seed_preventivos.py`: formulario preventivo del prestador, 3 planes, 6 equipos con plan, 8 filas de calendario
  (ejecutados con desvío ±, reprogramado, cancelado, programados), noviembre publicado y 3 reasignaciones.

**Frontend**
- Páginas Calendario, Planes (editor con Fase 2 deshabilitada), Autorizaciones y Reporte de reasignaciones (+ catálogo de
  razones); módulos `preventivos` y `reasignaciones` con ruta; `FolioDetalle` con modal **Reasignar**, panel de preventivo
  y sección de reasignaciones; app del técnico con insignia Preventivo, lista de verificación del plan y materiales.

**Pruebas:** 226 pytest y 54 vitest en verde; `tsc --noEmit` limpio; `npm run build` verde.

**Incidencias resueltas:** la cancelación autorizada no puede ejecutarla el rol `sistema` (la tabla §6.8.6 no lo permite
desde asignado): la ejecuta el solicitante con la autorización en el contexto. `notificaciones.ENVIADAS` es un deque
acotado: las pruebas buscan por contenido. La alerta `CALENDARIO_MES_SIN_PUBLICAR` depende del día del mes: la prueba de
auditoría ya no exige un conteo exacto de disparos.

## 2026-10-28 · P05 — Apps PWA del operador y del técnico, modo offline y chat

**Base de datos (migración 0005)**
- 9 tablas: chats, chat_participantes, chat_mensajes (id_cliente UNIQUE por chat, doble timestamp, leído), chat_archivos,
  chat_eventos_sistema, sincronizacion_dispositivos, sincronizacion_conflictos, sincronizacion_mutaciones (bitácora
  idempotente) y suscripciones_push; `plazo_encuesta_horas` en las políticas del tenant. Trigger de inmutabilidad de
  mensajes en folio cerrado; RLS de mensajes/archivos limitada a participantes (políticas de escritura por comando, misma
  corrección aplicada a `folios`).

**Backend**
- Sincronización: paquete incremental de catálogos por rol con bajas lógicas, lote de mutaciones en orden e idempotente
  (7 tipos) con las reglas de §6.2 (server-wins, client-wins con hora real, merge con alerta como gancho para P09),
  evidencias en dos pasos y registro de conflictos. `transicionar()` y `enviar()` aceptan `momento`.
- Chat: tres chats automáticos por folio (gancho `folio.creado`), participantes fijos y permisos literales de §6.8.1,
  eventos de sistema por transición, evidencia posterior al cierre, archivado de cancelados sin asignar, WebSocket por chat
  con Redis pub/sub y fallback SSE.
- Cierre en campo: firma del operador/Admin UN, encuesta NPS con formulario resuelto por P03 y plazo configurable, evento
  `encuesta.pendiente` al cerrar. Push PWA con web-push (VAPID) y suscripciones por dispositivo; `mis-permisos`.
- Seed: encuesta publicada, chats y mensajes demo (incluido el folio cerrado) y suscripción push de prueba.

**Frontend**
- Dexie v2, `syncEngine` (cola FIFO, reintento exponencial, «requiere atención», reanudación tras recarga, refresco de
  catálogos, ids locales), transporte híbrido de formularios, `useConexion` + indicador global, pantalla «Pendientes de
  sincronizar», service worker con `NetworkFirst` para la API y manejador de push.
- App del operador (inicio por UN, captura táctil offline con confirmación de UN, detalle con chat, firma a pantalla
  completa y encuesta), app del técnico (mis folios hoy/próximos, atención con acciones, formulario de P03, refacciones y
  chat) y `ChatFolio` con pestañas por canal, tiempo real, adjuntos, leído y participantes, integrado en el detalle.

**Pruebas:** 203 pytest y 45 vitest en verde; `tsc --noEmit` limpio; `npm run build` verde.

**Incidencias resueltas:** una política RLS `FOR ALL` concede SELECT (se separó por comando); `INSERT … RETURNING` exige
pasar la política de lectura (ids generados en el cliente para mensajes de sistema); el envío push debe correr en sesión
de sistema; parches con `replace` fallaban por archivos con CRLF (script tolerante a finales de línea).

## 2026-10-27 · P04 — Folios: ciclo de vida, validaciones y aprobación multinivel

**Base de datos (migración 0004)**
- 16 tablas: folios (numero correlativo por tenant con prefijo, 11 estados, severidad y origen, confirmación de UN,
  duplicado con justificación, monto estimado), folio_estados_historial y aprobacion_decisiones (append-only, también
  para superadmin), folio_formulario_captura/atencion, folio_evidencias, folio_refacciones, folio_sla, folio_encuesta,
  revision_manual_triggers, folio_keywords_alerta, folio_politicas_tenant, aprobacion_reglas, aprobacion_flujos,
  aprobacion_niveles_config (CHECK del Nivel 3) y aprobacion_alertas_timeout. Trigger de inmutabilidad del folio
  cerrado/cancelado; función `acma_siguiente_numero_folio()` (acma_auth); `contratos.horario_servicio_json`,
  `equipos.criticidad`, `familias_equipo.habilidad_clave`; 3 alertas nuevas (25 en el catálogo).

**Backend**
- Motor de estados `folio_estados.py` con la tabla literal de §6.8.6 y `transicionar()` como única puerta de cambio de estado
  (409 `TRANSICION_NO_PERMITIDA` / `CIERRE_INCOMPLETO`, historial, auditoría, fechas, suscriptores para P05/P06/P07/P10).
- Captura `folios_captura_service.py` con las 8 validaciones en orden, duplicado con bloqueo total o confirmación fuerte,
  severidad automática y override, permisos configurables de técnico y despachador, alcance por rol y archivo completo.
- Aprobación `aprobacion_service.py`: nivel de entrada (monto, criticidad, tipo de trabajo; la más restrictiva gana),
  auto-aprobación de críticos, bandeja por nivel, aprobación en cadena, rechazo con 4 razones → módulo destino y evento
  `folio.derivado_a_modulo`, timeouts con las cuatro opciones (Celery cada minuto). Evaluador `FOLIO_EN_REVISION_SIN_ATENDER`.
- 32 endpoints bajo `/api/folios`; stub `services/notificaciones.py`.
- Seed: políticas y prefijo `CD`, 6 reglas, 3 niveles, criticidad en 12 equipos, 4 palabras clave, horario de servicio y 15
  folios (uno por trigger, flujo en Nivel 1 y 2, pendiente de información, autorizado, asignado, en ejecución, cerrado
  con atención y firma, cancelado por rechazo).

**Frontend**
- Módulo Folios: listado con filtros y Kanban, detalle con todas las secciones del archivo, línea de tiempo, acciones
  según la tabla de transiciones del servidor y panel de aprobación; captura con selector de UN, equipos con contrato,
  falla por familia, formulario dinámico de P03, tarjeta de duplicado con justificación y confirmación obligatoria de UN
  («Sí, es esta unidad» / «No, quiero cambiarla»); bandeja de aprobación con rechazo en dos pasos y configuración del
  flujo para Admin empresa; `services/notificaciones.ts` (stub en consola).

**Pruebas:** 185 pytest y 39 vitest en verde; `tsc --noEmit` limpio; `npm run build` verde.

**Incidencias resueltas:** Docker Desktop otra vez con sockets huérfanos (mismo remedio); `ALTER FUNCTION … OWNER TO
acma_auth` requiere `GRANT CREATE ON SCHEMA` temporal y privilegios de tabla para la función SECURITY DEFINER; el
`now()` de PostgreSQL empataba el orden del historial (timestamps explícitos); las pruebas de catálogos cambian las
habilidades del técnico demo (las pruebas de folios las fijan); el evaluador de matriz ignoraba alertas por folio.

## 2026-10-23 · P03 — Motor de formularios dinámicos

**Base de datos (migración 0003)**
- 9 tablas: formularios, formulario_versiones, formulario_asignaciones, formulario_permisos_mesa, catalogos_personalizados,
  catalogo_personalizado_opciones, formulario_respuestas (inmutable al enviar), formulario_evidencias (inmutables con la
  respuesta; sin altas tras el envío) y calidad_foto_defaults. Alerta `GEOLOCALIZACION_FUERA_DE_UN`.

**Backend**
- Contrato Pydantic de los 22 tipos de campo con `config` validada por tipo, condiciones, fuentes fijas/catálogo y cascada.
- Motor de reglas (`validacion.py`): visibilidad en cadena, validación por tipo, concatenación/matemáticas/sellos en servidor.
- 26 endpoints bajo `/api/formularios`: CRUD con versionado, publicar, archivar, clonar, diff; asignaciones y `resolver`
  con prioridad §6.8.3c; permisos de mesa; catálogos personalizados; `opciones` de catálogos del sistema; respuestas
  (crear, parcial, enviar, listar) y evidencias (subir con control de calidad, EXIF/GPS, hash; descargar; eliminar).
- Geofencing con PostGIS al enviar + evaluador de respaldo; auditoría de ajustes manuales; transcripción stub.
- Seed: 4 plantillas base (22 tipos), catálogo «Causa raíz» (6 opciones), formulario de captura y de atención publicados y
  asignados a Refrigeración, y uno específico del tenant demo.

**Frontend**
- Tipos espejo y motor de validación espejo; `respuestas.ts` como única puerta de escritura (interceptable en P05).
- Renderizador con un componente por tipo: cámara (`mediaDevices`) con indicador verde/rojo y anotación, firma y dibujo en
  `canvas`, escáner con `@zxing/browser`, audio con `MediaRecorder`, geolocalización con ajuste dentro del radio, cascada.
- Constructor visual: paleta de 22 tipos, lienzo con secciones y arrastre, panel con todos los parámetros de `config`,
  editor de condiciones, enlace de catálogos por arrastre, vista previa real, publicar con notas y comparación de versiones.
- Repositorio de plantillas, lista de formularios y «Mis formularios» (iniciar, reanudar, consultar enviados); página de
  llenado con guardado parcial automático.
- Documentación `docs/formularios/tipos_de_campo.md`.

**Pruebas:** 131 pytest y 33 vitest en verde; `tsc --noEmit` limpio; `npm run build` verde.

**Incidencias resueltas:** rutas literales (`/respuestas`, `/catalogos-personalizados`) declaradas después de
`/{formulario_id}`; EXIF GPS de prueba con `IFDRational`; caché de opciones compartida entre pruebas de vitest.

## 2026-10-23 · P02 — Catálogos maestros

**Base de datos (migración 0002)**
- 11 tablas nuevas: habilidades, tecnicos, tecnico_habilidades, tecnico_tenants_habilitados, niveles_severidad (5 por
  prestador, sembrados también al crear un prestador), familias_equipo y tipos_equipo (globales o del tenant), equipos,
  tipos_falla (flag `requiere_revision_manual` protegido además por trigger), tipo_falla_severidad e importaciones_catalogo.
- `contratos.cobertura`, `contrato_sla.nivel_severidad_id` (con backfill) y la alerta `MATRIZ_SEVERIDAD_INCOMPLETA`.
- Función `acma_equipo_con_contrato_activo(equipo_id)` y helpers reutilizables de migración en `core/sql_migracion.py`.

**Backend**
- 30 endpoints nuevos bajo `/api/catalogos`: habilidades, técnicos (ficha, habilidades, tenants §6.10.8, grupo, overrides y
  permisos efectivos), grupos de técnicos, severidades, familias y tipos de equipo (cascada), equipos (filtro por UN, texto y
  contrato activo), tipos de falla, matriz de severidad (celda, masiva y `resolver`) e importador (catálogos, plantilla,
  vista previa, confirmar, cancelar).
- Importador CSV/Excel para 8 catálogos con validación por fila, duplicados y límite de 10,000 filas; archivos en MinIO.
- Evaluador de alertas `MATRIZ_SEVERIDAD_INCOMPLETA` registrado en Celery (no se repite mientras haya una sin atender).
- Seed: 5 habilidades, 4 técnicos (2 nuevos: tecnico3 y tecnico4), 3 familias globales con 2 tipos cada una, 12 equipos
  (2 sin contrato activo, 1 en garantía), 8 tipos de falla y matriz completa (16 celdas) para el tenant demo.

**Frontend**
- Módulo Catálogos con pestañas por rol: Técnicos, Severidades, Familias y tipos, Equipos, Tipos de falla, Matriz de
  severidad (cuadrícula con color) e Importar (plantilla → vista previa → confirmar). Buscador reutilizable y
  `SelectorBusqueda` para P04.

**Pruebas:** 96 pytest y 27 vitest en verde; `tsc --noEmit` limpio; `npm run build` verde.

**Incidencias resueltas:** Docker Desktop otra vez con sockets huérfanos (mismo remedio); las semillas de una migración
chocan con la RLS forzada (se fija `app.rol = sistema` al inicio de la migración).

## 2026-10-19 · P01 — Cimientos

**Infraestructura**
- Repositorio nuevo en `Desktop\acma`, separado de `acma-proyecto` (que no se modificó).
- Docker Compose con PostgreSQL 16 + PostGIS, Redis 7 y MinIO en puertos propios; script de init con los roles
  `acma_owner`, `acma_api` y `acma_auth` y las bases `acma` y `acma_test`.
- Python 3.12 instalado; venv del backend; dependencias del frontend (React 19, Vite 8, TypeScript 7, Tailwind 4, vite-plugin-pwa 2).

**Base de datos (migración 0001)**
- 31 tablas: tenants, prestadores, tenant_prestador, usuarios, historial_contrasenas, roles (11, ENUM), permisos_catalogo,
  permisos_tecnico, grupos_tecnicos, grupo_tecnico_permisos, tecnico_grupo, tecnico_permisos_override, permisos_despachador,
  permisos_despachador_log, grupos_un, unidades_negocio (PostGIS), grupo_un_miembros, usuario_grupos, usuario_un, contratos,
  contrato_sla, alertas_catalogo (20 alertas semilla), alertas_configuracion, alertas_historial, alertas_supresiones,
  configuracion_tenant, configuracion_prestador, sesiones, intentos_fallidos, audit_log y audit_accesos_api (particionadas).
- RLS habilitada y forzada en todas las tablas con dueño; políticas fail-closed por tenant, prestador y rol.
- Auditoría append-only con triggers que rechazan UPDATE/DELETE/TRUNCATE, incluso al dueño del esquema.
- `version_hash` y `updated_at` mantenidos por trigger.

**Backend**
- FastAPI con 43 rutas en 10 routers: auth, usuarios, tenants, prestadores, unidades_negocio, grupos_un, contratos, alertas,
  configuracion, auditoria. OpenAPI con descripciones en español.
- Login en dos pasos con MFA TOTP (enrolamiento con QR, verificación, códigos de recuperación, deshabilitar, regenerar);
  JWT de 15 min y refresh rotativo de 7 días con detección de reúso que revoca la familia.
- Límite de 5 intentos fallidos por IP en 10 min, bloqueo temporal por usuario, política de contraseñas con historial de 10.
- Cabeceras de seguridad, CORS por entorno, bitácora de cada llamada a la API, cifrado AES-256-GCM de secreto MFA y datos fiscales.
- Celery con worker, beat y tareas `evaluar_alertas` (60 s), particiones de auditoría y purga de sesiones.
- `seed_dev.py`: Prestador Demo, Cliente Demo, 3 UNs, 1 grupo, 1 contrato con 5 SLAs y 12 usuarios (11 roles).

**Frontend**
- PWA instalable (manifest, íconos, service worker con precache del shell).
- Login con MFA y códigos de recuperación, AppShell con barra lateral y cabecera, RoleHub por rol con módulos futuros
  marcados "Disponible en el prompt Pxx".
- Pantallas: usuarios, clientes, prestadores (con logo y colores), UNs y grupos, contratos con SLAs, configuración de
  alertas, auditoría y "Mi seguridad".

**Pruebas:** 76 pytest y 19 vitest en verde; `tsc --noEmit` limpio; `npm run build` verde.

**Incidencias resueltas:** Docker Desktop bloqueado por sockets huérfanos; asyncpg 0.32 bloqueado por el Control de
aplicaciones de Windows (se fijó 0.31.0); `localStorage` de Node 25 en vitest; funciones SECURITY DEFINER sujetas a la RLS
forzada (se movieron a `acma_auth`).
