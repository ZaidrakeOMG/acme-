import { lazy, Suspense, useCallback, useEffect, useRef, useState } from 'react'
import { IconoAcma } from '../../components/IconosAcma'
import { Aviso, Boton, Encabezado } from '../../components/ui'
import { api, mensajeDeError } from '../../services/api'
import { useAppAndroid } from '../../services/clienteAndroid'
import type { PersonaGPS } from './MapaPersonal'

const MapaPersonal = lazy(() => import('./MapaPersonal'))

interface EstadoGPS {
  activa: boolean
  consentimiento_at: string | null
  ultima_ubicacion_at: string | null
  puede_ver_mapa: boolean
  puede_administrar_visores: boolean
}

interface UsuarioVisor {
  id: string
  nombre: string
  email: string
  rol: string
  habilitado: boolean
}

function etiquetaFecha(fecha: string | null): string {
  if (!fecha) return 'Sin ubicación reciente'
  return new Date(fecha).toLocaleString('es-MX', { dateStyle: 'short', timeStyle: 'short' })
}

function ubicacionActual(): Promise<GeolocationPosition> {
  return new Promise((resolve, reject) => {
    if (!navigator.geolocation) {
      reject(new Error('Este teléfono no permite obtener ubicación por GPS.'))
      return
    }
    navigator.geolocation.getCurrentPosition(resolve, reject, {
      enableHighAccuracy: true, timeout: 20000, maximumAge: 0,
    })
  })
}

function explicacionError(e: unknown): string {
  if (e != null && typeof e === 'object' && 'code' in e) {
    const error = e as GeolocationPositionError
    if (error.code === 1) return 'No se autorizó la ubicación. Habilítala para ACMA desde los permisos de Android.'
    if (error.code === 2) return 'El GPS no encontró tu posición. Activa la ubicación del teléfono.'
    if (error.code === 3) return 'El teléfono tardó demasiado en localizarte. Inténtalo otra vez.'
  }
  return e instanceof Error ? e.message : mensajeDeError(e)
}

/** Módulo independiente, visible únicamente en la aplicación Android de ACMA.
 *  No realiza rastreo oculto, ni envía posiciones hasta pulsar «Comenzar».
 *  La señal se suspende al salir de la pantalla o cuando Android oculta ACMA.
 */
export function UbicacionMovil() {
  const esAndroid = useAppAndroid()
  const [estado, setEstado] = useState<EstadoGPS | null>(null)
  const [personas, setPersonas] = useState<PersonaGPS[]>([])
  const [visores, setVisores] = useState<UsuarioVisor[]>([])
  const [busqueda, setBusqueda] = useState('')
  const [emitir, setEmitir] = useState(false)
  const [procesando, setProcesando] = useState(false)
  const [guardandoId, setGuardandoId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [mensaje, setMensaje] = useState<string | null>(null)
  const [seleccionado, setSeleccionado] = useState<string | null>(null)
  const observador = useRef<number | null>(null)
  const ultimoEnvio = useRef(0)
  const emitiendo = useRef(false)
  const montado = useRef(true)

  const pararGPSLocal = useCallback(() => {
    if (observador.current !== null) navigator.geolocation?.clearWatch(observador.current)
    observador.current = null
    emitiendo.current = false
    if (montado.current) setEmitir(false)
  }, [])

  useEffect(() => {
    montado.current = true
    const ocultar = () => {
      if (document.visibilityState === 'hidden') pararGPSLocal()
    }
    document.addEventListener('visibilitychange', ocultar)
    return () => {
      document.removeEventListener('visibilitychange', ocultar)
      montado.current = false
      pararGPSLocal()
    }
  }, [pararGPSLocal])

  const cargarEstado = useCallback(async () => {
    try {
      setEstado(await api<EstadoGPS>('/ubicacion-movil/estado'))
    } catch (e) {
      setError(mensajeDeError(e))
    }
  }, [])

  useEffect(() => {
    if (!esAndroid) return
    void cargarEstado()
  }, [esAndroid, cargarEstado])

  const cargarMapa = useCallback(async () => {
    try {
      const lista = await api<PersonaGPS[]>('/ubicacion-movil/mapa')
      setPersonas(lista)
    } catch (e) {
      setError(mensajeDeError(e))
    }
  }, [])

  useEffect(() => {
    if (!esAndroid || !estado?.puede_ver_mapa) return
    void cargarMapa()
    const intervalo = window.setInterval(() => void cargarMapa(), 20000)
    return () => window.clearInterval(intervalo)
  }, [esAndroid, estado?.puede_ver_mapa, cargarMapa])

  useEffect(() => {
    if (!esAndroid || !estado?.puede_administrar_visores) return
    void api<UsuarioVisor[]>('/ubicacion-movil/admin/usuarios')
      .then(setVisores)
      .catch(e => setError(mensajeDeError(e)))
  }, [esAndroid, estado?.puede_administrar_visores])

  async function enviarPosicion(p: GeolocationPosition) {
    if (!emitiendo.current || document.visibilityState === 'hidden') return
    const ahora = Date.now()
    if (ahora - ultimoEnvio.current < 30000) return
    ultimoEnvio.current = ahora
    try {
      await api('/ubicacion-movil/posicion', {
        metodo: 'POST',
        cuerpo: { lat: p.coords.latitude, lng: p.coords.longitude, precision_m: p.coords.accuracy },
      })
      setMensaje('Compartiendo mientras esta pantalla permanezca abierta.')
    } catch (e) {
      pararGPSLocal()
      setError(mensajeDeError(e))
    }
  }

  async function comenzar() {
    setProcesando(true)
    setError(null)
    setMensaje(null)
    try {
      // El permiso se solicita como consecuencia directa de pulsar el botón;
      // nunca al iniciar sesión ni automáticamente al abrir ACMA.
      const p = await ubicacionActual()
      if (!montado.current || document.visibilityState === 'hidden') return
      await api('/ubicacion-movil/activar', { metodo: 'POST', cuerpo: { acepto: true } })
      if (!montado.current || document.visibilityState === 'hidden') {
        // Si el usuario salió mientras la API activaba el consentimiento,
        // no conservamos una ubicación activa accidentalmente.
        await api('/ubicacion-movil/detener', { metodo: 'POST' })
        return
      }
      emitiendo.current = true
      ultimoEnvio.current = 0
      await enviarPosicion(p)
      if (!emitiendo.current) return
      observador.current = navigator.geolocation.watchPosition(
        (punto) => { void enviarPosicion(punto) },
        (e) => setError(explicacionError(e)),
        { enableHighAccuracy: true, maximumAge: 15000, timeout: 20000 },
      )
      setEmitir(true)
      await cargarEstado()
    } catch (e) {
      pararGPSLocal()
      setError(explicacionError(e))
    } finally {
      setProcesando(false)
    }
  }

  async function detener() {
    setProcesando(true)
    setError(null)
    pararGPSLocal()
    try {
      await api('/ubicacion-movil/detener', { metodo: 'POST' })
      await cargarEstado()
      setMensaje('Se dejó de compartir tu ubicación y se borró tu última posición.')
      if (estado?.puede_ver_mapa) void cargarMapa()
    } catch (e) {
      setError(mensajeDeError(e))
    } finally {
      setProcesando(false)
    }
  }

  async function conceder(usuario: UsuarioVisor) {
    setGuardandoId(usuario.id)
    setError(null)
    try {
      await api(`/ubicacion-movil/admin/usuarios/${usuario.id}`, {
        metodo: 'PUT', cuerpo: { habilitado: !usuario.habilitado },
      })
      setVisores(lista => lista.map(u => u.id === usuario.id ? { ...u, habilitado: !u.habilitado } : u))
    } catch (e) {
      setError(mensajeDeError(e))
    } finally {
      setGuardandoId(null)
    }
  }

  if (!esAndroid) {
    return (
      <div className="rounded-2xl border border-slate-200 bg-white p-6">
        <Encabezado titulo="Ubicación de personal" descripcion="Esta sección solo está disponible dentro de la aplicación Android ACMA." />
        <p className="text-sm text-slate-600">Abre ACMA desde la aplicación Android para compartir tu ubicación o consultar el mapa si tienes autorización.</p>
      </div>
    )
  }

  const filtrados = visores.filter(u => `${u.nombre} ${u.email} ${u.rol}`.toLowerCase().includes(busqueda.toLowerCase()))

  return (
    <div className="space-y-6">
      <Encabezado titulo="Ubicación de personal"
        descripcion="GPS voluntario de Android y mapa de usuarios autorizados. Sin historial de recorridos." />
      {error && <Aviso>{error}</Aviso>}
      {mensaje && <Aviso tipo="info">{mensaje}</Aviso>}

      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="flex min-w-0 items-center gap-3">
            <span className="grid h-12 w-12 shrink-0 place-items-center rounded-xl bg-[#faebef] text-[#9e2144]">
              <IconoAcma nombre="ubicación" className="h-6 w-6" />
            </span>
            <div>
              <h2 className="text-lg font-bold text-slate-900">Compartir mi ubicación</h2>
              <p className="mt-1 text-sm text-slate-500">
                {emitir ? 'GPS activo en esta pantalla' : 'Tu ubicación no se está enviando desde esta pantalla'}
              </p>
            </div>
          </div>
          <span className={`rounded-full px-3 py-1.5 text-xs font-bold ${emitir ? 'bg-green-100 text-green-800' : 'bg-slate-100 text-slate-600'}`}>
            {emitir ? 'Compartiendo ahora' : 'Sin transmisión'}
          </span>
        </div>
        <p className="mt-4 text-sm leading-6 text-slate-600">
          Al comenzar, autorizas que los responsables con permiso consulten tu posición actual.
          Se actualiza aproximadamente cada 30 segundos, únicamente mientras esta pantalla
          esté abierta y visible. Al detenerla se elimina la última ubicación guardada.
          No se registra tu recorrido ni se utiliza GPS en segundo plano.
        </p>
        <p className="mt-2 text-xs text-slate-500">Última señal registrada: {etiquetaFecha(estado?.ultima_ubicacion_at ?? null)}</p>
        <div className="mt-5 flex flex-wrap gap-3">
          {!emitir && (
            <Boton type="button" onClick={() => void comenzar()} disabled={procesando}>
              <IconoAcma nombre="ubicación" className="h-4 w-4" />
              {procesando ? 'Localizando…' : 'Comenzar a compartir'}
            </Boton>
          )}
          {(emitir || estado?.activa) && (
            <Boton type="button" variante={emitir ? 'peligro' : 'secundario'}
              onClick={() => void detener()} disabled={procesando}>
              <IconoAcma nombre="cerrar" className="h-4 w-4" /> Detener y borrar ubicación
            </Boton>
          )}
        </div>
      </section>

      {estado?.puede_ver_mapa && (
        <section className="space-y-4 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-6">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-lg font-bold text-slate-900">Mapa de personal</h2>
              <p className="mt-1 text-sm text-slate-500">
                {personas.length} usuario(s) compartiendo · solo posiciones de los últimos 5 minutos.
              </p>
            </div>
            <Boton variante="secundario" onClick={() => void cargarMapa()}>
              <IconoAcma nombre="sincronizar" className="h-4 w-4" /> Actualizar
            </Boton>
          </div>
          <Suspense fallback={<div className="h-80 animate-pulse rounded-xl bg-slate-100" />}>
            <MapaPersonal personas={personas} seleccionado={seleccionado} alSeleccionar={setSeleccionado} />
          </Suspense>
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {personas.map(p => (
              <button key={p.usuario_id} type="button" onClick={() => setSeleccionado(p.usuario_id)}
                className={`flex items-center gap-3 rounded-xl border px-3 py-3 text-left transition ${seleccionado === p.usuario_id ? 'border-[#ac143c] bg-[#fff7f9]' : 'border-slate-200 hover:bg-slate-50'}`}>
                <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-[#f4e5eb] text-[#972846]">
                  <IconoAcma nombre="usuario" className="h-5 w-5" />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-semibold">{p.nombre}</span>
                  <span className="block truncate text-xs text-slate-500">{etiquetaFecha(p.ultima_ubicacion_at)}</span>
                </span>
              </button>
            ))}
            {!personas.length && <p className="text-sm text-slate-500">Nadie está compartiendo una ubicación reciente.</p>}
          </div>
          {personas.filter(p => p.usuario_id === seleccionado).map(p => (
            <a key={p.usuario_id} href={`https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(`${p.lat},${p.lng}`)}`}
              target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-2 rounded-xl border border-[#e6ced6] bg-[#fff7f9] px-4 py-2.5 text-sm font-semibold text-[#962442]">
              <IconoAcma nombre="ubicación" className="h-4 w-4" /> Abrir {p.nombre} en Google Maps
            </a>
          ))}
        </section>
      )}

      {estado?.puede_administrar_visores && (
        <section className="space-y-4 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-6">
          <div>
            <h2 className="text-lg font-bold text-slate-900">Permisos para ver el mapa</h2>
            <p className="mt-1 text-sm text-slate-500">
              Solo Superadmin puede conceder o retirar este acceso. Los visores solo ven
              personas de su empresa o prestador y que hayan aceptado compartir.
            </p>
          </div>
          <label className="flex items-center gap-2 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2">
            <IconoAcma nombre="buscar" className="h-5 w-5 text-slate-400" />
            <span className="sr-only">Buscar usuario</span>
            <input type="search" value={busqueda} onChange={e => setBusqueda(e.target.value)}
              placeholder="Buscar persona para autorizar"
              className="min-h-10 min-w-0 flex-1 bg-transparent text-sm outline-none" />
          </label>
          <div className="max-h-96 space-y-2 overflow-y-auto">
            {filtrados.map(u => (
              <div key={u.id} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-100 px-3 py-3">
                <div className="min-w-0">
                  <p className="truncate text-sm font-bold text-slate-800">{u.nombre}</p>
                  <p className="truncate text-xs text-slate-500">{u.email} · {u.rol}</p>
                </div>
                <button type="button" aria-pressed={u.habilitado} disabled={guardandoId === u.id}
                  onClick={() => void conceder(u)}
                  className={`min-h-10 rounded-lg px-3 text-xs font-bold transition disabled:opacity-50 ${u.habilitado ? 'border border-red-200 bg-red-50 text-red-700' : 'bg-[#962442] text-white'}`}>
                  {guardandoId === u.id ? 'Guardando…' : u.habilitado ? 'Retirar acceso' : 'Permitir acceso'}
                </button>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  )
}
