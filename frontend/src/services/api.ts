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
  guardar(tokens: Tokens) {
    tokenAcceso = tokens.access_token
    try {
      localStorage.setItem(CLAVE_SESION, '1')
    } catch {
      /* almacenamiento no disponible: la sesión dura lo que la pestaña */
    }
  },
  limpiar() {
    tokenAcceso = null
    try {
      localStorage.removeItem(CLAVE_SESION)
    } catch {
      /* sin almacenamiento */
    }
  },
  /** ¿Conviene intentar renovar? La cookie no se puede leer, así que basta la marca o el CSRF visible. */
  tieneRefresh: () => hayMarca() || csrfActual() !== null,
  alExpirar(fn: () => void) {
    alExpirarSesion = fn
  },
}

async function aErrorAPI(respuesta: Response): Promise<ErrorAPI> {
  try {
    const cuerpo = (await respuesta.json()) as Partial<ErrorEstandar>
    return new ErrorAPI(respuesta.status, cuerpo)
  } catch {
    return new ErrorAPI(respuesta.status, { codigo: `HTTP_${respuesta.status}`, mensaje: respuesta.statusText })
  }
}

/** Renueva tokens una sola vez aunque la pidan varias peticiones a la vez. */
export function refrescar(): Promise<boolean> {
  if (!refrescoEnCurso) {
    refrescoEnCurso = (async () => {
      if (!sesion.tieneRefresh()) return false
      try {
        const r = await fetch(`${BASE}/auth/refresh`, {
          method: 'POST',
          headers: cabecerasCsrf(),
          credentials: 'same-origin',
        })
        if (!r.ok) {
          // 0 y 5xx pueden ser falta de red: no se borra la marca para no perder la sesión al recargar sin señal.
          if (r.status >= 400 && r.status < 500) sesion.limpiar()
          return false
        }
        sesion.guardar((await r.json()) as Tokens)
        return true
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
    alExpirarSesion?.()
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
