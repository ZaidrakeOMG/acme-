/** Tipos de mensajería por WhatsApp y SMS (§6.1, §7.5). F2-02. */

export type CanalMensajeria = 'whatsapp' | 'sms'
export type EstadoEnvio = 'en_cola' | 'enviado' | 'entregado' | 'leido' | 'fallido' | 'rechazado_por_proveedor'
export type EstadoAprobacion = 'borrador' | 'enviada' | 'aprobada' | 'rechazada' | 'pausada'

export interface HorarioSilencio {
  inicio: string
  fin: string
  zona: string
}

export interface ConfiguracionMensajeria {
  id: string
  prestador_id: string
  tenant_id: string | null
  whatsapp_activo: boolean
  sms_activo: boolean
  eventos_whatsapp: string[]
  eventos_sms: string[]
  horario_silencio: HorarioSilencio
  tope_mensual_mensajes: number
  alerta_consumo_pct: number
  remitente_whatsapp: string
  remitente_sms: string
  tarifa_whatsapp: string
  tarifa_sms: string
  moneda: string
  ventana_respuesta_horas: number
}

export interface Consumo {
  mes: string
  mensajes: number
  tope: number
  porcentaje: number
  costo_estimado: string
  moneda: string
  alerta_pct: number
  por_canal: Record<string, { mensajes: number; costo: string }>
}

export interface BotonPlantilla {
  tipo: 'url' | 'respuesta_rapida'
  texto: string
  ruta?: string
}

export interface Plantilla {
  id: string
  clave: string
  nombre: string
  evento: string
  canal: CanalMensajeria
  idioma: string
  nombre_proveedor: string
  categoria: 'utility' | 'authentication' | 'marketing'
  cuerpo: string
  encabezado: string
  pie: string
  botones: BotonPlantilla[]
  variables: string[]
  estado_aprobacion: EstadoAprobacion
  motivo_rechazo: string
  version: number
  activa: boolean
  prestador_id: string | null
  es_global: boolean
}

export interface VistaPrevia {
  clave: string
  canal: CanalMensajeria
  cuerpo: string
  botones: { texto: string; tipo: string }[]
  segmentos: number
  codificacion: string
  caracteres: number
  critica: boolean
  aviso: string
}

export interface Envio {
  id: string
  canal: CanalMensajeria
  estado: EstadoEnvio
  evento: string
  plantilla: string
  proveedor: string
  telefono: string
  cuerpo: string
  costo_estimado: string
  moneda: string
  segmentos_sms: number
  intentos: number
  codigo_error: string
  detalle_error: string
  created_at: string
  enviado_at: string | null
  entregado_at: string | null
  leido_at: string | null
  abierto_at: string | null
  usuario_id: string | null
  critico: boolean
  enlace_destino: string
  mensaje_id_proveedor: string | null
}

export interface ModoCanal {
  modo: 'stub' | 'prueba' | 'real'
  proveedor: string
  remitente: string
}

export interface Modos {
  whatsapp: ModoCanal
  sms: ModoCanal
  pendiente_para_produccion: string[]
  guia: string
}

export interface ConsentimientoCanal {
  consentimiento_at: string | null
  baja_at: string | null
  activo: boolean
}

export interface MiTelefono {
  telefono_mascara: string | null
  tiene_telefono: boolean
  verificado: boolean
  verificado_at: string | null
  whatsapp: ConsentimientoCanal
  sms: ConsentimientoCanal
  aviso_privacidad: string
}

export const NOMBRE_ESTADO_ENVIO: Record<EstadoEnvio, string> = {
  en_cola: 'En cola',
  enviado: 'Enviado',
  entregado: 'Entregado',
  leido: 'Leído',
  fallido: 'Falló',
  rechazado_por_proveedor: 'Rechazado por el proveedor',
}

export const NOMBRE_APROBACION: Record<EstadoAprobacion, string> = {
  borrador: 'Borrador',
  enviada: 'Enviada a Meta',
  aprobada: 'Aprobada',
  rechazada: 'Rechazada',
  pausada: 'Pausada',
}

export const NOMBRE_CANAL: Record<string, string> = {
  app: 'Bandeja',
  push: 'Push',
  email: 'Correo',
  whatsapp: 'WhatsApp',
  sms: 'SMS',
}
