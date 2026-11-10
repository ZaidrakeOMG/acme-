/**
 * Envío de la posición del técnico desde la app (§6.8.4 «Arquitectura de actualización GPS»). F2-03.
 *
 * Frecuencias literales del diseño: cada 30 s en jornada activa, cada 5 min en pausa y cada 2 min si la batería
 * baja del 20 %. `watchPosition` deja de reportar cuando el teléfono se bloquea o la app se cierra, que es
 * justamente lo que §6.8.4 pide: no se registra nada fuera de la jornada ni con la app cerrada.
 *
 * Sin señal, las posiciones se guardan en IndexedDB (`posiciones_pendientes`) y se envían al reconectar marcadas
 * como `tardia`, para que el mapa no dé saltos falsos.
 */
import { enviarPosiciones, type PosicionAEnviar } from './operacion'
import { baseLocal, type PosicionPendiente } from './db'
import type { Parametros, SugerenciaLlegada } from '../types/operaciones'

interface Opciones {
  parametros: Parametros
  jornadaId: string | null
  enPausa: boolean
  alEnviar?: (aceptadas: number, sugerencia: SugerenciaLlegada | null) => void
  alGuardarSinSenal?: (pendientes: number) => void
  alFallar?: (mensaje: string) => void
}

let vigilancia: number | null = null
let temporizador: ReturnType<typeof setInterval> | null = null
let ultima: GeolocationPosition | null = null
let bateria: number | null = null
let opcionesActuales: Opciones | null = null

export function soportado(): boolean {
  return typeof navigator !== 'undefined' && 'geolocation' in navigator
}

/** Intervalo de envío en milisegundos, según la jornada y la batería (§6.8.4). */
export function intervaloMs(p: Parametros, enPausa: boolean, bateriaPct: number | null): number {
  if (enPausa) return p.frecuencias.pausa_s * 1000
  if (bateriaPct != null && bateriaPct <= p.frecuencias.bateria_baja_pct) return p.frecuencias.bateria_baja_s * 1000
  return p.frecuencias.jornada_activa_s * 1000
}

async function leerBateria(): Promise<number | null> {
  type ConBateria = Navigator & { getBattery?: () => Promise<{ level: number }> }
  const nav = navigator as ConBateria
  if (typeof nav.getBattery !== 'function') return null  // sin Battery Status API se usa el intervalo normal
  try {
    const estado = await nav.getBattery()
    return Math.round(estado.level * 100)
  } catch {
    return null
  }
}

function aEnviar(p: GeolocationPosition, bateriaPct: number | null, tardia = false): PosicionAEnviar {
  return {
    lat: p.coords.latitude,
    lng: p.coords.longitude,
    capturada_at: new Date(p.timestamp).toISOString(),
    precision_m: p.coords.accuracy != null ? Math.round(p.coords.accuracy * 10) / 10 : null,
    velocidad_mps: p.coords.speed != null && !Number.isNaN(p.coords.speed) ? Math.round(p.coords.speed * 100) / 100 : null,
    rumbo: p.coords.heading != null && !Number.isNaN(p.coords.heading) ? Math.round(p.coords.heading * 10) / 10 : null,
    bateria_pct: bateriaPct,
    tardia,
  }
}

async function guardarPendiente(posicion: PosicionAEnviar, jornadaId: string | null): Promise<number> {
  const fila: PosicionPendiente = {
    id_cliente: crypto.randomUUID(),
    jornada_id: jornadaId,
    lat: posicion.lat,
    lng: posicion.lng,
    capturada_at: posicion.capturada_at,
    precision_m: posicion.precision_m ?? null,
    velocidad_mps: posicion.velocidad_mps ?? null,
    rumbo: posicion.rumbo ?? null,
    bateria_pct: posicion.bateria_pct ?? null,
    intentos: 0,
    enviado: 0,
  }
  await baseLocal.posiciones_pendientes.put(fila)
  return await baseLocal.posiciones_pendientes.where('enviado').equals(0).count()
}

export async function pendientes(): Promise<PosicionPendiente[]> {
  return await baseLocal.posiciones_pendientes.where('enviado').equals(0).sortBy('capturada_at')
}

/** Manda lo que quedó guardado sin señal, marcado como `tardia`. Devuelve cuántas se aceptaron. */
export async function enviarPendientes(maximo = 60): Promise<number> {
  const filas = (await pendientes()).slice(0, maximo)
  if (filas.length === 0) return 0
  const lote: PosicionAEnviar[] = filas.map((f) => ({
    lat: f.lat, lng: f.lng, capturada_at: f.capturada_at, precision_m: f.precision_m,
    velocidad_mps: f.velocidad_mps, rumbo: f.rumbo, bateria_pct: f.bateria_pct, tardia: true,
  }))
  const r = await enviarPosiciones(lote)
  await baseLocal.posiciones_pendientes.bulkDelete(filas.map((f) => f.id_cliente))
  return r.aceptadas
}

async function enviarAhora(): Promise<void> {
  const o = opcionesActuales
  if (!o || !ultima) return
  const posicion = aEnviar(ultima, bateria)
  try {
    if (typeof navigator !== 'undefined' && navigator.onLine === false) throw new Error('sin conexión')
    await enviarPendientes()
    const r = await enviarPosiciones([posicion])
    o.alEnviar?.(r.aceptadas, r.sugerencia_llegada)
  } catch (e) {
    const cuantas = await guardarPendiente(posicion, o.jornadaId)
    o.alGuardarSinSenal?.(cuantas)
    if (typeof navigator !== 'undefined' && navigator.onLine) {
      o.alFallar?.(e instanceof Error ? e.message : 'No se pudo enviar la posición')
    }
  }
}

/** Arranca el seguimiento. Idempotente: volver a llamarlo cambia el intervalo (por ejemplo, al entrar en pausa). */
export async function iniciarSeguimiento(opciones: Opciones): Promise<boolean> {
  opcionesActuales = opciones
  if (!soportado()) {
    opciones.alFallar?.('Este teléfono no comparte su ubicación con el navegador')
    return false
  }
  bateria = await leerBateria()
  if (vigilancia == null) {
    vigilancia = navigator.geolocation.watchPosition(
      (p) => { ultima = p },
      (error) => {
        opciones.alFallar?.(error.code === error.PERMISSION_DENIED
          ? 'Tienes que permitir la ubicación para que el despachador sepa dónde estás'
          : 'El GPS no está dando posición')
      },
      { enableHighAccuracy: true, maximumAge: 15000, timeout: 20000 },
    )
  }
  if (temporizador) clearInterval(temporizador)
  temporizador = setInterval(() => {
    void (async () => {
      bateria = await leerBateria()
      await enviarAhora()
    })()
  }, intervaloMs(opciones.parametros, opciones.enPausa, bateria))
  return true
}

export function detenerSeguimiento(): void {
  if (vigilancia != null && soportado()) navigator.geolocation.clearWatch(vigilancia)
  vigilancia = null
  if (temporizador) clearInterval(temporizador)
  temporizador = null
  ultima = null
  opcionesActuales = null
}

export function siguiendo(): boolean {
  return vigilancia != null
}

/** Para las pruebas y para el botón «mandar mi posición ahora». */
export async function enviarUnaVez(): Promise<void> {
  await enviarAhora()
}
