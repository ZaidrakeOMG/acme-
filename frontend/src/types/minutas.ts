/** Espejo de backend/schemas/minutas.py (P07): hallazgos, minuta, notificaciones, módulos de seguimiento y clasificación. */
import type { Rol } from './api'
import type { CanalAprobacion, EstadoFolio, FolioResumen } from './folios'

export type NivelUrgencia = 'baja' | 'media' | 'alta' | 'critica'
export type OpcionRespuesta = 'enterado' | 'cotizacion' | 'autorizar_reparar' | 'por_presupuesto' | 'seguimiento_interno' | 'reprogramacion'
export type EstadoMinuta = 'borrador' | 'pendiente_validacion' | 'enviada' | 'respondida' | 'vencida'
export type ModoMinuta = 'automatica' | 'con_validacion'
export type CanalNotificacion = 'push' | 'email' | 'whatsapp' | 'sms' | 'app'
export type EstadoNotificacion = 'pendiente' | 'enviada' | 'fallida' | 'omitida'
export type Modulo = 'cotizaciones' | 'presupuesto' | 'interno' | 'reprogramacion'
export type ModuloDestino = 'cotizaciones' | 'por_presupuesto' | 'seguimiento_interno' | 'reprogramacion'
export type OpcionClasificacion = 'presupuesto' | 'reprogramacion' | 'cotizacion' | 'autorizado' | 'seguimiento_interno'

/** §7.4: las seis opciones con su efecto literal. */
export const OPCIONES_RESPUESTA: { valor: OpcionRespuesta; texto: string; efecto: string }[] = [
  { valor: 'enterado', texto: 'Enterado sin observaciones', efecto: 'Queda registrado como recibido; no genera módulo de seguimiento.' },
  { valor: 'cotizacion', texto: 'Cotización', efecto: 'Se crea en Cotizaciones como «solicitada»; el prestador recibe aviso para prepararla.' },
  { valor: 'autorizar_reparar', texto: 'Autorizar reparar sin cotización', efecto: 'Se genera un folio correctivo directamente autorizado; el despachador lo programa.' },
  { valor: 'por_presupuesto', texto: 'Por presupuesto', efecto: 'Pasa a Por presupuesto como «diferido»; reaparece en la minuta mensual y al inicio de cada período.' },
  { valor: 'seguimiento_interno', texto: 'Seguimiento interno', efecto: 'Tú gestionas con tu proveedor o garantía; ACMA alerta si pasan 15 días sin novedad.' },
  { valor: 'reprogramacion', texto: 'Reprogramación', efecto: 'Registra la fecha acordada con el tercero; ACMA alerta si la fecha vence sin cambio de estado.' },
]

/** §6.10.5: las cinco opciones de clasificación. */
export const OPCIONES_CLASIFICACION: { valor: OpcionClasificacion; texto: string; efecto: string }[] = [
  { valor: 'presupuesto', texto: 'Pendiente por presupuesto', efecto: 'Pasa a Por presupuesto; reaparece en la minuta mensual y al inicio del período.' },
  { valor: 'reprogramacion', texto: 'Pendiente por reprogramación', efecto: 'Pide una fecha tentativa y crea el recordatorio en Reprogramación.' },
  { valor: 'cotizacion', texto: 'Pendiente por cotización', efecto: 'Solicita cotización al prestador (Mesa de control, Despachador y Admin prestador).' },
  { valor: 'autorizado', texto: 'Autorizado', efecto: 'El despachador puede asignarlo; el SLA corre desde este momento.' },
  { valor: 'seguimiento_interno', texto: 'Seguimiento interno', efecto: 'Lo gestionas con otro proveedor o vía garantía; ACMA alerta a los 15 días sin novedad.' },
]

export const NOMBRE_ESTADO_MINUTA: Record<EstadoMinuta, string> = { borrador: 'Borrador', pendiente_validacion: 'Pendiente de validación', enviada: 'Enviada', respondida: 'Respondida', vencida: 'Vencida' }
export const NOMBRE_MODULO: Record<Modulo, string> = { cotizaciones: 'Cotizaciones', presupuesto: 'Por presupuesto', interno: 'Seguimiento interno', reprogramacion: 'Reprogramación' }
export const RUTA_MODULO: Record<ModuloDestino, Modulo> = { cotizaciones: 'cotizaciones', por_presupuesto: 'presupuesto', seguimiento_interno: 'interno', reprogramacion: 'reprogramacion' }
export const ESTADOS_MODULO: Record<Modulo, string[]> = {
  cotizaciones: ['solicitada', 'en_preparacion', 'enviada', 'autorizada', 'rechazada', 'convertida'],
  presupuesto: ['diferido', 'reactivado', 'descartado'],
  interno: ['registrado', 'en_gestion', 'con_proveedor', 'resuelto', 'cancelado'],
  reprogramacion: ['pendiente_fecha', 'fecha_asignada', 'tercero_confirmado', 'en_ejecucion', 'resuelto', 'cancelado'],
}
export const NOMBRE_ESTADO_MODULO: Record<string, string> = {
  solicitada: 'Solicitada por admin UN', en_preparacion: 'En preparación', enviada: 'Enviada al cliente', autorizada: 'Autorizada', rechazada: 'Rechazada', convertida: 'Convertida en TE',
  diferido: 'Diferido', reactivado: 'Reactivado', descartado: 'Descartado definitivamente',
  registrado: 'Registrado', en_gestion: 'En gestión', con_proveedor: 'Con proveedor confirmado', resuelto: 'Resuelto', cancelado: 'Cancelado',
  pendiente_fecha: 'Pendiente de fecha', fecha_asignada: 'Fecha asignada', tercero_confirmado: 'Tercero confirmado', en_ejecucion: 'En ejecución',
}

export interface Hallazgo {
  id: string
  folio_id: string | null
  tenant_id: string
  prestador_id: string
  un_id: string
  equipo_id: string | null
  descripcion: string
  nivel_urgencia: NivelUrgencia
  foto_evidencia_id: string | null
  foto_url: string | null
  tipo: 'preventivo' | 'correctivo'
  origen: 'formulario_atencion' | 'chat' | 'manual'
  respuesta_id: string | null
  mensaje_id: string | null
  capturado_por: string | null
  capturado_por_nombre: string | null
  timestamp: string
  estado_respuesta: 'pendiente' | 'respondido'
  opcion_respuesta: OpcionRespuesta | null
  respondido_por: string | null
  respondido_por_nombre: string | null
  respondido_at: string | null
  modulo_destino: ModuloDestino | null
  modulo_registro_id: string | null
  equipo_codigo: string | null
  equipo_nombre: string | null
  un_codigo: string | null
  un_nombre: string | null
  numero_folio: string | null
}

export interface Contador { total: number; color: 'rojo' | 'amarillo' | 'verde'; umbral: string; pendientes_enviar?: number; pendientes_autorizar?: number; con_tercero?: number }

export interface MinutaResumen {
  id: string
  tenant_id: string
  tenant_nombre: string | null
  prestador_id: string
  un_id: string | null
  un_codigo: string | null
  un_nombre: string | null
  fecha: string
  tipo: 'un' | 'global'
  estado: EstadoMinuta
  modo: ModoMinuta
  timestamp_generacion: string
  timestamp_envio: string | null
  validada_por: string | null
  validada_por_nombre: string | null
  notas_despachador: string
  enviada_sin_validacion: boolean
  vence_respuesta_at: string | null
  respondida_at: string | null
  hash_pdf: string | null
  urgente: boolean
  hallazgos: number
  hallazgos_pendientes: number
  colores: Record<string, string | null>
}

export interface SeccionHallazgo { hallazgo_id: string; descripcion: string; equipo: string; un: string; urgencia: NivelUrgencia; foto_url: string | null; tipo: string; numero_folio: string | null; estado_respuesta: 'pendiente' | 'respondido'; opcion_respuesta: OpcionRespuesta | null; pendiente_de_dias_anteriores: boolean; timestamp: string }
export interface SeccionPreventivo { calendario_id: string; folio_id: string | null; numero_folio: string | null; un: string; equipo: string; tecnico: string; hora: string | null; fecha_programada: string; fecha_real: string | null; desvio_dias: number | null; texto_desvio: string }
export interface SeccionCotizacion { cotizacion_id: string; numero: string; un: string; equipo: string; descripcion: string; monto: string | null; estado: string; dias: number }

export interface MinutaDetalle extends MinutaResumen {
  secciones: {
    contadores: Record<'cotizaciones' | 'por_presupuesto' | 'seguimiento_interno' | 'reprogramacion', Contador>
    preventivos: SeccionPreventivo[]
    hallazgos: SeccionHallazgo[]
    cotizaciones: { pendientes_enviar: SeccionCotizacion[]; pendientes_autorizar: SeccionCotizacion[] }
    trabajos_especiales: { nota: string }
    peticiones: { peticion_id: string; texto: string; un: string; origen: string; capturado_por: string; numero_folio: string | null; timestamp: string }[]
    pendientes_autorizacion: { folio_id: string; numero_folio: string; descripcion: string; nivel: number; rol_aprobador: string | null; monto_estimado: string | null }[]
    recordatorio_presupuesto?: { hallazgo_presupuesto_id: string; descripcion: string; un: string; periodo: string; dias_diferido: number; monto_estimado: string | null; motivo: string }[]
  }
  hallazgos_detalle: Hallazgo[]
  respuestas: { id: string; hallazgo_id: string; opcion_elegida: OpcionRespuesta; usuario_id: string | null; usuario_nombre: string | null; timestamp: string; notas: string; canal: CanalNotificacion; modulo_destino: ModuloDestino | null; modulo_registro_id: string | null; folio_generado_id: string | null }[]
  destinatarios: { usuario_id: string; nombre: string | null; canal: CanalNotificacion; estado_entrega: EstadoNotificacion; timestamp: string }[]
  puede_validar: boolean
  puede_responder: boolean
  opciones: { valor: OpcionRespuesta; texto: string }[]
  pdf_disponible: boolean
}

export interface MinutaConfiguracion { modo: ModoMinuta; hora_envio: string; ventana_validacion_min: number; plazo_respuesta_horas: number; dias_sin_respuesta_alerta: number; dias_cotizacion_sin_respuesta: number; dias_presupuesto_sin_revision: number; dias_interno_sin_actualizar: number }

export interface RespuestaHallazgoEntrada { opcion: OpcionRespuesta; notas?: string; canal?: CanalNotificacion; fecha_tentativa?: string | null; proveedor?: string | null; trabajo_coordinado?: boolean; variante?: 'A' | 'B' | null }

// --------------------------------------------------------- notificaciones

export interface Notificacion { id: string; evento: string; canal: CanalNotificacion; asunto: string; cuerpo: string; datos: Record<string, unknown>; estado: EstadoNotificacion; timestamp: string; leida_at: string | null; url: string | null }
export interface EventoNotificable { clave: string; nombre: string; canales_default: string[] }
export interface Preferencia { evento: string; canales: CanalNotificacion[] }

// ------------------------------------------------------------ seguimiento

export interface RegistroSeguimiento {
  id: string
  hallazgo_id: string | null
  folio_id: string | null
  numero_folio: string | null
  tenant_id: string
  prestador_id: string
  un_id: string
  un_codigo: string | null
  un_nombre: string | null
  equipo_id: string | null
  equipo_codigo: string | null
  descripcion: string
  origen: string
  estado: string
  estado_desde: string
  dias_en_estado: number
  alertas_activas: string[]
  proxima_alerta: string | null
  urgencia_hallazgo: NivelUrgencia | null
  destinos: string[]
  created_at: string
  updated_at: string
  // Cotizaciones
  numero?: string
  monto?: string | null
  moneda?: string
  fecha_envio?: string | null
  fecha_respuesta?: string | null
  notas_respuesta?: string
  pdf_disponible?: boolean
  hash_pdf?: string | null
  estado_trabajo_especial?: string | null
  pasar_a_presupuesto_si_rechaza?: boolean
  envios_externos?: { id: string; destinatarios: string[]; comentario: string; timestamp: string; estado_entrega: string }[]
  // Presupuesto
  periodo_presupuestal?: string
  ultima_revision?: string
  razon_descarte?: string | null
  monto_estimado?: string | null
  reactivado_como?: string | null
  // Interno / reprogramación
  proveedor?: string | null
  proveedor_tercero?: string | null
  fecha_acordada?: string | null
  fecha_tentativa?: string | null
  referencia_tercero?: string | null
  ultima_actualizacion?: string
  justificacion_cierre?: string | null
  motivo?: string
  trabajo_coordinado?: boolean
  variante?: 'A' | 'B' | null
  tercero_completo?: boolean
  fechas_vencidas_count?: number
  escalada_empresa?: boolean
  historial?: { id: string; estado_anterior: string | null; estado_nuevo: string; usuario_nombre: string | null; actor_rol: string; timestamp: string; notas: string; datos_json: Record<string, unknown> }[]
}

export interface CambioEstado { estado: string; notas?: string; proveedor?: string | null; fecha_acordada?: string | null; referencia_tercero?: string | null; descripcion?: string | null; monto?: string | null; pasar_a_presupuesto?: boolean | null; como?: 'folio' | 'cotizacion' | null }

export interface ReporteEjecutivo { desde: string | null; hasta: string | null; tiempo_promedio_resolucion_dias: Record<string, number | null>; totales: Record<string, number>; tasa_conversion_cotizaciones: number; cotizaciones: Record<string, number>; hallazgos_recurrentes: { tipo_equipo: string; total: number }[]; monto_potencial: { un_id: string; un_codigo: string | null; diferidos: number; monto_potencial: string }[] }

// ---------------------------------------------------------- clasificación

export interface PendienteClasificacion { folio: FolioResumen; pendiente_desde: string; plazo_at: string; horas_restantes: number; vencido: boolean; opciones: { valor: OpcionClasificacion; texto: string }[] }
export interface ClasificacionConfig { severidades_no_criticas_json: string[]; plazo_horas: number; umbral_calificacion: number; admin_empresa_puede_clasificar: boolean; puntos_json: Record<string, number>; activa: boolean }
export interface Calificacion { id: string; usuario_id: string; usuario_nombre: string | null; un_id: string | null; un_codigo: string | null; periodo: string; puntos_total: number; folios_clasificados_tiempo: number; folios_tardios: number; folios_sin_clasificar: number; minutas_respondidas: number; minutas_tardias: number; calificacion_final: string; eventos_json: { tipo: string; descuento: number; folio_id?: string; minuta_id?: string; horas_retraso?: string | number }[]; calculada_at: string; cerrada: boolean }

export const ROLES_MINUTA: Rol[] = ['superadmin', 'admin_prestador', 'despachador', 'mesa_control', 'admin_empresa', 'admin_un', 'supervisor_operadores', 'direccion_prestador', 'supervisor_prestador', 'operador']
export const ROLES_VALIDAN: Rol[] = ['superadmin', 'despachador', 'admin_prestador', 'mesa_control']
export const ROLES_RESPONDEN: Rol[] = ['superadmin', 'admin_un', 'admin_empresa']
export const ROLES_SEGUIMIENTO: Rol[] = ['superadmin', 'admin_prestador', 'despachador', 'mesa_control', 'admin_empresa', 'admin_un', 'supervisor_operadores', 'direccion_prestador', 'supervisor_prestador']
export const ROLES_KANBAN: Rol[] = ['superadmin', 'admin_prestador', 'despachador']
export const ROLES_CLASIFICAN: Rol[] = ['superadmin', 'admin_un', 'admin_empresa', 'supervisor_operadores']
export const ROLES_MARCAN_CHAT: Rol[] = ['superadmin', 'tecnico', 'operador', 'admin_un', 'despachador']

export type { CanalAprobacion, EstadoFolio }
