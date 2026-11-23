/** Contexto persistente: GPS voluntario del usuario, independiente de la ruta React.
 * Funciona mientras ACMA está visible, incluso al navegar entre páginas.
 * No intenta geolocalizar con el móvil bloqueado ni en segundo plano.
 */
import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from 'react'
import { Link } from 'react-router'
import { mensajeDeError } from '../services/api'
import { consultarMiUbicacion, detenerMiUbicacion, enviarMiUbicacion, iniciarMiUbicacion } from '../services/rastreoUsuarios'

type Estado = {
  activo: boolean
  ocupado: boolean
  mensaje: string
  error: string | null
  iniciar: () => Promise<void>
  detener: () => Promise<void>
}
const Contexto = createContext<Estado | null>(null)

export function usarMiUbicacion(): Estado {
  const actual = useContext(Contexto)
  if (!actual) throw new Error('Usar ubicación requiere ProveedorMiUbicacion')
  return actual
}

function detectarDispositivo(): 'pc' | 'android' | 'iphone' | 'navegador' {
  const ua = navigator.userAgent.toLowerCase()
  if (/android/.test(ua)) return 'android'
  if (/iphone|ipad|ipod/.test(ua)) return 'iphone'
  if (/windows|macintosh|linux/.test(ua)) return 'pc'
  return 'navegador'
}

function AvisoActivo() {
  const { activo, detener } = usarMiUbicacion()
  if (!activo) return null
  return (
    <div role="status" className="mb-4 flex flex-wrap items-center justify-between gap-2 rounded-xl border border-emerald-300 bg-emerald-50 px-4 py-2 text-sm text-emerald-900"
      data-testid="gps-usuario-activo">
      <span className="font-semibold">Estás compartiendo tu ubicación con ACMA</span>
      <div className="flex items-center gap-3">
        <Link to="/mi-ubicacion" className="font-semibold underline">Mi ubicación</Link>
        <button type="button" onClick={() => void detener()}
          className="rounded-lg bg-rose-700 px-3 py-2 font-semibold text-white">
          Detener GPS
        </button>
      </div>
    </div>
  )
}

export function ProveedorMiUbicacion({ children }: { children: ReactNode }) {
  const [activo, setActivo] = useState(false)
  const [ocupado, setOcupado] = useState(false)
  const [mensaje, setMensaje] = useState('No estás compartiendo tu ubicación.')
  const [error, setError] = useState<string | null>(null)
  const vigilando = useRef<number | null>(null)
  const intervalo = useRef<ReturnType<typeof setInterval> | null>(null)
  const ultimaPosicion = useRef<GeolocationPosition | null>(null)
  const ultimoEnvio = useRef(0)
  const activoRef = useRef(false)
  const enviando = useRef(false)

  function limpiarSensores() {
    activoRef.current = false
    if (vigilando.current != null && navigator.geolocation) navigator.geolocation.clearWatch(vigilando.current)
    vigilando.current = null
    if (intervalo.current) clearInterval(intervalo.current)
    intervalo.current = null
    ultimaPosicion.current = null
    ultimoEnvio.current = 0
    setActivo(false)
  }

  async function detener() {
    limpiarSensores()
    setMensaje('Ubicación detenida. Ya no se enviarán nuevos puntos.')
    try { await detenerMiUbicacion() }
    catch {
      setError('No se pudo confirmar la detención. La última ubicación dejará de mostrarse en 90 segundos.')
    }
  }

  async function transmitir() {
    const p = ultimaPosicion.current
    if (!activoRef.current || !p || enviando.current) return
    if (Date.now() - p.timestamp > 45000) {
      setMensaje('Esperando GPS reciente; no se envía una coordenada antigua.')
      return
    }
    if (Date.now() - ultimoEnvio.current < 12000) return
    enviando.current = true
    ultimoEnvio.current = Date.now()
    try {
      const accuracy = Number.isFinite(p.coords.accuracy) && p.coords.accuracy <= 1000000
        ? p.coords.accuracy : null
      const r = await enviarMiUbicacion(p.coords.latitude, p.coords.longitude, accuracy)
      if (activoRef.current) {
        setMensaje('Compartiendo GPS · última actualización: ' +
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
      setError('Se requiere HTTPS y servicios de ubicación activos en PC, Android o iPhone.')
      return
    }
    setOcupado(true)
    try {
      // Se activa exclusivamente desde el botón del dueño de la sesión.
      await iniciarMiUbicacion(detectarDispositivo())
      activoRef.current = true
      setActivo(true)
      setMensaje('Esperando permiso y primera ubicación del dispositivo…')
      vigilando.current = navigator.geolocation.watchPosition(
        p => {
          if (!activoRef.current) return
          ultimaPosicion.current = p
          void transmitir()
        },
        e => {
          if (!activoRef.current) return
          setError(e.code === 1
            ? 'Permiso de ubicación denegado. Autorízalo en el navegador y el sistema.'
            : 'Sin señal de ubicación. Comprueba los servicios de ubicación de este dispositivo.')
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
      limpiarSensores()
      setError(mensajeDeError(e))
    } finally { setOcupado(false) }
  }

  useEffect(() => {
    let presente = true
    // Si el navegador se recargó, no recuperar el GPS sin un nuevo clic.
    void consultarMiUbicacion().then(r => {
      if (presente && r.compartiendo) {
        setMensaje('Hay una activación anterior reciente. Pulsa Activar para iniciar aquí.')
      }
    }).catch(() => undefined)
    const ocultar = () => { if (document.hidden && activoRef.current) void detener() }
    const salir = () => {
      if (activoRef.current) {
        limpiarSensores()
        void detenerMiUbicacion().catch(() => undefined)
      }
    }
    document.addEventListener('visibilitychange', ocultar)
    window.addEventListener('pagehide', salir)
    return () => {
      presente = false
      document.removeEventListener('visibilitychange', ocultar)
      window.removeEventListener('pagehide', salir)
      salir()
    }
  }, [])

  return (
    <Contexto.Provider value={{ activo, ocupado, mensaje, error, iniciar, detener }}>
      <AvisoActivo />
      {children}
    </Contexto.Provider>
  )
}
