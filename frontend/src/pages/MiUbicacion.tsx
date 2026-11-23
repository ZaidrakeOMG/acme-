/** Activación de GPS voluntaria en PC, Android o iPhone.
 * No rastrea en segundo plano ni solicita permisos silenciosamente.
 */
import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router'
import { mensajeDeError } from '../services/api'
import { consultarMiUbicacion, detenerMiUbicacion, enviarMiUbicacion, iniciarMiUbicacion } from '../services/rastreoUsuarios'

function dispositivoActual(): 'pc' | 'android' | 'iphone' | 'navegador' {
  const ua = navigator.userAgent.toLowerCase()
  if (/android/.test(ua)) return 'android'
  if (/iphone|ipad|ipod/.test(ua)) return 'iphone'
  if (/windows|macintosh|linux/.test(ua)) return 'pc'
  return 'navegador'
}

export function MiUbicacion() {
  const [activo, setActivo] = useState(false)
  const [ocupado, setOcupado] = useState(false)
  const [mensaje, setMensaje] = useState('No estás compartiendo tu ubicación.')
  const [error, setError] = useState<string | null>(null)
  const vigilando = useRef<number | null>(null)
  const intervalo = useRef<ReturnType<typeof setInterval> | null>(null)
  const ultimaPosicion = useRef<GeolocationPosition | null>(null)
  const activoRef = useRef(false)
  const enviando = useRef(false)

  function detenerSensores() {
    activoRef.current = false
    if (vigilando.current != null && navigator.geolocation) navigator.geolocation.clearWatch(vigilando.current)
    vigilando.current = null
    if (intervalo.current) clearInterval(intervalo.current)
    intervalo.current = null
    ultimaPosicion.current = null
    setActivo(false)
  }

  async function detener() {
    detenerSensores()
    setMensaje('Ubicación detenida. No se enviarán nuevos puntos.')
    try { await detenerMiUbicacion() }
    catch {
      setError('No se pudo confirmar la detención con el servidor. La ubicación dejará de mostrarse al caducar (90 segundos).')
    }
  }

  async function transmitir() {
    const p = ultimaPosicion.current
    if (!activoRef.current || !p || enviando.current) return
    if (Date.now() - p.timestamp > 45000) {
      setMensaje('Esperando una posición reciente. No se enviará una coordenada antigua.')
      return
    }
    enviando.current = true
    try {
      const r = await enviarMiUbicacion(p.coords.latitude, p.coords.longitude,
        Number.isFinite(p.coords.accuracy) ? p.coords.accuracy : null)
      if (activoRef.current) {
        setMensaje('Compartiendo ubicación · última actualización: ' +
          new Date(r.ultima_at ?? Date.now()).toLocaleTimeString())
        setError(null)
      }
    } catch (e) {
      if (activoRef.current) {
        setError(mensajeDeError(e))
        await detener()
      }
    } finally { enviando.current = false }
  }

  async function iniciar() {
    if (ocupado || activoRef.current) return
    setError(null)
    if (!window.isSecureContext || !('geolocation' in navigator)) {
      setError('Debes usar HTTPS y tener habilitados los servicios de ubicación del equipo.')
      return
    }
    setOcupado(true)
    try {
      await iniciarMiUbicacion(dispositivoActual())
      activoRef.current = true
      setActivo(true)
      setMensaje('Esperando el permiso y la primera posición GPS…')
      vigilando.current = navigator.geolocation.watchPosition(
        p => {
          if (!activoRef.current) return
          ultimaPosicion.current = p
          void transmitir()
        },
        e => {
          if (!activoRef.current) return
          setError(e.code === 1 ? 'Permiso de ubicación denegado. Actívalo en el dispositivo o navegador.'
            : 'No se puede obtener tu ubicación. Revisa que los servicios de ubicación estén encendidos.')
          void detener()
        },
        { enableHighAccuracy: true, maximumAge: 5000, timeout: 20000 },
      )
      intervalo.current = setInterval(() => {
        if (ultimaPosicion.current && Date.now() - ultimaPosicion.current.timestamp > 75000) {
          void detener()
        } else void transmitir()
      }, 15000)
    } catch (e) {
      detenerSensores()
      setError(mensajeDeError(e))
    } finally { setOcupado(false) }
  }

  useEffect(() => {
    // No reactivamos el GPS automáticamente: el consentimiento debe ser explícito.
    void consultarMiUbicacion().then(r => {
      if (r.compartiendo) setMensaje('Existe una activación reciente. Pulsa Compartir para activarla en este dispositivo.')
    }).catch(() => undefined)
    const ocultar = () => { if (document.hidden && activoRef.current) void detener() }
    const salir = () => {
      if (!activoRef.current) return
      detenerSensores()
      void detenerMiUbicacion().catch(() => undefined)
    }
    document.addEventListener('visibilitychange', ocultar)
    window.addEventListener('pagehide', salir)
    return () => {
      document.removeEventListener('visibilitychange', ocultar)
      window.removeEventListener('pagehide', salir)
      salir()
    }
  }, [])

  return (
    <div className="mx-auto max-w-2xl space-y-5" data-testid="mi-ubicacion">
      <header>
        <h1 className="text-2xl font-bold text-slate-900">Compartir mi ubicación</h1>
        <p className="mt-2 text-slate-600">Actívala desde una computadora, Android o iPhone.
          No necesitas tener ningún folio asignado.</p>
      </header>
      <section className="rounded-2xl border border-sky-200 bg-white p-5 shadow-sm">
        <h2 className="font-semibold text-slate-900">Mi GPS en tiempo real</h2>
        <p className="mt-2 text-sm text-slate-600">
          Al activarlo, el personal autorizado de tu organización podrá ver tu última posición en
          Operaciones. Solo se guarda la ubicación más reciente; no se almacena una ruta.
          Se actualiza mientras esta pantalla está abierta y visible. Tu posición
          deja de mostrarse al detenerla o después de 90 segundos sin señal.
        </p>
        <p role="status" className="mt-4 text-sm font-semibold text-slate-700">{mensaje}</p>
        {error && <p role="alert" className="mt-3 text-sm text-red-700">{error}</p>}
        {activo
          ? <button type="button" onClick={() => void detener()}
              className="mt-4 min-h-12 w-full rounded-xl bg-rose-700 px-4 py-2 font-semibold text-white">
              Dejar de compartir mi ubicación
            </button>
          : <button type="button" disabled={ocupado} onClick={() => void iniciar()}
              className="mt-4 min-h-12 w-full rounded-xl bg-sky-800 px-4 py-2 font-semibold text-white disabled:opacity-50">
              {ocupado ? 'Activando…' : 'Activar mi ubicación'}
            </button>}
      </section>
      <p className="text-sm text-slate-500">
        En PC, la precisión depende de Windows/macOS y el navegador; puede ser aproximada.
        En Android y iPhone la ubicación también depende del permiso del sistema.
        La web no garantiza seguimiento cuando cierras la pantalla, bloqueas el móvil
        o cambias de aplicación.
      </p>
      <Link to="/" className="inline-block text-sm font-semibold text-primario underline">Volver al inicio</Link>
    </div>
  )
}
