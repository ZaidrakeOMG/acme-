import { useEffect, useState } from 'react'
import { Link } from 'react-router'
import { Aviso, Boton } from '../../../components/ui'
import { useConexion } from '../../../hooks/useConexion'
import { api, mensajeDeError } from '../../../services/api'
import { foliosCampo, type FolioLocal } from '../../../services/campo'
import { EstadoInsignia, SeveridadInsignia, antiguedad } from '../../folios/comunes'

const ACTIVOS = new Set(['asignado', 'reasignado', 'en_camino', 'en_ejecucion', 'pendiente_refaccion'])

/** App del técnico: folios asignados para hoy y próximos, con estado; las acciones se ejecutan en la atención. */
export function MisFolios() {
  const { enLinea, pendientes } = useConexion()
  const [folios, setFolios] = useState<FolioLocal[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [puedeCrear, setPuedeCrear] = useState(false)

  useEffect(() => {
    foliosCampo({ limite: '200' }).then(setFolios).catch((e) => setError(mensajeDeError(e)))
    api<{ clave: string; habilitado: boolean }[]>('/configuracion/mis-permisos').then((p) => setPuedeCrear(p.some((x) => x.clave === 'crear_folio_en_campo' && x.habilitado))).catch(() => undefined)
  }, [enLinea, pendientes])

  const hoy = new Date().toDateString()
  const activos = (folios ?? []).filter((f) => ACTIVOS.has(f.estado))
  const deHoy = activos.filter((f) => new Date(f.capturado_at).toDateString() === hoy || f.estado !== 'asignado')
  const proximos = activos.filter((f) => !deHoy.includes(f))
  const Lista = ({ titulo, items }: { titulo: string; items: FolioLocal[] }) => (
    <section>
      <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">{titulo} · {items.length}</h2>
      {items.length === 0 && <p className="text-sm text-slate-400">Nada por aquí.</p>}
      <ul className="space-y-3">
        {items.map((f) => (
          <li key={f.id}>
            <Link to={`/campo/folio/${f.id}`} data-testid={`folio-campo-${f.numero_folio}`} className="block rounded-xl border border-slate-200 bg-white p-4 shadow-sm active:bg-slate-50">
              <div className="flex items-center justify-between gap-2">
                <span className="font-mono text-sm font-semibold">{f.numero_folio}</span>
                <EstadoInsignia estado={f.estado} />
              </div>
              <p className="mt-1 text-base text-slate-800">{f.descripcion}</p>
              <p className="mt-1 text-xs text-slate-500">{f.un_codigo} · {f.un_nombre} · {f.equipo_codigo} {f.equipo_nombre}</p>
              <div className="mt-2 flex items-center gap-2 text-xs"><SeveridadInsignia severidad={f.severidad} /><span className="text-slate-500">hace {antiguedad(f.antiguedad_horas)}</span></div>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  )
  return (
    <div className="mx-auto max-w-lg space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-xs uppercase tracking-wide text-slate-500">App del técnico</p>
          <h1 className="text-xl font-semibold text-slate-900">Mis folios</h1>
        </div>
        {puedeCrear && <Link to="/campo/nuevo"><Boton className="min-h-12 text-base">Nuevo folio</Boton></Link>}
      </div>
      {!enLinea && <Aviso tipo="info">Sin conexión: trabajas con la última lista descargada; tus acciones se encolan.</Aviso>}
      {error && <Aviso>{error}</Aviso>}
      <Lista titulo="Hoy" items={deHoy} />
      <Lista titulo="Próximos" items={proximos} />
    </div>
  )
}
