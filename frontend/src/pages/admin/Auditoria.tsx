import { useState } from 'react'
import { Aviso, Encabezado, Tabla, Tarjeta } from '../../components/ui'
import { useRecurso } from '../../hooks/useRecurso'
import type { EventoAuditoria } from '../../types/api'

export function Auditoria() {
  const [tipo, setTipo] = useState('')
  const { datos, error } = useRecurso<EventoAuditoria[]>('/auditoria/eventos', { evento_tipo: tipo || undefined })
  return (
    <div>
      <Encabezado titulo="Auditoría" descripcion="Registro inmutable de eventos de seguridad (ISO 27001). Solo lectura." />
      <Tarjeta
        acciones={
          <input aria-label="Filtrar por tipo de evento" placeholder="Tipo de evento (ej. auth.)" value={tipo} onChange={(e) => setTipo(e.target.value)} className="w-64 rounded-lg border border-slate-300 px-3 py-1.5 text-sm" />
        }
      >
        {error && <Aviso>{error}</Aviso>}
        <Tabla
          filas={datos ?? []}
          columnas={[
            { titulo: 'Fecha', celda: (e) => <span className="whitespace-nowrap text-xs">{new Date(e.created_at).toLocaleString('es-MX')}</span> },
            { titulo: 'Evento', celda: (e) => <span className="font-mono text-xs">{e.evento_tipo}</span> },
            { titulo: 'Actor', celda: (e) => <span className="text-xs">{e.actor_rol ?? '—'}</span> },
            { titulo: 'Recurso', celda: (e) => <span className="text-xs">{e.recurso_tipo ?? ''} {e.recurso_id?.slice(0, 8) ?? ''}</span> },
            { titulo: 'IP', celda: (e) => <span className="text-xs">{e.ip_origen ?? '—'}</span> },
          ]}
        />
      </Tarjeta>
    </div>
  )
}
