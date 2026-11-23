/** Contexto persistente: GPS voluntario del usuario, independiente de la ruta React.
 * Funciona mientras ACMA está visible, incluso al navegar entre páginas.
 * No intenta geolocalizar con el móvil bloqueado ni en segundo plano.
 */
import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from 'react'
import { Link } from 'react-router'
import { useAuth } from './AuthContext'
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
  const { usuario } = useAuth()
  const [solicitudVisible, setSolicitudVisible] = useState(false)
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
      // Primero solicitar permiso desde el clic REAL: iOS Safari pierde
      // activación del usuario si esperamos una llamada HTTP antes del prompt.
      const primera = await new Promise<GeolocationPosition>((resolve, reject) => {
        navigator.geolocation.getCurrentPosition(resolve, reject, {
          enableHighAccuracy: true, maximumAge: 5000, timeout: 20000,
        })
      })
      // Solo después del permiso se registra el consentimiento en el servidor.
      await iniciarMiUbicacion(detectarDispositivo())
      activoRef.current = true
      setActivo(true)
      ultimaPosicion.current = primera
      setMensaje('Ubicación autorizada. Compartiendo posición reciente…')
      void transmitir()
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
      const codigo = (e as { code?: number })?.code
      setError(codigo === 1
        ? 'Rechazaste el acceso a tu ubicación. Puedes activarlo después desde Mi ubicación.'
        : codigo === 2 || codigo === 3
          ? 'No se pudo obtener tu ubicación. Revisa el GPS y vuelve a intentarlo.'
          : mensajeDeError(e))
    } finally { setOcupado(false) }
  }

  function responderSolicitud(aceptar: boolean) {
    const id = usuario?.id
    if (id) {
      try { sessionStorage.setItem('acma.gps.ofrecido.' + id, '1') }
      catch { /* El navegador podría bloquear sessionStorage. */ }
    }
    setSolicitudVisible(false)
    if (aceptar) void iniciar()
  }

  useEffect(() => {
    if (!usuario?.id || activoRef.current) return
    let yaSeOfrecio = false
    try { yaSeOfrecio = sessionStorage.getItem('acma.gps.ofrecido.' + usuario.id) === '1' }
    catch { /* Ofrecer si no se puede leer el almacenamiento. */ }
    setSolicitudVisible(!yaSeOfrecio)
  }, [usuario?.id])

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
      {solicitudVisible && !activo && (
        <div className="pointer-events-none fixed bottom-4 right-4 z-[1100] w-[min(28rem,calc(100vw-2rem))]"
          data-testid="solicitud-ubicacion-inicio">
          <section role="region" aria-labelledby="gps-solicitud-titulo"
            className="pointer-events-auto w-full rounded-3xl border border-emerald-200 bg-white p-5 shadow-2xl">
            <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-emerald-100">
              <span className="text-2xl text-emerald-800" aria-hidden="true">⌖</span>
            </div>
            <h2 id="gps-solicitud-titulo" className="text-xl font-extrabold text-slate-900">
              ¿Compartir tu ubicación con ACMA?
            </h2>
            <p className="mt-3 text-sm leading-6 text-slate-600">
              {usuario?.nombre}, puedes compartir tu ubicación en tiempo real desde PC,
              Android o iPhone. Los administradores autorizados podrán seleccionarte
              por tu nombre en el mapa. Se guarda únicamente la última posición.
              Se actualizará mientras ACMA permanezca visible y puedes detenerla cuando quieras.
            </p>
            <p className="mt-2 text-xs text-slate-500">
              Al pulsar Activar se solicitará permiso de ubicación al dispositivo.
              Si eliges Ahora no, no se consultará tu GPS.
            </p>
            <div className="mt-6 grid gap-2 sm:grid-cols-2">
              <button type="button" onClick={() => responderSolicitud(false)}
                className="min-h-12 rounded-xl border border-slate-300 px-4 py-3 font-semibold text-slate-700">
                Ahora no
              </button>
              <button type="button" onClick={() => responderSolicitud(true)}
                className="min-h-12 rounded-xl bg-emerald-800 px-4 py-3 font-semibold text-white">
                Activar mi ubicación
              </button>
            </div>
          </section>
        </div>
      )}
    </Contexto.Provider>
  )
}
