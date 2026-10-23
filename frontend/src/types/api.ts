export type Rol =
  | 'superadmin'
  | 'admin_prestador'
  | 'direccion_prestador'
  | 'mesa_control'
  | 'despachador'
  | 'supervisor_prestador'
  | 'tecnico'
  | 'admin_empresa'
  | 'admin_un'
  | 'supervisor_operadores'
  | 'operador'

export type Dominio = 'tenant' | 'prestador' | 'plataforma'
export type EstadoRegistro = 'activo' | 'inactivo' | 'suspendido'
export type NivelSeveridad = 'muy_baja' | 'baja' | 'media' | 'alta' | 'critica'

export interface ErrorEstandar {
  codigo: string
  mensaje: string
  detalles: unknown[]
}

export interface Tokens {
  access_token: string
  refresh_token: string
  token_type: string
  expira_en: number
}

export interface Perfil {
  id: string
  email: string
  nombre: string
  telefono: string | null
  rol: Rol
  dominio: Dominio
  tenant_id: string | null
  prestador_id: string | null
  mfa_habilitado: boolean
  mfa_obligatorio: boolean
}

export interface Tema {
  color_primario: string
  color_acento: string
  prestador: string | null
}

export interface PerfilConTema extends Perfil {
  tema: Tema
}

export interface LoginSalida {
  mfa_requerido: boolean
  mfa_enrolamiento_requerido: boolean
  token_mfa: string | null
  tokens: Tokens | null
  usuario: Perfil | null
}

export interface MfaSetupSalida {
  secreto: string
  uri: string
  qr_svg: string
}

export interface MfaVerificarSalida {
  tokens: Tokens | null
  usuario: Perfil | null
  codigos_recuperacion: string[] | null
}

interface ConVersion {
  id: string
  created_at: string
  updated_at: string
  version_hash: string | null
}

export interface Usuario extends ConVersion {
  email: string
  nombre: string
  telefono: string | null
  rol: Rol
  dominio: Dominio
  tenant_id: string | null
  prestador_id: string | null
  estado: EstadoRegistro
  mfa_habilitado: boolean
  ultimo_acceso_at: string | null
}

export interface Tenant extends ConVersion {
  razon_social: string
  rfc: string
  pais: string
  moneda: string
  zona_horaria: string
  estado: EstadoRegistro
}

export interface DatosFiscales {
  regimen_fiscal?: string | null
  codigo_postal?: string | null
  domicilio_fiscal?: string | null
  correo_facturacion?: string | null
}

export interface Prestador extends ConVersion {
  razon_social: string
  rfc: string
  pais: string
  logo_key: string | null
  color_primario: string
  color_acento: string
  estado: EstadoRegistro
  datos_fiscales: DatosFiscales | null
}

export interface Coordenadas {
  lat: number
  lng: number
}

export interface UnidadNegocio extends ConVersion {
  tenant_id: string
  nombre: string
  codigo: string
  direccion: string
  ubicacion: Coordenadas | null
  zona_horaria: string
  estado: EstadoRegistro
  grupo_id: string | null
}

export interface GrupoUN extends ConVersion {
  tenant_id: string
  nombre: string
  descripcion: string
  responsable_id: string | null
  estado: EstadoRegistro
  unidad_ids: string[]
  supervisor_ids: string[]
}

export interface SLA {
  nivel_severidad: NivelSeveridad
  tiempo_respuesta_horas: number
  tiempo_resolucion_horas: number
  unidad_expresion: 'horas' | 'dias' | 'semanas' | 'meses'
  penalizacion_tipo: 'monto' | 'porcentaje'
  penalizacion_valor: string | number
}

export interface Contrato extends ConVersion {
  tenant_id: string
  prestador_id: string
  nombre: string
  modalidad: 'evento' | 'iguala'
  fecha_inicio: string
  fecha_fin: string
  folios_correctivos_iguala: number | null
  penalizacion_tope_porcentaje: string | null
  estado: EstadoRegistro
  slas: SLA[]
}

export interface AlertaEfectiva {
  clave: string
  descripcion: string
  tipo_umbral: string
  umbral_min: string
  umbral_max: string
  umbral_default: string
  umbral_valor: string
  parametros: Record<string, unknown>
  canales: string[]
  destinatarios_roles: string[]
  activa: boolean
  personalizada: boolean
  prompt_origen: string
  modulo_origen: string
}

export interface EventoAuditoria {
  id: string
  created_at: string
  evento_tipo: string
  actor_id: string | null
  actor_rol: string | null
  tenant_id: string | null
  recurso_tipo: string | null
  recurso_id: string | null
  ip_origen: string | null
}

// ------------------------------------------------------------- P02 catálogos

export type EstadoActivo = 'activo' | 'inactivo' | 'baja'

export interface Habilidad {
  id: string
  prestador_id: string
  clave: string
  nombre: string
  descripcion: string
  activa: boolean
}

export interface HabilidadDeTecnico {
  habilidad_id: string
  clave: string
  nombre: string
  certificada: boolean
  fecha_certificacion: string | null
  vigencia_hasta: string | null
  origen: 'manual' | 'curso'
  vigente: boolean
}

export interface Tecnico {
  id: string
  prestador_id: string
  usuario_id: string
  nombre: string
  email: string
  numero_empleado: string | null
  telefono: string | null
  vehiculo_placas: string | null
  estado: EstadoActivo
  fecha_ingreso: string | null
  habilidades: HabilidadDeTecnico[]
  tenants_habilitados: string[]
  grupo_id: string | null
}

export interface GrupoTecnicos {
  id: string
  prestador_id: string
  nombre: string
  descripcion: string
  permisos: Record<string, boolean>
}

export interface PermisoEfectivoTecnico {
  clave: string
  descripcion: string
  habilitado: boolean
  origen: 'override' | 'grupo' | 'prestador' | 'catalogo'
  razon: string | null
}

export interface Severidad {
  id: string
  prestador_id: string
  clave: string
  nombre: string
  orden: number
  color_hex: string
  tiempo_respuesta_horas: number
  tiempo_resolucion_horas: number
  activo: boolean
}

export interface FamiliaEquipo {
  id: string
  tenant_id: string | null
  nombre: string
  descripcion: string
  activa: boolean
  es_global: boolean
}

export interface TipoEquipo {
  id: string
  familia_id: string
  tenant_id: string | null
  nombre: string
  descripcion: string
  activa: boolean
  es_global: boolean
}

export interface Equipo {
  id: string
  tenant_id: string
  un_id: string
  tipo_equipo_id: string
  familia_id: string | null
  codigo: string
  nombre: string
  marca: string | null
  modelo: string | null
  numero_serie: string | null
  fecha_instalacion: string | null
  valor_reposicion: string | null
  estado: EstadoActivo
  garantia_vigente_hasta: string | null
  contrato_id: string | null
  notas: string
  con_contrato_activo: boolean
  en_garantia: boolean
}

export interface TipoFalla {
  id: string
  prestador_id: string
  descripcion: string
  familia_equipo_id: string
  requiere_revision_manual: boolean
  activa: boolean
}

export interface Matriz {
  tenant_id: string
  tipos_falla: { id: string; descripcion: string; familia_equipo_id: string; prestador_id: string }[]
  tipos_equipo: { id: string; nombre: string; familia_id: string; en_uso: boolean }[]
  niveles: { id: string; prestador_id: string; clave: string; nombre: string; orden: number; color_hex: string }[]
  celdas: { tipo_falla_id: string; tipo_equipo_id: string; nivel_severidad_id: string }[]
  faltantes_en_uso: number
}

export interface CatalogoImportable {
  clave: string
  nombre: string
  propietario: 'tenant' | 'prestador'
  columnas: { nombre: string; requerida: boolean; descripcion: string; ejemplo: string }[]
}

export interface ErrorFila {
  fila: number
  columna: string | null
  motivo: string
}

export interface Importacion {
  id: string
  catalogo: string
  archivo_nombre: string
  total_filas: number
  filas_ok: number
  filas_error: number
  errores_json: ErrorFila[]
  duplicados_json: ErrorFila[]
  estado: 'vista_previa' | 'confirmada' | 'cancelada'
  vista_previa: Record<string, unknown>[]
  resultado: { creados: number; actualizados: number } | null
}
