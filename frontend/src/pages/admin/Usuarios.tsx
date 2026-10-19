import { zodResolver } from '@hookform/resolvers/zod'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { z } from 'zod'
import { Aviso, Boton, Campo, Encabezado, Insignia, Modal, Selector, Tabla, Tarjeta } from '../../components/ui'
import { NOMBRE_ROL } from '../../config/modulos'
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
  const [aviso, setAviso] = useState<string | null>(null)
  if (!usuario) return null

  async function cambiarEstado(u: Usuario) {
    setAviso(null)
    try {
      await api(`/usuarios/${u.id}`, { metodo: 'PATCH', cuerpo: { estado: u.estado === 'activo' ? 'inactivo' : 'activo' } })
      await recargar()
    } catch (e) {
      setAviso(mensajeDeError(e))
    }
  }

  return (
    <div>
      <Encabezado titulo="Usuarios" descripcion="Usuarios que puedes administrar según tu rol." acciones={<Boton onClick={() => setAbierto(true)}>Nuevo usuario</Boton>} />
      <Tarjeta acciones={<input aria-label="Buscar usuarios" placeholder="Buscar por nombre o correo" value={q} onChange={(e) => setQ(e.target.value)} className="w-64 rounded-lg border border-slate-300 px-3 py-1.5 text-sm" />}>
        {(error || aviso) && <div className="mb-3"><Aviso>{error ?? aviso}</Aviso></div>}
        <Tabla
          filas={datos ?? []}
          columnas={[
            { titulo: 'Nombre', celda: (u) => <><p className="font-medium">{u.nombre}</p><p className="text-xs text-slate-500">{u.email}</p></> },
            { titulo: 'Rol', celda: (u) => NOMBRE_ROL[u.rol] },
            { titulo: 'MFA', celda: (u) => (u.mfa_habilitado ? <Insignia tono="ok">Activo</Insignia> : <Insignia>No</Insignia>) },
            { titulo: 'Estado', celda: (u) => <Insignia tono={u.estado === 'activo' ? 'ok' : 'alerta'}>{u.estado}</Insignia> },
            {
              titulo: 'Acciones',
              celda: (u) =>
                u.id === usuario.id ? null : (
                  <Boton variante="fantasma" onClick={() => void cambiarEstado(u)}>
                    {u.estado === 'activo' ? 'Desactivar' : 'Activar'}
                  </Boton>
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
    </div>
  )
}

function FormularioUsuario({ rolActor, alGuardar }: { rolActor: Rol; alGuardar: () => Promise<void> }) {
  const roles = rolesAsignables(rolActor)
  const esSuper = rolActor === 'superadmin'
  const tenants = useRecurso<Tenant[]>(esSuper ? '/tenants' : null)
  const prestadores = useRecurso<Prestador[]>(esSuper ? '/prestadores' : null)
  const [error, setError] = useState<string | null>(null)
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
      <Selector etiqueta="Rol" opciones={roles.map((r) => ({ valor: r, texto: NOMBRE_ROL[r] }))} {...register('rol')} />
      {esSuper && ROLES_TENANT.includes(rol) && (
        <Selector etiqueta="Cliente" opciones={[{ valor: '', texto: 'Selecciona…' }, ...(tenants.datos ?? []).map((t) => ({ valor: t.id, texto: t.razon_social }))]} {...register('tenant_id')} />
      )}
      {esSuper && ROLES_PRESTADOR.includes(rol) && (
        <Selector etiqueta="Prestador" opciones={[{ valor: '', texto: 'Selecciona…' }, ...(prestadores.datos ?? []).map((p) => ({ valor: p.id, texto: p.razon_social }))]} {...register('prestador_id')} />
      )}
      <Campo etiqueta="Contraseña inicial" type="password" autoComplete="new-password" error={formState.errors.contrasena?.message} {...register('contrasena')} />
      <Boton type="submit" className="w-full" disabled={formState.isSubmitting}>Crear usuario</Boton>
    </form>
  )
}
