import type { ReactNode } from 'react'
import { CLASE_ESTADO, estadoDePrueba, type EstadoIndicador, type TipoIndicador } from '../services/testbotEstadoVisual'

const TRAZOS: Record<TipoIndicador, ReactNode> = {
  edicion: <><circle cx="12" cy="12" r="9" /><path d="m7.5 12.5 3 3 6-7" /></>,
  alta: <><circle cx="12" cy="12" r="9" /><path d="M12 7v10M7 12h10" /></>,
  consulta: <><circle cx="12" cy="12" r="9" /><path d="M12 11v5" /><circle cx="12" cy="7.5" r=".8" fill="currentColor" stroke="none" /></>,
  pendiente: <><circle cx="12" cy="12" r="9" /><path d="M12 6v6l4 2" /></>,
  error: <><circle cx="12" cy="12" r="9" /><path d="m8.5 8.5 7 7m0-7-7 7" /></>,
  sin_prueba: <><circle cx="12" cy="12" r="9" /><circle cx="12" cy="12" r="2" /></>,
}

/** El color siempre va acompañado de un icono y texto accesible. */
export function IndicadorEstadoTestBot({ estado, compacto = false }: {
  estado?: EstadoIndicador
  compacto?: boolean
}) {
  const actual = estado ?? estadoDePrueba()
  const explicacion = actual.etiqueta + '. ' + actual.explicacion +
    (actual.comprobadoEn ? ' Última prueba: ' + actual.comprobadoEn : '')
  return (
    <span role="img" aria-label={explicacion} title={explicacion}
      data-testid={'estado-testbot-' + actual.tipo}
      className={'inline-flex shrink-0 items-center justify-center gap-1.5 rounded-full border font-semibold ' +
        CLASE_ESTADO[actual.tipo] + (compacto ? ' h-6 w-6' : ' px-2 py-1 text-[11px]')}>
      <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor"
        strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
        className={compacto ? 'h-[16px] w-[16px]' : 'h-4 w-4'}>
        {TRAZOS[actual.tipo]}
      </svg>
      {!compacto && <span>{actual.etiqueta}</span>}
    </span>
  )
}
