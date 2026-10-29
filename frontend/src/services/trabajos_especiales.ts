/** Cliente de /api/trabajos-especiales y /api/oc-activos (P08). */
import type { Tecnico } from '../types/api'
import type { RegistroSeguimiento } from '../types/minutas'
import type {
  AutorizacionActivoDetalle, EstatusOCEntrada, PendienteOC, ProgramarEntrada, ReporteTE, TrabajoEspecial, TrabajoEspecialDetalle, TrabajoEspecialEntrada,
} from '../types/trabajos_especiales'
import { api, descargar } from './api'

type Params = Record<string, string | number | boolean | null | undefined>

export const listarTE = (params: Params = {}) => api<TrabajoEspecial[]>('/trabajos-especiales', { params })
export const obtenerTE = (id: string) => api<TrabajoEspecialDetalle>(`/trabajos-especiales/${id}`)
export const crearTE = (datos: TrabajoEspecialEntrada) => api<TrabajoEspecial>('/trabajos-especiales', { metodo: 'POST', cuerpo: datos })
export const enviarTE = (id: string, datos: { notas?: string; monto?: string | null; descripcion?: string | null } = {}) => api<TrabajoEspecialDetalle>(`/trabajos-especiales/${id}/enviar`, { metodo: 'POST', cuerpo: datos })
export const aceptarTE = (id: string, comentario = '', canal = 'app') => api<TrabajoEspecialDetalle>(`/trabajos-especiales/${id}/aceptar`, { metodo: 'POST', cuerpo: { canal, comentario } })
export const rechazarTE = (id: string, comentario: string, canal = 'app') => api<TrabajoEspecialDetalle>(`/trabajos-especiales/${id}/rechazar`, { metodo: 'POST', cuerpo: { canal, comentario } })
export const programarTE = (id: string, datos: ProgramarEntrada) => api<TrabajoEspecialDetalle>(`/trabajos-especiales/${id}/programar`, { metodo: 'POST', cuerpo: datos })
export const iniciarTE = (id: string, notas = '') => api<TrabajoEspecialDetalle>(`/trabajos-especiales/${id}/iniciar`, { metodo: 'POST', cuerpo: { notas } })
export const cerrarTE = (id: string, notas = '') => api<TrabajoEspecialDetalle>(`/trabajos-especiales/${id}/cerrar`, { metodo: 'POST', cuerpo: { notas } })
export const cancelarTE = (id: string, notas: string) => api<TrabajoEspecialDetalle>(`/trabajos-especiales/${id}/cancelar`, { metodo: 'POST', cuerpo: { notas } })
export const cambiarEstadoTE = (id: string, estado: string, notas = '') => api<TrabajoEspecialDetalle>(`/trabajos-especiales/${id}/estado`, { metodo: 'POST', cuerpo: { estado, notas } })
export const cotizacionRetroactiva = (id: string, datos: { monto?: string | null; descripcion?: string | null }) =>
  api<RegistroSeguimiento>(`/trabajos-especiales/${id}/cotizacion-retroactiva`, { metodo: 'POST', cuerpo: datos })
export const reporteTE = (params: Params = {}) => api<ReporteTE>('/trabajos-especiales/reporte', { params })
export const descargarReporteTE = (formato: 'xlsx' | 'pdf', params: Record<string, string | undefined> = {}) => descargar(`/trabajos-especiales/reporte.${formato}`, params)
export const tecnicosDelPrestador = () => api<Tecnico[]>('/catalogos/tecnicos')

export const pendientesOC = (params: Params = {}) => api<PendienteOC[]>('/oc-activos/pendientes', { params })
export const obtenerOC = (folioId: string) => api<AutorizacionActivoDetalle>(`/oc-activos/${folioId}`)
export const registrarEstatusOC = (folioId: string, datos: EstatusOCEntrada) => api<AutorizacionActivoDetalle>(`/oc-activos/${folioId}/estatus`, { metodo: 'POST', cuerpo: datos })
