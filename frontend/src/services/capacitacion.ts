/** Cliente de /api/capacitacion y /api/biblioteca (F2-01). */
import type {
  AlertasCapacitacion, ApoyoDeFolio, ContenidoGuardado, ContenidoServicio, Curso, DescargaOffline, EnlaceDescarga, Expediente,
  Manual, PuntoRevision, TecnicoDelCliente, Vencimiento, VersionManual,
} from '../types/capacitacion'
import { api, descargar } from './api'

type Params = Record<string, string | number | boolean | null | undefined>

// ------------------------------------------------------------------ capacitación
export const listarCursos = (params: Params = {}) => api<Curso[]>('/capacitacion/cursos', { params })
export const crearCurso = (datos: Partial<Curso> & { nombre: string; global?: boolean }) =>
  api<Curso>('/capacitacion/cursos', { metodo: 'POST', cuerpo: datos })
export const editarCurso = (id: string, cambios: Partial<Curso>) =>
  api<Curso>(`/capacitacion/cursos/${id}`, { metodo: 'PUT', cuerpo: cambios })

export const expedienteDe = (tecnicoId: string) =>
  api<Expediente>(`/capacitacion/tecnicos/${tecnicoId}/expediente`)
export const vencimientos = (dias?: number) =>
  api<Vencimiento[]>('/capacitacion/vencimientos', { params: { dias } })
export const tecnicosDeMisUnidades = () =>
  api<TecnicoDelCliente[]>('/capacitacion/tecnicos-de-mis-unidades')

export const alertasCapacitacion = () => api<AlertasCapacitacion>('/capacitacion/alertas/configuracion')
export const guardarAlertasCapacitacion = (cambios: Partial<AlertasCapacitacion>) =>
  api<AlertasCapacitacion>('/capacitacion/alertas/configuracion', { metodo: 'PUT', cuerpo: cambios })

/** Registro del curso: multipart, con la constancia opcional. */
export function registrarCurso(tecnicoId: string, datos: Record<string, string>, certificado?: File | null) {
  const formulario = new FormData()
  for (const [k, v] of Object.entries(datos)) if (v !== '') formulario.append(k, v)
  if (certificado) formulario.append('certificado', certificado)
  return api<Expediente>(`/capacitacion/tecnicos/${tecnicoId}/cursos`, { metodo: 'POST', formulario })
}

export const constancia = (tecnicoId: string, tecnicoCursoId: string) =>
  descargar(`/capacitacion/tecnicos/${tecnicoId}/certificado/${tecnicoCursoId}`)
export const expedienteArchivo = (tecnicoId: string, formato: 'xlsx' | 'pdf') =>
  descargar(`/capacitacion/tecnicos/${tecnicoId}/expediente.${formato}`)

// ------------------------------------------------------------------ biblioteca
export const listarManuales = (params: Params = {}) => api<Manual[]>('/biblioteca/manuales', { params })
export const versionesDeManual = (id: string) => api<VersionManual[]>(`/biblioteca/manuales/${id}/versiones`)
export const desactivarManual = (id: string) =>
  api<{ mensaje: string }>(`/biblioteca/manuales/${id}`, { metodo: 'DELETE' })

export function subirManual(datos: { tipo_equipo_id: string; titulo: string; categoria: string; descripcion: string },
                            archivo: File) {
  const formulario = new FormData()
  for (const [k, v] of Object.entries(datos)) formulario.append(k, v)
  formulario.append('archivo', archivo)
  return api<Manual>('/biblioteca/manuales', { metodo: 'POST', formulario })
}

export function subirVersion(manualId: string, archivo: File, notas: string) {
  const formulario = new FormData()
  formulario.append('archivo', archivo)
  formulario.append('notas', notas)
  return api<Manual>(`/biblioteca/manuales/${manualId}/versiones`, { metodo: 'POST', formulario })
}

export const enlaceManual = (id: string, version?: number) =>
  api<EnlaceDescarga>(`/biblioteca/manuales/${id}/enlace`, { params: { version } })
export const enlaceContenido = (id: string) =>
  api<EnlaceDescarga>(`/biblioteca/contenido/${id}/enlace`)

export const listarContenido = (params: Params = {}) =>
  api<ContenidoServicio[]>('/biblioteca/contenido', { params })
export const guardarContenido = (datos: {
  tipo_equipo_id: string; contrato_id: string; titulo: string; puntos_revision: PuntoRevision[]
  periodicidad?: string | null; correctivos_iguala?: number | null
  preventivos_iguala?: Record<string, unknown> | null
}) => api<ContenidoGuardado>('/biblioteca/contenido', { metodo: 'POST', cuerpo: datos })

// ------------------------------------------------------------------ uso sin señal
export const misDescargas = () => api<DescargaOffline[]>('/biblioteca/offline')
export const registrarDescarga = (datos: {
  manual_id?: string; contenido_id?: string; version: number; dispositivo_id?: string | null
  en_dispositivo?: boolean
}) => api<{ mensaje: string }>('/biblioteca/offline', { metodo: 'POST', cuerpo: datos })

/**
 * Trae el archivo del manual con su enlace firmado. Se usa tanto para el visor como para guardarlo sin señal:
 * el enlace no lleva cabecera de autorización, así que `fetch` directo basta y el blob se puede guardar en Dexie.
 */
export async function archivoDeManual(id: string, version?: number): Promise<{ blob: Blob; nombre: string }> {
  const enlace = await enlaceManual(id, version)
  const respuesta = await fetch(enlace.url)
  if (!respuesta.ok) throw new Error('No se pudo descargar el manual')
  return { blob: await respuesta.blob(), nombre: enlace.nombre }
}

/** Puntos de revisión del contrato y manuales del tipo de equipo del folio, en una sola llamada. */
export const apoyoDeFolio = (folioId: string) => api<ApoyoDeFolio>(`/biblioteca/folios/${folioId}/apoyo`)
