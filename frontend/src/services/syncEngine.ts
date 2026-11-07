/**
 * Motor de sincronización offline (§6.2 capa 3): cola FIFO en IndexedDB con `id_cliente`, reintento exponencial
 * (1 s, 4 s, 16 s, 64 s, 256 s; a los 5 intentos "requiere atención"), envío en orden al lote `/sync/mutaciones`,
 * evidencias en dos pasos, refresco de catálogos al volver en línea y registro local de conflictos. Regla de §6.2:
 * ningún dato crítico de operación se pierde por conectividad.
 */
import { api, ErrorAPI, mensajeDeError } from './api'
import { baseLocal, type EvidenciaPendiente, type MutacionPendiente, type TipoMutacion } from './db'

export const RETRASOS_MS = [1000, 4000, 16000, 64000, 256000]
export const MAX_INTENTOS = RETRASOS_MS.length

export interface EstadoSync {
  enLinea: boolean
  sincronizando: boolean
  pendientes: number
  errores: number
  ultimoSync: string | null
}

type Oyente = (estado: EstadoSync) => void

function uuid(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID()
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => { const r = (Math.random() * 16) | 0; return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16) })
}

export async function sha256Hex(blob: Blob): Promise<string> {
  const buffer = await blob.arrayBuffer()
  if (typeof crypto !== 'undefined' && crypto.subtle) {
    const digest = await crypto.subtle.digest('SHA-256', buffer)
    return Array.from(new Uint8Array(digest)).map((b) => b.toString(16).padStart(2, '0')).join('')
  }
  // Sin WebCrypto (jsdom): hash simple pero determinista; el servidor recalcula el real.
  let h = 0
  for (const b of new Uint8Array(buffer)) h = (h * 31 + b) >>> 0
  return h.toString(16).padStart(64, '0')
}

export function esSinConexion(e: unknown): boolean {
  return e instanceof ErrorAPI && (e.codigo === 'SIN_CONEXION' || e.estado === 0)
}

export function dispositivoId(): string {
  try {
    let id = localStorage.getItem('acma.dispositivo')
    if (!id) {
      id = uuid()
      localStorage.setItem('acma.dispositivo', id)
    }
    return id
  } catch {
    return 'navegador'
  }
}

class MotorSincronizacion {
  private oyentes = new Set<Oyente>()
  private temporizador: ReturnType<typeof setTimeout> | null = null
  private enCurso: Promise<EstadoSync> | null = null
  private iniciado = false
  sincronizando = false
  ultimoSync: string | null = null
  private forzarOffline: boolean | null = null

  enLinea(): boolean {
    if (this.forzarOffline !== null) return !this.forzarOffline
    return typeof navigator === 'undefined' ? true : navigator.onLine
  }

  /** Pruebas y demos: simula sin conexión. */
  simularSinConexion(valor: boolean | null) {
    this.forzarOffline = valor
    void this.notificar()
  }

  iniciar() {
    if (this.iniciado || typeof window === 'undefined') return
    this.iniciado = true
    window.addEventListener('online', () => { void this.alVolverEnLinea() })
    window.addEventListener('offline', () => { void this.notificar() })
    void this.procesar()
  }

  suscribir(oyente: Oyente): () => void {
    this.oyentes.add(oyente)
    void this.resumen().then(oyente)
    return () => this.oyentes.delete(oyente)
  }

  async resumen(): Promise<EstadoSync> {
    const mutaciones = await baseLocal.mutaciones_pendientes.toArray()
    const evidencias = await baseLocal.evidencias_pendientes.toArray()
    const pendientes = mutaciones.filter((m) => m.estado === 'pendiente' || m.estado === 'enviando').length + evidencias.filter((e) => e.estado === 'pendiente').length
    const errores = mutaciones.filter((m) => m.estado === 'atencion' || m.estado === 'rechazada').length + evidencias.filter((e) => e.estado === 'atencion' || e.estado === 'error').length
    return { enLinea: this.enLinea(), sincronizando: this.sincronizando, pendientes, errores, ultimoSync: this.ultimoSync }
  }

  private async notificar() {
    const estado = await this.resumen()
    for (const o of this.oyentes) o(estado)
  }

  // ------------------------------------------------------------- cola
  async encolar(tipo: TipoMutacion, payload: Record<string, unknown>, descripcion: string, opciones: { idCliente?: string; timestampDispositivo?: string } = {}): Promise<MutacionPendiente> {
    const ultimo = await baseLocal.mutaciones_pendientes.orderBy('orden').last()
    const m: MutacionPendiente = {
      id_cliente: opciones.idCliente ?? uuid(), orden: (ultimo?.orden ?? 0) + 1, tipo, payload,
      timestamp_dispositivo: opciones.timestampDispositivo ?? new Date().toISOString(), estado: 'pendiente', intentos: 0,
      proximo_intento: null, ultimo_error: null, resultado: null, descripcion,
    }
    await baseLocal.mutaciones_pendientes.put(m)
    await this.notificar()
    this.programar(0)
    return m
  }

  /** Actualiza el payload de una mutación pendiente (p. ej. el borrador de una respuesta que sigue editándose). */
  async actualizarPendiente(idCliente: string, payload: Record<string, unknown>): Promise<boolean> {
    const m = await baseLocal.mutaciones_pendientes.get(idCliente)
    if (!m || m.estado !== 'pendiente') return false
    await baseLocal.mutaciones_pendientes.update(idCliente, { payload, timestamp_dispositivo: new Date().toISOString() })
    return true
  }

  async encolarEvidencia(e: Omit<EvidenciaPendiente, 'id_cliente' | 'hash_sha256' | 'creado' | 'estado' | 'intentos' | 'ultimo_error'> & { id_cliente?: string }): Promise<EvidenciaPendiente> {
    const fila: EvidenciaPendiente = {
      ...e, id_cliente: e.id_cliente ?? uuid(), hash_sha256: await sha256Hex(e.blob), creado: new Date().toISOString(), estado: 'pendiente', intentos: 0, ultimo_error: null,
    }
    await baseLocal.evidencias_pendientes.put(fila)
    await this.notificar()
    this.programar(0)
    return fila
  }

  async pendientes(): Promise<{ mutaciones: MutacionPendiente[]; evidencias: EvidenciaPendiente[] }> {
    return { mutaciones: await baseLocal.mutaciones_pendientes.orderBy('orden').toArray(), evidencias: await baseLocal.evidencias_pendientes.toArray() }
  }

  async reintentar(idCliente: string) {
    const m = await baseLocal.mutaciones_pendientes.get(idCliente)
    if (m) await baseLocal.mutaciones_pendientes.update(idCliente, { estado: 'pendiente', intentos: 0, proximo_intento: null, ultimo_error: null })
    const e = await baseLocal.evidencias_pendientes.get(idCliente)
    if (e) await baseLocal.evidencias_pendientes.update(idCliente, { estado: 'pendiente', intentos: 0, ultimo_error: null })
    await this.notificar()
    await this.procesar()
  }

  async descartar(idCliente: string) {
    await baseLocal.mutaciones_pendientes.delete(idCliente)
    await baseLocal.evidencias_pendientes.delete(idCliente)
    await this.notificar()
  }

  private programar(ms: number) {
    if (this.temporizador) clearTimeout(this.temporizador)
    this.temporizador = setTimeout(() => { void this.procesar() }, ms)
  }

  private async alVolverEnLinea() {
    await this.procesar()
    try {
      await this.refrescarCatalogos()
    } catch {
      /* sin catálogos nuevos */
    }
  }

  /** Envía en orden todo lo pendiente cuyo reintento ya venció. Una rechazada no detiene a las siguientes. */
  async procesar(): Promise<EstadoSync> {
    if (this.enCurso) return this.enCurso        // una corrida a la vez; quien llama espera a la que está en curso
    if (!this.enLinea()) return this.resumen()
    this.enCurso = this._procesar().finally(() => { this.enCurso = null })
    return this.enCurso
  }

  private async _procesar(): Promise<EstadoSync> {
    this.sincronizando = true
    await this.notificar()
    try {
      const ahora = Date.now()
      const todas = await baseLocal.mutaciones_pendientes.orderBy('orden').toArray()
      const listas = todas.filter((m) => m.estado === 'pendiente' && (!m.proximo_intento || new Date(m.proximo_intento).getTime() <= ahora))
      if (listas.length) {
        await baseLocal.mutaciones_pendientes.bulkPut(listas.map((m) => ({ ...m, estado: 'enviando' as const })))
        try {
          const resultados = await api<{ id_cliente: string; resultado: 'aplicada' | 'duplicada' | 'rechazada'; entidad_id: string | null; codigo: string | null; mensaje: string }[]>(
            '/sync/mutaciones', { metodo: 'POST', cuerpo: { dispositivo_id: dispositivoId(), version_app: '0.5', plataforma: navigator?.userAgent?.slice(0, 60) ?? 'web',
              mutaciones: listas.map((m) => ({ id_cliente: m.id_cliente, tipo: m.tipo, timestamp_dispositivo: m.timestamp_dispositivo, payload: m.payload })) } },
          )
          for (const r of resultados) {
            const m = listas.find((x) => x.id_cliente === r.id_cliente)
            if (!m) continue
            if (r.resultado === 'rechazada') {
              await baseLocal.mutaciones_pendientes.update(m.id_cliente, { estado: 'rechazada', ultimo_error: `${r.codigo ?? ''} ${r.mensaje}`.trim(), resultado: r as unknown as Record<string, unknown> })
            } else {
              await baseLocal.mutaciones_pendientes.update(m.id_cliente, { estado: r.resultado, resultado: r as unknown as Record<string, unknown> })
              if (r.entidad_id) await this.registrarMapa(m.id_cliente, r.entidad_id)
            }
          }
          // Las aplicadas se retiran de la cola; conservamos las rechazadas para que el usuario las vea.
          await baseLocal.mutaciones_pendientes.where('estado').anyOf('aplicada', 'duplicada').delete()
          this.ultimoSync = new Date().toISOString()
        } catch (e) {
          await this.fallo(listas, e)
        }
      }
      await this.subirEvidencias()
    } finally {
      this.sincronizando = false
      await this.notificar()
    }
    return this.resumen()
  }

  private async fallo(lista: MutacionPendiente[], e: unknown) {
    const mensaje = mensajeDeError(e)
    let menor: number | null = null
    for (const m of lista) {
      const intentos = m.intentos + 1
      if (intentos >= MAX_INTENTOS) {
        await baseLocal.mutaciones_pendientes.update(m.id_cliente, { estado: 'atencion', intentos, ultimo_error: mensaje, proximo_intento: null })
      } else {
        const retraso = RETRASOS_MS[intentos - 1]!
        menor = menor === null ? retraso : Math.min(menor, retraso)
        await baseLocal.mutaciones_pendientes.update(m.id_cliente, { estado: 'pendiente', intentos, ultimo_error: mensaje, proximo_intento: new Date(Date.now() + retraso).toISOString() })
      }
    }
    if (menor !== null) this.programar(menor)
  }

  private async subirEvidencias() {
    const pendientes = (await baseLocal.evidencias_pendientes.toArray()).filter((e) => e.estado === 'pendiente')
    for (const e of pendientes) {
      try {
        const respuestaId = (await this.resolverId(e.respuesta_id)) ?? e.respuesta_id
        const inicio = await api<{ estado: 'pendiente' | 'existente' | 'duplicada'; evidencia_id: string | null; subir_a: string | null }>(
          '/sync/evidencias/iniciar', { metodo: 'POST', cuerpo: { id_cliente: e.id_cliente, respuesta_id: respuestaId, campo_clave: e.campo_clave, nombre: e.nombre, mime: e.mime, bytes: e.blob.size, hash_sha256: e.hash_sha256 } },
        )
        if (inicio.estado === 'pendiente' && inicio.subir_a) {
          const f = new FormData()
          f.append('archivo', e.blob, e.nombre)
          f.append('respuesta_id', respuestaId)
          f.append('campo_clave', e.campo_clave)
          f.append('hash_sha256', e.hash_sha256)
          f.append('dispositivo_id', dispositivoId())
          f.append('timestamp_dispositivo', e.creado)
          if (e.etiqueta) f.append('etiqueta', e.etiqueta)
          if (e.geolat != null) f.append('geolat', String(e.geolat))
          if (e.geolng != null) f.append('geolng', String(e.geolng))
          await api(inicio.subir_a.replace(/^\/api/, ''), { metodo: 'PUT', formulario: f })
        }
        await baseLocal.evidencias_pendientes.delete(e.id_cliente)
      } catch (err) {
        const intentos = e.intentos + 1
        if (err instanceof ErrorAPI && err.estado >= 400 && err.estado < 500 && !esSinConexion(err)) {
          await baseLocal.evidencias_pendientes.update(e.id_cliente, { estado: 'error', intentos, ultimo_error: mensajeDeError(err) })
        } else if (intentos >= MAX_INTENTOS) {
          await baseLocal.evidencias_pendientes.update(e.id_cliente, { estado: 'atencion', intentos, ultimo_error: mensajeDeError(err) })
        } else {
          await baseLocal.evidencias_pendientes.update(e.id_cliente, { intentos, ultimo_error: mensajeDeError(err) })
          this.programar(RETRASOS_MS[intentos - 1]!)
          break // sin red: no intentar las demás ahora
        }
      }
    }
  }

  // ------------------------------------------------------- ids locales
  private async registrarMapa(idCliente: string, entidadId: string) {
    const actual = ((await baseLocal.metadatos.get('sync.mapa'))?.valor as Record<string, string> | undefined) ?? {}
    await baseLocal.metadatos.put({ clave: 'sync.mapa', valor: { ...actual, [idCliente]: entidadId }, actualizado: new Date().toISOString() })
  }

  /** Id del servidor para un id_cliente ya sincronizado (o null). */
  async resolverId(idCliente: string): Promise<string | null> {
    const mapa = ((await baseLocal.metadatos.get('sync.mapa'))?.valor as Record<string, string> | undefined) ?? {}
    return mapa[idCliente] ?? null
  }

  // ---------------------------------------------------------- catálogos
  async refrescarCatalogos(): Promise<number> {
    const desde = (await baseLocal.metadatos.get('sync.desde'))?.valor as string | undefined
    const paquete = await api<Record<string, unknown>>('/sync/catalogos', { params: { desde, dispositivo_id: dispositivoId(), version_app: '0.5', plataforma: 'web' } })
    let total = 0
    const entidades = ['unidades', 'equipos', 'familias_equipo', 'tipos_equipo', 'tipos_falla', 'niveles_severidad'] as const
    for (const entidad of entidades) {
      const filas = (paquete[entidad] as Record<string, unknown>[] | undefined) ?? []
      for (const fila of filas) {
        const id = String(fila.id)
        if (fila.activo === false) await baseLocal.catalogos_cache.delete(`${entidad}:${id}`)
        else await baseLocal.catalogos_cache.put({ clave: `${entidad}:${id}`, entidad, id, updated_at: String(fila.updated_at ?? ''), activo: true, datos: fila })
        total += 1
      }
    }
    for (const f of (paquete.formularios as Record<string, unknown>[] | undefined) ?? []) {
      await baseLocal.formularios_cache.put({ id: String(f.id), tipo: String(f.tipo), updated_at: String(f.updated_at ?? ''), datos: f })
      total += 1
    }
    if (paquete.formularios_ids) {
      const vigentes = new Set(paquete.formularios_ids as string[])
      for (const f of await baseLocal.formularios_cache.toArray()) if (!vigentes.has(f.id)) await baseLocal.formularios_cache.delete(f.id)
    }
    for (const f of (paquete.folios as Record<string, unknown>[] | undefined) ?? []) {
      await baseLocal.folios_cache.put({ id: String(f.id), numero_folio: String(f.numero_folio), estado: String(f.estado), un_id: String(f.un_id), tecnico_id: (f.tecnico_id as string | null) ?? null, updated_at: String(f.updated_at ?? ''), datos: f })
      total += 1
    }
    if (paquete.folios_ids) {
      const vigentes = new Set(paquete.folios_ids as string[])
      for (const f of await baseLocal.folios_cache.toArray()) if (!vigentes.has(f.id)) await baseLocal.folios_cache.delete(f.id)
    }
    if (paquete.formulario_por_folio) await baseLocal.metadatos.put({ clave: 'sync.formulario_por_folio', valor: paquete.formulario_por_folio, actualizado: new Date().toISOString() })
    // F2-01: la biblioteca viaja como metadatos; el servicio sin conexión decide qué archivos guardar o retirar.
    // Import dinámico a propósito: `bibliotecaOffline` usa `dispositivoId` de este módulo y así no hay ciclo.
    if (paquete.biblioteca) {
      try {
        const { conciliar } = await import('./bibliotecaOffline')
        const metadatos = paquete.biblioteca as Parameters<typeof conciliar>[0]
        await conciliar(metadatos)
        total += metadatos.length
      } catch {
        /* la biblioteca sin conexión es un extra: no debe tumbar el refresco de catálogos */
      }
    }
    await baseLocal.metadatos.put({ clave: 'sync.desde', valor: paquete.servidor_at, actualizado: new Date().toISOString() })
    return total
  }

  async catalogo<T = Record<string, unknown>>(entidad: string): Promise<T[]> {
    return (await baseLocal.catalogos_cache.where('entidad').equals(entidad).toArray()).map((c) => c.datos as T)
  }
}

export const syncEngine = new MotorSincronizacion()

/** Ejecuta la llamada en línea; sin red, encola la mutación y devuelve `null` (quien llama decide el marcador local). */
export async function conRespaldoOffline<T>(enLinea: () => Promise<T>, tipo: TipoMutacion, payload: Record<string, unknown>, descripcion: string, idCliente?: string, timestampDispositivo?: string): Promise<{ valor: T | null; encolada: MutacionPendiente | null }> {
  if (syncEngine.enLinea()) {
    try {
      return { valor: await enLinea(), encolada: null }
    } catch (e) {
      if (!esSinConexion(e)) throw e
    }
  }
  const encolada = await syncEngine.encolar(tipo, payload, descripcion, { idCliente, timestampDispositivo })
  return { valor: null, encolada }
}

export { uuid as nuevoIdCliente }
