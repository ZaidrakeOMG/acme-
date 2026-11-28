/** Contexto persistente: GPS voluntario del usuario, independiente de la ruta React.
 * Funciona mientras ACMA está visible, incluso al navegar entre páginas.
 * No intenta geolocalizar con el móvil bloqueado ni en segundo plano.
 */
import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from 'react'
import { useAuth } from './AuthContext'
import { createPortal } from 'react-dom'
import { mensajeDeError } from '../services/api'
import { registrarPush } from '../services/campo'
import { consultarMiUbicacion, detenerMiUbicacion, enviarMiUbicacion, iniciarMiUbicacion } from '../services/rastreoUsuarios'

type Estado = {
  activo: boolean
  bloqueado: boolean
  gpsObligatorio: boolean
  ocupado: boolean
  mensaje: string
  error: string | null
  iniciar: () => Promise<void>
  detener: () => Promise<void>
}
const Contexto = createContext<Estado | null>(null)

// Solo las cuentas que realizan trabajo de campo deben completar el alta de GPS.
// Superadmin, administradores y supervisores consultan a su personal desde PC:
// no se les debe bloquear el portal ni pedir su propia ubicación.
export const requierePermisosDeCampo = (rol: string): boolean =>
  ['tecnico', 'operador', 'admin_un'].includes(rol)

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
  const { usuario, cerrarSesion } = useAuth()
  const gpsObligatorio = usuario?.rol === 'tecnico'
  const [solicitudVisible, setSolicitudVisible] = useState(false)
  const [solicitandoPermisos, setSolicitandoPermisos] = useState(false)
  const [avisoPermisos, setAvisoPermisos] = useState<string | null>(null)
  const [activo, setActivo] = useState(false)
  const [gpsConfirmado, setGpsConfirmado] = useState(false)
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
  const suspendidoRef = useRef(false)
  const gpsNativoRef = useRef<{ autorizado: boolean; servicioActivo: boolean } | null>(null)
  const pausandoRef = useRef<Promise<unknown> | null>(null)
  const generacionRef = useRef(0)
  const saliendoRef = useRef(false)

  function limpiarSensores() {
    generacionRef.current += 1
    activoRef.current = false
    if (vigilando.current != null && navigator.geolocation) navigator.geolocation.clearWatch(vigilando.current)
    vigilando.current = null
    if (intervalo.current) clearInterval(intervalo.current)
    intervalo.current = null
    ultimaPosicion.current = null
    ultimoEnvio.current = 0
    setActivo(false)
    setGpsConfirmado(false)
  }

  async function pausar() {
    if (!activoRef.current) return
    limpiarSensores()
    setMensaje('Ubicación pausada hasta regresar a ACMA.')
    const tarea = detenerMiUbicacion().catch(() => undefined)
    pausandoRef.current = tarea
    try { await tarea } finally { if (pausandoRef.current === tarea) pausandoRef.current = null }
  }

  async function detener() {
    // El perfil técnico corporativo no tiene un interruptor interno de GPS.
    // Cerrar sesión y los ajustes del sistema siguen disponibles.
    if (gpsObligatorio) return
    // Revocación explícita para los demás perfiles.
    if (usuario?.id) guardarConsentimiento(usuario.id, false)
    limpiarSensores()
    setSolicitudVisible(true)
    setMensaje('Ubicación detenida. No se enviarán nuevos puntos.')
    const tarea = detenerMiUbicacion()
    pausandoRef.current = tarea
    try { await tarea }
    catch { setError('No se pudo confirmar la detención. La última ubicación dejará de mostrarse en 90 segundos.') }
    finally { if (pausandoRef.current === tarea) pausandoRef.current = null }
  }

  async function transmitir() {
    const p = ultimaPosicion.current
    if (!activoRef.current || !p || enviando.current) return
    if (Date.now() - p.timestamp > 45000) {
      setMensaje('Esperando GPS reciente; no se envía una coordenada antigua.')
      return
    }
    if (Date.now() - ultimoEnvio.current < 12000) return
    const generacion = generacionRef.current
    enviando.current = true
    ultimoEnvio.current = Date.now()
    try {
      const accuracy = Number.isFinite(p.coords.accuracy) && p.coords.accuracy <= 1000000
        ? p.coords.accuracy : null
      const r = await enviarMiUbicacion(p.coords.latitude, p.coords.longitude, accuracy)
      if (activoRef.current && generacion === generacionRef.current) {
        setGpsConfirmado(true)
        setMensaje('Compartiendo GPS · última actualización: ' +
          new Date(r.ultima_at ?? Date.now()).toLocaleTimeString())
        setError(null)
      }
    } catch (e) {
      if (activoRef.current && generacion === generacionRef.current) {
        setError(mensajeDeError(e))
        await pausar()
        setAvisoPermisos('Error de conexión al enviar ubicación. Se reanudará al volver a abrir ACMA.')
      }
    } finally { enviando.current = false }
  }

  async function iniciar() {
    if (iniciandoRef.current || activoRef.current || saliendoRef.current || suspendidoRef.current || document.hidden) return
    iniciandoRef.current = true
    const generacion = generacionRef.current
    setError(null)
    if (!window.isSecureContext || !('geolocation' in navigator)) {
      setError('Se requiere HTTPS y servicios de ubicación activos en PC, Android o iPhone.')
      iniciandoRef.current = false
      return
    }
    setOcupado(true)
    try {
      if (pausandoRef.current) await pausandoRef.current.catch(() => undefined)
      if (generacion !== generacionRef.current || suspendidoRef.current || saliendoRef.current) return
      if (gpsNativoRef.current && (!gpsNativoRef.current.autorizado || !gpsNativoRef.current.servicioActivo)) {
        throw new Error('Enciende la ubicación de Android y autoriza el permiso de ACMA.')
      }
      // Primero solicitar permiso desde el clic REAL: iOS Safari pierde
      // activación del usuario si esperamos una llamada HTTP antes del prompt.
      const primera = await new Promise<GeolocationPosition>((resolve, reject) => {
        navigator.geolocation.getCurrentPosition(resolve, reject, {
          enableHighAccuracy: true, maximumAge: 5000, timeout: 20000,
        })
      })
      if (generacion !== generacionRef.current || suspendidoRef.current || saliendoRef.current || document.hidden) return
      // Solo después del permiso se registra el consentimiento en el servidor.
      await iniciarMiUbicacion(detectarDispositivo())
      if (generacion !== generacionRef.current || suspendidoRef.current || saliendoRef.current || document.hidden) {
        await detenerMiUbicacion().catch(() => undefined)
        return
      }
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
          setAvisoPermisos('No se recibe una ubicación reciente. Comprueba el GPS y vuelve a intentarlo.')
          setSolicitudVisible(true)
          void pausar()
        } else void transmitir()
      }, 15000)
    } catch (e) {
      if (generacion !== generacionRef.current || saliendoRef.current) return
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


  // El puente nativo verifica permiso y el interruptor global de ubicación por separado.
  // Las APK antiguas no tienen este mensaje: siguen utilizando geolocalización web.
  function consultarGpsNativo(solicitar = false): Promise<boolean | null> {
    const w = window as Window & {
      AcmaPermisos?: { postMessage: (mensaje: string) => void }
      __acmaGpsNativoDisponible?: boolean
    }
    if (!w.AcmaPermisos || !w.__acmaGpsNativoDisponible) return Promise.resolve(null)
    return new Promise(resolve => {
      const terminar = (resultado: boolean | null) => {
        clearTimeout(timer)
        window.removeEventListener('acma:estado-gps', recibido)
        resolve(resultado)
      }
      const recibido = (evento: Event) => {
        const d = (evento as CustomEvent<{ autorizado: boolean; servicioActivo: boolean }>).detail
        if (!d) return
        gpsNativoRef.current = d
        terminar(d.autorizado && d.servicioActivo)
      }
      const timer = setTimeout(() => terminar(false), solicitar ? 30000 : 4000)
      window.addEventListener('acma:estado-gps', recibido)
      try { w.AcmaPermisos!.postMessage(solicitar ? 'solicitar_ubicacion' : 'consultar_ubicacion') }
      catch { terminar(false) }
    })
  }

  async function autorizarPermisosIniciales() {
    if (solicitandoPermisos) return
    setSolicitandoPermisos(true)
    setAvisoPermisos(null)
    try {
      // PRIMERO notificaciones: en Chrome y Edge requieren gesto humano.
      const recordado = !!usuario?.id && tieneConsentimiento(usuario.id)
      const notificaciones = recordado && gpsObligatorio ? true : recordado ? (await solicitarNotificaciones(true) || await solicitarNotificaciones()) : await solicitarNotificaciones()
      if (!notificaciones) {
        setAvisoPermisos('Notificaciones rechazadas. Habilítalas en los ajustes del teléfono o navegador para continuar.')
        return
      }
      const nativo = await consultarGpsNativo(true)
      if (nativo === false) {
        setAvisoPermisos('Activa Ubicación en los ajustes rápidos de Android y permite el acceso a ACMA. Después pulsa Reintentar GPS.')
        return
      }
      // Después se abre el diálogo de ubicación del propio sistema si hace falta.
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
    if (!tieneConsentimiento(id) || iniciandoRef.current || activoRef.current || suspendidoRef.current || saliendoRef.current) return
    const generacion = generacionRef.current
    try {
      // Sólo consultar permisos previamente aprobados: no abrir diálogos
      // del SO al recuperar la sesión.
      if (!gpsObligatorio && !await solicitarNotificaciones(true)) {
        setSolicitudVisible(true)
        setAvisoPermisos('Las notificaciones ya no están permitidas. Revisa los ajustes del dispositivo.')
        return
      }
      if (document.hidden || suspendidoRef.current || generacion !== generacionRef.current || saliendoRef.current) return
      const nativo = await consultarGpsNativo()
      if (generacion !== generacionRef.current || suspendidoRef.current || saliendoRef.current) return
      if (nativo === false) {
        setSolicitudVisible(true)
        setAvisoPermisos('La ubicación de Android está apagada o ACMA no tiene permiso. Actívala para continuar.')
        return
      }
      // Evitar que el navegador muestre un nuevo diálogo automático si
      // su autorización de ubicación caducó o fue revocada.
      if (nativo === null && navigator.permissions?.query) {
        try {
          const gps = await navigator.permissions.query({ name: 'geolocation' })
          if (gps.state !== 'granted') {
            setSolicitudVisible(true)
            setAvisoPermisos('Es necesario volver a permitir ubicación en este dispositivo.')
            return
          }
        } catch { /* Algunos WebView no implementan Permissions API. */ }
      }
      if (generacion !== generacionRef.current || suspendidoRef.current || saliendoRef.current) return
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
    if (!id || !requierePermisosDeCampo(usuario.rol)) {
      // Las cuentas de administración no deben quedar atrapadas en un
      // diálogo de GPS al entrar a formularios, usuarios o reportes.
      setSolicitudVisible(false)
      setAvisoPermisos(null)
      return
    }
    suspendidoRef.current = document.hidden
    saliendoRef.current = false
    setAvisoPermisos(null)
    setError(null)
    let vigente = true
    if (tieneConsentimiento(id)) {
      setSolicitudVisible(false)
      // El primer montaje de StrictMode se desmonta antes de esta microtarea.
      void Promise.resolve().then(() => { if (vigente) void reanudarSiRecordado(id) })
    } else {
      setSolicitudVisible(true)
    }
    return () => { vigente = false }
  }, [usuario?.id, usuario?.rol])

  useEffect(() => {
    let presente = true
    // React solo recupera GPS cuando hay consentimiento persistido por usuario.
    void consultarMiUbicacion().then(r => {
      if (presente && r.compartiendo) {
        setMensaje('Hay una activación anterior reciente. Pulsa Activar para iniciar aquí.')
      }
    }).catch(() => undefined)
    const suspender = () => {
      suspendidoRef.current = true
      if (activoRef.current) void pausar()
      else if (iniciandoRef.current) generacionRef.current += 1
    }
    const reanudar = () => {
      if (document.hidden) return
      suspendidoRef.current = false
      if (usuario?.id && tieneConsentimiento(usuario.id) && !activoRef.current) {
        setSolicitudVisible(false)
        setAvisoPermisos(null)
        setError(null)
      }
      if (usuario?.id && requierePermisosDeCampo(usuario.rol) && tieneConsentimiento(usuario.id)) {
        void reanudarSiRecordado(usuario.id)
      }
    }
    const ocultar = () => document.hidden ? suspender() : reanudar()
    const estadoNativo = (evento: Event) => {
      const d = (evento as CustomEvent<{ autorizado: boolean; servicioActivo: boolean }>).detail
      if (!d || !gpsObligatorio || suspendidoRef.current || saliendoRef.current) return
      gpsNativoRef.current = d
      if (!d.autorizado || !d.servicioActivo) {
        setAvisoPermisos('GPS desactivado. Enciende Ubicación en Android y permite el acceso a ACMA.')
        setSolicitudVisible(true)
        if (activoRef.current) void pausar()
        else if (iniciandoRef.current) generacionRef.current += 1
      }
    }
    const revisarGps = () => {
      if (!gpsObligatorio || document.hidden || suspendidoRef.current || saliendoRef.current || iniciandoRef.current || !activoRef.current) return
      void consultarGpsNativo().then(ok => {
        if (!presente || suspendidoRef.current || saliendoRef.current || ok !== false) return
        setSolicitudVisible(true)
        setAvisoPermisos('No se pudo verificar el GPS de Android. Revisa Ubicación y vuelve a intentar.')
        void pausar()
      })
    }
    const revision = setInterval(revisarGps, 5000)
    let permisoWeb: PermissionStatus | null = null
    const cambioPermiso = () => {
      if (gpsObligatorio && permisoWeb?.state === 'denied' && !suspendidoRef.current && activoRef.current) {
        setSolicitudVisible(true)
        setAvisoPermisos('Permiso de ubicación revocado. Autorízalo para continuar.')
        void pausar()
      }
    }
    if (gpsObligatorio && navigator.permissions?.query) {
      void navigator.permissions.query({ name: 'geolocation' }).then(p => {
        if (!presente) return
        permisoWeb = p
        p.addEventListener?.('change', cambioPermiso)
      }).catch(() => undefined)
    }
    const salir = () => {
      if (activoRef.current) {
        limpiarSensores()
        void detenerMiUbicacion().catch(() => undefined)
      }
    }
    document.addEventListener('visibilitychange', ocultar)
    window.addEventListener('acma:resume', reanudar)
    window.addEventListener('acma:pause', suspender)
    window.addEventListener('acma:estado-gps', estadoNativo)
    window.addEventListener('pagehide', salir)
    return () => {
      presente = false
      document.removeEventListener('visibilitychange', ocultar)
      window.removeEventListener('acma:resume', reanudar)
      window.removeEventListener('acma:pause', suspender)
      window.removeEventListener('acma:estado-gps', estadoNativo)
      window.removeEventListener('pagehide', salir)
      permisoWeb?.removeEventListener?.('change', cambioPermiso)
      clearInterval(revision)
      saliendoRef.current = true
      generacionRef.current += 1
      suspender()
      salir()
    }
  }, [])

  const bloqueado = !!usuario && (gpsObligatorio ? !activo || !gpsConfirmado : !activo && solicitudVisible)
  const recordado = !!usuario?.id && tieneConsentimiento(usuario.id)
  const recuperacion = recordado && gpsObligatorio
  const comprobando = recuperacion && (!solicitudVisible && !avisoPermisos && !error || solicitandoPermisos || ocupado || (activo && !gpsConfirmado))
  async function salirSinGps() {
    saliendoRef.current = true
    generacionRef.current += 1
    await pausar()
    await cerrarSesion()
  }

  return (
    <Contexto.Provider value={{ activo, bloqueado, gpsObligatorio, ocupado, mensaje, error, iniciar, detener }}>
      {children}
      {bloqueado && createPortal(
        <div className="fixed inset-0 z-[1100] flex items-center justify-center overflow-y-auto bg-slate-950/90 p-4"
          data-testid="solicitud-ubicacion-inicio">
          <section role="dialog" aria-modal="true" aria-labelledby="acma-permisos-titulo"
            style={{ width: 'min(100%, 32rem)', maxHeight: 'calc(100vh - 2rem)', overflowY: 'auto' }}
            className="rounded-3xl border border-emerald-200 bg-white p-5 shadow-2xl sm:p-8">
            <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-emerald-100">
              <span className="text-3xl font-bold text-emerald-800" aria-hidden="true">+</span>
            </div>
            <h2 id="acma-permisos-titulo" className="text-xl font-extrabold text-slate-900 sm:text-2xl">
              {comprobando ? 'Conectando con GPS…' : recuperacion ? 'Ubicación necesaria para continuar' : 'Permisos necesarios para usar ACMA'}
            </h2>
            <p className="mt-3 text-sm leading-6 text-slate-700">
              {comprobando ? 'Verificando la ubicación autorizada del dispositivo.' : recuperacion
                ? 'Activa la ubicación del teléfono para continuar trabajando.'
                : usuario?.nombre + ', ACMA requiere que habilites la ubicación y las notificaciones de este dispositivo para acceder a la plataforma.'}
            </p>
            {!recuperacion && <><div data-testid="aviso-inicial-gps" className="mt-4 space-y-3 rounded-xl bg-slate-50 p-4 text-sm text-slate-700">
              <p><strong>Ubicación:</strong> el supervisor autorizado de tu organización podrá
                ver tu posición reciente mientras ACMA esté abierta y visible.
                Se conserva solamente la última posición, no un historial de recorridos.
                Al habilitar los permisos, ACMA recordará tu elección en este dispositivo
                y reanudará el GPS mientras esté abierta. {gpsObligatorio
                  ? 'En equipos corporativos el perfil técnico no tiene un interruptor interno de GPS. Puedes cerrar sesión o gestionar el permiso desde los ajustes del sistema.'
                  : 'Puedes retirar tu autorización desde tu perfil → Mi ubicación.'}</p>
              <p><strong>Notificaciones:</strong> ACMA solicitará permiso para mostrar avisos
                relacionados con la operación en este equipo.</p>
            </div>
            <p className="mt-3 text-xs leading-5 text-slate-500">
              El sistema Android, Windows, macOS o el navegador controla la autorización.
              Si rechazas un permiso, deberás habilitarlo desde sus ajustes.
              ACMA no utiliza el GPS cuando la aplicación está cerrada o en segundo plano.
            </p></>}
            {(avisoPermisos || error) && (
              <p role="alert" className="mt-4 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
                {avisoPermisos ?? error}
              </p>
            )}
            <div className="mt-6 flex flex-col gap-3">
              {!comprobando && <><button type="button" disabled={solicitandoPermisos || ocupado || (activo && !gpsConfirmado)}
                onClick={() => void autorizarPermisosIniciales()}
                className="min-h-12 w-full rounded-xl bg-emerald-800 px-4 py-3 font-bold text-white disabled:opacity-60">
                {solicitandoPermisos || ocupado || (activo && !gpsConfirmado) ? 'Comprobando ubicación…' : recuperacion ? 'Reintentar GPS' : 'Habilitar ubicación y notificaciones'}
              </button>
              <button type="button" onClick={abrirAjustes}
                className="min-h-11 w-full rounded-xl border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700">
                Revisar permisos en configuración
              </button></>}
              <button type="button" onClick={() => void salirSinGps()}
                className="min-h-11 w-full rounded-xl px-4 py-2 text-sm font-semibold text-slate-600">
                Cerrar sesión
              </button>
            </div>
          </section>
        </div>, document.body
      )}
    </Contexto.Provider>
  )
}
