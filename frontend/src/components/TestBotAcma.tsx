import { useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router'
import { useAuth } from '../contexts/AuthContext'
import { api, mensajeDeError } from '../services/api'
import { crearRespuesta, enviarRespuesta, guardarRespuesta, obtenerFormulario, obtenerRespuesta } from '../services/formularios/respuestas'
import { validar } from '../services/formularios/validacion'
import { EVENTO_ACCION_TESTBOT, EVENTO_RESULTADO_TESTBOT, type AccionTestBot, type ResultadoTestBot } from '../services/testbotAcma'
import type { Tenant } from '../types/api'
import { camposDe, type Formulario } from '../types/formularios'

/** Progreso local por usuario. El formulario y las respuestas reales se verifican siempre contra la API. */
interface Progreso {
  paso: number
  formularioId: string | null
  respuestaId: string | null
}
const inicial: Progreso = { paso: 0, formularioId: null, respuestaId: null }
const pasos = [
  'Configurar los cuatro campos existentes',
  'Guardar el formulario sin duplicarlo',
  'Abrir la vista previa real',
  'Publicar la versión (con confirmación)',
  'Verificar que aparezca en Mis formularios',
  'Enviar una respuesta ficticia de prueba',
  'Verificar el envío y la persistencia',
] as const
const accionesConstructor: AccionTestBot[] = ['preparar', 'guardar', 'vista_previa', 'publicar']
const clave = (usuarioId: string) => 'acma.testbot.formularios.v1.' + usuarioId

function cargar(usuarioId: string): Progreso {
  try {
    const dato = JSON.parse(localStorage.getItem(clave(usuarioId)) || 'null') as Partial<Progreso> | null
    if (!dato || typeof dato.paso !== 'number') return { ...inicial }
    return {
      paso: Math.max(0, Math.min(pasos.length, Math.floor(dato.paso))),
      formularioId: typeof dato.formularioId === 'string' ? dato.formularioId : null,
      respuestaId: typeof dato.respuestaId === 'string' ? dato.respuestaId : null,
    }
  } catch {
    return { ...inicial }
  }
}
function guardarLocal(usuarioId: string, progreso: Progreso) {
  try { localStorage.setItem(clave(usuarioId), JSON.stringify(progreso)) } catch { /* almacenamiento opcional */ }
}

const boton = 'rounded-xl px-3 py-2 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-50'
const botonSecundario = boton + ' border border-slate-200 bg-white text-slate-700 hover:bg-slate-50'

function ayudaPorRuta(pathname: string): string {
  if (pathname.startsWith('/formularios/constructor')) return 'Puedo ayudarte a configurar, guardar y publicar este formulario.'
  if (pathname.startsWith('/mis-formularios')) return 'Aquí puedes iniciar, reanudar y consultar formularios publicados para tu rol.'
  if (pathname.startsWith('/catalogos')) return 'Los catálogos conectan técnicos, equipos, fallas y severidades.'
  if (pathname.startsWith('/folios')) return 'Un folio permite documentar y dar seguimiento a un servicio.'
  return 'Puedo orientarte en los módulos de mantenimiento de ACMA.'
}

export function TestBotAcma() {
  const { usuario } = useAuth()
  const navegar = useNavigate()
  const { pathname } = useLocation()
  const usuarioId = usuario?.id ?? ''
  const esSuperadmin = usuario?.rol === 'superadmin'
  const [abierto, setAbierto] = useState(false)
  const [oculto, setOculto] = useState(false)
  const [mostrarSugerencia, setMostrarSugerencia] = useState(true)
  const [modo, setModo] = useState<'ayuda' | 'pruebas'>('ayuda')
  const [progreso, setProgreso] = useState<Progreso>(() => cargar(usuarioId))
  const [ocupado, setOcupado] = useState(false)
  const [aviso, setAviso] = useState('')
  const [mascotaFallida, setMascotaFallida] = useState(false)

  useEffect(() => {
    setProgreso(cargar(usuarioId))
    setAviso('')
    setOcupado(false)
  }, [usuarioId])

  function actualizar(proximo: Progreso) {
    guardarLocal(usuarioId, proximo)
    setProgreso(proximo)
  }

  useEffect(() => {
    if (!esSuperadmin) return
    const escuchar = (e: Event) => {
      const detalle = (e as CustomEvent<ResultadoTestBot>).detail
      const actual = accionesConstructor[progreso.paso]
      if (!detalle || detalle.accion !== actual) return
      setOcupado(false)
      setAviso(detalle.mensaje)
      if (detalle.exito) {
        actualizar({
          ...progreso,
          formularioId: detalle.formularioId ?? progreso.formularioId,
          paso: progreso.paso + 1,
        })
      }
    }
    window.addEventListener(EVENTO_RESULTADO_TESTBOT, escuchar)
    return () => window.removeEventListener(EVENTO_RESULTADO_TESTBOT, escuchar)
    // actualizar escribe el valor obtenido del evento; no debe rehacer el listener en cada render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [esSuperadmin, progreso, usuarioId])

  async function siguiente() {
    if (!esSuperadmin || ocupado || progreso.paso >= pasos.length) return
    setAviso('')
    if (progreso.paso < accionesConstructor.length) {
      if (!pathname.startsWith('/formularios/constructor')) {
        // Abrir solo el formulario ya guardado; jamás crear uno nuevo al navegar.
        if (progreso.formularioId) {
          navegar('/formularios/constructor/' + progreso.formularioId)
          setAviso('Abrí el formulario guardado. Pulsa Siguiente para continuar.')
        } else {
          setAviso('Vuelve al constructor que ya tienes abierto, sin crear otro formulario.')
        }
        return
      }
      setOcupado(true)
      window.dispatchEvent(new CustomEvent(EVENTO_ACCION_TESTBOT, { detail: { accion: accionesConstructor[progreso.paso] } }))
      if (progreso.paso === 3) {
        // La publicación tiene confirmación nativa; solo avanza cuando el servidor confirme.
        setOcupado(false)
        setAviso('Confirma la publicación en la ventana de ACMA para continuar.')
      }
      return
    }
    setOcupado(true)
    try {
      if (!progreso.formularioId) throw new Error('No hay formulario guardado. No se creará otro automáticamente.')
      if (progreso.paso === 4) {
        const publicados = await api<{ formulario: Formulario }[]>('/formularios/mis-formularios')
        if (!publicados.some((item) => item.formulario.id === progreso.formularioId)) {
          throw new Error('El formulario todavía no aparece en Mis formularios para Superadmin.')
        }
        actualizar({ ...progreso, paso: 5 })
        navegar('/mis-formularios')
        setAviso('Verificado: el formulario está publicado y dirigido a tu rol.')
      } else if (progreso.paso === 5) {
        const f = await obtenerFormulario(progreso.formularioId)
        const tenants = await api<Tenant[]>('/tenants')
        if (f.estado !== 'publicado' || !f.tenant_id || !tenants.some((t) =>
          t.id === f.tenant_id && t.razon_social.toUpperCase().includes('DEMO'))) {
          throw new Error('Seguridad: la respuesta automática solo se permite en un formulario publicado para el cliente DEMO.')
        }
        if (!f.nombre.toUpperCase().includes('DEMO')) throw new Error('El nombre del formulario debe indicar DEMO para las pruebas automáticas.')
        const campos = camposDe(f.esquema_json)
        const tipos = campos.map((c) => c.tipo)
        if (tipos.length !== 4 || tipos.join(',') !== 'si_no,texto_amplio,texto_amplio,texto') {
          throw new Error('El formulario cambió: se esperaban exactamente los cuatro campos ya configurados.')
        }
        const valores: Record<string, unknown> = {
          [campos[0]!.clave]: false,
          [campos[1]!.clave]: 'TESTBOT DEMO: el minisplit no enfría durante la inspección.',
          [campos[2]!.clave]: 'TESTBOT DEMO: inspección ficticia; no corresponde a una orden de trabajo real.',
          [campos[3]!.clave]: 'Aire acondicionado tipo minisplit DEMO',
        }
        const revision = validar(f.esquema_json, valores, {}, true)
        if (revision.errores.length) throw new Error('Validación de datos de prueba: ' + revision.errores.map((e) => e.mensaje).join('; '))
        let r = progreso.respuestaId ? await obtenerRespuesta(progreso.respuestaId) : null
        if (!r) {
          r = await crearRespuesta(f.id, 'independiente', { tenant_id: f.tenant_id })
          actualizar({ ...progreso, respuestaId: r.id })
        }
        if (r.formulario_id !== f.id) throw new Error('La respuesta anterior pertenece a otro formulario.')
        if (r.estado !== 'enviado') {
          await guardarRespuesta(r.id, valores)
          r = await enviarRespuesta(r.id)
        }
        if (r.estado !== 'enviado') throw new Error('El servidor no confirmó el envío.')
        actualizar({ ...progreso, respuestaId: r.id, paso: 6 })
        setAviso('Respuesta ficticia enviada. Su ID quedó guardado para comprobarla, sin enviar una segunda vez.')
      } else if (progreso.paso === 6) {
        if (!progreso.respuestaId) throw new Error('Falta el identificador de la respuesta enviada.')
        const r = await obtenerRespuesta(progreso.respuestaId)
        if (r.formulario_id !== progreso.formularioId || r.estado !== 'enviado') {
          throw new Error('La respuesta no se encuentra enviada o pertenece a otro formulario.')
        }
        actualizar({ ...progreso, paso: 7 })
        setAviso('Prueba aprobada: el servidor conserva la respuesta enviada y la marca inmutable.')
      }
    } catch (e) {
      setAviso(mensajeDeError(e))
    } finally {
      setOcupado(false)
    }
  }

  if (!usuario) return null

  return (
    <div className="fixed bottom-[calc(5.8rem+env(safe-area-inset-bottom))] right-3 z-40 lg:bottom-6 lg:right-6" data-testid="acma-testbot">
      {abierto && !oculto && (
        <section role="dialog" aria-label="Asistente ACMA TestBot"
          className="mb-3 flex max-h-[min(70dvh,570px)] w-[min(365px,calc(100vw-24px))] flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-[0_18px_65px_rgba(15,23,42,.24)]">
          <header className="flex items-center justify-between gap-3 bg-[#242632] px-4 py-3 text-white">
            <div className="min-w-0"><strong className="block text-sm">ACMA TestBot</strong><span className="text-xs text-white/70">Tu asistente de mantenimiento</span></div>
            <div className="flex items-center gap-2">
              <button type="button" aria-label="Ocultar asistente" onClick={() => { setOculto(true); setAbierto(false) }} className="rounded-lg px-2 py-1 text-sm hover:bg-white/10">Ocultar</button>
              <button type="button" aria-label="Cerrar panel" onClick={() => setAbierto(false)} className="rounded-lg px-2 py-1 text-lg hover:bg-white/10">×</button>
            </div>
          </header>
          <div className="overflow-y-auto p-4">
            {esSuperadmin && (
              <div className="mb-4 flex gap-2" role="tablist" aria-label="Modo del asistente">
                <button type="button" role="tab" aria-selected={modo === 'ayuda'} onClick={() => setModo('ayuda')} className={modo === 'ayuda' ? boton + ' bg-[#a70d2d] text-white' : botonSecundario}>Ayuda</button>
                <button type="button" role="tab" aria-selected={modo === 'pruebas'} onClick={() => setModo('pruebas')} className={modo === 'pruebas' ? boton + ' bg-[#a70d2d] text-white' : botonSecundario}>Probar sistema</button>
              </div>
            )}
            {!esSuperadmin || modo === 'ayuda' ? (
              <div className="space-y-3">
                <p className="text-sm text-slate-700">{ayudaPorRuta(pathname)}</p>
                <p className="text-xs text-slate-500">Esta primera versión ofrece orientación contextual. No modifica registros desde el modo Ayuda.</p>
              </div>
            ) : (
              <div className="space-y-3">
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Formularios dinámicos · DEMO</p>
                {progreso.paso < pasos.length ? (
                  <>
                    <p className="text-sm font-bold text-slate-900">Prueba {progreso.paso + 1} de {pasos.length}</p>
                    <p className="text-sm text-slate-700">{pasos[progreso.paso]}</p>
                    <div role="progressbar" aria-valuemin={0} aria-valuemax={pasos.length} aria-valuenow={progreso.paso}
                      aria-label="Avance de pruebas" className="h-2 overflow-hidden rounded-full bg-slate-100">
                      <div className="h-full bg-[#a70d2d] transition-all" style={{ width: ((progreso.paso / pasos.length) * 100) + '%' }} />
                    </div>
                    <p className="text-xs text-slate-500">Solo reutiliza el formulario actual. Las escrituras automáticas se limitan al cliente DEMO.</p>
                    <button type="button" disabled={ocupado} onClick={() => void siguiente()}
                      className={boton + ' w-full bg-[#a70d2d] text-white hover:bg-[#870b25]'}>
                      {ocupado ? 'Ejecutando…' : 'Siguiente'}
                    </button>
                  </>
                ) : (
                  <p className="rounded-xl bg-green-50 p-3 text-sm font-semibold text-green-800">Prueba de Formularios dinámicos completada.</p>
                )}
                {aviso && <p role="status" aria-live="polite" className="rounded-lg bg-slate-50 p-3 text-sm text-slate-700">{aviso}</p>}
                {progreso.formularioId && <p className="break-all text-[11px] text-slate-400">Formulario: {progreso.formularioId}</p>}
              </div>
            )}
          </div>
        </section>
      )}
      {!abierto && !oculto && mostrarSugerencia && (
        <div className="mb-2 flex max-w-56 items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs text-slate-700 shadow-lg">
          <span>¿Necesitas ayuda con ACMA?</span>
          <button type="button" aria-label="Descartar sugerencia" onClick={() => setMostrarSugerencia(false)} className="text-slate-500">×</button>
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
