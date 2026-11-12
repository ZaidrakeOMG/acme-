/** Criticidad de activos, FMEA y mitigación del riesgo (ISO 55000, §6.9.3). F2-05. */
import type { Criticidad } from './folios'
import type { Rol } from './api'

export type { Criticidad }

export const NIVELES: Criticidad[] = ['A', 'B', 'C', 'D']
export const DIMENSIONES = ['operacional', 'seguridad', 'economico', 'imagen'] as const
export type Dimension = (typeof DIMENSIONES)[number]

/** Etiqueta y color de cada nivel. El tono sigue la paleta de `Insignia` para no inventar colores nuevos. */
export const ETIQUETA_NIVEL: Record<Criticidad, string> = {
  A: 'Crítico', B: 'Importante', C: 'Estándar', D: 'No crítico',
}
export const TONO_NIVEL: Record<Criticidad, 'alerta' | 'acento' | 'neutro' | 'ok'> = {
  A: 'alerta', B: 'acento', C: 'neutro', D: 'ok',
}
export const NOMBRE_DIMENSION: Record<Dimension, string> = {
  operacional: 'Operacional', seguridad: 'Seguridad', economico: 'Económico', imagen: 'Imagen',
}
export const NOMBRE_MOTIVO: Record<string, string> = {
  evaluacion_inicial: 'Evaluación inicial', revision_periodica: 'Revisión periódica',
  recalculo_por_historial: 'Recálculo por historial', ajuste_manual: 'Ajuste manual',
  cambio_configuracion: 'Cambio de configuración',
}
export const NOMBRE_ORIGEN_PROBABILIDAD: Record<string, string> = {
  historial_equipo: 'historial de fallas del activo', mtbf_equipo: 'MTBF del activo',
  tipo_equipo_cliente: 'promedio del mismo tipo de equipo', tipo_equipo_plataforma: 'promedio del mismo tipo en ACMA',
  sin_referencia: 'sin referencia todavía',
}
export const NOMBRE_TIPO_MITIGACION: Record<string, string> = {
  plan_preventivo: 'Plan preventivo', capacitacion: 'Capacitación',
  refaccion_en_inventario: 'Refacción en inventario', rediseno: 'Rediseño', otro: 'Otra',
}
export const NOMBRE_ESTADO_MITIGACION: Record<string, string> = {
  propuesta: 'Propuesta', en_proceso: 'En proceso', implementada: 'Implementada', descartada: 'Descartada',
}
export const NOMBRE_CATEGORIA_RIESGO: Record<string, string> = {
  bajo: 'Bajo', medio: 'Medio', alto: 'Alto', critico: 'Crítico',
}
export const TONO_CATEGORIA: Record<string, 'ok' | 'neutro' | 'acento' | 'alerta'> = {
  bajo: 'ok', medio: 'neutro', alto: 'acento', critico: 'alerta',
}
export const NOMBRE_IMPLICACION: Record<string, string> = {
  pm_obligatorio: 'PM obligatorio con plan definido',
  respuesta_maxima: 'Respuesta máxima por criticidad (4 h en A, 8 h en B)',
  tecnico_certificado: 'Técnico especialista en A y certificado en B',
  refaccion_en_inventario: 'Refacciones de activos críticos siempre en inventario',
}

/** Quién evalúa, quién configura y quién solo consulta (§5.1, igual que el servicio). */
export const ROLES_EVALUAN: Rol[] = ['superadmin', 'admin_empresa', 'admin_un']
export const ROLES_CONFIGURAN: Rol[] = ['superadmin', 'admin_empresa']
export const ROLES_CONSULTAN: Rol[] = [...ROLES_EVALUAN, 'admin_prestador', 'mesa_control', 'despachador',
  'supervisor_operadores', 'direccion_prestador', 'supervisor_prestador']
export const ROLES_RIESGO: Rol[] = ['superadmin', 'admin_empresa', 'admin_un', 'admin_prestador', 'mesa_control',
  'despachador']

export interface Pesos { operacional: number; seguridad: number; economico: number; imagen: number }
export type Dimensiones = Pesos

export interface RangoNivel { nivel: Criticidad; desde: number; hasta: number; etiqueta: string }
export interface RangoEconomico { nivel: number; hasta: number | null; texto: string }
export interface BandaFallas { nivel: number; hasta: number | null; texto: string }
export interface EscalaProbabilidad {
  meses: number
  minimo_meses_historia: number
  por_fallas: BandaFallas[]
  por_mtbf: { nivel: number; desde_horas: number }[]
  minimo_fallas_para_mtbf: number
}
export interface Implicacion { alerta: boolean; restriccion: boolean; [extra: string]: unknown }

export interface ConfiguracionCriticidad {
  id: string
  tenant_id: string
  pesos_json: Pesos
  rangos_economico_json: RangoEconomico[]
  escala_probabilidad_json: EscalaProbabilidad
  rangos_nivel_json: RangoNivel[]
  meses_revision: number
  implicaciones_activas_json: Record<string, Implicacion>
  configurado_por: string | null
  version_hash: string
}

export interface CriticidadActivo {
  id: string
  equipo_id: string
  tenant_id: string
  indice_criticidad: string
  nivel: Criticidad
  probabilidad: string
  probabilidad_estimada: boolean
  probabilidad_origen: string
  impacto_ponderado: string
  dimensiones_json: Record<string, unknown>
  origen: 'calculado' | 'manual'
  razon_manual: string
  evaluado_por: string | null
  fecha_evaluacion: string
  proxima_revision: string | null
}

export interface FilaRegistro {
  equipo_id: string
  codigo: string
  nombre: string
  tipo_equipo: string
  un_codigo: string
  un_nombre: string
  tenant_id: string
  nivel: Criticidad
  indice_criticidad: string
  probabilidad: string
  probabilidad_estimada: boolean
  impacto_ponderado: string
  origen: string
  fecha_evaluacion: string
  proxima_revision: string | null
  revision_vencida: boolean
}

export interface ResumenCriticidad {
  por_nivel: Record<Criticidad, number>
  total: number
  criticos_sin_plan: number
  criticos_sin_plan_ids: string[]
  mitigaciones_vencidas: number
  revisiones_vencidas: number
}

export interface CeldaMatriz {
  probabilidad: number
  impacto: number
  total: number
  equipos: { equipo_id: string; codigo: string; nivel: Criticidad }[]
}
export interface MatrizCriticidad { celdas: CeldaMatriz[]; total: number }

export interface NivelGuia { pregunta: string; peso_default: number; niveles: Record<string, string> }
export interface Guia {
  dimensiones: Record<Dimension, NivelGuia>
  niveles: Record<Criticidad, string>
  implicaciones: Record<Criticidad, string>
}

export interface AporteDimension {
  clave: Dimension
  valor: number
  peso: number
  aporte: string
  pregunta: string
  texto: string
}

/** Respuesta de `GET /api/criticidad/equipos/{id}`: sin evaluar trae la guía y la propuesta económica. */
export interface DetalleCriticidad {
  evaluado: boolean
  guia: Record<Dimension, NivelGuia>
  pesos: Pesos
  meses_revision: number
  nivel_manual?: Criticidad | null
  economico_propuesto?: { nivel: number; texto?: string; costo_promedio?: string; nota?: string }
  /** El numero del activo evaluado; null cuando todavia no se evalua. */
  probabilidad: string | null
  probabilidad_estimada: boolean
  probabilidad_origen: string
  probabilidad_detalle: Record<string, unknown>
  /** Sin evaluar: la probabilidad que saldria hoy, para estimar el indice en la pantalla. */
  probabilidad_si_se_evalua?: string | null
  nivel?: Criticidad
  etiqueta?: string
  implicaciones?: string
  indice_criticidad?: string
  impacto_ponderado?: string
  dimensiones?: AporteDimension[]
  origen?: 'calculado' | 'manual'
  razon_manual?: string
  fecha_evaluacion?: string
  proxima_revision?: string | null
  revision_vencida?: boolean
}

export interface EvaluacionHistorial {
  id: string
  equipo_id: string
  indice_anterior: string | null
  indice_nuevo: string
  nivel_anterior: Criticidad | null
  nivel_nuevo: Criticidad
  probabilidad: string
  impacto_ponderado: string
  dimensiones_json: Record<string, unknown>
  motivo: string
  razon: string
  evaluado_por: string | null
  timestamp: string
}

export interface ModoFalla {
  id: string
  tenant_id: string
  equipo_id: string | null
  tipo_equipo_id: string | null
  descripcion_falla: string
  tipo_falla_id: string | null
  causa_probable: string
  efecto_operacional: string
  severidad: number
  frecuencia_historica: number
  fallas_12m: number
  deteccion: number | null
  nivel_riesgo: number
  origen: 'manual' | 'sugerido' | 'importado'
  activo: boolean
  registrado_por: string | null
}

export interface SugerenciaModo {
  descripcion_falla: string
  tipo_falla_id: string | null
  causa_probable: string
  severidad: number
  frecuencia_historica: number
  fallas_12m: number
  nivel_riesgo: number
  categoria: string
  ya_registrado: boolean
  nota: string
}

export interface CeldaRiesgo {
  severidad: number
  frecuencia: number
  total: number
  categoria: string
  modos: { id: string; descripcion: string; equipo_id: string | null; nivel_riesgo: number }[]
}
export interface MatrizRiesgo {
  celdas: CeldaRiesgo[]
  total: number
  por_categoria: Record<string, number>
}

export interface Mitigacion {
  id: string
  modo_falla_id: string
  tenant_id: string
  accion_mitigacion: string
  tipo: string
  plan_mantenimiento_id: string | null
  curso_id: string | null
  articulo_id: string | null
  responsable_id: string | null
  fecha_compromiso: string | null
  fecha_implementacion: string | null
  estado: string
  efectividad_json: Efectividad | Record<string, never>
  evidencia_key: string | null
  razon_descarte: string
}

export interface Efectividad {
  estado: 'sin_implementar' | 'no_aplicable' | 'sin_datos_suficientes' | 'medida'
  nota?: string
  dias_desde_implementacion?: number
  ventana_meses?: number
  antes?: { fallas: number; mtbf_horas: string | null }
  despues?: { fallas: number; mtbf_horas: string | null }
  delta_fallas?: number
  veredicto?: 'mejoro' | 'sin_cambio' | 'empeoro'
  mejora_mtbf_pct?: string | null
}

export interface MitigacionPendiente {
  id: string
  accion_mitigacion: string
  tipo: string
  estado: string
  fecha_compromiso: string | null
  responsable_id: string | null
  vencida: boolean
  dias_vencida: number
  modo_falla_id: string
  modo_falla: string
  nivel_riesgo: number
  equipo_id: string | null
  equipo_codigo: string | null
  equipo_nombre: string | null
  tenant_id: string
}

export interface PlantillaIso { tipo: string; nombre: string }

/** Suma de los cuatro pesos, para avisar antes de mandar la configuración (el backend exige 100 %). */
export function sumaPesos(p: Pesos): number {
  return Number(p.operacional) + Number(p.seguridad) + Number(p.economico) + Number(p.imagen)
}

/** Impacto ponderado con los mismos pesos del cliente: así la pantalla muestra el índice antes de guardar. */
export function impactoPonderado(d: Dimensiones, p: Pesos): number {
  const total = DIMENSIONES.reduce((acc, k) => acc + Number(d[k]) * Number(p[k]), 0)
  return Math.round((total / 100) * 100) / 100
}

/** Índice de §6.9.3: `probabilidad × impacto / 25 × 100`. */
export function indiceDe(probabilidad: number, impacto: number): number {
  return Math.round(((probabilidad * impacto) / 25) * 100 * 100) / 100
}

export function nivelDe(indice: number, rangos: RangoNivel[]): Criticidad {
  const ordenados = [...rangos].sort((a, b) => Number(b.desde) - Number(a.desde))
  for (const r of ordenados) if (indice >= Number(r.desde)) return r.nivel
  return 'D'
}

export function categoriaRiesgo(severidad: number, frecuencia: number): string {
  const p = Number(severidad) * Number(frecuencia)
  if (p >= 16) return 'critico'
  if (p >= 10) return 'alto'
  if (p >= 5) return 'medio'
  return 'bajo'
}
