/**
 * Escrituras de respuestas de formularios. Toda escritura pasa por aquí para que P05 pueda interceptarla con la cola
 * offline (IndexedDB) sin tocar el renderizador: basta con sustituir `transporte`.
 */
import { api, descargar } from '../api'
import type { ContextoRespuesta, Evidencia, Formulario, OpcionCatalogo, Respuesta } from '../../types/formularios'

export interface EvidenciaSubida {
  archivo: Blob
  nombre: string
  campoClave: string
  etiqueta?: string | null
  orden?: number
  anotaciones?: Record<string, unknown>
  imagenAnotada?: Blob | null
  geolat?: number | null
  geolng?: number | null
}

export interface Transporte {
  crear(formularioId: string, origen: string, contexto: ContextoRespuesta, referenciaId?: string | null): Promise<Respuesta>
  guardar(respuestaId: string, respuestas: Record<string, unknown>, dispositivo?: Record<string, unknown>): Promise<Respuesta>
  enviar(respuestaId: string): Promise<Respuesta>
  subirEvidencia(respuestaId: string, e: EvidenciaSubida): Promise<Evidencia>
  eliminarEvidencia(respuestaId: string, evidenciaId: string): Promise<void>
}

const transporteHttp: Transporte = {
  crear: (formularioId, origen, contexto, referenciaId) =>
    api<Respuesta>(`/formularios/${formularioId}/respuestas`, { metodo: 'POST', cuerpo: { origen, contexto, referencia_id: referenciaId ?? null, dispositivo: dispositivo() } }),
  guardar: (respuestaId, respuestas, disp) =>
    api<Respuesta>(`/formularios/respuestas/${respuestaId}`, { metodo: 'PUT', cuerpo: { respuestas, dispositivo: disp ?? dispositivo() } }),
  enviar: (respuestaId) => api<Respuesta>(`/formularios/respuestas/${respuestaId}/enviar`, { metodo: 'POST' }),
  subirEvidencia: (respuestaId, e) => {
    const f = new FormData()
    f.append('archivo', e.archivo, e.nombre)
    f.append('campo_clave', e.campoClave)
    if (e.etiqueta) f.append('etiqueta', e.etiqueta)
    if (e.orden !== undefined) f.append('orden', String(e.orden))
    if (e.anotaciones) f.append('anotaciones', JSON.stringify(e.anotaciones))
    if (e.imagenAnotada) f.append('imagen_anotada', e.imagenAnotada, 'anotada.png')
    if (e.geolat != null) f.append('geolat', String(e.geolat))
    if (e.geolng != null) f.append('geolng', String(e.geolng))
    return api<Evidencia>(`/formularios/respuestas/${respuestaId}/evidencias`, { metodo: 'POST', formulario: f })
  },
  eliminarEvidencia: async (respuestaId, evidenciaId) => {
    await api(`/formularios/respuestas/${respuestaId}/evidencias/${evidenciaId}`, { metodo: 'DELETE' })
  },
}

let transporte: Transporte = transporteHttp

/** P05: `usarTransporte(colaOffline)` intercepta todas las escrituras. */
export function usarTransporte(t: Transporte | null) {
  transporte = t ?? transporteHttp
}

export function dispositivo(): Record<string, unknown> {
  if (typeof navigator === 'undefined') return {}
  return { user_agent: navigator.userAgent.slice(0, 200), en_linea: navigator.onLine, idioma: navigator.language }
}

export const crearRespuesta = (formularioId: string, origen: string, contexto: ContextoRespuesta, referenciaId?: string | null) =>
  transporte.crear(formularioId, origen, contexto, referenciaId)

/** Única puerta de escritura de valores (guardado parcial, reanudable). */
export const guardarRespuesta = (respuestaId: string, respuestas: Record<string, unknown>) => transporte.guardar(respuestaId, respuestas)

export const enviarRespuesta = (respuestaId: string) => transporte.enviar(respuestaId)
export const subirEvidencia = (respuestaId: string, e: EvidenciaSubida) => transporte.subirEvidencia(respuestaId, e)
export const eliminarEvidencia = (respuestaId: string, evidenciaId: string) => transporte.eliminarEvidencia(respuestaId, evidenciaId)

export const obtenerRespuesta = (respuestaId: string) => api<Respuesta>(`/formularios/respuestas/${respuestaId}`)
export const obtenerEvidencias = (respuestaId: string) => api<Evidencia[]>(`/formularios/respuestas/${respuestaId}/evidencias`)
export const obtenerFormulario = (formularioId: string) => api<Formulario>(`/formularios/${formularioId}`)
export const descargarEvidencia = (respuestaId: string, evidenciaId: string) => descargar(`/formularios/respuestas/${respuestaId}/evidencias/${evidenciaId}/archivo`)

const cacheOpciones = new Map<string, Promise<{ opciones: OpcionCatalogo[]; aviso: string | null }>>()

/** Opciones de un catálogo del sistema (con contexto y cascada), cacheadas por consulta. */
export function opcionesCatalogo(params: Record<string, string | undefined>) {
  const clave = JSON.stringify(params)
  if (!cacheOpciones.has(clave)) {
    const promesa = api<{ opciones: OpcionCatalogo[]; aviso: string | null }>('/formularios/opciones', { params }).catch((e) => {
      cacheOpciones.delete(clave)
      throw e
    })
    cacheOpciones.set(clave, promesa)
  }
  return cacheOpciones.get(clave)!
}

export function limpiarCacheOpciones() {
  cacheOpciones.clear()
}
