/** Optimización de rutas (VRPTW), reasignación automática, ETA y desvío (§6.8.2, §6.8.4). F2-06. */
import type { Rol } from './api'
import type { Criticidad } from './folios'

export type EstadoPlanRuta = 'borrador' | 'publicado' | 'en_curso' | 'cerrado'
export type ModoReasignacion = 'solo_sugerir' | 'aplicar_y_avisar'
export type ProveedorDistancias = 'estimado' | 'google_routes'
export type DisparadorRecalculo =
  | 'desvio' | 'tiempo_muerto' | 'sla_en_riesgo' | 'incidencia_tecnico'
  | 'folio_nuevo_urgente' | 'reasignacion_forzada' | 'manual'
export type TipoIncidencia = 'vehiculo' | 'salud' | 'otro'

/** §5.2: la ruta la opera el prestador. El cliente no la ve. */
export const ROLES_CALCULAN: Rol[] = ['superadmin', 'admin_prestador', 'despachador']
export const ROLES_CONSULTAN: Rol[] = [...ROLES_CALCULAN, 'mesa_control', 'direccion_prestador',
  'supervisor_prestador']
export const ROLES_CONFIGURAN: Rol[] = ['superadmin', 'admin_prestador']

export const NOMBRE_ESTADO_PLAN: Record<EstadoPlanRuta, string> = {
  borrador: 'Borrador', publicado: 'Publicado', en_curso: 'En curso', cerrado: 'Cerrado',
}
export const NOMBRE_DISPARADOR: Record<DisparadorRecalculo, string> = {
  desvio: 'Desvío de ruta', tiempo_muerto: 'Tiempo muerto', sla_en_riesgo: 'SLA en riesgo',
  incidencia_tecnico: 'Incidencia del técnico', folio_nuevo_urgente: 'Folio urgente nuevo',
  reasignacion_forzada: 'Reasignación del despachador', manual: 'Recálculo manual',
}
export const NOMBRE_MODO: Record<ModoReasignacion, string> = {
  solo_sugerir: 'Solo sugerir (el despachador decide)',
  aplicar_y_avisar: 'Aplicar y avisar (el sistema reasigna solo)',
}
export const NOMBRE_PROVEEDOR: Record<ProveedorDistancias, string> = {
  estimado: 'Estimado (línea recta y velocidad promedio)',
  google_routes: 'Google Maps Routes (con tráfico)',
}
export const NOMBRE_INCIDENCIA: Record<TipoIncidencia, string> = {
  vehiculo: 'Problema con el vehículo', salud: 'Problema de salud', otro: 'Otra causa',
}

/** Lo que cada peso significa, en lenguaje claro, para la pantalla de configuración (ACT-2.1). */
export const EXPLICACION_PESOS: Record<string, string> = {
  distancia: 'Cuánto importa recorrer menos kilómetros. Es el costo base contra el que compiten los demás.',
  sla: 'Cuánto se castiga entregar un folio cuando su SLA ya venció. Súbelo si el cumplimiento es lo primero.',
  criticidad: 'Cuánto se adelantan los activos críticos. Un activo A pesa tres veces lo que uno C.',
  folio_sin_asignar: 'Cuánto se castiga dejar un folio fuera de la ruta. Es el más alto a propósito: ACMA prefiere una ruta larga a un folio sin atender.',
  horas_extra: 'Cuánto se castiga que la ruta pase de la jornada del técnico, por cada hora de más.',
  sin_refaccion: 'Cuánto se castiga asignar un folio a quien no trae la refacción en su vehículo.',
}
export const NOMBRE_PESO: Record<string, string> = {
  distancia: 'Distancia', sla: 'Cumplimiento del SLA', criticidad: 'Criticidad del activo',
  folio_sin_asignar: 'Folio sin asignar', horas_extra: 'Horas extra', sin_refaccion: 'Sin refacción',
}

export interface Mercado {
  id: string
  prestador_id: string
  codigo: string
  nombre: string
  zona_horaria: string
  activo: boolean
  unidades: number
}

export interface PesosRutas {
  distancia: number
  sla: number
  criticidad: number
  folio_sin_asignar: number
  horas_extra: number
  sin_refaccion: number
}

export interface ConfiguracionRutas {
  id: string
  prestador_id: string
  mercado_id: string | null
  pesos_json: PesosRutas
  hora_inicio_jornada: string
  duracion_jornada_min: number
  tiempo_servicio_default_min: number
  factor_sinuosidad: string
  velocidades_json: Record<string, number>
  modo_reasignacion_automatica: ModoReasignacion
  minutos_vigencia_propuesta: number
  umbral_desvio_m: number
  umbral_desvio_min: number
  corredor_desvio_m: number
  proveedor_distancias: ProveedorDistancias
  segundos_limite_calculo: number
  hora_calculo_automatico: string
  configurado_por: string | null
  version_hash: string
}

export interface TiempoServicio {
  id: string
  prestador_id: string
  tipo_folio: string
  tipo_equipo_id: string | null
  tipo_equipo: string | null
  minutos_estimados: number
  origen: string
  muestras: number
}

export interface ParadaRuta {
  parada_id: string
  folio_id: string
  numero_folio: string
  orden: number
  un_codigo: string
  un_nombre: string
  tipo_folio: string
  estado_folio: string
  criticidad: Criticidad | null
  llegada_estimada: string | null
  fin_estimado: string | null
  minutos_desde_anterior: number
  km_desde_anterior: number
  minutos_servicio: number
  ventana_ok: boolean
  sla_ok: boolean
  holgura_sla_min: number | null
  fijo: boolean
}

export interface RutaTecnico {
  tecnico_id: string
  tecnico: string
  paradas: ParadaRuta[]
  km: number
  minutos: number
}

export interface SinAsignar {
  folio_id: string
  numero_folio: string
  motivo: string
}

export interface PlanResumen {
  id: string
  mercado_id: string
  fecha: string
  estado: EstadoPlanRuta
  version: number
  distancia_total_km: number
  folios_asignados: number
  folios_sin_asignar: number
  sin_asignar: SinAsignar[]
  tiempo_calculo_ms: number
  motor: string
  costo_objetivo: number
  publicado_at: string | null
}

export interface PlanDetalle {
  plan: PlanResumen
  rutas: RutaTecnico[]
}

export interface MovimientoPropuesta {
  folio_id: string
  numero_folio: string
  de_tecnico_id: string | null
  a_tecnico_id: string
  orden: number
  llegada_estimada: string
}

export interface Propuesta {
  id: string
  plan_id: string
  disparador: DisparadorRecalculo
  motivo: string
  movimientos: MovimientoPropuesta[]
  tecnicos_afectados: string[]
  vence_at: string | null
  timestamp: string
  tiempo_calculo_ms: number
  sin_asignar: string[]
}

export interface TrazoRuta {
  tecnico_id: string
  tecnico: string
  proveedor: ProveedorDistancias
  /** [[lat, lng], ...] para dibujar la polilínea en el mapa. */
  puntos: [number, number][]
}

export interface Eta {
  tiene_eta: boolean
  tecnico: string | null
  llegada_estimada: string | null
  orden: number | null
  en_camino: boolean | null
  minutos_restantes: number | null
  motivo: string | null
}

export interface Simulacion {
  plan_id: string
  antes: { km: number; fuera_ventana: number; fuera_sla: number }
  despues: { km: number; fuera_ventana: number; fuera_sla: number }
  diferencia_km: number
  rechazados: { folio_id?: string; motivo: string }[]
  nota: string
}

export interface ParadaDelTecnico {
  folio_id: string
  numero_folio: string
  orden: number
  un_codigo: string
  un_nombre: string
  direccion: string
  estado_folio: string
  tipo_folio: string
  llegada_estimada: string | null
  fin_estimado: string | null
  minutos_servicio: number
  minutos_desde_anterior: number
  km_desde_anterior: number
  lat: number | null
  lng: number | null
}

/** La ruta del día del propio técnico: lo único de rutas que su app puede pedir. */
export interface MiRuta {
  tiene_ruta: boolean
  plan_id?: string
  fecha?: string
  km?: number
  paradas: ParadaDelTecnico[]
  mensaje?: string
}

/** Enlaces de navegación gratuitos: no requieren API ni llave (§3 del prompt). */
export function enlaceWaze(lat: number, lng: number): string {
  return `https://waze.com/ul?ll=${lat},${lng}&navigate=yes`
}
export function enlaceGoogleMaps(lat: number, lng: number): string {
  return `https://www.google.com/maps/dir/?api=1&destination=${lat},${lng}&travelmode=driving`
}

/** Hora corta de una ETA, o un guion si no hay. */
export function hora(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

/** Texto de la holgura del SLA: lo que le queda, o cuánto se pasó. */
export function textoHolgura(minutos: number | null | undefined): string {
  if (minutos == null) return 'sin SLA'
  if (minutos < 0) return `vencido por ${Math.abs(minutos)} min`
  if (minutos < 60) return `${minutos} min de holgura`
  return `${Math.floor(minutos / 60)} h ${minutos % 60} min de holgura`
}

export function sumaPesosRutas(p: PesosRutas): number {
  return Object.values(p).reduce((a, b) => a + Number(b), 0)
}
