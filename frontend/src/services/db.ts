/**
 * Base local IndexedDB (Dexie) — §6.2 capa 3. Versión 2 (P05): caché de catálogos, folios y formularios, borradores de
 * respuestas, evidencias pendientes (blob + metadatos), cola FIFO de mutaciones con `id_cliente`, caché y pendientes del chat.
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
  }
}

export let baseLocal = new BaseLocal()

/** Para pruebas: sustituye la base por una independiente. */
export function usarBaseLocal(nombre: string): BaseLocal {
  baseLocal = new BaseLocal(nombre)
  return baseLocal
}
