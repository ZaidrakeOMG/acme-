import { useEffect, useState } from 'react'
import { Link } from 'react-router'
import { Aviso, Boton, Campo, Insignia, Modal, Selector, Tarjeta } from '../../components/ui'
import { ErrorAPI, mensajeDeError } from '../../services/api'
import { candidatosReasignacion, listarAutorizaciones, razonesReasignacion, reasignarFolio, resolverAutorizacion, solicitarCancelacion, solicitarReprogramacion } from '../../services/preventivos'
import type { FolioResumen } from '../../types/folios'
import type { Autorizacion, Candidato, RazonReasignacion } from '../../types/preventivos'
import { fecha } from './comunes'

/**
 * Reasignación forzada (§6.8.2): candidatos con validaciones (habilidad = restricción dura, refacción = advertencia),
 * razón obligatoria del catálogo del prestador y confirmación explícita de las advertencias (409 CONFIRMACION_REQUERIDA).
 */
export function ReasignarModal({ folio, alCerrar, alReasignar }: { folio: FolioResumen; alCerrar: () => void; alReasignar: (nombre: string) => Promise<void> }) {
  const [candidatos, setCandidatos] = useState<Candidato[]>([])
  const [razones, setRazones] = useState<RazonReasignacion[]>([])
  const [destino, setDestino] = useState('')
  const [razonId, setRazonId] = useState('')
  const [comentario, setComentario] = useState('')
  const [razonSinHabilidad, setRazonSinHabilidad] = useState('')
  const [advertencias, setAdvertencias] = useState<string[]>([])
  const [confirmar, setConfirmar] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [enviando, setEnviando] = useState(false)

  useEffect(() => {
    candidatosReasignacion(folio.id).then(setCandidatos).catch((e) => setError(mensajeDeError(e)))
    razonesReasignacion().then(setRazones).catch(() => setRazones([]))
  }, [folio.id])

  const elegido = candidatos.find((c) => c.usuario_id === destino)

  async function enviar() {
    if (!elegido) return
    setEnviando(true)
    setError(null)
    try {
      const r = await reasignarFolio(folio.id, { tecnico_destino_id: destino, razon_id: razonId, comentario, confirmar_advertencias: confirmar, razon_sin_habilidad: razonSinHabilidad || null })
      await alReasignar(r.tecnico_destino_nombre ?? elegido.nombre)
    } catch (e) {
      if (e instanceof ErrorAPI && e.codigo === 'CONFIRMACION_REQUERIDA') {
        setAdvertencias(e.detalles.map(String))
      } else {
        setError(mensajeDeError(e))
      }
    } finally {
      setEnviando(false)
    }
  }

  return (
    <Modal titulo={`Reasignar ${folio.numero_folio}`} abierto alCerrar={alCerrar}>
      {error && <div className="mb-3"><Aviso>{error}</Aviso></div>}
      <p className="mb-3 text-sm text-slate-600">Técnico actual: <strong>{folio.tecnico_nombre ?? '—'}</strong>. La habilidad requerida es restricción dura; la refacción solo advierte.</p>
      <div className="max-h-64 space-y-1 overflow-y-auto" role="radiogroup" aria-label="Técnicos candidatos">
        {candidatos.filter((c) => !c.es_actual).map((c) => (
          <label key={c.usuario_id} data-testid={`candidato-${c.usuario_id}`} className={`flex cursor-pointer items-start gap-2 rounded-lg border p-2 text-sm ${destino === c.usuario_id ? 'border-primario bg-primario/5' : 'border-slate-200'}`}>
            <input type="radio" name="destino" value={c.usuario_id} checked={destino === c.usuario_id} onChange={() => { setDestino(c.usuario_id); setAdvertencias([]); setConfirmar(false) }} aria-label={c.nombre} />
            <span className="flex-1">
              <span className="font-medium">{c.nombre}</span> <span className="text-xs text-slate-500">{c.vehiculo_placas ?? ''} · {c.carga_dia} folio(s) activos</span>
              <span className="mt-1 flex flex-wrap gap-1">
                {c.habilidad_ok ? <Insignia tono="ok">Habilidad {c.habilidad_requerida ?? 'ok'}</Insignia> : <Insignia tono="alerta">Sin habilidad {c.habilidad_requerida}</Insignia>}
                {c.refaccion_ok === null && <Insignia>Refacción no verificada</Insignia>}
              </span>
            </span>
          </label>
        ))}
        {candidatos.length === 0 && <p className="text-sm text-slate-500">Cargando candidatos…</p>}
      </div>
      <div className="mt-3 space-y-3">
        <Selector etiqueta="Razón de la reasignación (obligatoria)" value={razonId} onChange={(e) => setRazonId(e.target.value)}
                  opciones={[{ valor: '', texto: 'Elegir razón…' }, ...razones.map((r) => ({ valor: r.id, texto: r.descripcion }))]} />
        {razonId && <p className="-mt-2 text-xs text-slate-500">{razones.find((r) => r.id === razonId)?.detalle}</p>}
        <Campo etiqueta="Comentario" value={comentario} onChange={(e) => setComentario(e.target.value)} />
        {elegido && !elegido.habilidad_ok && (
          <Campo etiqueta="Razón para asignar sin la habilidad (requiere permiso del despachador)" value={razonSinHabilidad} onChange={(e) => setRazonSinHabilidad(e.target.value)} />
        )}
        {advertencias.length > 0 && (
          <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm" data-testid="advertencias">
            <p className="font-medium text-amber-900">Advertencias</p>
            <ul className="list-disc pl-5 text-amber-900">{advertencias.map((a) => <li key={a}>{a}</li>)}</ul>
            <label className="mt-2 flex items-center gap-2"><input type="checkbox" checked={confirmar} onChange={(e) => setConfirmar(e.target.checked)} /> Entiendo las advertencias y confirmo la reasignación</label>
          </div>
        )}
        <div className="flex justify-end gap-2">
          <Boton variante="fantasma" onClick={alCerrar}>Cancelar</Boton>
          <Boton onClick={() => void enviar()} disabled={!destino || !razonId || enviando || (advertencias.length > 0 && !confirmar)}>Reasignar</Boton>
        </div>
      </div>
    </Modal>
  )
}

/** Panel del folio preventivo: calendario, plan y autorizaciones de reprogramación / cancelación (§6.9.1). */
export function PanelPreventivo({ folio, puedeSolicitar, puedeAutorizar, alCambiar }: { folio: FolioResumen; puedeSolicitar: boolean; puedeAutorizar: boolean; alCambiar: () => Promise<void> }) {
  const [autorizaciones, setAutorizaciones] = useState<Autorizacion[]>([])
  const [modo, setModo] = useState<'reprogramacion' | 'cancelacion' | null>(null)
  const [razon, setRazon] = useState('')
  const [fechaNueva, setFechaNueva] = useState('')
  const [notas, setNotas] = useState('')
  const [error, setError] = useState<string | null>(null)

  async function cargar() {
    try { setAutorizaciones(await listarAutorizaciones({ folio_id: folio.id })) } catch { setAutorizaciones([]) }
  }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { void cargar() }, [folio.id, folio.estado])

  async function solicitar() {
    setError(null)
    try {
      if (modo === 'reprogramacion') await solicitarReprogramacion(folio.id, razon, fechaNueva)
      else await solicitarCancelacion(folio.id, razon)
      setModo(null)
      setRazon('')
      await cargar()
      await alCambiar()
    } catch (e) {
      setError(mensajeDeError(e))
    }
  }
  async function resolver(a: Autorizacion, autorizar: boolean) {
    setError(null)
    try {
      await resolverAutorizacion(a.id, autorizar, notas)
      setNotas('')
      await cargar()
      await alCambiar()
    } catch (e) {
      setError(mensajeDeError(e))
    }
  }
  const pendiente = autorizaciones.find((a) => a.estado === 'pendiente')

  return (
    <Tarjeta titulo="Preventivo" acciones={<Link to="/preventivos/calendario" className="text-xs text-primario underline">Calendario</Link>}>
      {error && <div className="mb-2"><Aviso>{error}</Aviso></div>}
      <p className="text-sm text-slate-700">Generado por el sistema {folio.plan_nombre ? <>desde el plan <strong>{folio.plan_nombre}</strong></> : 'desde el calendario manual'} · fecha programada {folio.fecha_falla.slice(0, 10)}. Reprogramar o cancelar requiere autorización del Admin UN o Admin empresa.</p>
      {autorizaciones.length > 0 && (
        <ul className="mt-2 divide-y divide-slate-100 text-sm" data-testid="autorizaciones-folio">
          {autorizaciones.map((a) => (
            <li key={a.id} className="py-1">
              <Insignia tono={a.estado === 'pendiente' ? 'alerta' : a.estado === 'autorizada' ? 'ok' : 'neutro'}>{a.tipo === 'reprogramacion' ? `Reprogramación → ${a.fecha_nueva}` : 'Cancelación'} · {a.estado}</Insignia>
              <span className="ml-2">{a.razon}</span> <span className="text-xs text-slate-500">· {a.solicitado_por_nombre} · {fecha(a.fecha_solicitud)}{a.autorizado_por_nombre && ` · resuelto por ${a.autorizado_por_nombre} (${a.canal})`}</span>
              {a.notas_respuesta && <span className="block text-xs text-slate-600">{a.notas_respuesta}</span>}
            </li>
          ))}
        </ul>
      )}
      {pendiente && puedeAutorizar && pendiente.puede_resolver && (
        <div className="mt-3 flex flex-wrap items-end gap-2">
          <Campo etiqueta="Notas de la decisión" value={notas} onChange={(e) => setNotas(e.target.value)} />
          <Boton onClick={() => void resolver(pendiente, true)}>Autorizar</Boton>
          <Boton variante="peligro" onClick={() => void resolver(pendiente, false)} disabled={!notas.trim()}>Rechazar</Boton>
        </div>
      )}
      {puedeSolicitar && !pendiente && !modo && (
        <div className="mt-3 flex gap-2">
          <Boton variante="secundario" onClick={() => setModo('reprogramacion')}>Solicitar reprogramación</Boton>
          <Boton variante="secundario" onClick={() => setModo('cancelacion')}>Solicitar cancelación</Boton>
        </div>
      )}
      {modo && (
        <form className="mt-3 grid gap-2 sm:grid-cols-[1fr_auto_auto_auto]" onSubmit={(e) => { e.preventDefault(); void solicitar() }}>
          <Campo etiqueta={modo === 'reprogramacion' ? 'Razón de la reprogramación' : 'Razón de la cancelación'} value={razon} onChange={(e) => setRazon(e.target.value)} minLength={5} required />
          {modo === 'reprogramacion' && <Campo etiqueta="Fecha nueva" type="date" value={fechaNueva} onChange={(e) => setFechaNueva(e.target.value)} required />}
          <Boton type="submit" className="self-end" disabled={razon.trim().length < 5 || (modo === 'reprogramacion' && !fechaNueva)}>Enviar solicitud</Boton>
          <Boton type="button" variante="fantasma" className="self-end" onClick={() => setModo(null)}>Cancelar</Boton>
        </form>
      )}
    </Tarjeta>
  )
}
