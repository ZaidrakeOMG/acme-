/**
 * Transporte híbrido de respuestas de formularios (P03 `usarTransporte`): intenta HTTP y, sin red, escribe en IndexedDB
 * y encola la mutación (§6.2 client-wins). Los ids locales (`id_cliente`) los resuelve el servidor al sincronizar.
 */
import { api } from '../api'
import { baseLocal } from '../db'
import type { EvidenciaSubida, Transporte } from '../formularios/respuestas'
import { esSinConexion, nuevoIdCliente, syncEngine } from '../syncEngine'
import type { ContextoRespuesta, Evidencia, Respuesta } from '../../types/formularios'

function respuestaLocal(id: string, formularioId: string, origen: string, contexto: ContextoRespuesta, referenciaId: string | null, respuestas: Record<string, unknown>, estado: 'en_progreso' | 'enviado', iniciadoAt: string): Respuesta {
  return {
    id, formulario_id: formularioId, version_id: '', numero_version: 0, tenant_id: contexto.tenant_id ?? null, un_id: contexto.un_id ?? null, equipo_id: contexto.equipo_id ?? null,
    origen, referencia_id: referenciaId, respuestas_json: respuestas, estado, iniciado_at: iniciadoAt, enviado_at: estado === 'enviado' ? new Date().toISOString() : null,
    inmutable: estado === 'enviado', nombre_formulario: null, errores: [],
  }
}

async function intentar<T>(fn: () => Promise<T>): Promise<T | null> {
  if (!syncEngine.enLinea()) return null
  try {
    return await fn()
  } catch (e) {
    if (esSinConexion(e)) return null
    throw e
  }
}

export const transporteHibrido: Transporte = {
  async crear(formularioId, origen, contexto, referenciaId) {
    const remota = await intentar(() => api<Respuesta>(`/formularios/${formularioId}/respuestas`, { metodo: 'POST', cuerpo: { origen, contexto, referencia_id: referenciaId ?? null, dispositivo: { modo: 'hibrido' } } }))
    if (remota) return remota
    const id = nuevoIdCliente()
    const ahora = new Date().toISOString()
    await baseLocal.respuestas_borrador.put({ id, formulario_id: formularioId, origen, referencia_id: referenciaId ?? null, contexto: contexto as Record<string, unknown>, respuestas: {}, estado: 'en_progreso', iniciado_at: ahora, actualizado: ahora, creada_offline: true })
    await syncEngine.encolar('guardar_respuesta', { respuesta_id: id, crear: { formulario_id: formularioId, origen, referencia_id: referenciaId ?? null, contexto }, respuestas: {} }, 'Formulario iniciado sin conexión', { idCliente: id })
    return respuestaLocal(id, formularioId, origen, contexto, referenciaId ?? null, {}, 'en_progreso', ahora)
  },

  async guardar(respuestaId, respuestas, dispositivo) {
    const borrador = await baseLocal.respuestas_borrador.get(respuestaId)
    if (!borrador || !borrador.creada_offline) {
      const remota = await intentar(() => api<Respuesta>(`/formularios/respuestas/${respuestaId}`, { metodo: 'PUT', cuerpo: { respuestas, dispositivo: dispositivo ?? { modo: 'hibrido' } } }))
      if (remota) {
        await baseLocal.respuestas_borrador.put({ id: respuestaId, formulario_id: remota.formulario_id, origen: remota.origen, referencia_id: remota.referencia_id, contexto: { tenant_id: remota.tenant_id, un_id: remota.un_id, equipo_id: remota.equipo_id }, respuestas: remota.respuestas_json, estado: remota.estado, iniciado_at: remota.iniciado_at, actualizado: new Date().toISOString(), creada_offline: false })
        return remota
      }
    }
    // Sin red (o respuesta creada offline): borrador local + una sola mutación pendiente por respuesta.
    const b = borrador ?? { id: respuestaId, formulario_id: '', origen: 'independiente', referencia_id: null, contexto: {}, respuestas: {}, estado: 'en_progreso' as const, iniciado_at: new Date().toISOString(), actualizado: '', creada_offline: false }
    await baseLocal.respuestas_borrador.put({ ...b, respuestas, actualizado: new Date().toISOString() })
    const pendientes = await baseLocal.mutaciones_pendientes.where('tipo').equals('guardar_respuesta').toArray()
    const previa = pendientes.find((m) => m.estado === 'pendiente' && m.payload.respuesta_id === respuestaId)
    if (previa) await syncEngine.actualizarPendiente(previa.id_cliente, { ...previa.payload, respuestas })
    else await syncEngine.encolar('guardar_respuesta', { respuesta_id: respuestaId, respuestas }, 'Formulario guardado sin conexión')
    return respuestaLocal(respuestaId, b.formulario_id, b.origen, b.contexto as ContextoRespuesta, b.referencia_id, respuestas, 'en_progreso', b.iniciado_at)
  },

  async enviar(respuestaId) {
    const borrador = await baseLocal.respuestas_borrador.get(respuestaId)
    if (!borrador?.creada_offline) {
      const remota = await intentar(() => api<Respuesta>(`/formularios/respuestas/${respuestaId}/enviar`, { metodo: 'POST' }))
      if (remota) {
        await baseLocal.respuestas_borrador.delete(respuestaId)
        return remota
      }
    }
    const b = borrador ?? { id: respuestaId, formulario_id: '', origen: 'independiente', referencia_id: null, contexto: {}, respuestas: {}, estado: 'en_progreso' as const, iniciado_at: new Date().toISOString(), actualizado: '', creada_offline: false }
    await baseLocal.respuestas_borrador.put({ ...b, estado: 'enviado', actualizado: new Date().toISOString() })
    await syncEngine.encolar('enviar_respuesta', { respuesta_id: respuestaId, respuestas: b.respuestas }, 'Formulario enviado sin conexión (se aplicará con la hora real)')
    return respuestaLocal(respuestaId, b.formulario_id, b.origen, b.contexto as ContextoRespuesta, b.referencia_id, b.respuestas, 'enviado', b.iniciado_at)
  },

  async subirEvidencia(respuestaId, e: EvidenciaSubida) {
    const borrador = await baseLocal.respuestas_borrador.get(respuestaId)
    if (!borrador?.creada_offline) {
      const remota = await intentar(() => {
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
      })
      if (remota) return remota
    }
    const pendiente = await syncEngine.encolarEvidencia({ respuesta_id: respuestaId, campo_clave: e.campoClave, nombre: e.nombre, mime: e.archivo.type || 'image/jpeg', blob: e.archivo, etiqueta: e.etiqueta ?? null, geolat: e.geolat ?? null, geolng: e.geolng ?? null })
    const tipo: Evidencia['tipo'] = e.nombre.startsWith('firma') ? 'firma' : e.nombre.startsWith('dibujo') ? 'dibujo' : e.archivo.type.startsWith('audio') ? 'audio' : e.archivo.type.startsWith('image') ? 'foto' : 'archivo'
    return { id: pendiente.id_cliente, created_at: pendiente.creado, respuesta_id: respuestaId, campo_clave: e.campoClave, tipo, nombre_original: e.nombre, mime: pendiente.mime, bytes: e.archivo.size,
             ancho_px: null, alto_px: null, etiqueta: e.etiqueta ?? null, orden: e.orden ?? 0, hash_sha256: pendiente.hash_sha256, anotaciones_json: e.anotaciones ?? {}, calidad: { pendiente: true } }
  },

  async eliminarEvidencia(respuestaId, evidenciaId) {
    const pendiente = await baseLocal.evidencias_pendientes.get(evidenciaId)
    if (pendiente) {
      await baseLocal.evidencias_pendientes.delete(evidenciaId)
      return
    }
    await api(`/formularios/respuestas/${respuestaId}/evidencias/${evidenciaId}`, { metodo: 'DELETE' })
  },
}
