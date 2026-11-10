import { useEffect, useState } from 'react'
import { Insignia, Tarjeta } from '../../components/ui'
import { enviosDelFolio } from '../../services/mensajeria'
import type { Envio } from '../../types/mensajeria'
import { NOMBRE_ESTADO_ENVIO } from '../../types/mensajeria'
import { fecha as fmtFecha } from './comunes'

const TONO: Record<string, 'neutro' | 'ok' | 'alerta' | 'acento'> = {
  en_cola: 'neutro', enviado: 'acento', entregado: 'ok', leido: 'ok', fallido: 'alerta',
  rechazado_por_proveedor: 'alerta',
}

/**
 * «Por qué canales se avisó de este folio y en qué estado va la entrega» (F2-02). Solo lo ven los roles que
 * consultan la bitácora de mensajería; si el servidor lo niega, la tarjeta no se dibuja.
 */
export function AvisosFolio({ folioId }: { folioId: string }) {
  const [lista, setLista] = useState<Envio[] | null>(null)

  useEffect(() => {
    let cancelado = false
    void enviosDelFolio(folioId)
      .then((r) => { if (!cancelado) setLista(r) })
      .catch(() => { if (!cancelado) setLista(null) })
    return () => { cancelado = true }
  }, [folioId])

  if (!lista || lista.length === 0) return null

  return (
    <Tarjeta titulo="Avisos por WhatsApp y SMS">
      <ul className="space-y-2 text-sm" data-testid="avisos-del-folio">
        {lista.map((e) => (
          <li key={e.id} className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 pb-1">
            <span>
              <span className="font-medium text-slate-800">{e.canal === 'whatsapp' ? 'WhatsApp' : 'SMS'}</span>
              <span className="text-xs text-slate-500"> · {e.telefono} · {e.plantilla} · {fmtFecha(e.created_at)}</span>
              {e.detalle_error && <span className="block text-xs text-red-700">{e.codigo_error}: {e.detalle_error}</span>}
            </span>
            <span className="flex items-center gap-2">
              {e.abierto_at && <span className="text-xs text-emerald-700">abrió el enlace</span>}
              <Insignia tono={TONO[e.estado]}>{NOMBRE_ESTADO_ENVIO[e.estado]}</Insignia>
            </span>
          </li>
        ))}
      </ul>
      <p className="mt-2 text-xs text-slate-500">
        Cuando un aviso no puede salir por WhatsApp o SMS —sin consentimiento, horario de silencio, tope del mes—
        cae al siguiente canal y el motivo queda en la bitácora de mensajería.
      </p>
    </Tarjeta>
  )
}
