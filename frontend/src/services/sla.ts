/** Cliente de /api/sla, /api/bi y el panel de /api/alertas (P10). */
import type { AlertaEfectiva } from '../types/api'
import type {
  AlertaPanel, CumplimientoContrato, Exclusion, FormatoReporte, Iguala, Jornada, Penalizacion, ReporteGenerado,
  ReporteProgramado, SLAFolio, Tablero,
} from '../types/sla'
import { api, descargar } from './api'

type Params = Record<string, string | number | boolean | null | undefined>

// ------------------------------------------------------------------ SLA
export const slaDelFolio = (folioId: string) => api<SLAFolio>(`/sla/folios/${folioId}`)
export const registrarExclusion = (folioId: string, datos: { causa: string; descripcion: string; timestamp_inicio: string; timestamp_fin: string }) =>
  api<Exclusion>(`/sla/folios/${folioId}/exclusiones`, { metodo: 'POST', cuerpo: datos })
export const listarExclusiones = (params: Params = {}) => api<Exclusion[]>('/sla/exclusiones', { params })
export const decidirExclusion = (id: string, aprobada: boolean, razon = '') =>
  api<Exclusion>(`/sla/exclusiones/${id}/decidir`, { metodo: 'POST', cuerpo: { aprobada, razon } })

// -------------------------------------------------- penalizaciones e iguala
export const cumplimientoContrato = (contratoId: string, params: Params = {}) =>
  api<CumplimientoContrato>(`/sla/contratos/${contratoId}/cumplimiento`, { params })
export const listarPenalizaciones = (contratoId: string) => api<Penalizacion[]>(`/sla/contratos/${contratoId}/penalizaciones`)
export const calcularPenalizaciones = (contratoId: string, periodo: string) =>
  api<Penalizacion>(`/sla/contratos/${contratoId}/penalizaciones/calcular`, { metodo: 'POST', params: { periodo } })
export const cambiarEstadoPenalizacion = (id: string, estado: string) =>
  api<Penalizacion>(`/sla/penalizaciones/${id}/estado`, { metodo: 'POST', cuerpo: { estado } })
export const archivoPenalizaciones = (id: string, formato: 'pdf' | 'xlsx') =>
  descargar(`/sla/penalizaciones/${id}/archivo`, { formato })
export const listarIguala = (contratoId: string) => api<Iguala[]>(`/sla/contratos/${contratoId}/iguala`)
export const calcularIguala = (contratoId: string, periodo: string) =>
  api<Iguala>(`/sla/contratos/${contratoId}/iguala/calcular`, { metodo: 'POST', params: { periodo } })

// -------------------------------------------------------------- alertas
export const panelAlertas = (params: Params = {}) => api<AlertaPanel[]>('/alertas/panel', { params })
export const marcarVista = (id: string) => api<AlertaPanel>(`/alertas/historial/${id}/vista`, { metodo: 'POST' })
export const atenderAlerta = (id: string, nota: string) =>
  api<AlertaPanel>(`/alertas/historial/${id}/atender`, { metodo: 'POST', cuerpo: { nota } })
export const escalaciones = () => api<AlertaEfectiva[]>('/alertas/escalaciones')
export const configurarEscalacion = (clave: string, escalacion_de: string | null) =>
  api<AlertaEfectiva>('/alertas/escalaciones', { metodo: 'PUT', cuerpo: { clave, escalacion_de } })

// ------------------------------------------------------------------- BI
export const tablero = (params: Params = {}) => api<Tablero>('/bi/tablero', { params })
export const jornada = () => api<Jornada>('/bi/jornada')
export const indicador = <T>(nombre: string, params: Params = {}) =>
  api<{ indicador: string; periodo: { desde: string; hasta: string }; valor: T }>(`/bi/indicador/${nombre}`, { params })

// -------------------------------------------------------------- reportes
export const generarReporte = (datos: { tipo_reporte: string; formato: FormatoReporte; desde?: string; hasta?: string; grupo_id?: string | null; un_id?: string | null }) =>
  descargar('/bi/reportes/generar', {}, { metodo: 'POST', cuerpo: datos })
export const reportesGenerados = (params: Params = {}) => api<ReporteGenerado[]>('/bi/reportes/generados', { params })
export const archivoReporte = (id: string) => descargar(`/bi/reportes/generados/${id}/archivo`)
export const reportesProgramados = () => api<ReporteProgramado[]>('/bi/reportes/programados')
export const crearProgramado = (datos: Record<string, unknown>) =>
  api<ReporteProgramado>('/bi/reportes/programados', { metodo: 'POST', cuerpo: datos })
export const editarProgramado = (id: string, datos: Record<string, unknown>) =>
  api<ReporteProgramado>(`/bi/reportes/programados/${id}`, { metodo: 'PATCH', cuerpo: datos })
export const borrarProgramado = (id: string) => api<void>(`/bi/reportes/programados/${id}`, { metodo: 'DELETE' })
