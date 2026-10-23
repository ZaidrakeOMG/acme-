import { useState } from 'react'
import { Aviso, Selector, Tarjeta } from '../../../components/ui'
import { useRecurso } from '../../../hooks/useRecurso'
import { api, mensajeDeError } from '../../../services/api'
import type { FamiliaEquipo, Matriz as MatrizDatos, Tenant } from '../../../types/api'
import { useAmbito } from '../Catalogos'

/** Cuadrícula tipo de falla × tipo de equipo por familia; cada celda elige el nivel con su color (§6.8.6). */
export function Matriz() {
  const ambito = useAmbito()
  const esTenant = ambito.rol === 'admin_empresa' || ambito.rol === 'admin_un'
  const tenants = useRecurso<Tenant[]>(esTenant ? null : '/tenants')
  const [tenantElegido, setTenantElegido] = useState('')
  const tenantId = esTenant ? undefined : ambito.params.tenant_id ?? tenantElegido
  const listo = esTenant || !!tenantId
  const { datos, error, recargar } = useRecurso<MatrizDatos>(listo ? '/catalogos/matriz-severidad' : null, { tenant_id: tenantId })
  const familias = useRecurso<FamiliaEquipo[]>('/catalogos/familias-equipo', { tenant_id: tenantId })
  const [aviso, setAviso] = useState<string | null>(null)
  const puedeEditar = ambito.puedeEditarTenant

  async function cambiar(tipo_falla_id: string, tipo_equipo_id: string, nivel: string) {
    setAviso(null)
    try {
      await api('/catalogos/matriz-severidad/celda', { metodo: 'PUT', params: { tenant_id: tenantId }, cuerpo: { tipo_falla_id, tipo_equipo_id, nivel_severidad_id: nivel || null } })
      await recargar()
    } catch (e) {
      setAviso(mensajeDeError(e))
    }
  }

  const nivelDe = (f: string, t: string) => datos?.celdas.find((c) => c.tipo_falla_id === f && c.tipo_equipo_id === t)?.nivel_severidad_id ?? ''
  const colorDe = (id: string) => datos?.niveles.find((n) => n.id === id)?.color_hex

  return (
    <Tarjeta titulo="Matriz de severidad">
      <p className="mb-3 text-sm text-slate-600">Filas: tipos de falla del prestador. Columnas: tipos de equipo de la misma familia. El operador nunca elige la severidad; la define esta matriz.</p>
      {!esTenant && !ambito.params.tenant_id && (
        <div className="mb-3 max-w-sm">
          <Selector etiqueta="Cliente" value={tenantElegido} onChange={(e) => setTenantElegido(e.target.value)}
                    opciones={[{ valor: '', texto: 'Selecciona…' }, ...(tenants.datos ?? []).map((t) => ({ valor: t.id, texto: t.razon_social }))]} />
        </div>
      )}
      {(error || aviso) && <Aviso>{error ?? aviso}</Aviso>}
      {datos && datos.faltantes_en_uso > 0 && (
        <div className="mb-3"><Aviso tipo="info">{datos.faltantes_en_uso} combinación(es) en uso sin severidad: esos folios irían a revisión manual.</Aviso></div>
      )}
      {datos && (familias.datos ?? []).map((fam) => {
        const fallas = datos.tipos_falla.filter((f) => f.familia_equipo_id === fam.id)
        const tipos = datos.tipos_equipo.filter((t) => t.familia_id === fam.id)
        if (fallas.length === 0 || tipos.length === 0) return null
        return (
          <div key={fam.id} className="mb-6 overflow-x-auto">
            <h3 className="mb-2 font-semibold text-slate-800">{fam.nombre}</h3>
            <table className="min-w-full text-sm">
              <thead>
                <tr>
                  <th className="px-2 py-1 text-left text-xs font-medium uppercase text-slate-500">Tipo de falla</th>
                  {tipos.map((t) => <th key={t.id} className="px-2 py-1 text-left text-xs font-medium text-slate-600">{t.nombre}{t.en_uso && <span title="En uso" className="ml-1 text-acento">●</span>}</th>)}
                </tr>
              </thead>
              <tbody>
                {fallas.map((f) => (
                  <tr key={f.id} className="border-t border-slate-100">
                    <td className="px-2 py-1 font-medium">{f.descripcion}</td>
                    {tipos.map((t) => {
                      const valor = nivelDe(f.id, t.id)
                      return (
                        <td key={t.id} className="px-2 py-1">
                          <select aria-label={`${f.descripcion} × ${t.nombre}`} value={valor} disabled={!puedeEditar}
                                  onChange={(e) => void cambiar(f.id, t.id, e.target.value)}
                                  className="rounded border border-slate-300 px-2 py-1 text-xs font-medium"
                                  style={{ background: valor ? `${colorDe(valor)}22` : undefined, borderColor: colorDe(valor) ?? undefined }}>
                            <option value="">— sin configurar —</option>
                            {datos.niveles.filter((n) => n.prestador_id === f.prestador_id).map((n) => <option key={n.id} value={n.id}>{n.nombre}</option>)}
                          </select>
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      })}
      {datos && datos.tipos_falla.length === 0 && <p className="text-sm text-slate-500">Este cliente no tiene prestadores con tipos de falla definidos.</p>}
    </Tarjeta>
  )
}
