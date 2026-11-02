import { useEffect, useState } from 'react'
import { Link } from 'react-router'
import { noLeidas } from '../services/minutas'
import { PanelAlertas } from './PanelAlertas'

/** Campana de la cabecera: conteo de notificaciones no leídas (se refresca cada minuto y al volver a la pestaña). */
export function CampanaNotificaciones() {
  const [n, setN] = useState(0)
  const [alertas, setAlertas] = useState(false)
  useEffect(() => {
    let activo = true
    const cargar = () => noLeidas().then((r) => { if (activo) setN(r.no_leidas) }).catch(() => undefined)
    void cargar()
    const t = setInterval(cargar, 60000)
    const alVolver = () => { if (document.visibilityState === 'visible') void cargar() }
    document.addEventListener('visibilitychange', alVolver)
    return () => { activo = false; clearInterval(t); document.removeEventListener('visibilitychange', alVolver) }
  }, [])
  return (
    <div className="relative flex items-center">
      <Link to="/notificaciones" aria-label={`Notificaciones: ${n} sin leer`} className="relative rounded-lg px-2 py-1.5 text-lg text-slate-600 hover:bg-slate-100" data-testid="campana">
        🔔
        {n > 0 && <span className="absolute -right-0.5 -top-0.5 rounded-full bg-red-600 px-1.5 text-[10px] font-semibold text-white">{n > 99 ? '99+' : n}</span>}
      </Link>
      <button aria-label="Panel de alertas" onClick={() => setAlertas((v) => !v)} data-testid="campana-alertas"
        className="rounded-lg px-2 py-1.5 text-lg text-slate-600 hover:bg-slate-100">⚠️</button>
      {alertas && <PanelAlertas alCerrar={() => setAlertas(false)} />}
    </div>
  )
}
