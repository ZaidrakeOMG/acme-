import { useState } from 'react'
import { Aviso, Boton, Campo, Insignia, Selector, Tabla, Tarjeta } from '../../../components/ui'
import { useRecurso } from '../../../hooks/useRecurso'
import { api, mensajeDeError } from '../../../services/api'
import type { FamiliaEquipo, TipoFalla } from '../../../types/api'
import { useAmbito } from '../Catalogos'

export function TiposFalla() {
  const ambito = useAmbito()
  const familias = useRecurso<FamiliaEquipo[]>('/catalogos/familias-equipo', ambito.params)
  const [familiaId, setFamiliaId] = useState('')
  const { datos, error, recargar } = useRecurso<TipoFalla[]>('/catalogos/tipos-falla', { ...ambito.params, familia_id: familiaId || undefined, incluir_inactivos: 'true' })
  const [descripcion, setDescripcion] = useState('')
  const [familiaNueva, setFamiliaNueva] = useState('')
  const [aviso, setAviso] = useState<string | null>(null)
  const globales = (familias.datos ?? []).filter((f) => f.es_global)
  const nombreFamilia = (id: string) => familias.datos?.find((f) => f.id === id)?.nombre ?? '—'
  const esSuper = ambito.rol === 'superadmin'

  async function ejecutar(fn: () => Promise<unknown>) {
    setAviso(null)
    try {
      await fn()
      await recargar()
    } catch (e) {
      setAviso(mensajeDeError(e))
    }
  }

  return (
    <Tarjeta
      titulo="Tipos de falla"
      acciones={
        <select aria-label="Familia" value={familiaId} onChange={(e) => setFamiliaId(e.target.value)} className="rounded-lg border border-slate-300 px-2 py-1.5 text-sm">
          <option value="">Todas las familias</option>
          {globales.map((f) => <option key={f.id} value={f.id}>{f.nombre}</option>)}
        </select>
      }
    >
      <p className="mb-3 text-sm text-slate-600">El prestador define los síntomas técnicos por familia; el cliente asigna su severidad en la matriz. «Revisión manual» es un flag global que solo cambia el superadmin.</p>
      {(error || aviso) && <Aviso>{error ?? aviso}</Aviso>}
      <Tabla
        filas={datos ?? []}
        columnas={[
          { titulo: 'Tipo de falla', celda: (t) => <span className={t.activa ? '' : 'text-slate-400 line-through'}>{t.descripcion}</span> },
          { titulo: 'Familia', celda: (t) => nombreFamilia(t.familia_equipo_id) },
          { titulo: 'Revisión manual', celda: (t) => esSuper
              ? <input type="checkbox" aria-label={`Revisión manual ${t.descripcion}`} checked={t.requiere_revision_manual}
                       onChange={(e) => void ejecutar(() => api(`/catalogos/tipos-falla/${t.id}`, { metodo: 'PATCH', params: ambito.params, cuerpo: { requiere_revision_manual: e.target.checked } }))} />
              : (t.requiere_revision_manual ? <Insignia tono="alerta">Sí</Insignia> : <span className="text-xs text-slate-400">No</span>) },
          ...(ambito.puedeEditarPrestador ? [{ titulo: '', celda: (t: TipoFalla) => (
            <Boton variante="fantasma" onClick={() => void ejecutar(() => api(`/catalogos/tipos-falla/${t.id}`, { metodo: 'PATCH', params: ambito.params, cuerpo: { activa: !t.activa } }))}>
              {t.activa ? 'Desactivar' : 'Activar'}
            </Boton>) }] : []),
        ]}
      />
      {ambito.puedeEditarPrestador && (
        <form className="mt-4 flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); void ejecutar(async () => {
          await api('/catalogos/tipos-falla', { metodo: 'POST', params: ambito.params, cuerpo: { descripcion, familia_equipo_id: familiaNueva } })
          setDescripcion('')
        }) }}>
          <div className="flex-1"><Campo etiqueta="Nuevo tipo de falla" name="descripcion" required value={descripcion} onChange={(e) => setDescripcion(e.target.value)} /></div>
          <div className="w-56"><Selector etiqueta="Familia" name="familia_nueva" required value={familiaNueva} onChange={(e) => setFamiliaNueva(e.target.value)}
                    opciones={[{ valor: '', texto: 'Selecciona…' }, ...globales.map((f) => ({ valor: f.id, texto: f.nombre }))]} /></div>
          <Boton type="submit" variante="secundario">Agregar</Boton>
        </form>
      )}
    </Tarjeta>
  )
}
