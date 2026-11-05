import { useState } from 'react'
import { Aviso, Boton, Campo, Encabezado, Insignia, Tabla, Tarjeta } from '../../components/ui'
import { useAuth } from '../../contexts/AuthContext'
import { useRecurso } from '../../hooks/useRecurso'
import { mensajeDeError } from '../../services/api'
import { crearRazon, editarRazon } from '../../services/preventivos'
import type { Conteo, RazonReasignacion, ReporteReasignaciones } from '../../types/preventivos'

function primerDiaDelMes(): string {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-01`
}

function TablaConteo({ titulo, filas, testid }: { titulo: string; filas: Conteo[]; testid: string }) {
  return (
    <Tarjeta titulo={titulo}>
      <table className="w-full text-sm" data-testid={testid}>
        <tbody className="divide-y divide-slate-100">
          {filas.length === 0 && <tr><td className="py-2 text-slate-500">Sin datos en el período</td></tr>}
          {filas.map((f) => (
            <tr key={f.nombre}>
              <td className="py-1 pr-2">{f.nombre}</td>
              <td className="w-16 py-1 text-right font-mono text-xs">{f.total}</td>
              <td className="w-40 py-1 pl-2">
                <div className="flex items-center gap-2"><div className="h-2 flex-1 rounded bg-slate-100"><div className="h-2 rounded bg-primario" style={{ width: `${f.porcentaje}%` }} /></div><span className="w-12 text-right text-xs text-slate-600">{f.porcentaje}%</span></div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Tarjeta>
  )
}

/** Reporte de reasignaciones por período (§4.1: principales causas) y catálogo de razones del prestador (§6.8.2). */
export function Reporte() {
  const { usuario } = useAuth()
  const [desde, setDesde] = useState(primerDiaDelMes())
  const [hasta, setHasta] = useState(new Date().toISOString().slice(0, 10))
  const { datos, error } = useRecurso<ReporteReasignaciones>('/reasignaciones/reporte', { desde: desde || undefined, hasta: hasta || undefined })
  const esAdminPrestador = usuario?.rol === 'admin_prestador' || usuario?.rol === 'superadmin'
  const razones = useRecurso<RazonReasignacion[]>(usuario && ['superadmin', 'admin_prestador', 'despachador', 'mesa_control'].includes(usuario.rol) ? '/reasignaciones/razones' : null, { incluir_inactivas: 'true' })
  const [nueva, setNueva] = useState({ descripcion: '', detalle: '' })
  const [fallo, setFallo] = useState<string | null>(null)

  async function alta() {
    try {
      await crearRazon({ descripcion: nueva.descripcion, detalle: nueva.detalle, activa: true, orden_display: (razones.datos?.length ?? 0) + 1 })
      setNueva({ descripcion: '', detalle: '' })
      await razones.recargar()
    } catch (e) {
      setFallo(mensajeDeError(e))
    }
  }
  async function alternar(r: RazonReasignacion) {
    try {
      await editarRazon(r.id, { descripcion: r.descripcion, detalle: r.detalle, activa: !r.activa, orden_display: r.orden_display })
      await razones.recargar()
    } catch (e) {
      setFallo(mensajeDeError(e))
    }
  }

  return (
    <div>
      <Encabezado titulo="Reasignaciones" descripcion="Principales causas de reasignación por período, técnicos origen y destino. Las razones se eligen del catálogo del prestador al reasignar desde el folio." />
      <div className="mb-4 flex flex-wrap items-end gap-2">
        <Campo etiqueta="Desde" type="date" value={desde} onChange={(e) => setDesde(e.target.value)} />
        <Campo etiqueta="Hasta" type="date" value={hasta} onChange={(e) => setHasta(e.target.value)} />
        {datos && <Insignia tono="acento">{datos.total} reasignaciones</Insignia>}
      </div>
      {(error || fallo) && <div className="mb-3"><Aviso>{error ?? fallo}</Aviso></div>}
      {datos && (
        <div className="grid gap-4 lg:grid-cols-2">
          <TablaConteo titulo="Por razón" filas={datos.por_razon} testid="por-razon" />
          <TablaConteo titulo="Por tipo" filas={datos.por_tipo} testid="por-tipo" />
          <TablaConteo titulo="Técnico origen" filas={datos.por_tecnico_origen} testid="por-origen" />
          <TablaConteo titulo="Técnico destino" filas={datos.por_tecnico_destino} testid="por-destino" />
        </div>
      )}
      {razones.datos && (
        <div className="mt-6">
          <Tarjeta titulo="Catálogo de razones">
            <Tabla
              filas={razones.datos}
              columnas={[
                { titulo: '#', celda: (r) => String(r.orden_display) },
                { titulo: 'Razón', celda: (r) => <span>{r.descripcion}<span className="block text-xs text-slate-500">{r.detalle}</span></span> },
                { titulo: 'Estado', celda: (r) => <Insignia tono={r.activa ? 'ok' : 'neutro'}>{r.activa ? 'activa' : 'inactiva'}</Insignia> },
                { titulo: '', celda: (r) => esAdminPrestador ? <Boton variante="fantasma" onClick={() => void alternar(r)}>{r.activa ? 'Desactivar' : 'Activar'}</Boton> : null },
              ]}
            />
            {esAdminPrestador && (
              <form className="mt-3 grid gap-2 sm:grid-cols-[1fr_2fr_auto]" onSubmit={(e) => { e.preventDefault(); void alta() }}>
                <Campo etiqueta="Nueva razón" value={nueva.descripcion} onChange={(e) => setNueva({ ...nueva, descripcion: e.target.value })} minLength={3} required />
                <Campo etiqueta="Detalle" value={nueva.detalle} onChange={(e) => setNueva({ ...nueva, detalle: e.target.value })} />
                <Boton type="submit" variante="secundario" className="self-end">Agregar</Boton>
              </form>
            )}
          </Tarjeta>
        </div>
      )}
    </div>
  )
}
