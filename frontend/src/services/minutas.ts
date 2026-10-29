/** Cliente de /api/minutas, /api/hallazgos, /api/notificaciones, /api/seguimiento y /api/clasificacion (P07). */
import type { ClasificacionConfig, CambioEstado, Calificacion, EventoNotificable, Hallazgo, MinutaConfiguracion, MinutaDetalle, MinutaResumen, Modulo, Notificacion, OpcionClasificacion, PendienteClasificacion, Preferencia, RegistroSeguimiento, ReporteEjecutivo, RespuestaHallazgoEntrada } from '../types/minutas'
import { api, descargar } from './api'

type Params = Record<string, string | number | boolean | null | undefined>

// ---------------------------------------------------------------- minuta
export const listarMinutas = (params: Params = {}) => api<MinutaResumen[]>('/minutas', { params })
export const obtenerMinuta = (id: string) => api<MinutaDetalle>(`/minutas/${id}`)
export const generarMinuta = (tenantId: string, fecha?: string, forzar = false) => api<MinutaResumen[]>('/minutas/generar', { metodo: 'POST', params: { tenant_id: tenantId, fecha, forzar } })
export const validarMinuta = (id: string, notas: string) => api<MinutaDetalle>(`/minutas/${id}/validar`, { metodo: 'POST', cuerpo: { notas } })
export const responderHallazgo = (minutaId: string, hallazgoId: string, datos: RespuestaHallazgoEntrada) =>
  api(`/minutas/${minutaId}/hallazgos/${hallazgoId}/responder`, { metodo: 'POST', cuerpo: { canal: 'app', ...datos } })
export const pdfMinuta = (id: string) => descargar(`/minutas/${id}/pdf`)
export const configuracionMinuta = (tenantId?: string) => api<MinutaConfiguracion>('/minutas/configuracion', { params: { tenant_id: tenantId } })
export const guardarConfiguracionMinuta = (datos: Partial<MinutaConfiguracion>, tenantId?: string) => api<MinutaConfiguracion>('/minutas/configuracion', { metodo: 'PUT', cuerpo: datos, params: { tenant_id: tenantId } })
export const listarHallazgos = (params: Params = {}) => api<Hallazgo[]>('/hallazgos', { params })
export const crearHallazgo = (datos: { folio_id?: string; un_id?: string; descripcion: string; nivel_urgencia: string }) => api<Hallazgo>('/hallazgos', { metodo: 'POST', cuerpo: datos })
export const marcarMensaje = (chatId: string, mensajeId: string, como: 'hallazgo' | 'peticion', urgencia?: string) =>
  api<{ tipo: string; registro: Record<string, unknown> }>(`/chats/${chatId}/mensajes/${mensajeId}/marcar`, { metodo: 'POST', cuerpo: { como, nivel_urgencia: urgencia ?? null } })

// --------------------------------------------------------- notificaciones
export const bandejaNotificaciones = (soloNoLeidas = false, limite = 50) => api<Notificacion[]>('/notificaciones', { params: { solo_no_leidas: soloNoLeidas, limite } })
export const noLeidas = () => api<{ no_leidas: number }>('/notificaciones/no-leidas')
export const marcarLeidas = (ids?: string[]) => api<{ marcadas: number }>('/notificaciones/leidas', { metodo: 'POST', cuerpo: { ids: ids ?? null } })
export const eventosNotificables = () => api<{ eventos: EventoNotificable[]; canales: { clave: string; nombre: string; fase: number }[] }>('/notificaciones/eventos')
export const preferencias = () => api<Preferencia[]>('/notificaciones/preferencias')
export const guardarPreferencia = (evento: string, canales: string[]) => api<Preferencia>('/notificaciones/preferencias', { metodo: 'PUT', cuerpo: { evento, canales } })

// ------------------------------------------------------------ seguimiento
export const listarModulo = (modulo: Modulo, params: Params = {}) => api<RegistroSeguimiento[]>(`/seguimiento/${modulo}`, { params })
export const obtenerRegistro = (modulo: Modulo, id: string) => api<RegistroSeguimiento>(`/seguimiento/${modulo}/${id}`)
export const cambiarEstado = (modulo: Modulo, id: string, datos: CambioEstado) => api<RegistroSeguimiento>(`/seguimiento/${modulo}/${id}/estado`, { metodo: 'POST', cuerpo: datos })
export const porUN = (unId: string) => api<Record<string, RegistroSeguimiento[] | string>>(`/seguimiento/por-un/${unId}`)
export const reporteEjecutivo = (params: Params = {}) => api<ReporteEjecutivo>('/seguimiento/reporte/ejecutivo', { params })
export const descargarReporte = (formato: 'xlsx' | 'pdf', params: Record<string, string | undefined> = {}) => descargar(`/seguimiento/reporte/ejecutivo.${formato}`, params)
export const prepararCotizacion = (id: string, datos: { descripcion?: string; monto?: string; detalle?: Record<string, unknown> }) => api<RegistroSeguimiento>(`/seguimiento/cotizaciones/${id}/preparar`, { metodo: 'POST', cuerpo: datos })
export const enviarCotizacion = (id: string) => api<RegistroSeguimiento>(`/seguimiento/cotizaciones/${id}/enviar`, { metodo: 'POST' })
export const convertirCotizacion = (id: string) => api<RegistroSeguimiento & { trabajo_especial: { id: string; numero: string } }>(`/seguimiento/cotizaciones/${id}/convertir`, { metodo: 'POST' })
export const responderCotizacion = (id: string, autorizar: boolean, notas = '', pasarAPresupuesto?: boolean) =>
  api<RegistroSeguimiento>(`/seguimiento/cotizaciones/${id}/responder`, { metodo: 'POST', cuerpo: { autorizar, notas, pasar_a_presupuesto_si_rechaza: pasarAPresupuesto ?? null } })
export const pdfCotizacion = (id: string) => descargar(`/seguimiento/cotizaciones/${id}/pdf`)
export const enviarCotizacionExterno = (id: string, destinatarios: string[], comentario: string) => api(`/seguimiento/cotizaciones/${id}/enviar-externo`, { metodo: 'POST', cuerpo: { destinatarios, comentario } })
export const reactivarPresupuesto = (id: string, como: 'folio' | 'cotizacion', notas = '') => api<RegistroSeguimiento & { registro: { tipo: string; id: string; numero: string | null } }>(`/seguimiento/presupuesto/${id}/reactivar`, { metodo: 'POST', cuerpo: { como, notas } })
export const descartarPresupuesto = (id: string, notas: string) => api<RegistroSeguimiento>(`/seguimiento/presupuesto/${id}/descartar`, { metodo: 'POST', cuerpo: { notas } })
export const revisarPresupuesto = (id: string, notas: string) => api<RegistroSeguimiento>(`/seguimiento/presupuesto/${id}/revisar`, { metodo: 'POST', cuerpo: { notas } })
export const actualizarInterno = (id: string, notas: string) => api<RegistroSeguimiento>(`/seguimiento/interno/${id}/actualizar`, { metodo: 'POST', cuerpo: { notas } })
export const confirmarTercero = (id: string, notas: string) => api<RegistroSeguimiento & { folio: { id: string; numero_folio: string } }>(`/seguimiento/reprogramacion/${id}/confirmar-tercero`, { metodo: 'POST', cuerpo: { notas } })

// ---------------------------------------------------------- clasificación
export const pendientesClasificacion = () => api<PendienteClasificacion[]>('/clasificacion/pendientes')
export const clasificarFolio = (folioId: string, opcion: OpcionClasificacion, fechaTentativa?: string | null, notas = '') =>
  api(`/clasificacion/${folioId}`, { metodo: 'POST', cuerpo: { opcion, fecha_tentativa: fechaTentativa ?? null, notas } })
export const configuracionClasificacion = () => api<ClasificacionConfig>('/clasificacion/configuracion')
export const guardarConfiguracionClasificacion = (datos: Partial<ClasificacionConfig>) => api<ClasificacionConfig>('/clasificacion/configuracion', { metodo: 'PUT', cuerpo: datos })
export const calificaciones = (periodo?: string) => api<Calificacion[]>('/clasificacion/calificaciones', { params: { periodo } })
export const calcularCalificaciones = (periodo?: string) => api<Calificacion[]>('/clasificacion/calificaciones/calcular', { metodo: 'POST', params: { periodo } })

export function abrirBlob(blob: Blob, nombre: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = nombre
  a.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
