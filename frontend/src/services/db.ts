/**
 * Base local IndexedDB (Dexie) — §6.2 capa 3. Versión 2 (P05): caché de catálogos, folios y formularios, borradores de
 * respuestas, evidencias pendientes (blob + metadatos), cola FIFO de mutaciones con `id_cliente`, caché y pendientes del chat.
 * Versión 3 (F2-01): biblioteca sin conexión, con el archivo y su versión para avisar cuando hay una más nueva.
 * Versión 4 (F2-03): cola de posiciones del GPS que no se pudieron mandar (sin señal); se envían al reconectar
 * marcadas como `tardia` para que el mapa no dé saltos falsos.
 */
import Dexie, { type EntityTable } from 'dexie'

export interface Metadato {
  clave: string
  valor: unknown
  actualizado: string
}

/** Un registro de catálogo cacheado: `entidad` (unidades, equipos, tipos_falla…) + id. */
export interface CatalogoCache {
  clave: string // `${entidad}:${id}`
  entidad: string
  id: string
  updated_at: string
  activo: boolean
  datos: Record<string, unknown>
}

export interface FolioCache {
  id: string
  numero_folio: string
  estado: string
  un_id: string
  tecnico_id: string | null
  updated_at: string
  datos: Record<string, unknown>
}

export interface FormularioCache {
  id: string
  tipo: string
  updated_at: string
  datos: Record<string, unknown>
}

export interface RespuestaBorrador {
  id: string // id del servidor o id_cliente si se creó offline
  formulario_id: string
  origen: string
  referencia_id: string | null
  contexto: Record<string, unknown>
  respuestas: Record<string, unknown>
  estado: 'en_progreso' | 'enviado'
  iniciado_at: string
  actualizado: string
  creada_offline: boolean
}

export interface EvidenciaPendiente {
  id_cliente: string
  respuesta_id: string
  campo_clave: string
  nombre: string
  mime: string
  blob: Blob
  hash_sha256: string
  etiqueta?: string | null
  geolat?: number | null
  geolng?: number | null
  creado: string
  estado: 'pendiente' | 'subida' | 'error' | 'atencion'
  intentos: number
  ultimo_error: string | null
}

export type TipoMutacion = 'crear_folio' | 'transicion' | 'guardar_respuesta' | 'enviar_respuesta' | 'subir_evidencia' | 'agregar_refaccion' | 'mensaje_chat'

export interface MutacionPendiente {
  id_cliente: string
  orden: number
  tipo: TipoMutacion
  payload: Record<string, unknown>
  timestamp_dispositivo: string
  estado: 'pendiente' | 'enviando' | 'aplicada' | 'duplicada' | 'rechazada' | 'atencion'
  intentos: number
  proximo_intento: string | null
  ultimo_error: string | null
  resultado: Record<string, unknown> | null
  descripcion: string
}

export interface MensajeCache {
  id: string
  chat_id: string
  timestamp_servidor: string
  datos: Record<string, unknown>
}

export interface ChatPendiente {
  id_cliente: string
  chat_id: string
  contenido_texto: string
  tipo: string
  timestamp_dispositivo: string
  estado: 'pendiente' | 'enviado' | 'error'
}

/** Un manual o un contenido de servicio guardado en el dispositivo (§6.10.4, ACT-5.3). F2-01. */
export interface BibliotecaOffline {
  clave: string // `${clase}:${id}`
  clase: 'manual' | 'contenido_servicio'
  id: string
  titulo: string
  tipo_equipo_id: string | null
  categoria: string | null
  version: number
  mime: string | null
  bytes: number
  /** El archivo; los contenidos de servicio sin documento guardan solo sus puntos. */
  archivo: Blob | null
  puntos_revision: unknown[] | null
  descargado: string
  /** Lo marca el paquete de sincronización cuando el servidor tiene una versión más nueva. */
  desactualizado: boolean
}

/** Una posición del GPS que se guardó sin señal y espera para salir (§6.8.4). F2-03. */
export interface PosicionPendiente {
  id_cliente: string
  jornada_id: string | null
  lat: number
  lng: number
  capturada_at: string
  precision_m: number | null
  velocidad_mps: number | null
  rumbo: number | null
  bateria_pct: number | null
  intentos: number
  enviado: 0 | 1
}

export class BaseLocal extends Dexie {
  metadatos!: EntityTable<Metadato, 'clave'>
  catalogos_cache!: EntityTable<CatalogoCache, 'clave'>
  folios_cache!: EntityTable<FolioCache, 'id'>
  formularios_cache!: EntityTable<FormularioCache, 'id'>
  respuestas_borrador!: EntityTable<RespuestaBorrador, 'id'>
  evidencias_pendientes!: EntityTable<EvidenciaPendiente, 'id_cliente'>
  mutaciones_pendientes!: EntityTable<MutacionPendiente, 'id_cliente'>
  chat_mensajes_cache!: EntityTable<MensajeCache, 'id'>
  chat_pendientes!: EntityTable<ChatPendiente, 'id_cliente'>
  biblioteca_offline!: EntityTable<BibliotecaOffline, 'clave'>
  posiciones_pendientes!: EntityTable<PosicionPendiente, 'id_cliente'>

  constructor(nombre = 'acma') {
    super(nombre)
    this.version(1).stores({ metadatos: '&clave' })
    this.version(2).stores({
      metadatos: '&clave',
      catalogos_cache: '&clave, entidad, id, updated_at',
      folios_cache: '&id, estado, un_id, tecnico_id, updated_at',
      formularios_cache: '&id, tipo',
      respuestas_borrador: '&id, formulario_id, referencia_id, estado',
      evidencias_pendientes: '&id_cliente, respuesta_id, estado',
      mutaciones_pendientes: '&id_cliente, orden, estado, tipo',
      chat_mensajes_cache: '&id, chat_id, timestamp_servidor',
      chat_pendientes: '&id_cliente, chat_id, estado',
    })
    this.version(3).stores({
      metadatos: '&clave',
      catalogos_cache: '&clave, entidad, id, updated_at',
      folios_cache: '&id, estado, un_id, tecnico_id, updated_at',
      formularios_cache: '&id, tipo',
      respuestas_borrador: '&id, formulario_id, referencia_id, estado',
      evidencias_pendientes: '&id_cliente, respuesta_id, estado',
      mutaciones_pendientes: '&id_cliente, orden, estado, tipo',
      chat_mensajes_cache: '&id, chat_id, timestamp_servidor',
      chat_pendientes: '&id_cliente, chat_id, estado',
      biblioteca_offline: '&clave, clase, id, tipo_equipo_id, desactualizado',
    })
    this.version(4).stores({
      metadatos: '&clave',
      catalogos_cache: '&clave, entidad, id, updated_at',
      folios_cache: '&id, estado, un_id, tecnico_id, updated_at',
      formularios_cache: '&id, tipo',
      respuestas_borrador: '&id, formulario_id, referencia_id, estado',
      evidencias_pendientes: '&id_cliente, respuesta_id, estado',
      mutaciones_pendientes: '&id_cliente, orden, estado, tipo',
      chat_mensajes_cache: '&id, chat_id, timestamp_servidor',
      chat_pendientes: '&id_cliente, chat_id, estado',
      biblioteca_offline: '&clave, clase, id, tipo_equipo_id, desactualizado',
      posiciones_pendientes: '&id_cliente, jornada_id, enviado, capturada_at',
    })
  }
}

export let baseLocal = new BaseLocal()

/** Para pruebas: sustituye la base por una independiente. */
export function usarBaseLocal(nombre: string): BaseLocal {
  baseLocal = new BaseLocal(nombre)
  return baseLocal
}
