/** Tipos de capacitación y biblioteca (§6.10.3, §6.10.4). F2-01. */
import type { Rol } from './api'

export type TipoCurso = 'curso' | 'certificacion'
export type EstadoCurso = 'vigente' | 'por_vencer' | 'vencido' | 'sin_vigencia'
export type CategoriaManual = 'ficha_tecnica' | 'procedimiento' | 'diagrama' | 'refacciones' | 'otro'

/** Texto además del color: el semáforo nunca se queda solo en el color (accesibilidad). */
export const NOMBRE_ESTADO: Record<EstadoCurso, string> = {
  vigente: 'Vigente',
  por_vencer: 'Por vencer',
  vencido: 'Vencida',
  sin_vigencia: 'No caduca',
}

export const COLOR_ESTADO: Record<EstadoCurso, string> = {
  vigente: 'bg-green-50 text-green-800 border-green-200',
  por_vencer: 'bg-amber-50 text-amber-900 border-amber-200',
  vencido: 'bg-red-50 text-red-800 border-red-200',
  sin_vigencia: 'bg-slate-50 text-slate-700 border-slate-200',
}

export const NOMBRE_CATEGORIA: Record<CategoriaManual, string> = {
  ficha_tecnica: 'Ficha técnica',
  procedimiento: 'Procedimiento',
  diagrama: 'Diagrama',
  refacciones: 'Refacciones',
  otro: 'Otro',
}

export interface Curso {
  id: string
  prestador_id: string | null
  nombre: string
  proveedor: string | null
  duracion_horas: string | null
  vigencia_meses: number | null
  habilidad_id: string | null
  tipo: TipoCurso
  norma_referencia: string | null
  descripcion: string
  activo: boolean
}

export interface CursoDeTecnico {
  id: string
  curso_id: string
  curso: string
  tipo: string | null
  proveedor: string | null
  norma_referencia: string | null
  fecha_inicio: string | null
  fecha_fin: string
  calificacion: string | null
  aprobado: boolean
  folio_constancia: string | null
  vigente_hasta: string | null
  estado: EstadoCurso
  dias_para_vencer: number | null
  tiene_certificado: boolean
  notas: string
  habilidad: string | null
}

export interface HabilidadDerivada {
  habilidad_id: string
  habilidad: string
  clave: string
  certificada: boolean
  origen: 'manual' | 'curso'
  fecha_certificacion: string | null
  vigencia_hasta: string | null
  estado: EstadoCurso
}

export interface Expediente {
  tecnico_id: string
  tecnico_nombre: string
  numero_empleado: string | null
  dias_anticipacion: number
  cursos: CursoDeTecnico[]
  habilidades: HabilidadDerivada[]
}

export interface Vencimiento {
  tecnico_curso_id: string
  tecnico_id: string
  tecnico_nombre: string
  curso: string
  tipo: string
  norma_referencia: string | null
  vigente_hasta: string
  dias: number
  estado: EstadoCurso
  habilidad_id: string | null
}

export interface CertificacionDelCliente {
  nombre: string
  tipo: string
  norma_referencia: string | null
  proveedor: string | null
  vigente_hasta: string | null
  vigencia: string
}

export interface TecnicoDelCliente {
  tecnico_id: string
  nombre: string
  certificaciones: CertificacionDelCliente[]
}

export interface AlertasCapacitacion {
  prestador_id: string
  dias_anticipacion: number
  notificar_cliente: boolean
  activa: boolean
}

// ------------------------------------------------------------------ biblioteca
export interface Manual {
  id: string
  tipo_equipo_id: string
  tipo_equipo: string
  titulo: string
  categoria: CategoriaManual
  descripcion: string
  version: number
  fecha_subida: string
  nombre_original: string
  mime: string
  bytes: number
  hash_sha256: string
  updated_at: string | null
}

export interface VersionManual {
  id: string
  manual_id: string
  version_anterior: number
  nombre_original_anterior: string | null
  bytes_anterior: number | null
  hash_sha256_anterior: string | null
  reemplazado_en: string
  reemplazado_por: string | null
  notas_version: string
}

export interface PuntoRevision {
  orden?: number
  clave?: string | null
  descripcion: string
  obligatorio: boolean
}

export interface ContenidoServicio {
  id: string
  tenant_id: string
  tipo_equipo_id: string
  tipo_equipo: string
  contrato_id: string
  titulo: string
  puntos_revision: PuntoRevision[]
  periodicidad: string | null
  correctivos_iguala: number | null
  preventivos_iguala: Record<string, unknown>
  version: number
  activo: boolean
  tiene_archivo: boolean
  updated_at: string | null
}

export interface ContenidoGuardado {
  contenido: ContenidoServicio
  /** §6.10.4 + P10: diferencias con la iguala del contrato. Avisan, no bloquean. */
  avisos: string[]
}

export interface EnlaceDescarga {
  url: string
  expira_en_segundos: number
  nombre: string
  mime: string
}

export interface DescargaOffline {
  tipo: 'manual' | 'contenido_servicio'
  id: string
  titulo: string
  bytes: number | null
  version_descargada: number
  version_vigente: number
  desactualizado: boolean
  activo: boolean
  fecha_descarga: string
  dispositivo_id: string | null
}

export const ROLES_CAPACITACION: Rol[] = ['superadmin', 'admin_prestador', 'mesa_control', 'despachador']
export const ROLES_GESTIONAN_CAPACITACION: Rol[] = ['superadmin', 'admin_prestador']
export const ROLES_VISTA_CLIENTE: Rol[] = ['superadmin', 'admin_empresa', 'admin_un']
export const ROLES_GESTIONAN_MANUALES: Rol[] = ['superadmin', 'admin_prestador']
export const ROLES_GESTIONAN_CONTENIDO: Rol[] = ['superadmin', 'admin_empresa']

/** Apoyo documental de un folio para la app del técnico (§6.10.4). */
export interface ApoyoDeFolio {
  folio_id: string
  tipo_equipo_id: string
  contenido: { id: string; titulo: string; puntos_revision: PuntoRevision[]; periodicidad: string | null; version: number } | null
  manuales: Manual[]
}
