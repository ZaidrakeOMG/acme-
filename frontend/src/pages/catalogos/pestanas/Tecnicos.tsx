import { useEffect, useState } from 'react'
import { Buscador } from '../../../components/Buscador'
import { Aviso, Boton, Campo, Insignia, Modal, Selector, Tabla, Tarjeta } from '../../../components/ui'
import { useRecurso } from '../../../hooks/useRecurso'
import { api, mensajeDeError } from '../../../services/api'
import type { GrupoTecnicos, Habilidad, PermisoEfectivoTecnico, Tecnico, Tenant } from '../../../types/api'
import { useAmbito } from '../Catalogos'

export function Tecnicos() {
  const ambito = useAmbito()
  const [q, setQ] = useState('')
  const { datos, error, recargar } = useRecurso<Tecnico[]>('/catalogos/tecnicos', { ...ambito.params, q: q || undefined })
  const habilidades = useRecurso<Habilidad[]>('/catalogos/habilidades', ambito.params)
  const grupos = useRecurso<GrupoTecnicos[]>('/catalogos/grupos-tecnicos', ambito.params)
  const [ficha, setFicha] = useState<Tecnico | null>(null)
  const [nuevo, setNuevo] = useState(false)
  const [nuevaHabilidad, setNuevaHabilidad] = useState(false)
  const nombreGrupo = (id: string | null) => grupos.datos?.find((g) => g.id === id)?.nombre ?? '—'

  return (
    <div className="space-y-4">
      <Tarjeta
        titulo="Técnicos"
        acciones={
          <div className="flex flex-wrap items-center gap-2">
            <Buscador etiqueta="Buscar técnico" placeholder="Nombre, correo o número" alBuscar={setQ} />
            {ambito.puedeEditarPrestador && (
              <>
                <Boton variante="secundario" onClick={() => setNuevaHabilidad(true)}>Nueva habilidad</Boton>
                <Boton onClick={() => setNuevo(true)}>Nuevo técnico</Boton>
              </>
            )}
          </div>
        }
      >
        {error && <Aviso>{error}</Aviso>}
        <Tabla
          filas={datos ?? []}
          columnas={[
            { titulo: 'Técnico', celda: (t) => <><p className="font-medium">{t.nombre}</p><p className="text-xs text-slate-500">{t.email} · {t.numero_empleado ?? 'sin número'}</p></> },
            { titulo: 'Habilidades', celda: (t) => <span className="flex flex-wrap gap-1">{t.habilidades.map((h) => <Insignia key={h.habilidad_id} tono={h.vigente ? 'ok' : 'alerta'}>{h.nombre}</Insignia>)}</span> },
            { titulo: 'Grupo', celda: (t) => nombreGrupo(t.grupo_id) },
            { titulo: 'Estado', celda: (t) => <Insignia tono={t.estado === 'activo' ? 'ok' : 'alerta'}>{t.estado}</Insignia> },
            { titulo: '', celda: (t) => <Boton variante="fantasma" onClick={() => setFicha(t)}>Ficha</Boton> },
          ]}
        />
      </Tarjeta>

      <Modal titulo="Nuevo técnico" abierto={nuevo} alCerrar={() => setNuevo(false)}>
        <FormularioTecnico alGuardar={async () => { setNuevo(false); await recargar() }} />
      </Modal>
      <Modal titulo="Nueva habilidad" abierto={nuevaHabilidad} alCerrar={() => setNuevaHabilidad(false)}>
        <FormularioHabilidad alGuardar={async () => { setNuevaHabilidad(false); await habilidades.recargar() }} />
      </Modal>
      <Modal titulo={ficha ? `Ficha · ${ficha.nombre}` : ''} abierto={ficha !== null} alCerrar={() => setFicha(null)}>
        {ficha && (
          <FichaTecnico
            tecnico={ficha}
            habilidades={habilidades.datos ?? []}
            grupos={grupos.datos ?? []}
            alCambiar={async (t) => { setFicha(t); await recargar() }}
          />
        )}
      </Modal>
    </div>
  )
}

function FormularioTecnico({ alGuardar }: { alGuardar: () => Promise<void> }) {
  const ambito = useAmbito()
  const [f, setF] = useState({ email: '', nombre: '', contrasena: '', numero_empleado: '', telefono: '' })
  const [error, setError] = useState<string | null>(null)
  const campo = (k: keyof typeof f) => ({ value: f[k], onChange: (e: React.ChangeEvent<HTMLInputElement>) => setF({ ...f, [k]: e.target.value }) })
  return (
    <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); void (async () => {
      try {
        await api('/catalogos/tecnicos', { metodo: 'POST', params: ambito.params, cuerpo: { ...f, numero_empleado: f.numero_empleado || null, telefono: f.telefono || null } })
        await alGuardar()
      } catch (err) { setError(mensajeDeError(err)) }
    })() }}>
      {error && <Aviso>{error}</Aviso>}
      <Campo etiqueta="Nombre" name="nombre" required {...campo('nombre')} />
      <Campo etiqueta="Correo" name="email" type="email" required {...campo('email')} />
      <Campo etiqueta="Contraseña inicial" name="contrasena" type="password" autoComplete="new-password" required {...campo('contrasena')} />
      <div className="grid grid-cols-2 gap-3">
        <Campo etiqueta="Número de empleado" name="numero_empleado" {...campo('numero_empleado')} />
        <Campo etiqueta="Teléfono" name="telefono" {...campo('telefono')} />
      </div>
      <Boton type="submit" className="w-full">Crear técnico</Boton>
    </form>
  )
}

function FormularioHabilidad({ alGuardar }: { alGuardar: () => Promise<void> }) {
  const ambito = useAmbito()
  const [clave, setClave] = useState('')
  const [nombre, setNombre] = useState('')
  const [error, setError] = useState<string | null>(null)
  return (
    <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); void (async () => {
      try {
        await api('/catalogos/habilidades', { metodo: 'POST', params: ambito.params, cuerpo: { clave, nombre } })
        await alGuardar()
      } catch (err) { setError(mensajeDeError(err)) }
    })() }}>
      {error && <Aviso>{error}</Aviso>}
      <Campo etiqueta="Clave (minúsculas, sin espacios)" name="clave" required value={clave} onChange={(e) => setClave(e.target.value)} />
      <Campo etiqueta="Nombre" name="nombre_hab" required value={nombre} onChange={(e) => setNombre(e.target.value)} />
      <Boton type="submit" className="w-full">Crear habilidad</Boton>
    </form>
  )
}

function FichaTecnico({ tecnico, habilidades, grupos, alCambiar }: {
  tecnico: Tecnico; habilidades: Habilidad[]; grupos: GrupoTecnicos[]; alCambiar: (t: Tecnico) => Promise<void>
}) {
  const ambito = useAmbito()
  const editar = ambito.puedeEditarPrestador
  const [error, setError] = useState<string | null>(null)
  const [seleccion, setSeleccion] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(tecnico.habilidades.map((h) => [h.habilidad_id, h.certificada])))
  const [permisos, setPermisos] = useState<PermisoEfectivoTecnico[]>([])
  const tenants = useRecurso<Tenant[]>(editar ? '/tenants' : null)
  const base = `/catalogos/tecnicos/${tecnico.id}`

  useEffect(() => {
    void api<PermisoEfectivoTecnico[]>(`${base}/permisos-efectivos`, { params: ambito.params }).then(setPermisos).catch(() => setPermisos([]))
  }, [base, ambito.params, tecnico.grupo_id])

  async function ejecutar(fn: () => Promise<Tecnico | void>) {
    setError(null)
    try {
      const t = await fn()
      if (t) await alCambiar(t)
    } catch (e) {
      setError(mensajeDeError(e))
    }
  }

  return (
    <div className="space-y-5 text-sm">
      {error && <Aviso>{error}</Aviso>}
      <section>
        <h3 className="mb-2 font-semibold text-slate-800">Habilidades</h3>
        <ul className="grid grid-cols-2 gap-1">
          {habilidades.map((h) => (
            <li key={h.id}>
              <label className="flex items-center gap-2">
                <input type="checkbox" disabled={!editar} checked={h.id in seleccion}
                       onChange={(e) => { const s = { ...seleccion }; if (e.target.checked) s[h.id] = true; else delete s[h.id]; setSeleccion(s) }} />
                {h.nombre}
              </label>
            </li>
          ))}
        </ul>
        {editar && (
          <Boton variante="secundario" className="mt-2" onClick={() => void ejecutar(() => api<Tecnico>(`${base}/habilidades`, {
            metodo: 'PUT', params: ambito.params,
            cuerpo: { habilidades: Object.entries(seleccion).map(([habilidad_id, certificada]) => ({ habilidad_id, certificada })) },
          }))}>Guardar habilidades</Boton>
        )}
      </section>

      <section>
        <h3 className="mb-2 font-semibold text-slate-800">Grupo de permisos</h3>
        <Selector etiqueta="Grupo" disabled={!editar} value={tecnico.grupo_id ?? ''}
                  opciones={[{ valor: '', texto: 'Sin grupo' }, ...grupos.map((g) => ({ valor: g.id, texto: g.nombre }))]}
                  onChange={(e) => void ejecutar(() => api<Tecnico>(`${base}/grupo`, { metodo: 'PUT', params: ambito.params, cuerpo: { grupo_id: e.target.value || null } }))} />
      </section>

      <section>
        <h3 className="mb-2 font-semibold text-slate-800">Permisos efectivos</h3>
        <table className="w-full text-xs">
          <tbody>
            {permisos.map((p) => (
              <tr key={p.clave} className="border-t border-slate-100">
                <td className="py-1 pr-2">{p.descripcion}</td>
                <td className="py-1 pr-2 text-slate-500">{p.origen}</td>
                <td className="py-1">
                  <input type="checkbox" aria-label={p.clave} checked={p.habilitado} disabled={!editar}
                         onChange={(e) => void ejecutar(async () => {
                           setPermisos(await api<PermisoEfectivoTecnico[]>(`${base}/permisos`, { metodo: 'PUT', params: ambito.params,
                             cuerpo: { overrides: [{ permiso_clave: p.clave, habilitado: e.target.checked, razon: 'Ajuste individual' }] } }))
                         })} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      {editar && tenants.datos && (
        <section>
          <h3 className="mb-2 font-semibold text-slate-800">Clientes adicionales que puede atender (§6.10.8)</h3>
          {tenants.datos.map((t) => (
            <label key={t.id} className="flex items-center gap-2">
              <input type="checkbox" checked={tecnico.tenants_habilitados.includes(t.id)}
                     onChange={(e) => void ejecutar(() => api<Tecnico>(`${base}/tenants`, { metodo: 'PUT', params: ambito.params,
                       cuerpo: { tenant_ids: e.target.checked ? [...tecnico.tenants_habilitados, t.id] : tecnico.tenants_habilitados.filter((x) => x !== t.id) } }))} />
              {t.razon_social}
            </label>
          ))}
        </section>
      )}
    </div>
  )
}
