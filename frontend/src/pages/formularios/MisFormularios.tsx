import { Link } from 'react-router'
import { Aviso, Boton, Encabezado, Insignia, Tarjeta } from '../../components/ui'
import { useRecurso } from '../../hooks/useRecurso'
import type { Formulario, Respuesta } from '../../types/formularios'

interface Mio { formulario: Formulario; en_progreso: Respuesta[]; enviados: number }

/** Formularios publicados dirigidos a mi rol: iniciar, reanudar en progreso y consultar enviados. */
export function MisFormularios() {
  const { datos, error } = useRecurso<Mio[]>('/formularios/mis-formularios')
  const enviados = useRecurso<Respuesta[]>('/formularios/respuestas', { mias: 'true', estado: 'enviado' })
  return (
    <div className="space-y-6">
      <Encabezado titulo="Mis formularios" descripcion="Formularios dirigidos a tu rol. Puedes reanudar los que dejaste en progreso; los enviados son de solo lectura." />
      {error && <Aviso>{error}</Aviso>}
      <div className="grid gap-4 sm:grid-cols-2">
        {(datos ?? []).map(({ formulario, en_progreso, enviados: n }) => (
          <Tarjeta key={formulario.id} titulo={formulario.nombre} acciones={<Insignia tono="acento">{formulario.tipo.replace('_', ' ')}</Insignia>}>
            <p className="mb-3 text-sm text-slate-600">{formulario.descripcion || 'Sin descripción'}</p>
            <div className="flex flex-wrap items-center gap-2">
              <Link to={`/formularios/llenar/${formulario.id}`}><Boton>Iniciar</Boton></Link>
              <span className="text-xs text-slate-500">{n} enviado(s)</span>
            </div>
            {en_progreso.length > 0 && (
              <ul className="mt-3 space-y-1 border-t border-slate-100 pt-2 text-sm">
                {en_progreso.map((r) => (
                  <li key={r.id} className="flex items-center justify-between">
                    <span className="text-slate-600">En progreso desde {new Date(r.iniciado_at).toLocaleString('es-MX')}</span>
                    <Link to={`/formularios/llenar/${formulario.id}?respuesta=${r.id}`} className="text-primario underline">Reanudar</Link>
                  </li>
                ))}
              </ul>
            )}
          </Tarjeta>
        ))}
        {datos && datos.length === 0 && <p className="text-sm text-slate-500">No hay formularios publicados para tu rol.</p>}
      </div>
      {enviados.datos && enviados.datos.length > 0 && (
        <Tarjeta titulo="Enviados recientemente">
          <ul className="divide-y divide-slate-100 text-sm">
            {enviados.datos.map((r) => (
              <li key={r.id} className="flex items-center justify-between py-2">
                <span>{r.nombre_formulario} · v{r.numero_version} · {new Date(r.enviado_at!).toLocaleString('es-MX')}</span>
                <Link to={`/formularios/llenar/${r.formulario_id}?respuesta=${r.id}`} className="text-primario underline">Ver</Link>
              </li>
            ))}
          </ul>
        </Tarjeta>
      )}
    </div>
  )
}
