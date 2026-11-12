# Indicadores de BI por rol (ACT-8.1)

Especificación de cada indicador de los tableros de P10: fórmula, fuente y filtros. Todo se calcula en el servidor
(`services/bi_service.py`) sobre la jerarquía **Tenant → Grupo de UNs → UN** de §6.8.5 y un período `desde`–`hasta`
(por defecto, del día 1 del mes a hoy). El resultado se guarda en Redis con TTL de **120 s**: los tableros se consultan
en ráfagas y un minuto de desfase es aceptable para indicadores operativos; sin Redis el cálculo se repite y nada falla.

## Filtros comunes

| Filtro | Efecto |
|---|---|
| `desde` / `hasta` | Período. Los folios se cuentan por `capturado_at`; los cerrados y los costos, por `fecha_cierre`. |
| `grupo_id` | Limita a las UNs del grupo (`grupo_unidades_miembros`). |
| `un_id` | Limita a una UN. |
| dominio del actor | El cliente queda fijo a su `tenant_id`; el prestador, a su `prestador_id`. El Admin UN solo ve sus UNs y el Supervisor de operadores solo las de sus grupos. |

Comparativos multi-período: `anterior` es el mismo número de días inmediatamente antes del período y `anio_anterior`
es el mismo rango del año previo. Cada uno trae folios, cerrados, cumplimiento de resolución y costo.

## Catálogo de indicadores

| Indicador | Fórmula | Fuente | Dónde aparece |
|---|---|---|---|
| Folios por estado | Conteo agrupado por `folios.estado` | `folios` | todos los tableros |
| Folios por severidad | Conteo agrupado por el nombre del nivel | `folios` + `niveles_severidad` | cliente, supervisión |
| Cumplimiento de SLA | `cumplimiento_respuesta` y `cumplimiento_resolucion` verdaderos ÷ folios cerrados del período, global y por severidad | `folio_sla` | cliente, prestador, dirección |
| Folios penalizados | Folios cerrados con `cumplimiento = false` | `folio_sla` | cliente, prestador |
| **MTTR** | Promedio de horas de `capturado_at` a `fecha_cierre` de los **correctivos cerrados** del período (glosario: «desde que se reporta hasta que el folio se cierra») | `folios` | cliente, prestador |
| **MTBF** | Promedio de horas entre capturas correctivas **consecutivas del mismo equipo** dentro del período; con menos de dos fallas por equipo devuelve 0 con aviso | `folios` | cliente |
| Gasto contra presupuesto | `monto` de los presupuestos vigentes que cruzan el período y su `consumido` (P09); disponible = monto − consumido | `presupuestos`, `presupuesto_consumos` | cliente |
| Costo del período | Suma de `folio_costos.costo_total` de los folios cerrados en el período | `folio_costos` | cliente, prestador, dirección |
| Top 10 equipos por costo | Suma de `costo_total` por equipo, descendente | `folios` + `folio_costos` + `equipos` | cliente |
| Top 10 equipos por fallas | Conteo de folios por equipo, descendente | `folios` + `equipos` | cliente |
| Cumplimiento de preventivos | Programados del período con `fecha_real` ÷ programados; desvío = promedio del valor absoluto de `desvio_dias` | `preventivos_calendario` (P06) | cliente, prestador |
| Hallazgos y su conversión | Hallazgos del período y cotizaciones con `hallazgo_id` creadas en el período | `hallazgos`, `cotizaciones` (P07) | cliente |
| Trabajos especiales | Total del período, urgencias y desglose por estado | `trabajos_especiales` (P08) | cliente |
| Cotizaciones | Total, autorizadas o convertidas, porcentaje de conversión y monto autorizado | `cotizaciones` | prestador |
| Penalizaciones del período | Suma de `monto_penalizacion` de los `penalizaciones_periodo` del rango, con su estado | `penalizaciones_periodo` | prestador, dirección |
| Consumo de iguala | Correctivos incluidos, atendidos y adicionales; preventivos incluidos y ejecutados | `iguala_consumo_periodo` | prestador |
| Carga por técnico | Folios asignados y cerrados por técnico en el período. **Sin productividad ni venta por técnico: Fase 2** | `folios` + `usuarios` | prestador |
| Inventario y caja chica | Existencias en o bajo el mínimo, saldo de los fondos, gastos del período y los que faltan por aprobar | `existencias`, `fondos_caja_chica`, `gastos_caja_chica` (P09) | prestador |
| Folios por cliente | Conteo por tenant y estado | `folios` + `tenants` | prestador |
| SLA en riesgo | Alertas `SLA_RESPUESTA_EN_RIESGO` y `SLA_RESOLUCION_EN_RIESGO` disparadas en el período | `alertas_historial` | supervisión |
| Histórico de escalaciones | Alertas con `escalacion_de` disparadas en el período | `alertas_historial` + `alertas_catalogo` | dirección |
| Calificación del Admin UN | Última calificación del período (P07) | `admin_un_calificacion` | Admin UN |
| Comparativo por grupo y por UN | Para cada grupo y cada UN: folios, cerrados, cumplimiento de resolución y costo | compuesto | cliente |

## Indicadores globales de jornada (§6.8.4, tablero del Despachador)

Barra sobre el listado de folios, calculada **solo del día en curso**:

| Indicador | Fórmula |
|---|---|
| Folios completados / total | Folios del día en estado `cerrado` ÷ folios capturados hoy |
| Técnicos con folios activos | Técnicos distintos con folios en `asignado`, `en_camino`, `en_ejecucion` o `pendiente_refaccion` |
| Alertas abiertas | Alertas del historial sin `atendida_at` |
| Tiempo promedio de atención | Promedio de horas de `fecha_inicio_atencion` a `fecha_cierre` de los folios cerrados hoy |

El mapa en vivo, el GPS de los técnicos y los desvíos de ruta de §6.8.4 son **Fase 2**: la barra los omite y lo dice.

## Tablero por rol (§5.1, §5.2, §7.5)

| Rol | Tablero | Contenido |
|---|---|---|
| Admin empresa | `cliente` | Todos los indicadores del cliente, la jerarquía completa y los comparativos multi-período. |
| Admin UN | `cliente` | Lo mismo, limitado a sus UNs, más su calificación del período. |
| Supervisor de operadores | `supervision` | **Literal de §5.1**: folios por estado, distribución por severidad y SLA en riesgo de sus grupos. Sin montos, sin detalle de folios y sin historial de cerrados. La respuesta trae `sin_finanzas: true`. |
| Admin prestador · Mesa de control | `prestador` | Folios por cliente y estado, SLA y penalizaciones, iguala, cotizaciones, carga por técnico, preventivos, inventario y caja chica. |
| Supervisor del prestador | `prestador` | El mismo tablero en solo lectura (`solo_lectura: true`), más el reporte de cierre de jornada por correo. |
| Dirección del prestador | `direccion` | Indicadores principales en solo lectura y el histórico de alertas de escalación. |
| Despachador | `jornada` | La barra de §6.8.4 sobre el listado de folios. |
| Superadmin | `prestador` | Sin acotar por dominio. |

## Reportes ejecutivos (ACT-8.4)

| Plantilla | Destinatario | Secciones |
|---|---|---|
| `cliente` | Admin empresa / Admin UN | Gasto contra presupuesto, cumplimiento de SLA, preventivos, hallazgos y comparativos multi-período. |
| `prestador` | Admin prestador | Folios por cliente, SLA y penalizaciones del período, iguala y cotizaciones. |
| `jornada` | Supervisor del prestador | Cierre de jornada: completados del día, técnicos activos, alertas abiertas y tiempo promedio. |

Se generan en el servidor en PDF (WeasyPrint, con el generador mínimo de respaldo en Windows) y en Excel (openpyxl) con
el logo y los colores del prestador, quedan en `reportes_generados` con su `archivo_key` y el tiempo de generación, y la
tarea `acma.enviar_reportes_programados` los manda por correo según la periodicidad configurada.

## Gestión de activos ISO 55000 (§6.9.3, F2-05)

El indicador `criticidad` del tablero del cliente y del prestador **no depende del período**: la criticidad es el
estado de hoy del parque, no un acumulado del mes.

| Campo | Qué es |
|---|---|
| `por_nivel` | Activos evaluados por nivel A, B, C y D. |
| `criticos_sin_plan` | Activos de nivel A sin plan de mantenimiento preventivo activo (§6.9.3 lo exige). |
| `mitigaciones_vencidas` | Acciones de mitigación de riesgo que pasaron su fecha compromiso sin implementarse. |
| `revisiones_vencidas` | Activos cuya criticidad debía revisarse y no se revisó (`meses_revision` por cliente). |

### Reportes de certificación

| Plantilla | Destinatario | Qué demuestra ante un auditor |
|---|---|---|
| `iso_registro` | Admin empresa / Admin prestador | Que cada activo tiene criticidad documentada, con su índice, su desglose, la fecha de evaluación y la próxima revisión. |
| `iso_matriz` | Admin empresa / Admin prestador | Que el riesgo está ubicado: probabilidad × impacto con los activos en cada celda, y la matriz 5×5 de los modos de falla. |
| `iso_modos_falla` | Admin empresa / Admin prestador | Que los modos de falla están analizados y tienen plan de mitigación con responsable, fecha y efectividad medida. |
| `iso_mejora_continua` | Admin empresa / Admin prestador | Que la gestión mejora: MTBF y MTTR por nivel de criticidad mes a mes, y cobertura de preventivos de los activos A y B. |
| `iso_historial` | Admin empresa / Admin prestador | La trazabilidad: cada cambio de criticidad con su motivo, su razón y quién lo hizo. |

Salen por `GET /api/reportes/iso55000/{tipo}?formato=pdf|excel` con el mismo generador de ACT-8.4, así que llevan el
logo y los colores del prestador, quedan en `reportes_generados` con su tiempo de generación y la descarga se anota en
la bitácora de acceso a datos sensibles (§6.9.5).

**MTBF y MTTR por nivel** usan las mismas definiciones del catálogo de indicadores (horas entre fallas consecutivas
del mismo equipo, y horas desde el reporte hasta el cierre), agrupadas por el nivel de criticidad vigente del activo.
Un mes sin dos fallas del mismo equipo sale como «sin datos» en lugar de como cero: un cero diría que el equipo falla
sin parar, que es lo contrario.
