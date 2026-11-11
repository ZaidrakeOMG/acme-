# F2-04 — Medidores de activos y planes de mantenimiento por uso (segunda etapa, prioridad 3)

## Contexto

F2-02 (WhatsApp y SMS) y F2-03 (pantalla de operaciones) están cerrados; la suite completa quedó en 531 pruebas en verde. Lee antes de empezar `CONTEXTO.md` completo (reglas de la segunda etapa, notas de entorno, «Preventivos y reasignaciones (P06)», «Inventario, costos y activos (P09)» y las decisiones pendientes), `BITACORA.md`, `docs/piloto/ACMA_Segunda_Etapa.xlsx` (hoja «Bloques Fase 2», bloque «Medidores de activos y planes por uso») y en `ACMA_Documento_Diseno_v2.5.docx`: §6.9.1 completo (los 6 tipos de trigger, estructura del plan y sus tablas), §6.9.2 completo (tipos de medidor, métodos de actualización y sus 4 tablas), §6.9.4 (depreciación por unidades de producción), §6.9.6 (alerta `MEDIDOR_PROXIMO_PM`, default 10 % del intervalo, al Despachador) y ACT-8.3 del §8.

Lo que la Fase 1 dejó listo y este prompt debe completar sin duplicar:
- Las 6 tablas de planes de P06 con `plan_triggers.tipo_trigger` ya definido para los 6 tipos y `parametros_json` genérico; el servicio hoy solo acepta `tiempo_fijo` y `calendario` y responde `TRIGGER_FASE_2` para `medidor_umbral`, `medidor_intervalo`, `evento` y `combinado`; la interfaz los muestra deshabilitados con la etiqueta «Fase 2».
- `equipo_planes.ultimo_valor_medidor` creado y sin uso.
- La tarea nocturna `generar_preventivos_programados` (P06) que crea los folios preventivos en `autorizado`, sin duplicar y con horizonte configurable.
- El método de depreciación «unidades de producción» de P09, que hoy responde `REQUIERE_MEDIDORES_FASE_2`.
- La alerta `MEDIDOR_PROXIMO_PM` registrada como Fase 2 e inactiva (P10).
- El importador de P02, el motor de formularios de P03 (con banderas por campo como `genera_hallazgo`), la app del operador y del técnico con modo sin señal (P05) y `notificar()` con todos sus canales (P07 y F2-02).

Este bloque no requiere proveedores externos. La importación desde ERP o SCADA se hace **por archivo** (CSV/Excel) y por una API de lecturas autenticada; no se conecta a ningún sistema de terceros.

## Objetivo

Que cada equipo pueda tener uno o más medidores (horas, ciclos, kilómetros, energía, unidades producidas o personalizados), que sus lecturas se registren por el técnico, por el operador, por importación o por estimación, y que los planes de mantenimiento generen solos los folios preventivos cuando el uso real lo requiera, además de los disparos por evento y las combinaciones «lo que ocurra primero».

## Entregables

### 1. Migración `0016_medidores_planes_uso.py`

Con los helpers de `core/sql_migracion.py`, RLS forzada en toda tabla con `tenant_id`/`prestador_id`.

**Medidores (§6.9.2, las 4 tablas literales más lo necesario):**

| Tabla | Campos clave |
|---|---|
| `tipos_medidor` | prestador_id / tenant_id nullable (NULL = catálogo global del Superadmin), nombre, unidad, categoria ENUM(`horas` / `ciclos` / `distancia` / `energia` / `unidades` / `personalizado`), descripcion, permite_estimacion, decimales, activo |
| `equipo_medidores` | equipo_id, tipo_medidor_id, valor_actual, valor_ultimo_pm, fecha_ultima_lectura, metodo_actualizacion ENUM(`tecnico` / `operador` / `importacion` / `estimado`), valor_maximo (para medidores que se reinician, p. ej. 99,999), numero_serie_medidor, instalado_en, activo |
| `medidor_lecturas` | equipo_medidor_id, equipo_id, tipo_medidor_id, valor, valor_acumulado (corrige reinicios y cambios de medidor), metodo, registrado_por, folio_id nullable, timestamp_dispositivo, timestamp, evidencia_id nullable (foto del marcador), estado ENUM(`valida` / `rechazada` / `en_revision`), motivo — **append-only** |
| `medidor_estimaciones` | equipo_medidor_id, incremento_por_dia, horario_operacion_json (días y horas de operación), activa, desde |
| `medidor_cambios` | equipo_medidor_id, tipo ENUM(`reinicio` / `reemplazo_medidor`), valor_anterior, valor_nuevo, motivo, registrado_por, timestamp — para que el acumulado no retroceda |
| `eventos_trigger_catalogo` | clave, descripcion, parametros_schema_json — catálogo cerrado de eventos que pueden disparar planes (sección 3) |

### 2. Lecturas de medidor

- **Técnico (§6.9.2):** en el motor de formularios, nueva bandera por campo `lectura_medidor` (en campos numéricos de tipo `texto` con formato numérico o `slider`), con `tipo_medidor_id` y foto opcional u obligatoria del marcador. Al enviarse el formulario de atención, la lectura se registra con `folio_id`. En los preventivos, el formulario del plan pide la lectura del medidor que disparó el plan. Funciona sin señal por la cola de mutaciones de P05 (nuevo tipo `registrar_lectura`).
- **Operador:** en su app de campo, pantalla «Registrar lectura» para los equipos de su sucursal con medidor `operador`, con foto del marcador opcional (configurable por tipo de medidor), sin señal incluido.
- **Importación:** nuevo catálogo `lecturas_medidor` en el importador de P02 (columnas: código de equipo, tipo de medidor, valor, fecha y hora) con vista previa y errores por fila; y `POST /api/medidores/lecturas/lote` con autenticación por **llave de API por tenant** (nueva, revocable, con permisos solo para registrar lecturas y registro en auditoría) para que un sistema SCADA o ERP del cliente pueda enviar lecturas en el futuro sin cambiar código. Documentar el formato en `docs/integracion/lecturas_medidor.md`.
- **Estimación:** tarea beat diaria que suma el `incremento_por_dia` según el horario de operación configurado y escribe una lectura `estimado`; una lectura real posterior **corrige** el valor y recalcula el incremento real promedio (mostrar estimado vs. real; anotar la regla).
- **Validaciones:** rechazar o enviar a revisión una lectura menor a la anterior (salvo reinicio o reemplazo registrado en `medidor_cambios`), un salto mayor al esperado (más de N veces el incremento diario promedio por los días transcurridos; N configurable, default 3), una lectura con fecha futura o duplicada. Las lecturas en revisión no disparan planes hasta que Despachador o Admin prestador las aprueben o rechacen con razón. Alertas `MEDIDOR_LECTURA_ANOMALA` y `MEDIDOR_SIN_LECTURA` (sin lecturas en X días para medidores no estimados; default 30).

### 3. Los cuatro triggers restantes (§6.9.1)

Habilitar en `planes_service` la creación de los 4 tipos y quitar `TRIGGER_FASE_2`:

- **`medidor_umbral`** — `{"tipo_medidor_id", "umbral"}`: se activa cuando el valor acumulado del medidor del equipo alcanza el umbral (ejemplo literal: cambio de aceite a las 500 h).
- **`medidor_intervalo`** — `{"tipo_medidor_id", "intervalo"}`: se activa cada `intervalo` unidades desde `valor_ultimo_pm` (ejemplo literal: revisión de banda cada 10,000 ciclos). Al cerrarse el folio preventivo, actualizar `equipo_medidores.valor_ultimo_pm` y `equipo_planes.ultimo_valor_medidor` con la lectura registrada en ese folio (o la última válida, si el folio no trajo lectura; anotar).
- **`evento`** — `{"evento": clave, ...parámetros}` con el catálogo cerrado de `eventos_trigger_catalogo`: `falla_correctiva_grave` (folio correctivo cerrado con severidad alta o crítica en el equipo; ejemplo literal), `fallas_repetidas` (N correctivos del equipo en X días), `equipo_instalado` (alta del equipo por instalación de activo, P08), `reemplazo_componente` (refacción de una categoría configurada consumida en un folio, P09), `cambio_medidor` (reemplazo del medidor). Los eventos se escuchan con los ganchos existentes de `transicionar()` y de los servicios, no con sondeo.
- **`combinado`** — `{"triggers_ids": [...], "logica": "OR" | "AND"}`: OR = «lo que ocurra primero» (ejemplo literal: 90 días O 400 horas); AND = cuando se cumplen todas. Al ejecutarse el plan, **todos** los triggers del combinado se reinician desde esa ejecución.
- Generación: extender la tarea nocturna de P06 y agregar una evaluación inmediata al registrar una lectura válida o al ocurrir un evento, para no esperar a la noche. El folio se crea con el mismo servicio de P06 (directo a `autorizado`, con el formulario del plan) y nunca se duplica mientras exista un folio abierto del mismo plan y equipo.
- Fecha programada del folio por medidor: si el umbral ya se alcanzó, hoy; si se proyecta, la fecha estimada con el incremento promedio y la ventana ±días del plan. Mostrar en `preventivos_calendario` el origen «por medidor» o «por evento».
- **Alerta `MEDIDOR_PROXIMO_PM`:** activarla (`fase` = 1) con su default literal de 10 % del intervalo restante, al Despachador, con la fecha estimada en que se alcanzará.

### 4. Depreciación por unidades de producción (§6.9.4, ACT-8.3)

Completar el método que P09 dejó pendiente: depreciación del periodo = (costo de adquisición − valor residual) × (unidades del periodo ÷ vida útil total en unidades), con las unidades tomadas del medidor elegido en la configuración de depreciación del equipo. Recalcular en la tarea mensual de P09 y escribir el historial. Prueba con un caso numérico.

### 5. Endpoints

`/api/medidores` (catálogo de tipos, medidores por equipo, lecturas con filtros, registro individual, lote por API, revisión de anómalas, cambios de medidor, estimaciones, llaves de API por tenant) y ampliación de `/api/planes` (los 4 triggers, catálogo de eventos, simulación «¿cuándo se dispararía este plan con las lecturas actuales?»). Validación de multitenancy en servicio además de RLS y auditoría con `registrar_actor`.

### 6. Frontend

- Ficha del equipo (P09): pestaña «Medidores» con cada medidor, valor actual, gráfica de lecturas (reales y estimadas diferenciadas, valores también en texto), próximo mantenimiento por uso y fecha estimada; alta, cambio y reinicio de medidor.
- Editor de planes (P06): habilitar los 4 triggers con formularios guiados en lenguaje claro (por ejemplo, «Cada [10,000] [ciclos] desde el último mantenimiento»), constructor de combinados con «O (lo que ocurra primero)» / «Y (cuando se cumplan todas)», selector del catálogo de eventos y vista de simulación. Quitar las etiquetas «Fase 2».
- Bandeja «Lecturas por revisar» para Despachador y Admin prestador.
- App del operador: «Registrar lectura». App del técnico: lectura dentro del formulario de atención.
- Llaves de API para lecturas (Admin empresa y Superadmin): crear, ver una sola vez, revocar.
- Calendario de preventivos (P06): distinguir origen manual, tiempo/calendario, medidor y evento.

### 7. Seed y pruebas

- Seed: catálogo global con los 6 tipos de §6.9.2; medidores en 6 equipos demo (un compresor con horas, un elevador con ciclos, un generador con kilómetros, un motor con kWh, una línea con unidades y uno personalizado), 60 días de lecturas con mezcla de técnico, operador, importación y estimado, una lectura anómala en revisión y un reinicio de medidor; 4 planes nuevos: cambio de aceite cada 500 h (umbral), banda cada 10,000 ciclos (intervalo), inspección tras falla grave (evento) y 90 días O 400 h (combinado), con uno a punto de dispararse para la demostración; un equipo con depreciación por unidades producidas.
- Backend (`tests/test_medidores.py`, `tests/test_medidor_lecturas.py`, `tests/test_triggers_medidor.py`, `tests/test_trigger_evento.py`, `tests/test_trigger_combinado.py`, `tests/test_depreciacion_unidades.py`, `tests/test_lecturas_api_llave.py`): validaciones de lectura (menor, salto, futura, duplicada) y aprobación de anómalas; reinicio y reemplazo sin retroceso del acumulado; estimación y corrección con lectura real; umbral e intervalo generan el folio una sola vez y actualizan el último PM al cerrar; cada evento del catálogo dispara su plan; combinado OR y AND con reinicio de todos los triggers; evaluación inmediata y nocturna sin duplicados; alerta `MEDIDOR_PROXIMO_PM` al 10 %; `MEDIDOR_SIN_LECTURA`; depreciación por unidades con caso numérico; llave de API por tenant (válida, revocada, de otro tenant, sin permiso para otra cosa); lectura sin señal por la cola; aislamiento entre tenants y prestadores; RLS forzada en las tablas nuevas.
- Frontend: editor de plan con los 4 triggers y la simulación, registro de lectura del operador sin señal, pestaña de medidores con gráfica, bandeja de revisión.
- `pytest`, `vitest`, `tsc --noEmit` y `npm run build` en verde, con los servidores de desarrollo apagados durante la suite completa.

## Reglas (vigentes)

1. Seguir el Documento de Diseño v2.5; lo no definido se anota en `CONTEXTO.md` como decisión pendiente de validación.
2. Multitenancy validado en servicio además de RLS.
3. Sin proveedores externos (importación por archivo y API propia).
4. Identificadores en español sin acentos.
5. Cerrar con `CONTEXTO.md` (avance F2-04 ✅; sección «Medidores y planes por uso (F2-04)») y `BITACORA.md` actualizados.
6. No cambiar el stack.
7. No correr la suite completa con los servidores de desarrollo encendidos; volver a encenderlos al terminar y dejar ACMA encendido para la revisión de la usuaria.
8. Commits solo locales; si el trabajo es largo, «F2-04 (1/2) backend» y «F2-04 (2/2) frontend». Si la sesión se corta, retomar desde el último commit.

## Al terminar

Resumen en español con: tablas de la migración 0016, endpoints, reglas elegidas (detección de anomalías, corrección de estimados, último PM sin lectura, fecha de folio por medidor), catálogo de eventos, alertas activadas, cómo ver la demostración (qué usuario y qué plan está por dispararse), decisiones pendientes nuevas y conteo de pruebas.
