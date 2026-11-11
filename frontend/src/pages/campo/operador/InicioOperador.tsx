import { useEffect, useState } from 'react'
import { Link } from 'react-router'
import { Aviso, Boton } from '../../../components/ui'
import { useAuth } from '../../../contexts/AuthContext'
import { useConexion } from '../../../hooks/useConexion'
import { mensajeDeError } from '../../../services/api'
import { foliosCampo, type FolioLocal } from '../../../services/campo'
import { EstadoInsignia, SeveridadInsignia, antiguedad } from '../../folios/comunes'

const ABIERTOS = new Set(['capturado', 'en_revision', 'pendiente_informacion', 'autorizado', 'asignado', 'reasignado', 'en_camino', 'en_ejecucion', 'pendiente_refaccion'])

/** §5.1: el operador ve los folios abiertos de su UN asignada (de cualquier operador de esa UN); sin acceso a otras UNs. */
export function InicioOperador() {
  const { usuario } = useAuth()
  const { enLinea, pendientes } = useConexion()
  const [folios, setFolios] = useState<FolioLocal[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [verCerrados, setVerCerrados] = useState(false)

  useEffect(() => {
    foliosCampo({ limite: '200' }).then(setFolios).catch((e) => setError(mensajeDeError(e)))
  }, [enLinea, pendientes])

  const lista = (folios ?? []).filter((f) => verCerrados || ABIERTOS.has(f.estado))
  return (
    <div className="mx-auto max-w-lg space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-xs uppercase tracking-wide text-slate-500">App del operador</p>
          <h1 className="text-xl font-semibold text-slate-900">Folios de mi unidad</h1>
        </div>
        <div className="flex gap-2">
          {/* F2-04 (§6.9.2): el operador lee el marcador de los equipos de su unidad, con o sin señal. */}
          <Link to="/campo/lectura"><Boton variante="secundario" className="min-h-12 px-4 text-base">Registrar lectura</Boton></Link>
          <Link to="/campo/nuevo"><Boton className="min-h-12 px-5 text-base">Nuevo folio</Boton></Link>
        </div>
      </div>
      {!enLinea && <Aviso tipo="info">Sin conexión: ves la última información guardada y puedes capturar; se enviará al recuperar señal.</Aviso>}
      {error && <Aviso>{error}</Aviso>}
      <label className="flex items-center gap-2 text-sm text-slate-600"><input type="checkbox" checked={verCerrados} onChange={(e) => setVerCerrados(e.target.checked)} /> Mostrar cerrados y cancelados</label>
      {folios && lista.length === 0 && <p className="rounded-xl border border-dashed border-slate-300 p-6 text-center text-sm text-slate-500">No hay folios abiertos en tu unidad.</p>}
      <ul className="space-y-3">
        {lista.map((f) => (
          <li key={f.id}>
            <Link to={`/campo/folio/${f.id}`} data-testid={`folio-campo-${f.numero_folio}`} className="block rounded-xl border border-slate-200 bg-white p-4 shadow-sm active:bg-slate-50">
              <div className="flex items-center justify-between gap-2">
                <span className="font-mono text-sm font-semibold">{f.pendiente ? 'Pendiente de enviar' : f.numero_folio}</span>
                <EstadoInsignia estado={f.estado} />
              </div>
              <p className="mt-1 line-clamp-2 text-base text-slate-800">{f.descripcion}</p>
              <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                <SeveridadInsignia severidad={f.severidad} />
                <span>{f.equipo_codigo ?? 'Equipo'} {f.equipo_nombre ?? ''}</span>
                <span>· hace {antiguedad(f.antiguedad_horas)}</span>
              </div>
              <div className="mt-2 grid grid-cols-2 gap-2 text-xs">
                <div className="rounded-lg bg-slate-50 p-2"><p className="text-slate-500">Técnico</p><p className="font-medium text-slate-800">{f.tecnico_nombre ?? 'Sin asignar'}</p></div>
                <div className="rounded-lg bg-slate-50 p-2"><p className="text-slate-500">Llegada estimada</p><p className="font-medium text-slate-400">Disponible en Fase 2</p></div>
              </div>
            </Link>
          </li>
        ))}
      </ul>
      {usuario?.rol === 'admin_un' && <p className="text-center text-xs text-slate-400">Como Admin UN ves los folios de tus unidades asignadas.</p>}
    </div>
  )
}
