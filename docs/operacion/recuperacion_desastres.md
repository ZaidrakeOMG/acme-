# Recuperación ante desastres

Lo que pide §6.9.5 y ACT-10.1: **respaldo diario a otra región, RTO < 4 h, RPO < 1 h y una prueba trimestral
documentada**. Aquí está el procedimiento, lo que se midió y lo que falta decidir con el cliente.

---

## 1. Qué hay

| Pieza | Dónde | Qué hace |
|---|---|---|
| Respaldo | [`scripts/respaldo.sh`](../../scripts/respaldo.sh) | Vuelca la base, copia los objetos de MinIO, **verifica lo que escribió**, rota lo viejo y manda una copia fuera del servidor |
| Restauración | [`scripts/restaurar.sh`](../../scripts/restaurar.sh) | Recrea la base, carga el respaldo, **coteja los conteos** contra el registro del respaldo y repone los archivos |

Las dos cosas que las hacen confiables: el respaldo **se lee completo antes de darse por bueno**, y guarda los
conteos de nueve tablas críticas (`folios`, `folio_evidencias`, `audit_log`, `usuarios`, `tenants`, `prestadores`,
`contratos`, `minutas`, `gastos_caja_chica`) para que la restauración los compare uno por uno. Un respaldo que no
se puede restaurar no es un respaldo, y la única forma de saberlo es intentarlo.

## 2. Respaldo diario

```bash
cd /opt/acma && ./scripts/respaldo.sh
```

Cron (diario a la 01:30, antes de la purga de auditoría de las 03:50):

```bash
30 1 * * *  cd /opt/acma && ./scripts/respaldo.sh >> /var/log/acma-respaldo.log 2>&1
```

Qué deja en `RESPALDO_DIR` (por defecto `/var/backups/acma`), en `diario/`, `semanal/` o `mensual/` según el día:

| Archivo | Contenido |
|---|---|
| `acma_<fecha>.dump` | base completa, formato custom, compresión 9 |
| `acma_<fecha>.dump.indice` | salida de `pg_restore --list`, prueba de que el dump se lee |
| `acma_<fecha>.txt` | conteos de las tablas críticas y número de objetos |
| `archivos_<fecha>.tar.gz` | objetos de MinIO (evidencia, PDF, adjuntos) |

**Rotación** (configurable): 14 diarios, 8 semanales, 12 mensuales. El respaldo del día 1 de cada mes se guarda
como mensual, el del domingo como semanal.

**Copia fuera del servidor.** Con `RESPALDO_REMOTO` el guion copia todo a un destino S3 compatible
(`RESPALDO_REMOTO_URL` + llaves) o a una carpeta montada por rsync. **Sin esa variable el guion lo avisa en cada
corrida**, porque un respaldo que vive en el mismo servidor no protege contra la pérdida del servidor.

## 3. Restauración

### Ensayo (lo normal: no toca producción)

```bash
./scripts/restaurar.sh /var/backups/acma/diario/acma_2026-11-05_0130.dump --base acma_ensayo --con-archivos
```

### Recuperación real

```bash
./scripts/restaurar.sh /var/backups/acma/diario/acma_2026-11-05_0130.dump --con-archivos
```

Sobre la base de producción el guion **exige escribir el nombre de la base** para confirmar: borra todo lo que haya.

Pasos que ejecuta, en orden:

1. Lee el dump completo (`pg_restore --list`). Si no se puede leer, **no toca nada**.
2. Cierra las conexiones a la base, la borra y la crea de nuevo con `acma_owner` como dueño y las extensiones
   `postgis` y `pgcrypto`. Los roles (`acma_owner`, `acma_api`) viven en el clúster, no en la base: sobreviven.
3. Carga con `pg_restore --jobs=4` (en paralelo; es la diferencia entre minutos y horas) conservando los dueños,
   porque las tablas llevan `FORCE ROW LEVEL SECURITY` y las políticas también aplican al dueño.
4. Coteja los conteos de las nueve tablas críticas. Si alguna no coincide, **falla**: la restauración no es buena.
5. Informa la versión de esquema restaurada (`alembic_version`), que debe ser la que espera la aplicación.
6. Con `--con-archivos`, repone los objetos en MinIO.

## 4. Lo que se midió (5 de noviembre de 2026)

Base de desarrollo con el histórico de P10: **1,449 folios**, 2,661 eventos de auditoría, 143 objetos en MinIO.
Portátil de 8 núcleos y 7.2 GB, PostgreSQL 16 en Docker.

| Paso | Tiempo |
|---|---|
| **Respaldo completo** | **21 s** (dump de 3.8 MB + 143 objetos en 64 KB comprimidos) |
| Verificación del dump (2,298 objetos) | 2 s |
| Recrear la base | 8 s |
| Cargar el respaldo | **20 s** |
| Cotejar las nueve tablas | 15 s |
| Reponer los objetos de MinIO | 9 s |
| **Restauración completa** | **47 s** |

Las nueve tablas coincidieron y el esquema quedó en la versión `0012`.

### Qué significa a volumen de producción

El tiempo de carga lo domina reconstruir el esquema (146 tablas, sus políticas RLS, triggers e índices), no el
tamaño de los datos: por eso 3.8 MB tardan 20 s. Extrapolando por tamaño de dump:

| Volumen de la base | Dump aproximado | Restauración estimada |
|---|---|---|
| Hoy (demo con histórico) | 4 MB | < 1 min |
| 1 año con 50 técnicos (~100,000 folios) | ~300 MB | 10–20 min |
| 5 años con 50 técnicos | ~1.5 GB | 40–60 min |
| 1 año con 500 técnicos | ~3 GB | 1–2 h |

**El RTO de 4 h se cumple con holgura en la base.** El riesgo está en los archivos: la evidencia fotográfica pesa
~2 MB por folio cerrado, así que un año con 50 técnicos son **~200 GB en MinIO**. Reponerlos desde un disco local
son ~35 min a 100 MB/s; **traerlos desde otra región por internet puede tardar más que el RTO completo**. La salida
es restaurar primero la base (el sistema ya opera: capturar, asignar, atender) y los archivos en segundo plano, que
es el orden en que el guion los hace.

## 5. RPO: lo que falta para bajar de 1 hora

**Con el respaldo diario el RPO real es de hasta 24 horas**, no de 1. Esto es un hecho, no una aproximación: si el
servidor se pierde a las 23:00, se pierde el trabajo desde la 01:30.

Para cumplir el RPO de 1 hora de §6.9.5 hace falta **archivado continuo de WAL**, que PostgreSQL trae de fábrica:

| Opción | Cómo | RPO | Costo |
|---|---|---|---|
| **Solo respaldo diario** (lo que hay) | `respaldo.sh` por cron | hasta 24 h | ninguno |
| **WAL a MinIO o a un disco** | `archive_mode=on` + `archive_command` que copie cada segmento al almacenamiento de objetos; restauración point-in-time con `recovery_target_time` | **minutos** | ~1–3 GB más de disco al día; sin servicios de pago |
| **Réplica en caliente (streaming)** | un segundo PostgreSQL con `primary_conninfo`; se puede promover | **segundos** | un servidor más (o una instancia chica en otra región) |

**Recomendación:** activar el archivado de WAL hacia el mismo MinIO de los respaldos. No cuesta dinero, solo disco,
y lleva el RPO de 24 h a minutos. La réplica en caliente solo vale la pena si el cliente también quiere alta
disponibilidad (que el sistema no se caiga), que es otro requisito distinto de no perder datos.

No se activó aquí porque **cambia la configuración de PostgreSQL en producción y el destino del archivado depende
de la infraestructura que contrate el cliente**. Queda como decisión a validar.

## 6. Prueba trimestral

§6.9.5 pide probarlo cada trimestre. Un respaldo que nunca se restauró es una suposición.

**Procedimiento** (1 hora, sin detener el servicio):

1. Tomar el respaldo más reciente de `diario/`.
2. `./scripts/restaurar.sh <dump> --base acma_ensayo_YYYYQn --con-archivos`
3. Anotar los tiempos que imprime el guion.
4. Comprobar a mano tres cosas en la base restaurada: el último folio cerrado está completo con su evidencia, el
   `audit_log` llega hasta la fecha del respaldo, y `alembic_version` es la versión que corre en producción.
5. Borrar la base de ensayo: `DROP DATABASE acma_ensayo_YYYYQn;`
6. Llenar la fila de abajo y commitear este archivo.

### Registro de pruebas

| Fecha | Quién | Respaldo probado | Tiempo base | Tiempo archivos | Total | Conteos | Observaciones |
|---|---|---|---|---|---|---|---|
| 2026-11-05 | P11a (automatizada) | `acma_2026-11-05_1334.dump` (demo con histórico) | 20 s | 9 s | 47 s | 9/9 ✓ | Primera prueba. Base de desarrollo, no producción. |
| | | | | | | | |
| | | | | | | | |
| | | | | | | | |

## 7. Si el servidor se perdió por completo

Orden de trabajo, suponiendo servidor nuevo y vacío:

1. **Servidor y Docker** — pasos 1 a 4 de [`despliegue.md`](despliegue.md) (~20 min).
2. **Secretos** — recuperarlos del gestor de secretos del cliente y escribir el `.env`. **`CLAVE_CIFRADO` es
   insustituible**: sin ella, los secretos MFA y los archivos del Object Storage quedan ilegibles para siempre. Es
   lo primero que hay que confirmar que existe fuera del servidor.
3. **Traer el respaldo** desde la copia remota.
4. **Levantar solo PostgreSQL y MinIO**: `docker compose -f docker-compose.prod.yml up -d postgres minio`.
5. **Restaurar**: `./scripts/restaurar.sh <dump> --con-archivos`.
6. **Levantar el resto**: `docker compose -f docker-compose.prod.yml up -d`. El servicio de migraciones comprueba
   que el esquema esté al día.
7. **Verificar**: `/api/salud` en verde, iniciar sesión, abrir un folio cerrado con su evidencia, revisar que la
   auditoría siga escribiendo.
8. **Avisar a los usuarios** qué ventana de trabajo se perdió (desde la hora del respaldo).

> Los técnicos en campo **no pierden lo capturado sin red**: la cola offline de P05 vive en su dispositivo y se
> vuelve a sincronizar sola cuando la API regresa, con su `id_cliente` idempotente. Eso recupera parte de la ventana
> perdida, pero solo lo de los dispositivos que no se hayan limpiado.
