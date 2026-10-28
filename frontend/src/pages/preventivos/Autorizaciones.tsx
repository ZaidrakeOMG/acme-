import { useState } from 'react'
import { Link } from 'react-router'
import { Aviso, Boton, Encabezado, Insignia, Selector, Tabla } from '../../components/ui'
import { useAuth } from '../../contexts/AuthContext'
import { useRecurso } from '../../hooks/useRecurso'
import { mensajeDeError } from '../../services/api'
import { resolverAutorizacion } from '../../services/preventivos'
import type { CanalAprobacion } from '../../types/folios'
import type { Autorizacion } from '../../types/preventivos'
import { EstadoInsignia, fecha } from '../folios/comunes'

/** Bandeja de autorizaciones de preventivos (§6.9.1): reprogramaciones y cancelaciones que el cliente debe autorizar. */
export function Autorizaciones() {
  const { usuario } = useAuth()
  const [estado, setEstado] = useState('pendiente')
  const { datos, error, recargar } = useRecurso<Autorizacion[]>('/preventivos/autorizaciones', { estado: estado || undefined })
  const [fallo, setFallo] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)
  const lista = datos ?? []

  async function resolver(a: Autorizacion, autorizar: boolean) {
    const notas = window.prompt(autorizar ? 'Notas (opcional)' : 'Motivo del rechazo') ?? ''
    if (!autorizar && !notas.trim()) return
    const canal: CanalAprobacion = 'app'
    try {
      await resolverAutorizacion(a.id, autorizar, notas, canal)
      setAviso(`${a.tipo === 'reprogramacion' ? 'Reprogramación' : 'Cancelación'} del folio ${a.numero_folio} ${autorizar ? 'autorizada' : 'rechazada'}`)
      await recargar()
    } catch (e) {
      setFallo(mensajeDeError(e))
    }
  }

  return (
    <div>
      <Encabezado titulo="Autorizaciones de preventivos" descripcion="El Despachador solicita reprogramar o cancelar un preventivo; lo autoriza el Admin UN de la unidad o el Admin empresa. Cada decisión queda en el historial del folio."
                  acciones={<Link to="/preventivos/calendario"><Boton variante="secundario">Calendario</Boton></Link>} />
      <div className="mb-4">
        <Selector etiqueta="Estado" value={estado} onChange={(e) => setEstado(e.target.value)} opciones={[{ valor: 'pendiente', texto: 'Pendientes' }, { valor: 'autorizada', texto: 'Autorizadas' }, { valor: 'rechazada', texto: 'Rechazadas' }, { valor: '', texto: 'Todas' }]} />
      </div>
      {(error || fallo) && <div className="mb-3"><Aviso>{error ?? fallo}</Aviso></div>}
      {aviso && <div className="mb-3"><Aviso tipo="exito">{aviso}</Aviso></div>}
      <div className="rounded-xl border border-slate-200 bg-white p-2">
        <Tabla
          filas={lista}
          vacio="Sin solicitudes"
          columnas={[
            { titulo: 'Folio', celda: (a) => <Link to={`/folios/${a.folio_id}`} className="font-mono text-xs text-primario underline">{a.numero_folio}</Link> },
            { titulo: 'Solicitud', celda: (a) => <span><Insignia tono={a.tipo === 'cancelacion' ? 'alerta' : 'acento'}>{a.tipo === 'reprogramacion' ? 'Reprogramación' : 'Cancelación'}</Insignia>{a.fecha_nueva && <span className="block text-xs">{a.fecha_programada} → <strong>{a.fecha_nueva}</strong></span>}</span> },
            { titulo: 'Razón', celda: (a) => <span className="text-sm">{a.razon}<span className="block text-xs text-slate-500">{a.solicitado_por_nombre} · {fecha(a.fecha_solicitud)}</span></span> },
            { titulo: 'Estado', celda: (a) => <span><Insignia tono={a.estado === 'pendiente' ? 'alerta' : a.estado === 'autorizada' ? 'ok' : 'neutro'}>{a.estado}</Insignia>{a.autorizado_por_nombre && <span className="block text-xs text-slate-500">{a.autorizado_por_nombre} · {a.canal} · {fecha(a.fecha_autorizacion)}</span>}{a.notas_respuesta && <span className="block text-xs">{a.notas_respuesta}</span>}</span> },
            { titulo: 'Folio hoy', celda: (a) => a.estado_folio ? <EstadoInsignia estado={a.estado_folio} /> : null },
            { titulo: '', celda: (a) => a.estado === 'pendiente' && a.puede_resolver && usuario ? (
              <div className="flex gap-1"><Boton onClick={() => void resolver(a, true)}>Autorizar</Boton><Boton variante="peligro" onClick={() => void resolver(a, false)}>Rechazar</Boton></div>
            ) : null },
          ]}
        />
      </div>
    </div>
  )
}
