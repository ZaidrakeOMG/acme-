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
      <Link to="/notificaciones" aria-label={`Notificaciones: ${n} sin leer`} className="relative inline-flex min-h-11 min-w-11 items-center justify-center rounded-lg text-slate-600 hover:bg-slate-100" data-testid="campana">
        <svg aria-hidden="true" className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
          <path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9ZM10 21h4" />
        </svg>
        {n > 0 && <span className="absolute -right-0.5 -top-0.5 rounded-full bg-red-600 px-1.5 text-[10px] font-semibold text-white">{n > 99 ? '99+' : n}</span>}
      </Link>
      <button aria-label="Panel de alertas" onClick={() => setAlertas((v) => !v)} data-testid="campana-alertas"
        className="hidden min-h-11 min-w-11 items-center justify-center rounded-lg text-slate-600 hover:bg-slate-100 sm:inline-flex">
          <svg aria-hidden="true" className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 3 2 20h20L12 3ZM12 9v5M12 17h.01" />
          </svg>
        </button>
      {alertas && <PanelAlertas alCerrar={() => setAlertas(false)} />}
    </div>
  )
}
