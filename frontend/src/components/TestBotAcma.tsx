import { useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router'
import { useAuth } from '../contexts/AuthContext'
import { api, ErrorAPI, mensajeDeError } from '../services/api'
import { prepararEsquemaDemo, respuestasDemo } from '../services/testbot/formularioDemo'
import type { Formulario, Respuesta } from '../types/formularios'

/**
 * Asistente flotante de ACMA.
 * No accede al DOM para simular clics: usa la API autenticada de la aplicación.
 * Cada petición de escritura requiere un clic real en «Siguiente prueba».
 */
type Registro = { momento: string; prueba: string; resultado: string }
type Progreso = { paso: number; formularioId: string | null; respuestaId: string | null; registros: Registro[] }
type PrepararResultado = { formularioId: string; nombre: string; totalCampos: number }
type PrepararSolicitud = {
  resolver: (resultado: PrepararResultado) => void
  rechazar: (error: Error) => void
}

const CLAVE = 'acma.testbot.guiado.v1'
const CLAVE_OCULTAR = 'acma.testbot.oculto.v1'
const PASOS = [
  'Continuar el formulario que ya empezaste',
  'Publicar la versión de prueba',
  'Verificar en Mis formularios',
  'Comprobar validación de obligatorios',
  'Llenar y guardar datos ficticios',
  'Enviar y verificar que no se pueda editar',
  'Pasar al módulo Biblioteca técnica',
] as const

function leerProgreso(): Progreso {
  try {
    const encontrado = JSON.parse(sessionStorage.getItem(CLAVE) ?? 'null') as Progreso | null
    if (encontrado && Number.isInteger(encontrado.paso) && Array.isArray(encontrado.registros))
      return encontrado
  } catch { /* Sesión de prueba nueva */ }
  return { paso: 0, formularioId: null, respuestaId: null, registros: [] }
}

function ahora(): string { return new Date().toLocaleString('es-MX') }
function mensajeDeAyuda(ruta: string): string {
  if (ruta.includes('/formularios/constructor')) return '¿Te ayudo a terminar este formulario?'
  if (ruta.includes('/mis-formularios')) return '¿Revisamos tus formularios publicados?'
  if (ruta.includes('/catalogos')) return '¿Necesitas revisar algún catálogo?'
  if (ruta.includes('/folios')) return '¿Quieres revisar el estado de tus folios?'
  if (ruta.includes('/biblioteca')) return '¿Buscamos un manual o una ficha técnica?'
  return '¿En qué puedo ayudarte dentro de ACMA?'
}

function descargarReporte(progreso: Progreso) {
  const contenido = JSON.stringify({
    herramienta: 'ACMA TestBot',
    version: 1,
    modo: 'pruebas_guiadas',
    formulario_id: progreso.formularioId,
    respuesta_id: progreso.respuestaId,
    paso: progreso.paso,
    resultados: progreso.registros,
  }, null, 2)
  const url = URL.createObjectURL(new Blob([contenido], { type: 'application/json' }))
  const enlace = document.createElement('a')
  enlace.href = url
  enlace.download = 'ACMA_TestBot_reporte.json'
  document.body.appendChild(enlace)
  enlace.click()
  enlace.remove()
  URL.revokeObjectURL(url)
}

export function TestBotAcma() {
  const { usuario } = useAuth()
  const ubicacion = useLocation()
  const navegar = useNavigate()
  const esSuperadmin = usuario?.rol === 'superadmin'
  const [oculto, setOculto] = useState(() => localStorage.getItem(CLAVE_OCULTAR) === '1')
  const [abierto, setAbierto] = useState(false)
  const [sugerenciaVisible, setSugerenciaVisible] = useState(true)
  const [progreso, setProgreso] = useState<Progreso>(leerProgreso)
  const [ejecutando, setEjecutando] = useState(false)
  const [mensaje, setMensaje] = useState('Continuamos desde el formulario de inspección que ya estabas llenando. No repetiremos los catálogos.')
  const [comando, setComando] = useState('')
  const [candidatos, setCandidatos] = useState<Formulario[]>([])
  const [elegido, setElegido] = useState('')

  useEffect(() => {
    sessionStorage.setItem(CLAVE, JSON.stringify(progreso))
  }, [progreso])

  useEffect(() => {
    localStorage.setItem(CLAVE_OCULTAR, oculto ? '1' : '0')
  }, [oculto])

  useEffect(() => {
    const mostrar = () => { setOculto(false); setAbierto(true) }
    window.addEventListener('acma:testbot:mostrar', mostrar)
    return () => window.removeEventListener('acma:testbot:mostrar', mostrar)
  }, [])

  useEffect(() => { setSugerenciaVisible(true) }, [ubicacion.pathname])

  if (!usuario) return null

  const registrar = (paso: number, prueba: string, resultado: string, cambios: Partial<Progreso> = {}) => {
    setProgreso(anterior => ({
      ...anterior, ...cambios, paso,
      registros: [...anterior.registros, { momento: ahora(), prueba, resultado }],
    }))
    setMensaje(resultado)
  }

  const buscarFormulario = async (): Promise<Formulario | null> => {
    const formularios = await api<Formulario[]>('/formularios', { params: { plantillas: 'false' } })
    if (elegido) {
      const seleccionado = formularios.find(f => f.id === elegido)
      if (!seleccionado) throw new Error('El formulario seleccionado ya no está disponible.')
      return seleccionado
    }
    const normalizar = (s: string) => s.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase()
    const coincidentes = formularios.filter(f =>
      normalizar(f.nombre).includes('inspeccion de mantenimiento demo'))
    if (coincidentes.length === 1) return coincidentes[0]!
    const genericos = formularios.filter(f =>
      f.nombre === 'Nuevo formulario' && f.esquema_json.secciones.some(s => s.campos.length > 0))
    if (coincidentes.length === 0 && genericos.length === 1) return genericos[0]!
    setCandidatos(coincidentes.length > 0 ? coincidentes : genericos)
    if (coincidentes.length > 1 || genericos.length > 1) {
      setMensaje('Encontré varios borradores parecidos. Selecciona el correcto; no voy a modificar otro formulario.')
    } else {
      navegar('/formularios/constructor')
      setMensaje('Abre el formulario que estabas preparando. Cuando aparezca su constructor, pulsa Siguiente y lo completaré sin borrar tus campos.')
    }
    return null
  }

  const prepararDesdeConstructor = async (): Promise<PrepararResultado> => {
    return new Promise<PrepararResultado>((resolver, rechazar) => {
      const evento = new CustomEvent<PrepararSolicitud>('acma:testbot:preparar', {
        cancelable: true, detail: { resolver, rechazar },
      })
      window.dispatchEvent(evento)
      if (!evento.defaultPrevented)
        rechazar(new Error('No se encontró el constructor activo. Abre el formulario e inténtalo de nuevo.'))
    })
  }

  async function siguiente() {
    if (!esSuperadmin || ejecutando) return
    setEjecutando(true)
    try {
      if (progreso.paso === 0) {
        let id: string
        let nombre: string
        let campos: number
        if (ubicacion.pathname.startsWith('/formularios/constructor')) {
          const resultado = await prepararDesdeConstructor()
          id = resultado.formularioId
          nombre = resultado.nombre
          campos = resultado.totalCampos
        } else {
          const encontrado = await buscarFormulario()
          if (!encontrado) return
          id = encontrado.id
          nombre = encontrado.nombre
          const esquema = prepararEsquemaDemo(encontrado.esquema_json)
          const roles = Array.from(new Set([...encontrado.rol_destino, 'superadmin']))
          const guardado = await api<Formulario>(`/formularios/${id}`, {
            metodo: 'PUT',
            cuerpo: {
              nombre: nombre === 'Nuevo formulario' ? 'Inspección de mantenimiento DEMO' : nombre,
              descripcion: encontrado.descripcion || 'Formulario de pruebas ACMA',
              tipo: encontrado.tipo,
              rol_destino: roles,
              tenant_id: encontrado.tenant_id,
              esquema,
            },
          })
          nombre = guardado.nombre
          campos = guardado.esquema_json.secciones.reduce((n, s) => n + s.campos.length, 0)
        }
        registrar(1, PASOS[0], `Formulario recuperado y guardado: ${nombre} (${campos} campos). Conservé los existentes.`, { formularioId: id, respuestaId: null })
      } else if (progreso.paso === 1) {
        if (!progreso.formularioId) throw new Error('Falta el formulario seleccionado.')
        const f = await api<Formulario>(`/formularios/${progreso.formularioId}`)
        if (!(f.estado === 'publicado' && f.version_actual === f.numero_version_publicada)) {
          await api<Formulario>(`/formularios/${f.id}/publicar`, {
            metodo: 'POST', cuerpo: { notas_version: 'ACMA TestBot · prueba de publicación controlada' },
          })
        }
        const verificado = await api<Formulario>(`/formularios/${f.id}`)
        if (verificado.estado !== 'publicado' || !verificado.numero_version_publicada)
          throw new Error('No se confirmó la publicación en el servidor.')
        registrar(2, PASOS[1], `Publicación comprobada: versión ${verificado.numero_version_publicada}.`)
      } else if (progreso.paso === 2) {
        if (!progreso.formularioId) throw new Error('Falta el formulario seleccionado.')
        const lista = await api<{ formulario: Formulario }[]>('/formularios/mis-formularios')
        const resultado = lista.find(item => item.formulario.id === progreso.formularioId)
        if (!resultado) throw new Error('El formulario publicado NO aparece en Mis formularios para Superadmin.')
        registrar(3, PASOS[2], 'Correcto: el formulario publicado aparece en Mis formularios.')
      } else if (progreso.paso === 3) {
        if (!progreso.formularioId) throw new Error('Falta el formulario seleccionado.')
        const f = await api<Formulario>(`/formularios/${progreso.formularioId}`)
        const campos = f.esquema_json.secciones.flatMap(s => s.campos)
        if (!campos.some(c => c.obligatorio)) throw new Error('No hay campos obligatorios; no se puede comprobar la validación.')
        let idRespuesta = progreso.respuestaId
        if (!idRespuesta) {
          const r = await api<Respuesta>(`/formularios/${f.id}/respuestas`, {
            metodo: 'POST',
            cuerpo: { origen: 'independiente', contexto: { tenant_id: f.tenant_id }, respuestas: {},
              dispositivo: { fuente: 'acma_testbot', ficticio: true } },
          })
          idRespuesta = r.id
          setProgreso(p => ({ ...p, respuestaId: r.id }))
        }
        let fueRechazado = false
        try {
          await api<Respuesta>(`/formularios/respuestas/${idRespuesta}/enviar`, { metodo: 'POST' })
        } catch (e) {
          if (e instanceof ErrorAPI && e.estado === 422) fueRechazado = true
          else throw e
        }
        if (!fueRechazado)
          throw new Error('FALLO: el servidor permitió enviar la prueba sin rellenar los campos obligatorios.')
        registrar(4, PASOS[3], 'Correcto: la API rechaza respuestas vacías con error 422.', { respuestaId: idRespuesta })
      } else if (progreso.paso === 4) {
        if (!progreso.formularioId || !progreso.respuestaId) throw new Error('Falta la respuesta iniciada.')
        const f = await api<Formulario>(`/formularios/${progreso.formularioId}`)
        const datos = respuestasDemo(f.esquema_json)
        await api<Respuesta>(`/formularios/respuestas/${progreso.respuestaId}`, {
          metodo: 'PUT', cuerpo: { respuestas: datos, dispositivo: { fuente: 'acma_testbot', ficticio: true } },
        })
        const consultado = await api<Respuesta>(`/formularios/respuestas/${progreso.respuestaId}`)
        for (const [k, v] of Object.entries(datos)) {
          if (consultado.respuestas_json[k] !== v) throw new Error(`No se conservó el valor del campo ${k}.`)
        }
        registrar(5, PASOS[4], `Correcto: se guardaron y recuperaron ${Object.keys(datos).length} respuestas ficticias.`)
      } else if (progreso.paso === 5) {
        if (!progreso.respuestaId) throw new Error('Falta la respuesta iniciada.')
        const id = progreso.respuestaId
        const enviado = await api<Respuesta>(`/formularios/respuestas/${id}/enviar`, { metodo: 'POST' })
        if (enviado.estado !== 'enviado' || !enviado.inmutable)
          throw new Error('No se confirmó la inmutabilidad de la respuesta enviada.')
        let bloqueado = false
        try {
          await api<Respuesta>(`/formularios/respuestas/${id}`, {
            metodo: 'PUT', cuerpo: { respuestas: enviado.respuestas_json },
          })
        } catch (e) {
          if (e instanceof ErrorAPI && (e.estado === 409 || e.estado === 403)) bloqueado = true
          else throw e
        }
        if (!bloqueado) throw new Error('FALLO: la API permitió editar una respuesta enviada.')
        registrar(6, PASOS[5], 'Correcto: respuesta enviada y bloqueada contra modificaciones.')
      } else if (progreso.paso === 6) {
        registrar(7, PASOS[6], 'Flujo de formularios finalizado. Ahora continuamos en Biblioteca técnica.')
        navegar('/biblioteca')
      } else {
        setMensaje('Esta primera serie ya terminó. Descarga el reporte; añadiremos pruebas de los demás módulos sin repetir las anteriores.')
      }
    } catch (e) {
      const detalle = mensajeDeError(e)
      setMensaje(`Prueba detenida: ${detalle}`)
      setProgreso(p => ({ ...p, registros: [...p.registros, {
        momento: ahora(), prueba: PASOS[Math.min(p.paso, PASOS.length - 1)] ?? 'Prueba',
        resultado: `ERROR: ${detalle}`,
      }] }))
    } finally {
      setEjecutando(false)
    }
  }

  function procesarComando() {
    const c = comando.trim().toLowerCase()
    setComando('')
    if (!c) return
    if (c === 'siguiente' || c === 'continuar' || c === 'probar') {
      void siguiente()
    } else if (c.includes('ocultar')) {
      setOculto(true); setAbierto(false)
    } else if (c.includes('reporte')) {
      descargarReporte(progreso)
    } else {
      setMensaje(esSuperadmin
        ? 'Escribe «siguiente» para ejecutar una prueba, o «reporte» para descargar los resultados.'
        : mensajeDeAyuda(ubicacion.pathname))
    }
  }

  if (oculto) return null
  return (
    <div className="pointer-events-none fixed bottom-[calc(5.75rem+env(safe-area-inset-bottom))] right-3 z-[65] flex max-w-[calc(100vw-1.5rem)] flex-col items-end gap-2 lg:bottom-5 lg:right-6">
      {abierto && (
        <section role="dialog" aria-label="Asistente ACMA TestBot"
          className="pointer-events-auto flex max-h-[min(72dvh,620px)] w-[min(370px,calc(100vw-1.5rem))] flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-[0_16px_50px_rgba(15,23,42,.24)]">
          <header className="flex items-center justify-between gap-2 bg-[#202b47] px-4 py-3 text-white">
            <div>
              <p className="text-sm font-bold">Asistente ACMA</p>
              <p className="text-[11px] text-white/75">{esSuperadmin ? 'TestBot · Modo Superadmin' : 'Ayuda contextual'}</p>
            </div>
            <div className="flex gap-1">
              <button type="button" aria-label="Minimizar asistente" title="Minimizar"
                onClick={() => setAbierto(false)} className="rounded-lg px-2 py-1 hover:bg-white/15">−</button>
              <button type="button" aria-label="Ocultar asistente" title="Ocultar por completo"
                onClick={() => { setOculto(true); setAbierto(false) }}
                className="rounded-lg px-2 py-1 hover:bg-white/15">×</button>
            </div>
          </header>
          <div className="min-h-0 space-y-3 overflow-y-auto p-4 text-sm text-slate-800">
            {esSuperadmin ? (
              <>
                <div className="rounded-xl bg-slate-50 p-3">
                  <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Prueba {Math.min(progreso.paso + 1, PASOS.length)} de {PASOS.length}</p>
                  <p className="mt-1 font-semibold">{PASOS[Math.min(progreso.paso, PASOS.length - 1)] ?? 'Finalizado'}</p>
                  <p className="mt-1 text-xs text-slate-600">Conservamos el formulario y los registros DEMO existentes.</p>
                </div>
                {candidatos.length > 1 && progreso.paso === 0 && (
                  <label className="block text-xs font-semibold">
                    Formulario que ya estabas trabajando
                    <select className="mt-1 w-full rounded-lg border border-slate-300 p-2 text-sm"
                      value={elegido} onChange={e => setElegido(e.target.value)}>
                      <option value="">Seleccionar sin duplicar</option>
                      {candidatos.map(f => <option key={f.id} value={f.id}>{f.nombre} · {f.estado}</option>)}
                    </select>
                  </label>
                )}
                <p aria-live="polite" className="rounded-xl border border-slate-200 p-3 text-xs leading-relaxed">{mensaje}</p>
                <button type="button" disabled={ejecutando || progreso.paso >= PASOS.length}
                  onClick={() => void siguiente()}
                  className="min-h-11 w-full rounded-xl bg-[#203c91] px-4 py-2 font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50">
                  {ejecutando ? 'Ejecutando prueba…' : progreso.paso >= PASOS.length ? 'Pruebas de formularios finalizadas' : 'Siguiente prueba'}
                </button>
                <button type="button" onClick={() => descargarReporte(progreso)}
                  className="min-h-10 w-full rounded-lg border border-slate-300 px-3 text-xs font-semibold">
                  Descargar reporte de pruebas
                </button>
                {progreso.registros.length > 0 && (
                  <div className="space-y-1 border-t border-slate-100 pt-2">
                    <p className="text-xs font-semibold">Historial de esta sesión</p>
                    {progreso.registros.slice(-5).map((r, i) => (
                      <p key={`${i}-${r.momento}`} className="text-[11px] text-slate-600">
                        {r.momento}: {r.resultado}
                      </p>
                    ))}
                  </div>
                )}
              </>
            ) : (
              <p className="rounded-xl bg-slate-50 p-3 text-sm">{mensajeDeAyuda(ubicacion.pathname)}</p>
            )}
          </div>
          <div className="flex gap-2 border-t border-slate-100 p-3">
            <input aria-label="Escribe una instrucción al asistente" value={comando}
              onChange={e => setComando(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') procesarComando() }}
              placeholder={esSuperadmin ? 'Escribe: siguiente' : '¿Qué necesitas?'}
              className="min-w-0 flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm" />
            <button type="button" onClick={procesarComando} className="rounded-lg bg-slate-900 px-3 py-2 text-xs font-semibold text-white">Enviar</button>
          </div>
        </section>
      )}
      {!abierto && sugerenciaVisible && (
        <div className="pointer-events-auto flex max-w-64 items-center gap-2 rounded-xl border border-slate-200 bg-white p-2 text-xs shadow-lg">
          <span>{esSuperadmin ? '¿Continuamos la prueba donde nos quedamos?' : mensajeDeAyuda(ubicacion.pathname)}</span>
          <button type="button" aria-label="Cerrar sugerencia" onClick={() => setSugerenciaVisible(false)}
            className="shrink-0 p-1 text-slate-500">×</button>
        </div>
      )}
      <button type="button" aria-label="Abrir asistente ACMA" title="Asistente ACMA"
        onClick={() => { setAbierto(a => !a); setSugerenciaVisible(false) }}
        className="pointer-events-auto flex h-14 w-14 items-center justify-center rounded-full border-2 border-white bg-[#243b84] text-sm font-black text-white shadow-[0_8px_26px_rgba(24,42,96,.32)]">
        AC
      </button>
    </div>
  )
}
