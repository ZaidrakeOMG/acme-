/** Cliente de /api/rutas y de la ETA e incidencias de /api/operacion (F2-06, §6.8.2 y §6.8.4). */
import type {
  ConfiguracionRutas, Eta, Mercado, MiRuta, PlanDetalle, Propuesta, Simulacion, TiempoServicio, TipoIncidencia,
  TrazoRuta,
} from '../types/rutas'
import { api } from './api'

type Params = Record<string, string | number | boolean | null | undefined>

// ------------------------------------------------------------------ mercados
export const mercados = (params: Params = {}) => api<Mercado[]>('/rutas/mercados', { params })
export const crearMercado = (datos: Record<string, unknown>) =>
  api<Mercado>('/rutas/mercados', { metodo: 'POST', cuerpo: datos })
export const editarMercado = (id: string, cambios: Record<string, unknown>) =>
  api<Mercado>(`/rutas/mercados/${id}`, { metodo: 'PUT', cuerpo: cambios })
export const asignarUnidades = (id: string, unIds: string[]) =>
  api<{ mensaje: string }>(`/rutas/mercados/${id}/unidades`, { metodo: 'POST', cuerpo: { un_ids: unIds } })

// ------------------------------------------------------------------ configuración
export const configuracion = (params: Params = {}) =>
  api<ConfiguracionRutas>('/rutas/configuracion', { params })
export const guardarConfiguracion = (cambios: Record<string, unknown>, params: Params = {}) =>
  api<ConfiguracionRutas>('/rutas/configuracion', { metodo: 'PUT', cuerpo: cambios, params })
export const tiemposServicio = (params: Params = {}) =>
  api<TiempoServicio[]>('/rutas/tiempos-servicio', { params })
export const guardarTiempoServicio = (datos: Record<string, unknown>) =>
  api<TiempoServicio>('/rutas/tiempos-servicio', { metodo: 'PUT', cuerpo: datos })
export const sugerirTiempos = (meses = 6) =>
  api<TiempoServicio[]>('/rutas/tiempos-servicio/sugerir', { metodo: 'POST', params: { meses } })

// ------------------------------------------------------------------ plan del día
export const calcular = (mercadoId: string, fecha?: string) =>
  api<PlanDetalle>('/rutas/calcular', { metodo: 'POST', cuerpo: { mercado_id: mercadoId, fecha: fecha ?? null } })
export const planDelDia = (mercadoId: string, fecha?: string) =>
  api<PlanDetalle | null>('/rutas', { params: { mercado_id: mercadoId, fecha } })
export const plan = (planId: string) => api<PlanDetalle>(`/rutas/${planId}`)
export const trazos = (planId: string) => api<TrazoRuta[]>(`/rutas/${planId}/trazos`)
export const moverParada = (planId: string, paradaId: string, tecnicoDestinoId: string, orden?: number) =>
  api<PlanDetalle>(`/rutas/${planId}/paradas/${paradaId}/mover`, {
    metodo: 'POST', cuerpo: { tecnico_destino_id: tecnicoDestinoId, orden: orden ?? null },
  })
export const publicar = (planId: string) =>
  api<{ plan_id: string; estado: string; asignados: number; respetados: number; tecnicos: number }>(
    `/rutas/${planId}/publicar`, { metodo: 'POST' })
export const cerrar = (planId: string) =>
  api<{ plan_id: string; estado: string }>(`/rutas/${planId}/cerrar`, { metodo: 'POST' })
export const simular = (planId: string, movimientos: { folio_id: string; tecnico_destino_id: string }[]) =>
  api<Simulacion>(`/rutas/${planId}/simulacion`, { metodo: 'POST', cuerpo: { movimientos } })

// ------------------------------------------------------------------ recálculo y propuestas
export const recalcular = (planId: string, datos: Record<string, unknown>) =>
  api<Propuesta>(`/rutas/${planId}/recalcular`, { metodo: 'POST', cuerpo: datos })
export const propuestasPendientes = (params: Params = {}) =>
  api<Propuesta[]>('/rutas/propuestas/pendientes', { params })
export const aceptarPropuesta = (id: string) =>
  api<{ recalculo_id: string; aplicados: number; omitidos: unknown[] }>(
    `/rutas/propuestas/${id}/aceptar`, { metodo: 'POST' })
export const rechazarPropuesta = (id: string, razon = '') =>
  api<{ recalculo_id: string; estado: string }>(`/rutas/propuestas/${id}/rechazar`,
                                                { metodo: 'POST', cuerpo: { razon } })

// ------------------------------------------------------------------ ETA e incidencias
export const etaDeFolio = (folioId: string) => api<Eta>('/operacion/eta', { params: { folio_id: folioId } })
export const refrescarEta = (planId: string, tecnicoId: string) =>
  api<{ plan_id: string; tecnico_id: string; paradas: unknown[] }>(
    `/operacion/eta/${planId}/refrescar`, { metodo: 'POST', params: { tecnico_id: tecnicoId } })
export const miRuta = () => api<MiRuta>('/operacion/mi-ruta')
export const reportarIncidencia = (tipo: TipoIncidencia, detalle = '', folioId?: string) =>
  api<{ registrada: boolean; recalculo_id: string | null; movimientos: number; mensaje: string }>(
    '/operacion/incidencia', { metodo: 'POST', cuerpo: { tipo, detalle, folio_id: folioId ?? null } })
