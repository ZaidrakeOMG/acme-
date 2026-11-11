/**
 * Servicios de las apps de campo (P05): folios con respaldo offline, firma, encuesta, refacciones, catálogos cacheados y
 * suscripción push.
 */
import { api, mensajeDeError } from './api'
import { baseLocal } from './db'
import { capturarFolio, listarFolios, obtenerFolio } from './folios'
import { equiposConMedidorDelOperador, registrarLectura } from './medidores'
import { conRespaldoOffline, dispositivoId, esSinConexion, nuevoIdCliente, syncEngine } from './syncEngine'
import type { EstadoFolio, FolioDetalle, FolioEntrada, FolioResumen } from '../types/folios'
import type { EquipoDelOperador } from '../types/medidores'

export type FolioLocal = FolioResumen & { pendiente?: boolean; id_cliente?: string }

/** Captura con respaldo offline: devuelve el folio del servidor o un marcador local `pendiente` con su id_cliente. */
export async function capturarFolioCampo(datos: FolioEntrada): Promise<FolioLocal> {
  const idCliente = nuevoIdCliente()
  const { valor } = await conRespaldoOffline(() => capturarFolio(datos), 'crear_folio', datos as unknown as Record<string, unknown>, `Folio capturado sin conexión (${datos.descripcion.slice(0, 40)})`, idCliente)
  if (valor) return valor
  const ahora = new Date().toISOString()
  const marcador: FolioLocal = {
    id: idCliente, id_cliente: idCliente, pendiente: true, created_at: ahora, updated_at: ahora, version_hash: null, numero_folio: 'PENDIENTE', tenant_id: '', prestador_id: '',
    un_id: datos.un_id, un_nombre: null, un_codigo: null, equipo_id: datos.equipo_id, equipo_codigo: null, equipo_nombre: null, tipo_falla_id: datos.tipo_falla_id, tipo_falla: null,
    tipo_folio: datos.tipo_folio ?? 'correctivo', estado: 'capturado', prioridad: 0, descripcion: datos.descripcion, tecnico_id: null, tecnico_nombre: null, severidad: null,
    severidad_origen: 'automatica_matriz', confirmacion_un: datos.confirmacion_un, monto_estimado: null, criticidad: null, capturado_por: '', capturado_por_nombre: null,
    capturado_at: ahora, fecha_falla: ahora, fecha_inicio_atencion: null, fecha_cierre: null, razon_cancelacion: null, flujo: null, triggers_pendientes: 0, antiguedad_horas: 0,
  }
  await baseLocal.folios_cache.put({ id: idCliente, numero_folio: 'PENDIENTE', estado: 'capturado', un_id: datos.un_id, tecnico_id: null, updated_at: ahora, datos: marcador as unknown as Record<string, unknown> })
  return marcador
}

/** Transición desde campo (en camino, llegada, pendiente de refacción, reanudar, cerrar) con cola offline y hora real. */
export async function transicionCampo(folioId: string, ruta: string, estado: EstadoFolio, cuerpo: Record<string, unknown> = {}, descripcion = ''): Promise<{ folio: FolioResumen | null; encolada: boolean }> {
  const { valor, encolada } = await conRespaldoOffline(
    () => api<FolioResumen>(`/folios/${folioId}/${ruta}`, { metodo: 'POST', cuerpo }),
    'transicion', { folio_id: folioId, estado, notas: (cuerpo.notas as string) ?? '', contexto: { geolat: cuerpo.geolat ?? null, geolng: cuerpo.geolng ?? null } },
    descripcion || `Folio: ${estado}`,
  )
  if (!valor && encolada) {
    const cache = await baseLocal.folios_cache.get(folioId)
    if (cache) await baseLocal.folios_cache.put({ ...cache, estado, datos: { ...cache.datos, estado, pendiente: true } })
  }
  return { folio: valor, encolada: !!encolada }
}

export async function agregarRefaccionCampo(folioId: string, datos: { descripcion: string; cantidad: number; origen: 'almacen' | 'oc' | 'caja_chica'; costo_unitario?: number }) {
  return conRespaldoOffline(() => api(`/folios/${folioId}/refacciones`, { metodo: 'POST', cuerpo: datos }), 'agregar_refaccion', { folio_id: folioId, ...datos }, `Refacción: ${datos.descripcion}`)
}

export async function vincularAtencion(folioId: string, respuestaId: string) {
  return api(`/folios/${folioId}/atencion`, { metodo: 'POST', cuerpo: { respuesta_id: respuestaId } })
}

/** Folios para la app: del servidor y, sin red, de la caché local (incluidos los capturados sin conexión). */
export async function foliosCampo(params: Record<string, string | undefined> = {}): Promise<FolioLocal[]> {
  try {
    const lista = await listarFolios(params)
    await baseLocal.folios_cache.bulkPut(lista.map((f) => ({ id: f.id, numero_folio: f.numero_folio, estado: f.estado, un_id: f.un_id, tecnico_id: f.tecnico_id, updated_at: f.updated_at, datos: f as unknown as Record<string, unknown> })))
    const pendientes = (await baseLocal.folios_cache.toArray()).filter((c) => (c.datos as unknown as FolioLocal).pendiente).map((c) => c.datos as unknown as FolioLocal)
    return [...pendientes, ...lista]
  } catch (e) {
    if (!esSinConexion(e) && syncEngine.enLinea()) throw e
    return (await baseLocal.folios_cache.toArray()).map((c) => c.datos as unknown as FolioLocal).sort((a, b) => b.capturado_at.localeCompare(a.capturado_at))
  }
}

export async function folioCampo(folioId: string): Promise<FolioDetalle | null> {
  try {
    const d = await obtenerFolio(folioId)
    await baseLocal.folios_cache.put({ id: d.folio.id, numero_folio: d.folio.numero_folio, estado: d.folio.estado, un_id: d.folio.un_id, tecnico_id: d.folio.tecnico_id, updated_at: d.folio.updated_at, datos: { ...d.folio, detalle: d } as unknown as Record<string, unknown> })
    return d
  } catch (e) {
    if (!esSinConexion(e) && syncEngine.enLinea()) throw e
    const cache = await baseLocal.folios_cache.get(folioId)
    if (!cache) return null
    const datos = cache.datos as unknown as FolioLocal & { detalle?: FolioDetalle }
    if (datos.detalle) return { ...datos.detalle, folio: { ...datos.detalle.folio, estado: datos.estado as EstadoFolio } }
    return { folio: datos, captura: { capturado_por: '', capturado_por_nombre: null, capturado_at: datos.capturado_at, un: { id: datos.un_id }, equipo: { id: datos.equipo_id }, tipo_falla: null, descripcion: datos.descripcion, geolat_captura: null, geolng_captura: null, confirmacion_un: datos.confirmacion_un, confirmacion_un_timestamp: null, confirmacion_un_geolat: null, confirmacion_un_geolng: null, folio_duplicado_justificacion: null, folio_duplicado_ref_id: null, folio_duplicado_ref_numero: null },
             formulario_captura: null, asignacion: { tecnico_id: null, tecnico_nombre: null, asignado_at: null, vehiculo: null, orden_en_ruta: null, ventana_inicio: null, ventana_fin: null }, historial: [], reasignaciones: [], hallazgos: [], derivaciones: [], clasificacion: null, evidencias: [], formulario_atencion: null, refacciones: [], sla: null, encuesta: null, triggers_revision: [], aprobacion: null, decisiones: [], chat: [], financiero: {}, acciones: [], puede_aprobar: false }
  }
}

// -------------------------------------------------------------- cierre

export async function firmarFolio(folioId: string, imagen: Blob, geo: { lat: number; lng: number } | null) {
  const f = new FormData()
  f.append('archivo', imagen, 'firma.png')
  if (geo) { f.append('geolat', String(geo.lat)); f.append('geolng', String(geo.lng)) }
  f.append('timestamp_dispositivo', new Date().toISOString())
  return api<{ id: string; tipo: string }>(`/folios/${folioId}/firma`, { metodo: 'POST', formulario: f })
}

export const encuestaDisponible = (folioId: string) => api<{ disponible: boolean; motivo: string | null }>(`/folios/${folioId}/encuesta/disponible`)
export const responderEncuesta = (folioId: string, nps: number, comentario: string, sugerencia = '') =>
  api<{ nps_score: number }>(`/folios/${folioId}/encuesta`, { metodo: 'POST', cuerpo: { nps_score: nps, comentario, respuestas: sugerencia ? { sugerencia } : {}, timestamp_dispositivo: new Date().toISOString() } })

// ---------------------------------------------------------- catálogos

export async function catalogoCampo<T = Record<string, unknown>>(entidad: string, cargarEnLinea: () => Promise<T[]>): Promise<T[]> {
  if (syncEngine.enLinea()) {
    try {
      return await cargarEnLinea()
    } catch (e) {
      if (!esSinConexion(e)) throw e
    }
  }
  return syncEngine.catalogo<T>(entidad)
}

// --------------------------------------------------------------- push

function base64ABytes(b64: string): Uint8Array {
  const relleno = '='.repeat((4 - (b64.length % 4)) % 4)
  const binario = atob((b64 + relleno).replace(/-/g, '+').replace(/_/g, '/'))
  return Uint8Array.from(binario, (c) => c.charCodeAt(0))
}

/** Registra la suscripción push del dispositivo (PushManager) si el navegador y el servidor lo permiten. */
export async function registrarPush(): Promise<'registrada' | 'sin_soporte' | 'sin_permiso' | 'deshabilitado' | 'error'> {
  if (typeof navigator === 'undefined' || !('serviceWorker' in navigator) || !('PushManager' in window)) return 'sin_soporte'
  try {
    const { clave_publica, habilitado } = await api<{ clave_publica: string | null; habilitado: boolean }>('/push/clave-publica')
    if (!habilitado || !clave_publica) return 'deshabilitado'
    if (typeof Notification !== 'undefined' && Notification.permission === 'denied') return 'sin_permiso'
    const registro = await navigator.serviceWorker.ready
    const sub = (await registro.pushManager.getSubscription()) ?? (await registro.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: base64ABytes(clave_publica) as BufferSource }))
    const json = sub.toJSON()
    await api('/push/suscripcion', { metodo: 'POST', cuerpo: { endpoint: json.endpoint, keys: json.keys ?? {}, dispositivo_id: dispositivoId() } })
    return 'registrada'
  } catch (e) {
    console.info('Push no registrado:', mensajeDeError(e))
    return 'error'
  }
}

// -------------------------------------------------- medidores (F2-04, §6.9.2)

/** Equipos de la unidad del operador con medidor que él lee. Con señal, del servidor; sin señal, del caché. */
export async function medidoresDelOperador(): Promise<EquipoDelOperador[]> {
  return catalogoCampo<EquipoDelOperador>('medidores', () => equiposConMedidorDelOperador())
}

/**
 * Registra la lectura del marcador con respaldo sin señal. Devuelve el resultado del servidor, o `null` con la
 * mutación encolada: la cola la aplica con la hora del dispositivo, que es la que vale para el acumulado y para
 * detectar saltos (§6.2).
 */
export async function registrarLecturaCampo(equipoMedidorId: string, valor: string, etiqueta: string) {
  return conRespaldoOffline(
    () => registrarLectura({ equipo_medidor_id: equipoMedidorId, valor }),
    'registrar_lectura',
    { equipo_medidor_id: equipoMedidorId, valor },
    `Lectura de ${etiqueta}: ${valor}`,
  )
}
