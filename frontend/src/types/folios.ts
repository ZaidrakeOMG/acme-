/** Espejo de backend/schemas/folios.py (P04). */
import type { Rol } from './api'
import type { ReasignacionFolio } from './preventivos'

export const ESTADOS_FOLIO = ['capturado', 'en_revision', 'pendiente_informacion', 'autorizado', 'asignado', 'reasignado', 'en_camino', 'en_ejecucion', 'pendiente_refaccion', 'cerrado', 'cancelado'] as const
export type EstadoFolio = (typeof ESTADOS_FOLIO)[number]
export type TipoFolio = 'correctivo' | 'preventivo' | 'especial'
export type Criticidad = 'A' | 'B' | 'C' | 'D'
export type TriggerRevision = 'sin_contrato' | 'garantia' | 'tipo_falla_flag' | 'fuera_horario' | 'keyword_alerta' | 'severidad_no_configurada' | 'confirmacion_un_faltante'
export type EstadoFlujo = 'activo' | 'aprobado' | 'rechazado' | 'bloqueado'
export type RazonRechazo = 'por_presupuesto' | 'requiere_cotizacion' | 'seguimiento_interno' | 'reprogramar'
export type CanalAprobacion = 'push' | 'app' | 'minuta' | 'sistema'
export type ComportamientoTimeout = 'escalar' | 'bloquear_alertar' | 'autorizar_automatico' | 'depende_criticidad'

export const NOMBRE_ESTADO: Record<EstadoFolio, string> = {
  capturado: 'Capturado', en_revision: 'En revisión', pendiente_informacion: 'Pendiente de información', autorizado: 'Autorizado',
  asignado: 'Asignado', reasignado: 'Reasignado', en_camino: 'En camino', en_ejecucion: 'En ejecución', pendiente_refaccion: 'Pendiente de refacción',
  cerrado: 'Cerrado', cancelado: 'Cancelado',
}

export const NOMBRE_TRIGGER: Record<TriggerRevision, string> = {
  sin_contrato: 'Equipo sin contrato activo', garantia: 'Equipo en garantía', tipo_falla_flag: 'Tipo de falla con revisión manual',
  fuera_horario: 'Fuera del horario del contrato', keyword_alerta: 'Palabra de alerta en la descripción',
  severidad_no_configurada: 'Severidad no configurada en la matriz', confirmacion_un_faltante: 'Falta la confirmación de UN',
}

/** §6.8.7: las cuatro razones de rechazo y su módulo destino. */
export const RAZONES_RECHAZO: { valor: RazonRechazo; texto: string; destino: string }[] = [
  { valor: 'por_presupuesto', texto: 'Por presupuesto', destino: 'Módulo: Por presupuesto' },
  { valor: 'requiere_cotizacion', texto: 'Requiere cotización primero', destino: 'Módulo: Cotizaciones' },
  { valor: 'seguimiento_interno', texto: 'Seguimiento interno', destino: 'Módulo: Seguimiento interno' },
  { valor: 'reprogramar', texto: 'Reprogramar a otra fecha', destino: 'Módulo: Reprogramación' },
]

export const NOMBRE_TIMEOUT: Record<ComportamientoTimeout, string> = {
  escalar: 'Escalar al siguiente nivel', bloquear_alertar: 'Bloquear y alertar', autorizar_automatico: 'Autorizar automáticamente', depende_criticidad: 'Depende de criticidad',
}

export interface SeveridadResumen { id: string; clave: string; nombre: string; orden: number; color_hex: string }

export interface FlujoResumen {
  id: string
  nivel_actual: number
  nivel_maximo_requerido: number
  estado: EstadoFlujo
  iniciado_at: string
  resuelto_at: string | null
  rol_aprobador_actual: Rol | null
  vence_at: string | null
}

export interface FolioResumen {
  id: string
  created_at: string
  updated_at: string
  version_hash: string | null
  numero_folio: string
  tenant_id: string
  prestador_id: string
  un_id: string
  un_nombre: string | null
  un_codigo: string | null
  equipo_id: string
  equipo_codigo: string | null
  equipo_nombre: string | null
  tipo_falla_id: string | null
  tipo_falla: string | null
  tipo_folio: TipoFolio
  estado: EstadoFolio
  prioridad: number
  descripcion: string
  tecnico_id: string | null
  tecnico_nombre: string | null
  severidad: SeveridadResumen | null
  severidad_origen: 'automatica_matriz' | 'override_admin'
  confirmacion_un: boolean
  monto_estimado: string | null
  criticidad: Criticidad | null
  capturado_por: string
  capturado_por_nombre: string | null
  capturado_at: string
  fecha_falla: string
  fecha_inicio_atencion: string | null
  fecha_cierre: string | null
  razon_cancelacion: string | null
  flujo: FlujoResumen | null
  triggers_pendientes: number
  antiguedad_horas: number
  plan_id?: string | null          // P06
  calendario_id?: string | null    // P06
  plan_nombre?: string | null
}

export interface HistorialFolio {
  id: string
  evento: string
  estado_anterior: EstadoFolio | null
  estado_nuevo: EstadoFolio
  actor_id: string | null
  actor_rol: string
  actor_nombre: string | null
  timestamp: string
  notas: string
  datos_contexto_json: Record<string, unknown>
}

export interface TriggerFolio { id: string; trigger_tipo: TriggerRevision; descripcion: string; timestamp: string; resuelto: boolean }

export interface DecisionAprobacion {
  id: string
  flujo_id: string
  nivel: number
  actor_id: string | null
  actor_nombre: string | null
  decision: 'aprobado' | 'rechazado' | 'auto_aprobado' | 'escalado' | 'bloqueado'
  razon_rechazo: RazonRechazo | null
  modulo_destino: string | null
  modulo_destino_id: string | null
  canal: CanalAprobacion
  timestamp: string
  notas: string
}

export interface VinculoFormulario { respuesta_id: string; formulario_id: string; formulario_nombre: string | null; version_formulario: number; timestamp: string; respuestas_json: Record<string, unknown> }
export interface EvidenciaFolio { id: string; evidencia_id: string | null; tipo: 'antes' | 'durante' | 'despues' | 'firma' | 'factura' | 'otro'; archivo_key: string; geolat: number | null; geolng: number | null; timestamp_captura: string; subido_por: string | null }
export interface RefaccionFolio { id: string; articulo_id: string | null; descripcion: string; cantidad: string; origen: 'almacen' | 'oc' | 'caja_chica'; costo_unitario: string; gasto_caja_chica_id: string | null }
export interface SLAFolio { nivel_severidad_id: string | null; tiempo_respuesta_prometido_horas: number; tiempo_resolucion_prometido_horas: number; tiempo_respuesta_real_min: number | null; tiempo_resolucion_real_min: number | null; cumplimiento_respuesta: boolean | null; cumplimiento_resolucion: boolean | null }

export interface FolioDetalle {
  folio: FolioResumen
  captura: {
    capturado_por: string; capturado_por_nombre: string | null; capturado_at: string
    un: { id?: string; codigo?: string; nombre?: string; direccion?: string }
    equipo: { id?: string; codigo?: string; nombre?: string; criticidad?: Criticidad | null; garantia_vigente_hasta?: string | null }
    tipo_falla: string | null; descripcion: string; geolat_captura: number | null; geolng_captura: number | null
    confirmacion_un: boolean; confirmacion_un_timestamp: string | null; confirmacion_un_geolat: number | null; confirmacion_un_geolng: number | null
    folio_duplicado_justificacion: string | null; folio_duplicado_ref_id: string | null; folio_duplicado_ref_numero: string | null
  }
  formulario_captura: VinculoFormulario | null
  asignacion: { tecnico_id: string | null; tecnico_nombre: string | null; asignado_at: string | null; vehiculo: string | null; orden_en_ruta: number | null; ventana_inicio: string | null; ventana_fin: string | null }
  historial: HistorialFolio[]
  reasignaciones: ReasignacionFolio[]
  evidencias: EvidenciaFolio[]
  formulario_atencion: VinculoFormulario | null
  refacciones: RefaccionFolio[]
  sla: SLAFolio | null
  encuesta: { operador_id: string; nps_score: number; respuesta_id: string | null; timestamp: string } | null
  triggers_revision: TriggerFolio[]
  aprobacion: FlujoResumen | null
  decisiones: DecisionAprobacion[]
  chat: unknown[]
  financiero: Record<string, unknown>
  acciones: EstadoFolio[]
  puede_aprobar: boolean
}

export interface TarjetaDuplicado {
  existe: boolean
  bloqueo_total: boolean
  folio_id: string | null
  numero_folio: string | null
  estado: EstadoFolio | null
  descripcion: string | null
  capturado_at: string | null
  tecnico_nombre: string | null
  eta: string | null
  severidad: string | null
}

export interface TransicionTabla { origen: EstadoFolio; destino: EstadoFolio; roles: string[] }

export interface FolioEntrada {
  un_id: string
  equipo_id: string
  tipo_falla_id: string
  descripcion: string
  tipo_folio?: TipoFolio
  confirmacion_un: boolean
  confirmacion_un_timestamp?: string | null
  confirmacion_un_geolat?: number | null
  confirmacion_un_geolng?: number | null
  geolat_captura?: number | null
  geolng_captura?: number | null
  respuesta_id?: string | null
  folio_duplicado_justificacion?: string | null
  monto_estimado?: number | null
}

export interface PendienteAprobacion { folio: FolioResumen; flujo: FlujoResumen; vence_at: string | null }

export interface Politicas { tenant_id: string; bloqueo_total_duplicados: boolean; revision_obligatoria_garantia: boolean; autorizacion_automatica_criticos: boolean; aprobacion_secuencial: boolean; prefijo_folio: string; ultimo_numero: number }
export interface Regla { id?: string; nivel: number; criterio: 'monto' | 'criticidad' | 'tipo_trabajo'; operador: string; valor_json: Record<string, unknown>; activa: boolean }
export interface NivelConfig { id?: string; nivel: number; rol_aprobador: Rol; tiempo_limite_horas: number; comportamiento_timeout: ComportamientoTimeout; notificar_por_json: string[] }
export interface ConfiguracionAprobacion { politicas: Politicas; reglas: Regla[]; niveles: NivelConfig[] }
