import { zodResolver } from '@hookform/resolvers/zod'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { z } from 'zod'
import { Aviso, Boton, Campo, Encabezado, Insignia, Modal, Selector, Tabla, Tarjeta } from '../../components/ui'
import { useAuth } from '../../contexts/AuthContext'
import { useRecurso } from '../../hooks/useRecurso'
import { api, mensajeDeError } from '../../services/api'
import type { GrupoUN, Tenant, UnidadNegocio } from '../../types/api'

const coordenada = (min: number, max: number) =>
  z.union([z.literal(''), z.coerce.number().min(min, `Mínimo ${min}`).max(max, `Máximo ${max}`)]).optional()

const esquemaUnidad = z.object({
  nombre: z.string().trim().min(2, 'Mínimo 2 caracteres'),
  codigo: z.string().trim().min(1, 'Obligatorio').max(40),
  direccion: z.string().max(500).optional(),
  lat: coordenada(-90, 90),
  lng: coordenada(-180, 180),
  grupo_id: z.string().optional(),
  tenant_id: z.string().optional(),
})
type FormUnidad = z.input<typeof esquemaUnidad>

export function Unidades() {
  const { usuario } = useAuth()
  const puedeEditar = usuario?.rol === 'superadmin'
  const unidades = useRecurso<UnidadNegocio[]>('/unidades-negocio')
  const grupos = useRecurso<GrupoUN[]>(usuario && ['admin_un', 'operador', 'tecnico'].includes(usuario.rol) ? null : '/grupos-un')
  const clientes = useRecurso<Tenant[]>(usuario?.rol === 'superadmin' ? '/tenants' : null)
  const [editar, setEditar] = useState<UnidadNegocio | 'nueva' | null>(null)
  const [grupoEditar, setGrupoEditar] = useState<GrupoUN | 'nuevo' | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)
  async function cambiarEstado(path: string, item: UnidadNegocio | GrupoUN, recargar: () => Promise<void>) {
    if (!window.confirm(item.estado === 'activo' ? `¿Dar de baja a ${item.nombre}? Se conserva su historial.` : `¿Reactivar a ${item.nombre}?`)) return
    try { setAviso(null); await api(`${path}/${item.id}`, { metodo: 'PATCH', cuerpo: { estado: item.estado === 'activo' ? 'inactivo' : 'activo' } }); await recargar() }
    catch (e) { setAviso(mensajeDeError(e)) }
  }
  const nombreGrupo = (id: string | null) => grupos.datos?.find((g) => g.id === id)?.nombre ?? '—'

  return (
    <div className="space-y-6">
      <Encabezado
        titulo="Unidades de negocio"
        descripcion="Sucursales o plantas del cliente, con su ubicación y grupo."
        acciones={puedeEditar && <Boton onClick={() => setEditar('nueva')}>Nueva unidad</Boton>}
      />
      <Tarjeta titulo="Unidades">
        {(unidades.error || aviso) && <Aviso>{unidades.error ?? aviso}</Aviso>}
        <Tabla
          filas={unidades.datos ?? []}
          columnas={[
            { titulo: 'Código', celda: (u) => <span className="font-mono text-xs">{u.codigo}</span> },
            { titulo: 'Nombre', celda: (u) => <><p className="font-medium">{u.nombre}</p><p className="text-xs text-slate-500">{u.direccion}</p></> },
            { titulo: 'Grupo', celda: (u) => nombreGrupo(u.grupo_id) },
            { titulo: 'Ubicación', celda: (u) => (u.ubicacion ? `${u.ubicacion.lat.toFixed(4)}, ${u.ubicacion.lng.toFixed(4)}` : '—') },
            { titulo: 'Estado', celda: (u) => <Insignia tono={u.estado === 'activo' ? 'ok' : 'alerta'}>{u.estado}</Insignia> },
            ...(puedeEditar ? [{ titulo: '', celda: (u: UnidadNegocio) => <div className="flex flex-wrap gap-1"><Boton variante="fantasma" onClick={() => setEditar(u)}>Editar</Boton><Boton variante="peligro" onClick={() => void cambiarEstado('/unidades-negocio', u, unidades.recargar)}>{u.estado === 'activo' ? 'Dar de baja' : 'Reactivar'}</Boton></div> }] : []),
          ]}
        />
      </Tarjeta>

      {grupos.datos && (
        <Tarjeta titulo="Grupos de unidades" acciones={puedeEditar && <Boton variante="secundario" onClick={() => setGrupoEditar('nuevo')}>Nuevo grupo</Boton>}>
          {grupos.error && <Aviso>{grupos.error}</Aviso>}
          <Tabla
            filas={grupos.datos}
            vacio="Aún no hay grupos"
            columnas={[
              { titulo: 'Grupo', celda: (g) => <><p className="font-medium">{g.nombre}</p><p className="text-xs text-slate-500">{g.descripcion}</p></> },
              { titulo: 'Unidades', celda: (g) => g.unidad_ids.length },
              { titulo: 'Supervisores', celda: (g) => g.supervisor_ids.length },
              { titulo: 'Estado', celda: (g) => <Insignia>{g.estado}</Insignia> },
              ...(puedeEditar
                ? [{
                    titulo: 'Miembros',
                    celda: (g: GrupoUN) => <div className="flex flex-wrap gap-1"><MiembrosGrupo grupo={g} unidades={(unidades.datos ?? []).filter(u => u.tenant_id === g.tenant_id)} alGuardar={grupos.recargar} /><Boton variante="fantasma" onClick={() => setGrupoEditar(g)}>Editar</Boton><Boton variante="peligro" onClick={() => void cambiarEstado('/grupos-un', g, grupos.recargar)}>{g.estado === 'activo' ? 'Dar de baja' : 'Reactivar'}</Boton></div>,
                  }]
                : []),
            ]}
          />
        </Tarjeta>
      )}

      <Modal titulo={editar === 'nueva' ? 'Nueva unidad' : 'Editar unidad'} abierto={editar !== null} alCerrar={() => setEditar(null)}>
        {editar && (
          <FormularioUnidad
            unidad={editar === 'nueva' ? null : editar}
            grupos={grupos.datos ?? []}
            clientes={clientes.datos ?? []}
            esSuper={usuario?.rol === 'superadmin'}
            alGuardar={async () => {
              setEditar(null)
              await Promise.all([unidades.recargar(), grupos.recargar()])
            }}
          />
        )}
      </Modal>
      <Modal titulo={grupoEditar === 'nuevo' ? 'Nuevo grupo' : 'Editar grupo'} abierto={grupoEditar !== null} alCerrar={() => setGrupoEditar(null)}>
        {grupoEditar && <FormularioGrupo key={grupoEditar === 'nuevo' ? 'nuevo' : grupoEditar.id} grupo={grupoEditar === 'nuevo' ? null : grupoEditar} clientes={clientes.datos ?? []} esSuper={usuario?.rol === 'superadmin'} alGuardar={async () => { setGrupoEditar(null); await grupos.recargar() }} />}
      </Modal>
    </div>
  )
}

function FormularioUnidad({ unidad, grupos, clientes, esSuper, alGuardar }: { unidad: UnidadNegocio | null; grupos: GrupoUN[]; clientes: Tenant[]; esSuper: boolean; alGuardar: () => Promise<void> }) {
  const [error, setError] = useState<string | null>(null)
  const { register, handleSubmit, watch, formState } = useForm<FormUnidad>({
    resolver: zodResolver(esquemaUnidad),
    defaultValues: {
      nombre: unidad?.nombre ?? '',
      codigo: unidad?.codigo ?? '',
      direccion: unidad?.direccion ?? '',
      lat: unidad?.ubicacion?.lat ?? '',
      lng: unidad?.ubicacion?.lng ?? '',
      grupo_id: unidad?.grupo_id ?? '',
      tenant_id: unidad?.tenant_id ?? '',
    },
  })
  const tenantElegido = watch('tenant_id')
  const gruposDelCliente = esSuper ? grupos.filter((g) => g.tenant_id === (unidad?.tenant_id ?? tenantElegido)) : grupos
  const enviar = handleSubmit(async (valores) => {
    const d = esquemaUnidad.parse(valores)
    setError(null)
    if (!unidad && esSuper && !d.tenant_id) {
      setError('Selecciona el cliente al que pertenece la unidad')
      return
    }
    if (d.grupo_id && !gruposDelCliente.some((g) => g.id === d.grupo_id)) {
      setError('Selecciona un grupo del mismo cliente')
      return
    }
    const ubicacion = typeof d.lat === 'number' && typeof d.lng === 'number' ? { lat: d.lat, lng: d.lng } : null
    const cuerpo = { nombre: d.nombre, codigo: d.codigo, direccion: d.direccion ?? '', ubicacion, grupo_id: d.grupo_id || null,
      ...(!unidad && esSuper ? { tenant_id: d.tenant_id } : {}) }
    try {
      if (unidad) await api(`/unidades-negocio/${unidad.id}`, { metodo: 'PATCH', cuerpo })
      else await api('/unidades-negocio', { metodo: 'POST', cuerpo })
      await alGuardar()
    } catch (e) {
      setError(mensajeDeError(e))
    }
  })
  return (
    <form onSubmit={enviar} className="space-y-3" noValidate>
      {error && <Aviso>{error}</Aviso>}
      {!unidad && esSuper && <Selector etiqueta="Cliente" opciones={[{ valor: '', texto: 'Selecciona cliente…' }, ...clientes.map((c) => ({ valor: c.id, texto: c.razon_social }))]} {...register('tenant_id')} />}
      <div className="grid grid-cols-3 gap-3">
        <Campo etiqueta="Código" error={formState.errors.codigo?.message} {...register('codigo')} />
        <div className="col-span-2">
          <Campo etiqueta="Nombre" error={formState.errors.nombre?.message} {...register('nombre')} />
        </div>
      </div>
      <Campo etiqueta="Dirección" {...register('direccion')} />
      <div className="grid grid-cols-2 gap-3">
        <Campo etiqueta="Latitud" inputMode="decimal" error={formState.errors.lat?.message} {...register('lat')} />
        <Campo etiqueta="Longitud" inputMode="decimal" error={formState.errors.lng?.message} {...register('lng')} />
      </div>
      <Selector etiqueta="Grupo principal" opciones={[{ valor: '', texto: 'Sin grupo' }, ...gruposDelCliente.map((g) => ({ valor: g.id, texto: g.nombre }))]} {...register('grupo_id')} />
      <Boton type="submit" className="w-full" disabled={formState.isSubmitting}>Guardar</Boton>
    </form>
  )
}

function FormularioGrupo({ grupo, clientes, esSuper, alGuardar }: { grupo: GrupoUN | null; clientes: Tenant[]; esSuper: boolean; alGuardar: () => Promise<void> }) {
  const [error, setError] = useState<string | null>(null)
  const { register, handleSubmit, formState } = useForm<{ nombre: string; descripcion: string; tenant_id: string }>({
    resolver: zodResolver(z.object({ nombre: z.string().trim().min(2, 'Mínimo 2 caracteres'), descripcion: z.string().max(1000), tenant_id: z.string() })),
    defaultValues: { nombre: grupo?.nombre ?? '', descripcion: grupo?.descripcion ?? '', tenant_id: grupo?.tenant_id ?? '' },
  })
  const enviar = handleSubmit(async (d) => {
    setError(null)
    if (esSuper && !d.tenant_id) {
      setError('Selecciona el cliente del grupo')
      return
    }
    try {
      if (grupo) await api(`/grupos-un/${grupo.id}`, { metodo: 'PATCH', cuerpo: { nombre: d.nombre, descripcion: d.descripcion } })
      else await api('/grupos-un', { metodo: 'POST', cuerpo: { nombre: d.nombre, descripcion: d.descripcion, ...(esSuper ? { tenant_id: d.tenant_id } : {}) } })
      await alGuardar()
    } catch (e) {
      setError(mensajeDeError(e))
    }
  })
  return (
    <form onSubmit={enviar} className="space-y-3" noValidate>
      {error && <Aviso>{error}</Aviso>}
      {esSuper && !grupo && <Selector etiqueta="Cliente" opciones={[{ valor: '', texto: 'Selecciona cliente…' }, ...clientes.map((c) => ({ valor: c.id, texto: c.razon_social }))]} {...register('tenant_id')} />}
      <Campo etiqueta="Nombre" error={formState.errors.nombre?.message} {...register('nombre')} />
      <Campo etiqueta="Descripción" {...register('descripcion')} />
      <Boton type="submit" className="w-full" disabled={formState.isSubmitting}>{grupo ? 'Guardar cambios' : 'Crear grupo'}</Boton>
    </form>
  )
}

function MiembrosGrupo({ grupo, unidades, alGuardar }: { grupo: GrupoUN; unidades: UnidadNegocio[]; alGuardar: () => Promise<void> }) {
  const [abierto, setAbierto] = useState(false)
  const [seleccion, setSeleccion] = useState<Set<string>>(new Set(grupo.unidad_ids))
  const [error, setError] = useState<string | null>(null)
  async function guardar() {
    try {
      await api(`/grupos-un/${grupo.id}/unidades`, { metodo: 'PUT', cuerpo: { unidad_ids: [...seleccion] } })
      setAbierto(false)
      await alGuardar()
    } catch (e) {
      setError(mensajeDeError(e))
    }
  }
  return (
    <>
      <Boton variante="fantasma" onClick={() => setAbierto(true)}>Definir</Boton>
      <Modal titulo={`Unidades de ${grupo.nombre}`} abierto={abierto} alCerrar={() => setAbierto(false)}>
        {error && <Aviso>{error}</Aviso>}
        <ul className="mb-4 max-h-72 space-y-1 overflow-y-auto">
          {unidades.map((u) => (
            <li key={u.id}>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={seleccion.has(u.id)}
                  onChange={(e) => {
                    const s = new Set(seleccion)
                    if (e.target.checked) s.add(u.id)
                    else s.delete(u.id)
                    setSeleccion(s)
                  }}
                />
                {u.codigo} · {u.nombre}
              </label>
            </li>
          ))}
        </ul>
        <Boton className="w-full" onClick={() => void guardar()}>Guardar miembros</Boton>
      </Modal>
    </>
  )
}
