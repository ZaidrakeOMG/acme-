import { useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router'
import { useAuth } from '../contexts/AuthContext'
import { ErrorAPI, mensajeDeError } from '../services/api'
import { ejecutarPasoDemo, INICIAL_DEMO, PASOS_DEMO, type ProgresoDemo } from '../services/testbotFlujoDemo'

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
  const [ocupado, setOcupado] = useState(false)
  const [mensaje, setMensaje] = useState('')
  const [historial, setHistorial] = useState<string[]>([])
  const [mascotaFallida, setMascotaFallida] = useState(false)
  const progresoRef = useRef<ProgresoDemo>(progreso)
  const bloqueado = useRef(false)

  useEffect(() => {
    const guardado = cargar(usuarioId)
    progresoRef.current = guardado
    setProgreso(guardado)
    setMensaje('')
    setHistorial([])
    setOcupado(false)
    bloqueado.current = false
  }, [usuarioId])

  function actualizar(p: ProgresoDemo) {
    progresoRef.current = p
    setProgreso(p)
    guardarLocal(usuarioId, p)
  }
  function registrar(texto: string) {
    setMensaje(texto)
    setHistorial((anterior) => [...anterior, texto].slice(-10))
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
                  <div className="rounded-xl bg-green-50 p-3 text-sm font-semibold text-green-800">
                    ✓ Formulario DEMO guardado, publicado, contestado y verificado.
                  </div>
                )}
                {mensaje && <p role="status" aria-live="polite" className="rounded-lg bg-slate-50 p-3 text-sm text-slate-700">{mensaje}</p>}
                {historial.length > 1 && (
                  <details className="text-xs text-slate-600">
                    <summary className="cursor-pointer font-semibold">Ver bitácora de pruebas ({historial.length})</summary>
                    <ol className="mt-2 space-y-1">{historial.map((linea, i) => <li key={i}>{linea}</li>)}</ol>
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
