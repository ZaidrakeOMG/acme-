import { createContext, useContext, useMemo, useState } from 'react'
import { Encabezado, Selector } from '../../components/ui'
import { useAuth } from '../../contexts/AuthContext'
import { useRecurso } from '../../hooks/useRecurso'
import type { Prestador, Rol, Tenant } from '../../types/api'
import { Equipos } from './pestanas/Equipos'
import { FamiliasTipos } from './pestanas/FamiliasTipos'
import { Importar } from './pestanas/Importar'
import { Matriz } from './pestanas/Matriz'
import { Severidades } from './pestanas/Severidades'
import { Tecnicos } from './pestanas/Tecnicos'
import { TiposFalla } from './pestanas/TiposFalla'

/** Ámbito de los catálogos: el tenant/prestador del usuario, o los que elija el superadmin. */
export interface Ambito {
  tenant_id?: string
  prestador_id?: string
  rol: Rol
  /** parámetros a enviar en cada llamada (solo superadmin los necesita) */
  params: Record<string, string | undefined>
  puedeEditarPrestador: boolean
  puedeEditarTenant: boolean
}

const AmbitoContext = createContext<Ambito | null>(null)

export function useAmbito(): Ambito {
  const a = useContext(AmbitoContext)
  if (!a) throw new Error('useAmbito fuera de Catalogos')
  return a
}

interface Pestana {
  id: string
  nombre: string
  roles: Rol[]
  componente: () => React.JSX.Element
}

const PESTANAS: Pestana[] = [
  { id: 'tecnicos', nombre: 'Técnicos', roles: ['superadmin', 'admin_prestador', 'mesa_control', 'despachador'], componente: Tecnicos },
  { id: 'severidades', nombre: 'Severidades', roles: ['superadmin', 'admin_prestador', 'mesa_control', 'despachador', 'admin_empresa', 'admin_un'], componente: Severidades },
  { id: 'familias', nombre: 'Familias y tipos', roles: ['superadmin', 'admin_prestador', 'mesa_control', 'despachador', 'admin_empresa', 'admin_un'], componente: FamiliasTipos },
  { id: 'equipos', nombre: 'Equipos', roles: ['superadmin', 'admin_prestador', 'mesa_control', 'despachador', 'admin_empresa', 'admin_un'], componente: Equipos },
  { id: 'fallas', nombre: 'Tipos de falla', roles: ['superadmin', 'admin_prestador', 'mesa_control', 'despachador', 'admin_empresa', 'admin_un'], componente: TiposFalla },
  { id: 'matriz', nombre: 'Matriz de severidad', roles: ['superadmin', 'admin_prestador', 'mesa_control', 'despachador', 'admin_empresa', 'admin_un'], componente: Matriz },
  { id: 'importar', nombre: 'Importar', roles: ['superadmin', 'admin_prestador', 'admin_empresa'], componente: Importar },
]

export function pestanasDe(rol: Rol): Pestana[] {
  return PESTANAS.filter((p) => p.roles.includes(rol))
}

export function Catalogos() {
  const { usuario } = useAuth()
  const esSuper = usuario?.rol === 'superadmin'
  const tenants = useRecurso<Tenant[]>(esSuper ? '/tenants' : null)
  const prestadores = useRecurso<Prestador[]>(esSuper ? '/prestadores' : null)
  const [tenantId, setTenantId] = useState('')
  const [prestadorId, setPrestadorId] = useState('')
  const pestanas = usuario ? pestanasDe(usuario.rol) : []
  const [activa, setActiva] = useState(pestanas[0]?.id ?? 'tecnicos')

  const ambito = useMemo<Ambito | null>(() => {
    if (!usuario) return null
    const rol = usuario.rol
    if (esSuper) {
      return {
        tenant_id: tenantId || undefined, prestador_id: prestadorId || undefined, rol,
        params: { tenant_id: tenantId || undefined, prestador_id: prestadorId || undefined },
        puedeEditarPrestador: true, puedeEditarTenant: true,
      }
    }
    return {
      tenant_id: usuario.tenant_id ?? undefined, prestador_id: usuario.prestador_id ?? undefined, rol, params: {},
      puedeEditarPrestador: rol === 'admin_prestador',
      puedeEditarTenant: rol === 'admin_empresa',
    }
  }, [usuario, esSuper, tenantId, prestadorId])

  if (!usuario || !ambito) return null
  const Activa = pestanas.find((p) => p.id === activa)?.componente ?? pestanas[0]!.componente

  return (
    <AmbitoContext.Provider value={ambito}>
      <Encabezado titulo="Catálogos maestros" descripcion="Técnicos, severidades, familias y tipos de equipo, equipos, tipos de falla, matriz de severidad e importador." />
      {esSuper && (
        <div className="mb-4 grid max-w-2xl gap-3 sm:grid-cols-2">
          <Selector etiqueta="Cliente (tenant)" value={tenantId} onChange={(e) => setTenantId(e.target.value)}
                    opciones={[{ valor: '', texto: 'Selecciona…' }, ...(tenants.datos ?? []).map((t) => ({ valor: t.id, texto: t.razon_social }))]} />
          <Selector etiqueta="Prestador" value={prestadorId} onChange={(e) => setPrestadorId(e.target.value)}
                    opciones={[{ valor: '', texto: 'Selecciona…' }, ...(prestadores.datos ?? []).map((p) => ({ valor: p.id, texto: p.razon_social }))]} />
        </div>
      )}
      <div role="tablist" aria-label="Catálogos" className="mb-5 flex flex-wrap gap-1 border-b border-slate-200">
        {pestanas.map((p) => (
          <button key={p.id} role="tab" aria-selected={p.id === activa} onClick={() => setActiva(p.id)}
                  className={`-mb-px border-b-2 px-3 py-2 text-sm ${p.id === activa ? 'border-primario font-medium text-primario' : 'border-transparent text-slate-600 hover:text-slate-900'}`}>
            {p.nombre}
          </button>
        ))}
      </div>
      <div role="tabpanel">
        {esSuper && activa === 'tecnicos' && !prestadorId ? (
          <div role="status" className="rounded-2xl border border-[#e9d5dc] bg-white px-5 py-6 text-sm text-slate-700">
            <p className="font-bold text-slate-900">Selecciona un prestador</p>
            <p className="mt-2 leading-6">Antes de consultar, crear técnicos o agregar habilidades, selecciona un prestador en el filtro superior. Así ACMA asignará los datos a la empresa correcta.</p>
          </div>
        ) : (
          <Activa />
        )}
      </div>
    </AmbitoContext.Provider>
  )
}
