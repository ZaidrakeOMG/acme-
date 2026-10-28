import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router'
import { Aviso, Boton, Encabezado, Insignia, Tarjeta } from '../components/ui'
import { mensajeDeError } from '../services/api'
import { bandejaNotificaciones, eventosNotificables, guardarPreferencia, marcarLeidas, preferencias } from '../services/minutas'
import type { EventoNotificable, Notificacion, Preferencia } from '../types/minutas'
import { fecha as fmtFecha } from './folios/comunes'

const CANALES_FASE_1 = ['app', 'push', 'email'] as const

/** Bandeja de notificaciones (canal app) y preferencias de canal por evento (§6.1). WhatsApp y SMS son Fase 2. */
export function Notificaciones() {
  const [lista, setLista] = useState<Notificacion[]>([])
  const [soloNoLeidas, setSoloNoLeidas] = useState(false)
  const [eventos, setEventos] = useState<EventoNotificable[]>([])
  const [prefs, setPrefs] = useState<Record<string, string[]>>({})
  const [error, setError] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)

  const cargar = useCallback(async () => {
    try {
      setLista(await bandejaNotificaciones(soloNoLeidas, 100))
      const [ev, pr] = await Promise.all([eventosNotificables(), preferencias()])
      setEventos(ev.eventos)
      setPrefs(Object.fromEntries(pr.map((p: Preferencia) => [p.evento, p.canales])))
    } catch (e) { setError(mensajeDeError(e)) }
  }, [soloNoLeidas])
  useEffect(() => { void cargar() }, [cargar])

  async function alternar(evento: string, canal: string, defecto: string[]) {
    const actual = prefs[evento] ?? defecto
    const nuevos = actual.includes(canal) ? actual.filter((c) => c !== canal) : [...actual, canal]
    try { const p = await guardarPreferencia(evento, nuevos); setPrefs({ ...prefs, [evento]: p.canales }); setAviso('Preferencia guardada') } catch (e) { setError(mensajeDeError(e)) }
  }

  return (
    <div>
      <Encabezado titulo="Notificaciones" descripcion="Avisos del sistema por evento: bandeja interna, push y correo (Fase 1). WhatsApp y SMS llegan en Fase 2."
                  acciones={<div className="flex gap-2"><Boton variante="secundario" onClick={() => setSoloNoLeidas((v) => !v)}>{soloNoLeidas ? 'Ver todas' : 'Solo no leídas'}</Boton><Boton onClick={() => void marcarLeidas().then(cargar).catch((e) => setError(mensajeDeError(e)))}>Marcar todas como leídas</Boton></div>} />
      {error && <div className="mb-3"><Aviso>{error}</Aviso></div>}
      {aviso && <div className="mb-3"><Aviso tipo="exito">{aviso}</Aviso></div>}
      <div className="grid gap-5 lg:grid-cols-[2fr_1fr]">
        <div className="rounded-xl border border-slate-200 bg-white" data-testid="bandeja">
          {lista.length === 0 && <p className="p-4 text-sm text-slate-500">Sin notificaciones.</p>}
          <ul className="divide-y divide-slate-100">
            {lista.map((n) => (
              <li key={n.id} className={`px-4 py-3 text-sm ${n.leida_at ? '' : 'bg-primario/5'}`}>
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <p className={n.leida_at ? 'text-slate-800' : 'font-semibold text-slate-900'}>{n.url ? <Link to={n.url} className="hover:underline" onClick={() => void marcarLeidas([n.id])}>{n.asunto}</Link> : n.asunto}</p>
                    {n.cuerpo && <p className="text-slate-600">{n.cuerpo}</p>}
                    <p className="text-xs text-slate-500">{fmtFecha(n.timestamp)} · <Insignia>{n.evento}</Insignia></p>
                  </div>
                  {!n.leida_at && <Boton variante="fantasma" onClick={() => void marcarLeidas([n.id]).then(cargar)}>Leída</Boton>}
                </div>
              </li>
            ))}
          </ul>
        </div>
        <Tarjeta titulo="Preferencias por evento">
          <p className="mb-2 text-xs text-slate-500">Marca por qué canales quieres recibir cada evento.</p>
          <ul className="space-y-2 text-sm" data-testid="preferencias">
            {eventos.map((e) => {
              const canales = prefs[e.clave] ?? e.canales_default
              return (
                <li key={e.clave} className="border-b border-slate-100 pb-1">
                  <p className="font-medium text-slate-800">{e.nombre}</p>
                  <div className="flex gap-3">{CANALES_FASE_1.map((c) => <label key={c} className="flex items-center gap-1 text-xs"><input type="checkbox" checked={canales.includes(c)} onChange={() => void alternar(e.clave, c, e.canales_default)} aria-label={`${e.nombre} por ${c}`} /> {c}</label>)}<span className="text-xs text-slate-400">whatsapp · sms (Fase 2)</span></div>
                </li>
              )
            })}
          </ul>
        </Tarjeta>
      </div>
    </div>
  )
}
