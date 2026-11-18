/**
 * Cliente HTTP de ACMA.
 * - Token de acceso en memoria; el refresh vive en la cookie `httpOnly` `acma_refresh` que emite el servidor (§6.9.5),
 *   así que este código nunca lo ve ni lo guarda. En `localStorage` solo queda una marca sin valor («hay sesión en este
 *   navegador») para saber si vale la pena intentar renovar al abrir la app, incluso sin red.
 * - Contra CSRF: el servidor emite también la cookie legible `acma_csrf` y `/auth/refresh` y `/auth/logout` exigen el
 *   mismo valor en la cabecera `X-ACMA-CSRF` (doble envío).
 * - Refresh automático single-flight: varias peticiones con 401 comparten una sola renovación.
 * - Toda respuesta de error se convierte en ErrorAPI con el formato estándar {codigo, mensaje, detalles}.
 */
import type { ErrorEstandar, Tokens } from '../types/api'

const CLAVE_SESION = 'acma.sesion'
const COOKIE_CSRF = 'acma_csrf'
const BASE = '/api'

export class ErrorAPI extends Error implements ErrorEstandar {
  codigo: string
  mensaje: string
  detalles: unknown[]
  estado: number

  constructor(estado: number, cuerpo: Partial<ErrorEstandar>) {
    super(cuerpo.mensaje ?? 'Error de comunicación con el servidor')
    this.estado = estado
    this.codigo = cuerpo.codigo ?? 'ERROR_DESCONOCIDO'
    this.mensaje = cuerpo.mensaje ?? 'Error de comunicación con el servidor'
    this.detalles = cuerpo.detalles ?? []
  }
}

let tokenAcceso: string | null = null
let refrescoEnCurso: Promise<boolean> | null = null
let alExpirarSesion: (() => void) | null = null
// Al recibir un 401/403 definitivo no se intenta restaurar repetidamente una cookie rechazada.
let refrescoRechazado = false
let accesoVenceEn = 0
let revisionAcceso = 0

// El JWT solo circula en memoria entre pestañas del MISMO origen. Nunca se escribe en localStorage.
const canalAuth: BroadcastChannel | null = (() => {
  try {
    return typeof BroadcastChannel === 'undefined' ? null : new BroadcastChannel('acma-sesion')
  } catch {
    return null
  }
})()

function cierreExplicito(): boolean {
  try {
    return localStorage.getItem(CLAVE_SESION) === '0'
  } catch {
    return false
  }
}

/** Marca local: no es un secreto, solo dice que este navegador tuvo sesión (para intentar renovar al abrir). */
function hayMarca(): boolean {
  try {
    return localStorage.getItem(CLAVE_SESION) === '1'
  } catch {
    return false
  }
}

/** CSRF: el servidor lo emite en una cookie legible y lo exige en la cabecera de refresh y logout. */
export function csrfActual(): string | null {
  const par = document.cookie.split('; ').find((c) => c.startsWith(`${COOKIE_CSRF}=`))
  return par ? decodeURIComponent(par.slice(COOKIE_CSRF.length + 1)) : null
}

function cabecerasCsrf(): Record<string, string> {
  const valor = csrfActual()
  return valor ? { 'X-ACMA-CSRF': valor } : {}
}

/** Token de acceso vigente (lo usan WebSocket/SSE, que no envían cabeceras). */
export function tokenActual(): string | null {
  return tokenAcceso
}

export const sesion = {
  guardar(tokens: Tokens, compartir = true) {
    refrescoRechazado = false
    tokenAcceso = tokens.access_token
    accesoVenceEn = Date.now() + tokens.expira_en * 1000
    revisionAcceso += 1
    try {
      localStorage.setItem(CLAVE_SESION, '1')
    } catch {
      /* Sin almacenamiento: la sesión depende de las cookies y la pestaña. */
    }
    if (compartir) canalAuth?.postMessage({ tipo: 'tokens', tokens })
  },
  limpiar(compartir = true) {
    refrescoRechazado = true
    tokenAcceso = null
    accesoVenceEn = 0
    revisionAcceso += 1
    try {
      // '0' evita que la cookie httpOnly todavía existente reabra la sesión después
      // de un cierre sin Internet (cuando el servidor no pudo borrar la cookie).
      localStorage.setItem(CLAVE_SESION, '0')
    } catch {
      /* sin almacenamiento */
    }
    if (compartir) canalAuth?.postMessage({ tipo: 'salir' })
  },
  /** Sin secretos persistidos: solo la marca y la cookie CSRF legible. */
  tieneRefresh: () => !refrescoRechazado && !cierreExplicito() && (hayMarca() || csrfActual() !== null),
  accesoPorVencer: () => !tokenAcceso || Date.now() >= accesoVenceEn - 60_000,
  alExpirar(fn: () => void) {
    alExpirarSesion = fn
  },
}

// Compartir el nuevo JWT corto con otras pestañas evita que roten una misma cookie
// repetidamente. El refresh permanece en httpOnly y nunca se transmite.
if (canalAuth) {
  canalAuth.onmessage = (evento: MessageEvent) => {
    const mensaje = evento.data
    if (mensaje?.tipo === 'tokens' && typeof mensaje.tokens?.access_token === 'string' &&
        typeof mensaje.tokens?.expira_en === 'number' && sesion.tieneRefresh()) {
      sesion.guardar(mensaje.tokens as Tokens, false)
    } else if (mensaje?.tipo === 'salir') {
      sesion.limpiar(false)
      alExpirarSesion?.()
    }
  }
}

async function aErrorAPI(respuesta: Response): Promise<ErrorAPI> {
  try {
    const cuerpo = (await respuesta.json()) as Partial<ErrorEstandar>
    return new ErrorAPI(respuesta.status, cuerpo)
  } catch {
    return new ErrorAPI(respuesta.status, { codigo: `HTTP_${respuesta.status}`, mensaje: respuesta.statusText })
  }
}

/** Renueva el acceso y serializa rotaciones también entre pestañas con Web Locks (si está disponible).
 * El refresh rotativo permanece exclusivamente en la cookie httpOnly; nunca se copia al almacenamiento web.
 */
export function refrescar(): Promise<boolean> {
  if (!refrescoEnCurso) {
    refrescoEnCurso = (async () => {
      if (!sesion.tieneRefresh()) return false
      const revisionAlPedir = revisionAcceso
      const renovar = async (): Promise<boolean> => {
        if (!sesion.tieneRefresh()) return false
        // Al salir de Web Locks, otra pestaña pudo renovar y compartir su acceso.
        // En ese caso no volvemos a rotar la cookie ni a invalidar accesos válidos.
        if (revisionAcceso !== revisionAlPedir && tokenAcceso &&
            Date.now() < accesoVenceEn - 60_000) return true
        const controlador = new AbortController()
        const limite = setTimeout(() => controlador.abort(), 15_000)
        try {
          const r = await fetch(`${BASE}/auth/refresh`, {
            method: 'POST',
            headers: cabecerasCsrf(),
            credentials: 'same-origin',
            cache: 'no-store',
            signal: controlador.signal,
          })
          if (!r.ok) {
            // Los 5xx y la pérdida de red no deben borrar una sesión recuperable.
            if (r.status === 401 || r.status === 403) {
              sesion.limpiar()
              alExpirarSesion?.()
            }
            return false
          }
          sesion.guardar((await r.json()) as Tokens)
          return true
        } catch {
          return false
        } finally {
          clearTimeout(limite)
        }
      }
      // En varias pestañas abiertas, rotar la misma cookie a la vez invalidaría toda la familia.
      // Web Locks funciona por origen y evita esas rotaciones simultáneas en navegadores compatibles.
      try {
        if (typeof navigator !== 'undefined' && navigator.locks?.request) {
          return await navigator.locks.request('acma-refresh-cookie', renovar)
        }
        return await renovar()
      } catch {
        return false
      }
    })().finally(() => {
      refrescoEnCurso = null
    })
  }
  return refrescoEnCurso
}

interface Opciones {
  metodo?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  cuerpo?: unknown
  params?: Record<string, string | number | boolean | null | undefined>
  formulario?: FormData
  sinAuth?: boolean
}

export async function api<T>(ruta: string, opciones: Opciones = {}, reintento = true): Promise<T> {
  const { metodo = 'GET', cuerpo, params, formulario, sinAuth } = opciones
  const consulta = params
    ? '?' +
      new URLSearchParams(
        Object.entries(params)
          .filter(([, v]) => v !== undefined && v !== null && v !== '')
          .map(([k, v]) => [k, String(v)]),
      ).toString()
    : ''
  const headers: Record<string, string> = {}
  if (cuerpo !== undefined) headers['Content-Type'] = 'application/json'
  if (tokenAcceso && !sinAuth) headers.Authorization = `Bearer ${tokenAcceso}`

  let respuesta: Response
  try {
    respuesta = await fetch(`${BASE}${ruta}${consulta}`, {
      method: metodo,
      headers: { ...headers, ...(ruta.startsWith('/auth/') ? cabecerasCsrf() : {}) },
      credentials: 'same-origin',
      body: formulario ?? (cuerpo !== undefined ? JSON.stringify(cuerpo) : undefined),
    })
  } catch {
    throw new ErrorAPI(0, { codigo: 'SIN_CONEXION', mensaje: 'No hay conexión con el servidor' })
  }

  if (respuesta.status === 401 && !sinAuth && reintento && sesion.tieneRefresh()) {
    if (await refrescar()) return api<T>(ruta, opciones, false)
    // Si el servidor/red no responde, mantener la sesión para reanudar al volver la conexión.
    if (!sesion.tieneRefresh()) alExpirarSesion?.()
  }
  if (!respuesta.ok) throw await aErrorAPI(respuesta)
  if (respuesta.status === 204) return undefined as T
  return (await respuesta.json()) as T
}

/** Descarga binaria autenticada (plantillas, reportes). Devuelve el Blob o lanza ErrorAPI. */
/** Descarga un archivo. P10: admite POST con cuerpo (la generación de reportes devuelve el archivo en la respuesta). */
export async function descargar(ruta: string, params?: Record<string, string | undefined>,
                                opciones?: { metodo?: 'GET' | 'POST'; cuerpo?: unknown }): Promise<Blob> {
  const consulta = params
    ? '?' + new URLSearchParams(Object.entries(params).filter((e): e is [string, string] => !!e[1])).toString()
    : ''
  const metodo = opciones?.metodo ?? 'GET'
  const armar = (): RequestInit => ({
    method: metodo,
    headers: {
      ...(tokenAcceso ? { Authorization: `Bearer ${tokenAcceso}` } : {}),
      ...(opciones?.cuerpo !== undefined ? { 'Content-Type': 'application/json' } : {}),
    },
    ...(opciones?.cuerpo !== undefined ? { body: JSON.stringify(opciones.cuerpo) } : {}),
  })
  let respuesta = await fetch(`${BASE}${ruta}${consulta}`, armar())
  if (respuesta.status === 401 && sesion.tieneRefresh() && (await refrescar())) {
    respuesta = await fetch(`${BASE}${ruta}${consulta}`, armar())
  }
  if (!respuesta.ok) throw await aErrorAPI(respuesta)
  return respuesta.blob()
}

export function mensajeDeError(error: unknown): string {
  if (error instanceof ErrorAPI) {
    const detalles = error.detalles
      .map((d) => (typeof d === 'string' ? d : typeof d === 'object' && d && 'mensaje' in d ? String((d as { mensaje: unknown }).mensaje) : ''))
      .filter(Boolean)
    return detalles.length ? `${error.mensaje}: ${detalles.join('; ')}` : error.mensaje
  }
  return 'Ocurrió un error inesperado'
}
