/** Tipos de la pantalla de operaciones en tiempo real y de la jornada del técnico (§6.8.4). F2-03. */

export type EstatusOperativo = 'fuera_de_jornada' | 'en_ruta' | 'en_servicio' | 'pausa' | 'sin_senal'
export type MotivoPausa = 'comida' | 'tramite' | 'otro'
export type RespuestaAlerta = 'estoy_bien' | 'necesito_apoyo'

export interface Parametros {
  frecuencias: { jornada_activa_s: number; pausa_s: number; bateria_baja_s: number; bateria_baja_pct: number }
  geocerca_radio_m: number
  jornada_cierre_horas: number
  sin_senal_min: number
  tiempo_muerto_min: number
  aviso_geolocalizacion: string
  max_lote: number
  precision_maxima_m: number
  horas_recorrido: number
  desvio_ruta: string
}

export interface Jornada {
  id: string
  inicio: string
  estado: 'activa' | 'pausa' | 'cerrada'
  dispositivo_id: string
  posiciones: number
  pausa_desde?: string | null
  pausa_motivo?: string | null
}

export interface MiJornada extends Parametros {
  tecnico_id: string
  estatus: EstatusOperativo
  jornada: Jornada | null
  aviso_aceptado: boolean
}

export interface SugerenciaLlegada {
  folio_id: string
  numero_folio: string
  distancia_m: number
  radio_m: number
  sucursal: string
  mensaje: string
}

export interface RespuestaPosiciones {
  aceptadas: number
  descartadas: { capturada_at: string; motivo: string }[]
  jornada_id: string
  estatus: EstatusOperativo
  sugerencia_llegada: SugerenciaLlegada | null
}

export interface TecnicoEnTablero {
  tecnico_id: string
  usuario_id: string
  nombre: string
  numero_empleado: string | null
  estatus: EstatusOperativo
  estatus_texto: string
  en_jornada: boolean
  jornada_desde: string | null
  minutos_en_estatus: number | null
  folios_pendientes: number
  lat: number | null
  lng: number | null
  ultima_posicion_at: string | null
  precision_m: string | null
  bateria_pct: number | null
  vehiculo_placas: string | null
  telefono: string | null
  alerta: { tipo: string; desde: string; escalada: boolean } | null
  respuesta_tecnico: string | null
}

export interface FolioEnTablero {
  folio_id: string
  numero_folio: string
  estado: string
  tecnico_id: string | null
  tecnico: string | null
  un_id: string
  sucursal: string
  capturado_at: string
  sla_disponible: boolean
  minutos_restantes: number | null
  limite_sla_min: number | null
  limite_respuesta_min?: number | null
  minutos_transcurridos?: number | null
  respondido_at?: string | null
  umbral_riesgo_pct?: number | null
  en_riesgo: boolean
  incumplido: boolean
  cumplimiento: boolean | null
}

export interface UnidadEnTablero {
  un_id: string
  codigo: string
  nombre: string
  lat: number
  lng: number
  folios_activos: number
}

export interface AlertaEnTablero {
  id: string | null
  clave: string
  nombre: string
  entidad_tipo: string | null
  entidad_id: string | null
  timestamp: string
  estado: string
  escalada: boolean
  vista: boolean
  datos: Record<string, unknown>
}

export interface Tablero {
  generado_at: string
  tecnicos: TecnicoEnTablero[]
  folios: FolioEnTablero[]
  unidades: UnidadEnTablero[]
  alertas: AlertaEnTablero[]
  indicadores: Record<string, unknown>
  parametros: Parametros
  solo_lectura: boolean
}

export interface PuntoRecorrido {
  lat: number
  lng: number
  capturada_at: string
  precision_m: string | null
  velocidad_mps: string | null
  bateria_pct: number | null
  tardia: boolean
}

export interface Recorrido {
  tecnico_id: string
  nombre: string
  desde: string
  estatus: EstatusOperativo
  puntos: PuntoRecorrido[]
}

export interface AlertaDelTecnico {
  id: string
  tipo: string
  desde: string
  folio_id: string | null
  pregunta: string
  datos: Record<string, unknown>
}

/** Evento que llega por el WebSocket del tablero. */
export interface EventoOperacion {
  evento: 'conectado' | 'pong' | 'posicion' | 'estatus' | 'jornada' | 'alerta' | 'escalacion' | 'respuesta_alerta'
  prestador_id?: string
  tecnico_id?: string
  lat?: number
  lng?: number
  precision_m?: number | null
  bateria_pct?: number | null
  capturada_at?: string
  estatus?: EstatusOperativo
  estado?: string
  clave?: string
  tipo?: string
  etiqueta?: string
  minutos?: number
  seguimiento_id?: string
  respuesta?: string
  motivo?: string
  cerrada_por?: string
}

/** Color y texto por estatus: §6.8.4 pide que el estatus se vea también en texto, no solo en color. */
export const COLOR_ESTATUS: Record<EstatusOperativo, string> = {
  en_servicio: 'bg-emerald-100 text-emerald-800 border-emerald-300',
  en_ruta: 'bg-sky-100 text-sky-800 border-sky-300',
  pausa: 'bg-amber-100 text-amber-800 border-amber-300',
  sin_senal: 'bg-slate-200 text-slate-700 border-slate-400',
  fuera_de_jornada: 'bg-white text-slate-500 border-slate-200',
}

export const MARCADOR_ESTATUS: Record<EstatusOperativo, string> = {
  en_servicio: '#047857',
  en_ruta: '#0369a1',
  pausa: '#b45309',
  sin_senal: '#64748b',
  fuera_de_jornada: '#cbd5e1',
}

export const NOMBRE_ESTATUS: Record<EstatusOperativo, string> = {
  en_servicio: 'En servicio',
  en_ruta: 'En ruta',
  pausa: 'En pausa',
  sin_senal: 'Sin señal',
  fuera_de_jornada: 'Fuera de jornada',
}

export const MOTIVOS_PAUSA: { valor: MotivoPausa; texto: string }[] = [
  { valor: 'comida', texto: 'Comida' },
  { valor: 'tramite', texto: 'Trámite' },
  { valor: 'otro', texto: 'Otro' },
]

export const ROLES_TABLERO = ['superadmin', 'admin_prestador', 'despachador', 'mesa_control'] as const
