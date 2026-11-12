/** Cliente de /api/criticidad, /api/modos-falla, /api/mitigaciones y /api/reportes/iso55000 (F2-05, §6.9.3). */
import type {
  ConfiguracionCriticidad, Criticidad, CriticidadActivo, DetalleCriticidad, Dimensiones, Efectividad,
  EvaluacionHistorial, FilaRegistro, Guia, MatrizCriticidad, MatrizRiesgo, Mitigacion, MitigacionPendiente,
  ModoFalla, PlantillaIso, ResumenCriticidad, SugerenciaModo,
} from '../types/criticidad'
import { api, descargar } from './api'

type Params = Record<string, string | number | boolean | null | undefined>

// ------------------------------------------------------------- configuración
export const configuracion = (tenantId?: string | null) =>
  api<ConfiguracionCriticidad>('/criticidad/configuracion', { params: { tenant_id: tenantId } })
export const guardarConfiguracion = (cambios: Record<string, unknown>, tenantId?: string | null) =>
  api<ConfiguracionCriticidad>('/criticidad/configuracion', { metodo: 'PUT', cuerpo: cambios, params: { tenant_id: tenantId } })

// ------------------------------------------------------------ registro y resumen
export const registro = (params: Params = {}) => api<FilaRegistro[]>('/criticidad', { params })
export const resumen = (tenantId?: string | null) =>
  api<ResumenCriticidad>('/criticidad/resumen', { params: { tenant_id: tenantId } })
export const matriz = (tenantId?: string | null) =>
  api<MatrizCriticidad>('/criticidad/matriz', { params: { tenant_id: tenantId } })
export const guia = () => api<Guia>('/criticidad/guia')

// --------------------------------------------------------- evaluación por equipo
export const detalle = (equipoId: string) => api<DetalleCriticidad>(`/criticidad/equipos/${equipoId}`)
export const evaluar = (equipoId: string, dimensiones: Dimensiones, razon = '', motivo = 'evaluacion_inicial') =>
  api<CriticidadActivo>(`/criticidad/equipos/${equipoId}`, { metodo: 'POST', cuerpo: { dimensiones, razon, motivo } })
export const ajustarNivel = (equipoId: string, nivel: Criticidad, razon: string) =>
  api<CriticidadActivo>(`/criticidad/equipos/${equipoId}/ajuste`, { metodo: 'POST', cuerpo: { nivel, razon } })
export const recalcular = (equipoId: string) =>
  api<{ estado: string; nivel?: Criticidad; nivel_anterior?: Criticidad; indice?: string }>(
    `/criticidad/equipos/${equipoId}/recalcular`, { metodo: 'POST' })
export const historial = (equipoId: string, limite = 50) =>
  api<EvaluacionHistorial[]>(`/criticidad/equipos/${equipoId}/historial`, { params: { limite } })
export const evaluarMasivo = (datos: { tipo_equipo_id: string; dimensiones: Dimensiones; tenant_id?: string | null; solo_sin_evaluar?: boolean }) =>
  api<{ evaluados: number; omitidos: number; por_nivel: Record<Criticidad, number> }>(
    '/criticidad/masiva', { metodo: 'POST', cuerpo: datos })

// ------------------------------------------------------------- modos de falla
export const modosDeEquipo = (equipoId: string, params: Params = {}) =>
  api<ModoFalla[]>('/modos-falla', { params: { equipo_id: equipoId, ...params } })
export const sugerenciasDeModos = (equipoId: string, meses = 12) =>
  api<SugerenciaModo[]>('/modos-falla/sugerencias', { params: { equipo_id: equipoId, meses } })
export const matrizDeRiesgo = (tenantId?: string | null) =>
  api<MatrizRiesgo>('/modos-falla/matriz', { params: { tenant_id: tenantId } })
export const crearModo = (datos: Record<string, unknown>) =>
  api<ModoFalla>('/modos-falla', { metodo: 'POST', cuerpo: datos })
export const aceptarSugerencias = (equipoId: string, sugerencias: Record<string, unknown>[]) =>
  api<ModoFalla[]>('/modos-falla/aceptar-sugerencias', { metodo: 'POST', cuerpo: { equipo_id: equipoId, sugerencias } })
export const editarModo = (modoId: string, cambios: Record<string, unknown>) =>
  api<ModoFalla>(`/modos-falla/${modoId}`, { metodo: 'PUT', cuerpo: cambios })

// -------------------------------------------------------------- mitigaciones
export const mitigacionesDe = (modoFallaId: string) =>
  api<Mitigacion[]>('/mitigaciones', { params: { modo_falla_id: modoFallaId } })
export const mitigacionesPendientes = (params: Params = {}) =>
  api<MitigacionPendiente[]>('/mitigaciones/pendientes', { params })
export const crearMitigacion = (datos: Record<string, unknown>) =>
  api<Mitigacion>('/mitigaciones', { metodo: 'POST', cuerpo: datos })
export const cambiarEstadoMitigacion = (id: string, datos: { estado: string; fecha_implementacion?: string | null; razon?: string }) =>
  api<Mitigacion>(`/mitigaciones/${id}/estado`, { metodo: 'POST', cuerpo: datos })
export const efectividadDe = (id: string) => api<Efectividad>(`/mitigaciones/${id}/efectividad`)

// --------------------------------------------------- reportes de certificación
export const plantillasIso = () => api<PlantillaIso[]>('/reportes/iso55000')
export const descargarReporteIso = (tipo: string, formato: 'pdf' | 'excel', params: Record<string, string | undefined> = {}) =>
  descargar(`/reportes/iso55000/${tipo}`, { formato, ...params })
