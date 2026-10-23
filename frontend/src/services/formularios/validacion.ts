/**
 * Motor de reglas de formularios: visibilidad por condiciones, validación por tipo y valores calculados.
 * Espejo exacto de backend/services/formularios/validacion.py; cualquier cambio se replica allá.
 */
import { TIPOS_CALCULADOS, TIPOS_SIN_DATO, camposDe, campoDe, type Campo, type Condicion, type EsquemaFormulario } from '../../types/formularios'

export type Respuestas = Record<string, unknown>
export interface ErrorValidacion { campo: string; mensaje: string }
export interface EvidenciaResumen { tipo: string; id?: string; etiqueta?: string | null }

export interface ContextoValidacion {
  evidencias?: Record<string, EvidenciaResumen[]>
  sistema?: Record<string, string>
  sellos?: Record<string, string>
  iniciadoAt?: Date
  enviadoAt?: Date
  hoy?: Date
  /** valores válidos de un campo enlazado a catálogo; undefined/null = no verificable */
  resolutor?: (campo: Campo) => string[] | null | undefined
}

const RE_NUMEROS = /^-?\d+([.,]\d+)?$/
const RE_LETRAS = /^[A-Za-zÁÉÍÓÚáéíóúÑñÜü\s]+$/
const RE_FECHA = /^\d{4}-\d{2}-\d{2}$/
const RE_HORA = /^\d{2}:\d{2}$/
const RE_FECHA_HORA = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/

export function vacio(v: unknown): boolean {
  if (v === null || v === undefined) return true
  if (typeof v === 'string') return v.trim() === ''
  if (Array.isArray(v)) return v.length === 0
  if (typeof v === 'object') return Object.keys(v as object).length === 0
  return false
}

function escalar(v: unknown): string {
  if (typeof v === 'boolean') return v ? 'true' : 'false'
  if (typeof v === 'number') return Number.isInteger(v) ? String(v) : String(v).replace(/0+$/, '').replace(/\.$/, '')
  return String(v)
}

function numero(v: unknown): number | null {
  if (typeof v === 'boolean') return null
  if (typeof v === 'number') return Number.isFinite(v) ? v : null
  if (typeof v === 'string') {
    const n = Number(v.replace(',', '.'))
    return Number.isNaN(n) || v.trim() === '' ? null : n
  }
  if (Array.isArray(v) && v.length && typeof v[0] !== 'object') return numero(v[0])
  return null
}

function valoresDe(v: unknown): string[] {
  if (Array.isArray(v)) return v.map((x) => escalar(typeof x === 'object' && x !== null ? (x as { valor: unknown }).valor : x))
  if (vacio(v)) return []
  return [escalar(v)]
}

export function cumple(operador: Condicion['operador'], valorCond: unknown, v: unknown): boolean {
  switch (operador) {
    case 'vacio': return vacio(v)
    case 'no_vacio': return !vacio(v)
    case 'igual':
      if (Array.isArray(v)) {
        const esperado = (Array.isArray(valorCond) ? valorCond : [valorCond]).map(escalar)
        const actual = valoresDe(v)
        return actual.length === esperado.length && actual.every((x, i) => x === esperado[i])
      }
      return !vacio(v) && escalar(v).toLowerCase() === escalar(valorCond).toLowerCase()
    case 'distinto': return !cumple('igual', valorCond, v)
    case 'contiene':
      if (vacio(v)) return false
      if (Array.isArray(v)) return valoresDe(v).includes(escalar(valorCond))
      return escalar(v).toLowerCase().includes(escalar(valorCond).toLowerCase())
    case 'opcion_seleccionada': return valoresDe(v).includes(escalar(valorCond))
    case 'en_rango': {
      if (vacio(v)) return false
      const [minimo, maximo] = valorCond as [unknown, unknown]
      if (typeof v === 'string' && (RE_FECHA.test(v) || RE_FECHA_HORA.test(v) || RE_HORA.test(v))) return String(minimo) <= v && v <= String(maximo)
      let x: unknown = v
      if (typeof v === 'object' && v !== null && 'minutos' in v) x = (v as { minutos: unknown }).minutos
      const n = numero(x)
      return n !== null && Number(minimo) <= n && n <= Number(maximo)
    }
    default: return false
  }
}

/** Claves visibles, evaluadas en orden de documento. */
export function visibilidad(esquema: EsquemaFormulario, respuestas: Respuestas): Set<string> {
  const visibles = new Set<string>()
  const ocultos = new Set<string>()
  for (const campo of camposDe(esquema)) {
    if (!campo.condiciones?.length) {
      visibles.add(campo.clave)
      continue
    }
    let visible = !campo.condiciones.some((c) => c.accion === 'mostrar')
    for (const cond of campo.condiciones) {
      const origen = ocultos.has(cond.campo_origen) ? null : respuestas[cond.campo_origen]
      if (cumple(cond.operador, cond.valor, origen)) visible = cond.accion === 'mostrar'
    }
    ;(visible ? visibles : ocultos).add(campo.clave)
  }
  return visibles
}

// ------------------------------------------------------------------- fechas

function fechaLocal(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

export function resolverFecha(expr: string | null | undefined, hoy: Date): string | null {
  if (!expr) return null
  const m = /^hoy([+-]\d+)?$/.exec(expr.trim())
  if (m) {
    const d = new Date(hoy)
    d.setDate(d.getDate() + Number(m[1] ?? 0))
    return fechaLocal(d)
  }
  return expr
}

function parseIso(v: string): Date | null {
  if (RE_FECHA_HORA.test(v)) return new Date(`${v}:00`)
  if (RE_FECHA.test(v)) return new Date(`${v}T00:00:00`)
  if (RE_HORA.test(v)) return new Date(`1900-01-01T${v}:00`)
  const d = new Date(v)
  return Number.isNaN(d.getTime()) ? null : d
}

export function haversineM(lat1: number, lng1: number, lat2: number, lng2: number): number {
  const r = 6371000
  const p1 = (lat1 * Math.PI) / 180
  const p2 = (lat2 * Math.PI) / 180
  const dp = ((lat2 - lat1) * Math.PI) / 180
  const dl = ((lng2 - lng1) * Math.PI) / 180
  const a = Math.sin(dp / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2
  return 2 * r * Math.asin(Math.sqrt(a))
}

export function formatearDuracion(minutos: number, unidad: string): string {
  if (unidad === 'minutos') return `${minutos} min`
  if (unidad === 'horas') return `${(minutos / 60).toFixed(2)} h`
  if (unidad === 'dias') return `${(minutos / 1440).toFixed(2)} d`
  const abs = Math.abs(minutos)
  const m = abs % 60
  const hTotal = Math.floor(abs / 60)
  const d = Math.floor(hTotal / 24)
  const h = hTotal % 24
  const partes = [d ? `${d}d` : '', h || d ? `${h}h` : '', `${m}min`].filter(Boolean)
  return (minutos < 0 ? '-' : '') + partes.join(' ')
}

// -------------------------------------------------------------- validación

function cuentaEvidencias(ctx: ContextoValidacion, clave: string, tipo?: string): number {
  return (ctx.evidencias?.[clave] ?? []).filter((e) => !tipo || e.tipo === tipo).length
}

function opcionesValidas(campo: Campo, ctx: ContextoValidacion): string[] | null {
  if (campo.fuente_opciones?.origen === 'fija') return campo.fuente_opciones.opciones.map((o) => o.valor)
  return ctx.resolutor?.(campo) ?? null
}

type Resultado = [unknown, string | null]

function validarCampo(campo: Campo, v: unknown, ctx: ContextoValidacion, respuestas: Respuestas): Resultado {
  const t = campo.tipo
  const cfg = campo.config as Record<string, never> & Campo['config']
  const oblig = campo.obligatorio

  if (t === 'si_no') {
    if (vacio(v)) return [null, oblig ? 'Selecciona una opción' : null]
    if (typeof v === 'string' && ['true', 'false'].includes(v.toLowerCase())) v = v.toLowerCase() === 'true'
    if (typeof v !== 'boolean') return [null, 'Valor inválido']
    return [v, null]
  }

  if (t === 'texto' || t === 'texto_amplio' || t === 'escaner') {
    if (vacio(v)) return [null, oblig ? 'Este campo es obligatorio' : null]
    if (typeof v !== 'string') return [null, 'Debe ser texto']
    const s = v.trim()
    if (t === 'escaner') return s.length <= 500 ? [s, null] : [null, 'Código demasiado largo']
    if (s.length < (cfg.longitud_min ?? 0)) return [null, `Mínimo ${cfg.longitud_min} caracteres`]
    if (s.length > (cfg.longitud_max ?? Infinity)) return [null, `Máximo ${cfg.longitud_max} caracteres`]
    if (cfg.formato === 'numeros' && !RE_NUMEROS.test(s)) return [null, cfg.mensaje_formato || 'Solo se permiten números']
    if (cfg.formato === 'letras' && !RE_LETRAS.test(s)) return [null, cfg.mensaje_formato || 'Solo se permiten letras']
    if (cfg.formato === 'regex' && cfg.regex && !new RegExp(`^(?:${cfg.regex})$`).test(s)) return [null, cfg.mensaje_formato || 'El formato no es válido']
    return [s, null]
  }

  if (t === 'radio' || t === 'boton_grupo' || t === 'lista_desplegable') {
    const multiple = t === 'lista_desplegable' && cfg.seleccion === 'multiple'
    const valores = valoresDe(v)
    if (!valores.length) return [null, oblig ? 'Selecciona una opción' : null]
    if (!multiple && valores.length > 1) return [null, 'Solo se permite una opción']
    const validas = opcionesValidas(campo, ctx)
    if (validas) {
      const malas = valores.filter((x) => !validas.includes(x))
      if (malas.length) return [null, `Opción no válida: ${malas.join(', ')}`]
    }
    return [multiple ? valores : valores[0], null]
  }

  if (t === 'opcion_multiple' || t === 'seleccion_multiple') {
    const valores = valoresDe(v)
    const min = cfg.min_selecciones ?? 0
    if (!valores.length) {
      if (oblig || min > 0) return [null, `Selecciona al menos ${Math.max(1, min)} opción(es)`]
      return [[], null]
    }
    if (new Set(valores).size !== valores.length) return [null, 'Hay opciones repetidas']
    if (valores.length < min) return [null, `Selecciona al menos ${min} opción(es)`]
    if (cfg.max_selecciones != null && valores.length > cfg.max_selecciones) return [null, `Máximo ${cfg.max_selecciones} opción(es)`]
    const validas = opcionesValidas(campo, ctx)
    if (validas) {
      const malas = valores.filter((x) => !validas.includes(x))
      if (malas.length) return [null, `Opción no válida: ${malas.join(', ')}`]
    }
    if (t === 'seleccion_multiple' && cfg.contador_por_opcion) {
      const normal: { valor: string; cantidad: number }[] = []
      for (const x of v as unknown[]) {
        const cantidad = typeof x === 'object' && x !== null ? ((x as { cantidad?: unknown }).cantidad ?? 1) : 1
        const n = numero(cantidad)
        if (n === null || !Number.isInteger(n) || n < (cfg.contador_min ?? 1) || (cfg.contador_max != null && n > cfg.contador_max)) return [null, 'Cantidad fuera de rango']
        normal.push({ valor: escalar(typeof x === 'object' && x !== null ? (x as { valor: unknown }).valor : x), cantidad: n })
      }
      return [normal, null]
    }
    return [valores, null]
  }

  if (t === 'fotografia') {
    const n = cuentaEvidencias(ctx, campo.clave, 'foto')
    const min = cfg.cantidad_min ?? 1
    if (n < min && (oblig || min > 0)) return [null, `Se requieren al menos ${min} foto(s); hay ${n}`]
    if (n > (cfg.cantidad_max ?? 5)) return [null, `Máximo ${cfg.cantidad_max} foto(s)`]
    return [{ evidencias: n }, null]
  }
  if (t === 'firma') {
    if (cuentaEvidencias(ctx, campo.clave, 'firma') < 1) return [null, 'La firma es obligatoria']
    const ts = typeof v === 'object' && v !== null ? (v as { timestamp?: unknown }).timestamp ?? null : null
    return [{ evidencias: 1, timestamp: ts }, null]
  }
  if (t === 'dibujo') {
    const n = cuentaEvidencias(ctx, campo.clave, 'dibujo')
    if (oblig && n < 1) return [null, 'El dibujo es obligatorio']
    return [{ evidencias: n }, null]
  }
  if (t === 'archivo') {
    const n = cuentaEvidencias(ctx, campo.clave, 'archivo')
    if (oblig && n < 1) return [null, 'Adjunta al menos un archivo']
    if (n > (cfg.cantidad_max ?? 3)) return [null, `Máximo ${cfg.cantidad_max} archivo(s)`]
    return [{ evidencias: n }, null]
  }
  if (t === 'audio') {
    const n = cuentaEvidencias(ctx, campo.clave, 'audio')
    if (oblig && n < 1) return [null, 'Graba una nota de voz']
    return [{ evidencias: n }, null]
  }

  if (t === 'fecha_hora') {
    if (vacio(v)) return [null, oblig ? 'Indica la fecha/hora' : null]
    if (typeof v !== 'string') return [null, 'Formato de fecha inválido']
    const modo = cfg.modo ?? 'ambos'
    const patron = { fecha: RE_FECHA, hora: RE_HORA, ambos: RE_FECHA_HORA }[modo]
    if (!patron.test(v) || !parseIso(v)) return [null, { fecha: 'Usa el formato AAAA-MM-DD', hora: 'Usa el formato HH:MM', ambos: 'Usa el formato AAAA-MM-DDTHH:MM' }[modo]]
    const hoy = ctx.hoy ?? new Date()
    if (modo !== 'hora') {
      const minimo = resolverFecha(cfg.fecha_minima, hoy)
      const maximo = resolverFecha(cfg.fecha_maxima, hoy)
      if (minimo && v.slice(0, 10) < minimo.slice(0, 10)) return [null, `La fecha no puede ser anterior a ${minimo.slice(0, 10)}`]
      if (maximo && v.slice(0, 10) > maximo.slice(0, 10)) return [null, `La fecha no puede ser posterior a ${maximo.slice(0, 10)}`]
    }
    if (modo !== 'fecha' && (cfg.intervalo_minutos ?? 1) > 1) {
      const minutos = Number(v.slice(-2))
      if (minutos % cfg.intervalo_minutos! !== 0) return [null, `Los minutos deben ir de ${cfg.intervalo_minutos} en ${cfg.intervalo_minutos}`]
    }
    if (cfg.vinculo?.rol === 'fin') {
      const inicio = respuestas[cfg.vinculo.campo_par]
      if (typeof inicio === 'string' && inicio && v < inicio) return [null, 'La fecha de fin no puede ser anterior a la de inicio']
    }
    return [v, null]
  }

  if (t === 'slider') {
    if (vacio(v)) return [null, oblig ? 'Indica un valor' : null]
    const rango = !!cfg.modo_rango
    if (rango && (!Array.isArray(v) || v.length !== 2)) return [null, 'Indica un rango [desde, hasta]']
    const valores = rango ? (v as unknown[]).map(numero) : [numero(v)]
    if (valores.some((x) => x === null)) return [null, 'Valor numérico inválido']
    for (const x of valores as number[]) {
      if (x < cfg.minimo! || x > cfg.maximo!) return [null, `El valor debe estar entre ${cfg.minimo} y ${cfg.maximo}`]
      const pasos = (x - cfg.minimo!) / cfg.incremento!
      if (Math.abs(pasos - Math.round(pasos)) > 1e-6) return [null, `El valor debe ir en incrementos de ${cfg.incremento}`]
    }
    if (rango && (valores[0] as number) > (valores[1] as number)) return [null, 'El inicio del rango no puede ser mayor que el fin']
    return [rango ? valores : valores[0], null]
  }

  if (t === 'encuesta_satisfaccion') {
    if (vacio(v)) return [null, oblig ? 'Califica el servicio' : null]
    const n = numero(v)
    if (n === null || !Number.isInteger(n) || n < 1 || n > cfg.escala_max!) return [null, `La calificación debe ser un entero entre 1 y ${cfg.escala_max}`]
    return [n, null]
  }

  if (t === 'geolocalizacion') {
    if (vacio(v)) return [null, oblig ? 'Captura la ubicación' : null]
    const g = v as Record<string, unknown>
    if (typeof v !== 'object' || numero(g.lat) === null || numero(g.lng) === null) return [null, 'Ubicación inválida']
    const lat = Number(g.lat)
    const lng = Number(g.lng)
    if (!(lat >= -90 && lat <= 90 && lng >= -180 && lng <= 180)) return [null, 'Coordenadas fuera de rango']
    const lat0 = numero(g.lat_original)
    const lng0 = numero(g.lng_original)
    const ajustada = !!g.ajustada && lat0 !== null && lng0 !== null
    if (ajustada && haversineM(lat0!, lng0!, lat, lng) > cfg.radio_ajuste_m!) return [null, `El ajuste manual excede el radio permitido de ${cfg.radio_ajuste_m} m`]
    return [{ lat, lng, lat_original: ajustada ? lat0 : lat, lng_original: ajustada ? lng0 : lng, ajustada, precision_m: numero(g.precision_m) }, null]
  }

  return [v, null]
}

function calcular(campo: Campo, respuestas: Respuestas, ctx: ContextoValidacion, esquema: EsquemaFormulario): unknown {
  const cfg = campo.config
  if (campo.tipo === 'concatenacion') {
    const partes: string[] = []
    for (const p of cfg.partes ?? []) {
      if (p.tipo === 'texto') {
        partes.push(p.valor)
        continue
      }
      const v = respuestas[p.valor]
      const origen = campoDe(esquema, p.valor)
      if (origen?.fuente_opciones?.origen === 'fija') {
        const etiquetas = Object.fromEntries(origen.fuente_opciones.opciones.map((o) => [o.valor, o.etiqueta]))
        partes.push(valoresDe(v).map((x) => etiquetas[x] ?? x).join(', '))
      } else if (Array.isArray(v)) partes.push(valoresDe(v).join(', '))
      else if (typeof v === 'object' && v !== null) partes.push(String((v as { texto?: unknown; valor?: unknown }).texto ?? (v as { valor?: unknown }).valor ?? ''))
      else if (vacio(v)) partes.push('')
      else partes.push(escalar(v))
    }
    const texto = partes.join(cfg.separador ?? '')
    return cfg.mayusculas ? texto.toUpperCase() : texto
  }
  if (campo.tipo === 'matematicas_tiempo') {
    const instante = (f: { origen: string; valor: string }): Date | null => {
      if (f.origen === 'campo') {
        const v = respuestas[f.valor]
        return typeof v === 'string' ? parseIso(v) : null
      }
      if (f.valor === 'ahora') return ctx.enviadoAt ?? ctx.hoy ?? new Date()
      const v = ctx.sistema?.[f.valor]
      return v ? parseIso(v) : null
    }
    const a = instante(cfg.inicio!)
    const b = instante(cfg.fin!)
    if (!a || !b) return null
    const minutos = Math.round((b.getTime() - a.getTime()) / 60000)
    return { minutos, unidad: cfg.unidad, texto: formatearDuracion(minutos, cfg.unidad ?? 'compuesto') }
  }
  if (campo.tipo === 'sello_fecha_hora') {
    const iso = (d: Date) => fechaLocal(d) + 'T' + d.toTimeString().slice(0, 8)
    if (cfg.trigger === 'al_abrir' && ctx.iniciadoAt) return iso(ctx.iniciadoAt)
    if (cfg.trigger === 'al_enviar' && ctx.enviadoAt) return iso(ctx.enviadoAt)
    if (ctx.sellos?.[campo.clave]) return ctx.sellos[campo.clave]
    return ctx.enviadoAt ? iso(ctx.enviadoAt) : null
  }
  return null
}

/** Normaliza y valida. `estricto=false` (guardado parcial) solo normaliza tipos y omite obligatorios. */
export function validar(esquema: EsquemaFormulario, respuestas: Respuestas, ctx: ContextoValidacion = {}, estricto = true): { salida: Respuestas; errores: ErrorValidacion[] } {
  const visibles = visibilidad(esquema, respuestas)
  const salida: Respuestas = {}
  const errores: ErrorValidacion[] = []
  for (const campo of camposDe(esquema)) {
    if (!visibles.has(campo.clave) || TIPOS_SIN_DATO.has(campo.tipo)) continue
    if (TIPOS_CALCULADOS.has(campo.tipo)) {
      const calculado = calcular(campo, { ...respuestas, ...salida }, ctx, esquema)
      if (calculado !== null && calculado !== undefined) salida[campo.clave] = calculado
      continue
    }
    let v = respuestas[campo.clave]
    if ((v === null || v === undefined) && campo.valor_defecto != null && campo.tipo !== 'texto' && campo.tipo !== 'texto_amplio') v = campo.valor_defecto
    if (!estricto && vacio(v) && !['fotografia', 'firma', 'dibujo', 'archivo', 'audio'].includes(campo.tipo)) continue
    const [normalizado, error] = validarCampo(campo, v, ctx, { ...respuestas, ...salida })
    if (error) {
      if (estricto || !vacio(v)) errores.push({ campo: campo.clave, mensaje: error })
      continue
    }
    if (normalizado !== null && normalizado !== undefined) salida[campo.clave] = normalizado
  }
  return { salida, errores }
}
