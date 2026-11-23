/** Contexto persistente: GPS voluntario del usuario, independiente de la ruta React.
 * Funciona mientras ACMA está visible, incluso al navegar entre páginas.
 * No intenta geolocalizar con el móvil bloqueado ni en segundo plano.
 */
import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from 'react'
import { useAuth } from './AuthContext'
import { mensajeDeError } from '../services/api'
import { registrarPush } from '../services/campo'
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

// Preferencia revocable por usuario, vinculada al dispositivo y al origen HTTPS.
export const claveConsentimientoGps = (id: string) =>
  'acma.gps.consentimiento.v1.' + id

function tieneConsentimiento(id: string) {
  try { return localStorage.getItem(claveConsentimientoGps(id)) === '1' }
  catch { return false }
}

function guardarConsentimiento(id: string, activo: boolean) {
  try {
    if (activo) localStorage.setItem(claveConsentimientoGps(id), '1')
    else localStorage.removeItem(claveConsentimientoGps(id))
  } catch { /* En dispositivos sin almacenamiento hay que volver a aceptar. */ }
}

export function ProveedorMiUbicacion({ children }: { children: ReactNode }) {
  const { usuario } = useAuth()
  const [solicitudVisible, setSolicitudVisible] = useState(false)
  const [solicitandoPermisos, setSolicitandoPermisos] = useState(false)
  const [avisoPermisos, setAvisoPermisos] = useState<string | null>(null)
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
  const iniciandoRef = useRef(false)

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

  async function pausar() {
    if (!activoRef.current) return
    limpiarSensores()
    setMensaje('Ubicación pausada hasta regresar a ACMA.')
    try { await detenerMiUbicacion() }
    catch { /* La ubicación caduca en el servidor después de 90 segundos. */ }
  }

  async function detener() {
    // Revocación explícita: no volver a compartir hasta nueva autorización.
    if (usuario?.id) guardarConsentimiento(usuario.id, false)
    limpiarSensores()
    setSolicitudVisible(true)
    setMensaje('Ubicación detenida. No se enviarán nuevos puntos.')
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
        await pausar()
        setAvisoPermisos('Error de conexión al enviar ubicación. Se reanudará al volver a abrir ACMA.')
      }
    } finally { enviando.current = false }
  }

  async function iniciar() {
    if (iniciandoRef.current || activoRef.current) return
    iniciandoRef.current = true
    setError(null)
    if (!window.isSecureContext || !('geolocation' in navigator)) {
      setError('Se requiere HTTPS y servicios de ubicación activos en PC, Android o iPhone.')
      iniciandoRef.current = false
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
          void pausar()
          setSolicitudVisible(true)
        },
        { enableHighAccuracy: true, maximumAge: 5000, timeout: 20000 },
      )
      intervalo.current = setInterval(() => {
        if (ultimaPosicion.current && Date.now() - ultimaPosicion.current.timestamp > 75000) {
          void pausar()
        } else void transmitir()
      }, 15000)
    } catch (e) {
      limpiarSensores()
      const codigo = (e as { code?: number })?.code
      setError(codigo === 1
        ? 'Permiso de ubicación rechazado. ACMA requiere habilitarlo para continuar. Revisa los ajustes del dispositivo y reintenta.'
        : codigo === 2 || codigo === 3
          ? 'No se pudo obtener tu ubicación. Revisa el GPS y vuelve a intentarlo.'
          : mensajeDeError(e))
    } finally {
      iniciandoRef.current = false
      setOcupado(false)
    }
  }

  async function solicitarNotificaciones(soloConsultar = false): Promise<boolean> {
    // La APK usa el sistema nativo Android: Notification no existe siempre
    // dentro de Android WebView. Jamás simular un permiso aprobado.
    const puente = (window as Window & {
      AcmaPermisos?: { postMessage: (mensaje: string) => void }
    }).AcmaPermisos
    if (puente) {
      return new Promise<boolean>(resolve => {
        let resuelto = false
        const concluir = (aceptado: boolean) => {
          if (resuelto) return
          resuelto = true
          clearTimeout(temporizador)
          window.removeEventListener('acma:permiso-notificaciones', recibido)
          resolve(aceptado)
        }
        const recibido = (evento: Event) => {
          concluir((evento as CustomEvent<{ autorizado?: boolean }>).detail?.autorizado === true)
        }
        window.addEventListener('acma:permiso-notificaciones', recibido)
        const temporizador = setTimeout(() => concluir(false), 15000)
        try { puente.postMessage(soloConsultar ? 'consultar_notificaciones' : 'solicitar_notificaciones') }
        catch { concluir(false) }
      })
    }
    // Android WebView no expone Notification aunque el permiso Android
    // ya haya sido concedido. La APK v0.1.6 publica el estado obtenido
    // de Permission.notification.status (nunca se supone autorizado).
    const android = (window as Window & {
      __acmaNotificacionesAutorizadas?: boolean
    }).__acmaNotificacionesAutorizadas
    if (/Android/i.test(navigator.userAgent) && android === true) return true
    if (!('Notification' in window) || !window.isSecureContext) {
      if (/Android/i.test(navigator.userAgent)) {
        throw new Error(
          'Esta versión Android no tiene el módulo nativo de notificaciones. Instala la APK ACMA 0.1.6 y vuelve a abrir la aplicación.',
        )
      }
      throw new Error('Este navegador no admite notificaciones del sistema. Usa Chrome o Edge con HTTPS y autoriza notificaciones en la configuración.')
    }
    if (Notification.permission === 'granted') return true
    if (Notification.permission === 'denied' || soloConsultar) return false
    // Debe invocarse directamente desde el toque/clic del usuario.
    return (await Notification.requestPermission()) === 'granted'
  }

  async function autorizarPermisosIniciales() {
    if (solicitandoPermisos) return
    setSolicitandoPermisos(true)
    setAvisoPermisos(null)
    try {
      // PRIMERO notificaciones: en Chrome y Edge requieren gesto humano.
      const notificaciones = await solicitarNotificaciones()
      if (!notificaciones) {
        setAvisoPermisos('Notificaciones rechazadas. Habilítalas en los ajustes del teléfono o navegador para continuar.')
        return
      }
      // Después se abre el diálogo de ubicación del propio sistema.
      if (!activoRef.current) await iniciar()
      if (activoRef.current) {
        setSolicitudVisible(false)
        setAvisoPermisos(null)
        if (usuario?.id) guardarConsentimiento(usuario.id, true)
        // Solo tras la aceptación humana registramos Push cuando el
        // navegador lo permita; Android WebView usa permiso nativo.
        void registrarPush().catch(() => undefined)
      } else {
        setAvisoPermisos('No se ha podido activar la ubicación. Autoriza el GPS y vuelve a pulsar Habilitar permisos.')
      }
    } catch (e) {
      setAvisoPermisos(e instanceof Error ? e.message : 'No se pudieron solicitar los permisos.')
    } finally {
      setSolicitandoPermisos(false)
    }
  }

  function abrirAjustes() {
    const puente = (window as Window & {
      AcmaPermisos?: { postMessage: (mensaje: string) => void }
    }).AcmaPermisos
    if (puente) puente.postMessage('abrir_ajustes')
    else setAvisoPermisos('En el navegador abre el candado junto a la dirección de ACMA, entra a Configuración del sitio y permite Ubicación y Notificaciones. Después vuelve a intentar.')
  }

  async function reanudarSiRecordado(id: string) {
    if (!tieneConsentimiento(id) || iniciandoRef.current || activoRef.current) return
    try {
      // Sólo consultar permisos previamente aprobados: no abrir diálogos
      // del SO al recuperar la sesión.
      if (!await solicitarNotificaciones(true)) {
        setSolicitudVisible(true)
        setAvisoPermisos('Las notificaciones ya no están permitidas. Revisa los ajustes del dispositivo.')
        return
      }
      if (document.hidden) return
      // Evitar que el navegador muestre un nuevo diálogo automático si
      // su autorización de ubicación caducó o fue revocada.
      if (navigator.permissions?.query) {
        try {
          const gps = await navigator.permissions.query({ name: 'geolocation' })
          if (gps.state !== 'granted') {
            setSolicitudVisible(true)
            setAvisoPermisos('Es necesario volver a permitir ubicación en este dispositivo.')
            return
          }
        } catch { /* Algunos WebView no implementan Permissions API. */ }
      }
      await iniciar()
      if (!activoRef.current) {
        setSolicitudVisible(true)
        setAvisoPermisos('Comprueba que el GPS esté activo y vuelve a autorizar desde ACMA.')
      } else {
        setSolicitudVisible(false)
        setAvisoPermisos(null)
      }
    } catch {
      setSolicitudVisible(true)
      setAvisoPermisos('No se pudieron verificar los permisos guardados. Vuelve a intentarlo.')
    }
  }

  useEffect(() => {
    const id = usuario?.id
    if (!id) {
      setSolicitudVisible(false)
      return
    }
    if (tieneConsentimiento(id)) {
      setSolicitudVisible(false)
      void reanudarSiRecordado(id)
    } else {
      setSolicitudVisible(true)
    }
  }, [usuario?.id])

  useEffect(() => {
    let presente = true
    // React solo recupera GPS cuando hay consentimiento persistido por usuario.
    void consultarMiUbicacion().then(r => {
      if (presente && r.compartiendo) {
        setMensaje('Hay una activación anterior reciente. Pulsa Activar para iniciar aquí.')
      }
    }).catch(() => undefined)
    const ocultar = () => {
      if (document.hidden && activoRef.current) void pausar()
      else if (!document.hidden && usuario?.id && tieneConsentimiento(usuario.id)) {
        void reanudarSiRecordado(usuario.id)
      }
    }
    const salir = () => {
      if (activoRef.current) {
        limpiarSensores()
        void detenerMiUbicacion().catch(() => undefined)
      }
    }
    document.addEventListener('visibilitychange', ocultar)
    window.addEventListener('acma:resume', ocultar)
    window.addEventListener('pagehide', salir)
    return () => {
      presente = false
      document.removeEventListener('visibilitychange', ocultar)
      window.removeEventListener('acma:resume', ocultar)
      window.removeEventListener('pagehide', salir)
      salir()
    }
  }, [])

  return (
    <Contexto.Provider value={{ activo, ocupado, mensaje, error, iniciar, detener }}>
      {children}
      {solicitudVisible && !activo && (
        <div className="fixed inset-0 z-[1100] flex items-center justify-center overflow-y-auto bg-slate-950/90 p-4"
          data-testid="solicitud-ubicacion-inicio">
          <section role="region" aria-labelledby="acma-permisos-titulo"
            className="w-full max-w-lg rounded-3xl border border-emerald-200 bg-white p-5 shadow-2xl sm:p-8">
            <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-emerald-100">
              <span className="text-3xl font-bold text-emerald-800" aria-hidden="true">+</span>
            </div>
            <h2 id="acma-permisos-titulo" className="text-xl font-extrabold text-slate-900 sm:text-2xl">
              Permisos necesarios para usar ACMA
            </h2>
            <p className="mt-3 text-sm leading-6 text-slate-700">
              {usuario?.nombre}, ACMA requiere que habilites la ubicación y las notificaciones
              de este dispositivo para acceder a la plataforma. No hay una opción
              para omitir esta configuración.
            </p>
            <div className="mt-4 space-y-3 rounded-xl bg-slate-50 p-4 text-sm text-slate-700">
              <p><strong>Ubicación:</strong> el supervisor autorizado de tu organización podrá
                ver tu posición reciente mientras ACMA esté abierta y visible.
                Se conserva solamente la última posición, no un historial de recorridos.
                Al habilitar los permisos, ACMA recordará tu elección en este dispositivo
                y reanudará el GPS mientras esté abierta. Puedes revocarlo desde
                tu perfil → Mi ubicación.</p>
              <p><strong>Notificaciones:</strong> ACMA solicitará permiso para mostrar avisos
                relacionados con la operación en este equipo.</p>
            </div>
            <p className="mt-3 text-xs leading-5 text-slate-500">
              El sistema Android, Windows, macOS o el navegador controla la autorización.
              Si rechazas un permiso, deberás habilitarlo desde sus ajustes.
              ACMA no utiliza el GPS cuando la aplicación está cerrada o en segundo plano.
            </p>
            {(avisoPermisos || error) && (
              <p role="alert" className="mt-4 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
                {avisoPermisos ?? error}
              </p>
            )}
            <div className="mt-6 flex flex-col gap-3">
              <button type="button" disabled={solicitandoPermisos || ocupado}
                onClick={() => void autorizarPermisosIniciales()}
                className="min-h-12 w-full rounded-xl bg-emerald-800 px-4 py-3 font-bold text-white disabled:opacity-60">
                {solicitandoPermisos || ocupado ? 'Solicitando permisos…' : 'Habilitar ubicación y notificaciones'}
              </button>
              <button type="button" onClick={abrirAjustes}
                className="min-h-11 w-full rounded-xl border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700">
                Revisar permisos en configuración
              </button>
            </div>
          </section>
        </div>
      )}
    </Contexto.Provider>
  )
}
