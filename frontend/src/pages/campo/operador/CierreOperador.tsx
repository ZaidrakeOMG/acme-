import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router'
import { Lienzo } from '../../../components/formularios/campos/evidencias'
import { Aviso, Boton } from '../../../components/ui'
import { mensajeDeError } from '../../../services/api'
import { encuestaDisponible, firmarFolio, folioCampo, responderEncuesta } from '../../../services/campo'

function posicion(): Promise<{ lat: number; lng: number } | null> {
  return new Promise((resolve) => {
    if (typeof navigator === 'undefined' || !navigator.geolocation) return resolve(null)
    navigator.geolocation.getCurrentPosition((p) => resolve({ lat: p.coords.latitude, lng: p.coords.longitude }), () => resolve(null), { timeout: 4000 })
  })
}

/** Cierre desde la app del operador (§6.8.6 datos de cierre): firma a pantalla completa y después la encuesta NPS. */
export function CierreOperador() {
  const { folioId } = useParams()
  const [params] = useSearchParams()
  const navegar = useNavigate()
  const [paso, setPaso] = useState<'firma' | 'encuesta' | 'listo'>(params.get('paso') === 'encuesta' ? 'encuesta' : 'firma')
  const [numero, setNumero] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [nps, setNps] = useState<number | null>(null)
  const [comentario, setComentario] = useState('')
  const [sugerencia, setSugerencia] = useState('')
  const [enviando, setEnviando] = useState(false)

  useEffect(() => {
    if (!folioId) return
    folioCampo(folioId).then((d) => {
      if (!d) return
      setNumero(d.folio.numero_folio)
      if (d.evidencias.some((e) => e.tipo === 'firma') && paso === 'firma') setPaso('encuesta')
      if (d.encuesta) setPaso('listo')
    }).catch((e) => setError(mensajeDeError(e)))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [folioId])

  async function firmar(blob: Blob, tiene: boolean) {
    if (!folioId) return
    if (!tiene) { setError('La firma no puede quedar vacía'); return }
    setEnviando(true)
    setError(null)
    try {
      await firmarFolio(folioId, blob, await posicion())
      const disp = await encuestaDisponible(folioId).catch(() => ({ disponible: true }))
      setPaso(disp.disponible ? 'encuesta' : 'listo')
    } catch (e) {
      setError(mensajeDeError(e))
    } finally {
      setEnviando(false)
    }
  }

  async function enviarEncuesta() {
    if (!folioId || nps === null) return
    if (nps <= 6 && comentario.trim().length < 5) { setError('Cuéntanos qué pasó (mínimo 5 caracteres)'); return }
    setEnviando(true)
    setError(null)
    try {
      await responderEncuesta(folioId, nps, comentario.trim(), sugerencia.trim())
      setPaso('listo')
    } catch (e) {
      setError(mensajeDeError(e))
    } finally {
      setEnviando(false)
    }
  }

  return (
    <div className="mx-auto max-w-lg space-y-4">
      <Link to={`/campo/folio/${folioId}`} className="text-xs text-primario underline">← Folio {numero}</Link>
      {error && <Aviso>{error}</Aviso>}
      {paso === 'firma' && (
        <div className="rounded-xl border border-slate-200 bg-white p-4">
          <h1 className="text-lg font-semibold text-slate-900">Firma de la orden de servicio</h1>
          <p className="mb-3 text-sm text-slate-600">Con tu firma confirmas que el técnico realizó el servicio. Queda registrada con fecha, hora y ubicación.</p>
          <Lienzo etiqueta="Firma del operador" pantallaCompleta textoConfirmar={enviando ? 'Guardando…' : 'Confirmar firma'} alGuardar={(blob, tiene) => void firmar(blob, tiene)} />
        </div>
      )}
      {paso === 'encuesta' && (
        <div className="rounded-xl border border-slate-200 bg-white p-4" data-testid="encuesta">
          <h1 className="text-lg font-semibold text-slate-900">¿Cómo fue el servicio?</h1>
          <p className="mb-3 text-sm text-slate-600">¿Qué tan probable es que recomiendes este servicio? 0 = nada probable, 10 = muy probable.</p>
          <div className="grid grid-cols-6 gap-2 sm:grid-cols-11">
            {Array.from({ length: 11 }, (_, i) => (
              <button key={i} type="button" aria-label={`Calificación ${i}`} aria-pressed={nps === i} onClick={() => setNps(i)}
                      className={`min-h-12 rounded-lg text-base font-semibold ${nps === i ? 'bg-primario text-white' : 'bg-slate-100 text-slate-800'}`}>{i}</button>
            ))}
          </div>
          {nps !== null && nps <= 6 && (
            <label className="mt-3 block text-sm">
              <span className="font-medium text-slate-800">Cuéntanos qué pasó (obligatorio)</span>
              <textarea aria-label="Comentario" value={comentario} onChange={(e) => setComentario(e.target.value)} rows={3} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-base" />
            </label>
          )}
          <label className="mt-3 block text-sm">
            <span className="font-medium text-slate-800">¿Algo que podamos mejorar?</span>
            <textarea aria-label="Sugerencia" value={sugerencia} onChange={(e) => setSugerencia(e.target.value)} rows={2} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-base" />
          </label>
          <Boton className="mt-4 min-h-12 w-full text-base" disabled={nps === null || enviando} onClick={() => void enviarEncuesta()}>Enviar encuesta</Boton>
        </div>
      )}
      {paso === 'listo' && (
        <div className="rounded-xl border border-green-200 bg-green-50 p-6 text-center">
          <p className="text-lg font-semibold text-green-900">¡Gracias!</p>
          <p className="mt-1 text-sm text-green-800">Tu firma y tu opinión quedaron registradas en el folio {numero}.</p>
          <Boton className="mt-4" variante="secundario" onClick={() => navegar('/campo')}>Volver a mis folios</Boton>
        </div>
      )}
    </div>
  )
}
