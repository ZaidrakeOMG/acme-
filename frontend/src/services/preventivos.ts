/** Cliente de /api/planes, /api/preventivos y /api/reasignaciones (P06). */
import type {
  Autorizacion, Candidato, FilaCalendario, FilaCalendarioEntrada, Plan, PlanEntrada, Publicacion, RazonReasignacion, ReasignacionFolio, ReasignarEntrada,
  ReporteReasignaciones, TareasMateriales,
} from '../types/preventivos'
import type { CanalAprobacion } from '../types/folios'
import { api } from './api'

type Params = Record<string, string | number | boolean | null | undefined>

// ---------------------------------------------------------------- planes
export const listarPlanes = (params: Params = {}) => api<Plan[]>('/planes', { params })
export const obtenerPlan = (id: string) => api<Plan>(`/planes/${id}`)
export const crearPlan = (datos: PlanEntrada, prestadorId?: string) => api<Plan>('/planes', { metodo: 'POST', cuerpo: datos, params: { prestador_id: prestadorId } })
export const editarPlan = (id: string, cambios: Partial<PlanEntrada>) => api<Plan>(`/planes/${id}`, { metodo: 'PUT', cuerpo: cambios })
export const asignarPlanAEquipo = (planId: string, equipoId: string, fechaBase?: string | null) =>
  api(`/planes/${planId}/equipos`, { metodo: 'POST', cuerpo: { equipo_id: equipoId, fecha_base: fechaBase ?? null } })
export const quitarPlanDeEquipo = (planId: string, equipoId: string) => api(`/planes/${planId}/equipos/${equipoId}`, { metodo: 'DELETE' })

// ------------------------------------------------------------ calendario
export const listarCalendario = (params: Params = {}) => api<FilaCalendario[]>('/preventivos/calendario', { params })
export const cargarCalendario = (filas: FilaCalendarioEntrada[], tenantId?: string | null) =>
  api<FilaCalendario[]>('/preventivos/calendario', { metodo: 'POST', cuerpo: { tenant_id: tenantId ?? null, filas } })
export const editarCalendario = (id: string, cambios: Partial<FilaCalendarioEntrada>) => api<FilaCalendario>(`/preventivos/calendario/${id}`, { metodo: 'PATCH', cuerpo: cambios })
export const publicarMes = (mes: string, tenantId?: string | null) => api<Publicacion>('/preventivos/calendario/publicar', { metodo: 'POST', params: { mes, tenant_id: tenantId } })
export const publicaciones = (tenantId?: string | null) => api<Publicacion[]>('/preventivos/calendario/publicaciones', { params: { tenant_id: tenantId } })
export const generarAhora = (horizonteDias = 7) => api<{ planes: number; manuales: number; omitidos: number; errores: number }>('/preventivos/generar', { metodo: 'POST', params: { horizonte_dias: horizonteDias } })

// --------------------------------------------------------- autorizaciones
export const solicitarReprogramacion = (folioId: string, razon: string, fechaNueva: string) =>
  api<Autorizacion>(`/preventivos/${folioId}/solicitar-reprogramacion`, { metodo: 'POST', cuerpo: { razon, fecha_nueva: fechaNueva } })
export const solicitarCancelacion = (folioId: string, razon: string) => api<Autorizacion>(`/preventivos/${folioId}/solicitar-cancelacion`, { metodo: 'POST', cuerpo: { razon } })
export const listarAutorizaciones = (params: Params = {}) => api<Autorizacion[]>('/preventivos/autorizaciones', { params })
export const resolverAutorizacion = (id: string, autorizar: boolean, notas = '', canal: CanalAprobacion = 'app') =>
  api<Autorizacion>(`/preventivos/autorizaciones/${id}/${autorizar ? 'autorizar' : 'rechazar'}`, { metodo: 'POST', cuerpo: { notas, canal } })
export const planDelFolio = (folioId: string) => api<TareasMateriales>(`/preventivos/${folioId}/plan`)

// ------------------------------------------------------------ reasignación
export const candidatosReasignacion = (folioId: string) => api<Candidato[]>(`/folios/${folioId}/reasignacion/candidatos`)
export const reasignarFolio = (folioId: string, datos: ReasignarEntrada) => api<ReasignacionFolio>(`/folios/${folioId}/reasignar`, { metodo: 'POST', cuerpo: datos })
export const reasignacionesDelFolio = (folioId: string) => api<ReasignacionFolio[]>(`/folios/${folioId}/reasignaciones`)
export const reporteReasignaciones = (params: Params = {}) => api<ReporteReasignaciones>('/reasignaciones/reporte', { params })
export const razonesReasignacion = (params: Params = {}) => api<RazonReasignacion[]>('/reasignaciones/razones', { params })
export const crearRazon = (datos: Omit<RazonReasignacion, 'id' | 'prestador_id'>) => api<RazonReasignacion>('/reasignaciones/razones', { metodo: 'POST', cuerpo: datos })
export const editarRazon = (id: string, datos: Omit<RazonReasignacion, 'id' | 'prestador_id'>) => api<RazonReasignacion>(`/reasignaciones/razones/${id}`, { metodo: 'PATCH', cuerpo: datos })

/** Mes AAAA-MM de una fecha (hoy por defecto). */
export function mesDe(d = new Date()): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}

/** Parámetros legibles de un trigger de Fase 1. */
export function describirTrigger(t: { tipo_trigger: string; parametros_json: Record<string, unknown> }): string {
  const p = t.parametros_json
  if (t.tipo_trigger === 'tiempo_fijo') return 'cada_dias' in p ? `cada ${String(p.cada_dias)} días` : `cada ${String(p.cada)} ${String(p.unidad)}`
  if (t.tipo_trigger === 'calendario') return 'fechas' in p ? `fechas: ${(p.fechas as string[]).join(', ')}` : `cada ${String(p.dia)}/${String(p.mes)}`
  return `${t.tipo_trigger} (Fase 2)`
}
