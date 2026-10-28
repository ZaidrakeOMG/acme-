/** Cliente de /api/folios (P04). P05 interceptará `capturarFolio` con la cola offline, igual que respuestas.ts. */
import type { EstadoFolio, FolioDetalle, FolioEntrada, FolioResumen, HistorialFolio, PendienteAprobacion, RazonRechazo, TarjetaDuplicado, TransicionTabla, ConfiguracionAprobacion, NivelConfig, Politicas, Regla, CanalAprobacion } from '../types/folios'
import { api } from './api'

type Params = Record<string, string | number | boolean | null | undefined>

export const listarFolios = (params: Params = {}) => api<FolioResumen[]>('/folios', { params })
export const obtenerFolio = (id: string) => api<FolioDetalle>(`/folios/${id}`)
export const historialFolio = (id: string) => api<HistorialFolio[]>(`/folios/${id}/historial`)
export const verificarDuplicado = (equipoId: string) => api<TarjetaDuplicado>('/folios/verificar-duplicado', { params: { equipo_id: equipoId } })
export const capturarFolio = (datos: FolioEntrada) => api<FolioResumen>('/folios', { metodo: 'POST', cuerpo: datos })

let tablaTransiciones: Promise<TransicionTabla[]> | null = null
/** Tabla §6.8.6 del servidor (cacheada): la misma que usa el motor. */
export function transiciones() {
  if (!tablaTransiciones) tablaTransiciones = api<TransicionTabla[]>('/folios/transiciones').catch((e) => { tablaTransiciones = null; throw e })
  return tablaTransiciones
}

/** Atajos semánticos del folio: ruta → estado destino, etiqueta y si requiere razón/notas. */
export const ACCIONES: { destino: EstadoFolio; ruta: string; etiqueta: string; campo?: 'razon' | 'notas' | 'tecnico'; desde?: EstadoFolio[] }[] = [
  { destino: 'autorizado', ruta: 'autorizar', etiqueta: 'Autorizar' },
  { destino: 'pendiente_informacion', ruta: 'pedir-informacion', etiqueta: 'Pedir información', campo: 'notas' },
  { destino: 'en_revision', ruta: 'responder-informacion', etiqueta: 'Responder información', campo: 'notas', desde: ['pendiente_informacion'] },
  { destino: 'asignado', ruta: 'asignar', etiqueta: 'Asignar técnico', campo: 'tecnico' },
  { destino: 'en_camino', ruta: 'en-camino', etiqueta: 'En camino' },
  { destino: 'en_ejecucion', ruta: 'confirmar-llegada', etiqueta: 'Confirmar llegada', desde: ['en_camino'] },
  { destino: 'en_ejecucion', ruta: 'reanudar', etiqueta: 'Reanudar ejecución', desde: ['pendiente_refaccion'] },
  { destino: 'pendiente_refaccion', ruta: 'pendiente-refaccion', etiqueta: 'Pendiente de refacción', campo: 'notas' },
  { destino: 'cerrado', ruta: 'cerrar', etiqueta: 'Cerrar folio' },
  { destino: 'cancelado', ruta: 'cancelar', etiqueta: 'Cancelar', campo: 'razon' },
]

export const accionFolio = (id: string, ruta: string, cuerpo: Record<string, unknown> = {}) => api<FolioResumen>(`/folios/${id}/${ruta}`, { metodo: 'POST', cuerpo })
export const comentarFolio = (id: string, notas: string) => api<HistorialFolio>(`/folios/${id}/comentario`, { metodo: 'POST', cuerpo: { notas } })
export const fijarMonto = (id: string, monto: number) => api<FolioResumen>(`/folios/${id}/monto-estimado`, { metodo: 'PUT', cuerpo: { monto_estimado: monto } })
export const overrideSeveridad = (id: string, severidadId: string, razon: string) => api<FolioResumen>(`/folios/${id}/severidad`, { metodo: 'PUT', cuerpo: { severidad_id: severidadId, razon } })
export const confirmarUn = (id: string, geo?: { lat: number; lng: number } | null) => api<FolioResumen>(`/folios/${id}/confirmar-un`, { metodo: 'POST', cuerpo: { geolat: geo?.lat ?? null, geolng: geo?.lng ?? null } })

export const pendientesAprobacion = () => api<PendienteAprobacion[]>('/folios/pendientes-aprobacion')
export const aprobarFolio = (id: string, canal: CanalAprobacion = 'app', notas = '') => api<FolioResumen>(`/folios/${id}/aprobacion/aprobar`, { metodo: 'POST', cuerpo: { canal, notas } })
export const rechazarFolio = (id: string, razon: RazonRechazo, canal: CanalAprobacion = 'app', notas = '') =>
  api<FolioResumen>(`/folios/${id}/aprobacion/rechazar`, { metodo: 'POST', cuerpo: { canal, razon_rechazo: razon, notas } })

export const configuracionAprobacion = (tenantId?: string) => api<ConfiguracionAprobacion>('/folios/aprobacion/configuracion', { params: { tenant_id: tenantId } })
export const guardarReglas = (reglas: Regla[], tenantId?: string) => api<Regla[]>('/folios/aprobacion/reglas', { metodo: 'PUT', cuerpo: reglas.map(({ id: _id, ...r }) => r), params: { tenant_id: tenantId } })
export const guardarNiveles = (niveles: NivelConfig[], tenantId?: string) => api<NivelConfig[]>('/folios/aprobacion/niveles', { metodo: 'PUT', cuerpo: niveles.map(({ id: _id, ...n }) => n), params: { tenant_id: tenantId } })
export const guardarPoliticas = (cambios: Partial<Politicas>, tenantId?: string) => api<Politicas>('/folios/politicas', { metodo: 'PUT', cuerpo: cambios, params: { tenant_id: tenantId } })

/** Reglas por monto equivalentes a "umbral A / umbral B" (§6.8.7), conservando las demás. */
export function reglasConUmbrales(reglas: Regla[], umbralA: number, umbralB: number): Regla[] {
  const otras = reglas.filter((r) => r.criterio !== 'monto')
  return [
    { nivel: 1, criterio: 'monto', operador: '<', valor_json: { monto: umbralA }, activa: true },
    { nivel: 2, criterio: 'monto', operador: 'entre', valor_json: { min: umbralA, max: umbralB }, activa: true },
    { nivel: 3, criterio: 'monto', operador: '>=', valor_json: { monto: umbralB }, activa: true },
    ...otras,
  ]
}

export function umbralesDe(reglas: Regla[]): { a: number; b: number } {
  const n1 = reglas.find((r) => r.criterio === 'monto' && r.nivel === 1)
  const n3 = reglas.find((r) => r.criterio === 'monto' && r.nivel === 3)
  return { a: Number(n1?.valor_json.monto ?? 5000), b: Number(n3?.valor_json.monto ?? 20000) }
}
