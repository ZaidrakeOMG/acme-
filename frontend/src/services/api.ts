/**
 * Cliente HTTP de ACMA.
 * - Token de acceso en memoria; refresh token en localStorage (decisión pendiente: cookie httpOnly).
 * - Refresh automático single-flight: varias peticiones con 401 comparten una sola renovación.
 * - Toda respuesta de error se convierte en ErrorAPI con el formato estándar {codigo, mensaje, detalles}.
 */
import type { ErrorEstandar, Tokens } from '../types/api'

const CLAVE_REFRESH = 'acma.refresh'
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

function leerRefresh(): string | null {
  try {
    return localStorage.getItem(CLAVE_REFRESH)
  } catch {
    return null
  }
}

/** Token de acceso vigente (lo usan WebSocket/SSE, que no envían cabeceras). */
export function tokenActual(): string | null {
  return tokenAcceso
}

export const sesion = {
  guardar(tokens: Tokens) {
    tokenAcceso = tokens.access_token
    try {
      localStorage.setItem(CLAVE_REFRESH, tokens.refresh_token)
    } catch {
      /* almacenamiento no disponible: la sesión dura lo que la pestaña */
    }
  },
  limpiar() {
    tokenAcceso = null
    try {
      localStorage.removeItem(CLAVE_REFRESH)
    } catch {
      /* sin almacenamiento */
    }
  },
  tieneRefresh: () => leerRefresh() !== null,
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
      const refresh = leerRefresh()
      if (!refresh) return false
      try {
        const r = await fetch(`${BASE}/auth/refresh`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ refresh_token: refresh }),
        })
        if (!r.ok) {
          sesion.limpiar()
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
      headers,
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
export async function descargar(ruta: string, params?: Record<string, string | undefined>): Promise<Blob> {
  const consulta = params
    ? '?' + new URLSearchParams(Object.entries(params).filter((e): e is [string, string] => !!e[1])).toString()
    : ''
  const headers: Record<string, string> = tokenAcceso ? { Authorization: `Bearer ${tokenAcceso}` } : {}
  let respuesta = await fetch(`${BASE}${ruta}${consulta}`, { headers })
  if (respuesta.status === 401 && sesion.tieneRefresh() && (await refrescar())) {
    respuesta = await fetch(`${BASE}${ruta}${consulta}`, { headers: { Authorization: `Bearer ${tokenAcceso}` } })
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
