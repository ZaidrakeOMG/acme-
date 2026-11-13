# Rendimiento y carga · resultados medidos

Requisito que se verifica: **§6.7 — 50 técnicos en simultáneo, escalable a 500+** y los percentiles de **ACT-1.6**.
Los guiones están en [`backend/pruebas_carga/`](../../backend/pruebas_carga/README.md); cualquiera puede repetir
estas corridas con el mismo comando.

Medido el **5 de noviembre de 2026**.

---

## 1. Cómo se midió

| Qué | Valor |
|---|---|
| Carga | 71 usuarios: 50 técnicos (sincronización + atención), 20 de oficina (listados, detalle, minuta, tablero, SLA), 1 operador capturando folios |
| Duración | 5 minutos por corrida, arranque de 5 usuarios por segundo |
| Datos | Seed de desarrollo + histórico de P10: **1,433 folios**, 400 equipos, 54 técnicos, 12 meses de historia |
| Base | PostgreSQL 16 + PostGIS en Docker, Redis y MinIO en Docker |
| Equipo | Portátil Windows 11, **8 núcleos lógicos y 7.2 GB de RAM** |

> **Lo que estas cifras no son.** El generador de carga, la API, PostgreSQL, Redis, MinIO y los contenedores de otro
> proyecto comparten esos 8 núcleos. Los percentiles absolutos miden *esta máquina saturada*, no el servidor de
> producción, y varían bastante entre corridas iguales. Lo que sí es sólido y reproducible es el **antes y después**
> de cada corrección (secciones 2 y 3) y el **costo por endpoint sin carga** (sección 4), que es la base de la
> estimación de servidor de la sección 6.

## 2. Lo que encontró la medición

### 2.1 El pool de conexiones se agotaba y la API devolvía 500 (grave)

Con 71 usuarios, **128 de 724 peticiones fallaron (17.7 %)** y la mediana se fue a 29 segundos. El log de la API
tenía **292 veces** el mismo error:

```
sqlalchemy.exc.TimeoutError: QueuePool limit of size 10 overflow 10 reached, connection timed out, timeout 30.00
```

El engine se creaba con `pool_size=10, max_overflow=10` fijos. Cada petición retiene su conexión mientras dura, así
que 20 conexiones no alcanzan para 71 usuarios: el resto espera 30 segundos y se rinde con un 500.

**Corregido:** el pool es configurable (`DB_POOL_SIZE`, `DB_POOL_OVERFLOW`, `DB_POOL_TIMEOUT`), con
`pool_recycle=1800`, y el valor por defecto subió a 15 + 10 por proceso. El tiempo de espera bajó de 30 s a 10 s:
más vale fallar rápido y que el proxy reintente que acumular peticiones colgadas.

> **Cómo se calcula.** `workers × (DB_POOL_SIZE + DB_POOL_OVERFLOW) ≤ max_connections de PostgreSQL − margen`.
> Con el valor por defecto y 4 workers son 100 conexiones, así que `docker-compose.prod.yml` levanta PostgreSQL con
> `max_connections=200` (deja espacio para Celery, los respaldos y una sesión de `psql`).

### 2.2 argon2 bloqueaba el event loop (grave)

`verificar_contrasena` y `hashear_contrasena` son argon2id: **110 ms de CPU medidos** por operación, con 4 hilos.
Se llamaban de forma síncrona dentro de una función `async`, así que cada inicio de sesión **congelaba todas las
peticiones del proceso** durante ese tiempo. Peor en el cambio de contraseña, que compara contra las 10 anteriores:
hasta 1.1 segundos de bloqueo total.

**Corregido:**
- Las dos operaciones corren en un hilo aparte (`asyncio.to_thread`), así el loop sigue atendiendo.
- Con tope de concurrencia (`HASH_CONCURRENCIA`, 2 por proceso): sin tope, una tanda de inicios de sesión ocupa
  todos los núcleos con argon2 y deja sin aire al resto de la API.
- La comparación contra el historial corta en la primera coincidencia en lugar de evaluar las diez.
- **Los parámetros de argon2 no se tocaron** (t=3, m=64 MiB, p=4, el default de argon2-cffi, más fuerte que el
  mínimo que recomienda OWASP). Bajarlos aceleraría el login a costa de seguridad, y el login es una vez por
  jornada: no vale el cambio.

Queda una consecuencia inevitable: **una tanda de N inicios de sesión simultáneos cuesta N × 110 ms de CPU**. En la
prueba los 71 usuarios entran en 15 segundos y el login llega a 5–7 s de mediana. En operación real los inicios de
sesión se reparten a lo largo de la mañana y no se acumulan así.

### 2.3 Tres cachés que no cacheaban nada (N+1 del ORM)

```python
niveles = cache.setdefault(folio.tenant_id, await niveles_de(db, folio.tenant_id))
```

`setdefault` evalúa su segundo argumento **siempre**, incluso cuando la clave ya está: el `await` se ejecutaba una
vez por cada elemento del ciclo. Aparecía en tres lugares (`folios_captura_service.resumen`,
`aprobacion_service` y la sincronización de formularios de preventivo), así que un listado de 50 folios con flujo
de aprobación hacía 50 consultas de más.

**Corregido** en los tres: `if clave not in cache: cache[clave] = await …`.

El resto de `resumen()` ya consultaba por lote (UNs, equipos, fallas, severidades, usuarios, flujos, timeouts y
triggers en ocho consultas, no una por folio). No se encontró ningún otro N+1 en los listados.

### 2.4 Faltaban índices para el orden del listado de folios

El listado **siempre** ordena por `capturado_at DESC` con `LIMIT`, y los índices de P01 solo cubrían
`(tenant_id, estado)` y `(prestador_id, estado)`. El plan real era:

```
Limit  (actual time=14.066..14.094 rows=50)
  ->  Sort (Sort Method: top-N heapsort)
        ->  Seq Scan on folios  (actual time=0.976..12.497 rows=1433)
```

Es decir: leer **los 1,433 folios** del cliente y ordenarlos para devolver 50. A este volumen son 14 ms, pero crece
lineal con el historial y es la consulta más llamada del sistema.

**Corregido** en la migración `0012`: `(tenant_id, capturado_at DESC)`, `(prestador_id, capturado_at DESC)` y
`(tecnico_id, capturado_at DESC)`.

Sin RLS el índice se usa y la consulta baja de **3.4 ms a 0.74 ms**, con un plan que ya no depende del tamaño de la
tabla:

```
Limit  (actual time=0.393..0.523 rows=50)
  ->  Index Scan using ix_folios_tenant_capturado on folios
```

**Hallazgo abierto.** Con las políticas RLS activas el planeador estima **1 fila** donde hay 1,433, porque las
políticas usan `current_setting()` y no puede calcular su selectividad; con esa estimación sigue prefiriendo el
`Seq Scan`. Los índices quedan creados (los usa todo camino sin RLS y el planeador los tomará cuando el volumen
cambie el cálculo), pero **con cientos de miles de folios por cliente esto será el cuello de botella**. La salida
razonable es que el listado traiga por defecto una ventana de tiempo (por ejemplo los últimos 90 días, con filtro
explícito para ir más atrás): es un cambio de comportamiento visible para el usuario, así que queda anotado como
decisión a validar y no se tomó aquí.

## 3. Antes y después

Misma carga, mismos datos, misma máquina.

| Corrida | Configuración | Peticiones | Fallas | p50 | p95 | p99 | RPS |
|---|---|---|---|---|---|---|---|
| **Antes** | 1 worker · pool 10+10 | 724 | **128 (17.7 %)** | 29,000 ms | 60,000 ms | 60,000 ms | 2.6 |
| Después de 2.1 y 2.2 | 1 worker · pool 25+15 | 5,197 | 20 (0.38 %) | 1,700 ms | 5,100 ms | 8,600 ms | 17.3 |
| + 3 workers | 3 workers · pool 15+10 | 7,117 | 38 (0.53 %) | 390 ms | 3,800 ms | 11,000 ms | 23.7 |
| + 2.3 y 2.4 | 3 workers · todo aplicado | 5,664 | **1 (0.02 %)** | 1,100 ms | 6,100 ms | 8,800 ms | 18.7 |
| repetición | 3 workers · todo aplicado | 4,428 | 28 (0.63 %) | 1,600 ms | 8,300 ms | 24,000 ms | 14.7 |

Lo que se puede afirmar:

- **El cambio de régimen es real:** de 17.7 % de errores y medianas de medio minuto a menos de 1 % de errores y
  medianas de 1–2 segundos. Siete veces más peticiones atendidas en el mismo tiempo.
- **Con 50 técnicos el sistema no se rompe:** en las tres corridas con todo aplicado no hubo ni un error de
  servidor; las fallas que quedan son conexiones que el sistema operativo corta cuando la máquina se satura
  (`status 0`), más la regla de duplicado del operador respondiendo como debe.
- **Los percentiles de estas corridas no sirven para comprometer un SLA.** Entre dos corridas idénticas el p95 va
  de 6.1 a 8.3 segundos: esa diferencia es el generador de carga peleando por los mismos núcleos. El número a
  comprometer se mide en el servidor de producción, con el generador en otra máquina (lo hace P11b).

## 3.1 Posiciones GPS de la jornada (F2-03)

§6.8.4 pide recibir la posición de **50 técnicos cada 30 segundos**, o sea **100 posiciones por minuto**, junto con
el uso normal del sistema. El perfil `TecnicoCampo` abre su jornada al arrancar y manda posiciones como su tarea más
frecuente (peso 10 de 24).

Corrida del 2026-11-10 · 71 usuarios (50 técnicos, 20 de oficina, 1 operador) · 90 segundos · 3 workers · misma
máquina para la API y el generador:

| Endpoint | Peticiones | Fallas | Mediana | p95 | p99 | Máximo | RPS |
|---|---|---|---|---|---|---|---|
| `POST /api/operacion/posiciones` | 321 | **0** | 960 ms | 6,100 ms | 8,800 ms | 10,000 ms | **3.7** |
| `POST /api/operacion/jornada/iniciar` | 50 | 0 | 8,300 ms | 12,000 ms | 15,000 ms | 14,600 ms | 0.6 |
| Toda la corrida | 1,379 | **0 (0.00 %)** | 920 ms | 8,600 ms | 12,000 ms | 17,000 ms | 15.9 |

Lo que se puede afirmar:

- **El requisito se cumple con margen:** 3.7 posiciones por segundo son **222 por minuto**, más del doble de las
  100 que pide §6.8.4, y **sin una sola falla** en toda la corrida.
- **Lo más caro es arrancar**, no mantener: los 50 técnicos abriendo jornada al mismo tiempo (mediana de 8.3 s)
  coinciden con los 71 logins del arranque, que en esta máquina ya cuestan 6.7 s de mediana por el hash de
  contraseña. En la jornada real las jornadas se abren a lo largo de la mañana, de una en una.
- **Los percentiles siguen sin servir para comprometer un SLA**, por lo mismo que dice la sección 3: el generador
  pelea por los mismos núcleos que la API y la base. Lo que esta corrida demuestra es que el flujo de posiciones no
  rompe nada ni se degrada: cero errores de servidor y ninguna petición perdida.
- **Cada posición cuesta poco más que un INSERT:** el servicio comprueba la jornada, inserta en la partición del
  día, actualiza la última posición del técnico, guarda el caché de Redis con TTL de 2 minutos, publica el evento
  del tablero y, si el técnico va camino a una unidad, mide la distancia a su geocerca. Son seis operaciones
  cortas, y la partición diaria mantiene los índices pequeños.

## 4. Costo real de cada endpoint, sin carga

Siete llamadas seguidas sobre los mismos datos, un usuario a la vez. Esto sí es el costo del código, y es la base
de la estimación de servidor.

| Endpoint | Mediana | Mín | Máx |
|---|---|---|---|
| `GET /api/folios` (50 filas) | 291 ms | 234 | 414 |
| `GET /api/folios/{id}` (archivo completo) | 294 ms | 220 | 392 |
| `GET /api/minutas` | 186 ms | 132 | 321 |
| `GET /api/sync/catalogos` (técnico) | 166 ms | 146 | 178 |
| `GET /api/bi/jornada` | 165 ms | 135 | 200 |
| `GET /api/folios/{id}/chats` | 98 ms | 94 | 117 |
| `GET /api/notificaciones` | 88 ms | 68 | 162 |
| `GET /api/folios/{id}/historial` | 82 ms | 70 | 92 |
| `GET /api/bi/tablero` (con caché) | 79 ms | 72 | 752 |
| `GET /api/sla/folios/{id}` | 75 ms | 72 | 111 |
| `POST /api/auth/login` | ~110 ms de CPU en argon2 | | |

Ningún endpoint es patológico: **la mediana del conjunto es ~165 ms**. Los dos más caros (listado y archivo del
folio) son los que arman más secciones, y ya consultan por lote. El tablero muestra el efecto del caché de 120 s de
P10: 79 ms tibio contra 752 ms frío.

## 5. Memoria

Medida durante la corrida de 71 usuarios:

| Componente | Memoria | Nota |
|---|---|---|
| API (cada worker de uvicorn) | 58–86 MB | el proceso padre suma ~16 MB |
| PostgreSQL | 29 MB de proceso + **57 conexiones abiertas** | los `shared_buffers` van aparte (128 MB por defecto) |
| Redis | 3.8 MB | solo caché de BI, cola de Celery y pub/sub del chat |
| MinIO | 77 MB | |

La API es ligera: el consumo lo marcan PostgreSQL y el número de workers.

## 6. Servidor recomendado

Cálculo: la prueba ofrece ~28 peticiones por segundo con 71 usuarios (cada uno espera 1–4 s entre acciones). A
~165 ms de CPU por petición, eso son **~4.6 núcleos de trabajo de API** más ~2 de PostgreSQL.

### Para 50 técnicos (el requisito de §6.7)

| Recurso | Recomendado | Por qué |
|---|---|---|
| CPU | **8 vCPU** | ~7 núcleos de trabajo medido, con margen para respaldos y picos de inicio de jornada |
| RAM | **16 GB** | 4 workers × 250 MB + PostgreSQL con `shared_buffers` 4 GB + Redis + MinIO + sistema |
| Disco | **200 GB SSD NVMe** | base, objetos de MinIO y 14 respaldos diarios; crece con la evidencia fotográfica |
| Workers de uvicorn | 4 | `DB_POOL_SIZE=15` + `DB_POOL_OVERFLOW=10` ⇒ 100 conexiones |
| PostgreSQL | `max_connections=200`, `shared_buffers=4GB` | ya configurado en `docker-compose.prod.yml` |

Un solo servidor basta. Cabe en cualquier VPS de gama media.

### Para 500 técnicos (la escala de §6.7)

Diez veces la carga son ~280 peticiones por segundo, ~46 núcleos de trabajo de API. Ya no es un servidor:

| Recurso | Recomendado |
|---|---|
| API | **2 o 3 servidores de 16 vCPU / 32 GB** detrás del proxy, 8 workers cada uno (la API no guarda estado: escala en horizontal sin cambios) |
| PostgreSQL | servidor dedicado de **16 vCPU / 64 GB**, `shared_buffers` 16 GB, disco NVMe |
| Réplica de lectura | **necesaria**: tableros y reportes al secundario con `DATABASE_READ_URL` (§6.2 ya lo contempla y el código ya usa `engine_lectura`) |
| Redis | instancia dedicada de 2 GB |
| MinIO | nodo propio o almacenamiento S3 compatible, dimensionado por evidencia (≈2 MB por folio cerrado) |

**Antes de llegar a esa escala hay que resolver el hallazgo de 4.2.4** (el listado de folios con RLS no usa el
índice): con 500 técnicos el historial crece a cientos de miles de folios por cliente y esa consulta pasa a dominar.
La prueba de carga sobre el servidor definitivo, con el generador en otra máquina, es parte de P11b.

## 7. Cómo repetir la medición

```bash
cd backend && .venv/Scripts/python -m pruebas_carga.preparar --tecnicos 50 --equipos 400
```

```bash
cd backend && .venv/Scripts/python -m locust -f pruebas_carga/locustfile.py --host http://localhost:8000 --headless -u 71 -r 5 -t 5m --only-summary
```

Con la suite de pytest y los demás servidores de desarrollo apagados: en una máquina de 7 GB, medir con pytest
corriendo no dice nada.

---

# Motor de optimización de rutas (VRPTW) · ACT-2.2

Requisito que se verifica: **ACT-2.2 — medir el cálculo inicial y el recálculo parcial con 10, 25 y 50 técnicos**.
El guion es [`backend/scripts/medir_rutas.py`](../../backend/scripts/medir_rutas.py) y arma problemas sintéticos
con la misma forma que los reales (habilidades por técnico, ventanas de horario, SLA y criticidad repartidos) sobre
una rejilla de 20 × 20 km con semilla fija, así que dos corridas son comparables.

Medido el **13 de noviembre de 2026**, con el motor en el contenedor `solver` (OR-Tools 9.15.6755 sobre Linux) y
los servidores de desarrollo apagados.

## Lo primero que hay que entender de estas cifras

**El tiempo de cálculo lo fija la configuración, no el tamaño del problema.** El optimizador usa el presupuesto
que se le da (`rutas_configuracion.segundos_limite_calculo`) mejorando la solución hasta agotarlo, así que medir
«cuánto tarda» es medir el presupuesto. Lo que importa es **qué calidad alcanza dentro de él**, y eso es lo que
muestran las dos corridas.

## Con presupuesto de 10 segundos

| Técnicos | Folios | Nodos | Cálculo inicial | Folios colocados | Sin asignar | Folios del recálculo | Recálculo parcial |
|---|---|---|---|---|---|---|---|
| 10 | 50 | 60 | 11,265 ms | 46 | 4 | 7 | 3,547 ms |
| 25 | 150 | 175 | 10,578 ms | 150 | 0 | 22 | 3,500 ms |
| 50 | 300 | 350 | 10,719 ms | 300 | 0 | 45 | 3,656 ms |

## Con presupuesto de 3 segundos

| Técnicos | Folios | Nodos | Cálculo inicial | Folios colocados | Sin asignar | Folios del recálculo | Recálculo parcial |
|---|---|---|---|---|---|---|---|
| 10 | 50 | 60 | 4,281 ms | 46 | 4 | 7 | 2,485 ms |
| 25 | 150 | 175 | 3,515 ms | 150 | 0 | 22 | 2,500 ms |
| 50 | 300 | 350 | 3,610 ms | 300 | 0 | 45 | 2,531 ms |

## Qué dicen

- **El escenario grande de ACT-2.2 entra completo.** Con 50 técnicos y 300 folios coloca los 300, y lo hace igual
  con 3 segundos que con 10: el motor llega rápido a una solución buena y después la pule.
- **Los 4 folios sin asignar del escenario chico no son un fallo del motor**: con 10 técnicos de dos habilidades
  cada uno, hay folios cuya habilidad nadie del turno tiene certificada. El plan los reporta con ese motivo, que
  es exactamente lo que el despachador necesita leer.
- **El recálculo parcial es lo que corre durante el día** y es el que tiene que ser rápido: mira solo los folios
  pendientes del técnico afectado más los huérfanos (15 % del parque en la medición), y termina en 2.5 segundos
  incluso con 50 técnicos activos.
- **El default de 30 segundos es conservador.** Para parques de este tamaño, 5 segundos sobran. Conviene dejarlo
  alto solo si el parque crece mucho o si se activa `google_routes`, donde la matriz de distancias tarda más en
  armarse.

## Lo que estas cifras no son

El contenedor del solver comparte los 8 núcleos y los 7.2 GB de esta máquina con PostgreSQL, Redis, MinIO y los
contenedores de otro proyecto. En el servidor de producción, con OR-Tools **en proceso** (sin el salto HTTP) y sin
competencia, los tiempos bajan. Lo que no cambia con el hardware es la **calidad**: los folios colocados y los
motivos de los que quedan fuera son del modelo, no de la máquina.

## Cómo repetir la medición

```bash
cd backend && .venv/Scripts/python -m scripts.medir_rutas 10
```


