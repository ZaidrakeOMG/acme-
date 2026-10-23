import { useState } from 'react'
import { Aviso, Boton, Campo, Insignia, Tarjeta } from '../../../components/ui'
import { useRecurso } from '../../../hooks/useRecurso'
import { api, mensajeDeError } from '../../../services/api'
import type { FamiliaEquipo, TipoEquipo } from '../../../types/api'
import { useAmbito } from '../Catalogos'

/** Familias (globales + propias) y, en cascada, los tipos de equipo de la familia elegida (§4.3). */
export function FamiliasTipos() {
  const ambito = useAmbito()
  const familias = useRecurso<FamiliaEquipo[]>('/catalogos/familias-equipo', ambito.params)
  const [familiaId, setFamiliaId] = useState<string | null>(null)
  const tipos = useRecurso<TipoEquipo[]>(familiaId ? '/catalogos/tipos-equipo' : null, { ...ambito.params, familia_id: familiaId ?? undefined })
  const [error, setError] = useState<string | null>(null)
  const [nuevaFamilia, setNuevaFamilia] = useState('')
  const [nuevoTipo, setNuevoTipo] = useState('')
  const [global, setGlobal] = useState(false)
  const puedeCrear = ambito.puedeEditarTenant || ambito.rol === 'superadmin'
  const familia = familias.datos?.find((f) => f.id === familiaId)

  async function crear(ruta: string, cuerpo: Record<string, unknown>, despues: () => Promise<void>) {
    setError(null)
    try {
      await api(ruta, { metodo: 'POST', params: ambito.params, cuerpo })
      await despues()
    } catch (e) {
      setError(mensajeDeError(e))
    }
  }

  return (
    <div className="grid gap-4 md:grid-cols-2">
      <Tarjeta titulo="Familias de equipo">
        {(familias.error || error) && <Aviso>{familias.error ?? error}</Aviso>}
        <ul className="divide-y divide-slate-100">
          {(familias.datos ?? []).map((f) => (
            <li key={f.id}>
              <button className={`flex w-full items-center justify-between px-2 py-2 text-left text-sm hover:bg-slate-50 ${f.id === familiaId ? 'bg-primario/5 font-medium' : ''}`} onClick={() => setFamiliaId(f.id)}>
                <span>{f.nombre}</span>
                <Insignia tono={f.es_global ? 'acento' : 'neutro'}>{f.es_global ? 'Global' : 'Propia'}</Insignia>
              </button>
            </li>
          ))}
        </ul>
        {puedeCrear && (
          <form className="mt-3 flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); void crear('/catalogos/familias-equipo', { nombre: nuevaFamilia, global }, async () => { setNuevaFamilia(''); await familias.recargar() }) }}>
            <div className="flex-1"><Campo etiqueta="Nueva familia" name="nueva_familia" required value={nuevaFamilia} onChange={(e) => setNuevaFamilia(e.target.value)} /></div>
            {ambito.rol === 'superadmin' && (
              <label className="flex items-center gap-1 pb-2 text-xs"><input type="checkbox" checked={global} onChange={(e) => setGlobal(e.target.checked)} /> Global</label>
            )}
            <Boton type="submit" variante="secundario">Agregar</Boton>
          </form>
        )}
      </Tarjeta>
      <Tarjeta titulo={familia ? `Tipos de ${familia.nombre}` : 'Tipos de equipo'}>
        {!familia && <p className="text-sm text-slate-500">Elige una familia para ver sus tipos.</p>}
        {familia && (
          <>
            {tipos.error && <Aviso>{tipos.error}</Aviso>}
            <ul className="divide-y divide-slate-100 text-sm">
              {(tipos.datos ?? []).map((t) => (
                <li key={t.id} className="flex items-center justify-between px-2 py-2">
                  <span>{t.nombre}</span>
                  <Insignia tono={t.es_global ? 'acento' : 'neutro'}>{t.es_global ? 'Global' : 'Propio'}</Insignia>
                </li>
              ))}
              {tipos.datos?.length === 0 && <li className="px-2 py-2 text-slate-500">Sin tipos en esta familia</li>}
            </ul>
            {puedeCrear && (
              <form className="mt-3 flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); void crear('/catalogos/tipos-equipo', { familia_id: familia.id, nombre: nuevoTipo, global: global && familia.es_global }, async () => { setNuevoTipo(''); await tipos.recargar() }) }}>
                <div className="flex-1"><Campo etiqueta="Nuevo tipo de equipo" name="nuevo_tipo" required value={nuevoTipo} onChange={(e) => setNuevoTipo(e.target.value)} /></div>
                <Boton type="submit" variante="secundario">Agregar</Boton>
              </form>
            )}
          </>
        )}
      </Tarjeta>
    </div>
  )
}
