/** Espejo de backend/schemas/medidores.py (F2-04, §6.9.2): medidores de activos, lecturas y llaves de API. */
import type { Rol } from './api'

export type CategoriaMedidor = 'horas' | 'ciclos' | 'distancia' | 'energia' | 'unidades' | 'personalizado'
export type MetodoMedidor = 'tecnico' | 'operador' | 'importacion' | 'estimado'
export type EstadoLectura = 'valida' | 'rechazada' | 'en_revision'
export type TipoCambioMedidor = 'reinicio' | 'reemplazo_medidor'

/** Los seis tipos literales de la tabla de §6.9.2, con el ejemplo del documento. */
export const CATEGORIAS: { valor: CategoriaMedidor; texto: string; ejemplo: string }[] = [
  { valor: 'horas', texto: 'Horas de operación', ejemplo: 'Compresor: cambio de aceite cada 500 h' },
  { valor: 'ciclos', texto: 'Ciclos o conteo', ejemplo: 'Elevador: cables cada 50,000 ciclos' },
  { valor: 'distancia', texto: 'Kilómetros / distancia', ejemplo: 'Generador móvil: mayor cada 10,000 km' },
  { valor: 'energia', texto: 'Energía consumida', ejemplo: 'Motor: rodamientos cada 50,000 kWh' },
  { valor: 'unidades', texto: 'Unidades producidas', ejemplo: 'Línea: banda cada 100,000 piezas' },
  { valor: 'personalizado', texto: 'Personalizado', ejemplo: 'Cualquier variable numérica del cliente' },
]

/** Los cuatro métodos de actualización de §6.9.2. */
export const METODOS: { valor: MetodoMedidor; texto: string; detalle: string }[] = [
  { valor: 'tecnico', texto: 'Lectura del técnico', detalle: 'La captura en el formulario de atención del preventivo' },
  { valor: 'operador', texto: 'Lectura del operador', detalle: 'La captura desde su app, con o sin señal' },
  { valor: 'importacion', texto: 'Importación (ERP o SCADA)', detalle: 'Por archivo o por la API de lecturas' },
  { valor: 'estimado', texto: 'Cálculo estimado', detalle: 'ACMA la estima con el horario de operación configurado' },
]

export const NOMBRE_METODO: Record<MetodoMedidor, string> = {
  tecnico: 'Técnico', operador: 'Operador', importacion: 'Importación', estimado: 'Estimada',
}
export const NOMBRE_ESTADO_LECTURA: Record<EstadoLectura, string> = {
  valida: 'Válida', rechazada: 'Rechazada', en_revision: 'En revisión',
}

export interface TipoMedidor {
  id: string
  created_at: string
  updated_at: string
  version_hash: string | null
  prestador_id: string | null
  tenant_id: string | null
  nombre: string
  unidad: string
  categoria: CategoriaMedidor
  descripcion: string
  permite_estimacion: boolean
  decimales: number
  requiere_foto: boolean
  factor_salto_maximo: string
  activo: boolean
}

export interface TipoMedidorEntrada {
  nombre: string
  unidad: string
  categoria: CategoriaMedidor
  descripcion?: string
  permite_estimacion?: boolean
  decimales?: number
  requiere_foto?: boolean
  factor_salto_maximo?: string
  global?: boolean
}

export interface Estimacion {
  incremento_por_dia: string
  incremento_real_promedio: string | null
  horario_operacion_json: { dias?: string[]; horas_por_dia?: number }
  activa: boolean
  desde: string
  ultima_estimacion_at: string | null
}

export interface ProximoMantenimiento {
  plan_id: string
  plan: string
  ventana_dias: number
  clave: string
  tipo_trigger: string
  fecha_estimada: string | null
  valor_objetivo: string | null
  valor_actual: string | null
  unidad: string | null
  faltante: string | null
  motivo: string
}

/** Lo que pinta la pestaña «Medidores» de la ficha del equipo. */
export interface MedidorEquipo {
  id: string
  tipo_medidor_id: string
  tipo: string
  unidad: string
  categoria: CategoriaMedidor | null
  decimales: number
  requiere_foto: boolean
  valor_actual: string
  valor_acumulado: string
  valor_ultimo_pm: string
  fecha_ultima_lectura: string | null
  metodo_actualizacion: MetodoMedidor
  valor_maximo: string | null
  numero_serie_medidor: string | null
  instalado_en: string | null
  activo: boolean
  incremento_por_dia: string
  origen_incremento: string
  estimacion: Estimacion | null
  proximos_mantenimientos: ProximoMantenimiento[]
}

export interface MedidorEntrada {
  tipo_medidor_id: string
  valor_inicial?: string
  metodo_actualizacion?: MetodoMedidor
  valor_maximo?: string | null
  numero_serie_medidor?: string | null
  instalado_en?: string | null
}

export interface Lectura {
  id: string
  created_at: string
  updated_at: string
  version_hash: string | null
  equipo_medidor_id: string
  equipo_id: string
  tipo_medidor_id: string
  valor: string
  valor_acumulado: string
  metodo: MetodoMedidor
  registrado_por: string | null
  folio_id: string | null
  evidencia_id: string | null
  timestamp_dispositivo: string | null
  timestamp: string
  estado: EstadoLectura
  motivo: string
  revisada_por: string | null
  revisada_at: string | null
}

export interface ResultadoLectura {
  lectura: Lectura
  duplicada: boolean
  anomalia: string
  folios_generados: { folio_id: string; numero_folio: string; plan: string; fecha_programada: string }[]
}

export interface PendienteRevision {
  id: string
  equipo_id: string
  equipo: string
  equipo_codigo: string
  tenant_id: string
  medidor: string
  unidad: string
  valor: string
  valor_acumulado: string
  metodo: MetodoMedidor
  motivo: string
  timestamp: string
  valor_anterior: string | null
  fecha_anterior: string | null
}

export interface CambioMedidor {
  id: string
  equipo_medidor_id: string
  tipo: TipoCambioMedidor
  valor_anterior: string
  valor_nuevo: string
  acumulado_al_cambio: string
  numero_serie_anterior: string | null
  numero_serie_nuevo: string | null
  motivo: string
  registrado_por: string | null
  timestamp: string
}

export interface EquipoDelOperador {
  equipo_medidor_id: string
  equipo_id: string
  equipo: string
  equipo_codigo: string
  un_id: string
  un_codigo: string
  medidor: string
  unidad: string
  decimales: number
  requiere_foto: boolean
  valor_actual: string
  valor_maximo: string | null
  fecha_ultima_lectura: string | null
}

export interface LlaveApi {
  id: string
  created_at: string
  tenant_id: string
  nombre: string
  prefijo: string
  permisos_json: string[]
  activa: boolean
  creada_por: string | null
  revocada_at: string | null
  ultimo_uso_at: string | null
  usos: number
}

export interface LlaveCreada { llave: LlaveApi; secreto: string }

export interface EventoCatalogo {
  clave: string
  descripcion: string
  parametros_schema_json: Record<string, { tipo: string; default?: unknown; etiqueta?: string; min?: number; max?: number }>
  activo: boolean
}

export interface FilaSimulacion {
  equipo_id: string
  equipo: string
  equipo_codigo: string
  fecha_estimada: string | null
  ultima_ejecucion: string | null
  ultimo_valor_medidor: string | null
  folio_abierto: { id: string; numero_folio: string; estado: string } | null
  triggers: ProximoMantenimiento[]
}

export const ROLES_MEDIDORES: Rol[] = ['superadmin', 'admin_prestador', 'despachador', 'mesa_control', 'admin_empresa', 'admin_un']
export const ROLES_REVISAN_LECTURAS: Rol[] = ['superadmin', 'admin_prestador', 'despachador', 'mesa_control']
export const ROLES_LLAVES_API: Rol[] = ['superadmin', 'admin_empresa']

/** Formatea un valor del medidor con los decimales de su tipo. */
export function formatoValor(valor: string | number | null | undefined, decimales = 0, unidad = ''): string {
  if (valor === null || valor === undefined || valor === '') return '—'
  const n = Number(valor)
  if (Number.isNaN(n)) return String(valor)
  const texto = n.toLocaleString('es-MX', { minimumFractionDigits: decimales, maximumFractionDigits: decimales })
  return unidad ? `${texto} ${unidad}` : texto
}
