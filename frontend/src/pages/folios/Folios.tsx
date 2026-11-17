import { useMemo, useState } from 'react'
import { Link } from 'react-router'
import { Buscador } from '../../components/Buscador'
import { Aviso, Boton, Encabezado, Insignia, Tabla } from '../../components/ui'
import { useAuth } from '../../contexts/AuthContext'
import { useRecurso } from '../../hooks/useRecurso'
import type { Severidad, UnidadNegocio } from '../../types/api'
import type { EstadoFolio, FolioResumen } from '../../types/folios'
import { ESTADOS_FOLIO, NOMBRE_ESTADO } from '../../types/folios'
import { EstadoInsignia, ROLES_APROBADOR, ROLES_CAPTURA, SeveridadInsignia, TarjetaFolio, antiguedad } from './comunes'

/** Listado de folios con filtros y alcance por rol (§5); vista Kanban opcional por estado. */
export function Folios() {
  const { usuario } = useAuth()
  const [vista, setVista] = useState<'tabla' | 'kanban'>('tabla')
  const [estado, setEstado] = useState('')
  const [unId, setUnId] = useState('')
  const [severidadId, setSeveridadId] = useState('')
  const [tipo, setTipo] = useState('')
  const [q, setQ] = useState('')
  const unidades = useRecurso<UnidadNegocio[]>('/unidades-negocio')
  const severidades = useRecurso<Severidad[]>('/catalogos/severidades')
  const { datos, error, cargando } = useRecurso<FolioResumen[]>('/folios', {
    estado: estado || undefined, un_id: unId || undefined, severidad_id: severidadId || undefined, tipo_folio: tipo || undefined, q: q || undefined,
  })
  const folios = datos ?? []
  const porEstado = useMemo(() => Object.fromEntries(ESTADOS_FOLIO.map((e) => [e, folios.filter((f) => f.estado === e)])) as Record<EstadoFolio, FolioResumen[]>, [folios])
  const puedeCapturar = usuario && ROLES_CAPTURA.includes(usuario.rol)
  const esAprobador = usuario && ROLES_APROBADOR.includes(usuario.rol)

  return (
    <div>
      <Encabezado
        titulo="Folios"
        descripcion="Ciclo de vida de §6.8.6: captura con validaciones automáticas, revisión, aprobación multinivel, asignación y cierre."
        acciones={
          <div className="flex flex-wrap gap-2">
            {esAprobador && <Link to="/folios/aprobaciones"><Boton variante="secundario">Aprobaciones</Boton></Link>}
            {puedeCapturar && <Link to="/folios/nuevo"><Boton>Nuevo folio</Boton></Link>}
          </div>
        }
      />
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <select aria-label="Estado" value={estado} onChange={(e) => setEstado(e.target.value)} className="min-h-11 w-full min-w-0 rounded-lg border border-slate-300 bg-white px-3 py-2 text-base sm:w-auto sm:text-sm">
          <option value="">Todos los estados</option>
          {ESTADOS_FOLIO.map((e) => <option key={e} value={e}>{NOMBRE_ESTADO[e]}</option>)}
        </select>
        <select aria-label="Unidad de negocio" value={unId} onChange={(e) => setUnId(e.target.value)} className="min-h-11 w-full min-w-0 rounded-lg border border-slate-300 bg-white px-3 py-2 text-base sm:w-auto sm:text-sm">
          <option value="">Todas las UNs</option>
          {(unidades.datos ?? []).map((u) => <option key={u.id} value={u.id}>{u.codigo} · {u.nombre}</option>)}
        </select>
        <select aria-label="Severidad" value={severidadId} onChange={(e) => setSeveridadId(e.target.value)} className="min-h-11 w-full min-w-0 rounded-lg border border-slate-300 bg-white px-3 py-2 text-base sm:w-auto sm:text-sm">
          <option value="">Toda severidad</option>
          {(severidades.datos ?? []).map((s) => <option key={s.id} value={s.id}>{s.nombre}</option>)}
        </select>
        <select aria-label="Tipo" value={tipo} onChange={(e) => setTipo(e.target.value)} className="min-h-11 w-full min-w-0 rounded-lg border border-slate-300 bg-white px-3 py-2 text-base sm:w-auto sm:text-sm">
          <option value="">Todo tipo</option>
          <option value="correctivo">Correctivo</option><option value="preventivo">Preventivo</option><option value="especial">Especial</option>
        </select>
        <Buscador etiqueta="Buscar folio" placeholder="Número o descripción" alBuscar={setQ} />
        <div className="ml-auto flex w-full gap-1 text-sm sm:w-auto">
          <button className={`min-h-11 flex-1 rounded-lg px-3 py-2 sm:flex-none ${vista === 'tabla' ? 'bg-primario text-white' : 'border border-slate-300'}`} onClick={() => setVista('tabla')}>Tabla</button>
          <button className={`rounded-lg px-3 py-1.5 ${vista === 'kanban' ? 'bg-primario text-white' : 'border border-slate-300'}`} onClick={() => setVista('kanban')}>Kanban</button>
        </div>
      </div>
      {error && <div className="mb-4"><Aviso>{error}</Aviso></div>}
      {cargando && !datos && <p className="text-sm text-slate-500">Cargando folios…</p>}
      {vista === 'tabla' ? (
        <div className="rounded-xl border border-slate-200 bg-white p-2">
          <Tabla
            filas={folios}
            vacio="No hay folios con esos filtros"
            columnas={[
              { titulo: 'Folio', celda: (f) => <Link to={`/folios/${f.id}`} className="font-mono text-xs font-semibold text-primario underline">{f.numero_folio}</Link> },
              { titulo: 'Estado', celda: (f) => <div className="flex flex-wrap items-center gap-1"><EstadoInsignia estado={f.estado} />{f.es_instalacion_activo && f.estado === 'en_revision' && <Insignia tono="alerta">Esperando OC del cliente</Insignia>}{f.tipo_folio === 'especial' && <Insignia tono="acento">TE</Insignia>}{f.flujo && f.flujo.estado !== 'aprobado' && f.flujo.estado !== 'rechazado' && <Insignia tono="acento">Nivel {f.flujo.nivel_actual}</Insignia>}{f.triggers_pendientes > 0 && <Insignia tono="alerta">{f.triggers_pendientes} trigger(s)</Insignia>}</div> },
              { titulo: 'Severidad', celda: (f) => <SeveridadInsignia severidad={f.severidad} /> },
              { titulo: 'UN', celda: (f) => <span>{f.un_codigo} <span className="text-xs text-slate-500">{f.un_nombre}</span></span> },
              { titulo: 'Equipo', celda: (f) => <span>{f.equipo_codigo} <span className="text-xs text-slate-500">{f.equipo_nombre}</span></span> },
              { titulo: 'Técnico', celda: (f) => f.tecnico_nombre ?? <span className="text-xs text-slate-400">—</span> },
              { titulo: 'Antigüedad', celda: (f) => <span className="text-xs text-slate-600">{antiguedad(f.antiguedad_horas)}</span> },
            ]}
          />
        </div>
      ) : (
        <div className="flex snap-x snap-mandatory gap-3 overflow-x-auto pb-2" data-testid="kanban">
          {ESTADOS_FOLIO.map((e) => (
            <section key={e} aria-label={NOMBRE_ESTADO[e]} className="w-[min(80vw,18rem)] shrink-0 snap-start rounded-xl bg-slate-100 p-2 sm:w-64">
              <h2 className="mb-2 px-1 text-xs font-semibold uppercase tracking-wide text-slate-600">{NOMBRE_ESTADO[e]} <span className="text-slate-400">{porEstado[e].length}</span></h2>
              <div className="space-y-2">
                {porEstado[e].map((f) => (
                  <Link key={f.id} to={`/folios/${f.id}`} className="block"><TarjetaFolio folio={f} /></Link>
                ))}
              </div>
            </section>
          ))}
        </div>
      )}
    </div>
  )
}
