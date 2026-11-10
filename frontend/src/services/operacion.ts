/** Cliente de /api/operacion y suscripción a los eventos del tablero (F2-03). */
import type {
  AlertaDelTecnico, EventoOperacion, MiJornada, MotivoPausa, Parametros, Recorrido, RespuestaAlerta,
  RespuestaPosiciones, Tablero,
} from '../types/operaciones'
import { api, tokenActual } from './api'

export interface PosicionAEnviar {
  lat: number
  lng: number
  capturada_at: string
  precision_m?: number | null
  velocidad_mps?: number | null
  rumbo?: number | null
  bateria_pct?: number | null
  tardia?: boolean
}

export const parametrosOperacion = () => api<Parametros>('/operacion/parametros')
export const miJornada = () => api<MiJornada>('/operacion/mi-jornada')
export const iniciarJornada = (dispositivo_id: string, acepta_aviso: boolean) =>
  api<MiJornada>('/operacion/jornada/iniciar', { metodo: 'POST', cuerpo: { dispositivo_id, acepta_aviso } })
export const cerrarJornada = () => api<MiJornada>('/operacion/jornada/cerrar', { metodo: 'POST' })
export const pausarJornada = (motivo: MotivoPausa, nota = '') =>
  api<MiJornada>('/operacion/jornada/pausar', { metodo: 'POST', cuerpo: { motivo, nota } })
export const reanudarJornada = () => api<MiJornada>('/operacion/jornada/reanudar', { metodo: 'POST' })
export const enviarPosiciones = (posiciones: PosicionAEnviar[]) =>
  api<RespuestaPosiciones>('/operacion/posiciones', { metodo: 'POST', cuerpo: { posiciones } })
export const misPosiciones = (horas = 8) => api<Recorrido>('/operacion/mis-posiciones', { params: { horas } })
export const misAlertas = () => api<AlertaDelTecnico[]>('/operacion/mis-alertas')
export const responderAlerta = (id: string, respuesta: RespuestaAlerta) =>
  api<{ id: string; respuesta: string; respondida_at: string }>(
    `/operacion/alertas/${id}/responder`, { metodo: 'POST', cuerpo: { respuesta } })

export const tablero = () => api<Tablero>('/operacion/tablero')
export const recorridoDe = (tecnicoId: string, horas = 2) =>
  api<Recorrido>(`/operacion/tecnicos/${tecnicoId}/recorrido`, { params: { horas } })
export const cerrarJornadaDe = (jornadaId: string) =>
  api<{ mensaje: string }>(`/operacion/jornada/${jornadaId}/cerrar`, { metodo: 'POST' })
/** Atender una alerta sin salir del tablero (§6.8.4: cada alerta con su acción directa). */
export const atenderAlerta = (alertaId: string, nota = 'Atendida desde el tablero de operaciones') =>
  api<{ id: string }>(`/alertas/historial/${alertaId}/atender`, { metodo: 'POST', cuerpo: { nota } })

/**
 * Eventos del tablero: WebSocket y, si no se puede, SSE (el mismo par que el chat de P05). Devuelve una función
 * para cerrar la suscripción y avisa de cada cambio de conexión para el indicador «datos en vivo / reconectando».
 */
export function suscribirOperacion(
  alRecibir: (e: EventoOperacion) => void,
  alCambiarConexion?: (estado: 'conectando' | 'en_vivo' | 'reconectando') => void,
): () => void {
  let cerrado = false
  let ws: WebSocket | null = null
  let sse: EventSource | null = null
  let reintento: ReturnType<typeof setTimeout> | null = null
  let latido: ReturnType<typeof setInterval> | null = null
  let intentos = 0

  function limpiar() {
    if (latido) { clearInterval(latido); latido = null }
    if (ws) { ws.onclose = null; ws.close(); ws = null }
    if (sse) { sse.close(); sse = null }
  }

  function programarReintento() {
    if (cerrado) return
    alCambiarConexion?.('reconectando')
    intentos += 1
    const espera = Math.min(30000, 1000 * 2 ** Math.min(4, intentos))
    reintento = setTimeout(conectar, espera)
  }

  function conectar() {
    if (cerrado) return
    limpiar()
    const token = tokenActual()
    if (!token) { programarReintento(); return }
    alCambiarConexion?.(intentos === 0 ? 'conectando' : 'reconectando')
    try {
      const protocolo = location.protocol === 'https:' ? 'wss' : 'ws'
      ws = new WebSocket(`${protocolo}://${location.host}/ws/operacion?token=${encodeURIComponent(token)}`)
      ws.onopen = () => {
        intentos = 0
        alCambiarConexion?.('en_vivo')
        latido = setInterval(() => ws?.readyState === WebSocket.OPEN && ws.send('ping'), 25000)
      }
      ws.onmessage = (m) => {
        try { alRecibir(JSON.parse(m.data as string) as EventoOperacion) } catch { /* evento ilegible */ }
      }
      ws.onerror = () => { /* onclose se encarga */ }
      ws.onclose = () => {
        if (cerrado) return
        if (intentos === 0) conectarSse()  // primer fallo: puede ser un proxy sin WebSocket
        else programarReintento()
      }
    } catch {
      conectarSse()
    }
  }

  function conectarSse() {
    if (cerrado) return
    limpiar()
    const token = tokenActual()
    if (!token) { programarReintento(); return }
    sse = new EventSource(`/api/operacion/stream?token=${encodeURIComponent(token)}`)
    sse.onopen = () => { intentos = 0; alCambiarConexion?.('en_vivo') }
    sse.onmessage = (m) => {
      try { alRecibir(JSON.parse(m.data) as EventoOperacion) } catch { /* evento ilegible */ }
    }
    sse.onerror = () => { intentos += 1; programarReintento() }
  }

  conectar()
  return () => {
    cerrado = true
    if (reintento) clearTimeout(reintento)
    limpiar()
  }
}
