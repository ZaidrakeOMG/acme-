/** Cliente de /api/medidores y de los endpoints de planes por uso (F2-04, §6.9.2). */
import type {
  CambioMedidor, EquipoDelOperador, EventoCatalogo, FilaSimulacion, Lectura, LlaveApi, LlaveCreada, MedidorEntrada,
  MedidorEquipo, PendienteRevision, ResultadoLectura, TipoCambioMedidor, TipoMedidor, TipoMedidorEntrada,
} from '../types/medidores'
import { api } from './api'

type Params = Record<string, string | number | boolean | null | undefined>

// ------------------------------------------------------------- catálogo
export const tiposMedidor = (params: Params = {}) => api<TipoMedidor[]>('/medidores/tipos', { params })
export const crearTipoMedidor = (datos: TipoMedidorEntrada) => api<TipoMedidor>('/medidores/tipos', { metodo: 'POST', cuerpo: datos })
export const editarTipoMedidor = (id: string, cambios: Partial<TipoMedidorEntrada> & { activo?: boolean }) =>
  api<TipoMedidor>(`/medidores/tipos/${id}`, { metodo: 'PUT', cuerpo: cambios })

// --------------------------------------------------- medidores del equipo
export const medidoresDeEquipo = (equipoId: string) => api<MedidorEquipo[]>(`/medidores/equipos/${equipoId}`)
export const altaMedidor = (equipoId: string, datos: MedidorEntrada) => api(`/medidores/equipos/${equipoId}`, { metodo: 'POST', cuerpo: datos })
export const editarMedidor = (medidorId: string, cambios: Record<string, unknown>) => api(`/medidores/${medidorId}`, { metodo: 'PUT', cuerpo: cambios })
export const cambiosDeMedidor = (medidorId: string) => api<CambioMedidor[]>(`/medidores/${medidorId}/cambios`)
export const registrarCambio = (medidorId: string, datos: { tipo: TipoCambioMedidor; valor_nuevo: string; motivo: string; numero_serie_nuevo?: string | null }) =>
  api<CambioMedidor>(`/medidores/${medidorId}/cambios`, { metodo: 'POST', cuerpo: datos })
export const configurarEstimacion = (medidorId: string, datos: Record<string, unknown>) =>
  api(`/medidores/${medidorId}/estimacion`, { metodo: 'PUT', cuerpo: datos })

// ------------------------------------------------------------- lecturas
export const lecturas = (params: Params = {}) => api<Lectura[]>('/medidores/lecturas', { params })
export const registrarLectura = (datos: { equipo_medidor_id: string; valor: string; metodo?: string | null; timestamp_dispositivo?: string | null; folio_id?: string | null; evidencia_id?: string | null }) =>
  api<ResultadoLectura>('/medidores/lecturas', { metodo: 'POST', cuerpo: datos })
export const lecturasPorRevisar = () => api<PendienteRevision[]>('/medidores/lecturas/por-revisar')
export const revisarLectura = (id: string, aprobar: boolean, razon = '') =>
  api<ResultadoLectura>(`/medidores/lecturas/${id}/revision`, { metodo: 'POST', cuerpo: { aprobar, razon } })

// --------------------------------------------------------- app del operador
export const equiposConMedidorDelOperador = (unId?: string | null) => api<EquipoDelOperador[]>('/medidores/operador/equipos', { params: { un_id: unId } })

// ------------------------------------------------------------ llaves de API
export const llavesApi = (tenantId?: string | null) => api<LlaveApi[]>('/medidores/llaves', { params: { tenant_id: tenantId } })
export const crearLlaveApi = (nombre: string, tenantId?: string | null) =>
  api<LlaveCreada>('/medidores/llaves', { metodo: 'POST', cuerpo: { nombre, tenant_id: tenantId ?? null } })
export const revocarLlaveApi = (id: string) => api<{ mensaje: string }>(`/medidores/llaves/${id}`, { metodo: 'DELETE' })

// -------------------------------------------------------------- planes
export const catalogoEventos = () => api<EventoCatalogo[]>('/planes/eventos-catalogo')
export const simularPlan = (planId: string) => api<FilaSimulacion[]>(`/planes/${planId}/simulacion`)

/** Texto en lenguaje claro de un trigger, para el editor de planes y la ficha del equipo (§6.9.1). */
export function describirTriggerUso(
  t: { tipo_trigger: string; parametros_json: Record<string, unknown> },
  tipos: TipoMedidor[] = [],
  claves: Record<string, string> = {},
): string {
  const p = t.parametros_json ?? {}
  const unidad = (id: unknown) => tipos.find((x) => x.id === String(id))?.unidad ?? 'unidades'
  const nombre = (id: unknown) => tipos.find((x) => x.id === String(id))?.nombre ?? 'medidor'
  if (t.tipo_trigger === 'medidor_umbral') return `Al llegar a ${String(p.umbral)} ${unidad(p.tipo_medidor_id)} de ${nombre(p.tipo_medidor_id)}`
  if (t.tipo_trigger === 'medidor_intervalo') return `Cada ${String(p.intervalo)} ${unidad(p.tipo_medidor_id)} de ${nombre(p.tipo_medidor_id)} desde el último mantenimiento`
  if (t.tipo_trigger === 'evento') {
    const extra = p.evento === 'fallas_repetidas' ? ` (${String(p.cantidad)} en ${String(p.dias)} días)`
      : p.evento === 'equipo_instalado' ? ` (${String(p.dias_despues ?? 0)} días después)`
      : p.evento === 'falla_correctiva_grave' ? ` (severidad ${(p.severidades as string[] ?? []).join(' o ')})` : ''
    return `Cuando ocurra: ${String(p.evento ?? '').replace(/_/g, ' ')}${extra}`
  }
  if (t.tipo_trigger === 'combinado') {
    const partes = ((p.triggers_claves as string[]) ?? []).map((c) => claves[c] ?? c)
    const union = String(p.logica ?? 'OR') === 'AND' ? ' Y ' : ' O '
    return `${partes.join(union)}${String(p.logica ?? 'OR') === 'AND' ? ' (cuando se cumplan todas)' : ' (lo que ocurra primero)'}`
  }
  if (t.tipo_trigger === 'tiempo_fijo') return 'cada_dias' in p ? `Cada ${String(p.cada_dias)} días` : `Cada ${String(p.cada)} ${String(p.unidad)}`
  if (t.tipo_trigger === 'calendario') return 'fechas' in p ? `Fechas: ${(p.fechas as string[]).join(', ')}` : `Cada ${String(p.dia)}/${String(p.mes)}`
  return t.tipo_trigger
}
