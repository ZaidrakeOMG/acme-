# Monitoreo diario

Sin servicios de pago: todo lo que hay que mirar sale de los logs de Docker, de dos endpoints y de tres consultas.
Quince minutos al día.

---

## 1. Lo primero: ¿está vivo y sano?

```bash
curl -s https://acma.unai.com.mx/api/salud
```

Devuelve `{"estado":"ok","entorno":"produccion","version":"0.1.0"}`. Es **a propósito ligera**: solo dice que el
proceso atiende. Es la que usa el healthcheck del contenedor, para que una caída de Redis no reinicie la API.

```bash
curl -s https://acma.unai.com.mx/api/salud/detalle | jq
```

Esta sí revisa las cuatro dependencias y responde **503** si alguna falla:

```json
{
  "estado": "ok",
  "dependencias": {
    "base_datos":     {"ok": true, "mensaje": "ok"},
    "redis":          {"ok": true, "mensaje": "ok"},
    "almacenamiento": {"ok": true, "mensaje": "ok"},
    "celery":         {"ok": true, "mensaje": "ok"}
  }
}
```

| Qué falla | Qué deja de funcionar | Qué hacer |
|---|---|---|
| `base_datos` | todo | `docker compose -f docker-compose.prod.yml logs postgres`; si no arranca, revisar disco |
| `redis` | notificaciones y correos en cola, caché de tableros, chat en tiempo real (los mensajes siguen guardándose) | reiniciar `redis`; la cola es persistente (AOF) y no se pierde |
| `almacenamiento` | subir y descargar evidencia, PDF y adjuntos | reiniciar `minio`; revisar espacio en disco |
| `celery` | minuta del día, alertas, SLA, preventivos nocturnos, correos | reiniciar `worker` y `beat`; las tareas pendientes se retoman |

**Si quiere una alarma automática** sin pagar nada, un cron en otra máquina basta:

```bash
*/5 * * * * curl -fsS https://acma.unai.com.mx/api/salud/detalle > /dev/null || echo "ACMA degradado" | mail -s "ACMA" soporte@cliente.com
```

## 2. Logs

En producción cada evento es **una línea JSON** (`LOG_JSON=true`), así que se filtran sin pelearse con el texto:

```bash
docker compose -f docker-compose.prod.yml logs --since 24h api | grep '"nivel":"ERROR"' | jq -r '.mensaje' | sort | uniq -c | sort -rn
```

Los errores de hoy, agrupados y contados. **Cero líneas es lo normal**: un `ERROR` en el log de la API es algo que
hay que entender, no ruido de fondo.

Rotación: la hace Docker (`max-size: 20m`, `max-file: 5` por servicio), así que los logs no llenan el disco. Son
unos 100 MB por servicio como máximo.

Lo que **nunca** aparece en los logs: contraseñas, tokens, secretos MFA ni el contenido de los archivos. Si algún
día aparece algo así, es un error y hay que reportarlo.

## 3. Las tres consultas de cada mañana

```bash
docker compose -f docker-compose.prod.yml exec postgres psql -U acma_super -d acma
```

**a) ¿La API está respondiendo bien y rápido?** (bitácora de accesos de las últimas 24 h)

```sql
SET app.rol='sistema';
SELECT codigo_respuesta, count(*), round(avg(duracion_ms)) AS ms_promedio, max(duracion_ms) AS ms_peor
  FROM audit_accesos_api WHERE created_at > now() - interval '24 hours'
 GROUP BY codigo_respuesta ORDER BY 2 DESC;
```

Qué esperar: casi todo en 200/201, algunos 401/403/404/422 (uso normal) y **ningún 500**. Un promedio por encima de
500 ms sostenido quiere decir que el servidor se quedó chico: comparar con `docs/rendimiento/resultados.md`.

**b) ¿Hay intentos de entrar que no deberían?**

```sql
SET app.rol='sistema';
SELECT evento_tipo, count(*), count(DISTINCT ip_origen) AS ips
  FROM audit_log WHERE evento_tipo LIKE 'auth.%' AND created_at > now() - interval '24 hours'
 GROUP BY evento_tipo ORDER BY 2 DESC;
```

Muchos `auth.login_fallido` desde pocas IP es alguien probando contraseñas; ACMA ya bloquea a los 5 intentos en 10
minutos (`auth.usuario_bloqueado`, `auth.limite_ip`) y avisa al superadmin, pero vale saberlo. Muchos desde muchas
IP distintas merece revisar el firewall. `auth.refresh_reuso_detectado` significa que alguien reusó un token de
sesión: ACMA revoca la familia completa, y si aparece seguido hay que investigarlo.

**c) ¿Las tareas de fondo dejaron huella?**

```sql
SET app.rol='sistema';
SELECT 'minutas' AS tarea, max(created_at) AS ultima_vez FROM minutas
UNION ALL SELECT 'alertas', max(created_at) FROM alertas_historial
UNION ALL SELECT 'folios preventivos', max(capturado_at) FROM folios WHERE tipo_folio = 'preventivo'
UNION ALL SELECT 'contador de SLA', max(updated_at) FROM folio_sla;
```

Ojo con cómo se lee: estas tareas **solo escriben cuando hay algo que hacer**, así que una fecha vieja puede ser
normal (un día sin alertas, por ejemplo). La señal firme de que el worker está vivo es `celery` en
`/api/salud/detalle`; esta consulta sirve para notar que algo lleva *varios* días sin moverse. Las minutas se
generan todos los días hábiles a la hora configurada por cliente: ahi sí, más de un día hábil de atraso es un
problema.

## 4. Espacio en disco

Es lo que de verdad tumba un servidor de producción, y crece solo:

```bash
df -h /
```

```bash
docker system df -v | head -20
```

Qué crece y a qué ritmo (medido en `docs/rendimiento/resultados.md`):

| Qué | Ritmo | Nota |
|---|---|---|
| Evidencia en MinIO | **~2 MB por folio cerrado** | lo que más crece; con 50 técnicos son ~200 GB al año |
| Base de datos | ~2.6 KB por folio | ~300 MB al año con 50 técnicos |
| `audit_accesos_api` | se purga sola | 90 días las llamadas normales, 1 año los errores |
| Respaldos | 14 diarios + 8 semanales + 12 mensuales | se rotan solos |
| Logs de Docker | tope de ~100 MB por servicio | rotación configurada |

**Avisar al cliente cuando el disco pase del 70 %.** Al 90 % PostgreSQL deja de aceptar escrituras y el sistema se
detiene: la evidencia de 5 años (§6.7) no se puede borrar para hacer espacio.

## 5. Certificado HTTPS

Caddy lo renueva solo. Para confirmarlo:

```bash
echo | openssl s_client -connect acma.unai.com.mx:443 2>/dev/null | openssl x509 -noout -dates
```

Si quedan menos de 20 días y no se renovó, revisar `docker compose logs proxy`: casi siempre es que el puerto 80
quedó cerrado (Let's Encrypt lo necesita para validar).

## 6. Cada semana

- Revisar que el **respaldo de anoche existe y pesa lo esperado**: `ls -lh /var/backups/acma/diario/`.
- Confirmar que la **copia en otra región** está al día.
- Mirar las alertas abiertas en la propia aplicación (panel de alertas): son del negocio, no del servidor, pero una
  acumulación avisa de que algo no se está atendiendo.

## 7. Cada trimestre

- **Probar la restauración.** El procedimiento y la tabla donde se anota están en
  [`recuperacion_desastres.md`](recuperacion_desastres.md). Un respaldo que nunca se restauró es una suposición.
- Correr la auditoría de dependencias y anotar el resultado en
  [`../seguridad/checklist_iso27001.md`](../seguridad/checklist_iso27001.md):

```bash
cd backend && .venv/Scripts/python -m pip_audit
```

```bash
cd frontend && npm audit
```

## 8. Lo que ACMA no vigila

Para que nadie lo dé por hecho: **no hay métricas históricas de servidor** (CPU y memoria en el tiempo), ni traza
distribuida, ni alertas automáticas por correo salvo el cron del punto 1. Nada de eso necesita un servicio de pago
—Prometheus y Grafana son libres— pero son infraestructura aparte y quedan para Fase 2. Lo de aquí alcanza para
operar un servidor con 50 técnicos y detectar un problema el mismo día.
