import { useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router'
import { useAuth } from '../contexts/AuthContext'
import { ErrorAPI, mensajeDeError } from '../services/api'
import { crearYSeguirFolioDemo, consultarSeguimientoFolioDemo, type SeguimientoFolioDemo } from '../services/testbotEscriturasDemo'
import { reporteTestBotTXT } from '../services/testbotReporte'
import { abrirCanalGpsDemo, type EventoGpsDemo, type PuntoGpsDemo } from '../services/testbotGpsDemo'
import { ejecutarPasoDemo, INICIAL_DEMO, PASOS_DEMO, type ProgresoDemo } from '../services/testbotFlujoDemo'
import { INICIAL_RECORRIDO, SECUENCIA_ACMA, guardarResultado, probarModuloDemo, type EstadoRecorrido } from '../services/testbotSecuencia'

const boton = 'rounded-xl px-3 py-2 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-50'
const botonSecundario = boton + ' border border-slate-200 bg-white text-slate-700 hover:bg-slate-50'
const clave = (usuarioId: string) => 'acma.testbot.formularios.v2.' + usuarioId

function cargar(usuarioId: string): ProgresoDemo {
  try {
    const actual = JSON.parse(localStorage.getItem(clave(usuarioId)) || 'null') as Partial<ProgresoDemo> | null
    if (actual && typeof actual.paso === 'number') {
      return { paso: Math.max(0, Math.min(PASOS_DEMO.length, Math.floor(actual.paso))),
        formularioId: typeof actual.formularioId === 'string' ? actual.formularioId : null,
        respuestaId: typeof actual.respuestaId === 'string' ? actual.respuestaId : null }
    }
    // La versión anterior dejó registros posibles, pero su estado era incompleto.
    // Revalidamos desde paso cero antes de reutilizar cualquier ID previo.
    const anterior = JSON.parse(localStorage.getItem('acma.testbot.formularios.v1.' + usuarioId) || 'null') as Partial<ProgresoDemo> | null
    return { paso: 0,
      formularioId: typeof anterior?.formularioId === 'string' ? anterior.formularioId : null,
      respuestaId: typeof anterior?.respuestaId === 'string' ? anterior.respuestaId : null }
  } catch { return { ...INICIAL_DEMO } }
}
function guardarLocal(usuarioId: string, p: ProgresoDemo) {
  try { localStorage.setItem(clave(usuarioId), JSON.stringify(p)) } catch { /* el modo temporal no interrumpe la prueba */ }
}
const claveRecorrido = (usuarioId: string) => 'acma.testbot.secuencia.v1.' + usuarioId
function leerRecorrido(usuarioId: string): EstadoRecorrido {
  try {
    const guardado = JSON.parse(localStorage.getItem(claveRecorrido(usuarioId)) || 'null') as EstadoRecorrido | null
    if (!guardado || !Number.isInteger(guardado.indice) || guardado.indice < 0 ||
        guardado.indice > SECUENCIA_ACMA.length || !Array.isArray(guardado.resultados)) {
      return { ...INICIAL_RECORRIDO, resultados: [] }
    }
    return guardado
  } catch {
    return { ...INICIAL_RECORRIDO, resultados: [] }
  }
}
function persistirRecorrido(usuarioId: string, estado: EstadoRecorrido) {
  try { localStorage.setItem(claveRecorrido(usuarioId), JSON.stringify(estado)) }
  catch { /* sin almacenamiento: el recorrido continúa en esta sesión */ }
}
function errorLegible(error: unknown): string {
  if (error instanceof ErrorAPI) return mensajeDeError(error)
  if (error instanceof Error) return error.message
  return mensajeDeError(error)
}
function ayudaPorRuta(pathname: string): string {
  if (pathname.startsWith('/formularios/constructor')) return 'Puedo completar los campos y probar la publicación de este formulario DEMO.'
  if (pathname.startsWith('/mis-formularios')) return 'Aquí puedes iniciar, reanudar y consultar formularios publicados.'
  if (pathname.startsWith('/catalogos')) return 'Los catálogos vinculan equipos, técnicos, tipos de falla y severidades.'
  if (pathname.startsWith('/folios')) return 'Un folio permite documentar y dar seguimiento a un servicio.'
  return '¿Necesitas ayuda para trabajar con ACMA?'
}

/** Asistente visual; el ejecutor opera exclusivamente sobre el cliente y prestador DEMO. */
export function TestBotAcma() {
  const { usuario } = useAuth()
  const navegar = useNavigate()
  const { pathname } = useLocation()
  const usuarioId = usuario?.id ?? ''
  const esSuperadmin = usuario?.rol === 'superadmin'
  const [abierto, setAbierto] = useState(false)
  const [oculto, setOculto] = useState(false)
  const [sugerencia, setSugerencia] = useState(true)
  const [modo, setModo] = useState<'ayuda' | 'pruebas'>('ayuda')
  const [progreso, setProgreso] = useState<ProgresoDemo>(() => cargar(usuarioId))
  const [recorrido, setRecorrido] = useState<EstadoRecorrido>(() => leerRecorrido(usuarioId))
  const [reintentados, setReintentados] = useState<string[]>([])
  const [ocupado, setOcupado] = useState(false)
  const [permitirEscrituras, setPermitirEscrituras] = useState(false)
  const [mensaje, setMensaje] = useState('')
  const [historial, setHistorial] = useState<string[]>([])
  const [folioRastreado, setFolioRastreado] = useState<SeguimientoFolioDemo | null>(null)
  const [rastreoActivo, setRastreoActivo] = useState(false)
  const [errorRastreo, setErrorRastreo] = useState<string | null>(null)
  const [gpsDemoActivo, setGpsDemoActivo] = useState(false)
  const [gpsDemoUltimo, setGpsDemoUltimo] = useState<PuntoGpsDemo | null>(null)
  const [gpsDemoError, setGpsDemoError] = useState<string | null>(null)
  const gpsWatchRef = useRef<number | null>(null)
  const canalGpsRef = useRef<BroadcastChannel | null>(null)
  const ultimoGpsRef = useRef<PuntoGpsDemo | null>(null)
  const [mascotaFallida, setMascotaFallida] = useState(false)
  const progresoRef = useRef<ProgresoDemo>(progreso)
  const bloqueado = useRef(false)

  useEffect(() => {
    const guardado = cargar(usuarioId)
    progresoRef.current = guardado
    setProgreso(guardado)
    setRecorrido(leerRecorrido(usuarioId))
    setReintentados([])
    setMensaje('')
    setHistorial([])
    setFolioRastreado(null)
    setRastreoActivo(false)
    setErrorRastreo(null)
    setGpsDemoActivo(false)
    setGpsDemoUltimo(null)
    setGpsDemoError(null)
    setOcupado(false)
    bloqueado.current = false
  }, [usuarioId])

  // Canal del navegador: compartir la prueba con OTRAS pestañas de ACMA,
  // sin persistir ni enviar posiciones al servidor.
  useEffect(() => {
    if (!esSuperadmin || !usuarioId) return
    const canal = abrirCanalGpsDemo()
    canalGpsRef.current = canal
    const responderSolicitud = (evento: MessageEvent<EventoGpsDemo>) => {
      if (evento.data?.tipo === 'solicitud' && evento.data.usuarioId === usuarioId &&
          ultimoGpsRef.current) canal?.postMessage(ultimoGpsRef.current)
    }
    canal?.addEventListener('message', responderSolicitud)
    return () => {
      if (gpsWatchRef.current != null && navigator.geolocation) {
        navigator.geolocation.clearWatch(gpsWatchRef.current)
      }
      gpsWatchRef.current = null
      canal?.postMessage({ tipo: 'detener', usuarioId } satisfies EventoGpsDemo)
      canal?.removeEventListener('message', responderSolicitud)
      canal?.close()
      canalGpsRef.current = null
      ultimoGpsRef.current = null
    }
  }, [usuarioId, esSuperadmin])

  function detenerGpsPersonal() {
    if (gpsWatchRef.current != null && navigator.geolocation) {
      navigator.geolocation.clearWatch(gpsWatchRef.current)
    }
    gpsWatchRef.current = null
    ultimoGpsRef.current = null
    canalGpsRef.current?.postMessage({ tipo: 'detener', usuarioId } satisfies EventoGpsDemo)
    setGpsDemoActivo(false)
    setGpsDemoUltimo(null)
    setGpsDemoError(null)
    registrar('GPS personal DEMO detenido; no se guardaron coordenadas en el servidor.')
  }

  function iniciarGpsPersonal() {
    if (!esSuperadmin || !folioRastreado || gpsWatchRef.current != null) return
    if (!navigator.geolocation) {
      setGpsDemoError('Este navegador no ofrece geolocalización. Prueba desde un teléfono con GPS.')
      return
    }
    if (!canalGpsRef.current) {
      setGpsDemoError('Este navegador no permite comunicar GPS entre las pestañas de ACMA.')
      return
    }
    setGpsDemoError(null)
    setGpsDemoActivo(true)
    const folioId = folioRastreado.id
    const numero = folioRastreado.numero
    gpsWatchRef.current = navigator.geolocation.watchPosition(
      (posicion) => {
        if (!Number.isFinite(posicion.coords.latitude) || !Number.isFinite(posicion.coords.longitude)) return
        const punto: PuntoGpsDemo = {
          tipo: 'posicion', usuarioId, folioId, numero,
          lat: posicion.coords.latitude, lng: posicion.coords.longitude,
          precisionM: Number.isFinite(posicion.coords.accuracy) ? posicion.coords.accuracy : null,
          capturadaAt: new Date(posicion.timestamp).toISOString(),
        }
        ultimoGpsRef.current = punto
        setGpsDemoUltimo(punto)
        setGpsDemoError(null)
        canalGpsRef.current?.postMessage(punto)
      },
      (error) => {
        const permisoDenegado = error.code === 1
        setGpsDemoError(permisoDenegado
          ? 'No se permitió la ubicación. Actívala en el candado de Chrome y vuelve a iniciar la prueba.'
          : 'Todavía no llega una ubicación GPS. Revisa permisos, señal y precisión del dispositivo.')
        if (permisoDenegado && gpsWatchRef.current != null) {
          navigator.geolocation.clearWatch(gpsWatchRef.current)
          gpsWatchRef.current = null
          setGpsDemoActivo(false)
        }
      },
      { enableHighAccuracy: true, maximumAge: 10000, timeout: 20000 },
    )
    registrar('Iniciada solicitud de GPS personal DEMO para ' + numero +
      '; se mostrará solo en las pestañas de este navegador.')
  }

  function actualizar(p: ProgresoDemo) {
    progresoRef.current = p
    setProgreso(p)
    guardarLocal(usuarioId, p)
  }
  function registrar(texto: string) {
    setMensaje(texto)
    setHistorial((anterior) => [...anterior, texto].slice(-100))
  }

  async function ejecutar(todo: boolean) {
    if (!esSuperadmin || bloqueado.current) return
    bloqueado.current = true
    setOcupado(true)
    setMensaje('')
    let actual = progresoRef.current
    try {
      while (actual.paso < PASOS_DEMO.length) {
        registrar('Ejecutando prueba ' + (actual.paso + 1) + ' de ' + PASOS_DEMO.length + '…')
        const resultado = await ejecutarPasoDemo(actual, (checkpoint) => {
          actualizar(checkpoint)
          actual = checkpoint
        })
        actual = resultado.progreso
        actualizar(actual)
        registrar('✓ ' + resultado.mensaje)
        if (!todo) {
          if (actual.paso === 1 && actual.formularioId) {
            // Mostrar en pantalla los cuatro campos ahora guardados.
            navegar('/formularios/constructor/' + actual.formularioId)
          }
          break
        }
      }
      if (todo && actual.paso === PASOS_DEMO.length) {
        navegar('/mis-formularios')
        registrar('Todas las pruebas de Formularios dinámicos finalizaron. Abriendo Mis formularios.')
      }
    } catch (e) {
      registrar('ERROR: ' + errorLegible(e))
    } finally {
      setOcupado(false)
      bloqueado.current = false
    }
  }

  async function siguienteDeACMA() {
    if (!esSuperadmin || bloqueado.current || progresoRef.current.paso !== PASOS_DEMO.length) return
    const actual = SECUENCIA_ACMA[recorrido.indice]
    if (!actual) return
    bloqueado.current = true
    setOcupado(true)
    setMensaje('Comprobando ' + actual.nombre + '…')
    try {
      const resultado = await probarModuloDemo(actual.id, permitirEscrituras)
      const actualizado = guardarResultado(recorrido, resultado)
      setRecorrido(actualizado)
      persistirRecorrido(usuarioId, actualizado)
      registrar((resultado.estado === 'error' ? '✗ ' : resultado.estado === 'consulta_verificada' ? '✓ ' : '• ') +
        actual.nombre + ': ' + resultado.mensaje)
      navegar(actual.ruta)
    } catch (e) {
      registrar('No se pudo guardar la prueba de ' + actual.nombre + ': ' + errorLegible(e))
    } finally {
      bloqueado.current = false
      setOcupado(false)
    }
  }

  async function ejecutarRecorridoCompleto(reiniciar = false) {
    if (!esSuperadmin || !permitirEscrituras || bloqueado.current ||
        progresoRef.current.paso !== PASOS_DEMO.length) return
    bloqueado.current = true
    setOcupado(true)
    let avance: EstadoRecorrido = reiniciar ? { ...INICIAL_RECORRIDO, resultados: [] } : recorrido
    if (reiniciar) {
      setRecorrido(avance)
      persistirRecorrido(usuarioId, avance)
      setReintentados([])
    }
    try {
      while (avance.indice < SECUENCIA_ACMA.length) {
        const actual = SECUENCIA_ACMA[avance.indice]!
        setMensaje('Probando datos ficticios de ' + actual.nombre + ' (' +
          (avance.indice + 1) + '/' + SECUENCIA_ACMA.length + ')…')
        // El test guarda su propio resultado incluso cuando una ruta falla.
        const resultado = await probarModuloDemo(actual.id, true)
        avance = guardarResultado(avance, resultado)
        setRecorrido(avance)
        persistirRecorrido(usuarioId, avance)
        registrar((resultado.estado === 'error' ? '✗ ' : '• ') + actual.nombre + ': ' + resultado.mensaje)
      }
      registrar('Recorrido DEMO terminado: revisa resultados; módulos sin ejecutor y roles ajenos siguen pendientes.')
    } catch (e) {
      registrar('El recorrido quedó guardado para reanudar: ' + errorLegible(e))
    } finally {
      setOcupado(false)
      bloqueado.current = false
    }
  }

  async function volverAErrores() {
    if (!esSuperadmin || bloqueado.current) return
    const primerError = recorrido.resultados.find((r) => r.estado === 'error' && !reintentados.includes(r.id))
    if (!primerError) {
      setReintentados([])
      setMensaje('Revisión reiniciada: podrás volver a comprobar los errores pendientes.')
      return
    }
    bloqueado.current = true
    setOcupado(true)
    try {
      setMensaje('Revisando de nuevo ' + primerError.nombre + '…')
      const resultado = await probarModuloDemo(primerError.id, permitirEscrituras)
      const actualizado = { ...recorrido, resultados: recorrido.resultados.map((r) =>
        r.id === resultado.id ? resultado : r) }
      setRecorrido(actualizado)
      persistirRecorrido(usuarioId, actualizado)
      setReintentados((anteriores) => [...anteriores, primerError.id])
      registrar((resultado.estado === 'error' ? '✗ ' : '✓ ') + primerError.nombre + ': ' + resultado.mensaje)
      navegar(SECUENCIA_ACMA.find((m) => m.id === primerError.id)?.ruta ?? '/')
    } catch (e) {
      setMensaje('No se pudo repetir la comprobación: ' + errorLegible(e))
    } finally {
      bloqueado.current = false
      setOcupado(false)
    }
  }


  // El estado del folio se refresca sin inventar posiciones ni simular cuentas Técnico.
  useEffect(() => {
    if (!rastreoActivo || !abierto || modo !== 'pruebas' || !esSuperadmin) return
    let vigente = true
    const consultar = async () => {
      try {
        const f = await consultarSeguimientoFolioDemo()
        if (!vigente) return
        if (f) { setFolioRastreado(f); setErrorRastreo(null) }
        else setErrorRastreo('El folio TESTBOT DEMO no aparece en la consulta del servidor.')
      } catch (e) {
        if (vigente) setErrorRastreo(errorLegible(e))
      }
    }
    void consultar()
    const intervalo = setInterval(() => void consultar(), 12000)
    return () => { vigente = false; clearInterval(intervalo) }
  }, [rastreoActivo, abierto, modo, esSuperadmin])

  async function empezarRastreo() {
    if (!esSuperadmin || !permitirEscrituras || bloqueado.current) return
    bloqueado.current = true
    setOcupado(true)
    setErrorRastreo(null)
    try {
      const f = await crearYSeguirFolioDemo()
      setFolioRastreado(f)
      setRastreoActivo(true)
      registrar('Folio ficticio rastreable: ' + f.numero + ' · ' + f.id + ' · estado ' + f.estado)
    } catch (e) {
      const error = errorLegible(e)
      setErrorRastreo(error)
      registrar('ERROR seguimiento de folio DEMO: ' + error)
    } finally {
      setOcupado(false)
      bloqueado.current = false
    }
  }

  function descargarDiagnostico() {
    const informe = reporteTestBotTXT(recorrido, progreso.paso, historial, folioRastreado)
    const archivo = new Blob(['\uFEFF' + informe], { type: 'text/plain;charset=utf-8' })
    const url = URL.createObjectURL(archivo)
    const enlace = document.createElement('a')
    enlace.href = url
    enlace.download = 'ACMA_TESTBOT_LOG_' + new Date().toISOString().replace(/[:.]/g, '-') + '.txt'
    document.body.appendChild(enlace)
    enlace.click()
    enlace.remove()
    setTimeout(() => URL.revokeObjectURL(url), 2000)
  }

  if (!usuario) return null
  return (
    <div data-testid="acma-testbot" className="fixed bottom-[calc(5.8rem+env(safe-area-inset-bottom))] right-3 z-40 lg:bottom-6 lg:right-6">
      {abierto && !oculto && (
        <section role="dialog" aria-label="Asistente ACMA TestBot"
          className="mb-3 flex max-h-[min(74dvh,620px)] w-[min(390px,calc(100vw-24px))] flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-[0_18px_65px_rgba(15,23,42,.24)]">
          <header className="flex shrink-0 items-center justify-between gap-3 bg-[#242632] px-4 py-3 text-white">
            <div><strong className="block text-sm">ACMA TestBot</strong><span className="text-xs text-white/70">Pruebas reales de mantenimiento DEMO</span></div>
            <div className="flex items-center gap-2">
              <button type="button" aria-label="Ocultar asistente" onClick={() => { setOculto(true); setAbierto(false) }}
                className="rounded-lg px-2 py-1 text-xs hover:bg-white/10">Ocultar</button>
              <button type="button" aria-label="Cerrar panel" onClick={() => setAbierto(false)}
                className="rounded-lg px-2 py-1 text-lg hover:bg-white/10">×</button>
            </div>
          </header>
          <div className="space-y-3 overflow-y-auto p-4">
            {esSuperadmin && (
              <div className="flex gap-2" role="tablist" aria-label="Modo del asistente">
                <button type="button" role="tab" aria-selected={modo === 'ayuda'} onClick={() => setModo('ayuda')}
                  className={modo === 'ayuda' ? boton + ' bg-[#a70d2d] text-white' : botonSecundario}>Ayuda</button>
                <button type="button" role="tab" aria-selected={modo === 'pruebas'} onClick={() => setModo('pruebas')}
                  className={modo === 'pruebas' ? boton + ' bg-[#a70d2d] text-white' : botonSecundario}>Probar sistema</button>
              </div>
            )}
            {!esSuperadmin || modo === 'ayuda' ? (
              <div className="space-y-3">
                <p className="text-sm text-slate-700">{ayudaPorRuta(pathname)}</p>
                <p className="text-xs text-slate-500">El modo Ayuda no modifica datos ni realiza pruebas automáticas.</p>
              </div>
            ) : (
              <div className="space-y-3">
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Formularios dinámicos · DEMO</p>
                {progreso.paso < PASOS_DEMO.length ? (
                  <>
                    <p className="text-sm font-bold text-slate-900">Prueba {progreso.paso + 1} de {PASOS_DEMO.length}</p>
                    <p className="text-sm text-slate-700">{PASOS_DEMO[progreso.paso]}</p>
                    <div role="progressbar" aria-valuemin={0} aria-valuemax={PASOS_DEMO.length} aria-valuenow={progreso.paso}
                      aria-label="Avance de pruebas" className="h-2 overflow-hidden rounded-full bg-slate-100">
                      <div className="h-full bg-[#a70d2d] transition-all" style={{ width: ((progreso.paso / PASOS_DEMO.length) * 100) + '%' }} />
                    </div>
                    <button type="button" disabled={ocupado} onClick={() => void ejecutar(false)}
                      className={boton + ' w-full bg-[#a70d2d] text-white hover:bg-[#870b25]'}>
                      {ocupado ? 'Ejecutando pruebas…' : 'Siguiente · ejecutar prueba'}
                    </button>
                    <button type="button" disabled={ocupado} onClick={() => void ejecutar(true)}
                      className={botonSecundario + ' w-full border-[#a70d2d] text-[#a70d2d]'}>
                      {ocupado ? 'Ejecutando…' : 'Ejecutar todas las pruebas DEMO'}
                    </button>
                    <p className="text-xs text-slate-500">La ejecución completa crea o reutiliza un formulario DEMO, lo publica y envía una respuesta ficticia. No modifica folios ni contratos reales.</p>
                  </>
                ) : (
                  <div className="space-y-3" data-testid="testbot-recorrido">
                    <div className="rounded-xl bg-green-50 p-3 text-sm font-semibold text-green-800">
                      ✓ Formularios dinámicos: 7/7 pruebas funcionales aprobadas.
                    </div>
                    <label className="flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs text-slate-800">
                      <input type="checkbox" checked={permitirEscrituras}
                        onChange={(e) => setPermitirEscrituras(e.target.checked)}
                        disabled={ocupado} className="mt-0.5" />
                      <span><strong>Autorizar altas y cambios de prueba.</strong> Solo registros TESTBOT DEMO
                        del cliente/prestador DEMO. Puede crear una familia y un tipo globales claramente
                        marcados TESTBOT DEMO; no modifica equipos reales ni envía mensajes externos.</span>
                    </label>
                    {recorrido.indice < SECUENCIA_ACMA.length ? (
                      <>
                        <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                          Recorrido general · {recorrido.indice} de {SECUENCIA_ACMA.length} módulos siguientes
                        </p>
                        <div role="progressbar" aria-label="Avance del recorrido de módulos"
                          aria-valuemin={0} aria-valuemax={SECUENCIA_ACMA.length} aria-valuenow={recorrido.indice}
                          className="h-2 overflow-hidden rounded-full bg-slate-100">
                          <div className="h-full bg-[#a70d2d]" style={{ width: (recorrido.indice / SECUENCIA_ACMA.length * 100) + '%' }} />
                        </div>
                        <p className="text-sm font-semibold text-slate-900">
                          Sigue: {SECUENCIA_ACMA[recorrido.indice]?.nombre}
                        </p>
                        <p className="text-xs text-slate-500">
                          Siguiente consulta el módulo. Si autorizas pruebas DEMO, también intenta
                          crear, editar y releer registros ficticios en los módulos implementados.
                        </p>
                        <button type="button" onClick={() => void siguienteDeACMA()} disabled={ocupado}
                          className={boton + ' w-full bg-[#a70d2d] text-white hover:bg-[#870b25]'}>
                          {ocupado ? 'Probando módulo…' : 'Siguiente · probar ' + (SECUENCIA_ACMA[recorrido.indice]?.nombre ?? '')}
                        </button>
                        <button type="button" onClick={() => void ejecutarRecorridoCompleto()}
                          disabled={ocupado || !permitirEscrituras}
                          className={botonSecundario + ' w-full border-[#a70d2d] text-[#a70d2d]'}>
                          {ocupado ? 'Ejecutando recorrido…' : 'Ejecutar todo el recorrido DEMO y guardar resultados'}
                        </button>
                      </>
                    ) : (
                      <div className="space-y-2 rounded-xl border border-slate-200 p-3 text-sm">
                        <strong className="block">Recorrido de consultas terminado</strong>
                        <p>{recorrido.resultados.filter((r) => r.estado === 'alta_cambio_demo_verificados').length} altas y ediciones DEMO verificadas,
                          {' '}{recorrido.resultados.filter((r) => r.estado === 'alta_demo_verificada').length} altas DEMO verificadas,
                          {' '}{recorrido.resultados.filter((r) => r.estado === 'consulta_verificada').length} solo lectura,
                          {' '}{recorrido.resultados.filter((r) => r.estado === 'error').length} con error,
                          {' '}{recorrido.resultados.filter((r) => r.estado === 'pendiente_funcional' || r.estado === 'requiere_otro_rol').length} pendientes.</p>
                        <p className="text-xs text-slate-500">Esto no equivale a haber probado todos los flujos de alta, edición,
                          permisos, evidencias, cobro o cierre. Las pruebas funcionales pendientes se desarrollan por módulo.</p>
                        <button type="button" onClick={() => void ejecutarRecorridoCompleto(true)}
                          disabled={ocupado || !permitirEscrituras}
                          className={botonSecundario + ' w-full border-[#a70d2d] text-[#a70d2d]'}>
                          {ocupado ? 'Repitiendo pruebas DEMO…' : 'Repetir recorrido DEMO con altas y verificaciones'}
                        </button>
                        {recorrido.resultados.some((r) => r.estado === 'error') && (
                          <button type="button" className={botonSecundario} disabled={ocupado} onClick={() => void volverAErrores()}>
                            {recorrido.resultados.some((r) => r.estado === 'error' && !reintentados.includes(r.id))
                              ? 'Siguiente · reintentar error pendiente'
                              : 'Reiniciar revisión de errores'}
                          </button>
                        )}
                      </div>
                    )}

                    <section aria-label="Rastrear folio DEMO" className="space-y-2 rounded-xl border border-slate-200 p-3 text-xs">
                      <p className="font-bold text-slate-900">Seguimiento de un folio DEMO</p>
                      <p>Se crea o reutiliza con tu sesión actual ({usuario.rol}).
                        El estado sí se consulta automáticamente cada 12 segundos. El GPS solo existe
                        cuando un Técnico asignado inicia su jornada y concede ubicación.</p>
                      <button type="button" disabled={ocupado || !permitirEscrituras}
                        onClick={() => void empezarRastreo()}
                        className={boton + ' w-full bg-[#a70d2d] text-white'}>
                        {ocupado ? 'Preparando folio…' : 'Crear / recuperar folio DEMO y rastrearlo'}
                      </button>
                      {errorRastreo && <p role="alert" className="rounded bg-red-50 p-2 text-red-700">
                        Error de rastreo: {errorRastreo}
                      </p>}
                      {folioRastreado && (
                        <div className="space-y-1 rounded-lg bg-slate-50 p-2" data-testid="testbot-folio-rastreo">
                          <p><strong>Folio:</strong> {folioRastreado.numero}</p>
                          <p><strong>Estado:</strong> {folioRastreado.estado}</p>
                          <p><strong>Técnico:</strong> {folioRastreado.tecnicoNombre ??
                            (folioRastreado.tecnicoId ? folioRastreado.tecnicoId : 'sin asignar')}</p>
                          <p><strong>Jornada:</strong> {folioRastreado.enJornada ? 'abierta' : 'no iniciada'}</p>
                          <p><strong>GPS:</strong> {folioRastreado.diagnosticoGPS}</p>
                          {folioRastreado.ultimaPosicion && <p>Última posición: {folioRastreado.ultimaPosicion}</p>}
                          <p>Última consulta: {folioRastreado.comprobadoEn}</p>
                          <div className="flex flex-wrap gap-2">
                            <button type="button" className="font-semibold text-[#a70d2d] underline"
                              onClick={() => navegar('/folios/' + folioRastreado.id)}>Ver folio</button>
                            <button type="button" className="font-semibold text-[#a70d2d] underline"
                              onClick={() => navegar('/operaciones')}>Ver tablero en tiempo real</button>
                          </div>
                        </div>
                      )}
                    </section>
                    {folioRastreado && (
                      <section className="space-y-2 rounded-xl border border-blue-200 bg-blue-50 p-3 text-xs"
                        data-testid="testbot-gps-personal">
                        <p className="font-bold text-blue-950">Prueba: rastrearme a mí (Superadmin)</p>
                        <p>Comparte tu GPS real con las otras pestañas abiertas de ACMA.
                          Verás un marcador vinculado a {folioRastreado.numero} en Operaciones.
                          Es una <strong>simulación local</strong>, no una jornada de Técnico;
                          no se guarda tu ubicación en la base de datos.</p>
                        {!gpsDemoActivo ? (
                          <button type="button" className={boton + ' w-full bg-blue-700 text-white'}
                            onClick={iniciarGpsPersonal}>
                            Iniciar mi GPS personal DEMO (pedir permiso)
                          </button>
                        ) : (
                          <button type="button" className={botonSecundario + ' w-full border-blue-400'}
                            onClick={detenerGpsPersonal}>Detener mi GPS personal DEMO</button>
                        )}
                        {gpsDemoActivo && !gpsDemoUltimo && <p>Esperando permiso y primera ubicación…</p>}
                        {gpsDemoUltimo && (
                          <p data-testid="testbot-gps-ultima">
                            Ubicación recibida: {gpsDemoUltimo.capturadaAt} ·
                            precisión aproximada {Math.round(gpsDemoUltimo.precisionM ?? 0)} m
                          </p>
                        )}
                        {gpsDemoError && <p role="alert" className="text-red-700">{gpsDemoError}</p>}
                      </section>
                    )}
                    {recorrido.resultados.length > 0 && (
                      <details className="text-xs text-slate-700" data-testid="testbot-resultados">
                        <summary className="cursor-pointer font-semibold">Resultados del recorrido ({recorrido.resultados.length})</summary>
                        <ol className="mt-2 max-h-48 space-y-2 overflow-y-auto">
                          {recorrido.resultados.map((r) => (
                            <li key={r.id} className="rounded-lg bg-slate-50 p-2">
                              <strong>{r.estado === 'error' ? 'Error' :
                                r.estado === 'alta_cambio_demo_verificados' ? 'Alta/edición DEMO OK' :
                                r.estado === 'alta_demo_verificada' ? 'Alta DEMO OK' :
                                r.estado === 'consulta_verificada' ? 'Consulta OK' : 'Pendiente'}: {r.nombre}</strong>
                              <p>{r.mensaje}</p>
                              {r.detalles.map((detalle, i) => <p key={i}>{detalle}</p>)}
                            </li>
                          ))}
                        </ol>
                      </details>
                    )}
                  </div>
                )}
                <button type="button" className={botonSecundario + ' w-full border-[#a70d2d] text-[#a70d2d]'}
                  onClick={descargarDiagnostico} data-testid="testbot-descargar-log">
                  Descargar diagnóstico de pruebas (.txt)
                </button>
                <p className="text-xs text-slate-500">El TXT incluye módulo, ruta y error HTTP cuando esté disponible,
                  IDs de prueba y pendientes; nunca exporta contraseñas ni tokens.</p>
                {mensaje && <p role="status" aria-live="polite" className="rounded-lg bg-slate-50 p-3 text-sm text-slate-700">{mensaje}</p>}
                {historial.length > 1 && (
                  <details className="text-xs text-slate-600">
                    <summary className="cursor-pointer font-semibold">Ver bitácora de pruebas ({historial.length})</summary>
                    <ol className="mt-2 space-y-1">{historial.slice(-10).map((linea, i) => <li key={i}>{linea}</li>)}</ol>
                  </details>
                )}
                {progreso.formularioId && (
                  <button type="button" className="text-left text-xs font-medium text-[#a70d2d] underline"
                    onClick={() => navegar('/formularios/constructor/' + progreso.formularioId)}>
                    Abrir formulario DEMO guardado
                  </button>
                )}
              </div>
            )}
          </div>
        </section>
      )}
      {!abierto && !oculto && sugerencia && (
        <div className="mb-2 flex max-w-56 items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs text-slate-700 shadow-lg">
          <span>¿Necesitas ayuda con ACMA?</span>
          <button type="button" aria-label="Descartar sugerencia" onClick={() => setSugerencia(false)} className="text-slate-500">×</button>
        </div>
      )}
      <button type="button" aria-label={oculto ? 'Mostrar asistente ACMA' : abierto ? 'Cerrar asistente ACMA' : 'Abrir asistente ACMA'}
        onClick={() => { setOculto(false); setAbierto((v) => !v) }}
        className="ml-auto flex h-14 w-14 items-center justify-center overflow-hidden rounded-full border-2 border-white bg-white shadow-[0_5px_22px_rgba(0,0,0,.27)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#a70d2d]">
        <img src={mascotaFallida ? '/icono.svg' : '/testbot-acma.webp'} onError={() => setMascotaFallida(true)}
          alt="" className="h-full w-full object-contain" />
      </button>
    </div>
  )
}
