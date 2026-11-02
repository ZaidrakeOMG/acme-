import { useCallback, useEffect, useState } from 'react'
import { atenderAlerta, marcarVista, panelAlertas } from '../services/sla'
import type { AlertaPanel } from '../types/sla'
import { Aviso, Boton, Insignia } from './ui'

function cuando(iso: string) {
  const d = new Date(iso)
  return d.toLocaleString('es-MX', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
}

/** Panel de alertas del usuario (§6.9.6): las de su dominio cuyos roles destinatarios lo incluyen, con vista y atención. */
export function PanelAlertas({ alCerrar }: { alCerrar: () => void }) {
  const [filas, setFilas] = useState<AlertaPanel[]>([])
  const [pendientes, setPendientes] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [nota, setNota] = useState<Record<string, string>>({})
  const cargar = useCallback(async () => {
    try { setFilas(await panelAlertas({ pendientes, limite: 50 })) } catch { setError('No se pudo cargar el panel de alertas') }
  }, [pendientes])
  useEffect(() => { void cargar() }, [cargar])

  async function ejecutar(fn: () => Promise<unknown>) {
    setError(null)
    try { await fn(); await cargar() } catch { setError('No se pudo actualizar la alerta') }
  }

  return (
    <div className="absolute right-0 top-10 z-40 w-96 max-w-[92vw] rounded-xl border border-slate-200 bg-white p-3 shadow-xl"
      data-testid="panel-alertas">
      <div className="mb-2 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-slate-800">Alertas</h2>
        <button aria-label="Cerrar alertas" className="rounded p-1 text-slate-500 hover:bg-slate-100" onClick={alCerrar}>✕</button>
      </div>
      <label className="mb-2 flex items-center gap-1 text-xs text-slate-600"><input type="checkbox" checked={pendientes}
        onChange={(e) => setPendientes(e.target.checked)} /> Solo las que faltan atender</label>
      {error && <Aviso>{error}</Aviso>}
      {filas.length === 0 ? <p className="text-sm text-slate-500">Sin alertas para tu rol.</p> : (
        <ul className="max-h-96 space-y-2 overflow-y-auto">
          {filas.map((a) => (
            <li key={a.id} className="rounded-lg border border-slate-200 p-2" data-testid={`alerta-${a.clave_alerta}`}>
              <div className="flex flex-wrap items-center justify-between gap-1">
                <span className="font-mono text-xs font-medium">{a.clave_alerta}</span>
                <span className="text-xs text-slate-500">{cuando(a.timestamp_disparo)}</span>
              </div>
              {a.descripcion && <p className="text-xs text-slate-600">{a.descripcion}</p>}
              <div className="mt-1 flex flex-wrap items-center gap-1">
                <Insignia tono={a.atendida_at ? 'ok' : a.timestamp_vista ? 'acento' : 'alerta'}>
                  {a.atendida_at ? 'Atendida' : a.timestamp_vista ? 'Vista' : 'Nueva'}
                </Insignia>
                {a.escalada && <Insignia tono="alerta">Escalada</Insignia>}
                {a.umbral_en_momento && <Insignia>umbral {Number(a.umbral_en_momento)}</Insignia>}
              </div>
              {a.nota_atencion && <p className="mt-1 text-xs text-slate-500">Nota: {a.nota_atencion}</p>}
              {!a.atendida_at && (
                <div className="mt-2 flex flex-wrap items-end gap-1">
                  {!a.timestamp_vista && <Boton variante="secundario" onClick={() => void ejecutar(() => marcarVista(a.id))}>Marcar vista</Boton>}
                  <input aria-label={`Nota para ${a.clave_alerta}`} placeholder="Nota de atención" value={nota[a.id] ?? ''}
                    onChange={(e) => setNota({ ...nota, [a.id]: e.target.value })}
                    className="flex-1 rounded border border-slate-300 px-2 py-1 text-xs" />
                  <Boton onClick={() => void ejecutar(() => atenderAlerta(a.id, nota[a.id] ?? ''))}>Atender</Boton>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
