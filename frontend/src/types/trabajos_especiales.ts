/** Trabajos especiales (§6.10.6) y seguimiento de OC de activos (§6.10.7). P08. */
import type { Rol } from './api'
import type { FolioResumen } from './folios'

export const ESTADOS_TE = ['creado', 'enviado_cliente', 'aceptado', 'rechazado', 'programado', 'en_ejecucion', 'cerrado', 'cancelado'] as const
export type EstadoTE = (typeof ESTADOS_TE)[number]
export const NOMBRE_ESTADO_TE: Record<EstadoTE, string> = {
  creado: 'Creado', enviado_cliente: 'Enviado al cliente', aceptado: 'Aceptado', rechazado: 'Rechazado', programado: 'Programado',
  en_ejecucion: 'En ejecución', cerrado: 'Cerrado', cancelado: 'Cancelado',
}
export const FINALES_TE = new Set<string>(['cerrado', 'cancelado'])

export interface TecnicoTE { id: string; nombre: string | null }

export interface TrabajoEspecial {
  id: string
  numero: string
  tenant_id: string
  prestador_id: string
  un_id: string
  un_codigo: string | null
  un_nombre: string | null
  equipo_id: string | null
  equipo_codigo: string | null
  equipo_nombre: string | null
  cotizacion_id: string | null
  cotizacion_numero: string | null
  cotizacion_estado: string | null
  cotizacion_retroactiva_id: string | null
  cotizacion_retroactiva_numero: string | null
  hallazgo_id: string | null
  descripcion: string
  detalle_json: Record<string, unknown>
  estado: EstadoTE
  estado_desde: string
  dias_en_estado: number
  urgencia: boolean
  creado_por_id: string | null
  creado_por_rol: string
  creado_por_nombre: string | null
  formulario_id: string | null
  respuesta_formulario_id: string | null
  monto: string | null
  moneda: string
  fecha_programada: string | null
  fecha_inicio: string | null
  fecha_cierre: string | null
  tecnicos: TecnicoTE[]
  tecnico_responsable_id: string | null
  tecnico_responsable_nombre: string | null
  folio_id: string | null
  numero_folio: string | null
  estado_folio: string | null
  razon_cancelacion: string | null
  version_enviada: number
  enviado_at: string | null
  aceptado_at: string | null
  programado_at: string | null
  alertas_activas: string[]
  destinos: string[]
  created_at: string
  updated_at: string
}

export interface HistorialTE { id: string; estado_anterior: string | null; estado_nuevo: string; actor_id: string | null; actor_nombre: string | null; actor_rol: string; timestamp: string; notas: string; datos_json: Record<string, unknown> }
export interface RespuestaClienteTE { id: string; version_enviada: number; respondido_por: string | null; respondido_por_nombre: string | null; decision: 'aceptado' | 'rechazado'; comentario: string; canal: string; timestamp: string }
export interface EvidenciaTE { id: string; tipo: 'avance' | 'cierre' | 'firma' | 'documento'; evidencia_id: string | null; archivo_key: string; geolat: number | null; geolng: number | null; timestamp: string; subido_por: string | null }

export interface TrabajoEspecialDetalle extends TrabajoEspecial {
  historial: HistorialTE[]
  respuestas_cliente: RespuestaClienteTE[]
  evidencias: EvidenciaTE[]
  requisitos_cierre_faltantes: string[]
  puede_responder: boolean
}

export interface ReporteTE {
  desde: string | null; hasta: string | null; total: number; por_estado: Record<string, number>; tiempo_promedio_etapas_dias: Record<string, number | null>
  porcentaje_urgencias: number; urgencias: number; monto_total: string; sin_cotizacion_retroactiva: number
}

export interface TrabajoEspecialEntrada { un_id: string; descripcion: string; equipo_id?: string | null; monto?: string | null; urgencia?: boolean; detalle?: Record<string, unknown>; tenant_id?: string | null }
export interface ProgramarEntrada { fecha_programada: string; tecnico_ids: string[]; tecnico_responsable_id?: string | null; notas?: string }

// ------------------------------------------------------------ OC de activos
export const ESTATUS_OC = ['pendiente_iniciar_tramite', 'oc_en_tramite', 'oc_autorizada', 'listo_para_asignar', 'oc_rechazada'] as const
export type EstatusOC = (typeof ESTATUS_OC)[number]
export const NOMBRE_ESTATUS_OC: Record<EstatusOC, string> = {
  pendiente_iniciar_tramite: 'Pendiente de iniciar trámite', oc_en_tramite: 'OC en trámite', oc_autorizada: 'OC autorizada', listo_para_asignar: 'Folio listo para asignar', oc_rechazada: 'OC rechazada',
}

export interface AutorizacionActivo {
  id: string; folio_id: string; tenant_id: string; prestador_id: string; un_id: string; estatus_multinivel: EstatusOC; estatus_nombre: string; estatus_desde: string; dias_en_estatus: number
  numero_oc_provisional: string | null; numero_oc_definitivo: string | null; fecha_autorizacion_erp: string | null; registrado_por: string | null; notas: string
  decision_rechazo: 'cancelar' | 'reprogramar_periodo' | null; periodo_presupuestal_destino: string | null; origen: string; datos_equipo: Record<string, unknown>; hallazgo_presupuesto_id: string | null
  destinos: string[]; created_at: string; updated_at: string
}
export interface HistorialOC { id: string; estatus_anterior: string | null; estatus_nuevo: string; actor_id: string | null; actor_nombre: string | null; actor_rol: string; timestamp: string; notas: string }
export interface PendienteOC extends AutorizacionActivo { folio: FolioResumen }
export interface AutorizacionActivoDetalle extends PendienteOC { historial: HistorialOC[]; equipo_instalado: { id: string; codigo: string; nombre: string; estado: string; marca: string | null; modelo: string | null; numero_serie: string | null } | null }
export interface EstatusOCEntrada { estatus: EstatusOC; numero_oc_provisional?: string | null; numero_oc_definitivo?: string | null; fecha_autorizacion_erp?: string | null; notas?: string; decision_rechazo?: 'cancelar' | 'reprogramar_periodo' | null; periodo_presupuestal_destino?: string | null }

export const ROLES_TE: Rol[] = ['superadmin', 'admin_prestador', 'mesa_control', 'despachador', 'admin_empresa', 'admin_un', 'supervisor_operadores', 'direccion_prestador', 'supervisor_prestador']
export const ROLES_KANBAN_TE: Rol[] = ['superadmin', 'admin_prestador', 'mesa_control', 'despachador']
export const ROLES_CREAN_TE: Rol[] = ['superadmin', 'admin_prestador', 'mesa_control', 'despachador']
export const ROLES_URGENCIA: Rol[] = ['superadmin', 'admin_empresa', 'admin_un']
export const ROLES_OC: Rol[] = ['superadmin', 'admin_empresa', 'admin_un', 'supervisor_operadores', 'admin_prestador', 'mesa_control', 'despachador']
export const ROLES_REGISTRAN_OC: Rol[] = ['superadmin', 'admin_empresa']
