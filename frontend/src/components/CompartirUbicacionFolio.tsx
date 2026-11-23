/** Compartir mi ubicacion con el folio: consentimiento explicito y opt-out.
 * Compatible con Chrome Android, Safari iOS y WebView que autoriza geolocalizacion.
 * La web NO rastrea con el telefono bloqueado o la aplicacion en segundo plano.
 */
import { useEffect, useRef, useState } from 'react'
import { mensajeDeError } from '../services/api'
import { actualizarRastreoFolio, comenzarRastreoFolio, detenerRastreoFolio } from '../services/rastreoUsuarioFolio'

interface Props { folioId: string }

export function CompartirUbicacionFolio({ folioId }: Props) {
  const [activo, setActivo] = useState(false)
  const [estado, setEstado] = useState('No estás compartiendo tu ubicación.')
  const [error, setError] = useState<string | null>(null)
  const [ocupado, setOcupado] = useState(false)
  const vigilancia = useRef<number | null>(null)
  const temporizador = useRef<ReturnType<typeof setInterval> | null>(null)
  const ultimoGps = useRef<GeolocationPosition | null>(null)
  const enviando = useRef(false)
  const activado = useRef(false)

  function limpiarSensores() {
    activado.current = false
    if (vigilancia.current !== null && typeof navigator !== 'undefined' && navigator.geolocation) {
      navigator.geolocation.clearWatch(vigilancia.current)
    }
    vigilancia.current = null
    if (temporizador.current) clearInterval(temporizador.current)
    temporizador.current = null
    ultimoGps.current = null
  }

  async function detener() {
    limpiarSensores()
    setActivo(false)
    setEstado('Ubicación detenida. Ya no se mostrarán nuevas posiciones.')
    try { await detenerRastreoFolio(folioId) }
    catch (e) { setError('No se pudo confirmar la detención. La posición dejará de mostrarse al caducar: ' + mensajeDeError(e)) }
  }

  async function enviar() {
    const punto = ultimoGps.current
    if (!activado.current || !punto || enviando.current) return
    if (Date.now() - punto.timestamp > 45_000) {
      setEstado('Sin señal GPS reciente; ACMA dejará de mostrar tu posición.')
      return
    }
    enviando.current = true
    try {
      const r = await actualizarRastreoFolio(folioId, punto.coords.latitude,
        punto.coords.longitude, Number.isFinite(punto.coords.accuracy) ? punto.coords.accuracy : null)
      if (activado.current) {
        setEstado('Compartiendo GPS del teléfono · última actualización ' +
          new Date(r.ultima_at ?? Date.now()).toLocaleTimeString())
        setError(null)
      }
    } catch (e) {
      if (activado.current) {
        setError(mensajeDeError(e))
        await detener()
      }
    } finally {
      enviando.current = false
    }
  }

  async function iniciar() {
    if (ocupado || activado.current) return
    setError(null)
    if (!window.isSecureContext || !navigator.geolocation) {
      setError('Para compartir GPS abre ACMA por HTTPS en un teléfono con ubicación habilitada.')
      return
    }
    setOcupado(true)
    try {
      await comenzarRastreoFolio(folioId) // Solo despues del clic voluntario.
      activado.current = true
      setActivo(true)
      setEstado('Esperando permiso y primera posición GPS…')
      vigilancia.current = navigator.geolocation.watchPosition(
        (p) => {
          if (!activado.current) return
          ultimoGps.current = p
          void enviar()
        },
        (e) => {
          setError(e.code === 1 ? 'Permiso de ubicación denegado. Actívalo en el teléfono.'
            : 'No se pudo obtener señal GPS. Revisa la ubicación del teléfono.')
          void detener()
        },
        { enableHighAccuracy: true, maximumAge: 5000, timeout: 20000 },
      )
      temporizador.current = setInterval(() => {
        // Sin nuevas lecturas no renovamos una posición antigua como si fuera actual.
        if (ultimoGps.current && Date.now() - ultimoGps.current.timestamp > 75_000) {
          void detener()
        } else void enviar()
      }, 15_000)
    } catch (e) {
      limpiarSensores()
      setActivo(false)
      setError(mensajeDeError(e))
    } finally {
      setOcupado(false)
    }
  }

  useEffect(() => {
    // Al ocultar o abandonar la página dejamos de compartir inmediatamente.
    const ocultar = () => { if (document.hidden && activado.current) void detener() }
    document.addEventListener('visibilitychange', ocultar)
    return () => {
      document.removeEventListener('visibilitychange', ocultar)
      if (activado.current) {
        limpiarSensores()
        void detenerRastreoFolio(folioId).catch(() => undefined)
      }
    }
    // La pagina del folio conserva identidad durante esta sesion.
  }, [folioId])

  return (
    <section className="rounded-xl border border-sky-200 bg-white p-4" data-testid="compartir-gps-folio">
      <h2 className="font-semibold text-slate-900">Compartir mi ubicación para este folio</h2>
      <p className="mt-1 text-sm text-slate-600">
        Solo tú puedes activarla desde tu Android o iPhone. La verá el personal autorizado
        del prestador mientras mantengas esta pantalla abierta; podrás detenerla cuando quieras.
        No se guarda un historial de recorrido y, si no hay señal durante 90 segundos,
        tu posición deja de aparecer en el mapa.
      </p>
      <p className="mt-2 text-sm" role="status">{estado}</p>
      {error && <p className="mt-2 text-sm text-red-700" role="alert">{error}</p>}
      {activo
        ? <button type="button" className="mt-3 min-h-12 w-full rounded-lg bg-rose-700 px-4 py-2 font-semibold text-white"
            onClick={() => void detener()}>Dejar de compartir ubicación</button>
        : <button type="button" disabled={ocupado}
            className="mt-3 min-h-12 w-full rounded-lg bg-sky-800 px-4 py-2 font-semibold text-white disabled:opacity-50"
            onClick={() => void iniciar()}>{ocupado ? 'Activando GPS…' : 'Compartir mi ubicación ahora'}</button>}
      <p className="mt-2 text-xs text-slate-500">
        En navegadores y WebView, iOS y Android pueden suspender el GPS al bloquear el teléfono o cambiar de app.
        Esto no habilita seguimiento oculto ni en segundo plano.
      </p>
    </section>
  )
}
