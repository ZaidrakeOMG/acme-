# Pruebas de carga de ACMA

Miden el requisito de §6.7 — **50 técnicos en simultáneo, escalable a 500+** — y los percentiles que pide ACT-1.6.
Los resultados medidos y la estimación de servidor viven en [`docs/rendimiento/resultados.md`](../../docs/rendimiento/resultados.md).

## Antes de correr

1. **Apaga la suite de pytest y los servidores de desarrollo que no uses.** Esta máquina tiene 7 GB; con pytest
   corriendo las mediciones no sirven y el equipo se queda sin memoria.
2. Levanta la infraestructura y la API:

```bash
docker compose up -d
```

```bash
cd backend && .venv/Scripts/python -m uvicorn main:app --port 8000
```

3. Aplica el seed de desarrollo y el histórico de P10 (si no están):

```bash
cd backend && .venv/Scripts/python -m scripts.seed_dev && .venv/Scripts/python -m scripts.seed_historico
```

4. Crea los usuarios y equipos de carga (idempotente):

```bash
cd backend && .venv/Scripts/python -m pruebas_carga.preparar --tecnicos 50 --equipos 300
```

`MFA_OBLIGATORIO` debe estar en `false` en el `.env` de desarrollo: el guion inicia sesión con usuario y contraseña,
y si el entorno exige TOTP se detiene avisando. En producción el MFA es obligatorio y no se mide carga ahí.

## Correr

```bash
cd backend && .venv/Scripts/python -m locust -f pruebas_carga/locustfile.py --host http://localhost:8000
```

La interfaz queda en <http://localhost:8089>. Para la medición de §6.7 se usan **71 usuarios** con un arranque de
5 por segundo: el reparto por peso deja ~50 técnicos, ~20 de oficina y 1 operador capturando.

Sin interfaz, con informe en HTML:

```bash
cd backend && .venv/Scripts/python -m locust -f pruebas_carga/locustfile.py --host http://localhost:8000 --headless -u 71 -r 5 -t 10m --html pruebas_carga/informe.html
```

## Qué hace cada perfil

| Perfil | Peso | Qué ejercita |
|---|---|---|
| `TecnicoCampo` | 50 | **`POST /api/operacion/posiciones`** (la escritura más frecuente de la jornada, F2-03), `GET /api/sync/catalogos` incremental, sus folios, detalle e historial, canales del folio y `POST /api/sync/mutaciones` con su cola offline |
| `UsuarioOficina` | 20 | listados con filtros, detalle de folio con su contador de SLA, tablero, jornada, minuta del día, cumplimiento del contrato y seguimiento |
| `OperadorCaptura` | 1 | `POST /api/folios`, la escritura más costosa: dispara clasificación, severidad, SLA y alertas |

Cada usuario simulado toma un correo distinto de la lista y conserva el token de acceso en memoria, igual que la app
después de P11a (el refresh vive en una cookie `httpOnly` y la carga no necesita renovarlo en corridas de minutos).

## Posiciones GPS (F2-03)

Cada `TecnicoCampo` **abre su jornada** al empezar (`POST /api/operacion/jornada/iniciar`) y la cierra al terminar,
porque sin jornada el servidor no acepta posiciones (§6.8.4). La tarea `mandar_posicion` tiene peso 10 de 24, así
que con `wait_time = between(1, 4)` los 50 técnicos mandan del orden de **8 posiciones por segundo** (unas 500 por
minuto): cinco veces el requisito de §6.8.4, que son 100 por minuto (50 técnicos cada 30 s). El resultado medido
está en [`docs/rendimiento/resultados.md`](../../docs/rendimiento/resultados.md).

Si una jornada se cierra sola durante la corrida (el cierre automático son 2 h sin actividad, así que no debería
pasar), el envío responde 409 y el guion lo cuenta como respuesta correcta, no como falla.

## Notas

- La corrida **escribe datos reales**: folios capturados por el operador y mensajes de chat de los técnicos. Es a
  propósito, porque medir solo lecturas no dice nada del costo de escribir. Para volver a un estado limpio se
  recrea la base de desarrollo con el seed.
- El operador consume un equipo por folio (un equipo con folio abierto responde 409 por la regla de duplicado, que
  el guion cuenta como respuesta correcta y no como falla). Con `--equipos 300` alcanza para corridas largas.
- Los nombres de las peticiones están agrupados (`GET /api/folios/{id}`) para que los percentiles salgan por
  endpoint y no por id.
