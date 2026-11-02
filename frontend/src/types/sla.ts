/** Contador de SLA, penalizaciones, iguala, panel de alertas, BI y reportes (§6.10.1, §6.9.6, §6.8.4-5, §7.5). P10. */
import type { Rol } from './api'

// ------------------------------------------------------------------ SLA
export type MotivoPausa = 'reasignacion' | 'pendiente_informacion' | 'otro'
export type CausaExclusion = 'cliente_sin_acceso' | 'fuerza_mayor' | 'refaccion_no_disponible_mercado' | 'otra'
export const NOMBRE_MOTIVO_PAUSA: Record<MotivoPausa, string> = {
  reasignacion: 'Reasignación del técnico', pendiente_informacion: 'Espera de datos del operador', otro: 'Otro',
}
export const NOMBRE_CAUSA: Record<CausaExclusion, string> = {
  cliente_sin_acceso: 'El cliente no dio acceso a la UN', fuerza_mayor: 'Fuerza mayor',
  refaccion_no_disponible_mercado: 'Refacción no disponible en el mercado', otra: 'Otra causa',
}

export interface PausaSLA { id: string; motivo: MotivoPausa; inicio: string; fin: string | null; minutos: number | null; notas: string }
export interface ExclusionEnFolio {
  id: string; causa: CausaExclusion; descripcion: string; minutos: number; inicio: string; fin: string
  aprobada: boolean | null; razon_decision: string; decidida_at: string | null
}
export interface SLAFolio {
  disponible: boolean; motivo?: string | null
  tiempo_inicio: string | null; tiempo_respuesta_at: string | null; tiempo_fin: string | null
  limite_respuesta_min: number | null; limite_sla_min: number | null
  tiempo_pausado_min: number; tiempo_exclusion_min: number
  tiempo_efectivo_min: number | null; tiempo_respuesta_efectivo_min: number | null
  cumplimiento_respuesta: boolean | null; cumplimiento_resolucion: boolean | null; cumplimiento: boolean | null
  penalizacion_calculada: string; penalizacion_detalle: Record<string, unknown>; excluir_sla_por_cliente: boolean
  tiempo_respuesta_prometido_horas: number | null; tiempo_resolucion_prometido_horas: number | null
  pausas: PausaSLA[]; exclusiones: ExclusionEnFolio[]
}
export interface Exclusion {
  id: string; created_at: string; updated_at: string; version_hash: string | null
  folio_id: string; tenant_id: string; prestador_id: string; causa: CausaExclusion; descripcion: string
  registrado_por: string | null; timestamp_inicio: string; timestamp_fin: string; minutos: number
  aprobada: boolean | null; aprobado_por: string | null; decidida_at: string | null; razon_decision: string
  numero_folio: string | null
}

// -------------------------------------------------- penalizaciones e iguala
export type EstadoPenalizacion = 'borrador' | 'revisado' | 'cerrado'
export const NOMBRE_ESTADO_PENALIZACION: Record<EstadoPenalizacion, string> = {
  borrador: 'Borrador', revisado: 'Revisado', cerrado: 'Cerrado',
}
export interface DetallePenalizacion {
  folio_id: string; numero_folio: string; limite_min: number | null; efectivo_min: number | null
  pausado_min: number | null; excluido_min: number | null; penalizacion: string; cierre: string | null
}
export interface Penalizacion {
  id: string; created_at: string; updated_at: string; version_hash: string | null
  contrato_id: string; tenant_id: string; prestador_id: string; periodo: string
  total_folios: number; folios_incumplidos: number; monto_penalizacion: string; moneda: string
  estado: EstadoPenalizacion; detalle_json: DetallePenalizacion[]
  revisado_por: string | null; revisado_at: string | null; cerrado_at: string | null; incluido_en_factura_id: string | null
}
export interface Iguala {
  id: string; created_at: string; updated_at: string; version_hash: string | null
  contrato_id: string; periodo: string; correctivos_incluidos: number; correctivos_atendidos: number
  correctivos_adicionales: number; preventivos_incluidos: number; preventivos_ejecutados: number
  tarifa_mensual: string; folios_adicionales_json: { folio_id: string; numero_folio: string; cierre: string | null }[]
}
export interface CumplimientoContrato {
  contrato_id: string; periodo: string; folios_cerrados: number; cumplimiento_respuesta_pct: string
  cumplimiento_resolucion_pct: string; folios_incumplidos: number; penalizacion: string
  por_severidad: Record<string, { total: number; respuesta_ok: number; resolucion_ok: number; penalizados: number; respuesta_pct: string; resolucion_pct: string }>
  exclusiones_pendientes: number
}

// -------------------------------------------------------------- alertas
export interface AlertaPanel {
  id: string; clave_alerta: string; descripcion: string | null; tenant_id: string | null; prestador_id: string | null
  entidad_tipo: string | null; entidad_id: string | null; umbral_en_momento: string | null
  datos_contexto_json: Record<string, unknown>; estado: string; timestamp_disparo: string; timestamp_vista: string | null
  vista_por: string | null; atendida_at: string | null; atendida_por: string | null; nota_atencion: string; escalada: boolean
}

// ------------------------------------------------------------------- BI
export interface NivelJerarquia { id: string; nombre: string; folios: number; cerrados: number; sla_resolucion_pct: string; costo: string }
export interface CumplimientoSLA {
  total: number; respuesta_pct: string; resolucion_pct: string
  por_severidad: Record<string, { total: number; respuesta_ok: number; resolucion_ok: number; penalizados: number; respuesta_pct: string; resolucion_pct: string }>
}
export interface Jornada {
  completados: number; total_dia: number; tecnicos_activos: number; alertas_abiertas: number
  tiempo_promedio_atencion_horas: string; aviso_fase_2: string
}
export interface Tablero {
  tipo: 'cliente' | 'supervision' | 'prestador' | 'direccion' | 'jornada'
  rol: Rol; periodo: { desde: string; hasta: string }; cache: boolean; ttl_cache_segundos: number
  folios_por_estado?: Record<string, number>
  folios_por_severidad?: Record<string, number>
  cumplimiento_sla?: CumplimientoSLA
  mttr?: { folios: number; horas: string }
  mtbf?: { equipos: number; intervalos: number; horas: string; aviso: string }
  gasto_vs_presupuesto?: { presupuestos: number; monto: string; consumido: string; disponible: string; porcentaje: string }
  costo?: { folios: number; total: string }
  preventivos?: { programados: number; ejecutados: number; cumplimiento_pct: string; desvio_promedio_dias: string }
  hallazgos?: { total: number; convertidos_a_cotizacion: number; conversion_pct: string }
  trabajos_especiales?: { total: number; urgencias: number; por_estado: Record<string, number> }
  cotizaciones?: { total: number; autorizadas: number; conversion_pct: string; monto_autorizado: string }
  penalizaciones?: { periodos: number; folios_incumplidos: number; monto: string; detalle: { periodo: string; estado: string; monto: string; folios_incumplidos: number }[] }
  iguala?: { contrato: string; periodo: string; correctivos_incluidos: number; correctivos_atendidos: number; correctivos_adicionales: number; preventivos_incluidos: number; preventivos_ejecutados: number; tarifa_mensual: string }[]
  carga_por_tecnico?: { tecnico_id: string; nombre: string; asignados: number; cerrados: number }[]
  inventario_y_caja?: { existencias_bajo_minimo: number; fondos: number; saldo_fondos: string; gastos: number; gastos_por_aprobar: number; monto_gastos: string }
  top_equipos_costo?: { equipo_id: string; codigo: string; nombre: string; valor: string; fallas: number }[]
  top_equipos_fallas?: { equipo_id: string; codigo: string; nombre: string; valor: string; fallas: number }[]
  folios_por_cliente?: { cliente: string; por_estado: Record<string, number>; total: number }[]
  jerarquia?: { grupos: NivelJerarquia[]; unidades: NivelJerarquia[] }
  comparativo_periodo?: { anterior: Omit<NivelJerarquia, 'id' | 'nombre'>; anio_anterior: Omit<NivelJerarquia, 'id' | 'nombre'> }
  calificacion_admin_un?: { periodo: string; calificacion: string; clasificados_en_plazo: number; tardios: number; sin_clasificar: number; minutas_respondidas: number } | null
  sla_en_riesgo?: { id: string; clave: string; disparo: string; datos: Record<string, unknown>; atendida: boolean; escalada: boolean; estado: string }[]
  escalaciones?: { id: string; clave: string; disparo: string; datos: Record<string, unknown>; atendida: boolean; escalada: boolean; estado: string }[]
  jornada?: Jornada
  sin_finanzas?: boolean
  solo_lectura?: boolean
  aviso?: string
}

// -------------------------------------------------------------- reportes
export type FormatoReporte = 'pdf' | 'excel'
export type PeriodicidadReporte = 'diaria' | 'semanal' | 'mensual'
export const NOMBRE_PERIODICIDAD: Record<PeriodicidadReporte, string> = {
  diaria: 'Diaria', semanal: 'Semanal', mensual: 'Mensual',
}
export const PLANTILLAS_REPORTE: { clave: string; nombre: string; destinatario: string }[] = [
  { clave: 'cliente', nombre: 'Reporte ejecutivo del cliente', destinatario: 'Admin empresa y Admin UN' },
  { clave: 'prestador', nombre: 'Reporte ejecutivo del prestador', destinatario: 'Admin prestador y Mesa de control' },
  { clave: 'jornada', nombre: 'Cierre de jornada', destinatario: 'Supervisor del prestador' },
]

export interface ReporteProgramado {
  id: string; created_at: string; updated_at: string; version_hash: string | null
  tenant_id: string | null; prestador_id: string | null; nombre: string; tipo_reporte: string
  formato: FormatoReporte; periodicidad: PeriodicidadReporte; dia_hora: string
  filtros_json: Record<string, unknown>; destinatarios_json: string[]; activo: boolean; ultimo_envio_at: string | null
}
export interface ReporteGenerado {
  id: string; created_at: string; updated_at: string; version_hash: string | null
  programado_id: string | null; tipo_reporte: string; formato: FormatoReporte; archivo_key: string
  filas: number; ms_generacion: number | null; generado_at: string
}

export const ROLES_SLA: Rol[] = ['superadmin', 'admin_prestador', 'mesa_control', 'despachador', 'admin_empresa', 'admin_un',
                                 'supervisor_operadores', 'direccion_prestador', 'supervisor_prestador']
export const ROLES_REGISTRAN_EXCLUSION: Rol[] = ['superadmin', 'admin_prestador', 'mesa_control', 'despachador']
export const ROLES_APRUEBAN_EXCLUSION: Rol[] = ['superadmin', 'admin_empresa']
export const ROLES_REVISAN_PENALIZACION: Rol[] = ['superadmin', 'admin_prestador']
export const ROLES_BI: Rol[] = ['superadmin', 'admin_empresa', 'admin_un', 'supervisor_operadores', 'admin_prestador',
                                'mesa_control', 'despachador', 'direccion_prestador', 'supervisor_prestador']
export const ROLES_REPORTES: Rol[] = ['superadmin', 'admin_empresa', 'admin_un', 'admin_prestador', 'mesa_control',
                                      'direccion_prestador', 'supervisor_prestador']
