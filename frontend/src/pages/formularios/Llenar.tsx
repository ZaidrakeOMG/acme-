import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router'
import { Renderizador } from '../../components/formularios/Renderizador'
import { Aviso, Boton, Encabezado, Insignia } from '../../components/ui'
import { api, mensajeDeError } from '../../services/api'
import { crearRespuesta, enviarRespuesta, guardarRespuesta, obtenerEvidencias, obtenerFormulario, obtenerRespuesta } from '../../services/formularios/respuestas'
import { validar } from '../../services/formularios/validacion'
import type { Evidencia, Formulario, Respuesta } from '../../types/formularios'

type Calidad = { tamano_minimo_kb: number; resolucion_minima_ancho: number; resolucion_minima_alto: number; compresion_maxima_pct: number }

/**
 * Llenado de un formulario publicado: crea o reanuda una respuesta, guarda parcial (debounce) y envía.
 * Ruta: /formularios/llenar/:formularioId?respuesta=&origen=&referencia=&un_id=&equipo_id=&tenant_id=
 */
export function Llenar() {
  const { formularioId } = useParams()
  const [params] = useSearchParams()
  const navegar = useNavigate()
  const [formulario, setFormulario] = useState<Formulario | null>(null)
  const [respuesta, setRespuesta] = useState<Respuesta | null>(null)
  const [valores, setValores] = useState<Record<string, unknown>>({})
  const [evidencias, setEvidencias] = useState<Record<string, Evidencia[]>>({})
  const [calidad, setCalidad] = useState<Calidad | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [mostrarErrores, setMostrarErrores] = useState(false)
  const [guardando, setGuardando] = useState<'idle' | 'guardando' | 'guardado'>('idle')
  const temporizador = useRef<ReturnType<typeof setTimeout> | null>(null)
  const contexto = { tenant_id: params.get('tenant_id'), un_id: params.get('un_id'), equipo_id: params.get('equipo_id') }

  useEffect(() => {
    if (!formularioId) return
    ;(async () => {
      try {
        const f = await obtenerFormulario(formularioId)
        setFormulario(f)
        api<Calidad>('/formularios/calidad-foto-defaults').then(setCalidad).catch(() => setCalidad(null))
        const existente = params.get('respuesta')
        const r = existente ? await obtenerRespuesta(existente) : await crearRespuesta(f.id, params.get('origen') ?? 'independiente', contexto, params.get('referencia'))
        setRespuesta(r)
        setValores(r.respuestas_json)
        const ev = await obtenerEvidencias(r.id)
        setEvidencias(ev.reduce<Record<string, Evidencia[]>>((acc, e) => ({ ...acc, [e.campo_clave]: [...(acc[e.campo_clave] ?? []), e] }), {}))
      } catch (e) {
        setError(mensajeDeError(e))
      }
    })()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [formularioId])

  function cambiar(nuevos: Record<string, unknown>) {
    setValores(nuevos)
    if (!respuesta || respuesta.estado === 'enviado') return
    if (temporizador.current) clearTimeout(temporizador.current)
    setGuardando('guardando')
    temporizador.current = setTimeout(async () => {
      try {
        const r = await guardarRespuesta(respuesta.id, nuevos)
        setRespuesta(r)
        setGuardando('guardado')
      } catch (e) {
        setError(mensajeDeError(e))
        setGuardando('idle')
      }
    }, 600)
  }

  async function enviar() {
    if (!formulario || !respuesta) return
    setMostrarErrores(true)
    const ctx = { evidencias: Object.fromEntries(Object.entries(evidencias).map(([k, v]) => [k, v.map((e) => ({ tipo: e.tipo }))])), iniciadoAt: new Date(respuesta.iniciado_at) }
    const { errores } = validar(formulario.esquema_json, valores, ctx, true)
    if (errores.length) {
      setError(`Revisa ${errores.length} campo(s) antes de enviar`)
      return
    }
    setError(null)
    try {
      if (temporizador.current) clearTimeout(temporizador.current)
      await guardarRespuesta(respuesta.id, valores)
      const r = await enviarRespuesta(respuesta.id)
      setRespuesta(r)
      setValores(r.respuestas_json)
    } catch (e) {
      setError(mensajeDeError(e))
    }
  }

  if (error && !formulario) return <Aviso>{error}</Aviso>
  if (!formulario || !respuesta) return <p className="text-slate-500">Cargando formulario…</p>
  const enviado = respuesta.estado === 'enviado'

  return (
    <div className="mx-auto max-w-3xl">
      <Encabezado titulo={formulario.nombre} descripcion={formulario.descripcion || undefined}
                  acciones={<div className="flex items-center gap-2 text-xs text-slate-500">
                    <Insignia tono={enviado ? 'ok' : 'alerta'}>{enviado ? 'Enviado' : 'En progreso'}</Insignia>
                    <span>v{respuesta.numero_version}</span>
                    {!enviado && <span>{guardando === 'guardando' ? 'Guardando…' : guardando === 'guardado' ? 'Guardado' : ''}</span>}
                  </div>} />
      {enviado && <div className="mb-4"><Aviso tipo="exito">Formulario enviado el {new Date(respuesta.enviado_at!).toLocaleString('es-MX')}. Es inmutable; la evidencia adicional va por el chat del folio.</Aviso></div>}
      {error && <div className="mb-4"><Aviso>{error}</Aviso></div>}
      <div className="rounded-xl border border-slate-200 bg-white p-5">
        <Renderizador esquema={formulario.esquema_json} respuestas={valores} onChange={cambiar} contexto={{ ...contexto, tenant_id: respuesta.tenant_id ?? contexto.tenant_id }}
                      respuestaId={respuesta.id} evidencias={evidencias} onEvidencias={(k, l) => setEvidencias((e) => ({ ...e, [k]: l }))}
                      soloLectura={enviado} mostrarErrores={mostrarErrores} iniciadoAt={new Date(respuesta.iniciado_at)} calidadDefaults={calidad} />
      </div>
      {!enviado && (
        <div className="mt-6 flex flex-wrap justify-end gap-2">
          <Boton variante="secundario" onClick={() => navegar(-1)}>Guardar y salir</Boton>
          <Boton onClick={() => void enviar()}>Enviar formulario</Boton>
        </div>
      )}
    </div>
  )
}
