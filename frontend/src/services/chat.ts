/**
 * Chat del folio (§6.8.1): mensajes por HTTP (con cola offline y doble timestamp), recepción en tiempo real por
 * WebSocket con fallback automático a SSE. El envío siempre es HTTP POST.
 */
import { api, descargar, tokenActual } from './api'
import { baseLocal } from './db'
import { conRespaldoOffline, nuevoIdCliente, syncEngine } from './syncEngine'

export type CanalChat = 'campo' | 'operativo' | 'interno'
export interface Chat {
  id: string
  folio_id: string
  canal: CanalChat
  estado: 'activo' | 'archivado'
  es_participante: boolean
  puede_gestionar: boolean
  no_leidos: number
  participantes: { usuario_id: string; nombre: string; rol: string; fijo: boolean }[]
}
export interface MensajeChat {
  id: string
  chat_id: string
  usuario_id: string | null
  usuario_nombre: string | null
  contenido_texto: string
  tipo: 'texto' | 'imagen' | 'audio' | 'sistema'
  timestamp_servidor: string
  timestamp_dispositivo: string | null
  leido_por_json: Record<string, string>
  datos_json: Record<string, unknown>
  id_cliente: string
  archivos: { id: string; archivo_key: string; nombre_original: string; tipo_mime: string; tamano_bytes: number }[]
  /** solo local: aún no llega al servidor */
  pendiente?: boolean
}

export const NOMBRE_CANAL: Record<CanalChat, string> = { campo: 'Campo (técnico · operador)', operativo: 'Operativo (despachador · admin UN)', interno: 'Interno (prestador)' }

export const chatsDelFolio = (folioId: string) => api<Chat[]>(`/folios/${folioId}/chats`)

export async function mensajesDe(chatId: string, desde?: string): Promise<MensajeChat[]> {
  try {
    const lista = await api<MensajeChat[]>(`/chats/${chatId}/mensajes`, { params: { desde } })
    await baseLocal.chat_mensajes_cache.bulkPut(lista.map((m) => ({ id: m.id, chat_id: chatId, timestamp_servidor: m.timestamp_servidor, datos: m as unknown as Record<string, unknown> })))
    return [...lista, ...(await pendientesDe(chatId))]
  } catch (e) {
    if (!syncEngine.enLinea() || (e as { codigo?: string }).codigo === 'SIN_CONEXION') {
      const cache = (await baseLocal.chat_mensajes_cache.where('chat_id').equals(chatId).toArray()).map((c) => c.datos as unknown as MensajeChat)
      return [...cache.sort((a, b) => a.timestamp_servidor.localeCompare(b.timestamp_servidor)), ...(await pendientesDe(chatId))]
    }
    throw e
  }
}

async function pendientesDe(chatId: string): Promise<MensajeChat[]> {
  const pendientes = await baseLocal.chat_pendientes.where('chat_id').equals(chatId).toArray()
  return pendientes.filter((p) => p.estado === 'pendiente').map((p) => ({
    id: p.id_cliente, chat_id: chatId, usuario_id: null, usuario_nombre: null, contenido_texto: p.contenido_texto, tipo: p.tipo as MensajeChat['tipo'],
    timestamp_servidor: p.timestamp_dispositivo, timestamp_dispositivo: p.timestamp_dispositivo, leido_por_json: {}, datos_json: {}, id_cliente: p.id_cliente, archivos: [], pendiente: true,
  }))
}

/** Envía un mensaje; sin red lo encola con la hora real de escritura (el receptor verá el doble timestamp). */
export async function enviarMensaje(chatId: string, texto: string): Promise<MensajeChat> {
  const idCliente = nuevoIdCliente()
  const timestampDispositivo = new Date().toISOString()
  const { valor } = await conRespaldoOffline(
    () => api<MensajeChat>(`/chats/${chatId}/mensajes`, { metodo: 'POST', cuerpo: { id_cliente: idCliente, contenido_texto: texto, tipo: 'texto', timestamp_dispositivo: timestampDispositivo } }),
    'mensaje_chat', { chat_id: chatId, contenido_texto: texto, tipo: 'texto' }, `Mensaje en chat: ${texto.slice(0, 40)}`, idCliente, timestampDispositivo,
  )
  if (valor) return valor
  await baseLocal.chat_pendientes.put({ id_cliente: idCliente, chat_id: chatId, contenido_texto: texto, tipo: 'texto', timestamp_dispositivo: timestampDispositivo, estado: 'pendiente' })
  return { id: idCliente, chat_id: chatId, usuario_id: null, usuario_nombre: null, contenido_texto: texto, tipo: 'texto', timestamp_servidor: timestampDispositivo, timestamp_dispositivo: timestampDispositivo, leido_por_json: {}, datos_json: {}, id_cliente: idCliente, archivos: [], pendiente: true }
}

export async function enviarImagen(chatId: string, archivo: Blob, nombre: string, texto = ''): Promise<MensajeChat> {
  const f = new FormData()
  f.append('archivo', archivo, nombre)
  f.append('id_cliente', nuevoIdCliente())
  f.append('tipo', 'imagen')
  f.append('contenido_texto', texto)
  f.append('timestamp_dispositivo', new Date().toISOString())
  return api<MensajeChat>(`/chats/${chatId}/mensajes/archivo`, { metodo: 'POST', formulario: f })
}

export const marcarLeido = (chatId: string) => api(`/chats/${chatId}/leido`, { metodo: 'POST', cuerpo: {} })
export const agregarParticipante = (chatId: string, usuarioId: string) => api<Chat>(`/chats/${chatId}/participantes`, { metodo: 'POST', cuerpo: { usuario_id: usuarioId } })
export const quitarParticipante = (chatId: string, usuarioId: string) => api(`/chats/${chatId}/participantes/${usuarioId}`, { metodo: 'DELETE' })
export const descargarAdjunto = (chatId: string, archivoId: string) => descargar(`/chats/${chatId}/archivos/${archivoId}`)

/** Al confirmar el envío de un mensaje encolado, se limpia el pendiente local. */
export async function confirmarPendiente(idCliente: string) {
  await baseLocal.chat_pendientes.delete(idCliente)
}

export type EventoTiempoReal = { evento: 'mensaje'; mensaje: MensajeChat } | { evento: 'leido'; usuario_id: string; hasta: string } | { evento: 'conectado' } | { evento: 'pong' }

/**
 * Conexión en tiempo real a un chat: WebSocket y, si no se sostiene (error o cierre anómalo), SSE.
 * Devuelve una función para cerrar.
 */
export function conectarTiempoReal(chatId: string, alEvento: (e: EventoTiempoReal) => void, alCambiarModo?: (modo: 'websocket' | 'sse' | 'ninguno') => void): () => void {
  let cerrado = false
  let ws: WebSocket | null = null
  let sse: EventSource | null = null
  let latido: ReturnType<typeof setInterval> | null = null
  const token = tokenActual() ?? ''
  const base = typeof location !== 'undefined' ? location.origin : 'http://localhost'

  const abrirSSE = () => {
    if (cerrado || typeof EventSource === 'undefined') { alCambiarModo?.('ninguno'); return }
    sse = new EventSource(`${base}/api/chats/${chatId}/stream?token=${encodeURIComponent(token)}`)
    alCambiarModo?.('sse')
    sse.onmessage = (ev) => { try { alEvento(JSON.parse(ev.data) as EventoTiempoReal) } catch { /* latido */ } }
    sse.onerror = () => { /* EventSource reintenta solo */ }
  }
  const abrirWS = () => {
    if (cerrado || typeof WebSocket === 'undefined') { abrirSSE(); return }
    let recibioAlgo = false
    try {
      ws = new WebSocket(`${base.replace(/^http/, 'ws')}/ws/chats/${chatId}?token=${encodeURIComponent(token)}`)
    } catch {
      abrirSSE()
      return
    }
    ws.onopen = () => { alCambiarModo?.('websocket'); latido = setInterval(() => ws?.readyState === 1 && ws.send('ping'), 25000) }
    ws.onmessage = (ev) => { recibioAlgo = true; try { alEvento(JSON.parse(ev.data) as EventoTiempoReal) } catch { /* ignorar */ } }
    ws.onerror = () => { /* onclose decide */ }
    ws.onclose = (ev) => {
      if (latido) clearInterval(latido)
      if (cerrado) return
      if (ev.code === 4403) { alCambiarModo?.('ninguno'); return }
      if (!recibioAlgo || ev.code !== 1000) abrirSSE()   // no se sostuvo: fallback SSE
      else setTimeout(abrirWS, 2000)
    }
  }
  abrirWS()
  return () => {
    cerrado = true
    if (latido) clearInterval(latido)
    ws?.close(1000)
    sse?.close()
  }
}
