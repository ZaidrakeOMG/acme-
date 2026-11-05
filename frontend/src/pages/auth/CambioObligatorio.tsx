import { zodResolver } from '@hookform/resolvers/zod'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { z } from 'zod'
import { Boton, Campo } from '../../components/ui'
import { useAuth } from '../../contexts/AuthContext'
import { api, mensajeDeError } from '../../services/api'
import { MarcoAuth, REGLAS_CONTRASENA } from './Marco'

/**
 * §6.9.5 · P11a: la contraseña de los roles administrativos vence a los 90 días. Mientras está vencida, el servidor
 * responde 403 CONTRASENA_VENCIDA a todo menos a su propio perfil, el cambio y el cierre de sesión, así que esta
 * pantalla reemplaza a la aplicación completa hasta que se cambie.
 */
const esquema = z
  .object({
    actual: z.string().min(1, 'Escribe tu contraseña actual'),
    nueva: z.string().min(10, 'La contraseña nueva necesita al menos 10 caracteres'),
    confirmacion: z.string().min(1, 'Repite la contraseña nueva'),
  })
  .refine((d) => d.nueva === d.confirmacion, { path: ['confirmacion'], message: 'Las dos contraseñas no coinciden' })
  .refine((d) => d.nueva !== d.actual, { path: ['nueva'], message: 'La contraseña nueva debe ser distinta de la actual' })
type Datos = z.infer<typeof esquema>

export function CambioObligatorio() {
  const { recargarPerfil, cerrarSesion } = useAuth()
  const [error, setError] = useState<string | null>(null)
  const { register, handleSubmit, formState } = useForm<Datos>({ resolver: zodResolver(esquema) })

  const enviar = handleSubmit(async ({ actual, nueva }) => {
    setError(null)
    try {
      await api('/auth/cambiar-contrasena', { metodo: 'POST', cuerpo: { actual, nueva } })
      await recargarPerfil() // el perfil vuelve sin la marca de vencida y la aplicación se abre
    } catch (e) {
      setError(mensajeDeError(e))
    }
  })

  return (
    <MarcoAuth error={error}>
      <form onSubmit={enviar} className="space-y-4" noValidate>
        <h1 className="text-xl font-semibold text-slate-900">Tu contraseña venció</h1>
        <p className="text-sm text-slate-600">
          Por política de seguridad, las cuentas administrativas cambian su contraseña cada 90 días. Elige una nueva
          para seguir usando ACMA.
        </p>
        <Campo etiqueta="Contraseña actual" type="password" autoComplete="current-password" error={formState.errors.actual?.message} {...register('actual')} />
        <Campo etiqueta="Contraseña nueva" type="password" autoComplete="new-password" error={formState.errors.nueva?.message} {...register('nueva')} />
        <Campo etiqueta="Repite la contraseña nueva" type="password" autoComplete="new-password" error={formState.errors.confirmacion?.message} {...register('confirmacion')} />
        <p className="text-xs text-slate-500">{REGLAS_CONTRASENA}</p>
        <Boton type="submit" className="w-full" disabled={formState.isSubmitting}>
          {formState.isSubmitting ? 'Guardando…' : 'Cambiar y continuar'}
        </Boton>
        <button type="button" className="w-full text-sm text-slate-500 hover:underline" onClick={() => void cerrarSesion()}>
          Cerrar sesión
        </button>
      </form>
    </MarcoAuth>
  )
}
