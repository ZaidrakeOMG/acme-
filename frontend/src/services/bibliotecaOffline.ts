/**
 * Biblioteca sin conexión del técnico (§6.2 capa 3, §6.10.4, ACT-5.3). F2-01.
 *
 * El paquete de `/api/sync/catalogos` trae **metadatos**; aquí se decide qué archivos se guardan de verdad:
 * - descarga **selectiva**: el técnico elige qué conservar;
 * - descarga automática de los manuales del tipo de equipo de sus folios del día, solo con Wi-Fi (configurable);
 * - aviso de «hay versión nueva» comparando la versión guardada con la del paquete;
 * - tope de almacenamiento con `navigator.storage.estimate()`, avisando **antes** de pasarse.
 *
 * Cada guardado y cada borrado se registra en el servidor; sin señal viaja por la cola de mutaciones de P05.
 */
import { baseLocal, type BibliotecaOffline } from './db'
import { archivoDeManual, registrarDescarga } from './capacitacion'
import { dispositivoId } from './syncEngine'

/** Entrada del paquete de sincronización (metadatos, sin archivo). */
export interface MetadatoBiblioteca {
  clase: 'manual' | 'contenido_servicio'
  id: string
  tipo_equipo_id: string | null
  titulo: string
  categoria?: string
  version: number
  mime?: string | null
  bytes?: number | null
  hash_sha256?: string
  nombre_original?: string
  puntos_revision?: unknown[]
  periodicidad?: string | null
  tiene_archivo?: boolean
  activo: boolean
  de_mis_folios: boolean
}

const CLAVE_TOPE = 'biblioteca.tope_mb'
const CLAVE_AUTO = 'biblioteca.descarga_automatica'
const TOPE_MB_DEFAULT = 200

export const clave = (m: { clase: string; id: string }) => `${m.clase}:${m.id}`

export async function topeMb(): Promise<number> {
  const v = (await baseLocal.metadatos.get(CLAVE_TOPE))?.valor
  return typeof v === 'number' ? v : TOPE_MB_DEFAULT
}

export async function fijarTopeMb(mb: number): Promise<void> {
  await baseLocal.metadatos.put({ clave: CLAVE_TOPE, valor: Math.max(10, Math.min(2000, Math.round(mb))),
                                  actualizado: new Date().toISOString() })
}

export async function descargaAutomatica(): Promise<boolean> {
  return (await baseLocal.metadatos.get(CLAVE_AUTO))?.valor !== false
}

export async function fijarDescargaAutomatica(activa: boolean): Promise<void> {
  await baseLocal.metadatos.put({ clave: CLAVE_AUTO, valor: activa, actualizado: new Date().toISOString() })
}

/** Lo guardado en el dispositivo, con lo desactualizado primero. */
export async function guardados(): Promise<BibliotecaOffline[]> {
  const todos = await baseLocal.biblioteca_offline.toArray()
  return todos.sort((a, b) => Number(b.desactualizado) - Number(a.desactualizado) || a.titulo.localeCompare(b.titulo))
}

export async function espacioUsado(): Promise<number> {
  return (await baseLocal.biblioteca_offline.toArray()).reduce((suma, x) => suma + (x.bytes || 0), 0)
}

export interface EspacioDisponible {
  usadoBytes: number
  topeBytes: number
  cuotaBytes: number | null
  /** Lo que el navegador dice que ya ocupa todo el sitio, no solo la biblioteca. */
  sitioBytes: number | null
}

export async function espacio(): Promise<EspacioDisponible> {
  const [usadoBytes, tope] = [await espacioUsado(), await topeMb()]
  let cuotaBytes: number | null = null
  let sitioBytes: number | null = null
  try {
    const est = await navigator.storage?.estimate?.()
    cuotaBytes = est?.quota ?? null
    sitioBytes = est?.usage ?? null
  } catch {
    /* el navegador no expone la cuota: se usa solo el tope propio */
  }
  return { usadoBytes, topeBytes: tope * 1_000_000, cuotaBytes, sitioBytes }
}

export class SinEspacio extends Error {
  constructor(public readonly faltanBytes: number) {
    super('No hay espacio suficiente para guardar este archivo')
  }
}

/** ¿Cabe `bytes` sin pasar el tope propio ni la cuota del navegador? */
export async function cabe(bytes: number): Promise<boolean> {
  const e = await espacio()
  if (e.usadoBytes + bytes > e.topeBytes) return false
  if (e.cuotaBytes !== null && e.sitioBytes !== null && e.sitioBytes + bytes > e.cuotaBytes * 0.9) return false
  return true
}

/** Guarda un manual en el dispositivo. Lanza `SinEspacio` si no cabe, antes de descargar nada. */
export async function guardarManual(m: MetadatoBiblioteca): Promise<BibliotecaOffline> {
  const estimado = m.bytes ?? 0
  if (estimado && !(await cabe(estimado))) {
    const e = await espacio()
    throw new SinEspacio(e.usadoBytes + estimado - e.topeBytes)
  }
  const { blob } = await archivoDeManual(m.id, m.version)
  const fila: BibliotecaOffline = {
    clave: clave(m), clase: 'manual', id: m.id, titulo: m.titulo, tipo_equipo_id: m.tipo_equipo_id,
    categoria: m.categoria ?? null, version: m.version, mime: m.mime ?? blob.type ?? null,
    bytes: blob.size, archivo: blob, puntos_revision: null, descargado: new Date().toISOString(),
    desactualizado: false,
  }
  await baseLocal.biblioteca_offline.put(fila)
  await avisarAlServidor({ manual_id: m.id, version: m.version, en_dispositivo: true })
  return fila
}

/** El contenido de servicio se guarda por sus puntos de revisión: es lo que el técnico necesita en sitio. */
export async function guardarContenido(m: MetadatoBiblioteca): Promise<BibliotecaOffline> {
  const puntos = m.puntos_revision ?? []
  const fila: BibliotecaOffline = {
    clave: clave(m), clase: 'contenido_servicio', id: m.id, titulo: m.titulo, tipo_equipo_id: m.tipo_equipo_id,
    categoria: null, version: m.version, mime: null,
    bytes: new Blob([JSON.stringify(puntos)]).size, archivo: null, puntos_revision: puntos,
    descargado: new Date().toISOString(), desactualizado: false,
  }
  await baseLocal.biblioteca_offline.put(fila)
  await avisarAlServidor({ contenido_id: m.id, version: m.version, en_dispositivo: true })
  return fila
}

export async function borrar(c: string): Promise<void> {
  const fila = await baseLocal.biblioteca_offline.get(c)
  await baseLocal.biblioteca_offline.delete(c)
  if (fila) {
    await avisarAlServidor(fila.clase === 'manual'
      ? { manual_id: fila.id, version: fila.version, en_dispositivo: false }
      : { contenido_id: fila.id, version: fila.version, en_dispositivo: false })
  }
}

/** El registro no debe tumbar la operación del técnico: sin red se intentará en la siguiente sincronización. */
async function avisarAlServidor(datos: { manual_id?: string; contenido_id?: string; version: number
                                         en_dispositivo: boolean }): Promise<void> {
  try {
    await registrarDescarga({ ...datos, dispositivo_id: dispositivoId() })
  } catch {
    /* sin señal: queda solo en el dispositivo y se registra cuando vuelva la red */
  }
}

/**
 * Compara lo guardado con el paquete del servidor: marca lo desactualizado, retira lo que se dio de baja y, si la
 * descarga automática está activa y hay Wi-Fi, guarda los manuales de los folios del día.
 */
export async function conciliar(paquete: MetadatoBiblioteca[]): Promise<{
  desactualizados: number; retirados: number; descargados: number
}> {
  const resumen = { desactualizados: 0, retirados: 0, descargados: 0 }
  const porClave = new Map(paquete.map((m) => [clave(m), m]))
  for (const fila of await baseLocal.biblioteca_offline.toArray()) {
    const m = porClave.get(fila.clave)
    if (m && !m.activo) {
      await baseLocal.biblioteca_offline.delete(fila.clave)
      resumen.retirados += 1
      continue
    }
    if (m && m.version > fila.version && !fila.desactualizado) {
      await baseLocal.biblioteca_offline.update(fila.clave, { desactualizado: true })
      resumen.desactualizados += 1
    }
  }
  if (await descargaAutomatica() && enWifi()) {
    for (const m of paquete) {
      if (!m.activo || !m.de_mis_folios || m.clase !== 'manual') continue
      const existente = await baseLocal.biblioteca_offline.get(clave(m))
      if (existente && existente.version >= m.version) continue
      try {
        await guardarManual(m)
        resumen.descargados += 1
      } catch {
        break   // sin espacio o sin red: no se insiste con el resto
      }
    }
  }
  return resumen
}

/**
 * ¿Hay Wi-Fi? `navigator.connection` no está en todos los navegadores: cuando no se puede saber, se asume que sí,
 * porque la alternativa (no descargar nunca) deja al técnico sin manuales en sitio.
 */
export function enWifi(): boolean {
  const conexion = (navigator as { connection?: { type?: string; effectiveType?: string; saveData?: boolean } }).connection
  if (!conexion) return true
  if (conexion.saveData) return false
  if (conexion.type) return conexion.type === 'wifi' || conexion.type === 'ethernet'
  return conexion.effectiveType === '4g'   // sin tipo, al menos no descargar en 2G/3G
}

/** Los puntos de revisión guardados para un tipo de equipo, para la atención sin señal. */
export async function puntosGuardados(tipoEquipoId: string): Promise<unknown[] | null> {
  const filas = await baseLocal.biblioteca_offline.where('clase').equals('contenido_servicio').toArray()
  return filas.find((f) => f.tipo_equipo_id === tipoEquipoId)?.puntos_revision ?? null
}
