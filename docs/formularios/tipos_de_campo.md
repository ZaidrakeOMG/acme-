# Motor de formularios — contrato de los 22 tipos de campo (ACT-4.1)

Referencia: §4.3 y §6.8.3c del Documento de Diseño v2.5. Implementación: `backend/schemas/formularios.py` (Pydantic) y
`frontend/src/types/formularios.ts` (TypeScript), con el motor de reglas en `backend/services/formularios/validacion.py`
y `frontend/src/services/formularios/validacion.ts` (idénticos: toda regla se cambia en ambos).

## Estructura del esquema

```json
{ "version_contrato": 1, "secciones": [ { "clave": "...", "titulo": "...", "descripcion": null, "campos": [ CAMPO ] } ] }
```

Cada **campo**: `clave` (única, `^[a-z][a-z0-9_]{0,59}$`), `tipo` (uno de los 22), `etiqueta`, `ayuda`, `obligatorio`,
`valor_defecto` (solo tipos que lo admiten), `config` (parámetros del tipo), `condiciones[]` y `fuente_opciones`
(solo tipos de selección).

### Lógica condicional

`{ "campo_origen", "operador", "valor", "accion" }` con operadores `igual`, `distinto`, `contiene`, `vacio`, `no_vacio`,
`en_rango` (`valor = [min, max]`; también fechas ISO) y `opcion_seleccionada`; acción `mostrar` u `ocultar`.

Reglas de evaluación (cliente y servidor, en orden de documento):
1. Sin condiciones → visible. Con condiciones: parte oculto si alguna es `mostrar`, visible si todas son `ocultar`.
2. Cada condición que se cumple fija la visibilidad según su acción; la última que se cumple decide.
3. El valor de un campo oculto cuenta como vacío para las condiciones siguientes y se elimina de la respuesta
   normalizada. Un campo oculto no es obligatorio ni se valida.

### Fuente de opciones

- Fija: `{ "origen": "fija", "opciones": [ { "valor", "etiqueta", "color"?, "grupo"?, "descripcion"? } ] }`.
- Catálogo: `{ "origen": "catalogo", "catalogo", "catalogo_personalizado_id"?, "filtro_contexto": true, "campo_padre"? }`.
  Catálogos: `equipos_tenant` (padre: UN), `unidades_negocio`, `tecnicos_prestador`, `tipos_falla` (padre: familia),
  `tipos_equipo` (padre: familia), `familias_equipo`, `materiales` (vacío hasta P09), `proveedores_externos` (vacío hasta
  P08), `catalogo_personalizado` (padre: opción padre). `GET /api/formularios/opciones` los resuelve con el contexto del
  folio (`tenant_id`, `un_id`, `equipo_id`) y `padre` para la cascada.

### Respuesta y evidencias

`respuestas_json` guarda por `clave` el valor normalizado. Las evidencias (fotos, firma, dibujo, archivos, audio) viven en
`formulario_evidencias` y el valor del campo en la respuesta es `{ "evidencias": n }`. Los tipos calculados
(`concatenacion`, `matematicas_tiempo`, `sello_fecha_hora`) se recalculan en el servidor al enviar: el valor del
cliente se descarta. Una respuesta enviada es inmutable (triggers en base de datos).

---

## Tipos

| # | Identificador | Nombre §4.3 | Valor por defecto | Opciones | Evidencia |
|---|---|---|---|---|---|
| 1 | `si_no` | Sí / No | sí | — | — |
| 2 | `opcion_multiple` | Opción múltiple | sí | sí | — |
| 3 | `texto` | Texto libre | sí (sugerido) | — | — |
| 4 | `texto_amplio` | Campo amplio de texto | sí (sugerido) | — | — |
| 5 | `fotografia` | Fotografía | — | — | foto |
| 6 | `firma` | Firma | — | — | firma |
| 7 | `dibujo` | Dibujo en pantalla | — | — | dibujo |
| 8 | `radio` | Botón de radio | sí | sí | — |
| 9 | `boton_grupo` | Botón de grupo (color) | sí | sí (fija, 2–5) | — |
| 10 | `lista_desplegable` | Lista desplegable | sí | sí | — |
| 11 | `seleccion_multiple` | Selección múltiple | sí | sí | — |
| 12 | `concatenacion` | Concatenación de secuencias | — | — | — |
| 13 | `archivo` | Carga de archivo | — | — | archivo |
| 14 | `escaner` | Escáner código de barras / QR | — | — | — |
| 15 | `etiqueta_info` | Etiqueta de información | — | — | — |
| 16 | `audio` | Grabación de audio | — | — | audio |
| 17 | `fecha_hora` | Selector de fecha y hora | sí (hoy + N) | — | — |
| 18 | `sello_fecha_hora` | Sello de fecha y hora | — | — | — |
| 19 | `matematicas_tiempo` | Matemáticas basadas en tiempo | — | — | — |
| 20 | `slider` | Slider numérico | sí | — | — |
| 21 | `encuesta_satisfaccion` | Encuesta de satisfacción | — | — | — |
| 22 | `geolocalizacion` | Geolocalización automática | — | — | — |

### 1. `si_no`
- **Comportamiento:** dos botones excluyentes con etiquetas configurables.
- **config:** `etiqueta_si`, `etiqueta_no`, `modo_defecto` (`sin_defecto` | `con_defecto`; con `con_defecto`, `valor_defecto` debe ser `true`/`false`).
- **Validación:** booleano (acepta `"true"`/`"false"`); obligatorio → debe elegirse.
- **Guarda:** `true` | `false`.
- **Límite:** condiciones con `igual` comparan con `true`/`false`.

### 2. `opcion_multiple`
- **Comportamiento:** casillas; una o varias.
- **config:** `min_selecciones` (≥0), `max_selecciones` (≥1 o null). Fuente fija o catálogo (con cascada).
- **Validación:** lista sin repetidos, entre mín y máx; valores dentro de la fuente (catálogo: solo si el servidor puede resolverlo).
- **Guarda:** `["valor", ...]`.
- **Límite:** `min_selecciones > 0` obliga aunque `obligatorio` sea falso.

### 3. `texto` / 4. `texto_amplio`
- **config:** `longitud_min`, `longitud_max` (texto ≤ 20 000; amplio ≤ 50 000), `formato` (`libre` | `numeros` | `letras` | `regex`), `regex`, `mensaje_formato`; amplio además `lineas_visibles`.
- **Validación:** longitud tras recortar espacios; `numeros` = `^-?\d+([.,]\d+)?$`; `letras` = letras y espacios (con acentos); `regex` = coincidencia completa.
- **Guarda:** cadena recortada. **Valor por defecto:** texto sugerido (placeholder); no se guarda si el usuario no escribe.
- **Condiciones típicas:** `vacio`, `no_vacio`, `contiene`.

### 5. `fotografia`
- **config:** `origen` (`camara` | `camara_galeria`), `calidad` {`tamano_minimo_kb`, `resolucion_minima_ancho`, `resolucion_minima_alto`, `compresion_maxima_pct`} (null = default global de `calidad_foto_defaults`), `cantidad_min`, `cantidad_max` (≤20), `etiquetas_secuencia[]` (nombre y orden de cada foto), `permitir_anotacion`, `vista_previa_confirmacion`.
- **Validación en servidor al subir:** tamaño, resolución (con orientación EXIF) y compresión (calidad JPEG estimada por la tabla de cuantización: `compresion = 100 − calidad`); EXIF `DateTimeOriginal` y GPS se extraen; `hash_sha256`. Rechazo: 422 `FOTO_RECHAZADA` con los motivos.
- **Al enviar:** `cantidad_min ≤ fotos ≤ cantidad_max`.
- **Guarda:** `{ "evidencias": n }` + filas en `formulario_evidencias`; anotaciones en `anotaciones_json` y la imagen compuesta en `archivo_anotado_key` (el original no se toca).
- **Límite:** PNG/WebP no reportan compresión (no se evalúa).

### 6. `firma`
- **Comportamiento:** lienzo; obligatorio por definición; no acepta lienzo vacío (el cliente lo verifica; el servidor exige la evidencia).
- **config:** `pantalla_completa`, `texto_conformidad`.
- **Guarda:** `{ "evidencias": 1, "timestamp": ISO }` (timestamp del trazo).
- **Límite:** una sola firma por campo (409 `FIRMA_DUPLICADA`); para refirmar se elimina la anterior mientras esté en progreso.

### 7. `dibujo`
- **config:** `imagen_referencia` {`tipo`: `ninguna` | `url` | `campo_fotografia`, `valor`}, `permitir_color`, `permitir_grosor`.
- **Validación:** evidencia `dibujo` si es obligatorio. La referencia a `campo_fotografia` debe apuntar a un campo `fotografia`.
- **Guarda:** `{ "evidencias": n }`.

### 8. `radio`
- **config:** `disposicion` (`vertical` | `horizontal`). Fuente fija o catálogo.
- **Validación:** un valor dentro de la fuente. **Guarda:** `"valor"`.

### 9. `boton_grupo`
- **config:** `tamano` (`grande` | `normal`). Fuente **fija** con 2 a 5 opciones, cada una con `color`.
- **Guarda:** `"valor"`.

### 10. `lista_desplegable`
- **config:** `busqueda`, `seleccion` (`unica` | `multiple`), `disponible_offline` (P05 descarga el catálogo).
- **Guarda:** `"valor"` o `["valor", ...]` si es múltiple.

### 11. `seleccion_multiple`
- **config:** los de `opcion_multiple` más `contador_por_opcion`, `contador_min`, `contador_max`, `grupos_colapsables` (usa `grupo` de cada opción), `plantillas_combinaciones[]` {`nombre`, `valores[]`, `cantidades{}`}.
- **Guarda:** `["valor", ...]` o, con contador, `[{ "valor", "cantidad" }, ...]`.
- **Validación:** cantidades enteras entre `contador_min` y `contador_max`.

### 12. `concatenacion`
- **config:** `partes[]` {`tipo`: `texto` | `campo`, `valor`}, `separador`, `mayusculas`.
- **Cálculo (servidor):** une las partes; para campos de opciones fijas usa la etiqueta; listas se unen con `, `.
- **Guarda:** cadena. No editable por el usuario; el valor del cliente se descarta.
- **Límite:** un campo origen oculto aporta cadena vacía.

### 13. `archivo`
- **config:** `tipos_permitidos[]` (`pdf`, `imagen`, `hoja_calculo`, `documento`, `cualquiera`), `tamano_maximo_mb` (≤100), `cantidad_max` (≤20), `permitir_anotacion_imagen`.
- **Validación al subir:** MIME permitido, tamaño, cantidad. **Guarda:** `{ "evidencias": n }`.

### 14. `escaner`
- **config:** `formatos[]` (`qr`, `ean`, `code128`, `datamatrix`), `precargar_equipo` (si el código coincide con un equipo, el cliente muestra su contexto), `permitir_captura_manual`.
- **Validación:** cadena ≤ 500. **Guarda:** el texto decodificado. Puede ser parte de una `concatenacion`.

### 15. `etiqueta_info`
- **config:** `contenido` (formato simple: `**negritas**`, listas con `- `), `icono` (`ninguno` | `info` | `advertencia` | `peligro`), `enlace` {`url`, `texto`}.
- **No produce datos**: se elimina de la respuesta. Recibe condiciones.

### 16. `audio`
- **config:** `duracion_maxima_seg` (5–900), `transcripcion` (stub en Fase 1: la evidencia queda con `anotaciones_json.transcripcion = {estado: "pendiente"}`).
- **Validación:** MIME `audio/*`; volver a grabar sustituye la nota. **Guarda:** `{ "evidencias": n }`.

### 17. `fecha_hora`
- **config:** `modo` (`fecha` | `hora` | `ambos`), `fecha_minima`, `fecha_maxima` (ISO o `hoy`, `hoy+N`, `hoy-N`), `intervalo_minutos` (1–60), `defecto_hoy_mas_dias`, `vinculo` {`rol`: `inicio` | `fin`, `campo_par`}.
- **Validación:** formato `AAAA-MM-DD`, `HH:MM` o `AAAA-MM-DDTHH:MM`; rango; minutos múltiplos del intervalo; con `rol = fin`, no anterior al campo par.
- **Guarda:** cadena ISO según el modo.

### 18. `sello_fecha_hora`
- **config:** `trigger` (`al_abrir` | `al_llegar_seccion` | `al_enviar` | `por_condicion`).
- **Cálculo (servidor):** `al_abrir` = `iniciado_at` de la respuesta; `al_enviar` = `enviado_at`; `al_llegar_seccion` y `por_condicion` = hora del servidor al recibir por primera vez un valor del cliente para ese campo (guardado parcial). No lo modifica el usuario; no dispara condiciones.
- **Guarda:** ISO.

### 19. `matematicas_tiempo`
- **config:** `inicio` y `fin` {`origen`: `campo` (fecha_hora o sello) | `sistema` (`captura_folio`, `asignacion`, `autorizacion`, `fecha_programada`, `ahora`)}, `unidad` (`minutos` | `horas` | `dias` | `compuesto`).
- **Cálculo (servidor):** diferencia en minutos; los timestamps de sistema los pasa P04 en `contexto.sistema`.
- **Guarda:** `{ "minutos": n, "unidad", "texto": "2h 35min" }`. Condiciones `en_rango` usan `minutos`.

### 20. `slider`
- **config:** `minimo`, `maximo`, `incremento`, `etiqueta_min`, `etiqueta_max`, `modo_rango`.
- **Validación:** dentro del rango y múltiplo del incremento; en modo rango `[desde, hasta]` con `desde ≤ hasta`.
- **Guarda:** número o `[a, b]`.

### 21. `encuesta_satisfaccion`
- **config:** `modalidad` (`estrellas` 1–5 | `numerica` 1–10 | `emojis` 1–3/1–5), `escala_max`, `etiqueta_min`, `etiqueta_max`, `umbral_bajo` (referencia para condiciones de calificación baja: `en_rango [1, umbral]`).
- **Validación:** entero entre 1 y `escala_max`; obligatoriedad configurable con `obligatorio`.
- **Guarda:** entero.

### 22. `geolocalizacion`
- **config:** `radio_ajuste_m` (0–2000), `geofencing_radio_m` (10–20000), `alertar_fuera_un`.
- **Validación:** `lat`/`lng` en rango; si `ajustada`, la distancia entre la coordenada original y la ajustada no puede exceder `radio_ajuste_m`.
- **Al enviar (servidor):** distancia a `unidades_negocio.ubicacion` con PostGIS; si supera `geofencing_radio_m` y `alertar_fuera_un`, dispara `GEOLOCALIZACION_FUERA_DE_UN`; si `ajustada`, registra `formularios.geolocalizacion_ajustada` en `audit_log`. El resultado queda en `contexto_json.geofencing`.
- **Guarda:** `{ "lat", "lng", "lat_original", "lng_original", "ajustada", "precision_m" }` (registro dual).
- **Límite:** sin `un_id` en la respuesta no hay geofencing.
