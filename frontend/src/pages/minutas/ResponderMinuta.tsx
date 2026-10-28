import { useCallback, useEffect, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router'
import { Aviso, Boton, Campo, Insignia, Selector, Tarjeta } from '../../components/ui'
import { useAuth } from '../../contexts/AuthContext'
import { mensajeDeError } from '../../services/api'
import { abrirBlob, obtenerMinuta, pdfMinuta, responderHallazgo, validarMinuta } from '../../services/minutas'
import type { MinutaDetalle, OpcionRespuesta, SeccionHallazgo } from '../../types/minutas'
import { NOMBRE_ESTADO_MINUTA, OPCIONES_RESPUESTA, RUTA_MODULO } from '../../types/minutas'
import { fecha as fmtFecha } from '../folios/comunes'

const COLOR = { rojo: 'border-red-300 bg-red-50 text-red-900', amarillo: 'border-amber-300 bg-amber-50 text-amber-900', verde: 'border-green-200 bg-green-50 text-green-900' } as Record<string, string>
const URGENCIA = { baja: 'neutro', media: 'acento', alta: 'alerta', critica: 'alerta' } as const

/** Vista interactiva de la minuta (§7.3) con la respuesta del Admin UN por hallazgo (§7.4) y la validación del despachador (§7.2). */
export function ResponderMinuta() {
  const { minutaId } = useParams()
  const [params] = useSearchParams()
  const { usuario } = useAuth()
  const [d, setD] = useState<MinutaDetalle | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)
  const [notas, setNotas] = useState('')
  const [abierto, setAbierto] = useState<string | null>(params.get('hallazgo'))

  const cargar = useCallback(async () => {
    if (!minutaId) return
    try { setD(await obtenerMinuta(minutaId)) } catch (e) { setError(mensajeDeError(e)) }
  }, [minutaId])
  useEffect(() => { void cargar() }, [cargar])

  if (error && !d) return <Aviso>{error}</Aviso>
  if (!d || !usuario) return <p className="text-sm text-slate-500">Cargando minuta…</p>
  const s = d.secciones
  const titulo = d.tipo === 'global' ? `Minuta global · ${d.tenant_nombre ?? ''}` : `Minuta de ${d.un_codigo} · ${d.un_nombre}`

  async function validar() {
    if (!d) return
    try { setD(await validarMinuta(d.id, notas)); setAviso('Minuta validada y enviada al cliente') } catch (e) { setError(mensajeDeError(e)) }
  }
  async function descargar() {
    if (!d) return
    try { abrirBlob(await pdfMinuta(d.id), `minuta-${d.fecha}.pdf`) } catch (e) { setError(mensajeDeError(e)) }
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <Link to="/minutas" className="text-xs text-primario underline">← Minutas</Link>
          <h1 className="text-2xl font-semibold text-slate-900">{titulo}</h1>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-sm text-slate-600">
            <span className="font-mono">{d.fecha}</span>
            <Insignia tono={d.estado === 'respondida' ? 'ok' : d.estado === 'vencida' || d.estado === 'pendiente_validacion' ? 'alerta' : 'acento'}>{NOMBRE_ESTADO_MINUTA[d.estado]}</Insignia>
            {d.urgente && <Insignia tono="alerta">Urgente</Insignia>}
            {d.enviada_sin_validacion && <Insignia>Enviada sin validación</Insignia>}
            {d.hash_pdf && <span className="text-xs text-slate-500" title="SHA-256 del PDF">firma {d.hash_pdf.slice(0, 12)}…</span>}
          </div>
        </div>
        <div className="flex gap-2">{d.pdf_disponible && <Boton variante="secundario" onClick={() => void descargar()}>Descargar PDF</Boton>}</div>
      </div>
      {error && <Aviso>{error}</Aviso>}
      {aviso && <Aviso tipo="exito">{aviso}</Aviso>}
      {d.notas_despachador && <Aviso tipo="info">Notas del despachador: {d.notas_despachador}</Aviso>}

      {d.puede_validar && (
        <Tarjeta titulo="Validación del despachador (§7.2)">
          <p className="mb-2 text-sm text-slate-600">Revisa el contenido, añade notas para el cliente y aprueba el envío. Si la ventana vence, ACMA la envía automáticamente y la marca «enviada sin validación».</p>
          <Campo etiqueta="Notas del despachador" value={notas} onChange={(e) => setNotas(e.target.value)} />
          <div className="mt-2"><Boton onClick={() => void validar()}>Aprobar y enviar</Boton></div>
        </Tarjeta>
      )}

      <Tarjeta titulo="Bloque 1 · Estatus acumulado de los módulos de seguimiento">
        <div className="grid gap-2 sm:grid-cols-4" data-testid="contadores">
          {(['cotizaciones', 'por_presupuesto', 'seguimiento_interno', 'reprogramacion'] as const).map((k) => {
            const c = s.contadores[k]
            return (
              <Link key={k} to={`/seguimiento?modulo=${RUTA_MODULO[k]}`} className={`rounded-lg border p-3 ${COLOR[c.color]}`} data-testid={`contador-${k}`}>
                <p className="text-xs font-semibold uppercase">{{ cotizaciones: 'Cotizaciones', por_presupuesto: 'Por presupuesto', seguimiento_interno: 'Seguimiento interno', reprogramacion: 'Reprogramación' }[k]}</p>
                <p className="text-2xl font-bold">{c.total}</p>
                <p className="text-xs">{c.color === 'verde' ? 'sin alertas' : `alerta: ${c.umbral}`}</p>
              </Link>
            )
          })}
        </div>
      </Tarjeta>

      <Tarjeta titulo={`Mantenimientos preventivos realizados (${s.preventivos.length})`}>
        {s.preventivos.length === 0 ? <p className="text-sm text-slate-500">Sin preventivos ejecutados.</p> : (
          <table className="w-full text-sm"><thead className="text-xs uppercase text-slate-500"><tr><th className="text-left">UN</th><th className="text-left">Equipo</th><th className="text-left">Técnico</th><th className="text-left">Programado</th><th className="text-left">Comparativa</th></tr></thead>
            <tbody>{s.preventivos.map((p) => <tr key={p.calendario_id} className="border-t border-slate-100"><td>{p.un}</td><td>{p.equipo}</td><td>{p.tecnico}</td><td className="font-mono text-xs">{p.fecha_programada}</td><td className={p.desvio_dias && p.desvio_dias > 0 ? 'text-amber-800' : 'text-slate-700'}>{p.texto_desvio}</td></tr>)}</tbody></table>
        )}
      </Tarjeta>

      <Tarjeta titulo={`Hallazgos importantes (${s.hallazgos.length})`}>
        {s.hallazgos.length === 0 ? <p className="text-sm text-slate-500">Sin hallazgos.</p> : (
          <ul className="divide-y divide-slate-100">
            {s.hallazgos.map((h) => (
              <li key={h.hallazgo_id} className="py-3" data-testid={`hallazgo-${h.hallazgo_id}`}>
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div>
                    <p className="text-sm text-slate-900">{h.descripcion}</p>
                    <p className="text-xs text-slate-500">{h.un} · {h.equipo}{h.numero_folio && ` · ${h.numero_folio}`}{h.pendiente_de_dias_anteriores && ' · pendiente de días anteriores'}</p>
                    <div className="mt-1 flex flex-wrap gap-1">
                      <Insignia tono={URGENCIA[h.urgencia]}>Urgencia {h.urgencia}</Insignia>
                      {h.foto_url && <a className="text-xs text-primario underline" href={h.foto_url} target="_blank" rel="noreferrer">foto</a>}
                      {h.estado_respuesta === 'respondido' ? <Insignia tono="ok">{OPCIONES_RESPUESTA.find((o) => o.valor === h.opcion_respuesta)?.texto ?? h.opcion_respuesta}</Insignia> : <Insignia tono="alerta">Pendiente de respuesta</Insignia>}
                    </div>
                  </div>
                  {d.puede_responder && h.estado_respuesta === 'pendiente' && d.estado !== 'pendiente_validacion' && (
                    <Boton variante="secundario" onClick={() => setAbierto(abierto === h.hallazgo_id ? null : h.hallazgo_id)}>Responder</Boton>
                  )}
                </div>
                {abierto === h.hallazgo_id && h.estado_respuesta === 'pendiente' && (
                  <FormularioRespuesta minutaId={d.id} hallazgo={h} alResponder={async (texto) => { setAbierto(null); setAviso(texto); await cargar() }} />
                )}
              </li>
            ))}
          </ul>
        )}
      </Tarjeta>

      <div className="grid gap-5 lg:grid-cols-2">
        <Tarjeta titulo="Cotizaciones">
          {(['pendientes_enviar', 'pendientes_autorizar'] as const).map((k) => (
            <div key={k} className="mb-2">
              <h3 className="text-xs font-semibold uppercase text-slate-500">{k === 'pendientes_enviar' ? 'Pendientes de enviar al cliente' : 'Pendientes de autorización'} ({s.cotizaciones[k].length})</h3>
              <ul className="text-sm">{s.cotizaciones[k].map((c) => <li key={c.cotizacion_id}><Link className="font-mono text-xs text-primario underline" to={`/seguimiento?modulo=cotizaciones&registro=${c.cotizacion_id}`}>{c.numero}</Link> · {c.un} · {c.equipo} · {c.descripcion} · {c.monto ? `$${Number(c.monto).toLocaleString('es-MX')}` : 'sin monto'} · {c.dias} d</li>)}</ul>
            </div>
          ))}
        </Tarjeta>
        <Tarjeta titulo="Trabajos especiales">
          <p className="text-sm text-slate-500">{s.trabajos_especiales.nota}</p>
        </Tarjeta>
        <Tarjeta titulo={`Peticiones especiales del cliente (${s.peticiones.length})`}>
          {s.peticiones.length === 0 ? <p className="text-sm text-slate-500">Sin peticiones.</p> : <ul className="list-disc pl-5 text-sm">{s.peticiones.map((p) => <li key={p.peticion_id}>{p.texto} <span className="text-xs text-slate-500">({p.un} · {p.capturado_por} · {p.origen})</span></li>)}</ul>}
        </Tarjeta>
        {s.pendientes_autorizacion.length > 0 && (
          <Tarjeta titulo="Folios pendientes de tu autorización (§6.8.7)">
            <ul className="text-sm">{s.pendientes_autorizacion.map((p) => <li key={p.folio_id}><Link className="font-mono text-xs text-primario underline" to={`/folios/${p.folio_id}`}>{p.numero_folio}</Link> · Nivel {p.nivel} · {p.descripcion}</li>)}</ul>
          </Tarjeta>
        )}
        {s.recordatorio_presupuesto && (
          <Tarjeta titulo="Recordatorio de hallazgos diferidos por presupuesto">
            {s.recordatorio_presupuesto.length === 0 ? <p className="text-sm text-slate-500">Sin diferidos.</p> : <ul className="list-disc pl-5 text-sm">{s.recordatorio_presupuesto.map((r) => <li key={r.hallazgo_presupuesto_id}>{r.descripcion} <span className="text-xs text-slate-500">({r.un} · {r.dias_diferido} días · {r.motivo})</span></li>)}</ul>}
          </Tarjeta>
        )}
      </div>

      <Tarjeta titulo="Entrega y respuestas">
        <p className="text-sm text-slate-600">Destinatarios: {d.destinatarios.map((x) => `${x.nombre ?? x.usuario_id} (${x.canal}: ${x.estado_entrega})`).join(' · ') || '—'}</p>
        {d.respuestas.length > 0 && <ul className="mt-2 text-sm">{d.respuestas.map((r) => <li key={r.id}>{fmtFecha(r.timestamp)} · {r.usuario_nombre} · {OPCIONES_RESPUESTA.find((o) => o.valor === r.opcion_elegida)?.texto} · canal {r.canal}{r.notas && ` · ${r.notas}`}{r.modulo_destino && <> · <Link className="text-primario underline" to={`/seguimiento?modulo=${RUTA_MODULO[r.modulo_destino]}&registro=${r.modulo_registro_id}`}>ver en el módulo</Link></>}{r.folio_generado_id && <> · <Link className="text-primario underline" to={`/folios/${r.folio_generado_id}`}>folio generado</Link></>}</li>)}</ul>}
      </Tarjeta>
    </div>
  )
}

function FormularioRespuesta({ minutaId, hallazgo, alResponder }: { minutaId: string; hallazgo: SeccionHallazgo; alResponder: (texto: string) => Promise<void> }) {
  const [opcion, setOpcion] = useState<OpcionRespuesta | null>(null)
  const [notas, setNotas] = useState('')
  const [fecha, setFecha] = useState('')
  const [proveedor, setProveedor] = useState('')
  const [coordinado, setCoordinado] = useState(false)
  const [variante, setVariante] = useState<'A' | 'B'>('A')
  const [error, setError] = useState<string | null>(null)
  const [enviando, setEnviando] = useState(false)

  async function enviar() {
    if (!opcion) return
    setEnviando(true)
    setError(null)
    try {
      await responderHallazgo(minutaId, hallazgo.hallazgo_id, { opcion, notas, fecha_tentativa: opcion === 'reprogramacion' && fecha ? fecha : null, proveedor: proveedor || null, trabajo_coordinado: opcion === 'reprogramacion' && coordinado, variante: opcion === 'reprogramacion' && coordinado ? variante : null })
      await alResponder(`Hallazgo respondido: ${OPCIONES_RESPUESTA.find((o) => o.valor === opcion)?.texto}`)
    } catch (e) { setError(mensajeDeError(e)) } finally { setEnviando(false) }
  }
  return (
    <div className="mt-3 rounded-lg border border-primario/30 bg-primario/5 p-3" data-testid="respuesta-hallazgo">
      {error && <div className="mb-2"><Aviso>{error}</Aviso></div>}
      <p className="mb-2 text-sm font-medium text-slate-800">Elige una de las seis opciones (§7.4)</p>
      <div className="grid gap-2 sm:grid-cols-2" role="radiogroup" aria-label="Opciones de respuesta">
        {OPCIONES_RESPUESTA.map((o) => (
          <label key={o.valor} className={`cursor-pointer rounded-lg border bg-white p-2 text-sm ${opcion === o.valor ? 'border-primario' : 'border-slate-200'}`}>
            <input type="radio" name={`opcion-${hallazgo.hallazgo_id}`} className="mr-2" checked={opcion === o.valor} onChange={() => setOpcion(o.valor)} aria-label={o.texto} />
            <span className="font-medium">{o.texto}</span>
            <span className="block text-xs text-slate-500">{o.efecto}</span>
          </label>
        ))}
      </div>
      {opcion === 'reprogramacion' && (
        <div className="mt-2 grid gap-2 sm:grid-cols-3">
          <Campo etiqueta="Fecha acordada con el tercero" type="date" value={fecha} onChange={(e) => setFecha(e.target.value)} />
          <Campo etiqueta="Nombre del tercero" value={proveedor} onChange={(e) => setProveedor(e.target.value)} />
          <label className="flex items-end gap-2 text-sm"><input type="checkbox" checked={coordinado} onChange={(e) => setCoordinado(e.target.checked)} /> Trabajo coordinado con el técnico</label>
          {coordinado && <Selector etiqueta="Variante" value={variante} onChange={(e) => setVariante(e.target.value as 'A' | 'B')} opciones={[{ valor: 'A', texto: 'A · Tercero habilita, técnico ejecuta' }, { valor: 'B', texto: 'B · Técnico ejecuta, tercero certifica' }]} />}
        </div>
      )}
      <div className="mt-2 flex items-end gap-2">
        <Campo etiqueta="Notas" value={notas} onChange={(e) => setNotas(e.target.value)} />
        <Boton onClick={() => void enviar()} disabled={!opcion || enviando}>Enviar respuesta</Boton>
      </div>
    </div>
  )
}
