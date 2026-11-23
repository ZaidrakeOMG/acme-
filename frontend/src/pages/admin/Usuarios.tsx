import { zodResolver } from '@hookform/resolvers/zod'
import { useState, type FormEvent } from 'react'
import { useForm } from 'react-hook-form'
import { z } from 'zod'
import { Aviso, Boton, Campo, Encabezado, Insignia, Modal, Selector, Tabla, Tarjeta } from '../../components/ui'
import { modulosDe, NOMBRE_ROL } from '../../config/modulos'
import { useAuth } from '../../contexts/AuthContext'
import { useRecurso } from '../../hooks/useRecurso'
import { api, mensajeDeError } from '../../services/api'
import type { Prestador, Rol, Tenant, Usuario } from '../../types/api'

const ROLES_TENANT: Rol[] = ['admin_empresa', 'admin_un', 'supervisor_operadores', 'operador']
const ROLES_PRESTADOR: Rol[] = ['admin_prestador', 'direccion_prestador', 'mesa_control', 'despachador', 'supervisor_prestador', 'tecnico']

export function rolesAsignables(rol: Rol): Rol[] {
  if (rol === 'superadmin') return ['superadmin', ...ROLES_PRESTADOR, ...ROLES_TENANT]
  if (rol === 'admin_empresa') return ROLES_TENANT
  if (rol === 'admin_prestador') return ROLES_PRESTADOR
  return []
}

const esquema = z.object({
  email: z.string().trim().email('Correo inválido'),
  nombre: z.string().trim().min(2, 'Mínimo 2 caracteres'),
  telefono: z.string().trim().max(30).optional(),
  rol: z.string().min(1),
  contrasena: z
    .string()
    .min(10, 'Mínimo 10 caracteres')
    .regex(/[a-z]/, 'Incluye una minúscula')
    .regex(/[A-Z]/, 'Incluye una mayúscula')
    .regex(/\d/, 'Incluye un número')
    .regex(/[^A-Za-z0-9]/, 'Incluye un símbolo'),
  tenant_id: z.string().optional(),
  prestador_id: z.string().optional(),
})
type Formulario = z.infer<typeof esquema>

export function Usuarios() {
  const { usuario } = useAuth()
  const [q, setQ] = useState('')
  const { datos, error, recargar } = useRecurso<Usuario[]>('/usuarios', { q: q || undefined })
  const [abierto, setAbierto] = useState(false)
  const [editando, setEditando] = useState<Usuario | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)
  if (!usuario || !['superadmin', 'admin_prestador', 'admin_empresa'].includes(usuario.rol)) return null

  async function cambiarEstado(u: Usuario) {
    setAviso(null)
    try {
      await api(`/usuarios/${u.id}`, { metodo: 'PATCH', cuerpo: { estado: u.estado === 'activo' ? 'inactivo' : 'activo' } })
      await recargar()
    } catch (e) {
      setAviso(mensajeDeError(e))
    }
  }

  async function eliminarCuenta(u: Usuario) {
    if (!window.confirm(`¿Eliminar el acceso de ${u.nombre}? Se cerrarán sus sesiones, pero su historial se conserva.`)) return
    setAviso(null)
    try {
      await api(`/usuarios/${u.id}`, { metodo: 'DELETE' })
      await recargar()
      setAviso('Cuenta dada de baja. Puedes reactivarla desde esta pantalla.')
    } catch (e) { setAviso(mensajeDeError(e)) }
  }

  return (
    <div>
      <Encabezado titulo="Usuarios" descripcion="Administra usuarios, roles y permisos individuales por módulo." acciones={<Boton onClick={() => setAbierto(true)}>Nuevo usuario</Boton>} />
      <Tarjeta acciones={<input aria-label="Buscar usuarios" placeholder="Buscar por nombre o correo" value={q} onChange={(e) => setQ(e.target.value)} className="w-64 rounded-lg border border-slate-300 px-3 py-1.5 text-sm" />}>
        {(error || aviso) && <div className="mb-3"><Aviso>{error ?? aviso}</Aviso></div>}
        <Tabla
          filas={datos ?? []}
          columnas={[
            { titulo: 'Nombre', celda: (u) => <><p className="font-medium">{u.nombre}</p><p className="text-xs text-slate-500">{u.email}</p></> },
            { titulo: 'Rol', celda: (u) => NOMBRE_ROL[u.rol] },
            { titulo: 'Módulos', celda: (u) => u.rol === 'superadmin' ? 'Todos' : `${modulosDe(u.rol, u.modulos_habilitados).length} de ${modulosDe(u.rol).length}` },
            { titulo: 'MFA', celda: (u) => (u.mfa_habilitado ? <Insignia tono="ok">Activo</Insignia> : <Insignia>No</Insignia>) },
            { titulo: 'Estado', celda: (u) => <Insignia tono={u.estado === 'activo' ? 'ok' : 'alerta'}>{u.estado}</Insignia> },
            {
              titulo: 'Acciones',
              celda: (u) => (
                <div className="flex flex-wrap gap-1">
                  <Boton variante="secundario" onClick={() => setEditando(u)}>Editar y permisos</Boton>
                  {u.id !== usuario.id && (
                    <>
                      <Boton variante="fantasma" onClick={() => void cambiarEstado(u)}>
                        {u.estado === 'activo' ? 'Desactivar' : 'Activar'}
                      </Boton>
                      {u.estado === 'activo' && <Boton variante="peligro" onClick={() => void eliminarCuenta(u)}>Eliminar acceso</Boton>}
                    </>
                  )}
                </div>
              ),
            },
          ]}
        />
      </Tarjeta>
      <Modal titulo="Nuevo usuario" abierto={abierto} alCerrar={() => setAbierto(false)}>
        <FormularioUsuario
          rolActor={usuario.rol}
          alGuardar={async () => {
            setAbierto(false)
            await recargar()
          }}
        />
      </Modal>
      <Modal titulo={editando ? `Editar: ${editando.nombre}` : 'Editar usuario'} abierto={!!editando} alCerrar={() => setEditando(null)}>
        {editando && (
          <FormularioEditar key={editando.id} usuario={editando} rolActor={usuario.rol}
            esPropio={editando.id === usuario.id}
            alGuardar={async () => { setEditando(null); await recargar() }} />
        )}
      </Modal>
    </div>
  )
}

function FormularioUsuario({ rolActor, alGuardar }: { rolActor: Rol; alGuardar: () => Promise<void> }) {
  const roles = rolesAsignables(rolActor)
  const esSuper = rolActor === 'superadmin'
  const tenants = useRecurso<Tenant[]>(esSuper ? '/tenants' : null)
  const prestadores = useRecurso<Prestador[]>(esSuper ? '/prestadores' : null)
  const [error, setError] = useState<string | null>(null)
  const [modulos, setModulos] = useState<string[] | null>(null)
  const { register, handleSubmit, watch, formState } = useForm<Formulario>({
    resolver: zodResolver(esquema),
    defaultValues: { rol: roles[roles.length - 1] },
  })
  const rol = watch('rol') as Rol

  const enviar = handleSubmit(async (d) => {
    setError(null)
    try {
      await api('/usuarios', {
        metodo: 'POST',
        cuerpo: {
          ...d,
          telefono: d.telefono || null,
          modulos_habilitados: rol === 'superadmin' ? null : modulos,
          tenant_id: esSuper && ROLES_TENANT.includes(rol) ? d.tenant_id : null,
          prestador_id: esSuper && ROLES_PRESTADOR.includes(rol) ? d.prestador_id : null,
        },
      })
      await alGuardar()
    } catch (e) {
      setError(mensajeDeError(e))
    }
  })

  return (
    <form onSubmit={enviar} className="space-y-3" noValidate>
      {error && <Aviso>{error}</Aviso>}
      <Campo etiqueta="Nombre" error={formState.errors.nombre?.message} {...register('nombre')} />
      <Campo etiqueta="Correo" type="email" error={formState.errors.email?.message} {...register('email')} />
      <Campo etiqueta="Teléfono" {...register('telefono')} />
      <Selector etiqueta="Rol" opciones={roles.map((r) => ({ valor: r, texto: NOMBRE_ROL[r] }))} {...register('rol', { onChange: () => setModulos(null) })} />
      {esSuper && ROLES_TENANT.includes(rol) && (
        <Selector etiqueta="Cliente" opciones={[{ valor: '', texto: 'Selecciona…' }, ...(tenants.datos ?? []).map((t) => ({ valor: t.id, texto: t.razon_social }))]} {...register('tenant_id')} />
      )}
      {esSuper && ROLES_PRESTADOR.includes(rol) && (
        <Selector etiqueta="Prestador" opciones={[{ valor: '', texto: 'Selecciona…' }, ...(prestadores.datos ?? []).map((p) => ({ valor: p.id, texto: p.razon_social }))]} {...register('prestador_id')} />
      )}
      <PanelModulos rol={rol} seleccion={modulos} alCambiar={setModulos} />
      <Campo etiqueta="Contraseña inicial" type="password" autoComplete="new-password" error={formState.errors.contrasena?.message} {...register('contrasena')} />
      <Boton type="submit" className="w-full" disabled={formState.isSubmitting}>Crear usuario</Boton>
    </form>
  )
}


/** Selección visual de módulos: los módulos fuera del rol jamás se pueden autorizar aquí. */
function PanelModulos({ rol, seleccion, alCambiar }: {
  rol: Rol; seleccion: string[] | null; alCambiar: (valor: string[]) => void
}) {
  if (rol === 'superadmin') return <Aviso tipo="info">Superadmin tiene acceso completo a todos los módulos.</Aviso>
  const disponibles = modulosDe(rol)
  const activos = seleccion ?? disponibles.map(m => m.id)
  const fijo = ['admin_empresa', 'admin_prestador'].includes(rol) ? 'usuarios' : null
  return (
    <fieldset className="rounded-xl border border-slate-200 p-3">
      <legend className="px-2 text-sm font-bold text-slate-800">Acceso a módulos</legend>
      <p className="mb-3 text-xs text-slate-600">Selecciona qué módulos podrá usar. Los permisos también se validan en el servidor.</p>
      <div className="mb-3 flex flex-wrap gap-3 text-xs">
        <button type="button" className="font-semibold text-primario underline" onClick={() => alCambiar(disponibles.map(m => m.id))}>Seleccionar todos</button>
        <button type="button" className="font-semibold text-primario underline" onClick={() => alCambiar(fijo ? [fijo] : [])}>Quitar selección</button>
      </div>
      <div className="grid max-h-64 grid-cols-1 gap-2 overflow-y-auto sm:grid-cols-2">
        {disponibles.map(m => (
          <label key={m.id} className="flex items-start gap-2 rounded-lg border border-slate-200 p-2.5 text-sm hover:bg-slate-50">
            <input type="checkbox" className="mt-0.5 accent-primario"
              checked={m.id === fijo || activos.includes(m.id)} disabled={m.id === fijo}
              onChange={e => alCambiar(e.target.checked ? [...new Set([...activos, m.id])] : activos.filter(id => id !== m.id))} />
            <span className="min-w-0"><strong className="block font-semibold text-slate-800">{m.nombre}</strong><small className="text-slate-500">{m.grupo}</small></span>
          </label>
        ))}
      </div>
    </fieldset>
  )
}

function FormularioEditar({ usuario, rolActor, esPropio, alGuardar }: {
  usuario: Usuario; rolActor: Rol; esPropio: boolean; alGuardar: () => Promise<void>
}) {
  const roles = rolesAsignables(rolActor).filter(r => r === usuario.rol ||
    (usuario.dominio === 'tenant' && ROLES_TENANT.includes(r)) ||
    (usuario.dominio === 'prestador' && ROLES_PRESTADOR.includes(r)))
  const [nombre, setNombre] = useState(usuario.nombre)
  const [telefono, setTelefono] = useState(usuario.telefono ?? '')
  const [rol, setRol] = useState<Rol>(usuario.rol)
  const [estado, setEstado] = useState(usuario.estado)
  const [modulos, setModulos] = useState<string[] | null>(usuario.modulos_habilitados)
  const [error, setError] = useState<string | null>(null)
  const [guardando, setGuardando] = useState(false)

  async function guardar(evento: FormEvent<HTMLFormElement>) {
    evento.preventDefault()
    if (nombre.trim().length < 2) { setError('El nombre requiere al menos 2 caracteres'); return }
    setError(null)
    setGuardando(true)
    try {
      await api(`/usuarios/${usuario.id}`, { metodo: 'PATCH', cuerpo: {
        nombre: nombre.trim(), telefono: telefono.trim(), rol: esPropio ? usuario.rol : rol,
        estado: esPropio ? usuario.estado : estado,
        ...(!esPropio && rol !== 'superadmin' ? { modulos_habilitados: modulos } : {}),
      } })
      await alGuardar()
    } catch (e) { setError(mensajeDeError(e)) }
    finally { setGuardando(false) }
  }

  return (
    <form onSubmit={guardar} className="space-y-3">
      {error && <Aviso>{error}</Aviso>}
      <p className="break-all text-xs text-slate-500">{usuario.email}</p>
      <Campo etiqueta="Nombre" value={nombre} onChange={e => setNombre(e.target.value)} maxLength={160} required />
      <Campo etiqueta="Teléfono" value={telefono} onChange={e => setTelefono(e.target.value)} maxLength={30} />
      {!esPropio && <Selector etiqueta="Rol" value={rol} opciones={roles.map(r => ({ valor: r, texto: NOMBRE_ROL[r] }))}
        onChange={e => { setRol(e.target.value as Rol); setModulos(null) }} />}
      {!esPropio && <Selector etiqueta="Estado" value={estado} opciones={[
        { valor: 'activo', texto: 'Activo' }, { valor: 'inactivo', texto: 'Inactivo' }, { valor: 'suspendido', texto: 'Suspendido' },
      ]} onChange={e => setEstado(e.target.value as Usuario['estado'])} />}
      {!esPropio && <PanelModulos rol={rol} seleccion={modulos} alCambiar={setModulos} />}
      {esPropio && <Aviso tipo="info">Por seguridad, no puedes cambiar tu propio rol ni desactivar tu cuenta.</Aviso>}
      <Boton type="submit" className="w-full" disabled={guardando}>{guardando ? 'Guardando…' : 'Guardar cambios'}</Boton>
    </form>
  )
}
