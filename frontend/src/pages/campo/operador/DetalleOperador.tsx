import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router'
import { ChatFolio } from '../../../components/chat/ChatFolio'
import { Aviso, Boton, Insignia } from '../../../components/ui'
import { useConexion } from '../../../hooks/useConexion'
import { mensajeDeError } from '../../../services/api'
import { encuestaDisponible, folioCampo } from '../../../services/campo'
import type { FolioDetalle } from '../../../types/folios'
import { NOMBRE_ESTADO, NOMBRE_TRIGGER } from '../../../types/folios'
import { EstadoInsignia, SeveridadInsignia, fecha } from '../../folios/comunes'

/** Detalle del folio en la app del operador: línea de tiempo, chat de campo y acceso a firma/encuesta. */
export function DetalleOperador() {
  const { folioId } = useParams()
  const { enLinea } = useConexion()
  const [d, setD] = useState<FolioDetalle | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [encuesta, setEncuesta] = useState<{ disponible: boolean; motivo: string | null } | null>(null)

  const cargar = useCallback(async () => {
    if (!folioId) return
    try {
      const det = await folioCampo(folioId)
      if (!det) { setError('Este folio no está disponible sin conexión'); return }
      setD(det)
      if (enLinea && !det.encuesta && ['en_ejecucion', 'pendiente_refaccion', 'cerrado'].includes(det.folio.estado)) encuestaDisponible(folioId).then(setEncuesta).catch(() => setEncuesta(null))
    } catch (e) {
      setError(mensajeDeError(e))
    }
  }, [folioId, enLinea])
  useEffect(() => { void cargar() }, [cargar])

  if (error && !d) return <Aviso>{error}</Aviso>
  if (!d) return <p className="text-sm text-slate-500">Cargando…</p>
  const f = d.folio
  const pendiente = (f as { pendiente?: boolean }).pendiente
  const tieneFirma = d.evidencias.some((e) => e.tipo === 'firma')
  const puedeFirmar = f.estado === 'en_ejecucion' && !tieneFirma && !pendiente
  const puedeEncuesta = !d.encuesta && encuesta?.disponible
  return (
    <div className="mx-auto max-w-lg space-y-4">
      <Link to="/campo" className="text-xs text-primario underline">← Mis folios</Link>
      <div className="rounded-xl border border-slate-200 bg-white p-4">
        <div className="flex items-center justify-between gap-2">
          <span className="font-mono text-lg font-semibold">{pendiente ? 'Pendiente de enviar' : f.numero_folio}</span>
          <EstadoInsignia estado={f.estado} />
        </div>
        <p className="mt-2 text-base text-slate-800">{f.descripcion}</p>
        <div className="mt-2 flex flex-wrap gap-2 text-xs text-slate-600">
          <SeveridadInsignia severidad={f.severidad} />
          <span>{d.captura.equipo.codigo} · {d.captura.equipo.nombre}</span>
          <span>{d.captura.un.codigo} · {d.captura.un.nombre}</span>
        </div>
        <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
          <div className="rounded-lg bg-slate-50 p-2"><p className="text-slate-500">Técnico</p><p className="font-medium">{f.tecnico_nombre ?? 'Sin asignar'}</p></div>
          <div className="rounded-lg bg-slate-50 p-2"><p className="text-slate-500">Llegada estimada</p><p className="font-medium text-slate-400">Fase 2</p></div>
        </div>
        {pendiente && <p className="mt-2 text-xs text-amber-800">Capturado sin conexión: se enviará automáticamente al recuperar la señal.</p>}
        {d.triggers_revision.filter((t) => !t.resuelto).length > 0 && (
          <p className="mt-2 text-xs text-amber-800">En revisión: {d.triggers_revision.filter((t) => !t.resuelto).map((t) => NOMBRE_TRIGGER[t.trigger_tipo]).join(', ')}</p>
        )}
      </div>

      {(puedeFirmar || puedeEncuesta || d.encuesta || tieneFirma) && (
        <div className="rounded-xl border border-slate-200 bg-white p-4">
          <h2 className="text-sm font-semibold text-slate-800">Cierre del servicio</h2>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            {tieneFirma ? <Insignia tono="ok">Firmado</Insignia> : <Insignia>Sin firma</Insignia>}
            {d.encuesta ? <Insignia tono="ok">Encuesta: NPS {d.encuesta.nps_score}</Insignia> : <Insignia>Encuesta pendiente</Insignia>}
          </div>
          {puedeFirmar && <Link to={`/campo/folio/${f.id}/cierre`}><Boton className="mt-3 min-h-12 w-full text-base">Firmar la orden de servicio</Boton></Link>}
          {!puedeFirmar && puedeEncuesta && <Link to={`/campo/folio/${f.id}/cierre?paso=encuesta`}><Boton className="mt-3 min-h-12 w-full text-base">Responder la encuesta</Boton></Link>}
          {encuesta && !encuesta.disponible && !d.encuesta && tieneFirma && <p className="mt-2 text-xs text-slate-500">{encuesta.motivo}</p>}
        </div>
      )}

      {!pendiente && (
        <div>
          <h2 className="mb-2 text-sm font-semibold text-slate-800">Chat con el técnico</h2>
          <ChatFolio folioId={f.id} canales={['campo']} compacto />
        </div>
      )}

      <div className="rounded-xl border border-slate-200 bg-white p-4">
        <h2 className="text-sm font-semibold text-slate-800">Línea de tiempo</h2>
        <ol className="mt-2 space-y-2 text-sm">
          {d.historial.map((h) => (
            <li key={h.id} className="flex gap-2">
              <span className="mt-1 h-2 w-2 shrink-0 rounded-full bg-primario" aria-hidden />
              <div>
                <p className="font-medium">{h.evento === 'transicion' ? NOMBRE_ESTADO[h.estado_nuevo] : h.notas || h.evento}</p>
                <p className="text-xs text-slate-500">{h.actor_nombre ?? h.actor_rol} · {fecha(h.timestamp)}</p>
              </div>
            </li>
          ))}
          {d.historial.length === 0 && <li className="text-xs text-slate-500">La línea de tiempo se verá al sincronizar.</li>}
        </ol>
      </div>
    </div>
  )
}
