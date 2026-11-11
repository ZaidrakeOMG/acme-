# F2-05 — Gestión de activos ISO 55000: criticidad, modos de falla y riesgo por activo (segunda etapa, prioridad 4)

## Contexto

Este prompt se ejecuta **después de cerrar F2-04** (medidores y planes por uso). Lee antes de empezar `CONTEXTO.md` completo (reglas de la segunda etapa, notas de entorno, «Folios (P04)» — criticidad manual y su efecto en la aprobación multinivel —, «Inventario, costos y activos (P09)», «SLA, alertas y BI (P10)» — MTBF y MTTR —, «Medidores y planes por uso (F2-04)» y las decisiones pendientes), `BITACORA.md`, `docs/piloto/ACMA_Segunda_Etapa.xlsx` (bloque «Gestión de activos ISO 55000») y en `ACMA_Documento_Diseno_v2.5.docx`: §6.9.3 completo (dimensiones de impacto con sus pesos, niveles A/B/C/D con sus rangos e implicaciones, y las 4 tablas), §6.9 (introducción de los módulos de clase mundial), objetivos OE-02, OE-09 y OE-11, §2 (beneficio «herramientas para obtener certificación ISO 55000: análisis de criticidad documentado, gestión del riesgo por activo (FMEA simplificado), métricas de MTBF y MTTR»), §6.8.7 (criticidad A/B en el flujo de aprobación) y ACT-8.2 del §8.

Lo que ya existe y debe usarse sin duplicar: `equipos.criticidad` capturada a mano (P04) y su uso en la aprobación multinivel (A/B mínimo Nivel 2, autorización automática de críticos); la ficha del equipo con historial, TCO, depreciación y alerta de reemplazo (P09); MTBF y MTTR del tablero (P10, `docs/bi/indicadores.md`); el historial de folios con fecha de falla, atención y cierre, tipos de falla y costos; el historial sintético de 12 meses (`scripts/seed_historico.py`); los planes de mantenimiento con sus 6 triggers (F2-04); el inventario con stock mínimo (P09); las habilidades certificadas (F2-01); y los generadores de PDF y Excel (P07/P10).

Este bloque no requiere proveedores externos. Su precisión depende del historial real: en desarrollo se calibra con el historial sintético y en producción conviene recalibrar a los 6–12 meses de operación (anotarlo en `CONTEXTO.md`).

## Objetivo

Que cada equipo tenga una criticidad A/B/C/D calculada con la fórmula de §6.9.3 a partir de su historial de fallas y de cuatro dimensiones de impacto que el cliente evalúa, con historial de evaluaciones y revisión periódica; que se documenten sus modos de falla y las acciones de mitigación con su efectividad medida; que la criticidad dispare las implicaciones de mantenimiento del diseño; y que el cliente pueda descargar los reportes que respaldan una certificación ISO 55000.

## Entregables

### 1. Migración `0017_iso55000_criticidad.py`

Con los helpers de `core/sql_migracion.py`, RLS forzada en toda tabla con `tenant_id`/`prestador_id`.

| Tabla | Campos clave |
|---|---|
| `criticidad_configuracion` | tenant_id, pesos_json (default literal: operacional 30 %, seguridad 35 %, económico 25 %, imagen 10 %; deben sumar 100 %), rangos_economico_json (default literal: 1 menor a $5,000 … 5 mayor a $500,000), escala_probabilidad_json (sección 2), rangos_nivel_json (default literal: A 80–100, B 50–79, C 20–49, D 0–19), meses_revision (default 12), implicaciones_activas_json (sección 4) |
| `activo_criticidad` (§6.9.3) | equipo_id (único), indice_criticidad, nivel ENUM(`A` / `B` / `C` / `D`), probabilidad, impacto_ponderado, dimensiones_json, origen ENUM(`calculado` / `manual`), razon_manual, evaluado_por, fecha_evaluacion, proxima_revision |
| `criticidad_evaluaciones` (§6.9.3) | equipo_id, indice_anterior, indice_nuevo, nivel_anterior, nivel_nuevo, dimensiones_json, probabilidad, motivo ENUM(`evaluacion_inicial` / `revision_periodica` / `recalculo_por_historial` / `ajuste_manual` / `cambio_configuracion`), evaluado_por, timestamp — **append-only** |
| `activo_modos_falla` (§6.9.3) | equipo_id (o tipo_equipo_id para modos genéricos del tipo; anotar), descripcion_falla, tipo_falla_id nullable, causa_probable, efecto_operacional, severidad (1–5), frecuencia_historica (calculada), deteccion (1–5, opcional), nivel_riesgo calculado, origen ENUM(`sugerido` / `manual`), activo, registrado_por |
| `activo_riesgo_mitigacion` (§6.9.3) | modo_falla_id, accion_mitigacion, tipo ENUM(`plan_preventivo` / `capacitacion` / `refaccion_en_inventario` / `rediseno` / `otro`), plan_mantenimiento_id nullable, responsable_id, fecha_compromiso, fecha_implementacion, estado ENUM(`propuesta` / `en_proceso` / `implementada` / `descartada`), efectividad (calculada, sección 3), evidencia_key |

`equipos.criticidad` (P04) se mantiene como el campo que leen la aprobación multinivel y el resto del sistema, ahora sincronizado desde `activo_criticidad.nivel`.

### 2. Cálculo de criticidad (`services/criticidad_service.py`)

- **Fórmula literal de §6.9.3:** criticidad = probabilidad de falla × impacto ponderado. Impacto ponderado = suma de cada dimensión (escala 1–5) por su peso. Probabilidad de falla en escala 1–5 a partir del historial de ACMA: número de correctivos del equipo en los últimos 12 meses (o MTBF del equipo cuando hay suficientes fallas), con rangos configurables en `escala_probabilidad_json`; para equipos con menos de 6 meses de historia, usar la probabilidad del tipo de equipo en el tenant (y si tampoco hay, la del tipo de equipo en toda la plataforma, anonimizada) y marcarlo como «estimada». Índice 0–100 = (probabilidad × impacto ponderado) ÷ 25 × 100. Anotar la escala y la normalización como decisión pendiente de validación.
- Las dimensiones operacional, seguridad e imagen las evalúa el **Admin empresa o el Admin UN** (formulario guiado con la descripción literal de cada nivel 1–5); la económica se **propone** automáticamente con el costo promedio de los correctivos del equipo y su costo de inactividad (P09) y se puede ajustar con razón.
- Evaluación inicial masiva por tipo de equipo (asignar las mismas dimensiones a todos los equipos de un tipo y después ajustar los particulares) e importación de evaluaciones con el importador de P02 (catálogo nuevo `criticidad`).
- Recalculo automático: tarea beat semanal que recalcula la probabilidad con el historial y escribe una evaluación `recalculo_por_historial` solo si cambia el nivel; revisión periódica según `meses_revision` con alerta `CRITICIDAD_REVISION_PENDIENTE` al Admin empresa.
- Ajuste manual del nivel por el Admin empresa con razón obligatoria (`origen = manual`), que se conserva hasta la siguiente revisión.
- Cambio de nivel de un equipo: notificar al Admin prestador y al Despachador (`notificar()`) porque cambia las implicaciones de mantenimiento y la aprobación multinivel.

### 3. Modos de falla y mitigación (FMEA simplificado)

- **Sugerencias desde el historial:** proponer modos de falla por equipo a partir de los tipos de falla y causas raíz (catálogo «Causa raíz» de P03) más frecuentes en sus correctivos, con su frecuencia histórica; el Admin prestador o el Admin empresa los aceptan, editan o descartan.
- Nivel de riesgo por modo de falla = severidad × frecuencia (y × detección si se captura; anotar), con matriz de riesgo 5×5.
- Acciones de mitigación con responsable y fecha compromiso; una acción de tipo `plan_preventivo` se vincula a un plan de F2-04 y una de tipo `capacitacion` a un curso de F2-01.
- **Efectividad medida:** al implementarse una acción, comparar la frecuencia del modo de falla y el MTBF del equipo en los 6 meses anteriores contra los posteriores (mostrar «sin datos suficientes» hasta tener al menos 90 días); alerta `MITIGACION_VENCIDA` cuando pasa la fecha compromiso sin implementar.

### 4. Implicaciones por nivel (§6.9.3)

Aplicar las implicaciones literales como **reglas configurables por tenant** (`implicaciones_activas_json`), activas por defecto como alertas y, solo si el tenant lo decide, como restricciones. Anotar cada una como decisión:

- **A — PM obligatorio con plan definido:** alerta `ACTIVO_CRITICO_SIN_PLAN` si un equipo A no tiene plan activo en `equipo_planes`.
- **A — Respuesta máxima 4 h / B — 8 h:** alerta `RESPUESTA_CRITICIDAD_EN_RIESGO` cuando un correctivo de un equipo A o B se acerca a ese límite aunque el SLA del contrato sea mayor (no modifica el SLA ni la penalización contractual de P10).
- **A — Técnico especialista / B — Técnico certificado:** en la asignación (P04/P06), advertencia si el técnico no tiene la habilidad requerida con certificación vigente (F2-01); restricción opcional por tenant.
- **A — Refacciones siempre en inventario:** alerta `REFACCION_CRITICA_SIN_STOCK` cuando un material de los planes de equipos A (`plan_materiales`) está bajo su stock mínimo (P09).
- **C y D:** solo informativo en la ficha.

### 5. Reportes para certificación ISO 55000

Con los generadores de P07/P10, en PDF y Excel, para Admin empresa (su tenant) y Admin prestador (por cliente):

- Registro de activos con criticidad, fecha de evaluación, próxima revisión y origen.
- Matriz de riesgo (probabilidad × impacto) con los activos ubicados y su conteo por celda.
- Modos de falla y plan de mitigación con responsables, estado y efectividad.
- Mejora continua: tendencia de MTBF y MTTR por nivel de criticidad (mensual, 12 meses) y cobertura de preventivos de activos A y B (porcentaje con plan activo y cumplimiento del calendario).
- Historial de evaluaciones de criticidad (trazabilidad para auditoría).

Agregar los indicadores nuevos a `docs/bi/indicadores.md` y al tablero del cliente (P10): distribución de activos por nivel, activos A sin plan y acciones de mitigación vencidas.

### 6. Endpoints

`/api/criticidad` (configuración, evaluación individual y masiva, ajuste manual, historial, recálculo), `/api/modos-falla` (sugerencias, alta, edición, matriz de riesgo), `/api/mitigaciones` (acciones, estado, efectividad) y `/api/reportes/iso55000/{tipo}` (PDF/Excel). Multitenancy validado en servicio además de RLS y auditoría con `registrar_actor` en evaluaciones, ajustes manuales y cambios de configuración.

### 7. Frontend

- Ficha del equipo (P09): pestaña «Criticidad y riesgo» con el nivel (color y texto), el índice y su desglose (probabilidad y cada dimensión con su peso), el historial de evaluaciones, los modos de falla con su nivel de riesgo y las acciones de mitigación. Quitar la etiqueta «Fase 2» de la criticidad.
- Nuevo módulo `iso55000` en `src/config/modulos.ts` (grupo Finanzas y activos o Análisis; elegir y anotar) para Admin empresa, Admin UN (sus UNs), Admin prestador, Mesa de control y Superadmin: evaluación guiada y masiva, matriz de riesgo interactiva, bandeja de revisiones pendientes y acciones vencidas, configuración de pesos y rangos (solo Admin empresa) y descarga de los reportes.
- Asignación de técnicos (P04/P06): advertencia por criticidad junto al indicador de certificación de F2-01.

### 8. Seed y pruebas

- Seed: configuración con los pesos y rangos literales para el tenant demo; evaluaciones de los 12 equipos demo con los 4 niveles representados (al menos 2 A, uno sin plan); 10 modos de falla (6 sugeridos desde el historial, 4 manuales) y 6 acciones de mitigación en distintos estados, una vencida y una implementada hace más de 90 días con efectividad medible sobre el historial sintético.
- Backend (`tests/test_criticidad_calculo.py`, `tests/test_criticidad_revision.py`, `tests/test_modos_falla.py`, `tests/test_mitigacion.py`, `tests/test_implicaciones_criticidad.py`, `tests/test_reportes_iso55000.py`): fórmula con casos numéricos que caen en cada nivel y en sus fronteras (19/20, 49/50, 79/80); pesos que no suman 100 % rechazados; probabilidad estimada por tipo de equipo; recálculo que solo registra si cambia el nivel; ajuste manual con razón y su vigencia; sincronización con `equipos.criticidad` y efecto en la aprobación multinivel; inmutabilidad del historial; sugerencia de modos de falla desde el historial; efectividad antes/después; cada implicación como alerta y como restricción opcional; reportes en PDF y Excel; aislamiento entre tenants (incluida la probabilidad de plataforma anonimizada); RLS forzada en las tablas nuevas.
- Frontend: evaluación guiada, matriz de riesgo, pestaña de la ficha, configuración de pesos con validación.
- `pytest`, `vitest`, `tsc --noEmit` y `npm run build` en verde, con los servidores de desarrollo apagados durante la suite completa.

## Reglas (vigentes)

1. Seguir el Documento de Diseño v2.5; lo no definido se anota en `CONTEXTO.md` como decisión pendiente de validación, y las que deba responder el negocio también en `docs/decisiones_para_validar.md`.
2. Multitenancy validado en servicio además de RLS.
3. Sin proveedores externos.
4. Identificadores en español sin acentos.
5. Cerrar con `CONTEXTO.md` (avance F2-05 ✅; sección «ISO 55000 (F2-05)» con la fórmula, las escalas y la recomendación de recalibrar con datos reales) y `BITACORA.md` actualizados.
6. No cambiar el stack.
7. No correr la suite completa con los servidores de desarrollo encendidos; volver a encenderlos al terminar y dejar ACMA encendido para la revisión de la usuaria.
8. Commits solo locales; si el trabajo es largo, «F2-05 (1/2) backend» y «F2-05 (2/2) frontend». Si la sesión se corta, retomar desde el último commit.

## Al terminar

Resumen en español con: tablas de la migración 0017, endpoints, fórmula y escalas elegidas con un ejemplo numérico, implicaciones activadas como alerta o restricción, alertas nuevas, reportes disponibles, cómo verlo en la demo (usuario y equipo), decisiones pendientes nuevas y conteo de pruebas.
