/** Espejo de backend/schemas/preventivos.py (P06): planes, calendario, autorizaciones y reasignaciones. */
import type { Rol } from './api'
import type { CanalAprobacion, EstadoFolio } from './folios'

export type TipoTrigger = 'tiempo_fijo' | 'calendario' | 'medidor_umbral' | 'medidor_intervalo' | 'evento' | 'combinado'
export type EstadoPlan = 'activo' | 'inactivo'
export type EstadoPreventivo = 'programado' | 'generado' | 'ejecutado' | 'reprogramado' | 'cancelado'
export type OrigenPreventivo = 'manual' | 'plan'
export type TipoAutorizacion = 'reprogramacion' | 'cancelacion'
export type EstadoAutorizacion = 'pendiente' | 'autorizada' | 'rechazada'

/** Triggers de Fase 1 (los demás se muestran deshabilitados: Fase 2, decisión del Anexo de alcance). */
export const TRIGGERS: { valor: TipoTrigger; texto: string; fase: 1 | 2 }[] = [
  { valor: 'tiempo_fijo', texto: 'Tiempo fijo (cada N días / semanas / meses)', fase: 1 },
  { valor: 'calendario', texto: 'Calendario (fecha fija anual o lista de fechas)', fase: 1 },
  { valor: 'medidor_umbral', texto: 'Medidor por umbral (horas de uso, ciclos)', fase: 2 },
  { valor: 'medidor_intervalo', texto: 'Medidor por intervalo', fase: 2 },
  { valor: 'evento', texto: 'Evento (falla, alarma de sensor)', fase: 2 },
  { valor: 'combinado', texto: 'Combinado (AND / OR)', fase: 2 },
]

export const NOMBRE_ESTADO_PREVENTIVO: Record<EstadoPreventivo, string> = {
  programado: 'Programado', generado: 'Folio generado', ejecutado: 'Ejecutado', reprogramado: 'Reprogramado', cancelado: 'Cancelado',
}

export interface Trigger { id?: string; tipo_trigger: TipoTrigger; parametros_json: Record<string, unknown>; logica_combinacion: string | null }
export interface TareaPlan { id?: string; orden: number | null; descripcion: string; tiempo_estimado_min: number; habilidad_requerida_id: string | null }
export interface MaterialPlan { id?: string; articulo_id: string | null; descripcion: string; cantidad_estandar: string; unidad: string }
export interface EquipoPlan { id: string; equipo_id: string; tenant_id: string; activo: boolean; fecha_proxima_ejecucion: string | null; fecha_ultima_ejecucion: string | null; fecha_alta: string }

export interface Plan {
  id: string
  created_at: string
  updated_at: string
  version_hash: string | null
  prestador_id: string
  tenant_id: string | null
  tipo_equipo_id: string
  tipo_equipo_nombre: string | null
  nombre: string
  descripcion: string
  version: number
  estado: EstadoPlan
  tiempo_ventana_dias: number
  formulario_id: string | null
  formulario_nombre: string | null
  nivel_severidad_id: string | null
  created_by: string | null
  triggers: Trigger[]
  tareas: TareaPlan[]
  materiales: MaterialPlan[]
  equipos: EquipoPlan[]
}

export interface PlanEntrada {
  nombre: string
  descripcion: string
  tipo_equipo_id: string
  tenant_id?: string | null
  estado?: EstadoPlan
  tiempo_ventana_dias: number
  formulario_id?: string | null
  nivel_severidad_id?: string | null
  triggers: Trigger[]
  tareas: TareaPlan[]
  materiales: MaterialPlan[]
}

export interface FilaCalendario {
  id: string
  created_at: string
  updated_at: string
  version_hash: string | null
  prestador_id: string
  tenant_id: string
  un_id: string
  un_codigo: string | null
  un_nombre: string | null
  equipo_id: string | null
  equipo_codigo: string | null
  equipo_nombre: string | null
  plan_id: string | null
  plan_nombre: string | null
  tecnico_id: string | null
  tecnico_nombre: string | null
  fecha_programada: string
  fecha_programada_original: string | null
  fecha_real: string | null
  desvio_dias: number | null
  texto_desvio: string
  estado: EstadoPreventivo
  folio_id: string | null
  numero_folio: string | null
  estado_folio: EstadoFolio | null
  formulario_id: string | null
  origen: OrigenPreventivo
  descripcion: string
  cargado_por: string | null
  reprogramado_desde_id: string | null
}

export interface FilaCalendarioEntrada { un_id: string; equipo_id?: string | null; plan_id?: string | null; tecnico_id?: string | null; fecha_programada: string; descripcion?: string }
export interface Publicacion { id: string; prestador_id: string; tenant_id: string; mes: string; publicado_por: string | null; publicado_at: string; total_preventivos: number }

export interface Autorizacion {
  id: string
  folio_id: string
  tenant_id: string
  prestador_id: string
  calendario_id: string | null
  tipo: TipoAutorizacion
  solicitado_por: string
  solicitado_por_nombre: string | null
  autorizado_por: string | null
  autorizado_por_nombre: string | null
  fecha_solicitud: string
  fecha_autorizacion: string | null
  razon: string
  fecha_nueva: string | null
  estado: EstadoAutorizacion
  canal: CanalAprobacion
  notas_respuesta: string
  numero_folio: string | null
  estado_folio: EstadoFolio | null
  fecha_programada: string | null
  puede_resolver: boolean
}

export interface TareasMateriales { tareas: TareaPlan[]; materiales: MaterialPlan[] }

// ---------------------------------------------------------- reasignación

export interface Candidato {
  usuario_id: string
  tecnico_id: string
  nombre: string
  vehiculo_placas: string | null
  habilidad_ok: boolean
  habilidad_requerida: string | null
  carga_dia: number
  refaccion_ok: boolean | null
  es_actual: boolean
  advertencias: string[]
  /** F2-01: estado de la certificación de la habilidad que el folio exige. */
  certificacion: 'vigente' | 'vencida' | 'sin_habilidad' | 'sin_requisito'
  certificacion_vence: string | null
}

export interface ReasignarEntrada { tecnico_destino_id: string; razon_id: string; comentario?: string; confirmar_advertencias?: boolean; razon_sin_habilidad?: string | null }

export interface ReasignacionFolio {
  id: string
  tecnico_origen_id: string | null
  tecnico_origen_nombre: string | null
  tecnico_destino_id: string
  tecnico_destino_nombre: string | null
  tipo: 'forzada' | 'automatica'
  razon: string | null
  comentario: string
  despachador_id: string | null
  despachador_nombre: string | null
  timestamp: string
}

export interface RazonReasignacion { id: string; prestador_id: string; descripcion: string; detalle: string; activa: boolean; orden_display: number }
export interface Conteo { nombre: string; total: number; porcentaje: number }
export interface ReporteReasignaciones { desde: string | null; hasta: string | null; total: number; por_razon: Conteo[]; por_tecnico_origen: Conteo[]; por_tecnico_destino: Conteo[]; por_tipo: Conteo[] }

export const ROLES_CALENDARIO: Rol[] = ['superadmin', 'admin_prestador', 'despachador', 'mesa_control', 'admin_empresa', 'admin_un', 'supervisor_operadores']
export const ROLES_CARGAN_CALENDARIO: Rol[] = ['superadmin', 'admin_prestador', 'despachador', 'mesa_control']
export const ROLES_PLANES: Rol[] = ['superadmin', 'admin_prestador', 'despachador']
export const ROLES_SOLICITAN: Rol[] = ['superadmin', 'admin_prestador', 'despachador', 'mesa_control']
export const ROLES_AUTORIZAN: Rol[] = ['superadmin', 'admin_empresa', 'admin_un']
export const ROLES_REASIGNAN: Rol[] = ['superadmin', 'admin_prestador', 'despachador']
