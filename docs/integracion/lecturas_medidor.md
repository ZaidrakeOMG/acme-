# Enviar lecturas de medidor a ACMA

Este documento es para quien integra un **SCADA, un PLC, un historiador o un ERP** con ACMA. Describe las dos
formas de cargar lecturas de medidor sin que una persona las capture: el archivo y la API.

ACMA **no se conecta a ningún sistema de terceros**: no hay agentes, ni colectores, ni credenciales de tu sistema
guardadas aquí. Siempre eres tú quien manda las lecturas.

> Módulo: medidores de activos (§6.9.2 del Documento de Diseño v2.5). Bloque F2-04.

---

## 1. Por archivo (CSV o Excel)

En **Catálogos → Importar → Lecturas de medidor**. Es el camino para una carga histórica o para un sistema que ya
exporta un reporte periódico.

| Columna | Obligatoria | Qué lleva | Ejemplo |
|---|---|---|---|
| `equipo_codigo` | sí | Código del equipo en ACMA | `EQ-0001` |
| `tipo_medidor` | sí | Nombre del tipo de medidor; el equipo debe tenerlo dado de alta | `Horas de operacion` |
| `valor` | sí | Lectura del marcador, con punto decimal | `1520.5` |
| `fecha` | sí | `AAAA-MM-DD` o `AAAA-MM-DD HH:MM` (sin zona = UTC) | `2026-11-10 07:30` |

La importación muestra **vista previa con errores por fila** antes de aplicar nada: una fila mala no detiene a las
demás. Las filas repetidas (mismo equipo, mismo medidor y misma fecha y hora, con el mismo valor) se marcan como
duplicadas y no se cargan dos veces, así que puedes reenviar el mismo archivo sin miedo.

Hay plantilla descargable en la misma pantalla.

---

## 2. Por API (`POST /api/medidores/lecturas/lote`)

Para un sistema que manda lecturas solo, cada hora o cada turno.

### Llave de API

La crea el **Admin empresa** en *Medidores → Llaves de API*. Se muestra **una sola vez**: ACMA guarda únicamente su
hash, así que si se pierde hay que revocarla y crear otra. Una llave:

- sirve **solo** para registrar lecturas de medidor (`medidores.lecturas`): con ella no se consulta nada más, no se
  crean folios y no se leen datos de otros módulos;
- está atada a **un cliente** y solo alcanza los equipos de ese cliente;
- se revoca en cualquier momento, sin borrarla, para que la auditoría siga apuntando a algo;
- deja registro de cada uso (`medidores.lote_por_llave` en la bitácora, con el prefijo de la llave y el conteo de
  filas aplicadas y rechazadas) y guarda su último uso y cuántas veces se usó.

### Petición

```http
POST /api/medidores/lecturas/lote
X-ACMA-Llave: acma_XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
Content-Type: application/json

{
  "lecturas": [
    {"equipo_codigo": "EQ-0001", "tipo_medidor": "Horas de operacion", "valor": 1520.5, "timestamp": "2026-11-10T07:30:00Z"},
    {"equipo_codigo": "EQ-0004", "tipo_medidor": "Ciclos",             "valor": 48210,  "timestamp": "2026-11-10T07:30:00Z"}
  ]
}
```

Hasta **1,000 lecturas por petición**. `timestamp` es la hora de la medición en tu sistema; si la omites se usa la
hora de llegada. No puede estar en el futuro.

### Respuesta

```json
{
  "total": 2, "aplicadas": 1, "duplicadas": 0, "en_revision": 1, "rechazadas": 0,
  "resultados": [
    {"indice": 0, "estado": "aplicada", "lectura_id": "…", "motivo": "", "folios_generados": 1},
    {"indice": 1, "estado": "en_revision", "lectura_id": "…", "motivo": "El salto de 9000 ciclos en 1 día es más de 3× lo esperado…", "folios_generados": 0}
  ]
}
```

Cada fila se resuelve por separado, así que una mala no tira el lote. Estados posibles por fila:

| Estado | Qué pasó | Qué hacer |
|---|---|---|
| `aplicada` | La lectura entró y movió el medidor. `folios_generados` dice si disparó un preventivo. | Nada. |
| `duplicada` | Ya existía esa misma medición del mismo instante. | Nada: es el caso normal de un reintento. |
| `en_revision` | La lectura retrocedió o saltó más de lo esperado. **No mueve el medidor ni dispara planes** hasta que el Despachador o el Admin prestador la apruebe. | Revisa el dato en tu sistema; si el marcador se reinició o se cambió el medidor, regístralo en ACMA. |
| `rechazada` | El equipo o el medidor no existen, o el dato es inválido (negativo, fecha futura). | Corrige y reenvía solo esa fila. |

### Reintentos

La petición es **idempotente por (medidor, `timestamp`, `valor`)**: reenviar el mismo lote no duplica lecturas.
Ante un error de red, reenvía el lote completo.

### Errores de la petición completa

| Código HTTP | `codigo` | Significado |
|---|---|---|
| 401 | `LLAVE_REQUERIDA` | Falta la cabecera `X-ACMA-Llave`. |
| 401 | `LLAVE_INVALIDA` | La llave no existe. |
| 401 | `LLAVE_REVOCADA` | La llave fue revocada. |
| 403 | `LLAVE_SIN_PERMISO` | La llave no tiene el permiso `medidores.lecturas`. |
| 422 | — | El cuerpo no cumple el formato (lista vacía, más de 1,000 filas, valor negativo). |

---

## 3. Qué hace ACMA con cada lectura

1. **Acumulado.** Guarda el valor del marcador y además el **acumulado real** del equipo, que corrige reinicios del
   marcador y cambios de medidor. Los planes de mantenimiento usan el acumulado, nunca el marcador.
2. **Validación.** Una lectura menor que la anterior, o con un salto mayor a *N* veces el incremento diario esperado
   (*N* se configura por tipo de medidor, por defecto 3), queda **en revisión** y dispara la alerta
   `MEDIDOR_LECTURA_ANOMALA`. Una fecha futura se rechaza.
3. **Corrección de los estimados.** Si ese medidor tenía lecturas estimadas, la lectura real las corrige y ACMA
   recalcula el incremento real promedio del equipo.
4. **Planes por uso.** Si con esa lectura un plan alcanza su umbral o su intervalo, el folio preventivo se genera
   **en ese momento**, sin esperar a la noche. Nunca nace un segundo folio del mismo plan mientras el anterior siga
   abierto.
5. **Aviso anticipado.** Cuando falta menos del 10 % del intervalo (configurable), el Despachador recibe
   `MEDIDOR_PROXIMO_PM` con la fecha estimada en que se alcanzará.

---

## 4. Si un medidor deja de reportar

Un medidor que no se estima y lleva más de 30 días sin lectura (configurable) dispara `MEDIDOR_SIN_LECTURA` al
Despachador y al Admin prestador: los planes por uso de ese equipo están ciegos mientras eso pase.
